import { test, assert } from "./recorded-test.ts";
import { intentDispatchable } from "../src/contracts/intents.ts";
const owner = { scopeId: "task", epoch: 1, token: "controller" };

for (const [id, kind] of [["T39", "start"], ["T40", "continue"], ["T71", "verify"]])
test(`[U ${id}] ${kind} with a sent uncertain or unnotified terminal intent cannot enter dispatch again`, () => {
  for (const status of ["sent", "unknown", "acked", "settled", "not_sent"]) {
    const intent = { id: "original-intent", scopeId: "task", epoch: 1, kind, status, nativeId: status === "acked" || status === "settled" ? "native" : null };
    const before = structuredClone(intent); assert.equal(intentDispatchable(owner, intent), false); assert.deepEqual(intent, before);
  }
  const prepared = { scopeId: "task", epoch: 1, status: "prepared" };
  assert.equal(intentDispatchable(owner, prepared), true);
  assert.equal(intentDispatchable(owner, null), false);
  assert.equal(intentDispatchable(owner, { ...prepared, epoch: 2 }), false);
  assert.equal(intentDispatchable(owner, { ...prepared, scopeId: "other-task" }), false);
});
