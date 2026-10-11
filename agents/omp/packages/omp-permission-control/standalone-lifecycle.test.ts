import { expect, test, setSystemTime } from "bun:test";
import { createHash } from "node:crypto";
import { baseConfig, fakeHost, fakeNativeRuntime, nativeReady, ready } from "./standalone-fixture";

const config = { ...baseConfig, nativeBash: true };
const limits = { contextTimeoutMs: 20, queueTimeoutMs: 200, pollIntervalMs: 5 };
const input = { command: "echo fixture", timeout: 2 };
function deferred<T = void>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
async function until(predicate: () => boolean) {
  for (let i = 0; i < 200 && !predicate(); i++) await new Promise(resolve => setTimeout(resolve, 1));
  expect(predicate()).toBe(true);
}
function response(decision = "allow") {
  return new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify({ decision,
    risk: decision === "allow" ? "low" : "unknown", authorization: decision === "allow" ? "sufficient" : "unknown",
    reasonCode: decision === "allow" ? "LOW_RISK_AUTHORIZED" : "UNKNOWN_RISK" }) } }] }));
}
function records(h: Awaited<ReturnType<typeof fakeHost>>, id: string) {
  const digest = createHash("sha256").update("rotom.permission-control.toolCallId.v1\0").update(id).digest("hex");
  return h.auditEntries.filter(row => row.data.toolCallIdDigest === digest);
}
const event = (id: string, name = "bash", params: object = input) =>
  ({ type: "tool_call", toolName: name, toolCallId: id, input: params });

test("a late session reset cannot undo the user's newer permission mode", async () => {
  const late = deferred<typeof config>();
  let loads = 0;
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime,
    loadConfig: async () => loads++ === 0 ? config : late.promise });
  const resetting = h.events.get("session_start")({}, h.ctx);
  await h.commands.get("permission-control").handler("manual", h.ctx);
  late.resolve(config); await resetting;
  await h.commands.get("permission-control").handler("status", h.ctx);
  expect(JSON.parse(h.notices.at(-1)!).mode).toBe("manual");
});

for (const mode of ["smart", "manual"] as const) test(`${mode} cannot approve an unsafe privacy representation`, async () => {
  const h = await fakeHost({ config: { ...config, defaultMode: mode }, select: "Approve",
    nativeRuntime: fakeNativeRuntime().runtime });
  const { tool } = await nativeReady(h);
  const result = await tool.execute("privacy-invalid", { command: 'TOKEN="$(case x in x) touch /fixture/side-effect ;; esac)"' }, undefined, undefined, h.ctx);
  expect(result.isError).toBe(true); expect(result.details.reasonCode).toBe("INPUT_INVALID");
  expect(h.fetchCalls).toHaveLength(0); expect(h.selectCalls).toHaveLength(0); expect(h.invokeCalls).toHaveLength(0);
  expect(records(h, "privacy-invalid")[0].data.reasonCode).toBe("INPUT_INVALID");
});

for (const cancelled of [false, true]) test(`raw backend throw is an execution ${cancelled ? "cancellation" : "failure"}`, async () => {
  const controller = new AbortController();
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime,
    execImpl: async () => { if (cancelled) controller.abort(); throw new Error("PRIVATE_CANARY_BACKEND"); } });
  await ready(h);
  const result = await h.tools.get("permission_bash").execute("raw-throw", input, controller.signal, undefined, h.ctx);
  expect(result.isError).toBe(true); expect(result.details.reasonCode).toBe("RAW_EXECUTION_FAILED");
  expect(h.execCalls).toHaveLength(1);
  const record = records(h, "raw-throw")[0].data;
  expect(record.outcome).toBe(cancelled ? "cancelled" : "failed");
  expect(record.reasonCode).toBe("RAW_EXECUTION_FAILED"); expect(JSON.stringify(record)).not.toContain("PRIVATE_CANARY");
});

for (const mode of ["manual", "smart"] as const) {
  for (const reasonCode of ["UNSUPPORTED_EXECUTION_CONTEXT", "NATIVE_PROMPT"] as const) {
    test(`${mode} approval cannot bypass unsupported native binding with ${reasonCode}`, async () => {
      const h = await fakeHost({ config: { ...config, defaultMode: mode }, select: "Approve",
        nativeRuntime: fakeNativeRuntime({ decision: "prompt", reasonCode, bindingSupported: false }).runtime });
      const { tool } = await nativeReady(h);
      const result = await tool.execute("unbound", input, undefined, undefined, h.ctx);
      expect(result.isError).toBe(true);
      expect(result.details.reasonCode).toBe("UNSUPPORTED_EXECUTION_CONTEXT");
      expect(h.invokeCalls).toHaveLength(0); expect(h.execCalls).toHaveLength(0);
      expect(h.selectCalls).toHaveLength(0);
      expect(h.fetchCalls).toHaveLength(mode === "smart" && reasonCode === "UNSUPPORTED_EXECUTION_CONTEXT" ? 1 : 0);
    });
  }
}

