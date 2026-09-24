import fs from "node:fs";
import { syncBuiltinESMExports } from "node:module";
import { join } from "node:path";
import { Store } from "../../src/store/database.ts";
const [root, mode] = process.argv.slice(2);
if (mode === "publish") {
  const link = fs.linkSync;
  fs.linkSync = ((source: fs.PathLike, target: fs.PathLike) => {
    link(source, target);
    if (String(target).endsWith(".identity")) {
      process.send?.({ type: "published" }); const until = Date.now() + 10000;
      while (!fs.existsSync(join(root, "release"))) {
        if (Date.now() > until) throw new Error("Publication observer did not release startup");
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 5);
      }
    }
  }) as typeof fs.linkSync;
  syncBuiltinESMExports();
}
process.send?.({ type: "ready" });
process.once("message", () => {
  try {
    const store = new Store(root);
    process.send?.({ type: "opened", identity: store.db.prepare("SELECT value FROM meta WHERE id='store-id'").get()!.value,
      mode: store.db.prepare("PRAGMA journal_mode").get()!.journal_mode }); store.close(); process.disconnect?.();
  } catch (error) { process.send?.({ type: "error", message: String(error), errcode: (error as {errcode?:number}).errcode }); process.disconnect?.(); }
});
