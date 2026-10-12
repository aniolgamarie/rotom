// 官方MCP公开工厂的受控组合；controller由仓库所有者提供，模型不能提供它。
import { AsyncLocalStorage } from "node:async_hooks";
import { isDeepStrictEqual } from "node:util";
import { isAbsolute, resolve } from "node:path";
import { captureOperationInput } from "./private-operation-input.ts";

const statics = ["codemode", "list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource", "tool_search"];
const modes = ["hidden", "codemode", "deferred", "direct"];
const fields = new Set(["name", "label", "description", "parameters", "execute", "promptSnippet", "promptGuidelines", "constrainedSampling", "renderShell", "prepareArguments", "outputSchema", "exposure", "namespace", "annotations", "defaultActive", "prepareLoadout", "executionMode", "renderCall", "renderResult"]);
const ownErrors = new WeakSet();
const fail = (code = "PI_MCP_UNAVAILABLE") => { const error = new Error(code); error.code = code; error.exitCode = 4; ownErrors.add(error); throw error; };
const closed = (value, keys, required = keys) => {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some(key => !keys.includes(key))
      || required.some(key => !Object.hasOwn(value, key))) fail("PI_MCP_CONFIGURATION_INVALID");
};
const copy = value => captureOperationInput(value, { allowFiniteNumbers: true }).value;
const component = value => typeof value === "string" && /^[A-Za-z0-9_-]+$/.test(value) && !value.includes("__");
const variable = value => typeof value === "string" && /^\$\{AGENTCFG_PI_CREDENTIAL_[A-Z0-9_]+\}$/.test(value);
const synchronous = value => {
  if (value && typeof value.then === "function") {
    if (value instanceof Promise) Promise.prototype.then.call(value, undefined, () => {});
    fail("PI_MCP_CONTROLLER_INVALID");
  }
  return value;
};

