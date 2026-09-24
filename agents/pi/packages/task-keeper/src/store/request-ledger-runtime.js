// 所有模型请求共用任务账本；统计分组和 fresh attempt 都不能重置预算。
import { assertRequest, assertReservation } from "../contracts/requests.ts";
import { randomUUID } from "node:crypto";
import { canonical, clone, closed, digest, reject, sha, text } from "@agentcfg/pi-runtime/managed-types";

const scale = 10n ** 18n;
function money(value) {
  if (value === null) return null;
  if (typeof value !== "string" || !/^[0-9]+(?:\.[0-9]{1,18})?$/.test(value)) reject("COST_BOUND_INVALID", 2);
  const [whole, fraction = ""] = value.split(".");
  return BigInt(whole) * scale + BigInt(fraction.padEnd(18, "0"));
}
function tokens(value) { return value === null || Number.isSafeInteger(value) && value >= 0; }


export class RequestLedger {
  constructor({ store, task_id, budget_scope_id, limits, verify, minimum_remaining = 0, now = () => Date.now() }) {
    closed(limits, ["model_requests", "model_turns", "deadline"], ["token_limit", "cost_limit"]);
    if (!text(task_id) || !text(budget_scope_id) || !Number.isSafeInteger(limits.model_requests) || limits.model_requests < 1
        || !Number.isSafeInteger(limits.model_turns) || limits.model_turns < 1 || !Number.isFinite(Date.parse(limits.deadline))
        || Object.hasOwn(limits, "token_limit") && (!Number.isSafeInteger(limits.token_limit) || limits.token_limit < 1)
        || typeof verify !== "function") reject();
    if (Object.hasOwn(limits, "cost_limit")) money(limits.cost_limit);
    if (!Number.isSafeInteger(minimum_remaining) || minimum_remaining < 0) reject();
    this.minimumRemaining = minimum_remaining;
    this.store = store; this.taskId = task_id; this.scope = budget_scope_id;
    this.limits = clone(limits); this.verify = verify; this.now = now;
  }
  async transaction(operation) {
    let result;
    await this.store.transaction(async state => {
      state.request_budgets ??= {};
      const key = digest(this.taskId);
      const budget = state.request_budgets[key] ??= { schema_version: 1, task_id: this.taskId, budget_scope_id: this.scope, limits_digest: digest(this.limits),
        requests_used: 0, turns_used: 0, tokens_used: 0, cost_units: "0", ordinal: 0, requests: {}, turns: {} };
      try {
        closed(budget, ["schema_version", "task_id", "budget_scope_id", "limits_digest", "requests_used", "turns_used", "tokens_used", "cost_units", "ordinal", "requests", "turns"]);
        if (budget.schema_version !== 1 || budget.task_id !== this.taskId) reject();
        for (const record of Object.values(budget.requests)) assertReservation(record);
      } catch { reject("BUDGET_STORE_VERSION", 4); }
      if (budget.budget_scope_id !== this.scope || budget.limits_digest !== digest(this.limits)) reject("BUDGET_SCOPE_MISMATCH", 4);
      result = await operation(budget);
    });
    return result;
  }
  admission(request) {
    if (Date.parse(this.limits.deadline) <= this.now()) reject("DEADLINE_EXCEEDED", 4);
    const proof = this.verify(clone(request));
    if (!proof || proof.valid !== true || proof.route_id !== request.route_id || proof.grant_digest !== request.grant_digest) reject("GRANT_STALE", 4);
    if ((this.limits.token_limit !== undefined || this.limits.cost_limit !== undefined) && proof.bounds_certified !== true) reject("UNBOUNDED_REQUEST", 5);
  }
  async reserve(request) {
    assertRequest(request);
    if (request.task_id !== this.taskId) reject("BUDGET_SCOPE_MISMATCH", 4);
    return this.transaction(budget => {
      const key = digest(request.request_id);
      const existing = budget.requests[key];
      if (existing) {
        if (existing.request_digest !== digest(request)) reject("RESERVATION_CONFLICT", 4);
        return clone(existing);
      }
      this.admission(request);
      if (this.limits.token_limit !== undefined && (request.reserved_input_tokens === null || request.reserved_output_tokens === null)
          || this.limits.cost_limit !== undefined && request.reserved_cost === null) reject("UNBOUNDED_REQUEST", 5);
      const reservedTokens = (request.reserved_input_tokens ?? 0) + (request.reserved_output_tokens ?? 0);
      const reservedCost = money(request.reserved_cost) ?? 0n;
      const turnKey = digest({ attempt_id: request.attempt_id, turn_id: request.turn_id });
      const newTurn = !budget.turns[turnKey];
      if (!Number.isSafeInteger(budget.tokens_used + reservedTokens) || budget.requests_used + 1 + this.minimumRemaining > this.limits.model_requests
          || budget.turns_used + Number(newTurn) > this.limits.model_turns
          || this.limits.token_limit !== undefined && budget.tokens_used + reservedTokens > this.limits.token_limit
          || this.limits.cost_limit !== undefined && BigInt(budget.cost_units) + reservedCost > money(this.limits.cost_limit)) reject("BUDGET_EXHAUSTED", 4);
      budget.requests_used++;
      budget.turns_used += Number(newTurn);
      budget.tokens_used += reservedTokens;
      budget.cost_units = String(BigInt(budget.cost_units) + reservedCost);
      budget.turns[turnKey] = (budget.turns[turnKey] ?? 0) + 1;
      const record = { schema_version: 1, ...clone(request), reservation_id: randomUUID(), budget_scope_id: this.scope, ordinal: ++budget.ordinal,
        reserved_at: this.now(), sent_at: null, settled_at: null, request_digest: digest(request), turn_key: turnKey, state: "reserved", accounted_tokens: reservedTokens,
        accounted_cost_units: String(reservedCost), observed_usage_id: null, settled_usage: null, never_sent: false };
      budget.requests[key] = record;
      return clone(record);
    });
  }
  async mark_sent(requestId) {
    return this.transaction(budget => {
      const record = budget.requests[digest(requestId)];
      if (!record || record.state !== "reserved") reject("REQUEST_ALREADY_SENT_OR_UNKNOWN", 4);
      this.admission(record);
      record.state = "sent";
      record.sent_at = this.now();
      return clone(record);
    });
  }
  async mark_unknown(requestId) {
    return this.transaction(budget => {
      const record = budget.requests[digest(requestId)];
      if (!record || !["reserved", "sent", "unknown"].includes(record.state)) reject("REQUEST_STATE", 4);
      record.state = "unknown";
      return clone(record);
    });
  }
  async settle(requestId, result) {
    closed(result, ["usage_id", "input_tokens", "output_tokens", "cost"], ["never_sent"]);
    const { usage_id, input_tokens, output_tokens, cost, never_sent = false } = result;
    const usage = { input_tokens, output_tokens, cost };
    if (!tokens(input_tokens) || !tokens(output_tokens) || !(usage_id === null || text(usage_id)) || typeof never_sent !== "boolean") reject();
    money(cost);
    return this.transaction(budget => {
      const record = budget.requests[digest(requestId)];
      if (!record) reject("REQUEST_STATE", 4);
      if (record.state === "settled") {
        if (canonical(record.settled_usage) !== canonical(usage) || record.observed_usage_id !== usage_id || record.never_sent !== never_sent) reject("USAGE_CONFLICT", 4);
        return clone(record);
      }
      if (never_sent && (record.state !== "reserved" || input_tokens !== 0 || output_tokens !== 0 || money(cost) !== 0n)) reject("REFUND_UNPROVEN", 4);
      if (!never_sent && record.state === "reserved") reject("REQUEST_NOT_SENT", 4);
      const actualTokens = input_tokens === null || output_tokens === null ? record.accounted_tokens : input_tokens + output_tokens;
      const actualCost = money(cost) ?? BigInt(record.accounted_cost_units);
      if (!Number.isSafeInteger(budget.tokens_used + actualTokens - record.accounted_tokens)) reject("USAGE_INVALID", 4);
      budget.tokens_used += actualTokens - record.accounted_tokens;
      budget.cost_units = String(BigInt(budget.cost_units) + actualCost - BigInt(record.accounted_cost_units));
      if (never_sent) {
        budget.requests_used--;
        if (--budget.turns[record.turn_key] === 0) {
          delete budget.turns[record.turn_key];
          budget.turns_used--;
        }
      }
      record.state = "settled";
      record.settled_at = this.now();
      record.observed_usage_id = usage_id;
      record.settled_usage = usage;
      record.never_sent = never_sent;
      record.accounted_tokens = actualTokens;
      record.accounted_cost_units = String(actualCost);
      return clone(record);
    });
  }
  async summary() {
    return this.transaction(budget => ({ task_id: budget.task_id, budget_scope_id: budget.budget_scope_id,
      requests_used: budget.requests_used, turns_used: budget.turns_used, tokens_used: budget.tokens_used,
      cost_reserved_units: budget.cost_units, unknown_requests: Object.values(budget.requests).filter(record => record.state === "unknown").length }));
  }
}
