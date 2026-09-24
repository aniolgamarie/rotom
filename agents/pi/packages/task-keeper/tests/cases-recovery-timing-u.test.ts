import { test, assert, evidence } from "./recorded-test.ts";
import { recoveryTiming, type RecoveryTiming } from "../src/reliability/timing.ts";
const base: RecoveryTiming = { now: 1100, monotonic: 100, previousWall: 1000, previousMonotonic: 0,
  notBefore: 1200, sharedNotBefore: 0, deadlineAt: null };

test("[U REC-009 T25] wall rollback postpones the original wait and never replays elapsed ticks", () => {
  const cases: Array<[Partial<RecoveryTiming>, {action: string; notBefore: number}]> = [
    [{}, { action: "wait", notBefore: 1200 }],
    [{ now: 900 }, { action: "wait", notBefore: 1400 }],
    [{ now: 900, sharedNotBefore: 1500 }, { action: "wait", notBefore: 1500 }],
    [{ now: 1199, monotonic: 199 }, { action: "wait", notBefore: 1200 }],
    [{ now: 1200, monotonic: 200 }, { action: "ready", notBefore: 1200 }],
    [{ now: 9000, monotonic: 8000 }, { action: "ready", notBefore: 1200 }],
    [{ now: 1100, monotonic: 100.75 }, { action: "wait", notBefore: 1200 }],
    [{ now: 900, monotonic: 0, previousMonotonic: 100 }, { action: "wait", notBefore: 1300 }],
  ];
  for (const id of ["REC-009", "T25"]) evidence(id, () => {
    for (const [patch, expected] of cases) { const input = { ...base, ...patch }, before = structuredClone(input);
      assert.deepEqual(recoveryTiming(input), expected); assert.deepEqual(input, before); }
  });
});

test("[U REC-011] an overall deadline takes precedence over both quota cooldown and a ready retry", () => {
  for (const notBefore of [1000, 1200, 999999]) {
    const input = { ...base, notBefore, deadlineAt: 1100 };
    assert.deepEqual(recoveryTiming(input), { action: "deadline", notBefore });
    assert.equal(recoveryTiming({ ...input, now: 1099, monotonic: 99 }).action, notBefore <= 1099 ? "ready" : "wait");
    assert.equal(recoveryTiming({ ...input, now: 1101, monotonic: 101 }).action, "deadline");
  }
  assert.equal(recoveryTiming({ ...base, now: 1000000, monotonic: 999000 }).action, "ready");
});
