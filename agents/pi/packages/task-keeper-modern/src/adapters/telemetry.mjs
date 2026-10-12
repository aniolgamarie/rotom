import { readFileSync, realpathSync, lstatSync } from "node:fs";
import { resolve, join } from "node:path";
import { homedir } from "node:os";
import { quotaTelemetry } from "../orchestration/policy.mjs";
export function readQuotaTelemetry(config, route, now = Date.now()) {
    if (!route.telemetry) return {
        status: "not_required",
        eligible: true,
        remaining: null
    };
    const binding = config.telemetryBindings[route.telemetry];
    if (!binding || binding.accountBinding !== route.accountBinding || binding.bucket !== route.quotaGroup) return {
        status: "unknown",
        eligible: false,
        remaining: null
    };
    try {
        const path = resolve(binding.path.startsWith("~/") ? join(homedir(), binding.path.slice(2)) : binding.path);
        const info = lstatSync(path);
        if (!info.isFile() || info.isSymbolicLink() || info.size > 65536 || (info.mode & 0o077) !== 0 || realpathSync(path) !== path) throw new Error("untrusted telemetry file");
        const observation = JSON.parse(readFileSync(path, "utf8"));
        const result = quotaTelemetry(observation, {
            account: binding.accountBinding,
            bucket: binding.bucket,
            source: binding.source,
            now,
            freshnessMs: binding.freshnessMs
        });
        return {
            ...result,
            eligible: result.status === "observed" && result.remaining !== null && result.remaining >= binding.minimumRemaining
        };
    } catch  {
        return {
            status: "unknown",
            eligible: false,
            remaining: null
        };
    }
}
