// 仅组合受信公开 API；所有权、目录恢复及真实 SQLite 验收由未来服务层负责。
import { posix } from "node:path";
import { types } from "node:util";

const applyOriginal = Reflect.apply;

function failure(code) {
  const error = new Error(code);
  Object.defineProperty(error, "code", Object.assign(Object.create(null), { value: code, enumerable: true }));
  return error;
}
function data(value, allowed, required = allowed) {
  // 固定 Node 的公开检测，不声称普通 JavaScript 能通用识别透明 Proxy。
  if (!value || typeof value !== "object" || types.isProxy(value)) throw failure("input-invalid");
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) throw failure("input-invalid");
  const keys = Reflect.ownKeys(value);
  if (keys.some(key => typeof key !== "string" || !allowed.includes(key)) || required.some(key => !keys.includes(key))) throw failure("input-invalid");
  const result = Object.create(null);
  for (const key of keys) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) throw failure("input-invalid");
    result[key] = descriptor.value;
  }
  return result;
}
function opaque(value) {
  if (!value || typeof value !== "object" || types.isProxy(value)) throw failure("input-invalid");
  return value;
}
function method(value, name) {
  if (!value || !["object", "function"].includes(typeof value) || types.isProxy(value)) throw failure("api-drift");
  // 只沿 SDK 的公开继承链寻找选定函数，通用根的同名污染不能补齐 SDK 契约。
  for (let current = value; current !== null && current !== Object.prototype && current !== Function.prototype; current = Object.getPrototypeOf(current)) {
    if (types.isProxy(current)) throw failure("api-drift");
    const descriptor = Object.getOwnPropertyDescriptor(current, name);
    if (descriptor) {
      if (!Object.hasOwn(descriptor, "value") || typeof descriptor.value !== "function" || types.isProxy(descriptor.value)) throw failure("api-drift");
      return descriptor.value;
    }
  }
  throw failure("api-drift");
}
function exportValue(value, name) {
  if (!value || typeof value !== "object" || types.isProxy(value)) throw failure("api-drift");
  const descriptor = Object.getOwnPropertyDescriptor(value, name);
  if (!descriptor || !Object.hasOwn(descriptor, "value")) throw failure("api-drift");
  return descriptor.value;
}
function options(value) {
  const selected = value === undefined ? Object.create(null) : data(value, ["busyTimeoutMs", "walAutoCheckpointPages"], []);
  const saved = { busyTimeoutMs: 5000, walAutoCheckpointPages: 1000, ...selected };
  if (!Number.isSafeInteger(saved.busyTimeoutMs) || saved.busyTimeoutMs < 0 || saved.busyTimeoutMs > 60000
      || !Number.isSafeInteger(saved.walAutoCheckpointPages) || saved.walAutoCheckpointPages < 0 || saved.walAutoCheckpointPages > 2147483647) throw failure("input-invalid");
  return Object.freeze(saved);
}
function readback(value, key, expected) {
  try {
    if (data(value, [key])[key] !== expected) throw failure("settings-invalid");
  } catch { throw failure("settings-invalid"); }
}

