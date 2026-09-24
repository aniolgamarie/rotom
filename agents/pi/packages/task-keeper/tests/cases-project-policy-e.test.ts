import { test, assert, evidence } from "./recorded-test.ts";
import { spawn } from "node:child_process";
import { once } from "node:events";
import { createServer } from "node:http";
import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import { DEFAULT_CONFIG } from "../src/config.ts";
import { isolatedDirectory, listenLoopback } from "./helpers.ts";
import type { TestContext } from "node:test";
import { Store } from "../src/store/database.ts";

async function load(t: TestContext, patch: unknown, reloadPatches: unknown[] = [], userPatch: Record<string, unknown> = {}, databaseName = "runtime.db", preservePending = false) {
  const root = isolatedDirectory(t), agent = join(root, "agent"), cwd = join(root, "workspace"), configPath = join(root, "task-keeper.json");
  mkdirSync(agent); mkdirSync(cwd); mkdirSync(join(cwd, ".pi"));
  const projectPath = join(cwd, ".pi/task-keeper.json"), authPath = join(agent, "auth.json"), database = join(root, "state", databaseName);
  let requests = 0; const server = createServer((req, res) => { requests++; req.resume(); res.end("unexpected"); });
  await listenLoopback(server); t.after(() => { server.closeAllConnections(); server.close(); });
  writeFileSync(join(agent, "models.json"), JSON.stringify({ providers: { fixture: { api: "openai-completions", apiKey: "fixture-only", baseUrl: `http://127.0.0.1:${(server.address() as {port:number}).port}/v1`,
    models: [{ id: "fixture-model", name: "Fixture", reasoning: false, input: ["text"], contextWindow: 32000, maxTokens: 1000, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] } } }));
  writeFileSync(join(agent, "settings.json"), JSON.stringify({ packages: [], enableInstallTelemetry: false, compaction: { enabled: false } }));
  const auth = JSON.stringify({ fixture: { type: "api_key", key: "fixture-private" } }), user = JSON.stringify({ ...structuredClone(DEFAULT_CONFIG), enabled: true, ...userPatch, storage: { path: database } }), project = JSON.stringify(patch);
  writeFileSync(authPath, auth, { mode: 0o600 }); writeFileSync(configPath, user); writeFileSync(projectPath, project);
  const pkg = fileURLToPath(new URL("..", import.meta.url));
  const child = spawn(process.execPath, [join(pkg, "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"), "--mode", "rpc", "--no-extensions", "-e", join(pkg, "index.ts"), "--no-skills", "--no-context-files", "--no-prompt-templates", "--no-themes", "--offline", "--provider", "fixture", "--model", "fixture-model", "--no-tools", "--session-dir", join(root, "sessions")], {
    cwd, env: { PATH: process.env.PATH, PI_CODING_AGENT_DIR: agent, PI_TASK_KEEPER_CONFIG: configPath, PI_OFFLINE: "1", PI_TELEMETRY: "0" }, stdio: ["pipe", "pipe", "pipe"],
  });
  let buffer = "", errors = ""; const events: Record<string, any>[] = [];
  child.stdout.on("data", chunk => { buffer += chunk; let at: number; while ((at = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, at); buffer = buffer.slice(at + 1); if (line.trim()) events.push(JSON.parse(line));
  } }); child.stderr.on("data", chunk => { errors += chunk; });
  t.after(async () => { if (child.exitCode === null && child.signalCode === null) { const stopped = once(child, "exit"); child.kill("SIGTERM"); await stopped; } });
  child.stdin.write(JSON.stringify({ id: "doctor", type: "prompt", message: "/orch doctor" }) + "\n");
  const deadline = Date.now() + 10000;
  while (!events.some(event => event.id === "doctor" && event.type === "response")) {
    if (Date.now() > deadline || child.exitCode !== null) throw new Error(JSON.stringify({ events, errors })); await delay(10);
  }
  const doctor = events.filter(event => event.type === "extension_ui_request" && event.method === "notify")
    .flatMap(event => { try { return [JSON.parse(event.message)]; } catch { return []; } }).find(value => "startupError" in value);
  assert.ok(doctor, JSON.stringify({events, errors})); assert.equal(requests, 0);
  assert.equal(readFileSync(authPath, "utf8"), auth); assert.equal(readFileSync(configPath, "utf8"), user); assert.equal(readFileSync(projectPath, "utf8"), project);
  assert.equal(existsSync(join(cwd, "injected")), false);
  if(preservePending){
    const store=new Store(dirname(database),databaseName);try{
      const owner=store.claimOwner("retained-scope","retained-owner");store.prepare(owner,"retained-intent","write",{},[{id:"retained-source",capacity:1,units:1}]);
      store.markSent(owner,"retained-intent");
      for(const state of ["sent","unknown"] as const){store.reserveRequest(owner,"retained-intent",state,[{id:"retained-budget",ceiling:2}]);store.settleRequest(state,state);}
      store.settle("retained-intent","unknown");
    }finally{store.close();}
  }
  const reloads: Record<string, any>[] = [];
  for (const [index, next] of reloadPatches.entries()) {
    writeFileSync(projectPath, JSON.stringify(next));
    for (const command of [{ id: `new-${index}`, type: "new_session" }, { id: `doctor-${index}`, type: "prompt", message: "/orch doctor" }]) {
      child.stdin.write(JSON.stringify(command) + "\n"); const until = Date.now() + 10000;
      while (!events.some(event => event.type === "response" && event.id === command.id)) {
        if (Date.now() > until) throw new Error(JSON.stringify({ events, errors })); await delay(10);
      }
      assert.equal(events.find(event => event.type === "response" && event.id === command.id)!.success, true);
    }
    const fresh = events.filter(event => event.type === "extension_ui_request" && event.method === "notify")
      .flatMap(event => { try { return [JSON.parse(event.message)]; } catch { return []; } }).filter(value => "startupError" in value).at(-1);
    assert.ok(fresh); reloads.push(fresh);
    assert.equal(requests, 0); assert.equal(readFileSync(authPath, "utf8"), auth); assert.equal(readFileSync(configPath, "utf8"), user);
    if(preservePending){const store=new Store(dirname(database),databaseName);try{
      assert.equal(store.intent("retained-intent")!.status,"unknown");assert.equal(store.claims().length,1);
      assert.equal(store.bucket("retained-budget")!.used,1);assert.equal(store.bucket("retained-budget")!.reserved,1);
      assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n,2);
    }finally{store.close();}}
  }
  return { doctor, database, databaseCreated: existsSync(database), reloads };
}

