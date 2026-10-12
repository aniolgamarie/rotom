import assert from "node:assert/strict";
import { test } from "node:test";
import { createOfficialMcpFactories } from "../official-mcp.ts";

const fixed = code => error => error.code === code && error.exitCode === 4;
function fixture(auth = "none") {
  const state = { invoke: 0, runs: 0, creates: 0, starts: 0, sends: 0, closes: 0, checks: 0, callbacks: {} };
  const config = { type: "http", url: "https://fixture.invalid/mcp", exposure: "hidden", toolExposure: { search: "codemode" } };
  if (auth === "none") config.headers = { Authorization: "" };
  const binding = { transport: "streamable-http", network_route: "fixture-route", authentication: auth };
  if (auth === "oauth") {
    config.oauth = { clientId: "fixture", callbackUrl: "http://localhost:8765/callback" };
    binding.oauth_policy = { allowed_origins: ["https://fixture.invalid"], callback_max_seconds: 120 };
  }
  const projection = { schema_version: 1, loaded_config: { servers: [{ name: "fixture", source: "agentcfg:registry/mcp/fixture", scope: "extension", config }], errors: [], autoEnableCodemode: false },
    bindings: { fixture: binding }, allowed_tools: { fixture: ["search"] } };
  const tools = new Map(), handlers = new Map(), ctx = { cwd: "/synthetic/project" };
  const pi = { registerTool(definition) { tools.set(definition.name, definition); },
    on(name, handler) { const rows = handlers.get(name) ?? []; rows.push(handler); handlers.set(name, rows); return () => {}; },
    getAllTools() { return [...tools.values()].map(definition => ({ name: definition.name, parameters: definition.parameters,
      exposure: definition.exposure ?? "direct", sourceInfo: { path: state.foreign ? "/foreign" : "<inline:rotom-native-mcp>" } })); },
    getMcpServers() { throw Error("ambient servers accessed"); } };
  const definition = (name, execute = async function (...args) { state.runs++; state.receiver = this; state.args = args; await state.wait; if (state.rawError) { const error = Error("SYNTHETIC-PRIVATE"); if (state.errorCode) error.code = state.errorCode; throw error; } return state.result ?? { content: [{ type: "text", text: "original" }], details: { kept: true } }; }) => ({ name, label: name.startsWith("mcp__") ? "fixture/" + name.split("__").at(-1) : name, description: "synthetic", parameters: {}, execute,
    ...(name.startsWith("mcp__") ? { namespace: { name: "mcp__fixture" }, exposure: "codemode" } : {}) });
  const sdk = { createMcpExtension(options) { state.mcp = options;
    // 真实公开SDK usesOAuth依据Authorization键是否存在，不读取值。
    state.nativeEnable = entry => {
      const usesOAuth = "url" in entry.config && !entry.config.auth
        && !Object.keys(entry.config.headers ?? {}).some(header => header.toLowerCase() === "authorization");
      const authProvider = usesOAuth ? (options.credentials.forServer(entry.name, entry.config.url), {}) : undefined;
      return options.createTransport(entry, ctx.cwd, authProvider);
    };
    return view => {
    state.view = view;
    for (const name of ["list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource", "tool_search"]) view.registerTool(definition(name));
  }; }, createCodemodeExtension(options) { state.codemode = options; return view => {
    assert.equal(view, state.view);
    view.registerTool(definition("codemode", async function (...args) { return state.code ? state.code(...args) : { content: [], details: {} }; }));
  }; } };
  const credentials = { forServer() { state.credentialReads = (state.credentialReads ?? 0) + 1; }, tokens() {}, remove() {} };
  const controller = { credentials, check(value) { assert.ok(value); state.checks++; return state.checkReturn; },
    openUrl(url) { state.url = url; }, invoke(request, execute) { state.invoke++; state.request = request; return state.invocation ? state.invocation(request, execute) : execute(); },
    createTransport(entry, cwd, authProvider) {
      state.creates++; state.transportArgs = [entry, cwd, authProvider];
      if (state.asyncTransport) return Promise.resolve({});
      const raw = { async start() { assert.equal(this, raw); state.starts++; await state.transportWait; },
        async send(message) { assert.equal(this, raw); state.sends++; state.message = message; },
        async close() { assert.equal(this, raw); state.closes++; if (state.closeError) throw Error("SYNTHETIC-PRIVATE"); },
        setProtocolVersion(version) { assert.equal(this, raw); state.version = version; } };
      for (const name of ["onMessage", "onError", "onClose"]) raw[name] = function (listener) { assert.equal(this, raw); state.callbacks[name] = listener; return () => { state.unsub = name; }; };
      state.raw = raw; return raw;
    } };
  const emit = async (name, event = {}, context = ctx) => { for (const handler of handlers.get(name) ?? []) await handler(event, context); };
  const build = () => createOfficialMcpFactories({ sdk, projection, controller });
  const install = async () => { const factory = build(); await factory.extensionFactories[0].factory(pi); await emit("session_start"); return factory; };
  const enabled = () => ({ ...state.mcp.loadConfig(ctx).servers[0], config: { ...state.mcp.loadConfig(ctx).servers[0].config, enabled: true } });
  const register = (name = "mcp__fixture__search") => { const raw = definition(name); state.view.registerTool(raw); return raw; };
  const call = (name = "mcp__fixture__search", input = {}, signal, update) => tools.get(name).execute("call", input, signal, update, ctx);
  return { state, projection, controller, sdk, pi, ctx, tools, definition, emit, build, install, enabled, register, call };
}

