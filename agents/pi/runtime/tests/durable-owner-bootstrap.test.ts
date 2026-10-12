import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// 两个真实安装sibling放入mock harness自有TMP；不运行CLI/fd3/proc。
const directory = mkdtempSync(join(process.env.TMPDIR, "bootstrap-module-"));
const bootstrap = join(directory, "durable-owner-bootstrap.mjs"), codec = join(directory, "durable-owner-message.mjs");
writeFileSync(bootstrap, readFileSync(fileURLToPath(new URL("../durable-owner-bootstrap.ts", import.meta.url))));
writeFileSync(codec, readFileSync(fileURLToPath(new URL("../../packages/durable-service/src/owner-message.ts", import.meta.url))));
const { _createOwnerBootstrapForTests: create } = await import(pathToFileURL(bootstrap).href);
const { encodeOwnerMessageFrame: encode, decodeOwnerMessageFrame: decode } = await import(pathToFileURL(codec).href);
process.on("exit", () => rmSync(directory, { recursive: true, force: true }));
const CODE = "PI_DURABLE_OWNER_BOOTSTRAP_INVALID";
const inputs = () => ["a".repeat(64), "b".repeat(64), "30", "31", "20", "21"];
const writer = () => ({ platform: "linux", boot_id: "12345678-1234-1234-1234-123456789abc", pid: 101, ppid: 100, pgid: 101,
  start_time: "42", namespace: "pid:[123]", uid: 1002 });
function harness(options = {}) {
  const events = [], sent = [], timers = [], state = { now: 0, lock: { device: "20", inode: "21", mode: "33152", uid: "1002", gid: "100",
    nlink: "1", size: "19", mtime_ns: "20", ctime_ns: "30", close_on_exec: true, read_write: true }, writer: writer(), ...options };
  const effects = {
    lock() { assert.equal(this, effects); events.push("lock"); return state.lock; },
    writer() { assert.equal(this, effects); events.push("writer"); return state.writer; },
    write(frame, done) {
      assert.equal(this, effects); const message = decode(frame); events.push("write:" + message.type); sent.push({ frame, done, message });
      if (state.onWrite) return state.onWrite(frame, done, message.type, sent.length - 1);
      done();
    },
    close() { assert.equal(this, effects); events.push("close"); if (state.onClose) return state.onClose(); },
    now() { events.push("now"); return state.now; },
    setTimer(delay, callback) { events.push("timer"); assert.equal(delay, 10000); const handle = {}; timers.push({ callback, handle }); if (state.onTimer) state.onTimer(callback); return handle; },
    clearTimer(handle) { events.push("clear"); assert(timers.some(timer => timer.handle === handle)); if (state.onClear) return state.onClear(); },
    finish(code) { events.push("finish:" + code); if (state.onFinish) return state.onFinish(code); },
  };
  const driver = create(inputs(), effects);
  const record = { schema: 1, deployment_identity: inputs()[0], storage_identity: { device: "30", inode: "31" }, epoch: inputs()[1],
    writer: writer(), controller: { ...writer(), pid: 100, ppid: 99, pgid: 100, start_time: "41" }, stage: "bound" };
  const message = kind => ({ schema: 1, type: kind, record: { ...record, stage: kind === "close" ? "closing" : "bound" },
    lock_identity: { device: "20", inode: "21" }, fd: 3, close_on_exec: true });
  return { effects, driver, state, events, sent, timers, record, message };
}
function finished(h, code = 2) { assert.deepEqual(h.events.filter(event => event.startsWith("finish:")), ["finish:" + code]); }
function succeed(h) { h.driver.start(); h.driver.push(encode(h.message("bind"))); h.driver.push(encode(h.message("close"))); finished(h, 0); }

