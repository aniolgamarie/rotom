import assert from "node:assert/strict";
import { test } from "node:test";
import { createDurableStorageInitializer } from "../src/storage.ts";

const secret = "synthetic-secret /private/database.sqlite SQL credentials";
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function fixture(hooks = {}) {
  const events = [], closeContext = Object.freeze({ opaque: "synthetic Context; never SDK qualified" });
  let privateReads = 0, owners = 0, reads = 0;
  class Executor {
    async exec(sql) {
      events.push(sql === "PRAGMA journal_mode = WAL" ? "set:wal" : "set:full");
      return hooks.exec?.(sql);
    }
    async get(sql) {
      const phase = ++reads <= 2 ? "before" : "after";
      const kind = sql === "PRAGMA journal_mode" ? "wal" : "full";
      events.push(`read:${phase}:${kind}`);
      return hooks.get ? hooks.get(sql, phase) : kind === "wal" ? { journal_mode: "wal" } : { synchronous: 2 };
    }
  }
  class Database extends Executor {
    async close(...args) { events.push("close:database"); assert.deepEqual(args, []); return hooks.dbClose?.(); }
  }
  class Storage {
    static async open(database) { events.push("storage:open"); assert.equal(database, db); if (hooks.storageOpen) return hooks.storageOpen(database); return storage; }
    async close(context) { events.push("close:storage"); assert.equal(context, closeContext); return hooks.storageClose?.(); }
  }
  const db = new Database(), storage = new Storage();
  for (const object of [db, storage]) for (const key of ["database", "db", "statements", "access", "closed", "closing"]) {
    Object.defineProperty(object, key, { get() { privateReads++; throw new Error(secret); } });
  }
  const cfg = {
    nodeSqlite: { async openNodeSqliteDatabase(path, options) {
      events.push("database:open"); assert.equal(path, "/synthetic/中文/storage.sqlite");
      assert.deepEqual(options, { busyTimeoutMs: 5000, walAutoCheckpointPages: 1000 }); assert(Object.isFrozen(options));
      if (hooks.open) return hooks.open(path, options); return db;
    }, openNodeSqliteStorage() { assert.fail("convenience API must not be used"); } },
    sqlite: { SqliteStorage: Storage }, path: "/synthetic/中文/storage.sqlite", closeContext,
    async verifyOwner() { events.push("owner"); owners++; return hooks.owner ? hooks.owner(owners) : true; },
  };
  return { cfg, db, storage, Storage, events, privateReads: () => privateReads, create: () => createDurableStorageInitializer(cfg) };
}
function code(expected) {
  return error => {
    assert.equal(error.code, expected); assert.equal(error.message, expected); assert.equal(error.cause, undefined);
    assert(!String(error.stack).includes(secret)); return true;
  };
}
const ownerAfter = actions => ["owner", ...actions.flatMap(action => [action, "owner"]), "owner"];
const actions = ["database:open", "set:wal", "set:full", "read:before:wal", "read:before:full", "storage:open", "read:after:wal", "read:after:full"];

test("lazy concurrent initialization uses one facade, stable public prototype methods and owned close context", async () => {
  const gate = deferred(), f = fixture({ open: () => gate.promise });
  const init = f.create(); assert.deepEqual(f.events, []);
  const first = init(); assert.equal(init(), first);
  await new Promise(resolve => setImmediate(resolve)); assert.deepEqual(f.events, ["owner", "database:open"]);
  gate.resolve(f.db); const result = await first;
  assert.equal(await init(), result); assert.equal(result.storage, f.storage);
  assert.deepEqual(result.settings, { journalMode: "wal", synchronous: 2 }); assert(Object.isFrozen(result.settings)); assert(Object.isFrozen(result));
  assert.deepEqual(f.events, ownerAfter(actions)); assert.equal(f.privateReads(), 0);
  const closing = result.close(); assert.equal(result.close(), closing); await closing;
  assert.equal(f.events.filter(event => event === "close:storage").length, 1);
  assert(!f.events.includes("close:database")); assert.equal(f.privateReads(), 0);
});

