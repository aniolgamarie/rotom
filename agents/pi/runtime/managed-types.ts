// managed-executor-v1 的封闭边界；数据校验不执行模型、工具或子进程。
import { createHash } from "node:crypto";
import { isAbsolute } from "node:path";

const protocolErrorBrand = Symbol.for("agentcfg.pi.protocol-error.v1");
export class ProtocolError extends Error {
  constructor(code, exitCode = 4) { super(code); this.code = code; this.exitCode = exitCode; Object.defineProperty(this, protocolErrorBrand, { value: true }); }
}
export const isProtocolError = value => value?.[protocolErrorBrand] === true && typeof value.code === "string"
  && /^[A-Z][A-Z0-9_]+$/.test(value.code) && [2, 3, 4, 5, 6].includes(value.exitCode);
export const reject = (code = "PROTOCOL_INVALID", exitCode = 2) => { throw new ProtocolError(code, exitCode); };
export const text = value => typeof value === "string" && value.length > 0 && !value.includes("\0") && !/[\uD800-\uDFFF]/u.test(value);
export const sha = value => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
export const list = value => Array.isArray(value) && value.every(text) && new Set(value).size === value.length;
export function closed(value, required, optional = []) {
  if (!value || Object.getPrototypeOf(value) !== Object.prototype || required.some(key => !Object.hasOwn(value, key))
      || Object.keys(value).some(key => !required.includes(key) && !optional.includes(key))) reject();
}
export function canonical(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean" || (typeof value === "number" && Number.isFinite(value))) return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (!value || Object.getPrototypeOf(value) !== Object.prototype) reject();
  return "{" + Object.keys(value).sort().map(key => JSON.stringify(key) + ":" + canonical(value[key])).join(",") + "}";
}
export const digest = value => createHash("sha256").update(canonical(value) + "\n").digest("hex");
export const clone = value => JSON.parse(canonical(value));

export function assertOwner(owner) {
  closed(owner, ["instance_id", "manager_activation_id", "owner_nonce"]);
  if (!Object.values(owner).every(text)) reject();
  return owner;
}

export function assertRule(rule) {
  const common = ["id", "kind", "effect", "tool_ids", "operations"];
  if (rule?.kind === "file") closed(rule, [...common, "root_ref", "relative_path", "match"]);
  else if (rule?.kind === "command") closed(rule, [...common, "command_ref"]);
  else reject();
  if (!/^[a-z][a-z0-9_-]{0,63}$/.test(rule.id) || !["allow", "deny"].includes(rule.effect) || !list(rule.tool_ids) || !rule.tool_ids.length
      || !list(rule.operations) || !rule.operations.length) reject();
  if (rule.kind === "file") {
    if (!/^[a-z][a-z0-9_-]{0,63}$/.test(rule.root_ref) || !text(rule.relative_path) || !["exact", "subtree"].includes(rule.match)
        || isAbsolute(rule.relative_path) || rule.relative_path.includes("\\")
        || rule.relative_path !== "." && rule.relative_path.split("/").some(part => !part || part === "." || part === "..")
        || rule.operations.some(op => !["read", "list", "search", "write", "create", "delete", "rename"].includes(op))) reject();
  } else if (!/^(check|tool):[a-z][a-z0-9_-]{0,63}$/.test(rule.command_ref) || canonical(rule.operations) !== '["execute"]') reject();
  return rule;
}

export function assertProcess(value) {
  closed(value, ["platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid"]);
  if (!["linux", "darwin"].includes(value.platform) || !text(value.boot_id) || !text(value.start_time)
      || ["pid", "pgid"].some(key => !Number.isSafeInteger(value[key]) || value[key] < 1)
      || ["ppid", "uid"].some(key => !Number.isSafeInteger(value[key]) || value[key] < 0)
      || !(value.namespace === null || text(value.namespace))) reject();
}

const descriptorStrings = ["request_id", "instance_id", "manager_activation_id", "owner_nonce", "task_id", "step_id", "attempt_id",
  "budget_scope_id", "role_id", "candidate_id", "cwd", "source_cwd", "provider_id", "model_id", "route_id", "thinking", "allocation_id"];
const descriptorDigests = ["role_digest", "runtime_digest", "policy_digest", "snapshot_digest", "model_digest", "result_schema_digest", "workspace_identity_digest"];
const descriptorLists = ["allowed_tools", "read_roots", "write_roots", "allowed_artifact_ids", "workspace_write_lease_ids"];
export function assertDescriptor(value) {
  closed(value, ["protocol_version", ...descriptorStrings, ...descriptorDigests, ...descriptorLists,
    "continuation_of", "inherited_denials", "context_mode", "nested", "executor", "request_ceiling", "turn_ceiling", "deadline", "grant_generation"],
    ["token_limit", "cost_limit"]);
  if (value.protocol_version !== 1 || descriptorStrings.some(key => !text(value[key]))
      || descriptorDigests.some(key => !sha(value[key])) || descriptorLists.some(key => !list(value[key]))
      || !(value.continuation_of === null || text(value.continuation_of)) || !Array.isArray(value.inherited_denials)
      || value.context_mode !== "fresh" || value.nested !== false || value.executor !== "managed-process"
      || !isAbsolute(value.cwd) || !isAbsolute(value.source_cwd)
      || !["off", "minimal", "low", "medium", "high", "xhigh", "max"].includes(value.thinking)
      || ["request_ceiling", "turn_ceiling", "grant_generation"].some(key => !Number.isSafeInteger(value[key]) || value[key] < 1)
      || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/.test(value.deadline) || !Number.isFinite(Date.parse(value.deadline))
      || new Date(value.deadline).toISOString().slice(0, 19) !== value.deadline.slice(0, 19)) reject();
  if (value.write_roots.length && !value.workspace_write_lease_ids.length) reject("WORKSPACE_BUSY", 4);
  for (const rule of value.inherited_denials) {
    assertRule(rule);
    if (rule.effect !== "deny") reject();
  }
  if (Object.hasOwn(value, "token_limit") && (!Number.isSafeInteger(value.token_limit) || value.token_limit < 1)) reject();
  if (Object.hasOwn(value, "cost_limit") && (typeof value.cost_limit !== "string" || !/^[0-9]+(?:\.[0-9]+)?$/.test(value.cost_limit))) reject();
  return value;
}

export function assertEvent(value) {
  closed(value, ["task_id", "step_id", "attempt_id", "manager_run_id", "producer_id", "sequence", "event_id", "phase",
    "request_id", "ordinal", "usage_id", "process_identity", "active_tool_ids", "external_work_ids", "candidate_digest", "result_digest", "termination_confirmed"]);
  if (["task_id", "step_id", "attempt_id", "manager_run_id", "producer_id", "event_id", "phase"].some(key => !text(value[key]))
      || !Number.isSafeInteger(value.sequence) || value.sequence < 1 || !list(value.active_tool_ids) || !list(value.external_work_ids)
      || !sha(value.candidate_digest) || !(value.result_digest === null || sha(value.result_digest)) || typeof value.termination_confirmed !== "boolean"
      || ["request_id", "usage_id"].some(key => !(value[key] === null || text(value[key])))
      || !(value.ordinal === null || Number.isSafeInteger(value.ordinal) && value.ordinal > 0)
      || !(value.process_identity === null || typeof value.process_identity === "object")) reject();
  if (value.process_identity !== null) assertProcess(value.process_identity);
  return value;
}
