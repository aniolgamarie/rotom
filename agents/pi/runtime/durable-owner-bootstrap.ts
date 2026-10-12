// 零SDK首包；fd/stat/回执只是观察，不签同OFD、EX锁、来源或初始化资格。
import fs from "node:fs";
import { types } from "node:util";
import { performance } from "node:perf_hooks";
import { fileURLToPath } from "node:url";
import { captureOwnerMessage, encodeOwnerMessageFrame, decodeOwnerMessageFrame } from "./durable-owner-message.mjs";

const CODE = "PI_DURABLE_OWNER_BOOTSTRAP_INVALID", apply = Reflect.apply;
const objectPrototype = Object.prototype, arrayPrototype = Array.prototype;
const Bytes = Uint8Array, bytesPrototype = Uint8Array.prototype, bufferPrototype = Buffer.prototype;
const typed = Object.getPrototypeOf(bytesPrototype), setBytes = typed.set;
const lengthGetter = Object.getOwnPropertyDescriptor(typed, "byteLength").get;
const offsetGetter = Object.getOwnPropertyDescriptor(typed, "byteOffset").get;
const bufferGetter = Object.getOwnPropertyDescriptor(typed, "buffer").get;
const capacityGetter = Object.getOwnPropertyDescriptor(ArrayBuffer.prototype, "byteLength").get;
const NAMES = ["lock", "writer", "write", "close", "now", "setTimer", "clearTimer", "finish"];
const STAT = ["device", "inode", "mode", "uid", "gid", "nlink", "size", "mtime_ns", "ctime_ns"];
const U64 = 18446744073709551615n, U32 = 4294967295n;
function invalid() { throw new Error(CODE); }
function decimal(value, maximum = U64, positive = false, signed = false) {
  if (typeof value !== "string" || value.length > 20 || value.length === 0) invalid();
  const match = (signed ? /^-?(0|[1-9][0-9]*)$/ : /^(0|[1-9][0-9]*)$/).exec(value);
  if (!match || match[0] !== value || value === "-0") invalid();
  const number = BigInt(value);
  if (signed ? number < -9223372036854775808n || number > 9223372036854775807n : number > maximum || positive && number === 0n) invalid();
  return value;
}
function scalars(value) {
  if (!Array.isArray(value) || types.isProxy(value) || Object.getPrototypeOf(value) !== arrayPrototype) invalid();
  const keys = Reflect.ownKeys(value);
  if (keys.length !== 7 || keys.some(key => typeof key !== "string" || !["0", "1", "2", "3", "4", "5", "length"].includes(key))) invalid();
  const size = Object.getOwnPropertyDescriptor(value, "length");
  if (!size || size.value !== 6) invalid();
  const result = [];
  for (let index = 0; index < 6; index++) {
    const descriptor = Object.getOwnPropertyDescriptor(value, String(index));
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value") || typeof descriptor.value !== "string") invalid();
    result.push(descriptor.value);
  }
  for (const value of result.slice(0, 2)) if (value.length !== 64 || !/^[0-9a-f]{64}$/.test(value)) invalid();
  decimal(result[2]); decimal(result[3], U64, true); decimal(result[4]); decimal(result[5], U64, true);
  return Object.freeze(result);
}
function table(value, names) {
  if (!value || typeof value !== "object" || types.isProxy(value)) invalid();
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== objectPrototype && prototype !== null) invalid();
  const keys = Reflect.ownKeys(value);
  if (keys.length !== names.length || keys.some(key => typeof key !== "string" || !names.includes(key))) invalid();
  const descriptors = Object.create(null);
  for (const name of names) {
    const descriptor = Object.getOwnPropertyDescriptor(value, name);
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) invalid();
    descriptors[name] = descriptor;
  }
  return { prototype, descriptors };
}
function equivalent(left, right) {
  if (left === right) return true;
  if (!left || !right || typeof left !== "object" || typeof right !== "object") return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every(key => Object.hasOwn(right, key) && equivalent(left[key], right[key]));
}
function lockObservation(value, input) {
  const captured = table(value, [...STAT, "close_on_exec", "read_write"]), result = Object.create(null);
  for (const name of STAT) result[name] = captured.descriptors[name].value;
  for (const name of STAT.slice(0, 7)) decimal(result[name], ["mode", "uid", "gid"].includes(name) ? U32 : U64, ["inode", "nlink"].includes(name));
  decimal(result.mtime_ns, U64, false, true); decimal(result.ctime_ns, U64, false, true);
  if (result.mode !== "33152" || result.nlink !== "1" || result.device !== input[4] || result.inode !== input[5]
      || captured.descriptors.close_on_exec.value !== true || captured.descriptors.read_write.value !== true) invalid();
  return Object.freeze(result);
}
function chunk(value) {
  if (!value || typeof value !== "object" || types.isProxy(value) || !types.isUint8Array(value)) invalid();
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== bytesPrototype && prototype !== bufferPrototype) invalid();
  const size = apply(lengthGetter, value, []), offset = apply(offsetGetter, value, []), buffer = apply(bufferGetter, value, []);
  if (!Number.isSafeInteger(size) || size > 4101 || offset + size > apply(capacityGetter, buffer, [])) invalid();
  const copy = new Bytes(size); apply(setBytes, copy, [value]); return copy;
}

