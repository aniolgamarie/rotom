import { test, assert, evidence } from "./recorded-test.ts";
import { fork, execFileSync } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, readFileSync, writeFileSync, existsSync, watch, symlinkSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { Store, type Owner } from "../src/store/database.ts";
import { originalProcessStopped, type ProcessIdentity } from "../src/adapters/process-identity.ts";
import { workspaceResource } from "../src/workspace/worktree.ts";
import { isolatedDirectory } from "./helpers.ts";
function written(path: string, expected: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const check = () => { if (existsSync(path) && readFileSync(path, "utf8") === expected) { cleanup(); resolve(); } };
    const watcher = watch(dirname(path), check), timer = setTimeout(() => { cleanup(); reject(new Error("writer barrier timed out")); }, 5000);
    const cleanup = () => { clearTimeout(timer); watcher.close(); }; check();
  });
}
for (const cause of ["owner-exit", "owner-revoked"] as const) test(`[P ${cause === "owner-exit" ? "T41 SCH-014 TK14" : "T42"}] live writer prevents replacement after ${cause}; proven termination releases only its resource`, { timeout: 15000 }, async t => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"), dbRoot = join(root, "state"); mkdirSync(cwd);
  const ownerProcess = fork(fileURLToPath(new URL("./fixtures/writer-owner.ts", import.meta.url)), [dbRoot, cwd], { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"] });
  let writer: ProcessIdentity | undefined;
  t.after(async () => {
    if (writer && originalProcessStopped(writer) === false) try { process.kill(writer.pid, "SIGKILL"); } catch {}
    if (ownerProcess.exitCode === null && ownerProcess.signalCode === null) { const exited = once(ownerProcess, "exit"); ownerProcess.kill("SIGKILL"); await exited; }
  });
  const ready = (await once(ownerProcess, "message"))[0] as { type: string; owner: Owner; writer: ProcessIdentity; controller: ProcessIdentity };
  assert.equal(ready.type, "ready"); writer = ready.writer; assert.ok(writer); assert.equal(originalProcessStopped(writer), false);
  writeFileSync(join(cwd, "advance"), "1"); await written(join(cwd, "completed"), "1");
  const store = new Store(dbRoot); t.after(() => store.close());
  if (cause === "owner-exit") {
    const exited = once(ownerProcess, "exit"); ownerProcess.kill("SIGKILL"); await exited;
    assert.equal(originalProcessStopped(ready.controller), true); store.revokeOwner(ready.owner);
  } else {
    const revoked = once(ownerProcess, "message"); ownerProcess.send("expire"); assert.equal((await revoked)[0].type, "revoked");
    assert.equal(originalProcessStopped(ready.controller), false);
  }
  store.settle("old-write", "unknown"); const replacement = store.claimOwner("writer-scope", "replacement");
  const ids = cause === "owner-exit" ? ["T41", "SCH-014", "TK14"] : ["T42"];
  for (const id of ids) evidence(id, () => { assert.ok(replacement.epoch > ready.owner.epoch); assert.equal(originalProcessStopped(writer!), false); assert.equal(store.intent("old-write")!.status, "unknown"); });
  const alias = join(root, "alias"); symlinkSync(cwd, alias);
  assert.equal(workspaceResource(alias), workspaceResource(cwd));
  for (const id of ids) evidence(id, () => {
    assert.throws(() => store.prepare(replacement, "new-write", "write", { cwd: alias }, [{ id: workspaceResource(alias), capacity: 1, units: 1 }]), { code: "RESOURCE_DENIED" });
    assert.equal(store.intent("new-write"), null); assert.equal(store.claims().length, 1); assert.equal(store.claims()[0].intent_id, "old-write");
  });
  writeFileSync(join(cwd, "advance"), "2"); await written(join(cwd, "completed"), "2");
  for (const id of ids) evidence(id, () => { assert.equal(readFileSync(join(cwd, "writes.log"), "utf8"), "1\n2\n"); assert.equal(originalProcessStopped(writer!), false); });
  process.kill(writer.pid, "SIGKILL");
  const until = Date.now() + 1000; while (Date.now() < until && originalProcessStopped(writer) !== true) await delay(5);
  assert.equal(originalProcessStopped(writer), true); store.settle("old-write", "terminated");
  store.prepare(replacement, "new-write", "write", { cwd }, [{ id: workspaceResource(cwd), capacity: 1, units: 1 }]);
  store.markSent(replacement, "new-write");
  execFileSync(process.execPath, ["-e", "require('fs').appendFileSync('writes.log','replacement\\n')"], { cwd });
  store.settle("new-write", "terminated");
  for (const id of ids) evidence(id, () => {
    assert.equal(readFileSync(join(cwd, "writes.log"), "utf8"), "1\n2\nreplacement\n"); assert.equal(store.claims().length, 0);
    assert.equal(originalProcessStopped(writer!), true); assert.equal(store.intent("old-write")!.status, "settled"); assert.equal(store.intent("new-write")!.status, "settled");
  });
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "resource-observers"); mkdirSync(path, { recursive: true });
    writeFileSync(join(path, `${cause}.json`), JSON.stringify({ ready, replacement, writerStopped: originalProcessStopped(writer),
      oldIntent: store.intent("old-write"), newIntent: store.intent("new-write"), claims: store.claims(), effects: readFileSync(join(cwd, "writes.log"), "utf8") }, null, 2)); }
});