test("explicit bounded options are captured before callback and preserve canonical Chinese path", async () => {
  const f = fixture(); f.cfg.options = { busyTimeoutMs: 0, walAutoCheckpointPages: 2147483647 };
  const original = f.cfg.nodeSqlite.openNodeSqliteDatabase;
  f.cfg.nodeSqlite.openNodeSqliteDatabase = async (path, options) => {
    assert.equal(path, f.cfg.path); assert.deepEqual(options, f.cfg.options); assert.notEqual(options, f.cfg.options);
    return f.db;
  };
  const result = await f.create()(); await result.close(); assert.equal(f.privateReads(), 0); assert.equal(typeof original, "function");
});

for (const path of ["", "/", "relative.sqlite", ":memory:", "file:/tmp/db", "/a/../db", "/a/./db", "/a//db", "/a/db/", "/a\0db", "/" + "中".repeat(1400), "/\ud800"]) {
  test(`invalid path shape ${JSON.stringify(path).slice(0, 35)} rejected before owner or SDK`, () => {
    const f = fixture(); f.cfg.path = path;
    assert.throws(f.create, code("input-invalid")); assert.deepEqual(f.events, []);
  });
}
for (const value of [null, [], new Date(0), { unknown: 0 }, { busyTimeoutMs: true }, { busyTimeoutMs: NaN }, { busyTimeoutMs: Infinity },
  { busyTimeoutMs: -1 }, { busyTimeoutMs: 60001 }, { busyTimeoutMs: 0.5 }, { walAutoCheckpointPages: 2147483648 }, { walAutoCheckpointPages: false }]) {
  test(`invalid options ${String(value)} rejected without effects`, () => {
    const f = fixture(); f.cfg.options = value;
    assert.throws(f.create, code("input-invalid")); assert.deepEqual(f.events, []);
  });
}
for (const kind of ["input-getter", "option-getter", "transparent-input-proxy", "transparent-option-proxy", "revoked-input-proxy", "revoked-option-proxy", "context-proxy", "missing-context"]) {
  test(`${kind} detected by Node API without evaluating getters/traps`, () => {
    const f = fixture(); let getterCalls = 0, value = f.cfg;
    if (kind === "input-getter") Object.defineProperty(f.cfg, "path", { enumerable: true, get() { getterCalls++; throw new Error(secret); } });
    if (kind === "option-getter") { f.cfg.options = {}; Object.defineProperty(f.cfg.options, "busyTimeoutMs", { enumerable: true, get() { getterCalls++; throw new Error(secret); } }); }
    if (kind === "transparent-input-proxy") value = new Proxy(f.cfg, {});
    if (kind === "transparent-option-proxy") f.cfg.options = new Proxy({}, {});
    if (kind === "revoked-input-proxy") { const proxy = Proxy.revocable(f.cfg, {}); proxy.revoke(); value = proxy.proxy; }
    if (kind === "revoked-option-proxy") { const proxy = Proxy.revocable({}, {}); proxy.revoke(); f.cfg.options = proxy.proxy; }
    if (kind === "context-proxy") f.cfg.closeContext = new Proxy({}, {});
    if (kind === "missing-context") delete f.cfg.closeContext;
    assert.throws(() => createDurableStorageInitializer(value), code("input-invalid")); assert.equal(getterCalls, 0); assert.deepEqual(f.events, []);
  });
}

