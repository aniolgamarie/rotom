import { ContractError, canonical, digest, identifier, object } from "../contracts/primitives.mjs";
export function groupFailures(failures, unresolvedIds = new Set()) {
    const groups = new Map();
    for (const failure of failures){
        const key = canonical([
            failure.layer,
            failure.code,
            failure.required
        ]);
        const group = groups.get(key) ?? {
            layer: failure.layer,
            code: failure.code,
            required: failure.required,
            count: 0,
            unresolved: 0,
            firstId: failure.id,
            ids: [],
            unresolvedIds: [],
            sample: failure.message.slice(0, 500)
        };
        group.count++;
        group.ids.push(failure.id);
        if (!failure.resolvedBy || unresolvedIds.has(failure.id)) {
            group.unresolved++;
            group.unresolvedIds.push(failure.id);
        }
        groups.set(key, group);
    }
    return [
        ...groups.values()
    ].sort((a, b)=>Number(b.required) - Number(a.required) || a.layer.localeCompare(b.layer) || a.code.localeCompare(b.code));
}
export function compilePacket(spec, receipt, references, claims, identity, budget, maxBytes, resolveArtifact) {
    if (receipt.jobId !== spec.id || receipt.specVersion !== spec.version || receipt.snapshot !== spec.snapshot) {
        throw new ContractError("STALE_RECEIPT");
    }
    const ids = new Set();
    for (const ref of references){
        identifier(ref.id);
        if (ids.has(ref.id) || ref.jobId !== spec.id || ref.snapshot !== spec.snapshot || !ref.artifactDigest || !Number.isSafeInteger(ref.start) || !Number.isSafeInteger(ref.end) || ref.start < 0 || ref.end < ref.start) {
            throw new ContractError("INVALID_EVIDENCE_REFERENCE");
        }
        ids.add(ref.id);
        const artifact = resolveArtifact?.(ref.id);
        if (!artifact || artifact.jobId !== spec.id || artifact.snapshot !== spec.snapshot || artifact.contentDigest !== ref.artifactDigest || artifact.source !== ref.source || ref.end > artifact.bytes) {
            throw new ContractError("UNVERIFIED_ARTIFACT_REFERENCE");
        }
    }
    const body = {
        id: `packet-${digest([
            spec.id,
            identity.decisionRevision,
            identity.ownerEpoch
        ])}`,
        jobId: spec.id,
        specVersion: spec.version,
        snapshot: spec.snapshot,
        policyDigest: spec.policyDigest,
        ...identity,
        blockers: receipt.reasons,
        required: spec.required,
        budget,
        references,
        claims,
        failureGroups: groupFailures(receipt.failureHistory, new Set(receipt.reasons.filter((reason)=>reason.startsWith("unresolved:")).map((reason)=>reason.slice("unresolved:".length))))
    };
    const packet = {
        ...body,
        digest: digest(body)
    };
    if (!Number.isSafeInteger(maxBytes) || maxBytes < 1 || Buffer.byteLength(canonical(packet)) > maxBytes) {
        throw new ContractError("PACKET_TOO_LARGE");
    }
    return structuredClone(packet);
}
export function parseProposal(input) {
    const value = object(input, [
        "packetId",
        "action",
        "target",
        "reason",
        "evidenceIds"
    ]);
    if (typeof value.packetId !== "string" || ![
        "advance",
        "verify",
        "request_finish",
        "request_help"
    ].includes(value.action) || typeof value.target !== "string" || typeof value.reason !== "string" || value.reason.length > 2000 || !Array.isArray(value.evidenceIds) || value.evidenceIds.some((id)=>typeof id !== "string")) throw new ContractError("INVALID_PROPOSAL");
    return structuredClone(value);
}
export function authorizeProposal(input, packet, allowedTargets, seen) {
    const proposal = parseProposal(input);
    if (proposal.packetId !== packet.id || !allowedTargets.includes(proposal.target) || proposal.evidenceIds.some((id)=>!packet.references.some((ref)=>ref.id === id))) throw new ContractError("INVALID_PROPOSAL");
    const fingerprint = digest([
        packet.jobId,
        packet.specVersion,
        packet.snapshot,
        packet.policyDigest,
        packet.decisionRevision,
        packet.ownerEpoch,
        proposal.action,
        proposal.target,
        [
            ...new Set(proposal.evidenceIds)
        ].sort()
    ]);
    if (seen.has(fingerprint)) throw new ContractError("DUPLICATE_PROPOSAL");
    seen.add(fingerprint);
    return structuredClone({
        proposal,
        fingerprint,
        packetDigest: packet.digest,
        jobId: packet.jobId,
        specVersion: packet.specVersion,
        snapshot: packet.snapshot,
        policyDigest: packet.policyDigest,
        decisionRevision: packet.decisionRevision,
        ownerEpoch: packet.ownerEpoch
    });
}
export function recheck(contract, current, resourceAllowed, cancelled) {
    for (const key of [
        "jobId",
        "specVersion",
        "snapshot",
        "policyDigest",
        "decisionRevision",
        "ownerEpoch"
    ]){
        if (contract[key] !== current[key]) throw new ContractError("STALE_PROPOSAL");
    }
    if (cancelled) throw new ContractError("CONTROL_REVOKED");
    if (!resourceAllowed) throw new ContractError("RESOURCE_DENIED");
}
