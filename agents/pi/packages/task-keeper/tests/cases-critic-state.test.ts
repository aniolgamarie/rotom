import { test, assert } from "./recorded-test.ts";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { completedState } from "./fixtures/service-state.ts";
import { SubagentsAdapter } from "../src/adapters/subagents.ts";
import { verificationInputs } from "../src/verification/inputs.ts";
import { digest } from "../src/contracts/primitives.ts";
import type { Intent } from "../src/store/database.ts";
import type { DelegationResult } from "../src/adapters/subagents.ts";

test("[S RTB-016] no finding or an unsupported opinion does not force a writer revision", async t => {
  for (const kind of ["none", "opinion", "unsupported", "supported"] as const) {
    const f = completedState(t, false, false, ["direct", "critique"], config => { config.roles.critic = { route: "primary", profileRef: "reviewer" }; });
    const job = f.service.get(f.jobId), plan = f.queue.job(f.jobId); writeFileSync(join(job.cwd!, "source.txt"), "observed source\n");
    job.checkInputsDigest = verificationInputs(f.config.verificationBindings, job.cwd!).digest;
    plan.steps.push({ id: "optional-critique", role: "critic", kind: "review", optional: true, dependencies: [], allowedSkippedDependencies: [], resources: [],
      status: "pending", intentId: null, readyAt: null, finishedAt: null });
    f.store.put("jobs", f.jobId, plan); f.store.put("managed-jobs", f.jobId, job);
    const intent = f.queue.dispatch(f.jobId, "optional-critique", "tree"); f.store.markSent(f.owner, intent.id);
    const report = { verdict: "pass", snapshot: "tree", summary: "independent diagnostic", scopeComplete: true, unverified: [],
      evidence: [{ path: "source.txt", startLine: 1, endLine: 1 }],
      findings: kind === "none" ? [] : [{ id: "finding", severity: "low", message: "diagnostic opinion", actionable: kind !== "opinion", evidenceIndices: kind === "unsupported" ? [] : [0] }] };
    let calls = 0;
    const mock = t.mock.method(SubagentsAdapter.prototype, "execute", async () => {
      calls++; return { descriptorId: "critic", nativeRunId: "native", status: "ended", terminationConfirmed: true,
        content: { kind: "structured", value: report }, observations: [{ toolErrors: [], artifactReads: [],
          fileReads: [{ path: "source.txt", firstLine: 1, lastLine: 1, toolCallId: "read", payloadDigest: digest("observed source"), readRequest: 1, deliveredRequest: 2 }],
          structuredOutputs: [{ toolCallId: "verdict", requestOrdinal: 2, valueDigest: digest(report) }] }] } as unknown as DelegationResult;
    });
    const internal = f.service as unknown as { capture(): Promise<unknown>; runStep(jobId: string, stepId: string, intent: Intent, epoch: number, signal: AbortSignal): Promise<void> };
    internal.capture = async () => ({ snapshot: { id: "tree", files: [] }, patch: "" });
    await internal.runStep(f.jobId, "optional-critique", intent, job.controlEpoch, new AbortController().signal); f.finalize(); mock.mock.restore();
    const final = f.service.get(f.jobId); assert.equal(calls, 1); assert.equal(final.critiquesUsed, 1);
    assert.equal(final.semanticAttempts, kind === "supported" ? 2 : 1);
    assert.equal(f.queue.job(f.jobId).steps.find(step => step.id === "implement")!.status, kind === "supported" ? "pending" : "passed");
    assert.deepEqual(f.queue.job(f.jobId).spec.required, ["build", "focused-tests", "independent-review"]);
    if (kind !== "supported") assert.equal(final.receipt!.status, "COMPLETED");
  }
});