function projectionInput(projection) {
  let fixed;
  try { fixed = copy(projection); } catch { fail("PI_MCP_CONFIGURATION_INVALID"); }
  closed(fixed, ["schema_version", "loaded_config", "bindings", "allowed_tools"]);
  if (fixed.schema_version !== 1) fail("PI_MCP_CONFIGURATION_INVALID");
  closed(fixed.loaded_config, ["servers", "errors", "autoEnableCodemode"]);
  closed(fixed.bindings, Object.keys(fixed.bindings ?? {}));
  closed(fixed.allowed_tools, Object.keys(fixed.allowed_tools ?? {}));
  if (!Array.isArray(fixed.loaded_config.servers) || !Array.isArray(fixed.loaded_config.errors)
      || fixed.loaded_config.errors.length || fixed.loaded_config.autoEnableCodemode !== false) fail("PI_MCP_CONFIGURATION_INVALID");
  const declarations = new Map(), entries = new Map(), names = new Set();
  for (const entry of fixed.loaded_config.servers) {
    closed(entry, ["name", "config", "source", "scope"]);
    if (!component(entry.name) || entries.has(entry.name) || entry.scope !== "extension"
        || entry.source !== "agentcfg:registry/mcp/" + entry.name) fail("PI_MCP_CONFIGURATION_INVALID");
    const binding = fixed.bindings[entry.name], allowed = fixed.allowed_tools[entry.name];
    if (!binding || !Array.isArray(allowed) || allowed.length > 64 || new Set(allowed).size !== allowed.length) fail("PI_MCP_CONFIGURATION_INVALID");
    closed(binding, ["transport", "command_ref", "network_route", "authentication", "credential_ref", "oauth_policy"], ["transport", "authentication"]);
    const config = entry.config;
    closed(config, ["type", "command", "args", "cwd", "env", "url", "headers", "oauth", "exposure", "toolExposure", "enabled"], ["type", "exposure", "toolExposure"]);
    closed(config.toolExposure, Object.keys(config.toolExposure ?? {}));
    if (config.exposure !== "hidden" || Object.hasOwn(config, "enabled") && config.enabled !== false
        || !isDeepStrictEqual(Object.keys(config.toolExposure).sort(), [...allowed].sort())) fail("PI_MCP_CONFIGURATION_INVALID");
    if (Object.values(config.toolExposure).some(mode => !["codemode", "direct"].includes(mode))) fail("PI_MCP_CONFIGURATION_INVALID");
    if (binding.transport === "stdio") {
      if (binding.authentication !== "none" || config.type !== "stdio" || typeof config.command !== "string" || !isAbsolute(config.command)
          || typeof config.cwd !== "string" || !isAbsolute(config.cwd) || !Array.isArray(config.args)
          || config.args.some(arg => typeof arg !== "string") || !isDeepStrictEqual(config.env, {}) || config.url || config.headers || config.oauth) fail("PI_MCP_CONFIGURATION_INVALID");
    } else if (["sse", "streamable-http"].includes(binding.transport)) {
      if (config.type !== "http" || typeof config.url !== "string" || !["none", "bearer", "oauth"].includes(binding.authentication)
          || !binding.network_route || config.command || config.args || config.cwd || config.env) fail("PI_MCP_CONFIGURATION_INVALID");
      if (binding.authentication === "none" && (!isDeepStrictEqual(config.headers, { Authorization: "" }) || config.oauth || binding.credential_ref || binding.oauth_policy)) fail("PI_MCP_CONFIGURATION_INVALID");
      if (binding.authentication === "bearer" && (!binding.credential_ref || config.oauth || !config.headers
          || Object.keys(config.headers).join() !== "Authorization" || !variable(config.headers.Authorization?.slice(7))
          || !config.headers.Authorization.startsWith("Bearer "))) fail("PI_MCP_CONFIGURATION_INVALID");
      if (binding.authentication === "oauth") {
        closed(config.oauth, ["clientId", "clientSecret", "scope", "authServerMetadataUrl", "callbackUrl"], ["callbackUrl"]);
        closed(binding.oauth_policy, ["allowed_origins", "callback_max_seconds"], ["allowed_origins"]);
        const redirect = new URL(config.oauth.callbackUrl);
        if (config.headers || redirect.protocol !== "http:" || !["localhost", "127.0.0.1", "[::1]"].includes(redirect.hostname)
            || !Array.isArray(binding.oauth_policy.allowed_origins) || config.oauth.clientSecret && !variable(config.oauth.clientSecret)) fail("PI_MCP_CONFIGURATION_INVALID");
      }
    } else fail("PI_MCP_CONFIGURATION_INVALID");
    for (const tool of allowed) {
      if (!component(tool)) fail("PI_MCP_TOOL_NAME_UNSUPPORTED");
      const name = "mcp__" + entry.name.replaceAll("-", "_") + "__" + tool.replaceAll("-", "_");
      if (name.length > 64 || names.has(name)) fail("PI_MCP_TOOL_NAME_UNSUPPORTED");
      names.add(name); declarations.set(name, { server: entry.name, tool });
    }
    if ([...entries.keys()].some(name => name.replaceAll("-", "_") === entry.name.replaceAll("-", "_"))) fail("PI_MCP_TOOL_NAME_UNSUPPORTED");
    entries.set(entry.name, entry);
  }
  if (!isDeepStrictEqual(Object.keys(fixed.bindings).sort(), [...entries.keys()].sort())
      || !isDeepStrictEqual(Object.keys(fixed.allowed_tools).sort(), [...entries.keys()].sort())) fail("PI_MCP_CONFIGURATION_INVALID");
  return { fixed, entries, declarations };
}

