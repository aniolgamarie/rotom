// 主模型公开能力视图；真实ModelRuntime仍保留原实例/原型/原Receiver。
import { isDeepStrictEqual } from "node:util";
import { captureOperationInput } from "./private-operation-input.ts";

const failures = new WeakSet();
const fail = (code = "MODEL_SCOPE_DENIED") => { const error = new Error(code); error.code = code; error.exitCode = 4; failures.add(error); throw error; };
const requests = ["stream", "complete", "streamSimple", "completeSimple", "streamDeferred", "fetchDeferred", "cancelDeferred", "generateImages", "classify"];
const mutations = ["setRuntimeApiKey", "removeRuntimeApiKey", "registerNativeProvider", "registerProvider", "unregisterProvider", "registerVirtualModel", "unregisterVirtualModel"];
const publicMethods = ["getProviders", "getProvider", "getModels", "getModel", "getModelsOfType", "getModelOfType", "getAllModels", "getAvailableOfType", "getAllAvailable", "checkAuth", "getAvailable", "getAvailableSnapshot", "getError", "getRegisteredProviderConfig", "getRegisteredProviderIds", "getRegisteredNativeProvider", "getCompatibilityRequestConfig", "isUsingOAuth", "isUsingSubscription", "hasConfiguredAuth", "getAuth", "listCredentials", "getProviderAuthStatus", "login", "logout", "refresh", "resolveModel", "getPhysicalModel", ...requests, ...mutations];
const safeOptions = new Set(["signal", "telemetryContext", "timeoutMs", "maxRetries", "maxRetryDelayMs", "temperature", "maxTokens", "transport", "cacheRetention", "sessionId", "websocketConnectTimeoutMs", "metadata", "reasoning", "thinkingBudgets", "reasoningEffort", "wait", "size", "quality", "n", "format", "onPayload", "onResponse", "onProviderStreamEvent", "transformHeaders", "apiKey", "headers", "env"]);
// 公开AgentLoopConfig会被SDK展开到stream options；循环控制留在Agent，不能交给Provider。
const loopCallbacks = ["beforeToolCall", "afterToolCall", "finishTurn", "prepareRequest", "prepareNextTurn", "convertToLlm", "transformContext", "getApiKey", "getSteeringMessages", "getFollowUpMessages"];
const streamOptions = new Set([...safeOptions, "model", "toolExecution", ...loopCallbacks]);
const protectedHeader = name => /^(authorization|proxy-authorization|host|cookie|api-key|x-api-key|x-goog-api-key)$/i.test(name);
const key = model => JSON.stringify([model.provider, model.id]);
const copy = value => captureOperationInput(value, { allowFiniteNumbers: true }).value;
const options = (value, names) => {
  if (value === undefined) return {};
  if (!value || Object.getPrototypeOf(value) !== Object.prototype || Object.keys(value).some(name => !names.has(name))) fail("MODEL_SCOPE_OPTIONS_UNSUPPORTED");
  return value;
};

