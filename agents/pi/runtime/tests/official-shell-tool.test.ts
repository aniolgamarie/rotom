import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { createOfficialShellTool } from "../official-shell-tool.ts";

function fixture(options = {}) {
  const root = mkdtempSync(join(tmpdir(), "official-shell-tool-")), calls = [], updates = [];
  const operation = "1".repeat(32), lease = "2".repeat(32), identity = { pid: 123, start: "synthetic" };
  const ticket = { operation_id: operation, lease_id: lease, kind: "command", tool_name: "bash", write: options.write ?? true,
    state: "consumed", timeout_seconds: 1, command_ref: "tool:shell", request_digest: "a".repeat(64) };
  options.ticket?.(ticket);
  const signal = new AbortController().signal, ctx = { cwd: "/work" }, input = { command: "secret script | cat\n$(true)", timeout: 1 };
  const captured = Object.freeze({ ...input });
  const parameters = { type: "object", properties: { command: { type: "string" } } };
  const state = { original: 0, admitted: 0 };
  const save = (path, value) => {
    const target = join(root, "activity", path); mkdirSync(join(target, ".."), { recursive: true, mode: 0o700 });
    writeFileSync(target, Buffer.isBuffer(value) ? value : JSON.stringify(value), { mode: 0o600 });
  };
  const streams = {}, bodies = {};
  for (const name of ["stdout", "stderr"]) {
    let body = Buffer.from(options[name] ?? (name === "stdout" ? "synthetic output\n" : ""));
    if (options.truncated && name === "stdout" && body.length <= 1024 * 1024) body = Buffer.concat([Buffer.alloc(1024 * 1024, 0x78), body]);
    bodies[name] = body;
    const retained = body.subarray(0, 1024 * 1024);
    save("outputs/" + lease + "/" + name, retained);
    streams[name] = { path: name, bytes: retained.length, sha256: createHash("sha256").update(retained).digest("hex"), truncated: body.length > retained.length, failed: false };
  }
  save("outputs/" + lease + "/capture.json", { schema_version: 1, complete: true, truncated: Object.values(streams).some(row => row.truncated), streams });
  save("exits/" + lease + ".json", { schema_version: 1, lease_id: lease, process_identity: identity, exit_code: options.exitCode ?? 0 });
  const chunks = options.events ?? ["stdout", "stderr"].filter(name => bodies[name].length).map(name => ({ stream: name, body: bodies[name] }));
  const queued = chunks.flatMap(chunk => {
    const bytes = Buffer.from(chunk.body), rows = [];
    for (let offset = 0; offset < bytes.length; offset += 65536) rows.push({ stream: chunk.stream, data_b64: bytes.subarray(offset, offset + 65536).toString("base64") });
    return rows;
  }).map((row, index) => ({ ...row, seq: index + 1 }));
  let delivered = 0;
  const supervisor = { options: { endpoint: join(root, "activity/control/control.json") }, async call(method, args) {
    calls.push({ method, args });
    if (method === "start") return { lease_id: lease, state: "running" };
    if (method === "reconcile") return { lease_id: lease, protected: false, process_identity: identity, termination_evidence: { verified: true }, ...options.proof };
    if (method === "ordinary_shell_output") {
      const events = queued.slice(delivered, delivered + 4); delivered += events.length;
      return { events, next_cursor: delivered, dropped: false, has_more: delivered < queued.length, complete: true };
    }
    throw Error("unexpected RPC");
  } };
  const sdk = { createBashToolDefinition(cwd, factoryOptions) {
    state.factory = { cwd, options: factoryOptions };
    return { name: "bash", label: "Bash", parameters, promptSnippet: "sdk metadata", description: "sdk description", async execute() {
      state.original++; throw Error("SDK_EXECUTE_FORBIDDEN");
    } };
  } };
  const admission = { async admit(request) {
    state.admitted++; state.request = request;
    if (options.reject) throw Error("OPERATION_CANCELED");
    return { ticket, input: options.unfrozen ? { ...captured } : captured };
  } };
  const tool = createOfficialShellTool({ sdk, cwd: "/work", admission, supervisor });
  return { tool, calls, state, input, captured, parameters, ticket, sdk, supervisor, admission,
    root, execute: () => tool.execute("tool-id", input, signal, result => updates.push(result), ctx), signal, ctx, updates };
}
const text = result => result.content.map(row => row.text).join("");

