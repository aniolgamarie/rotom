import type { AdvisoryMode, EffectiveConfig, EnforcementMode } from "./types.ts";

type Environment = Record<string, string | undefined>;

const DEFAULT_REPEAT_LIMIT = 2;
const MIN_REPEAT_LIMIT = 1;
const MAX_REPEAT_LIMIT = 4;

export function readLoopGuardConfig(env?: Environment): EffectiveConfig {
  const fromManifest = env === undefined;
  if (env === undefined) {
    const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
    if (!runtime) throw new Error("AGENTCFG_RUNTIME_REQUIRED");
    const configured = runtime.manifest.options.loop_guard ?? {};
    const names: Record<string, string> = { enforcementMode: "PI_LOOP_GUARD_MODE", advisoryMode: "PI_LOOP_GUARD_ADVISORY_MODE",
      repeatLimit: "PI_LOOP_GUARD_REPEAT_LIMIT", failureLimit: "PI_LOOP_GUARD_FAILURE_LIMIT", responseRepeatLimit: "PI_LOOP_GUARD_RESPONSE_REPEAT_LIMIT",
      responseSimilarityThreshold: "PI_LOOP_GUARD_RESPONSE_SIMILARITY", windowMs: "PI_LOOP_GUARD_WINDOW_MS", maxEntries: "PI_LOOP_GUARD_MAX_ENTRIES",
      maxPendingCalls: "PI_LOOP_GUARD_MAX_PENDING_CALLS", maxIncidents: "PI_LOOP_GUARD_MAX_INCIDENTS", maxResponses: "PI_LOOP_GUARD_MAX_RESPONSES",
      maxCycleHistory: "PI_LOOP_GUARD_CYCLE_HISTORY", minResponseChars: "PI_LOOP_GUARD_MIN_RESPONSE_CHARS", contextMaxMessages: "PI_LOOP_GUARD_CONTEXT_MAX_MESSAGES",
      contextMaxChars: "PI_LOOP_GUARD_CONTEXT_MAX_CHARS", checkpointScanLimit: "PI_LOOP_GUARD_CHECKPOINT_SCAN_LIMIT" };
    if (!configured || typeof configured !== "object" || Array.isArray(configured)
        || Object.entries(configured).some(([key, value]) => !names[key] || typeof value !== (key.endsWith("Mode") ? "string" : "number"))) throw new Error("AGENTCFG_LOOP_GUARD_CONFIG");
    env = Object.fromEntries(Object.entries(configured).map(([key, value]) => [names[key], String(value)]));
  }
	const warnings: string[] = [];
	const enforcementMode = readEnforcementMode(env, warnings);
	const advisoryMode = readAdvisoryMode(env, warnings);

	const result = {
		enforcementMode,
		advisoryMode,
		repeatLimit: readBoundedInt(
			env,
			"PI_LOOP_GUARD_REPEAT_LIMIT",
			DEFAULT_REPEAT_LIMIT,
			MIN_REPEAT_LIMIT,
			MAX_REPEAT_LIMIT,
			warnings,
		),
		failureLimit: readBoundedInt(
			env,
			"PI_LOOP_GUARD_FAILURE_LIMIT",
			2,
			1,
			8,
			warnings,
		),
		responseRepeatLimit: readBoundedInt(
			env,
			"PI_LOOP_GUARD_RESPONSE_REPEAT_LIMIT",
			1,
			1,
			8,
			warnings,
		),
		responseSimilarityThreshold: readBoundedFloat(
			env,
			"PI_LOOP_GUARD_RESPONSE_SIMILARITY",
			0.82,
			0.5,
			1,
			warnings,
		),
		windowMs: readBoundedInt(
			env,
			"PI_LOOP_GUARD_WINDOW_MS",
			15 * 60 * 1000,
			10_000,
			24 * 60 * 60 * 1000,
			warnings,
		),
		maxEntries: readBoundedInt(env, "PI_LOOP_GUARD_MAX_ENTRIES", 200, 16, 1_000, warnings),
		maxPendingCalls: readBoundedInt(
			env,
			"PI_LOOP_GUARD_MAX_PENDING_CALLS",
			64,
			4,
			256,
			warnings,
		),
		maxIncidents: readBoundedInt(env, "PI_LOOP_GUARD_MAX_INCIDENTS", 32, 4, 128, warnings),
		maxResponses: readBoundedInt(env, "PI_LOOP_GUARD_MAX_RESPONSES", 12, 4, 64, warnings),
		maxCycleHistory: readBoundedInt(env, "PI_LOOP_GUARD_CYCLE_HISTORY", 18, 6, 96, warnings),
		minResponseChars: readBoundedInt(
			env,
			"PI_LOOP_GUARD_MIN_RESPONSE_CHARS",
			24,
			8,
			2_000,
			warnings,
		),
		contextMaxMessages: readBoundedInt(
			env,
			"PI_LOOP_GUARD_CONTEXT_MAX_MESSAGES",
			64,
			8,
			256,
			warnings,
		),
		contextMaxChars: readBoundedInt(
			env,
			"PI_LOOP_GUARD_CONTEXT_MAX_CHARS",
			24_000,
			2_000,
			100_000,
			warnings,
		),
		checkpointScanLimit: readBoundedInt(
			env,
			"PI_LOOP_GUARD_CHECKPOINT_SCAN_LIMIT",
			256,
			16,
			2_000,
			warnings,
		),
		warnings,
	};
  if (fromManifest && warnings.length) throw new Error("AGENTCFG_LOOP_GUARD_CONFIG");
  return result;
}

