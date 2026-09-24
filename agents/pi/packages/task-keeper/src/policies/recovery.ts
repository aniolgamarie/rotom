import type { Config, Route, Rule } from "../config.ts";
import { ContractError, digest } from "../contracts/primitives.ts";
import { duration, type RetryPolicy } from "./configuration.ts";

export interface CurrentTarget { provider: string; model: string; transportIdentity?: string }
export interface ResolvedRecoveryPolicy {
  policy: RetryPolicy; sources: Record<keyof RetryPolicy, string>; intervals: number[];
  maxLocalIntervalMs: number; maxWaitMs: number | null; requestTimeoutMs: number;
}
/** Policy is independent of quota identity. A narrower classifier runs first. */
export function resolveRecoveryPolicy(config: Config, target: CurrentTarget, route?: Route): ResolvedRecoveryPolicy {
  let policy = structuredClone(config.recovery.policies.defaults);
  const sources = Object.fromEntries(Object.keys(policy).map(key => [key, "defaults"])) as Record<keyof RetryPolicy, string>;
  const rules: Rule[][] = [policy.rules];
  const apply = (patch: Partial<RetryPolicy>, source: string) => {
    for (const key of Object.keys(patch) as Array<keyof RetryPolicy>) sources[key] = source;
    policy = { ...policy, ...structuredClone(patch) }; if (patch.rules) rules.unshift(patch.rules);
  };
  if (route?.recoveryPolicy) {
    const reference = config.recovery.policies.legacy[route.recoveryPolicy];
    if (!reference) throw new ContractError("UNKNOWN_RECOVERY_POLICY");
    const pool = config.quotaGroups[reference.quotaGroup];
    const intervals = [pool.baseIntervalMs, ...pool.tailIntervalsMs];
    apply({ quotaBackoff: intervals.map(ms => `${ms}ms`), maxLocalInterval: `${Math.min(2147483647, Math.ceil(Math.max(...intervals) * (1 + config.recovery.positiveJitterRatio)))}ms`,
      repeatLast: true, positiveJitterRatio: config.recovery.positiveJitterRatio, maxWait: config.recovery.maxWaitMs === null ? null : `${config.recovery.maxWaitMs}ms`,
      requestTimeout: `${config.recovery.requestTimeoutMs}ms`, maxNetworkAttempts: config.recovery.maxNetworkAttempts, rules: pool.rules }, `legacy:${route.recoveryPolicy}`);
  }
  const { models = {}, ...provider } = config.recovery.policies.providers[target.provider] ?? {};
  apply(provider, `provider:${target.provider}`); apply(models[target.model] ?? {}, `model:${target.provider}/${target.model}`);
  policy.rules = rules.flat();
  if(policy.quotaBackoff.some(interval=>duration(interval)>duration(policy.maxLocalInterval)))throw new ContractError("BACKOFF_EXCEEDS_LOCAL_MAXIMUM");
  return { policy, sources, intervals: policy.quotaBackoff.map(duration), maxLocalIntervalMs: duration(policy.maxLocalInterval),
    maxWaitMs: policy.maxWait === null ? null : duration(policy.maxWait), requestTimeoutMs: duration(policy.requestTimeout) };
}
export function resolveRecoveryTarget(config: Config, target: CurrentTarget) {
  const explicit = config.recovery.primaryRoute;
  if (explicit) {
    const route = config.routes[explicit]; if (!route) throw new ContractError("UNKNOWN_ROUTE");
    return { routeId: explicit, route, ...resolveRecoveryPolicy(config, route, route) };
  }
  if (!target.provider || !target.model || target.provider === "unknown" || target.model === "unknown") throw new ContractError("CURRENT_MODEL_REQUIRED");
  const matching = config.quotaBindings.filter(binding => binding.provider === target.provider && (!binding.model || binding.model === target.model));
  const specific = matching.filter(binding => binding.model === target.model), candidates = specific.length ? specific : matching;
  if (candidates.length > 1) throw new ContractError("AMBIGUOUS_QUOTA_BINDING");
  const binding = candidates[0], accountBinding = `provider:${target.provider}`;
  const quotaGroup = binding?.quotaGroup ?? `current-${digest([accountBinding, target.model])}`;
  const route: Route = { provider: target.provider, model: target.model, accountBinding, quotaGroup,
    transportDomain: binding?.transportDomain ?? `current-${digest([accountBinding, target.transportIdentity ?? target.provider])}`,
    network: "direct", protected: false };
  return { routeId: `current-${digest([accountBinding, target.model, route.transportDomain])}`, route, ...resolveRecoveryPolicy(config, target) };
}
export function localRetryDelay(resolved: ResolvedRecoveryPolicy, failureIndex: number, sample: number): number | null {
  if (!Number.isInteger(failureIndex) || failureIndex < 0 || !Number.isFinite(sample) || sample < 0 || sample > 1) throw new ContractError("INVALID_RETRY_INPUT");
  if (failureIndex >= resolved.intervals.length && !resolved.policy.repeatLast) return null;
  const base = resolved.intervals[Math.min(failureIndex, resolved.intervals.length - 1)];
  return Math.min(resolved.maxLocalIntervalMs, base + Math.ceil(base * resolved.policy.positiveJitterRatio * sample));
}
