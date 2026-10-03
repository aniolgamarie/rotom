import type { PermissionLedger } from "./controller";

export const PERMISSION_USAGE = ["smart", "manual", "status", "explain"]
  .map((command) => `/permission-control ${command}`).join("\n");
export type CommandServices = Pick<PermissionLedger, "snapshot" | "explain" | "setMode">;

/** 仅由宿主认证的真实命令通道调用；该窄接口没有请求、人工批准和许可能力。 */
export function handleSessionCommand(args: string, services: CommandServices): string {
  const command = args.trim();
  if (!["smart", "manual", "status", "explain"].includes(command)) return PERMISSION_USAGE;
  if (command === "explain") return JSON.stringify(services.explain());
  if (command === "smart" || command === "manual") {
    const before = services.snapshot();
    const reviewerReady = (before.reviewer_state ? before.reviewer_state === "ready" : before.reviewer !== "unavailable") ||
      before.remote_fallback_state === "ready";
    const healthy = before.bridge_health === "healthy" && before.identity_verified &&
      reviewerReady && Object.values(before.native_protection).every(Boolean);
    const effective = command === "smart" && healthy ? "smart" : "manual";
    services.setMode(effective);
    const state = services.snapshot();
    return JSON.stringify({ state: command === "smart" && !healthy ? "smart-unavailable" : "mode-updated",
      mode: state.active_mode, source: state.mode_source, generation: state.generation,
      health: state.bridge_health, ...(effective === "manual" ? { reviewer: "not-called-in-manual" } : {}) });
  }
  const state = services.snapshot();
  return JSON.stringify({ configuredMode: state.configured_mode, activeMode: state.active_mode,
    modeSource: state.mode_source, generation: state.generation, reviewer: state.reviewer,
    reviewerHealth: state.reviewer_state ?? (state.reviewer === "unavailable" ? "unavailable" : "ready"),
    reviewerSource: state.reviewer === "unavailable" ? "unavailable" :
      state.reviewer_selection === "explicit" ? "explicit-profile" : "session-default",
    ...(state.remote_fallback_state ? { remoteFallback: state.remote_fallback,
      remoteFallbackHealth: state.remote_fallback_state, remoteFallbackSource: "remote-fallback" } : {}),
    fallback: state.fallback_state === "disabled" ? "disabled" : "local/lfm2.5-230m",
    fallbackLimit: "ask-or-deny-only; installed-only; never-allow", fallbackHealth: state.fallback_state,
    coverage: state.coverage, executionLimits: state.coverage.reasons,
    nativeProtection: state.native_protection,
    childAndHeadless: "native-prompt-or-block; no-smart-permit-inheritance; no-yolo",
    bridge: { abi: "permission-control/v1", health: state.bridge_health, identityVerified: state.identity_verified },
    policyVersion: state.policy_version, pending: state.pending,
    unverified: ["real-model-quality", "real-host-smoke", "non-linux-platforms"] });
}