for (const name of ["bash", "permission_bash"]) test(`${name} session A B A cannot replay a consumed call`, async () => {
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime });
  let session = "A";
  h.ctx.sessionManager.getSessionId = () => session;
  await ready(h);
  const tool = h.tools.get(name);
  expect((await tool.execute("same-id", input, undefined, undefined, h.ctx)).isError).toBeUndefined();
  session = "B"; await h.events.get("session_switch")({}, h.ctx);
  expect((await tool.execute("same-id", input, undefined, undefined, h.ctx)).isError).toBeUndefined();
  session = "A"; await h.events.get("session_switch")({}, h.ctx);
  const replay = await tool.execute("same-id", input, undefined, undefined, h.ctx);
  expect(replay.isError).toBe(true); expect(replay.details.reasonCode).toBe("DUPLICATE_TOOL_CALL");
  expect(h.fetchCalls).toHaveLength(2);
  expect(name === "bash" ? h.invokeCalls : h.execCalls).toHaveLength(2);
});

for (const name of ["bash", "permission_bash"]) test(`${name} hook never waits for capture/model/UI and direct execute still reviews`, async () => {
  const capture = deferred();
  const native = fakeNativeRuntime();
  const original = native.runtime.capture;
  native.runtime.capture = async (...args: any[]) => { await capture.promise; return original(...args); };
  const h = await fakeHost({ config, nativeRuntime: native.runtime, lifecycle: { ...limits, contextTimeoutMs: 200 } });
  await ready(h);
  const result = await Promise.race([h.events.get("tool_call")(event("quick", name), h.ctx),
    new Promise(resolve => setTimeout(() => resolve("HOST_HOOK_TIMEOUT"), 10))]);
  expect(result).toBeUndefined(); expect(h.fetchCalls).toHaveLength(0); expect(h.selectCalls).toHaveLength(0);
  const pending = h.tools.get(name).execute("direct", input, undefined, undefined, h.ctx);
  await new Promise(resolve => setTimeout(resolve, 15));
  expect(h.fetchCalls).toHaveLength(0); expect(h.invokeCalls).toHaveLength(0); expect(h.execCalls).toHaveLength(0);
  capture.resolve();
  expect((await pending).isError).toBeUndefined(); expect(h.fetchCalls).toHaveLength(1);
  expect(name === "bash" ? h.invokeCalls : h.execCalls).toHaveLength(1);
});

test("ten requests use two model slots and independent one-place human queue", async () => {
  let activeModels = 0, maxModels = 0, activeUI = 0, maxUI = 0;
  const modelGates: Array<ReturnType<typeof deferred<Response>>> = [];
  const uiGates: Array<ReturnType<typeof deferred<string>>> = [];
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime, lifecycle: { ...limits, queueTimeoutMs: 1000 },
    fetchImpl: async (_url, init) => {
      activeModels++; maxModels = Math.max(maxModels, activeModels);
      const gate = deferred<Response>(); modelGates.push(gate);
      try { return await gate.promise; } finally { activeModels--; }
    },
    selectImpl: async () => {
      activeUI++; maxUI = Math.max(maxUI, activeUI);
      const gate = deferred<string>(); uiGates.push(gate);
      try { return await gate.promise; } finally { activeUI--; }
    } });
  const { tool } = await nativeReady(h);
  const operations = Array.from({ length: 10 }, (_, index) => tool.execute(`parallel-${index}`,
    { command: `echo fixture-${index}` }, undefined, undefined, h.ctx));
  await until(() => modelGates.length === 2);
  expect(maxModels).toBe(2);
  for (let index = 0; index < 10; index++) {
    await until(() => modelGates.length > index);
    modelGates[index].resolve(response(index < 2 ? "ask" : "allow"));
  }
  await until(() => h.invokeCalls.length === 8 && uiGates.length === 1);
  expect(h.fetchCalls).toHaveLength(10); expect(h.selectCalls).toHaveLength(1);
  uiGates[0].resolve("Approve"); await until(() => uiGates.length === 2); uiGates[1].resolve("Approve");
  const results = await Promise.all(operations);
  expect(results.every(result => result.isError !== true)).toBe(true);
  expect(maxModels).toBe(2); expect(maxUI).toBe(1); expect(h.invokeCalls).toHaveLength(10);
  expect(h.auditEntries.filter(row => row.data.outcome === "executed")).toHaveLength(10);
});

