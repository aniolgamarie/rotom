import { windowsOverlap } from "./calendar.ts";
import { ContractError, finiteInteger, object, digest } from "../contracts/primitives.ts";
import type { Config, Rule } from "../config.ts";

export interface Window { days: number[]; start: string; end: string }
export interface ModelReference { provider: string; model: string }
export interface RetryPolicy {
  quotaBackoff: string[]; repeatLast: boolean; maxLocalInterval: string; positiveJitterRatio: number;
  maxWait: string | null; requestTimeout: string; maxNetworkAttempts: number; unknownReset: "pause" | "configured-backoff";
  respectRetryAfter: true; rules: Rule[];
}
export type PolicyPatch = Partial<RetryPolicy>;
export interface RecoveryPolicies {
  defaults: RetryPolicy;
  providers: Record<string, PolicyPatch & { models?: Record<string, PolicyPatch> }>;
  legacy: Record<string, { quotaGroup: string }>;
}
export interface PriceBook {
  id: string; provider: string; model: string; accountPlanRef: string | null; currency: string; source: string;
  effectiveFrom: string; effectiveUntil: string | null; timing: "request-start" | "response-end" | "unknown";
  timezone: string; rates: { input: string | null; output: string | null; cacheRead: string | null; cacheWrite: string | null };
  windows: Array<{ window: Window; rates: PriceBook["rates"] }>;
}
export interface R2Fields {
  usage: { enabled: boolean; defaultRangeDays: number; priceBooks: PriceBook[]; accountPlans?: Array<{provider:string;model?:string;accountPlanRef:string}> };
  secondOpinion: { enabled: boolean; model: ModelReference | string | null; profileRef: string | null; reviewTask: string; focus: string[]; maxExchanges: number };
  timePolicy: { timezone: string; windows: Window[]; admissionBoundary: "task-start"; missed: "pause" };
  modelPolicy: { automaticSelection: boolean; ranking: "ordered" | "history-cost"; candidates: Array<ModelReference | string>;
    preferByTime: Array<{ priority: number; window: Window; orderedCandidates: Array<ModelReference | string> }>;
    defaultPreference: Array<ModelReference | string>; history: { rangeDays: number; minimumVerifiedTasks: number; minimumSuccessRate: number } };
  quotaBindings: Array<{ provider: string; model?: string; quotaGroup: string; transportDomain?: string }>;
}
export const DEFAULT_RETRY_POLICY: RetryPolicy = { quotaBackoff: ["1m", "5m", "15m", "30m", "1h"], repeatLast: true,
  maxLocalInterval: "1h", positiveJitterRatio: 0.1, maxWait: "24h", requestTimeout: "2m", maxNetworkAttempts: 2,
  unknownReset: "pause", respectRetryAfter: true, rules: [] };
