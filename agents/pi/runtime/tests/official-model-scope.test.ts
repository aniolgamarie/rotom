import assert from "node:assert/strict";
import { test } from "node:test";
import { createOfficialModelScope } from "../official-model-scope.ts";

const fixed = code => error => error.code === code && error.cause === undefined;
function fixture({ missingNative = false } = {}) {
  const state = { calls: [], io: 0, auth: 0, logins: 0, all: 0 };
  const models = [{ provider: "selected", id: "main", api: "chat-api", baseUrl: "https://selected.invalid", name: "Main", headers: { "x-private": "SYNTHETIC-PRIVATE" } },
    { provider: "native", id: "chat", api: "chat-api", baseUrl: "https://native.invalid", name: "Native" },
    { provider: "foreign", id: "unselected", api: "chat-api", baseUrl: "https://foreign.invalid", name: "Foreign" }];
  const nativeModel = models[1]; if (missingNative) models.splice(1, 1);
  const auth = { auth: { apiKey: "SYNTHETIC-PRIVATE", headers: { authorization: "Bearer SYNTHETIC-PRIVATE" }, baseUrl: "https://selected-auth.invalid" }, env: { PRIVATE_ENV: "SYNTHETIC-PRIVATE" } };
  const provider = id => ({ id, name: id, baseUrl: "https://provider.invalid", headers: { secret: "SYNTHETIC-PRIVATE" },
    auth: { apiKey: { name: "API key", resolve() { state.auth++; throw Error("raw provider auth"); } },
      oauth: { name: "OAuth", isSubscription: true, login() { state.logins++; }, refresh() {}, toAuth() {} } },
    stream() { state.io++; throw Error("raw provider stream"); }, streamSimple() { state.io++; throw Error("raw provider stream"); } });
  class FakeModelRuntime {
    constructor() { this.models = models; this.credentials = { secret: "SYNTHETIC-PRIVATE" }; this.state = state; }
    record(name, args) { this.state.calls.push({ name, args, receiver: this }); }
    getModel(p, id) { this.record("getModel", [p, id]); return this.models.find(model => model.provider === p && model.id === id); }
    getProvider(p) { this.record("getProvider", [p]); return provider(p); }
    getRegisteredProviderIds() { this.record("getRegisteredProviderIds", []); return this.state.registeredIds ?? []; }
    getRegisteredNativeProvider(p) { this.record("getRegisteredNativeProvider", [p]); return (this.state.nativeIds ?? []).includes(p) ? provider(p) : undefined; }
    getAuth(input) { this.record("getAuth", [input]); this.state.auth++; if (this.state.fail) return Promise.reject(Object.assign(Error("SYNTHETIC-PRIVATE"), { cause: Error("SYNTHETIC-PRIVATE") })); return Promise.resolve(this.state.authWait).then(() => auth); }
    checkAuth(p) { this.record("checkAuth", [p]); return Promise.resolve({ type: "api_key" }); }
    hasConfiguredAuth(p) { this.record("hasConfiguredAuth", [p]); return true; }
    isUsingOAuth(p) { this.record("isUsingOAuth", [p]); return p === "native"; }
    isUsingSubscription() { return false; }
    getProviderAuthStatus(p) { this.record("getProviderAuthStatus", [p]); return { configured: true, source: "stored" }; }
    getError() { return this.state.error; }
    getModels() { this.state.all++; return this.models; }
    getAvailableSnapshot() { this.state.all++; return this.models; }
    getAllModels() { this.state.all++; return this.models; }
    async stream(model, context, options) { this.record("stream", [model, context, options]);
      if (options?.transformHeaders) await options.transformHeaders({ authorization: "Bearer SYNTHETIC-PRIVATE", host: "selected.invalid", "x-public": "before" });
      this.state.io++; return { model, context, options }; }
    streamSimple(...args) { return this.stream(...args); }
    complete(...args) { return this.stream(...args); }
    completeSimple(...args) { return this.stream(...args); }
    streamDeferred(...args) { return this.stream(...args); }
    fetchDeferred(...args) { return this.stream(...args); }
    cancelDeferred(...args) { return this.stream(...args); }
    generateImages(...args) { return this.stream(...args); }
    classify(...args) { return this.stream(...args); }
    login(p, type, interaction, options) { this.record("login", [p, type, interaction, options]); this.state.logins++; return Promise.resolve({ type: "oauth", access: "SYNTHETIC-PRIVATE" }); }
    logout(p) { this.record("logout", [p]); return Promise.resolve(this.state.logoutWait); }
    listCredentials() { this.record("listCredentials", []); return Promise.resolve(this.state.credentialInfo ?? [{ providerId: "selected", type: "api_key" }, { providerId: "native", type: "oauth" }, { providerId: "foreign", type: "oauth" }]); }
    refresh(options) { this.record("refresh", [options]); return Promise.resolve({ aborted: false, errors: new Map() }); }
    resolveModel(model) { this.record("resolveModel", [model]); return Promise.resolve({ model: this.state.physical ?? model, thinkingLevel: "off" }); }
    getPhysicalModel(p, id) { this.record("getPhysicalModel", [p, id]); return this.getModel(p, id); }
    setRuntimeApiKey() { throw Error("raw mutation"); }
    registerProvider() { throw Error("raw mutation"); }
  }
  Object.freeze(FakeModelRuntime.prototype);
  const target = new FakeModelRuntime();
  const manifest = { allowed_models: [{ provider: "selected", model: "main" }, { provider: "native", model: "chat" }],
    provider_bindings: { selected: { auth_kind: "api-key", owner: "pi-environment" }, native: { auth_kind: "oauth", owner: "pi-native" } } };
  const describe = model => ({ provider: model.provider, id: model.id, api: model.api, baseUrl: model.baseUrl, name: model.name });
  const scope = createOfficialModelScope({ modelRuntime: target, manifest, describe });
  state.calls.length = 0;
  return { state, models, nativeModel, auth, target, manifest, describe, scope, Class: FakeModelRuntime, proxy: scope.modelRuntime };
}

