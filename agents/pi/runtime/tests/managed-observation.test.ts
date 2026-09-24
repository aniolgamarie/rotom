import assert from "node:assert/strict";
import { test } from "node:test";
import { ManagedObservation } from "../managed-observation.ts";
import { descriptor } from "./fixtures.ts";

test("a file read becomes review evidence only after matching delivery in a later real request", () => {
  const observation = new ManagedObservation(descriptor(), null);
  observation.response({ phase: "response_headers", request_id: "first", ordinal: 1, status: 200, headers: {} });
  const result = { content: [{ type: "text", text: "source line" }], details: { content_digest: "a".repeat(64),
    read: { kind: "file", path: "src/a", first_line: 1, last_line: 1, start: 0, end: 11, total: 11 } } };
  observation.tool("tk_read", "read-call", {}, result);
  assert.equal(observation.snapshot().reads[0].delivered_request, null);
  observation.delivered({ ordinal: 2, payload: { messages: [{ role: "tool", tool_call_id: "read-call", content: "different text" }] } });
  assert.equal(observation.snapshot().reads[0].delivered_request, null);
  observation.delivered({ ordinal: 2, payload: { messages: [{ role: "tool", tool_call_id: "read-call", content: "source line" }] } });
  assert.equal(observation.snapshot().reads[0].delivered_request, 2);
  observation.response({ phase: "response_headers", request_id: "second", ordinal: 2, status: 200, headers: {} });
  observation.tool("structured_output", "verdict", { verdict: "pass" }, { content: [] });
  assert.equal(observation.snapshot().structured_outputs[0].request_ordinal, 2);
});

test("committed request with no response and pre-send denial remain distinguishable", () => {
  const observation = new ManagedObservation(descriptor(), null);
  observation.response({ phase: "request_committed", request_id: "network", ordinal: 1 });
  observation.response({ phase: "request_denied", request_id: "budget", ordinal: null, code: "BUDGET_EXHAUSTED" });
  const saved = observation.snapshot();
  assert.equal(saved.requests[0].status, null);
  assert.equal(saved.last_response, null);
  assert.deepEqual(saved.request_denials, [{ request_id: "budget", code: "BUDGET_EXHAUSTED" }]);
});
