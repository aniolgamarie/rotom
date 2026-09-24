import { migrateStore, type MaintenanceCut } from "../../src/store/maintenance.ts";
const [root, wanted] = process.argv.slice(2);
process.send?.({ type: "ready" });
process.on("message", message => {
  if (message !== "go") return;
  try {
    migrateStore(root, (cut: MaintenanceCut) => {
      if (cut !== wanted) return;
      process.send?.({ type: "cut", cut });
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 30000);
      throw new Error("Supervisor did not terminate at the requested cut");
    });
    process.send?.({ type: "unexpected-complete" });
  } catch (error) { process.send?.({ type: "error", error: String(error) }); }
});
