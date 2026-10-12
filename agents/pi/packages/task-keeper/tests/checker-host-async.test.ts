// 真 service core/SQLite/Scheduler，只有原 auxiliary/RPC 端口为 fake；不是 SDK/namespace 资格。
import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import childProcess from "node:child_process";
import { registerHooks, syncBuiltinESMExports } from "node:module";
import { configured } from "./fixtures/config.ts";
import { Store } from "../src/store/database.ts";
import { Scheduler } from "../src/orchestration/scheduler.ts";
import { digest } from "../src/contracts/primitives.ts";

const runtimeKey = Symbol.for("agentcfg.pi.runtime.v1"), portKey = Symbol.for("task-keeper.test.async-check-port");
const hooks = registerHooks({ resolve(specifier, context, next) {
  if (specifier === "@agentcfg/pi-runtime/auxiliary-executor" && /\/(verification\/supervisor|workspace\/async-workspace)\.ts$/.test(context.parentURL ?? ""))
    return { url: "data:text/javascript," + encodeURIComponent(`export async function runAuxiliary(options) { return globalThis[Symbol.for("task-keeper.test.async-check-port")](options); }`), shortCircuit: true };
  return next(specifier, context);
} });
const { TaskServiceCore } = await import("../src/orchestration/service-core.ts");
const { verificationContracts } = await import("../src/verification/inputs.ts");
const { supervisedCommand } = await import("../src/verification/supervisor.ts");
hooks.deregister();
function deferred<T>() { let resolve!: (v: T) => void, reject!: (e: unknown) => void; const promise = new Promise<T>((a,b) => { resolve=a;reject=b; }); return { promise, resolve, reject }; }
export async function fixture(t: any,options:{configure?:(config:any)=>void}={}) {
  const root = mkdtempSync(join(tmpdir(), "async-check-host-")), cwd = join(root,"source"), candidate = join(root,"candidate");
  mkdirSync(cwd);mkdirSync(candidate);mkdirSync(join(root,"supervisor/scripts"),{recursive:true});writeFileSync(join(root,"supervisor/scripts/pi-project-check"),"inert helper");
  const git = t.mock.method(childProcess,"execFileSync",(_exe: unknown,args: string[]) => {
    if(args.includes("--git-common-dir"))return Buffer.from(join(cwd,".git")+"\n");
    if(args.includes("--show-toplevel"))return Buffer.from(cwd+"\n");
    if(args.includes("--verify"))return Buffer.from("a".repeat(40)+"\n");return Buffer.from("");
  });syncBuiltinESMExports();
  const config=configured();config.features.managedWorkflows=true;
  for(const role of ["worker","reviewer","scout"]){config.roles[role]={route:"primary",profileRef:role};config.executionProfiles[role]={tools:[],requiredCapabilities:[],timeoutMs:1000,maxModelTurns:1,toolTimeoutMs:1000,thinking:"off"};}
  for(const id of ["build","focused-tests"])config.verificationBindings[id]={executable:process.execPath,args:["-e","fixed literal checker"],environment:{},timeoutMs:1000,kind:id==="build"?"build":"tests",parser:"json",minimumTests:1,inputs:[]};
  options.configure?.(config);
  const counters={creates:0,snapshots:0,checks:0,dispatches:0,queries:0}, oldRuntime=globalThis[runtimeKey], oldPort=globalThis[portKey];
  const barrier=deferred<void>(), started=deferred<void>();let hold=true, hash="a".repeat(64), queryError: unknown=null;
  const runtime={owner:{role:"manager",instance_id:"fake"},runtimeRoot:root,installed:{runtime_identity:"fake-fixed"},manifest:{options:{checks:Object.fromEntries(Object.entries(config.verificationBindings).map(([id,b])=>[id,{executable:b.executable,args:b.args,timeout_seconds:1,kind:b.kind,parser:b.parser,minimum_tests:1,inputs:[],...(b.requiredTestIds?{required_test_ids:b.requiredTestIds}:{})}]))}},supervisor:{async call(method:string,args:any){
    assert.equal(method,"check_binding_snapshot");counters.queries++;started.resolve();if(hold)await barrier.promise;if(queryError)throw queryError;
    return {schema_version:1,check_id:args.check_id,task_id:args.task_id,contract_digest:hash};
  }}};
  globalThis[runtimeKey]=runtime;globalThis[portKey]=async (o:any)=>{
    o.onDispatch?.();counters.dispatches++;
    if(o.program==="workspace"){
      if(o.payload.operation==="create")counters.creates++;else counters.snapshots++;
      return {terminationConfirmed:true,exitCode:0,workspace_result:o.payload.operation==="create"?{cwd:candidate,path:candidate,snapshot:{id:"tree",files:[]},baseline:{tree:"baseline"}}:{snapshot:{id:"tree",files:[]},patch:""}};
    }
    counters.checks++;assert.equal(o.payload.contract_digest,hash);return {stdout:'{"tests":1,"passed":1,"failed":0,"skipped":0}',stderr:"",truncated:false,timedOut:false,cancelled:false,started:true,exitCode:0,terminationConfirmed:true,lease_id:"fake",process_identity:{pid:42000+counters.checks,boot_id:"fake-boot",start_time:String(counters.checks),namespace:"fake-pid-namespace",uid:process.getuid(),platform:"linux"}};
  };
  const store=new Store(join(root,"state")), ctx={cwd,modelRegistry:{find:()=>undefined},sessionManager:{getBranch:()=>[],getHeader:()=>null,getSessionId:()=>"session",getSessionFile:()=>null}};
  const service=new TaskServiceCore({appendEntry(){}} as never,store,config,ctx as never,()=>{},()=>config,{},()=>({runtimeContract:()=>({fixed:"own fake runtime"}),async close(){},async dispatch(){throw Error("unexpected delegate dispatch");}}));
  const internal=service as any;internal.wake=()=>{};
  const job=service.submit("fix","async source-bound checker"),owner=store.owner(job.workScope)!,queue=new Scheduler(store,owner);
  store.prepare(owner,"job-scope-fixture","job-scope",{jobId:job.id},[{id:job.projectId,capacity:1,units:1}]);store.prepare(owner,"setup-fixture","workspace-create",{jobId:job.id},[{id:"workspace-io",capacity:1,units:1}]);
  job.jobLease="job-scope-fixture";job.status="RUNNING";job.reason="preparing_workspace";store.put("managed-jobs",job.id,job);
  t.after(async()=>{await service.dispose();store.close();git.mock.restore();syncBuiltinESMExports();globalThis[runtimeKey]=oldRuntime;globalThis[portKey]=oldPort;});
  return {root,candidate,config,runtime,service,internal,store,queue,owner,job,counters,started,barrier,begin:()=>internal.prepare(job,"setup-fixture",new AbortController().signal).finally(()=>{if(!counters.queries)started.reject(Error("before-query:"+store.get<any>("managed-jobs",job.id)?.reason));}),release:()=>{hold=false;barrier.resolve();},changeHash:()=>{hash="b".repeat(64);},queryError:(e:unknown)=>{queryError=e;},current:()=>store.get<any>("managed-jobs",job.id)!};
}

