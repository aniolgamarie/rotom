import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { fork, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import type { TestContext } from "node:test";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";

async function worker(t: TestContext, root: string) {
  const child = fork(fileURLToPath(new URL("./fixtures/event-ledger-worker.ts", import.meta.url)), [root], {
    execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"],
  });
  t.after(async () => { if (child.exitCode === null && child.signalCode === null) { const stopped = once(child, "exit"); child.kill("SIGKILL"); await stopped; } });
  assert.equal((await once(child, "message"))[0].ready, true); return child;
}
let serial = 0;
function send(child: ChildProcess, input: Record<string, unknown>): Promise<any> {
  return new Promise((resolve, reject) => {
    const id = ++serial;
    const done = (value: any) => { if (value.id === id) { cleanup(); resolve(value); } };
    const died = () => { cleanup(); reject(new Error("event ledger worker exited before reply")); };
    const timer = setTimeout(() => { cleanup(); reject(new Error("event ledger worker reply timed out")); }, 10000);
    const cleanup = () => { clearTimeout(timer); child.off("message", done); child.off("exit", died); };
    child.on("message", done); child.once("exit", died); child.send({ ...input, id });
  });
}

test("[P EVD-001 T14 T15] concurrent completion delivery and producer restart preserve one charge and enforce sequence repair", {timeout:20000}, async t => {
  const root = isolatedDirectory(t), store = new Store(root); t.after(() => store.close()); const owner = store.claimOwner("scope", "owner");
  store.prepare(owner, "original", "continue", {}); store.reserveRequest(owner, "original", "request", [{ id: "budget", ceiling: 1 }]);
  store.markSent(owner, "original"); store.acknowledge("original", "native"); store.settle("original", "terminated"); store.settleRequest("request", "sent");
  const [a, b] = await Promise.all([worker(t, root), worker(t, root)]);
  const event = { id: "completion", producer: "native", seq: 1, scopeId: "scope", kind: "completed", payload: { nativeId: "native" } };
  const results = await Promise.all([send(a, { kind: "append", event }), send(b, { kind: "append", event })]);
  for (const id of ["EVD-001", "T15"]) evidence(id, () => {
    assert.deepEqual(results.map(result => result.result).sort(), ["duplicate", "inserted"]);
    assert.deepEqual(store.events("scope"), [event]); assert.equal(store.bucket("budget")!.used, 1); assert.equal(store.bucket("budget")!.reserved, 0);
  });
  const repeated = await send(b, { kind: "prepare", owner, intentId: "original" });
  for (const id of ["EVD-001", "T15"]) evidence(id, () => { assert.equal(repeated.error, "DUPLICATE_INTENT"); assert.equal(store.db.prepare("SELECT count(*) n FROM intents").get()!.n, 1); });
  await send(a, { kind: "append", event: { ...event, id: "later", seq: 3 } });
  const denied = await send(b, { kind: "prepare", owner, intentId: "next" });
  for (const id of ["EVD-001", "T14"]) evidence(id, () => {
    assert.equal(denied.error, "EVIDENCE_GAP"); assert.equal(store.intent("next"), null);
    assert.deepEqual(store.sequenceGaps("scope"), [{ producer: "native", expected: 2, actual: 3 }]);
  });
  for(const variant of ["sequence-gap","duplicate-event"])acceptance("AC26",variant,{level:"P",observer:"concurrent-producer-processes-and-SQLite-sequence",predicate:variant,artifact:observerArtifact(variant,{results,denied,gaps:store.sequenceGaps("scope"),events:store.events("scope")})},()=>{assert.deepEqual(results.map(r=>r.result).sort(),["duplicate","inserted"]);assert.equal(denied.error,"EVIDENCE_GAP");assert.equal(store.intent("next"),null);assert.equal(store.bucket("budget")!.used,1);});
  const stopped = once(a, "exit"); a.kill("SIGKILL"); await stopped;
  const restarted = await worker(t, root);
  assert.equal((await send(restarted, { kind: "append", event })).result, "duplicate");
  assert.equal((await send(restarted, { kind: "append", event: { ...event, id: "repaired", seq: 2 } })).result, "inserted");
  assert.equal((await send(b, { kind: "prepare", owner, intentId: "next" })).result.status, "prepared");
  for (const id of ["EVD-001", "T14", "T15"]) evidence(id, () => {
    assert.deepEqual(store.sequenceGaps("scope"), []); assert.equal(store.intent("original")!.nativeId, "native");
    assert.equal(store.intent("original")!.status, "settled"); assert.equal(store.bucket("budget")!.used, 1);
    assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 1);
  });
});

test("[P EVD-002] competing conflicting producers retain one payload and block both affected scopes", {timeout:20000}, async t => {
  const root = isolatedDirectory(t), store = new Store(root); t.after(() => store.close());
  const owners = [store.claimOwner("scope-a", "owner-a"), store.claimOwner("scope-b", "owner-b")];
  const [a, b] = await Promise.all([worker(t, root), worker(t, root)]);
  const events = owners.map((owner, index) => ({ id: `event-${index}`, producer: "shared-producer", seq: 1, scopeId: owner.scopeId, kind: "result", payload: { outcome: index ? "passed" : "failed" } }));
  const results = await Promise.all([send(a, { kind: "append", event: events[0] }), send(b, { kind: "append", event: events[1] })]);
  assert.deepEqual(results.map(result => result.result).sort(), ["conflict", "inserted"]);
  const winner = results.findIndex(result => result.result === "inserted"); assert.deepEqual(store.events(events[winner].scopeId), [events[winner]]);
  assert.deepEqual(store.events(events[1 - winner].scopeId), []);
  for (const [index, owner] of owners.entries()) {
    assert.ok(store.issues(owner.scopeId).some(issue => issue.kind === "event_conflict"));
    assert.equal((await send(index ? b : a, { kind: "prepare", owner, intentId: `blocked-${index}` })).error, "EVIDENCE_CONFLICT");
  }
  acceptance("AC26","conflict",{level:"P",observer:"competing-conflicting-process-events",predicate:"conflicts block both scopes without replacing payload",artifact:observerArtifact("event-conflict",{results,events,issues:owners.map(o=>store.issues(o.scopeId))})},()=>{assert.deepEqual(results.map(r=>r.result).sort(),["conflict","inserted"]);for(const owner of owners)assert.ok(store.issues(owner.scopeId).some(i=>i.kind==="event_conflict"));assert.equal(store.events(events[winner].scopeId).length,1);});
  const independent = store.claimOwner("independent", "owner-independent");
  assert.equal((await send(a, { kind: "prepare", owner: independent, intentId: "independent" })).result.status, "prepared");
});
