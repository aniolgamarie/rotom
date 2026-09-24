import { ContractError, canonical, digest, identifier, object } from "../contracts/primitives.ts";
import type { TaskSpec, Receipt, FailureFact } from "../contracts/task.ts";

export function groupFailures(failures: FailureFact[], unresolvedIds: ReadonlySet<string> = new Set()) {
  const groups = new Map<string, { layer: string; code: string; required: boolean; count: number; unresolved: number; firstId: string; ids: string[]; unresolvedIds: string[]; sample: string }>();
  for (const failure of failures) {
    const key = canonical([failure.layer, failure.code, failure.required]);
    const group = groups.get(key) ?? { layer: failure.layer, code: failure.code, required: failure.required, count: 0, unresolved: 0,
      firstId: failure.id, ids: [], unresolvedIds: [], sample: failure.message.slice(0, 500) };
    group.count++; group.ids.push(failure.id);
    if (!failure.resolvedBy || unresolvedIds.has(failure.id)) { group.unresolved++; group.unresolvedIds.push(failure.id); }
    groups.set(key, group);
  }
  return [...groups.values()].sort((a, b) => Number(b.required) - Number(a.required) || a.layer.localeCompare(b.layer) || a.code.localeCompare(b.code));
}

export interface EvidenceRef {
  id: string; jobId: string; snapshot: string; artifactDigest: string;
  start: number; end: number; source: "runtime" | "verifier" | "claim";
}
export interface Packet {
  id: string; jobId: string; specVersion: number; snapshot: string; policyDigest: string;
  decisionRevision: number; ownerEpoch: number;
  blockers: string[]; required: string[]; budget: { available: number | null };
  references: EvidenceRef[]; claims: string[]; digest: string;
  failureGroups: ReturnType<typeof groupFailures>;
}

export function compilePacket(spec: TaskSpec, receipt: Receipt, references: EvidenceRef[], claims: string[],
  identity: { decisionRevision: number; ownerEpoch: number }, budget: { available: number | null }, maxBytes: number,
  resolveArtifact?: (id: string) => { jobId: string; snapshot: string; contentDigest: string; bytes: number; source: string }): Packet {
  if (receipt.jobId !== spec.id || receipt.specVersion !== spec.version || receipt.snapshot !== spec.snapshot) {
    throw new ContractError("STALE_RECEIPT");
  }
  const ids = new Set<string>();
  for (const ref of references) {
    identifier(ref.id);
    if (ids.has(ref.id) || ref.jobId !== spec.id || ref.snapshot !== spec.snapshot || !ref.artifactDigest
      || !Number.isSafeInteger(ref.start) || !Number.isSafeInteger(ref.end) || ref.start < 0 || ref.end < ref.start) {
      throw new ContractError("INVALID_EVIDENCE_REFERENCE");
    }
    ids.add(ref.id);
    const artifact = resolveArtifact?.(ref.id);
    if (!artifact || artifact.jobId !== spec.id || artifact.snapshot !== spec.snapshot
      || artifact.contentDigest !== ref.artifactDigest || artifact.source !== ref.source || ref.end > artifact.bytes) {
      throw new ContractError("UNVERIFIED_ARTIFACT_REFERENCE");
    }
  }
  const body = { id: `packet-${digest([spec.id, identity.decisionRevision, identity.ownerEpoch])}`,
    jobId: spec.id, specVersion: spec.version, snapshot: spec.snapshot, policyDigest: spec.policyDigest,
    ...identity, blockers: receipt.reasons, required: spec.required, budget, references, claims,
    failureGroups: groupFailures(receipt.failureHistory, new Set(receipt.reasons.filter((reason) => reason.startsWith("unresolved:")).map((reason) => reason.slice("unresolved:".length)))) };
  const packet = { ...body, digest: digest(body) };
  if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || Buffer.byteLength(canonical(packet)) > maxBytes) {
    throw new ContractError("PACKET_TOO_LARGE");
  }
  return structuredClone(packet);
}

export interface StepProposal {
  packetId: string;
  action: "advance" | "verify" | "request_finish" | "request_help";
  target: string;
  reason: string;
  evidenceIds: string[];
}
export interface StepContract {
  proposal: StepProposal;
  fingerprint: string;
  packetDigest: string;
  jobId: string; specVersion: number; snapshot: string; policyDigest: string;
  decisionRevision: number; ownerEpoch: number;
}

/** Cheap structural validation precedes any snapshot capture or proposal lookup. */
export function parseProposal(input: unknown): StepProposal {
  const value = object(input, ["packetId", "action", "target", "reason", "evidenceIds"]);
  if (typeof value.packetId !== "string" || !["advance", "verify", "request_finish", "request_help"].includes(value.action as string)
    || typeof value.target !== "string" || typeof value.reason !== "string" || value.reason.length > 2000
    || !Array.isArray(value.evidenceIds) || value.evidenceIds.some(id => typeof id !== "string")) throw new ContractError("INVALID_PROPOSAL");
  return structuredClone(value) as unknown as StepProposal;
}

export function authorizeProposal(input: unknown, packet: Packet, allowedTargets: string[], seen: Set<string>): StepContract {
  const proposal = parseProposal(input);
  if (proposal.packetId !== packet.id || !allowedTargets.includes(proposal.target)
    || proposal.evidenceIds.some(id => !packet.references.some(ref => ref.id === id))) throw new ContractError("INVALID_PROPOSAL");
  const fingerprint = digest([packet.jobId, packet.specVersion, packet.snapshot, packet.policyDigest, packet.decisionRevision,
    packet.ownerEpoch, proposal.action, proposal.target, [...new Set(proposal.evidenceIds)].sort()]);
  if (seen.has(fingerprint)) throw new ContractError("DUPLICATE_PROPOSAL");
  seen.add(fingerprint);
  return structuredClone({ proposal, fingerprint, packetDigest: packet.digest, jobId: packet.jobId,
    specVersion: packet.specVersion, snapshot: packet.snapshot, policyDigest: packet.policyDigest,
    decisionRevision: packet.decisionRevision, ownerEpoch: packet.ownerEpoch });
}

/** Called again immediately before durable dispatch. Resource observations do not change decision identity. */
export function recheck(contract: StepContract, current: Pick<Packet, "jobId" | "specVersion" | "snapshot" | "policyDigest" | "decisionRevision" | "ownerEpoch">,
  resourceAllowed: boolean, cancelled: boolean): void {
  for (const key of ["jobId", "specVersion", "snapshot", "policyDigest", "decisionRevision", "ownerEpoch"] as const) {
    if (contract[key] !== current[key]) throw new ContractError("STALE_PROPOSAL");
  }
  if (cancelled) throw new ContractError("CONTROL_REVOKED");
  if (!resourceAllowed) throw new ContractError("RESOURCE_DENIED");
}
