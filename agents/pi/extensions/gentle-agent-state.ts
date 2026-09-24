/** 父会话状态通知：显式服务绑定、单条串行通道和有界状态合并。 */
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { agentStateClient } from "@agentcfg/pi-runtime/service-bindings";

type State = "working" | "blocked" | "idle";
export default function (pi: ExtensionAPI) {
  let active = false, closing = false, warned = false;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;
  let pending: { state: State; context: ExtensionContext } | undefined;
  let running: Promise<void> | undefined;
  const blocked = new Set<string>();
  const clearIdle = () => { if (idleTimer) clearTimeout(idleTimer); idleTimer = undefined; };
  const queue = (state: State, context: ExtensionContext) => {
    if (closing && state !== "idle") return;
    const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
    if (runtime?.owner?.role !== "manager" || runtime.managedRequestScope?.getStore()) return;
    pending = { state, context };
    if (!running) {
      running = (async () => {
        while (pending) {
          const next = pending; pending = undefined;
          try { await agentStateClient(runtime, next.context).report(next.state); }
          catch {
            if (!warned && next.context.hasUI) next.context.ui.notify("终端状态报告未完成：请检查显式服务绑定或 supervisor 状态。", "warning");
            warned = true;
          }
        }
      })().finally(() => {
        running = undefined;
        if (pending) { const next = pending; pending = undefined; void queue(next.state, next.context); }
      });
    }
    return running;
  };
  const isPrompt = (event: { toolName?: string }) => /(?:askuserquestion|requestuserinput|exitplanmode|confirm)/.test((event.toolName ?? "").toLowerCase().replace(/[^a-z0-9]/g, ""));
  pi.on("session_start", (_event, ctx) => { closing = false; active = false; blocked.clear(); warned = false; void queue("idle", ctx); });
  pi.on("agent_start", (_event, ctx) => { active = true; clearIdle(); void queue(blocked.size ? "blocked" : "working", ctx); });
  pi.on("agent_end", (_event, ctx) => {
    active = false; blocked.clear(); clearIdle();
    idleTimer = setTimeout(() => { if (!closing) void queue(blocked.size ? "blocked" : "idle", ctx); }, 250);
    idleTimer.unref?.();
  });
  pi.on("tool_call", (event, ctx) => {
    if (!isPrompt(event)) return;
    blocked.add(event.toolCallId); clearIdle(); void queue("blocked", ctx);
  });
  pi.on("tool_result", (event, ctx) => {
    if (!blocked.delete(event.toolCallId)) return;
    void queue(blocked.size ? "blocked" : active ? "working" : "idle", ctx);
  });
  pi.on("session_shutdown", async (_event, ctx) => {
    closing = true; clearIdle(); blocked.clear(); void queue("idle", ctx);
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        (async () => { while (running) await running; })(),
        new Promise<void>(resolve => { timer = setTimeout(resolve, 500); }),
      ]);
    } finally {
      if (timer) clearTimeout(timer);
      // 超过退出窗口的任务仍归 supervisor；不再排入新的通知阻塞正常撤权。
      pending = undefined;
    }
  });
}
