import { test, assert, evidence } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";

test("[S EVD-012] retained passing checks cannot finish a plan with an unreconciled running execution", t => {
  for (const state of ["running", "unknown"] as const) {
    const f = completedState(t); f.queue.retryFrom(f.jobId, "focused-tests"); const intent = f.queue.dispatch(f.jobId, "focused-tests", "tree"); f.store.markSent(f.owner, intent.id);
    if (state === "unknown") f.queue.finish(f.jobId, "focused-tests", { terminated: false, passed: false, artifactId: null }, 2);
    f.finalize(); assert.equal(f.service.get(f.jobId).status, "BLOCKED"); assert.notEqual(f.service.get(f.jobId).receipt?.status, "COMPLETED");
    assert.equal(f.service.get(f.jobId).receipt!.status, "BLOCKED"); assert.ok(f.service.get(f.jobId).receipt!.reasons.includes("unknown_mutator"));
    assert.ok(f.store.claims().some(claim => claim.intent_id === intent.id)); assert.equal(f.queue.job(f.jobId).steps.find(step => step.id === "focused-tests")!.status, state);
  }
  const valid = completedState(t); valid.finalize(); assert.equal(valid.service.get(valid.jobId).status, "COMPLETED"); assert.equal(valid.service.describe(valid.jobId).receipt?.status, "COMPLETED");
});

test("[S EVD-010] blocked execution publishes a durable receipt even when later required steps were never dispatched", t => {
  const f = completedState(t), job = f.service.get(f.jobId), plan = f.queue.job(f.jobId);
  job.status = "BLOCKED"; job.reason = "required_tests_not_passed";
  job.checks.find(check => check.checkId === "focused-tests")!.status = "failed";
  job.checks = job.checks.filter(check => check.checkId !== "independent-review");
  job.failures.push({ id: "check-error", layer: "verification", code: "CHECK:focused-tests", message: "required_tests_not_passed", attemptId: "check-attempt", required: true, resolvedBy: null });
  plan.steps.find(step => step.id === "focused-tests")!.status = "failed"; plan.steps.find(step => step.id === "independent-review")!.status = "pending";
  f.store.put("jobs", f.jobId, plan); f.store.put("managed-jobs", f.jobId, job); f.finalize();
  const result = f.service.get(f.jobId), receipt = result.receipt!;
  assert.equal(receipt.status, "BLOCKED"); assert.equal(receipt.nativeStatus, "workflow-blocked");
  for (const reason of ["required:focused-tests", "required:independent-review", "unresolved:check-error", "workflow:required_tests_not_passed"]) assert.ok(receipt.reasons.includes(reason));
  assert.deepEqual(receipt.failureHistory, job.failures); assert.equal(result.reason, "required_tests_not_passed");
  const artifact = f.artifacts.read(result.outputs.receipt, f.jobId, "tree"); assert.deepEqual(JSON.parse(artifact.content.toString("utf8")), receipt);
  const before = result.outputs.receipt; f.finalize(); assert.equal(f.service.get(f.jobId).outputs.receipt, before);
  assert.equal(f.queue.job(f.jobId).steps.find(step => step.id === "independent-review")!.status, "pending");
});

test("[S EVD-013 T47] receipt artifact storage failure retains a blocked database record and unknown ownership", t => {
  const f = completedState(t); f.queue.retryFrom(f.jobId, "focused-tests");
  const intent = f.queue.dispatch(f.jobId, "focused-tests", "tree"); f.store.markSent(f.owner, intent.id);
  f.queue.finish(f.jobId, "focused-tests", { terminated: false, passed: false, artifactId: null }, 2);
  const internal = f.service as unknown as { artifacts: { pin: (...args: unknown[]) => unknown } }, original = internal.artifacts.pin;
  internal.artifacts.pin = () => { throw Object.assign(new Error("fixture disk full"), { code: "ENOSPC" }); };
  f.finalize();
  for (const id of ["EVD-013", "T47"]) evidence(id, () => {
    const job = f.service.get(f.jobId); assert.equal(job.status, "BLOCKED"); assert.equal(job.receipt!.status, "BLOCKED");
    assert.equal(job.outputs.receipt, undefined); assert.ok(job.receipt!.reasons.some(reason => reason.startsWith("receipt_artifact_unavailable:")));
    assert.equal(f.store.intent(intent.id)!.status, "unknown"); assert.ok(f.store.claims().some(claim => claim.intent_id === intent.id));
    assert.equal(f.queue.job(f.jobId).dispatched, 6);
  });
  internal.artifacts.pin = original; f.finalize();
  for (const id of ["EVD-013", "T47"]) evidence(id, () => {
    const job = f.service.get(f.jobId); assert.ok(job.outputs.receipt); assert.equal(job.receipt!.status, "BLOCKED");
    assert.ok(job.receipt!.reasons.includes("unknown_mutator")); assert.equal(f.store.intent(intent.id)!.status, "unknown");
  });
});

test("[S REC-019] a revoked owner cannot publish a new blocked receipt artifact", t => {
  const f = completedState(t), job = f.service.get(f.jobId), before = f.store.list("artifacts");
  f.store.revokeOwner(f.owner); f.store.claimOwner(f.owner.scopeId, "replacement");
  const internal = f.service as unknown as { recordBlockedReceipt(value: typeof job): void };
  assert.throws(() => internal.recordBlockedReceipt(job)); assert.deepEqual(f.store.list("artifacts"), before);
  assert.equal(f.service.get(f.jobId).receipt, null); assert.equal(job.receipt, null);
});