test("Proxy preserves real class identity/receivers and rejects private reflection or writes without changing target", async () => {
  const f = fixture(), before = Object.getOwnPropertyDescriptors(f.target);
  assert.equal(f.proxy instanceof f.Class, true); assert.equal(Object.getPrototypeOf(f.proxy), f.Class.prototype);
  for (const action of [() => f.proxy.credentials, () => f.proxy.send, () => Object.getOwnPropertyDescriptor(f.proxy, "credentials"), () => Object.keys(f.proxy),
    () => { f.proxy.credentials = {}; }, () => Object.defineProperty(f.proxy, "extra", { value: 1 }), () => delete f.proxy.models,
    () => Object.setPrototypeOf(f.proxy, {}), () => Object.preventExtensions(f.proxy), () => f.Class.prototype.getModel.call(f.proxy, "selected", "main")])
    assert.throws(action, error => error.code?.startsWith("MODEL_SCOPE_"));
  const model = f.proxy.getModel("selected", "main"); assert.equal(model.headers, undefined); assert.equal(Object.isFrozen(model), true);
  await f.proxy.getAuth(model); assert.ok(f.state.calls.every(call => call.receiver === f.target));
  assert.deepEqual(Object.getOwnPropertyDescriptors(f.target), before);
});

test("catalog/availability enumerate only selected pairs and checkAuth selected providers without all account discovery", async () => {
  const f = fixture(); assert.deepEqual(f.proxy.getModels().map(model => model.provider), ["selected", "native"]);
  assert.equal(f.proxy.getAllModels().length, 2); assert.equal(f.proxy.getAvailableSnapshot().length, 2);
  assert.equal((await f.proxy.getAvailable()).length, 2); assert.equal(f.state.all, 0);
  assert.deepEqual(f.state.calls.filter(call => call.name === "checkAuth").map(call => call.args[0]), ["selected", "native"]);
  f.manifest.allowed_models.push({ provider: "foreign", model: "unselected" });
  assert.throws(() => f.proxy.getModel("foreign", "unselected"), fixed("MODEL_SCOPE_PROVIDER_DENIED"));
});

