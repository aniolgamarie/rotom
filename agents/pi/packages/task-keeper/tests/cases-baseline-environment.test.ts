import { test, assert } from "./recorded-test.ts";
import { mkdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { TaskService } from "../src/orchestration/service.ts";
import { SubagentsAdapter } from "../src/adapters/subagents.ts";
import { Store } from "../src/store/database.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S WFL-006] a real baseline environment failure blocks before any quality upgrade or writer attempt", { timeout: 15000 }, async t => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"); mkdirSync(cwd);
  const git = (...args: string[]) => execFileSync("git", args, { cwd }); git("init", "-q"); git("config", "user.email", "fixture@example.invalid"); git("config", "user.name", "Fixture");
  writeFileSync(join(cwd, "source.txt"), "preserved\n"); git("add", "."); git("commit", "-qm", "baseline");
  const config = configured(); config.features.managedWorkflows = true; config.features.crossProviderFailover = true; config.workflow.recipes = ["direct"];
  config.routes.backup = { ...config.routes.primary, model: "backup", protected: true }; config.allowedRoutes.push("backup"); config.projectRouteApprovals["*"].push("backup");
  for (const role of ["worker", "reviewer", "upgrade"]) {
    config.executionProfiles[role] = { tools: [], requiredCapabilities: [], thinking: "off", timeoutMs: 1000, maxModelTurns: 1, toolTimeoutMs: 1000 };
    config.roles[role] = { route: role === "upgrade" ? "backup" : "primary", profileRef: role };
  }
  config.verificationBindings.build = { executable: process.execPath, args: ["-e", "console.log(JSON.stringify({failureCategory:'environment'}));process.exit(1)"],
    environment: {}, timeoutMs: 2000, kind: "build", parser: "json", minimumTests: 1 };
  config.verificationBindings["focused-tests"] = { ...config.verificationBindings.build, kind: "tests", args: ["-e", 'console.log(JSON.stringify({tests:1,passed:1,failed:0,skipped:0}))'] };
  const context = { cwd, modelRegistry: { find: () => undefined }, sessionManager: { getBranch: () => [], getHeader: () => null, getSessionId: () => "session", getSessionFile: () => null } } as unknown as ExtensionContext;
  const store = new Store(join(root, "state")), service = new TaskService({ appendEntry() {} } as unknown as ExtensionAPI, store, config, context);
  t.after(async () => { await service.dispose(); store.close(); }); let modelCalls = 0;
  t.mock.method(SubagentsAdapter.prototype, "execute", async () => { modelCalls++; throw new Error("Unexpected model call after environment failure"); });
  const created = service.submit("fix", "Bounded implementation"), deadline = Date.now() + 10000;
  while (service.get(created.id).status !== "BLOCKED") { if (Date.now() > deadline) throw new Error(JSON.stringify(service.get(created.id))); await delay(10); }
  const job = service.get(created.id); assert.equal(job.reason, "baseline_environment_failed"); assert.equal(job.semanticAttempts, 1); assert.equal(job.upgradesUsed ?? 0, 0);
  assert.equal(modelCalls, 0); assert.equal(job.verification["baseline:build"].failureCategory, "environment"); assert.equal(job.verification["baseline:build"].exitCode, 1);
  assert.equal(job.verification["baseline:build"].terminationConfirmed, true); assert.equal(store.list("recipe-decisions").length, 0);
  assert.equal(job.receipt!.status, "BLOCKED"); assert.ok(job.receipt!.reasons.includes("required:independent-review"));
});
