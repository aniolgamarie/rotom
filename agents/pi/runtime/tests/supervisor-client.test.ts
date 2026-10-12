import assert from "node:assert/strict";
import { test } from "node:test";
import { SupervisorClient } from "../supervisor-client.ts";
import { mkdtempSync, mkdirSync, openSync, closeSync, chmodSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const options = { python: "/fixture/python", client: "/fixture/pi-control.py", endpoint: "/fixture/control.json", capability: "private-fixture-capability" };

test("private directory binding stays outside request and rejects fd reuse before transport", async t => {
  const root = mkdtempSync(join(tmpdir(), "control-fd-")), second = join(root, "second"); mkdirSync(second, { mode: 0o700 });
  let fd = openSync(root, "r"), calls = 0;
  t.after(() => { closeSync(fd); rmSync(root, { recursive: true, force: true }); });
  const client = new SupervisorClient({ ...options, directoryFd: fd, invoke: async value => {
    calls++; assert.equal(value.directoryFd, fd);
    assert.equal(Object.hasOwn(value.request, "directoryFd"), false);
    return '{"schema_version":1,"ok":true,"result":{"valid":true}}';
  } });
  assert.deepEqual(await client.call("handshake", {}), { valid: true });
  const original = fd; closeSync(fd); fd = openSync(second, "r"); assert.equal(fd, original);
  await assert.rejects(client.call("handshake", {}), error => error.code === "PI_CONTROL_UNAVAILABLE");
  assert.equal(calls, 1);
});

test("wrong directory mode and late descriptor change cannot publish accepted response", async t => {
  const root = mkdtempSync(join(tmpdir(), "control-fd-")); let fd = openSync(root, "r");
  t.after(() => { closeSync(fd); rmSync(root, { recursive: true, force: true }); });
  chmodSync(root, 0o755);
  assert.throws(() => new SupervisorClient({ ...options, directoryFd: fd }), error => error.code === "PI_CONTROL_UNAVAILABLE");
  chmodSync(root, 0o700);
  let calls = 0;
  const client = new SupervisorClient({ ...options, directoryFd: fd, invoke: async () => {
    calls++; chmodSync(root, 0o755);
    return '{"schema_version":1,"ok":true,"result":{"valid":true}}';
  } });
  await assert.rejects(client.call("handshake", {}), error => error.code === "PI_CONTROL_UNAVAILABLE");
  assert.equal(calls, 1);
});

test("control messages use a separate trusted capability and preserve literal arguments", async () => {
  const calls = [];
  const client = new SupervisorClient({ ...options, invoke: async value => {
    calls.push(value);
    return JSON.stringify({ schema_version: 1, ok: true, result: { state: "running" } });
  } });
  assert.deepEqual(await client.call("start", { lease_id: "lease", program: "worker", payload: { literal: "a b" } }), { state: "running" });
  assert.equal(calls[0].request.args.payload.literal, "a b");
  assert.equal(Object.hasOwn(calls[0].request, "capability"), false);
  assert.equal(calls[0].capability, options.capability);
});

test("oversize requests and private child errors never turn into accepted control", async () => {
  let calls = 0;
  const client = new SupervisorClient({ ...options, invoke: async () => { calls++; throw Error("synthetic secret transport output"); } });
  await assert.rejects(client.call("start", { body: "a".repeat(1024 * 1024) }), /PI_CONTROL_FRAME_LIMIT/);
  assert.equal(calls, 0);
  await assert.rejects(client.call("inspect", { lease_id: "lease" }), error => error.code === "PI_CONTROL_UNAVAILABLE" && !String(error).includes("secret"));
  const malformed = new SupervisorClient({ ...options, invoke: async () => '{"schema_version":1,"ok":true,"result":{},"unknown":true}' });
  await assert.rejects(malformed.call("inspect", { lease_id: "lease" }), /PROTOCOL_INVALID/);
});

test("Codex admission shows only fixed safe reason codes", async () => {
  for (const reason of ["CODEX_SYSTEM_CONFIG_PRESENT", "CODEX_ACCOUNT_CONFIG_UNVERIFIED", "synthetic private token", { secret: "private" }]) {
    const client = new SupervisorClient({ ...options, invoke: async () => JSON.stringify({ schema_version: 1, ok: false, exit_code: 5, error: reason }) });
    await assert.rejects(client.call("start", {}), error => error.code === (typeof reason === "string" && reason.startsWith("CODEX_") ? reason : "PI_CONTROL_REJECTED"));
  }
});

test("confirmed zero-write backpressure remains distinguishable from unknown pipe failure", async () => {
  for (const reason of ["ORDINARY_STDIN_BACKPRESSURE", "ORDINARY_STDIN_UNKNOWN"]) {
    const client = new SupervisorClient({ ...options, invoke: async () => JSON.stringify({ schema_version: 1, ok: false, exit_code: 4, error: reason }) });
    await assert.rejects(client.call("ordinary_command_stdin", {}), error => error.code === (reason === "ORDINARY_STDIN_BACKPRESSURE" ? reason : "PI_CONTROL_REJECTED"));
  }
});

test("policy deny remains distinct while arbitrary rejection details stay private", async () => {
  for (const reason of ["PERMISSION_DENIED", "PERMISSION_DENIED private synthetic marker", "PI_CONTROL_REJECTED"]) {
    const client = new SupervisorClient({ ...options, invoke: async () => JSON.stringify({ schema_version: 1, ok: false, exit_code: 4, error: reason }) });
    await assert.rejects(client.call("ordinary_admission_prepare", {}), error =>
      error.code === (reason === "PERMISSION_DENIED" ? reason : "PI_CONTROL_REJECTED") && !String(error).includes("private synthetic marker"));
  }
});