test("human wait beyond old hook budget leaves model slot free", async () => {
  const ui = deferred<string>();
  let fetches = 0;
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime, lifecycle: limits,
    fetchImpl: async () => response(fetches++ === 0 ? "ask" : "allow"), selectImpl: () => ui.promise });
  const { tool, hook } = await nativeReady(h);
  expect(await hook(event("long-ui"), h.ctx)).toBeUndefined();
  const pending = tool.execute("long-ui", input, undefined, undefined, h.ctx);
  await until(() => h.selectCalls.length === 1);
  const now = Date.now();
  try {
    setSystemTime(now + 31_000);
    expect((await tool.execute("during-ui", input, undefined, undefined, h.ctx)).isError).toBeUndefined();
    expect(h.invokeCalls).toHaveLength(1);
    ui.resolve("Approve"); expect((await pending).isError).toBeUndefined();
    expect(h.invokeCalls).toHaveLength(2);
  } finally { setSystemTime(); }
});

test("queued human requests have a deadline without expiring the active UI", async () => {
  const ui = deferred<string>();
  const controller = new AbortController();
  const h = await fakeHost({ config: { ...config, defaultMode: "manual" }, nativeRuntime: fakeNativeRuntime().runtime,
    lifecycle: { ...limits, queueTimeoutMs: 20 }, selectImpl: () => ui.promise });
  const { tool } = await nativeReady(h);
  const active = tool.execute("active-human", input, controller.signal, undefined, h.ctx);
  await until(() => h.selectCalls.length === 1);
  const expired = await tool.execute("queued-human", input, undefined, undefined, h.ctx);
  expect(expired.details.reasonCode).toBe("REVIEW_QUEUE_TIMEOUT");
  expect(h.selectCalls).toHaveLength(1); expect(h.invokeCalls).toHaveLength(0);
  controller.abort(); expect((await active).isError).toBe(true); ui.resolve("Approve");
  expect(h.invokeCalls).toHaveLength(0);
});

for (const phase of ["capture", "recheck"] as const) test(`hung ${phase} cancelled on generation change and successor advances`, async () => {
  const entered = deferred(); const late = deferred();
  const native = fakeNativeRuntime(); const original = native.runtime[phase];
  let calls = 0;
  native.runtime[phase] = async (...args: any[]) => {
    if (calls++ === 0) { entered.resolve(); await late.promise; }
    return original(...args);
  };
  const h = await fakeHost({ config, nativeRuntime: native.runtime, lifecycle: { ...limits, contextTimeoutMs: 200 } });
  const { tool } = await nativeReady(h);
  const obsolete = tool.execute("old-generation", input, undefined, undefined, h.ctx);
  await entered.promise;
  await h.commands.get("permission-control").handler("manual", h.ctx);
  await h.commands.get("permission-control").handler("smart", h.ctx);
  expect((await obsolete).isError).toBe(true);
  expect((await tool.execute("new-generation", input, undefined, undefined, h.ctx)).isError).toBeUndefined();
  expect(h.invokeCalls).toHaveLength(1);
  late.resolve(); await new Promise(resolve => setTimeout(resolve, 5));
  expect(h.invokeCalls).toHaveLength(1);
  expect(records(h, "old-generation")).toHaveLength(1);
});

for (const phase of ["capture", "recheck"] as const) test(`hung ${phase} has bounded context timeout`, async () => {
  const native = fakeNativeRuntime();
  native.runtime[phase] = async () => new Promise<any>(() => {});
  const h = await fakeHost({ config, nativeRuntime: native.runtime, lifecycle: limits });
  const { tool } = await nativeReady(h);
  const result = await tool.execute(`timeout-${phase}`, input, undefined, undefined, h.ctx);
  expect(result.isError).toBe(true); expect(h.invokeCalls).toHaveLength(0);
  expect(h.auditEntries).toHaveLength(1);
});

