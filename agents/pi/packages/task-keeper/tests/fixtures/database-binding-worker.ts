import { Store } from "../../src/store/database.ts";
const [root, filename, id] = process.argv.slice(2); let store: Store | undefined;
process.on("message", command => {
  if (command === "go") {
    try { store = new Store(root, filename); const owner = store.claimOwner(id, id);
      store.prepare(owner, id, "write", {}, [{ id: "host-child", capacity: 1, units: 1 }]);
      process.send?.({ type: "result", acquired: true, filename, stateRoot: store.root });
    } catch (error) { process.send?.({ type: "result", acquired: false, filename, code: (error as {code?:string}).code }); }
  }
  if (command === "quit") { store?.close(); process.exit(0); }
});
process.send?.({ type: "ready", pid: process.pid });
