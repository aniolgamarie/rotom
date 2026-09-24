import { resolveRecoveryTarget } from "../policies/recovery.ts";
import { configurationPolicy, type Config } from "../config.ts";
import { digest } from "../contracts/primitives.ts";
import type { InteractiveSnapshot, RecoveryRecord } from "./recovery.ts";

/** Pure admission decision shared by the timer and the final transport recheck.
 * Queue/native-tail state must come from the adapter; this is not termination proof. */
export function recoveryEligibility(config: Config,
  record: Pick<RecoveryRecord, "policyDigest" | "routeId" | "sessionId" | "leafId">,
  snapshot: InteractiveSnapshot): string | null {
  if (!config.enabled || !config.features.interactiveRecovery) return "interactive_recovery_disabled";
  if (record.policyDigest !== digest([configurationPolicy(config), snapshot.runtimeFingerprint ?? null])) return "policy_changed";
  let resolved;
  try { resolved = resolveRecoveryTarget(config, snapshot); } catch { return "route_not_allowed"; }
  const route = resolved.route;
  if (record.routeId !== resolved.routeId || (config.recovery.primaryRoute && !config.allowedRoutes.includes(record.routeId))) return "route_not_allowed";
  if (route.protected) return "request_gate_not_certified";
  if (snapshot.sessionId !== record.sessionId || snapshot.leafId !== record.leafId) return "session_or_leaf_changed";
  if (snapshot.provider !== route.provider || snapshot.model !== route.model) return "route_changed";
  if (!snapshot.certified) return "adapter_not_certified";
  if (!snapshot.terminationKnown || snapshot.blockedReasons.length) return "execution_or_mutator_unknown";
  if (!snapshot.idle || snapshot.pendingMessages) return "not_settled";
  return null;
}
