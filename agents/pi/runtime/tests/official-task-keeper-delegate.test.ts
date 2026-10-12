import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../../packages/task-keeper/src/store/database.ts";
import { TaskKeeperDelegateAdapter } from "../official-task-keeper-delegate.ts";
function fixture(t, { lost = false } = {}) {
  const root = mkdtempSync(join(tmpdir(), "tk-core-"));
  const store = new Store(root), owner = store.claimOwner("scope", "owner-token");
  t.after(() => { store.close(); rmSync(root, { recursive: true, force: true }); });
  const manifest = { profile_id: "pi-full", options: { task_keeper: { enabled: true }, model_delegate: { max_run_seconds: 30 } },
    permission_policy: { schema_version: 1, default: "deny", rules: [] }, model_bindings: { task_keeper_reader: { provider: "selected", model: "model" } } };
  const config = { roles: { scout: { route: "selected" } }, routes: { selected: { provider: "selected", model: "model" } } };
  store.put("managed-jobs", "job", { id: "job", workScope: "scope", cwd: root, sourceCwd: root, controlEpoch: 1, cancelRequested: false });
  store.put("jobs", "job", { spec: { workScope: "scope" }, steps: [{ id: "inspect", kind: "read", status: "running", intentId: "phase-intent" }] });
  const calls = [], sources = [], retired = [];
  const result = { run_id: "logical", status: "completed", active_attempt_id: "attempt", budget: { deadline_ms: Date.now() + 5000 },
    actions: [{ attempt_id: "attempt", physical_run_id: "physical", receipt_ref: "physical", termination_verified: true, task_succeeded: true }] };
  const supervisor = { async call(method, args) {
    calls.push([method, structuredClone(args)]);
    if (method === "delegate_action_v3" && lost) throw new Error("synthetic lost ACK");
    if (["delegate_lookup_v3", "delegate_status_v3"].includes(method) && lost) return { ...result, status: "unknown", actions: [] };
    if (method === "delegate_artifact_v3") return { content: "real interface fixture result", offset: 0, next_offset: null, total_bytes: 29 };
    return result;
  } };
  const adapter = new TaskKeeperDelegateAdapter({ store, owner, config, manifest, supervisor,
    issuer: { async open(facts) { sources.push(structuredClone(facts)); return "private-source"; }, async retire(ref) { retired.push(ref); } },
    policySnapshot() {}, runtimeContract: () => ({ checker: "trusted-own-fixture" }) });
  const input = { jobId: "job", stepId: "inspect", parentIntentId: "phase-intent", role: "scout", task: "readonly evidence", cwd: root };
  return { adapter, store, owner, root, calls, sources, retired, input };
}
test("actual own Store job/step supplies readonly source; adapter uses core once and persists only references", async t => {
  const f = fixture(t), result = await f.adapter.execute(f.input);
  assert.equal(result.status, "ended"); assert.equal(result.content, "real interface fixture result");
  assert.equal(f.sources[0].task_id, "job"); assert.deepEqual(f.sources[0].store_owner, f.owner);
  assert.deepEqual(f.calls.map(row => row[0]), ["delegate_action_v3", "delegate_status_v3", "delegate_artifact_v3"]);
  assert.equal(f.calls[0][1].action.allow_workspace_write, false);
  const link = f.store.list("delegate-core-links-v3")[0].value;
  assert.deepEqual(Object.keys(link).sort(), ["logical_run_id", "physical_attempt_id", "receipt_ref", "request_id"]);
  await f.adapter.execute(f.input);
  assert.equal(f.calls.filter(row => row[0] === "delegate_action_v3").length, 1);
  await f.adapter.close(); assert.deepEqual(f.retired, ["private-source"]);
});
test("writer or changed Store owner is rejected before source registration or physical allocation", async t => {
  const f = fixture(t);
  await assert.rejects(f.adapter.execute({ ...f.input, role: "worker" }), /WRITE_UNAVAILABLE/);
  f.store.revokeOwner(f.owner);
  await assert.rejects(f.adapter.execute(f.input));
  assert.equal(f.sources.length, 0); assert.equal(f.calls.length, 0);
  assert.equal(f.store.list("delegate-core-links-v3").length, 0);
});
test("lost ACK lookup is readonly and replay never submits another action", async t => {
  const f = fixture(t, { lost: true });
  assert.equal((await f.adapter.execute(f.input)).status, "unknown");
  assert.equal((await f.adapter.execute(f.input)).status, "unknown");
  assert.equal(f.calls.filter(row => row[0] === "delegate_action_v3").length, 1);
  assert.equal(f.calls.filter(row => row[0] === "delegate_lookup_v3").length, 1);
});
test("modern recovery consumes only original core association and verified termination without another send", async t => {
  const f = fixture(t);
  await f.adapter.execute(f.input);
  const sends = f.calls.filter(row => row[0] === "delegate_action_v3").length;
  assert.deepEqual(await f.adapter.reconcileStep("job", "inspect", "phase-intent"), { stopped: true, neverStarted: false });
  assert.equal(f.calls.filter(row => row[0] === "delegate_action_v3").length, sends);
  f.adapter.sources.clear();
  const count = f.calls.length;
  assert.deepEqual(await f.adapter.reconcileStep("job", "inspect", "phase-intent"), { stopped: false, neverStarted: false });
  assert.equal(f.calls.length, count);
});
test("unknown or mismatched old physical attempt cannot reconcile stopped", async t => {
  const f = fixture(t, { lost: true });
  await f.adapter.execute(f.input);
  assert.deepEqual(await f.adapter.reconcileStep("job", "inspect", "phase-intent"), { stopped: false, neverStarted: false });
  const g = fixture(t);
  await g.adapter.execute(g.input);
  const entry = g.store.list("delegate-core-links-v3")[0];
  g.store.put("delegate-core-links-v3", entry.id, { ...entry.value, physical_attempt_id: "foreign-attempt" });
  assert.deepEqual(await g.adapter.reconcileStep("job", "inspect", "phase-intent"), { stopped: false, neverStarted: false });
});