test("import is cold; driver constructor is pure and its entrypoints are frozen", () => {
  const h = harness(); assert.deepEqual(h.events, []); assert(Object.isFrozen(h.driver));
  assert.deepEqual(Object.keys(h.driver), ["start", "push", "end"]);
});
test("three original sends and one close finish without any retired-lock reinspection", () => {
  const h = harness(); succeed(h);
  assert.deepEqual(h.events.filter(event => /^(write:|close$|finish:)/.test(event)), ["write:hello", "write:bound", "close", "write:closed", "finish:0"]);
  assert.equal(h.sent[2].message.descriptor_closed, true);
  assert(!h.events.slice(h.events.indexOf("close") + 1).includes("lock"));
  assert.equal(h.timers.length, 3); assert.equal(h.events.filter(event => event === "clear").length, 3);
});
test("early candidates cannot advance before the original write returns after callback", () => {
  const h = harness();
  h.state.onWrite = (_frame, done, kind) => {
    if (kind === "hello") { h.driver.push(encode(h.message("bind"))); done(); assert.equal(h.sent.length, 1); }
    else if (kind === "bound") { h.driver.push(encode(h.message("close"))); done(); assert.equal(h.sent.length, 2); }
    else done();
  };
  assert.equal(h.driver.start(), undefined); finished(h, 0); assert.equal(h.sent.length, 3);
});
test("asynchronous receipts retain one candidate and consume only after its original callback", () => {
  const h = harness({ onWrite() {} }); h.driver.start(); h.driver.push(encode(h.message("bind")));
  assert.equal(h.sent.length, 1); h.sent[0].done(); assert.equal(h.sent.length, 2);
  h.driver.push(encode(h.message("close"))); assert.equal(h.sent.length, 2); h.sent[1].done();
  assert.equal(h.sent.length, 3); assert(!h.events.includes("finish:0")); h.sent[2].done(); finished(h, 0);
});
for (const position of [0, 1, 2, 3, 4, 5]) test("scalar " + position + " rejects noncanonical input before effects", () => {
  for (const value of [null, 1, new String("1"), position < 2 ? "A".repeat(64) : "01", position < 2 ? "a".repeat(65) : "18446744073709551616"]) {
    const h = harness(); const values = inputs(); values[position] = value;
    assert.throws(() => create(values, h.effects), error => error.message === CODE); assert.deepEqual(h.events, []);
  }
});
test("input proxies/getters/symbols/prototypes and effect proxies never trigger foreign callbacks", () => {
  let calls = 0; const h = harness(); const values = inputs();
  Object.defineProperty(values, "0", { get() { calls++; return "a".repeat(64); }, enumerable: true });
  const proxy = new Proxy(inputs(), { get() { calls++; }, ownKeys() { calls++; return []; } });
  const symbol = inputs(); symbol[Symbol("foreign")] = "x";
  const proto = inputs(); Object.setPrototypeOf(proto, {});
  for (const value of [values, proxy, symbol, proto]) assert.throws(() => create(value, h.effects), error => error.message === CODE);
  const effects = new Proxy(h.effects, { ownKeys() { calls++; return []; } });
  assert.throws(() => create(inputs(), effects), error => error.message === CODE); assert.equal(calls, 0); assert.deepEqual(h.events, []);
});
test("effect getters/symbols/unknown fields/nonfunction and proxy functions are pure rejections", () => {
  let calls = 0;
  for (const kind of ["getter", "symbol", "unknown", "number", "proxy-function"]) {
    const h = harness(); const effects = { ...h.effects };
    if (kind === "getter") Object.defineProperty(effects, "lock", { get() { calls++; }, enumerable: true });
    else if (kind === "symbol") effects[Symbol("extra")] = () => {};
    else if (kind === "unknown") effects.extra = () => {};
    else if (kind === "number") effects.now = 1;
    else effects.lock = new Proxy(() => {}, { apply() { calls++; } });
    assert.throws(() => create(inputs(), effects), error => error.message === CODE); assert.deepEqual(h.events, []);
  }
  assert.equal(calls, 0);
});
for (const field of ["device", "inode", "mode", "uid", "gid", "nlink", "size", "mtime_ns", "ctime_ns", "close_on_exec", "read_write"]) test("lock rejects " + field + " before writer or hello", () => {
  const h = harness(); h.state.lock[field] = field.endsWith("ns") ? "-0" : field === "close_on_exec" || field === "read_write" ? false : "01";
  h.driver.start(); finished(h); assert.equal(h.sent.length, 0); assert(!h.events.includes("writer")); assert(!h.events.includes("close"));
});
test("nonempty lock and canonical signed times/u64 upper endpoints are legitimate metadata", () => {
  const h = harness(); h.state.lock.size = "18446744073709551615"; h.state.lock.mtime_ns = "-9223372036854775808"; h.state.lock.ctime_ns = "9223372036854775807"; succeed(h);
});
for (const drift of ["lock", "writer"]) test("post-write " + drift + " drift blocks early bind advancement", () => {
  const h = harness(); h.state.onWrite = (_frame, done, kind) => {
    if (kind === "hello") { h.driver.push(encode(h.message("bind"))); done(); if (drift === "lock") h.state.lock = { ...h.state.lock, ctime_ns: "31" }; else h.state.writer = { ...h.state.writer, start_time: "43" }; }
  };
  h.driver.start(); finished(h); assert.equal(h.sent.length, 1); assert(!h.events.includes("close"));
});
test("effect drift cleanup uses captured clearTimer and finish, never replacement functions", () => {
  const h = harness(); let foreign = 0;
  h.state.onWrite = (_frame, done) => { done(); h.effects.clearTimer = () => foreign++; h.effects.finish = () => foreign++; };
  h.driver.start(); finished(h); assert.equal(foreign, 0); assert.equal(h.events.filter(event => event === "clear").length, 1);
});
test("frame mutation fails postpure before consuming an early candidate", () => {
  const h = harness(); h.state.onWrite = (frame, done) => { h.driver.push(encode(h.message("bind"))); done(); frame[4] ^= 1; };
  h.driver.start(); finished(h); assert.equal(h.sent.length, 1);
});
for (const field of ["parent", "namespace", "deployment", "epoch", "storage", "writer"]) test("bind " + field + " mismatch fails closed", () => {
  const h = harness(); h.driver.start(); const message = h.message("bind");
  if (field === "parent") message.record.controller.pid = 99;
  else if (field === "namespace") message.record.controller.namespace = "pid:[124]";
  else if (field === "deployment") message.record.deployment_identity = "c".repeat(64);
  else if (field === "epoch") message.record.epoch = "c".repeat(64);
  else if (field === "storage") message.record.storage_identity = { device: "30", inode: "32" };
  else message.record.writer = { ...message.record.writer, start_time: "43" };
  h.driver.push(encode(message)); finished(h); assert.equal(h.sent.length, 1);
});
test("framing fragmented header/payload uses independent caller bytes", () => {
  const h = harness(); h.driver.start(); const frame = encode(h.message("bind"));
  h.driver.push(frame.subarray(0, 2)); const part = frame.subarray(2, 9); h.driver.push(part); part.fill(0);
  h.driver.push(frame.subarray(9)); assert.equal(h.sent.length, 2); h.driver.push(encode(h.message("close"))); finished(h, 0);
});
for (const fault of ["zero", "oversize-header", "oversize-chunk", "tail", "two-frames", "wrong-order", "EOF", "duplicate-candidate"]) test("framing " + fault + " permanently stops", () => {
  const h = harness({ onWrite() {} }); h.driver.start(); const valid = encode(h.message("bind"));
  if (fault === "zero") h.driver.push(new Uint8Array(4));
  else if (fault === "oversize-header") h.driver.push(new Uint8Array([0, 0, 16, 1]));
  else if (fault === "oversize-chunk") h.driver.push(new Uint8Array(4102));
  else if (fault === "tail") h.driver.push(Buffer.concat([valid, Buffer.from([0])]));
  else if (fault === "two-frames") h.driver.push(Buffer.concat([valid, valid]));
  else if (fault === "wrong-order") h.driver.push(encode(h.message("close")));
  else if (fault === "EOF") h.driver.end();
  else { h.driver.push(valid); h.driver.push(valid); }
  finished(h); assert.equal(h.sent.length, 1); assert(!h.events.includes("close"));
});
for (const kind of ["hello", "bound", "closed"]) test(kind + " missing receipt times out once", () => {
  const h = harness(); h.state.onWrite = (_frame, done, current) => { if (current !== kind) done(); };
  h.driver.start(); if (kind !== "hello") h.driver.push(encode(h.message("bind"))); if (kind === "closed") h.driver.push(encode(h.message("close")));
  h.timers.at(-1).callback(); finished(h); const count = h.sent.length; h.sent.at(-1).done(); h.driver.end(); h.driver.start(); h.driver.push(new Uint8Array(1)); assert.equal(h.sent.length, count);
});
for (const kind of ["callback-error", "double-callback", "callback-then-throw", "return-value"]) test("write " + kind + " never commits early candidate", () => {
  const h = harness(); let reads = 0; const foreign = new Proxy({}, { get() { reads++; throw Error("foreign"); } });
  h.state.onWrite = (_frame, done) => {
    h.driver.push(encode(h.message("bind")));
    if (kind === "callback-error") done(foreign);
    else if (kind === "double-callback") { done(); done(); }
    else if (kind === "callback-then-throw") { done(); throw foreign; }
    else { done(); return foreign; }
  };
  h.driver.start(); finished(h); assert.equal(h.sent.length, 1); assert.equal(reads, 0);
});
test("close exception retires fd once, does not send closed and never retries", () => {
  const h = harness({ onClose() { throw Error("private close text"); } }); h.driver.start(); h.driver.push(encode(h.message("bind"))); h.driver.push(encode(h.message("close")));
  finished(h); assert.equal(h.sent.length, 2); const events = h.events.slice(); h.driver.push(encode(h.message("close"))); h.driver.end(); assert.deepEqual(h.events, events); assert.equal(events.filter(event => event === "close").length, 1);
});
test("close fullname mismatch and bytes during closed-send cannot create success ACK", () => {
  const h = harness(); h.driver.start(); h.driver.push(encode(h.message("bind"))); const message = h.message("close"); message.record.epoch = "c".repeat(64); h.driver.push(encode(message)); finished(h); assert(!h.events.includes("close"));
  const second = harness(); second.state.onWrite = (_frame, done, kind) => { if (kind === "closed") second.driver.push(new Uint8Array([0])); done(); };
  second.driver.start(); second.driver.push(encode(second.message("bind"))); second.driver.push(encode(second.message("close"))); finished(second); assert.equal(second.sent.length, 3);
});
for (const value of [NaN, Infinity, -1, -0]) test("invalid clock " + String(value) + " fails before timer/send", () => {
  const h = harness({ now: value }); h.driver.start(); finished(h); assert.equal(h.sent.length, 0);
});
test("backward and deadline clocks stop; synchronous timer waits only to cancel returned handle", () => {
  const h = harness(); h.driver.start(); h.state.now = -1; h.driver.push(encode(h.message("bind"))); finished(h);
  const deadline = harness(); deadline.driver.start(); deadline.state.now = 10000; deadline.driver.push(encode(deadline.message("bind"))); finished(deadline);
  const sync = harness({ onTimer(callback) { callback(); } }); sync.driver.start(); finished(sync); assert.equal(sync.sent.length, 0); assert.equal(sync.events.filter(event => event === "clear").length, 1);
});
test("cleanup clear failure still calls captured finish; finish throws only once", () => {
  const h = harness({ onClear() { throw Error("private clear"); }, onFinish() { throw Error("private finish"); } }); h.driver.start(); h.driver.end(); finished(h); h.driver.end(); assert.equal(h.events.filter(event => event === "clear").length, 1);
});
test("finished success ignores all late entries and old timer/callbacks without new effects", () => {
  const h = harness(); succeed(h); const events = h.events.slice();
  h.driver.start(); h.driver.push(new Proxy({}, { get() { throw Error("late getter"); } })); h.driver.end();
  for (const timer of h.timers) timer.callback(); for (const sent of h.sent) sent.done(); assert.deepEqual(h.events, events);
});
