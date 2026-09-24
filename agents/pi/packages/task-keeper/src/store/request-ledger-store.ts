// 预算保留复用 Task Keeper SQLite；异步协议不把 SQLite 事务跨 await 持有。
// operation 必须是纯状态变换，提交发生前不得发送请求或执行工具。
import { clone, closed, digest, reject, text } from "@agentcfg/pi-runtime/managed-types";
import type { Store, Owner } from "./database.ts";

export class TaskLedgerStore {
  private database: Store;
  private owner: Owner;
  private key: string;
  private tail: Promise<unknown> = Promise.resolve();
  constructor(database: Store, owner: Owner, taskId: string) {
    if (!text(taskId)) reject();
    this.database = database; this.owner = owner; this.key = taskId;
  }
  private snapshot() {
    if (!this.database.has("agentcfg-request-ledger-v1", this.key)) return { schema_version: 1, revision: 0, state: {} };
    const value = this.database.get<any>("agentcfg-request-ledger-v1", this.key);
    closed(value, ["schema_version", "revision", "state"]);
    return value;
  }
  transaction<T>(operation: (state: Record<string, unknown>) => T | Promise<T>): Promise<T> {
    const pending = this.tail.then(async () => {
      for (let retries = 0; retries < 16; retries++) {
        this.database.assertOwner(this.owner);
        const previous = this.snapshot();
        if (previous.schema_version !== 1 || !Number.isSafeInteger(previous.revision) || previous.revision < 0
            || !previous.state || Object.getPrototypeOf(previous.state) !== Object.prototype) reject("BUDGET_STORE_VERSION", 4);
        const state = clone(previous.state), result = await operation(state);
        const committed = this.database.transaction(() => {
          this.database.assertOwner(this.owner);
          const current = this.snapshot();
          if (digest(current) !== digest(previous)) return false;
          this.database.put("agentcfg-request-ledger-v1", this.key, { schema_version: 1, revision: previous.revision + 1, state });
          return true;
        });
        if (committed) return result;
      }
      reject("BUDGET_STORE_BUSY", 4);
    });
    this.tail = pending.catch(() => {});
    return pending;
  }
}
