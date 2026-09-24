import { ContractError, finiteInteger, identifier, digest } from "../contracts/primitives.ts";
import { validateTaskSpec, type TaskSpec } from "../contracts/task.ts";
import { MAX_BASE_PRIORITY, selectReadyCandidate, type ReadyCandidate } from "./fairness.ts";
import { Store, type Owner, type Intent } from "../store/database.ts";

export interface ResourceDemand { id: string; capacity: number; units: number }
export interface PlanStep {
  id: string; dependencies: string[]; allowedSkippedDependencies: string[];
  role: string; kind: "read" | "write" | "verify" | "review"; optional: boolean; resources: ResourceDemand[];
}
export interface QueuedStep extends PlanStep {
  status: "pending" | "running" | "passed" | "failed" | "skipped" | "unknown";
  readyAt: number | null; intentId: string | null; finishedAt: number | null;
}
export interface QueuedJob {
  spec: TaskSpec; initialSpec: TaskSpec; priority: number; createdAt: number; paused: boolean; cancelled: boolean;
  dispatched: number; steps: QueuedStep[]; semanticReplans?: number;
}

/** Only accepted evidence or an explicitly allowed optional skip satisfies an edge. */
export function dependenciesSatisfied(steps: readonly Pick<QueuedStep, "id" | "status" | "optional">[],
  step: Pick<PlanStep, "dependencies" | "allowedSkippedDependencies">): boolean {
  return step.dependencies.every(id => {
    const upstream = steps.find(candidate => candidate.id === id);
    return upstream?.status === "passed" || (upstream?.status === "skipped" && upstream.optional && step.allowedSkippedDependencies.includes(id));
  });
}

export function validatePlan(steps: PlanStep[], maxSteps: number): void {
  if (!steps.length || steps.length > maxSteps) throw new ContractError("STEP_LIMIT");
  const ids = new Set<string>();
  for (const step of steps) {
    identifier(step.id); identifier(step.role);
    if (ids.has(step.id)) throw new ContractError("DUPLICATE_STEP");
    ids.add(step.id);
    if (!["read", "write", "verify", "review"].includes(step.kind)) throw new ContractError("INVALID_STEP_KIND");
    if (typeof step.optional !== "boolean") throw new ContractError("INVALID_OPTIONAL_STEP");
    for (const demand of step.resources) { identifier(demand.id); finiteInteger(demand.capacity); finiteInteger(demand.units, 1); }
  }
  for (const step of steps) {
    if (step.dependencies.some((id) => !ids.has(id) || id === step.id)
      || new Set(step.dependencies).size !== step.dependencies.length
      || step.allowedSkippedDependencies.some((id) => !step.dependencies.includes(id))) throw new ContractError("INVALID_DEPENDENCY");
    if (step.allowedSkippedDependencies.some((id) => !steps.find((item) => item.id === id)?.optional)) throw new ContractError("REQUIRED_DEPENDENCY_CANNOT_SKIP");
  }
  const resolved = new Set<string>();
  while (resolved.size < steps.length) {
    const ready = steps.filter((step) => !resolved.has(step.id) && step.dependencies.every((id) => resolved.has(id)));
    if (!ready.length) throw new ContractError("DEPENDENCY_CYCLE");
    for (const step of ready) resolved.add(step.id);
  }
}

