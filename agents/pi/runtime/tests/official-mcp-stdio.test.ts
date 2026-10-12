import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createHash } from "node:crypto";
import { createOfficialMcpStdioTransport } from "../official-mcp-stdio.ts";

const fixed = code => error => error.code === code && !error.message.includes("SYNTHETIC-PRIVATE");
function fixture(options = {}) {
  const root = mkdtempSync(join(tmpdir(), "native-stdio-")), calls = [], writes = [];
  const lease = "a".repeat(32), operation = "b".repeat(64);
  const processIdentity = { platform: "linux", boot_id: "synthetic-boot", pid: 123, ppid: 1, pgid: 123,
    start_time: "synthetic-start", namespace: "synthetic-namespace", uid: process.getuid() };
  const state = { started: false, stopped: false, generation: 1, checks: 0, callbacks: 0 };
  const body = Buffer.from('{"jsonrpc":"2.0","id":1,"result":{"text":"测试"}}\n');
  const save = (name, value) => { const path = join(root, "activity", name); mkdirSync(join(path, ".."), { recursive: true, mode: 0o700 });
    writeFileSync(path, Buffer.isBuffer(value) ? value : JSON.stringify(value), { mode: 0o600 }); };
  const receipt = () => {
    save("exits/" + lease + ".json", { schema_version: 1, lease_id: lease, process_identity: processIdentity, exit_code: options.exitCode ?? 0 });
    const streams = {};
    for (const [name, bytes] of [["stdout", body], ["stderr", Buffer.alloc(0)]]) {
      save("outputs/" + lease + "/" + name, bytes);
      streams[name] = { path: name, bytes: bytes.length, sha256: createHash("sha256").update(bytes).digest("hex"), truncated: false, failed: false };
    }
    if (options.badHash) streams.stdout.sha256 = "f".repeat(64);
    save("outputs/" + lease + "/capture.json", { schema_version: 1, complete: true, truncated: false, streams });
  };
  const summary = { operation_id: operation, lease_id: lease, kind: "command", execution_class: "service", service_name: "fixture",
    tool_name: "bash", command_ref: "mcp-fixture", timeout_seconds: 1, write: false }; // 原Pythonsummary没有state。
  const proof = () => ({ lease_id: lease, attempt_id: options.wrongAttempt ? "foreign" : operation, task_id: null,
    grant_generation: options.runningGeneration && state.started && !state.stopped ? 2 : state.generation, state: state.stopped || state.natural ? "reclaimed" : state.started ? "running" : "allocating",
    protected: !(state.stopped || state.natural), spawn_committed: state.started, process_status: state.started && !state.stopped ? "alive" : "dead",
    process_identity: state.started ? { ...processIdentity, ...(options.wrongProcess && state.stopped ? { start_time: "foreign" } : {}) } : null,
    termination_evidence: state.stopped || state.natural ? { verified: true, kind: state.started ? "terminated" : "never-started", execution_lease_id: lease } : null });
  const supervisor = { options: { endpoint: join(root, "activity/control/control.json") }, async call(method, args) {
    assert.equal(this, supervisor); calls.push({ method, args });
    if (method === "ordinary_mcp_stdio_prepare") { await state.prepareWait; return { ...summary, ...options.ticket }; }
    if (method === "inspect" || method === "reconcile") return proof();
    if (method === "start") {
      assert.deepEqual(args, { lease_id: lease, program: "ordinary-command", payload: { operation_id: operation } });
      await state.startWait; state.started = true;
      if (options.lostStart) throw Error("SYNTHETIC-PRIVATE lost ack");
      return { lease_id: lease, state: "running" };
    }
    if (method === "cancel" || method === "abort_allocation") {
      if (method === "cancel") state.generation++;
      else assert.equal(state.started, false);
      state.stopped = !options.unknown; if (state.started && state.stopped) receipt();
      if (options.lostCancel) throw Error("SYNTHETIC-PRIVATE lost cancel ack");
      return proof();
    }
    if (method === "ordinary_command_finish") return { finished: true };
    if (method === "ordinary_command_output") {
      if (options.dropped) return { dropped: true, events: [], next_cursor: 0 };
      const split = body.indexOf(Buffer.from("测")) + 1;
      return { dropped: false, next_cursor: Math.min(2, args.cursor + 1), has_more: args.cursor === 0, complete: state.stopped,
        events: args.cursor < 2 ? [{ stream: "stdout", data_b64: (args.cursor === 0 ? body.subarray(0, split) : body.subarray(split)).toString("base64") }] : [] };
    }
    if (method === "ordinary_command_stdin") { writes.push(args.data); return { accepted_bytes: Buffer.byteLength(args.data), stdin_closed: false }; }
    throw Error("unexpected call");
  } };
  const runtime = { owner: { role: "manager" }, supervisor, instanceRoot: join(root, "separate-instance"), managedRequestScope: { getStore: () => null },
    manifest: { profile_id: "pi-base", bootstrap: false, plugins: [], native_mcp: { schema_version: 1 }, options: {
      mcp: { servers: { fixture: { transport: "stdio", command_ref: "mcp-fixture" } } },
      external_tools: { "mcp-fixture": { interactive: true, project_root: "project" } },
      paths: { roots: { project: { path: "/synthetic/project", purpose: "project" } } } } } };
  const check = () => { state.checks++; if (state.stale) throw Error("SYNTHETIC-PRIVATE context"); };
  const transport = createOfficialMcpStdioTransport({ runtime, serverName: "fixture", check });
  return { transport, runtime, state, calls, writes, lease, operation, processIdentity, receipt };
}
const methods = f => f.calls.map(row => row.method);