test("workspace ack is durable before delayed Host query; success submits once with independent contract",async t=>{
  const f=await fixture(t),pending=f.begin();await f.started.promise;
  assert.equal(f.current().cwd,f.candidate);assert.equal(f.current().snapshot,"tree");assert.equal(f.current().status,"RUNNING");assert.equal(f.store.get("jobs",f.job.id),null);
  f.release();await pending;assert.equal(f.current().status,"RUNNING");assert.equal(f.current().checkBindingSnapshotDigest,digest({build:"a".repeat(64),"focused-tests":"a".repeat(64)}));assert.ok(f.current().checkInputsDigest);assert.equal(f.queue.job(f.job.id).spec.version,1);
  assert.equal(f.counters.creates,1);assert.equal(f.counters.checks,0);
});

for(const action of ["pause","stop","owner","policy","error"] as const)test(`delayed Host reply after ${action} cannot publish a plan or revive control`,async t=>{
  const f=await fixture(t),pending=f.begin();await f.started.promise;
  if(action==="pause"||action==="stop")f.service.pause(f.job.id,action==="stop");
  if(action==="owner"){f.store.revokeOwner(f.owner);f.store.claimOwner(f.job.workScope,"replacement-owner");}
  if(action==="policy")f.config.limits.semanticAttemptsPerImplementationTask++;
  if(action==="error")f.queryError(Error("host unavailable"));
  const before=f.current();f.release();await pending;assert.equal(f.store.get("jobs",f.job.id),null);assert.equal(f.counters.checks,0);
  if(action==="pause"||action==="stop"){assert.equal(f.current().controlEpoch,before.controlEpoch);assert.equal(f.current().status,before.status);assert.equal(f.current().cancelRequested,before.cancelRequested);}
  else if(action==="owner")assert.deepEqual(f.current(),before);
  else assert.equal(f.current().status,"BLOCKED");
});