export const DEFAULT_R2: R2Fields = {
  usage: { enabled: true, defaultRangeDays: 30, priceBooks: [] },
  secondOpinion: { enabled: false, model: null, profileRef: null, reviewTask: "Independently inspect the current task, candidate and verification evidence. Identify blocking issues with concrete evidence.", focus: [], maxExchanges: 2 },
  timePolicy: { timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, windows: [], admissionBoundary: "task-start", missed: "pause" },
  modelPolicy: { automaticSelection: false, ranking: "ordered", candidates: [], preferByTime: [], defaultPreference: [], history: { rangeDays: 30, minimumVerifiedTasks: 5, minimumSuccessRate: 0.8 } },
  quotaBindings: [],
};
export function duration(value: unknown): number {
  if (typeof value !== "string") throw new ContractError("INVALID_DURATION");
  const match = /^([1-9]\d*)(ms|s|m|h|d)$/.exec(value);
  if (!match) throw new ContractError("INVALID_DURATION");
  const factors: Record<string, number> = { ms: 1, s: 1000, m: 60000, h: 3600000, d: 86400000 };
  const amount = Number(match[1]) * factors[match[2]];
  finiteInteger(amount, 1, 2147483647); return amount;
}
export function instant(value: unknown): number {
  if (typeof value !== "string" || !/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d{1,3})?)?(?:Z|[+-]\d\d:\d\d)$/.test(value)) throw new ContractError("ABSOLUTE_TIME_REQUIRED");
  const parts = value.slice(0,10).split("-").map(Number), day = new Date(0);
  day.setUTCFullYear(parts[0],parts[1]-1,parts[2]);
  if(day.getUTCFullYear()!==parts[0] || day.getUTCMonth()!==parts[1]-1 || day.getUTCDate()!==parts[2])throw new ContractError("INVALID_TIME");
  if(Number(value.slice(11,13))>23 || Number(value.slice(14,16))>59)throw new ContractError("INVALID_TIME");
  const time = Date.parse(value); if (!Number.isFinite(time)) throw new ContractError("INVALID_TIME"); return time;
}
export function timezone(value: string): void {
  if(typeof value!=="string" || /^[+-]/.test(value))throw new ContractError("INVALID_TIMEZONE");
  try { new Intl.DateTimeFormat("en-US", { timeZone: value }).format(0); } catch { throw new ContractError("INVALID_TIMEZONE"); }
}
export function validateWindow(value: Window): void {
  object(value, ["days", "start", "end"]);
  if (!Array.isArray(value.days) || !value.days.length || new Set(value.days).size !== value.days.length
    || value.days.some(day => !Number.isInteger(day) || day < 1 || day > 7)
    || ![value.start, value.end].every(s => typeof s === "string" && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(s)) || value.start === value.end) throw new ContractError("INVALID_TIME_WINDOW");
}
const policyKeys = Object.keys(DEFAULT_RETRY_POLICY);
function validatePolicy(patch: PolicyPatch, base: RetryPolicy = DEFAULT_RETRY_POLICY): RetryPolicy {
  object(patch, policyKeys);
  const policy = { ...base, ...patch };
  if (!Array.isArray(policy.quotaBackoff) || !policy.quotaBackoff.length) throw new ContractError("EMPTY_BACKOFF");
  const maximum = duration(policy.maxLocalInterval);
  if (policy.quotaBackoff.some(v => duration(v) > maximum)) throw new ContractError("BACKOFF_EXCEEDS_LOCAL_MAXIMUM");
  duration(policy.requestTimeout); if (policy.maxWait !== null) duration(policy.maxWait);
  finiteInteger(policy.maxNetworkAttempts);
  if (typeof policy.repeatLast !== "boolean" || !["pause", "configured-backoff"].includes(policy.unknownReset)
    || policy.respectRetryAfter !== true || !Number.isFinite(policy.positiveJitterRatio) || policy.positiveJitterRatio < 0 || policy.positiveJitterRatio > 1
    || !Array.isArray(policy.rules)) throw new ContractError("INVALID_RECOVERY_POLICY");
  for (const rule of policy.rules) {
    object(rule, ["code", "messageIncludes", "category"]);
    if ((!rule.code && !rule.messageIncludes) || !["frequency_limit","resource_pressure","window_quota","network_overload","auth_billing_policy","context_contract","execution_unknown","other"].includes(rule.category)) throw new ContractError("INVALID_CLASSIFICATION_RULE");
  }
  return policy;
}
export function validateR2(config: Config): void {
  validatePolicy(config.recovery.policies.defaults);
  for (const value of Object.values(config.recovery.policies.providers)) {
    const { models = {}, ...patch } = value; const base = validatePolicy(patch, config.recovery.policies.defaults);
    for (const model of Object.values(models)) validatePolicy(model, base);
  }
  for (const policy of Object.values(config.recovery.policies.legacy)) if (!config.quotaGroups[policy.quotaGroup]) throw new ContractError("UNKNOWN_LEGACY_QUOTA_POLICY");
  timezone(config.timePolicy.timezone); config.timePolicy.windows.forEach(validateWindow);
  if (config.timePolicy.admissionBoundary !== "task-start") throw new ContractError("REQUEST_WINDOW_NOT_SUPPORTED");
  for (const row of config.modelPolicy.preferByTime) validateWindow(row.window);
  for (const binding of config.quotaBindings) if (!config.quotaGroups[binding.quotaGroup]) throw new ContractError("INVALID_QUOTA_BINDING");
  const plans=config.usage.accountPlans??[];
  if(new Set(plans.map(row=>JSON.stringify([row.provider,row.model??null]))).size!==plans.length)throw new ContractError("DUPLICATE_ACCOUNT_PLAN_BINDING");
  const quotes = config.usage.priceBooks;
  for (const q of quotes) {
    timezone(q.timezone); instant(q.effectiveFrom); if (q.effectiveUntil !== null && instant(q.effectiveUntil) <= instant(q.effectiveFrom)) throw new ContractError("INVALID_PRICE_INTERVAL");
    q.windows.forEach(row => validateWindow(row.window));
    for(let i=0;i<q.windows.length;i++)for(let j=i+1;j<q.windows.length;j++)if(windowsOverlap(q.windows[i].window,q.windows[j].window))throw new ContractError("OVERLAPPING_PRICE_WINDOWS");
    for (const rates of [q.rates, ...q.windows.map(w => w.rates)]) for (const v of Object.values(rates)) if (v !== null && !/^(?:0|[1-9]\d*)(?:\.\d{1,12})?$/.test(v)) throw new ContractError("INVALID_PRICE");
  }
  if (new Set(quotes.map(q => q.id)).size !== quotes.length) throw new ContractError("DUPLICATE_PRICE_BOOK");
  for (let i = 0; i < quotes.length; i++) for (let j = i + 1; j < quotes.length; j++) {
    const a = quotes[i], b = quotes[j];
    if (a.provider === b.provider && a.model === b.model && a.accountPlanRef === b.accountPlanRef
      && instant(a.effectiveFrom) < (b.effectiveUntil === null ? Infinity : instant(b.effectiveUntil))
      && instant(b.effectiveFrom) < (a.effectiveUntil === null ? Infinity : instant(a.effectiveUntil))) throw new ContractError("OVERLAPPING_PRICE_BOOKS");
  }
}
const string = { type: "string", minLength: 1 }, boolean = { type: "boolean" }, number = { type: "number", minimum: 0, maximum: 1 };
const int = (minimum = 0, maximum = Number.MAX_SAFE_INTEGER) => ({ type: "integer", minimum, maximum });
const array = (items: unknown) => ({ type: "array", items });
const shape = (properties: Record<string, unknown>, required = Object.keys(properties)) => ({ type: "object", properties, required, additionalProperties: false });
const nullable = (type: unknown) => ({ anyOf: [type, { type: "null" }] });
const map = (additionalProperties: unknown) => ({ type: "object", additionalProperties });
const model = { anyOf: [string, shape({ provider: string, model: string })] };
const window = shape({ days: { ...array(int(1, 7)), minItems: 1, uniqueItems: true }, start: string, end: string });
const rates = shape(Object.fromEntries(["input", "output", "cacheRead", "cacheWrite"].map(k => [k, nullable(string)])));
const policy = { quotaBackoff: array(string), repeatLast: boolean, maxLocalInterval: string, positiveJitterRatio: number, maxWait: nullable(string),
  requestTimeout: string, maxNetworkAttempts: int(), unknownReset: { enum: ["pause", "configured-backoff"] }, respectRetryAfter: { const: true },
  rules: array(shape({ code: string, messageIncludes: string, category: string }, ["category"])) };