test("native-only service starts once without consumed state or legacy global manager and preserves UTF8 IO", async () => {
  const symbol = Symbol.for("agentcfg.pi.managed.v1"), previous = Object.getOwnPropertyDescriptor(globalThis, symbol);
  Object.defineProperty(globalThis, symbol, { configurable: true, get() { throw Error("legacy manager accessed"); } });
  const f = fixture(), messages = []; let closed = 0;
  try {
    let unsubscribed = 0; const unsubscribe = f.transport.onMessage(() => unsubscribed++); unsubscribe();
    f.transport.onMessage(function (message) { assert.equal(this.serverName, "fixture"); messages.push(message); }); f.transport.onClose(() => closed++);
    await f.transport.start(); await f.transport.send({ jsonrpc: "2.0", id: 2, params: { text: "中文".repeat(500), ratio: 1.5 } });
    assert.equal(JSON.parse(f.writes.join("")).params.ratio, 1.5); assert.ok(f.writes.every(value => Buffer.byteLength(value) <= 512));
    assert.equal(messages[0].result.text, "测试"); assert.equal(unsubscribed, 0); await f.transport.close(); assert.equal(closed, 1);
    assert.equal(methods(f).filter(name => name === "start").length, 1); assert.ok(methods(f).includes("ordinary_command_finish"));
  } finally { if (previous) Object.defineProperty(globalThis, symbol, previous); else delete globalThis[symbol]; }
});

test("lost start ack inspects the same lease and never reissues start", async () => {
  const f = fixture({ lostStart: true }); await f.transport.start(); await f.transport.close();
  assert.equal(methods(f).filter(name => name === "start").length, 1);
  assert.ok(methods(f).filter(name => name === "inspect").length >= 2);
});

test("wrong service ticket refuses startup and does not falsify consumed state", async () => {
  const f = fixture({ ticket: { service_name: "foreign" } });
  await assert.rejects(f.transport.start(), error => error.code?.startsWith("MCP_STDIO_"));
  assert.equal(methods(f).includes("start"), false);
});

test("wrong attempt blocks start and running generation drift cannot be startup proof", async () => {
  for (const options of [{ wrongAttempt: true }, { runningGeneration: true }]) {
    const f = fixture(options);
    await assert.rejects(f.transport.start(), fixed("MCP_STDIO_TERMINATION_UNKNOWN"));
    await f.transport.close().catch(() => {});
    if (options.wrongAttempt) assert.equal(methods(f).includes("start"), false);
  }
});

