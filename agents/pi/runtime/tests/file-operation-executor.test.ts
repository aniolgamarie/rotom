import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { executeFileOperation } from "../file-operation-executor.ts";

function fixture(options = {}) {
  const instanceRoot = mkdtempSync(join(tmpdir(), "file-executor-")), stateRoot = mkdtempSync(join(tmpdir(), "file-state-")), calls = [], identity = { pid: 123, start: "fixture" };
  const ticket = { kind: "file", write: true, state: "consumed", lease_id: "lease", operation_id: "op", tool_name: "write" };
  let started = false, stopped = false, time = 0;
  const save = (name, value, root = stateRoot) => { const path = join(root, "activity", name); mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 }); writeFileSync(path, JSON.stringify(value), { mode: 0o600 }); };
  save("exits/lease.json", { lease_id: "lease", exit_code: 0, process_identity: identity, ...options.exit });
  save("ordinary-results/op.json", { schema_version: 1, lease_id: "lease", operation_id: "op", result: { changed: true }, ...options.result });
  const supervisor = { options: { endpoint: join(stateRoot, "activity/control/control.json") }, async call(method, args) {
    calls.push(method); assert.equal(args.lease_id ?? "lease", "lease");
    if (method === "ordinary_stage_write") return {};
    if (method === "start") { assert.equal(args.program, "file-operation"); started = true; if (options.lostStart) throw Error("lost ack"); return { state: "running" }; }
    if (method === "cancel") { stopped = !options.unknownCancel; return {}; }
    if (method === "inspect" || method === "reconcile") {
      const ended = stopped || started && !options.running;
      return { lease_id: "lease", protected: !ended, state: ended ? "reclaimed" : started ? "running" : "allocating", process_identity: started ? identity : null,
        termination_evidence: ended ? { verified: true } : null, ...options.proof };
    }
    throw Error("unexpected call " + method);
  } };
  return { ticket, calls, supervisor, instanceRoot, stateRoot, save, execute: (extra = {}) => executeFileOperation({ supervisor, instanceRoot, ticket, content: "new", expectedDigest: "a".repeat(64), clock: () => time, pause: async () => { time += 1000; }, ...extra }) };
}

test("file executor stages and starts once and returns only bound terminated result", async () => {
  const f = fixture(); assert.deepEqual(await f.execute(), { changed: true });
  assert.equal(f.calls.filter(value => value === "start").length, 1);
  assert.equal(f.calls[0], "ordinary_stage_write");
});
test("lost start acknowledgement reconciles without resending or releasing", async () => {
  const f = fixture({ lostStart: true }); assert.deepEqual(await f.execute(), { changed: true });
  assert.equal(f.calls.filter(value => value === "start").length, 1); assert.ok(f.calls.includes("inspect"));
  assert.ok(!f.calls.some(value => ["ordinary_finish", "abort_allocation"].includes(value)));
});
test("rename never stages contents", async () => {
  const f = fixture(); f.ticket.tool_name = "rename"; await f.execute(); assert.ok(!f.calls.includes("ordinary_stage_write"));
});
test("preaborted operation never stages or starts and cancels with confirmed termination", async () => {
  const f = fixture(), controller = new AbortController(); controller.abort();
  await assert.rejects(f.execute({ signal: controller.signal }), /ORDINARY_OPERATION_CANCELED/);
  assert.ok(f.calls.includes("cancel")); assert.ok(!f.calls.includes("start")); assert.ok(!f.calls.includes("ordinary_stage_write"));
  assert.notEqual(f.ticket.state, "unknown");
});
test("cancel without termination proof is bounded and preserves unknown protection", async () => {
  const f = fixture({ unknownCancel: true }), controller = new AbortController(); controller.abort();
  await assert.rejects(f.execute({ signal: controller.signal }), /TERMINATION_UNKNOWN/);
  assert.equal(f.ticket.state, "unknown"); assert.equal(f.calls.filter(value => value === "cancel").length, 1);
  assert.ok(!f.calls.some(value => ["ordinary_finish", "abort_allocation"].includes(value)));
});
test("execution deadline cancels once and requires actual settlement", async () => {
  const f = fixture({ running: true }); await assert.rejects(f.execute(), /ORDINARY_OPERATION_TIMEOUT/);
  assert.equal(f.calls.filter(value => value === "cancel").length, 1);
});
for (const fault of [
  { exit: { lease_id: "other" } }, { exit: { process_identity: { pid: 456 } } }, { exit: { process_identity: null } },
  { exit: { exit_code: 7 } }, { result: { operation_id: "other" } }, { result: { lease_id: "other" } },
  { result: { schema_version: 2 } },
]) test("bound output evidence rejects " + JSON.stringify(fault), async () => {
  const f = fixture(fault); await assert.rejects(f.execute(), /ORDINARY_OPERATION_EVIDENCE/);
});
for (const invalid of [{ kind: "command" }, { write: false }, { lease_id: null }, { state: "prepared" }]) test("executor rejects unconsumed or nonfile ticket", async () => {
  const f = fixture(); Object.assign(f.ticket, invalid); await assert.rejects(f.execute(), /ORDINARY_FILE_TICKET/); assert.deepEqual(f.calls, []);
});

