import { test, assert, evidence } from "./recorded-test.ts";
import { mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import taskKeeper from "../index.ts";
import { configured } from "./fixtures/config.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";
import type { TestContext } from "node:test";

async function fixture(t: TestContext, maxBytes?: number) {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"), configPath = join(root, "config.json"); mkdirSync(cwd);
  const config = configured(); config.features.interactiveRecovery = false; config.features.managedWorkflows = true;
  config.storage.path = join(root, "state/runtime.db"); config.limits.jobsPerWorkScope = 32;
  config.limits.semanticAttemptsPerWorkScope = 32;
  writeFileSync(configPath, JSON.stringify({ ...config, ...(maxBytes === undefined ? {} : { evidence: { packetByteBudget: maxBytes } }) }));
  const saved = process.env.PI_TASK_KEEPER_CONFIG; process.env.PI_TASK_KEEPER_CONFIG = configPath;
  const hooks = new Map<string, any>(), commands = new Map<string, any>(), notifications: string[] = []; let aborts = 0;
  const pi = { on: (name: string, callback: any) => hooks.set(name, callback), registerTool() {}, appendEntry() {},
    registerCommand: (name: string, definition: any) => commands.set(name, definition) } as unknown as ExtensionAPI;
  const ctx = { cwd, model: { api: "openai-completions", provider: "fixture-provider", id: "fixture-model", baseUrl: "http://127.0.0.1:1/v1" },
    modelRegistry: { find: () => undefined }, abort: () => { aborts++; }, ui: { notify: (value: string) => notifications.push(value), setStatus() {} },
    sessionManager: { getBranch: () => [], getHeader: () => null, getSessionId: () => "session", getSessionFile: () => null } } as unknown as ExtensionContext;
  taskKeeper(pi); await hooks.get("session_start")({}, ctx);
  const store = new Store(join(root, "state"));
  t.after(async () => { await hooks.get("session_shutdown")({}, ctx); store.close(); if (saved === undefined) delete process.env.PI_TASK_KEEPER_CONFIG; else process.env.PI_TASK_KEEPER_CONFIG = saved; });
  const scope = store.list<{scopeId:string}>("session-scopes")[0].value.scopeId;
  for (let i = 0; i < 21; i++) store.put("managed-jobs", `job-${String(i).padStart(2, "0")}`, {
    id: `job-${String(i).padStart(2, "0")}`, parentSessionId: "session", workScope: scope, workflow: "fix", sourceCwd: cwd, cwd: null, snapshot: `tree-${i}`,
    status: "BLOCKED", reason: i ? "waiting for independent checks" : "oldest required failure", goal: "bounded fixture", semanticAttempts: 1, controlEpoch: 1,
    modelBindings: {}, outputs: {}, verification: {}, checks: [], receipt: null, failures: i ? [] : [
      { id: "critical-oldest", layer: "verification", code: "CHECK:focused-tests", message: "required failure lost by summary", required: true, resolvedBy: null, attemptId: "attempt" },
    ],
  });
  store.put("native-errors", "quota-origin", { sessionId: "session", at: 1, category: "resource_pressure", code: "throttling", message: "retained main failure", retryAt: null });
  return { store, hooks, ctx, notifications, configPath, aborts: () => aborts, project: () => hooks.get("context")({ messages: [{ role: "assistant", content: "Summary claims everything passed" }] }, ctx) };
}

test("[S EVD-004 T11 T53 T57] context after an incomplete summary restores older job blockers and native failures together", async t => {
  const f = await fixture(t), result = await f.project(), text = result.messages.at(-1).content;
  for (const id of ["EVD-004", "T11", "T53", "T57"]) evidence(id, () => {
    assert.ok(text.includes("critical-oldest")); assert.ok(text.includes("quota-origin"));
    for (let i = 0; i < 21; i++) assert.ok(text.includes(`job-${String(i).padStart(2, "0")}`));
    assert.ok(text.includes("CHECK:focused-tests")); assert.equal(f.aborts(), 0);
    assert.equal(f.store.list("managed-jobs").length, 21);
  });
});

test("[S EVD-005 T56] an oversized mandatory packet aborts and keeps the final request gate closed", async t => {
  const f = await fixture(t, 32); assert.equal(await f.project(), undefined);
  await assert.rejects(fetch("http://127.0.0.1:1/v1/chat/completions", { method: "POST", body: '{"model":"fixture-model"}' }), { code: "PACKET_TOO_LARGE" });
  for (const id of ["EVD-005", "T56"]) evidence(id, () => {
    assert.equal(f.aborts(), 1); assert.ok(f.notifications.some(text => text.includes("PACKET_TOO_LARGE")));
    assert.ok(f.store.list<{reason:string}>("request-denials").some(row => row.value.reason === "PACKET_TOO_LARGE"));
    assert.equal(f.store.list("managed-jobs").length, 21); assert.equal(f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n, 0);
  });
  const next = JSON.parse(readFileSync(f.configPath, "utf8")); next.evidence.packetByteBudget = 65536; writeFileSync(f.configPath, JSON.stringify(next));
  const restored = await f.project(); assert.ok(restored.messages.at(-1).content.includes("critical-oldest")); assert.equal(f.aborts(), 1);
  assert.equal(f.store.list("managed-jobs").length, 21);
});

test("[S EVD-005] the final send guard observes a smaller byte budget published after context compilation", async t => {
  const f = await fixture(t); assert.ok(await f.project());
  const next = JSON.parse(readFileSync(f.configPath, "utf8")); next.evidence.packetByteBudget = 32; writeFileSync(f.configPath, JSON.stringify(next));
  await assert.rejects(fetch("http://127.0.0.1:1/v1/chat/completions", { method: "POST", body: '{"model":"fixture-model"}' }), { code: "PACKET_TOO_LARGE" });
  assert.equal(f.aborts(), 0); assert.equal(f.store.list("managed-jobs").length, 21);
  assert.ok(f.store.list<{reason:string}>("request-denials").some(row => row.value.reason === "PACKET_TOO_LARGE"));
});

test("[S] failing to read mandatory context facts also closes the outgoing request gate", async t => {
  const f = await fixture(t), original = Store.prototype.list;
  Store.prototype.list = () => { throw new Error("fixture evidence unavailable"); };
  try { assert.equal(await f.project(), undefined); } finally { Store.prototype.list = original; }
  assert.equal(f.aborts(), 1);
  await assert.rejects(fetch("http://127.0.0.1:1/v1/chat/completions", { method: "POST", body: '{"model":"fixture-model"}' }), { code: "CONTEXT_EVIDENCE_UNAVAILABLE" });
  assert.ok(f.notifications.some(text => text.includes("fixture evidence unavailable")));
});