test("[E T87] project guard-disable flags fail on actual session reload without resetting unknown work or budget", {timeout:30000}, async t=>{
  const result=await load(t,{},[{unknownIsSuccess:true},{cancelMayResume:true},{ignoreRequiredChecks:true},{}],{},"runtime.db",true);
  assert.equal(result.doctor.enabled,true);assert.equal(result.doctor.startupError,null);assert.equal(result.reloads.length,4);
  for(const denied of result.reloads.slice(0,3)){
    assert.equal(denied.enabled,false);assert.equal(denied.startupError,"UNKNOWN_FIELD");assert.equal(denied.managedWorkflows.enabled,false);
    assert.equal(denied.effectivePolicy,null);
  }
  assert.equal(result.reloads[3].enabled,true);assert.equal(result.reloads[3].startupError,null);
  assert.equal(result.databaseCreated,true);
});

test("[A E CFG-005] real Pi refuses project attempts to disable correctness invariants", {timeout:30000}, async t => {
  for (const key of ["unknownIsSuccess", "cancelMayResume", "ignoreRequiredChecks"]) {
    const result = await load(t, { [key]: true }); assert.equal(result.doctor.enabled, false); assert.equal(result.doctor.startupError, "UNKNOWN_FIELD");
    assert.equal(result.databaseCreated, false); assert.equal(result.doctor.managedWorkflows.enabled, false);
  }
  const valid = await load(t, { enabled: false }); assert.equal(valid.doctor.startupError, null); assert.equal(valid.databaseCreated, false);
});

test("[A E CFG-006] project executable bindings are rejected before any command can run", {timeout:20000}, async t => {
  const result = await load(t, { verificationBindings: { malicious: { executable: process.execPath, args: ["-e", "require('fs').writeFileSync('injected','bad')"] } } });
  assert.equal(result.doctor.enabled, false); assert.equal(result.doctor.startupError, "UNKNOWN_FIELD"); assert.equal(result.databaseCreated, false);
  const valid = await load(t, {}); assert.equal(valid.doctor.startupError, null); assert.equal(valid.doctor.enabled, true); assert.equal(valid.databaseCreated, true);
});

test("[A E CFG-008] malformed project numeric limits fail closed and a zero restriction remains valid", {timeout:30000}, async t => {
  for (const parallelReaders of [-1, 0.5, "2"]) {
    const result = await load(t, { limits: { parallelReaders } }); assert.equal(result.doctor.enabled, false); assert.ok(result.doctor.startupError); assert.equal(result.databaseCreated, false);
  }
  const valid = await load(t, { limits: { parallelReaders: 0 } }); assert.equal(valid.doctor.startupError, null); assert.equal(valid.doctor.enabled, true);
  assert.equal(valid.doctor.effectivePolicy.limits.parallelReaders, 0);
});

