import { test, assert } from "./recorded-test.ts";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { Store } from "../src/store/database.ts";
import { digest } from "../src/contracts/primitives.ts";
import { isolatedDirectory, seededRandom } from "./helpers.ts";

test("[S VAL-017] the same recorded settlement interleaving reproduces an injected duplicate-charge failure and passes after removing the fault", t => {
  const seed = 107, random = seededRandom(seed), order = Array.from({ length: 8 }, (_, n) => `request-${n}`);
  for (let n = order.length - 1; n > 0; n--) { const target = Math.floor(random() * (n + 1)); [order[n], order[target]] = [order[target], order[n]]; }
  const trace = order.flatMap(id => { const terminal = random() < 0.7 ? "sent" as const : "not_sent" as const;
    return [{ id, fact: "unknown" as const }, { id, fact: "unknown" as const }, { id, fact: terminal }, { id, fact: terminal }]; });
  const traceDigest = digest(trace);
  const replay = (injectDuplicateCharge: boolean) => {
    const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); const owner = store.claimOwner("scope", "owner");
    store.prepare(owner, "execution", "model", {}); const expected = new Map<string, string>();
    for (const id of order) { store.reserveRequest(owner, "execution", id, [{ id: "budget", ceiling: 12 }]); expected.set(id, "reserved"); }
    let divergence: { index: number; id: string; actual: number; expected: number } | null = null;
    for (const [index, event] of trace.entries()) {
      const duplicate = store.request(event.id)!.state === "sent" && event.fact === "sent";
      store.settleRequest(event.id, event.fact);
      if (injectDuplicateCharge && duplicate) store.db.prepare("UPDATE buckets SET used=used+1 WHERE id=?").run("budget");
      expected.set(event.id, event.fact);
      const used = [...expected.values()].filter(state => state === "sent").length;
      const reserved = [...expected.values()].filter(state => state === "reserved" || state === "unknown").length;
      const actual = store.bucket("budget")!;
      if (Number(actual.used) !== used || Number(actual.reserved) !== reserved) { divergence = { index, id: event.id, actual: Number(actual.used), expected: used }; break; }
    }
    return { seed, traceDigest, fault: injectDuplicateCharge ? "injected-duplicate-charge" : null, divergence, budget: store.bucket("budget") };
  };
  const failed = replay(true), repeated = replay(true), fixed = replay(false);
  assert.ok(failed.divergence); assert.deepEqual(repeated.divergence, failed.divergence); assert.equal(failed.traceDigest, repeated.traceDigest);
  assert.equal(failed.divergence!.actual, failed.divergence!.expected + 1); assert.equal(trace[failed.divergence!.index].fact, "sent");
  assert.equal(fixed.divergence, null); assert.equal(fixed.traceDigest, traceDigest); assert.equal(fixed.budget!.reserved, 0);
  assert.equal(fixed.budget!.used, new Set(trace.filter(event => event.fact === "sent").map(event => event.id)).size);
  if (process.env.TASK_KEEPER_TEST_RECORD_DIR) {
    const path = join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR), "state-replay-observers"); mkdirSync(path, { recursive: true });
    writeFileSync(join(path, `settlement-${seed}.json`), JSON.stringify({ seed, trace, traceDigest, failed, repeated, fixed }, null, 2));
  }
});
