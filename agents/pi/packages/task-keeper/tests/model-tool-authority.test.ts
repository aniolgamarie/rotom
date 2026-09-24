import { test, assert, evidence } from "./recorded-test.ts";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import taskKeeper from "../index.ts";
import { TaskService } from "../src/orchestration/service.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S CFG-001 REC-019] a model tool reply from before a human pause cannot renew control", async t => {
  const root = isolatedDirectory(t), config = configured(), configPath = join(root, "config.json");
  config.features.interactiveRecovery = false; config.features.managedWorkflows = true; config.storage.path = join(root, "state/runtime.db");
  writeFileSync(configPath, JSON.stringify(config), { mode: 0o600 });
  const saved = process.env.PI_TASK_KEEPER_CONFIG; process.env.PI_TASK_KEEPER_CONFIG = configPath;
  const hooks = new Map<string, (event: any, ctx: ExtensionContext) => any>(), commands = new Map<string, any>(); let tool: any;
  const pi = { on: (name: string, callback: any) => hooks.set(name, callback), registerTool: (definition: any) => { tool = definition; },
    registerCommand: (name: string, definition: any) => commands.set(name, definition), appendEntry() {} } as unknown as ExtensionAPI;
  const ctx = { cwd: root, modelRegistry: { find: () => undefined }, ui: { notify() {} },
    sessionManager: { getBranch: () => [], getHeader: () => null, getSessionId: () => "session", getSessionFile: () => join(root, "session.jsonl") } } as unknown as ExtensionContext;
  let state = "RUNNING", resumes = 0, submissions = 0;
  t.mock.method(TaskService.prototype, "submit", () => { submissions++; return { id: "job" }; });
  t.mock.method(TaskService.prototype, "describe", () => ({ id: "job", status: state }));
  t.mock.method(TaskService.prototype, "inspect", async () => ({ id: "job", status: state }));
  t.mock.method(TaskService.prototype, "pause", () => { state = "PAUSED"; });
  t.mock.method(TaskService.prototype, "resume", async () => { resumes++; state = "RUNNING"; });
  taskKeeper(pi);
  t.after(async () => { await hooks.get("session_shutdown")!({}, ctx); if (saved === undefined) delete process.env.PI_TASK_KEEPER_CONFIG; else process.env.PI_TASK_KEEPER_CONFIG = saved; });
  await hooks.get("session_start")!({}, ctx); assert.ok(tool);
  const input = (source: string) => hooks.get("input")!({ source, text: "fixture", images: [] }, ctx);
  const start = () => hooks.get("before_agent_start")!({}, ctx);
  const reply = async (id: string) => {
    await hooks.get("before_provider_request")!({}, ctx);
    await hooks.get("message_end")!({ message: { role: "assistant", stopReason: "toolUse", content: [{ type: "toolCall", id, name: "kernel_task", arguments: {} }] } }, ctx);
  };
  const execute = (id: string, action: string) => tool.execute(id, { action, goal: "fixture", jobId: "job" }, undefined, undefined, ctx);
  await input("rpc"); await start(); await reply("submit"); await execute("submit", "fix"); assert.equal(submissions, 1);
  await reply("old-resume"); await commands.get("orch").handler("pause job", ctx);
  for (const id of ["CFG-001", "REC-019"]) await evidence(id, async () => {
    assert.equal(state, "PAUSED"); await assert.rejects(execute("old-resume", "resume"), { code: "MODEL_CONTROL_REVOKED" });
    assert.equal(resumes, 0); assert.equal(state, "PAUSED");
  });
  const status = await execute("status", "status"); assert.equal(status.details.status, "PAUSED");
  await input("extension"); await start(); await reply("internal-resume");
  await assert.rejects(execute("internal-resume", "resume"), { code: "MODEL_CONTROL_REVOKED" }); assert.equal(resumes, 0);
  await input("rpc"); await start(); await reply("fresh-resume"); await execute("fresh-resume", "resume");
  assert.equal(resumes, 1); assert.equal(state, "RUNNING");
  await assert.rejects(execute("fresh-resume", "resume"), { code: "MODEL_CONTROL_REVOKED" }); assert.equal(resumes, 1);
  await hooks.get("before_provider_request")!({}, ctx);
  await hooks.get("message_end")!({ message: { role: "assistant", stopReason: "length", content: [{ type: "toolCall", id: "incomplete", name: "kernel_task", arguments: {} }] } }, ctx);
  await assert.rejects(execute("incomplete", "resume"), { code: "MODEL_CONTROL_REVOKED" }); assert.equal(resumes, 1);
});
