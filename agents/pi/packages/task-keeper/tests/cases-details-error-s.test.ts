import { test, assert } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import { SubagentsAdapter } from "../src/adapters/subagents.ts";
import { verificationInputs } from "../src/verification/inputs.ts";
import type { Intent } from "../src/store/database.ts";

test("[S T10] an adapter failure accompanied by Done content becomes a blocked receipt and visible error", async t => {
  const f = completedState(t), job = f.service.get(f.jobId);
  job.checkInputsDigest = verificationInputs(f.config.verificationBindings, job.cwd!).digest;
  f.store.put("managed-jobs", f.jobId, job); f.queue.retryFrom(f.jobId, "implement");
  const intent = f.queue.dispatch(f.jobId, "implement", "tree"); f.store.markSent(f.owner, intent.id);
  let calls = 0;
  t.mock.method(SubagentsAdapter.prototype, "execute", async () => {
    calls++; return { descriptorId: "failed-descriptor", nativeRunId: "native", status: "failed", terminationConfirmed: true,
      content: { kind: "text", text: "Done" }, error: "FIXTURE_REQUIRED_DETAILS_ERROR", observations: [] };
  });
  const internal = f.service as unknown as { capture(): Promise<unknown>; runStep(jobId: string, stepId: string, intent: Intent, epoch: number, signal: AbortSignal): Promise<void> };
  internal.capture = async () => ({ snapshot: { id: "tree", files: [] }, patch: "" });
  await internal.runStep(f.jobId, "implement", intent, job.controlEpoch, new AbortController().signal); f.finalize();
  const failed = f.service.get(f.jobId), shown = f.service.describe(f.jobId);
  assert.equal(calls, 1); assert.equal(failed.status, "BLOCKED"); assert.equal(failed.receipt!.status, "BLOCKED");
  assert.ok(failed.receipt!.failureHistory.some(failure => failure.message === "FIXTURE_REQUIRED_DETAILS_ERROR"));
  assert.equal(shown.status, "BLOCKED"); assert.equal(shown.reason, "FIXTURE_REQUIRED_DETAILS_ERROR");
  assert.equal(f.queue.job(f.jobId).steps.find(step => step.id === "implement")!.status, "failed");
  const raw = JSON.parse(f.artifacts.read(failed.outputs.implement, f.jobId, "tree").content.toString("utf8"));
  assert.equal(raw.content.text, "Done"); assert.equal(raw.error, "FIXTURE_REQUIRED_DETAILS_ERROR");
});
