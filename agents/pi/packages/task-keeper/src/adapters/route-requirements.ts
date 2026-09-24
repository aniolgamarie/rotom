import type { Profile } from "../config.ts";
import { modelBindingDigest } from "./capabilities.ts";

export type RuntimeModel = Parameters<typeof modelBindingDigest>[0];
/** Structural admission uses each route's own protocol/mapping; it does not rank model quality. */
export function routeRequirements(model: RuntimeModel | undefined, profile: Profile | undefined, role: "worker" | "scout" | "reviewer", protectedRoute: boolean) {
  const reasons: string[] = [];
  if (!model) return { eligible: false, reasons: ["model_not_in_registry"], bindingDigest: null, thinking: null };
  if (!profile) return { eligible: false, reasons: ["profile_not_bound"], bindingDigest: null, thinking: null };
  if (model.api !== "openai-completions") reasons.push("protocol_not_certified");
  if (!Number.isSafeInteger(model.contextWindow) || model.contextWindow <= 0 || !Number.isSafeInteger(model.maxTokens) || model.maxTokens <= 0) reasons.push("context_limits_unknown");
  if (profile.minimumContextTokens !== undefined && model.contextWindow < profile.minimumContextTokens) reasons.push("required_context_not_available");
  const expected = role === "worker" ? ["read", "grep", "find", "ls", "write", "edit"] : ["read", "grep", "find", "ls"];
  if (profile.tools.some(tool => !expected.includes(tool)) || expected.some(tool => !profile.tools.includes(tool))) reasons.push("tool_profile_mismatch");
  const capabilities = new Set(["events", "termination", "workspace", ...(role === "worker" ? [] : ["readonly"]), ...(protectedRoute ? ["requestGate"] : [])]);
  for (const required of profile.requiredCapabilities) if (!capabilities.has(required)) reasons.push(`capability_not_certified:${required}`);
  const level = profile.thinking;
  const mapping = model.thinkingLevelMap as Record<string, unknown> | undefined;
  // Matches the pinned SDK's supported-level/clamping contract; a clamp is not accepted as the requested level.
  if (!level || !["off", "minimal", "low", "medium", "high", "xhigh", "max"].includes(level)
    || (!model.reasoning && level !== "off") || (model.reasoning && mapping?.[level] === null)
    || (["xhigh", "max"].includes(level) && mapping?.[level] === undefined)) reasons.push("thinking_level_not_supported");
  return { eligible: reasons.length === 0, reasons, bindingDigest: modelBindingDigest(model),
    thinking: { requested: level ?? null, mapped: level ? mapping?.[level] ?? level : null, api: model.api } };
}