test("paused durable workspace without plan resumes by capture/query, never recreates and submits once",async t=>{
  const f=await fixture(t),pending=f.begin();await f.started.promise;f.service.pause(f.job.id);f.release();await pending;
  f.internal.finalize(f.job.id);await f.service.resume(f.job.id);
  assert.equal(f.counters.creates,1);assert.equal(f.counters.snapshots,1);assert.equal(f.current().status,"RUNNING");assert.equal(f.queue.job(f.job.id).spec.version,1);
  await assert.rejects(f.service.resume(f.job.id),/JOB_ALREADY_RUNNING/);
});

test("changed Host source blocks a real queued Worker before delegate/check dispatch and cannot approve it locally",async t=>{
  const f=await fixture(t),pending=f.begin();await f.started.promise;f.release();await pending;
  const baseline=f.queue.dispatch(f.job.id,"baseline:build","tree");f.store.markSent(f.owner,baseline.id);f.queue.finish(f.job.id,"baseline:build",{terminated:true,passed:true,artifactId:f.internal.artifacts.pin(f.job.id,"tree",JSON.stringify({mock:true,baseline:true}),"verifier").id},1);
  const intent=f.queue.dispatch(f.job.id,"implement","tree"),job=f.current();f.changeHash();
  await f.internal.runStep(f.job.id,"implement",intent,job.controlEpoch,new AbortController().signal);
  assert.equal(f.current().status,"BLOCKED");assert.match(f.current().reason,/CHECK_IMPLEMENTATION_CHANGED_REQUIRES_RECONCILIATION/);assert.equal(f.counters.checks,0);assert.equal(f.store.intent(intent.id)!.status,"not_sent");assert.equal(f.current().checkInputChange,undefined);
});

test("snapshot DTO is closed; late canceled query publishes no aggregate, missing dispatch contract sends nothing",async t=>{
  const f=await fixture(t);f.release();const bindings=f.config.verificationBindings;
  for(const result of [null,{schema_version:1,check_id:"build",task_id:f.job.id,contract_digest:"short"},{schema_version:1,check_id:"build",task_id:f.job.id,contract_digest:"a".repeat(64),approved:true}]){
    const call=f.runtime.supervisor.call;f.runtime.supervisor.call=async()=>result as any;
    await assert.rejects(verificationContracts(bindings,f.candidate,f.job.id),/CHECK_BINDING_SNAPSHOT_INVALID/);f.runtime.supervisor.call=call;
  }
  const wait=deferred<any>(),controller=new AbortController();f.runtime.supervisor.call=async()=>wait.promise;
  const querying=verificationContracts(bindings,f.candidate,f.job.id,controller.signal);controller.abort();wait.resolve({schema_version:1,check_id:"build",task_id:f.job.id,contract_digest:"a".repeat(64)});
  await assert.rejects(querying,/CANCELLED/);
  await assert.rejects(supervisedCommand(bindings.build,f.candidate,{}, {checkId:"build",jobId:f.job.id,maxBytes:1000,killGraceMs:100}),/CHECK_CONTRACT_REQUIRED/);assert.equal(f.counters.checks,0);
});