/** One parent's queue; cross-parent capacity is enforced by Store's transactions. */
export class Scheduler {
  private store: Store;
  private owner: Owner;
  private agingMs: number;
  private scopeStepLimit: number;
  constructor(store: Store, owner: Owner, agingMs = 60_000, scopeStepLimit = Number.MAX_SAFE_INTEGER) {
    finiteInteger(agingMs, 1, 2147483647); this.store = store; this.owner = owner; this.agingMs = agingMs;
    finiteInteger(scopeStepLimit); this.scopeStepLimit = scopeStepLimit;
  }
  scopeDispatched(): number {
    return this.store.list<QueuedJob>("jobs").filter(row => row.value.spec.workScope === this.owner.scopeId)
      .reduce((sum, row) => { finiteInteger(row.value.dispatched); const total = sum + row.value.dispatched; finiteInteger(total); return total; }, 0);
  }
  submit(input: TaskSpec, steps: PlanStep[], priority: number, now: number): QueuedJob {
    const spec = validateTaskSpec(input); finiteInteger(priority, 0, MAX_BASE_PRIORITY); finiteInteger(now);
    if (spec.workScope !== this.owner.scopeId) throw new ContractError("WORK_SCOPE_ESCALATION");
    validatePlan(steps, spec.maxSteps);
    const job: QueuedJob = { spec, initialSpec: structuredClone(spec), priority, createdAt: now, paused: false, cancelled: false, dispatched: 0,
      steps: steps.map((step) => ({ ...structuredClone(step), status: "pending", readyAt: null, intentId: null, finishedAt: null })) };
    this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      if (this.scopeDispatched() >= this.scopeStepLimit) throw new ContractError("WORK_SCOPE_STEP_LIMIT");
      if (this.store.get("jobs", spec.id)) throw new ContractError("DUPLICATE_JOB");
      this.store.put("jobs", spec.id, job);
    });
    return structuredClone(job);
  }
  job(id: string): QueuedJob {
    const job = this.store.get<QueuedJob>("jobs", id);
    if (!job || job.spec.workScope !== this.owner.scopeId) throw new ContractError("UNKNOWN_JOB");
    return job;
  }
  private dependenciesPassed(job: QueuedJob, step: QueuedStep): boolean {
    return dependenciesSatisfied(job.steps, step);
  }
  private available(resources: ResourceDemand[]): boolean {
    const claims = this.store.claims();
    return resources.every((demand) => {
      const row = this.store.db.prepare("SELECT capacity FROM resources WHERE id=?").get(demand.id);
      const cap = Math.min(demand.capacity, row ? Number(row.capacity) : demand.capacity);
      return claims.filter((claim) => claim.resource_id === demand.id).reduce((sum, claim) => sum + Number(claim.units), 0) + demand.units <= cap;
    });
  }
  next(now: number, additionalResources?: (spec: TaskSpec, step: PlanStep) => PlanStep["resources"], eligible?: (spec: TaskSpec, step: PlanStep) => boolean): { jobId: string; stepId: string; effectivePriority: number; readyAt: number; reason: string } | null {
    finiteInteger(now);
    return this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      if (this.scopeDispatched() >= this.scopeStepLimit) return null;
      const candidates: ReadyCandidate[] = [];
      for (const { value: job } of this.store.list<QueuedJob>("jobs")) {
        if (job.spec.workScope !== this.owner.scopeId || job.paused || job.cancelled) continue;
        for (const step of job.steps) {
          if (step.status !== "pending" || eligible?.(job.spec, step) === false) continue;
          const ready = this.dependenciesPassed(job, step) && job.dispatched < job.spec.maxSteps;
          if (!ready) { step.readyAt = null; continue; }
          step.readyAt ??= now;
          // Ordinary slot contention must not erase age on every bounded worker turn.
          if (!this.available([...step.resources, ...(additionalResources?.(job.spec, step) ?? [])])) continue;
          candidates.push({ jobId: job.spec.id, stepId: step.id, readyAt: step.readyAt,
            priority: job.priority });
        }
        this.store.put("jobs", job.spec.id, job);
      }
      return selectReadyCandidate(candidates, now, this.agingMs);
    });
  }
  dispatch(jobId: string, stepId: string, expectedSnapshot: string, extraResources: ResourceDemand[] = [], check?: (intentId: string) => void): Intent {
    const job = this.job(jobId), step = job.steps.find((s) => s.id === stepId);
    if (!step) throw new ContractError("UNKNOWN_STEP");
    const id = `step-${digest([jobId, stepId, job.dispatched])}`;
    return this.store.prepare(this.owner, id, step.kind, { jobId, stepId, snapshot: expectedSnapshot }, [...step.resources, ...extraResources], () => {
      if (this.scopeDispatched() >= this.scopeStepLimit) throw new ContractError("WORK_SCOPE_STEP_LIMIT");
      const current = this.job(jobId), actual = current.steps.find((s) => s.id === stepId)!;
      if (current.paused || current.cancelled || actual.status !== "pending" || !this.dependenciesPassed(current, actual)
        || current.spec.snapshot !== expectedSnapshot || current.dispatched >= current.spec.maxSteps) throw new ContractError("STEP_NOT_READY");
      check?.(id);
      current.dispatched++; actual.status = "running"; actual.intentId = id; actual.readyAt = null;
      this.store.put("jobs", jobId, current);
    });
  }
  finish(jobId: string, stepId: string, evidence: { terminated: boolean; passed: boolean; artifactId: string | null; notSent?: boolean; nextSnapshot?: string }, now: number, commit?:()=>void): void {
    this.store.assertOwner(this.owner);
    const job = this.job(jobId), step = job.steps.find((s) => s.id === stepId);
    if (!step?.intentId || !["running", "unknown"].includes(step.status)) throw new ContractError("STEP_NOT_RUNNING");
    if (evidence.passed) {
      const artifact = evidence.artifactId ? this.store.get<{ jobId: string; snapshot: string; source: string }>("artifacts", evidence.artifactId) : null;
      if (!evidence.terminated || !artifact || artifact.jobId !== jobId || artifact.snapshot !== job.spec.snapshot || artifact.source === "claim") {
        throw new ContractError("STEP_EVIDENCE_MISSING");
      }
    }
    if (evidence.nextSnapshot) {
      identifier(evidence.nextSnapshot);
      if (!evidence.terminated || job.steps.some((item) => item.id !== stepId && ["running", "unknown"].includes(item.status))) throw new ContractError("SNAPSHOT_HAS_ACTIVE_EXECUTION");
    }
    // Evidence can settle late after pause/cancel; it cannot authorize another step.
    this.store.settle(step.intentId, evidence.notSent ? "not_sent" : evidence.terminated ? "terminated" : "unknown", () => {
      this.store.assertOwner(this.owner);
      const current = this.job(jobId), actual = current.steps.find((s) => s.id === stepId)!;
      actual.status = !evidence.terminated ? "unknown" : evidence.passed ? "passed" : "failed";
      if (evidence.nextSnapshot) current.spec.snapshot = evidence.nextSnapshot;
      actual.finishedAt = now; this.store.put("jobs", jobId, current);commit?.();
    });
  }
  pause(jobId: string): void { this.changeControl(jobId, true, false); }
  cancel(jobId: string): void { this.changeControl(jobId, true, true); }
  resume(jobId: string): void {
    if (this.job(jobId).cancelled) throw new ContractError("CANCELLED_JOB");
    this.changeControl(jobId, false, false);
  }
  reconcileStopped(jobId: string, stepId: string, notSent: boolean): void {
    this.store.assertOwner(this.owner);
    const job = this.job(jobId), step = job.steps.find((item) => item.id === stepId);
    if (!step?.intentId || !["running", "unknown"].includes(step.status)) throw new ContractError("STEP_NOT_RECONCILABLE");
    this.store.settle(step.intentId, notSent ? "not_sent" : "terminated", () => {
      this.store.assertOwner(this.owner);
      const current = this.job(jobId), actual = current.steps.find((item) => item.id === stepId)!;
      actual.status = "failed"; actual.finishedAt = Date.now(); this.store.put("jobs", jobId, current);
    });
  }
  approveAcceptanceRevision(jobId: string): void {
    this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      const job = this.job(jobId);
      if (job.cancelled || !job.paused || job.steps.some((step) => ["running", "unknown"].includes(step.status))) throw new ContractError("REVISION_NOT_SAFE");
      this.store.put("spec-history", `${jobId}:${job.spec.version}`, job.spec); job.spec.version++;
      for (const step of job.steps) if ((step.kind === "verify" && !step.id.startsWith("baseline:")) || step.kind === "review") {
        step.status = "pending"; step.readyAt = null; step.intentId = null; step.finishedAt = null;
      }
      this.store.put("jobs", jobId, job);
    });
  }
  updateSnapshot(jobId: string, snapshot: string): void {
    identifier(snapshot);
    this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      const job = this.job(jobId);
      if (job.steps.some((step) => step.status === "running" || step.status === "unknown")) throw new ContractError("SNAPSHOT_HAS_ACTIVE_EXECUTION");
      job.spec.snapshot = snapshot;
      this.store.put("jobs", jobId, job);
    });
  }
  retryFrom(jobId: string, stepId: string, diagnose = false, commit?: () => void): void {
    this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      const job = this.job(jobId);
      if (job.cancelled || job.dispatched >= job.spec.maxSteps) throw new ContractError("STEP_LIMIT_OR_CANCELLED");
      if (job.steps.some((step) => step.status === "running" || step.status === "unknown")) throw new ContractError("EXECUTION_NOT_RECONCILED");
      if (diagnose) {
        const used = job.semanticReplans ?? 0; finiteInteger(used);
        if (stepId !== "implement" || job.spec.workflow !== "fix" || used >= (job.spec.maxSemanticReplans ?? 0)) throw new ContractError("REPLAN_LIMIT_OR_TEMPLATE_DENIED");
        const implementation = job.steps.find(step => step.id === "implement");
        if (!implementation || implementation.kind !== "write") throw new ContractError("REPLAN_TEMPLATE_REQUIRES_WRITER");
        const previous = job.steps.map(step => ({ id: step.id, dependencies: step.dependencies }));
        const diagnostic: QueuedStep = { id: `replan:diagnose:${used + 1}`, role: "scout", kind: "read", optional: false,
          dependencies: [...implementation.dependencies], allowedSkippedDependencies: [...implementation.allowedSkippedDependencies],
          resources: implementation.resources.filter(resource => resource.id === "model-dispatch-slots"),
          status: "pending", readyAt: null, intentId: null, finishedAt: null };
        implementation.dependencies = [diagnostic.id]; implementation.allowedSkippedDependencies = [];
        job.steps.splice(job.steps.indexOf(implementation), 0, diagnostic); job.semanticReplans = used + 1;
        validatePlan(job.steps, job.spec.maxSteps);
        this.store.put("plan-revisions", `${jobId}:${used + 1}`, { jobId, count: used + 1, template: "diagnose-before-repair", previous,
          next: job.steps.map(step => ({id: step.id, dependencies: step.dependencies})), rootSpecDigest: digest(job.spec) });
      }
      const reset = new Set([stepId]);
      for (let i = 0; i < job.steps.length; i++) for (const step of job.steps) if (step.dependencies.some((id) => reset.has(id))) reset.add(step.id);
      for (const step of job.steps) if (reset.has(step.id)) {
        step.status = "pending"; step.readyAt = null; step.finishedAt = null; step.intentId = null;
      }
      this.store.put("jobs", jobId, job); commit?.();
    });
  }
  skipOptional(jobId: string, stepId: string, reason: string, now: number): void {
    if (!reason.trim()) throw new ContractError("SKIP_REASON_REQUIRED");
    this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      const job = this.job(jobId), step = job.steps.find((item) => item.id === stepId);
      if (!step?.optional || !["pending", "failed"].includes(step.status)
        || (step.intentId && !["settled", "not_sent"].includes(this.store.intent(step.intentId)?.status ?? "unknown"))) throw new ContractError("CANNOT_SKIP_REQUIRED_OR_ACTIVE_STEP");
      step.status = "skipped"; step.finishedAt = now;
      this.store.put("skip-reasons", `${jobId}:${stepId}`, { reason, at: now });
      this.store.put("jobs", jobId, job);
    });
  }
  private changeControl(jobId: string, paused: boolean, cancelled: boolean): void {
    this.store.transaction(() => {
      this.store.assertOwner(this.owner);
      const job = this.job(jobId); job.paused = paused; job.cancelled ||= cancelled;
      for (const step of job.steps) if (step.status === "pending") step.readyAt = null;
      this.store.put("jobs", jobId, job);
    });
  }
}


