// 原生权限提示器的上界来自 agentcfg；会话覆盖只影响提示，不重写规则或角色。
import { realpathSync } from "node:fs";
import { relative, isAbsolute, sep } from "node:path";
import { assertRule, canonical, clone, closed, digest, reject } from "./managed-types.ts";
import { convertParentPolicy } from "./permission-policy.ts";

export class PermissionAccess {
  constructor(context) {
    this.context = context;
    this.base = context.manifest.permission_policy === undefined ? null : clone(context.manifest.permission_policy);
    this.sessions = new Map(); this.generation = 1; this.blocked = false;
    this.approvals = new Map();
  }
  require() {
    if (this.blocked) reject("PERMISSION_RESTART_REQUIRED", 4);
    if (this.base === null) reject("PERMISSION_CAPABILITY_MISSING", 5);
    closed(this.base, ["schema_version", "default", "rules"]);
    if (this.base.schema_version !== 1 || this.base.default !== "deny" || !Array.isArray(this.base.rules)) reject("PERMISSION_UNREPRESENTABLE", 5);
    const ids = new Set();
    for (const rule of this.base.rules) { assertRule(rule); if (ids.has(rule.id)) reject("PERMISSION_UNREPRESENTABLE", 5); ids.add(rule.id); }
    if (canonical(this.context.manifest.permission_policy) !== canonical(this.base)) reject("PERMISSION_RESTART_REQUIRED", 4);
    return { policy: clone(this.base), policy_digest: digest(this.base), generation: this.generation };
  }
  state(sessionId) {
    this.require();
    return { ...(this.sessions.get(sessionId) ?? { mode: "off", cwd: null }), generation: this.generation, policy_digest: digest(this.base) };
  }
  setMode(sessionId, mode, cwd) {
    this.require();
    if (!["off", "cwd", "global"].includes(mode) || this.context.managedRequestScope?.getStore()) reject("USER_CONTROL_REQUIRED", 4);
    this.generation++;
    for (const ticket of this.approvals.values()) void this.context.ordinaryOperations?.abort(ticket.result).catch(() => {});
    this.approvals.clear();
    this.sessions.set(sessionId, { mode, cwd: mode === "cwd" ? realpathSync(cwd) : null });
    return this.state(sessionId);
  }
  yolo(sessionId, cwd) {
    if (this.context.managedRequestScope?.getStore()) return false;
    const state = this.state(sessionId);
    if (state.mode === "global") return true;
    if (state.mode !== "cwd") return false;
    const tail = relative(state.cwd, realpathSync(cwd));
    return tail === "" || !tail.startsWith(".." + sep) && tail !== ".." && !isAbsolute(tail);
  }
  parentSnapshot(source = null, options = { roots: {}, commands: {} }) {
    const snapshot = this.require();
    const rules = source === null ? snapshot.policy.rules : convertParentPolicy(source, options).policy.rules;
    return { ...snapshot, inherited_denials: rules.filter(rule => rule.effect === "deny").map(clone) };
  }
  async check(event, ctx) {
    const snapshot = this.require();
    if (this.context.managedRequestScope?.getStore()) reject("MANAGED_PARENT_TOOL_DENIED", 5);
    if (!this.context.ordinaryOperations) reject("ORDINARY_IO_CAPABILITY_MISSING", 5);
    const scope = this.scope(ctx);
    const result = await this.context.ordinaryOperations.preflight(event, ctx, snapshot);
    return { result, scope, generation: snapshot.generation, digest: digest({ name: event.toolName, input: event.input }) };
  }
  scope(ctx) {
    const session = ctx?.sessionManager?.getSessionId();
    if (typeof session !== "string" || !session || typeof ctx.cwd !== "string") reject("PERMISSION_SESSION_REQUIRED", 4);
    return digest({ session, cwd: realpathSync(ctx.cwd) });
  }
  approve(event, checked, ctx) {
    this.require();
    if (checked.generation !== this.generation || checked.scope !== this.scope(ctx)
        || checked.digest !== digest({ name: event.toolName, input: event.input }) || this.approvals.has(event.toolCallId)) reject("PERMISSION_ADMISSION_STALE", 4);
    if (checked.result.kind !== "service") this.approvals.set(event.toolCallId, checked);
  }
  take(toolCallId, toolName, input, ctx) {
    this.require();
    const ticket = this.approvals.get(toolCallId);
    if (!ticket || ticket.generation !== this.generation || ticket.scope !== this.scope(ctx)
        || ticket.digest !== digest({ name: toolName, input })) reject("PERMISSION_ADMISSION_STALE", 4);
    this.approvals.delete(toolCallId);
    return clone(ticket.result);
  }
}
