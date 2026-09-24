import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { scrub } from "../src/reliability/classifier.ts";
import { completedState } from "./fixtures/service-state.ts";

test("[S T84] stored redacted failures retain diagnostic identity actual route and required gaps in every state projection", t => {
  const f = completedState(t), job = f.service.get(f.jobId), secret = "complete confidential error body";
  job.failures = [{ id: "original-required-failure", layer: "provider", code: "RESOURCE_PRESSURE", message: scrub(secret, [secret]),
    required: true, attemptId: "original-execution", resolvedBy: null }];
  job.routes = { implement: "selected-route" };
  f.store.put("child-grants", "original-execution", { jobId: job.id, stepId: "implement", routeId: "selected-route", provider: "requested-provider", model: "requested-model" });
  f.store.put("child-observations", "native", { descriptorId: "original-execution", provider: "observed-provider", model: "observed-model",
    thinking: "off", producerId: "native-producer", stopReason: "error" });
  f.store.put("managed-jobs", job.id, job); f.finalize();
  const stored = f.service.get(job.id), view = f.service.describe(job.id), context = f.service.contextEvidence()[0];
  assert.equal(stored.status, "BLOCKED"); assert.equal(stored.receipt!.status, "BLOCKED");
  assert.ok(stored.receipt!.reasons.includes("unresolved:original-required-failure"));
  assert.equal(stored.receipt!.failureHistory[0].message, "[redacted]");
  assert.equal(view.status, "BLOCKED"); assert.equal(view.failureGroups[0].code, "RESOURCE_PRESSURE");
  assert.equal(view.failureGroups[0].unresolved, 1); assert.equal(view.failureGroups[0].sample, "[redacted]");
  assert.equal(context.status, "BLOCKED"); assert.equal(context.failures[0].code, "RESOURCE_PRESSURE");
  assert.equal(context.failures[0].unresolved, 1); assert.ok(context.receipt!.reasons.includes("unresolved:original-required-failure"));
  for (const routes of [stored.receipt!.routes!, view.routes, context.routes]) {
    const route = routes.find(item => item.stepId === "implement")!;
    assert.equal(route.configuredRoute, "primary"); assert.equal(route.selectedRoute, "selected-route");
    assert.equal(route.attempts[0].descriptorId, "original-execution");
    assert.deepEqual(route.attempts[0].requested, { provider: "requested-provider", model: "requested-model" });
    assert.equal(route.attempts[0].observed![0].provider, "observed-provider"); assert.equal(route.attempts[0].observed![0].model, "observed-model");
    assert.equal(route.attempts[0].observed![0].stopReason, "error");
  }
  assert.equal(JSON.stringify({stored,view,context}).includes(secret), false);
  acceptance("AC33","redacted-failure",{level:"S",observer:"durable-receipt-and-identical-user-model-projections",predicate:"redaction retains failure identity required blockers and route",artifact:observerArtifact("redacted-state",{stored,view,context})},()=>{assert.equal(JSON.stringify({stored,view,context}).includes(secret),false);assert.equal(view.status,"BLOCKED");assert.equal(context.status,"BLOCKED");assert.equal(context.failures[0].code,"RESOURCE_PRESSURE");assert.equal(view.failureGroups[0].sample,"[redacted]");assert.ok(context.receipt!.reasons.includes("unresolved:original-required-failure"));});
  // Independent accepted state is the positive control; redaction itself is never recovery evidence.
  const good = completedState(t); good.finalize(); assert.equal(good.service.get(good.jobId).receipt!.status, "COMPLETED");
});
