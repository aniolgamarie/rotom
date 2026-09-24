import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import type { ManagedJob } from "../src/orchestration/service.ts";
import type { Incident } from "../src/reliability/incidents.ts";

for (const termination of ["confirmed", "unknown"] as const)
test(`[S SCH-013] quota parking with ${termination} execution releases only resources whose work has ended`, t => {
  const f = completedState(t), job = f.service.get(f.jobId), plan = f.queue.job(f.jobId);
  for (const step of plan.steps) {
    step.status = step.id === "implement" ? termination === "unknown" ? "unknown" : "failed" : "pending";
    step.intentId = step.id === "implement" ? "native-write" : null; step.finishedAt = null;
  }
  plan.dispatched++;
  f.store.put("jobs", f.jobId, plan); job.checks = []; job.receipt = null;
  f.store.prepare(f.owner, "job-slot", "job-scope", { jobId: f.jobId }, [{ id: job.projectId, capacity: 1, units: 1 }]); job.jobLease = "job-slot";
  f.store.prepare(f.owner, "native-write", "write", { jobId: f.jobId }, [{ id: "source-writer", capacity: 1, units: 1 }]); f.store.markSent(f.owner, "native-write");
  f.store.settle("native-write", termination === "confirmed" ? "terminated" : "unknown"); f.store.put("managed-jobs", f.jobId, job);
  const incident: Incident = { id: "quota-incident", status: "OPEN", failures: 1, notBefore: Date.now() + 60000, domain: { kind: "quota", id: "pool" } };
  f.store.put("incidents", "pool", incident);
  const internal = f.service as unknown as { park(job: ManagedJob, stepId: string, routeId: string, incident: Incident): void };
  internal.park(job, "implement", "primary", incident);
  const parked = f.service.get(f.jobId); assert.equal(parked.status, "WAITING_QUOTA"); assert.equal(f.queue.job(f.jobId).paused, true);
  assert.equal(parked.semanticAttempts, 1); assert.equal(parked.recovery!.incidentId, incident.id); assert.equal(parked.snapshot, job.snapshot);
  const admitPeer = () => f.store.prepare(f.owner, "peer-slot", "job-scope", { jobId: "peer" }, [{ id: job.projectId, capacity: 1, units: 1 }]);
  if (termination === "unknown") {
    assert.throws(admitPeer, { code: "RESOURCE_DENIED" }); assert.equal(f.store.intent("peer-slot"), null);
    assert.equal(f.store.intent("job-slot")!.status, "prepared"); assert.equal(f.store.intent("native-write")!.status, "unknown"); assert.equal(f.store.claims().length, 2);
    f.store.settle("native-write", "terminated"); const current = f.queue.job(f.jobId); current.steps.find(step => step.id === "implement")!.status = "failed";
    f.store.put("jobs", f.jobId, current); f.finalize();
  }
  assert.equal(f.store.intent("job-slot")!.status, "settled"); assert.equal(f.store.claims().length, 0);
  assert.equal(admitPeer().status, "prepared"); assert.equal(f.store.claims()[0].intent_id, "peer-slot");
  assert.equal(f.service.get(f.jobId).status, "WAITING_QUOTA"); assert.deepEqual(f.store.get("incidents", "pool"), incident);
  acceptance("AC28","park-release",{level:"S",observer:"persistent-parking-and-competing-resource-admission",predicate:"parking releases ended work without resetting incident or semantic attempts",artifact:observerArtifact(`park-${termination}`,{parked,incident,claims:f.store.claims(),plan:f.queue.job(f.jobId)})},()=>{assert.equal(f.store.intent("job-slot")!.status,"settled");assert.equal(f.store.claims()[0].intent_id,"peer-slot");assert.equal(f.service.get(f.jobId).status,"WAITING_QUOTA");assert.deepEqual(f.store.get("incidents","pool"),incident);assert.equal(f.service.get(f.jobId).semanticAttempts,1);});
  assert.equal(f.queue.job(f.jobId).dispatched, 6); assert.equal(f.service.get(f.jobId).semanticAttempts, 1);
});
