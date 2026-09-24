import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { DecisionLedger } from "../src/evidence/decision-ledger.ts";
import { Store } from "../src/store/database.ts";
import type { Packet } from "../src/evidence/packet.ts";
import { isolatedDirectory } from "./helpers.ts";
for (const id of ["EVD-007", "EVD-008", "EVD-009", "T59", "T60", "T62", "T63", "T64", "T65", "T70", "T85"]) test(`[S ${id}] TC-${id}-S persisted proposal survives resource waiting but not changed authority`, t => {
  const root = isolatedDirectory(t), store = new Store(root), owner = store.claimOwner("scope", "owner"); t.after(() => store.close());
  const packet: Packet = { id: "packet", jobId: "job", specVersion: 1, snapshot: "snapshot", policyDigest: "policy", decisionRevision: 1,
    ownerEpoch: owner.epoch, blockers: [], required: ["tests", "review"], budget: { available: 2 }, references: [], claims: [], failureGroups: [], digest: "packet-digest" };
  const input = { packetId: packet.id, action: "verify", target: "tests", reason: "check current snapshot", evidenceIds: [] };
  const ledger = new DecisionLedger(store, owner);
  for (const bad of ["{", { ...input, shell: "untrusted" }, { ...input, required: [] }, { ...input, target: "unbound" }])
    assert.throws(() => ledger.authorize(bad, packet, ["tests"]));
  assert.equal(store.list("proposals").length, 0); const contract = ledger.authorize(input, packet, ["tests"]);
  const reopened = new Store(root); t.after(() => reopened.close()); const next = new DecisionLedger(reopened, owner);
  assert.equal(reopened.list("proposals").length, 1);
  assert.throws(() => next.authorize({ ...input, reason: "same decision" }, packet, ["tests"]), { code: "DUPLICATE_PROPOSAL" });
  assert.throws(() => next.admit(contract, packet, [{ id: "slot", capacity: 1, units: 1 }], () => false), { code: "RESOURCE_DENIED" });
  assert.equal(reopened.claims().length, 0); assert.equal(reopened.intent(`proposal-${contract.fingerprint}`), null);
  for (const change of [{ snapshot: "changed" }, { specVersion: 2 }, { policyDigest: "revoked" }, { decisionRevision: 2 }, { ownerEpoch: owner.epoch + 1 }])
    assert.throws(() => next.admit(contract, { ...packet, ...change }, [], () => true), { code: "STALE_PROPOSAL" });
  if(id === "EVD-009")for(const name of ["proposal-json-action-reference","duplicate-fingerprint"])acceptance("AC26",name,{level:"S",observer:"persisted-proposal-reopened-DB-and-explicit-admission",predicate:name,artifact:observerArtifact(name,{packet,contract,proposals:reopened.list("proposals")})},()=>{assert.equal(reopened.list("proposals").length,1);assert.equal(reopened.claims().length,0);assert.throws(()=>next.authorize({...input,reason:"same work"},packet,["tests"]),{code:"DUPLICATE_PROPOSAL"});assert.throws(()=>next.authorize({...input,evidenceIds:["forged-reference"]},packet,["tests"]));assert.throws(()=>next.authorize({...input,action:"shell"},packet,["tests"]));});
  const accepted = next.admit(contract, { ...packet, budget: { available: 1 } }, [{ id: "slot", capacity: 1, units: 1 }], () => true);
  assert.equal(accepted.status, "prepared"); assert.equal(reopened.claims().length, 1); assert.equal(reopened.list("proposals").length, 1);
  assert.throws(() => next.admit(contract, packet, [], () => true));
  store.revokeOwner(owner); assert.throws(() => next.admit(contract, packet, [], () => true));
  assert.deepEqual(packet.required, ["tests", "review"]);
});

// Production packet projection, rather than a hand-built Packet, owns revisions.
import { completedState } from "./fixtures/service-state.ts";
import { workflowPacket, workflowProposalTargets } from "../src/orchestration/decisions.ts";
import type { ManagedJob } from "../src/orchestration/service.ts";
import { evidence } from "./recorded-test.ts";

