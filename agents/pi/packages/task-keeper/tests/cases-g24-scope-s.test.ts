import { test, assert } from "./recorded-test.ts";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { TaskService } from "../src/orchestration/service.ts";
import { Scheduler, type PlanStep } from "../src/orchestration/scheduler.ts";
import { Store } from "../src/store/database.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";
import type { Config } from "../src/config.ts";
function context(cwd: string, id: string, file: string, parentFile?: string) {
  return { cwd, modelRegistry: { find: () => undefined }, sessionManager: { getBranch: () => [], getSessionId: () => id,
    getSessionFile: () => file, getHeader: () => parentFile ? { parentSession: parentFile } : null } } as unknown as ExtensionContext;
}
function policy(): Config {
  const config = configured(); config.features.managedWorkflows = true;
  for (const role of ["worker", "reviewer", "scout"]) {
    config.roles[role] = { route: "primary", profileRef: role };
    config.executionProfiles[role] = { tools: [], requiredCapabilities: [], thinking: "off", timeoutMs: 1000, maxModelTurns: 1, toolTimeoutMs: 1000 };
  }
  config.verificationBindings.build = { executable: process.execPath, args: ["-e", ""], environment: {}, timeoutMs: 1000, kind: "build", parser: "exit-code", minimumTests: 1 };
  config.verificationBindings["focused-tests"] = { ...config.verificationBindings.build, kind: "tests", parser: "json" };
  return config;
}
function dormant(service: TaskService) { (service as unknown as { wake: () => void }).wake = () => {}; return service; }

test("[S T30] the service rejects a malformed branch marker and uses a trusted fork origin when the header lacks one", async t => {
  const root = isolatedDirectory(t), store = new Store(join(root, "state")), config = policy(), pi = { appendEntry() {} } as unknown as ExtensionAPI;
  const malformed = context(root, "bad", join(root, "bad.jsonl"));
  (malformed.sessionManager as unknown as { getBranch(): unknown[] }).getBranch = () => [{ type: "custom", customType: "task-keeper:work-scope", data: {} }];
  assert.throws(() => new TaskService(pi, store, config, malformed), { code: "WORK_SCOPE_REFERENCE_INVALID" });
  assert.equal(store.db.prepare("SELECT count(*) n FROM owners").get()!.n, 0);
  const file = join(root, "parent.jsonl"), parent = dormant(new TaskService(pi, store, config, context(root, "parent", file)));
  const scope = store.list<{scopeId:string}>("session-scopes")[0].value.scopeId;
  await parent.dispose();
  const fork = dormant(new TaskService(pi, store, config, context(root, "fork", join(root, "fork.jsonl")), undefined, undefined, { fork: true, parentFile: file }));
  t.after(async () => { await fork.dispose(); store.close(); });
  assert.equal(store.get<{scopeId:string}>("session-scopes", "fork")!.scopeId, scope);
  assert.equal(store.db.prepare("SELECT count(*) n FROM owners").get()!.n, 1);
});
for (const id of ["SCH-001", "T30"]) test(`[S ${id}] model-created replacement jobs and forks retain the workScope semantic ceiling`, async t => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"); mkdirSync(cwd); execFileSync("git", ["init", "-q", cwd]);
  const store = new Store(join(root, "state")), config = policy(), pi = { appendEntry() {} } as unknown as ExtensionAPI;
  const file = join(root, "parent.jsonl"), parent = dormant(new TaskService(pi, store, config, context(cwd, "parent", file)));
  const children: TaskService[] = [parent];
  t.after(async () => { for (const service of children) await service.dispose(); store.close(); });
  const jobs = [1, 2, 3].map(n => parent.submit("fix", `part ${n} of the same goal`));
  assert.equal(new Set(jobs.map(job => job.workScope)).size, 1); assert.equal(parent.scopeUsage().semanticAttempts, 3);
  assert.throws(() => parent.submit("fix", "restart with a fresh job"), { code: "WORK_SCOPE_SEMANTIC_LIMIT" });
  assert.equal(parent.list().length, 3); parent.pause(jobs[0].id, true);
  assert.throws(() => parent.submit("fix", "replace cancelled work"), { code: "WORK_SCOPE_SEMANTIC_LIMIT" });
  await parent.dispose();
  const fork = dormant(new TaskService(pi, store, config, context(cwd, "fork", join(root, "fork.jsonl"), file))); children.push(fork);
  assert.equal(fork.scopeUsage().semanticAttempts, 3); assert.throws(() => fork.submit("fix", "fork cannot reset"), { code: "WORK_SCOPE_SEMANTIC_LIMIT" });
  const independent = dormant(new TaskService(pi, store, config, context(cwd, "new-user-session", join(root, "independent.jsonl")))); children.push(independent);
  assert.notEqual(independent.submit("fix", "independent user goal").workScope, jobs[0].workScope);
  assert.equal(independent.scopeUsage().semanticAttempts, 1);
});

test("[S SCH-002] finite scope job capacity also bounds read-only model submissions", async t => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"); mkdirSync(cwd); execFileSync("git", ["init", "-q", cwd]);
  const store = new Store(join(root, "state")), config = policy(); config.limits.jobsPerWorkScope = 2;
  const service = dormant(new TaskService({ appendEntry() {} } as unknown as ExtensionAPI, store, config, context(cwd, "session", join(root, "session.jsonl"))));
  t.after(async () => { await service.dispose(); store.close(); });
  service.submit("inspect", "first"); service.submit("inspect", "second");
  assert.throws(() => service.submit("inspect", "third"), { code: "WORK_SCOPE_JOB_LIMIT" });
  assert.equal(service.scopeUsage().jobs, 2); assert.equal(service.scopeUsage().semanticAttempts, 0);
});

test("[S T30] different jobs share a persisted step ceiling and owner replacement cannot reset it", t => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close()); let owner = store.claimOwner("scope", "owner");
  let scheduler = new Scheduler(store, owner, 10, 2);
  const spec = (id: string) => ({ id, workScope: "scope", version: 1, objective: id, workflow: "inspect" as const, required: ["work"], optional: [], allowPartial: false,
    policyDigest: "policy", snapshot: "snapshot", maxSteps: 16, maxSemanticAttempts: 3 });
  const step: PlanStep = { id: "work", role: "reader", kind: "read", dependencies: [], allowedSkippedDependencies: [], optional: false, resources: [] };
  for (const id of ["a", "b", "c"]) scheduler.submit(spec(id), [step], 0, 0);
  for (const id of ["a", "b"]) { scheduler.dispatch(id, "work", "snapshot"); scheduler.finish(id, "work", { terminated: true, passed: false, artifactId: null }, 1); }
  assert.equal(scheduler.scopeDispatched(), 2); assert.equal(scheduler.next(10), null);
  assert.throws(() => scheduler.dispatch("c", "work", "snapshot"), { code: "WORK_SCOPE_STEP_LIMIT" });
  store.revokeOwner(owner); owner = store.claimOwner("scope", "next"); scheduler = new Scheduler(store, owner, 10, 2);
  assert.equal(scheduler.scopeDispatched(), 2); assert.throws(() => scheduler.submit(spec("replacement"), [step], 0, 10), { code: "WORK_SCOPE_STEP_LIMIT" });
  assert.equal(store.get("jobs", "replacement"), null);
});
