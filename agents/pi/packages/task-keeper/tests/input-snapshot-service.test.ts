// 真TaskService/SQLite/Scheduler；只原Host/getter/执行端口fake，不证明SDK/物理权限。
import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import { join } from "node:path";
import { fixture } from "./checker-host-async.test.ts";
import { semanticSource } from "../src/workspace/worktree.ts";
import { inputDigest } from "../src/evidence/context.ts";
const port=Symbol.for("task-keeper.test.async-check-port");
function deferred(){let resolve!:()=>void;const promise=new Promise<void>(r=>resolve=r);return {promise,resolve};}
export async function modern(t:any,configure?:(config:any)=>void){
 const f=await fixture(t,{configure}),file=join(f.candidate,"source.txt");fs.writeFileSync(file,"initial");
 Object.assign(f.runtime.installed,{schema_version:2,profile_id:"pi-full",runtime_identity:"a".repeat(64)});
 fs.mkdirSync(join(f.root,"runtime"),{recursive:true});fs.writeFileSync(join(f.root,"runtime/official-task-keeper-delegate.mjs"),"inert own adapter source fixture, never executed");
 const scope={schema_version:1,source_root:f.candidate,candidate_root:f.candidate,root_identity:null,creating:true,policy:{explicit_inputs:["source.txt"],artifact_exclusions:[]},protected_inputs:[],outside_exclusions:[]};
 const hash="a".repeat(64),meta={config_identity:hash,effective_config_digest:hash,host_manifest_identity:hash,policy_digest:hash,project_constraints_digest:hash,resources_digest:hash,runtime_identity:hash,lock_identity:hash,slice_identity:hash,capability_provider_digest:hash,model_routes:[],environment:{platform:"linux",architecture:"x64",node_version:"v24.14.0",sdk_version:"1.0.1",declared_nonsecret_variables:[{name:"LANG",value:"C.UTF-8"}]}};
 let getterCalls=0;await f.internal.delegateAdapter();f.internal.modernDelegateAdapter.semanticContext=async()=>{getterCalls++;return structuredClone(meta);};
 const original=globalThis[port];globalThis[port]=async(o:any)=>{const result=await original(o);if(o.program==="workspace")result.workspace_result.semantic_source=semanticSource(f.candidate,scope);return result;};
 return {...f,file,meta,scope,getterCalls:()=>getterCalls,readSource:()=>semanticSource(f.candidate,scope)};
}
export async function ready(t:any,configure?:(config:any)=>void){const f=await modern(t,configure),p=f.begin();await f.started.promise;f.release();await p;assert.equal(f.current().status,"RUNNING",f.current().reason);return f;}

