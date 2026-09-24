import { test, assert } from "./recorded-test.ts";
import { canonical, digest, object, finiteInteger } from "../src/contracts/primitives.ts";
import { FakeClock, FakeAdapter, seededRandom } from "./helpers.ts";

test("canonical facts have deterministic digests and reject lossy JSON", () => {
  assert.equal(digest({ a: 1, b: [true] }), digest({ b: [true], a: 1 }));
  for (const v of [NaN, Infinity, undefined, { a: undefined }, new Date()]) assert.throws(() => canonical(v));
  for (const v of [-1, 0.5, Infinity, "12"]) assert.throws(() => finiteInteger(v));
  finiteInteger(0);
  assert.throws(() => object({ ignoreRequiredChecks: true }, ["enabled"]));
});

test("fake clock coalesces expired timers and cancellation removes callbacks", () => {
  const clock = new FakeClock();
  let calls = 0;
  clock.schedule(5, () => { calls++; clock.schedule(5, () => calls++); });
  const cancel = clock.schedule(5, () => calls += 100);
  cancel(); clock.advance(10_000);
  assert.equal(calls, 1);
  assert.equal(clock.pending, 1);
  clock.advance(5); assert.equal(calls, 2);
});

test("barrier preserves a late completion after a cancellation action", async () => {
  const adapter = new FakeAdapter();
  const pending = adapter.start("intent-1");
  adapter.cancel("intent-1");
  adapter.next.resolve("native-1");
  assert.equal(await pending, "native-1");
  assert.deepEqual(adapter.actions.map((a) => a.kind), ["start", "cancel"]);
  const a = seededRandom(42), b = seededRandom(42);
  assert.deepEqual(Array.from({ length: 20 }, a), Array.from({ length: 20 }, b));
});
