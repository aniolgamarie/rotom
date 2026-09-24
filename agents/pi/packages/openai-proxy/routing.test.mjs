import assert from "node:assert/strict";
import test from "node:test";
import { getGlobalDispatcher, setGlobalDispatcher } from "undici";
import { isOpenAIOrigin, OpenAIProxyDispatcher, createOpenAIProxyFetch, installOpenAIProxy, getProxyStatus, getProxyDiagnostics } from "./routing.mjs";

test("matches official domains without matching lookalikes or internal gateways", () => {
  for (const origin of ["https://api.openai.com", "https://auth.openai.com", "https://chatgpt.com", "https://openai.com"]) {
    assert.equal(isOpenAIOrigin(origin), true, origin);
  }
  for (const origin of ["https://openai.com.evil.example", "https://fakeopenai.com", "https://work.oceanbase-dev.com", "http://127.0.0.1:8080", "ftp://api.openai.com"]) {
    assert.equal(isOpenAIOrigin(origin), false, origin);
  }
});

test("routes simultaneous requests independently and preserves request options and handlers", async () => {
  const calls = [];
  const fallback = { dispatch: (options, handler) => { calls.push(["fallback", options, handler]); return false; } };
  const proxy = { dispatch: (options, handler) => { calls.push(["proxy", options, handler]); return true; } };
  const router = new OpenAIProxyDispatcher(fallback, proxy);
  const openai = { origin: "https://api.openai.com", path: "/v1/responses", method: "POST", body: "payload" };
  const internal = { origin: "https://work.oceanbase-dev.com", path: "/tokensflow", method: "POST" };
  const handler = {};
  const results = await Promise.all([openai, internal].map(async (options) => router.dispatch(options, handler)));
  assert.deepEqual(results, [true, false]);
  assert.deepEqual(calls, [["proxy", openai, handler], ["fallback", internal, handler]]);
});

test("proxy failure is surfaced without retrying through the fallback", () => {
  const error = new Error("proxy unavailable");
  const router = new OpenAIProxyDispatcher(
    { dispatch: () => assert.fail("must not fall back to direct access") },
    { dispatch: () => { throw error; } },
  );
  assert.throws(() => router.dispatch({ origin: "https://chatgpt.com" }, {}), (actual) => actual === error);
});

test("reload is idempotent, preserves process env, and follows a replaced Pi dispatcher", async () => {
  const original = getGlobalDispatcher();
  const originalFetch = globalThis.fetch;
  const env = { ...process.env };
  let proxy;
  try {
    globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = { owner: { role: "manager" }, manifest: { options: { network: { openai_proxy_route: "fixture", routes: { fixture: { mode: "proxy", proxy_url: "http://fixture.invalid:18080" } } } } } };
    const first = installOpenAIProxy();
    const firstFetch = globalThis.fetch;
    proxy = first.proxy;
    assert.equal(installOpenAIProxy(), first);
    assert.equal(first.fallback, original);
    setGlobalDispatcher(original);
    const reloaded = installOpenAIProxy();
    assert.notEqual(reloaded, first);
    assert.equal(reloaded.fallback, original);
    assert.equal(reloaded.proxy.proxy, proxy.proxy);
    assert.notEqual(globalThis.fetch, firstFetch);
    assert.deepEqual({ ...process.env }, env);
  } finally {
    setGlobalDispatcher(original);
    globalThis.fetch = originalFetch;
    delete globalThis[Symbol.for("starter.pi.openai-proxy")];
    delete globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
    await proxy?.close();
  }
});

test("explicit reload replaces code wrappers, keeps one raw pool and preserves diagnostics", async () => {
  const original = getGlobalDispatcher();
  const originalFetch = globalThis.fetch;
  let raw;
  try {
    globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = { owner: { role: "manager" }, manifest: { options: { network: { openai_proxy_route: "fixture", routes: { fixture: { mode: "proxy", proxy_url: "http://fixture.invalid:18080" } } } } } };
    const first = installOpenAIProxy();
    raw = first.proxy.proxy;
    const firstFetch = globalThis.fetch;
    const diagnostics = getProxyDiagnostics();
    diagnostics.total.requests = 3;
    const second = installOpenAIProxy({ reload: true });
    assert.notEqual(second, first);
    assert.notEqual(globalThis.fetch, firstFetch);
    assert.equal(second.proxy.proxy, raw);
    assert.equal(second.fallback, original);
    assert.equal(getProxyDiagnostics(), diagnostics);
    assert.equal(getProxyStatus().total.requests, 3);
    assert.equal(getProxyStatus().fetchActive, true);
    assert.equal(getProxyStatus().dispatcherActive, true);
  } finally {
    setGlobalDispatcher(original);
    globalThis.fetch = originalFetch;
    delete globalThis[Symbol.for("starter.pi.openai-proxy")];
    delete globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
    await raw?.close();
  }
});

