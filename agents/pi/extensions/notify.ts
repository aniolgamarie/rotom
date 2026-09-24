/** 终端通知只发送固定OSC消息，不启动脱离监督的系统进程。 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export function notificationSequence(mode: string): string {
  if (mode === "osc99") return "\x1b]99;i=agentcfg-pi:d=0;Pi\x1b\\\x1b]99;i=agentcfg-pi:p=body;Ready for input\x1b\\";
  if (mode === "osc777") return "\x1b]777;notify;Pi;Ready for input\x07";
  if (mode === "bell") return "\x07";
  if (mode === "off") return "";
  throw new Error("TERMINAL_NOTIFICATION_MODE");
}
export default function notify(pi: ExtensionAPI) {
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager") throw new Error("AGENTCFG_RUNTIME_REQUIRED");
  pi.on("agent_end", (_event, ctx) => {
    if (!ctx.hasUI || runtime.managedRequestScope?.getStore()) return;
    const configured = runtime.manifest.options.ui?.notifications ?? "auto";
    const mode = configured === "auto" ? process.env.KITTY_WINDOW_ID ? "osc99" : process.env.WT_SESSION ? "bell" : "osc777" : configured;
    const sequence = notificationSequence(mode);
    if (sequence) process.stdout.write(sequence);
  });
}
