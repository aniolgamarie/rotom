import { test, assert, matrixCase } from "./recorded-test.ts";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { TaskService } from "../src/orchestration/service.ts";
import { Scheduler } from "../src/orchestration/scheduler.ts";
import { Store } from "../src/store/database.ts";
import { verificationInputs } from "../src/verification/inputs.ts";
import { configured } from "./fixtures/config.ts";
import { barrier, isolatedDirectory } from "./helpers.ts";

for (const action of ["pause", "stop", "dispose"] as const) for (const order of ["revoke-first", "await-first"] as const)
test(`[S REC-019] snapshot ${action} / ${order} preserves the current control decision`, async t => matrixCase("await-orders", `R09.${action}.${order}`, async () => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"); mkdirSync(cwd); execFileSync("git", ["init", "-q", cwd]);
  const store = new Store(join(root, "state")), config = configured(); config.features.managedWorkflows = true;
  for (const role of ["worker", "reviewer"]) {
    config.roles[role] = { route: "primary", profileRef: role };
    config.executionProfiles[role] = { tools: [], requiredCapabilities: [], timeoutMs: 1000, maxModelTurns: 1, toolTimeoutMs: 1000, thinking: "off" };
  }
  config.verificationBindings.build = { executable: process.execPath, args: ["-e", ""], environment: {}, timeoutMs: 1000, kind: "build", parser: "exit-code", minimumTests: 1 };
  config.verificationBindings["focused-tests"] = { ...config.verificationBindings.build, kind: "tests", parser: "json" };
  const ctx = { cwd, modelRegistry: { find: () => undefined }, sessionManager: { getBranch: () => [], getHeader: () => null,
    getSessionId: () => "session", getSessionFile: () => null } } as unknown as ExtensionContext;
  const service = new TaskService({ appendEntry() {} } as unknown as ExtensionAPI, store, config, ctx);
  const internal = service as unknown as { wake(): void; capture(): Promise<unknown> }; internal.wake = () => {};
  t.after(async () => { await service.dispose(); store.close(); });
  const job = service.submit("fix", "Snapshot control fixture"), owner = store.owner(job.workScope)!;
  const queue = new Scheduler(store, owner); queue.submit({ id: job.id, workScope: job.workScope, version: 1, objective: job.goal, workflow: "fix",
    required: ["focused-tests"], optional: [], allowPartial: false, policyDigest: job.policyDigest, snapshot: "tree", maxSteps: 16, maxSemanticAttempts: 3 },
  [{ id: "focused-tests", role: "verify", kind: "verify", optional: false, dependencies: [], allowedSkippedDependencies: [], resources: [] }], 0, 0);
  store.put("managed-jobs", job.id, { ...job, cwd, snapshot: "tree", baselineTree: "baseline", checkInputsDigest: verificationInputs(config.verificationBindings, cwd).digest });
  service.pause(job.id);
  const snapshot = barrier<{ snapshot: { id: string }; patch: string }>(), trace: string[] = [];
  internal.capture = async () => { trace.push("snapshot-requested"); const value = await snapshot.promise; trace.push("snapshot-returned"); return value; };
  const pending = service.resume(job.id);
  const control = async () => { trace.push("control"); if (action === "dispose") await service.dispose(); else service.pause(job.id, action === "stop"); };
  if (order === "revoke-first") {
    const rejected = assert.rejects(pending, { code: action === "dispose" ? "SERVICE_DISPOSED" : "RESUME_CONTROL_REVOKED" });
    await control(); snapshot.resolve({ snapshot: { id: "tree" }, patch: "" }); await rejected;
  } else {
    snapshot.resolve({ snapshot: { id: "tree" }, patch: "" }); await pending;
    assert.equal(service.get(job.id).status, "RUNNING"); await control();
  }
  assert.equal(service.get(job.id).status, action === "stop" ? "CANCELLED" : "PAUSED");
  assert.equal(queue.job(job.id).paused, true); assert.equal(queue.job(job.id).dispatched, 0);
  assert.equal(service.get(job.id).semanticAttempts, 1); assert.equal(service.get(job.id).receipt, null);
  assert.equal(trace.indexOf("control") < trace.indexOf("snapshot-returned"), order === "revoke-first");
}));
