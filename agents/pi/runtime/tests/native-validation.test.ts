import assert from "node:assert/strict";
import { test } from "node:test";
import { exerciseNativeSession } from "../native-validation.ts";
const runtimeSlot = Symbol.for("agentcfg.pi.runtime.v1"), managerSlot = Symbol.for("agentcfg.pi.managed.v1");
test("native scenario assertions cannot accept version-only or empty SDK results", async () => {
  const input = { scenario: "host-resources", project: "/fixture/project" };
  const session = { bindExtensions: async () => {}, getActiveToolNames: () => ["Agent", "read"], prompt: async () => {},
    getLastAssistantText: () => "synthetic version-only response", messages: [], sessionManager: { getSessionId: () => "fixture" } };
  const host = { session, services: { modelRuntime: { getModels: () => [{ provider: "fixture", id: "agentcfg-native-main" }] } } };
  try {
    await assert.rejects(exerciseNativeSession(host, input), /NATIVE_MANAGER_UNVERIFIED/);
    globalThis[runtimeSlot] = { supervisor: {}, permissionAccess: { setMode: (session, mode, cwd) => {
      assert.equal(session, "fixture"); assert.equal(mode, "cwd"); assert.equal(cwd, input.project);
    } }, manifest: { plugins: [], role_bindings: {}, allowed_models: [{ provider: "fixture", model: "agentcfg-native-main" }] } };
    globalThis[managerSlot] = { manager: { getMaxConcurrent: () => 2 } };
    await assert.rejects(exerciseNativeSession(host, input), /NATIVE_PROMPT_UNVERIFIED/);
    session.getActiveToolNames = () => ["Agent", "read", "codex_delegate"];
    await assert.rejects(exerciseNativeSession(host, input), /NATIVE_TOOLS_UNVERIFIED/);
    await assert.rejects(exerciseNativeSession(host, { ...input, scenario: "invented" }), /NATIVE_SCENARIO_UNSUPPORTED/);
  } finally { delete globalThis[runtimeSlot]; delete globalThis[managerSlot]; }
});

test("native commands recognize structured rejection and retry only a still-stopping response", async () => {
  const { nativeCommand } = await import("../native-validation.ts");
  const session = { messages: [] }, runner = { createCommandContext: () => ({}) };
  const command = details => ({ handler: async () => { session.messages.push({ role: "custom", customType: "task-keeper:status", details }); } });
  assert.equal(await nativeCommand(session, runner, command({ id: "job", status: "RUNNING" }), "resume job"), true);
  assert.equal(await nativeCommand(session, runner, command({ code: "JOB_STILL_STOPPING", exit_code: 4 }), "resume job", true), false);
  await assert.rejects(nativeCommand(session, runner, command({ code: "POLICY_CHANGED_REQUIRES_RECONCILIATION", exit_code: 4 }), "resume job", true), /NATIVE_COMMAND_REJECTED/);
  await assert.rejects(nativeCommand(session, runner, { handler: async () => {} }, "resume job"), /NATIVE_COMMAND_RESULT_UNVERIFIED/);
});

test("native user CLI uses a fixed first-party entry and a minimal environment", async () => {
  const { nativeUserCLI } = await import("../native-validation.ts");
  const { EventEmitter } = await import("node:events");
  const runtime = { supervisor: { options: { python: "/fixture/python" } }, runtimeRoot: "/fixture/runtime", instanceRoot: "/fixture/instance" };
  const child = new EventEmitter(); child.stdout = new EventEmitter(); child.stderr = new EventEmitter(); child.kill = () => {};
  const result = await nativeUserCLI(runtime, "model-delegate-batch.py", ["status", "--batch-id", "fixture"], (program, argv, options) => {
    assert.equal(program, "/fixture/python");
    assert.equal(argv[2], "/fixture/runtime/supervisor/scripts/model-delegate-batch.py");
    assert.deepEqual(Object.keys(options.env).sort(), ["HOME", "PATH", "PYTHONDONTWRITEBYTECODE"]);
    queueMicrotask(() => { child.stdout.emit("data", Buffer.from('{"state":"completed"}\n')); child.emit("close", 0); });
    return child;
  });
  assert.equal(result.state, "completed");
  await assert.rejects(nativeUserCLI(runtime, "arbitrary.py", [], () => assert.fail("must not spawn")), /NATIVE_CLI_UNSUPPORTED/);
});

