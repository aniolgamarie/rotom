// OMP v18.3.0 原生 registerCommand API；只报告固定验收标记，不输出未知原生内容。
const FIXTURE = {
  main: "omp-smoke/large-v1",
  smol: "omp-smoke/small-v1",
  theme: "rotom-dark",
  echo: "ROTOM_OMP_ECHO_OK",
};

function exactModel(model, expected) {
  if (!model) return null;
  return `${model.provider}/${model.id}` === expected ? expected : null;
}

async function inspectFixture(omp, ctx) {
  const prompt = ctx.getSystemPrompt().join("\n");
  const main = ctx.models.resolve("@default");
  const smol = ctx.models.resolve("@smol");
  const theme = await ctx.ui.getTheme(FIXTURE.theme);
  const tools = omp.getAllTools();
  return {
    ruleOne: prompt.includes("rule-one"),
    ruleTwo: prompt.includes("rule-two"),
    fullPackageSkill: prompt.includes("full-package"),
    main: exactModel(main, FIXTURE.main),
    smol: exactModel(smol, FIXTURE.smol),
    theme: theme ? FIXTURE.theme : null,
    mcpToolPresent: tools.some(tool =>
      tool.name.includes("echo") && tool.sourceInfo?.source === "mcp"),
  };
}

async function exerciseEchoMcp(ctx) {
  let connection;
  let disconnect;
  try {
    const [mcp, { getAgentDir }, fs, path] = await Promise.all([
      import("@oh-my-pi/pi-coding-agent/mcp"),
      import("@oh-my-pi/pi-coding-agent"),
      import("node:fs/promises"),
      import("node:path"),
    ]);
    const { connectToServer, listTools, callTool } = mcp;
    disconnect = mcp.disconnectServer;
    const agentDir = getAgentDir();
    const raw = JSON.parse(await fs.readFile(path.join(agentDir, "mcp.json"), "utf8"));
    if (Object.keys(raw).length !== 1 || !raw.mcpServers || Object.keys(raw.mcpServers).join("") !== "echo-stdio") {
      throw new Error("invalid-managed-mcp-config");
    }
    const server = raw.mcpServers["echo-stdio"];
    if (!server || Object.keys(server).sort().join(",") !== "args,command,type" || server.type !== "stdio"
      || !path.isAbsolute(server.command) || !Array.isArray(server.args) || server.args.length !== 1
      || !path.isAbsolute(server.args[0]) || !server.args[0].replaceAll("\\", "/").endsWith("/packages/echo-mcp/server.py")) {
      throw new Error("invalid-managed-mcp-config");
    }
    connection = await connectToServer("echo-stdio", server);
    const tools = await listTools(connection);
    if (tools.length !== 1 || tools[0]?.name !== "echo") throw new Error("unexpected-mcp-tools");
    const result = await callTool(connection, "echo", { text: FIXTURE.echo });
    const content = result?.content;
    if (result?.isError || !Array.isArray(content) || content.length !== 1
      || content[0]?.type !== "text" || content[0]?.text !== FIXTURE.echo) {
      throw new Error("unexpected-mcp-result");
    }
    ctx.ui.notify("ROTOM_OMP_MCP_OK", "info");
  } catch {
    ctx.ui.notify("ROTOM_OMP_MCP_ERROR", "error");
  } finally {
    if (connection && disconnect) {
      try {
        await disconnect(connection);
      } catch {
        // 关闭失败不回显底层路径或进程错误。
      }
    }
  }
}

export default function (omp) {
  omp.registerCommand("rotom-health", {
    description: "Verify the locked rotom OMP fixture without model calls",
    handler: async (args, ctx) => {
      const operation = args.trim();
      if (!operation) {
        ctx.ui.notify("ROTOM_OMP_HEALTH_OK", "info");
        return;
      }
      if (operation === "inspect") {
        try {
          ctx.ui.notify(`ROTOM_OMP_INSPECT ${JSON.stringify(await inspectFixture(omp, ctx))}`, "info");
        } catch {
          ctx.ui.notify("ROTOM_OMP_INSPECT_ERROR", "error");
        }
        return;
      }
      if (operation === "mcp") {
        await exerciseEchoMcp(ctx);
        return;
      }
      ctx.ui.notify("ROTOM_OMP_HEALTH_USAGE", "warning");
    },
  });
}
