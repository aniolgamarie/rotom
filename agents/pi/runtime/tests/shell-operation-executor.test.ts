import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { executeShellOperation } from "../shell-operation-executor.ts";

function fixture(options = {}) {
  const root = mkdtempSync(join(tmpdir(), "shell-executor-")), calls = [], updates = [];
  const identity = { pid: 123, start: "synthetic" }, signal = new AbortController();
  const ticket = { operation_id: "op", lease_id: "lease", kind: "command", tool_name: "bash", write: true,
    state: "consumed", timeout_seconds: options.timeoutSeconds ?? 1, command_ref: "tool:shell", request_digest: "a".repeat(64) };
  let started = false, stopped = false, time = 0, delivered = false;
  const save = (path, value) => {
    const target = join(root, "activity", path); mkdirSync(join(target, ".."), { recursive: true, mode: 0o700 });
    writeFileSync(target, Buffer.isBuffer(value) ? value : JSON.stringify(value), { mode: 0o600 });
  };
  const streams = {}, bodies = {};
  for (const name of ["stdout", "stderr"]) {
    const body = Buffer.from(options[name] ?? (name === "stdout" ? "synthetic output\n" : ""));
    bodies[name] = body;
    save("outputs/lease/" + name, body);
    streams[name] = { path: name, bytes: body.length, sha256: createHash("sha256").update(body).digest("hex"), truncated: false, failed: false };
  }
  const capture = { schema_version: 1, complete: true, truncated: false, streams };
  options.capture?.(capture); save("outputs/lease/capture.json", capture);
  save("exits/lease.json", { schema_version: 1, lease_id: "lease", process_identity: identity, exit_code: options.exitCode ?? 0, ...options.exit });
  const supervisor = { options: { endpoint: join(root, "activity/control/control.json") }, async call(method, args) {
    calls.push({ method, args });
    if (options.beforeMethod) await options.beforeMethod(method);
    if (options.delayMethod === method) time += 1001;
    if (method === "start") {
      assert.deepEqual(args, { lease_id: "lease", program: "ordinary-shell", payload: { operation_id: "op" } });
      started = true; if (options.lostStart) throw Error("private lost reply");
      return { lease_id: "lease", state: "running", attempt_id: "attempt" };
    }
    if (method === "cancel") { stopped = !options.unknownStop; return { accepted: true }; }
    if (method === "abort_allocation") { assert.equal(started, false); stopped = true; return { lease_id: "lease", state: "failed" }; }
    if (method === "inspect" || method === "reconcile") {
      const ended = stopped || started && !options.running;
      return { lease_id: "lease", state: ended ? "reclaimed" : started ? "running" : "allocating", protected: !ended,
        spawn_committed: started, process_identity: started ? identity : null,
        termination_evidence: ended ? { verified: true } : null, ...options.proof };
    }
    if (method === "ordinary_shell_output") {
      assert.equal(args.operation_id, "op");
      if (options.outputError) throw Error("private output error");
      const events = options.events ?? Object.entries(bodies).filter(([, bytes]) => bytes.length).map(([stream, bytes], index) =>
        ({ seq: index + 1, stream, data_b64: bytes.toString("base64") }));
      const result = { events: delivered ? [] : structuredClone(events), next_cursor: events.length, dropped: false, has_more: false, complete: !options.running };
      delivered = true; options.output?.(result); return result;
    }
    throw Error("unexpected method " + method);
  } };
  return { ticket, calls, signal, updates, save, root, execute: (extra = {}) => executeShellOperation({ supervisor, ticket,
    signal: signal.signal, onUpdate: value => updates.push(value), clock: () => time, pause: async () => { time += 100; }, ...extra }) };
}
const methods = f => f.calls.map(row => row.method);