test("abort during execution cancels and observes termination without a second start", async () => {
  const f = fixture({ running: true }), controller = new AbortController();
  await assert.rejects(f.execute({ signal: controller.signal, pause: async () => controller.abort() }), /ORDINARY_OPERATION_CANCELED/);
  assert.equal(f.calls.filter(value => value === "start").length, 1);
  assert.equal(f.calls.filter(value => value === "cancel").length, 1);
  assert.equal(f.ticket.state, "terminated");
});
test("lost start acknowledgement with still-unknown process never restarts or abandons Writer", async () => {
  const f = fixture({ lostStart: true, running: true, unknownCancel: true });
  await assert.rejects(f.execute(), /TERMINATION_UNKNOWN/); assert.equal(f.ticket.state, "unknown");
  assert.equal(f.calls.filter(value => value === "start").length, 1);
  assert.equal(f.calls.filter(value => value === "cancel").length, 1);
  assert.ok(!f.calls.some(value => ["ordinary_finish", "abort_allocation"].includes(value)));
});
for (const proof of [{ lease_id: "other" }, { termination_evidence: { verified: false } }, { protected: true }])
  test("unbound or unverified termination evidence cannot release protection", async () => {
    const f = fixture({ proof }); await assert.rejects(f.execute(), /TERMINATION_UNKNOWN/); assert.equal(f.ticket.state, "unknown");
  });

for (const key of ["lease_id", "operation_id"]) for (const value of ["../escape", "nested/id", "bad\u0000id", "a".repeat(201)])
  test("path ID rejected before RPC: " + key + " " + JSON.stringify(value), async () => {
    const f = fixture(); f.ticket[key] = value;
    await assert.rejects(f.execute(), /ORDINARY_FILE_TICKET/); assert.deepEqual(f.calls, []);
  });
for (const instanceRoot of ["relative", "/tmp/../outside", "/tmp/bad\u0000root"])
  test("invalid instance root rejected before RPC", async () => {
    const f = fixture(); await assert.rejects(f.execute({ instanceRoot }), /ORDINARY_FILE_TICKET/); assert.deepEqual(f.calls, []);
  });
test("unselected tool name rejected before RPC", async () => {
  const f = fixture(); f.ticket.tool_name = "bash";
  await assert.rejects(f.execute(), /ORDINARY_FILE_TICKET/); assert.deepEqual(f.calls, []);
});
test("concurrent same ticket executes stage/start exactly once", async () => {
  const f = fixture(); let release, entered;
  const gate = new Promise(resolve => { release = resolve; }), ready = new Promise(resolve => { entered = resolve; });
  const original = f.supervisor.call;
  f.supervisor.call = async (method, args) => {
    if (method === "ordinary_stage_write") { entered(); await gate; }
    return original(method, args);
  };
  const first = f.execute(); await ready;
  assert.equal(f.ticket.state, "executing");
  try { await assert.rejects(f.execute(), /ORDINARY_FILE_TICKET/); }
  finally { release(); }
  assert.deepEqual(await first, { changed: true });
  assert.equal(f.calls.filter(method => method === "ordinary_stage_write").length, 1);
  assert.equal(f.calls.filter(method => method === "start").length, 1);
  assert.equal(f.ticket.state, "terminated");
});
test("wrong inspect identity after lost start stays unknown despite later valid proof", async () => {
  const f = fixture({ lostStart: true }), original = f.supervisor.call;
  f.supervisor.call = async (method, args) => method === "inspect" ? { lease_id: "other" } : original(method, args);
  await assert.rejects(f.execute(), /TERMINATION_UNKNOWN/);
  assert.equal(f.ticket.state, "unknown"); assert.ok(!f.calls.includes("reconcile")); assert.ok(!f.calls.includes("cancel"));
});

test("default deadline clock does not read adjustable wall clock", async () => {
  const f = fixture(), original = Date.now;
  Date.now = () => { throw Error("wall clock used"); };
  try { assert.deepEqual(await f.execute({ clock: undefined }), { changed: true }); }
  finally { Date.now = original; }
});

for (const endpoint of [undefined, "relative/activity/control/control.json", "/tmp/../state/activity/control/control.json", "/tmp/state/activity/other/control.json", "/tmp/state/activity/control/other.json", "/tmp/bad\u0000state/activity/control/control.json"])
  test("invalid supervisor endpoint is refused before RPC", async () => {
    const f = fixture(); f.supervisor.options.endpoint = endpoint;
    await assert.rejects(f.execute(), /ORDINARY_FILE_TICKET/); assert.deepEqual(f.calls, []);
  });
test("actual state root is authoritative over valid-looking instance output decoys", async () => {
  const f = fixture();
  f.save("exits/lease.json", { lease_id: "lease", exit_code: 0, process_identity: { pid: 123, start: "fixture" } }, join(f.instanceRoot, "state"));
  f.save("ordinary-results/op.json", { schema_version: 1, lease_id: "lease", operation_id: "op", result: { changed: "decoy" } }, join(f.instanceRoot, "state"));
  assert.deepEqual(await f.execute(), { changed: true });
});
test("invalid actual evidence cannot fall back to matching instance output", async () => {
  const f = fixture({ result: { lease_id: "other" } });
  f.save("exits/lease.json", { lease_id: "lease", exit_code: 0, process_identity: { pid: 123, start: "fixture" } }, join(f.instanceRoot, "state"));
  f.save("ordinary-results/op.json", { schema_version: 1, lease_id: "lease", operation_id: "op", result: { changed: true } }, join(f.instanceRoot, "state"));
  await assert.rejects(f.execute(), /ORDINARY_OPERATION_EVIDENCE/);
});
