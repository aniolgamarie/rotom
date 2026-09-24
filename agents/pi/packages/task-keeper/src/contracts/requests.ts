// 受管请求协议独立于旧交互恢复桶；状态和费用未知值不相互替代。
import { closed, reject, sha, text } from "@agentcfg/pi-runtime/managed-types";

export type ManagedRequestState = "reserved" | "sent" | "settled" | "unknown";
export interface ManagedRequest {
  task_id: string; attempt_id: string; request_id: string; reason: string; turn_id: string;
  route_id: string; grant_digest: string; payload_digest: string;
  reserved_input_tokens: number | null; reserved_output_tokens: number | null; reserved_cost: string | null;
}
export function assertRequest(value: any): ManagedRequest {
  closed(value, ["task_id", "attempt_id", "request_id", "reason", "turn_id", "route_id", "grant_digest", "payload_digest",
    "reserved_input_tokens", "reserved_output_tokens", "reserved_cost"]);
  if (["task_id", "attempt_id", "request_id", "reason", "turn_id", "route_id"].some(key => !text(value[key]))
      || !sha(value.grant_digest) || !sha(value.payload_digest)
      || [value.reserved_input_tokens, value.reserved_output_tokens].some(number => number !== null && (!Number.isSafeInteger(number) || number < 0))
      || value.reserved_cost !== null && (typeof value.reserved_cost !== "string" || !/^[0-9]+(?:\.[0-9]{1,18})?$/.test(value.reserved_cost))) reject();
  return value;
}

export function assertReservation(value: any) {
  const requestFields = ["task_id", "attempt_id", "request_id", "reason", "turn_id", "route_id", "grant_digest", "payload_digest",
    "reserved_input_tokens", "reserved_output_tokens", "reserved_cost"];
  closed(value, [...requestFields, "schema_version", "reservation_id", "budget_scope_id", "ordinal", "request_digest", "turn_key", "state",
    "accounted_tokens", "accounted_cost_units", "observed_usage_id", "settled_usage", "never_sent", "reserved_at", "sent_at", "settled_at"]);
  assertRequest(Object.fromEntries(requestFields.map(key => [key, value[key]])));
  if (value.schema_version !== 1 || !text(value.reservation_id) || !text(value.budget_scope_id) || !sha(value.request_digest) || !sha(value.turn_key)
      || !Number.isSafeInteger(value.ordinal) || value.ordinal < 1 || !Number.isSafeInteger(value.accounted_tokens) || value.accounted_tokens < 0
      || typeof value.accounted_cost_units !== "string" || !/^[0-9]+$/.test(value.accounted_cost_units)
      || !["reserved", "sent", "settled", "unknown"].includes(value.state) || typeof value.never_sent !== "boolean"
      || value.observed_usage_id !== null && !text(value.observed_usage_id)) reject();
  if (!Number.isSafeInteger(value.reserved_at) || value.reserved_at < 0 || [value.sent_at, value.settled_at].some(at => at !== null && (!Number.isSafeInteger(at) || at < value.reserved_at))) reject();
  if (value.state === "settled") {
    closed(value.settled_usage, ["input_tokens", "output_tokens", "cost"]);
    if ([value.settled_usage.input_tokens, value.settled_usage.output_tokens].some(number => number !== null && (!Number.isSafeInteger(number) || number < 0))
        || value.settled_usage.cost !== null && (typeof value.settled_usage.cost !== "string" || !/^[0-9]+(?:\.[0-9]{1,18})?$/.test(value.settled_usage.cost))) reject();
  } else if (value.settled_usage !== null || value.observed_usage_id !== null || value.never_sent) reject();
  return value;
}
