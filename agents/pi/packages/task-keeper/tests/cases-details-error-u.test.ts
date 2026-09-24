import { test, assert } from "./recorded-test.ts";
import { createJiti } from "jiti";
const { toSubagentDelegationResponse } = await createJiti(import.meta.url).import<any>("../node_modules/pi-subagents/src/slash/delegation-adapters.ts");

test("[U T10] the pinned native converter preserves a details-only error despite Done content and zero exit", () => {
  const request = { requestId: "request", ownerRunId: "job", nodeId: "step", result: { kind: "text" } };
  const bridge = { content: [{ type: "text", text: "Done" }], details: { runId: "native", results: [{ exitCode: 0, finalOutput: "Done", error: "required failure" }] } };
  const failed = toSubagentDelegationResponse(request, bridge, false);
  assert.equal(failed.status, "failed"); assert.equal(failed.error, "required failure"); assert.equal(failed.result, undefined);
  assert.equal(failed.runId, "native"); assert.equal(bridge.content[0].text, "Done");
  const valid = toSubagentDelegationResponse(request, { ...bridge, details: { ...bridge.details, results: [{ exitCode: 0, finalOutput: "Done" }] } }, false);
  assert.equal(valid.status, "completed"); assert.deepEqual(valid.result, { kind: "text", text: "Done" });
});
