import { test, assert } from "./recorded-test.ts";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import taskKeeper from "../index.ts";
import { PiInteractiveAdapter } from "../src/adapters/pi-interactive.ts";
import { Store } from "../src/store/database.ts";
import type { RecoveryRecord } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S T36] internal continuation input and terminal protocol replies preserve authority while human input pauses recovery", async t => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"), configPath = join(root, "config.json"); mkdirSync(cwd);
  const config = configured(); config.storage.path = join(root, "state/runtime.db"); config.quotaGroups.pool.baseIntervalMs = 60000;
  writeFileSync(configPath, JSON.stringify(config)); const saved = process.env.PI_TASK_KEEPER_CONFIG; process.env.PI_TASK_KEEPER_CONFIG = configPath;
  const hooks = new Map<string, any>(); let terminalInput: ((data: string) => unknown) | undefined, removed = false;
  const pi = { on: (name: string, callback: any) => hooks.set(name, callback), registerTool() {}, registerCommand() {} } as unknown as ExtensionAPI;
  const ctx = { cwd, mode: "tui", abort() {}, sessionManager: { getSessionId: () => "session" }, ui: { setStatus() {}, notify() {},
    onTerminalInput: (callback: (data: string) => unknown) => { terminalInput = callback; return () => { removed = true; }; } } } as unknown as ExtensionContext;
  // This state test supplies an already-certified adapter snapshot; real PTY/transport certification is tested separately.
  t.mock.method(PiInteractiveAdapter.prototype, "snapshot", () => ({ sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [], runtimeFingerprint: "state-fixture" }));
  taskKeeper(pi); let observer: Store | undefined;
  t.after(async () => { await hooks.get("session_shutdown")({}, ctx); observer?.close(); if (saved === undefined) delete process.env.PI_TASK_KEEPER_CONFIG; else process.env.PI_TASK_KEEPER_CONFIG = saved; });
  await hooks.get("session_start")({}, ctx); observer = new Store(join(root, "state")); assert.ok(terminalInput);
  await hooks.get("after_provider_response")({ status: 429, headers: { "retry-after": "30" } }, ctx);
  await hooks.get("message_end")({ message: { role: "assistant", content: [], stopReason: "error", errorMessage: "429 quota" } }, ctx);
  await hooks.get("agent_settled")({}, ctx);
  const before = observer.list<RecoveryRecord>("recovery")[0].value; assert.equal(before.status, "WAITING_QUOTA"); const owner = observer.owner(before.scopeId);
  await hooks.get("input")({ source: "extension", text: "Continue the retained task from its current state" }, ctx);
  await hooks.get("before_agent_start")({}, ctx);
  for (const reply of ["\x1b[?1;2c", "\x1b[8;24;80t"]) assert.equal(terminalInput!(reply), undefined);
  assert.deepEqual(observer.list<RecoveryRecord>("recovery")[0].value, before); assert.deepEqual(observer.owner(before.scopeId), owner);
  assert.equal(terminalInput!("x"), undefined); const after = observer.list<RecoveryRecord>("recovery")[0].value;
  assert.equal(after.status, "PAUSED"); assert.equal(after.reason, "user_terminal_input"); assert.equal(observer.owner(before.scopeId)!.active, false);
  assert.equal(after.notBefore, before.notBefore); assert.deepEqual(after.history, before.history); assert.equal(after.attempts, 0);
  await hooks.get("session_shutdown")({}, ctx); assert.equal(removed, true);
});