export interface OneShotSchedule {
  schema_version: 1; schedule_id: string; task_id: string; budget_scope_id: string;
  due_at: number; deadline: number | null; admitted_at: number | null; dispatch_id: string | null;
  state: "scheduled" | "admitted" | "executed" | "canceled" | "expired" | "paused-missed";
}

// 与任务准备共用 SQLite 事务；唯一计时来源仍是 TaskService，退出后没有后台唤醒。
export class TaskSchedules {
  private store: Store;
  private owner: Owner;
  constructor(store: Store, owner: Owner) { this.store = store; this.owner = owner; }
  read(taskId: string): OneShotSchedule | null { return this.store.get("one-shot-schedules-v1", taskId); }
  private save(record: OneShotSchedule): void { this.store.assertOwner(this.owner); this.store.put("one-shot-schedules-v1", record.task_id, record); }
  create(taskId: string, dueAt: number, deadline: number | null): OneShotSchedule {
    finiteInteger(dueAt); if (deadline !== null) { finiteInteger(deadline); if (deadline <= dueAt) throw new ContractError("SCHEDULE_DEADLINE_EXHAUSTED"); }
    if (this.read(taskId)) throw new ContractError("DUPLICATE_SCHEDULE");
    const record: OneShotSchedule = { schema_version: 1, schedule_id: "schedule-" + taskId, task_id: taskId, budget_scope_id: "budget-" + taskId,
      due_at: dueAt, deadline, admitted_at: null, dispatch_id: null, state: "scheduled" };
    this.save(record); return record;
  }
  recover(taskId: string, now: number): OneShotSchedule {
    const record = this.required(taskId);
    if (record.state === "scheduled") {
      if (record.deadline !== null && now >= record.deadline) record.state = "expired";
      else if (now >= record.due_at) record.state = "paused-missed";
      this.save(record);
    }
    return record;
  }
  private required(taskId: string): OneShotSchedule {
    const record = this.read(taskId); if (!record) throw new ContractError("SCHEDULE_NOT_FOUND"); return record;
  }
  admit(taskId: string, now: number): OneShotSchedule {
    const record = this.required(taskId);
    if (record.state !== "scheduled" || now < record.due_at || record.deadline !== null && now >= record.deadline)
      throw new ContractError("SCHEDULE_START_NOT_ELIGIBLE");
    record.state = "admitted"; record.admitted_at = now; this.save(record); return record;
  }
  executed(taskId: string, dispatchId: string): void {
    const record = this.required(taskId);
    if (record.state !== "admitted" || record.admitted_at === null) throw new ContractError("SCHEDULE_NOT_ADMITTED");
    record.state = "executed"; record.dispatch_id = dispatchId; this.save(record);
  }
  pause(taskId: string, cancel = false): void {
    const record = this.required(taskId);
    if (["scheduled", "paused-missed"].includes(record.state)) { record.state = cancel ? "canceled" : "paused-missed"; this.save(record); }
  }
  resume(taskId: string, dueAt: number, now: number): void {
    const record = this.required(taskId);
    if (!["paused-missed", "scheduled"].includes(record.state) || dueAt < now || record.deadline !== null && dueAt >= record.deadline)
      throw new ContractError("SCHEDULE_RESUME_INVALID");
    record.state = "scheduled"; record.due_at = dueAt; this.save(record);
  }
}
