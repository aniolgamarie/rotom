import type { TestContext } from "node:test";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { TaskService } from "../../src/orchestration/service.ts";
import { Scheduler } from "../../src/orchestration/scheduler.ts";
import { Store } from "../../src/store/database.ts";
import { Artifacts } from "../../src/store/artifacts.ts";
import { configured } from "./config.ts";
import type { Config } from "../../src/config.ts";
import { isolatedDirectory } from "../helpers.ts";

/** A declared post-execution state, driven through the production finalizer; not native A/E evidence. */
export function completedState(t: TestContext, allowPartial = false, fallback = false, recipes: Array<"direct" | "cascade" | "critique"> = ["direct"], tune?: (config: Config) => void) {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"); mkdirSync(cwd); execFileSync("git", ["init", "-q", cwd]);
  const store = new Store(join(root, "state")), config = configured(); config.features.managedWorkflows = true; config.workflow.allowPartial = allowPartial;
  config.workflow.optionalChecks.fix = ["extra"];
  config.workflow.recipes = recipes;
  if (fallback) {
    config.features.crossProviderFailover = true;
    config.routes.backup = { ...config.routes.primary, provider: "backup-provider", model: "backup-model", accountBinding: "provider:backup-provider", protected: true };
    config.allowedRoutes.push("backup"); config.projectRouteApprovals["*"].push("backup");
  }
  for (const role of ["worker", "reviewer"]) {
    config.roles[role] = { route: "primary", profileRef: role };
    config.executionProfiles[role] = { tools: [], requiredCapabilities: [], timeoutMs: 1000, maxModelTurns: 1, toolTimeoutMs: 1000, thinking: "off" };
  }
  if (fallback) config.roles.upgrade = { route: "backup", profileRef: "worker" };
  for (const id of ["build", "focused-tests", "extra"]) config.verificationBindings[id] = { executable: process.execPath, args: ["-e", ""], environment: {}, timeoutMs: 1000, kind: "build", parser: "exit-code", minimumTests: 1 };
  config.verificationBindings["focused-tests"].kind = "tests"; config.verificationBindings["focused-tests"].parser = "json";
  tune?.(config);
  const ctx = { cwd, modelRegistry: { find: () => undefined }, sessionManager: { getBranch: () => [], getHeader: () => null, getSessionId: () => "session", getSessionFile: () => null } } as unknown as ExtensionContext;
  const service = new TaskService({ appendEntry() {} } as unknown as ExtensionAPI, store, config, ctx);
  const internal = service as unknown as { wake(): void; finalize(id: string): void }; internal.wake = () => {};
  t.after(async () => { await service.dispose(); store.close(); });
  const job = service.submit("fix", "Completion state fixture"), owner = store.owner(job.workScope)!, queue = new Scheduler(store, owner), artifacts = new Artifacts(store);
  const ids = ["build", "focused-tests", "independent-review", "extra"];
  const steps = ["implement", ...ids];
  queue.submit({ id: job.id, workScope: job.workScope, version: 1, objective: job.goal, workflow: "fix", required: ids.slice(0, 3), optional: ["extra"],
    allowPartial, policyDigest: job.policyDigest, snapshot: "tree", maxSteps: 16, maxSemanticAttempts: 3 }, steps.map(id => ({ id, role: id === "implement" ? "worker" : id === "independent-review" ? "reviewer" : "verifier",
    kind: id === "implement" ? "write" as const : id === "independent-review" ? "review" as const : "verify" as const,
    dependencies: [], allowedSkippedDependencies: [], optional: id === "extra", resources: [{ id: `resource-${id}`, capacity: 1, units: 1 }] })), 0, 0);
  job.status = "RUNNING"; job.reason = "workflow_ready"; job.cwd = cwd; job.snapshot = "tree";
  for (const id of steps) {
    const intent = queue.dispatch(job.id, id, "tree"); store.markSent(owner, intent.id);
    const artifact = artifacts.pin(job.id, "tree", JSON.stringify({ checkId: id, passed: true }), "verifier");
    queue.finish(job.id, id, { terminated: true, passed: true, artifactId: artifact.id }, 1);
    if (id !== "implement") job.checks.push({ checkId: id, status: "passed", snapshot: "tree", specVersion: 1, policyDigest: job.policyDigest,
      source: id === "independent-review" ? "reviewer" : "verifier", artifactId: artifact.id });
  }
  store.put("managed-jobs", job.id, job);
  return { store, config, service, queue, owner, jobId: job.id, artifacts, finalize: () => internal.finalize(job.id) };
}
