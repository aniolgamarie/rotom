// 唯一管理者的受管后端：预检只核对已持久分配，进程启动/停止都交给 supervisor。
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { createHash } from "node:crypto";
import { privateFile } from "./launch.ts";
import { validateWorkerInput } from "./managed-worker.ts";
import { assertObservation } from "./managed-observation.ts";
import { canonical, clone, closed, digest, reject, text } from "./managed-types.ts";

export function managedModelDigest(providerId, provider, model, route) {
  return digest({ provider_id: providerId, api: provider.api, base_url: provider.baseUrl, model, route });
}

export class ManagedBackend {
  constructor(context, { read = path => JSON.parse(privateFile(path)), readText = privateFile,
      list = readdirSync, pause = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds)), now = () => Date.now() } = {}) {
    this.context = context; this.supervisor = context.supervisor; this.read = read; this.readText = readText; this.list = list; this.pause = pause; this.now = now;
    this.stateRoot = dirname(dirname(dirname(context.supervisor.options.endpoint)));
    this.runs = new Map(); this.bridge = null;
    const commands = read(join(context.runtimeRoot, "runtime/commands.json"));
    if (commands.programs?.worker?.entrypoint !== "runtime/managed-worker-main.mjs" || context.installed.engine !== "node") reject("CAPABILITY_MISSING", 5);
    this.capabilities = ["managed-process", "fresh-context", "guarded-tools", "request-metering", "durable-results", "physical-termination", "workspace-leases"];
  }
  bindBridge(bridge, owner) {
    if (this.bridge !== null) reject("MANAGER_LISTENER_CONFLICT", 5);
    this.bridge = bridge; this.owner = clone(owner);
  }
  unbindBridge(bridge) { if (this.bridge === bridge) this.bridge = null; }
  input(descriptor) {
    if (!/^[a-zA-Z0-9_-]{1,128}$/.test(descriptor.attempt_id)) reject();
    const value = this.read(join(this.context.instanceRoot, "pi-home/task-keeper/dispatches", descriptor.attempt_id + ".json"));
    if (canonical(value.descriptor) !== canonical(descriptor) || value.context.manager_run_id !== null) reject("DISPATCH_IDENTITY", 4);
    return value;
  }
  async resolve(descriptor, { purpose = "admission" } = {}) {
    const { manifest, installed, roleManifest } = this.context;
    const input = this.input(descriptor), context = input.context;
    validateWorkerInput({ descriptor, context: { ...context, manager_run_id: "preflight" } });
    const role = roleManifest.roles.find(value => value.id === descriptor.role_id && value.managed);
    if (!role || role.compiled_digest !== descriptor.role_digest || canonical(role.tools) !== canonical(descriptor.allowed_tools)
        || role.model.provider !== descriptor.provider_id || role.model.model !== descriptor.model_id
        || descriptor.runtime_digest !== installed.runtime_identity || descriptor.policy_digest !== digest(manifest.permission_policy)
        || descriptor.read_roots.some(root => !role.read_roots.includes(root)) || descriptor.write_roots.some(root => !role.write_roots.includes(root))) reject("ROLE_CONFLICT", 5);
    const definition = this.readText(role.path);
    if (createHash("sha256").update(definition).digest("hex") !== descriptor.role_digest || context.role.definition !== definition) reject("ROLE_CONFLICT", 4);
    const native = this.read(join(this.context.instanceRoot, "pi-home/models.json"));
    const provider = native.providers?.[descriptor.provider_id];
    const models = Array.isArray(provider?.models) ? provider.models.filter(value => value?.id === descriptor.model_id) : [];
    const route = manifest.options.network?.routes?.[descriptor.route_id];
    if (!provider || provider.api !== "openai-completions" || models.length !== 1 || !route
        || !route.provider_ids.includes(descriptor.provider_id.replace(/^agentcfg-/, ""))
        || !/^\$AGENTCFG_PI_CREDENTIAL_[A-F0-9]{16}$/.test(provider.apiKey ?? "")) reject("UNSUPPORTED_TRANSPORT", 5);
    if (!process.env[provider.apiKey.slice(1)]) reject("CREDENTIAL_MISSING", 3);
    closed(provider, ["api", "baseUrl", "apiKey", "models"]);
    closed(models[0], ["id", "input"], ["contextWindow", "maxTokens", "reasoning", "thinkingLevelMap"]);
    if (descriptor.thinking !== "off" && (models[0].reasoning !== true || models[0].thinkingLevelMap?.[descriptor.thinking] === null
        || ["xhigh", "max"].includes(descriptor.thinking) && models[0].thinkingLevelMap?.[descriptor.thinking] === undefined)) reject("THINKING_LEVEL_UNSUPPORTED", 2);
    const resolvedRoute = { id: descriptor.route_id, type: route.mode, base_url: provider.baseUrl, proxy_url: route.proxy_url ?? null };
    if (canonical(resolvedRoute) !== canonical(context.route) || managedModelDigest(descriptor.provider_id, provider, models[0], resolvedRoute) !== descriptor.model_digest) reject("MODEL_ROUTE_MISMATCH", 4);
    if (descriptor.cost_limit !== undefined || descriptor.token_limit !== undefined && ![models[0].contextWindow, models[0].maxTokens].every(value => Number.isSafeInteger(value) && value > 0)) reject("UNBOUNDED_REQUEST", 2);
    const admission = await this.supervisor.call("worker_admission", { descriptor, purpose });
    return { transport_authenticated: true, role_digest: descriptor.role_digest, policy_digest: descriptor.policy_digest,
      model_digest: descriptor.model_digest, workspace_identity_digest: admission.workspace_identity_digest,
      grant_generation: descriptor.grant_generation, provider_id: descriptor.provider_id, model_id: descriptor.model_id,
      allowed_tools: descriptor.allowed_tools, snapshot_digest: admission.snapshot_digest };
  }
  async allocate(descriptor, { manager_run_id }) {
    await this.resolve(descriptor);
    const lease_id = descriptor.allocation_id;
    if (this.runs.has(lease_id)) reject("DISPATCH_CONFLICT", 4);
    this.runs.set(lease_id, { descriptor: clone(descriptor), manager_run_id, seen: new Set(), canceled: false });
    return { lease_id, attempt_id: descriptor.attempt_id };
  }
  async recheck(descriptor, leaseId) {
    if (leaseId !== descriptor.allocation_id) reject("DISPATCH_IDENTITY", 4);
    return this.resolve(descriptor);
  }
  async execute(descriptor, { manager_run_id, lease_id }) {
    if (!this.bridge) reject("CAPABILITY_MISSING", 5);
    const input = clone(this.input(descriptor));
    input.context.manager_run_id = manager_run_id;
    const started = await this.supervisor.call("start", { lease_id, program: "worker", payload: input });
    if (started.state !== "running" || started.attempt_id !== descriptor.attempt_id) reject("START_UNKNOWN", 4);
    const limit = Date.parse(descriptor.deadline) + 10000;
    let stopped = false;
    while (this.now() < limit) {
      const observation = await this.supervisor.call("inspect", { lease_id });
      await this.events(lease_id);
      if (!observation.protected) return this.complete(lease_id, await this.supervisor.call("worker_admission", { descriptor, purpose: "result" }));
      if (this.now() >= Date.parse(descriptor.deadline) && !stopped) {
        await this.supervisor.call("cancel", { lease_id }); stopped = true;
      }
      await this.pause(250);
    }
    return { response_text: "", terminal_status: "timeout", termination_confirmed: false, external_work_empty: false };
  }
  async events(leaseId) {
    const run = this.runs.get(leaseId), directory = join(this.stateRoot, "activity/worker-homes", leaseId, "reports");
    let names;
    try { names = this.list(directory); } catch (error) { if (error.code === "ENOENT") return; throw error; }
    for (const name of names.filter(value => /^event-[a-f0-9]{64}-[0-9]{12}\.json$/.test(value)).sort()) {
      if (run.seen.has(name)) continue;
      const event = this.read(join(directory, name));
      if (name !== "event-" + digest(event.producer_id) + "-" + String(event.sequence).padStart(12, "0") + ".json") reject("EVENT_ORDER", 4);
      await this.bridge.event(this.owner, event);
      if (["execution_settled", "execution_failed"].includes(event.phase)) run.workerSettled = event;
      run.seen.add(name);
    }
  }
  result(leaseId) {
    try {
      const value = this.read(join(this.stateRoot, "activity/worker-homes", leaseId, "reports/result.json"));
      closed(value, ["schema_version", "attempt_id", "manager_run_id", "request_digest", "candidate_digest", "response_text", "requested_model", "observed_model", "state", "failure_code", "termination_confirmed", "structured_result", "observation"]);
      assertObservation(value.observation, value.attempt_id, { failed: value.state === "execution_failed" });
      if (value.schema_version !== 1 || value.termination_confirmed !== false) reject("EVIDENCE_IDENTITY", 4);
      return value;
    }
    catch (error) { if (error.code === "ENOENT") return null; throw error; }
  }
  async verify_result(leaseId, artifactDigest) {
    const run = this.runs.get(leaseId);
    if (!run) reject("EVIDENCE_MISSING", 5);
    const observation = await this.supervisor.call("worker_admission", { descriptor: run.descriptor, purpose: "result" });
    const result = this.result(leaseId);
    const matches = result !== null && result.attempt_id === run.descriptor.attempt_id && result.manager_run_id === run.manager_run_id
      && result.request_digest === digest(run.descriptor) && ["execution_settled", "execution_failed"].includes(result.state)
      && result.candidate_digest === observation.snapshot_digest
      && canonical(result.observation.process_identity) === canonical(observation.process_identity)
      && canonical(result.requested_model) === canonical({ provider_id: run.descriptor.provider_id, model_id: run.descriptor.model_id });
    const actual = result === null ? null : digest(result);
    if (actual !== artifactDigest || result !== null && !matches) reject("EVIDENCE_IDENTITY", 4);
    const structured = result?.structured_result?.value;
    const nonempty = matches && result.state === "execution_settled" && text(result.response_text) && result.response_text.trim().length > 0
      && (!run.descriptor.allowed_tools.includes("structured_output") || structured && typeof structured === "object" && Object.keys(structured).length > 0);
    return { lease_id: leaseId, termination_confirmed: observation.resources_reclaimed && observation.termination_evidence?.verified === true,
      external_work_empty: observation.resources_reclaimed, artifact_digest: actual, artifact_nonempty: !!nonempty,
      candidate_digest: observation.snapshot_digest, mutation_chain_verified: observation.mutation_chain_verified ?? false,
      initial_candidate_digest: run.descriptor.snapshot_digest, exit_code: observation.exit_code };
  }
  async complete(leaseId, observation) {
    const run = this.runs.get(leaseId), descriptor = run.descriptor, result = this.result(leaseId);
    if (run.completed) return run.completed;
    if (result !== null) {
      const { structured_result, observation, ...base } = result;
      if (!run.workerSettled || run.workerSettled.result_digest !== digest(base)) reject("EVIDENCE_MISSING", 5);
    }
    const artifact = result === null ? null : digest(result), proof = await this.verify_result(leaseId, artifact);
    if (!proof.termination_confirmed || !proof.external_work_empty) reject("TERMINATION_UNKNOWN", 4);
    const status = observation.stop_requested || run.canceled ? "canceled" : observation.exit_code === 0 && proof.artifact_nonempty ? "completed" : "failed";
    const event = { task_id: descriptor.task_id, step_id: descriptor.step_id, attempt_id: descriptor.attempt_id,
      manager_run_id: run.manager_run_id, producer_id: "supervisor-" + leaseId, sequence: 1, event_id: "terminated-" + leaseId,
      phase: "resources_reclaimed", request_id: null, ordinal: null, usage_id: null, process_identity: observation.process_identity,
      active_tool_ids: [], external_work_ids: [], candidate_digest: observation.snapshot_digest, result_digest: artifact, termination_confirmed: true };
    await this.bridge.event(this.owner, event);
    const receipt = { receipt_id: "receipt-" + leaseId, task_id: descriptor.task_id, step_id: descriptor.step_id, attempt_id: descriptor.attempt_id,
      manager_run_id: run.manager_run_id, candidate_digest: observation.snapshot_digest, request_digest: digest(descriptor), runtime_digest: descriptor.runtime_digest,
      policy_digest: descriptor.policy_digest, final_artifact_digest: artifact, check_results: [], requested_model: { provider_id: descriptor.provider_id, model_id: descriptor.model_id },
      observed_model: result?.observed_model ?? null, terminal_status: status, termination_confirmed: true, external_work_empty: true, sequence_complete: true };
    await this.bridge.publishResult(this.owner, run.manager_run_id, receipt);
    run.completed = { response_text: result?.response_text ?? "", terminal_status: status, termination_confirmed: true, external_work_empty: true };
    return run.completed;
  }
  async cancel(leaseId) {
    const run = this.runs.get(leaseId);
    if (!run) reject("TERMINATION_UNKNOWN", 4);
    run.canceled = true;
    const before = await this.supervisor.call("inspect", { lease_id: leaseId });
    await this.supervisor.call(before.state === "allocating" ? "abort_allocation" : "cancel", { lease_id: leaseId });
    const observation = await this.supervisor.call("worker_admission", { descriptor: run.descriptor, purpose: "result" });
    if (observation.resources_reclaimed) return this.complete(leaseId, observation);
    return undefined;
  }
  reconcile(leaseId) { return this.supervisor.call("reconcile", { lease_id: leaseId }); }
  detach() { /* 父退出后持久 lease 继续由独立 supervisor 负责。 */ }
}
