import assert from "node:assert/strict";
import { test } from "node:test";
import { SupervisedScriptWorker } from "../mcp-script.ts";

function fixture() {
  const calls = [], sent = [], output = []; let pendingInput = "", alive = true, finishJob;
  const runtime = { owner: { role: "manager" }, manifest: { plugins: ["pi-mcp"], options: {
    mcp: { scripting: { enabled: true, tool_ref: "script-node", max_seconds: 30 } },
  } }, ordinaryOperations: {
    write(ticket, _c, _d, _s, hooks) {
      const job = new Promise(resolve => { finishJob = resolve; });
      hooks.onStarted({ lease_id: ticket.lease_id, process_identity: { pid: 123 } }); return job;
    }, async abort() { calls.push("abort"); alive = false; finishJob?.({ terminationConfirmed: true, truncated: false, exitCode: 0 }); },
  }, supervisor: { async call(method, args) {
    calls.push(method);
    if (method === "ordinary_mcp_script_prepare") return { operation_id: "fixture-script", lease_id: "lease", kind: "command" };
    if (method === "ordinary_command_output") return { dropped: false, next_cursor: output.length, has_more: false,
      complete: !alive, events: output.slice(args.cursor).map(value => ({ stream: "stdout", data_b64: Buffer.from(JSON.stringify(value) + "\n").toString("base64") })) };
    if (method === "ordinary_command_stdin") {
      pendingInput += args.data;
      if (pendingInput.endsWith("\n")) {
        const message = JSON.parse(pendingInput); pendingInput = ""; sent.push(message);
        if (message.type === "init") output.push({ jsonrpc: "2.0", type: "call", id: 1, path: "fixture.tool", args: {} });
        if (message.type === "result") {
          output.push({ jsonrpc: "2.0", type: "done", returnBlock: { type: "text", text: "done" } });
          alive = false; finishJob({ terminationConfirmed: true, truncated: false, exitCode: 0 });
        }
      }
      return { accepted_bytes: Buffer.byteLength(args.data), stdin_closed: false };
    }
    if (method === "reconcile") return { lease_id: "lease", protected: alive, termination_evidence: alive ? null : { verified: true } };
    if (method === "ordinary_command_finish") return { finished: true };
    throw Error("unexpected call");
  } } };
  return { runtime, calls, sent, options: { runtime, transportOptions: { pause: () => new Promise(resolve => setTimeout(resolve, 1)) } } };
}

test("MCP script runs through supervisor and returns only after physical termination", async () => {
  const f = fixture(), worker = new SupervisedScriptWorker("await tools.call('fixture.tool', {});", 10000, f.options);
  const done = new Promise((resolve, fail) => {
    worker.on("error", fail);
    worker.on("message", value => {
      if (value.type === "call") worker.postMessage({ type: "result", id: value.id, envelope: { ok: true, data: "fixture" } });
      if (value.type === "done") resolve(value.returnBlock);
    });
  });
  assert.deepEqual(await done, { type: "text", text: "done" });
  await worker.terminate();
  assert.equal(f.sent[0].type, "init"); assert.equal(f.sent[1].type, "result");
  assert.equal(f.calls[0], "ordinary_mcp_script_prepare");
  assert.ok(f.calls.includes("reconcile") && f.calls.includes("ordinary_command_finish"));
});

test("script selection, timeout and managed context reject before a process can be allocated", () => {
  for (const kind of ["disabled", "timeout", "managed"]) {
    const f = fixture();
    if (kind === "disabled") f.runtime.manifest.options.mcp.scripting.enabled = false;
    if (kind === "managed") f.runtime.managedRequestScope = { getStore: () => ({ task: "fixture" }) };
    assert.throws(() => new SupervisedScriptWorker("emit('fixture');", kind === "timeout" ? 31000 : 1000, f.options), /SCRIPT_NOT_SELECTED|UNMETERED_PARENT_HELPER/);
    assert.deepEqual(f.calls, []);
  }
});

test("termination during asynchronous preparation still verifies and releases the late lease", async () => {
  const f = fixture(), original = f.runtime.supervisor.call;
  let release, entered;
  const prepared = new Promise(resolve => { entered = resolve; });
  f.runtime.supervisor.call = async (method, args) => {
    if (method === "ordinary_mcp_script_prepare") { entered(); await new Promise(resolve => { release = resolve; }); }
    return original(method, args);
  };
  const worker = new SupervisedScriptWorker("emit('fixture');", 1000, f.options); worker.on("error", () => {});
  await prepared;
  const stopped = worker.terminate(); release(); await stopped;
  assert.equal(f.sent.length, 0); assert.ok(f.calls.includes("abort"));
  assert.ok(f.calls.includes("reconcile") && f.calls.includes("ordinary_command_finish"));
});

test("script tool stays outside readonly roles and requires the explicit scripting choice", async () => {
  const { OrdinaryOperations } = await import("../ordinary-operations.ts");
  const f = fixture(), operations = new OrdinaryOperations({}, f.runtime);
  const event = { toolName: "mcpScript", input: { code: "emit('fixture');" } };
  assert.deepEqual(await operations.preflight(event, {}, {}, "main"), { kind: "service", tool_name: "mcpScript" });
  await assert.rejects(operations.preflight(event, {}, {}, "reviewer"), /ROLE_CEILING/);
  f.runtime.manifest.options.mcp.scripting.enabled = false;
  await assert.rejects(operations.preflight(event, {}, {}, "main"), /MCP_SCRIPT_NOT_SELECTED/);
});

test("script unknown termination cannot release its operation or claim success", async () => {
  const f = fixture(), original = f.runtime.supervisor.call;
  f.options.transportOptions.pause = async () => {};
  f.runtime.supervisor.call = async (method, args) => method === "reconcile"
    ? { lease_id: "lease", protected: true, termination_evidence: null } : original(method, args);
  const worker = new SupervisedScriptWorker("emit('fixture');", 1000, f.options); worker.on("error", () => {});
  await worker.startup;
  await assert.rejects(worker.terminate(), /MCP_TERMINATION_UNKNOWN/);
  assert.equal(f.calls.includes("ordinary_command_finish"), false);
});