export function _createOwnerBootstrapForTests(values, effects) {
  try {
    const input = scalars(values), saved = table(effects, NAMES), functions = Object.create(null);
    for (const name of NAMES) {
      const value = saved.descriptors[name].value;
      if (typeof value !== "function" || types.isProxy(value)) invalid();
      functions[name] = value;
    }
    let started = false, finished = false, retired = false, closeAttempted = false, finishAttempted = false;
    let lock = null, writer = null, bound = null, window = null, candidate = null, sending = null;
    let lastTime = null, deadline = null, timer = null, header = new Bytes(4), used = 0, frame = null;
    function guard() {
      const current = table(effects, NAMES);
      if (current.prototype !== saved.prototype) invalid();
      for (const name of NAMES) {
        const a = saved.descriptors[name], b = current.descriptors[name];
        if (b.value !== functions[name] || a.writable !== b.writable || a.configurable !== b.configurable) invalid();
      }
    }
    function cleanupTimer() {
      if (!timer || timer.cleared) return;
      timer.cancel = true;
      if (!timer.known) return;
      timer.cleared = true;
      try { apply(functions.clearTimer, effects, [timer.handle]); } catch {}
    }
    function fail() {
      if (finished) return;
      finished = true; window = null; candidate = null; sending = null;
      // 故障cleanup有意不重查漂移table，只调用初次captured函数各一次。
      cleanupTimer();
      if (!finishAttempted) { finishAttempted = true; try { apply(functions.finish, effects, [2]); } catch {} }
    }
    function run(action) { if (finished) return; try { action(); } catch { fail(); } }
    function invoke(name, args = []) {
      if (finished) invalid(); guard();
      const value = apply(functions[name], effects, args);
      if (finished) invalid(); guard(); return value;
    }
    function time() {
      const value = invoke("now");
      if (typeof value !== "number" || !Number.isFinite(value) || Object.is(value, -0) || value < 0 || lastTime !== null && value < lastTime) invalid();
      lastTime = value; return value;
    }
    function within() { if (deadline !== null && time() >= deadline) invalid(); }
    function sources() {
      if (!retired) {
        const observation = lockObservation(invoke("lock"), input);
        if (lock && !equivalent(lock, observation)) invalid();
        lock = observation;
      }
      const observation = captureOwnerMessage({ schema: 1, type: "hello", writer: invoke("writer"), lock_identity: { device: input[4], inode: input[5] }, fd: 3, close_on_exec: true }).writer;
      if (String(observation.uid) !== lock.uid || writer && !equivalent(writer, observation)) invalid();
      writer = observation;
    }
    function clearNormalTimer() {
      if (!timer || timer.cleared) return;
      if (!timer.known || finished) invalid(); guard(); timer.cleared = true;
      const value = apply(functions.clearTimer, effects, [timer.handle]);
      if (finished) invalid(); guard(); if (value !== undefined) invalid();
    }
    function arm() {
      clearNormalTimer(); deadline = time() + 10000;
      if (!Number.isFinite(deadline)) invalid();
      const current = { known: false, cleared: false, cancel: false, handle: null }; timer = current;
      guard();
      const handle = apply(functions.setTimer, effects, [10000, () => { if (finished || timer !== current || current.cleared) return; fail(); }]);
      current.handle = handle; current.known = true;
      if (finished || current.cancel) { cleanupTimer(); invalid(); }
      guard();
    }
    function reset(next) { window = next; candidate = null; used = 0; frame = null; header = new Bytes(4); }
    function expected(message) {
      if (message.lock_identity.device !== input[4] || message.lock_identity.inode !== input[5]) invalid();
      if (window === "bind") {
        if (message.type !== "bind" || !equivalent(message.record.writer, writer) || message.record.controller.pid !== writer.ppid
            || message.record.controller.boot_id !== writer.boot_id || message.record.controller.namespace !== writer.namespace || message.record.controller.uid !== writer.uid
            || message.record.deployment_identity !== input[0] || message.record.epoch !== input[1]
            || message.record.storage_identity.device !== input[2] || message.record.storage_identity.inode !== input[3]) invalid();
      } else if (window === "close") {
        if (message.type !== "close" || !equivalent(message.record, { ...bound, stage: "closing" })) invalid();
      } else invalid();
    }
    function complete() {
      clearNormalTimer(); guard(); finished = true; window = null;
      if (finishAttempted) invalid(); finishAttempted = true;
      try { if (apply(functions.finish, effects, [0]) !== undefined) invalid(); guard(); } catch { /* 不重试已请求的finish。 */ }
    }
    function consume() {
      if (!candidate || sending && !sending.settled) return;
      within(); expected(candidate); sources();
      const message = candidate, kind = window; candidate = null; window = null;
      if (kind === "bind") {
        bound = message.record;
        send({ schema: 1, type: "bound", record: bound, lock_identity: message.lock_identity, fd: 3, close_on_exec: true }, "close");
      } else {
        if (closeAttempted || retired) invalid();
        retired = true; closeAttempted = true;
        if (invoke("close") !== undefined) invalid();
        send({ schema: 1, type: "closed", record: message.record, lock_identity: message.lock_identity, fd: 3, descriptor_closed: true }, null);
      }
    }
    function send(message, next) {
      sources(); arm(); reset(next);
      const bytes = encodeOwnerMessageFrame(message), gate = { done: false, returned: false, settled: false }; sending = gate;
      function settle() {
        if (finished || gate.settled || !gate.done || !gate.returned) return;
        // 原发送回执、原调用正常返回、来源及自有frame的postpure都通过才推进。
        if (!equivalent(decodeOwnerMessageFrame(bytes), captureOwnerMessage(message))) invalid();
        within(); sources(); gate.settled = true;
        if (next === null) complete(); else consume();
      }
      guard();
      const returned = apply(functions.write, effects, [bytes, error => run(() => {
        if (gate.done || error !== undefined && error !== null) invalid();
        gate.done = true; settle();
      })]);
      if (finished) invalid(); guard();
      if (returned !== undefined) invalid(); gate.returned = true; settle();
    }
    return Object.freeze({
      start() { run(() => {
        if (started) invalid(); started = true; sources();
        send({ schema: 1, type: "hello", writer, lock_identity: { device: input[4], inode: input[5] }, fd: 3, close_on_exec: true }, "bind");
      }); },
      push(value) { run(() => {
        if (!started || window === null || candidate) invalid(); within();
        const bytes = chunk(value);
        if (used + bytes.length > 4101) invalid();
        for (let index = 0; index < bytes.length; index++) {
          if (used < 4) {
            header[used++] = bytes[index];
            if (used === 4) {
              const size = header[0] * 16777216 + header[1] * 65536 + header[2] * 256 + header[3];
              if (size < 1 || size > 4096) invalid();
              frame = new Bytes(size + 4); apply(setBytes, frame, [header]);
            }
          } else {
            if (used >= frame.length) invalid(); frame[used++] = bytes[index];
          }
          if (frame && used === frame.length) {
            if (index !== bytes.length - 1) invalid();
            candidate = decodeOwnerMessageFrame(frame); expected(candidate);
          }
        }
        if (candidate) consume();
      }); },
      end() { run(() => { invalid(); }); },
    });
  } catch { invalid(); }
}