for (const stage of actions) {
  test(`owner loss after awaited ${stage} prevents later SDK use and closes only owned handle`, async () => {
    const index = actions.indexOf(stage), f = fixture({ owner: n => n !== index + 2 });
    const init = f.create(), first = init(); await assert.rejects(first, code("owner-invalid")); assert.equal(init(), first);
    assert.deepEqual(f.events.filter(event => !event.startsWith("close:") && event !== "owner"), actions.slice(0, index + 1));
    assert.equal(f.events.filter(event => event.startsWith("close:")).length, 1);
    assert.equal(f.events.at(-1), index < actions.indexOf("storage:open") ? "close:database" : "close:storage");
    assert.equal(f.privateReads(), 0);
  });
}
for (const owner of [false, 1, "true", undefined]) {
  test(`owner exact true required (${String(owner)}) before opener`, async () => {
    const f = fixture({ owner: () => owner }); await assert.rejects(f.create()(), code("owner-invalid")); assert.deepEqual(f.events, ["owner"]);
  });
}
test("owner rejection is sanitized before opening", async () => {
  const f = fixture({ owner: async () => { throw new Error(secret); } }); await assert.rejects(f.create()(), code("owner-invalid")); assert.deepEqual(f.events, ["owner"]);
});

for (const fault of ["opener", "storage-open", "module-class", "facade-exec", "facade-get", "path", "options", "context"]) {
  test(`binding drift ${fault} after asynchronous owner boundary rejected`, async () => {
    let f;
    f = fixture({ owner: n => {
      if (n === (fault.startsWith("facade") ? 3 : 1)) {
        if (fault === "opener") f.cfg.nodeSqlite.openNodeSqliteDatabase = async () => assert.fail("replacement opener");
        if (fault === "storage-open") f.Storage.open = async () => assert.fail("replacement storage");
        if (fault === "module-class") f.cfg.sqlite.SqliteStorage = class {};
        if (fault === "facade-exec") f.db.exec = async () => assert.fail("replacement exec");
        if (fault === "facade-get") f.db.get = async () => assert.fail("replacement get");
        if (fault === "path") f.cfg.path = "/other/storage.sqlite";
        if (fault === "options") f.cfg.options.busyTimeoutMs = 1;
        if (fault === "context") f.cfg.closeContext = {};
      }
      return true;
    } });
    if (fault === "options") f.cfg.options = { busyTimeoutMs: 5000 };
    const init = f.create(); await assert.rejects(init(), code("api-drift"));
    const calls = f.events.filter(event => event !== "owner" && !event.startsWith("close:"));
    assert.deepEqual(calls, fault.startsWith("facade") ? ["database:open", "set:wal"] : []);
  });
}

