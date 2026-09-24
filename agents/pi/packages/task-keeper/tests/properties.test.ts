import { test, assert } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory, seededRandom, listenLoopback } from "./helpers.ts";
import { installHttpTransport } from "../src/adapters/http-transport.ts";
import { createServer } from "node:http";
import { once } from "node:events";

for (const seed of [1, 29, 107, 65537]) test(`[S RTB-013] seed ${seed} preserves budget conservation across reordered/duplicate facts`, (t) => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  let owner = store.claimOwner("scope", "owner"); const random = seededRandom(seed), ledger = new Map<string, string>();
  let serial = 0;
  for (let turn = 0; turn < 150; turn++) {
    const unsettled = [...ledger].filter(([, state]) => state === "reserved" || state === "unknown");
    const charged = [...ledger].filter(([, state]) => state === "sent").length;
    if (random() < 0.45 && charged + unsettled.length < 12) {
      const id = `r-${++serial}`; store.prepare(owner, id, "request", {});
      store.reserveRequest(owner, id, id, [{ id: "budget", ceiling: 12 }]); ledger.set(id, "reserved");
    } else if (unsettled.length) {
      const [id] = unsettled[Math.floor(random() * unsettled.length)];
      const value = random(), fact = value < 0.25 ? "unknown" : value < 0.6 ? "not_sent" : "sent";
      store.settleRequest(id, fact); store.settleRequest(id, fact); ledger.set(id, fact);
    }
    if (random() < 0.1) { store.revokeOwner(owner); owner = store.claimOwner("scope", `owner-${turn}`); }
    const expectedUsed = [...ledger.values()].filter((state) => state === "sent").length;
    const expectedReserved = [...ledger.values()].filter((state) => state === "reserved" || state === "unknown").length;
    const bucket = store.bucket("budget");
    assert.equal(Number(bucket?.used ?? 0), expectedUsed, `seed ${seed}, turn ${turn}`);
    assert.equal(Number(bucket?.reserved ?? 0), expectedReserved, `seed ${seed}, turn ${turn}`);
    assert.ok(expectedUsed + expectedReserved <= 12);
  }
});

test("[A V VAL-014] independent receiver detects a deliberately swallowed gate rejection", async (t) => {
  const original = globalThis.fetch; let received = 0;
  const server = createServer((req, res) => { received++; req.resume(); req.on("end", () => res.end("ok")); });
  await listenLoopback(server);
  const baseUrl = `http://127.0.0.1:${(server.address() as { port: number }).port}`;
  const gate = installHttpTransport(() => ({ baseUrl, model: "fixture", token: 1 }), { before: () => { throw new Error("denied"); } }, true);
  t.after(() => { gate.dispose(); server.closeAllConnections(); server.close(); });
  const url = `${baseUrl}/chat/completions`, options = { method: "POST", body: '{"model":"fixture"}' };
  await assert.rejects(fetch(url, options)); assert.equal(received, 0);
  // Negative control represents an unsafe backend ignoring the rejected transport boundary.
  try { await fetch(url, options); } catch { await original(url, options); }
  assert.equal(received, 1); assert.throws(() => assert.equal(received, 0));
});