function readEnforcementMode(env: Environment, warnings: string[]): EnforcementMode {
	const explicit = env.PI_LOOP_GUARD_MODE?.trim().toLowerCase();
	if (explicit === "enforce" || explicit === "off") return explicit;
	if (explicit) warnings.push("PI_LOOP_GUARD_MODE is invalid; using the legacy enable setting");
	return env.PI_LOOP_GUARD === "0" ? "off" : "enforce";
}

function readAdvisoryMode(env: Environment, warnings: string[]): AdvisoryMode {
	const explicit = env.PI_LOOP_GUARD_ADVISORY_MODE?.trim().toLowerCase();
	if (explicit === "observe" || explicit === "off") return explicit;
	if (explicit) warnings.push("PI_LOOP_GUARD_ADVISORY_MODE is invalid; using the legacy response setting");
	return env.PI_LOOP_GUARD_RESPONSE === "0" ? "off" : "observe";
}

function readBoundedInt(
	env: Environment,
	name: string,
	fallback: number,
	minimum: number,
	maximum: number,
	warnings: string[],
): number {
	const raw = env[name];
	if (raw === undefined || raw.trim() === "") return fallback;
	const value = Number(raw);
	if (!Number.isFinite(value) || !Number.isInteger(value)) {
		warnings.push(`${name} is invalid; using ${fallback}`);
		return fallback;
	}
	if (value < minimum || value > maximum) {
		const bounded = Math.min(maximum, Math.max(minimum, value));
		warnings.push(`${name} is outside ${minimum}-${maximum}; using ${bounded}`);
		return bounded;
	}
	return value;
}

function readBoundedFloat(
	env: Environment,
	name: string,
	fallback: number,
	minimum: number,
	maximum: number,
	warnings: string[],
): number {
	const raw = env[name];
	if (raw === undefined || raw.trim() === "") return fallback;
	const value = Number(raw);
	if (!Number.isFinite(value)) {
		warnings.push(`${name} is invalid; using ${fallback}`);
		return fallback;
	}
	if (value < minimum || value > maximum) {
		const bounded = Math.min(maximum, Math.max(minimum, value));
		warnings.push(`${name} is outside ${minimum}-${maximum}; using ${bounded}`);
		return bounded;
	}
	return value;
}
