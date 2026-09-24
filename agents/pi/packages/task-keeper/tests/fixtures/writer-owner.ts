import { spawn } from "node:child_process";
import { Store } from "../../src/store/database.ts";
import { processIdentity, originalProcessStopped } from "../../src/adapters/process-identity.ts";
import { workspaceResource } from "../../src/workspace/worktree.ts";
const [root, cwd] = process.argv.slice(2), store = new Store(root), owner = store.claimOwner("writer-scope", "old-owner");
store.prepare(owner, "old-write", "write", { cwd }, [{ id: workspaceResource(cwd), capacity: 1, units: 1 }]);
store.markSent(owner, "old-write");
const program = `const fs=require('fs');let last=0;process.on('SIGTERM',()=>{});process.on('disconnect',()=>{});process.send({ready:true});setInterval(()=>{let next=0;try{next=Number(fs.readFileSync('advance','utf8'))}catch{};if(next>last){fs.appendFileSync('writes.log',String(next)+'\\n');last=next;fs.writeFileSync('completed',String(last));}},5);`;
const writer = spawn(process.execPath, ["-e", program], { cwd, detached: true, stdio: ["ignore", "ignore", "ignore", "ipc"] });
let identity: ReturnType<typeof processIdentity> = null;
writer.once("message", () => {
  identity = processIdentity(writer.pid!); store.acknowledge("old-write", `writer-${writer.pid}`);
  store.put("writer-proof", "old-write", { identity });
  process.send?.({ type: "ready", owner, controller: processIdentity(), writer: identity });
});
process.on("message", message => {
  if (message === "expire") { store.revokeOwner(owner); process.send?.({ type: "revoked" }); }
  if (message === "quit") { if (identity && originalProcessStopped(identity) === false) writer.kill("SIGKILL"); store.close(); process.exit(0); }
});
