import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Text } from "@earendil-works/pi-tui";
import { beginRound, finishRound, formatSummary } from "./diagnostics.mjs";
import { getProxyDiagnostics, getProxyStatus, installOpenAIProxy } from "./routing.mjs";

const ENTRY_TYPE = "starter-openai-proxy-traffic";

export default function (pi: ExtensionAPI) {
  // Recreate wrappers on every extension load. Preserve only the live pool and
  // counters so /reload installs updated code without duplicating accounting.
  const runtime = (globalThis as any)[Symbol.for("agentcfg.pi.runtime.v1")];
  if (!runtime || runtime.owner?.role !== "manager") throw new Error("AGENTCFG_RUNTIME_REQUIRED");
  installOpenAIProxy({ reload: true });
  // Pi may rebuild its HTTP dispatcher during startup or a resource reload.
  pi.on("session_start", (event) => {
    installOpenAIProxy();
    if (event.reason !== "reload") {
      const diagnostics = getProxyDiagnostics();
      diagnostics.active = null;
      diagnostics.last = null;
    }
  });

  pi.registerEntryRenderer(ENTRY_TYPE, (entry: any, options, theme) => {
    const data = entry.data;
    const detail = options.expanded ? `\n${data.proxy}\n${data.stats.hosts.join(", ")}\n读取端取消 ${data.stats.cancellations ?? 0}（包括正常 SSE 收尾和用户中止，不等同于网络失败）\n不含 HTTP 头、TLS/TCP 开销及其他进程流量。` : "";
    return new Text(theme.fg(data.stats.failures ? "warning" : "dim", formatSummary(data.stats) + detail), 0, 0);
  });

  pi.on("before_agent_start", () => {
    installOpenAIProxy();
    beginRound(getProxyDiagnostics());
  });

  // Unlike agent_end, settled waits for retries and automatic compaction.
  pi.on("agent_settled", (_event, ctx) => {
    const stats = finishRound(getProxyDiagnostics());
    if (!stats) return;
    const status = getProxyStatus();
    // Custom entries render in the transcript but never enter model context.
    pi.appendEntry(ENTRY_TYPE, { version: status.version, proxy: status.proxy, stats });
    if (!ctx.hasUI) console.error(formatSummary(stats));
  });

  pi.registerCommand("openai-proxy", {
    description: "查看 OpenAI 代理状态、本轮及进程累计 HTTP 正文流量",
    handler: async (_args, ctx) => {
      const status = getProxyStatus();
      const lines = [
        `OpenAI 代理 v${status.version} · ${status.proxy}`,
        `fetch 分流：${status.fetchActive ? "已挂载" : "被其他包装覆盖，需结合计数判断"}；dispatcher：${status.dispatcherActive ? "已挂载" : "已被替换"}；连接池：${status.poolOpen ? "未关闭" : "已关闭"}`,
        "范围：openai.com、chatgpt.com 及其子域名；代理失败不回退直连。",
        formatSummary(status.total, "进程累计"),
        `累计读取端取消 ${status.total.cancellations}（含正常 SSE 收尾和用户中止）`,
        status.current ? formatSummary(status.current, "进行中") : status.last ? formatSummary(status.last, "上轮") : "尚无对话统计。",
        "口径：压缩后的 HTTP 正文（若有压缩）；不含 HTTP 头、TLS/TCP 开销和其他进程流量。",
      ];
      ctx.ui.notify(lines.join("\n"), status.poolOpen ? "info" : "warning");
    },
  });
}
