import { test } from "node:test";
import assert from "node:assert/strict";
import { readEvidenceView } from "../src/evidence/producer.ts";
import { reduceEvidence, summarizeEvidence } from "../src/evidence/records.ts";
const sha="a".repeat(64);
function fixture(){
  const origin={profileId:"pi-full",runtimeIdentity:sha,configDigest:sha,platform:"linux",architecture:"x64",
    snapshot:"snapshot",inputSnapshotDigest:sha,specVersion:1,policyDigest:sha,bindingDigest:sha,
    environmentDigest:sha,contractDigest:sha,cwdIdentity:sha,entryIdentity:sha,argvDigest:sha};
  const record={schemaVersion:1,jobId:"job",attemptId:"attempt",checkId:"check",layer:"checker",origin,
    execution:{startedAt:null,endedAt:null,protocolStatus:"not_sent",exitCode:null,counts:null,
      terminalObserved:false,termination:"confirmed",processIdentity:null,notSent:true,unknowns:[]},
    result:{status:"not_run",reason:"not_sent"},artifact:null};
  const current:any={jobId:"job",attemptId:"attempt",checkId:"check",origin,requiredLayer:"checker",oraclePassed:false};
  const pointer:any={stepId:"check",attemptId:"attempt",checkId:"check",layer:"checker",recordRef:"record",
    snapshot:"snapshot",rawArtifactId:"raw",observedAt:1};
  return {record,current,pointer};
}
test("parsed not-sent facts remain invalid after pointer read/scope failure, while standalone no-artifact not-sent is legal",()=>{
  const {record,current,pointer}=fixture();
  assert.equal(reduceEvidence(record,current,null).validity,"current");
  for(const fault of ["null-scope","missing","foreign","scope"]){
    let oracleCalls=0;
    const artifacts:any={read(id:string){
      if(id!=="record")throw Error(fault);
      return {artifact:{source:"runtime"},content:Buffer.from(JSON.stringify(fault==="null-scope"?record:{...record,artifact:{id:"raw",source:"verifier",digest:sha,bytes:1}}))};
    }};
    const view=readEvidenceView(artifacts,{...pointer,...(fault==="scope"?{attemptId:"other"}:{})},"job",current,()=>{oracleCalls++;return true;});
    assert.equal(view.validity,"invalid",fault);assert.equal(view.result,"not_run");
    assert.equal(view.record?.result.reason,"not_sent");assert.equal(view.supportsPassed,false);
    assert.equal(summarizeEvidence([view]).total,1);assert.equal(oracleCalls,0);
  }
});
test("artifact failures preserve parsed failed counts; unparsable record remains invalid without invented facts",()=>{
  const {record,current,pointer}=fixture();
  const failed={...record,execution:{...record.execution,notSent:false,protocolStatus:"failed",startedAt:1,endedAt:2,
    exitCode:1,counts:{tests:2,passed:1,failed:1,skipped:0},terminalObserved:true,processIdentity:sha},
    result:{status:"failed",reason:"nonzero_exit"},artifact:{id:"raw",source:"verifier",digest:sha,bytes:1}};
  for(const fault of ["missing","foreign","scope","parse"]){
    const artifacts:any={read(id:string){if(id!=="record")throw Error(fault);
      return {artifact:{source:"runtime"},content:Buffer.from(fault==="parse"?"{":JSON.stringify(failed))};}};
    const view=readEvidenceView(artifacts,{...pointer,...(fault==="scope"?{checkId:"other"}:{})},"job",current,()=>true);
    assert.equal(view.validity,"invalid");assert.equal(view.supportsPassed,false);
    assert.equal(summarizeEvidence([view]).total,1);
    if(fault!=="parse"){assert.equal(view.result,"failed");assert.deepEqual(view.counts,failed.execution.counts);}
    else {assert.equal(view.record,null);assert.equal(view.counts,null);}
  }
});
