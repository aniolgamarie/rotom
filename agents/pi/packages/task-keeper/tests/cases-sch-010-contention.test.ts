import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { registerWorkflowCases } from "./fixtures/workflow-cases.ts";

// /orch starts the actual verifier, but the competing adapter harness is not an E entry.
registerWorkflowCases(["verifier-first"]);

if (!process.env.TASK_KEEPER_SCH010_CUT) test("[V] SCH010 verifier workspace demand negative control trips the frozen-byte oracle", { timeout: 90000 }, async (t) => {
  const artifacts = join(process.env.TASK_KEEPER_TEST_RESULT_ROOT!, `sch010-negative-${Date.now()}-${process.pid}`);
  mkdirSync(artifacts);
  const command = ["--experimental-strip-types", "--test", fileURLToPath(import.meta.url)];
  const child = spawn(process.execPath, command, { env: { ...process.env, NODE_TEST_CONTEXT: undefined, TASK_KEEPER_SCH010_CUT: "1",
    TASK_KEEPER_TEST_RECORD_DIR: join(artifacts, "records") }, stdio: ["ignore", "pipe", "pipe"] });
  t.after(async () => {
    if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGTERM"); await exit; }
  });
  let output = ""; child.stdout.on("data", data => { output += data; }); child.stderr.on("data", data => { output += data; });
  const exit = await new Promise<{ code: number | null; signal: string | null }>((resolve, reject) => {
    child.once("error", reject); child.once("close", (code, signal) => resolve({ code, signal }));
  });
  writeFileSync(join(artifacts, "negative.log"), output);
  writeFileSync(join(artifacts, "exit.json"), JSON.stringify({ command: [process.execPath, ...command], ...exit }, null, 2));
  assert.equal(exit.code, 1); assert.equal(exit.signal, null);
  assert.match(output, /SCH010_FREEZE_ZERO_WRITES: candidate bytes changed while verifier held/);
  assert.match(output, /SCH010_ARTIFACT/);
  acceptance("AC34","writer-freeze-cut",{level:"V",observer:"real-verifier-and-competing-writer-private-cut",predicate:"removing freeze permits forbidden byte mutation",artifact:observerArtifact("writer-freeze-cut",{exit,output})},()=>{
    assert.equal(exit.code,1);assert.equal(exit.signal,null);assert.match(output,/SCH010_FREEZE_ZERO_WRITES: candidate bytes changed while verifier held/);assert.doesNotMatch(output,/ERR_MODULE_NOT_FOUND|test timed out/);
  });
});
