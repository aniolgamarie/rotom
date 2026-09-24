import { configurationPolicyDigest } from "../src/config.ts";
import { test, assert } from "./recorded-test.ts";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { TaskService, type ManagedJob } from "../src/orchestration/service.ts";
import { Store, type Owner } from "../src/store/database.ts";
import { Scheduler } from "../src/orchestration/scheduler.ts";
import { digest } from "../src/contracts/primitives.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory, barrier } from "./helpers.ts";

for (const ordering of ["control-first", "result-first"] as const) for (const control of ["pause", "stop"] as const) {
  test(`[S T38] ${control} and resume snapshot ${ordering} cannot revive cancelled work`, async t => {
    const root = isolatedDirectory(t), store = new Store(root), config = configured();
    const pi = { appendEntry() {} } as unknown as ExtensionAPI;
    const context = { cwd: root, sessionManager: { getBranch: () => [], getSessionId: () => "session", getSessionFile: () => join(root, "session.jsonl"), getHeader: () => null } } as unknown as ExtensionContext;
    const service = new TaskService(pi, store, config, context);
    const internals = service as unknown as { owner: Owner; capture: () => Promise<unknown>; wake: () => void };
    internals.wake = () => {};
    t.after(async () => { await service.dispose(); store.close(); });
    const scheduler = new Scheduler(store, internals.owner), policyDigest = configurationPolicyDigest(config);
    scheduler.submit({ id: "job", workScope: internals.owner.scopeId, version: 1, objective: "bounded", workflow: "inspect", required: ["inspect"], optional: [], allowPartial: false,
      snapshot: "snapshot", policyDigest, maxSteps: 16, maxSemanticAttempts: 3 }, [{ id: "inspect", kind: "read", role: "scout", dependencies: [], allowedSkippedDependencies: [], optional: false, resources: [] }], 0, 0);
    scheduler.pause("job");
    const job: ManagedJob = { id: "job", parentSessionId: "session", workScope: internals.owner.scopeId, workflow: "inspect", goal: "bounded", sourceCwd: root, cwd: root,
      projectId: "repo", modelBindings: {}, createdAt: 0, status: "PAUSED", reason: "paused", controlEpoch: 1, policyDigest, snapshot: "snapshot", initialSnapshot: "snapshot", baselineTree: "tree",
      patchArtifact: null, jobLease: null, checks: [], verification: {}, outputs: {}, failures: [], receipt: null, semanticAttempts: 1 };
    store.put("managed-jobs", "job", job);
    const gate = barrier<unknown>(); internals.capture = () => gate.promise;
    const resumed = service.resume("job");
    const snapshot = { snapshot: { id: "snapshot", files: [] }, patch: "" };
    if (ordering === "control-first") {
      service.pause("job", control === "stop"); gate.resolve(snapshot);
      await assert.rejects(resumed, { code: "RESUME_CONTROL_REVOKED" });
    } else {
      gate.resolve(snapshot); await resumed; assert.equal(service.get("job").status, "RUNNING"); service.pause("job", control === "stop");
    }
    assert.equal(service.get("job").status, control === "stop" ? "CANCELLED" : "PAUSED");
    assert.equal(scheduler.job("job").dispatched, 0);
    assert.equal(scheduler.job("job").cancelled, control === "stop");
    assert.equal(service.get("job").semanticAttempts, 1);
  });
}
