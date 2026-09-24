import { test, assert } from "./recorded-test.ts";
import { createJiti } from "jiti";
import { isolatedDirectory } from "./helpers.ts";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import type { runVerification as Run } from "../src/verification/runner.ts";
const loaded = await createJiti(import.meta.url).import<{ runVerification: typeof Run }>("../src/verification/runner.ts");
test("[P] repeated namespace completion under Pi's TypeScript loader has an independently closed supervisor", { timeout: 60000 }, async t => {
  const cwd = isolatedDirectory(t), observed: unknown[] = [];
  for (let i = 0; i < 60; i++) {
    const result = await loaded.runVerification("build", { build: { executable: process.execPath, args: ["-e", "process.exit(0)"], environment: {},
      timeoutMs: 5000, kind: "build", parser: "exit-code", minimumTests: 1 } }, { cwd, jobId: "job", snapshot: "tree" });
    observed.push(result); writeFileSync(join(cwd, "supervisor-results.json"), JSON.stringify(observed));
    assert.equal(result.status, "passed", JSON.stringify({ iteration: i, result })); assert.equal(result.supervisor.namespaceStopped, true);
  }
});
