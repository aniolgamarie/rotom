import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AgentManager } from "../../packages/subagents-vendor/src/agent-manager.ts";
import { WebRuntime } from "../web-runtime.ts";
import { assertSessionBoundary } from "../capability-policy.ts";

const slot = Symbol.for("agentcfg.pi.runtime.v1"), managerSlot = Symbol.for("agentcfg.pi.managed.v1");
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
function fixture(factory) {
  const manager = new AgentManager(undefined, 2), cwd = mkdtempSync(join(tmpdir(), "web-runtime-"));
  const calls = [], closed = [];
  const runtime = { cwd, owner: { role: "manager" }, manifest: { plugins: ["pi-web"], options: {
    task_keeper: { enabled: true }, network: { routes: {
      direct: { mode: "direct", service_ids: ["web:public"] }, proxy: { mode: "proxy", proxy_url: "http://127.0.0.1:8123", service_ids: ["web:public"] },
    } } }, web_services: { public: { type: "public", network_route: "proxy" } } },
    supervisor: { async call() { return { active_count: 0 }; } } };
  globalThis[slot] = runtime; globalThis[managerSlot] = { manager, pi: {}, getContext: () => ({ cwd }) };
  const web = new WebRuntime(runtime, { fetchFactory: factory ?? (async (_runtime, name, options) => {
    const fetch = async (url, init) => { init.signal.throwIfAborted(); calls.push({ name, url, options }); return new Response("content"); };
    fetch.close = async () => { closed.push(name); }; return fetch;
  }) });
  return { manager, runtime, web, calls, closed, async cleanup() {
    await web.close(); await flush(); await manager.dispose(); delete globalThis[slot]; delete globalThis[managerSlot];
  } };
}

test("web requests use the existing manager and only declared route overrides", async () => {
  const f = fixture();
  try {
    const result = await f.web.run("web", undefined, async () => f.web.withProxy("", async () => {
      assert.equal(f.manager.hasRunning(), true); assert.equal(f.manager.blocksOrdinaryHelpers(), false);
      return (await f.web.fetch("public", "https://example.invalid")).text();
    }));
    assert.equal(result, "content"); assert.equal(f.calls[0].options.routeName, "direct");
    assert.equal(f.manager.hasRunning(), false); assert.equal(f.web.operations.size, 0);
    await assert.rejects(f.web.run("invalid", undefined, () => f.web.withProxy("http://unselected.invalid", () => f.web.fetch("public", "https://example.invalid"))), /UNBOUND/);
  } finally { await f.cleanup(); }
});

test("nested helper work shares its original ownership and cannot reset a failed proxy operation", async () => {
  const f = fixture();
  try {
    assert.equal(await f.web.run("parent", undefined, async () => {
      const first = f.web.current().id;
      return f.web.run("helper", undefined, async () => {
        assert.equal(f.web.current().id, first); assert.equal(f.web.operations.size, 1);
        return "one operation";
      });
    }), "one operation");
    await assert.rejects(f.web.run("failed proxy", undefined, async () => {
      f.web.current().proxyFailed = true;
      return f.web.run("hidden retry", undefined, async () => "must not run");
    }), /CLOSED/);
  } finally { await f.cleanup(); }
});

test("background work retains ownership after foreground results and blocks session switches until settled", async () => {
  const f = fixture(); let release;
  try {
    assert.equal(await f.web.run("background", undefined, async () => {
      void f.web.track(new Promise(resolve => { release = resolve; }).then(async () => (await f.web.fetch("public", "https://example.invalid")).text()));
      return "initial results";
    }), "initial results");
    assert.equal(f.manager.hasRunning(), true);
    await assert.rejects(assertSessionBoundary(f.runtime), /PROTECTED/);
    release(); await flush(); await flush();
    assert.equal(f.manager.hasRunning(), false); assert.equal(f.web.operations.size, 0);
  } finally { await f.cleanup(); }
});

test("unknown external closure cannot publish a foreground success or release the resource record", async () => {
  const f = fixture(); let known = false;
  try {
    await assert.rejects(f.web.run("external", undefined, async () => {
      f.web.verifyExternal(async () => known); return "not yet verified";
    }), /TERMINATION_UNKNOWN/);
    assert.equal(f.manager.hasRunning(), true); assert.equal(f.web.operations.size, 1);
    known = true; f.manager.abort([...f.web.operations.keys()][0]); await flush(); await flush();
    assert.equal(f.manager.hasRunning(), false);
  } finally { await f.cleanup(); }
});

test("cancellation aborts the whole operation, while a failed transport factory does not invent live work", async () => {
  const f = fixture(); const abort = new AbortController(); let ready;
  const started = new Promise(resolve => { ready = resolve; });
  try {
    const result = f.web.run("cancel", abort.signal, signal => new Promise((_, reject) => {
      signal.addEventListener("abort", () => reject(new Error("stopped")), { once: true }); ready();
    }));
    await started; abort.abort(); await assert.rejects(result, /CANCELED|stopped/); await flush();
    assert.equal(f.manager.hasRunning(), false);
  } finally { await f.cleanup(); }
  const failed = fixture(async () => { throw new Error("fixture binding unavailable"); });
  try {
    await assert.rejects(failed.web.run("unavailable", undefined, () => failed.web.fetch("public", "https://example.invalid")), /binding unavailable/);
    await flush(); assert.equal(failed.manager.hasRunning(), false);
  } finally { await failed.cleanup(); }
});

test("private media cleanup waits for verified external termination", async () => {
  const f = fixture(); let known = false, cleanups = 0;
  try {
    await assert.rejects(f.web.run("media", undefined, async () => {
      f.web.cleanup(async () => { cleanups++; }); f.web.verifyExternal(async () => known); return "pending proof";
    }), /TERMINATION_UNKNOWN/);
    assert.equal(cleanups, 0); assert.equal(f.manager.hasRunning(), true);
    known = true; f.manager.abort([...f.web.operations.keys()][0]); await flush(); await flush();
    assert.equal(cleanups, 1); assert.equal(f.manager.hasRunning(), false);
  } finally { await f.cleanup(); }
});

test("a web helper model does not block the same operation's already-owned HTTP work", async () => {
  const f = fixture(); f.runtime.web = f.web;
  const model = { provider: "fixture", id: "selected" }; let ready, release, modelRequest;
  const started = new Promise(resolve => { ready = resolve; });
  f.runtime.models = { current: { getModel: () => model, completeSimple: async () => { ready(); return new Promise(resolve => { release = resolve; }); } } };
  try {
    const { webComplete } = await import("../web-model.ts");
    const { webCredential } = await import("../web-config.ts");
    const credentialName = "AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA";
    f.runtime.manifest.web_credential_variables = [credentialName]; process.env[credentialName] = "synthetic credential";
    const result = await f.web.run("search with summary", undefined, async () => {
      modelRequest = webComplete(model, { messages: [] });
      await started;
      try { assert.equal(webCredential("$" + credentialName), "synthetic credential"); return await (await f.web.fetch("public", "https://example.invalid")).text(); }
      finally { release({ content: "summary" }); await modelRequest; }
    });
    assert.equal(result, "content"); assert.equal(f.calls.length, 1);
  } finally { release?.({ content: "summary" }); await modelRequest?.catch(() => {}); delete process.env.AGENTCFG_PI_CREDENTIAL_AAAAAAAAAAAAAAAA; await f.cleanup(); }
});
