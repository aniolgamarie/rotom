import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { cpSync, mkdirSync, readFileSync, writeFileSync, existsSync, watch } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isolatedDirectory } from "./helpers.ts";
import type { TestContext } from "node:test";

async function cancelBeforeHandshake(t: TestContext, cut: boolean) {
  const root = isolatedDirectory(t), pkg = fileURLToPath(new URL("..", import.meta.url));
  cpSync(join(pkg, "src"), join(root, "src"), { recursive: true });
  writeFileSync(join(root, "package.json"), '{"type":"module"}');
  const marker = join(root, "namespace-before-handshake"), effect = join(root, "must-not-run");
  const childPath = join(root, "src/verification/namespace-command.ts"), source = readFileSync(childPath, "utf8");
  const needle = 'report({ type: "ready", namespace });';
  assert.equal(source.split(needle).length, 2);
  writeFileSync(childPath, 'import {writeFileSync as fixtureWrite} from "node:fs";\n' + source.replace(needle,
    `process.on("SIGTERM", () => {});\nfixtureWrite(${JSON.stringify(marker)}, "namespace alive before ready message");\nawait new Promise(resolve => setTimeout(resolve, 500));\n${needle}`));
  // Hold the pre-authorization child deterministically even if signalling is
  // unavailable. Both copies use this same fault; only closing the gate differs.
  const supervisorPath = join(root, "src/verification/supervisor.ts");
  let supervisor = readFileSync(supervisorPath, "utf8");
  supervisor = 'const fixtureKill = (..._args: unknown[]): never => { throw new Error("injected signal unavailable"); };\n'
    + supervisor.replaceAll("process.kill(", "fixtureKill(");
  if (cut) {
    const gate = 'if (!started && !authorization.writableEnded) authorization.end();';
    assert.equal(supervisor.split(gate).length, 2); supervisor = supervisor.replace(gate, "// Negative control: leave authorization pipe open.");
  }
  writeFileSync(supervisorPath, supervisor);
  const { supervisedCommand } = await import(pathToFileURL(join(root, "src/verification/supervisor.ts")).href);
  const cancellation = new AbortController();
  let abortedAt: number | null = null;
  const watcher = watch(root, () => { if (existsSync(marker) && abortedAt === null) { abortedAt = performance.now(); cancellation.abort(); } });
  let result;
  try {
    result = await supervisedCommand({ executable: process.execPath, args: ["-e", `require('node:fs').writeFileSync(${JSON.stringify(effect)},'unauthorized')`],
      environment: {}, timeoutMs: 6000, kind: "build", parser: "exit-code", minimumTests: 1 }, root, process.env,
      { signal: cancellation.signal, maxBytes: 4096, killGraceMs: 200 });
  } finally { watcher.close(); }
  assert.notEqual(abortedAt, null);
  const elapsed = performance.now() - abortedAt!;
  assert.equal(existsSync(marker), true); assert.equal(cancellation.signal.aborted, true);
  assert.equal(existsSync(effect), false); assert.equal(result.started, false); assert.equal(result.cancelled, true);
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
    const target = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "handshake-observers"); mkdirSync(target,{recursive:true});
    writeFileSync(join(target, cut ? "negative.json" : "fixed.json"), JSON.stringify({elapsed,result,cut},null,2));
  }
  return { elapsed, result };
}
function bounded(outcome: Awaited<ReturnType<typeof cancelBeforeHandshake>>) {
  assert.ok(outcome.elapsed < 2500, "SUPERVISOR_HANDSHAKE_CANCEL_BOUNDED");
  assert.equal(outcome.result.terminationConfirmed, true);
  assert.equal(outcome.result.timedOut, false);
}

test("[P] cancellation before namespace proof closes the unopened command gate promptly", {timeout:15000}, async t => {
  const result=await cancelBeforeHandshake(t,false);bounded(result);
  acceptance("AC08","pre-handshake-cancel",{level:"P",observer:"actual-preauthorization-namespace-and-closed-gate",predicate:"cancel before handshake cannot start user command",artifact:observerArtifact("handshake-cancel",result)},()=>{assert.equal(result.result.started,false);assert.equal(result.result.terminationConfirmed,true);assert.equal(result.result.timedOut,false);});
});
test("verifier cancellation negative control detects an unclosed authorization pipe", {timeout:15000}, async t => {
  const broken = await cancelBeforeHandshake(t, true);
  assert.throws(() => bounded(broken), /SUPERVISOR_HANDSHAKE_CANCEL_BOUNDED/);
});
