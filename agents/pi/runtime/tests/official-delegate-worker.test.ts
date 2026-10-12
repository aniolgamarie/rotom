import test from "node:test";
import assert from "node:assert/strict";
import { runOfficialDelegateWorker } from "../official-delegate-worker.ts";
function fixture({ deny = false } = {}) {
  const saved = [], appended = [], calls = []; let sender = 0;
  const model = { provider: "selected", id: "model", api: "openai-completions", baseUrl: "https://synthetic.invalid" };
  const answer = { role: "assistant", content: [{ type: "text", text: "synthetic result" }], stopReason: "stop", usage: { input: 1, output: 2 } };
  const ai = { createAssistantMessageEventStream() { return { push() {}, end(message) { this.message = message; }, async result() { return this.message; } }; } };
  class Agent {
    constructor(options) { this.options = options; this.state = { ...options.initialState, isStreaming: false }; this.listeners = []; }
    subscribe(fn) { this.listeners.push(fn); return () => {}; }
    emit(event) { for (const fn of this.listeners) fn(event); }
    async prompt(text) {
      this.state.isStreaming = true;
      this.emit({ type: "turn_start" });
      const stream = await this.options.streamFn(this.state.model, { messages: this.state.messages }, {});
      const result = await stream.result(); this.state.messages.push(result);
      this.emit({ type: "message_end", message: result }); this.state.isStreaming = false;
    }
    async waitForIdle() {} abort() { this.state.isStreaming = false; } steer() {} followUp() {} hasQueuedMessages() { return false; }
  }
  const manager = { getCwd: () => "/owned", getSessionId: () => "native-session", getSessionFile: () => "/private/reports/sessions/new.jsonl",
    buildSessionContext: () => ({ messages: [{ role: "user", content: "preserved failure sentinel" }] }), appendMessage(value) { appended.push(value); } };
  const sdk = { SessionManager: { create: () => manager, forkFrom: () => manager } };
  const supervisor = { async call(method, args) {
    calls.push([method, structuredClone(args)]);
    if (method === "delegate_authorize_v3") return { valid: true, grant_generation: 1 };
    if (method === "delegate_meter_v3") return { allowed: !(deny && args.metric === "calls") };
    throw new Error("unexpected operation");
  } };
  const worker = { schema_version: 3, input: { request: { backend: "pi", execution_boundary: "agentcfg-tools", execution_mode: "delegate-readonly",
    run_id: "run-physical", attempt_id: "attempt-physical", lease_id: "lease", grant_generation: 1, cwd: "/owned", request_digest: "digest",
    requested_model: { provider_id: "selected", model_id: "model" } }, grant: { allowed_tools: [] }, retry_limit: 0, prompt: "literal task" },
    scoped_manifest: {}, scoped_instance_root: "/private", owner: { role: "worker", lease_id: "lease", process_identity: { pid: process.pid } }, reports: "/private/reports",
    budget: { totals: { calls: 0, turns: 0 }, limits: { per_call_output_tokens: 10 } } };
  const runtime = { getModel: () => structuredClone(model), getError: () => undefined, streamSimple() { sender++; return { async result() { return answer; } }; } };
  const input = { sdk, ai, core: { Agent }, worker, supervisor, save: async (name, value) => { saved.push([name, structuredClone(value)]); },
    initializeRuntime: () => async () => ({ modelRuntime: runtime, check() {} }) };
  return { input, saved, appended, calls, sender: () => sender };
}
test("modern worker persists public messages then reports real request and native association", async () => {
  const f = fixture(), result = await runOfficialDelegateWorker(f.input);
  assert.equal(result.failed, false); assert.equal(f.sender(), 1);
  assert.deepEqual(f.calls.filter(row => row[0] === "delegate_meter_v3").map(row => row[1].metric), ["turns", "calls"]);
  assert.equal(f.appended.length, 1);
  const session = f.saved.find(row => row[0] === "session-v3.json")[1];
  assert.equal(session.session_id, "native-session"); assert.equal(session.physical_run_id, "run-physical");
  const receipt = f.saved.find(row => row[0] === "result.json")[1];
  assert.deepEqual(receipt.observed_model, { provider_id: "selected", model_id: "model" });
  assert.equal(receipt.resume_token, null); assert.equal(receipt.host_completed, true); assert.equal(receipt.usage.cost, null);
});
test("denied pre-send meter gives zero sender and failure result, no synthetic successful output", async () => {
  const f = fixture({ deny: true }), result = await runOfficialDelegateWorker(f.input);
  assert.equal(result.failed, true); assert.equal(f.sender(), 0);
  assert.equal(f.saved.some(row => row[0] === "final.md"), false);
  assert.equal(f.saved.find(row => row[0] === "result.json")[1].host_completed, false);
});
test("wrong worker birth pid fails before any initializer or control call", async () => {
  const f = fixture(); f.input.worker.owner.process_identity.pid = process.pid + 1;
  await assert.rejects(runOfficialDelegateWorker(f.input), /WORKER_INPUT_INVALID/);
  assert.equal(f.calls.length, 0); assert.equal(f.sender(), 0);
});
