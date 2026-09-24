import { digest } from "../contracts/primitives.ts";

export function modelBindingDigest(model: { api: string; provider: string; id: string; baseUrl: string; reasoning: boolean;
  contextWindow: number; maxTokens: number; compat?: unknown; thinkingLevelMap?: unknown; samplingParams?: unknown; headers?: unknown; input?: unknown }) {
  return digest(JSON.parse(JSON.stringify({ api: model.api, provider: model.provider, id: model.id, baseUrl: model.baseUrl,
    reasoning: model.reasoning, contextWindow: model.contextWindow, maxTokens: model.maxTokens, compat: model.compat ?? null,
    thinkingLevelMap: model.thinkingLevelMap ?? null, samplingParams: model.samplingParams ?? null, headers: model.headers ?? null, input: model.input ?? null })));
}

export type Capability = "settled" | "continuationIdentity" | "termination" | "events" | "requestGate" | "readonly" | "workspace";
export interface AdapterIdentity {
  adapter: string; version: string; runtime: string; profileDigest: string; transportDigest: string; mode: string;
}
export interface Certification {
  identityDigest: string;
  capabilities: Partial<Record<Capability, { supported: boolean; testEvidence: string[]; level: "U" | "A" | "P" | "E" }>>;
}
export function capabilityStatus(identity: AdapterIdentity, certification: Certification | null, required: Capability[]) {
  const missing: string[] = [];
  if (!certification || certification.identityDigest !== digest(identity)) return { eligible: false, missing: ["certification_missing_or_stale"] };
  for (const cap of required) {
    const evidence = certification.capabilities[cap];
    if (!evidence?.supported || !evidence.testEvidence.length || evidence.level === "U") missing.push(cap);
  }
  return { eligible: missing.length === 0, missing };
}

/** Actual transport certification is separate from a model's requested capabilities. */
export function executionRequirements(kind: "inspect" | "fix" | "interactive", protectedRoute: boolean): Capability[] {
  const base: Capability[] = kind === "interactive" ? ["settled", "continuationIdentity", "termination", "events"]
    : kind === "inspect" ? ["events", "termination", "readonly"] : ["events", "termination", "workspace"];
  return protectedRoute ? [...base, "requestGate"] : base;
}