test("public SDK metadata retained while original execute and fallback stay forbidden", async () => {
  const f = fixture(); assert.equal(f.tool.parameters, f.parameters); assert.equal(f.tool.label, "Bash"); assert.equal(f.tool.promptSnippet, "sdk metadata");
  assert.equal(f.state.factory.options.exposeSessionEnvironment, false);
  await assert.rejects(f.state.factory.options.operations.exec("secret", "/work", {}), /ORDINARY_SHELL_FALLBACK_FORBIDDEN/);
  const result = await f.execute(); assert.equal(f.state.original, 0); assert.equal(result.details.terminationConfirmed, true);
});
for (const write of [true, false]) test("one admission then one controlled start write=" + write, async () => {
  const f = fixture({ write }), result = await f.execute();
  assert.equal(f.state.admitted, 1); assert.deepEqual(f.state.request, { id: "tool-id", toolName: "bash", input: f.input, signal: f.signal, ctx: f.ctx });
  assert.deepEqual(f.calls.find(row => row.method === "start").args, { lease_id: f.ticket.lease_id, program: "ordinary-shell", payload: { operation_id: f.ticket.operation_id } });
  assert.equal(f.calls.filter(row => row.method === "start").length, 1); assert.equal(JSON.stringify(f.calls).includes("secret script"), false);
  assert.equal(text(result), "synthetic output\n"); assert.equal(result.isError, false);
  await assert.rejects(f.execute(), /ORDINARY_SHELL_TICKET/); assert.equal(f.calls.filter(row => row.method === "start").length, 1);
});
test("admission refusal cannot start or invoke SDK", async () => {
  const f = fixture({ reject: true }); await assert.rejects(f.execute(), /ORDINARY_|OPERATION_/); assert.equal(f.calls.length, 0); assert.equal(f.state.original, 0);
});
for (const change of [t => { t.kind = "file"; }, t => { t.tool_name = "user_bash"; }, t => { t.state = "prepared"; }, t => { t.lease_id = null; },
  t => { t.request_digest = "bad"; }, t => { t.extra = true; }, t => { t.timeout_seconds = false; }, t => { t.command_ref = "bad"; }])
  test("invalid ticket never starts", async () => {
    const f = fixture({ ticket: change }); await assert.rejects(f.execute(), /ORDINARY_SHELL_/); assert.equal(f.calls.length, 0);
  });
