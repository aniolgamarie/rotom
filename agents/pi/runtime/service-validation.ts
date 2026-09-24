// 实际 SDK 服务验收；只加载本次声明的扩展，结果只包含计数和布尔证明。
import { randomUUID } from "node:crypto";
import { dirname, join, resolve, isAbsolute } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { writeFileSync } from "node:fs";
import { launch, privateFile } from "./launch.ts";
import { closed, reject, isProtocolError } from "./managed-types.ts";
import { SupervisorClient } from "./supervisor-client.ts";
import { agentStateClient } from "./service-bindings.ts";
import { exerciseManaged } from "./managed-validation.ts";

export function serviceExtensions(manifest, installed, capability) {
  const plugins = new Set(["pi-subagents", "pi-permissions", "openai-proxy"]);
  const required = { mcp: "pi-mcp", web: "pi-web", "task-keeper": "task-keeper" }[capability];
  if (required) {
    if (!manifest.plugins.includes(required)) reject("SERVICE_VALIDATION_NOT_SELECTED", 2);
    plugins.add(required);
  } else if (capability !== "terminal") reject("SERVICE_VALIDATION_UNKNOWN", 2);
  const ids = installed.resources.extensions.filter(row => plugins.has(row.capability_id) && manifest.plugins.includes(row.capability_id)).map(row => row.id);
  if (capability === "terminal") {
    if (!Object.hasOwn(manifest.resource_ids.extensions, "gentle-agent-state")) reject("SERVICE_VALIDATION_NOT_SELECTED", 2);
    ids.push("gentle-agent-state");
  }
  return [...new Set(ids)].sort();
}

async function drained(manager) {
  const deadline = Date.now() + 30000;
  while (manager.hasRunning()) {
    if (Date.now() >= deadline) reject("SERVICE_VALIDATION_ACTIVITY", 5);
    await new Promise(resolve => setTimeout(resolve, 100));
  }
}

export async function exerciseServices(host, input) {
  const errors = [];
  await host.session.bindExtensions({ mode: "print", onError: () => errors.push(true) });
  const runtime = globalThis[Symbol.for("agentcfg.pi.runtime.v1")], entry = globalThis[Symbol.for("agentcfg.pi.managed.v1")];
  if (!entry?.manager || !runtime?.supervisor) reject("SERVICE_VALIDATION_MANAGER", 5);
  const runner = host.session.extensionRunner, context = runner.createContext();
  if (input.capability === "task-keeper") {
    const facts = await exerciseManaged(host, input);
    if (errors.length) reject("SERVICE_VALIDATION_EXTENSION_ERROR", 5);
    return facts;
  }
  const invoke = async (name, params) => {
    const tool = runner.getToolDefinition(name);
    if (!tool) reject("SERVICE_VALIDATION_TOOL_MISSING", 5);
    const value = await tool.execute(randomUUID(), params, AbortSignal.timeout(90000), undefined, context);
    if (!value || value.isError || value.details?.error || value.details?.cancelled) reject("SERVICE_VALIDATION_CALL_FAILED", 5);
    return value.details;
  };
  let facts;
  if (input.capability === "mcp") {
    const servers = Object.keys(runtime.manifest.options.mcp?.servers ?? {});
    if (!servers.length) reject("SERVICE_VALIDATION_BINDING_MISSING", 2);
    for (const server of servers) {
      const value = await invoke("mcp", { connect: server });
      if (value?.mode !== "list" || value.server !== server || value.cached === true || !Number.isSafeInteger(value.count) || value.count < 0) reject("SERVICE_VALIDATION_MCP_METADATA", 5);
    }
    const status = await invoke("mcp", {});
    if (!Array.isArray(status?.servers) || servers.some(name => !status.servers.some(row => row.name === name && row.status === "connected"))) reject("SERVICE_VALIDATION_MCP_CONNECTION", 5);
    facts = { mcp_servers_verified: servers.length, metadata_refreshed: true };
  } else if (input.capability === "web") {
    const options = runtime.manifest.options.web ?? {};
    const selected = options.providers ?? options.settings?.searchProvider ?? options.settings?.provider;
    const providers = Array.isArray(selected) ? selected : typeof selected === "string" ? [selected] : [];
    if (!providers.length || providers.some(name => ["auto", "all"].includes(name) || !Object.hasOwn(options.services ?? {}, name))) reject("SERVICE_VALIDATION_WEB_SELECTION", 2);
    const toolName = options.settings?.toolNames?.webSearch ?? "web_search";
    for (const provider of providers) {
      const details = await invoke(toolName, { query: "OpenAI API documentation", provider, numResults: 1, includeContent: false, workflow: "none" });
      if (!Number.isSafeInteger(details?.successfulQueries) || details.successfulQueries !== 1
          || !Number.isSafeInteger(details.totalResults) || details.totalResults < 1) reject("SERVICE_VALIDATION_WEB_RESULT", 5);
    }
    await drained(entry.manager);
    facts = { web_providers_verified: providers.length, search_response_verified: true };
  } else if (input.capability === "terminal") {
    if (runtime.manifest.options.agent_state?.mode !== "service") reject("SERVICE_VALIDATION_TERMINAL_BINDING", 2);
    await drained(entry.manager);
    const client = agentStateClient(runtime, context);
    for (const state of ["working", "blocked", "idle"]) await client.report(state);
    await drained(entry.manager);
    facts = { terminal_reports_acknowledged: 3 };
  } else reject("SERVICE_VALIDATION_UNKNOWN", 2);
  if (errors.length) reject("SERVICE_VALIDATION_EXTENSION_ERROR", 5);
  return { ...facts, sdk_session: true, capability: input.capability };
}