async function prepared(t: any) { const f=await fixture(t),p=f.begin();await f.started.promise;f.release();await p;return f; }
function holdNext(f: any) {
  const started=deferred<void>(),reply=deferred<void>();
  const original=f.runtime.supervisor.call;
  f.runtime.supervisor.call=async(method: string,args: any)=>{started.resolve();await reply.promise;return original(method,args);};
  return {started,release:()=>reply.resolve()};
}
for(const action of ["pause-error","stop","owner","policy","cwd","snapshot","version"] as const)test(`normal resume Host await rejects ${action} without reviving plan`,async t=>{
  const f=await prepared(t);f.service.pause(f.job.id);const gate=holdNext(f),resuming=f.service.resume(f.job.id);await gate.started.promise;
  if(action==="pause-error"){f.service.pause(f.job.id);f.queryError(Error("late host failure"));}
  else if(action==="stop")f.service.pause(f.job.id,true);
  else if(action==="owner"){f.store.revokeOwner(f.owner);f.store.claimOwner(f.job.workScope,"new-control");}
  else if(action==="policy")f.config.limits.semanticAttemptsPerImplementationTask++;
  else if(action==="version"){const plan=f.queue.job(f.job.id);plan.spec.version++;f.store.put("jobs",f.job.id,plan);}
  else {const job=f.current();job[action]=action==="cwd"?f.root:"new-snapshot";f.store.put("managed-jobs",f.job.id,job);}
  const before=f.current();gate.release();await assert.rejects(resuming);assert.deepEqual(f.current(),before);assert.equal(f.counters.creates,1);assert.equal(f.counters.checks,0);assert.equal(f.queue.job(f.job.id).paused,true);
});

test("normal resume and local acceptance approval cannot adopt changed Host implementation",async t=>{
  const f=await prepared(t);f.service.pause(f.job.id);f.changeHash();
  await assert.rejects(f.service.resume(f.job.id),/CHECK_IMPLEMENTATION_CHANGED_REQUIRES_RECONCILIATION/);
  const {verificationInputs}=await import("../src/verification/inputs.ts");
  const job=f.current(),local=verificationInputs(f.config.verificationBindings,f.candidate);job.checkInputChange={digest:local.digest,artifact:"existing-local-change"};f.store.put("managed-jobs",job.id,job);
  const source=job.checkBindingSnapshotDigest,version=f.queue.job(job.id).spec.version;
  await assert.rejects(f.service.approveChecks(job.id,local.digest),/CHECK_IMPLEMENTATION_CHANGED_REQUIRES_RECONCILIATION/);
  assert.equal(f.current().checkBindingSnapshotDigest,source);assert.equal(f.queue.job(job.id).spec.version,version);assert.equal(f.current().outputs.checkApproval,undefined);assert.equal(f.counters.checks,0);
});

test("inspect cannot certify receipt after delayed control loss or changed Host source",async t=>{
  const f=await prepared(t);f.service.pause(f.job.id);const job=f.current();job.receipt={status:"BLOCKED",snapshot:"tree",specVersion:1,reasons:[],nativeStatus:"fixture"};f.store.put("managed-jobs",job.id,job);
  const gate=holdNext(f),inspecting=f.service.inspect(job.id);await gate.started.promise;f.service.pause(job.id);gate.release();
  const result=await inspecting;assert.equal(result.receiptCurrent,false);assert.equal(f.current().status,"PAUSED");assert.equal(f.counters.checks,0);
});

