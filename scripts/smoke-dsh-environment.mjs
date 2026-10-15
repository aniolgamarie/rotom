// 独立显式原生验收：仅公开宿主接口、合成环境和隔离路径，不调用模型。
import fs from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";

if (process.argv[2] === "--deny-package-operation") {
  process.stderr.write("Package operations are disabled in native environment acceptance\n");
  process.exit(1);
}
const root = process.env.AGENTCFG_ENV_SMOKE_ROOT;
const output = process.env.AGENTCFG_ENV_SMOKE_RESULT;
const patch = process.env.AGENTCFG_ENV_SMOKE_PATCH;
const runtime = process.argv[2];
const inside = (base, target) => typeof target === "string" && path.isAbsolute(target)
  && target !== base && path.relative(base, target) !== ".." && !path.relative(base, target).startsWith(".." + path.sep) && !path.isAbsolute(path.relative(base, target));
if (!root || !path.isAbsolute(root) || root === "/" || !inside(root, output) || !inside(root, patch)
    || !runtime || !path.isAbsolute(runtime) || !inside(root, process.cwd())
    || !inside(root, process.env.HOME) || !inside(root, process.env.DSH_HOME)) {
  throw new Error("Explicit isolated environment acceptance paths required");
}
for (const name of ["XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_RUNTIME_DIR"]) {
  if (process.env[name] !== undefined && !inside(root, process.env[name])) {
    throw new Error("Explicit isolated XDG paths required");
  }
}
const require = createRequire(path.join(runtime, "package.json"));
const moduleAt = name => import(pathToFileURL(require.resolve(name)).href);
const state = { kind: "native-dsh-execution-environment", stage: "initializing", checks: {},
  model_calls: 0, native_complete: false, status: "IN_PROGRESS" };
