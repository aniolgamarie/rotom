import { test, assert } from "./recorded-test.ts";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import taskKeeper from "../index.ts";
import { DEFAULT_CONFIG } from "../src/config.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S CFG-005] repeated session-start on one extension instance clears an earlier policy after an invalid project reload", async t => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"), configPath = join(root, "config.json"), projectPath = join(cwd, ".pi/task-keeper.json");
  mkdirSync(cwd); mkdirSync(join(cwd, ".pi"));
  writeFileSync(configPath, JSON.stringify({ ...structuredClone(DEFAULT_CONFIG), enabled: true, storage: { path: join(root, "state/runtime.db") } }));
  const saved = process.env.PI_TASK_KEEPER_CONFIG; process.env.PI_TASK_KEEPER_CONFIG = configPath;
  const hooks = new Map<string, (event: unknown, ctx: ExtensionContext) => unknown>(), commands = new Map<string, any>(), shown: any[] = [];
  const pi = { on: (name: string, callback: any) => hooks.set(name, callback), registerTool() {},
    registerCommand: (name: string, definition: any) => commands.set(name, definition) } as unknown as ExtensionAPI;
  const ctx = { cwd, ui: { notify: (text: string) => shown.push(JSON.parse(text)) } } as unknown as ExtensionContext;
  taskKeeper(pi);
  t.after(async () => { await hooks.get("session_shutdown")!({}, ctx); if (saved === undefined) delete process.env.PI_TASK_KEEPER_CONFIG; else process.env.PI_TASK_KEEPER_CONFIG = saved; });
  const inspect = async () => { await commands.get("orch").handler("doctor", ctx); return shown.at(-1); };
  await hooks.get("session_start")!({}, ctx); const initial = await inspect();
  assert.equal(initial.enabled, true); assert.ok(initial.effectivePolicy); assert.equal(initial.startupError, null);
  writeFileSync(projectPath, '{"unknownIsSuccess":true}');
  await hooks.get("session_start")!({}, ctx); const invalid = await inspect();
  assert.equal(invalid.enabled, false); assert.equal(invalid.effectivePolicy, null); assert.equal(invalid.startupError, "UNKNOWN_FIELD"); assert.equal(invalid.storageRoot, null);
  writeFileSync(projectPath, "{}"); await hooks.get("session_start")!({}, ctx); const restored = await inspect();
  assert.equal(restored.enabled, true); assert.equal(restored.startupError, null); assert.deepEqual(restored.effectivePolicy, initial.effectivePolicy);
});
