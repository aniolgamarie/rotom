import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { fork, execFileSync } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, readFileSync, writeFileSync, existsSync, watch } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { Store, type Owner } from "../src/store/database.ts";
import { originalProcessStopped, type ProcessIdentity } from "../src/adapters/process-identity.ts";
import { workspaceResource } from "../src/workspace/worktree.ts";
import { isolatedDirectory } from "./helpers.ts";
import { exe010NegativeControl } from "./fixtures/exe010-workspace-freeze.ts";

function written(path: string, expected: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const check = () => { if (existsSync(path) && readFileSync(path, "utf8") === expected) { cleanup(); resolve(); } };
    const watcher = watch(dirname(path), check), timer = setTimeout(() => { cleanup(); reject(new Error("writer barrier timed out")); }, 5000);
    const cleanup = () => { clearTimeout(timer); watcher.close(); }; check();
  });
}

// [P EXE-010] owner replacement cannot release an unconfirmed writer or undo its observed effects
test("[P EXE-010] unconfirmed writer continues after owner revocation; replacement denied until termination confirmed", { timeout: 15000 }, async t => {
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
  // 撤权但不 terminate intent
  const revoked = once(ownerProcess, "message"); ownerProcess.send("expire"); assert.equal((await revoked)[0].type, "revoked");
  assert.equal(originalProcessStopped(ready.controller), false);
  // intent 仍为 unknown（markSent 但未 acknowledge/terminate）
  store.settle("old-write", "unknown");
  const replacement = store.claimOwner("writer-scope", "replacement");
  for (const id of ["EXE-010"]) evidence(id, () => {
    assert.ok(replacement.epoch > ready.owner.epoch);
    assert.equal(originalProcessStopped(writer!), false);
    assert.equal(store.intent("old-write")!.status, "unknown");
  });
  // 旧 writer 仍活着且继续写
  writeFileSync(join(cwd, "advance"), "2"); await written(join(cwd, "completed"), "2");
  for (const id of ["EXE-010"]) evidence(id, () => {
    assert.equal(readFileSync(join(cwd, "writes.log"), "utf8"), "1\n2\n");
    assert.equal(originalProcessStopped(writer!), false);
  });
  // 接替者被拒绝（RESOURCE_DENIED）
  for (const id of ["EXE-010"]) evidence(id, () => {
    assert.throws(() => store.prepare(replacement, "new-write", "write", { cwd }, [{ id: workspaceResource(cwd), capacity: 1, units: 1 }]), { code: "RESOURCE_DENIED" }, "EXE010_LIVE_WRITER_MUST_BLOCK_REPLACEMENT");
    assert.equal(store.intent("new-write"), null);
    assert.equal(store.claims().length, 1);
    assert.equal(store.claims()[0].intent_id, "old-write");
  });
  acceptance("AC08","unconfirmed-writer",{level:"P",observer:"live-writer-process-and-file-bytes-after-owner-revocation",predicate:"revocation cannot release a writer that still changes files",artifact:observerArtifact("live-writer",{ready,replacement,alive:originalProcessStopped(writer!)===false,effects:readFileSync(join(cwd,"writes.log"),"utf8"),claims:store.claims()})},()=>{assert.equal(originalProcessStopped(writer!),false);assert.equal(store.claims().length,1);assert.equal(store.intent("new-write"),null);});
  // 确认旧进程终止后才允许接替
  process.kill(writer.pid, "SIGKILL");
  const until = Date.now() + 1000; while (Date.now() < until && originalProcessStopped(writer) !== true) await delay(5);
  assert.equal(originalProcessStopped(writer), true);
  store.settle("old-write", "terminated");
  store.prepare(replacement, "new-write", "write", { cwd }, [{ id: workspaceResource(cwd), capacity: 1, units: 1 }]);
  store.markSent(replacement, "new-write");
  execFileSync(process.execPath, ["-e", "require('node:fs').appendFileSync('writes.log', 'replacement\\n')"], { cwd });
  store.settle("new-write", "terminated");
  for (const id of ["EXE-010"]) evidence(id, () => {
    assert.equal(store.claims().length, 0);
    assert.equal(originalProcessStopped(writer!), true);
    assert.equal(store.intent("old-write")!.status, "settled");
    assert.equal(store.intent("new-write")!.status, "settled");
    assert.equal(readFileSync(join(cwd, "writes.log"), "utf8"), "1\n2\nreplacement\n");
  });
  acceptance("AC08","confirmed-release",{level:"P",observer:"actual-old-writer-termination-and-replacement-effect",predicate:"confirmed stop is required before replacement writes",artifact:observerArtifact("writer-released",{old:store.intent("old-write"),replacement:store.intent("new-write"),effects:readFileSync(join(cwd,"writes.log"),"utf8"),claims:store.claims()})},()=>{assert.equal(originalProcessStopped(writer!),true);assert.equal(store.claims().length,0);assert.equal(readFileSync(join(cwd,"writes.log"),"utf8"),"1\n2\nreplacement\n");});
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
    const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "exe-010-observers"); mkdirSync(path, { recursive: true });
    writeFileSync(join(path, "unconfirmed-writer.json"), JSON.stringify({ ready, replacement, writerStopped: originalProcessStopped(writer),
      oldIntent: store.intent("old-write"), newIntent: store.intent("new-write"), claims: store.claims(), effects: readFileSync(join(cwd, "writes.log"), "utf8") }, null, 2));
  }
});

// 负向控制：移除 resource 检查后，旧进程仍活着时接替者应被允许（违反 EXE-010 规则）
test("EXE010 negative control: removing resource check allows replacement while writer alive", (t) => {
  const result = exe010NegativeControl(t);
  assert.equal(result.code, 1, `expected exit 1 due to RESOURCE_DENIED assertion failure, got ${result.code}\n${result.output}`);
  assert.match(result.output, /Missing expected exception.*EXE010_LIVE_WRITER_MUST_BLOCK_REPLACEMENT/);
  assert.match(result.output, /# tests 1\b/);
  assert.match(result.output, /# fail 1\b/);
  assert.doesNotMatch(result.output, /ERR_MODULE_NOT_FOUND|timed out|cancelledByParent/);
});
