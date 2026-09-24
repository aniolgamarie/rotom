import assert from "node:assert/strict";
import { test } from "node:test";
import { SupervisorClient } from "../supervisor-client.ts";

const options = { python: "/fixture/python", client: "/fixture/pi-control.py", endpoint: "/fixture/control.json", capability: "private-fixture-capability" };

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
