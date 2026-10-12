import test from "node:test";
import assert from "node:assert/strict";
import { prepareSharedReviewModel } from "../src/shared-model.ts";
import { compileSharedReviewSdkContract } from "../src/shared-sdk-contract.ts";
import { copySdkModel } from "../src/sdk-worker.ts";
function shared() {
 const route={logical_provider:"synthetic",native_route:"synthetic",model_id:"model",auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url:"https://synthetic.invalid/v1"},configuration_identity="a".repeat(64);
 const prepared=prepareSharedReviewModel({route,configuration_identity,token_limits:{input_tokens:12000,output_tokens:4096},descriptor:{id:"model",provider:"synthetic",api:route.api,name:"Actual Synthetic Flash",baseUrl:route.base_url,reasoning:true,input:["text","image"],cost:{input:1,output:2,cacheRead:0.1,cacheWrite:0},contextWindow:1000000,maxTokens:384000,compat:{requiresReasoningContentOnAssistantMessages:true,thinkingFormat:"deepseek"},thinkingLevelMap:{low:"low",medium:"high",high:"high"}}});
 return {prepared,route,configuration_identity};
}
test("shared copier preserves actual complete model with native caps",()=>{
 const packet=shared(),model=compileSharedReviewSdkContract(packet).sdk_model;
 assert.deepEqual(copySdkModel(model,packet),model);
});
import { EventEmitter } from "node:events";
import { Worker } from "node:worker_threads";
import { mkdtempSync,mkdirSync,writeFileSync,existsSync,rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createIsolatedReviewSdk,copySdkOptions } from "../src/sdk-worker.ts";
import { startSdkWorker } from "../src/sdk-worker-entry.ts";
const CODE="PI_RISK_REVIEW_SDK_INVALID",anchor="/tmp/synthetic-slice/package.json";
const context=()=>({systemPrompt:"synthetic policy",messages:[{role:"user",content:"synthetic objective",timestamp:1}]});
const options=()=>({apiKey:"SYNTHETIC_PRIVATE",maxRetries:0,maxTokens:4096,temperature:0,timeoutMs:2000,reasoning:"off"});
const callbacks=()=>({...options(),signal:new AbortController().signal,fetch:async()=>new Response("synthetic"),onProviderStreamEvent:async()=>{}});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
const done=()=>({type:"done",message:{api:"openai-completions",provider:"synthetic",model:"model",stopReason:"stop",content:[{type:"text",text:"candidate"}]}});
class FakeWorker extends EventEmitter {
 constructor(){super();this.stdout=new EventEmitter();this.stderr=new EventEmitter();this.sent=[];this.ends=0;}
 postMessage(message){this.sent.push(message);}
 terminate(){this.ends++;return Promise.resolve(0);}
}
class Port extends EventEmitter {constructor(){super();this.sent=[];}postMessage(m){this.sent.push(m);}message(m){this.emit("message",{schema_version:1,...m});}}
function parent(packet=shared()) {
 const worker=new FakeWorker(),seen=[];
 const adapter=createIsolatedReviewSdk({anchor,sharedModel:packet,workerFactory:(url,settings)=>{seen.push({url,settings});return worker;}});
 const start=(m=packet.prepared.sdk_model,o=callbacks())=>adapter.sdk.streamSimple(m,adapter.sdk.normalizeContext(context()),o);
 return {worker,adapter,seen,start};
}
test("bound construction/normalization starts zero Workers, fixed private marker and full run",async()=>{
 const packet=shared(),f=parent(packet);f.adapter.sdk.normalizeContext(context());assert.equal(f.seen.length,0);
 const i=f.start(),settings=f.seen[0].settings,run=f.worker.sent[0];
 assert.deepEqual(settings.workerData,{schema_version:1,anchor,shared_model_identity:packet.prepared.model_identity});
 assert.deepEqual(settings.env,{OPENAI_LOG:"off"});assert.deepEqual(settings.argv,[]);assert.deepEqual(settings.execArgv,["--experimental-import-meta-resolve"]);
 assert.deepEqual(run.model,packet.prepared.sdk_model);assert.equal(run.model.maxTokens,384000);assert.equal(run.model.reasoning,true);
 assert.deepEqual(run.model.input,["text","image"]);assert.equal(run.model.name,"Actual Synthetic Flash");
 assert.deepEqual(run.options,options());assert.deepEqual(run.sharedModel,packet);assert.equal(Object.isFrozen(run.sharedModel.prepared.sdk_model.compat),true);
 f.worker.emit("message",{schema_version:1,type:"event",seq:1,event:done()});assert.equal((await i.next()).value.type,"done");await i.return();await f.adapter.close();
 assert.equal(f.adapter.snapshot().worker_terminated,true);assert.equal(f.adapter.snapshot().failure_code,null);
});
test("caller packet mutation after capture cannot change the private binding",async()=>{
 const packet=structuredClone(shared()),model=structuredClone(packet.prepared.sdk_model),f=parent(packet);
 packet.route.base_url="https://changed.invalid";packet.prepared.sdk_model.name="changed";packet.prepared.request_policy.output_tokens=1;
 const i=f.start(model);assert.equal(f.worker.sent[0].model.name,"Actual Synthetic Flash");assert.equal(f.worker.sent[0].sharedModel.route.base_url,"https://synthetic.invalid/v1");await i.return();
});
for(const field of ["name","reasoning","input","maxTokens","contextWindow","cost","compat","thinkingLevelMap","id","baseUrl","provider","api"])test(`actual model drift ${field} refuses before Worker`,async()=>{
 const f=parent(),model=structuredClone(shared().prepared.sdk_model);
 if(field==="input")model.input=["text"];
 else if(field==="cost")model.cost.input++;
 else if(field==="compat")model.compat.supportsStore=true;
 else if(field==="thinkingLevelMap")model.thinkingLevelMap.low="changed";
 else if(typeof model[field]==="number")model[field]--;
 else if(typeof model[field]==="boolean")model[field]=!model[field];else model[field]="changed";
 assert.throws(()=>f.start(model),e=>e.code===CODE);assert.equal(f.seen.length,0);await f.adapter.close();
});
for(const field of ["maxTokens","maxRetries","temperature","reasoning","missing-reasoning","extra"])test(`bound options ${field} refuses before Worker`,async()=>{
 const f=parent(),o=callbacks();
 if(field==="missing-reasoning")delete o.reasoning;
 else if(field==="extra")o.extra=true;
 else if(field==="reasoning")o.reasoning="high";else o[field]=1;
 assert.throws(()=>f.start(undefined,o),e=>e.code===CODE);assert.equal(f.seen.length,0);await f.adapter.close();
});
for(const field of ["identity","configuration","route","cap","native-compat","header","proxy","getter"])test(`invalid packet ${field} is fixed zero Worker without traps`,()=>{
 const packet=structuredClone(shared());let calls=0;
 if(field==="identity")packet.prepared.model_identity="b".repeat(64);
 if(field==="configuration")packet.configuration_identity="b".repeat(64);
 if(field==="route")packet.route.base_url="https://other.invalid";
 if(field==="cap")packet.prepared.request_policy.output_tokens=1;
 if(field==="native-compat")packet.prepared.sdk_model.compat.thinkingFormat="other";
 if(field==="header")packet.prepared.sdk_model.headers={authorization:"SYNTHETIC_PRIVATE"};
 if(field==="proxy")packet.prepared=new Proxy(packet.prepared,{ownKeys(){calls++;throw Error("PRIVATE");}});
 if(field==="getter")Object.defineProperty(packet.prepared,"sdk_model",{enumerable:true,get(){calls++;throw Error("PRIVATE");}});
 assert.throws(()=>parent(packet),e=>e.message===CODE&&e.code===CODE&&!e.cause);assert.equal(calls,0);
});
test("direct options copier requires exact off and cap, legacy remains closed",()=>{
 const packet=shared();assert.deepEqual(copySdkOptions(options(),packet),options());
 assert.throws(()=>copySdkOptions(options()),e=>e.code===CODE);
 assert.throws(()=>copySdkModel(packet.prepared.sdk_model),e=>e.code===CODE);
});
function runPacket(packet=shared()){return {type:"run",seq:1,model:packet.prepared.sdk_model,context:context(),options:options(),sharedModel:packet};}
for(const fault of ["missing-packet","wrong-marker","no-marker","model","options","identity","configuration","route","getter","proxy"])test(`child packet ${fault} refuses before fake SDK import`,async()=>{
 const packet=structuredClone(shared()),port=new Port();let loads=0;
 const data={schema_version:1,anchor,shared_model_identity:packet.prepared.model_identity},m=runPacket(packet);
 if(fault==="missing-packet")delete m.sharedModel;
 if(fault==="wrong-marker")data.shared_model_identity="b".repeat(64);
 if(fault==="no-marker")delete data.shared_model_identity;
 if(fault==="model")m.model={...m.model,name:"changed"};
 if(fault==="options")m.options={...m.options,reasoning:"high"};
 if(fault==="identity")packet.prepared.model_identity="b".repeat(64);
 if(fault==="configuration")packet.configuration_identity="b".repeat(64);
 if(fault==="route")packet.route.model_id="other";
 if(fault==="getter")Object.defineProperty(packet.prepared,"sdk_model",{enumerable:true,get(){assert.fail("getter executed");}});
 if(fault==="proxy")m.sharedModel=new Proxy(packet,{ownKeys(){assert.fail("proxy executed");}});
 const handle=startSdkWorker({port,data,load:async()=>{loads++;assert.fail("SDK import before packet validation");}});
 port.message(m);await flush();assert.equal(loads,0);assert.deepEqual(port.sent.at(-1).event,{type:"error"});handle.close();
});
test("child uses complete model and explicit off without remapping",async()=>{
 const packet=shared(),port=new Port();let loaded=0;
 const handle=startSdkWorker({port,data:{schema_version:1,anchor,shared_model_identity:packet.prepared.model_identity},load:async()=>{
  loaded++;return {normalizeContext:v=>v,streamSimple(model,c,o){assert.deepEqual(model,packet.prepared.sdk_model);assert.equal(o.maxTokens,4096);assert.equal(model.maxTokens,384000);assert.equal(o.reasoning,"off");return (async function*(){yield done();})();}};
 }});
 port.message(runPacket(packet));await flush();assert.equal(loaded,1);assert.equal(port.sent.at(-1).event.type,"done");handle.close();
});
test("bound once/abort remains sticky and no second Worker",async()=>{
 const f=parent(),o=callbacks(),controller=new AbortController();o.signal=controller.signal;const i=f.start(undefined,o),pending=i.next();controller.abort();
 await assert.rejects(pending,e=>e.code===CODE);assert.throws(()=>f.start(),e=>e.code===CODE);await f.adapter.close();assert.equal(f.seen.length,1);assert.equal(f.worker.ends,1);
});
test("real self-owned Worker preserves actual full Model/off policy and stream transfer",async t=>{
 const directory=mkdtempSync(join(tmpdir(),"shared-own-sdk-"));t.after(()=>rmSync(directory,{recursive:true,force:true}));
 const pkg=join(directory,"node_modules/@earendil-works/pi-ai");mkdirSync(pkg,{recursive:true,mode:0o700});
 const localAnchor=join(directory,"package.json"),marker=join(directory,"observed");writeFileSync(localAnchor,'{"type":"module"}');
 writeFileSync(join(pkg,"package.json"),JSON.stringify({type:"module",exports:{"./api/openai-completions":{import:"./provider.mjs"},"./utils/transcript":{import:"./transcript.mjs"}}}));
 const packet=shared();
 writeFileSync(join(pkg,"transcript.mjs"),'export function normalizeContext(v){return v;}');
 writeFileSync(join(pkg,"provider.mjs"),`import assert from 'node:assert/strict';import {writeFileSync} from 'node:fs';
 export async function* streamSimple(model,ctx,o){
 assert.deepEqual(Object.keys(process.env),['OPENAI_LOG']);assert.equal(process.env.OPENAI_LOG,'off');
 assert.deepEqual(model,${JSON.stringify(packet.prepared.sdk_model)});assert.equal(o.reasoning,'off');assert.equal(o.maxTokens,4096);assert.equal(model.maxTokens,384000);
 const response=await o.fetch(model.baseUrl+'/chat/completions',{method:'POST',headers:{authorization:'Bearer '+o.apiKey},body:'{}',signal:o.signal});assert.equal(await response.text(),'own-body');
 writeFileSync(${JSON.stringify(marker)},'observed');yield ${JSON.stringify(done())};}`);
 let sends=0;const adapter=createIsolatedReviewSdk({anchor:localAnchor,sharedModel:packet,workerFactory:(url,settings)=>new Worker(url,settings)});
 try{
  const i=adapter.sdk.streamSimple(packet.prepared.sdk_model,adapter.sdk.normalizeContext(context()),{...callbacks(),fetch:async()=>{sends++;return new Response('own-body');}});
  assert.equal((await i.next()).value.type,'done');assert.equal(sends,1);assert(existsSync(marker));await i.return();
 }finally{await adapter.close();}
 assert.equal(adapter.snapshot().worker_terminated,true);assert.equal(adapter.snapshot().failure_code,null);
});
for(const fault of ["outer-getter","outer-proxy","outer-extra","model-getter","model-proxy","options-getter"])test(`bound external ${fault} executes zero traps/Workers`,async()=>{
 let calls=0,started=0;const trap=()=>{calls++;throw Error("SYNTHETIC_PRIVATE");};
 const packet=shared(),config={anchor,sharedModel:packet,workerFactory:()=>{started++;return new FakeWorker();}};
 if(fault==="outer-getter")Object.defineProperty(config,"sharedModel",{enumerable:true,get:trap});
 if(fault==="outer-extra")config.untrusted=true;
 if(fault.startsWith("outer")){
  assert.throws(()=>createIsolatedReviewSdk(fault==="outer-proxy"?new Proxy(config,{ownKeys:trap}):config),e=>e.code===CODE);
 }else{
  const f=parent(packet);let model=structuredClone(packet.prepared.sdk_model),o=callbacks();
  if(fault==="model-getter")Object.defineProperty(model,"name",{enumerable:true,get:trap});
  if(fault==="model-proxy")model=new Proxy(model,{ownKeys:trap});
  if(fault==="options-getter")Object.defineProperty(o,"reasoning",{enumerable:true,get:trap});
  assert.throws(()=>f.start(model,o),e=>e.code===CODE);assert.equal(f.seen.length,0);await f.adapter.close();
 }
 assert.equal(calls,0);assert.equal(started,0);
});
test("bound already-aborted attempt never creates a Worker and cannot restart",async()=>{
 const f=parent(),o=callbacks(),controller=new AbortController();controller.abort();o.signal=controller.signal;
 assert.throws(()=>f.start(undefined,o),e=>e.code===CODE);assert.equal(f.seen.length,0);assert.throws(()=>f.start(),e=>e.code===CODE);await f.adapter.close();
});
for(const marker of [undefined,null,1,"bad","A".repeat(64)])test(`explicit malformed bound marker ${String(marker)} cannot downgrade`,()=>{
 const port=new Port();assert.throws(()=>startSdkWorker({port,data:{schema_version:1,anchor,shared_model_identity:marker},load:async()=>{assert.fail("load before marker");}}),e=>e.code===CODE);
 assert.equal(port.listenerCount("message"),0);
});