test("upgrade from the old global state and replacement of a closed pool work", async () => {
  const original = getGlobalDispatcher();
  const originalFetch = globalThis.fetch;
  let raw;
  try {
    globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = { owner: { role: "manager" }, manifest: { options: { network: { openai_proxy_route: "fixture", routes: { fixture: { mode: "proxy", proxy_url: "http://fixture.invalid:18080" } } } } } };
    const { ProxyAgent } = await import("undici");
    const oldProxy = new ProxyAgent("http://127.0.0.1:10808");
    const oldRouter = new OpenAIProxyDispatcher(original, oldProxy);
    const oldFetch = createOpenAIProxyFetch(originalFetch, oldProxy);
    setGlobalDispatcher(oldRouter);
    globalThis.fetch = oldFetch;
    globalThis[Symbol.for("starter.pi.openai-proxy")] = { proxy: oldProxy, dispatcher: oldRouter, fetch: oldFetch };
    const upgraded = installOpenAIProxy({ reload: true });
    raw = upgraded.proxy.proxy;
    assert.notEqual(raw, oldProxy);
    assert.equal(upgraded.fallback, original);
    assert.notEqual(globalThis.fetch, oldFetch);
    assert.equal(getProxyStatus().version, "0.2.0");
    await raw.close();
    const replaced = installOpenAIProxy();
    assert.notEqual(replaced.proxy.proxy, raw);
    raw = replaced.proxy.proxy;
    assert.equal(getProxyStatus().poolOpen, true);
  } finally {
    setGlobalDispatcher(original);
    globalThis.fetch = originalFetch;
    delete globalThis[Symbol.for("starter.pi.openai-proxy")];
    delete globalThis[Symbol.for("agentcfg.pi.runtime.v1")];
    await raw?.close();
  }
});

test("OAuth refresh, model catalog and SSE use an explicit proxy after global dispatcher replacement", async () => {
  const original = getGlobalDispatcher();
  const calls = [];
  const proxy = {};
  const fallback = (input, init) => { calls.push({ route: "fallback", input, init }); return "original"; };
  const fetch = createOpenAIProxyFetch(fallback, proxy, (input, init) => {
    calls.push({ route: "proxy", input, init });
    return "proxied";
  });
  const signal = new AbortController().signal;
  const init = { method: "POST", headers: { "content-type": "application/x-www-form-urlencoded" }, body: "test-body", signal };
  try {
    // Reproduce Pi resetting its global dispatcher after extension loading.
    setGlobalDispatcher({ dispatch() { assert.fail("OpenAI fetch must use its explicit dispatcher"); } });
    for (const input of [
      "https://auth.openai.com/oauth/token",
      new URL("https://chatgpt.com/backend-api/codex/models"),
      new Request("https://api.openai.com/v1/models"),
      "https://chatgpt.com/backend-api/codex/responses",
    ]) {
      assert.equal(await fetch(input, init), "proxied");
      const call = calls.at(-1);
      assert.equal(call.input, input);
      assert.equal(call.init.dispatcher, proxy);
      assert.equal(call.init.body, init.body);
      assert.equal(call.init.headers, init.headers);
      assert.equal(call.init.signal, signal);
    }
    assert.equal(await fetch("https://work.oceanbase-dev.com/tokensflow", init), "original");
    assert.equal(calls.at(-1).init, init);
    assert.equal(calls.at(-1).route, "fallback");
  } finally {
    setGlobalDispatcher(original);
  }
});


test("missing explicit proxy route or a managed helper cannot borrow ambient routing", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), old = globalThis[key];
  delete globalThis[key];
  try {
    assert.throws(() => installOpenAIProxy(), /OPENAI_PROXY_ROUTE_REQUIRED/);
    globalThis[key] = { managedRequestScope: { getStore: () => ({ task_id: "managed" }) } };
    const router = new OpenAIProxyDispatcher({ dispatch: () => assert.fail("fallback forbidden") }, { dispatch: () => assert.fail("send forbidden") });
    assert.throws(() => router.dispatch({ origin: "https://api.openai.com" }, {}), /UNMETERED_PROXY_HELPER_DENIED/);
    await assert.rejects(createOpenAIProxyFetch(() => assert.fail("fallback forbidden"), {}, () => assert.fail("send forbidden"))("https://api.openai.com"), /UNMETERED_PROXY_HELPER_DENIED/);
  } finally { globalThis[key] = old; }
});

test("proxy credentials come only from the selected route and never appear in status", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), old = globalThis[key], dispatcher = getGlobalDispatcher(), originalFetch = globalThis.fetch;
  const { createHash } = await import("node:crypto");
  const variable = "AGENTCFG_PI_ROUTE_CREDENTIAL_" + createHash("sha256").update("private-route").digest("hex").slice(0, 16).toUpperCase();
  const previous = process.env[variable]; let proxy;
  globalThis[key] = { owner: { role: "manager" }, manifest: { options: { network: { openai_proxy_route: "private-route", routes: {
    "private-route": { mode: "proxy", proxy_url: "http://fixture.invalid:18080", credential_ref: "secret:fixture" } } } } } };
  try {
    delete process.env[variable]; assert.throws(() => installOpenAIProxy(), /OPENAI_PROXY_CREDENTIAL_REQUIRED/);
    process.env[variable] = "Bearer synthetic-private-token";
    proxy = installOpenAIProxy().proxy;
    assert.equal(JSON.stringify(getProxyStatus()).includes("synthetic-private-token"), false);
    process.env[variable] = "bad\r\nheader";
    assert.throws(() => installOpenAIProxy(), /OPENAI_PROXY_CREDENTIAL_REQUIRED/);
  } finally {
    globalThis[key] = old; setGlobalDispatcher(dispatcher); globalThis.fetch = originalFetch;
    delete globalThis[Symbol.for("starter.pi.openai-proxy")];
    if (previous === undefined) delete process.env[variable]; else process.env[variable] = previous;
    await proxy?.close();
  }
});
