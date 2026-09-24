import assert from "node:assert/strict";
import { test } from "node:test";
import { BoundStdioTransport } from "../mcp-stdio.ts";

function fixture() {
  const calls = [], writes = [], messages = [], errors = [];
  let alive = true, accepted = false, mode = "normal", resolveJob;
  const runtime = { owner: { role: "manager" }, managedRequestScope: { getStore: () => null },
    manifest: { plugins: ["pi-mcp"], options: { mcp: { servers: { fixture: { transport: "stdio", command_ref: "mcp-fixture" } } },
      external_tools: { "mcp-fixture": { interactive: true, project_root: "project" } }, paths: { roots: { project: { path: "/fixture/project" } } } } },
    ordinaryOperations: { write(ticket, _content, _digest, _signal, callbacks) {
      callbacks.onStarted({ lease_id: "lease", process_identity: { pid: 10 } });
      return new Promise(resolve => { resolveJob = resolve; });
    }, async abort() { calls.push("abort"); if (mode !== "unknown") alive = false; } },
    supervisor: { async call(method, args) {
      calls.push(method);
      if (method === "ordinary_mcp_stdio_prepare") {
        assert.equal(args.server_name, "fixture");
        return { operation_id: "operation", lease_id: "lease", execution_class: "service", service_name: "fixture", kind: "command" };
      }
      if (method === "ordinary_command_output") {
        if (mode === "dropped") return { dropped: true, events: [], next_cursor: 0 };
        const data = Buffer.from('{"jsonrpc":"2.0","id":1,"result":{"text":"测试"}}\n');
        const split = data.indexOf(Buffer.from("测")) + 1;
        const offset = args.cursor === 0 ? data.subarray(0, split) : data.subarray(split);
        return { dropped: false, events: args.cursor < 2 ? [{ stream: "stdout", data_b64: offset.toString("base64") }] : [],
          next_cursor: Math.min(2, args.cursor + 1), has_more: args.cursor === 0, complete: false };
      }
      if (method === "ordinary_command_stdin") {
        if (!accepted) { accepted = true; throw Error("ORDINARY_STDIN_BACKPRESSURE"); }
        writes.push(args.data); assert.ok(Buffer.byteLength(args.data) <= 512);
        return { accepted_bytes: Buffer.byteLength(args.data), stdin_closed: false };
      }
      if (method === "reconcile") return { lease_id: "lease", protected: alive, termination_evidence: alive ? null : { verified: true } };
      if (method === "ordinary_command_finish") return { finished: true };
      throw Error("unexpected call");
    } } };
  const transport = new BoundStdioTransport(runtime, "fixture", { pause: () => new Promise(resolve => setTimeout(resolve, 1)), pollMilliseconds: 1 });
  transport.onmessage = message => messages.push(message); transport.onerror = error => errors.push(error.message);
  return { transport, runtime, calls, writes, messages, errors, mode(value) { mode = value; },
    finish() { alive = false; resolveJob?.({ terminationConfirmed: true, truncated: false, exitCode: 0 }); } };
}

test("MCP stdio uses bound supervised commands, preserves UTF-8 frames and chunks confirmed writes", async () => {
  const f = fixture(); let closed = 0; f.transport.onclose = () => closed++;
  await f.transport.start();
  const message = { jsonrpc: "2.0", id: 2, method: "fixture", params: { text: "中文".repeat(3000) } };
  await f.transport.send(message);
  assert.equal(f.writes.join(""), JSON.stringify(message) + "\n");
  assert.ok(f.writes.length > 1);
  assert.equal(f.messages[0].result.text, "测试");
  await f.transport.close(); f.finish();
  assert.equal(closed, 1);
  assert.ok(f.calls.includes("abort") && f.calls.includes("ordinary_command_finish"));
  await assert.rejects(f.transport.send({ jsonrpc: "2.0", method: "late" }), /CLOSED/);
});

test("MCP refuses a managed caller before allocating, and unknown termination cannot report closed", async () => {
  const denied = fixture(); denied.runtime.managedRequestScope.getStore = () => ({ task: "managed" });
  await assert.rejects(denied.transport.start(), /UNMETERED_PARENT_HELPER/);
  assert.deepEqual(denied.calls, []);
  const f = fixture(); f.mode("unknown"); f.transport.pause = async () => {};
  let closed = false; f.transport.onclose = () => { closed = true; };
  await f.transport.start();
  await assert.rejects(f.transport.close(), /MCP_TERMINATION_UNKNOWN/);
  assert.equal(closed, false);
  assert.equal(f.calls.includes("ordinary_command_finish"), false);
  f.finish();
});

test("lost supervisor output fails the transport and terminates its owned process", async () => {
  const f = fixture(); f.mode("dropped");
  await f.transport.start(); await f.transport.polling; f.finish();
  assert.deepEqual(f.errors, ["MCP_OUTPUT_INVALID"]);
  assert.equal(f.transport.closed, true);
  assert.ok(f.calls.includes("abort"));
});