export const POLICIES_SCHEMA = shape({ defaults: shape(policy), providers: map(shape({ ...policy, models: map(shape(policy, [])) }, [])), legacy: map(shape({ quotaGroup: string })) });
export const R2_SCHEMA = {
  usage: shape({ accountPlans:array(shape({provider:string,model:string,accountPlanRef:string},["provider","accountPlanRef"])), enabled: boolean, defaultRangeDays: int(1, 3650), priceBooks: array(shape({ id: string, provider: string, model: string, accountPlanRef: nullable(string), currency: string, source: string,
    effectiveFrom: string, effectiveUntil: nullable(string), timing: { enum: ["request-start", "response-end", "unknown"] }, timezone: string, rates, windows: array(shape({ window, rates })) })) },["enabled","defaultRangeDays","priceBooks"]),
  secondOpinion: shape({ enabled: boolean, model: nullable(model), profileRef: nullable(string), reviewTask: string, focus: array(string), maxExchanges: int(0, 16) }),
  timePolicy: shape({ timezone: string, windows: array(window), admissionBoundary: { const: "task-start" }, missed: { const: "pause" } }),
  modelPolicy: shape({ automaticSelection: boolean, ranking: { enum: ["ordered", "history-cost"] }, candidates: array(model),
    preferByTime: array(shape({ priority: int(), window, orderedCandidates: array(model) })), defaultPreference: array(model),
    history: shape({ rangeDays: int(1, 3650), minimumVerifiedTasks: int(5), minimumSuccessRate: number }) }),
  quotaBindings: array(shape({ provider: string, model: string, quotaGroup: string, transportDomain: string }, ["provider", "quotaGroup"])),
};

/** In-memory migration. Writing user configuration is a separate explicit preview/apply action. */
export function migrateConfigInput(input: Record<string, unknown>): Record<string, unknown> {
  if (input.schemaVersion !== undefined && input.schemaVersion !== 6 && input.schemaVersion !== 7) throw new ContractError("UNSUPPORTED_CONFIG_VERSION");
  const result = structuredClone(input);
  const recipes = (result.workflow as { recipes?: unknown[] } | undefined)?.recipes;
  if (recipes?.includes("cascade")) throw new ContractError("CASCADE_REMOVED", "Automatic quality escalation was removed; remove cascade from workflow.recipes. History and availability fallback are retained.");
  result.schemaVersion = 7;
  const recovery = object(result.recovery ?? {});
  // An explicit legacy pool is a compatibility reference, not a new quota namespace.
  if (result.routes && result.quotaGroups && !recovery.policies) {
    const legacy: Record<string, { quotaGroup: string }> = {};
    for (const value of Object.values(object(result.routes))) {
      const route = object(value); const group = String(route.quotaGroup);
      if (object(result.quotaGroups)[group]) {
        const id = `legacy-${digest(group).slice(0, 16)}`;
        legacy[id] = { quotaGroup: group }; route.recoveryPolicy = id;
      }
    }
    recovery.policies = { legacy }; result.recovery = recovery;
  }
  if (input.schemaVersion !== 7 && recipes?.includes("critique") && !result.secondOpinion) {
    const role = (result.roles as Record<string, { route: string; profileRef: string }> | undefined)?.critic;
    result.secondOpinion = { enabled: true, model: role?.route ?? null, profileRef: role?.profileRef ?? null, maxExchanges: 1 };
  }
  return result;
}
