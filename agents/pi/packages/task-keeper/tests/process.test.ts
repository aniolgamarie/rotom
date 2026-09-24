import { test, assert, evidence } from "./recorded-test.ts";
import { fork, type ChildProcess } from "node:child_process";
import { once } from "node:events";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { Store } from "../src/store/database.ts";
import { createServer } from "node:http";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";

function worker(root: string, id: string, mode: string, endpoint = ""): ChildProcess {
  return fork(fileURLToPath(new URL("./fixtures/store-worker.ts", import.meta.url)), [root, id, mode, endpoint], {
    execArgv: ["--experimental-strip-types"], stdio: ["ignore", "ignore", "pipe", "ipc"],
  });
}
function receive(child: ChildProcess, type: string): Promise<Record<string, unknown>> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error(`worker timed out waiting for ${type}`)); }, 10_000);
    const exit = () => { cleanup(); reject(new Error(`worker exited before ${type}`)); };
    const message = (input: unknown) => {
      const msg = input as Record<string, unknown>;
      if (msg.type === type) { cleanup(); resolve(msg); }
    };
    const cleanup = () => { clearTimeout(timer); child.off("message", message); child.off("exit", exit); };
    child.on("message", message); child.once("exit", exit);
  });
}

test("[T24 TK07] ten real processes have one half-open winner and a loser proceeds after release", { timeout: 25_000 }, async (t) => {
  const root = isolatedDirectory(t);
  // Initialize once; concurrent process transactions still perform admission independently.
  new Store(root).close();
  const children = Array.from({ length: 10 }, (_, i) => worker(root, String(i), "compete"));
  t.after(() => { for (const child of children) child.kill("SIGKILL"); });
  await Promise.all(children.map((child) => receive(child, "ready")));
  const results = children.map((child) => receive(child, "result"));
  for (const child of children) child.send("go");
  const values = await Promise.all(results);
  for (const id of ["TK07"]) evidence(id, () => {
    assert.equal(values.filter((value) => value.acquired).length, 1);
  });
  const winner = children[values.findIndex((value) => value.acquired)];
  const loser = children[values.findIndex((value) => !value.acquired)];
  const released = receive(winner, "released"); winner.send("release"); await released;
  const resumed = receive(loser, "result"); loser.send("go"); assert.equal((await resumed).acquired, true);
  const store = new Store(root); assert.equal(store.claims().length, 1); store.close();
  const exits = children.map((child) => once(child, "exit"));
  for (const child of children) child.send("quit");
  await Promise.all(exits);
});

for (const cut of ["C0", "C1", "C2", "C3", "C4", "C5"]) {
  test(`[T39 T40 T71] actual process crash at ${cut} preserves intent and never sends twice`, { timeout: 15_000 }, async (t) => {
    const root = isolatedDirectory(t), child = worker(root, "crash", cut);
    let acknowledgementReceived = false;
    child.on("message", (message: { type?: string }) => { if (message.type === "native_ack") acknowledgementReceived = true; });
    t.after(() => child.kill("SIGKILL"));
    await receive(child, "ready"); const reached = receive(child, "cut"); child.send("go"); await reached;
    const stopped = once(child, "exit"); child.kill("SIGKILL"); await stopped;
    const store = new Store(root); t.after(() => store.close());
    const intent = store.intent("intent-crash");
    for (const id of ["T39", "T71"]) evidence(id, () => {
      assert.equal(acknowledgementReceived, ["C3", "C4", "C5"].includes(cut));
    });
    const sends = existsSync(join(root, "external-sends.txt")) ? readFileSync(join(root, "external-sends.txt"), "utf8").trim().split("\n").length : 0;
    if (cut === "C0") {
      assert.equal(intent, null); assert.equal(store.get("probe", "uncommitted"), null); assert.equal(sends, 0);
    } else if (cut === "C1") {
      assert.equal(intent!.status, "prepared"); assert.equal(sends, 0);
      store.settle("intent-crash", "not_sent"); assert.equal(store.claims().length, 0);
    } else {
      assert.equal(sends, 1);
      if (cut === "C5") { assert.equal(intent!.status, "settled"); assert.equal(store.claims().length, 0); }
      else {
        assert.equal(store.claims().length, 1);
        // The independent receiver's durable record is the acknowledgement evidence.
        store.acknowledge("intent-crash", "native-crash");
        store.settle("intent-crash", "terminated"); assert.equal(store.claims().length, 0);
      }
      assert.equal(readFileSync(join(root, "external-sends.txt"), "utf8"), "crash\n");
    }
  });
}

test("[P RTB-011 T30 T31] actual HTTP and two-process last-budget competition retain unknown reservations", { timeout: 20000 }, async (t) => {
  const root = isolatedDirectory(t); new Store(root).close(); let requests = 0;
  const server = createServer((req, res) => { requests++; req.resume(); req.on("end", () => res.end("ack")); });
  await listenLoopback(server);
  t.after(() => { server.closeAllConnections(); server.close(); });
  const endpoint = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
  const first = worker(root, "request-first", "budget-unknown", endpoint), second = worker(root, "request-second", "budget", endpoint);
  t.after(() => { first.kill("SIGKILL"); second.kill("SIGKILL"); });
  await Promise.all([receive(first, "ready"), receive(second, "ready")]);
  const cut = receive(first, "cut"); first.send("go"); await cut;
  const stopped = once(first, "exit"); first.kill("SIGKILL"); await stopped;
  const result = receive(second, "result"); second.send("go"); assert.equal((await result).acquired, false);
  const store = new Store(root); t.after(() => store.close());
  for (const id of ["RTB-011", "T30", "T31"]) evidence(id, () => {
    assert.equal(requests, 1); assert.equal(store.bucket("shared-work")?.reserved, 1); assert.equal(store.bucket("shared-work")?.used, 0);
    assert.equal(store.intent("intent-request-second")?.status, "prepared");
    assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 1);
  });
  store.settleRequest("request-request-first", "sent"); store.settleRequest("request-request-first", "sent");
  for (const id of ["RTB-011", "T30", "T31"]) evidence(id, () => {
    assert.equal(store.bucket("shared-work")?.used, 1); assert.equal(store.bucket("shared-work")?.reserved, 0);
    assert.equal(store.bucket("shared-incident")?.used, 1); assert.equal(store.bucket("shared-incident")?.reserved, 0);
    assert.equal(requests, 1);
  });
  const exit = once(second, "exit"); second.send("quit"); await exit;
});
