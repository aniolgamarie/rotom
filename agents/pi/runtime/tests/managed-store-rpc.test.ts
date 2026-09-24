import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { ManagedStore } from "../managed-store.ts";
import { ManagedBridge } from "../managed-bridge.ts";
import { ManagedClient, registerManagedRpc } from "../managed-rpc.ts";
import { descriptor, fixture } from "./fixtures.ts";

function bus() {
  const emitter = new EventEmitter();
  return { emit: (key, data) => emitter.emit(key, data), on(key, fn) { emitter.on(key, fn); return () => emitter.off(key, fn); } };
}

test("durable dispatch survives reopening without executing again after lost acknowledgment", async () => {
  const f = fixture(), root = mkdtempSync(join(tmpdir(), "managed-store-"));
  let store = new ManagedStore({ root, owner: f.owner, authorize: async () => {} });
  assert.throws(() => new ManagedStore({ root, owner: f.owner, authorize: async () => {} }), /ALREADY_OPEN/);
  const bridge = new ManagedBridge({ ...f.bridge, store });
  let count = 0;
  bridge.executor = { ...f.executor, async dispatch() {
    count++;
    assert.equal(Object.values(JSON.parse(readFileSync(store.path, "utf8")).state.runs)[0].state, "starting");
    throw Error("lost response");
  } };
  const value = descriptor(), admission = await bridge.preflight(value);
  const request = { descriptor: value, admission_token: admission.admission_token, idempotency_key: "one" };
  const first = await bridge.dispatch(request);
  assert.equal(first.state, "start_unknown");
  await store.close();
  store = new ManagedStore({ root, owner: f.owner, authorize: async () => {} });
  bridge.store = store;
  assert.deepEqual(await bridge.dispatch(request), first);
  assert.equal(count, 1);
  await store.close();
});

test("serialized transactions roll back exceptions and reject corrupt state without reset", async () => {
  const f = fixture(), root = mkdtempSync(join(tmpdir(), "managed-store-"));
  const store = new ManagedStore({ root, owner: f.owner, authorize: async () => {} });
  await Promise.all(Array.from({ length: 12 }, () => store.transaction(async state => { const n = state.count ?? 0; await Promise.resolve(); state.count = n + 1; })));
  await assert.rejects(store.transaction(state => { state.count = 900; throw Error("fixture"); }));
  await store.transaction(state => assert.equal(state.count, 12));
  const path = store.path;
  await store.close();
  writeFileSync(path, "broken");
  assert.throws(() => new ManagedStore({ root, owner: f.owner, authorize: async () => {} }), /STORE_CORRUPT/);
  assert.equal(readFileSync(path, "utf8"), "broken");
});

test("RPC has one listener, closed arguments, attempt cancellation and no raw errors", async () => {
  const f = fixture(), events = bus(), client = new ManagedClient(events);
  await assert.rejects(client.call("handshake", { protocol_version: 1, instance_id: "instance", request_id: "hello" }), /LISTENER_CONFLICT/);
  const off = registerManagedRpc(events, f.bridge);
  assert.throws(() => registerManagedRpc(events, f.bridge), /LISTENER_CONFLICT/);
  const reply = await client.call("handshake", { protocol_version: 1, instance_id: "instance", request_id: "hello" });
  assert.equal(reply.manager_activation_id, "manager");
  const value = descriptor();
  const admission = await client.call("preflight", { descriptor: value });
  const run = await client.call("dispatch", { descriptor: value, admission_token: admission.admission_token, idempotency_key: "one" });
  assert.equal(run.attempt_id, value.attempt_id);
  assert.equal((await client.call("cancel", { owner: f.owner, attempt_id: value.attempt_id, reason: "user" })).termination_confirmed, false);
  await assert.rejects(client.call("inspect", { owner: f.owner, manager_run_id: run.manager_run_id, bypassQueue: true }), /PROTOCOL_INVALID/);
  f.bridge.resolve = () => { throw Error("synthetic private detail"); };
  await assert.rejects(client.call("preflight", { descriptor: value }), /MANAGED_OPERATION_FAILED/);
  off();
});

test("protocol errors preserve safe codes across frozen launcher and package module copies", async () => {
  const foreign = await import("../managed-types.ts?independent-package-copy");
  const { ProtocolError } = await import("../managed-types.ts");
  const failure = new foreign.ProtocolError("CREDENTIAL_MISSING", 3);
  assert.equal(failure instanceof ProtocolError, false);
  const events = bus(), client = new ManagedClient(events);
  const off = registerManagedRpc(events, { handshake() { throw failure; } });
  try {
    await assert.rejects(client.call("handshake", { protocol_version: 1, instance_id: "instance", request_id: "hello" }),
      error => error.code === "CREDENTIAL_MISSING" && error.exitCode === 3);
  } finally { off(); }
});