test("late verifier result remains unadopted when the Host source changed",async t=>{
  const f=await prepared(t),intent=f.queue.dispatch(f.job.id,"baseline:build","tree");f.store.markSent(f.owner,intent.id);
  const job=f.current();job.status="PAUSED";f.store.put("managed-jobs",job.id,job);f.queue.pause(job.id);
  const artifact=f.internal.artifacts.pin(job.id,"tree",JSON.stringify({jobId:job.id,snapshot:"tree",checkId:"build",terminationConfirmed:true,notSent:true,
    contractDigest:"a".repeat(64),specVersion:intent.payload.specVersion,policyDigest:intent.payload.policyDigest,supervisor:{namespaceStopped:true,launcherStopped:true,commandStarted:false}}),"runtime");
  f.store.put("late-execution-results",intent.id,{jobId:job.id,snapshot:"tree",kind:"verification",artifactId:artifact.id,ownerEpoch:intent.epoch});f.changeHash();
  await assert.rejects(f.internal.adoptLateVerification(job,"baseline:build",intent),/CHECK_IMPLEMENTATION_CHANGED_REQUIRES_RECONCILIATION/);
  assert.equal(f.current().verification["baseline:build"],undefined);assert.equal(f.queue.job(job.id).steps.find(s=>s.id==="baseline:build")!.status,"running");assert.equal(f.counters.checks,0);
});

test("verifier dispatch receives exactly prepared Host contract and saves it in the result",async t=>{
  const f=await prepared(t),intent=f.queue.dispatch(f.job.id,"baseline:build","tree"),job=f.current();
  await f.internal.runStep(job.id,"baseline:build",intent,job.controlEpoch,new AbortController().signal);
  assert.equal(f.counters.checks,1);assert.equal(f.current().verification["baseline:build"].contractDigest,"a".repeat(64));assert.equal(f.store.intent(intent.id)!.status,"settled");
});

for(const action of ["pause","stop","owner"] as const)test(`Worker source-query ${action} winner makes no delegate/check dispatch`,async t=>{
  const f=await prepared(t),baseline=f.queue.dispatch(f.job.id,"baseline:build","tree");f.store.markSent(f.owner,baseline.id);
  const artifact=f.internal.artifacts.pin(f.job.id,"tree","mock baseline evidence","verifier");f.queue.finish(f.job.id,"baseline:build",{terminated:true,passed:true,artifactId:artifact.id},1);
  const intent=f.queue.dispatch(f.job.id,"implement","tree"),job=f.current(),gate=holdNext(f),running=f.internal.runStep(job.id,"implement",intent,job.controlEpoch,new AbortController().signal);
  await gate.started.promise;
  if(action==="owner"){f.store.revokeOwner(f.owner);f.store.claimOwner(job.workScope,"fresh-owner");}else f.service.pause(job.id,action==="stop");
  const before=f.current();gate.release();await running;assert.equal(f.counters.checks,0);assert.equal(f.counters.dispatches,1);
  if(action==="owner")assert.deepEqual(f.current(),before);else {assert.equal(f.current().controlEpoch,before.controlEpoch);assert.equal(f.current().cancelRequested,before.cancelRequested);}
});

test("local approval async pause winner cannot publish a revision; unchanged Host source can approve local inputs only",async t=>{
  const f=await prepared(t);f.service.pause(f.job.id);
  const {verificationInputs}=await import("../src/verification/inputs.ts"),local=verificationInputs(f.config.verificationBindings,f.candidate);
  const job=f.current();job.checkInputChange={digest:local.digest,artifact:"declared-local-change"};f.store.put("managed-jobs",job.id,job);
  const gate=holdNext(f),approval=f.service.approveChecks(job.id,local.digest);await gate.started.promise;f.service.pause(job.id);const before=f.current();gate.release();
  await assert.rejects(approval);assert.deepEqual(f.current(),before);assert.equal(f.queue.job(job.id).spec.version,1);
  await f.service.approveChecks(job.id,local.digest);assert.equal(f.queue.job(job.id).spec.version,2);assert.equal(f.current().checkBindingSnapshotDigest,before.checkBindingSnapshotDigest);assert.deepEqual(f.current().checkBindingContracts,before.checkBindingContracts);
});

