import { test, assert } from "./recorded-test.ts";
import type { TestContext } from "node:test";
import { mkdirSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import taskKeeper from "../index.ts";
import { DEFAULT_CONFIG } from "../src/config.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";

function fixture(t: TestContext) {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"), configPath = join(root, "user.json"), projectPath = join(cwd, ".pi/task-keeper.json"), stateRoot = join(root, "state");
  mkdirSync(join(cwd, ".pi"), { recursive: true });
  const user = { ...structuredClone(DEFAULT_CONFIG), enabled: true, storage: { path: join(stateRoot, "runtime.db") } };
  writeFileSync(configPath, JSON.stringify(user));
  const store = new Store(stateRoot), owner = store.claimOwner("existing-scope", "existing-owner");
  store.prepare(owner, "existing-intent", "model", {});
  store.reserveRequest(owner, "existing-intent", "sent-request", [{ id: "existing-budget", ceiling: 12 }]); store.settleRequest("sent-request", "sent");
  store.reserveRequest(owner, "existing-intent", "unknown-request", [{ id: "existing-budget", ceiling: 12 }]); store.settleRequest("unknown-request", "unknown");
  const originalBudget = store.bucket("existing-budget"), originalIntent = store.intent("existing-intent");
  const saved = process.env.PI_TASK_KEEPER_CONFIG; process.env.PI_TASK_KEEPER_CONFIG = configPath;
  const hooks = new Map<string, any>(), commands = new Map<string, any>(), shown: any[] = [];
  taskKeeper({ on: (name: string, callback: any) => hooks.set(name, callback), registerTool() {}, registerCommand: (name: string, value: any) => commands.set(name, value) } as unknown as ExtensionAPI);
  const ctx = { cwd, ui: { setStatus() {}, notify: (text: string) => shown.push(JSON.parse(text)) } } as unknown as ExtensionContext;
  t.after(async () => { await hooks.get("session_shutdown")({}, ctx); store.close(); if (saved === undefined) delete process.env.PI_TASK_KEEPER_CONFIG; else process.env.PI_TASK_KEEPER_CONFIG = saved; });
  return { cwd, user, store, originalBudget, originalIntent, reload: async (project: unknown) => {
    writeFileSync(projectPath, JSON.stringify(project)); await hooks.get("session_start")({}, ctx); await commands.get("orch").handler("doctor", ctx); return shown.at(-1);
  } };
}

test("[S CFG-004] reloading project budget and required-check restrictions preserves the existing ledger", async t => {
  const f = fixture(t);
  for (const ceiling of [24, 12, 1, 0]) {
    const status = await f.reload({ budget: { protectedAttemptsPerWorkScope: ceiling }, workflow: { requiredChecks: { fix: [], inspect: [] }, allowPartial: true } });
    assert.equal(status.startupError, null); assert.equal(status.effectivePolicy.budget.protectedAttemptsPerWorkScope, Math.min(12, ceiling));
    assert.deepEqual(status.effectivePolicy.requiredChecks, f.user.workflow.requiredChecks); assert.equal(status.effectivePolicy.allowPartial, false);
    assert.deepEqual(f.store.bucket("existing-budget"), f.originalBudget); assert.deepEqual(f.store.intent("existing-intent"), f.originalIntent);
  }
});

test("[S CFG-006] an untrusted executable on project reload retires policy without running the command or resetting records", async t => {
  const f = fixture(t); assert.equal((await f.reload({})).enabled, true);
  const status = await f.reload({ verificationBindings: { injected: { executable: process.execPath, args: ["-e", "require('fs').writeFileSync('injected','bad')"] } } });
  assert.equal(status.enabled, false); assert.equal(status.startupError, "UNKNOWN_FIELD"); assert.equal(status.effectivePolicy, null);
  assert.equal(existsSync(join(f.cwd, "injected")), false); assert.deepEqual(f.store.bucket("existing-budget"), f.originalBudget);
  assert.equal((await f.reload({})).enabled, true); assert.deepEqual(f.store.intent("existing-intent"), f.originalIntent);
});

test("[S CFG-008] numeric boundary reloads reject malformed values and preserve valid zero restrictions", async t => {
  const f = fixture(t);
  for (const value of [-1, 0.5, "2", null]) {
    assert.equal((await f.reload({})).enabled, true);
    const status = await f.reload({ limits: { parallelReaders: value } }); assert.equal(status.enabled, false); assert.ok(status.startupError); assert.equal(status.effectivePolicy, null);
  }
  const zero = await f.reload({ limits: { parallelReaders: 0 } }); assert.equal(zero.enabled, true); assert.equal(zero.startupError, null); assert.equal(zero.effectivePolicy.limits.parallelReaders, 0);
  assert.deepEqual(f.store.bucket("existing-budget"), f.originalBudget); assert.deepEqual(f.store.intent("existing-intent"), f.originalIntent);
});

test("[S T87] every project correctness override invalidates the current instance policy and cannot hide prior unknown budget", async t => {
  const f = fixture(t);
  for (const key of ["unknownIsSuccess", "cancelMayResume", "ignoreRequiredChecks"]) {
    assert.equal((await f.reload({})).enabled, true); const status = await f.reload({ [key]: true });
    assert.equal(status.enabled, false); assert.equal(status.startupError, "UNKNOWN_FIELD"); assert.equal(status.effectivePolicy, null);
    assert.deepEqual(f.store.bucket("existing-budget"), f.originalBudget); assert.equal(f.store.request("unknown-request")!.state, "unknown");
  }
  assert.equal((await f.reload({})).enabled, true);
});
