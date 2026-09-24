import { test, assert, evidence } from "./recorded-test.ts";
import { fork, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { join, dirname } from "node:path";
import { mkdirSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";
const errors = new WeakMap<ChildProcess, string>();
function receive(child: ChildProcess, matches: (value: any) => boolean): Promise<any> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error(`worker ${child.pid} timed out`)); }, 10000);
    const exit = () => { cleanup(); reject(new Error(`worker ${child.pid} exited: ${errors.get(child)}`)); };
    const message = (value: any) => { if (matches(value)) { cleanup(); resolve(value); } };
    const cleanup = () => { clearTimeout(timer); child.off("message", message); child.off("exit", exit); };
    child.on("message", message); child.once("exit", exit);
  });
}
for (const paused of [false, true]) test(`[P ${paused ? "REC-014" : "REC-013 T24"}] ten independent recovery controllers ${paused ? "remove every waiter before resuming one" : "share one recovery permit and release it progressively"}`, { timeout: 25000 }, async t => {
  const root = isolatedDirectory(t); new Store(root).close(); const requests: any[] = [];
  const server = createServer((req, res) => { let body = ""; req.on("data", chunk => body += chunk); req.on("end", () => { requests.push(JSON.parse(body)); res.end("ack"); }); });
  const port = await listenLoopback(server);
  t.after(async () => { server.closeAllConnections(); await new Promise<void>(resolve => server.close(() => resolve())); });
  const children = Array.from({ length: 10 }, (_, i) => fork(fileURLToPath(new URL("./fixtures/recovery-worker.ts", import.meta.url)),
    [root, `parent-${i}`, `http://127.0.0.1:${port}`], { execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"] }));
  for (const child of children) child.stderr?.on("data", chunk => errors.set(child, ((errors.get(child) ?? "") + chunk).slice(-4000)));
  t.after(async () => { await Promise.all(children.map(async child => { if (child.exitCode === null && child.signalCode === null) { const exit = once(child, "exit"); child.kill("SIGKILL"); await exit; } })); });
  const ready = await Promise.all(children.map(child => receive(child, value => value.type === "ready")));
  let serial = 0; const trace: any[] = [];
  async function command(child: ChildProcess, action: string) { const token = ++serial, result = receive(child, value => value.serial === token);
    child.send({ command: action, serial: token }); const value = await result; assert.equal(value.error, undefined); trace.push(value); return value; }
  const observer = new Store(root); t.after(() => observer.close());
  if (paused) {
    await Promise.all(children.map(child => command(child, "pause")));
    const stopped = await Promise.all(children.map(child => command(child, "tick")));
    assert.equal(requests.length, 0); assert.equal(observer.claims().length, 0); assert.ok(stopped.every(value => value.state.status === "PAUSED" && value.sends === 0));
    await command(children[0], "resume");
    const first = await Promise.all(children.map(child => command(child, "tick")));
    assert.equal(requests.length, 1); assert.equal(first[0].state.status, "RUNNING"); assert.ok(first.slice(1).every(value => value.state.status === "PAUSED"));
    assert.equal(observer.claims().length, 1); assert.equal(requests[0].id, "parent-0");
  } else {
    const first = await Promise.all(children.map(child => command(child, "tick")));
    const winner = first.findIndex(value => value.sends === 1);
    for (const id of ["REC-013", "T24"]) evidence(id, () => {
      assert.equal(new Set(ready.map(value => value.pid)).size, 10); assert.equal(requests.length, 1);
      assert.equal(first.filter(value => value.state.status === "RUNNING").length, 1); assert.equal(observer.claims().length, 1);
      assert.equal(observer.claims()[0].intent_id, requests[0].intent); assert.ok(first.filter((_, index) => index !== winner).every(value => value.sends === 0 && value.state.status === "WAITING_QUOTA"));
    });
    await command(children[winner], "settle"); assert.equal(observer.claims().length, 0);
    const second = await Promise.all(children.map(child => command(child, "tick")));
    for (const id of ["REC-013", "T24"]) evidence(id, () => {
      assert.equal(requests.length, 2); assert.notEqual(requests[0].id, requests[1].id);
      assert.equal(observer.claims().length, 1); assert.equal(observer.claims()[0].intent_id, requests[1].intent);
      assert.equal(second[winner].state.status, "DONE"); assert.equal(second.filter(value => value.state.status === "RUNNING").length, 1);
      assert.equal(second.reduce((sum, value) => sum + value.sends, 0), 2);
    });
  }
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) { const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "recovery-observers"); mkdirSync(path, { recursive: true });
    writeFileSync(join(path, paused ? "all-paused-processes.json" : "ten-process-permit.json"), JSON.stringify({ ready, requests, trace, claims: observer.claims() }, null, 2)); }
});
