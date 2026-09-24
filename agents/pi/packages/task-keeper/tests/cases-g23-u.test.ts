import { test, assert, evidence } from "./recorded-test.ts";
import { requestBudgetAvailable, requestSettlement } from "../src/contracts/budget.ts";

test("[U RTB-008 T29] every distinct primary retry summary and compaction consumes the shared allowance once", () => {
  // Unit accounting facts only. Actual SDK request interception is covered at A/P.
  const bucket = { used: 0, reserved: 0, ceiling: 4 };
  for (const purpose of ["primary", "native-retry", "summary", "compaction"]) {
    for (const id of ["RTB-008", "T29"]) evidence(id, () => assert.equal(requestBudgetAvailable(bucket), true, purpose));
    bucket.reserved++;
    const unknown = requestSettlement("reserved", "unknown");
    const sent = requestSettlement(unknown.state, "sent");
    bucket.used += sent.usedDelta; bucket.reserved += sent.reservedDelta;
    for (const id of ["RTB-008", "T29"]) evidence(id, () => {
      assert.equal(unknown.reservedDelta, 0); assert.equal(unknown.usedDelta, 0);
      assert.equal(sent.usedDelta, 1); assert.equal(sent.reservedDelta, -1);
      assert.deepEqual(requestSettlement("sent", "sent"), { changed: false, state: "sent", usedDelta: 0, reservedDelta: 0 });
    });
  }
  for (const id of ["RTB-008", "T29"]) evidence(id, () => {
    assert.deepEqual(bucket, { used: 4, reserved: 0, ceiling: 4 }); assert.equal(requestBudgetAvailable(bucket), false);
  });
});

for (const id of ["RTB-009", "RTB-010", "T28"]) test(`[U ${id}] TC-${id}-U the last configured request is available but the next is rejected`, () => {
  for (const ceiling of [0, 1, 4, 12]) for (let used = 0; used <= ceiling + 1; used++) {
    const bucket = { used, reserved: 0, ceiling }, before = structuredClone(bucket);
    assert.equal(requestBudgetAvailable(bucket), used < ceiling); assert.deepEqual(bucket, before);
  }
  assert.equal(requestBudgetAvailable({ used: 3, reserved: 0, ceiling: 4 }), true);
  assert.equal(requestBudgetAvailable({ used: 4, reserved: 0, ceiling: 4 }), false);
});
for (const id of ["RTB-011", "T31"]) test(`[U ${id}] TC-${id}-U unknown reservations occupy the remaining request allowance`, () => {
  const bucket = { used: 2, reserved: 2, ceiling: 4 };
  assert.equal(requestBudgetAvailable(bucket), false);
  assert.equal(requestBudgetAvailable({ ...bucket, reserved: 1 }), true);
  assert.deepEqual(bucket, { used: 2, reserved: 2, ceiling: 4 });
  assert.equal(requestBudgetAvailable({ used: 0, reserved: 4, ceiling: 4 }), false);
});
for (const id of ["RTB-018", "T82"]) test(`[U ${id}] TC-${id}-U optional requests cannot consume the required acceptance reserve`, () => {
  for (const used of [0, 1, 2, 3, 4]) {
    const bucket = { used, reserved: 0, ceiling: 4 };
    assert.equal(requestBudgetAvailable(bucket, 2), used < 2);
    assert.equal(requestBudgetAvailable(bucket, 0), used < 4);
  }
  assert.equal(requestBudgetAvailable({ used: 0, reserved: 1, ceiling: 4 }, 2), true);
  assert.equal(requestBudgetAvailable({ used: 1, reserved: 1, ceiling: 4 }, 2), false);
});
test("[U] budget predicate rejects lossy values and arithmetic boundaries without mutating the ledger snapshot", () => {
  for (const field of ["used", "reserved", "ceiling"] as const) for (const value of [-1, 0.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])
    assert.throws(() => requestBudgetAvailable({ used: 0, reserved: 0, ceiling: 4, [field]: value }));
  for (const reserve of [-1, NaN, Infinity]) assert.throws(() => requestBudgetAvailable({ used: 0, reserved: 0, ceiling: 4 }, reserve));
  const max = Number.MAX_SAFE_INTEGER;
  assert.equal(requestBudgetAvailable({ used: max - 1, reserved: 0, ceiling: max }), true);
  assert.equal(requestBudgetAvailable({ used: max - 1, reserved: 1, ceiling: max }), false);
  assert.equal(requestBudgetAvailable({ used: max, reserved: max, ceiling: max }, max), false);
});