for (const stage of ["set:wal", "set:full", "read:before:wal", "read:before:full", "read:after:wal", "read:after:full"]) {
  test(`SDK settings failure ${stage} sanitized, no later operation, permanent rejection`, async () => {
    const f = fixture({ exec: sql => { if ((sql.includes("journal_mode") ? "set:wal" : "set:full") === stage) throw new Error(secret); },
      get: (sql, phase) => { if (`read:${phase}:${sql.includes("journal_mode") ? "wal" : "full"}` === stage) throw new Error(secret); return sql.includes("journal_mode") ? { journal_mode: "wal" } : { synchronous: 2 }; } });
    const init = f.create(), first = init(); await assert.rejects(first, code("settings-invalid")); assert.equal(init(), first);
    assert.deepEqual(f.events.filter(event => event !== "owner" && !event.startsWith("close:")), actions.slice(0, actions.indexOf(stage) + 1));
    assert.equal(f.events.at(-1), stage.includes("after") ? "close:storage" : "close:database"); assert.equal(f.privateReads(), 0);
  });
}
for (const phase of ["before", "after"]) for (const value of [undefined, { journal_mode: "WAL" }, { journal_mode: "delete" }, { journal_mode: "wal", extra: 1 },
  { synchronous: "2" }, { synchronous: true }, { synchronous: 1 }]) {
  test(`strict readback ${phase} rejects ${JSON.stringify(value)}`, async () => {
    const sync = value && Object.hasOwn(value, "synchronous"), f = fixture({ get: (sql, at) => at === phase && sql.includes(sync ? "synchronous" : "journal_mode") ? value : sql.includes("journal_mode") ? { journal_mode: "wal" } : { synchronous: 2 } });
    await assert.rejects(f.create()(), code("settings-invalid"));
    if (phase === "before") assert(!f.events.includes("storage:open"));
    assert.equal(f.events.at(-1), phase === "before" ? "close:database" : "close:storage");
  });
}
for (const kind of ["getter", "transparent-proxy", "revoked-proxy"]) {
  test(`readback ${kind} rejected without executing getter`, async () => {
    let getterCalls = 0, row = {};
    if (kind === "getter") Object.defineProperty(row, "journal_mode", { enumerable: true, get() { getterCalls++; throw new Error(secret); } });
    if (kind === "transparent-proxy") row = new Proxy({ journal_mode: "wal" }, {});
    if (kind === "revoked-proxy") { const proxy = Proxy.revocable({}, {}); proxy.revoke(); row = proxy.proxy; }
    const f = fixture({ get: () => row }); await assert.rejects(f.create()(), code("settings-invalid")); assert.equal(getterCalls, 0); assert(!f.events.includes("storage:open"));
  });
}
test("storage initialization failure closes original facade once without rollback claim", async () => {
  const f = fixture({ storageOpen: () => { throw new Error(secret); } }); const init = f.create(), first = init();
  await assert.rejects(first, code("initialization-failed")); assert.equal(init(), first); await assert.rejects(init(), code("initialization-failed"));
  assert.equal(f.events.filter(event => event === "close:database").length, 1); assert(!f.events.includes("close:storage")); assert(!f.events.includes("read:after:wal"));
});
test("opener failure without returned handle is open-unknown and never closes others", async () => {
  const f = fixture({ open: () => { throw new Error(secret); } }); const init = f.create(), first = init();
  await assert.rejects(first, code("open-unknown")); assert.equal(init(), first); assert.deepEqual(f.events, ["owner", "database:open"]);
});
for (const target of ["database", "storage"]) {
  test(`failure cleanup ${target} rejection reports cleanup-unknown once`, async () => {
    const f = fixture({ exec: () => { if (target === "database") throw new Error(secret); },
      get: (sql, phase) => phase === "after" ? undefined : sql.includes("journal_mode") ? { journal_mode: "wal" } : { synchronous: 2 },
      dbClose: () => { throw new Error(secret); }, storageClose: () => { throw new Error(secret); } });
    const init = f.create(), first = init(); await assert.rejects(first, code("cleanup-unknown")); assert.equal(init(), first);
    await assert.rejects(init(), code("cleanup-unknown")); assert.equal(f.events.filter(event => event.startsWith("close:")).length, 1);
    assert.equal(f.events.at(-1), `close:${target}`);
  });
}
test("returned close is permanently memoized even when cleanup fails", async () => {
  const f = fixture({ storageClose: () => { throw new Error(secret); } }); const result = await f.create()();
  const first = result.close(); assert.equal(result.close(), first); await assert.rejects(first, code("cleanup-unknown"));
  assert.equal(result.close(), first); assert.equal(f.events.filter(event => event === "close:storage").length, 1); assert(!f.events.includes("close:database"));
});

