import { test, assert } from "./recorded-test.ts";
import { fork } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { fileURLToPath } from "node:url";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";

test("[P RTB-009] two processes at the request-reservation barrier have exactly one final permit", { timeout: 15000 }, async t => {
  const root = isolatedDirectory(t); new Store(root).close(); const received: string[] = [];
  const server = createServer((req, res) => { let body = ""; req.on("data", chunk => body += chunk); req.on("end", () => { received.push(body); res.end("accepted"); }); });
  await listenLoopback(server); t.after(() => { server.closeAllConnections(); server.close(); });
  const endpoint = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
  const children = ["a", "b"].map(id => fork(fileURLToPath(new URL("./fixtures/store-worker.ts", import.meta.url)), [root, id, "budget-race", endpoint], { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"] }));
  t.after(async () => { await Promise.all(children.map(async child => { if (child.exitCode === null && child.signalCode === null) { const stopped = once(child, "exit"); child.kill("SIGKILL"); await stopped; } })); });
  const ready = await Promise.all(children.map(child => once(child, "message"))); assert.ok(ready.every(([m]) => m.type === "ready"));
  const prepared = children.map(child => once(child, "message")); children.forEach(child => child.send("go"));
  assert.ok((await Promise.all(prepared)).every(([m]) => m.type === "reservation-ready"));
  const results = children.map(child => once(child, "message")); children.forEach(child => child.send("reserve"));
  const actual = await Promise.all(results); assert.equal(actual.filter(([m]) => m.acquired).length, 1); assert.equal(received.length, 1);
  const store = new Store(root); assert.equal(store.bucket("shared-work")?.used, 1); assert.equal(store.bucket("shared-work")?.reserved, 0);
  assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 1); store.close();
});
