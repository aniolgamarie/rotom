import { test, assert, evidence } from "./recorded-test.ts";
import { mkdirSync, writeFileSync, readFileSync, watch, existsSync, readdirSync, readlinkSync, unlinkSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { setTimeout as delay } from "node:timers/promises";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { TaskService } from "../src/orchestration/service.ts";
import { Store } from "../src/store/database.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[P RTB-012 T71] a late local verifier is reconciled once despite exhausted model budget", { timeout: 15000 }, async t => {
  const root = isolatedDirectory(t), cwd = join(root, "workspace"), readyFile = join(root, "ready.json"), release = join(root, "release"), counter = join(root, "executions");
  mkdirSync(cwd); execFileSync("git", ["init", "-q", cwd]);
  execFileSync("git", ["-C", cwd, "config", "user.email", "fixture@example.invalid"]); execFileSync("git", ["-C", cwd, "config", "user.name", "Fixture"]);
  writeFileSync(join(cwd, "source.txt"), "preserved\n"); execFileSync("git", ["-C", cwd, "add", "."]); execFileSync("git", ["-C", cwd, "commit", "-qm", "baseline"]);
  const config = configured(); config.features.managedWorkflows = true; config.routes.primary.protected = true; config.budget.protectedAttemptsPerWorkScope = 1;
  for (const role of ["worker", "reviewer"]) {
    config.roles[role] = { route: "primary", profileRef: role };
    config.executionProfiles[role] = { tools: ["read", "write"], requiredCapabilities: [], timeoutMs: 5000, maxModelTurns: 2, toolTimeoutMs: 1000, thinking: "off" };
  }
  const code = `const fs=require('node:fs');fs.appendFileSync(${JSON.stringify(counter)},'executed\\n');
fs.writeFileSync(${JSON.stringify(readyFile + ".tmp")},JSON.stringify({pid:process.pid,namespace:fs.readlinkSync('/proc/self/ns/pid')}));
fs.renameSync(${JSON.stringify(readyFile + ".tmp")},${JSON.stringify(readyFile)});
const timer=setInterval(()=>{if(fs.existsSync(${JSON.stringify(release)})){clearInterval(timer);process.exit(0);}},5);`;
  config.verificationBindings.build = { executable: process.execPath, args: ["-e", code], environment: {}, timeoutMs: 5000, kind: "build", parser: "exit-code", minimumTests: 1 };
  config.verificationBindings["focused-tests"] = { ...config.verificationBindings.build, kind: "tests", parser: "json", args: ["-e", 'console.log(JSON.stringify({tests:1,passed:1,failed:0,skipped:0}))'] };
  const model = { api: "openai-completions", provider: "fixture-provider", id: "fixture-model", baseUrl: "http://127.0.0.1:1/v1", reasoning: false, contextWindow: 32000, maxTokens: 1000 };
  const ctx = { cwd, sessionManager: { getBranch: () => [], getHeader: () => null, getSessionId: () => "session", getSessionFile: () => join(root, "session.jsonl") },
    modelRegistry: { find: () => model } } as unknown as ExtensionContext;
  const pi = { appendEntry() {} } as unknown as ExtensionAPI;
  const firstStore = new Store(join(root, "state")), first = new TaskService(pi, firstStore, config, ctx); let second: TaskService | undefined, secondStore: Store | undefined;
  t.after(async () => { writeFileSync(release, "cleanup"); await first.dispose(); await second?.dispose(); secondStore?.close(); firstStore.close(); });
  const scope = firstStore.list<{ scopeId: string }>("session-scopes")[0].value.scopeId, owner = firstStore.owner(scope)!;
  // Seed a historical spent permit; the current test sends no model request.
  firstStore.prepare(owner, "spent", "model", {}); firstStore.reserveRequest(owner, "spent", "spent", [{ id: `work-${scope}`, ceiling: 1 }]); firstStore.settleRequest("spent", "sent");
  let signalReady!: () => void; const ready = new Promise<void>(resolve => { signalReady = resolve; });
  const watcher = watch(root, () => { if (existsSync(readyFile)) signalReady(); }); t.after(() => watcher.close());
  const job = first.submit("fix", "Bounded candidate verification"); await ready;
  assert.equal(firstStore.bucket(`work-${scope}`)!.used, 1); assert.equal(readFileSync(counter, "utf8"), "executed\n");
  const started = JSON.parse(readFileSync(readyFile, "utf8"));
  const pid = readdirSync("/proc").filter(id => /^\d+$/.test(id)).find(id => {
    try { return readlinkSync(`/proc/${id}/ns/pid`) === started.namespace
      && Number(/^NSpid:\s+(.+)$/m.exec(readFileSync(`/proc/${id}/status`, "utf8"))?.[1].trim().split(/\s+/).at(-1)) === started.pid; } catch { return false; }
  });
  assert.ok(pid); assert.doesNotThrow(() => process.kill(Number(pid), 0));
  firstStore.revokeOwner(owner); secondStore = new Store(join(root, "state")); second = new TaskService(pi, secondStore, config, ctx);
  (second as unknown as { wake(): void }).wake = () => {};
  writeFileSync(release, "finish once"); const until = Date.now() + 5000;
  while ((first as unknown as { active: Map<string, unknown> }).active.size) { if (Date.now() > until) throw new Error("Late verification missing"); await delay(5); }
  assert.throws(() => process.kill(Number(pid), 0), { code: "ESRCH" });
  const late = secondStore.list<{ artifactId: string; ownerEpoch: number }>("late-execution-results")[0]; assert.ok(late);
  const path = join(root, "state/artifacts", late.value.artifactId), original = readFileSync(path);
  unlinkSync(path); await assert.rejects(second.resume(job.id), { code: "EXECUTION_NOT_RECONCILED" });
  assert.ok(secondStore.claims().some(claim => claim.intent_id === late.id)); writeFileSync(path, original, { mode: 0o600 });
  secondStore.put("late-execution-results", late.id, { ...late.value, ownerEpoch: owner.epoch + 1 });
  await assert.rejects(second.resume(job.id), { code: "EXECUTION_NOT_RECONCILED" }); secondStore.put("late-execution-results", late.id, late.value);
  await second.resume(job.id);
  const plan = secondStore.get<{ dispatched: number; steps: Array<{id: string; status: string}> }>("jobs", job.id)!;
  assert.equal(plan.steps.find(step => step.id === "baseline:build")!.status, "passed"); assert.equal(plan.dispatched, 1);
  assert.equal(plan.steps.find(step => step.id === "implement")!.status, "pending"); assert.equal(second.get(job.id).receipt, null);
  assert.equal(secondStore.claims().some(claim => claim.intent_id === late.id), false); assert.equal(secondStore.bucket(`work-${scope}`)!.used, 1);
  assert.equal(readFileSync(counter, "utf8"), "executed\n"); assert.ok(second.get(job.id).outputs["late-adoption:baseline:build"]);
  for (const id of ["RTB-012", "T71"]) evidence(id, () => {
    assert.equal(plan.steps.find(step => step.id === "baseline:build")!.status, "passed");
    assert.equal(plan.dispatched, 1); assert.equal(readFileSync(counter, "utf8"), "executed\n");
    assert.equal(secondStore!.bucket(`work-${scope}`)!.used, 1);
    assert.equal(secondStore!.db.prepare("SELECT count(*) n FROM requests").get()!.n, 1);
    assert.equal(second!.get(job.id).receipt, null); assert.equal(secondStore!.claims().some(claim => claim.intent_id === late.id), false);
  });
});