test("private safe OAuth description composes actual model route without fake credential ref",async t=>{
 const f=fixture(t),hash="a".repeat(64),sentinel="never export this header fixture";
 const configuration={configIdentity:hash,runtimeIdentity:hash,effectiveConfigDigest:hash,policyDigest:hash,projectConstraintsDigest:hash,resourcesDigest:hash,model:{provider:"selected",model:"model"},thinking:"off"};
 const models=[{role_id:"task_keeper_reader",provider_id:"selected",model_id:"model",description:{id:"model",provider:"selected",api:"openai-completions",baseUrl:"https://fixture.invalid",contextWindow:4096,maxTokens:64,input:["text"],reasoning:false}}];
 f.adapter.manifest.model_configuration={providers:{selected:{logical_id:"selected",auth_kind:"oauth",owner:"pi-native",credential_ref:null,config:null}}};
 f.adapter.installed={runtime_identity:hash,toolchains:{node:process.version},sdk_version:"1.0.1"};f.adapter.contract=()=>({runtime_identity:hash,lock_identity:hash,slice_identity:hash,config_identity:hash,provider_projection:{selected:{owner:"pi-native"}}});f.adapter.semanticProducer=async()=>({configuration,models});
 const result=await f.adapter.semanticContext();assert.equal(result.model_routes[0].auth.credential_ref,null);assert.match(result.model_routes[0].public_configuration_digest,/^[a-f0-9]{64}$/);assert.equal(JSON.stringify(result).includes(sentinel),false);
 models[0].description.headers={Authorization:sentinel};await assert.rejects(f.adapter.semanticContext(),/INPUT_SNAPSHOT_PROVIDER_INVALID/);
 delete models[0].description.headers;models[0].role_id="unapproved";await assert.rejects(f.adapter.semanticContext(),/MODEL_METADATA_UNAVAILABLE/);
});