test("ordinary cancellation waits for the SDK promise and stream after the manager says stopped", async () => {
  const { mkdtempSync, writeFileSync, rmSync } = await import("node:fs");
  const { tmpdir } = await import("node:os");
  const { join } = await import("node:path");
  const root = mkdtempSync(join(tmpdir(), "native-cancel-"));
  let settle, settled = false;
  const record = { status: "running", session: { isStreaming: true }, promise: new Promise(resolve => { settle = resolve; }) };
  const session = { bindExtensions: async () => {}, getActiveToolNames: () => ["Agent"] };
  const host = { session, services: { modelRuntime: { getModels: () => [] } } };
  const input = { scenario: "ordinary-cancel", project: root, output: join(root, "scenario-result.json"), nonce: "fixture", runtime_identity: "runtime" };
  writeFileSync(join(root, "model-request-started.json"), JSON.stringify({ nonce: input.nonce, runtime_identity: input.runtime_identity }), { mode: 0o600 });
  writeFileSync(join(root, "code.txt"), "original\n");
  try {
    globalThis[runtimeSlot] = { supervisor: {}, manifest: { plugins: [], role_bindings: { scout: {} }, allowed_models: [] } };
    globalThis[managerSlot] = { pi: {}, getContext: () => ({}), manager: {
      getMaxConcurrent: () => 2, spawn: () => "ordinary", getRecord: () => record, hasRunning: () => false,
      abort: () => { record.status = "stopped"; setTimeout(() => { settled = true; record.session.isStreaming = false; settle(); }, 20); return true; }
    } };
    const result = await exerciseNativeSession(host, input);
    assert.equal(settled, true);
    assert.equal(result.sdk_stream_settled, true);
    assert.equal(result.cancel_after_request_verified, true);
  } finally { delete globalThis[runtimeSlot]; delete globalThis[managerSlot]; rmSync(root, { recursive: true, force: true }); }
});

test("managed proxy scenarios are admitted by the SDK driver", async () => {
  const { nativeSessionScenarios } = await import("../native-validation.ts");
  for (const name of ["taskkeeper-proxy-fix", "taskkeeper-proxy-second-view"]) assert.ok(nativeSessionScenarios.has(name));
});

test("native proxy admission requires the reserved model target and authenticated loopback route", async () => {
  const { validateNativeProvider } = await import("../native-validation.ts");
  const { createHash } = await import("node:crypto");
  const variable = "AGENTCFG_PI_CREDENTIAL_0123456789ABCDEF";
  const credential = "AGENTCFG_PI_ROUTE_CREDENTIAL_" + createHash("sha256").update("native-direct").digest("hex").slice(0,16).toUpperCase();
  const input = { scenario: "taskkeeper-proxy-fix", provider_port: 43217 };
  const provider = { baseUrl: "http://agentcfg-native.invalid/v1", apiKey: "$" + variable };
  const environment = { [variable]: "synthetic-native-key", [credential]: "Bearer synthetic-proxy-key" };
  const manifest = { options: { network: { routes: { "native-direct": { mode: "proxy", proxy_url: "http://127.0.0.1:43217",
    credential_ref: "secret:native-proxy-key", provider_ids: ["native-fixture"] } } } } };
  validateNativeProvider(provider, input, manifest, environment);
  for (const baseUrl of ["http://real.invalid/v1", "http://agentcfg-native.invalid:1234/v1", "http://agentcfg-native.invalid/v1?token=bad"]) {
    assert.throws(() => validateNativeProvider({ ...provider, baseUrl }, input, manifest, environment), /NATIVE_ACCOUNT_INPUT_DENIED/);
  }
  assert.throws(() => validateNativeProvider(provider, input, manifest, { ...environment, [credential]: "real-secret" }), /NATIVE_ACCOUNT_INPUT_DENIED/);
  assert.throws(() => validateNativeProvider(provider, { ...input, scenario: "taskkeeper-fix" }, manifest, environment), /NATIVE_ACCOUNT_INPUT_DENIED/);
  manifest.options.network.routes["native-direct"].proxy_url = "http://proxy.invalid:43217";
  assert.throws(() => validateNativeProvider(provider, input, manifest, environment), /NATIVE_ACCOUNT_INPUT_DENIED/);
});