test("lost cancel ACK uses one revocation generation and no cancel replay", async () => {
  const f = fixture({ lostCancel: true }); await f.transport.start(); await f.transport.close(); await f.transport.close();
  assert.equal(methods(f).filter(name => name === "cancel").length, 1); assert.equal(f.state.generation, 2);
});

test("close waits delayed prepare and aborts its actual late lease without spawning", async () => {
  const f = fixture(); let release; f.state.prepareWait = new Promise(resolve => { release = resolve; });
  const start = f.transport.start(); start.catch(() => {}); const close = f.transport.close(); release();
  await close; await assert.rejects(start, error => error.code?.startsWith("MCP_STDIO_"));
  assert.equal(methods(f).includes("start"), false); assert.equal(methods(f).filter(name => name === "abort_allocation").length, 1);
});

test("close waits delayed physical start ACK and cancels late child exactly once", async () => {
  const f = fixture(); let release; f.state.startWait = new Promise(resolve => { release = resolve; });
  const start = f.transport.start(); start.catch(() => {});
  while (!methods(f).includes("start")) await new Promise(resolve => setTimeout(resolve, 1));
  const close = f.transport.close(); release(); await close;
  await assert.rejects(start, error => error.code?.startsWith("MCP_STDIO_"));
  assert.equal(methods(f).filter(name => name === "start").length, 1); assert.equal(methods(f).filter(name => name === "cancel").length, 1);
});

test("unknown termination cannot emit close or finish an unverified lease", async () => {
  const f = fixture({ unknown: true }); let closed = 0; f.transport.onClose(() => closed++); await f.transport.start();
  await assert.rejects(f.transport.close(), fixed("MCP_STDIO_TERMINATION_UNKNOWN"));
  assert.equal(closed, 0); assert.equal(methods(f).includes("ordinary_command_finish"), false);
});

test("private capture hash and process identity failures remain explicit and cannot report closed", async () => {
  for (const options of [{ badHash: true }, { wrongProcess: true }]) {
    const f = fixture(options); let closed = false; f.transport.onClose(() => { closed = true; }); await f.transport.start();
    await assert.rejects(f.transport.close(), error => ["MCP_STDIO_EVIDENCE_INVALID", "MCP_STDIO_TERMINATION_UNKNOWN"].includes(error.code));
    assert.equal(closed, false); assert.equal(methods(f).includes("ordinary_command_finish"), false);
  }
});

test("managed/stale callers are rejected before allocation and later sends are blocked after close", async () => {
  const f = fixture(); f.runtime.managedRequestScope.getStore = () => ({ managed: true });
  await assert.rejects(f.transport.start(), error => error.code?.startsWith("MCP_STDIO_")); assert.deepEqual(f.calls, []);
  const stale = fixture(); stale.state.stale = true;
  await assert.rejects(stale.transport.start(), fixed("MCP_STDIO_CONTEXT_INVALID")); assert.deepEqual(stale.calls, []);
  const g = fixture(); await g.transport.start(); await g.transport.close();
  await assert.rejects(g.transport.send({ jsonrpc: "2.0", method: "late" }), fixed("MCP_STDIO_CLOSED"));
});

test("live stdin rejects a revoked generation before writing any protocol bytes", async () => {
  const f = fixture(); await f.transport.start(); f.state.generation = 2;
  try {
    await assert.rejects(f.transport.send({ jsonrpc: "2.0", id: 1, method: "ping" }), fixed("MCP_STDIO_TERMINATION_UNKNOWN"));
    assert.equal(methods(f).includes("ordinary_command_stdin"), false);
  } finally { await f.transport.close().catch(() => {}); }
});

test("natural verified termination retains original generation and reads real receipt without cancel", async () => {
  const f = fixture(); await f.transport.start(); f.state.natural = true; f.receipt(); await f.transport.close();
  assert.equal(f.state.generation, 1); assert.equal(methods(f).includes("cancel"), false);
  assert.ok(methods(f).includes("ordinary_command_finish"));
});
