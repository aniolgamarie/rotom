import { test, assert, matrixCase } from "./recorded-test.ts";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { TaskService } from "../src/orchestration/service.ts";
import { SubagentsAdapter, type DelegationResult } from "../src/adapters/subagents.ts";
import type { Intent } from "../src/store/database.ts";
import { verificationInputs } from "../src/verification/inputs.ts";
import { barrier } from "./helpers.ts";
import { completedState } from "./fixtures/service-state.ts";

for (const order of ["revoke-first", "await-first"] as const)
test(`[S REC-019] native result and owner replacement ${order} preserve the accepted action without further dispatch`, { timeout: 15000 }, async t => matrixCase("await-orders", `R06.owner-loss.${order}`, async () => {
  // Enter a declared dispatch-ready state. Real worktree/verifier startup belongs to P/E tests.
  const f = completedState(t), first = f.service, store = f.store;
  const internal = first as unknown as { pi: ExtensionAPI; context: ExtensionContext; bindingDigests(routes: string[]): Record<string,string|null>;
    capture(): Promise<unknown>; runStep(jobId:string,stepId:string,intent:Intent,epoch:number,signal:AbortSignal):Promise<void> };
  t.mock.method(internal.context.modelRegistry, "find", () => ({api:"openai-completions",provider:"fixture-provider",id:"fixture-model",baseUrl:"http://fixture.invalid",reasoning:false,contextWindow:32000,maxTokens:1000}));
  internal.capture = async () => ({snapshot:{id:"tree",files:[]},patch:""});
  const job = first.get(f.jobId), plan = f.queue.job(f.jobId);
  for (const step of plan.steps) {step.status="pending";step.intentId=null;step.readyAt=null;step.finishedAt=null;}
  job.checks=[];job.checkInputsDigest=verificationInputs(f.config.verificationBindings,job.cwd!).digest;
  job.modelBindings=internal.bindingDigests(["primary"]);store.put("managed-jobs",job.id,job);store.put("jobs",job.id,plan);
  const started=barrier(), completed=barrier<DelegationResult>(), trace:string[]=[];let dispatches=0,second:TaskService|undefined;
  t.mock.method(SubagentsAdapter.prototype,"execute",async(...args:Parameters<SubagentsAdapter["execute"]>)=>{args[3]?.();dispatches++;trace.push("dispatched");started.resolve();return completed.promise;});
  const native:DelegationResult={descriptorId:"late-child",nativeRunId:"late-native",status:"ended",terminationConfirmed:true,content:"late factual result",error:null,observations:[]};
  const intent=f.queue.dispatch(job.id,"implement","tree"), pending=internal.runStep(job.id,"implement",intent,job.controlEpoch,new AbortController().signal);
  try {
    await Promise.race([started.promise,pending.then(()=>{throw new Error(`Step ended before adapter dispatch: ${first.get(job.id).reason}`);})]);
    const finish=async()=>{trace.push("native-return");completed.resolve(native);await pending;};
    if(order==="await-first")await finish();
    const old=store.owner(job.workScope)!;trace.push("owner-revoked");store.revokeOwner(old);
    second=new TaskService(internal.pi,store,f.config,internal.context);(second as unknown as {wake():void}).wake=()=>{};
    const replacement=store.owner(job.workScope)!;assert.ok(replacement.epoch>old.epoch);
    const currentJob=structuredClone(second.get(job.id)),currentPlan=structuredClone(store.get("jobs",job.id));
    if(order==="revoke-first")await finish();
    assert.equal(trace.indexOf("native-return")<trace.indexOf("owner-revoked"),order==="await-first");
    assert.equal(dispatches,1);assert.deepEqual(second.get(job.id),currentJob);assert.deepEqual(store.get("jobs",job.id),currentPlan);
    assert.equal(store.owner(job.workScope)!.token,replacement.token);
    const late=store.list<{jobId:string;snapshot:string;kind:string;artifactId:string;ownerEpoch:number}>("late-execution-results");
    if(order==="await-first"){
      assert.equal(late.length,0);assert.ok(second.get(job.id).outputs.implement);
      assert.equal(f.queue.job(job.id).steps.find(step=>step.id==="implement")!.status,"passed");
      assert.equal(store.intent(intent.id)!.status,"settled");assert.equal(store.claims().some(claim=>claim.intent_id===intent.id),false);
    }else{
      assert.equal(late.length,1);assert.equal(late[0].value.kind,"delegation");assert.equal(late[0].value.ownerEpoch,old.epoch);
      const retained=JSON.parse(f.artifacts.read(late[0].value.artifactId,job.id,late[0].value.snapshot).content.toString());
      assert.equal(retained.nativeRunId,"late-native");assert.equal(retained.content,"late factual result");
      assert.equal(second.describe(job.id).lateExecutionResults[0].artifactId,late[0].value.artifactId);
      assert.equal(store.intent(intent.id)!.status,"acked");assert.equal(store.intent(intent.id)!.nativeId,"late-native");assert.ok(store.claims().some(claim=>claim.intent_id===intent.id));
    }
    assert.equal(second.get(job.id).receipt,null);await first.dispose();
    assert.deepEqual(second.get(job.id),currentJob);assert.deepEqual(store.get("jobs",job.id),currentPlan);
  }finally{completed.resolve(native);await pending;await second?.dispose();}
}));