export function createOfficialModelScope({ modelRuntime: target, manifest, describe }) {
  if (!target || Object.getPrototypeOf(target) === Object.prototype || typeof describe !== "function") fail("MODEL_SCOPE_INCOMPATIBLE");
  const original = new Map();
  for (const name of publicMethods) {
    const descriptor = Object.getOwnPropertyDescriptor(target, name);
    if (descriptor && !descriptor.configurable && !descriptor.writable) fail("MODEL_SCOPE_INCOMPATIBLE");
    const method = Reflect.get(target, name, target);
    if (typeof method === "function") original.set(name, method);
  }
  if (["getModel", "getProvider", "getAuth", "checkAuth"].some(name => !original.has(name))) fail("MODEL_SCOPE_INCOMPATIBLE");
  const call = (name, ...args) => {
    if (!original.has(name)) fail("MODEL_SCOPE_UNSUPPORTED");
    try {
      const value = original.get(name).apply(target, args);
      return value instanceof Promise ? value.catch(error => { if (failures.has(error)) throw error; fail("MODEL_SCOPE_OPERATION_FAILED"); }) : value;
    } catch (error) { if (failures.has(error)) throw error; fail("MODEL_SCOPE_OPERATION_FAILED"); }
  };
  let rows, bindings;
  try { rows = copy(manifest.allowed_models); bindings = copy(manifest.provider_bindings); } catch { fail("MODEL_SCOPE_CONFIGURATION"); }
  if (!Array.isArray(rows) || !rows.length || rows.length > 4096 || rows.some(row => !row || Object.keys(row).sort().join() !== "model,provider"
      || typeof row.provider !== "string" || typeof row.model !== "string") || new Set(rows.map(row => JSON.stringify([row.provider, row.model]))).size !== rows.length) fail("MODEL_SCOPE_CONFIGURATION");
  const providers = [...new Set(rows.map(row => row.provider))], selected = new Set(rows.map(row => JSON.stringify([row.provider, row.model])));
  if (!bindings || !isDeepStrictEqual(Object.keys(bindings).sort(), [...providers].sort())) fail("MODEL_SCOPE_CONFIGURATION");
  const descriptions = new Map(), auth = new Map(), views = new Map(), epochs = new Map(providers.map(p => [p, 0]));
  const notAborted = signal => { if (signal?.aborted) fail("MODEL_SCOPE_CANCELED"); };
  let bytes = 0;
  const provider = value => { if (!providers.includes(value)) fail("MODEL_SCOPE_PROVIDER_DENIED"); return value; };
  const metadata = model => { try { return copy(describe(model)); } catch { fail("MODEL_SCOPE_MODEL_DENIED"); } };
  for (const row of rows) {
    const model = call("getModel", row.provider, row.model);
    if (!model && bindings[row.provider].auth_kind === "oauth") continue;
    if (!model || model.provider !== row.provider || model.id !== row.model) fail("MODEL_SCOPE_MODEL_DENIED");
    descriptions.set(key(model), metadata(model));
  }
  const forget = id => { const record = auth.get(id); if (record) { clearTimeout(record.timer); bytes -= record.bytes; auth.delete(id); } };
  const remembered = id => { const record = auth.get(id); if (record && performance.now() >= record.until) { forget(id); return undefined; } return record; };
  const current = (p, id) => {
    if (original.has("getError") && call("getError") !== undefined) fail("MODEL_SCOPE_RUNTIME_ERROR");
    if (!selected.has(JSON.stringify([p, id]))) fail("MODEL_SCOPE_MODEL_DENIED");
    const model = call("getModel", p, id);
    if (!model && bindings[p].auth_kind === "oauth") return undefined;
    if (!model || model.provider !== p || model.id !== id) fail("MODEL_SCOPE_MODEL_DENIED");
    const pair = JSON.stringify([p, id]), observed = metadata(model);
    if (!descriptions.has(pair)) descriptions.set(pair, observed);
    if (!isDeepStrictEqual(observed, descriptions.get(pair))) fail("MODEL_SCOPE_MODEL_DENIED");
    return model;
  };
  const guard = model => {
    if (!model || !selected.has(key(model))) fail("MODEL_SCOPE_MODEL_DENIED");
    const actual = current(model.provider, model.id), expected = descriptions.get(key(model)), snapshot = remembered(key(model));
    if (!actual) fail("MODEL_SCOPE_MODEL_DENIED");
    let observed = model;
    if (model.baseUrl !== actual.baseUrl) {
      if (!snapshot?.value.auth.baseUrl || model.baseUrl !== snapshot.value.auth.baseUrl) fail("MODEL_SCOPE_MODEL_DENIED");
      observed = { ...model, baseUrl: actual.baseUrl };
    }
    if (!isDeepStrictEqual(metadata(observed), expected)) fail("MODEL_SCOPE_MODEL_DENIED");
    // 使用原目录model，不能通过description省略的私密headers注入请求。
    return model.baseUrl === actual.baseUrl ? actual : { ...actual, baseUrl: model.baseUrl };
  };
  const check = () => { if (original.has("getError") && call("getError") !== undefined) fail("MODEL_SCOPE_RUNTIME_ERROR"); for (const row of rows) current(row.provider, row.model); };
  const exposed = model => copy({ ...descriptions.get(key(model)), baseUrl: model.baseUrl, ...(model.type === undefined ? {} : { type: model.type }) });
  const saveAuth = (model, result) => {
    forget(key(model));
    if (!result) return;
    let value;
    try {
      const fields = Object.fromEntries(Object.entries(result.auth ?? {}).filter(([, value]) => value !== undefined));
      if (Object.keys(fields).some(name => !["apiKey", "headers", "baseUrl"].includes(name))) fail();
      value = copy({ auth: fields, ...(result.env === undefined ? {} : { env: result.env }) });
    } catch { fail("MODEL_SCOPE_AUTH_INVALID"); }
    const size = Buffer.byteLength(JSON.stringify(value));
    if (size > 1024 * 1024) fail("MODEL_SCOPE_AUTH_INVALID");
    while (auth.size >= 64 || bytes + size > 1024 * 1024) forget(auth.keys().next().value);
    const id = key(model), timer = setTimeout(() => forget(id), 60000); timer.unref();
    auth.set(id, { value, bytes: size, until: performance.now() + 60000, timer }); bytes += size;
  };
  const headerMap = value => {
    const output = new Map();
    if (!value || Object.getPrototypeOf(value) !== Object.prototype) fail("MODEL_SCOPE_HEADERS_INVALID");
    for (const [name, item] of Object.entries(value)) {
      if (typeof item !== "string" && item !== null || output.has(name.toLowerCase())) fail("MODEL_SCOPE_HEADERS_INVALID");
      output.set(name.toLowerCase(), item);
    }
    return output;
  };
  const requestOptions = (model, input) => {
    const value = options(input, streamOptions), snapshot = remembered(key(model));
    if (value.model !== undefined) {
      if (!value.model || typeof value.model !== "object") fail("MODEL_SCOPE_MODEL_DENIED");
      if (key(value.model) !== key(model)) fail("MODEL_SCOPE_MODEL_DENIED");
      guard(value.model);
    }
    if (value.toolExecution !== undefined && !["sequential", "parallel"].includes(value.toolExecution)) fail("MODEL_SCOPE_OPTIONS_UNSUPPORTED");
    for (const name of loopCallbacks) if (value[name] !== undefined && typeof value[name] !== "function") fail("MODEL_SCOPE_OPTIONS_UNSUPPORTED");
    if (value.signal !== undefined && !(value.signal instanceof AbortSignal)) fail("MODEL_SCOPE_OPTIONS_UNSUPPORTED");
    for (const name of ["apiKey", "headers", "env"]) if (value[name] !== undefined) {
      const expected = name === "env" ? snapshot?.value.env : snapshot?.value.auth[name];
      if (!snapshot || !isDeepStrictEqual(value[name], expected)) fail("MODEL_SCOPE_AUTH_OVERRIDE");
    }
    for (const name of ["onPayload", "onResponse", "onProviderStreamEvent", "transformHeaders"]) if (value[name] !== undefined && typeof value[name] !== "function") fail("MODEL_SCOPE_OPTIONS_UNSUPPORTED");
    const result = { ...value };
    for (const name of ["model", "toolExecution", ...loopCallbacks]) delete result[name];
    if (value.transformHeaders) {
      const callback = value.transformHeaders;
      result.transformHeaders = async headers => {
        guard(model);
        const before = headerMap(copy(headers));
        const protectedNames = new Set([...before.keys()].filter(protectedHeader));
        for (const name of Object.keys(remembered(key(model))?.value.auth.headers ?? {})) protectedNames.add(name.toLowerCase());
        let changed;
        try { changed = await callback(headers); } catch { fail("MODEL_SCOPE_HEADERS_INVALID"); }
        guard(model);
        const after = headerMap(changed);
        for (const name of new Set([...before.keys(), ...after.keys()])) if (protectedHeader(name)) protectedNames.add(name);
        for (const name of protectedNames) if (before.has(name) !== after.has(name) || before.get(name) !== after.get(name)) fail("MODEL_SCOPE_HEADERS_INVALID");
        return changed;
      };
    }
    return result;
  };
  const request = (method, model, payload, input) => {
    const bound = guard(model);
    if (bound.api === "pi-virtual") fail("MODEL_SCOPE_VIRTUAL_UNSUPPORTED");
    const prepared = requestOptions(model, input); notAborted(prepared.signal);
    return call(method, bound, payload, prepared);
  };
  const list = (p, type) => rows.filter(row => p === undefined || row.provider === provider(p)).map(row => current(row.provider, row.model))
    .filter(model => model !== undefined && (type === undefined || (model.type ?? "chat") === type));
  const authOptions = value => { const result = options(value, new Set(["signal"])); if (result.signal !== undefined && !(result.signal instanceof AbortSignal)) fail("MODEL_SCOPE_OPTIONS_UNSUPPORTED"); return result; };
  const available = async (p, input, type) => {
    if (p !== undefined) provider(p); const args = authOptions(input); check();
    const results = new Map();
    for (const selectedProvider of p === undefined ? providers : [p]) results.set(selectedProvider, await call("checkAuth", selectedProvider, args));
    check(); return list(p, type).filter(model => results.get(model.provider) !== undefined).map(exposed);
  };
  const api = new Map();
  api.set("getModel", (p, id) => { const model = current(provider(p), id); return model ? exposed(model) : undefined; });
  api.set("getModels", p => list(p, "chat").map(exposed)); api.set("getAllModels", p => list(p).map(exposed));
  api.set("getModelsOfType", (type, p) => list(p, type).map(exposed));
  api.set("getModelOfType", (type, p, id) => { const model = current(provider(p), id); return model && (model.type ?? "chat") === type ? exposed(model) : undefined; });
  api.set("getAvailable", (p, o) => available(p, o, "chat")); api.set("getAllAvailable", (p, o) => available(p, o));
  api.set("getAvailableOfType", (type, p, o) => available(p, o, type));
  api.set("getAvailableSnapshot", () => list(undefined, "chat").filter(model => call("hasConfiguredAuth", model.provider)).map(exposed));
  api.set("getRegisteredProviderIds", () => {
    const registered = call("getRegisteredProviderIds");
    if (!Array.isArray(registered) || registered.some(id => typeof id !== "string")) fail("MODEL_SCOPE_REGISTRATION_METADATA");
    return registered.filter(id => providers.includes(id));
  });
  for (const name of ["checkAuth", "isUsingOAuth", "isUsingSubscription", "hasConfiguredAuth", "getProviderAuthStatus"]) api.set(name, (p, o) => call(name, provider(p), authOptions(o)));
  api.set("getError", () => { if (original.has("getError") && call("getError") !== undefined) fail("MODEL_SCOPE_RUNTIME_ERROR"); return undefined; });
  api.set("getAuth", async (input, o) => {
    // SDK公开ModelRuntimeAuthOverrides带apiKey/env own slots；只转发已签发的同模型值。
    const args = options(o, new Set(["signal", "apiKey", "env"]));
    if (args.signal !== undefined && !(args.signal instanceof AbortSignal)) fail("MODEL_SCOPE_OPTIONS_UNSUPPORTED");
    notAborted(args.signal);
    const model = typeof input === "string" ? provider(input) : guard(input);
    if (typeof model !== "string" && model.api === "pi-virtual") fail("MODEL_SCOPE_VIRTUAL_UNSUPPORTED");
    const snapshot = typeof model === "string" ? undefined : remembered(key(model));
    for (const name of ["apiKey", "env"]) if (args[name] !== undefined) {
      const expected = name === "env" ? snapshot?.value.env : snapshot?.value.auth.apiKey;
      if (!snapshot || !isDeepStrictEqual(args[name], expected)) fail("MODEL_SCOPE_AUTH_OVERRIDE");
    }
    const p = typeof model === "string" ? model : model.provider, epoch = epochs.get(p);
    const result = await call("getAuth", model, args);
    notAborted(args.signal);
    if (epochs.get(p) !== epoch) fail("MODEL_SCOPE_AUTH_STALE");
    if (typeof input !== "string") { guard(input); saveAuth(input, result); }
    return result;
  });
  for (const method of requests) api.set(method, (model, payload, o) => request(method, model, payload, o));
  api.set("resolveModel", async (model, messages, input) => {
    const bound = guard(model); if (bound.api === "pi-virtual") fail("MODEL_SCOPE_VIRTUAL_UNSUPPORTED");
    const o = options(input, new Set(["reason", "thinkingLevel", "signal", "failed", "state"]));
    const route = await call("resolveModel", bound, messages, o); return { ...route, model: exposed(guard(route.model)) };
  });
  api.set("getPhysicalModel", (p, id) => { current(provider(p), id); const model = call("getPhysicalModel", p, id); return model ? exposed(guard(model)) : undefined; });
  for (const method of ["login", "logout"]) api.set(method, async (p, type, interaction, input) => {
    provider(p); if (bindings[p].auth_kind !== "oauth" || bindings[p].owner !== "pi-native" || method === "login" && type !== "oauth") fail("MODEL_SCOPE_CREDENTIAL_MUTATION");
    const args = method === "login" ? options(input, new Set(["getDeviceId"])) : authOptions(type);
    epochs.set(p, epochs.get(p) + 1);
    for (const row of rows.filter(row => row.provider === p)) forget(JSON.stringify([row.provider, row.model]));
    return method === "login" ? await call(method, p, type, interaction, args) : await call(method, p, args);
  });
  api.set("refresh", input => {
    const o = options(input, new Set(["providers", "allowNetwork", "signal"]));
    if (o.allowNetwork !== false || !Array.isArray(o.providers) || !o.providers.length || new Set(o.providers).size !== o.providers.length) fail("MODEL_SCOPE_REFRESH_UNSUPPORTED");
    o.providers.forEach(provider); return call("refresh", { ...o, providers: [...o.providers], allowNetwork: false });
  });
  const providerView = p => {
    provider(p); check(); if (views.has(p)) return views.get(p);
    const raw = call("getProvider", p); if (!raw || raw.id !== p) fail("MODEL_SCOPE_PROVIDER_DENIED");
    const authMetadata = {};
    for (const kind of ["apiKey", "oauth"]) if (raw.auth?.[kind]) {
      const source = raw.auth[kind], item = {};
      for (const name of ["name", "isSubscription", "loginLabel"]) if (source[name] !== undefined) item[name] = source[name];
      for (const name of ["login", "check", "resolve", "refresh", "toAuth"]) if (typeof source[name] === "function") item[name] = () => fail("MODEL_SCOPE_PROVIDER_AUTH_DENIED");
      authMetadata[kind] = Object.freeze(item);
    }
    const value = { id: p, name: raw.name, ...(raw.baseUrl === undefined ? {} : { baseUrl: raw.baseUrl }), auth: Object.freeze(authMetadata),
      getModels: () => list(p, "chat").map(exposed), getAllModels: () => list(p).map(exposed) };
    for (const [method, routed] of Object.entries({ stream: "stream", streamSimple: "streamSimple", fetchDeferred: "streamDeferred", cancelDeferred: "cancelDeferred", generateImages: "generateImages", classify: "classify" })) value[method] = (model, ...args) => {
      if (model?.provider !== p) fail("MODEL_SCOPE_PROVIDER_DENIED"); return api.get(routed)(model, ...args);
    };
    for (const name of ["refreshModels", "filterModels", "filterAllModels"]) value[name] = () => fail("MODEL_SCOPE_PROVIDER_AUTH_DENIED");
    const view = new Proxy(Object.freeze(value), { get: (object, name) => { if (!Object.hasOwn(object, name)) fail("MODEL_SCOPE_PROPERTY_DENIED"); return object[name]; }, set: () => fail("MODEL_SCOPE_WRITE_DENIED") });
    views.set(p, view); return view;
  };
  api.set("getProvider", providerView); api.set("getProviders", () => providers.map(providerView));
  api.set("getRegisteredNativeProvider", p => {
    provider(p); check();
    const registered = call("getRegisteredNativeProvider", p);
    if (registered === undefined) return undefined;
    if (!registered || registered.id !== p) fail("MODEL_SCOPE_REGISTRATION_METADATA");
    return providerView(p);
  });
  api.set("listCredentials", async input => {
    const args = authOptions(input); notAborted(args.signal);
    const rows = await call("listCredentials", args); notAborted(args.signal);
    if (!Array.isArray(rows) || rows.some(row => !row || Object.getPrototypeOf(row) !== Object.prototype
      || Object.keys(row).sort().join() !== "providerId,type" || typeof row.providerId !== "string" || !["api_key", "oauth"].includes(row.type))) fail("MODEL_SCOPE_CREDENTIAL_METADATA");
    return copy(rows.filter(row => providers.includes(row.providerId)));
  });
  for (const method of [...mutations, "getRegisteredProviderConfig", "getCompatibilityRequestConfig"]) api.set(method, () => fail("MODEL_SCOPE_CREDENTIAL_MUTATION"));
  const proxy = new Proxy(target, {
    has: (_object, name) => { if (!api.has(name)) fail("MODEL_SCOPE_PROPERTY_DENIED"); return true; },
    get: (_object, name) => { if (!api.has(name)) fail("MODEL_SCOPE_PROPERTY_DENIED"); return api.get(name); },
    set: () => fail("MODEL_SCOPE_WRITE_DENIED"), defineProperty: () => fail("MODEL_SCOPE_WRITE_DENIED"), deleteProperty: () => fail("MODEL_SCOPE_WRITE_DENIED"),
    setPrototypeOf: () => fail("MODEL_SCOPE_WRITE_DENIED"), preventExtensions: () => fail("MODEL_SCOPE_WRITE_DENIED"), ownKeys: () => fail("MODEL_SCOPE_REFLECTION_DENIED"),
    getOwnPropertyDescriptor: (_object, name) => {
      if (!api.has(name)) fail("MODEL_SCOPE_PROPERTY_DENIED"); const descriptor = Object.getOwnPropertyDescriptor(target, name);
      return descriptor ? { ...descriptor, value: api.get(name) } : undefined;
    },
  });
  return Object.freeze({ modelRuntime: proxy, check });
}