test("public factories are explicit, disabled by default, models false and no ambient config/log IO", async () => {
  const f = fixture(), api = await f.install();
  assert.equal(api.extensionFactories[0].name, "rotom-native-mcp");
  assert.equal(f.state.mcp.loadConfig(f.ctx).servers[0].config.enabled, false);
  assert.equal(f.state.mcp.loadConfig(f.ctx).autoEnableCodemode, false);
  assert.equal(f.state.mcp.credentials, f.controller.credentials);
  assert.equal(f.state.mcp.logPath, "/dev/null"); assert.deepEqual(f.state.codemode, { models: false });
  assert.deepEqual(f.state.view.getMcpServers(), []); assert.equal(f.state.creates, 0);
  assert.ok(api.allowedToolNames.includes("mcp__fixture__search"));
  assert.throws(() => f.state.mcp.updateConfig({}, {}), fixed("PI_MCP_CONFIG_WRITE_REJECTED"));
  const snapshot = api.snapshot(); f.projection.allowed_tools.fixture.push("later");
  assert.deepEqual(snapshot.projection.allowed_tools.fixture, ["search"]);
  await api.close();
});

test("manual session-only Enable creates only the selected transport and preserves original receivers", async () => {
  const f = fixture(), api = await f.install();
  assert.throws(() => f.state.mcp.createTransport(f.state.mcp.loadConfig(f.ctx).servers[0], f.ctx.cwd), fixed("PI_MCP_TRANSPORT_INVALID"));
  const transport = f.state.mcp.createTransport(f.enabled(), f.ctx.cwd);
  await transport.start(); await transport.send({ jsonrpc: "2.0", id: 1, method: "ping" });
  transport.setProtocolVersion("2025-06-18");
  assert.equal(f.state.starts, 1); assert.equal(f.state.sends, 1); assert.equal(f.state.version, "2025-06-18");
  await transport.close(); await api.close(); assert.equal(f.state.closes, 1);
});

test("wrong entry endpoint/cwd/tool scope and authnone provider cannot reach transport controller", async () => {
  const f = fixture(), api = await f.install(), base = f.enabled();
  for (const entry of [{ ...base, name: "foreign" }, { ...base, source: "/ambient" }, { ...base, config: { ...base.config, url: "https://foreign.invalid" } },
    { ...base, config: { ...base.config, toolExposure: { "*": "direct" } } }, { ...base, config: { ...base.config, oauth: { callbackUrl: "http://localhost:9999" } } }])
    assert.throws(() => f.state.mcp.createTransport(entry, f.ctx.cwd), fixed("PI_MCP_TRANSPORT_INVALID"));
  assert.throws(() => f.state.mcp.createTransport(base, "/foreign"), fixed("PI_MCP_TRANSPORT_INVALID"));
  assert.throws(() => f.state.mcp.createTransport(base, f.ctx.cwd, {}), fixed("PI_MCP_TRANSPORT_INVALID"));
  assert.equal(f.state.creates, 0); await api.close();
});

test("unsupported names/wildcards/hash-length/collisions fail without guessing SDK mapper", () => {
  for (const names of [["*"], ["has__separator"], ["non.ascii"], ["x".repeat(70)], ["a-b", "a_b"]]) {
    const f = fixture(); f.projection.allowed_tools.fixture = names;
    f.projection.loaded_config.servers[0].config.toolExposure = Object.fromEntries(names.map(name => [name, "codemode"]));
    assert.throws(f.build, error => error.code?.startsWith("PI_MCP_"));
  }
});