test("configured models do not imply extension or native-provider registration", () => {
  const f = fixture();
  assert.deepEqual(f.proxy.getRegisteredProviderIds(), []);
  assert.equal(f.proxy.getRegisteredNativeProvider("selected"), undefined);
  assert.equal(f.proxy.getRegisteredNativeProvider("native"), undefined);
});

test("public registration metadata preserves selected extension/native distinction and original receiver", () => {
  const f = fixture(); f.state.registeredIds = ["selected", "native", "foreign"]; f.state.nativeIds = ["native", "foreign"];
  assert.deepEqual(f.proxy.getRegisteredProviderIds(), ["selected", "native"]);
  assert.equal(f.proxy.getRegisteredNativeProvider("selected"), undefined);
  const view = f.proxy.getRegisteredNativeProvider("native");
  assert.equal(view, f.proxy.getProvider("native"));
  assert.throws(() => view.send, fixed("MODEL_SCOPE_PROPERTY_DENIED"));
  assert.ok(f.state.calls.filter(call => call.name.startsWith("getRegistered")).every(call => call.receiver === f.target));
});

test("foreign native-provider lookup rejects before reading its registration metadata", () => {
  const f = fixture(); f.state.nativeIds = ["foreign"];
  assert.throws(() => f.proxy.getRegisteredNativeProvider("foreign"), fixed("MODEL_SCOPE_PROVIDER_DENIED"));
  assert.equal(f.state.calls.some(call => call.name === "getRegisteredNativeProvider"), false);
});

test("wrong model ID/API/baseUrl are rejected before auth and every explicit SDK dispatch", async () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main");
  for (const value of [{ ...model, id: "unselected" }, { ...model, api: "foreign-api" }, { ...model, baseUrl: "https://foreign.invalid" }]) {
    await assert.rejects(f.proxy.getAuth(value), fixed("MODEL_SCOPE_MODEL_DENIED"));
    for (const name of ["stream", "streamSimple", "complete", "completeSimple", "streamDeferred", "fetchDeferred", "cancelDeferred", "generateImages", "classify"])
      assert.throws(() => f.proxy[name](value, {}), fixed("MODEL_SCOPE_MODEL_DENIED"));
  }
  assert.equal(f.state.auth, 0); assert.equal(f.state.io, 0);
  assert.throws(() => f.proxy.getProvider("foreign"), fixed("MODEL_SCOPE_PROVIDER_DENIED"));
});

test("normal SDK auth-derived endpoint/apiKey/headers/env dispatch uses private independent snapshot", async () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main"), resolution = await f.proxy.getAuth(model);
  const options = { apiKey: resolution.auth.apiKey, headers: { ...resolution.auth.headers }, env: { ...resolution.env }, sessionId: "session", signal: new AbortController().signal };
  resolution.auth.apiKey = "changed outside";
  await f.proxy.streamSimple({ ...model, baseUrl: "https://selected-auth.invalid" }, { messages: [] }, options);
  assert.equal(f.state.io, 1); assert.equal(f.state.calls.find(call => call.name === "stream").args[0].baseUrl, "https://selected-auth.invalid");
});

test("public SDK auth overrides permit undefined slots and only previously issued apiKey/env", async () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main");
  const first = await f.proxy.getAuth(model, { apiKey: undefined, env: undefined, signal: undefined });
  await f.proxy.getAuth(model, { apiKey: first.auth.apiKey, env: { ...first.env } });
  const before = f.state.auth;
  for (const overrides of [{ apiKey: "foreign" }, { env: { PRIVATE_ENV: "foreign" } }])
    await assert.rejects(f.proxy.getAuth(model, overrides), fixed("MODEL_SCOPE_AUTH_OVERRIDE"));
  assert.equal(f.state.auth, before);
});

