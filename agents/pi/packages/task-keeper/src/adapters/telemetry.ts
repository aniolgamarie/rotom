import { readFileSync, realpathSync, lstatSync } from "node:fs";
import { resolve, join } from "node:path";
import { homedir } from "node:os";
import { quotaTelemetry, type QuotaTelemetry } from "../orchestration/policy.ts";
import type { Config, Route } from "../config.ts";

/** Optional user-owned normalized observation. Fetching service data remains the binding producer's job. */
export function readQuotaTelemetry(config: Config, route: Route, now = Date.now()) {
  if (!route.telemetry) return { status: "not_required" as const, eligible: true, remaining: null };
  const binding = config.telemetryBindings[route.telemetry];
  if (!binding || binding.accountBinding !== route.accountBinding || binding.bucket !== route.quotaGroup) return { status: "unknown" as const, eligible: false, remaining: null };
  try {
    const path = resolve(binding.path.startsWith("~/") ? join(homedir(), binding.path.slice(2)) : binding.path);
    const info = lstatSync(path);
    if (!info.isFile() || info.isSymbolicLink() || info.size > 65536 || (info.mode & 0o077) !== 0 || realpathSync(path) !== path) throw new Error("untrusted telemetry file");
    const observation = JSON.parse(readFileSync(path, "utf8")) as QuotaTelemetry;
    const result = quotaTelemetry(observation, { account: binding.accountBinding, bucket: binding.bucket, source: binding.source, now, freshnessMs: binding.freshnessMs });
    return { ...result, eligible: result.status === "observed" && result.remaining !== null && result.remaining >= binding.minimumRemaining };
  } catch { return { status: "unknown" as const, eligible: false, remaining: null }; }
}
