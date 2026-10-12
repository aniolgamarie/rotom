import { Artifacts } from "../store/artifacts.mjs";
import { Store } from "../store/database.mjs";
import { digest } from "../contracts/primitives.mjs";
export function reviewReuseKey(contract) {
    return digest({
        ...contract,
        artifacts: [
            ...contract.artifacts
        ].sort(),
        writerDescriptorIds: [
            ...contract.writerDescriptorIds
        ].sort()
    });
}
export class ReviewCache {
    artifacts;
    store;
    constructor(store){
        this.store = store;
        this.artifacts = new Artifacts(store);
    }
    remember(contract, proof) {
        if (!proof.complete || !proof.independent || contract.writerDescriptorIds.includes(proof.descriptorId)) return false;
        const key = reviewReuseKey(contract);
        const artifact = this.artifacts.pin(contract.spec.id, contract.spec.snapshot, JSON.stringify({
            ...proof,
            key
        }), "verifier");
        this.store.put("review-cache", key, {
            artifactId: artifact.id
        });
        return true;
    }
    lookup(contract) {
        const key = reviewReuseKey(contract), entry = this.store.get("review-cache", key);
        if (!entry) return null;
        try {
            const pinned = this.artifacts.read(entry.artifactId, contract.spec.id, contract.spec.snapshot);
            if (pinned.artifact.source !== "verifier") return null;
            const proof = JSON.parse(pinned.content.toString());
            if (proof.key !== key || !proof.complete || !proof.independent || ![
                "diagnostic",
                "acceptance"
            ].includes(proof.purpose) || contract.writerDescriptorIds.includes(proof.descriptorId)) return null;
            const receipt = this.artifacts.read(proof.receiptArtifact, contract.spec.id, contract.spec.snapshot);
            const raw = this.artifacts.read(proof.resultArtifact, contract.spec.id, contract.spec.snapshot);
            if (receipt.artifact.source !== "verifier" || raw.artifact.source !== "runtime") return null;
            const verified = JSON.parse(receipt.content.toString());
            if (verified.review?.passed !== true || verified.invocation !== proof.descriptorId) return null;
            const result = JSON.parse(raw.content.toString());
            if (result.descriptorId !== proof.descriptorId || result.status !== "ended" || !result.terminationConfirmed) return null;
            return {
                result,
                proofArtifact: entry.artifactId,
                receiptArtifact: proof.receiptArtifact,
                purpose: proof.purpose
            };
        } catch  {
            return null;
        }
    }
}
