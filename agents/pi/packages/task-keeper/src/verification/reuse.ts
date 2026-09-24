import { Artifacts } from "../store/artifacts.ts";
import { Store } from "../store/database.ts";
import { digest } from "../contracts/primitives.ts";
import type { TaskSpec } from "../contracts/task.ts";
import type { DelegationResult } from "../adapters/subagents.ts";

export interface ReviewReuseContract {
  spec: TaskSpec; artifacts: string[]; profileDigest: string; modelDigest: string; runtimeDigest: string;
  writerDescriptorIds: string[]; instructionsDigest?: string;
}
export function reviewReuseKey(contract: ReviewReuseContract): string {
  return digest({ ...contract, artifacts: [...contract.artifacts].sort(), writerDescriptorIds: [...contract.writerDescriptorIds].sort() });
}
interface ReviewProof {
  key: string; resultArtifact: string; receiptArtifact: string; descriptorId: string;
  purpose: "diagnostic" | "acceptance"; complete: boolean; independent: boolean;
}
/** Only the caller that verified the actual execution, full input coverage and verdict may mint a proof. */
export class ReviewCache {
  private artifacts: Artifacts;
  private store: Store;
  constructor(store: Store) { this.store = store; this.artifacts = new Artifacts(store); }
  remember(contract: ReviewReuseContract, proof: Omit<ReviewProof, "key">): boolean {
    if (!proof.complete || !proof.independent || contract.writerDescriptorIds.includes(proof.descriptorId)) return false;
    const key = reviewReuseKey(contract);
    // Pin provenance separately; metadata in the lookup index is never sufficient proof.
    const artifact = this.artifacts.pin(contract.spec.id, contract.spec.snapshot, JSON.stringify({ ...proof, key }), "verifier");
    this.store.put("review-cache", key, { artifactId: artifact.id }); return true;
  }
  lookup(contract: ReviewReuseContract): { result: DelegationResult; proofArtifact: string; receiptArtifact: string; purpose: string } | null {
    const key = reviewReuseKey(contract), entry = this.store.get<{ artifactId: string }>("review-cache", key);
    if (!entry) return null;
    try {
      const pinned = this.artifacts.read(entry.artifactId, contract.spec.id, contract.spec.snapshot);
      if (pinned.artifact.source !== "verifier") return null;
      const proof: ReviewProof = JSON.parse(pinned.content.toString());
      if (proof.key !== key || !proof.complete || !proof.independent || !["diagnostic", "acceptance"].includes(proof.purpose)
        || contract.writerDescriptorIds.includes(proof.descriptorId)) return null;
      const receipt = this.artifacts.read(proof.receiptArtifact, contract.spec.id, contract.spec.snapshot);
      const raw = this.artifacts.read(proof.resultArtifact, contract.spec.id, contract.spec.snapshot);
      if (receipt.artifact.source !== "verifier" || raw.artifact.source !== "runtime") return null;
      const verified = JSON.parse(receipt.content.toString());
      if (verified.review?.passed !== true || verified.invocation !== proof.descriptorId) return null;
      const result: DelegationResult = JSON.parse(raw.content.toString());
      if (result.descriptorId !== proof.descriptorId || result.status !== "ended" || !result.terminationConfirmed) return null;
      return { result, proofArtifact: entry.artifactId, receiptArtifact: proof.receiptArtifact, purpose: proof.purpose };
    } catch { return null; }
  }
}
