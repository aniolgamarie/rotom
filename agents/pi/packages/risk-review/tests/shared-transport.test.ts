import test from "node:test";
import assert from "node:assert/strict";
import { prepareSharedReviewModel } from "../src/shared-model.ts";
import { createReviewAttempt } from "../src/transport.ts";
function shared(reasoning=true) {
 const route={logical_provider:"synthetic",native_route:"synthetic",model_id:"model",auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url:"https://synthetic.invalid/v1"},configuration_identity="a".repeat(64);
 const prepared=prepareSharedReviewModel({route,configuration_identity,token_limits:{input_tokens:12000,output_tokens:4096},descriptor:{id:"model",provider:"synthetic",api:route.api,name:"Actual Synthetic Flash",baseUrl:route.base_url,reasoning,input:["text","image"],cost:{input:1,output:2,cacheRead:0.1,cacheWrite:0},contextWindow:1000000,maxTokens:384000,...(reasoning?{compat:{thinkingFormat:"deepseek"},thinkingLevelMap:{low:"low",high:"high"}}:{})}});
 return {prepared,route,configuration_identity};
}
function fixture() {
 const packet=structuredClone(shared());let captured,sends=0,normalizes=0,streams=0,qualifies=0,editBody;
 const cfg={binding:{request_id:"1".repeat(32),operation_digest:"a".repeat(64),context_digest:"b".repeat(64),reviewer_identity:packet.prepared.model_identity},
 route:{identity:packet.prepared.model_identity,pricing_identity:"d".repeat(64),currency:"USD",provider:"synthetic",model:"model",base_url:packet.route.base_url,context_window:1000000,max_output_tokens:4096,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}},
 input:{system_prompt:"policy",user_prompt:"operation"},qualification:{profile:"pi-full",enabled:true,hard_policy_allowed:true,role_allows:true,requires_human:false,automatic_risk_allowed:true},apiKey:"synthetic-private",expectedHeaders:{authorization:"Bearer synthetic-private",accept:"application/json","content-type":"application/json"},deadlineMs:Date.now()+10000,maxDurationMs:2000,isCurrent:()=>true,send:async()=>{sends++;return new Response("synthetic");},
 sharedModel:packet,inputQualification:()=>{qualifies++;return true;},
 sdk:{normalizeContext:v=>{normalizes++;return v;},streamSimple(model,ctx,o){streams++;captured={model,ctx,o};return(async function*(){
 const body={model:model.id,messages:[...(ctx.systemPrompt?[{role:"system",content:ctx.systemPrompt}]:[]),{role:"user",content:ctx.messages[0].content}],stream:true,stream_options:{include_usage:true},temperature:0,max_tokens:o.maxTokens,...(model.reasoning?{thinking:{type:"disabled"}}:{})};
 editBody?.(body);
 const response=await o.fetch(new URL(model.baseUrl.replace(/\/$/,"")+"/chat/completions").href,{method:"POST",body:JSON.stringify(body),headers:cfg.expectedHeaders});await response.text();
 o.onProviderStreamEvent({model:model.id,usage:{prompt_tokens:5,completion_tokens:3,total_tokens:8}});
 yield {type:"done",message:{api:model.api,provider:model.provider,model:model.id,stopReason:"stop",content:[{type:"text",text:JSON.stringify({schema_version:1,...cfg.binding,decision:"allow",reason_code:"authorized-in-scope"})}]}};
 })();}}};
 return {packet,cfg,captured:()=>captured,counts:()=>({sends,normalizes,streams,qualifies}),editBody:fn=>{editBody=fn;}};
}
test("actual shared Model reaches SDK without synthetic reconstruction",async()=>{
 const f=fixture();await createReviewAttempt(f.cfg).run();assert.deepEqual(f.captured().model,f.packet.prepared.sdk_model);
});
const CODE="PI_RISK_REVIEW_TRANSPORT_INVALID";
const zero=f=>assert.deepEqual({...f.counts(),qualifies:0},{sends:0,normalizes:0,streams:0,qualifies:0});
const reject=f=>{assert.throws(()=>createReviewAttempt(f.cfg),e=>e.code===CODE&&e.message===CODE&&!e.cause);zero(f);};
test("bound complete Model/identity and DeepSeek wire gets one allow only",async()=>{
 const f=fixture(),a=createReviewAttempt(f.cfg);assert.equal(f.counts().streams,0);const first=a.run();assert.equal(a.run(),first);
 const result=await first;assert.equal(result.outcome,"valid");assert.equal(result.candidate.decision,"allow");assert.equal(result.candidate.reviewer_identity,f.packet.prepared.model_identity);
 assert.deepEqual(f.counts(),{sends:1,normalizes:1,streams:1,qualifies:1});assert.equal(result.requests,1);assert.equal(result.remote_model_verified,true);assert.equal(result.usage.total_tokens,8);
 assert.equal(f.captured().model.name,"Actual Synthetic Flash");assert.equal(f.captured().model.reasoning,true);assert.equal(f.captured().model.maxTokens,384000);assert.deepEqual(f.captured().model.input,["text","image"]);
 assert.equal(f.captured().o.reasoning,"off");assert.equal(f.captured().o.maxTokens,4096);assert.deepEqual(f.captured().model.cost,f.packet.prepared.sdk_model.cost);assert.notDeepEqual(f.captured().model.cost,f.cfg.route.cost);
 assert.equal(result.product_gate,false);assert.equal(await a.run(),result);
});
for(const withSystem of [true,false])test(`nonreasoning ${withSystem?"with":"without"} system preserves shape`,async()=>{
 const f=fixture(),packet=shared(false);f.packet=packet;f.cfg.sharedModel=packet;f.cfg.route.identity=packet.prepared.model_identity;f.cfg.binding.reviewer_identity=packet.prepared.model_identity;
 if(!withSystem)f.cfg.input.system_prompt="";
 const result=await createReviewAttempt(f.cfg).run();assert.equal(result.outcome,"valid");assert.deepEqual(f.captured().model,packet.prepared.sdk_model);assert.equal(f.captured().o.reasoning,"off");
});
const throwPrivate=()=>{throw Error("SYNTHETIC_PRIVATE_QUALIFIER");};
for(const answer of [undefined,false,null,0,1,"true",{},[],()=>Promise.resolve(true),()=>Promise.reject(Error("synthetic-rejected")),throwPrivate])test(`unqualified input ${typeof answer}/${String(answer).slice(0,20)} has zero SDK`,async()=>{
 const f=fixture();if(answer===undefined)delete f.cfg.inputQualification;else f.cfg.inputQualification=()=>typeof answer==="function"?answer():answer;
 const result=await createReviewAttempt(f.cfg).run();assert.equal(result.outcome,"transport-failure");assert.equal(result.requests,0);assert.equal(result.candidate,null);zero(f);
 assert(result.records.some(r=>r.event==="input-unqualified"));assert.equal(result.usage.status,"not-sent");assert.equal(JSON.stringify(result).includes("SYNTHETIC_PRIVATE_QUALIFIER"),false);
});
test("thenable getter is never read to inspect qualification",async()=>{
 const f=fixture();let touched=0;f.cfg.inputQualification=()=>Object.defineProperty({},"then",{get(){touched++;throw Error("PRIVATE");}});
 const result=await createReviewAttempt(f.cfg).run();assert.equal(result.outcome,"transport-failure");zero(f);assert.equal(touched,0);
});
for(const callback of [null,1,{},async()=>true,new Proxy(()=>true,{apply(){assert.fail("proxy called");}})])test(`illegal qualifier constructor ${typeof callback} rejected`,()=>{
 const f=fixture();f.cfg.inputQualification=callback;reject(f);
});
test("qualifier not accepted in legacy constructor",()=>{const f=fixture();delete f.cfg.sharedModel;reject(f);});
test("qualification receives private independent safe clone without authentication",async()=>{
 const f=fixture();let calls=0;
 f.cfg.inputQualification=value=>{calls++;assert.deepEqual(Object.keys(value).sort(),["model","policy","input","model_identity","configuration_identity"].sort());
 assert.deepEqual(value.model,f.packet.prepared.sdk_model);assert.deepEqual(value.input,f.cfg.input);assert.equal(value.model_identity,f.packet.prepared.model_identity);
 assert.equal(JSON.stringify(value).includes("synthetic-private"),false);value.model.name="mutated";value.input.user_prompt="mutated";value.policy.output_tokens=1;return true;};
 const result=await createReviewAttempt(f.cfg).run();assert.equal(result.outcome,"valid");assert.equal(calls,1);assert.equal(f.captured().model.name,"Actual Synthetic Flash");assert.equal(f.captured().ctx.messages[0].content,"operation");assert.equal(f.captured().o.maxTokens,4096);
});
for(const [key,value,outcome]of [["profile","pi-base","not-called"],["enabled",false,"not-called"],["hard_policy_allowed",false,"policy-blocked"],["role_allows",false,"policy-blocked"],["requires_human",true,"human-required"],["automatic_risk_allowed",false,"human-required"]])test(`policy ${key} is before input qualification`,async()=>{
 const f=fixture();f.cfg.qualification[key]=value;f.cfg.inputQualification=()=>assert.fail("callback before policy gate");const result=await createReviewAttempt(f.cfg).run();assert.equal(result.outcome,outcome);zero(f);
});
for(const change of ["cancel","current","wall","monotonic"])test(`qualifier changing ${change} cannot authorize SDK`,async()=>{
 const f=fixture(),signal=new AbortController();let current=true,wall=1000,mono=0;
 f.cfg.signal=signal.signal;f.cfg.isCurrent=()=>current;f.cfg.deadlineMs=2000;f.cfg.clocks={wall:()=>wall,monotonic:()=>mono};
 f.cfg.inputQualification=()=>{if(change==="cancel")signal.abort();if(change==="current")current=false;if(change==="wall")wall=2000;if(change==="monotonic")mono=2000;return true;};
 const result=await createReviewAttempt(f.cfg).run();assert.equal(result.outcome,change==="cancel"?"canceled":change==="current"?"discarded":"timeout");zero(f);
});
for(const field of ["binding","identity","provider","model","base_url","context_window","max_output_tokens","configuration","packet-identity","sdk-name","off-null","OAuth","extra"])test(`constructor drift ${field} rejected without SDK`,()=>{
 const f=fixture();f.packet=structuredClone(f.packet);f.cfg.sharedModel=f.packet;
 if(field==="binding")f.cfg.binding.reviewer_identity="e".repeat(64);
 else if(field==="configuration")f.packet.configuration_identity="e".repeat(64);
 else if(field==="packet-identity")f.packet.prepared.model_identity="e".repeat(64);
 else if(field==="sdk-name")f.packet.prepared.sdk_model.name="other";
 else if(field==="off-null")f.packet.prepared.base_model.thinkingLevelMap.off=null;
 else if(field==="OAuth")f.packet.route.auth_kind="oauth";
 else if(field==="extra")f.packet.prepared.sdk_model.headers={authorization:"PRIVATE"};
 else f.cfg.route[field]=["identity"].includes(field)?"e".repeat(64):typeof f.cfg.route[field]==="number"?f.cfg.route[field]-1:field==="base_url"?"https://other.invalid":"other";
 reject(f);
});
for(const fault of ["getter","proxy","qualifier-getter","qualifier-proxy"])test(`constructor ${fault} no side effects`,()=>{
 const f=fixture();let calls=0;const trap=()=>{calls++;throw Error("PRIVATE");};
 if(fault==="getter")Object.defineProperty(f.cfg.sharedModel.prepared,"sdk_model",{get:trap,enumerable:true});
 if(fault==="proxy")f.cfg.sharedModel=new Proxy(f.cfg.sharedModel,{ownKeys:trap});
 if(fault==="qualifier-getter")Object.defineProperty(f.cfg,"inputQualification",{get:trap,enumerable:true});
 if(fault==="qualifier-proxy")f.cfg.inputQualification=new Proxy(()=>true,{apply:trap});
 reject(f);assert.equal(calls,0);
});
for(const change of ["no-thinking","thinking-enabled","tools","prompt","max_tokens","reasoning_effort"])test(`DeepSeek body ${change} zero real send`,async()=>{
 const f=fixture();f.editBody(body=>{if(change==="no-thinking")delete body.thinking;else if(change==="thinking-enabled")body.thinking.type="enabled";else if(change==="tools")body.tools=[];else if(change==="prompt")body.messages[1].content="other";else if(change==="max_tokens")body.max_tokens=4097;else body.reasoning_effort="off";});
 const result=await createReviewAttempt(f.cfg).run();assert.equal(result.outcome,"transport-failure");assert.equal(f.counts().sends,0);assert.equal(result.requests,0);assert.equal(result.candidate,null);
});
test("caller mutation after capture leaves shared model/policy/input unchanged",async()=>{
 const f=fixture(),original=structuredClone(f.packet.prepared.sdk_model),a=createReviewAttempt(f.cfg);
 f.packet.prepared.sdk_model.name="mutated";f.packet.route.base_url="https://other.invalid";f.packet.prepared.request_policy.output_tokens=1;f.cfg.input.user_prompt="mutated";
 // fake provider body must use the captured prompt; own fake wire uses callback context, not cfg.input.
 const result=await a.run();assert.equal(result.outcome,"valid");assert.deepEqual(f.captured().model,original);assert.equal(f.captured().ctx.messages[0].content,"operation");assert.equal(f.captured().o.maxTokens,4096);
});