test("hidden undeclared MCP registrations are filtered while other unknown definitions fail", async () => {
  const f = fixture(), api = await f.install();
  const extra = f.definition("mcp__fixture__extra"); extra.exposure = "hidden";
  f.state.view.registerTool(extra); assert.equal(f.tools.has(extra.name), false);
  assert.equal(api.snapshot().filtered_registrations, 1);
  assert.throws(() => f.state.view.registerTool(f.definition("foreign")), fixed("PI_MCP_REGISTRATION_INVALID"));
  assert.throws(() => f.state.view.registerTool(f.definition("mcp__fixture__hashed_suffix")), fixed("PI_MCP_REGISTRATION_INVALID"));
  await api.close();
  const g = fixture(); g.projection.allowed_tools.fixture = ["search_bad"];
  g.projection.loaded_config.servers[0].config.toolExposure = { search_bad: "codemode" };
  const other = await g.install(), alias = g.definition("mcp__fixture__search_bad");
  alias.label = "fixture/search-bad"; alias.exposure = "direct";
  assert.throws(() => g.state.view.registerTool(alias), fixed("PI_MCP_REGISTRATION_INVALID"));
  await other.close();
});

test("invoke owns one action with independent frozen finite JSON and original execute context/signal/update", async () => {
  const f = fixture(), api = await f.install(), raw = f.register(), input = { ratio: 1.25, nested: { value: 2 } }, signal = new AbortController().signal, update = () => {};
  f.state.invocation = async (request, execute) => { input.nested.value = 99; assert.equal(Object.isFrozen(request.input.nested), true); return execute(); };
  await f.call(undefined, input, signal, update);
  assert.equal(f.state.receiver, raw); assert.equal(f.state.args[1].nested.value, 2);
  assert.equal(f.state.args[2], signal); assert.equal(f.state.args[3], update); assert.equal(f.state.args[4], f.ctx);
  assert.deepEqual(Object.keys(f.state.request).sort(), ["action", "ctx", "id", "input", "name", "server_name", "signal"]);
  assert.equal(f.state.request.action, "tool"); assert.equal(f.state.request.name, "search"); assert.equal(f.state.request.server_name, "fixture"); await api.close();
});

test("controller cannot claim success without invoking execute", async () => {
  const f = fixture(), api = await f.install(); f.register(); let late;
  f.state.invocation = (_request, execute) => { late = execute; return { content: [] }; };
  await assert.rejects(f.call(), fixed("PI_MCP_OPERATION_REJECTED")); assert.equal(f.state.runs, 0);
  assert.throws(() => late(), fixed("PI_MCP_EXECUTE_REUSED")); assert.equal(f.state.runs, 0); await api.close();
});

test("execute closure is once-only", async () => {
  const f = fixture(), api = await f.install(); f.register();
  f.state.invocation = async (_request, execute) => { await execute(); return execute(); };
  await assert.rejects(f.call(), fixed("PI_MCP_EXECUTE_REUSED")); assert.equal(f.state.runs, 1); await api.close();
});

test("foreign execute errors and malformed result become fixed private errors", async () => {
  const f = fixture(), api = await f.install(); f.register(); f.state.rawError = true;
  await assert.rejects(f.call(), error => error.code === "PI_MCP_OPERATION_REJECTED" && !error.message.includes("SYNTHETIC"));
  f.state.errorCode = "PI_MCP_FOREIGN";
  await assert.rejects(f.call(), error => error.code === "PI_MCP_OPERATION_REJECTED" && !error.message.includes("SYNTHETIC"));
  f.state.rawError = false; f.state.result = { content: "malformed" };
  await assert.rejects(f.call(), fixed("PI_MCP_RESULT_INVALID"));
  f.state.result = { content: [123] };
  await assert.rejects(f.call(), fixed("PI_MCP_RESULT_INVALID")); await api.close();
});

test("registration generations retire old wrappers and public ToolInfo rejects foreign same names", async () => {
  const f = fixture(), api = await f.install(); f.register(); const old = f.tools.get("mcp__fixture__search"); const before = api.snapshot().registration_generation;
  f.register(); assert.ok(api.snapshot().registration_generation > before);
  await assert.rejects(old.execute("old", {}, undefined, undefined, f.ctx), fixed("PI_MCP_REGISTRATION_INVALID"));
  await f.call(); const current = f.register(); current.label = "fixture/foreign";
  await assert.rejects(f.call(), fixed("PI_MCP_REGISTRATION_INVALID")); current.label = "fixture/search";
  f.state.foreign = true;
  assert.throws(() => f.state.view.getAllTools(), fixed("PI_MCP_REGISTRATION_INVALID")); await api.close();
});

