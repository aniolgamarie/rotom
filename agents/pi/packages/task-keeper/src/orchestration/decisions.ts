import type { Config } from "../config.ts";
import { ContractError, digest, finiteInteger } from "../contracts/primitives.ts";
import { outcome } from "../contracts/task.ts";
import { compilePacket, type Packet, type EvidenceRef } from "../evidence/packet.ts";
import { Artifacts } from "../store/artifacts.ts";
import type { Store, Owner } from "../store/database.ts";
import { dependenciesSatisfied, type QueuedJob } from "./scheduler.ts";
import type { ManagedJob } from "./service.ts";

/** Fixed-workflow decision facts; resource observations never allocate a new revision. */
export function workflowPacket(store: Store, owner: Owner, config: Config, job: ManagedJob, plan: QueuedJob): Packet {
  store.assertOwner(owner);
  if (!job.cwd || !job.snapshot || plan.spec.snapshot !== job.snapshot) throw new ContractError("DECISION_NOT_READY");
  const artifacts = new Artifacts(store), references: EvidenceRef[] = [];
  const ids = [...new Set(Object.entries(job.outputs).filter(([key]) => !["failures", "receipt"].includes(key)).map(([, id]) => id))].sort();
  for (const id of ids) {
    const metadata = store.get<{ jobId: string; snapshot: string }>("artifacts", id);
    if (!metadata) throw new ContractError("ARTIFACT_MISSING_OR_CHANGED");
    if (metadata.jobId !== job.id) throw new ContractError("ARTIFACT_SCOPE_MISMATCH");
    if (metadata.snapshot !== job.snapshot) continue;
    const { artifact } = artifacts.read(id, job.id, job.snapshot);
    references.push({ id, jobId: job.id, snapshot: job.snapshot, artifactDigest: artifact.contentDigest, start: 0, end: artifact.bytes, source: artifact.source });
  }
  const facts = digest({ spec: plan.spec, semanticReplans: plan.semanticReplans ?? 0, topology: plan.steps.map(step => ({ id: step.id, dependencies: step.dependencies })), snapshot: job.snapshot, status: job.status, controlEpoch: job.controlEpoch,
    semanticAttempts: job.semanticAttempts, routes: job.routes ?? {}, profiles: job.profiles ?? {}, checks: job.checks, failures: job.failures, references });
  const previous = store.get<{ facts: string; revision: number }>("decision-revisions", job.id);
  const revision = previous ? previous.revision + Number(previous.facts !== facts) : 1; finiteInteger(revision, 1);
  store.put("decision-revisions", job.id, { facts, revision });
  const unresolved = plan.steps.filter(step => ["running", "unknown"].includes(step.status)).map(step => step.intentId ?? step.id);
  const receipt = outcome(plan.spec, { delivery: plan.dispatched ? "started" : "queued", nativeRunId: plan.dispatched ? job.id : null,
    execution: unresolved.length ? "unknown" : plan.steps.some(step => step.status === "pending") ? "running" : "ended",
    nativeStatus: "workflow-decision", terminationConfirmed: unresolved.length === 0,
    contract: { requested: { workflow: job.workflow }, resolved: { workflow: job.workflow }, runtimeObserved: { workflow: job.workflow }, violations: [] },
    observation: { complete: unresolved.length === 0, gaps: unresolved }, unknownMutators: unresolved, failures: job.failures, checks: job.checks, claims: [] });
  const budget = store.bucket(`work-${owner.scopeId}`);
  return compilePacket(plan.spec, receipt, references, [], { decisionRevision: revision, ownerEpoch: owner.epoch },
    { available: Math.max(0, config.budget.protectedAttemptsPerWorkScope - Number(budget?.used ?? 0) - Number(budget?.reserved ?? 0)) },
    config.evidence.packetByteBudget, id => artifacts.read(id, job.id, job.snapshot!).artifact);
}

export function workflowProposalTargets(job: ManagedJob, plan: QueuedJob) {
  const steps = job.status === "RUNNING" ? plan.steps.filter(step => step.status === "pending" && dependenciesSatisfied(plan.steps, step)) : [];
  return [...steps.map(step => ({ action: step.kind === "verify" ? "verify" : "advance", target: step.id })),
    { action: "request_finish", target: job.id }, { action: "request_help", target: job.id }];
}