test("Shell starts once without staging private script and binds completed output to process identity", async () => {
  const f = fixture(), result = await f.execute();
  assert.deepEqual(result, { stdout: "synthetic output\n", stderr: "", output: "synthetic output\n", exitCode: 0, truncated: false, terminationConfirmed: true });
  assert.equal(methods(f).filter(name => name === "start").length, 1);
  assert.ok(!methods(f).some(name => ["ordinary_stage_write", "ordinary_command_finish", "ordinary_shell_take_input"].includes(name)));
  assert.equal(f.updates[0].terminationConfirmed, false); assert.equal(f.ticket.state, "terminated");
  await assert.rejects(f.execute(), /ORDINARY_SHELL_TICKET/);
});
test("lost start reply is reconciled without resending or allocation abort", async () => {
  const f = fixture({ lostStart: true }); await f.execute();
  assert.equal(methods(f).filter(name => name === "start").length, 1); assert.ok(!methods(f).includes("abort_allocation"));
});
test("nonzero command result remains a terminated nonzero result", async () => {
  const f = fixture({ exitCode: 7, stderr: "synthetic failure\n" });
  const result = await f.execute(); assert.equal(result.exitCode, 7); assert.equal(result.terminationConfirmed, true);
});
test("preaborted known unstarted allocation is explicitly aborted without spawn", async () => {
  const f = fixture(); f.signal.abort(); await assert.rejects(f.execute(), /ORDINARY_OPERATION_CANCELED/);
  assert.ok(methods(f).includes("abort_allocation")); assert.ok(!methods(f).includes("start"));
});
test("cancellation after start waits for authoritative termination", async () => {
  const f = fixture({ running: true });
  await assert.rejects(f.execute({ pause: async () => f.signal.abort() }), /ORDINARY_OPERATION_CANCELED/);
  assert.equal(f.ticket.state, "terminated"); assert.equal(methods(f).filter(name => name === "cancel").length, 1);
});
test("deadline cancels once, retaining unknown when actual termination is unavailable", async () => {
  const f = fixture({ running: true, lostStart: true, unknownStop: true });
  await assert.rejects(f.execute(), /TERMINATION_UNKNOWN/);
  assert.equal(f.ticket.state, "unknown"); assert.equal(methods(f).filter(name => name === "cancel").length, 1);
  assert.ok(!methods(f).includes("abort_allocation"));
});
for (const patch of [{ lease_id: "other" }, { protected: true }, { termination_evidence: { verified: false } }])
  test("invalid termination proof cannot make exit status sufficient: " + JSON.stringify(patch), async () => {
    const f = fixture({ proof: patch }); await assert.rejects(f.execute(), /TERMINATION_UNKNOWN/); assert.equal(f.ticket.state, "unknown");
  });
for (const exit of [{ lease_id: "other" }, { process_identity: { pid: 456 } }, { exit_code: null }, { exit_code: "0" }, { schema_version: 2 }])
  test("rejects unbound exit record " + JSON.stringify(exit), async () => {
    const f = fixture({ exit }); await assert.rejects(f.execute(), /ORDINARY_OPERATION_EVIDENCE/);
  });
for (const change of [c => { c.complete = false; }, c => { c.streams.stdout.sha256 = "b".repeat(64); },
  c => { c.streams.stdout.bytes++; }, c => { c.streams.stdout.failed = true; }, c => { c.streams.stdout.path = "../other"; },
  c => { c.unexpected = true; }]) test("rejects incomplete or mismatched retained output", async () => {
  const f = fixture({ capture: change }); await assert.rejects(f.execute(), /ORDINARY_OPERATION_EVIDENCE/);
});
for (const output of [r => { r.events[0].stream = "unknown"; }, r => { r.events[0].data_b64 = "%%"; },
  r => { r.next_cursor = 0; }, r => { r.events[0].seq = 0; }, r => { r.extra = true; }])
  test("malformed live output never yields success", async () => {
    const f = fixture({ output }); await assert.rejects(f.execute(), /ORDINARY_SHELL_OUTPUT/);
    assert.equal(methods(f).filter(name => name === "start").length, 1);
  });