for (const name of ["bash", "permission_bash"]) test(`${name} duplicate and cross-entrypoint id never executes twice`, async () => {
  const wait = deferred<Response>();
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime, lifecycle: limits, fetchImpl: () => wait.promise });
  await ready(h);
  const tool = h.tools.get(name);
  const first = tool.execute("same-id", input, undefined, undefined, h.ctx);
  await until(() => h.fetchCalls.length === 1);
  expect((await tool.execute("same-id", input, undefined, undefined, h.ctx)).isError).toBe(true);
  const other = h.tools.get(name === "bash" ? "permission_bash" : "bash");
  expect((await other.execute("same-id", input, undefined, undefined, h.ctx)).isError).toBe(true);
  wait.resolve(response()); expect((await first).isError).toBeUndefined();
  expect((await tool.execute("same-id", input, undefined, undefined, h.ctx)).isError).toBe(true);
  expect(h.fetchCalls).toHaveLength(1); expect(h.invokeCalls.length + h.execCalls.length).toBe(1);
});

test("late model allow after cancellation never executes or calls fallback", async () => {
  const late = deferred<Response>(); const controller = new AbortController();
  const h = await fakeHost({ config: { ...config, remoteFallback: { provider: "remote", model: "fallback" } },
    nativeRuntime: fakeNativeRuntime().runtime, lifecycle: limits, fetchImpl: () => late.promise });
  const { tool } = await nativeReady(h);
  const pending = tool.execute("late", input, controller.signal, undefined, h.ctx);
  await until(() => h.fetchCalls.length === 1); controller.abort();
  expect((await pending).isError).toBe(true); late.resolve(response());
  await new Promise(resolve => setTimeout(resolve, 5));
  expect(h.fetchCalls).toHaveLength(1); expect(h.selectCalls).toHaveLength(0); expect(h.invokeCalls).toHaveLength(0);
  expect(h.auditEntries).toHaveLength(1);
});

test("new queued user input cancels active and model-queued operations", async () => {
  const late = deferred<Response>();
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime, lifecycle: limits, fetchImpl: () => late.promise });
  const { tool } = await nativeReady(h);
  const operations = Array.from({ length: 3 }, (_, index) => tool.execute(`user-queued-${index}`, input, undefined, undefined, h.ctx));
  await until(() => h.fetchCalls.length === 2);
  h.ctx.hasPendingMessages = () => true;
  const results = await Promise.all(operations);
  expect(results.every(result => result.isError === true)).toBe(true);
  expect(h.fetchCalls).toHaveLength(2); expect(h.invokeCalls).toHaveLength(0); expect(h.selectCalls).toHaveLength(0);
  late.resolve(response());
  expect(h.auditEntries).toHaveLength(3);
});

test("live SessionManager cwd changes invalidate a snapshot ExtensionContext", async () => {
  const late = deferred<Response>();
  let cwd = "/repo";
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime, lifecycle: limits,
    fetchImpl: () => late.promise });
  h.ctx.sessionManager.getCwd = () => cwd;
  const { tool } = await nativeReady(h);
  const pending = tool.execute("live-cwd-changed", input, undefined, undefined, h.ctx);
  await until(() => h.fetchCalls.length === 1);
  cwd = "/fixture-moved";
  const result = await pending;
  expect(h.ctx.cwd).toBe("/repo"); expect(result.isError).toBe(true);
  expect(h.invokeCalls).toHaveLength(0); expect(h.execCalls).toHaveLength(0);
  late.resolve(response());
});

for (const name of ["bash", "permission_bash"]) test(`${name} consumed execution survives mode change but caller abort reaches backend`, async () => {
  const started = deferred<AbortSignal>(); const finish = deferred(); const controller = new AbortController();
  const execute = async (...args: any[]) => {
    const signal = name === "bash" ? args[1].signal : args[2].signal;
    started.resolve(signal); await finish.promise;
    return name === "bash" ? { content: [{ type: "text", text: "native-ok" }] } : { stdout: "ok", stderr: "", code: 0, killed: false };
  };
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime, lifecycle: limits,
    invokeImpl: execute, execImpl: execute });
  await ready(h);
  const operation = h.tools.get(name).execute(`running-${name}`, input, controller.signal, undefined, h.ctx);
  const signal = await started.promise;
  await h.commands.get("permission-control").handler("explain", h.ctx);
  expect(JSON.parse(h.notices.at(-1)!).outcome).toBe("executing");
  await h.commands.get("permission-control").handler("manual", h.ctx);
  expect(signal.aborted).toBe(false); controller.abort(); expect(signal.aborted).toBe(true);
  finish.resolve(); await operation;
  expect(h.invokeCalls.length + h.execCalls.length).toBe(1);
  expect(records(h, `running-${name}`)).toHaveLength(1);
});