test("initial auth overrides cannot supply a credential before an issued snapshot", async () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main");
  await assert.rejects(f.proxy.getAuth(model, { apiKey: "SYNTHETIC-PRIVATE" }), fixed("MODEL_SCOPE_AUTH_OVERRIDE"));
  await assert.rejects(f.proxy.getAuth(model, { env: {} }), fixed("MODEL_SCOPE_AUTH_OVERRIDE"));
  assert.equal(f.state.auth, 0);
});

test("SDK AgentLoopConfig is validated and projected to stream options without forwarding loop callbacks", async () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main");
  const callbacks = ["beforeToolCall", "afterToolCall", "finishTurn", "prepareRequest", "prepareNextTurn", "convertToLlm", "transformContext", "getApiKey", "getSteeringMessages", "getFollowUpMessages"];
  const input = { model, toolExecution: "parallel", reasoning: undefined, sessionId: "own-session",
    ...Object.fromEntries(callbacks.map(name => [name, () => { throw Error("loop callback must not reach provider"); }])) };
  await f.proxy.streamSimple(model, { messages: [] }, input);
  const sent = f.state.calls.find(call => call.name === "stream").args[2];
  assert.deepEqual(sent, { reasoning: undefined, sessionId: "own-session" });
  assert.equal(f.state.io, 1); assert.equal(input.model, model);
});

test("loop projection still rejects foreign model, malformed controls and unknown keys before sender", () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main");
  for (const input of [{ model: null }, { model: "foreign" }, { model: f.models[2] }, { model: { ...model, api: "foreign" } }, { toolExecution: "unknown" },
    { getApiKey: "SYNTHETIC-PRIVATE" }, { futureLoopField: undefined }])
    assert.throws(() => f.proxy.streamSimple(model, {}, input), error => error.code?.startsWith("MODEL_SCOPE_"));
  assert.equal(f.state.auth, 0); assert.equal(f.state.io, 0);
});

test("forged auth options/fetch reject with zero extra authentication or IO", async () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main"); await f.proxy.getAuth(model); const count = f.state.auth;
  for (const options of [{ apiKey: "foreign" }, { headers: { authorization: "foreign" } }, { env: { foreign: "secret" } }, { fetch() {} }, { unknown: true }])
    assert.throws(() => f.proxy.streamSimple(model, {}, options), error => error.code?.startsWith("MODEL_SCOPE_"));
  assert.equal(f.state.auth, count); assert.equal(f.state.io, 0);
});

test("Provider view never returns raw sending/auth capabilities and routes selected sends through original runtime", async () => {
  const f = fixture(), view = f.proxy.getProvider("selected"), model = f.proxy.getModel("selected", "main");
  assert.throws(() => view.headers, fixed("MODEL_SCOPE_PROPERTY_DENIED")); assert.throws(() => view.send, fixed("MODEL_SCOPE_PROPERTY_DENIED"));
  assert.throws(() => view.auth.apiKey.resolve({}), fixed("MODEL_SCOPE_PROVIDER_AUTH_DENIED"));
  assert.throws(() => view.stream(f.models[2], {}), fixed("MODEL_SCOPE_PROVIDER_DENIED"));
  await view.stream(model, { messages: [] }); assert.equal(f.state.io, 1); assert.equal(f.state.calls.find(call => call.name === "stream").receiver, f.target);
});