export function createOfficialMcpFactories({ sdk, projection, controller }) {
  if (process.platform !== "linux" || typeof sdk?.createMcpExtension !== "function" || typeof sdk?.createCodemodeExtension !== "function"
      || !controller || ["createTransport", "openUrl", "invoke", "check"].some(name => typeof controller[name] !== "function")
      || !controller.credentials || ["forServer", "tokens", "remove"].some(name => typeof controller.credentials[name] !== "function")) fail();
  let parsed;
  try { parsed = projectionInput(projection); } catch (error) { if (ownErrors.has(error)) throw error; fail("PI_MCP_CONFIGURATION_INVALID"); }
  const { fixed, entries, declarations } = parsed;
  const original = Object.fromEntries(["createTransport", "openUrl", "invoke", "check"].map(name => [name, controller[name]]));
  const credentials = controller.credentials;
  const registry = new Map(), transports = new Set(), roots = new AsyncLocalStorage();
  let retired = false, context, sessionCwd, sessionGeneration = 0, generation = 0, filtered = 0, closePromise, installed = false;
  const alive = () => { if (retired) fail("PI_MCP_RETIRED"); };
  const check = ctx => {
    alive();
    try { synchronous(original.check.call(controller, ctx)); }
    catch (error) { if (ownErrors.has(error)) throw error; fail("PI_MCP_CONTEXT_INVALID"); }
    alive();
  };
  const active = ctx => { alive(); if (!context || !ctx || ctx.cwd !== sessionCwd) fail("PI_MCP_CONTEXT_INVALID"); check(ctx); };
  const error = code => fail(code);
  const entryForTransport = (entry, cwd, authProvider) => {
    active(context);
    const selected = entries.get(entry?.name);
    if (!selected || cwd !== sessionCwd || !isAbsolute(cwd) || resolve(cwd) !== cwd) fail("PI_MCP_TRANSPORT_INVALID");
    closed(entry, ["name", "config", "source", "scope"]);
    if (entry.source !== selected.source || entry.scope !== selected.scope) fail("PI_MCP_TRANSPORT_INVALID");
    const config = entry.config, base = selected.config;
    const stable = value => Object.fromEntries(Object.entries(value).filter(([key]) => !["enabled", "exposure", "toolExposure"].includes(key)));
    if (!isDeepStrictEqual(stable(config), stable(base)) || typeof config.enabled !== "boolean" || config.enabled !== true
        || !modes.includes(config.exposure) || !isDeepStrictEqual(Object.keys(config.toolExposure).sort(), Object.keys(base.toolExposure).sort())
        || Object.values(config.toolExposure).some(mode => !modes.includes(mode))) fail("PI_MCP_TRANSPORT_INVALID");
    if (fixed.bindings[entry.name].authentication === "none" && authProvider !== undefined) fail("PI_MCP_TRANSPORT_INVALID");
    return copy(entry);
  };
  function transport(entry, cwd, authProvider) {
    let safe, raw;
    try { safe = entryForTransport(entry, cwd, authProvider); raw = synchronous(original.createTransport.call(controller, safe, cwd, authProvider)); }
    catch { fail("PI_MCP_TRANSPORT_INVALID"); }
    const methods = {};
    const record = { raw, methods, sessionGeneration, retired: false, closing: undefined }; transports.add(record);
    try { for (const name of ["close", "start", "send", "onMessage", "onError", "onClose", "setProtocolVersion"]) methods[name] = raw?.[name]; }
    catch { fail("PI_MCP_TRANSPORT_INVALID"); }
    if (["start", "send", "close", "onMessage", "onError", "onClose"].some(name => typeof methods[name] !== "function")) fail("PI_MCP_TRANSPORT_INVALID");
    const live = () => { active(context); if (record.retired || record.sessionGeneration !== sessionGeneration) fail("PI_MCP_RETIRED"); };
    const shutdown = () => {
      if (record.closing) return record.closing;
      record.retired = true;
      record.closing = Promise.resolve().then(() => methods.close.call(raw)).then(value => { transports.delete(record); return value; }).catch(() => error("PI_MCP_CLOSE_FAILED"));
      return record.closing;
    };
    const facade = { close: shutdown };
    for (const name of ["start", "send"]) facade[name] = async (...args) => {
      try { live(); const result = await methods[name].apply(raw, args); live(); return result; }
      catch { fail("PI_MCP_TRANSPORT_FAILED"); }
    };
    for (const name of ["onMessage", "onError", "onClose"]) facade[name] = listener => {
      live(); if (typeof listener !== "function") fail("PI_MCP_TRANSPORT_INVALID");
      return methods[name].call(raw, function (...args) {
        if (name !== "onClose" && (retired || record.retired)) return;
        if (name === "onError") args = [new Error("PI_MCP_TRANSPORT_FAILED")];
        return listener.apply(this, args);
      });
    };
    if (typeof methods.setProtocolVersion === "function") facade.setProtocolVersion = version => { live(); return methods.setProtocolVersion.call(raw, version); };
    return Object.freeze(facade);
  }
  function close() {
    if (closePromise) return closePromise;
    retired = true; generation++;
    for (const record of registry.values()) record.retired = true;
    closePromise = Promise.allSettled([...transports].map(record => {
      if (record.closing) return record.closing;
      record.retired = true;
      record.closing = Promise.resolve().then(() => {
        if (typeof record.methods.close !== "function") fail("PI_MCP_CLOSE_FAILED");
        return record.methods.close.call(record.raw);
      }).then(value => { transports.delete(record); return value; });
      return record.closing;
    })).then(results => { if (results.some(result => result.status === "rejected")) fail("PI_MCP_CLOSE_FAILED"); });
    return closePromise;
  }
  const snapshot = () => { alive(); return Object.freeze({ schema_version: 1, projection: fixed, registration_generation: generation, filtered_registrations: filtered }); };
  const allowedToolNames = Object.freeze([...statics, ...declarations.keys()]);
  const factory = async pi => {
    alive(); if (installed || typeof pi?.registerTool !== "function" || typeof pi?.on !== "function" || typeof pi?.getAllTools !== "function") fail();
    installed = true;
    const api = { registerTool: pi.registerTool, on: pi.on, getAllTools: pi.getAllTools };
    const sourcePath = "<inline:rotom-native-mcp>";
    const info = () => {
      alive(); const rows = api.getAllTools.call(pi);
      if (!Array.isArray(rows)) fail("PI_MCP_REGISTRATION_INVALID");
      for (const name of registry.keys()) {
        const matches = rows.filter(row => row.name === name);
        if (matches.length !== 1 || matches[0].sourceInfo?.path !== sourcePath) fail("PI_MCP_REGISTRATION_INVALID");
      }
      return rows.filter(row => registry.has(row.name));
    };
    const result = value => {
      if (!value || typeof value !== "object" || Array.isArray(value) || !Array.isArray(value.content)
          || value.content.some(item => !item || typeof item !== "object"
            || (item.type === "text" ? typeof item.text !== "string" : item.type === "image" ? typeof item.data !== "string" || typeof item.mimeType !== "string" : true))
          || value.isError !== undefined && typeof value.isError !== "boolean") fail("PI_MCP_RESULT_INVALID");
      return value;
    };
    function register(definition) {
      alive();
      if (!definition || typeof definition !== "object" || typeof definition.name !== "string"
          || typeof definition.execute !== "function" || Object.keys(definition).some(key => !fields.has(key))) fail("PI_MCP_REGISTRATION_INVALID");
      const mapping = declarations.get(definition.name);
      if (!mapping && !statics.includes(definition.name)) {
        if (definition.name.startsWith("mcp__")) {
          if (definition.exposure !== "hidden") fail("PI_MCP_REGISTRATION_INVALID");
          filtered++; return;
        }
        fail("PI_MCP_REGISTRATION_INVALID");
      }
      if (mapping && (definition.namespace?.name !== "mcp__" + mapping.server.replaceAll("-", "_")
          || definition.label !== mapping.server + "/" + mapping.tool)) fail("PI_MCP_REGISTRATION_INVALID");
      const previous = registry.get(definition.name); if (previous) previous.retired = true;
      const record = { definition, execute: definition.execute, name: definition.name, sessionGeneration, retired: false, generation: ++generation };
      registry.set(record.name, record);
      const valid = ctx => {
        active(ctx); info();
        if (record.retired || mapping && record.sessionGeneration !== sessionGeneration || registry.get(record.name) !== record || definition.execute !== record.execute || definition.name !== record.name
            || definition.exposure === "hidden" || mapping && (definition.label !== mapping.server + "/" + mapping.tool
              || definition.namespace?.name !== "mcp__" + mapping.server.replaceAll("-", "_"))) fail("PI_MCP_REGISTRATION_INVALID");
      };
      const execute = async function (id, input, signal, update, ctx) {
        try {
          valid(ctx); if (typeof id !== "string" || !id || signal?.aborted) fail("PI_MCP_OPERATION_REJECTED");
          const captured = copy(input);
          const run = async () => { valid(ctx); if (signal?.aborted) fail("PI_MCP_OPERATION_REJECTED");
            const value = await record.execute.call(definition, id, captured, signal, update, ctx);
            valid(ctx); if (signal?.aborted) fail("PI_MCP_OPERATION_REJECTED"); return result(value); };
          if (record.name === "codemode") {
            const root = { id, failed: false };
            const value = await roots.run(root, run);
            return root.failed ? { ...value, isError: true } : value;
          }
          const resourceActions = { list_mcp_resources: "list_resources", list_mcp_resource_templates: "list_templates", read_mcp_resource: "read_resource", tool_search: "tool_search" };
          const server = mapping?.server ?? captured.server ?? null;
          if (server !== null && !entries.has(server) || record.name === "read_mcp_resource" && server === null) fail("PI_MCP_OPERATION_REJECTED");
          let called = false, finished = false, pending;
          const perform = () => { if (called || finished) fail("PI_MCP_EXECUTE_REUSED"); called = true; pending = run(); pending.catch(() => {}); return pending; };
          const request = Object.freeze({ id, server_name: server, action: mapping ? "tool" : resourceActions[record.name],
            name: mapping?.tool ?? record.name, input: captured, signal, ctx });
          let value;
          try { value = await original.invoke.call(controller, request, perform); }
          finally { finished = true; }
          valid(ctx);
          if (!called) fail("PI_MCP_OPERATION_REJECTED");
          await pending; valid(ctx); if (signal?.aborted) fail("PI_MCP_OPERATION_REJECTED"); return result(value);
        } catch (error) {
          if (ownErrors.has(error)) throw error;
          fail("PI_MCP_OPERATION_REJECTED");
        }
      };
      api.registerTool.call(pi, { ...definition, execute });
    }
    const view = {};
    for (const [key, value] of Object.entries(pi)) view[key] = typeof value === "function" ? (...args) => value.apply(pi, args) : value;
    Object.assign(view, { registerTool: register, getAllTools: info, getMcpServers: () => [],
      registerMcpServer: () => fail("PI_MCP_REGISTRATION_INVALID") });
    Object.freeze(view);
    api.on.call(pi, "session_start", (_event, ctx) => {
      check(ctx);
      if (typeof ctx?.cwd !== "string" || !isAbsolute(ctx.cwd) || resolve(ctx.cwd) !== ctx.cwd) fail("PI_MCP_CONTEXT_INVALID");
      context = ctx; sessionCwd = ctx.cwd; sessionGeneration++; generation++;
    });
    api.on.call(pi, "session_shutdown", () => close());
    api.on.call(pi, "tool_result", event => {
      const root = roots.getStore();
      if (root && event.isError === true && (event.parentToolCallId === root.id || event.toolCallId?.startsWith(root.id + "/"))) root.failed = true;
    });
    try {
      const mcp = sdk.createMcpExtension({ loadConfig: ctx => {
        active(ctx); return copy({ ...fixed.loaded_config, servers: [...entries.values()].map(entry => ({ ...entry, config: { ...entry.config, enabled: false } })) });
      }, createTransport: transport, credentials, openUrl: url => {
        active(context);
        try { return original.openUrl.call(controller, url); } catch { fail("PI_MCP_AUTH_UNAVAILABLE"); }
      },
      updateConfig: () => fail("PI_MCP_CONFIG_WRITE_REJECTED"), logPath: "/dev/null" });
      const codemode = sdk.createCodemodeExtension({ models: false });
      await mcp(view); alive(); await codemode(view); alive();
    } catch {
      try { await close(); } catch { fail("PI_MCP_CLOSE_FAILED"); }
      fail("PI_MCP_FACTORY_FAILED");
    }
  };
  return Object.freeze({ extensionFactories: Object.freeze([Object.freeze({ name: "rotom-native-mcp", factory })]), allowedToolNames, snapshot, close });
}