test("paused preparation errors remain paused; missing facts or unsettled setup cannot recreate a workspace",async t=>{
  const f=await fixture(t),pending=f.begin();await f.started.promise;f.service.pause(f.job.id);f.queryError(Error("query after pause failed"));f.release();await pending;
  assert.equal(f.current().status,"PAUSED");assert.equal(f.store.get("jobs",f.job.id),null);
  const job=f.current();job.initialSnapshot=null;f.store.put("managed-jobs",job.id,job);
  await assert.rejects(f.service.resume(job.id),/RECONCILIATION/);assert.equal(f.counters.creates,1);
  job.initialSnapshot="tree";f.store.put("managed-jobs",job.id,job);f.store.prepare(f.owner,"unsettled-fixture","workspace-create",{jobId:job.id},[]);
  await assert.rejects(f.service.resume(job.id),/RECONCILIATION/);assert.equal(f.counters.creates,1);
});

test("binding/runtime mutation and pre-cancel reject Host query result without aggregate publication",async t=>{
  const f=await fixture(t),controller=new AbortController();controller.abort();
  await assert.rejects(verificationContracts(f.config.verificationBindings,f.candidate,f.job.id,controller.signal),/CANCELLED/);assert.equal(f.counters.queries,0);
  const querying=verificationContracts(f.config.verificationBindings,f.candidate,f.job.id);await f.started.promise;f.runtime.manifest.options.checks.build.args=["-e","changed literal"];
  f.release();await assert.rejects(querying,/STALE|BINDING_CHANGED/);
});


test("optional verifier cannot skip a failed Host-source gate into an accepted workflow",async t=>{
  const f=await prepared(t),plan=f.queue.job(f.job.id);plan.steps[0].optional=true;f.store.put("jobs",f.job.id,plan);
  const intent=f.queue.dispatch(f.job.id,"baseline:build","tree"),job=f.current();f.changeHash();
  await f.internal.runStep(job.id,"baseline:build",intent,job.controlEpoch,new AbortController().signal);
  assert.equal(f.current().status,"BLOCKED");assert.match(f.current().reason,/CHECK_IMPLEMENTATION_CHANGED/);assert.notEqual(f.queue.job(job.id).steps[0].status,"skipped");assert.equal(f.counters.checks,0);
});

async function completeMockWorkflow(f: any) {
  const baseline=f.queue.dispatch(f.job.id,"baseline:build","tree");await f.internal.runStep(f.job.id,"baseline:build",baseline,f.current().controlEpoch,new AbortController().signal);
  const writer=f.queue.dispatch(f.job.id,"implement","tree"),wa=f.internal.artifacts.pin(f.job.id,"tree","controlled mock implementation result","runtime");f.store.markSent(f.owner,writer.id);f.queue.finish(f.job.id,"implement",{terminated:true,passed:true,artifactId:wa.id},1);
  for(const id of ["build","focused-tests"]){const intent=f.queue.dispatch(f.job.id,id,"tree");await f.internal.runStep(f.job.id,id,intent,f.current().controlEpoch,new AbortController().signal);}

}

