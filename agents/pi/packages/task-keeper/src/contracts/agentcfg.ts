// 新协议与任务库共用一份校验；旧数据库不会自动转换为新 attempt 授权。
import { randomUUID } from "node:crypto";
import { assertDescriptor, assertEvent, canonical, clone, closed, digest, list, reject, sha, text } from "@agentcfg/pi-runtime/managed-types";
import type { Store, Owner } from "../store/database.ts";

export { assertDescriptor, assertEvent };
const taskStates = ["queued", "running", "waiting", "paused", "blocked", "completed", "failed", "canceled"];
const attemptStates = ["prepared", "starting", "queued", "running", "start_unknown", "cancel_requested", "completed", "failed", "canceled", "timeout", "unknown"];

export function assertManagedTask(value: any) {
  closed(value, ["schema_version", "task_id", "goal", "workflow", "candidate_id", "budget_scope_id", "role_bindings",
    "policy_digest", "check_ids", "required_review", "second_view", "state"]);
  if (value.schema_version !== 1 || !["inspect", "fix"].includes(value.workflow) || !taskStates.includes(value.state)
      || ![value.task_id, value.goal, value.candidate_id, value.budget_scope_id].every(text)
      || !sha(value.policy_digest) || !list(value.check_ids) || typeof value.required_review !== "boolean") reject();
  closed(value.role_bindings, ["reader", "writer", "reviewer"]);
  if (!Object.values(value.role_bindings).every(text)) reject();
  if (value.second_view !== null) {
    closed(value.second_view, ["model_role", "max_attempts", "required"]);
    if (!text(value.second_view.model_role) || !Number.isSafeInteger(value.second_view.max_attempts)
        || value.second_view.max_attempts < 1 || typeof value.second_view.required !== "boolean") reject();
  }
  return value;
}
export function assertAttempt(value: any) {
  closed(value, ["schema_version", "attempt_id", "task_id", "step_id", "continuation_of", "idempotency_key", "descriptor_digest",
    "manager_run_id", "lease_id", "candidate_snapshot_digest", "state", "result_receipt_id"]);
  if (value.schema_version !== 1 || ![value.attempt_id, value.task_id, value.step_id, value.idempotency_key].every(text)
      || !sha(value.descriptor_digest) || !sha(value.candidate_snapshot_digest) || !attemptStates.includes(value.state)
      || [value.continuation_of, value.manager_run_id, value.lease_id, value.result_receipt_id].some(item => item !== null && !text(item))) reject();
  return value;
}