// 捕获公共builtins；import本身不执行fd/proc/stream/timer操作。
const fstat = fs.fstatSync, open = fs.openSync, read = fs.readSync, close = fs.closeSync, readlink = fs.readlinkSync;
const now = performance.now, setTimer = globalThis.setTimeout, clearTimer = globalThis.clearTimeout;
const getuid = process.getuid, exit = process.exit;
function boundedProc(path, cap) {
  const fd = open(path, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
  try {
    const bytes = new Bytes(cap + 1); let count = 0;
    while (count <= cap) { const amount = read(fd, bytes, count, cap + 1 - count, null); if (!amount) break; count += amount; }
    if (count > cap) invalid(); return new TextDecoder("utf-8", { fatal: true }).decode(bytes.subarray(0, count));
  } finally { close(fd); }
}
function _main() {
  try {
    if (process.platform !== "linux" || process.arch !== "x64") invalid();
    const input = scalars(process.argv.slice(2));
    let stdout = null, stdoutWrite = null;
    function observeLock() {
      const before = fstat(3, { bigint: true }), uid = apply(getuid, process, []);
      if (before.mode !== 33152n || before.nlink !== 1n || before.uid !== BigInt(uid) || String(before.dev) !== input[4] || String(before.ino) !== input[5]) invalid();
      const fdinfo = boundedProc("/proc/self/fdinfo/3", 4096), matches = [...fdinfo.matchAll(/^flags:[ \t]+([0-7]{1,22})$/gm)];
      if (matches.length !== 1) invalid(); const flags = BigInt("0o" + matches[0][1]);
      if ((flags & 0o2000000n) === 0n || (flags & 3n) !== 2n) invalid();
      const after = fstat(3, { bigint: true });
      const snapshot = value => ({ device: String(value.dev), inode: String(value.ino), mode: String(value.mode), uid: String(value.uid), gid: String(value.gid),
        nlink: String(value.nlink), size: String(value.size), mtime_ns: String(value.mtimeNs), ctime_ns: String(value.ctimeNs), close_on_exec: true, read_write: true });
      const result = snapshot(before); if (!equivalent(result, snapshot(after))) invalid(); return result;
    }
    function observeWriter() {
      const raw = boundedProc("/proc/self/stat", 4096), split = raw.lastIndexOf(") ");
      if (split < 0) invalid(); const pid = raw.slice(0, raw.indexOf(" (")).trim(), fields = raw.slice(split + 2).trim().split(/\s+/);
      const value = { platform: "linux", boot_id: boundedProc("/proc/sys/kernel/random/boot_id", 128).trim(), pid: Number(pid), ppid: Number(fields[1]),
        pgid: Number(fields[2]), start_time: fields[19], namespace: readlink("/proc/self/ns/pid", "utf8"), uid: apply(getuid, process, []) };
      if (value.namespace.length > 128 || value.pid !== process.pid || value.ppid !== process.ppid) invalid(); return value;
    }
    const effects = Object.freeze({ lock: observeLock, writer: observeWriter,
      write(frame, done) {
        if (stdout === null) { stdout = process.stdout; stdoutWrite = stdout.write; }
        apply(stdoutWrite, stdout, [frame, done]);
      }, close() { close(3); },
      now() { return apply(now, performance, []); }, setTimer(delay, callback) { return setTimer(callback, delay); },
      clearTimer(handle) { clearTimer(handle); }, finish(code) { apply(exit, process, [code]); },
    });
    const driver = _createOwnerBootstrapForTests(input, effects); driver.start();
    const stdin = process.stdin;
    stdin.on("data", value => driver.push(value)); stdin.on("end", () => driver.end());
    stdin.on("error", () => driver.end()); stdout.on("error", () => driver.end());
  } catch { apply(exit, process, [2]); }
}
if (process.argv[1] === fileURLToPath(import.meta.url)) _main();