test("opener returned undefined is open-unknown without fake close", async () => {
  const f = fixture({ open: () => undefined }); await assert.rejects(f.create()(), code("open-unknown"));
  assert.deepEqual(f.events, ["owner", "database:open"]);
});
for (const value of [null, 2]) {
  test(`opener malformed handle (${String(value)}) reports cleanup-unknown without fake close`, async () => {
    const f = fixture({ open: () => value }); await assert.rejects(f.create()(), code("cleanup-unknown"));
    assert.deepEqual(f.events, ["owner", "database:open"]);
  });
}
test("malformed facade close reports cleanup-unknown without evaluating accessor", async () => {
  let reads = 0;
  const malformed = {};
  Object.defineProperty(malformed, "close", { get() { reads++; throw new Error(secret); } });
  const f = fixture({ open: () => malformed }); await assert.rejects(f.create()(), code("cleanup-unknown"));
  assert.equal(reads, 0); assert.deepEqual(f.events, ["owner", "database:open"]);
});
test("missing facade exec is api-drift and cleans only received facade", async () => {
  const f = fixture(); f.db.exec = undefined;
  await assert.rejects(f.create()(), code("api-drift"));
  assert.deepEqual(f.events, ["owner", "database:open", "owner", "close:database"]);
});
test("storage without public close reports cleanup-unknown without bypassing to database", async () => {
  const f = fixture({ storageOpen: () => ({}) }); await assert.rejects(f.create()(), code("cleanup-unknown"));
  assert(!f.events.includes("close:database")); assert(!f.events.includes("read:after:wal"));
});
test("no returned storage cleans own facade and reports initialization-failed", async () => {
  const f = fixture({ storageOpen: () => null }); await assert.rejects(f.create()(), code("initialization-failed"));
  assert.equal(f.events.at(-1), "close:database"); assert(!f.events.includes("read:after:wal"));
});
test("opener public identity drift while open is awaited cleans acquired handle", async () => {
  const gate = deferred(), f = fixture({ open: () => gate.promise });
  const init = f.create(), first = init(); await new Promise(resolve => setImmediate(resolve));
  f.cfg.nodeSqlite.openNodeSqliteDatabase = async () => assert.fail("replacement must not run");
  gate.resolve(f.db); await assert.rejects(first, code("api-drift")); assert.equal(init(), first);
  assert.deepEqual(f.events, ["owner", "database:open", "owner", "close:database"]);
});
test("owner loss while setting is awaited prevents next setting and cleans acquired handle", async () => {
  const gate = deferred(); let live = true;
  const f = fixture({ exec: () => gate.promise, owner: () => live });
  const first = f.create()(); await new Promise(resolve => setImmediate(resolve));
  live = false; gate.resolve(); await assert.rejects(first, code("owner-invalid"));
  assert.deepEqual(f.events, ["owner", "database:open", "owner", "set:wal", "owner", "close:database"]);
});
test("owner final recheck rejects completed settings and closes storage with captured context", async () => {
  const f = fixture({ owner: n => n !== 10 }); await assert.rejects(f.create()(), code("owner-invalid"));
  assert.deepEqual(f.events.filter(event => event !== "owner" && !event.startsWith("close:")), actions);
  assert.equal(f.events.at(-1), "close:storage"); assert.equal(f.privateReads(), 0);
});
test("storage initialization owner loss awaits original close exactly once", async () => {
  const open = deferred(), closing = deferred(); let live = true;
  const f = fixture({ storageOpen: () => open.promise, owner: () => live, storageClose: () => closing.promise });
  const init = f.create(), first = init(); let settled = false; first.catch(() => { settled = true; });
  await new Promise(resolve => setImmediate(resolve)); live = false; open.resolve(f.storage);
  await new Promise(resolve => setImmediate(resolve)); assert.equal(settled, false); assert.equal(f.events.at(-1), "close:storage");
  closing.resolve(); await assert.rejects(first, code("owner-invalid")); assert.equal(init(), first);
  assert.equal(f.events.filter(event => event === "close:storage").length, 1); assert(!f.events.includes("close:database"));
});
test("SDK module accessors are rejected at capture without invoking them", () => {
  const f = fixture(); let reads = 0;
  Object.defineProperty(f.cfg.sqlite, "SqliteStorage", { get() { reads++; throw new Error(secret); } });
  assert.throws(f.create, code("input-invalid")); assert.equal(reads, 0); assert.deepEqual(f.events, []);
});
test("real self-owned ESM namespace public data functions compose without any upstream import", async () => {
  // 动态模块内容全部为本测试自有替身，绝不导入 SDK、node:sqlite 或数据库。
  const nodeModule = await import("data:text/javascript,export async function openNodeSqliteDatabase(path, options) { return { async exec() {}, async get(sql) { return sql.includes('journal_mode') ? {journal_mode: 'wal'} : {synchronous: 2}; }, async close() {} }; }");
  const sqliteModule = await import("data:text/javascript,export class SqliteStorage { static async open(db) { return new SqliteStorage(); } async close(context) {} }");
  const init = createDurableStorageInitializer({ nodeSqlite: nodeModule, sqlite: sqliteModule, path: "/synthetic/db.sqlite", verifyOwner: () => true, closeContext: {} });
  const result = await init(); assert.equal(result.storage.constructor, sqliteModule.SqliteStorage); await result.close();
});

