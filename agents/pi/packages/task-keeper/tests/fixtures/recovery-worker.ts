import { Store } from "../../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../../src/reliability/recovery.ts";
import { configured } from "./config.ts";
const [root, id, endpoint] = process.argv.slice(2);
const store = new Store(root); let now = 1000000, sends = 0;
const snapshot: InteractiveSnapshot = { sessionId: id, leafId: "limited", provider: "fixture-provider", model: "fixture-model",
  idle: true, pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
const controller = new RecoveryController(store, configured(), {
  snapshot: () => snapshot, abort: () => {},
  continue: async intent => { snapshot.idle = false; sends++; await fetch(endpoint, { method: "POST", body: JSON.stringify({ id, intent: intent.id }) }); return { nativeId: `native-${id}` }; },
}, { now: () => now, monotonic: () => now - 1000000, schedule: () => () => {} }, () => 0);
controller.settled({ status: 429, message: "controlled quota pressure", code: "ResourcePressure", stream: "error", responseObserved: true });
process.on("message", async (message: { command: string; serial: number }) => {
  try {
    if (message.command === "tick") { now += 100000; await controller.tick(); }
    if (message.command === "pause") controller.pause();
    if (message.command === "resume") controller.resume();
    if (message.command === "settle") { snapshot.idle = true; snapshot.leafId = "finished"; controller.settled(null); }
    if (message.command === "quit") { controller.dispose(); store.close(); process.exit(0); }
    process.send?.({ type: "result", serial: message.serial, id, sends, state: controller.state() });
  } catch (error) { process.send?.({ type: "result", serial: message.serial, id, error: String(error) }); }
});
process.send?.({ type: "ready", id, pid: process.pid });
