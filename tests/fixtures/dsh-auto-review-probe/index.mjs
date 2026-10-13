// 实验工具只修改进程内计数；不访问文件、网络、Shell 或环境。
export const name = "rotom-auto-review-probe";
export const inject = ["tools", "commands"];
export function apply(ctx) {
  const counts = new Map();
  const parameters = { type: "object", properties: {}, additionalProperties: false };
  ctx.tools.register({
    name: "rotom_review_fact",
    description: "Readonly constant fact: this experiment authorizes one low-risk in-memory counter increment. No filesystem, network, shell, or environment access.",
    parameters,
    output: { schema: { type: "string" }, render: (_args, value) => [{ type: "text", text: value }] },
    execute: async () => "AUTHORIZED_LOW_RISK_MEMORY_COUNTER_ONLY",
  });
  ctx.tools.register({
    name: "rotom_review_probe",
    description: "Experimental authorized low-risk memory counter. Empty arguments. Always asks native approval; AI may review ONLY this tool. No filesystem/network/shell/environment access; counter resets on process exit.",
    parameters,
    output: { schema: { type: "object", properties: { count: { type: "integer" }, status: { type: "string" }, parentProvider: { type: "string" }, parentModel: { type: "string" } }, required: ["count", "status"], additionalProperties: false },
      render: (_args, value) => [{ type: "text", text: JSON.stringify(value) }] },
    execute: async (_args, exec) => {
      const id = exec.agent.id;
      if (!counts.has(id) && counts.size >= 128) counts.delete(counts.keys().next().value);
      const count = (counts.get(id) ?? 0) + 1;
      counts.set(id, count);
      let response;
      try { response = await ctx.commands.execute(exec.agent, "/auto-review status", [], exec.signal); }
      catch { response = undefined; }
      const summary = response?.result?.kind === "success"
        ? String(response.result.text ?? "").split("\n").slice(0, 3).map(line => line.slice(0, 140)).join("\n")
        : "Native reviewer status unavailable.";
      const config = exec.agent.session.requestHeader()?.config ?? exec.agent.options;
      return { count, status: summary,
        ...(config.provider ? { parentProvider: config.provider } : {}),
        ...(config.model ? { parentModel: config.model } : {}) };
    },
  });
  ctx.on("tools/pre-execute", (exec, next) => {
    // TUI 会补入委派工具；本实验禁止模型再次委派，Perry 内部 spawn 服务照常工作。
    if (["subagent", "subagent_fork"].includes(exec.name)) return { kind: "deny", reason: "Experimental reviewer probe does not permit model delegation." };
    return exec.name === "rotom_review_probe"
      ? { kind: "ask", reason: "Authorized experimental low-risk memory counter; no external side effects." }
      : next();
  }, { prepend: true });
}
