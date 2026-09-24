import assert from "node:assert/strict";
import { test } from "node:test";
import { EventEmitter } from "node:events";
import { mkdtempSync, writeFileSync, readFileSync, statSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { externalControl } from "../external-control.ts";

async function fixture() {
  const root = mkdtempSync(join(tmpdir(), "delegate-control-")), calls = [];
  let accept;
  const server = new EventEmitter();
  server.listen = (path, ready) => { writeFileSync(path, "fake socket", { mode: 0o600 }); ready(); };
  server.close = callback => { callback?.(); };
  const owner = { instance_id: "instance", manager_activation_id: "activation", owner_nonce: "owner" };
  const bridge = { owner, async authorize(value) { assert.equal(value, owner); calls.push("authorize"); },
    async submit_batch(value, id, items) { calls.push(items); return { batch_id: id, parent_owner: owner, state: "pending", dispatch_ids: ["dispatch"], result_refs: [] }; },
    async get_batch(value, id) { return { batch_id: id, parent_owner: owner, state: "partial", dispatch_ids: ["dispatch"], result_refs: [] }; } };
  const close = await externalControl({ root, socketRoot: root, bridge, runtime: { manifest: { permission_policy: { schema_version: 1, default: "deny", rules: [] } } },
    createServer(handler) { accept = handler; return server; } });
  const record = JSON.parse(readFileSync(join(root, "control.json"), "utf8"));
  function connect() {
    const connection = new EventEmitter(); let resolve;
    connection.reply = new Promise(done => { resolve = done; });
    connection.setTimeout = () => {};
    connection.end = text => { connection.emit("close"); resolve(JSON.parse(text)); };
    connection.destroy = () => { connection.destroyed = true; connection.emit("close"); resolve(null); };
    accept(connection); return connection;
  }
  return { root, record, close, connect, calls };
}

test("private batch transport handles split UTF-8 and retains only the existing manager's batch reference", async () => {
  const f = await fixture();
  try {
    assert.equal(statSync(join(f.root, "control.json")).mode & 0o777, 0o600);
    assert.equal(statSync(join(f.record.socket, "..")).mode & 0o777, 0o700);
    const connection = f.connect();
    const frame = Buffer.from(JSON.stringify({ capability: f.record.capability, method: "submit", args: { batch_id: "batch", items: [{ task: "审查中文" }] } }) + "\n");
    for (const byte of frame) connection.emit("data", Buffer.from([byte]));
    const reply = await connection.reply;
    assert.equal(reply.ok, true); assert.equal(reply.result.state, "pending");
    assert.equal(Object.hasOwn(reply.result, "parent_owner"), false);
    assert.equal(f.calls[1][0].backend_request.task, "审查中文");
    assert.match(f.calls[1][0].idempotency_key, /^batch-[a-f0-9]{64}$/);
  } finally { await f.close(); }
  assert.equal(existsSync(join(f.root, "control.json")), false);
});

test("wrong capability, invalid UTF-8 and trailing frames cannot submit work; shutdown closes incomplete clients", async () => {
  const f = await fixture();
  try {
    const bad = f.connect(); bad.emit("data", Buffer.from(JSON.stringify({ capability: "wrong", method: "status", args: { batch_id: "batch" } }) + "\n"));
    assert.equal((await bad.reply).error, "OWNER_MISMATCH"); assert.deepEqual(f.calls, []);
    const malformed = f.connect(); malformed.emit("data", Buffer.from([0xff, 0x0a])); assert.equal(await malformed.reply, null);
    const double = f.connect(); double.emit("data", Buffer.from("{}\n{}\n")); assert.equal((await double.reply).ok, false);
    const pending = f.connect(); pending.emit("data", Buffer.from("{"));
    await f.close(); assert.equal(pending.destroyed, true); assert.deepEqual(f.calls, []);
  } finally { await f.close(); }
});
