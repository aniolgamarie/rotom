import { migrateStore, recoverMaintenance } from "../src/store/maintenance.ts";
const [action, root, ...extra] = process.argv.slice(2);
if (!root || extra.length || !["upgrade", "finish", "rollback"].includes(action)) throw new Error("Usage: state-maintenance.ts upgrade|finish|rollback EXPLICIT_STATE_DIRECTORY");
console.log(JSON.stringify(action === "upgrade" ? migrateStore(root) : recoverMaintenance(root, action as "finish" | "rollback")));
