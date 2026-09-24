import { test, assert, evidence } from "./recorded-test.ts";
import { ownerMatches } from "../src/contracts/ownership.ts";

test("[U T35] every independent ownership mismatch rejects the old probe or model callback", () => {
  for (const id of ["T35"]) evidence(id, () => {
    const callback = { scopeId: "original-task", token: "controller", epoch: 7 }, live = { ...callback, active: true };
    const cases = [null, { ...live, active: false }, { ...live, token: "successor" },
      { ...live, epoch: 8 }, { ...live, scopeId: "new-task" }];
    for (const current of cases) {
      const before = structuredClone({ callback, current });
      assert.equal(ownerMatches(callback, current), false); assert.deepEqual({ callback, current }, before);
      assert.equal(ownerMatches(callback, live), true);
    }
    // Reusing the token cannot recover the older epoch.
    assert.equal(ownerMatches(callback, { ...live, epoch: 9 }), false);
    assert.equal(ownerMatches({ ...callback, epoch: 9 }, { ...live, epoch: 9 }), true);
  });
});

test("[U T38] late success and quota availability do not restore a cancelled owner", () => {
  for (const id of ["T38"]) evidence(id, () => {
    const callback = { scopeId: "task", token: "controller", epoch: 1 };
    for (const active of [false, true]) for (const nativeSuccess of [false, true]) for (const quotaRecovered of [false, true]) {
      const current = { ...callback, epoch: 2, active, nativeSuccess, quotaRecovered };
      const before = structuredClone(current);
      assert.equal(ownerMatches(callback, current), false); assert.deepEqual(current, before);
    }
    assert.equal(ownerMatches(callback, { ...callback, active: true }), true);
    assert.equal(ownerMatches(callback, { ...callback, active: false }), false);
  });
});

test("[U T49] a second controller needs the exact current owner and cannot borrow a matching job or epoch", () => {
  for (const id of ["T49"]) evidence(id, () => {
    const current = { scopeId: "same-job", token: "original-controller", epoch: 7, active: true };
    const before = structuredClone(current);
    for (const token of ["fallback", "watchdog", "other-executor"]) {
      assert.equal(ownerMatches({ scopeId: current.scopeId, token, epoch: current.epoch }, current), false);
      assert.equal(ownerMatches(current, current), true);
    }
    const successor = { ...current, token: "authorized-successor", epoch: 8 };
    assert.equal(ownerMatches(current, successor), false);
    assert.equal(ownerMatches(successor, successor), true);
    assert.deepEqual(current, before);
  });
});
