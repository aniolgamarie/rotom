import { test, assert } from "./recorded-test.ts";
import { spawn } from "node:child_process";
import { once } from "node:events";
import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { processIdentity, originalProcessStopped, type ProcessIdentity } from "../src/adapters/process-identity.ts";

test("[U] reaping between proc reads cannot reverse an observed terminal process", t => {
  const own = processIdentity()!, pid = 2000000000, path = `/proc/${pid}/stat`;
  const stat = fs.readFileSync(`/proc/${process.pid}/stat`, "utf8");
  const fields = stat.slice(stat.lastIndexOf(")") + 2).trim().split(/\s+/); fields[0] = "Z";
  const zombie = `${pid} (reaping-fixture) ${fields.join(" ")}`;
  const read = fs.readFileSync; let reads = 0;
  t.mock.method(fs, "readFileSync", (...args: Parameters<typeof read>) => {
    if (args[0] === path) {
      reads++;
      if (reads === 1) return zombie;
      throw Object.assign(new Error("reaped at the next read"), { code: "ENOENT" });
    }
    return Reflect.apply(read, fs, args);
  });
  syncBuiltinESMExports();
  try {
    // Replays the exact Z -> proc disappearance interleaving from the retained failure.
    assert.equal(originalProcessStopped({ ...own, pid }), true);
    assert.equal(reads, 1);
    assert.equal(originalProcessStopped({ ...own, pid }), true); // subsequent ESRCH also confirms it
  } finally { t.mock.restoreAll(); syncBuiltinESMExports(); }
});

test("[P] PID namespace and startup identity are necessary to prove physical termination", async t => {
  const own = processIdentity()!;
  assert.ok(own.pidNamespace); assert.equal(originalProcessStopped(own), false);
  assert.equal(originalProcessStopped({ ...own, pidNamespace: undefined }), null);
  assert.equal(originalProcessStopped({ ...own, pid: 2000000000, pidNamespace: "pid:[foreign]" }), null);
  const script = "const fs=require('node:fs');const s=fs.readFileSync('/proc/self/stat','utf8');console.log(JSON.stringify({pid:process.pid,bootId:fs.readFileSync('/proc/sys/kernel/random/boot_id','utf8').trim(),startTicks:s.slice(s.lastIndexOf(')')+2).trim().split(/\\s+/)[19],pidNamespace:fs.readlinkSync('/proc/self/ns/pid')}));setInterval(()=>{},1000);";
  const child = spawn("bwrap", ["--unshare-user", "--unshare-pid", "--die-with-parent", "--ro-bind", "/", "/", "--proc", "/proc", process.execPath, "-e", script], { stdio: ["ignore", "pipe", "pipe"] });
  t.after(async () => { if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGKILL"); await exit; } });
  let output = ""; const ready = new Promise<ProcessIdentity>((resolve, reject) => {
    child.stdout.on("data", chunk => { output += chunk; if (output.includes("\n")) { try { resolve(JSON.parse(output.split("\n")[0])); } catch (error) { reject(error); } } });
    child.once("exit", () => reject(new Error(`namespace process exited: ${output}`))); child.once("error", reject);
  });
  const remote = await ready;
  assert.notEqual(remote.pidNamespace, own.pidNamespace); assert.equal(originalProcessStopped(remote), null);
  const stopped = once(child, "exit"); child.kill("SIGKILL"); await stopped;
  // Even after the supervisor terminates it, this API cannot resolve a PID in another namespace.
  assert.equal(originalProcessStopped(remote), null);
  assert.equal(originalProcessStopped({ ...own, bootId: "previous-boot" }), true);
});
