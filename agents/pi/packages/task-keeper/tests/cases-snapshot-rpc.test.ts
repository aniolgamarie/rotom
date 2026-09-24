import { registerWorkflowCases } from "./fixtures/workflow-cases.ts";
registerWorkflowCases(["snapshot-pause-revoke-first", "snapshot-pause-await-first", "snapshot-stop-revoke-first", "snapshot-stop-await-first", "snapshot-dispose-revoke-first", "snapshot-dispose-await-first"]);

import { test, assert } from "./recorded-test.ts";
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
if (!process.env.TASK_KEEPER_SNAPSHOT_GUARD_CUT) test("snapshot negative control rejects removal of the stale-resume check", {timeout: 90000}, () => {
  const artifact = join(process.env.TASK_KEEPER_TEST_RESULT_ROOT!, `snapshot-negative-${Date.now()}-${process.pid}`);
  mkdirSync(artifact, {recursive:true});
  const result = spawnSync(process.execPath, ["--experimental-strip-types", "--test", "--test-reporter=tap", "--test-name-pattern=snapshot-pause-revoke-first", fileURLToPath(import.meta.url)], {
    timeout: 85000, encoding:"utf8", env:{...process.env, NODE_TEST_CONTEXT:undefined, TASK_KEEPER_SNAPSHOT_GUARD_CUT:"1",TASK_KEEPER_TEST_RECORD_DIR:join(artifact,"records")},
  });
  writeFileSync(join(artifact,"negative.tap"),result.stdout+result.stderr);
  writeFileSync(join(artifact,"exit.json"),JSON.stringify({status:result.status,signal:result.signal}));
  assert.equal(result.status,1);assert.equal(result.signal,null);
  assert.match(result.stdout,/SNAPSHOT_REVOKED_CONTROL_MUST_PERSIST/);
  assert.match(result.stdout,/# tests 1\b/);assert.match(result.stdout,/# fail 1\b/);
});
