import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../../packages/task-keeper/src/store/database.ts";
import { TaskKeeperDelegateAdapter } from "../official-task-keeper-delegate.ts";

function fixture(t:any,fault:string|null=null){
  const root=mkdtempSync(join(tmpdir(),"evidence-dto-")),store=new Store(root),owner=store.claimOwner("scope","token");
  t.after(()=>store.close());
  store.put("managed-jobs","job",{id:"job",workScope:"scope",cwd:root,sourceCwd:root,controlEpoch:1,cancelRequested:false});
  store.put("jobs","job",{spec:{workScope:"scope"},steps:[{id:"inspect",kind:"read",status:"running",intentId:"intent"}]});
  const proof:any={schema_version:1,physical_run_id:"physical",attempt_id:"attempt",lease_id:"lease",grant_generation:2,
    process_identity_digest:"a".repeat(64),termination_evidence_digest:"b".repeat(64),terminated:true,resources_reclaimed:true,exit_code:0};
  if(fault==="run")proof.physical_run_id="foreign";if(fault==="attempt")proof.attempt_id="foreign";if(fault==="lease")proof.lease_id="foreign";
  if(fault==="generation")proof.grant_generation=0;if(fault==="selfapproved")proof.approved=true;if(fault==="unknown")proof.terminated=false;
  let getters=0;if(fault==="getter")Object.defineProperty(proof,"headers",{enumerable:true,get(){getters++;return "never-read";}});
  const result={run_id:"logical",status:"completed",active_attempt_id:"attempt",budget:{deadline_ms:Date.now()+5000},
    actions:[{attempt_id:"attempt",physical_run_id:"physical",lease_id:"lease",receipt_ref:"physical",termination_verified:true,task_succeeded:true,execution_evidence:proof}]};
  const adapter=new TaskKeeperDelegateAdapter({store,owner,config:{roles:{scout:{route:"route"}},routes:{route:{provider:"p",model:"m"}}},
    manifest:{profile_id:"pi-full",options:{task_keeper:{enabled:true},model_delegate:{max_run_seconds:2}},permission_policy:{},
      model_bindings:{task_keeper_reader:{provider:"p",model:"m"}}},supervisor:{async call(method:any){return method==="delegate_artifact_v3"?{content:"observed",offset:0,next_offset:null,total_bytes:8}:result;}},
    issuer:{async open(){return "own-source";},async retire(){}},policySnapshot(){},runtimeContract(){return {};}});
  return {adapter,input:{jobId:"job",stepId:"inspect",parentIntentId:"intent",role:"scout",task:"readonly",cwd:root},getters:()=>getters};
}
test("production-shaped readonly proof is matched and actual fresh invocation window is retained; cached observe gets no invented origin/window",async t=>{
  const f=fixture(t),first=await f.adapter.execute(f.input);assert.equal(first.evidence?.lease_id,"lease");
  assert.equal(first.evidence?.grant_generation,2);assert.ok(first.invocationWindow.endedAt>=first.invocationWindow.startedAt);
  const again=await f.adapter.execute(f.input);assert.equal(again.invocationWindow,null);assert.equal(again.evidenceOrigin,null);
});
for(const fault of ["run","attempt","lease","generation","selfapproved","unknown","getter"])test("unmatched "+fault+" DTO cannot provide physical acceptance proof",async t=>{
  const f=fixture(t,fault),value=await f.adapter.execute(f.input);assert.equal(value.evidence,null);assert.equal(f.getters(),0);
  // 原task/terminal事实不因proof失效改成虚假成功或删除。
  assert.equal(value.status,"ended");
});
