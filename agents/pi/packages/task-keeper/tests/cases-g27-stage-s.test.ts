import { writeFileSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { configurationPolicyDigest } from "../src/config.ts";
import { modelBindingDigest } from "../src/adapters/capabilities.ts";
import { test, assert, evidence, acceptance, observerArtifact } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import { digest } from "../src/contracts/primitives.ts";
import type { ManagedJob } from "../src/orchestration/service.ts";
import type { TestContext } from "node:test";

function waiting(t: TestContext) {
  const f = completedState(t, false, true), job = f.service.get(f.jobId), plan = f.queue.job(f.jobId);
  f.config.executionProfiles.worker.tools = ["read", "grep", "find", "ls", "write", "edit"];
  f.config.routes.backup.quotaGroup = "backup-pool"; f.config.quotaGroups["backup-pool"] = structuredClone(f.config.quotaGroups.pool);
  f.config.recovery.chain = [
    { id: "primary-short", route: "primary", wait: { mode: "bounded", maxMs: 100 } },
    { id: "backup", route: "backup", wait: { mode: "bounded", maxMs: 200 } },
    { id: "primary-tail", route: "primary", wait: { mode: "forever" } },
  ];
  const internal = f.service as unknown as { context: { modelRegistry: { find: (provider: string, id: string) => unknown } }; advanceWait(job: ManagedJob): void };
  internal.context.modelRegistry.find = (provider, id) => ({ api: "openai-completions", provider, id, baseUrl: "http://fixture.invalid", reasoning: false,
    contextWindow: 32000, maxTokens: 1000 });
  job.status = "WAITING_QUOTA"; job.reason = "quota_wait"; job.policyDigest = configurationPolicyDigest(f.config); plan.spec.policyDigest = job.policyDigest;
  plan.steps.find(step => step.id === "implement")!.status = "failed";
  for (const step of plan.steps.filter(step => step.id !== "implement")) step.status = "pending";
  job.recovery = { stepId: "implement", primaryRoute: "primary", incidentId: "original", networkAttempts: 0,
    stage: { chainDigest: digest(f.config.recovery.chain), incidentId: "original", stageId: "backup", stageEnteredAt: 1100, deadline: 1300 } };
  f.store.put("incidents", "pool", { id: "original", status: "OPEN", failures: 2, notBefore: 2000 });
  f.store.put("incidents", "backup-pool", { id: "backup-incident", status: "OPEN", failures: 1, notBefore: 1300 });
  f.store.put("jobs", f.jobId, plan); f.queue.pause(f.jobId); f.store.put("managed-jobs", f.jobId, job);
  return { ...f, advance: () => internal.advanceWait(f.service.get(f.jobId)) };
}

test("[S RTB-003 T50] early primary availability remains a candidate until unknown work and server cooldown are cleared", t => {
  let now = 1150; t.mock.method(Date, "now", () => now); const f = waiting(t);
  f.store.put("incidents", "pool", { id: "original", status: "CLOSED", failures: 2, notBefore: 2000 });
  const plan = f.queue.job(f.jobId); plan.steps.find(step => step.id === "implement")!.status = "unknown"; f.store.put("jobs", f.jobId, plan);
  const previous = f.service.get(f.jobId).recovery!.stage; f.advance();
  for (const id of ["RTB-003", "T50"]) evidence(id, () => {
    assert.equal(f.service.get(f.jobId).status, "WAITING_QUOTA"); assert.deepEqual(f.service.get(f.jobId).recovery!.stage, previous);
    assert.equal(f.service.get(f.jobId).routes?.implement, undefined);
  });
  plan.steps.find(step => step.id === "implement")!.status = "failed"; f.store.put("jobs", f.jobId, plan);
  f.store.put("transport-incidents", "fixture-domain", { id: "transport", status: "OPEN", failures: 1, notBefore: 1151 });
  f.advance(); assert.equal(f.service.get(f.jobId).status, "WAITING_QUOTA"); now = 1151; f.advance();
  for (const id of ["RTB-003", "T50"]) evidence(id, () => {
    const job = f.service.get(f.jobId); assert.equal(job.routes!.implement, "primary"); assert.equal(job.status, "RUNNING");
    assert.equal(job.recovery!.incidentId, "original"); assert.ok(now < previous!.deadline!); assert.equal(f.queue.job(f.jobId).dispatched, 5);
  });
});

test("[S RTB-010 T28] the fourth spent or unknown incident permit returns to primary without clearing either budget", t => {
  t.mock.method(Date, "now", () => 1200);
  for (const fourth of ["sent", "unknown"] as const) {
    const f = waiting(t); f.store.prepare(f.owner, "history", "request-history", {});
    for (let i = 0; i < 4; i++) {
      f.store.reserveRequest(f.owner, "history", `attempt-${i}`, [{ id: "incident-original", ceiling: 4 }, { id: `work-${f.owner.scopeId}`, ceiling: 12 }]);
      f.store.settleRequest(`attempt-${i}`, i === 3 ? fourth : "sent");
    }
    const incident = f.store.bucket("incident-original"), work = f.store.bucket(`work-${f.owner.scopeId}`); f.advance();
    for (const id of ["RTB-010", "T28"]) evidence(id, () => {
      const job = f.service.get(f.jobId); assert.equal(job.recovery!.stage!.stageId, "primary-tail"); assert.equal(job.recovery!.stage!.deadline, null);
      assert.equal(job.status, "WAITING_QUOTA"); assert.equal(job.routes?.implement, undefined);
      assert.deepEqual(f.store.bucket("incident-original"), incident); assert.deepEqual(f.store.bucket(`work-${f.owner.scopeId}`), work);
      assert.throws(() => f.store.reserveRequest(f.owner, "history", "fifth", [{ id: "incident-original", ceiling: 4 }]));
      assert.equal(f.store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 4);
    });
  }
});

test("[S RTB-004] reloaded stage records retain their entered-at and deadline across repeated waiting ticks", t => {
  for (const id of ["RTB-004"]) evidence(id, () => {
    let now = 1150; t.mock.method(Date, "now", () => now); const f = waiting(t);
    const original = f.service.get(f.jobId).recovery!.stage!;
    for (const at of [1150, 1199, 1299]) {
      now = at; const reloaded = JSON.parse(JSON.stringify(f.service.get(f.jobId))); f.store.put("managed-jobs", f.jobId, reloaded); f.advance();
      const actual = f.service.get(f.jobId); assert.equal(actual.status, "WAITING_QUOTA"); assert.deepEqual(actual.recovery!.stage, original);
    }
    now = 1300; f.advance(); const next = f.service.get(f.jobId);
    assert.equal(next.recovery!.stage!.stageId, "primary-tail"); assert.equal(next.recovery!.stage!.stageEnteredAt, 1300);
    assert.equal(next.recovery!.stage!.deadline, null); assert.equal(next.recovery!.incidentId, "original");
    acceptance("AC29","stage-restart",{level:"S",observer:"durable-reloaded-stage-through-fixed-clock-deadline",predicate:"reloaded waiting stage cannot renew its deadline",artifact:observerArtifact("stage-restart",{original,next,now})},()=>{assert.equal(original.deadline,1300);assert.equal(next.recovery!.stage!.stageId,"primary-tail");assert.equal(next.recovery!.stage!.stageEnteredAt,1300);assert.equal(next.recovery!.incidentId,"original");assert.equal(f.queue.job(f.jobId).dispatched,5);});
    assert.equal(next.status, "WAITING_QUOTA"); assert.equal(f.queue.job(f.jobId).dispatched, 5);
  });
});

for(const mode of ["waiting", "paused", "restored"] as const)
test(`[S CFG-013 RTB-010] ${mode} quota resume preserves the stage until fresh route admission`, async t => {
  let now=1200;t.mock.method(Date,"now",()=>now);const f=waiting(t);
  // The actual fixture's snapshot is used as an unchanged input, not a new authorization.
  const original=f.service.get(f.jobId);
  original.modelBindings=Object.fromEntries(Object.entries(f.config.routes).map(([id,route])=>[id,modelBindingDigest({api:"openai-completions",provider:route.provider,id:route.model,
    baseUrl:"http://fixture.invalid",reasoning:false,contextWindow:32000,maxTokens:1000})]));
  (f.service as unknown as {capture():Promise<unknown>}).capture=async()=>({snapshot:{id:original.snapshot,files:[]},patch:""});
  original.quotaWaitPending=true;f.store.put("managed-jobs",f.jobId,original);
  if(mode==="paused")f.service.pause(f.jobId);
  if(mode==="restored"){const job=f.service.get(f.jobId);job.status="BLOCKED";job.reason="restart_reconciliation_required";f.store.put("managed-jobs",f.jobId,job);}
  const stage=structuredClone(original.recovery!.stage),dispatched=f.queue.job(f.jobId).dispatched;
  await f.service.resume(f.jobId);
  for(const id of ["CFG-013","RTB-010"])evidence(id,()=>{
    const job=f.service.get(f.jobId);assert.equal(job.status,"WAITING_QUOTA");assert.equal(job.quotaWaitPending,true);
    assert.deepEqual(job.recovery!.stage,stage);assert.equal(job.recovery!.incidentId,"original");
    assert.equal(f.queue.job(f.jobId).paused,true);assert.equal(f.queue.job(f.jobId).dispatched,dispatched);
    assert.equal(f.store.db.prepare("SELECT count(*) n FROM requests").get()!.n,0);
  });
  f.advance();assert.equal(f.service.get(f.jobId).status,"WAITING_QUOTA");assert.deepEqual(f.service.get(f.jobId).recovery!.stage,stage);
  now=2000;f.advance();
  for(const id of ["CFG-013","RTB-010"])evidence(id,()=>{
    const job=f.service.get(f.jobId);assert.equal(job.status,"RUNNING");assert.equal(job.quotaWaitPending,false);
    assert.equal(job.routes!.implement,"primary");assert.equal(job.recovery!.stage!.stageId,"primary-tail");
    assert.equal(f.queue.job(f.jobId).dispatched,dispatched);assert.equal(f.queue.job(f.jobId).steps.find(step=>step.id==="implement")!.status,"pending");
    if(id === "RTB-010")acceptance("AC29","primary-return",{level:"S",observer:"retained-stage-and-fresh-primary-route-admission",predicate:"returning to primary preserves incident identity and dispatched count",artifact:observerArtifact(`primary-${mode}`,{stage,job,dispatched})},()=>{assert.equal(job.routes!.implement,"primary");assert.equal(job.recovery!.incidentId,"original");assert.equal(job.recovery!.stage!.stageId,"primary-tail");assert.equal(f.queue.job(f.jobId).dispatched,dispatched);});

  });
});


test("[S T32] stale or mismatched quota observations cannot admit a protected recovery candidate", t => {
  for (const id of ["T32"]) evidence(id, () => {
    t.mock.method(Date, "now", () => 1200);
    for (const patch of [{account:"different"}, {bucket:"different"}, {source:"different"}, {observedAt:1000}, {}]) {
      const f = waiting(t), path = join(f.store.root, "telemetry.json"), route = f.config.routes.backup;
      route.telemetry = "quota"; f.config.telemetryBindings.quota = { path, accountBinding: route.accountBinding, bucket: route.quotaGroup,
        source: "fixture", freshnessMs: 100, minimumRemaining: 1 };
      const observation = { account: route.accountBinding, bucket: route.quotaGroup, source:"fixture", observedAt:1150, remaining:4, resetAt:null, ...patch };
      writeFileSync(path, JSON.stringify(observation), {mode:0o600});
      f.store.put("incidents", "backup-pool", { id:"backup-incident",status:"OPEN",failures:1,notBefore:1100 });
      const configuredJob = f.service.get(f.jobId), configuredPlan = f.queue.job(f.jobId);
      configuredJob.policyDigest = configurationPolicyDigest(f.config); configuredPlan.spec.policyDigest = configuredJob.policyDigest;
      f.store.put("managed-jobs", f.jobId, configuredJob); f.store.put("jobs", f.jobId, configuredPlan);
      const before = f.store.db.prepare("SELECT count(*) n FROM requests").get()!.n; f.advance();
      const job = f.service.get(f.jobId), assessment = f.store.get<{rejected:Array<{id:string;reasons:string[]}>}>("route-assessments", f.jobId)!;
      if (Object.keys(patch).length) {
        assert.equal(job.status, "WAITING_QUOTA"); assert.equal(job.routes?.implement, undefined);
        assert.ok(assessment.rejected.some(item => item.id === "backup" && item.reasons.includes("quota_telemetry_not_eligible")));
        assert.equal(f.store.bucket(`work-${f.owner.scopeId}`), null); assert.equal(f.queue.job(f.jobId).dispatched, 5);
      } else {
        assert.equal(job.status, "RUNNING"); assert.equal(job.routes!.implement, "backup");
        assert.equal(assessment.rejected.some(item => item.id === "backup"), false);
      }
      assert.equal(f.store.db.prepare("SELECT count(*) n FROM requests").get()!.n, before);
      assert.deepEqual(JSON.parse(readFileSync(path, "utf8")), observation); assert.equal(job.recovery!.incidentId, "original");
    }
  });
});