async function main(path) {
  if (!isAbsolute(path) || process.env.AGENTCFG_SERVICE_VALIDATION !== "1") reject("SERVICE_VALIDATION_AUTHORIZATION", 2);
  const input = JSON.parse(privateFile(path));
  closed(input, ["schema_version", "nonce", "capability", "instance_root", "project", "runtime_identity", "output"], ["variant"]);
  if (input.schema_version !== 1 || !/^[a-f0-9]{64}$/.test(input.nonce) || !["mcp", "web", "terminal", "task-keeper"].includes(input.capability)
      || input.capability === "task-keeper" && !["workflow", "second-view"].includes(input.variant)
      || input.output !== join(dirname(path), "service-result.json")) reject("SERVICE_VALIDATION_INPUT", 2);
  const runtimeRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  const installed = JSON.parse(privateFile(join(runtimeRoot, "runtime/profile.json")));
  const manifest = JSON.parse(privateFile(join(input.instance_root, "pi-home/agentcfg-manifest.json")));
  const engine = typeof globalThis.Bun !== "undefined" ? "bun" : "node";
  if (installed.runtime_identity !== input.runtime_identity || installed.engine !== engine
      || installed.toolchains[engine] !== (engine === "bun" ? globalThis.Bun.version : process.version)
      || process.env.HOME !== join(input.instance_root, "user-home") || process.env.PI_CODING_AGENT_DIR !== join(input.instance_root, "pi-home")) reject("SERVICE_VALIDATION_IDENTITY", 4);
  const supervisor = new SupervisorClient({ python: process.env.AGENTCFG_PYTHON, client: process.env.AGENTCFG_SUPERVISOR_CLIENT,
    endpoint: process.env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: process.env.AGENTCFG_SUPERVISOR_CAPABILITY });
  delete process.env.AGENTCFG_SUPERVISOR_CAPABILITY;
  const sdk = await import(pathToFileURL(resolve(runtimeRoot, installed.entrypoint)).href);
  let facts, passed = false, failureCode = null;
  try {
    const result = await launch({ sdk: { ...sdk, runPrintMode: async host => { facts = await exerciseServices(host, input); return 0; } },
      manifest, installed, instanceRoot: input.instance_root, runtimeRoot, cwd: input.project, engine, supervisor,
      extensionScope: serviceExtensions(manifest, installed, input.capability), argv: ["--print"] });
    passed = result.code === 0 && !!facts;
  } catch (error) {
    // 只记录本地协议枚举，不记录第三方错误正文、URL 或凭据。
    const known = new Set(["SERVICE_VALIDATION_TOOL_MISSING", "SERVICE_VALIDATION_CALL_FAILED", "SERVICE_VALIDATION_MCP_METADATA",
      "SERVICE_VALIDATION_MCP_CONNECTION", "SERVICE_VALIDATION_WEB_SELECTION", "SERVICE_VALIDATION_WEB_RESULT", "SERVICE_VALIDATION_TERMINAL_BINDING",
      "SERVICE_VALIDATION_EXTENSION_ERROR", "SERVICE_VALIDATION_ACTIVITY", "SERVICE_VALIDATION_BINDING_MISSING", "SERVICE_VALIDATION_MANAGER"]);
    failureCode = isProtocolError(error) && known.has(error.code) ? error.code : "SERVICE_VALIDATION_FAILED";
  }
  writeFileSync(input.output, JSON.stringify({ schema_version: 1, nonce: input.nonce, capability: input.capability,
    runtime_identity: input.runtime_identity, status: passed ? "passed" : "failed", failure_code: failureCode, facts: facts ?? null }) + "\n", { flag: "wx", mode: 0o600 });
  return passed ? 0 : 5;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = process.argv[2] === "--input" && process.argv.length === 4 ? await main(process.argv[3]) : 2; }
  catch { process.stderr.write("服务验收未完成；检查已选绑定和活动记录。\n"); process.exitCode = 5; }
}
