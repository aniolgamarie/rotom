// 可信父控制器的纯事实投影；不认证调用者、不签许可、不判断远端费用或终止。
import { types } from "node:util";
import { parseReviewResponse } from "./protocol.ts";

const code = "PI_RISK_REVIEW_SETTLEMENT_INVALID";
const bindingKeys = ["request_id", "operation_digest", "context_digest", "reviewer_identity"];
const wireResponseKeys = ["schema_version", ...bindingKeys, "decision", "reason_code"];
const required = ["schema_version", "phase", "outcome", "candidate", "binding", "requests", "request_count_scope", "wire"];
const allowed = [...required, "route_identity", "pricing_identity", "currency", "provider", "model", "remote_model_verified",
  "usage", "usage_late", "elapsed_ms", "model_wait_ms", "local_ms", "raw_event_count", "records", "product_gate"];
const wireKeys = ["invocations", "requests", "response_bytes", "body_complete", "redirect_blocked", "second_request_blocked", "failure_code"];
const outcomes = ["valid", "not-called", "policy-blocked", "human-required", "canceled", "timeout", "discarded", "transport-failure", "protocol-failure"];
function fail() { const error = new Error(code); error.code = code; throw error; }
function data(value, keys, mandatory = keys) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) fail();
  const names = Reflect.ownKeys(value);
  if (names.some(key => typeof key !== "string" || !keys.includes(key)) || mandatory.some(key => !names.includes(key))) fail();
  const copy = {};
  for (const key of names) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) fail();
    copy[key] = descriptor.value;
  }
  return copy;
}
function binding(value) {
  const copy = data(value, bindingKeys);
  for (const key of bindingKeys) if (typeof copy[key] !== "string" || !(key === "request_id" ? /^[0-9a-f]{32}$/ : /^[0-9a-f]{64}$/).test(copy[key])) fail();
  return copy;
}
const counter = value => Number.isSafeInteger(value) && value >= 0;
export function compileReviewTransportSettlement(snapshot, expectedBinding) {
  try {
    const expected = binding(expectedBinding), saved = data(snapshot, allowed, required), actual = binding(saved.binding);
    if (saved.schema_version !== 1 || saved.phase !== "settled" || typeof saved.outcome !== "string" || !outcomes.includes(saved.outcome)
        || saved.request_count_scope !== "local-platform-fetch-invocations" || !counter(saved.requests) || saved.requests > 1) fail();
    for (const key of bindingKeys) if (actual[key] !== expected[key]) fail();
    const wire = data(saved.wire, [...wireKeys, "gate_attempted", "gate_acknowledged"], wireKeys);
    if (wire.requests !== saved.requests || !counter(wire.invocations) || !counter(wire.response_bytes)
        || [wire.body_complete, wire.redirect_blocked, wire.second_request_blocked].some(value => typeof value !== "boolean")
        || wire.failure_code !== null && typeof wire.failure_code !== "string") fail();
    const gated = Object.hasOwn(wire, "gate_attempted");
    if (gated !== Object.hasOwn(wire, "gate_acknowledged") || gated &&
        (typeof wire.gate_attempted !== "boolean" || typeof wire.gate_acknowledged !== "boolean" || wire.gate_acknowledged && !wire.gate_attempted)) fail();
    let response = null;
    if (saved.outcome === "valid") {
      const captured = data(saved.candidate, [...wireResponseKeys, "source"]);
      if (captured.source !== "reviewer" || captured.schema_version !== 1 || wireResponseKeys.slice(1).some(key => typeof captured[key] !== "string" || captured[key].length > 8192)) fail();
      // 明确只序列化已捕获primitive七字段，不能触发外来toJSON或把source传Python。
      const candidateWire = {};
      for (const key of wireResponseKeys) candidateWire[key] = captured[key];
      const verified = parseReviewResponse(JSON.stringify(candidateWire), expected);
      const verifiedWire = {};
      for (const key of wireResponseKeys) verifiedWire[key] = verified[key];
      response = JSON.stringify(verifiedWire);
    } else if (saved.candidate !== null) fail();
    return Object.freeze({ outcome: saved.outcome, platform_requests: saved.requests, response,
      gate_attempted: gated ? wire.gate_attempted : false, gate_acknowledged: gated ? wire.gate_acknowledged : false });
  } catch { fail(); }
}