test("modern preparation publishes separate initial semantic artifact; same source capture preserves digest",async t=>{
 const f=await ready(t),job=f.current();assert.match(job.initialInputSnapshotDigest,/^[a-f0-9]{64}$/);assert.equal(job.inputSnapshotDigest,job.initialInputSnapshotDigest);assert.ok(job.outputs.initialInputSnapshot);assert.equal(f.queue.job(job.id).spec.version,1);assert.equal(f.counters.creates,1);assert.equal(f.counters.checks,0);assert.ok(f.getterCalls()>0);
 const source=await f.internal.currentCheckContracts(job),captured=await f.internal.capture(job),again=await f.internal.inputSnapshot(f.current(),captured,source.contracts);assert.equal(again.digest,job.inputSnapshotDigest);
});
for(const action of ["pause","stop","owner","policy"] as const)test(`delayed actual semantic getter after ${action} cannot publish plan`,async t=>{
 const f=await modern(t),started=deferred(),reply=deferred(),producer=f.internal.modernDelegateAdapter.semanticContext;
 f.internal.modernDelegateAdapter.semanticContext=async()=>{started.resolve();await reply.promise;return producer();};
 const pending=f.begin();await f.started.promise;f.release();await started.promise;
 if(action==="pause"||action==="stop")f.service.pause(f.job.id,action==="stop");
 if(action==="owner"){f.store.revokeOwner(f.owner);f.store.claimOwner(f.job.workScope,"replacement");}
 if(action==="policy")f.config.limits.semanticAttemptsPerImplementationTask++;
 const prior=f.current();reply.resolve();await pending;assert.equal(f.store.get("jobs",f.job.id),null);assert.equal(f.counters.checks,0);if(action==="owner")assert.deepEqual(f.current(),prior);if(action==="pause"||action==="stop")assert.equal(f.current().status,prior.status);
});
test("modern pause with acknowledged workspace resumes once, without recreation, capturing semantic source",async t=>{
 const f=await modern(t),pending=f.begin();await f.started.promise;f.service.pause(f.job.id);f.release();await pending;f.internal.finalize(f.job.id);await f.service.resume(f.job.id);
 assert.equal(f.counters.creates,1);assert.equal(f.current().status,"RUNNING");assert.match(f.current().initialInputSnapshotDigest,/^[a-f0-9]{64}$/);assert.equal(f.queue.job(f.job.id).spec.version,1);
});
test("verifier has exact semantic origin; external source mutation retains passed facts but stales applicability",async t=>{
 const f=await ready(t),original=globalThis[port];globalThis[port]=async(o:any)=>{const result=await original(o);if(o.program==="check")fs.writeFileSync(f.file,"external modification during verifier");return result;};
 const intent=f.queue.dispatch(f.job.id,"baseline:build","tree");await f.internal.runStep(f.job.id,"baseline:build",intent,f.current().controlEpoch,new AbortController().signal);
 const result=f.current().verification["baseline:build"];assert.match(result.inputSnapshotDigest,/^[a-f0-9]{64}$/);assert.equal(result.status,"passed");assert.equal(result.snapshotComparison,null);assert.equal(f.current().evidenceObservation.summary.rows.filter((r:any)=>r.checkId===result.checkId&&r.layer==="checker").at(-1).validity,"stale");assert.equal(result.exitCode,0);assert.notEqual(f.queue.job(f.job.id).steps.find((s:any)=>s.id==="baseline:build").status,"passed");assert.notEqual(f.current().status,"COMPLETED");assert.equal(f.current().checks.filter((x:any)=>x.supportsPassed===true).length,0);
});
test("accepted Worker edit is not compared to initial semantic input; next verifier captures edited source",async t=>{
 const f=await ready(t),initial=f.current().inputSnapshotDigest;
 const baseline=f.queue.dispatch(f.job.id,"baseline:build","tree");await f.internal.runStep(f.job.id,"baseline:build",baseline,f.current().controlEpoch,new AbortController().signal);
 let workers=0;f.internal.modernDelegateAdapter.execute=async(_input:any,_ctx:any,_signal:any,onDispatch:any)=>{workers++;onDispatch();fs.writeFileSync(f.file,"authorized worker edit");return {status:"ended",terminationConfirmed:true,notSent:false,nativeRunId:"fake-worker",observations:[]};};
 const worker=f.queue.dispatch(f.job.id,"implement","tree");await f.internal.runStep(f.job.id,"implement",worker,f.current().controlEpoch,new AbortController().signal);
 assert.equal(workers,1);assert.equal(f.queue.job(f.job.id).steps.find((x:any)=>x.id==="implement").status,"passed");const next=f.current().inputSnapshotDigest;assert.notEqual(next,initial);
 const verify=f.queue.dispatch(f.job.id,"build","tree");await f.internal.runStep(f.job.id,"build",verify,f.current().controlEpoch,new AbortController().signal);
 assert.equal(f.current().verification.build.inputSnapshotDigest,next);assert.equal(f.current().verification.build.snapshotComparison,null);assert.equal(f.current().evidenceObservation.summary.rows.filter((r:any)=>r.checkId==="build"&&r.layer==="checker").at(-1).validity,"current");assert.equal(f.current().verification.build.status,"passed");
});
test("missing private modern getter fails closed, without plan or checker",async t=>{
 const f=await modern(t);delete f.internal.modernDelegateAdapter.semanticContext;const p=f.begin();await f.started.promise;f.release();await p;assert.equal(f.store.get("jobs",f.job.id),null);assert.equal(f.counters.checks,0);assert.match(f.current().reason,/INPUT_SNAPSHOT_CONTEXT_REQUIRED/);
});

