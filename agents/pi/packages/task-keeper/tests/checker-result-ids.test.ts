import assert from "node:assert/strict";
import { test } from "node:test";
import { parseConfig, DEFAULT_CONFIG } from "../src/config.ts";
import { evaluateVerification, parseTestResults } from "../src/verification/runner.ts";

const binding={kind:"tests" as const,parser:"json" as const,minimumTests:1,requiredTestIds:["critical"]};
const facts=(value:any,extra:any={})=>({stdout:JSON.stringify(value),truncated:false,timedOut:false,cancelled:false,spawnFailed:false,exitCode:0,
  terminationConfirmed:true,admissionError:null,lingering:0,launcherExitCode:0,started:true,terminalObserved:true,...extra});
const output=(rows:any[])=>({tests:rows.length,passed:rows.filter(r=>r.status==="passed").length,failed:rows.filter(r=>r.status==="failed").length,skipped:rows.filter(r=>r.status==="skipped").length,test_results:rows});

test("required IDs accept each required test passed exactly once with consistent additional IDs",()=>{
  assert.equal(evaluateVerification(binding,facts(output([{id:"critical",status:"passed"},{id:"unconfigured-extra",status:"passed"}]))).status,"passed");
  assert.equal(evaluateVerification({...binding,requiredTestIds:undefined},facts({tests:1,passed:1,failed:0,skipped:0})).status,"passed");
});
for(const [name,rows,aggregate] of [
  ["missing required",[{id:"other",status:"passed"}],null],
  ["duplicate ID",[{id:"critical",status:"passed"},{id:"critical",status:"passed"}],null],
  ["required skipped",[{id:"critical",status:"skipped"},{id:"other",status:"passed"}],null],
  ["required failed",[{id:"critical",status:"failed"},{id:"other",status:"passed"}],null],
  ["invalid status",[{id:"critical",status:"approved"}],{tests:1,passed:1,failed:0,skipped:0}],
  ["wrong ID type",[{id:3,status:"passed"}],null],
  ["unknown row field",[{id:"critical",status:"passed",approved:true}],null],
  ["false aggregate",[{id:"critical",status:"skipped"}],{tests:1,passed:1,failed:0,skipped:0}],
  ["row count mismatch",[{id:"critical",status:"passed"}],{tests:2,passed:2,failed:0,skipped:0}],
] as const)test(`required-ID contract rejects ${name}`,()=>{
  const value=aggregate?{...aggregate,test_results:rows}:output([...rows]);assert.notEqual(evaluateVerification(binding,facts(value)).status,"passed");
});

test("real zero/all-skipped/nonzero facts stay failed rather than hidden by invalid ID output",()=>{
  for(const value of [{tests:0,passed:0,failed:0,skipped:0},{tests:2,passed:0,failed:0,skipped:2}])assert.equal(evaluateVerification(binding,facts(value)).status,"failed");
  assert.equal(evaluateVerification(binding,facts({bad:true},{exitCode:1})).status,"failed");
  assert.equal(evaluateVerification(binding,facts(output([{id:"critical",status:"passed"}]),{truncated:true})).status,"unknown");
});

test("per-ID parser has a bounded closed-row contract",()=>{
  assert.equal(parseTestResults(JSON.stringify(output(Array.from({length:4097},(_,i)=>({id:"id"+i,status:"passed"})))),{tests:4097,passed:4097,failed:0,skipped:0}),null);
  assert.equal(parseTestResults(JSON.stringify({tests:1,passed:1,failed:0,skipped:0,test_results:{critical:"passed"}}),{tests:1,passed:1,failed:0,skipped:0}),null);
});

test("schema7 optional IDs are tests/json only, bounded unique safe IDs and absent defaults remain compatible",()=>{
  const config=structuredClone(DEFAULT_CONFIG);config.verificationBindings.test={executable:"/own/check",args:[],environment:{},timeoutMs:1000,kind:"tests",parser:"json",minimumTests:1,requiredTestIds:["critical"]};
  assert.deepEqual(parseConfig(config).verificationBindings.test.requiredTestIds,["critical"]);
  for(const value of [[],null,["same","same"],["bad id"],[3],Array.from({length:4097},(_,i)=>"id"+i)]){
    const invalid=structuredClone(config) as any;invalid.verificationBindings.test.requiredTestIds=value;assert.throws(()=>parseConfig(invalid));
  }
  for(const patch of [{kind:"build"},{parser:"pytest"},{parser:"exit-code"}]){const invalid=structuredClone(config) as any;Object.assign(invalid.verificationBindings.test,patch);assert.throws(()=>parseConfig(invalid));}
  delete config.verificationBindings.test.requiredTestIds;assert.equal(Object.hasOwn(parseConfig(config).verificationBindings.test,"requiredTestIds"),false);
});


for(const [name,text] of [
  ["duplicate status",String.raw`{"tests":1,"passed":1,"failed":0,"skipped":0,"test_results":[{"id":"critical","status":"failed","status":"passed"}]}`],
  ["duplicate id",String.raw`{"tests":1,"passed":1,"failed":0,"skipped":0,"test_results":[{"id":"other","id":"critical","status":"passed"}]}`],
  ["escaped duplicate status",String.raw`{"tests":1,"passed":1,"failed":0,"skipped":0,"test_results":[{"id":"critical","status":"failed","sta\u0074us":"passed"}]}`],
  ["escaped duplicate id",String.raw`{"tests":1,"passed":1,"failed":0,"skipped":0,"test_results":[{"id":"other","\u0069d":"critical","status":"passed"}]}`],
  ["top-level count overwrite",String.raw`{"tests":0,"tests":1,"passed":1,"failed":0,"skipped":0,"test_results":[{"id":"critical","status":"passed"}]}`],
  ["escaped top count overwrite",String.raw`{"tests":1,"passed":0,"pa\u0073sed":1,"failed":0,"skipped":0,"test_results":[{"id":"critical","status":"passed"}]}`],
  ["nonfinite count",String.raw`{"tests":1e400,"passed":1,"failed":0,"skipped":0,"test_results":[{"id":"critical","status":"passed"}]}`],
] as const)test(`encoded JSON cannot overwrite ${name} into passed required-ID evidence`,()=>{
  assert.notEqual(evaluateVerification(binding,{...facts({}),stdout:text}).status,"passed");
});


test("strict structured JSON cap rejects oversized legacy and ID results but preserves capture and failed facts",()=>{
  const text=JSON.stringify({...output([{id:"critical",status:"passed"}]),padding:"x".repeat(1024*1024)});
  for(const declared of [binding,{...binding,requiredTestIds:undefined}])assert.equal(evaluateVerification(declared,{...facts({}),stdout:text}).status,"unknown");
  assert.equal(evaluateVerification(binding,{...facts({}),stdout:text,exitCode:1}).status,"failed");
  for(const declared of [binding,{...binding,requiredTestIds:undefined},{kind:"build" as const,parser:"json" as const,minimumTests:1}]){
    assert.notEqual(evaluateVerification(declared,{...facts({}),stdout:String.raw`{"tests":1,"passed":1,"failed":0,"skipped":0,"ignored":1e400,"test_results":[{"id":"critical","status":"passed"}]}`}).status,"passed");
  }
});