const save = () => {
  fs.writeFileSync(output + ".tmp", JSON.stringify(state, null, 2) + "\n", { mode: 0o600 });
  fs.renameSync(output + ".tmp", output);
};
const stage = name => { state.stage = name; save(); };
const controller = new AbortController();
const owned = new Set();
const disposers = [];
let booted;
let cleaning;
const bounded = (promise, ms) => {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("Native acceptance deadline exceeded")), ms);
  })]).finally(() => clearTimeout(timer));
};
const cleanupFailure = () => {
  state.status = "FAIL"; state.error = "CLEANUP_FAILED"; state.error_stage = "cleanup";
  state.native_complete = false; save();
};
const cleanup = code => cleaning ??= (async () => {
  controller.abort();
  for (const dispose of disposers.reverse()) { try { dispose(); } catch { cleanupFailure(); } }
  const settled = await bounded(Promise.allSettled([...owned].map(async handle => {
    await handle.terminate();
    if (handle.waitForExit) await handle.waitForExit();
  })), 5000).catch(() => { cleanupFailure(); return []; });
  if (settled.some(result => result.status === "rejected")) cleanupFailure();
  if (booted) await bounded(booted.shutdown.shutdown(state.status === "FAIL" ? 1 : code), 10000).catch(cleanupFailure);
})();
const deadline = setTimeout(() => {
  state.status = "FAIL"; state.error = "DEADLINE_EXCEEDED"; state.error_stage = state.stage; save();
  void cleanup(1).finally(() => process.exit(1));
}, 90000);
const wait = async predicate => {
  for (let index = 0; index < 6000; index++) {
    controller.signal.throwIfAborted();
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error("Native fixture readiness deadline exceeded");
};
const marker = "ROTOM_ENV_PROBE:";
const names = ["HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "CUSTOM_BUILD_VAR", "DELETED_BUILD_VAR",
  "AGENTCFG_DEVELOPMENT_ENV", "AGENTCFG_MCP_ENV_ARGS", "AGENTCFG_MCP_0123456789ABCDEF"];
// 只读取本任务的合成字段；任何通道都不输出完整环境。
const probeExpression = `Object.fromEntries(${JSON.stringify(names)}.map(name => [name, process.env[name] ?? null]))`;
const expected = { HOME: path.join(root, "caller"), XDG_CONFIG_HOME: path.join(root, "caller-config"),
  XDG_DATA_HOME: null, CUSTOM_BUILD_VAR: "caller-build", DELETED_BUILD_VAR: null,
  AGENTCFG_DEVELOPMENT_ENV: null, AGENTCFG_MCP_ENV_ARGS: null, AGENTCFG_MCP_0123456789ABCDEF: null };
const checkProbe = text => {
  const match = text.match(/ROTOM_ENV_PROBE:(\{[^\r\n]*\})/);
  assert(match, "Synthetic environment probe output missing");
  assert.deepEqual(JSON.parse(match[1]), expected);
};
const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";

let code = 1;
try {
  stage("helpers.load");
  const { mcpArguments, readDevelopmentEnvironment } = await moduleAt("rotom-dsh-execution-environment/environment");
  const { default: DevelopmentSubprocessRuntime } = await moduleAt("rotom-dsh-execution-environment");
  const development = readDevelopmentEnvironment();
  assert.equal(development.values.HOME, expected.HOME);
  assert.equal(development.values.XDG_CONFIG_HOME, expected.XDG_CONFIG_HOME);
  assert(!Object.hasOwn(development.values, "XDG_DATA_HOME"));
  assert.equal(development.values.CUSTOM_BUILD_VAR, "caller-build");
  assert(development.unset.includes("DELETED_BUILD_VAR"));
  process.env.AGENTCFG_MCP_ENV_ARGS = JSON.stringify(mcpArguments("/rotom-placeholder", []).slice(1, -1));
  const probeFile = path.join(root, "environment-probe.mjs");
  const outside = path.join(root, "outside");
  assert(!inside(process.cwd(), outside) && outside !== process.cwd());
  const sentinel = "synthetic environment outside sentinel\n";
  fs.writeFileSync(outside, sentinel, { flag: "wx", mode: 0o600 });
  fs.writeFileSync(probeFile, `import fs from "node:fs";\nif (process.argv[2] === "--outside-write") {\n`
    + `try { fs.writeFileSync(process.argv[3], "unexpected synthetic write"); process.exit(0); }\n`
    + `catch (error) { if (["EACCES", "EROFS"].includes(error.code)) { process.stdout.write("ROTOM_WRITE_DENIED:" + error.code); process.exit(7); } process.exit(8); }\n}\n`
    + `process.stdout.write(${JSON.stringify(marker)} + JSON.stringify(${probeExpression}) + "\\n");\n`, { flag: "wx", mode: 0o600 });
  const serverFile = path.join(root, "environment-mcp-server.mjs");
  fs.writeFileSync(serverFile, `import readline from "node:readline";\n`
    + `const probe = () => ${probeExpression};\n`
    + `const send = (id, result) => process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id, result }) + "\\n");\n`
    + `for await (const line of readline.createInterface({ input: process.stdin })) {\n`
    + `let message; try { message = JSON.parse(line); } catch { process.exit(9); }\n`
    + `if (message.id === undefined) continue;\n`
    + `if (message.method === "initialize") send(message.id, { protocolVersion: message.params.protocolVersion, capabilities: { tools: {} }, serverInfo: { name: "synthetic-env-fixture", version: "1.0.0" } });\n`
    + `else if (message.method === "ping") send(message.id, {});\n`
    + `else if (message.method === "tools/list") send(message.id, { tools: [{ name: "EnvProbe", description: "Synthetic environment probe", inputSchema: { type: "object", properties: {}, additionalProperties: false } }] });\n`
    + `else if (message.method === "tools/call" && message.params.name === "EnvProbe") send(message.id, { content: [{ type: "text", text: ${JSON.stringify(marker)} + JSON.stringify(probe()) }] });\n`
    + `else process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: "Unsupported fixture method" } }) + "\\n");\n}\n`,
    { flag: "wx", mode: 0o600 });
  stage("host.boot");
  const { runProfile } = await moduleAt("@deepseek-ai/dsh/profile-boot");
  const { createLaunchEnvironmentSnapshot } = await moduleAt("@deepseek-ai/dsh-launch-environment");
  process.env.DSH_TUI_WORKSPACE_TARGET = process.cwd();
  booted = await runProfile({ environment: createLaunchEnvironmentSnapshot([{ source: "process", values: process.env }]),
    profile: "agentcfg", patchFiles: [patch], args: [], packageManager: { command: process.execPath,
      args: [fileURLToPath(import.meta.url), "--deny-package-operation"], env: {} } });
  const { ctx } = booted;
  stage("host.agent-ready");
  disposers.push(ctx.on("llm/stream", () => {
    state.model_calls++; save(); throw new Error("Model calls disabled in native environment acceptance");
  }));
  await wait(() => ctx.get("agents").list().length > 0);
  const main = ctx.get("agents").list()[0];
  stage("host.agent-cwd");
  assert.equal(main.session.header.cwd, process.cwd());
  stage("host.provider-identity");
  const subprocess = main.ctx.get("subprocess");
  state.provider_class = subprocess?.constructor?.name;
  assert(subprocess instanceof DevelopmentSubprocessRuntime, "Execution environment provider is not mounted");
  state.checks.public_provider = "PASS";
  stage("subprocess.ordinary");
  const spec = { argv: [process.execPath, probeFile], cwd: process.cwd(), graceMs: 500,
    signal: controller.signal, env: { HOME: path.join(root, "host-override"), DELETED_BUILD_VAR: "tool-override" } };
  const ordinary = subprocess.spawn({ ...spec,
    stdio: { stdin: "ignore", stdout: { maxBytes: 16384 }, stderr: { maxBytes: 4096 } } });
  owned.add(ordinary);
  assert.equal((await ordinary.done).exitCode, 0);
  assert(await ordinary.waitForExit(controller.signal));
  checkProbe(ordinary.collected.stdout.readFrom(0).text);
  state.checks.ordinary_spawn = "PASS";
  stage("subprocess.pty");
  const terminal = await subprocess.spawnTerminal({ ...spec, rows: 24, cols: 80, terminalType: "xterm-256color" });
  owned.add(terminal);
  let terminalOutput = "";
  const terminalRead = (async () => {
    for await (const chunk of terminal.output) {
      terminalOutput += String(chunk);
      assert(terminalOutput.length <= 16384, "Unexpected terminal output size");
    }
  })();
  assert.equal((await terminal.done).exitCode, 0);
  await terminalRead;
  checkProbe(terminalOutput);
  state.checks.pty_spawn = "PASS";
  stage("tools.bash-environment");
  const tools = main.ctx.get("tools");
  assert.equal(main.ctx.get("shell").sandboxMode, "workspace-write", "Native workspace sandbox is required");
  const allowed = new Map();
  disposers.push(main.ctx.on("approval/request", (request, next) => {
    if (request.agent === main && allowed.get(request.callId) === request.toolName) {
      state.manual_probe_approvals = (state.manual_probe_approvals ?? 0) + 1;
      return "allowed-once";
    }
    return next();
  }, { prepend: true }));
  const execute = async (name, args) => {
    const callId = "environment-probe-" + randomUUID();
    allowed.set(callId, name);
    try { return await tools.execute({ callId, name, arguments: args, agent: main, signal: controller.signal }); }
    finally { allowed.delete(callId); }
  };
  const bashArguments = command => ({ command, description: "Check isolated synthetic execution environment", timeoutMs: 10000,
    workdir: process.cwd(), run_in_background: false });
  // 原生 bwrap 隔离 /tmp；在测试根复制同一官方解释器，保持二进制不变。
  const probeNode = path.join(root, "probe-node");
  fs.copyFileSync(process.execPath, probeNode, fs.constants.COPYFILE_EXCL);
  fs.chmodSync(probeNode, 0o700);
  const bash = await execute("bash", bashArguments(`${quote(probeNode)} ${quote(probeFile)}`));
  state.bash_exit = bash.value?.exitCode;
  state.bash_stderr = bash.value?.stderr?.text?.slice(0, 2048);
  save();
  assert.equal(bash.isError, false);
  assert.equal(bash.value.kind, "foreground");
  assert.equal(bash.value.exitCode, 0);
  assert.equal(bash.value.sandbox?.mode, "workspace-write");
  assert.equal(bash.value.sandbox?.enforcement, "full");
  checkProbe(bash.value.stdout.text);
  state.checks.standard_bash_environment = "PASS";
  stage("tools.bash-outside-denied");
  const denied = await execute("bash", bashArguments(`${quote(probeNode)} ${quote(probeFile)} --outside-write ${quote(outside)}`));
  assert.equal(denied.isError, false);
  assert.equal(denied.value.kind, "foreground");
  assert.equal(denied.value.exitCode, 7);
  assert.equal(denied.value.sandbox?.mode, "workspace-write");
  assert.equal(denied.value.sandbox?.enforcement, "full");
  assert.match(denied.value.stdout.text, /^ROTOM_WRITE_DENIED:(EACCES|EROFS)$/);
  assert.equal(fs.readFileSync(outside, "utf8"), sentinel);
  state.checks.outside_write_denied = "PASS";
  stage("mcp.tool-environment");
  const schema = tools.schemas(main).find(tool => tool.name === "mcp__env-fixture__EnvProbe");
  assert(schema, "Native MCP fixture tool missing");
  const mcpResult = await execute(schema.name, {});
  assert.equal(mcpResult.isError, false);
  checkProbe(mcpResult.content.filter(block => block.type === "text").map(block => block.text).join("\n"));
  state.checks.mcp_environment = "PASS";
  assert.equal(state.model_calls, 0);
  state.native_complete = true; state.status = "PASS"; stage("complete");
  code = 0;
} catch (error) {
  state.status = "FAIL";
  state.error = error?.code === "ERR_ASSERTION" ? "ASSERTION_FAILED" : "NATIVE_ENVIRONMENT_FAILED";
  state.error_stage = state.stage;
  state.error_frames = String(error?.stack ?? "").split("\n").filter(line => /^\s+at /.test(line)).slice(0, 6);
  save();
} finally {
  await cleanup(code);
  clearTimeout(deadline);
  process.exitCode = state.status === "FAIL" ? 1 : code;
}