test("invalid private input is rejected before permission/controller execution", async () => {
  const f = fixture(), api = await f.install(); f.register();
  await assert.rejects(f.call(undefined, { value: NaN }), fixed("PI_MCP_OPERATION_REJECTED"));
  assert.equal(f.state.invoke, 0); assert.equal(f.state.runs, 0); await api.close();
});

test("cancellation blocks pre-execution and late success", async () => {
  const f = fixture(), api = await f.install(); f.register(); const cancelled = new AbortController(); cancelled.abort();
  await assert.rejects(f.call(undefined, {}, cancelled.signal), fixed("PI_MCP_OPERATION_REJECTED"));
  let release; f.state.wait = new Promise(resolve => { release = resolve; }); const running = new AbortController(); const call = f.call(undefined, {}, running.signal);
  await Promise.resolve(); running.abort(); release(); await assert.rejects(call, fixed("PI_MCP_OPERATION_REJECTED")); await api.close();
});

test("shutdown retires immediately and closes every created transport once despite failure", async () => {
  const f = fixture(), api = await f.install(); f.register();
  f.state.mcp.createTransport(f.enabled(), f.ctx.cwd); f.state.mcp.createTransport(f.enabled(), f.ctx.cwd); f.state.closeError = true;
  const pending = api.close(); assert.throws(api.snapshot, fixed("PI_MCP_RETIRED"));
  await assert.rejects(pending, fixed("PI_MCP_CLOSE_FAILED")); await assert.rejects(api.close(), fixed("PI_MCP_CLOSE_FAILED"));
  assert.equal(f.state.closes, 2); await assert.rejects(f.call(), fixed("PI_MCP_RETIRED"));
});

test("late transport start cannot revive a shutdown session", async () => {
  const f = fixture(), api = await f.install(); let release; f.state.transportWait = new Promise(resolve => { release = resolve; });
  const transport = f.state.mcp.createTransport(f.enabled(), f.ctx.cwd), start = transport.start();
  await f.emit("session_shutdown"); release(); await assert.rejects(start, fixed("PI_MCP_TRANSPORT_FAILED")); assert.equal(f.state.closes, 1);
});

test("public callbacks preserve receiver/unsubscribe and suppress late data without claiming EOF termination", async () => {
  const f = fixture(), api = await f.install(), transport = f.state.mcp.createTransport(f.enabled(), f.ctx.cwd); let messages = 0, closes = 0;
  const unsubscribe = transport.onMessage(function () { assert.equal(this, f.state.raw); messages++; });
  transport.onClose(() => closes++); transport.onError(error => assert.equal(error.message, "PI_MCP_TRANSPORT_FAILED"));
  f.state.callbacks.onMessage.call(f.state.raw, {}); f.state.callbacks.onError(Error("SYNTHETIC-PRIVATE")); f.state.callbacks.onClose();
  assert.equal(f.state.closes, 0); unsubscribe(); assert.equal(f.state.unsub, "onMessage");
  await api.close(); f.state.callbacks.onMessage({}); assert.equal(messages, 1); assert.equal(closes, 1); assert.equal(f.state.closes, 1);
});

test("codemode avoids double invoke and marks nested public tool_result failure while keeping original content/details", async () => {
  const f = fixture(), api = await f.install(); f.register();
  f.state.code = async () => { await f.call(); await f.emit("tool_result", { isError: true, toolCallId: "root/1", parentToolCallId: "root" });
    return { content: [{ type: "text", text: "original" }], details: { original: true } }; };
  const result = await f.tools.get("codemode").execute("root", { code: "synthetic" }, undefined, undefined, f.ctx);
  assert.equal(result.isError, true); assert.deepEqual(result.details, { original: true }); assert.equal(result.content[0].text, "original"); assert.equal(f.state.invoke, 1); await api.close();
});

test("resource aggregate and single server scopes stay inside frozen selected services", async () => {
  const f = fixture(), api = await f.install();
  await f.call("list_mcp_resources", {}); assert.equal(f.state.request.server_name, null); assert.equal(f.state.request.action, "list_resources");
  await f.call("list_mcp_resource_templates", { server: "fixture" }); assert.equal(f.state.request.server_name, "fixture"); assert.equal(f.state.request.action, "list_templates");
  await f.call("tool_search", { query: "synthetic" }); assert.equal(f.state.request.action, "tool_search");
  await assert.rejects(f.call("read_mcp_resource", { server: "foreign", uri: "x" }), fixed("PI_MCP_OPERATION_REJECTED")); await api.close();
});

