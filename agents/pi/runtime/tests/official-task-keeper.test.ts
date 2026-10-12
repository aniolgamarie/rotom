import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createOfficialTaskKeeper } from "../official-task-keeper.ts";

async function fixture(failure) {
  const root = mkdtempSync(join(tmpdir(), "tk-close-"));
  const path = "node_modules/@agentcfg/pi-task-keeper/index.mjs";
  mkdirSync(join(root, "node_modules/@agentcfg/pi-task-keeper"), { recursive: true });
  writeFileSync(join(root, path), "export default () => {};\n");
  const calls = { dispose: 0, close: 0 };
  class Store {
    close() { assert.equal(++calls.close, 1); }
  }
  class TaskServiceCore {
    async dispose() { assert.equal(++calls.dispose, 1); if (failure) throw failure; }
    get() { throw new Error("RECORDED_GET_MUST_NOT_BE_CURRENT_STATUS"); }
    async inspect(id) { calls.inspect=(calls.inspect??0)+1;await Promise.resolve();return {id,status:"BLOCKED",reason:"required:tests",
      goal:"never copy private goal",evidence:{checkedAt:123,currentness:"reobserved",summary:{total:2,current:1,stale:1,invalid:0,failed:1,unknown:0,
        rows:[{privateRecordBody:"never copy record body"}]}}}; }
  }
  const installed = { runtime_identity: "runtime", slice_identity: "slice", lock_identity: "lock",
    resources: { extensions: [{ capability_id: "task-workflow", path }] } };
  const contract = { schema_version: 3, profile_id: "pi-full", runtime_identity: "runtime",
    slice_identity: "slice", lock_identity: "lock", capability_projection: {}, provider_projection: {},
    source_projection: {}, config_identity: "config", policy_digest: "policy", checker_identity: "delegate-runtime-contract-v3" };
  const sessionManager = { getSessionId: () => "session" }, handlers = new Map();
  const api = { on: (event, handler) => handlers.set(event, handler) };
  const value = createOfficialTaskKeeper({ manifest: { profile_id: "pi-full", plugins: ["task-keeper"],
    plugin_capabilities: { "task-keeper": { capability_id: "task-workflow" } }, options: { task_keeper: { enabled: true } } },
    installed, runtimeRoot: root, instanceRoot: root, cwd: root, sessionManager,
    supervisor: { call: async () => contract }, issuer: { open() {}, retire() {} },
    configurationSnapshot: async () => ({}), policySnapshot() {},
    importCore: async () => ({ Store, TaskServiceCore, readConfigForDirectory: () => ({}) }) });
  value.factory(api);
  await handlers.get("session_start")({}, { cwd: root, sessionManager });
  return { value, calls, handlers,root,sessionManager };
}
test("Task Keeper session shutdown and runtime drain share one close operation", async () => {
  const { value, calls, handlers } = await fixture();
  await handlers.get("session_shutdown")();
  await Promise.all([value.close(), value.close()]);
  assert.deepEqual(calls, { dispose: 1, close: 1 });
});
test("Task Keeper keeps the first rejected cleanup promise and does not retry resources", async () => {
  const failure = new Error("OWN_CLOSE_REJECTED");
  const { value, calls } = await fixture(failure);
  const first = value.close();
  assert.equal(value.close(), first);
  await assert.rejects(first, error => error === failure);
  await assert.rejects(value.close(), error => error === failure);
  assert.deepEqual(calls, { dispose: 1, close: 1 });
});
test("official status awaits original inspect and exposes only safe counts/currentness without raw goal/record",async()=>{
  const {value,calls,root,sessionManager}=await fixture();
  const result=await value.tool.execute("status-request",{action:"status",job_id:"job"},undefined,undefined,{cwd:root,sessionManager});
  assert.equal(calls.inspect,1);assert.equal(result.details.evidence.currentness,"reobserved");assert.equal(result.details.evidence.counts.stale,1);
  assert.equal(JSON.stringify(result).includes("never copy"),false);assert.deepEqual(Object.keys(result.details).sort(),["evidence","id","reason","status"]);
  await value.close();
});