test("legitimate header callback keeps auth/host fields while in-place tampering cannot reach IO", async () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main"); await f.proxy.getAuth(model);
  await f.proxy.streamSimple(model, {}, { transformHeaders: headers => ({ ...headers, "x-public": "after" }), onPayload() {}, onResponse() {}, onProviderStreamEvent() {} });
  const before = f.state.io;
  await assert.rejects(f.proxy.streamSimple(model, {}, { transformHeaders: headers => { headers.authorization = "foreign"; return headers; } }), fixed("MODEL_SCOPE_HEADERS_INVALID"));
  await assert.rejects(f.proxy.streamSimple(model, {}, { transformHeaders: headers => ({ ...headers, "proxy-authorization": "foreign" }) }), fixed("MODEL_SCOPE_HEADERS_INVALID"));
  assert.equal(f.state.io, before);
});

test("mutations and nonnative/API-key login deny; selected native OAuth uses original login/logout only", async () => {
  const f = fixture();
  for (const method of ["setRuntimeApiKey", "removeRuntimeApiKey", "registerProvider", "unregisterProvider", "registerNativeProvider", "registerVirtualModel", "unregisterVirtualModel"])
    assert.throws(() => f.proxy[method]("selected", {}), fixed("MODEL_SCOPE_CREDENTIAL_MUTATION"));
  await assert.rejects(f.proxy.login("selected", "api_key", {}), fixed("MODEL_SCOPE_CREDENTIAL_MUTATION"));
  await f.proxy.login("native", "oauth", { prompt: async () => "synthetic", notify() {} }); await f.proxy.logout("native");
  assert.equal(f.state.logins, 1);
  assert.deepEqual((await f.proxy.listCredentials()).map(row => row.providerId), ["selected", "native"]);
  f.state.credentialInfo = [{ providerId: "selected", type: "api_key", raw: "SYNTHETIC-PRIVATE" }];
  await assert.rejects(f.proxy.listCredentials(), fixed("MODEL_SCOPE_CREDENTIAL_METADATA"));
});

test("refresh requires explicit selected providers and network false; physical route outside allowlist rejects", async () => {
  const f = fixture();
  for (const options of [undefined, { allowNetwork: true, providers: ["selected"] }, { allowNetwork: false, providers: ["foreign"] }])
    assert.throws(() => f.proxy.refresh(options), error => error.code?.startsWith("MODEL_SCOPE_"));
  await f.proxy.refresh({ allowNetwork: false, providers: ["selected"] });
  const model = f.proxy.getModel("selected", "main"); f.state.physical = f.models[2];
  await assert.rejects(f.proxy.resolveModel(model, [], { reason: "direct", thinkingLevel: "off" }), fixed("MODEL_SCOPE_MODEL_DENIED"));
  assert.throws(() => f.proxy.getPhysicalModel("foreign", "unselected"), fixed("MODEL_SCOPE_PROVIDER_DENIED")); assert.equal(f.state.auth, 0);
  f.state.physical = undefined;
  const physical = f.proxy.getPhysicalModel("selected", "main");
  assert.equal(physical.headers, undefined); assert.equal(Object.isFrozen(physical), true);
  const route = await f.proxy.resolveModel(model, [], { reason: "direct", thinkingLevel: "off" });
  assert.equal(route.model.headers, undefined); assert.equal(Object.isFrozen(route.model), true);
});

test("private/foreign thrown auth errors are fixed with no cause; metadata drift blocks check", async () => {
  const f = fixture(); f.state.fail = true;
  await assert.rejects(f.proxy.getAuth(f.proxy.getModel("selected", "main")), error => error.code === "MODEL_SCOPE_OPERATION_FAILED" && !error.message.includes("SYNTHETIC") && error.cause === undefined);
  f.models[0].baseUrl = "https://drift.invalid"; assert.throws(f.scope.check, fixed("MODEL_SCOPE_MODEL_DENIED"));
});

test("nonconfigurable own method is incompatible instead of violating Proxy invariants or modifying it", () => {
  const f = fixture(); Object.defineProperty(f.target, "getModel", { value: f.target.getModel, configurable: false, writable: false });
  assert.throws(() => createOfficialModelScope({ modelRuntime: f.target, manifest: f.manifest, describe: f.describe }), fixed("MODEL_SCOPE_INCOMPATIBLE"));
});

