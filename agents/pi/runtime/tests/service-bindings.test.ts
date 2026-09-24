import assert from "node:assert/strict";
import { test } from "node:test";
import { agentStateClient, terminalStateSequence, terminalHyperlink, terminalClipboard } from "../service-bindings.ts";
import extension from "../../extensions/gentle-agent-state.ts";

function runtime(mode = "service") {
  return { owner: { role: "manager" }, manifest: { options: { agent_state: { mode, title: "Project" } }, resource_ids: { extensions: { "gentle-agent-state": "entry" } } } };
}

test("terminal title is explicit, bounded and never interprets injected controls", async () => {
  const output = [], value = runtime("osc");
  await agentStateClient(value, { hasUI: true }, item => output.push(item)).report("working");
  await agentStateClient(value, { hasUI: false }, item => output.push(item)).report("idle");
  assert.deepEqual(output, ["\x1b]2;Project · working\x07"]);
  assert.throws(() => terminalStateSequence("injected\x1b]2;bad", "idle"));
  assert.throws(() => terminalStateSequence("Project", "unknown"));
  value.managedRequestScope = { getStore: () => ({ task: true }) };
  await assert.rejects(agentStateClient(value, {}).report("working"), /SERVICE_CONTEXT/);
});

test("explicit link and clipboard UI actions use bounded terminal protocols without OS processes", () => {
  assert.match(terminalHyperlink("https://example.invalid/文档"), /^\x1b\]8;;https:\/\/example.invalid\//);
  for (const value of ["file:///private/file", "https://user:secret@example.invalid", "https://example.invalid/\x1b]52;bad"]) {
    assert.throws(() => terminalHyperlink(value));
  }
  assert.equal(terminalClipboard("中文\ncopy"), "\x1b]52;c;" + Buffer.from("中文\ncopy").toString("base64") + "\x07");
  assert.throws(() => terminalClipboard("x".repeat(1024 * 1024 + 1)), /OVERSIZE/);
});

test("service uses controlled command output and always finalizes, including failed delivery", async () => {
  const value = runtime(), calls = [];
  value.supervisor = { async call(method, args) { calls.push([method, args]); return { operation_id: "notify", kind: "command" }; } };
  value.ordinaryOperations = { async write() { calls.push(["execute"]); return { exitCode: 0, truncated: false, terminationConfirmed: true }; } };
  await agentStateClient(value, {}).report("blocked");
  assert.deepEqual(calls.map(row => row[0]), ["ordinary_service_prepare", "execute", "ordinary_command_finish"]);
  assert.equal(calls[0][1].state, "blocked");
  value.ordinaryOperations.write = async () => ({ exitCode: 1, truncated: false, terminationConfirmed: true });
  await assert.rejects(agentStateClient(value, {}).report("idle"), /SERVICE_EXECUTION_FAILED/);
  assert.equal(calls.at(-1)[0], "ordinary_command_finish");
});

test("independent reporter clients share one physical service channel", async () => {
  const value = runtime(), states = []; let release;
  value.supervisor = { call: async (method, args) => { if (method === "ordinary_service_prepare") states.push(args.state); return { operation_id: args.state ?? "finish" }; } };
  value.ordinaryOperations = { write: async () => { if (states.length === 1) await new Promise(resolve => { release = resolve; }); return { exitCode: 0, truncated: false, terminationConfirmed: true }; } };
  const first = agentStateClient(value, {}).report("idle"), second = agentStateClient(value, {}).report("working");
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(states, ["idle"]);
  release(); await Promise.all([first, second]);
  assert.deepEqual(states, ["idle", "working"]);
});

test("extension coalesces reports and preserves blocked state for overlapping prompts", async () => {
  const key = Symbol.for("agentcfg.pi.runtime.v1"), handlers = new Map(), states = [], warnings = [], value = runtime();
  let complete;
  value.supervisor = { async call(method, args) { if (method === "ordinary_service_prepare") states.push(args.state); return { operation_id: "notify", kind: "command" }; } };
  value.ordinaryOperations = { async write() { await new Promise(resolve => { complete = resolve; }); return { exitCode: 0, truncated: false, terminationConfirmed: true }; } };
  globalThis[key] = value;
  const ctx = { hasUI: true, ui: { notify: text => warnings.push(text) } };
  try {
    extension({ on(name, callback) { handlers.set(name, callback); } });
    handlers.get("agent_start")({}, ctx);
    await new Promise(resolve => setImmediate(resolve));
    handlers.get("tool_call")({ toolName: "request_user_input", toolCallId: "one" }, ctx);
    handlers.get("tool_call")({ toolName: "request_user_input", toolCallId: "two" }, ctx);
    handlers.get("tool_result")({ toolName: "request_user_input", toolCallId: "one" }, ctx);
    complete(); await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(states, ["working", "blocked"]);
    handlers.get("tool_result")({ toolName: "request_user_input", toolCallId: "two" }, ctx);
    complete(); await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(states, ["working", "blocked", "working"]);
    complete(); await new Promise(resolve => setImmediate(resolve));
    value.ordinaryOperations.write = async () => ({ exitCode: 0, truncated: false, terminationConfirmed: true });
    await handlers.get("session_shutdown")({}, ctx);
    assert.equal(states.at(-1), "idle"); assert.deepEqual(warnings, []);
  } finally { delete globalThis[key]; }
});
