import { test, assert } from "./recorded-test.ts";
import { watch, existsSync, readFileSync, writeFileSync, readdirSync, readlinkSync } from "node:fs";
import { join } from "node:path";
import { runVerification } from "../src/verification/runner.ts";
import { processIdentity, originalProcessStopped } from "../src/adapters/process-identity.ts";
import type { VerificationBinding } from "../src/config.ts";
import { isolatedDirectory } from "./helpers.ts";
const binding = (program: string): VerificationBinding => ({ executable: process.execPath, args: ["-e", program], environment: {}, timeoutMs: 10000,
  kind: "build", parser: "exit-code", minimumTests: 1 });
for (const detached of [false, true]) test(`[P T41] a ${detached ? "detached" : "ordinary"} grandchild cannot outlive verifier completion`, { timeout: 15000 }, async t => {
  const cwd = isolatedDirectory(t), ready = join(cwd, "grandchild-ready"), release = join(cwd, "release-parent");
  const childProgram = "const fs=require('fs');process.on('SIGTERM',()=>{});fs.writeFileSync('grandchild-ready.tmp',JSON.stringify({pid:process.pid,ns:fs.readlinkSync('/proc/self/ns/pid')}));fs.renameSync('grandchild-ready.tmp','grandchild-ready');setInterval(()=>fs.appendFileSync('writes','x'),10)";
  const program = `const fs=require('fs');const child=require('child_process').spawn(process.execPath,['-e',${JSON.stringify(childProgram)}],{detached:${detached},stdio:'ignore'});child.unref();const timer=setInterval(()=>{if(fs.existsSync('release-parent')){clearInterval(timer);process.exit(0)}},5)`;
  let notified!: () => void; const reached = new Promise<void>(resolve => { notified = resolve; });
  const watcher = watch(cwd, () => { if (existsSync(ready)) notified(); }); t.after(() => watcher.close());
  const pending = runVerification("build", { build: binding(program) }, { cwd, jobId: "job", snapshot: "tree" });
  await reached;
  const actual = JSON.parse(readFileSync(ready, "utf8"));
  const pid = readdirSync("/proc").filter(id => /^\d+$/.test(id)).find(id => {
    try { return readlinkSync(`/proc/${id}/ns/pid`) === actual.ns && Number(/^NSpid:\s+(.+)$/m.exec(readFileSync(`/proc/${id}/status`, "utf8"))?.[1].trim().split(/\s+/).at(-1)) === actual.pid; }
    catch { return false; }
  });
  assert.ok(pid); const identity = processIdentity(Number(pid))!; assert.ok(identity); assert.equal(originalProcessStopped(identity), false);
  if (detached) {
    const stat = readFileSync(`/proc/${pid}/stat`, "utf8").split(") ")[1].split(" ");
    assert.equal(Number(stat[2]), Number(pid), "grandchild really has its own process group");
  }
  writeFileSync(release, "release"); const result = await pending;
  assert.equal(result.exitCode, 0); assert.equal(result.status, "failed", JSON.stringify(result));
  assert.equal(result.reason, "unfinished_descendants_terminated"); assert.equal(result.terminationCoverage, "pid-namespace");
  assert.equal(result.terminationConfirmed, true); assert.equal(originalProcessStopped(identity), true);
  assert.notEqual(result.supervisor.namespace, readlinkSync("/proc/self/ns/pid"));
});
for (const control of ["abort", "throw", "async"] as const) test(`[P EXE-011] verifier ${control} at final admission sends no command through the namespace gate`, async t => {
  const cwd = isolatedDirectory(t), controller = new AbortController(); let entered = false;
  const onDispatch = control === "async" ? async () => { entered = true; } : () => {
    entered = true; if (control === "abort") controller.abort(); else throw new Error("revoked-before-command");
  };
  const result = await runVerification("build", { build: binding("require('fs').writeFileSync('should-not-exist','bad')") }, { cwd, jobId: "job", snapshot: "tree" }, { signal: controller.signal, onDispatch, killGraceMs: 50 });
  assert.equal(existsSync(join(cwd, "should-not-exist")), false); assert.equal(result.status, "failed", JSON.stringify(result));
  assert.equal(result.terminationConfirmed, true); assert.equal(entered, control !== "async");
  assert.equal(result.reason, control === "abort" ? "cancelled" : control === "throw" ? "revoked-before-command" : "ASYNC_VERIFICATION_GUARD_NOT_SUPPORTED");
});

test("[P EXE-012] an unavailable or non-isolating supervisor cannot execute the trusted check", async t => {
  const cwd = isolatedDirectory(t), check = binding("require('fs').writeFileSync('should-not-exist','bad')");
  await assert.rejects(runVerification("build", { build: { ...check, supervisorExecutable: join(cwd, "missing") } }, { cwd, jobId: "job", snapshot: "tree" }), { code: "VERIFIER_SUPERVISOR_UNAVAILABLE" });
  const result = await runVerification("build", { build: { ...check, supervisorExecutable: "/bin/true" } }, { cwd, jobId: "job", snapshot: "tree" });
  assert.notEqual(result.status, "passed"); assert.equal(existsSync(join(cwd, "should-not-exist")), false);
  const good = await runVerification("build", { build: binding("process.exit(0)") }, { cwd, jobId: "job", snapshot: "tree" });
  assert.equal(good.status, "passed");
});