test("virtual router is explicitly unsupported before router/auth calls", async () => {
  const f = fixture(); f.models[0].api = "pi-virtual";
  const scope = createOfficialModelScope({ modelRuntime: f.target, manifest: f.manifest, describe: f.describe });
  f.state.calls.length = 0;
  await assert.rejects(scope.modelRuntime.getAuth(scope.modelRuntime.getModel("selected", "main")), fixed("MODEL_SCOPE_VIRTUAL_UNSUPPORTED"));
  await assert.rejects(scope.modelRuntime.resolveModel(scope.modelRuntime.getModel("selected", "main"), [], { reason: "direct", thinkingLevel: "off" }), fixed("MODEL_SCOPE_VIRTUAL_UNSUPPORTED"));
  assert.equal(f.state.calls.some(call => call.name === "resolveModel"), false); assert.equal(f.state.auth, 0); assert.equal(f.state.io, 0);
});

test("aborted auth and request reject before sender and late auth cannot survive cancellation", async () => {
  const f = fixture(), model = f.proxy.getModel("selected", "main"), aborted = new AbortController(); aborted.abort();
  await assert.rejects(f.proxy.getAuth(model, { signal: aborted.signal }), fixed("MODEL_SCOPE_CANCELED"));
  assert.throws(() => f.proxy.streamSimple(model, {}, { signal: aborted.signal }), fixed("MODEL_SCOPE_CANCELED"));
  assert.equal(f.state.auth, 0); assert.equal(f.state.io, 0);
  let release; f.state.authWait = new Promise(resolve => { release = resolve; }); const later = new AbortController();
  const pending = f.proxy.getAuth(model, { signal: later.signal }); later.abort(); release();
  await assert.rejects(pending, fixed("MODEL_SCOPE_CANCELED"));
  assert.throws(() => f.proxy.streamSimple(model, {}, { apiKey: "SYNTHETIC-PRIVATE" }), fixed("MODEL_SCOPE_AUTH_OVERRIDE"));
});

test("logout start revokes auth cache and old in-flight getAuth cannot republish after epoch changes", async () => {
  const f = fixture(), model = f.proxy.getModel("native", "chat"); await f.proxy.getAuth(model);
  let releaseAuth, releaseLogout;
  f.state.authWait = new Promise(resolve => { releaseAuth = resolve; }); f.state.logoutWait = new Promise(resolve => { releaseLogout = resolve; });
  const pending = f.proxy.getAuth(model), logout = f.proxy.logout("native");
  assert.throws(() => f.proxy.streamSimple(model, {}, { apiKey: "SYNTHETIC-PRIVATE" }), fixed("MODEL_SCOPE_AUTH_OVERRIDE"));
  releaseAuth(); await assert.rejects(pending, fixed("MODEL_SCOPE_AUTH_STALE")); releaseLogout(); await logout;
  assert.equal(f.state.io, 0);
});

test("unavailable OAuth secondary model permits login UI without auto auth/refresh and freezes first valid metadata", async () => {
  const f = fixture({ missingNative: true });
  assert.equal(f.proxy.getModel("native", "chat"), undefined); assert.equal(f.proxy.getModels().length, 1);
  assert.equal(f.proxy.getProvider("native").auth.oauth.name, "OAuth"); f.scope.check();
  assert.equal(f.state.auth, 0); assert.equal(f.state.calls.some(call => call.name === "refresh"), false);
  await f.proxy.login("native", "oauth", { prompt: async () => "synthetic", notify() {} });
  f.models.push(f.nativeModel); assert.equal(f.proxy.getModel("native", "chat").id, "chat");
  f.nativeModel.api = "foreign-api"; assert.throws(f.scope.check, fixed("MODEL_SCOPE_MODEL_DENIED"));
});
