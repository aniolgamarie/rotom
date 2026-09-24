import { Store } from "../../src/store/database.ts";
import { join } from "node:path";
import { mkdirSync, writeFileSync } from "node:fs";

const [root, id, mode] = process.argv.slice(2);
const dbRoot = join(root, "state");
mkdirSync(dbRoot, { recursive: true });
const store = new Store(dbRoot);

process.send!({ type: "ready" });

process.on("message", (message: any) => {
  if (message.type === "start") {
    if (mode === "write") {
      // 尝试获取写入锁
      const owner = store.claimOwner("writer-scope", id);
      try {
        store.prepare(owner, "write-intent", "write", {}, []);
        writeFileSync(join(root, "workspace", "source.txt"), `written by ${id}`);
        process.send!({ type: "result", allowed: true });
        store.settle("write-intent", "terminated");
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
