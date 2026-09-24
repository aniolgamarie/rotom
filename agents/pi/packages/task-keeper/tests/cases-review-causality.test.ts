import { test, assert } from "./recorded-test.ts";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { digest } from "../src/contracts/primitives.ts";
import { presentedReads, readBeforeVerdict } from "../src/verification/read-causality.ts";
import { validateReview } from "../src/verification/review.ts";
import type { DelegationResult } from "../src/adapters/subagents.ts";
import type { ReadDelivery } from "../src/adapters/child-contract.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[U WFL-009] only a matching completed tool result in the actual provider payload can count as presented evidence", () => {
  const read = { toolCallId: "read", payloadDigest: digest("actual evidence"), readRequest: 1 };
  const message = { role: "tool", tool_call_id: "read", content: "actual evidence" };
  assert.deepEqual(presentedReads([read], { messages: [message] }, 2), [read]);
  assert.deepEqual(presentedReads([read], { messages: [{ ...message, content: [{ type: "text", text: "actual evidence" }] }] }, 2), [read]);
  for (const change of [{ role: "user" }, { tool_call_id: "other" }, { content: "truncated or replaced" }, { content: null }])
    assert.deepEqual(presentedReads([read], { messages: [{ ...message, ...change }] }, 2), []);
  assert.deepEqual(presentedReads([read], { messages: [message] }, 1), []);
  assert.deepEqual(presentedReads([read], {}, 2), []);
});

test("[U WFL-009] reading and producing a verdict in the same response has no causal evidence credit", () => {
  const read: ReadDelivery = { toolCallId: "read", payloadDigest: digest("evidence"), readRequest: 1, deliveredRequest: 2 };
  assert.equal(readBeforeVerdict(read, 2), true); assert.equal(readBeforeVerdict(read, 3), true);
  for (const change of [{ toolCallId: undefined }, { payloadDigest: undefined }, { readRequest: undefined }, { deliveredRequest: undefined },
    { readRequest: 2 }, { deliveredRequest: 1 }, { deliveredRequest: 3 }]) assert.equal(readBeforeVerdict({ ...read, ...change }, 2), false);
});

test("[S WFL-009] review validation requires file and artifact delivery before the matching successful verdict", t => {
  const cwd = isolatedDirectory(t); writeFileSync(join(cwd, "source.txt"), "observed source\n");
  const { spec } = acceptedCandidate(), report = { verdict: "pass", snapshot: spec.snapshot, summary: "verified", scopeComplete: true,
    findings: [], evidence: [{ path: "source.txt", startLine: 1, endLine: 1 }], unverified: [] };
  const proof = { toolCallId: "read", payloadDigest: digest("delivered bytes"), readRequest: 1, deliveredRequest: 2 };
  const result = { status: "ended", terminationConfirmed: true, content: { kind: "structured", value: report }, observations: [{
    fileReads: [{ path: "source.txt", firstLine: 1, lastLine: 1, ...proof }], artifactReads: [{ id: "required", start: 0, end: 4, total: 4, ...proof }],
    structuredOutputs: [{ toolCallId: "verdict", requestOrdinal: 2, valueDigest: digest(report) }],
  }] } as unknown as DelegationResult;
  assert.equal(validateReview(result, spec, cwd, "required").passed, true);
  for (const kind of ["same-response", "late-artifact", "late-file", "different-verdict", "missing-verdict"] as const) {
    const changed = structuredClone(result), observation = changed.observations[0];
    if (kind === "same-response") { observation.fileReads[0].readRequest = 2; observation.artifactReads[0].readRequest = 2; }
    if (kind === "late-artifact") observation.artifactReads[0].deliveredRequest = 3;
    if (kind === "late-file") observation.fileReads[0].deliveredRequest = 3;
    if (kind === "different-verdict") observation.structuredOutputs![0].valueDigest = digest("other report");
    if (kind === "missing-verdict") delete observation.structuredOutputs;
    assert.throws(() => validateReview(changed, spec, cwd, "required"), { code: kind.includes("verdict") ? "REVIEW_VERDICT_NOT_OBSERVED" : "REVIEW_EVIDENCE_NOT_DELIVERED" });
  }
});
