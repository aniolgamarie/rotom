// 真TaskService/Artifacts/SQLite/Scheduler；Host/getter/执行proof端口fake，不提供SDK/物理资格。
import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import { join } from "node:path";
import { ready } from "./input-snapshot-service.test.ts";
import { digest } from "../src/contracts/primitives.ts";
const port=Symbol.for("task-keeper.test.async-check-port");
async function rig(t:any){
  const f=await ready(t,(config:any)=>{config.workflow.reuseReviews=false;config.verificationBindings["focused-tests"].requiredTestIds=["required"];});
  const original=globalThis[port];globalThis[port]=async(o:any)=>{const value=await original(o);if(o.program==="check")value.stdout='{"tests":1,"passed":1,"failed":0,"skipped":0,"test_results":[{"id":"required","status":"passed"}]}';return value;};
  let number=0,reviewFault=false,proofMissing=false;
  f.internal.modernDelegateAdapter.execute=async(input:any,_ctx:any,_signal:any,onDispatch:any)=>{
    const startedAt=Date.now();onDispatch();number++;const descriptorId="descriptor-"+input.stepId+"-"+number,nativeRunId="physical-"+number;
    let content:any=null,observations:any[]=[];
    if(input.role==="reviewer"){
      const report={verdict:"pass",snapshot:f.queue.job(f.job.id).spec.snapshot,summary:"bounded independent review",scopeComplete:true,
        findings:[],evidence:[{path:"source.txt",startLine:1,endLine:1}],unverified:[]};content={kind:"structured",value:report};
      const delivery={toolCallId:"read-1",payloadDigest:digest("ordinary source delivery"),readRequest:1,deliveredRequest:2};
      observations=[{descriptorId,producerId:"review-producer",toolErrors:[],contextOperations:[],lastResponse:null,requestDenials:[],activeTools:[],lastError:null,
        fileReads:reviewFault?[]:[{path:"source.txt",firstLine:1,lastLine:1,...delivery}],
        artifactReads:input.evidenceIds.map((id:string)=>{const meta=f.store.get<any>("artifacts",id);f.internal.artifacts.read(id,f.job.id,meta.snapshot);
          return {id,start:0,end:meta.bytes,total:meta.bytes,...delivery};}),
        structuredOutputs:[{toolCallId:"verdict",requestOrdinal:2,valueDigest:digest(report)}]}];
    }
    return {descriptorId,nativeRunId,status:"ended",terminationConfirmed:true,notSent:false,content,error:null,observations,
      evidenceOrigin:structuredClone(input.evidenceOrigin),invocationWindow:{startedAt,endedAt:Date.now()},
      evidence:proofMissing?null:{schema_version:1,physical_run_id:nativeRunId,attempt_id:descriptorId,lease_id:"lease-"+number,grant_generation:1,
        process_identity_digest:digest({kind:"fake-original-host-proof",pid:30000+number}),termination_evidence_digest:digest({kind:"fake-validated-termination",lease:"lease-"+number}),
        terminated:true,resources_reclaimed:true,exit_code:0}};
  };
  const run=async(id:string)=>{const job=f.current(),intent=f.queue.dispatch(job.id,id,job.snapshot),controller=new AbortController();
    const promise=f.internal.runStep(job.id,id,intent,job.controlEpoch,controller.signal),key=job.id+":"+id;
    // 与原pump同一active生命周期，避免手动调用fixture缺失原active守卫。
    f.internal.active.set(key,{jobId:job.id,intentId:intent.id,controller,promise});
    try{await promise;}finally{f.internal.active.delete(key);f.internal.finalize(job.id);}return intent;};
  const finish=async()=>{f.internal.finalize(f.job.id);await f.internal.finalizingEvidence.get(f.job.id);};
  return {...f,run,finish,reviewFault:()=>reviewFault=true,proofMissing:()=>proofMissing=true};
}
async function beforeChecks(t:any){const f=await rig(t);await f.run("baseline:build");await f.run("implement");return f;}
async function complete(t:any){const f=await beforeChecks(t);await f.run("build");await f.run("focused-tests");await f.run("independent-review");await f.finish();return f;}
test("actual producer/immutable raw artifact/closed record/fresh independent reviewer completes real workflow",async t=>{
  const f=await complete(t),job=f.current();assert.equal(job.status,"COMPLETED",JSON.stringify({reason:job.reason,checks:job.checks,evidence:job.evidenceObservation}));
  assert.ok(job.evidenceRecords.length>=6);assert.equal(job.checks.length,3);assert.ok(job.checks.every((r:any)=>r.validity==="current"&&r.supportsPassed));
  for(const pointer of job.evidenceRecords){assert.ok(f.internal.artifacts.read(pointer.rawArtifactId,job.id,pointer.snapshot).content.length);
    assert.ok(f.internal.artifacts.read(pointer.recordRef,job.id,pointer.snapshot));}
  const inspected=await f.service.inspect(job.id);assert.equal(inspected.receiptCurrent,true);assert.equal(inspected.evidence.currentness,"reobserved");
  assert.equal(f.service.describe(job.id).evidence.currentness,"recorded_not_reobserved");
});
for(const disposition of ["nonzero","zero","allskip","assertion","required-id"])test("current "+disposition+" failure remains counted and blocks completion",async t=>{
  const f=await beforeChecks(t);await f.run("build");const original=globalThis[port];globalThis[port]=async(o:any)=>{const value=await original(o);if(o.program==="check"){
    value.exitCode=disposition==="nonzero"?2:0;value.stdout=disposition==="allskip"?'{"tests":1,"passed":0,"failed":0,"skipped":1}':
      disposition==="zero"?'{"tests":0,"passed":0,"failed":0,"skipped":0}':disposition==="required-id"?'{"tests":1,"passed":1,"failed":0,"skipped":0,"test_results":[{"id":"other","status":"passed"}]}':'{"tests":1,"passed":0,"failed":1,"skipped":0}';}return value;};
  await f.run("focused-tests");const job=f.current(),row=job.evidenceObservation.summary.rows.filter((r:any)=>r.checkId==="focused-tests").at(-1);
  assert.equal(row.validity,"current");assert.equal(row.result,"failed");assert.equal(row.supportsPassed,false);
  assert.ok(job.evidenceObservation.summary.total>=4);assert.ok(job.evidenceObservation.summary.failed>=1);
  assert.equal(job.verification["focused-tests"].status,"failed");assert.notEqual(job.status,"COMPLETED");
});
test("explicit missing process proof is current unknown; omitted record identity is invalid",async t=>{
  const f=await beforeChecks(t),original=globalThis[port];globalThis[port]=async(o:any)=>{const value=await original(o);if(o.program==="check")value.process_identity=null;return value;};await f.run("build");
  let observed=await f.service.inspect(f.job.id),row=observed.evidence.summary.rows.filter((r:any)=>r.checkId==="build").at(-1);
  assert.equal(row.validity,"current");assert.equal(row.result,"unknown");assert.equal(row.supportsPassed,false);
  const job=f.current(),pointer=job.evidenceRecords.at(-1),stored=f.internal.artifacts.read(pointer.recordRef,job.id,pointer.snapshot),bad=JSON.parse(stored.content);
  delete bad.origin.runtimeIdentity;pointer.recordRef=f.internal.artifacts.pin(job.id,pointer.snapshot,JSON.stringify(bad),"runtime").id;f.store.put("managed-jobs",job.id,job);
  observed=await f.service.inspect(job.id);row=observed.evidence.summary.rows.at(-1);assert.equal(row.validity,"invalid");assert.equal(row.counts,null);
});
test("same snapshot new configuration/spec revision re-reduces without mutating original raw artifacts",async t=>{
  const f=await complete(t),job=f.current(),raw=f.internal.artifacts.read(job.outputs.build,job.id,job.snapshot).content;
  f.meta.config_identity="b".repeat(64);let view=await f.service.inspect(job.id);assert.equal(view.receiptCurrent,false);assert.ok(view.evidence.summary.stale>0);
  assert.deepEqual(f.internal.artifacts.read(job.outputs.build,job.id,job.snapshot).content,raw);
  f.meta.config_identity="a".repeat(64);const plan=f.queue.job(job.id);f.store.put("jobs",job.id,{...plan,spec:{...plan.spec,version:2}});
  view=await f.service.inspect(job.id);assert.equal(view.receiptCurrent,false);assert.ok(view.evidence.summary.stale>0);
});
for(const fault of ["delete","bytes","scope"])test("real artifact "+fault+" invalidates acceptance but retains denominator",async t=>{
  const f=await complete(t),job=f.current(),pointer=job.evidenceRecords.find((r:any)=>r.stepId==="focused-tests"),meta=f.store.get<any>("artifacts",pointer.rawArtifactId);
  if(fault==="delete")fs.unlinkSync(join(f.store.root,"artifacts",pointer.rawArtifactId));
  if(fault==="bytes")fs.appendFileSync(join(f.store.root,"artifacts",pointer.rawArtifactId),"corruption");
  if(fault==="scope")f.store.put("artifacts",meta.id,{...meta,jobId:"foreign-job"});
  const view=await f.service.inspect(job.id);assert.equal(view.receiptCurrent,false);assert.ok(view.evidence.summary.invalid>0);
  assert.equal(view.evidence.summary.total,job.evidenceRecords.length);
});
test("reviewer model pass without delivered references or matched physical proof cannot complete",async t=>{
  const f=await beforeChecks(t);await f.run("build");await f.run("focused-tests");f.reviewFault();await f.run("independent-review");
  assert.notEqual(f.current().status,"COMPLETED");assert.ok(f.current().failures.some((r:any)=>r.code==="REVIEW_EVIDENCE_NOT_READ"));
  const g=await beforeChecks(t);await g.run("build");await g.run("focused-tests");g.proofMissing();await g.run("independent-review");
  assert.notEqual(g.current().status,"COMPLETED");assert.equal(g.current().checks.find((r:any)=>r.checkId==="independent-review").supportsPassed,false);
});
for(const action of ["pause","stop","owner","newconfig"])test("final currentness getter await after "+action+" publishes no acceptance",async t=>{
  const f=await beforeChecks(t);await f.run("build");await f.run("focused-tests");
  let release!:()=>void,entered!:()=>void;const barrier=new Promise<void>(r=>release=r),started=new Promise<void>(r=>entered=r);
  const original=f.internal.modernDelegateAdapter.semanticContext;
  f.internal.modernDelegateAdapter.semanticContext=async()=>{if(f.internal.finalizingEvidence.has(f.job.id)){entered();await barrier;}return original();};
  await f.run("independent-review");await started;
  if(action==="pause"||action==="stop")f.service.pause(f.job.id,action==="stop");
  if(action==="owner"){f.store.revokeOwner(f.owner);f.store.claimOwner(f.job.workScope,"new-owner");}
  if(action==="newconfig")f.config.limits.semanticAttemptsPerImplementationTask++;
  const prior=f.current(),pending=f.internal.finalizingEvidence.get(f.job.id);release();await pending;
  assert.notEqual(f.current().status,"COMPLETED");assert.equal(f.current().receipt?.status==="COMPLETED",false);
  if(action==="owner")assert.deepEqual(f.current(),prior);
  if(action==="pause"||action==="stop")assert.equal(f.current().status,prior.status);
});
test("modern legacy missing record cannot resume/adopt; late factual results retain original version",async t=>{
  const f=await beforeChecks(t);await f.run("build");f.service.pause(f.job.id);
  const job=f.current();job.checks[0].recordRef=null;f.store.put("managed-jobs",job.id,job);
  await assert.rejects(f.service.resume(job.id),/EVIDENCE_REQUIRES_RECONCILIATION/);
  assert.notEqual(f.current().status,"RUNNING");
  const pointer=job.evidenceRecords.find((r:any)=>r.stepId==="build"),raw=JSON.parse(f.internal.artifacts.read(pointer.rawArtifactId,job.id,pointer.snapshot).content);
  const original=structuredClone(raw);f.internal.retainLateResult(job,pointer.attemptId,"verification",raw);
  const plan=f.queue.job(job.id);f.store.put("jobs",job.id,{...plan,spec:{...plan.spec,version:2}});
  assert.equal(await f.internal.adoptLateVerification(f.current(),"build",f.store.intent(pointer.attemptId)),false);
  const late=f.store.get<any>("late-execution-results",pointer.attemptId);
  assert.deepEqual(JSON.parse(f.internal.artifacts.read(late.artifactId,job.id,late.snapshot).content),original);
});
