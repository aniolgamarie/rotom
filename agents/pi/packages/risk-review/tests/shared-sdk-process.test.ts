import test from "node:test";
import assert from "node:assert/strict";
import { prepareSharedReviewModel } from "../src/shared-model.ts";
import { processMessage } from "../src/sdk-process.ts";
function shared(reasoning=true) {
 const route={logical_provider:"synthetic",native_route:"synthetic",model_id:"model",auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url:"https://synthetic.invalid/v1"},configuration_identity="a".repeat(64);
 const prepared=prepareSharedReviewModel({route,configuration_identity,token_limits:{input_tokens:12000,output_tokens:4096},descriptor:{id:"model",provider:"synthetic",api:route.api,name:"Actual Synthetic Flash",baseUrl:route.base_url,reasoning,input:["text","image"],cost:{input:1,output:2,cacheRead:0.1,cacheWrite:0},contextWindow:1000000,maxTokens:384000,compat:{requiresReasoningContentOnAssistantMessages:true,thinkingFormat:"deepseek"},thinkingLevelMap:{low:"low"}}});
 return {prepared,route,configuration_identity};
}
const context=()=>({systemPrompt:"synthetic",messages:[{role:"user",content:"objective",timestamp:1}]});
const opts=()=>({apiKey:"SYNTHETIC_PRIVATE",maxRetries:0,maxTokens:4096,temperature:0,timeoutMs:2000,reasoning:"off"});
const run=(p)=>({schema_version:1,type:"run",seq:1,anchor:"/tmp/synthetic/package.json",model:p.prepared.sdk_model,context:context(),options:opts()});
test("complete shared Model is preserved at the process run boundary",()=>{
 const p=shared(),m=run(p);
 assert.deepEqual(processMessage({...m,sharedModel:p},"parent",p.prepared.model_identity).model,p.prepared.sdk_model);
});
import { EventEmitter } from "node:events";
import { createProcessReviewSdk,processJson,FRAME_LIMITS } from "../src/sdk-process.ts";
import { startSdkProcess } from "../src/sdk-process-entry.ts";
import { createReviewFrameReader,encodeReviewFrame } from "../src/process-frames.ts";
const CODE="PI_RISK_REVIEW_PROCESS_INVALID";
const tick=()=>new Promise(r=>setImmediate(r));
const done=()=>({type:"done",message:{api:"openai-completions",provider:"synthetic",model:"model",stopReason:"stop",content:[{type:"text",text:"candidate"}]}});
function pipe(peer,messages){const p=new EventEmitter(),decoder=createReviewFrameReader(FRAME_LIMITS);p.write=(bytes,callback)=>{messages.push(...decoder.push(bytes).map(processJson));peer.emit("data",bytes);queueMicrotask(()=>callback());return true;};return p;}
function pair(packet=shared(),extra={}) {
 const input=new EventEmitter(),output=new EventEmitter(),sent=[],received=[],settings=[],calls=[];let loads=0,fetches=0,ends=0;
 const parentWrite=pipe(input,sent),childWrite=pipe(output,received),child=new EventEmitter();child.stdio=[null,null,null,parentWrite,output];child.stdout=new EventEmitter();child.stderr=new EventEmitter();let handle;
 const adapter=createProcessReviewSdk({anchor:"/tmp/synthetic/package.json",sharedModel:packet,processFactory:(url,value)=>{settings.push(value);handle=startSdkProcess({input,output:childWrite,sharedModelIdentity:value.argv[1]?.slice("--risk-review-shared-model=".length),createSdk:cfg=>{
  loads++;calls.push(cfg);return {sdk:{normalizeContext:v=>v,streamSimple(model,c,o){calls.push({model,options:o});return(async function*(){const response=await o.fetch("https://synthetic.invalid/v1/chat/completions",{method:"POST",headers:{accept:"application/json"},body:"{}",signal:o.signal});assert.equal(await response.text(),"synthetic");await o.onProviderStreamEvent({model:"model",usage:{prompt_tokens:5,completion_tokens:3,total_tokens:8}});await o.onProviderStreamEvent({model:"model"});yield done();})();}},close:async()=>{}};
 }});return {child,terminate:async()=>{ends++;handle.close();return true;}};},...extra});
 const start=(model=packet.prepared.sdk_model,options={})=>adapter.sdk.streamSimple(model,adapter.sdk.normalizeContext(context()),{...opts(),signal:new AbortController().signal,fetch:async()=>{fetches++;return new Response("synthetic");},onProviderStreamEvent:async m=>calls.push(m),...options});
 return {adapter,start,sent,received,settings,calls,get loads(){return loads;},get fetches(){return fetches;},get ends(){return ends;}};
}
for(const reasoning of [true,false])test(`paired private FD shared ${reasoning} preserves Model and serial raw ACK`,async()=>{
 const p=shared(reasoning),f=pair(p);assert.equal(f.settings.length,0);f.adapter.sdk.normalizeContext(context());assert.equal(f.settings.length,0);
 const iterator=f.start(),event=await iterator.next();assert.equal(event.value.type,"done");await iterator.return();await f.adapter.close();
 assert.deepEqual(f.settings[0].env,{OPENAI_LOG:"off"});assert.deepEqual(f.settings[0].argv,["--risk-review-sdk-process","--risk-review-shared-model="+p.prepared.model_identity]);assert.deepEqual(f.settings[0].stdio,["ignore","pipe","pipe","pipe","pipe"]);
 assert.deepEqual(f.calls[0],{anchor:"/tmp/synthetic/package.json",sharedModel:p});assert.deepEqual(f.calls[1].model,p.prepared.sdk_model);assert.equal(f.calls[1].model.maxTokens,384000);assert.equal(f.calls[1].options.maxTokens,4096);assert.equal(f.calls[1].options.reasoning,"off");
 assert.deepEqual(f.sent.map(m=>m.type),["run","response","raw-ack","raw-ack"]);assert.deepEqual(f.received.map(m=>m.type),["fetch","raw","raw","event"]);assert.equal(f.fetches,1);assert.equal(f.loads,1);assert.equal(f.ends,1);assert.equal(f.adapter.snapshot().process_terminated,true);
 assert.throws(()=>f.start(),e=>e.code===CODE);
});
test("captured packet is independent of caller mutations",async()=>{
 const p=structuredClone(shared()),original=structuredClone(p.prepared.sdk_model),f=pair(p);p.route.base_url="https://changed.invalid";p.prepared.sdk_model.name="changed";
 const iterator=f.start(original);await iterator.next();await iterator.return();assert.equal(f.sent[0].sharedModel.route.base_url,"https://synthetic.invalid/v1");assert.equal(f.sent[0].model.name,"Actual Synthetic Flash");
});
for(const fault of ["model","route","configuration","identity","cap","missing","legacy","malformed-marker","wrong-marker","getter","proxy"])test(`closed run refuses ${fault} without SDK import`,async()=>{
 const p=structuredClone(shared()),m={...run(p),sharedModel:p};let marker=p.prepared.model_identity,calls=0;
 if(fault==="model")m.model.name="changed";
 if(fault==="route")p.route.model_id="other";
 if(fault==="configuration")p.configuration_identity="b".repeat(64);
 if(fault==="identity")p.prepared.model_identity="b".repeat(64);
 if(fault==="cap")m.options.maxTokens=1;
 if(fault==="missing")delete m.sharedModel;
 if(fault==="legacy")marker=undefined;
 if(fault==="malformed-marker")marker="invalid";
 if(fault==="wrong-marker")marker="b".repeat(64);
 if(fault==="getter")Object.defineProperty(p,"prepared",{enumerable:true,get(){calls++;throw Error("synthetic-private");}});
 if(fault==="proxy")m.sharedModel=new Proxy(p,{ownKeys(){calls++;throw Error("synthetic-private");}});
 assert.throws(()=>processMessage(m,"parent",marker),e=>e.code===CODE&&!e.cause);assert.equal(calls,0);
 if(!["getter","proxy","malformed-marker"].includes(fault)){
  const input=new EventEmitter(),peer=new EventEmitter(),sent=[],out=pipe(peer,sent);let imports=0;
  const handle=startSdkProcess({input,output:out,sharedModelIdentity:marker,createSdk:()=>{imports++;assert.fail("unexpected import");}});
  input.emit("data",encodeReviewFrame(JSON.stringify(m),{maxFrameBytes:524288}));await tick();assert.equal(imports,0);assert.equal(sent[0].event.type,"error");handle.close();
 }
});
for(const fault of ["model","cap","reasoning","missing-reasoning","getter","proxy"])test(`invalid stream ${fault} starts zero processes`,async()=>{
 const p=shared(),f=pair(p),model=structuredClone(p.prepared.sdk_model),options={};let calls=0;
 if(fault==="model")model.name="changed";
 if(fault==="cap")options.maxTokens=1;
 if(fault==="reasoning")options.reasoning="high";
 if(fault==="missing-reasoning")options.reasoning=undefined;
 if(fault==="getter")Object.defineProperty(model,"name",{enumerable:true,get(){calls++;return "private";}});
 const actual=fault==="proxy"?new Proxy(model,{ownKeys(){calls++;throw Error("private");}}):model;
 assert.throws(()=>f.start(actual,options),e=>e.code===CODE);assert.equal(calls,0);assert.equal(f.settings.length,0);await f.adapter.close();
});
for(const fault of ["identity","route","configuration","cap","getter","proxy","undefined"])test(`invalid captured packet ${fault} starts zero processes`,()=>{
 let p=structuredClone(shared()),calls=0;
 if(fault==="identity")p.prepared.model_identity="b".repeat(64);
 if(fault==="route")p.route.base_url="https://other.invalid";
 if(fault==="configuration")p.configuration_identity="b".repeat(64);
 if(fault==="cap")p.prepared.request_policy.output_tokens=1;
 if(fault==="getter")Object.defineProperty(p,"prepared",{enumerable:true,get(){calls++;throw Error("private");}});
 if(fault==="proxy")p=new Proxy(p,{ownKeys(){calls++;throw Error("private");}});
 assert.throws(()=>pair(p,fault==="undefined"?{sharedModel:undefined}:{}),e=>e.code===CODE&&!e.message.includes("private"));assert.equal(calls,0);
});
test("malformed child marker is rejected before listeners or imports",()=>{const input=new EventEmitter(),output=new EventEmitter();assert.throws(()=>startSdkProcess({input,output,sharedModelIdentity:"bad"}),e=>e.code===CODE);assert.equal(input.listenerCount("data"),0);});
