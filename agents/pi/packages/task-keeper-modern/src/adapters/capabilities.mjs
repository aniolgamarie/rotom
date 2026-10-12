import { digest } from "../contracts/primitives.mjs";
export function modelBindingDigest(model) {
    return digest(JSON.parse(JSON.stringify({
        api: model.api,
        provider: model.provider,
        id: model.id,
        baseUrl: model.baseUrl,
        reasoning: model.reasoning,
        contextWindow: model.contextWindow,
        maxTokens: model.maxTokens,
        compat: model.compat ?? null,
        thinkingLevelMap: model.thinkingLevelMap ?? null,
        samplingParams: model.samplingParams ?? null,
        headers: model.headers ?? null,
        input: model.input ?? null
    })));
}
export function capabilityStatus(identity, certification, required) {
    const missing = [];
    if (!certification || certification.identityDigest !== digest(identity)) return {
        eligible: false,
        missing: [
            "certification_missing_or_stale"
        ]
    };
    for (const cap of required){
        const evidence = certification.capabilities[cap];
        if (!evidence?.supported || !evidence.testEvidence.length || evidence.level === "U") missing.push(cap);
    }
    return {
        eligible: missing.length === 0,
        missing
    };
}
export function executionRequirements(kind, protectedRoute) {
    const base = kind === "interactive" ? [
        "settled",
        "continuationIdentity",
        "termination",
        "events"
    ] : kind === "inspect" ? [
        "events",
        "termination",
        "readonly"
    ] : [
        "events",
        "termination",
        "workspace"
    ];
    return protectedRoute ? [
        ...base,
        "requestGate"
    ] : base;
}
