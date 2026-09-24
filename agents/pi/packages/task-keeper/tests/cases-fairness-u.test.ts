import { test, assert, evidence } from "./recorded-test.ts";
import { selectReadyCandidate, MAX_BASE_PRIORITY } from "../src/orchestration/fairness.ts";

test("[U SCH-006 TK03] continuously eligible old work eventually beats every newly arriving bounded priority", () => {
  const old = { jobId: "old", stepId: "work", priority: 0, readyAt: 0 };
  for (const id of ["SCH-006", "TK03"]) evidence(id, () => {
    for (const agingMs of [1, 10, 60000]) {
      const before = structuredClone(old), prior = MAX_BASE_PRIORITY * agingMs - 1;
      assert.equal(selectReadyCandidate([old, { jobId: "fresh", stepId: "work", priority: MAX_BASE_PRIORITY, readyAt: prior }], prior, agingMs)!.jobId, "fresh");
      for (let round = MAX_BASE_PRIORITY; round < MAX_BASE_PRIORITY + 5; round++) {
        const now = round * agingMs, result = selectReadyCandidate([old, { jobId: `fresh-${round}`, stepId: "work", priority: MAX_BASE_PRIORITY, readyAt: now }], now, agingMs)!;
        assert.equal(result.jobId, "old"); assert.equal(result.effectivePriority, round); assert.equal(result.readyAt, 0);
        assert.equal(result.reason, "priority+ready-aging; ready-time; stable-id");
      }
      assert.deepEqual(old, before);
    }
  });
});

test("[U SCH-006] ready-time and stable identities break ties without mutating candidates or inventing negative age", () => {
  const candidates = [{ jobId: "b", stepId: "z", priority: 1, readyAt: 100 }, { jobId: "a", stepId: "z", priority: 1, readyAt: 100 },
    { jobId: "a", stepId: "a", priority: 1, readyAt: 100 }], before = structuredClone(candidates);
  assert.equal(selectReadyCandidate(candidates, 109, 10)!.stepId, "a"); assert.equal(selectReadyCandidate(candidates, 109, 10)!.effectivePriority, 1);
  assert.equal(selectReadyCandidate([...candidates].reverse(), 110, 10)!.effectivePriority, 2);
  assert.equal(selectReadyCandidate([{ jobId: "earlier", stepId: "work", priority: 1, readyAt: 99 }, ...candidates], 109, 100)!.jobId, "earlier");
  assert.equal(selectReadyCandidate(candidates, 90, 10)!.effectivePriority, 1); assert.deepEqual(candidates, before); assert.equal(selectReadyCandidate([], 0, 10), null);
  for (const priority of [-1, 101, Infinity]) assert.throws(() => selectReadyCandidate([{ ...candidates[0], priority }], 100, 10), { code: "INVALID_INTEGER" });
  for (const agingMs of [0, 0.5, 2147483648]) assert.throws(() => selectReadyCandidate(candidates, 100, agingMs), { code: "INVALID_INTEGER" });
});
