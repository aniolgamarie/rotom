// 自有默认 SQLite fixture；公开 facade 排队契约，不导入 SDK，不创建模型调用。
import { DatabaseSync } from "node:sqlite";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

export function databaseFixture(options = {}) {
  const directory = join(process.env.HOME, "model-attempt-test");
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const path = options.path ?? join(directory, randomUUID() + ".sqlite");
  const raw = new DatabaseSync(path, { readOnly: options.readOnly ?? false });
  if (!options.readOnly) raw.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL;");
  const events = [], faults = {}, counters = { transactions: 0, reads: 0, writes: 0, dbCloses: 0, rollbacks: 0, commits: 0 };
  let tail = Promise.resolve();
  function enqueue(action) { const result = tail.then(action); tail = result.catch(() => {}); return result; }
  class Executor {
    async exec(sql) {
      events.push(["exec", sql]); counters.writes++;
      if (faults.writeFailure) throw faults.writeFailure;
      raw.exec(sql);
    }
    async run(sql, ...params) {
      events.push(["run", sql, params]); counters.writes++;
      if (faults.writeFailure) throw faults.writeFailure;
      raw.prepare(sql).run(...params);
    }
    async get(sql, ...params) {
      events.push(["get", sql, params]); counters.reads++;
      if (faults.getFailure) throw faults.getFailure;
      const result = raw.prepare(sql).get(...params);
      if (faults.getGate) await faults.getGate.promise;
      if (faults.methodDrift) this.get = async () => result;
      return result;
    }
  }
  class Database {
    async transaction(callback) {
      return enqueue(async () => {
        counters.transactions++; events.push(["begin"]); raw.exec(options.readOnly ? "BEGIN" : "BEGIN IMMEDIATE");
        const executor = new Executor(); let value;
        try {
          value = await callback(executor);
        } catch (caught) {
          counters.rollbacks++; events.push(["rollback"]);
          try {
            raw.exec("ROLLBACK");
            if (faults.rollbackFailure) throw faults.rollbackFailure;
          } catch { throw new AggregateError([caught], "synthetic rollback secret"); }
          if (faults.swallowSemantic) return undefined;
          if (faults.replaceSemantic) throw faults.replaceSemantic;
          throw caught;
        }
        if (faults.commitFailure) {
          raw.exec("ROLLBACK"); throw faults.commitFailure;
        }
        raw.exec("COMMIT"); counters.commits++; events.push(["commit"]);
        if (faults.afterCommitGate) await faults.afterCommitGate.promise;
        if (faults.lostAck) throw faults.lostAck;
        return value;
      });
    }
    async get(sql, ...params) { return enqueue(() => new Executor().get(sql, ...params)); }
    async close() { counters.dbCloses++; return enqueue(() => raw.close()); }
  }
  const database = new Database();
  return { path, raw, database, faults, events, counters, async cleanup() { await tail; raw.close(); } };
}