test("per-request diagnostics and finalization stay independent during concurrency", async () => {
  const running = deferred(); const started = deferred();
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime, lifecycle: limits,
    invokeImpl: async (params: any) => {
      if (params.command === "echo first") { started.resolve(); await running.promise; }
      return { content: [{ type: "text", text: "native-ok" }] };
    } });
  const { tool } = await nativeReady(h);
  const first = tool.execute("diagnostic-first", { command: "echo first" }, undefined, undefined, h.ctx);
  await started.promise;
  expect((await tool.execute("diagnostic-second", { command: "echo second" }, undefined, undefined, h.ctx)).isError).toBeUndefined();
  running.resolve(); await first;
  expect(h.auditEntries).toHaveLength(2);
  for (const id of ["diagnostic-first", "diagnostic-second"]) {
    expect(records(h, id)).toHaveLength(1);
    expect(records(h, id)[0].data).toMatchObject({ outcome: "executed", source: "primary" });
  }
  await h.commands.get("permission-control").handler("status", h.ctx);
  const status = JSON.parse(h.notices.at(-1)!);
  expect(status.pending).toBe(0);
});

for (const name of ["bash", "permission_bash"]) test(`${name} host shutdown still cancels consumed backend execution`, async () => {
  const started = deferred<AbortSignal>(); const finish = deferred();
  const execute = async (...args: any[]) => {
    started.resolve(name === "bash" ? args[1].signal : args[2].signal);
    await finish.promise;
    return name === "bash" ? { content: [{ type: "text", text: "native-ok" }] } : { stdout: "ok", stderr: "", code: 0, killed: false };
  };
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime, lifecycle: limits,
    invokeImpl: execute, execImpl: execute });
  await ready(h);
  const operation = h.tools.get(name).execute(`shutdown-${name}`, input, undefined, undefined, h.ctx);
  const signal = await started.promise;
  expect(signal.aborted).toBe(false); await h.events.get("session_shutdown")({}, h.ctx); expect(signal.aborted).toBe(true);
  finish.resolve(); await operation;
  expect(h.invokeCalls.length + h.execCalls.length).toBe(1);
});

test("model queue deadline never starts another fetch and cancellation releases successors", async () => {
  const late = deferred<Response>();
  const h = await fakeHost({ config, nativeRuntime: fakeNativeRuntime().runtime,
    lifecycle: { ...limits, queueTimeoutMs: 20 }, fetchImpl: () => late.promise });
  const { tool } = await nativeReady(h);
  const controllers = [new AbortController(), new AbortController()];
  const first = controllers.map((controller, index) => tool.execute(`queue-active-${index}`, input, controller.signal, undefined, h.ctx));
  await until(() => h.fetchCalls.length === 2);
  const queued = await tool.execute("queue-deadline", input, undefined, undefined, h.ctx);
  expect(queued.isError).toBe(true); expect(h.fetchCalls).toHaveLength(2);
  expect(records(h, "queue-deadline")[0].data.reasonCode).toBe("REVIEW_QUEUE_TIMEOUT");
  controllers.forEach(controller => controller.abort()); await Promise.all(first);
  late.resolve(response());
  expect((await tool.execute("queue-successor", input, undefined, undefined, h.ctx)).isError).toBeUndefined();
  expect(h.invokeCalls).toHaveLength(1);
});

test("cancelled human selection releases its UI slot and late approval cannot execute", async () => {
  const controller = new AbortController(); const stale = deferred<string>();
  let selections = 0;
  const h = await fakeHost({ config: { ...config, defaultMode: "manual" }, nativeRuntime: fakeNativeRuntime().runtime,
    lifecycle: limits, selectImpl: async (_title, _items, options) => {
      expect(options.signal).toBeInstanceOf(AbortSignal);
      return selections++ === 0 ? stale.promise : "Approve";
    } });
  const { tool } = await nativeReady(h);
  const cancelled = tool.execute("ui-cancelled", input, controller.signal, undefined, h.ctx);
  await until(() => h.selectCalls.length === 1);
  const successor = tool.execute("ui-successor", input, undefined, undefined, h.ctx);
  controller.abort();
  expect((await cancelled).isError).toBe(true);
  expect((await successor).isError).toBeUndefined();
  stale.resolve("Approve"); await new Promise(resolve => setTimeout(resolve, 5));
  expect(h.invokeCalls).toHaveLength(1); expect(h.selectCalls).toHaveLength(2);
  expect(records(h, "ui-cancelled")).toHaveLength(1);
});
