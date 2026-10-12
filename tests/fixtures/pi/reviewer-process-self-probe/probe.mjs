// 自有fresh child + fake公开SDK探针；仅显式OS入口执行，默认测试不启动。
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { setEnvironmentData } from "node:worker_threads";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { createProcessReviewSdk } from "/probe/src/sdk-process.ts";
import { createReviewAttempt } from "/probe/src/transport.ts";
import { prepareSharedReviewModel } from "/probe/src/shared-model.ts";
setEnvironmentData("synthetic-main-secret", "SYNTHETIC_MAIN_SECRET");
process.env.SYNTHETIC_MAIN_KEY="SYNTHETIC_MAIN_SECRET";
const binding={request_id:"1".repeat(32),operation_digest:"a".repeat(64),context_digest:"b".repeat(64),reviewer_identity:"c".repeat(64)};
const route={identity:binding.reviewer_identity,pricing_identity:"d".repeat(64),currency:"USD",provider:"self-provider",model:"self-model",base_url:"https://self.invalid/v1",context_window:32000,max_output_tokens:1024,cost:{input:1,output:2,cacheRead:1,cacheWrite:1}};
function shared(reasoning){
 const id=reasoning?"shared-deepseek":"shared-text",r={logical_provider:"self-provider",native_route:"self-provider",model_id:id,auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url:"https://self.invalid/v1"},configuration_identity="e".repeat(64);
 const prepared=prepareSharedReviewModel({route:r,configuration_identity,token_limits:{input_tokens:12000,output_tokens:4096},descriptor:{id,provider:"self-provider",api:r.api,name:reasoning?"Actual Synthetic DeepSeek":"Actual Synthetic Text",baseUrl:r.base_url,reasoning,input:["text","image"],cost:{input:1,output:2,cacheRead:0.1,cacheWrite:0},contextWindow:1000000,maxTokens:384000,compat:{requiresReasoningContentOnAssistantMessages:true,thinkingFormat:"deepseek"},thinkingLevelMap:{low:"low",medium:"high",high:"high"}}});
 return {prepared,route:r,configuration_identity};
}
const deadline=setTimeout(()=>process.exit(5),25000);
let started=0,sends=0,closed=0,stdout=0,stderr=0;
function factory(url,settings) {
 started++;assert.equal(url.href,"file:///probe/src/sdk-process-entry.ts");
 assert.deepEqual(settings.env,{OPENAI_LOG:"off"});assert.deepEqual(settings.execArgv,["--experimental-import-meta-resolve"]);assert.deepEqual(settings.stdio,["ignore","pipe","pipe","pipe","pipe"]);
 assert.equal(settings.argv[0],"--risk-review-sdk-process");assert(settings.argv.length===1||settings.argv.length===2&&/^--risk-review-shared-model=[a-f0-9]{64}$/.test(settings.argv[1]));
 const child=spawn(process.execPath,[...settings.execArgv,fileURLToPath(url),...settings.argv],{env:settings.env,stdio:settings.stdio,cwd:"/work"});
 const close=new Promise(resolve=>child.once("close",()=>{closed++;resolve();}));child.stdout.on("data",p=>stdout+=p.byteLength);child.stderr.on("data",p=>stderr+=p.byteLength);
 return {child,terminate:async()=>{if(child.exitCode===null&&child.signalCode===null)child.kill("SIGTERM");await close;return false;}};
}
try {
 const cases=[];
 for(const [name,qualification,expected,variant] of [["allow",{},"valid"],["base",{profile:"pi-base"},"not-called"],["off",{enabled:false},"not-called"],["hard",{hard_policy_allowed:false},"policy-blocked"],["human",{requires_human:true},"human-required"],["shared-deepseek-allow",{},"valid",true],["shared-text-allow",{},"valid",false],["shared-input-unqualified",{},"transport-failure",true]]) {
  const before={started,sends},packet=variant===undefined?undefined:shared(variant),b={...binding,...(packet?{reviewer_identity:packet.prepared.model_identity}:{})},r=packet?{...route,identity:b.reviewer_identity,model:packet.route.model_id,context_window:1000000,max_output_tokens:4096}:route;
  const adapter=createProcessReviewSdk({anchor:"/probe/sdk/package.json",processFactory:factory,...(packet?{sharedModel:packet}:{})});
  try {
   const attempt=createReviewAttempt({binding:b,route:r,input:{system_prompt:"own probe only",user_prompt:JSON.stringify({schema_version:1,...b,decision:"allow",reason_code:"authorized-in-scope"})},qualification:{profile:"pi-full",enabled:true,hard_policy_allowed:true,role_allows:true,requires_human:false,automatic_risk_allowed:true,...qualification},apiKey:"SYNTHETIC_SELECTED_PRIVATE_KEY",expectedHeaders:{authorization:"Bearer SYNTHETIC_SELECTED_PRIVATE_KEY",accept:"application/json","content-type":"application/json"},sdk:adapter.sdk,send:async()=>{sends++;return new Response("own bounded response");},isCurrent:()=>true,deadlineMs:Date.now()+5000,maxDurationMs:3000,...(packet?{sharedModel:packet,...(name==="shared-input-unqualified"?{}:{inputQualification:()=>true})}:{})});
   const result=await attempt.run();assert.equal(result.outcome,expected);
   const called=expected==="valid";assert.equal(result.requests,Number(called));if(called){assert.equal(result.candidate.decision,"allow");assert.equal(result.raw_event_count,2);assert.equal(result.usage.total_tokens,8);}else{assert.equal(started,before.started);assert.equal(sends,before.sends);}
   await adapter.close();
   cases.push({case:name,outcome:result.outcome,requests:result.requests,processes:started-before.started,raw_events:result.raw_event_count,usage:{status:result.usage.status,input_tokens:result.usage.input_tokens,output_tokens:result.usage.output_tokens,total_tokens:result.usage.total_tokens},model_identity:packet?packet.prepared.model_identity:null,scope_termination:"not-independently-observed"});
  } finally {await adapter.close();}
 }
 const observations={};for(const id of ["self-model","shared-deepseek","shared-text"])observations[id]=JSON.parse(readFileSync("/work/sdk-observation-"+id+".json","utf8"));
 assert.equal(started,3);assert.equal(sends,3);assert.equal(closed,3);assert.equal(stdout,0);assert.equal(stderr,0);
 const result={schema_version:1,status:"observed",sdk:"self-owned-fake-only",cases,observations,child_close_observed:true,child_stdout_bytes:stdout,child_stderr_bytes:stderr,real_model_requests:0,product_gate:false};
 writeFileSync("/work/result.json",JSON.stringify(result)+"\n",{flag:"wx",mode:0o600});process.stdout.write(JSON.stringify({schema_version:1,status:"observed",cases:8,product_gate:false})+"\n");
} catch {process.stderr.write("PI_RISK_REVIEW_SELF_PROCESS_PROBE_FAILED\n");process.exitCode=5;} finally {clearTimeout(deadline);}
