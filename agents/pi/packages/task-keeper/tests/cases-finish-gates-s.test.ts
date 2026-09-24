import { test, assert } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import { DecisionLedger } from "../src/evidence/decision-ledger.ts";
import { compilePacket } from "../src/evidence/packet.ts";

for (const checkId of ["independent-review", "focused-tests"] as const)
test(`[S ${checkId === "independent-review" ? "T03" : "T61"}] ended native work cannot finish while ${checkId} rejects the candidate`, t => {
  const f = completedState(t), job = f.service.get(f.jobId), plan = f.queue.job(f.jobId);
  const artifact = f.artifacts.pin(job.id, "tree", JSON.stringify({ checkId, status: "failed", reason: "independent_gate_failed" }), "verifier");
  job.checks = job.checks.map(check => check.checkId === checkId ? { ...check, status: "failed", artifactId: artifact.id } : check);
  job.failures.push({ id: "gate-failed", layer: "verification", code: "INDEPENDENT_GATE_FAILED", message: "Declared state fixture: independent gate rejected completed native work",
    attemptId: "ended-native", required: true, resolvedBy: null });
  f.store.put("managed-jobs", job.id, job); f.finalize();
  const blocked = f.service.get(job.id);
  assert.equal(blocked.receipt!.status, "BLOCKED"); assert.ok(blocked.receipt!.reasons.includes(`required:${checkId}`));
  assert.equal(blocked.receipt!.nativeStatus, "workflow-ended"); assert.ok(plan.steps.every(step => step.status === "passed"));
  assert.equal(blocked.receipt!.failureHistory[0].code, "INDEPENDENT_GATE_FAILED");
  const counts = { intents: f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n, requests: f.store.db.prepare("SELECT count(*) n FROM requests").get()!.n };
  if (checkId === "focused-tests") {
    const packet = compilePacket(plan.spec, blocked.receipt!, [], [], { ownerEpoch: f.owner.epoch, decisionRevision: 1 }, { available: 4 }, 10000);
    const contract = new DecisionLedger(f.store, f.owner).authorize({ packetId: packet.id, action: "request_finish", target: "root", reason: "model claims completion", evidenceIds: [] }, packet, ["root"]);
    assert.equal(contract.proposal.action, "request_finish"); assert.equal(f.store.list("proposals").length, 1);
    f.finalize(); assert.equal(f.service.get(job.id).receipt!.status, "BLOCKED");
    assert.ok(f.service.get(job.id).receipt!.reasons.includes(`required:${checkId}`));
  }
  assert.equal(f.queue.job(job.id).dispatched, plan.dispatched); assert.equal(f.service.get(job.id).semanticAttempts, 1);
  assert.equal(f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n, counts.intents);
  assert.equal(f.store.db.prepare("SELECT count(*) n FROM requests").get()!.n, counts.requests);
  assert.equal(f.service.describe(job.id).status, "BLOCKED");
  const valid = completedState(t); valid.finalize(); assert.equal(valid.service.get(valid.jobId).receipt!.status, "COMPLETED");
});