test("[S EVD-010 T12] workflow completion preserves the missing test and required reviewer blockers", t => {
  for (const checkId of ["focused-tests", "independent-review"]) {
    const f = completedState(t), job = f.service.get(f.jobId);
    job.checks = job.checks.filter(check => check.checkId !== checkId); f.store.put("managed-jobs", f.jobId, job); f.finalize();
    evidence("EVD-010", () => { assert.equal(f.service.get(f.jobId).status, "BLOCKED"); assert.ok(f.service.get(f.jobId).receipt!.reasons.includes(`required:${checkId}`)); });
    if (checkId === "independent-review") evidence("T12", () => {
      assert.equal(f.service.describe(f.jobId).receipt!.status, "BLOCKED"); assert.ok(f.service.describe(f.jobId).receipt!.reasons.includes("required:independent-review"));
      assert.equal(f.queue.job(f.jobId).steps.every(step => step.status === "passed"), true);
    });
  }
});

test("[S EVD-011 T13] optional evidence failure follows the declared partial policy without demoting required checks", t => {
  for (const allowed of [false, true]) {
    const f = completedState(t, allowed), job = f.service.get(f.jobId); job.checks.find(check => check.checkId === "extra")!.status = "failed";
    f.store.put("managed-jobs", f.jobId, job); f.finalize();
    for (const id of ["EVD-011", "T13"]) evidence(id, () => {
      assert.equal(f.service.get(f.jobId).status, allowed ? "PARTIAL" : "BLOCKED"); assert.deepEqual(f.service.get(f.jobId).receipt!.optionalGaps, ["extra"]);
      assert.deepEqual(f.queue.job(f.jobId).spec.required, ["build", "focused-tests", "independent-review"]);
      assert.equal(f.service.describe(f.jobId).receipt!.status, allowed ? "PARTIAL" : "BLOCKED");
    });
  }
});

test("[S T09] a required tool failure remains blocking until authenticated matching recovery evidence arrives", t => {
  const f = completedState(t), job = f.service.get(f.jobId);
  job.failures.push({ id: "tool-failure", layer: "tool", code: "TOOL_FAILED", message: "required read failed", attemptId: "attempt", required: true, resolvedBy: null });
  job.outputs.claim = f.artifacts.pin(f.jobId, "tree", "Everything is complete", "claim").id; f.store.put("managed-jobs", f.jobId, job);
  f.finalize(); assert.equal(f.service.get(f.jobId).status, "BLOCKED"); assert.ok(f.service.get(f.jobId).receipt!.reasons.includes("unresolved:tool-failure"));
  const updated = f.service.get(f.jobId); updated.status = "RUNNING"; updated.failures[0].resolvedBy = updated.checks.find(check => check.checkId === "focused-tests")!.artifactId;
  f.store.put("managed-jobs", f.jobId, updated); f.finalize();
  assert.equal(f.service.get(f.jobId).status, "COMPLETED"); assert.equal(f.service.get(f.jobId).receipt!.failureHistory[0].id, "tool-failure");
  assert.ok(f.service.get(f.jobId).receipt!.failureHistory[0].resolvedBy);
});

test("[S EVD-003 T05] a recovered fallback keeps failed and successful model facts in the final receipt", t => {
  const f = completedState(t, false, true), job = f.service.get(f.jobId);
  job.routes = { implement: "backup" }; job.recovery = { stepId: "implement", primaryRoute: "primary", incidentId: "incident", stage: null, networkAttempts: 0 };
  job.failures.push({ id: "primary-failure", layer: "provider", code: "RATE_LIMIT", message: "primary quota", attemptId: "primary-attempt", required: false, resolvedBy: null });
  f.store.put("managed-jobs", f.jobId, job);
  for (const routeId of ["primary", "backup"]) {
    const route = f.config.routes[routeId], descriptorId = `${routeId}-attempt`;
    f.store.put("child-grants", descriptorId, { jobId: f.jobId, stepId: "implement", routeId, provider: route.provider, model: route.model });
    f.store.put("child-observations", descriptorId, { descriptorId, producerId: `${routeId}-producer`, provider: route.provider, model: route.model,
      thinking: "off", stopReason: routeId === "primary" ? "error" : "stop" });
  }
  f.finalize(); const receipt = f.service.get(f.jobId).receipt!, route = receipt.routes!.find(row => row.stepId === "implement")!;
  for (const id of ["EVD-003", "T05"]) evidence(id, () => {
    assert.equal(receipt.status, "COMPLETED"); assert.equal(receipt.failureHistory[0].attemptId, "primary-attempt");
    assert.equal(route.configuredRoute, "primary"); assert.equal(route.selectedRoute, "backup"); assert.equal(route.recovery!.incidentId, "incident");
    assert.equal(route.attempts.find(attempt => attempt.descriptorId === "primary-attempt")!.observed![0].stopReason, "error");
    assert.equal(route.attempts.find(attempt => attempt.descriptorId === "backup-attempt")!.observed![0].model, "backup-model");
    assert.equal(route.attempts.find(attempt => attempt.descriptorId === "backup-attempt")!.observed![0].stopReason, "stop");
    assert.deepEqual(f.service.describe(f.jobId).routes, receipt.routes);
  });
});
