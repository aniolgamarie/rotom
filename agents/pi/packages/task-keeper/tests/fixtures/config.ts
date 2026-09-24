import { parseConfig } from "../../src/config.ts";

export function configured() {
  return parseConfig({ enabled: true, features: { interactiveRecovery: true }, allowedRoutes: ["primary"], projectRouteApprovals: { "*": ["primary"] },
    routes: { primary: { provider: "fixture-provider", model: "fixture-model", accountBinding: "provider:fixture-provider", quotaGroup: "pool", transportDomain: "fixture-domain", network: "local", protected: false } },
    executionProfiles: { interactive: { tools: ["read", "write", "edit"], requiredCapabilities: ["settled"], timeoutMs: 1000, maxModelTurns: 10, toolTimeoutMs: 500 } },
    network: { local: { type: "direct" } }, quotaGroups: { pool: { classifier: "http", rules: [{ code: "ResourcePressure", category: "resource_pressure" }], baseIntervalMs: 100, tailIntervalsMs: [100, 200, 400] } },
    recovery: { primaryRoute: "primary", profileRef: "interactive", requestTimeoutMs: 500, positiveJitterRatio: 0 } });
}