test("same-snapshot old verifier origin cannot be restamped by an N+1 receipt, while fresh N+1 results are current",async t=>{
  const f=await prepared(t);await completeMockWorkflow(f);const oldResults=[f.current().verification.build,f.current().verification["focused-tests"]];
  assert.equal(oldResults[0].specVersion,1);f.service.pause(f.job.id);
  const {verificationInputs}=await import("../src/verification/inputs.ts"),local=verificationInputs(f.config.verificationBindings,f.candidate),paused=f.current();
  paused.checkInputChange={digest:local.digest,artifact:"controlled local acceptance revision"};f.store.put("managed-jobs",paused.id,paused);
  await f.service.approveChecks(paused.id,local.digest);await f.service.resume(paused.id);const changed=f.current();assert.equal(f.queue.job(changed.id).spec.version,2);
  for(const id of ["build","focused-tests"]){const intent=f.queue.dispatch(changed.id,id,"tree");await f.internal.runStep(changed.id,id,intent,changed.controlEpoch,new AbortController().signal);}
  const review=f.queue.dispatch(changed.id,"independent-review","tree"),artifact=f.internal.artifacts.pin(changed.id,"tree","mock current review","reviewer");f.store.markSent(f.owner,review.id);f.queue.finish(changed.id,"independent-review",{terminated:true,passed:true,artifactId:artifact.id},1);
  const current=f.current();current.checks.push({checkId:"independent-review",status:"passed",snapshot:"tree",specVersion:2,policyDigest:current.policyDigest,source:"reviewer",artifactId:artifact.id});f.store.put("managed-jobs",current.id,current);f.internal.finalize(current.id);
  assert.equal(f.current().verification.build.specVersion,2);assert.equal((await f.service.inspect(current.id)).receiptCurrent,true);
  const forged=f.current(),stale=f.internal.artifacts.pin(forged.id,"tree",JSON.stringify(oldResults[0]),"verifier");forged.checks.find((row:any)=>row.checkId==="build").artifactId=stale.id;f.store.put("managed-jobs",forged.id,forged);
  const result=await f.service.inspect(forged.id);assert.equal(result.receiptCurrent,false);assert.match(result.reason,/acceptance_artifact_missing_or_changed/);
});

test("late adoption rejects an old same-snapshot origin and missing legacy tuple without stamping current",async t=>{
  const f=await prepared(t),intent=f.queue.dispatch(f.job.id,"baseline:build","tree"),artifact=f.internal.artifacts.pin(f.job.id,"tree",JSON.stringify({jobId:f.job.id,snapshot:"tree",checkId:"build",terminationConfirmed:true,notSent:true,contractDigest:"a".repeat(64),
    specVersion:intent.payload.specVersion,policyDigest:intent.payload.policyDigest,supervisor:{namespaceStopped:true,launcherStopped:true,commandStarted:false}}),"runtime");
  f.queue.finish(f.job.id,"baseline:build",{terminated:true,passed:false,notSent:true,artifactId:artifact.id},1);f.queue.pause(f.job.id);f.queue.approveAcceptanceRevision(f.job.id);
  f.store.put("late-execution-results",intent.id,{jobId:f.job.id,snapshot:"tree",kind:"verification",artifactId:artifact.id,ownerEpoch:intent.epoch});
  assert.equal(await f.internal.adoptLateVerification(f.current(),"baseline:build",intent),false);assert.equal(f.current().verification["baseline:build"],undefined);
  const legacy=f.internal.artifacts.pin(f.job.id,"tree",JSON.stringify({jobId:f.job.id,snapshot:"tree",checkId:"build",terminationConfirmed:true,notSent:true,contractDigest:"a".repeat(64),supervisor:{namespaceStopped:true,launcherStopped:true,commandStarted:false}}),"runtime");
  f.store.put("late-execution-results",intent.id,{jobId:f.job.id,snapshot:"tree",kind:"verification",artifactId:legacy.id,ownerEpoch:intent.epoch});assert.equal(await f.internal.adoptLateVerification(f.current(),"baseline:build",intent),false);
});