test("mutable captured input is refused before start", async () => {
  const f = fixture({ unfrozen: true }); await assert.rejects(f.execute(), /ORDINARY_SHELL_/); assert.equal(f.calls.length, 0);
});
test("nonzero command is a terminated error with merged bounded output", async () => {
  const f = fixture({ exitCode: 7, stdout: "中文", stderr: "failure" }), result = await f.execute();
  assert.equal(text(result), "中文failure"); assert.equal(result.isError, true); assert.equal(result.details.exitCode, 7); assert.equal(result.details.terminationConfirmed, true);
});
test("binary output is represented by replacement characters", async () => {
  const f = fixture({ stdout: Buffer.from([0xff, 0x61]) }), result = await f.execute(); assert.equal(text(result), "�a");
});
for (const retained of [false, true]) test("UTF8 final and streaming previews stay within 8192 bytes retained-truncated=" + retained, async () => {
  const f = fixture({ stdout: "中文".repeat(4000), truncated: retained }), result = await f.execute();
  assert.ok(Buffer.byteLength(text(result), "utf8") <= 8192); assert.equal(result.details.truncated, true); assert.ok(text(result).includes("truncated"));
  assert.equal(text(result).includes("�"), false);
  assert.ok(f.updates.length > 0);
  for (const update of f.updates) {
    assert.ok(Buffer.byteLength(text(update), "utf8") <= 8192); assert.equal(update.details.terminationConfirmed, false); assert.equal(update.isError, undefined);
  }
});
for (const missing of ["sdk", "admission", "supervisor"]) test("missing trusted dependency " + missing + " cannot fall back", () => {
  const f = fixture(), options = { sdk: f.sdk, cwd: "/work", admission: f.admission, supervisor: f.supervisor }; delete options[missing];
  assert.throws(() => createOfficialShellTool(options), /ORDINARY_SHELL_UNAVAILABLE/);
});
test("complete capture and exit cannot substitute for bound termination proof", async () => {
  const f = fixture({ proof: { lease_id: "foreign" } });
  await assert.rejects(f.execute(), /TERMINATION_UNKNOWN/);
  assert.equal(f.ticket.state, "unknown"); assert.equal(f.calls.filter(row => row.method === "start").length, 1);
  assert.ok(f.updates.every(row => row.details.terminationConfirmed === false));
});
test("tool creates no extra output log and returns only bounded display details", async () => {
  const f = fixture({ stdout: "x".repeat(20000) });
  const inventory = () => readdirSync(f.root, { recursive: true }).sort();
  const before = inventory(), result = await f.execute(); assert.deepEqual(inventory(), before);
  assert.deepEqual(Object.keys(result.details).sort(), ["exitCode", "terminationConfirmed", "truncated"]);
  assert.equal(JSON.stringify(result).includes("fullOutputPath"), false);
  assert.ok(text(result).length <= 8192);
});
test("source input changes cannot become a second command transfer", async () => {
  const f = fixture(); f.input.command = "mutated after capture";
  await f.execute(); assert.equal(f.captured.command, "secret script | cat\n$(true)");
  assert.equal(JSON.stringify(f.calls).includes("mutated after capture"), false);
  assert.equal(JSON.stringify(f.calls).includes("secret script"), false);
});

test("globally sequenced stdout A, stderr B, stdout C displays ABC", async () => {
  const f = fixture({ stdout: "AC", stderr: "B", events: [{ stream: "stdout", body: "A" }, { stream: "stderr", body: "B" }, { stream: "stdout", body: "C" }] });
  assert.equal(text(await f.execute()), "ABC");
  assert.equal(text(f.updates.at(-1)), "ABC");
});
test("truncated final and preview retain log tail with a leading bounded notice", async () => {
  const f = fixture({ stdout: "HEAD-MARKER\n" + "x".repeat(20000) + "\nTAIL-MARKER" });
  const result = await f.execute();
  for (const displayed of [result, ...f.updates]) {
    assert.ok(text(displayed).startsWith("[Output truncated]\n"));
    assert.ok(text(displayed).endsWith("TAIL-MARKER"));
    assert.equal(text(displayed).includes("HEAD-MARKER"), false);
    assert.ok(Buffer.byteLength(text(displayed), "utf8") <= 8192);
  }
});
test("tail trimming preserves complete Chinese characters", async () => {
  const f = fixture({ stdout: "HEAD-MARKER" + "中文".repeat(4000) + "末尾" }), result = await f.execute();
  assert.ok(text(result).endsWith("末尾")); assert.equal(text(result).includes("HEAD-MARKER"), false);
  for (const displayed of [result, ...f.updates]) {
    assert.equal(text(displayed).includes("�"), false); assert.ok(Buffer.byteLength(text(displayed), "utf8") <= 8192);
  }
});
test("binary replacement expansion remains bounded and preserves the end marker", async () => {
  const stdout = Buffer.concat([Buffer.from("HEAD-MARKER"), Buffer.alloc(15000, 0xff), Buffer.from("中文TAIL-MARKER")]);
  const f = fixture({ stdout }), result = await f.execute();
  for (const displayed of [result, ...f.updates]) {
    assert.ok(text(displayed).endsWith("中文TAIL-MARKER")); assert.ok(text(displayed).includes("�"));
    assert.equal(text(displayed).includes("HEAD-MARKER"), false); assert.ok(Buffer.byteLength(text(displayed), "utf8") <= 8192);
  }
});
