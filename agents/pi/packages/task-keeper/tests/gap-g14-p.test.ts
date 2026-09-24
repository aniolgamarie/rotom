import { test, assert } from "./recorded-test.ts";
import { watch, existsSync, readFileSync, writeFileSync, readdirSync, readlinkSync } from "node:fs";
import { join } from "node:path";
import { setImmediate as flush } from "node:timers/promises";
import { runVerification } from "../src/verification/runner.ts";
import { processIdentity, originalProcessStopped } from "../src/adapters/process-identity.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[P EXE-013] a silent live build stays active until its barrier, and its deadline still terminates it", { timeout: 15000 }, async t => {
  const cwd = isolatedDirectory(t), marker = join(cwd, "ready"), release = join(cwd, "release");
  let notify!: () => void; const ready = new Promise<void>(resolve => { notify = resolve; });
  const watcher = watch(cwd, () => { if (existsSync(marker)) notify(); }); t.after(() => watcher.close());
  const program = "const fs=require('fs');fs.writeFileSync('ready.tmp',JSON.stringify({pid:process.pid,namespace:fs.readlinkSync('/proc/self/ns/pid')}));fs.renameSync('ready.tmp','ready');const timer=setInterval(()=>{if(fs.existsSync('release')){clearInterval(timer);process.exit(0)}},5)";
  const binding = { executable: process.execPath, args: ["-e", program], environment: {}, timeoutMs: 10000, kind: "build" as const, parser: "exit-code" as const, minimumTests: 1 };
  let settled = false;
  const pending = runVerification("build", { build: binding }, { cwd, jobId: "job", snapshot: "snapshot" }).then(result => { settled = true; return result; });
  await ready; await flush(); assert.equal(settled, false);
  const readyProcess = JSON.parse(readFileSync(marker, "utf8"));
  const pid = readdirSync("/proc").filter(id => /^\d+$/.test(id)).find(id => {
    try { return readlinkSync(`/proc/${id}/ns/pid`) === readyProcess.namespace
      && Number(/^NSpid:\s+(.+)$/m.exec(readFileSync(`/proc/${id}/status`, "utf8"))?.[1].trim().split(/\s+/).at(-1)) === readyProcess.pid; } catch { return false; }
  });
  assert.ok(pid); const identity = processIdentity(Number(pid))!; assert.ok(identity); assert.equal(originalProcessStopped(identity), false);
  writeFileSync(release, "go"); const result = await pending;
  assert.equal(result.status, "passed"); assert.equal(result.stdout, ""); assert.equal(result.terminationConfirmed, true); assert.equal(originalProcessStopped(identity), true);
  const timeout = await runVerification("build", { build: { ...binding, args: ["-e", "setInterval(()=>{},1000)"], timeoutMs: 100 } }, { cwd, jobId: "job", snapshot: "snapshot" }, { killGraceMs: 50 });
  assert.equal(timeout.reason, "timeout"); assert.notEqual(timeout.status, "passed"); assert.equal(timeout.terminationConfirmed, true);
});