export function createDurableStorageInitializer(input) {
  let selected, savedOptions, openDatabase, Storage, openStorage;
  const keys = ["nodeSqlite", "sqlite", "path", "options", "verifyOwner", "closeContext"];
  try {
    selected = data(input, keys, keys.filter(key => key !== "options"));
    const path = selected.path;
    if (typeof path !== "string" || !posix.isAbsolute(path) || path === "/" || path.endsWith("/") || path.includes("\0")
        || path.split("/").includes("..") || posix.normalize(path) !== path || Buffer.byteLength(path, "utf8") > 4096
        || Buffer.from(path, "utf8").toString("utf8") !== path) throw failure("input-invalid");
    savedOptions = options(selected.options);
    opaque(selected.closeContext);
    if (typeof selected.verifyOwner !== "function" || types.isProxy(selected.verifyOwner)) throw failure("input-invalid");
    openDatabase = method(selected.nodeSqlite, "openNodeSqliteDatabase");
    Storage = exportValue(selected.sqlite, "SqliteStorage");
    openStorage = method(Storage, "open");
  } catch { throw failure("input-invalid"); }
  const { nodeSqlite, sqlite, path, verifyOwner, closeContext } = selected;
  let initialization, db, storage, dbClose, storageClose, exec, get, closing;
  function close() {
    if (closing === undefined) {
      // 无论成功关闭或清理失败，都不能靠重试重复清理同一 handle。
      closing = Promise.resolve().then(() => {
        if (storage !== undefined) {
          if (!storageClose) throw failure("cleanup-unknown");
          return applyOriginal(storageClose, storage, [closeContext]);
        }
        if (db !== undefined) {
          if (!dbClose) throw failure("cleanup-unknown");
          return applyOriginal(dbClose, db, []);
        }
      }).catch(() => { throw failure("cleanup-unknown"); });
    }
    return closing;
  }
  function binding() {
    try {
      const current = data(input, keys, keys.filter(key => key !== "options"));
      if (Object.keys(current).length !== Object.keys(selected).length || Object.keys(selected).some(key => current[key] !== selected[key])) throw failure("api-drift");
      const currentOptions = options(current.options);
      if (currentOptions.busyTimeoutMs !== savedOptions.busyTimeoutMs || currentOptions.walAutoCheckpointPages !== savedOptions.walAutoCheckpointPages
          || method(nodeSqlite, "openNodeSqliteDatabase") !== openDatabase || exportValue(sqlite, "SqliteStorage") !== Storage
          || method(Storage, "open") !== openStorage || dbClose && method(db, "close") !== dbClose
          || exec && method(db, "exec") !== exec || get && method(db, "get") !== get
          || storageClose && method(storage, "close") !== storageClose) throw failure("api-drift");
    } catch { throw failure("api-drift"); }
  }
  async function checkpoint() {
    let current;
    try { current = await verifyOwner(); } catch { throw failure("owner-invalid"); }
    binding();
    if (current !== true) throw failure("owner-invalid");
  }
  async function operation(invoke, code) {
    let value;
    try { value = await invoke(); } catch { throw failure(code); }
    await checkpoint();
    return value;
  }
  async function observe() {
    const journal = await operation(() => applyOriginal(get, db, ["PRAGMA journal_mode"]), "settings-invalid");
    readback(journal, "journal_mode", "wal");
    const synchronous = await operation(() => applyOriginal(get, db, ["PRAGMA synchronous"]), "settings-invalid");
    readback(synchronous, "synchronous", 2);
  }
  async function initialize() {
    try {
      await checkpoint();
      try { db = await applyOriginal(openDatabase, nodeSqlite, [path, savedOptions]); } catch { throw failure("open-unknown"); }
      if (db === undefined) throw failure("open-unknown");
      // 先捕获自有 close，owner 随后漂移时仍可释放自己的 handle。
      dbClose = method(db, "close");
      await checkpoint();
      exec = method(db, "exec"); get = method(db, "get");
      await operation(() => applyOriginal(exec, db, ["PRAGMA journal_mode = WAL"]), "settings-invalid");
      await operation(() => applyOriginal(exec, db, ["PRAGMA synchronous = FULL"]), "settings-invalid");
      await observe();
      try { storage = await applyOriginal(openStorage, Storage, [db]); } catch { throw failure("initialization-failed"); }
      if (!storage || typeof storage !== "object") { storage = undefined; throw failure("initialization-failed"); }
      storageClose = method(storage, "close");
      await checkpoint();
      await observe();
      await checkpoint();
      return Object.freeze({ storage, settings: Object.freeze({ journalMode: "wal", synchronous: 2 }), close });
    } catch (error) {
      if (db !== undefined || storage !== undefined) await close();
      // 只允许本模块产生的固定阶段码；外来异常原文永不传出。
      const code = ["api-drift", "owner-invalid", "settings-invalid", "initialization-failed", "open-unknown"].includes(error?.code) ? error.code : "initialization-failed";
      throw failure(code);
    }
  }
  return function initializeOnce() {
    if (initialization === undefined) initialization = Promise.resolve().then(initialize);
    return initialization;
  };
}