test("generic root prototype methods cannot replace public SDK contracts", { concurrency: false }, async t => {
  await t.test("generic Object close cannot report a malformed own handle cleaned", { concurrency: false }, async () => {
    const original = Object.getOwnPropertyDescriptor(Object.prototype, "close");
    let pollutedCalls = 0;
    try {
      Object.defineProperty(Object.prototype, "close", { configurable: true, value: async () => { pollutedCalls++; } });
      const f = fixture({ open: () => ({}) });
      let error; try { await f.create()(); } catch (caught) { error = caught; }
      assert.equal(pollutedCalls, 0, "generic noop close must never be invoked");
      assert(error); code("cleanup-unknown")(error);
      assert.deepEqual(f.events, ["owner", "database:open"]);
    } finally {
      if (original) Object.defineProperty(Object.prototype, "close", original);
      else delete Object.prototype.close;
    }
  });
  await t.test("generic Function open cannot provide a missing storage opener", { concurrency: false }, () => {
    const original = Object.getOwnPropertyDescriptor(Function.prototype, "open");
    let pollutedCalls = 0;
    try {
      Object.defineProperty(Function.prototype, "open", { configurable: true, value: async () => { pollutedCalls++; } });
      const f = fixture(); f.cfg.sqlite.SqliteStorage = class MissingStorageOpen {};
      assert.throws(f.create, code("input-invalid"));
      assert.equal(pollutedCalls, 0); assert.deepEqual(f.events, []);
    } finally {
      if (original) Object.defineProperty(Function.prototype, "open", original);
      else delete Function.prototype.open;
    }
  });
  for (const name of ["exec", "get"]) await t.test(`generic Object ${name} cannot reach settings`, { concurrency: false }, async () => {
    const original = Object.getOwnPropertyDescriptor(Object.prototype, name);
    let pollutedCalls = 0, closed = 0;
    try {
      Object.defineProperty(Object.prototype, name, { configurable: true, value: async () => {
        pollutedCalls++; return { journal_mode: "wal" };
      } });
      const f = fixture({ open: () => {
        const malformed = { async close() { closed++; } };
        if (name === "get") malformed.exec = async () => assert.fail("settings must not be reached with missing get contract");
        return malformed;
      } });
      await assert.rejects(f.create()(), code("api-drift"));
      assert.equal(pollutedCalls, 0); assert.equal(closed, 1);
      assert.deepEqual(f.events, ["owner", "database:open", "owner"]);
    } finally {
      if (original) Object.defineProperty(Object.prototype, name, original);
      else delete Object.prototype[name];
    }
  });
});

test("original get body cannot be replaced by its own call getter to forge WAL/FULL", async () => {
  const f = fixture({ get(sql) { return sql === "PRAGMA journal_mode" ? { journal_mode: "delete" } : { synchronous: 0 }; } });
  let getter = 0, spy = 0;
  Object.defineProperty(f.db.get, "call", { get() { getter++; return async (receiver, sql) => { spy++; assert.equal(receiver, f.db); return sql === "PRAGMA journal_mode" ? { journal_mode: "wal" } : { synchronous: 2 }; }; } });
  let caught; try { await f.create()(); } catch (error) { caught = error; }
  assert.deepEqual({ getter, spy, originalReads: f.events.filter(event => typeof event === "string" && event.startsWith("read:")).length }, { getter: 0, spy: 0, originalReads: 1 });
  assert(code("settings-invalid")(caught));
});