test("dropped live output is explicitly marked even when retained final output verifies", async () => {
  const f = fixture({ output: row => { row.dropped = true; } });
  assert.equal((await f.execute()).truncated, true); assert.equal(f.updates[0].truncated, true);
});
test("live preview remains bounded with a full chunk", async () => {
  const f = fixture({ stdout: Buffer.alloc(65536, 120) });
  await f.execute(); assert.ok(Buffer.byteLength(f.updates[0].text) <= 8192); assert.equal(f.updates[0].truncated, true);
});
test("binary output cannot expand decoded live preview past the byte bound", async () => {
  const f = fixture({ stdout: Buffer.alloc(65536, 255) });
  await f.execute(); assert.ok(Buffer.byteLength(f.updates[0].text) <= 8192);
});
for (const delayMethod of ["ordinary_shell_output", "reconcile"]) test("late " + delayMethod + " cannot turn timeout into success", async () => {
  const f = fixture({ delayMethod }); await assert.rejects(f.execute(), /ORDINARY_OPERATION_TIMEOUT/);
  assert.equal(methods(f).filter(name => name === "start").length, 1);
});
test("empty live batch cannot advance cursor without output events", async () => {
  const f = fixture({ output: row => { row.events = []; row.next_cursor = 999; } });
  await assert.rejects(f.execute(), /ORDINARY_SHELL_OUTPUT/);
});
test("final bounded display preserves observed stdout/stderr interleaving", async () => {
  const events = [["stdout", "A"], ["stderr", "B"], ["stdout", "C"]].map(([stream, value], index) =>
    ({ stream, seq: index + 1, data_b64: Buffer.from(value).toString("base64") }));
  const f = fixture({ stdout: "AC", stderr: "B", events });
  const result = await f.execute(); assert.equal(result.output, "ABC"); assert.equal(result.truncated, false);
});
test("live output mismatch cannot be accepted just because stored files verify independently", async () => {
  const f = fixture({ output: row => { row.events[0].data_b64 = Buffer.from("corrupt live output").toString("base64"); } });
  await assert.rejects(f.execute(), /ORDINARY_OPERATION_EVIDENCE/);
});
test("verified completed capture can settle with unread live events and a checked prefix", async () => {
  const f = fixture({ stdout: "prefix and retained tail", output: row => {
    if (!row.events.length) throw Error("remaining live queue must not be drained after verified termination");
    row.events[0].data_b64 = Buffer.from("prefix").toString("base64"); row.has_more = true;
  } });
  const result = await f.execute();
  assert.equal(result.exitCode, 0); assert.equal(result.stdout, "prefix and retained tail");
  assert.equal(result.output, "prefix"); assert.equal(result.truncated, true); assert.equal(result.terminationConfirmed, true);
  assert.equal(methods(f).filter(name => name === "ordinary_shell_output").length, 1);
  assert.ok(!methods(f).includes("cancel"));
});
for (const prefix of ["corrupt", "prefix longer than the final file"]) test("unread queue cannot bypass live prefix evidence: " + prefix, async () => {
  const f = fixture({ stdout: "prefix", output: row => {
    row.events[0].data_b64 = Buffer.from(prefix).toString("base64"); row.has_more = true;
  } });
  await assert.rejects(f.execute(), /ORDINARY_OPERATION_EVIDENCE/);
});
test("unread queue still requires complete capture and timely verified termination", async () => {
  const f = fixture({ output: row => { row.has_more = true; }, capture: row => { row.complete = false; } });
  await assert.rejects(f.execute(), /ORDINARY_OPERATION_EVIDENCE/);
});
test("late termination proof cannot accept an otherwise valid partial capture", async () => {
  const f = fixture({ delayMethod: "reconcile", output: row => { row.has_more = true; } });
  await assert.rejects(f.execute(), /ORDINARY_OPERATION_TIMEOUT/);
});
for (const patch of [{ lease_id: "../escape" }, { state: "prepared" }, { kind: "file" }, { tool_name: "editor" }, { timeout_seconds: 0 }])
  test("invalid ticket rejected before any RPC " + JSON.stringify(patch), async () => {
    const f = fixture(); Object.assign(f.ticket, patch); await assert.rejects(f.execute(), /ORDINARY_SHELL_TICKET/); assert.deepEqual(f.calls, []);
  });


test("slow start within the original run window does not abandon its reply at five seconds", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let release;
  const f = fixture({ timeoutSeconds: 60, beforeMethod: method => method === "start" ? new Promise(resolve => { release = resolve; }) : undefined });
  const outcome = f.execute().then(value => ({ value }), error => ({ error }));
  for (let i = 0; i < 40 && !release; i++) await Promise.resolve();
  assert.equal(typeof release, "function");
  t.mock.timers.tick(6000);
  for (let i = 0; i < 40; i++) await Promise.resolve();
  const queriedBeforeStartReply = methods(f).includes("ordinary_shell_output");
  release();
  const result = await outcome;
  assert.equal(queriedBeforeStartReply, false);
  assert.equal(result.error, undefined);
  assert.equal(result.value.terminationConfirmed, true);
  assert.equal(methods(f).filter(method => method === "start").length, 1);
});

test("abort while start reply is pending sends cancel promptly and never resends start", async t => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let release;
  const f = fixture({ timeoutSeconds: 60, beforeMethod: method => method === "start" ? new Promise(resolve => { release = resolve; }) : undefined });
  const outcome = f.execute().then(value => ({ value }), error => ({ error }));
  for (let i = 0; i < 40 && !release; i++) await Promise.resolve();
  assert.equal(typeof release, "function");
  f.signal.abort();
  for (let i = 0; i < 40; i++) await Promise.resolve();
  const canceledBeforeTimer = methods(f).includes("cancel");
  t.mock.timers.tick(6000);
  release();
  const result = await outcome;
  assert.equal(canceledBeforeTimer, true);
  assert.match(String(result.error), /ORDINARY_OPERATION_CANCELED/);
  assert.equal(methods(f).filter(method => method === "start").length, 1);
  assert.equal(methods(f).filter(method => method === "cancel").length, 1);
});
