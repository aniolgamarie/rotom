import { test, assert, evidence } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { completedState } from "./fixtures/service-state.ts";
import { barrier } from "./helpers.ts";
import type { Intent } from "../src/store/database.ts";

test("[S RTB-018 T82] dispatcher skips a critic at the reserve boundary and keeps required review mandatory", async t => {
  for (const ceiling of [6, 7]) {
    const f = completedState(t, false, false, ["direct", "critique"], config => {
      config.roles.critic = { route: "primary", profileRef: "reviewer" }; config.routes.primary.protected = true;
      config.budget.protectedAttemptsPerWorkScope = ceiling; config.budget.minimumRequiredStageAttemptReserves["independent-review"] = 4;
    });
    const job = f.service.get(f.jobId), plan = f.queue.job(f.jobId);
    plan.steps.push({ id: "optional-critique", role: "critic", kind: "review", optional: true, dependencies: ["build", "focused-tests"], allowedSkippedDependencies: [],
      resources: [], status: "pending", intentId: null, readyAt: null, finishedAt: null });
    const review = plan.steps.find(step => step.id === "independent-review")!; review.status = "pending"; review.intentId = null;
    review.dependencies = ["optional-critique"]; review.allowedSkippedDependencies = ["optional-critique"]; review.resources = [{ id: "review-slot", capacity: 1, units: 1 }];
    job.checks = job.checks.filter(check => check.checkId !== "independent-review"); f.store.put("jobs", f.jobId, plan); f.store.put("managed-jobs", f.jobId, job);
    const other = f.store.claimOwner("other", "other-owner"); f.store.prepare(other, "hold-review", "read", {}, [{ id: "review-slot", capacity: 1, units: 1 }]);
    f.store.prepare(f.owner, "past-model", "model", {});
    for (let i = 0; i < 2; i++) { f.store.reserveRequest(f.owner, "past-model", `used-${i}`, [{ id: `work-${f.owner.scopeId}`, ceiling }]); f.store.settleRequest(`used-${i}`, "sent"); }
    const before = f.store.bucket(`work-${f.owner.scopeId}`), completion = barrier(), starts: Array<{stepId:string;intent:Intent}> = [];
    const internal = f.service as unknown as { pump(): void; runStep(jobId: string, stepId: string, intent: Intent): Promise<void> };
    internal.runStep = async (_jobId, stepId, intent) => { starts.push({ stepId, intent }); await completion.promise; };
    internal.pump();
    for (const id of ["RTB-018", "T82"]) evidence(id, () => {
      assert.equal(f.queue.job(f.jobId).steps.find(step => step.id === "optional-critique")!.status, ceiling === 6 ? "skipped" : "running");
      assert.equal(starts.length, ceiling === 6 ? 0 : 1); if (starts.length) assert.equal(starts[0].stepId, "optional-critique");
      assert.equal(f.queue.job(f.jobId).steps.find(step => step.id === "independent-review")!.status, "pending");
      assert.ok(f.queue.job(f.jobId).spec.required.includes("independent-review")); assert.deepEqual(f.store.bucket(`work-${f.owner.scopeId}`), before);
      if (ceiling === 6) assert.equal(f.store.get<{reason:string}>("skip-reasons", `${f.jobId}:optional-critique`)!.reason, "required_reserve");
    });
    for (const start of starts) f.queue.finish(f.jobId, start.stepId, { terminated: true, passed: false, artifactId: null, notSent: true }, 1);
    completion.resolve(); await flush();
  }
});
