import { appendFileSync } from "node:fs";
import { join } from "node:path";
import { Store } from "../../src/store/database.ts";

const [root, worker, mode, endpoint] = process.argv.slice(2);
const store = new Store(root);
const owner = store.claimOwner(`scope-${worker}`, `owner-${worker}`);
process.send?.({ type: "ready" });
process.on("message", async (message) => {
  if (message === "go") {
    try {
      if (mode === "budget-race") { store.prepare(owner, `intent-${worker}`, "protected-request", {}); process.send?.({ type: "reservation-ready" }); return; }
      if (mode === "budget" || mode === "budget-unknown") {
        store.prepare(owner, `intent-${worker}`, "protected-request", {});
        store.reserveRequest(owner, `intent-${worker}`, `request-${worker}`, [{ id: "shared-incident", ceiling: 4 }, { id: "shared-work", ceiling: 1 }]);
        await fetch(endpoint, { method: "POST", body: worker });
        if (mode === "budget-unknown") { process.send?.({ type: "cut" }); return; }
        store.settleRequest(`request-${worker}`, "sent"); process.send?.({ type: "result", acquired: true }); return;
      }
      if (mode === "C0") {
        store.db.exec("BEGIN IMMEDIATE");
        store.db.prepare("INSERT INTO records VALUES(?,?,?)").run("probe", "uncommitted", JSON.stringify({ value: true }));
        process.send?.({ type: "cut" });
        return;
      }
      store.prepare(owner, `intent-${worker}`, "continue", {}, [{ id: "half-open", capacity: 1, units: 1 }]);
      if (mode === "compete") { process.send?.({ type: "result", acquired: true }); return; }
      if (mode !== "C1") {
        store.markSent(owner, `intent-${worker}`);
        appendFileSync(join(root, "external-sends.txt"), `${worker}\n`, { mode: 0o600 });
      }
      if (["C4", "C5"].includes(mode)) store.acknowledge(`intent-${worker}`, `native-${worker}`);
      if (["C3", "C4", "C5"].includes(mode)) process.send?.({ type: "native_ack", nativeId: `native-${worker}` });
      if (mode === "C5") store.settle(`intent-${worker}`, "terminated");
      process.send?.({ type: "cut" });
    } catch (error) {
      process.send?.({ type: "result", acquired: false, error: error instanceof Error ? error.message : String(error) });
    }
  }
  if (message === "reserve" && mode === "budget-race") {
    try {
      store.reserveRequest(owner, `intent-${worker}`, `request-${worker}`, [{ id: "shared-work", ceiling: 1 }]);
      await fetch(endpoint, { method: "POST", body: worker }); store.settleRequest(`request-${worker}`, "sent");
      process.send?.({ type: "result", acquired: true });
    } catch (error) { process.send?.({ type: "result", acquired: false, error: String(error) }); }
  }
  if (message === "release") {
    store.settle(`intent-${worker}`, "not_sent");
    process.send?.({ type: "released" });
  }
  if (message === "quit") { store.close(); process.exit(0); }
});