test("[S EVD-007 EVD-008] workflow decision revisions retain resource-only changes and invalidate changed acceptance facts", t => {
  const f = completedState(t), job = f.store.get<ManagedJob>("managed-jobs", f.jobId)!, plan = f.queue.job(f.jobId);
  const initial = workflowPacket(f.store, f.owner, f.config, job, plan), ledger = new DecisionLedger(f.store, f.owner);
  const proposal = { packetId: initial.id, action: "request_finish", target: job.id, reason: "Check actual acceptance", evidenceIds: [] };
  const contract = ledger.authorize(proposal, initial, [job.id]);
  f.store.prepare(f.owner, "resource-observation", "read", {}, [{ id: "observation", capacity: 1, units: 1 }]);
  f.store.reserveRequest(f.owner, "resource-observation", "accounted-request", [{ id: `work-${f.owner.scopeId}`, ceiling: 12 }]);
  const changedBudget = workflowPacket(f.store, f.owner, f.config, job, plan);
  evidence("EVD-008", () => {
    assert.equal(changedBudget.id, initial.id); assert.equal(changedBudget.decisionRevision, initial.decisionRevision);
    assert.equal(changedBudget.budget.available, initial.budget.available! - 1); assert.doesNotThrow(() => ledger.check(contract, changedBudget));
    assert.deepEqual(workflowProposalTargets(job, plan), [{action:"request_finish",target:job.id},{action:"request_help",target:job.id}]);
  });
  evidence("EVD-007", () => {
    assert.throws(() => workflowPacket(f.store, f.owner, f.config, { ...job, outputs: { forged: "artifact-missing" } }, plan), {code:"ARTIFACT_MISSING_OR_CHANGED"});
    const foreign = f.artifacts.pin("another-job", job.snapshot!, "foreign evidence", "runtime");
    assert.throws(() => workflowPacket(f.store, f.owner, f.config, { ...job, outputs: { forged: foreign.id } }, plan), {code:"ARTIFACT_SCOPE_MISMATCH"});
  });
  acceptance("AC26","resource-only-change",{level:"S",observer:"real-workflow-packet-before-and-after-budget-reservation",predicate:"resource observation rechecks without expiring semantic identity",artifact:observerArtifact("resource-only",{initial,changedBudget,contract})},()=>{assert.equal(changedBudget.id,initial.id);assert.equal(changedBudget.budget.available,initial.budget.available!-1);assert.doesNotThrow(()=>ledger.check(contract,changedBudget));});
  for (const mutation of ["control", "spec", "checks", "failure"] as const) {
    const nextJob = structuredClone(job), nextPlan = structuredClone(plan);
    if (mutation === "control") nextJob.controlEpoch++;
    if (mutation === "spec") nextPlan.spec.version++;
    if (mutation === "checks") nextJob.checks = [];
    if (mutation === "failure") nextJob.failures.push({ id: "new-failure", layer: "verification", code: "CHECK:tests", message: "failed", attemptId: "attempt", required: true, resolvedBy: null });
    const changed = workflowPacket(f.store, f.owner, f.config, nextJob, nextPlan);
    evidence("EVD-007", () => { assert.ok(changed.decisionRevision > initial.decisionRevision); assert.throws(() => ledger.check(contract, changed), {code:"STALE_PROPOSAL"}); });
  }
});

