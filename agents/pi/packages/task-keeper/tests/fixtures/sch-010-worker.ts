import { Store } from "../../src/store/database.ts";
import { join } from "node:path";
import { mkdirSync } from "node:fs";

const [root, id, mode] = process.argv.slice(2);
const dbRoot = join(root, "state");
mkdirSync(dbRoot, { recursive: true });
const store = new Store(dbRoot);

process.send!({ type: "ready" });

process.on("message", (message: any) => {
  if (message.type === "start") {
    if (mode === "verify") {
      // 尝试获取验证锁
      const owner = store.claimOwner("verification-scope", id);
      try {
        store.prepare(owner, "verify-intent", "verify", {}, []);
        process.send!({ type: "verifying" });
        
        // 模拟验证过程
        setTimeout(() => {
          store.settle("verify-intent", "terminated");
          process.send!({ type: "result", status: "verified" });
        }, 100);
      } catch (e) {
        process.send!({ type: "result", status: "rejected" });
      }
    } else if (mode === "write") {
      // 尝试获取写入锁
      const owner = store.claimOwner("verification-scope", id);
      try {
        store.prepare(owner, "write-intent", "write", {}, []);
        process.send!({ type: "result", allowed: true });
        store.settle("write-intent", "terminated");
      } catch (e) {
        process.send!({ type: "result", allowed: false });
      }
    }
  } else if (message.type === "retry") {
    if (mode === "write") {
      const owner = store.claimOwner("verification-scope", id);
      try {
        store.prepare(owner, "write-intent-2", "write", {}, []);
        process.send!({ type: "result", allowed: true });
        store.settle("write-intent-2", "terminated");
      } catch (e) {
        process.send!({ type: "result", allowed: false });
      }
    }
  }
});

process.on("disconnect", () => {
  store.close();
  process.exit(0);
});
