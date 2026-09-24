import { test, assert } from "./recorded-test.ts";
import { successfulRecoveryTerminal, classify, type FailureSignal } from "../src/reliability/classifier.ts";

test("[U T22] a successful short probe cannot substitute for the long request's quota terminal", () => {
  const canary: FailureSignal = { status: 200, stream: "complete", message: "short probe passed" };
  const longRequest: FailureSignal = { status: 429, stream: "error", message: "long request still limited", headers: { "retry-after": "2" } };
  const before = structuredClone({ canary, longRequest });
  assert.equal(successfulRecoveryTerminal(canary), true);
  assert.equal(successfulRecoveryTerminal(longRequest), false);
  assert.equal(classify(longRequest, [], 1000).category, "frequency_limit");
  assert.equal(classify(longRequest, [], 1000).retryAt, 3000);
  assert.deepEqual({ canary, longRequest }, before);
  assert.equal(successfulRecoveryTerminal({ ...longRequest, status: 200, stream: "complete" }), true);
});

test("[U T18] a settled native retry success is terminal success without preserving an earlier quota failure as a new retry", () => {
  const failed: FailureSignal = { status: 429, message: "earlier attempt", stream: "error" };
  assert.equal(successfulRecoveryTerminal(failed), false);
  for (const terminal of [null, { status: 200, message: "native retry succeeded", stream: "complete" as const }]) {
    const before = structuredClone(terminal);
    assert.equal(successfulRecoveryTerminal(terminal), true); assert.deepEqual(terminal, before);
  }
  assert.deepEqual(failed, { status: 429, message: "earlier attempt", stream: "error" });
});

test("[U T23] HTTP success with a failed or incomplete stream never proves recovery", () => {
  for (const status of [undefined, 200, 299, 399, 400, 429, 500]) for (const stream of ["complete", "error", "incomplete"] as const) {
    const signal = { status, stream, message: "terminal observation" }, before = structuredClone(signal);
    const expected = stream === "complete" && (status === undefined || [200, 299, 399].includes(status));
    assert.equal(successfulRecoveryTerminal(signal), expected, `${status}:${stream}`); assert.deepEqual(signal, before);
  }
});
