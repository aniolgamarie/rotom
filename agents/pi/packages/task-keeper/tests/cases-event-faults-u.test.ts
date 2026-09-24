import { test, assert } from "./recorded-test.ts";
import { classifyEventAppend, eventSequenceGaps } from "../src/contracts/events.ts";
import { outcome } from "../src/contracts/task.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";

test("[U T14] a completed native status cannot fill a sequence hole or a disconnected observation channel", () => {
  const { spec, facts } = acceptedCandidate(), original = structuredClone(facts);
  const events = [{ producer: "worker", seq: 1 }, { producer: "worker", seq: 3 }];
  assert.deepEqual(eventSequenceGaps(events), [{ producer: "worker", expected: 2, actual: 3 }]);
  for (const gaps of [["worker:missing-sequence-2"], ["native-observation-channel-disconnected"]]) {
    const incomplete = { ...facts, observation: { complete: false, gaps } }, result = outcome(spec, incomplete);
    assert.equal(incomplete.nativeStatus, "completed"); assert.equal(result.status, "BLOCKED");
    assert.ok(result.reasons.includes("observation_incomplete")); assert.equal(incomplete.terminationConfirmed, true);
  }
  assert.deepEqual(eventSequenceGaps([events[0], { producer: "worker", seq: 2 }, events[1]]), []);
  assert.equal(outcome(spec, facts).status, "COMPLETED"); assert.deepEqual(facts, original);
});

test("[U T15] replayed completion is a duplicate fact while conflicting completion content remains a conflict", () => {
  const event = { id: "completion", producer: "native", seq: 1, scopeId: "scope", kind: "completed", payload: { nativeId: "original-run", intentId: "original-intent", outcome: "failed" } };
  const first = classifyEventAppend(event, []); assert.equal(first.status, "inserted");
  const recorded = [{ hash: first.hash, scopeId: event.scopeId }], original = structuredClone({ event, recorded });
  for (const replay of [structuredClone(event), JSON.parse(JSON.stringify(event)), { ...event, payload: { outcome: "failed", intentId: "original-intent", nativeId: "original-run" } }]) {
    const result = classifyEventAppend(replay, recorded); assert.equal(result.status, "duplicate"); assert.equal(result.hash, first.hash); assert.deepEqual(result.conflictScopes, []);
  }
  const changed = classifyEventAppend({ ...event, payload: { ...event.payload, outcome: "passed" } }, recorded);
  assert.equal(changed.status, "conflict"); assert.deepEqual(changed.conflictScopes, ["scope"]);
  assert.deepEqual({ event, recorded }, original);
});
