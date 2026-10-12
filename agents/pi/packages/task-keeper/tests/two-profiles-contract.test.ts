import { test, assert } from "./recorded-test.ts";
import { fixedWorkflowPlan } from "../src/orchestration/workflow-plan.ts";
import { configured } from "./fixtures/config.ts";
import { mkdtempSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import childProcess from "node:child_process";
import { syncBuiltinESMExports } from "node:module";
import { TaskService } from "../src/orchestration/service.ts";
import { Store } from "../src/store/database.ts";
import { Scheduler } from "../src/orchestration/scheduler.ts";
import { Artifacts } from "../src/store/artifacts.ts";
import type { TestContext } from "node:test";
import type { ManagedJob } from "../src/orchestration/service.ts";

function planFixture() {
  const config = configured();
  for (const id of ["build", "focused-tests"]) config.verificationBindings[id] = {
    executable: "mock-check", args: [], environment: {}, timeoutMs: 1000,
    kind: id === "build" ? "build" : "tests", parser: "json", minimumTests: 1 };
  return { config, input: { id: "job", workScope: "scope", goal: "Bound repairs", workflow: "fix" as const,
    policyDigest: "policy", snapshot: "tree", workspaceLock: "workspace" } };
}

// GuardedMock的公开store/scheduler端口；git只返回明确的本地替身，没有宿主/delegate进程。
function completedMockState(t: TestContext, attemptLimit = 20) {
  const root = mkdtempSync(join(tmpdir(), "bounded-repair-")), cwd = join(root, "workspace"); mkdirSync(cwd);
  const mock = t.mock.method(childProcess, "execFileSync", (_program: unknown, args: string[]) => {
    if (args.includes("--git-common-dir")) return Buffer.from(join(cwd, ".git") + "\n");
    if (args.includes("--show-toplevel")) return Buffer.from(cwd + "\n");
    if (args.includes("--verify")) return Buffer.from("a".repeat(40) + "\n");
    return Buffer.from("");
  }); syncBuiltinESMExports();
  const store = new Store(join(root, "state")), config = configured(); config.features.managedWorkflows = true;
  config.limits.semanticAttemptsPerImplementationTask = attemptLimit; config.limits.semanticReplansPerTask = 20;
  config.limits.semanticAttemptsPerWorkScope = 100; config.features.semanticReplanning = true;
  for (const role of ["worker", "reviewer", "scout"]) {
    config.roles[role] = { route: "primary", profileRef: role };
    config.executionProfiles[role] = { tools: [], requiredCapabilities: [], timeoutMs: 1000, maxModelTurns: 1, toolTimeoutMs: 1000, thinking: "off" };
  }
  for (const id of ["build", "focused-tests"]) config.verificationBindings[id] = {
    executable: "mock-check", args: [], environment: {}, timeoutMs: 1000,
    kind: id === "build" ? "build" : "tests", parser: "json", minimumTests: 1, inputs: [] };
  const ctx = { cwd, modelRegistry: { find: () => undefined }, sessionManager: { getBranch: () => [], getHeader: () => null,
    getSessionId: () => "session", getSessionFile: () => null } };
  const service = new TaskService({ appendEntry() {} } as never, store, config, ctx as never);
  const internal = service as unknown as { wake(): void; finalize(id: string): void }; internal.wake = () => {};
  t.after(async () => { await service.dispose(); store.close(); mock.mock.restore(); syncBuiltinESMExports(); });
  const job = service.submit("fix", "bounded repair fixture"), owner = store.owner(job.workScope)!;
  const queue = new Scheduler(store, owner), artifacts = new Artifacts(store);
  const ids = ["implement", "build", "focused-tests", "independent-review"];
  queue.submit({ id: job.id, workScope: job.workScope, version: 1, objective: job.goal, workflow: "fix",
    required: ids.slice(1), optional: [], allowPartial: false, policyDigest: job.policyDigest, snapshot: "tree", maxSteps: 64, maxSemanticAttempts: 20,
    maxSemanticReplans: 20 }, ids.map(id => ({ id, kind: id === "implement" ? "write" : id === "independent-review" ? "review" : "verify",
      role: id === "implement" ? "worker" : id === "independent-review" ? "reviewer" : "verify", dependencies: [],
      allowedSkippedDependencies: [], optional: false, resources: [] })), 0, 0);
  job.status = "RUNNING"; job.reason = "workflow_ready"; job.cwd = cwd; job.snapshot = "tree";
  for (const id of ids) {
    const intent = queue.dispatch(job.id, id, "tree"); store.markSent(owner, intent.id);
    if (id === "implement") {
      store.reserveRequest(owner, intent.id, "mock-request-initial", [{ id: "mock-write-budget", ceiling: 100 }]);
      store.settleRequest("mock-request-initial", "sent");
    }
    const artifact = artifacts.pin(job.id, "tree", JSON.stringify({ checkId: id, mock: true }), "verifier");
    queue.finish(job.id, id, { terminated: true, passed: true, artifactId: artifact.id }, 1);
  }
  store.put("managed-jobs", job.id, job);
  return { store, config, service, queue, owner, jobId: job.id, artifacts, finalize: () => internal.finalize(job.id) };
}

test("[U T067 T070] fixed inspect/fix never expand the three-attempt/two-replan ceilings", () => {
  const { config, input } = planFixture(); config.features.semanticReplanning = true;
  for (const limit of [1, 2, 3, 20]) {
    config.limits.semanticAttemptsPerImplementationTask = limit; config.limits.semanticReplansPerTask = 20;
    for (const workflow of ["fix", "inspect"] as const) {
      const { spec, steps } = fixedWorkflowPlan(config, { ...input, workflow });
      assert.equal(spec.maxSemanticAttempts, Math.min(limit, 3));
      assert.equal(spec.maxSemanticReplans, 2);
      assert.equal(steps.filter(step => step.kind === "write").length, workflow === "fix" ? 1 : 0);
      assert.ok(steps.some(step => step.kind === "review" && !step.optional));
    }
  }
  config.limits.semanticAttemptsPerImplementationTask = 0;
  assert.throws(() => fixedWorkflowPlan(config, input), { code: "SEMANTIC_ATTEMPTS_DISABLED" });
  assert.throws(() => fixedWorkflowPlan(config, { ...input, workflow: "inspect" }), { code: "SEMANTIC_ATTEMPTS_DISABLED" });
});

test("[S T067 T070] real service/store keeps initial plus two repairs and blocks a fourth under config20", t => {
  const f = completedMockState(t);
  // Mock fixture has dispatched and physically settled the initial implementation.
  const initial = f.queue.job(f.jobId); initial.spec.maxSemanticAttempts = 20;
  initial.spec.maxSemanticReplans = 20; initial.spec.maxSteps = 64;
  f.store.put("jobs", f.jobId, initial);
  const internal = f.service as unknown as { block(job: ManagedJob, reason: string, allowRepair: boolean): void };
  let implementationDispatches = 1;
  for (let attempt = 1; attempt <= 3; attempt++) {
    const job = f.service.get(f.jobId);
    job.failures.push({ id: "failed-attempt-" + attempt, layer: "verification", code: "CHECK:focused-tests",
      message: "mock implementation still fails", attemptId: "attempt-" + attempt, required: true, resolvedBy: null });
    job.checks = job.checks.filter(check => check.checkId !== "focused-tests");
    f.store.put("managed-jobs", f.jobId, job);
    internal.block(job, "required_step_failed", true); f.finalize();
    if (attempt < 3) {
      assert.equal(f.service.get(f.jobId).semanticAttempts, attempt + 1);
      const plan = f.queue.job(f.jobId);
      for (const step of plan.steps.filter(step => step.status === "pending")) {
        const intent = f.queue.dispatch(f.jobId, step.id, "tree"); f.store.markSent(f.owner, intent.id);
        if (step.id === "implement") {
          implementationDispatches++;
          const request = "mock-request-repair-" + attempt;
          f.store.reserveRequest(f.owner, intent.id, request, [{ id: "mock-write-budget", ceiling: 100 }]);
          f.store.settleRequest(request, "sent");
        }
        const artifact = f.artifacts.pin(f.jobId, "tree", JSON.stringify({ checkId: step.id, mock: true }), "verifier");
        f.queue.finish(f.jobId, step.id, { terminated: true, passed: true, artifactId: artifact.id }, attempt + 1);
      }
    }
  }
  const final = f.service.get(f.jobId);
  assert.equal(implementationDispatches, 3);
  assert.equal(final.semanticAttempts, 3);
  assert.equal(Number(f.store.bucket("mock-write-budget")!.used), 3);
  assert.equal(Number(f.store.bucket("mock-write-budget")!.reserved), 0);
  assert.equal(final.status, "BLOCKED");
  assert.ok(final.failures.some(failure => failure.id === "failed-attempt-3" && !failure.resolvedBy));
  assert.notEqual(final.receipt?.status, "COMPLETED");
  assert.equal(f.store.list("managed-jobs").length, 1);
  assert.equal(f.queue.next(Date.now()), null);
  assert.ok(f.queue.job(f.jobId).semanticReplans! <= 2);
});

for (const limit of [1, 2]) test(`[S T070] stricter configured attempt limit ${limit} remains authoritative`, t => {
  const f = completedMockState(t, limit);
  const internal = f.service as unknown as { block(job: ManagedJob, reason: string, allowRepair: boolean): void };
  for (let attempt = 1; attempt <= limit; attempt++) {
    const job = f.service.get(f.jobId);
    job.failures.push({ id: "failure-" + attempt, layer: "verification", code: "CHECK:focused-tests", message: "mock failure",
      attemptId: "attempt-" + attempt, required: true, resolvedBy: null });
    internal.block(job, "required_step_failed", true); f.finalize();
    if (attempt < limit) {
      for (const step of f.queue.job(f.jobId).steps.filter(step => step.status === "pending")) {
        const intent = f.queue.dispatch(f.jobId, step.id, "tree"); f.store.markSent(f.owner, intent.id);
        const artifact = f.artifacts.pin(f.jobId, "tree", "mock completed step", "verifier");
        f.queue.finish(f.jobId, step.id, { terminated: true, passed: true, artifactId: artifact.id }, attempt + 1);
      }
    }
  }
  assert.equal(f.service.get(f.jobId).semanticAttempts, limit);
  assert.equal(f.service.get(f.jobId).status, "BLOCKED");
  assert.equal(f.queue.next(Date.now()), null);
});

test("[S T070] second-opinion revision at three attempts cannot create a separate repair allowance", t => {
  const f = completedMockState(t), job = f.service.get(f.jobId);
  job.semanticAttempts = 3; job.reason = "critic_revision_pending"; job.status = "RUNNING";
  job.failures.push({ id: "critic-finding", layer: "verification", code: "CRITIC", message: "mock supported finding",
    attemptId: "critic-attempt", required: true, resolvedBy: null });
  f.store.put("managed-jobs", f.jobId, job); const dispatched = f.queue.job(f.jobId).dispatched;
  f.finalize();
  assert.equal(f.service.get(f.jobId).status, "BLOCKED");
  assert.equal(f.service.get(f.jobId).semanticAttempts, 3);
  assert.equal(f.queue.job(f.jobId).dispatched, dispatched);
  assert.equal(f.queue.next(Date.now()), null);
  assert.equal(f.service.get(f.jobId).failures[0].resolvedBy, null);
});