test("[A E CFG-004] effective Pi policy cannot enlarge user budgets or relax required checks", {timeout:20000}, async t => {
  const enlarged = await load(t, { budget: { protectedAttemptsPerWorkScope: 1000, backupAttemptsPerIncident: 1000 },
    limits: { parallelReaders: 100 }, workflow: { requiredChecks: { fix: [], inspect: [] }, allowPartial: true } });
  const policy = enlarged.doctor.effectivePolicy;
  assert.equal(enlarged.doctor.startupError, null);
  assert.equal(policy.budget.protectedAttemptsPerWorkScope, DEFAULT_CONFIG.budget.protectedAttemptsPerWorkScope);
  assert.equal(policy.budget.backupAttemptsPerIncident, DEFAULT_CONFIG.budget.backupAttemptsPerIncident);
  assert.equal(policy.limits.parallelReaders, DEFAULT_CONFIG.limits.parallelReaders);
  assert.deepEqual(policy.requiredChecks, DEFAULT_CONFIG.workflow.requiredChecks); assert.equal(policy.allowPartial, false);
  const restricted = await load(t, { budget: { protectedAttemptsPerWorkScope: 2, backupAttemptsPerIncident: 1 } },
    [{ limits: { writersPerJob: 0 } }, { limits: { writersPerJob: 100 } }], { limits: { ...DEFAULT_CONFIG.limits, writersPerJob: 4 } });
  for (const [result, configuredLimit, effectiveLimit] of [[restricted.doctor, 4, 1], [restricted.reloads[0], 0, 0], [restricted.reloads[1], 4, 1]] as const) {
    assert.equal(result.startupError, null); assert.equal(result.effectivePolicy.limits.writersPerJob, effectiveLimit);
    assert.deepEqual(result.effectivePolicy.writerPolicy, { configuredLimit, effectiveLimit, mode: "single-writer" });
    assert.equal(result.bindingGaps.fix.includes("limits.writersPerJob"), configuredLimit === 0);
  }
  assert.equal(restricted.doctor.effectivePolicy.budget.protectedAttemptsPerWorkScope, 2);
  assert.equal(restricted.doctor.effectivePolicy.budget.backupAttemptsPerIncident, 1);
});

test("[A E] failed session configuration reload cannot advertise a previous enabled policy", {timeout:30000}, async t => {
  const result = await load(t, {}, [{ unknownIsSuccess: true }, {}]);
  assert.equal(result.doctor.enabled, true); assert.ok(result.doctor.effectivePolicy);
  assert.equal(result.reloads[0].enabled, false); assert.equal(result.reloads[0].effectivePolicy, null);
  assert.equal(result.reloads[0].startupError, "UNKNOWN_FIELD"); assert.equal(result.reloads[0].storageRoot, null);
  assert.equal(result.reloads[1].enabled, true); assert.equal(result.reloads[1].startupError, null);
  assert.deepEqual(result.reloads[1].effectivePolicy, result.doctor.effectivePolicy);
});


test("[A CFG-003] default disabled Pi configuration reports workflow bindings and accepts current-model recovery configuration", { timeout: 20000 }, async t => {
  const disabled = await load(t, {}, [], { enabled: false });
  assert.equal(disabled.doctor.enabled, false); assert.equal(disabled.databaseCreated, false); assert.equal(disabled.doctor.startupError, null);
  assert.deepEqual(disabled.doctor.bindingGaps.interactiveRecovery,[]);
  assert.ok(disabled.doctor.bindingGaps.fix.includes("roles.worker")); assert.ok(disabled.doctor.bindingGaps.fix.includes("verificationBindings.focused-tests"));
  const unbound = await load(t, {}, [], { features: { ...DEFAULT_CONFIG.features, interactiveRecovery: true } });
  assert.equal(unbound.doctor.enabled, true); assert.equal(unbound.doctor.startupError, null); assert.equal(unbound.databaseCreated, true);
});

test("[E CFG-009] real Pi explicitly rejects every unimplemented Advisor mode without substituting the parent model", { timeout: 30000 }, async t => {
  for (const mode of ["on-demand", "shadow", "always"]) {
    const rejected = await load(t, {}, [], { advisor: { mode } });
    assert.equal(rejected.doctor.startupError, "ADVISOR_NOT_IMPLEMENTED"); assert.equal(rejected.doctor.enabled, false); assert.equal(rejected.databaseCreated, false);
    assert.equal(rejected.doctor.support.advisor, "off; not implemented");
  }
  const off = await load(t, {}, [], { advisor: { mode: "off" } }); assert.equal(off.doctor.startupError, null); assert.equal(off.doctor.enabled, true);
});


test("[E SCH-012 TK08] real Pi doctor identifies independent coordination roots and their actual database", {timeout:20000}, async t => {
  const first = await load(t, {}), second = await load(t, {}, [], {}, "custom.db");
  for (const id of ["SCH-012", "TK08"]) evidence(id, () => {
    for (const result of [first, second]) {
      assert.equal(result.doctor.startupError, null); assert.equal(result.databaseCreated, true);
      assert.equal(result.doctor.coordination.stateRoot, result.doctor.storageRoot);
      assert.equal(result.doctor.coordination.database, result.database);
      assert.equal(result.doctor.coordination.scope, "one-database-per-state-directory");
      assert.equal(result.doctor.coordination.otherStateDirectories, "independent"); assert.equal(result.doctor.coordination.crossParentFairness, false);
    }
    assert.notEqual(first.doctor.coordination.stateRoot, second.doctor.coordination.stateRoot);
  });
});
