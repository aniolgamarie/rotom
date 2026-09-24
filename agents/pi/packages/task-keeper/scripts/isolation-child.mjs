import { readFileSync, readlinkSync, writeFileSync, symlinkSync, readdirSync, mkdirSync } from "node:fs";
import { networkInterfaces } from "node:os";
import { join } from "node:path";
import { spawn } from "node:child_process";
import assert from "node:assert/strict";
const config = JSON.parse(readFileSync(process.argv[2], "utf8"));
assert.equal(process.env.TASK_KEEPER_ISOLATED, "1");
const namespaces = Object.fromEntries(["mnt", "net", "pid"].map(key => [key, readlinkSync(`/proc/self/ns/${key}`)]));
for (const key of Object.keys(namespaces)) assert.notEqual(namespaces[key], config.namespaces[key]);
assert.ok(Object.values(networkInterfaces()).flat().every(address => !address || address.internal));
assert.equal(process.env.HOME, join(config.root, "home"));
const sentinel = join(config.root, "protected", "sentinel");
assert.throws(() => writeFileSync(sentinel, "changed"), error => ["EROFS", "EACCES"].includes(error.code));
const alias = join(config.root, "escape"); symlinkSync(sentinel, alias);
assert.throws(() => writeFileSync(alias, "changed"), error => ["EROFS", "EACCES"].includes(error.code));
assert.equal(readFileSync(sentinel, "utf8"), "unchanged");
writeFileSync(join(config.root, "writable"), "ok");
assert.equal(readFileSync(join(config.root, "writable"), "utf8"), "ok");
// The actual home is hidden; only the explicitly mounted Node installation is exposed there.
assert.throws(() => readFileSync(join(config.realHome, ".claude", "settings.json")), error => error.code === "ENOENT");
writeFileSync(join(config.root, "isolation.json"), JSON.stringify({ passed: true, namespaces, checks: ["private namespaces", "loopback only", "private home", "absolute write denied", "symlink write denied", "temporary write allowed", "real Claude config hidden"] }), { mode: 0o600 });
const focused = config.nodeArgs.includes("--test");
const focusedRoot = focused ? join(process.env.TASK_KEEPER_TEST_RESULT_ROOT, `focused-${new Date().toISOString().replace(/[:.]/g, "-")}`) : null;
const recordRoot = focusedRoot ? join(focusedRoot, "records") : null;
if (recordRoot) mkdirSync(recordRoot, { recursive: true, mode: 0o700 });
const child = spawn(process.execPath, config.nodeArgs, { cwd: config.pkg, env: { ...process.env, ...(recordRoot ? { TASK_KEEPER_TEST_RECORD_DIR: recordRoot } : {}) }, stdio: "inherit" });
child.on("error", error => { console.error(error); process.exitCode = 1; });
child.on("exit", (code) => {
  process.exitCode = code ?? 1;
  if (!recordRoot) return;
  const executions = readdirSync(recordRoot).filter(file => !file.endsWith(".discovery.jsonl"))
    .flatMap(file => readFileSync(join(recordRoot, file), "utf8").trim().split("\n").filter(Boolean).map(line => JSON.parse(line)));
  const meaningful = executions.filter(item => item.status === "passed" && item.assertions > 0);
  const reason = !executions.length ? "ZERO_EXECUTED_TESTS" : !meaningful.length ? "NO_ASSERTED_EXECUTIONS"
    : executions.some(item => item.status === "passed" && item.assertions === 0) ? "ZERO_ASSERTION_TEST" : null;
  if (reason) { console.error(reason); process.exitCode = 1; }
  writeFileSync(join(focusedRoot, "summary.json"), JSON.stringify({ nodeArgs: config.nodeArgs, executed: executions.length,
    assertedPassed: meaningful.length, assertions: executions.reduce((sum, item) => sum + item.assertions, 0), reason, exitCode: process.exitCode }), { mode: 0o600 });
});