test("current N+1 not-sent origin can be reconciled without converting a failed result into success",async t=>{
  const f=await prepared(t);f.queue.pause(f.job.id);f.queue.approveAcceptanceRevision(f.job.id);f.queue.resume(f.job.id);
  const intent=f.queue.dispatch(f.job.id,"baseline:build","tree"),binding=f.config.verificationBindings.build;
  const {verificationEnvironment,verificationEnvironmentDigest}=await import("../src/verification/runner.ts"),{verifierSupervisor}=await import("../src/verification/supervisor.ts"),supervisor=verifierSupervisor(binding,f.candidate);
  const result={jobId:f.job.id,snapshot:"tree",checkId:"build",terminationConfirmed:true,notSent:true,status:"failed",reason:"spawn_failed",contractDigest:"a".repeat(64),specVersion:intent.payload.specVersion,policyDigest:intent.payload.policyDigest,
    bindingDigest:digest(binding),environmentDigest:verificationEnvironmentDigest(verificationEnvironment(binding),{executable:supervisor.path,hash:supervisor.hash,engineHash:supervisor.engineHash}),supervisor:{namespaceStopped:true,launcherStopped:true,commandStarted:false}};
  const artifact=f.internal.artifacts.pin(f.job.id,"tree",JSON.stringify(result),"runtime");f.store.put("late-execution-results",intent.id,{jobId:f.job.id,snapshot:"tree",kind:"verification",artifactId:artifact.id,ownerEpoch:intent.epoch});
  assert.equal(await f.internal.adoptLateVerification(f.current(),"baseline:build",intent),true);assert.equal(f.current().verification["baseline:build"].specVersion,2);assert.equal(f.current().verification["baseline:build"].status,"failed");assert.equal(f.store.intent(intent.id).status,"not_sent");
});

test("modern runner missing origin rejects before fake auxiliary dispatch, target mutation cannot change captured origin",async t=>{
  const f=await prepared(t),{runVerification}=await import("../src/verification/runner.ts");Object.assign(f.runtime.installed,{schema_version:2,profile_id:"pi-full"});
  const target={jobId:f.job.id,snapshot:"tree",cwd:f.candidate,contractDigest:"a".repeat(64)};
  await assert.rejects(runVerification("build",f.config.verificationBindings,target),/VERIFICATION_ORIGIN_REQUIRED/);assert.equal(f.counters.checks,0);
  const fixed={...target,inputSnapshotDigest:"a".repeat(64),specVersion:f.queue.job(f.job.id).spec.version,policyDigest:f.queue.job(f.job.id).spec.policyDigest},original=globalThis[portKey];globalThis[portKey]=async(o:any)=>{const result=await original(o);fixed.specVersion=4;return result;};
  const result=await runVerification("build",f.config.verificationBindings,fixed);assert.equal(result.specVersion,1);assert.equal(fixed.specVersion,4);
});


test("in-flight verifier cannot use a changed current version to stamp its old origin passed",async t=>{
  const f=await prepared(t),intent=f.queue.dispatch(f.job.id,"baseline:build","tree"),original=globalThis[portKey];
  globalThis[portKey]=async(o:any)=>{const result=await original(o);if(o.program==="check"){const plan=f.queue.job(f.job.id);plan.spec.version++;f.store.put("jobs",f.job.id,plan);}return result;};
  await f.internal.runStep(f.job.id,"baseline:build",intent,f.current().controlEpoch,new AbortController().signal);
  const result=f.current().verification["baseline:build"];assert.equal(result.specVersion,1);assert.equal(result.status,"passed");assert.equal(result.reason,"verified");assert.notEqual(f.queue.job(f.job.id).steps[0].status,"passed");
});


test("legacy runner absent origin remains nullable and never invents current version",async t=>{
  const f=await prepared(t),{runVerification}=await import("../src/verification/runner.ts");Object.assign(f.runtime.installed,{schema_version:1});
  const result=await runVerification("build",f.config.verificationBindings,{jobId:f.job.id,snapshot:"tree",cwd:f.candidate,contractDigest:"a".repeat(64)});
  assert.equal(result.specVersion,null);assert.equal(result.policyDigest,null);
});
