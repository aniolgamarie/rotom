import { test, assert } from "./recorded-test.ts";
import { classifyEventAppend, eventSequenceGaps, type FactEvent } from "../src/contracts/events.ts";

const original: FactEvent = { id: "event-a", producer: "worker", seq: 1, scopeId: "scope-a", kind: "failed", payload: { count: 1, error: "required check failed" } };

test("[U EVD-001] canonical event replay is idempotent and missing sequences stay explicit until the facts arrive", () => {
  const snapshot = structuredClone(original), first = classifyEventAppend(original, []);
  assert.equal(first.status, "inserted"); assert.deepEqual(first.conflictScopes, []);
  const replay = { ...original, payload: { error: "required check failed", count: 1 } };
  assert.deepEqual(classifyEventAppend(replay, [{ hash: first.hash, scopeId: "scope-a" }]), { status: "duplicate", hash: first.hash, conflictScopes: [] });
  const events = [{ producer: "worker", seq: 1 }, { producer: "worker", seq: 3 }, { producer: "reviewer", seq: 2 }];
  const before = structuredClone(events);
  assert.deepEqual(eventSequenceGaps(events), [{ producer: "worker", expected: 2, actual: 3 }, { producer: "reviewer", expected: 1, actual: 2 }]);
  assert.deepEqual(eventSequenceGaps([events[0], { producer: "worker", seq: 2 }, events[1], events[2]]), [{ producer: "reviewer", expected: 1, actual: 2 }]);
  assert.deepEqual(eventSequenceGaps([events[0], { producer: "worker", seq: 2 }, events[1], { producer: "reviewer", seq: 1 }, events[2]]), []);
  assert.deepEqual(eventSequenceGaps([]), []); assert.deepEqual(events, before); assert.deepEqual(original, snapshot);
});

test("[U EVD-002] every critical identity or payload difference conflicts and both matching rows retain their scope fences", () => {
  const first = classifyEventAppend(original, []), match = { hash: first.hash, scopeId: "scope-a" };
  for (const delta of [{ id: "event-b" }, { producer: "other" }, { seq: 2 }, { scopeId: "scope-new" }, { kind: "passed" }, { payload: { count: 1, error: "" } }]) {
    const event = { ...original, ...delta }, before = structuredClone(event), result = classifyEventAppend(event, [match]);
    assert.equal(result.status, "conflict"); assert.notEqual(result.hash, first.hash);
    assert.deepEqual(result.conflictScopes, delta.scopeId ? ["scope-new", "scope-a"] : ["scope-a"]); assert.deepEqual(event, before);
  }
  const matches = [match, { hash: "different", scopeId: "scope-b" }], before = structuredClone(matches);
  assert.deepEqual(classifyEventAppend(original, matches).conflictScopes, ["scope-a", "scope-b"]);
  assert.equal(classifyEventAppend(original, matches).status, "conflict");
  assert.deepEqual(classifyEventAppend({ ...original, scopeId: "scope-new" }, matches).conflictScopes, ["scope-new", "scope-a", "scope-b"]);
  assert.deepEqual(matches, before); assert.deepEqual(match, { hash: first.hash, scopeId: "scope-a" });
});