test("OAuth authProvider and browser are explicit controller interfaces with immutable callback binding", async () => {
  const f = fixture("oauth"), api = await f.install(), provider = {};
  const transport = f.state.mcp.createTransport(f.enabled(), f.ctx.cwd, provider); assert.equal(f.state.transportArgs[2], provider);
  f.state.mcp.openUrl("https://fixture.invalid/authorize"); assert.equal(f.state.url, "https://fixture.invalid/authorize");
  const wrong = f.enabled(); wrong.config.oauth = { ...wrong.config.oauth, callbackUrl: "http://localhost:9999/foreign" };
  assert.throws(() => f.state.mcp.createTransport(wrong, f.ctx.cwd, provider), fixed("PI_MCP_TRANSPORT_INVALID")); await transport.close(); await api.close();
});

test("async creation/check and missing controller never fallback to SDK defaults", async () => {
  const f = fixture(); delete f.controller.credentials; assert.throws(f.build, fixed("PI_MCP_UNAVAILABLE"));
  const g = fixture(), api = g.build(); g.state.checkReturn = Promise.resolve(); await api.extensionFactories[0].factory(g.pi);
  await assert.rejects(g.emit("session_start"), fixed("PI_MCP_CONTROLLER_INVALID")); await api.close();
  const h = fixture(), other = await h.install(); h.state.asyncTransport = true;
  assert.throws(() => h.state.mcp.createTransport(h.enabled(), h.ctx.cwd), fixed("PI_MCP_TRANSPORT_INVALID")); await other.close();
});

test("native usesOAuth default honors empty Authorization marker before credentials/provider creation", async () => {
  const f = fixture(), api = await f.install();
  assert.deepEqual(f.state.mcp.loadConfig(f.ctx).servers[0].config.headers, { Authorization: "" });
  const transport = f.state.nativeEnable(f.enabled());
  assert.equal(f.state.credentialReads ?? 0, 0); assert.equal(f.state.transportArgs[2], undefined);
  assert.deepEqual(f.state.transportArgs[0].config.headers, { Authorization: "" });
  await transport.close(); await api.close();
});

test("parallel Code Mode roots keep nested failure isolated after out-of-order completion", async () => {
  const f = fixture(), api = await f.install();
  let releaseFailed, releaseSuccessful, enteredFailed, enteredSuccessful;
  const failedGate = new Promise(resolve => { releaseFailed = resolve; });
  const successfulGate = new Promise(resolve => { releaseSuccessful = resolve; });
  const failedEntered = new Promise(resolve => { enteredFailed = resolve; });
  const successfulEntered = new Promise(resolve => { enteredSuccessful = resolve; });
  f.state.code = async (id) => {
    if (id === "failed-root") {
      enteredFailed(); await failedGate;
      // SDK 的失败事件可能来自非零子操作；外层结果不能吞掉它。
      await f.emit("tool_result", { isError: true, toolCallId: id + "/child", parentToolCallId: id });
    } else {
      enteredSuccessful(); await successfulGate;
      await f.emit("tool_result", { isError: false, toolCallId: id + "/child", parentToolCallId: id });
    }
    return { content: [{ type: "text", text: id }], details: { originalRoot: id } };
  };
  const definition = f.tools.get("codemode");
  const failed = definition.execute("failed-root", {}, undefined, undefined, f.ctx);
  const successful = definition.execute("successful-root", {}, undefined, undefined, f.ctx);
  await Promise.all([failedEntered, successfulEntered]);
  releaseFailed(); const failedResult = await failed;
  releaseSuccessful(); const successfulResult = await successful;
  assert.equal(failedResult.isError, true);
  assert.notEqual(successfulResult.isError, true);
  assert.deepEqual(failedResult.details, { originalRoot: "failed-root" });
  assert.deepEqual(successfulResult.content, [{ type: "text", text: "successful-root" }]);
  assert.equal(f.state.invoke, 0);
  await api.close();
});

test("unrelated failed event cannot overwrite a successful Code Mode root", async () => {
  const f = fixture(), api = await f.install();
  f.state.code = async () => {
    await f.emit("tool_result", { isError: true, toolCallId: "foreign/child", parentToolCallId: "foreign" });
    return { content: [{ type: "text", text: "own result" }], details: { kept: true } };
  };
  const result = await f.tools.get("codemode").execute("own", {}, undefined, undefined, f.ctx);
  assert.notEqual(result.isError, true);
  assert.deepEqual(result.details, { kept: true });
  assert.equal(f.state.invoke, 0);
  await api.close();
});