export class AttemptJournal {
  private store: Store;
  private owner: Owner;
  constructor(store: Store, owner: Owner) { this.store = store; this.owner = owner; }
  createTask(task: any) {
    assertManagedTask(task);
    if (task.state !== "queued") reject();
    return this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      const existing = this.store.get("agentcfg-tasks-v1", task.task_id);
      if (existing && canonical(existing) !== canonical(task)) reject("TASK_IDENTITY_CONFLICT", 4);
      if (!existing) this.store.put("agentcfg-tasks-v1", task.task_id, task);
      return clone(task);
    });
  }
  prepareIdentity(input: any) {
    closed(input, ["task_id", "step_id", "continuation_of", "idempotency_key"]);
    if (![input.task_id, input.step_id, input.idempotency_key].every(text)
        || input.continuation_of !== null && !text(input.continuation_of)) reject();
    return this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      if (!this.store.get("agentcfg-tasks-v1", input.task_id)) reject("TASK_NOT_FOUND", 4);
      const key = digest({ task_id: input.task_id, idempotency_key: input.idempotency_key });
      const previous = this.store.get<any>("agentcfg-attempt-intents-v1", key);
      if (previous) {
        if (previous.identity_digest !== digest(input)) reject("DISPATCH_CONFLICT", 4);
        return clone(previous);
      }
      const value = { schema_version: 1, attempt_id: "attempt-" + randomUUID(), ...clone(input), identity_digest: digest(input) };
      this.store.put("agentcfg-attempt-intents-v1", key, value);
      return clone(value);
    });
  }
  allocate(input: any) {
    closed(input, ["task_id", "step_id", "continuation_of", "idempotency_key", "descriptor"]);
    if (![input.task_id, input.step_id, input.idempotency_key].every(text)
        || input.continuation_of !== null && !text(input.continuation_of)) reject();
    return this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      const task = this.store.get<any>("agentcfg-tasks-v1", input.task_id);
      if (!task) reject("TASK_NOT_FOUND", 4);
      assertManagedTask(task);
      const index = digest({ task_id: input.task_id, idempotency_key: input.idempotency_key });
      const previous = this.store.get<any>("agentcfg-attempt-keys-v1", index);
      if (previous) {
        if (previous.input_digest !== digest(input)) reject("DISPATCH_CONFLICT", 4);
        return this.read(previous.attempt_id);
      }
      // 新 attempt 只在显式 resume 记录了旧物理 lease 终止证据之后创建。
      if (input.continuation_of !== null) {
        const previousAttempt = this.read(input.continuation_of).attempt;
        const proof = this.store.get<any>("agentcfg-attempt-termination-v1", input.continuation_of);
        if (previousAttempt.task_id !== task.task_id || !proof || proof.lease_id !== previousAttempt.lease_id
            || proof.termination_confirmed !== true || proof.resources_reclaimed !== true || !sha(proof.evidence_digest)) reject("TERMINATION_UNKNOWN", 4);
      }
      const intent = this.store.get<any>("agentcfg-attempt-intents-v1", index);
      const identity = { task_id: input.task_id, step_id: input.step_id, continuation_of: input.continuation_of, idempotency_key: input.idempotency_key };
      if (intent && intent.identity_digest !== digest(identity)) reject("DISPATCH_CONFLICT", 4);
      const attempt_id = intent?.attempt_id ?? "attempt-" + randomUUID();
      const descriptor = { ...clone(input.descriptor), attempt_id, task_id: task.task_id, step_id: input.step_id,
        continuation_of: input.continuation_of, budget_scope_id: task.budget_scope_id };
      // 身份字段不能被调用方覆盖或借 undefined 静默丢掉。
      if (["attempt_id", "task_id", "step_id", "continuation_of", "budget_scope_id"].some(key => Object.hasOwn(input.descriptor, key))) reject();
      assertDescriptor(descriptor);
      if (descriptor.policy_digest !== task.policy_digest || descriptor.candidate_id !== task.candidate_id) reject("TASK_IDENTITY_CONFLICT", 4);
      const attempt = { schema_version: 1, attempt_id, task_id: task.task_id, step_id: input.step_id,
        continuation_of: input.continuation_of, idempotency_key: input.idempotency_key, descriptor_digest: digest(descriptor),
        manager_run_id: null, lease_id: null, candidate_snapshot_digest: descriptor.snapshot_digest, state: "prepared", result_receipt_id: null };
      assertAttempt(attempt);
      this.store.put("agentcfg-attempts-v1", attempt_id, attempt);
      this.store.put("agentcfg-descriptors-v1", attempt_id, descriptor);
      this.store.put("agentcfg-attempt-keys-v1", index, { input_digest: digest(input), attempt_id });
      return { attempt: clone(attempt), descriptor: clone(descriptor) };
    });
  }
  read(attemptId: string) {
    this.store.assertOwner(this.owner);
    const attempt = this.store.get<any>("agentcfg-attempts-v1", attemptId);
    const descriptor = this.store.get<any>("agentcfg-descriptors-v1", attemptId);
    if (!attempt || !descriptor) reject("ATTEMPT_NOT_FOUND", 4);
    assertAttempt(attempt); assertDescriptor(descriptor);
    if (digest(descriptor) !== attempt.descriptor_digest || descriptor.attempt_id !== attempt.attempt_id) reject("ATTEMPT_IDENTITY_CONFLICT", 4);
    return { attempt, descriptor };
  }
  acknowledge(attemptId: string, response: any) {
    closed(response, ["attempt_id", "manager_run_id", "lease_id", "state"]);
    return this.store.transaction(() => {
      const { attempt } = this.read(attemptId);
      if (response.attempt_id !== attemptId || !text(response.manager_run_id)
          || !["queued", "running", "start_unknown"].includes(response.state)
          || response.lease_id !== null && !text(response.lease_id)
          || response.state !== "start_unknown" && response.lease_id === null
          || attempt.manager_run_id !== null && attempt.manager_run_id !== response.manager_run_id
          || attempt.lease_id !== null && attempt.lease_id !== response.lease_id) reject("DISPATCH_IDENTITY", 4);
      this.store.put("agentcfg-attempts-v1", attemptId, { ...attempt, ...response });
    });
  }
}
