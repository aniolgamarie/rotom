import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { fork, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, symlinkSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Store } from "../src/store/database.ts";
import { Scheduler, type QueuedJob } from "../src/orchestration/scheduler.ts";
import { isolatedDirectory } from "./helpers.ts";

function receive(child: ChildProcess, type: string): Promise<any> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error(`worker ${child.pid} timed out: ${type}`)); }, 10000);
    const exit = () => { cleanup(); reject(new Error(`worker ${child.pid} exited before ${type}`)); };
    const message = (value: any) => { if (value.type === type) { cleanup(); resolve(value); } };
    const cleanup = () => { clearTimeout(timer); child.off("message", message); child.off("exit", exit); };
    child.on("message", message); child.once("exit", exit);
  });
}
for (const mode of ["reverse", "alias", "declared", "slot"] as const) {
  const ids = mode === "reverse" ? ["SCH-007", "SCH-008", "TK04"] : ["alias", "declared"].includes(mode) ? ["SCH-009", "TK05"] : ["SCH-011", "TK07"];
  test(`[P ${ids.join(" ")}] ${mode} contention uses real parents, retains unknown, and resumes after confirmed death`, { timeout: 25000 }, async t => {
    const root = isolatedDirectory(t), state = join(root, "state"), source = join(root, "source"), alias = join(root, "alias");
    mkdirSync(source); symlinkSync(source, alias); new Store(state).close();
    const children = ["a", "b"].map((id, index) => fork(fileURLToPath(new URL("./fixtures/resource-worker.ts", import.meta.url)),
      [state, id, mode, ["alias", "declared"].includes(mode) && index === 1 ? alias : source], { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "ignore", "ipc"] }));
    t.after(async () => { await Promise.all(children.map(async child => { if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGKILL"); await exit; } })); });
    const ready = await Promise.all(children.map(child => receive(child, "ready")));
    const pending = children.map(child => receive(child, "result")); children.forEach(child => child.send("go"));
    const results = await Promise.all(pending), observer = new Store(state); t.after(() => observer.close());
    const winnerIndex = results.findIndex(result => result.acquired), loserIndex = 1 - winnerIndex;
    for (const id of ids) evidence(id, () => {
      assert.equal(new Set(ready.map(item => item.pid)).size, 2); assert.equal(results.filter(result => result.acquired).length, 1);
      assert.equal(results[loserIndex].code, "RESOURCE_DENIED");
      assert.equal(observer.claims().length, mode === "reverse" ? 2 : 1);
      assert.ok(observer.claims().every(claim => claim.intent_id === results[winnerIndex].intent));
      assert.equal(observer.get<QueuedJob>("jobs", ["a", "b"][loserIndex])!.dispatched, 0);
      assert.equal(readFileSync(join(source, "effects.txt"), "utf8"), `${["a", "b"][winnerIndex]}\n`);
    });
    const intent = results[winnerIndex].intent, before = observer.claims();
    observer.settle(intent, "unknown");
    const stillDenied = receive(children[loserIndex], "result"); children[loserIndex].send("go");
    const denied = await stillDenied;
    for (const id of ids) evidence(id, () => {
      assert.equal(denied.code, "RESOURCE_DENIED"); assert.deepEqual(observer.claims(), before);
      assert.equal(observer.intent(intent)!.status, "unknown"); assert.equal(readFileSync(join(source, "effects.txt"), "utf8").trim().split("\n").length, 1);
    });
    // The worker has no descendants. Its actual exit, not a cancellation reply, is the termination witness.
    const dead = once(children[winnerIndex], "exit"); children[winnerIndex].kill("SIGKILL"); const exit = await dead;
    const winnerId = ["a", "b"][winnerIndex];
    observer.revokeOwner(observer.owner(`scope-${winnerId}`)!);
    const recovered = new Scheduler(observer, observer.claimOwner(`scope-${winnerId}`, `reconciler-${winnerId}`));
    recovered.reconcileStopped(winnerId, "work", false);
    const resumed = receive(children[loserIndex], "result"); children[loserIndex].send("go"); const after = await resumed;
    for (const id of ids) evidence(id, () => {
      assert.equal(exit[1], "SIGKILL"); assert.equal(observer.intent(intent)!.status, "settled"); assert.equal(after.acquired, true);
      assert.equal(observer.claims().length, before.length); assert.ok(observer.claims().every(claim => claim.intent_id === after.intent));
      assert.deepEqual(readFileSync(join(source, "effects.txt"), "utf8").trim().split("\n"), [winnerId, ["a", "b"][loserIndex]]);
      assert.equal(observer.get<QueuedJob>("jobs", ["a", "b"][loserIndex])!.dispatched, 1);
    });
    for(const variant of [mode === "reverse"?"reverse-demands":mode === "slot"?"last-slot":"alias-writer","unknown-owner"])
      acceptance("AC28",variant,{level:"P",observer:"two-real-resource-processes-and-file-effects",predicate:variant,artifact:observerArtifact(`resource-${mode}-${variant}`,{ready,results,denied,exit,after,effects:readFileSync(join(source,"effects.txt"),"utf8")})},()=>{
        assert.equal(results.filter(r=>r.acquired).length,1);assert.equal(denied.code,"RESOURCE_DENIED");assert.equal(exit[1],"SIGKILL");assert.equal(after.acquired,true);assert.equal(observer.intent(intent)!.status,"settled");assert.equal(readFileSync(join(source,"effects.txt"),"utf8").trim().split("\n").length,2);
      });
    const parentRecords = process.env.TASK_KEEPER_TEST_RECORD_DIR;
    if (parentRecords) { const target = join(dirname(parentRecords), "resource-observers"); mkdirSync(target, { recursive: true });
      writeFileSync(join(target, `${mode}.json`), JSON.stringify({ ready, results, before, denied, exit, after, claims: observer.claims(), effects: readFileSync(join(source, "effects.txt"), "utf8") }, null, 2)); }
  });
}
