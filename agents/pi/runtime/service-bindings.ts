// 终端通知仅使用当前实例明确选择的报告服务，不读取全局脚本路径。
import { randomUUID } from "node:crypto";
import { reject } from "./managed-types.ts";
const reportQueues = new WeakMap();

export function terminalStateSequence(title, state) {
  if (typeof title !== "string" || title.length > 200 || /[\x00-\x1f\x7f]/.test(title) || !["working", "blocked", "idle"].includes(state)) reject("SERVICE_TITLE_INVALID", 2);
  const suffix = { working: " · working", blocked: " · blocked", idle: "" }[state];
  return "\x1b]2;" + title + suffix + "\x07";
}

export function terminalHyperlink(target) {
  if (typeof target !== "string" || target.length > 16384 || /[\x00-\x1f\x7f-\x9f]/.test(target)) reject("TERMINAL_LINK_INVALID", 2);
  const url = new URL(target);
  if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) reject("TERMINAL_LINK_INVALID", 2);
  return "\x1b]8;;" + url.href + "\x1b\\" + url.href + "\x1b]8;;\x1b\\\n";
}

export function terminalClipboard(text) {
  if (typeof text !== "string" || Buffer.byteLength(text) > 1024 * 1024) reject("TERMINAL_CLIPBOARD_OVERSIZE", 2);
  return "\x1b]52;c;" + Buffer.from(text, "utf8").toString("base64") + "\x07";
}

export function agentStateClient(runtime, context, emit = value => process.stdout.write(value)) {
  const check = () => {
    if (runtime?.owner?.role !== "manager" || runtime.managedRequestScope?.getStore()
        || !Object.hasOwn(runtime.manifest.resource_ids?.extensions ?? {}, "gentle-agent-state")) reject("SERVICE_CONTEXT_UNAVAILABLE", 4);
  };
  const send = async state => {
    check();
    const binding = runtime.manifest.options.agent_state;
    if (!binding) reject("SERVICE_BINDING_REQUIRED", 2);
    if (binding.mode === "osc") {
      if (context.hasUI) emit(terminalStateSequence(binding.title, state));
      return;
    }
    const ticket = await runtime.supervisor.call("ordinary_service_prepare", { operation_id: randomUUID(), state });
    try {
      const result = await runtime.ordinaryOperations.write(ticket, null, null, undefined);
      if (result.exitCode !== 0 || result.truncated !== false || result.terminationConfirmed !== true) reject("SERVICE_EXECUTION_FAILED", 5);
    } finally { await runtime.supervisor.call("ordinary_command_finish", { operation_id: ticket.operation_id }); }
  };
  return {
    async report(state) {
      check();
      // 生命周期通知和显式控制共享同一条报告通道；失败不毒化后续状态。
      const previous = reportQueues.get(runtime) ?? Promise.resolve();
      const pending = previous.catch(() => {}).then(() => send(state));
      reportQueues.set(runtime, pending);
      try { return await pending; }
      finally { if (reportQueues.get(runtime) === pending) reportQueues.delete(runtime); }
    },
  };
}

export async function declaredRules() {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (runtime?.owner?.role !== "manager" || runtime.managedRequestScope?.getStore() || !runtime.manifest.plugins.includes("pi-rules")) reject("RULES_CONTEXT_UNAVAILABLE", 4);
  return runtime.supervisor.call("ordinary_rules_read", {});
}

export async function readDeclaredSkill(path) {
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
  if (runtime?.owner?.role !== "manager" || runtime.managedRequestScope?.getStore()
      || !runtime.resources?.skills.some(row => row.path === path || row.path + "/SKILL.md" === path)) reject("RULE_SKILL_UNSELECTED", 4);
  const ticket = await runtime.supervisor.call("ordinary_prepare", { operation_id: randomUUID(), role_id: "main", cwd: runtime.cwd, tool_name: "read", input: { path } });
  try { return (await runtime.ordinaryOperations.read(ticket, path)).bytes.toString("utf8"); }
  finally { await runtime.supervisor.call("ordinary_finish", { operation_id: ticket.operation_id }); }
}