test("source changes during semantic getter await make no checker dispatch",async t=>{
 const f=await ready(t),started=deferred(),reply=deferred(),producer=f.internal.modernDelegateAdapter.semanticContext;
 f.internal.modernDelegateAdapter.semanticContext=async()=>{started.resolve();await reply.promise;return producer();};
 const intent=f.queue.dispatch(f.job.id,"baseline:build","tree"),pending=f.internal.runStep(f.job.id,"baseline:build",intent,f.current().controlEpoch,new AbortController().signal);
 await started.promise;fs.writeFileSync(f.file,"external edit while getter awaited");reply.resolve();await pending;assert.equal(f.counters.checks,0);assert.match(f.current().reason,/INPUT_SNAPSHOT_CHANGED_DURING_CAPTURE/);assert.notEqual(f.current().status,"COMPLETED");
});
for(const disposition of ["nonzero","zero","allskip"] as const)test(`stale ${disposition} keeps failed facts and never supports passed acceptance`,async t=>{
 const f=await ready(t);
 const baseline=f.queue.dispatch(f.job.id,"baseline:build","tree");await f.internal.runStep(f.job.id,"baseline:build",baseline,f.current().controlEpoch,new AbortController().signal);
 f.internal.modernDelegateAdapter.execute=async(_input:any,_ctx:any,_signal:any,onDispatch:any)=>{onDispatch();return {status:"ended",terminationConfirmed:true,notSent:false,nativeRunId:"fake-worker",observations:[]};};
 const worker=f.queue.dispatch(f.job.id,"implement","tree");await f.internal.runStep(f.job.id,"implement",worker,f.current().controlEpoch,new AbortController().signal);
 const build=f.queue.dispatch(f.job.id,"build","tree");await f.internal.runStep(f.job.id,"build",build,f.current().controlEpoch,new AbortController().signal);
 const original=globalThis[port];globalThis[port]=async(o:any)=>{const value=await original(o);if(o.program==="check"){fs.writeFileSync(f.file,"external drift");value.exitCode=disposition==="nonzero"?1:0;value.stdout=disposition==="allskip"?'{"tests":1,"passed":0,"failed":0,"skipped":1}':'{"tests":0,"passed":0,"failed":0,"skipped":0}';}return value;};
 const intent=f.queue.dispatch(f.job.id,"focused-tests","tree");await f.internal.runStep(f.job.id,"focused-tests",intent,f.current().controlEpoch,new AbortController().signal);
 const result=f.current().verification["focused-tests"];assert.equal(result.status,"failed");assert.equal(result.snapshotComparison,null);assert.equal(f.current().evidenceObservation.summary.rows.filter((r:any)=>r.checkId===result.checkId&&r.layer==="checker").at(-1).validity,"stale");assert.equal(result.exitCode,disposition==="nonzero"?1:0);assert.notEqual(f.current().status,"COMPLETED");assert.equal(f.current().checks.some((x:any)=>x.checkId==="focused-tests"&&x.supportsPassed===true),false);
});

test("modern inspect refuses stale origin semantic identity, normal resume refuses new external input",async t=>{
 const f=await ready(t),job=f.current(),result={checkId:"build",jobId:job.id,snapshot:"tree",specVersion:1,policyDigest:job.policyDigest,contractDigest:"a".repeat(64),inputSnapshotDigest:job.inputSnapshotDigest,snapshotComparison:"current",status:"passed"};
 const artifact=f.internal.artifacts.pin(job.id,"tree",JSON.stringify(result),"verifier");job.checks=[{checkId:"build",status:"passed",snapshot:"tree",specVersion:1,policyDigest:job.policyDigest,source:"verifier",artifactId:artifact.id}];job.receipt={status:"PASSED",snapshot:"tree",specVersion:1,reasons:[]};f.store.put("managed-jobs",job.id,job);
 fs.writeFileSync(f.file,"unmanaged external input after evidence");const inspected=await f.service.inspect(job.id);assert.equal(inspected.receiptCurrent,false);assert.notEqual(inspected.status,"COMPLETED");
 f.service.pause(job.id);f.internal.finalize(job.id);await assert.rejects(f.service.resume(job.id),/INPUT_SNAPSHOT_CHANGED_REQUIRES_RECONCILIATION/);assert.notEqual(f.current().status,"RUNNING");
});
test("modern late adoption rejects missing or old semantic origin rather than stamping current",async t=>{
 const f=await ready(t),job=f.current(),intent=f.queue.dispatch(job.id,"baseline:build","tree");f.store.markSent(f.owner,intent.id);f.store.acknowledge(intent.id,"fake-run");f.queue.pause(job.id);job.status="PAUSED";job.controlEpoch++;f.store.put("managed-jobs",job.id,job);
 const originalResult={checkId:"build",jobId:job.id,snapshot:"tree",specVersion:1,policyDigest:job.policyDigest,contractDigest:"a".repeat(64),status:"passed",notSent:false,terminationConfirmed:true,exitCode:0};
 f.internal.retainLateResult(job,intent.id,"verification",originalResult);assert.equal(await f.internal.adoptLateVerification(f.current(),"baseline:build",intent),false);
 assert.equal(f.store.intent(intent.id)?.status,"acked");assert.equal(f.current().verification["baseline:build"],undefined);
});
