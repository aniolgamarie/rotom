import { importManagedUsage } from "../usage/managed.ts";
// 业务工作流到 managed-executor-v1 的适配；沿用同一 task、候选与请求预算。
import { randomUUID } from "node:crypto";
import { mkdirSync, readFileSync, realpathSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";
import { managedModelDigest } from "@agentcfg/pi-runtime/managed-backend";
import { assertRule, canonical, digest, reject } from "@agentcfg/pi-runtime/managed-types";
import type { Store, Owner } from "../store/database.ts";
import type { Config } from "../config.ts";
import type { SubagentsAdapter, DelegationResult } from "../adapters/subagents.ts";

export interface ManagedStepInput {
  jobId: string; stepId: string; role: "scout" | "worker" | "reviewer"; task: string; cwd: string;
  evidenceIds?: string[]; parentIntentId?: string; routeId?: string; profileRef?: string; incidentId?: string;
  minimumRemaining?: number; resultSchema?: Record<string, unknown>;
}
const defaultResult = { type: "object", additionalProperties: false, required: ["summary"], properties: { summary: { type: "string", minLength: 1 } } };

export class ManagedExecution {
  private adapter: SubagentsAdapter; private store: Store; private owner: Owner; private config: Config; private runtime: any;
  constructor(adapter: SubagentsAdapter, store: Store, owner: Owner, config: Config, runtime: any) {
    this.adapter = adapter; this.store = store; this.owner = owner; this.config = config; this.runtime = runtime;
  }
  async prepare(input: ManagedStepInput) {
    this.store.assertOwner(this.owner);
    const job = this.store.get<any>("managed-jobs", input.jobId);
    if (!job || job.workScope !== this.owner.scopeId || realpathSync(input.cwd) !== realpathSync(job.cwd)) reject("TASK_IDENTITY_CONFLICT", 4);
    const setting = this.runtime.manifest.options.task_keeper;
    if (!setting?.enabled) reject("CAPABILITY_MISSING", 5);
    const policy = this.runtime.manifest.permission_policy;
    if (typeof this.runtime.permissionAccess?.parentSnapshot !== "function") reject("PERMISSION_CAPABILITY_MISSING", 5);
    const parent = this.runtime.permissionAccess.parentSnapshot();
    if (!parent || parent.policy_digest !== digest(policy) || canonical(parent.policy) !== canonical(policy)
        || !Number.isSafeInteger(parent.generation) || parent.generation < 1 || !Array.isArray(parent.inherited_denials)) reject("PERMISSION_ADMISSION_STALE", 4);
    for (const rule of parent.inherited_denials) {
      assertRule(rule);
      if (rule.effect !== "deny") reject("PARENT_DENIALS_INVALID", 5);
    }
    if (policy.rules.some((rule: any) => rule.effect === "deny" && !parent.inherited_denials.some((inherited: any) => canonical(inherited) === canonical(rule)))) reject("PARENT_DENIALS_MISSING", 5);
    const roleId = input.stepId === "second-opinion" ? "task-keeper-second-view"
      : input.role === "worker" ? "task-keeper-writer" : input.role === "reviewer" ? "task-keeper-reviewer" : "task-keeper-reader";
    const role = this.runtime.roleManifest.roles.find((row: any) => row.id === roleId && row.managed);
    const routeId = input.routeId ?? this.config.roles[input.role]?.route;
    const configured = this.config.routes[routeId], profile = this.config.executionProfiles[input.profileRef ?? this.config.roles[input.role]?.profileRef];
    if (!role || !configured || !profile?.thinking || configured.provider !== role.model.provider || configured.model !== role.model.model) reject("UNBOUND_MODEL", 2);
    const native = JSON.parse(readFileSync(join(this.runtime.instanceRoot, "pi-home/models.json"), "utf8"));
    const provider = native.providers[role.model.provider], model = provider?.models.find((row: any) => row.id === role.model.model);
    const network = this.runtime.manifest.options.network?.routes?.[configured.network];
    if (!model || !network) reject("UNSUPPORTED_TRANSPORT", 5);
    const route = { id: configured.network, type: network.mode, base_url: provider.baseUrl, proxy_url: network.proxy_url ?? null };
    const taskId = input.jobId;
    if (!this.store.has("agentcfg-tasks-v1", taskId)) this.adapter.journal.createTask({ schema_version: 1, task_id: taskId, goal: job.goal,
      workflow: job.workflow, candidate_id: taskId, budget_scope_id: "budget-" + taskId,
      role_bindings: { reader: "task_keeper_reader", writer: "task_keeper_writer", reviewer: "task_keeper_reviewer" },
      policy_digest: digest(policy), check_ids: setting.check_ids, required_review: true,
      second_view: setting.second_view_enabled ? { model_role: "second_view", max_attempts: setting.max_second_view_rounds, required: true } : null, state: "queued" });
    let budget = this.store.get<any>("agentcfg-task-budgets-v1", taskId);
    if (!budget) {
      budget = { schema_version: 1, task_id: taskId, deadline: new Date(Math.min(job.schedule?.deadline ?? Infinity,
        (job.schedule?.admittedAt ?? job.createdAt) + setting.limits.wall_seconds * 1000)).toISOString(), ...setting.limits };
      this.store.put("agentcfg-task-budgets-v1", taskId, budget);
    }
    const key = input.parentIntentId ?? input.stepId;
    const already = this.store.get<any>("agentcfg-attempt-keys-v1", digest({ task_id: taskId, idempotency_key: key }));
    if (already) return this.adapter.journal.read(already.attempt_id);
    if (Date.now() >= Date.parse(budget.deadline)) reject("DEADLINE_EXCEEDED", 4);
    const previous = this.store.get<any>("agentcfg-last-attempt-v1", digest([taskId, input.stepId]));
    const identity = this.adapter.journal.prepareIdentity({ task_id: taskId, step_id: input.stepId,
      continuation_of: previous?.attempt_id ?? null, idempotency_key: key });
    if (this.store.has("agentcfg-descriptors-v1", identity.attempt_id)) return this.adapter.journal.read(identity.attempt_id);
    if (previous) {
      const old = this.adapter.journal.read(previous.attempt_id);
      const proof = await this.runtime.supervisor.call("reconcile", { lease_id: old.descriptor.allocation_id });
      if (proof.protected || !proof.termination_evidence?.verified) reject("TERMINATION_UNKNOWN", 4);
      this.store.put("agentcfg-attempt-termination-v1", previous.attempt_id, { lease_id: old.attempt.lease_id,
        termination_confirmed: true, resources_reclaimed: true, evidence_digest: proof.termination_evidence.evidence_digest });
    }
    const cwd = realpathSync(input.cwd), source = await this.runtime.supervisor.call("workspace_identity", { path: job.sourceCwd });
    const project = await this.runtime.supervisor.call("workspace_identity", { path: cwd });
    const snapshot = await this.runtime.supervisor.call("workspace_snapshot", { path: cwd });
    const owner = (await this.adapter.handshake()).owner;
    const definition = readFileSync(role.path, "utf8"), separator = definition.indexOf("\n---\n");
    if (separator < 0) reject("ROLE_CONFLICT", 5);
    const roots: Record<string, any> = {};
    const { rootIdentity } = await import("@agentcfg/pi-runtime/permission-policy");
    const planned = new Map<string, any>();
    for (const id of [...new Set([...Object.keys(this.runtime.manifest.options.paths?.roots ?? {}), ...role.read_roots, ...role.write_roots])]) {
      const path = id === "project" ? cwd : realpathSync(this.runtime.manifest.options.paths.roots[id as string].path);
      roots[id as string] = { path, identity: rootIdentity(path) };
      if (role.write_roots.includes(id)) { const value = await this.runtime.supervisor.call("workspace_identity", { path }); planned.set(value.workspace_key, value); }
    }
    const allocation = await this.runtime.supervisor.call("allocate", { kind: "worker", execution_id: identity.attempt_id, task_id: taskId,
      attempt_id: identity.attempt_id, lock_identity: this.runtime.installed.lock_identity, slice_identity: this.runtime.installed.slice_identity,
      policy_digest: digest(policy), candidate_digest: snapshot.snapshot_digest, planned_workspaces: [...planned.values()] });
    try {
      const resultSchema = input.resultSchema ?? defaultResult;
      const descriptor = { protocol_version: 1, request_id: "request-" + randomUUID(), ...owner, role_id: roleId, role_digest: role.compiled_digest,
        runtime_digest: this.runtime.installed.runtime_identity, policy_digest: digest(policy), candidate_id: taskId, snapshot_digest: snapshot.snapshot_digest,
        cwd, source_cwd: source.worktree_path, allowed_tools: role.tools, read_roots: role.read_roots, write_roots: role.write_roots,
        inherited_denials: parent.inherited_denials, context_mode: "fresh", nested: false, executor: "managed-process",
        provider_id: role.model.provider, model_id: role.model.model, model_digest: managedModelDigest(role.model.provider, provider, model, route),
        route_id: route.id, thinking: profile.thinking, request_ceiling: budget.model_requests, turn_ceiling: budget.model_turns, deadline: budget.deadline,
        result_schema_digest: digest(resultSchema), allowed_artifact_ids: input.evidenceIds ?? [], workspace_write_lease_ids: allocation.workspace_write_lease_ids,
        workspace_identity_digest: project.workspace_key, grant_generation: allocation.grant_generation, allocation_id: allocation.allocation_id,
        ...(budget.token_limit === undefined ? {} : { token_limit: budget.token_limit }), ...(budget.cost_limit === undefined ? {} : { cost_limit: budget.cost_limit }) };
      const prepared = this.adapter.journal.allocate({ task_id: taskId, step_id: input.stepId, continuation_of: identity.continuation_of, idempotency_key: key, descriptor });
      const artifacts = Object.fromEntries((input.evidenceIds ?? []).map(id => {
        const value = this.store.get<any>("artifacts", id);
        if (!value || value.jobId !== taskId) reject("ARTIFACT_SCOPE_MISMATCH", 4);
        return [id, value];
      }));
      const context = { schema_version: 1, manager_run_id: null, lease_id: allocation.lease_id,
        prompt: input.task + "\nSubmit the final result using structured_output; do not claim project checks passed unless the supplied evidence proves it.",
        role: { id: roleId, digest: role.compiled_digest, definition, system_prompt: definition.slice(separator + 5).trim(), tools: role.tools },
        model: { provider_id: descriptor.provider_id, model_id: descriptor.model_id, model_digest: descriptor.model_digest, api: provider.api },
        route, root_bindings: roots, artifacts, result_schema: resultSchema,
        database: { root: this.store.root, filename: basename(this.store.path), owner: this.owner }, minimum_remaining: input.minimumRemaining ?? 0 };
      const directory = join(this.store.root, "dispatches"); mkdirSync(directory, { recursive: true, mode: 0o700 });
      writeFileSync(join(directory, identity.attempt_id + ".json"), canonical({ descriptor: prepared.descriptor, context }) + "\n", { flag: "wx", mode: 0o600 });
      this.store.put("agentcfg-last-attempt-v1", digest([taskId, input.stepId]), { attempt_id: identity.attempt_id });
      return prepared;
    } catch (error) {
      await this.runtime.supervisor.call("abort_allocation", { lease_id: allocation.lease_id });
      throw error;
    }
  }
  async execute(input: ManagedStepInput, signal?: AbortSignal, onDispatch?: () => void): Promise<DelegationResult> {
    if (signal?.aborted) reject("GRANT_REVOKED", 4);
    const prepared = await this.prepare(input), id = prepared.attempt.attempt_id;
    return this.adapter.withManagedScope(input.jobId, async () => {
      let run = prepared.attempt;
      if (prepared.attempt.state === "prepared") {
        try {
          await this.adapter.preflight(id);
          if (signal?.aborted) reject("GRANT_REVOKED", 4);
        } catch (error) {
          // 这里尚未发 dispatch；完整未启动分配只能由监督者核实后撤销。
          await this.runtime.supervisor.call("abort_allocation", { lease_id: prepared.descriptor.allocation_id });
          const proof = await this.runtime.supervisor.call("reconcile", { lease_id: prepared.descriptor.allocation_id });
          if (!proof.protected && proof.termination_evidence?.verified) {
            this.store.put("agentcfg-attempt-termination-v1", id, { lease_id: prepared.descriptor.allocation_id,
              termination_confirmed: true, resources_reclaimed: true, evidence_digest: proof.termination_evidence.evidence_digest });
            this.store.put("agentcfg-attempts-v1", id, { ...prepared.attempt, lease_id: prepared.descriptor.allocation_id, state: "failed" });
          }
          throw error;
        }
        onDispatch?.();
        run = await this.adapter.dispatch(id);
      }
      const cancel = () => { void this.adapter.cancel(id, "user-stop").catch(() => {}); };
      signal?.addEventListener("abort", cancel, { once: true });
      try {
        if (signal?.aborted) cancel();
        let first = true;
        while (first || Date.now() < Date.parse(prepared.descriptor.deadline) + 10000) {
          first = false;
          const state: any = await this.adapter.inspect(id);
          if (["completed", "failed", "canceled", "timeout"].includes(state.state)) {
            const verified: any = await this.adapter.get_result(id);
            const raw = this.runtime.managedBackend.result(prepared.descriptor.allocation_id);
            const physical = await this.runtime.supervisor.call("reconcile", { lease_id: prepared.descriptor.allocation_id });
            const result = this.result(input, prepared.descriptor, verified.receipt, raw, physical);
            await this.adapter.consume(verified.receipt.receipt_id);
            return result;
          }
          if (state.state === "start_unknown") {
            await this.adapter.reconcile(prepared.descriptor.allocation_id);
          }
          await new Promise(resolve => setTimeout(resolve, 250));
        }
        await this.adapter.cancel(id, "deadline").catch(() => {});
        return { descriptorId: id, nativeRunId: run.manager_run_id, status: "unknown", terminationConfirmed: false, content: null,
          error: "TERMINATION_UNKNOWN", observations: [] };
      } finally {
        signal?.removeEventListener("abort", cancel);
        importManagedUsage(this.store, input.jobId, prepared.descriptor);
      }
    });
  }
  private result(input: ManagedStepInput, descriptor: any, receipt: any, raw: any, physical: any): DelegationResult {
    const observation = raw?.observation;
    const process = observation?.process_identity;
    const common = (read: any) => ({ toolCallId: read.tool_call_id, payloadDigest: read.payload_digest,
      readRequest: read.read_request, ...(read.delivered_request === null ? {} : { deliveredRequest: read.delivered_request }) });
    const value: any = { ready: true, descriptorId: descriptor.attempt_id, process: process ? { pid: process.pid, bootId: process.boot_id,
      startTicks: process.start_time, ...(process.namespace ? { pidNamespace: process.namespace } : {}), executionLeaseId: descriptor.allocation_id, instanceId: descriptor.instance_id } : null, producerId: "worker-" + descriptor.attempt_id,
      leaseId: descriptor.allocation_id, cwd: descriptor.cwd, provider: descriptor.provider_id, model: descriptor.model_id, thinking: descriptor.thinking,
      modelDigest: descriptor.model_digest, runtimeDigest: descriptor.runtime_digest, settled: true, activeTools: [], externalWork: [], stopReason: receipt.terminal_status,
      toolErrors: (observation?.tool_errors ?? []).map((error: any) => ({ toolCallId: error.tool_call_id, toolName: error.tool_name, error: error.code })),
      requestGate: true, requestDenials: (observation?.request_denials ?? []).map((value: any) => value.code === "BUDGET_EXHAUSTED" ? "BUDGET_DENIED" : value.code),
      lastResponse: observation?.last_response ?? null, lastError: raw?.failure_code ?? null,
      fileReads: (observation?.reads ?? []).filter((read: any) => read.kind === "file" && read.root_ref === "project").map((read: any) => ({ path: read.path, firstLine: read.first_line, lastLine: read.last_line, ...common(read) })),
      artifactReads: (observation?.reads ?? []).filter((read: any) => read.kind === "artifact").map((read: any) => ({ id: read.artifact_id, start: read.start, end: read.end, total: read.total, ...common(read) })),
      structuredOutputs: (observation?.structured_outputs ?? []).map((output: any) => ({ toolCallId: output.tool_call_id, requestOrdinal: output.request_ordinal, valueDigest: output.compatibility_digest })),
      sequence: observation?.last_request_ordinal ?? 0 };
    this.store.put("child-observations", value.producerId, value);
    this.store.put("child-grants", descriptor.attempt_id, { jobId: input.jobId, stepId: input.stepId, ...(input.parentIntentId ? { parentIntentId: input.parentIntentId } : {}),
      routeId: input.routeId ?? this.config.roles[input.role].route, provider: descriptor.provider_id, model: descriptor.model_id, active: false, stop: false });
    for (const [index, request] of (observation?.requests ?? []).entries()) this.store.append({ id: value.producerId + ":" + (index + 1),
      producer: value.producerId, seq: index + 1, scopeId: this.owner.scopeId, kind: "http_attempt", payload: request });
    if (physical.protected || !physical.termination_evidence?.verified) reject("TERMINATION_UNKNOWN", 4);
    const proof = { lease_id: descriptor.allocation_id, termination_confirmed: receipt.termination_confirmed,
      resources_reclaimed: receipt.external_work_empty, evidence_digest: physical.termination_evidence.evidence_digest };
    this.store.put("agentcfg-attempt-termination-v1", descriptor.attempt_id, proof);
    importManagedUsage(this.store, input.jobId, descriptor);
    return { descriptorId: descriptor.attempt_id, nativeRunId: receipt.manager_run_id, status: receipt.terminal_status === "completed" ? "ended" : "failed",
      nativeStatus: receipt.terminal_status, terminationConfirmed: true, content: raw?.structured_result
        ? { kind: "structured", value: raw.structured_result.value } : { kind: "text", text: raw?.response_text ?? "" },
      error: raw?.failure_code ?? (receipt.terminal_status === "completed" ? null : receipt.terminal_status), observations: [value], notSent: false };
  }
}
