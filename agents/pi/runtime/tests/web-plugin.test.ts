import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, chmodSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
const slot = Symbol.for("agentcfg.pi.runtime.v1");
test("actual Web extension registers renamed tools and fetches through the selected route with a private cache", async () => {
  const root = mkdtempSync(join(tmpdir(), "web-plugin-")); chmodSync(root, 0o700);
  const tools = new Map(), events = new Map(), entries = [], requests = [], operation = { id: "fixture-operation", controller: new AbortController() };
  const runtime = { owner: { role: "manager" }, instanceRoot: root, cwd: root,
    manifest: { plugins: ["pi-web"], options: {}, web_services: { public: { type: "public" } }, web_config: {
      workflow: "none", tools: { webSearch: { enabled: false }, sourceCheck: { enabled: false } }, toolNames: { fetchContent: "selected_fetch" },
      fetchRouting: { providers: ["http"], allowRemoteHostedProviders: false },
    } },
    web: { current: () => operation, async run(_name, _signal, callback) { return callback(operation.controller.signal); },
      track: value => value, async close() {}, proxySelection: () => ({ specified: false, url: null }), withProxy: (_proxy, callback) => callback(),
      async fetch(service, url) {
        requests.push({ service, url });
        return new Response("Synthetic raw article text", { headers: { "Content-Type": "text/plain" } });
      } },
  };
  globalThis[slot] = runtime;
  const pi = { registerTool(tool) { tools.set(tool.name, tool); }, registerCommand() {}, registerShortcut() {},
    on(name, callback) { events.set(name, callback); }, appendEntry(type, data) { entries.push({ type, data }); } };
  const ctx = { cwd: root, hasUI: false, sessionManager: { getBranch: () => [] }, ui: { setWidget() {}, notify() {} } };
  try {
    const { default: install } = await import("../../packages/web-vendor/index.ts");
    install(pi);
    assert.deepEqual([...tools.keys()].sort(), ["get_search_content", "selected_fetch"]);
    await events.get("session_start")({}, ctx);
    const result = await tools.get("selected_fetch").execute("fixture", { url: "https://8.8.8.8/article", mode: "raw" }, undefined, undefined, ctx);
    assert.equal(result.details.successful, 1); assert.match(result.content[0].text, /Synthetic raw article text/);
    assert.equal(requests.length, 1); assert.equal(requests[0].service, "public");
    assert.equal(entries.at(-1).type, "web-search-results"); assert.ok(entries.at(-1).data.fetchCache, entries.at(-1).data.fetchCacheError);
    runtime.web.fetch = async service => {
      assert.equal(service, "public");
      return new Response("<!doctype html><html><head><title>Fixture article</title></head><body><article><h1>Fixture article</h1><p>"
        + "Synthetic readable article explains the configured service boundary. ".repeat(30) + "</p></article></body></html>", { headers: { "Content-Type": "text/html" } });
    };
    const readable = await tools.get("selected_fetch").execute("readable", { url: "https://8.8.8.8/article" }, undefined, undefined, ctx);
    assert.equal(readable.details.successful, 1); assert.match(readable.content[0].text, /Synthetic readable article/);
    await events.get("session_shutdown")({}, ctx);
    await assert.rejects(tools.get("selected_fetch").execute("stale", { url: "https://8.8.8.8/article" }, undefined, undefined, ctx), /STALE/);
  } finally { delete globalThis[slot]; rmSync(root, { recursive: true, force: true }); }
});
