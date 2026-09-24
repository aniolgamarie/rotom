import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ManagedBackend, managedModelDigest } from "../managed-backend.ts";
import { ManagerExecutor } from "../manager-executor.ts";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";
import { descriptor, fixture } from "./fixtures.ts";
import { clone, digest } from "../managed-types.ts";

function setup({ exitCode = 0, missingEvents = false } = {}) {
  const f = fixture(), cwd = mkdtempSync(join(tmpdir(), "managed-backend-"));
  const files = new Map(), calls = [], definition = "fixture role", policy = { schema_version: 1, default: "deny", rules: [] };
  const route = { id: "direct", type: "direct", base_url: "https://fixture.invalid/v1", proxy_url: null };
  const provider = { api: "openai-completions", baseUrl: route.base_url, apiKey: "$AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA", models: [{ id: "selected", input: ["text"], reasoning: true }] };
  const value = { ...descriptor(), cwd, provider_id: "agentcfg-fixture", allocation_id: "lease", result_schema_digest: digest({}), policy_digest: digest(policy),
    role_digest: createHash("sha256").update(definition).digest("hex"), model_digest: managedModelDigest("agentcfg-fixture", provider, provider.models[0], route) };
  const instanceRoot = join(cwd, "instance"), runtimeRoot = join(cwd, "runtime"), stateRoot = join(cwd, "state");
  const reports = join(stateRoot, "activity/worker-homes/lease/reports");
  const input = { descriptor: value, context: { schema_version: 1, manager_run_id: null, lease_id: "lease", prompt: "fixture prompt",
    role: { id: value.role_id, digest: value.role_digest, definition, system_prompt: definition, tools: value.allowed_tools }, route,
    model: { provider_id: value.provider_id, model_id: value.model_id, model_digest: value.model_digest, api: "openai-completions" },
    root_bindings: { project: { path: cwd, identity: "a".repeat(64) } }, artifacts: {}, result_schema: {}, minimum_remaining: 0,
    database: { root: join(instanceRoot, "pi-home/task-keeper"), filename: "runtime.db", owner: { scopeId: "scope", token: "owner", epoch: 1 } } } };
  files.set(join(instanceRoot, "pi-home/task-keeper/dispatches", value.attempt_id + ".json"), input);
  files.set(join(instanceRoot, "pi-home/models.json"), { providers: { "agentcfg-fixture": provider } });
  files.set(join(runtimeRoot, "runtime/commands.json"), { programs: { worker: { entrypoint: "runtime/managed-worker-main.mjs" } } });
  let ended = false;
  const observation = () => ({ lease_id: "lease", state: ended ? "reclaimed" : "allocating", grant_generation: 1,
    workspace_identity_digest: value.workspace_identity_digest, snapshot_digest: value.snapshot_digest,
    resources_reclaimed: ended, termination_evidence: ended ? { verified: true } : null, exit_code: ended ? exitCode : null,
    stop_requested: false, process_identity: { platform: "linux", boot_id: "fixture", pid: 100, ppid: 99, pgid: 100,
      start_time: "100", namespace: "fixture", uid: process.getuid() } });
  const supervisor = { options: { endpoint: join(stateRoot, "activity/control/control.json") }, async call(method, args) {
    calls.push(method);
    if (method === "worker_admission") return observation();
    if (method === "start") {
      const result = { schema_version: 1, attempt_id: value.attempt_id, manager_run_id: args.payload.context.manager_run_id,
        request_digest: digest(value), candidate_digest: value.snapshot_digest, response_text: "fixture result",
        requested_model: { provider_id: value.provider_id, model_id: value.model_id }, observed_model: null,
        state: "execution_settled", failure_code: null, termination_confirmed: false };
      files.set(join(reports, "result.json"), { ...result, structured_result: null, observation: { schema_version: 1, attempt_id: value.attempt_id, process_identity: observation().process_identity,
        last_request_ordinal: 1, reads: [], structured_outputs: [], tool_errors: [], request_denials: [], requests: [{ request_id: "request", ordinal: 1, status: 200 }], last_response: { status: 200, headers: {} } } });
      if (!missingEvents) files.set(join(reports, "event-" + digest("worker") + "-000000000001.json"), {
        task_id: value.task_id, step_id: value.step_id, attempt_id: value.attempt_id, manager_run_id: result.manager_run_id,
        producer_id: "worker", sequence: 1, event_id: "worker-settled", phase: "execution_settled", request_id: null, ordinal: null, usage_id: null,
        process_identity: null, active_tool_ids: [], external_work_ids: [], candidate_digest: value.snapshot_digest,
        result_digest: digest(result), termination_confirmed: false });
      ended = true;
      return { state: "running", attempt_id: value.attempt_id };
    }
    if (method === "inspect") return { state: "reclaimed", protected: false };
    throw Error("unexpected supervisor method");
  } };
  const context = { supervisor, instanceRoot, runtimeRoot, installed: { engine: "node", runtime_identity: value.runtime_digest },
    manifest: { permission_policy: policy, options: { network: { routes: { direct: { mode: "direct", provider_ids: ["fixture"] } } } } },
    roleManifest: { roles: [{ id: value.role_id, managed: true, compiled_digest: value.role_digest, path: join(cwd, "role.md"), tools: value.allowed_tools,
      model: { provider: value.provider_id, model: value.model_id }, read_roots: ["project"], write_roots: [] }] } };
  const read = path => { if (!files.has(path)) throw Object.assign(Error("missing fixture"), { code: "ENOENT" }); return clone(files.get(path)); };
  const backend = new ManagedBackend(context, { read, readText: () => definition, list: directory => [...files.keys()].filter(path => path.startsWith(directory + "/")).map(path => path.slice(directory.length + 1)),
    now: () => f.environment.time, pause: async () => {} });
  const manager = new AgentManager(undefined, 2);
  f.bridge.runtime.identity = value.runtime_digest;
  f.bridge.resolve = (value, options) => backend.resolve(value, options);
  f.bridge.executor = new ManagerExecutor({ manager, backend, store: f.store, pi: {}, context: () => ({ cwd }) });
  backend.bindBridge(f.bridge, f.owner);
  return { ...f, value, backend, manager, calls };
}

test("actual manager/backend/bridge chain accepts completed only after supervisor termination and exit zero", async () => {
  process.env.AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA = "synthetic selected";
  try {
    for (const exitCode of [0, 1]) {
      const f = setup({ exitCode });
      const admission = await f.bridge.preflight(f.value);
      assert.equal(f.calls.includes("start"), false);
      const run = await f.bridge.dispatch({ descriptor: f.value, admission_token: admission.admission_token, idempotency_key: "once" });
      await f.manager.waitForAll();
      const result = await f.bridge.get_result(f.owner, f.value.attempt_id);
      assert.equal(result.receipt.terminal_status, exitCode === 0 ? "completed" : "failed");
      assert.equal(result.receipt.manager_run_id, run.manager_run_id);
      assert.equal(f.calls.filter(name => name === "start").length, 1);
      await f.manager.dispose();
    }
  } finally { delete process.env.AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA; }
});

test("a result file without worker event evidence cannot complete a managed run", async () => {
  process.env.AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA = "synthetic selected";
  const f = setup({ missingEvents: true });
  try {
    await f.backend.allocate(f.value, { manager_run_id: "run" });
    await assert.rejects(f.backend.execute(f.value, { manager_run_id: "run", lease_id: "lease" }), /EVIDENCE_MISSING/);
  } finally { await f.manager.dispose(); delete process.env.AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA; }
});
