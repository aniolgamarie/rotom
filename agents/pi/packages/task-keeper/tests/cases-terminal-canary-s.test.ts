import { test, assert } from "./recorded-test.ts";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { setImmediate as flush } from "node:timers/promises";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import taskKeeper from "../index.ts";
import { PiInteractiveAdapter } from "../src/adapters/pi-interactive.ts";
import { Store } from "../src/store/database.ts";
import { systemClock } from "../src/contracts/primitives.ts";
import type { RecoveryRecord, RequestGuard } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory, FakeClock, barrier } from "./helpers.ts";

for (const order of ["input-first", "canary-first"] as const)
test(`[S T35] terminal input ${order} stays unconsumed and cannot renew a completed canary's authority`, {timeout:15000}, async t => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"), configPath = join(root, "config.json"); mkdirSync(cwd);
  const config = configured(); config.storage.path = join(root, "state/runtime.db"); config.recovery.lightCanaryEnabled = true;
  writeFileSync(configPath, JSON.stringify(config)); const saved = process.env.PI_TASK_KEEPER_CONFIG; process.env.PI_TASK_KEEPER_CONFIG = configPath;
  const hooks = new Map<string, any>(); let terminalInput: ((data: string) => unknown) | undefined;
  const pi = { on: (name: string, callback: any) => hooks.set(name, callback), registerTool() {}, registerCommand() {} } as unknown as ExtensionAPI;
  const ctx = { cwd, mode: "tui", abort() {}, sessionManager: { getSessionId: () => "session" }, ui: { setStatus() {}, notify() {},
    onTerminalInput: (callback: (data: string) => unknown) => { terminalInput = callback; return () => {}; } } } as unknown as ExtensionContext;
  const clock = new FakeClock(); clock.wall = Date.now();
  t.mock.method(systemClock, "now", () => clock.now()); t.mock.method(systemClock, "monotonic", () => clock.monotonic());
  t.mock.method(systemClock, "schedule", (ms: number, callback: () => void) => clock.schedule(ms, callback));
  const started = barrier(), returned = barrier<{nativeId:string;terminated:boolean;failure:null}>(), trace: string[] = [];
  t.mock.method(PiInteractiveAdapter.prototype, "snapshot", () => ({ sessionId: "session", leafId: "leaf", provider: "fixture-provider", model: "fixture-model", idle: true,
    pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [], runtimeFingerprint: "state-fixture" }));
  t.mock.method(PiInteractiveAdapter.prototype, "canary", async (_signal: AbortSignal, guard: RequestGuard) => { guard(); trace.push("canary-start"); started.resolve(); const result = await returned.promise; trace.push("canary-return"); return result; });
  t.mock.method(PiInteractiveAdapter.prototype, "continue", async () => { trace.push("continuation"); return {nativeId:"unexpected"}; });
  taskKeeper(pi); let observer: Store | undefined;
  t.after(async () => { returned.resolve({ nativeId: "canary", terminated: true, failure: null }); await hooks.get("session_shutdown")({}, ctx); observer?.close(); if (saved === undefined) delete process.env.PI_TASK_KEEPER_CONFIG; else process.env.PI_TASK_KEEPER_CONFIG = saved; });
  await hooks.get("session_start")({}, ctx); observer = new Store(join(root, "state"));
  await hooks.get("after_provider_response")({ status: 429, headers: {"retry-after":"0"} }, ctx);
  await hooks.get("message_end")({ message: {role:"assistant",content:[],stopReason:"error",errorMessage:"429 quota"} }, ctx);
  await hooks.get("agent_settled")({}, ctx); clock.advance(1000); await started.promise;
  const before = observer.list<RecoveryRecord>("recovery")[0].value, intent = before.intentId!;
  assert.ok(intent); assert.equal(before.canaryAttempts, 1);
  if (order === "canary-first") { returned.resolve({ nativeId:"canary",terminated:true,failure:null }); await flush(); assert.equal(observer.list<RecoveryRecord>("recovery")[0].value.reason, "canary_passed_real_request_pending"); }
  trace.push("input"); assert.equal(terminalInput!("x"), undefined);
  if (order === "input-first") { returned.resolve({nativeId:"canary",terminated:true,failure:null}); await flush(); }
  clock.advance(10000); await flush();
  const after = observer.list<RecoveryRecord>("recovery")[0].value;
  assert.equal(after.status, "PAUSED"); assert.equal(after.reason, "user_terminal_input"); assert.equal(after.attempts, 0);
  assert.equal(observer.owner(before.scopeId)!.active, false); assert.equal(trace.includes("continuation"), false);
  assert.equal(trace.indexOf("input") < trace.indexOf("canary-return"), order === "input-first");
  assert.equal(observer.intent(intent)!.status, "settled"); assert.equal(observer.claims().length, 0);
  assert.equal(after.canaryAttempts, 1); assert.deepEqual(after.history, before.history);
});