test("[S EVD-009] rejected workflow proposal attachment rolls back registration and all queued effects", t => {
  const f = completedState(t), job = f.store.get<ManagedJob>("managed-jobs", f.jobId)!, packet = workflowPacket(f.store, f.owner, f.config, job, f.queue.job(f.jobId));
  const ledger = new DecisionLedger(f.store, f.owner), input = { packetId: packet.id, action: "request_finish", target: job.id, reason: "No implicit dispatch", evidenceIds: [] };
  const before = f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n;
  assert.throws(() => ledger.authorize(input, packet, [job.id], contract => {
    f.store.put("pending-proposals", job.id, contract); throw new Error("attachment rejected");
  }), /attachment rejected/);
  assert.deepEqual(f.store.list("proposals"), []); assert.equal(f.store.get("pending-proposals", job.id), null);
  assert.equal(f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n, before);
  assert.doesNotThrow(() => ledger.authorize(input, packet, [job.id]));
});

test("[S] proposal help uses existing pause and authority revoked during projection leaves no authorization", async t => {
  const f = completedState(t), original = f.store.get<ManagedJob>("managed-jobs", f.jobId)!, packet = workflowPacket(f.store, f.owner, f.config, original, f.queue.job(f.jobId));
  // Inject only the already verified snapshot projection; exercise the real
  // second-stage authorization and existing pause, without claiming native E.
  f.service.decisions = async () => ({ packet, reason: null, allowed: workflowProposalTargets(original, f.queue.job(f.jobId)), history: [] });
  const input = { packetId: packet.id, action: "request_help", target: f.jobId, reason: "Keep the candidate", evidenceIds: [] };
  await assert.rejects(f.service.propose(f.jobId, input, () => false), { code: "MODEL_CONTROL_REVOKED" });
  assert.equal(f.store.list("proposals").length, 0); assert.equal(f.store.get<ManagedJob>("managed-jobs", f.jobId)!.controlEpoch, original.controlEpoch);
  const accepted = await f.service.propose(f.jobId, input);
  assert.equal(accepted.job.status, "PAUSED"); assert.equal(f.store.get<ManagedJob>("managed-jobs", f.jobId)!.controlEpoch, original.controlEpoch + 1);
  assert.equal(f.queue.job(f.jobId).paused, true); assert.equal(f.store.get<ManagedJob>("managed-jobs", f.jobId)!.semanticAttempts, original.semanticAttempts);
  assert.deepEqual(f.queue.job(f.jobId).spec.required, ["build", "focused-tests", "independent-review"]);
});


test("[S] a stale queued proposal is retired so an explicit later resume can make progress", async t => {
  const f = completedState(t), job = f.service.get(f.jobId), plan = f.queue.job(f.jobId), step = plan.steps.find(step => step.id === "build")!;
  step.status = "pending"; step.intentId = null; step.finishedAt = null; job.checks = job.checks.filter(check => check.checkId !== "build");
  f.store.put("jobs", f.jobId, plan); f.store.put("managed-jobs", f.jobId, job);
  const packet = workflowPacket(f.store, f.owner, f.config, job, plan), contract = new DecisionLedger(f.store, f.owner).authorize(
    { packetId: packet.id, action: "verify", target: "build", reason: "Fixed pending check", evidenceIds: [] }, packet, ["build"]);
  f.store.put("pending-proposals", f.jobId, contract);
  const internal = f.service as unknown as {capture(): Promise<unknown>;pump(): void};
  internal.capture = async () => ({ snapshot: { id: "tree", files: [] }, patch: "" });
  f.service.pause(f.jobId); await f.service.resume(f.jobId); internal.pump();
  assert.equal(f.service.get(f.jobId).status, "BLOCKED"); assert.equal(f.service.get(f.jobId).reason, "STALE_PROPOSAL");
  assert.equal(f.store.get("pending-proposals", f.jobId), null); assert.equal(f.queue.job(f.jobId).dispatched, plan.dispatched);
  assert.equal(f.store.list("proposal-executions").length, 0);
  assert.equal(f.store.get<{status:string}>("proposal-results", contract.fingerprint)!.status, "rejected");
  await f.service.resume(f.jobId);
  assert.equal(f.service.get(f.jobId).status, "RUNNING"); assert.equal(f.queue.next(Date.now())!.stepId, "build");
  assert.equal(f.queue.job(f.jobId).dispatched, plan.dispatched);
});
