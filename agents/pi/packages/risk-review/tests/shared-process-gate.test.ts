// 仅自有pipe/假SDK组合；无spawn、Worker、官方SDK或真实发送。
import assert from "node:assert/strict";
import { test as nodeTest } from "node:test";
import { EventEmitter } from "node:events";
import { PassThrough } from "node:stream";
import { prepareSharedReviewModel } from "../src/shared-model.ts";
import { createProcessReviewSdk, FRAME_LIMITS, processJson } from "../src/sdk-process.ts";
import { startSdkProcess } from "../src/sdk-process-entry.ts";
import { createReviewAttempt } from "../src/transport.ts";
import { createReviewFrameReader, encodeReviewFrame } from "../src/process-frames.ts";

const test=(name,fn)=>nodeTest(name,{timeout:3000},fn);
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
function packet(reasoning=true){
  const route={logical_provider:"synthetic",native_route:"synthetic",model_id:"model",auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url:"https://synthetic.invalid/v1"};
  const configuration_identity="a".repeat(64);
  const prepared=prepareSharedReviewModel({route,configuration_identity,token_limits:{input_tokens:12000,output_tokens:4096},
    descriptor:{id:"model",provider:"synthetic",api:route.api,name:"Actual Synthetic Flash",baseUrl:route.base_url,reasoning,input:["text","image"],
      cost:{input:1,output:2,cacheRead:0.1,cacheWrite:0},contextWindow:1000000,maxTokens:384000,
      ...(reasoning?{compat:{thinkingFormat:"deepseek",requiresReasoningContentOnAssistantMessages:true},thinkingLevelMap:{low:"low",high:"high"}}:{})}});
  return{prepared,route,configuration_identity};
}
function fixture({reasoning=true,gate,mode="normal",qualification={},inputQualified=true,omitInputQualification=false,sendFails=false}={}){
  const shared=packet(reasoning),abort=new AbortController(),p2c=new PassThrough(),c2p=new PassThrough();
  const child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdio=[null,null,null,p2c,c2p];
  const parentFrames=[],childFrames=[],models=[],options=[],settings=[],bodies=[];
  for(const[pipe,frames]of[[p2c,parentFrames],[c2p,childFrames]]){const decoder=createReviewFrameReader(FRAME_LIMITS);pipe.on("data",chunk=>frames.push(...decoder.push(chunk).map(processJson)));}
  let starts=0,imports=0,sends=0,gates=0,terminations=0,current=true,entry;
  const binding={request_id:"1".repeat(32),operation_digest:"b".repeat(64),context_digest:"c".repeat(64),reviewer_identity:shared.prepared.model_identity};
  const adapter=createProcessReviewSdk({anchor:"/own/slice/package.json",sharedModel:shared,processFactory(url,config){
    starts++;settings.push(config);
    entry=startSdkProcess({input:p2c,output:c2p,sharedModelIdentity:config.argv[1].slice("--risk-review-shared-model=".length),createSdk(){
      imports++;return{sdk:{normalizeContext:value=>value,async *streamSimple(model,context,opts){
        models.push(model);options.push({maxTokens:opts.maxTokens,reasoning:opts.reasoning,maxRetries:opts.maxRetries,temperature:opts.temperature});
        const body={model:model.id,messages:[{role:"system",content:context.systemPrompt},{role:"user",content:context.messages[0].content}],stream:true,stream_options:{include_usage:true},temperature:0,max_tokens:opts.maxTokens,...(model.reasoning?{thinking:{type:"disabled"}}:{})};
        if(mode==="wire-invalid")body.max_tokens=4097;
        const init={method:"POST",headers:{authorization:"Bearer "+opts.apiKey,accept:"application/json","content-type":"application/json"},body:JSON.stringify(body),signal:opts.signal};
        const response=await opts.fetch(model.baseUrl+"/chat/completions",init);assert.equal(await response.text(),"synthetic-response");
        if(mode==="second-sdk-fetch")await opts.fetch(model.baseUrl+"/chat/completions",init);
        if(mode==="second-child-frame")c2p.write(encodeReviewFrame(JSON.stringify({schema_version:1,type:"fetch",seq:1,url:model.baseUrl+"/chat/completions",init:{method:init.method,headers:init.headers,body:init.body},aborted:false}),{maxFrameBytes:524288}));
        await opts.onProviderStreamEvent({model:model.id,usage:{prompt_tokens:5,completion_tokens:3,total_tokens:8}});
        yield{type:"done",message:{api:model.api,provider:model.provider,model:model.id,stopReason:"stop",content:[{type:"text",text:JSON.stringify({schema_version:1,...binding,decision:"allow",reason_code:"authorized-in-scope"})}]}};
      }},close:async()=>{}};
    }});
    return{child,terminate:async()=>{terminations++;entry.close();return true;}};
  }});
  const cfg={binding,route:{identity:binding.reviewer_identity,pricing_identity:"d".repeat(64),currency:"USD",provider:"synthetic",model:"model",base_url:shared.route.base_url,context_window:1000000,max_output_tokens:4096,cost:{input:0,output:0,cacheRead:0,cacheWrite:0}},
    input:{system_prompt:"policy",user_prompt:"operation"},qualification:{profile:"pi-full",enabled:true,hard_policy_allowed:true,role_allows:true,requires_human:false,automatic_risk_allowed:true,...qualification},
    apiKey:"SYNTHETIC_PRIVATE_KEY",expectedHeaders:{authorization:"Bearer SYNTHETIC_PRIVATE_KEY",accept:"application/json","content-type":"application/json"},
    sharedModel:shared,sdk:adapter.sdk,isCurrent:()=>current,signal:abort.signal,deadlineMs:Date.now()+10000,maxDurationMs:1000,
    beforeSend:(...args)=>{gates++;assert.deepEqual(args,[]);return gate?gate({abort,invalidate:()=>{current=false;}}):true;},
    send:(url,init)=>{sends++;const body=JSON.parse(init.body);bodies.push({model:body.model,max_tokens:body.max_tokens,thinking:body.thinking??null});if(sendFails)throw Error("SYNTHETIC_PRIVATE_SEND_FAILURE");return new Response("synthetic-response");}};
  if(!omitInputQualification)cfg.inputQualification=()=>inputQualified;
  const attempt=createReviewAttempt(cfg);
  return{shared,adapter,attempt,abort,parentFrames,childFrames,models,options,settings,bodies,
    counts:()=>({starts,imports,sends,gates,terminations}),async close(){await adapter.close();for(const pipe of[p2c,c2p,child.stdout,child.stderr])pipe.destroy();}};
}
const unknown=result=>assert.deepEqual({status:result.usage.status,input:result.usage.input_tokens,output:result.usage.output_tokens,total:result.usage.total_tokens},{status:"unknown",input:null,output:null,total:null});
function zero(f,result){assert.equal(result.requests,0);assert.equal(result.candidate,null);assert.deepEqual(f.counts(),{starts:0,imports:0,sends:0,gates:0,terminations:0});assert.equal(f.adapter.snapshot().fetch_requests,0);}

for(const reasoning of[true,false])test(`shared ${reasoning?"DeepSeek":"text"} private process + parent gate preserves full Model`,async()=>{
  const f=fixture({reasoning});try{
    const result=await f.attempt.run();await f.adapter.close();
    assert.equal(result.outcome,"valid");assert.equal(result.candidate.decision,"allow");assert.equal(result.requests,1);assert.equal(result.usage.total_tokens,8);
    assert.deepEqual(f.counts(),{starts:1,imports:1,sends:1,gates:1,terminations:1});assert.equal(f.adapter.snapshot().fetch_requests,1);
    assert.deepEqual(f.models[0],f.shared.prepared.sdk_model);assert.equal(f.models[0].name,"Actual Synthetic Flash");assert.equal(f.models[0].maxTokens,384000);assert.equal(f.models[0].contextWindow,1000000);assert.equal(f.models[0].reasoning,reasoning);assert.deepEqual(f.models[0].input,["text","image"]);
    assert.deepEqual(f.options[0],{maxTokens:4096,reasoning:"off",maxRetries:0,temperature:0});
    assert.deepEqual(f.bodies,[{model:"model",max_tokens:4096,thinking:reasoning?{type:"disabled"}:null}]);
    assert.equal(result.wire.gate_attempted,true);assert.equal(result.wire.gate_acknowledged,true);
    assert.deepEqual(f.settings[0].env,{OPENAI_LOG:"off"});assert.deepEqual(f.settings[0].argv,["--risk-review-sdk-process","--risk-review-shared-model="+f.shared.prepared.model_identity]);
    const run=f.parentFrames.find(frame=>frame.type==="run");assert.deepEqual(Object.keys(run).sort(),["schema_version","type","seq","anchor","model","context","options","sharedModel"].sort());
    assert.deepEqual(Object.keys(run.options).sort(),["apiKey","maxRetries","maxTokens","temperature","timeoutMs","reasoning"].sort());
    for(const key of["beforeSend","gate","ticket","source","permit"])assert.equal(Object.hasOwn(run,key)||Object.hasOwn(run.options,key),false);
    assert.deepEqual(f.parentFrames.map(frame=>frame.type),["run","response","raw-ack"]);
    assert.equal(f.adapter.snapshot().process_terminated,true);assert.equal(result.product_gate,false);
    assert.equal(JSON.stringify(result).includes("SYNTHETIC_PRIVATE"),false);
  }finally{await f.close();}
});
for(const failure of["false","throw","reject"])test(`child fetch1 but failed parent gate ${failure} has platform0 and unknown usage`,async()=>{
  const f=fixture({gate:()=>{if(failure==="throw")throw Error("SYNTHETIC_PRIVATE_GATE");return failure==="reject"?Promise.reject(Error("SYNTHETIC_PRIVATE_GATE")):false;}});
  try{const result=await f.attempt.run();assert.equal(result.outcome,"transport-failure");assert.equal(result.requests,0);assert.equal(result.candidate,null);unknown(result);
    assert.equal(f.adapter.snapshot().fetch_requests,1);assert.equal(f.counts().gates,1);assert.equal(f.counts().sends,0);assert.equal(result.wire.gate_attempted,true);assert.equal(result.wire.gate_acknowledged,false);
    assert.equal(JSON.stringify(result).includes("SYNTHETIC_PRIVATE"),false);
  }finally{await f.close();}
});
for(const late of["resolve","reject"])test(`cancel wakes never-finished gate and late ${late} cannot send`,async()=>{
  const entered=deferred(),pending=deferred(),f=fixture({gate:()=>{entered.resolve();return pending.promise;}});
  try{const running=f.attempt.run();await entered.promise;f.abort.abort();const result=await running;
    assert.equal(result.outcome,"canceled");unknown(result);assert.equal(f.adapter.snapshot().fetch_requests,1);assert.equal(result.requests,0);assert.equal(f.counts().sends,0);
    if(late==="resolve")pending.resolve(true);else pending.reject(Error("SYNTHETIC_PRIVATE_LATE"));await tick();
    assert.equal(f.attempt.snapshot().wire.gate_acknowledged,late==="resolve");assert.equal(f.counts().sends,0);assert.equal(f.counts().gates,1);
  }finally{await f.close();}
});
for(const change of["cancel","current"])test(`gate ack then ${change} keeps acknowledged but platform0`,async()=>{
  const f=fixture({gate:control=>{if(change==="cancel")control.abort.abort();else control.invalidate();return true;}});
  try{const result=await f.attempt.run();assert.equal(result.outcome,change==="cancel"?"canceled":"discarded");assert.equal(result.wire.gate_acknowledged,true);assert.equal(result.requests,0);unknown(result);assert.equal(f.counts().gates,1);assert.equal(f.counts().sends,0);assert.equal(f.adapter.snapshot().fetch_requests,1);
  }finally{await f.close();}
});
test("platform synchronous throw retains one platform entry after one child frame and ack",async()=>{
  const f=fixture({sendFails:true});try{const result=await f.attempt.run();assert.equal(result.outcome,"transport-failure");assert.equal(result.requests,1);assert.equal(result.candidate,null);unknown(result);assert.equal(f.counts().sends,1);assert.equal(f.counts().gates,1);assert.equal(f.adapter.snapshot().fetch_requests,1);assert.equal(result.wire.gate_acknowledged,true);}finally{await f.close();}
});
test("invalid final shared wire has child frame1 but zero parent gate/send",async()=>{
  const f=fixture({mode:"wire-invalid"});try{const result=await f.attempt.run();assert.equal(result.outcome,"transport-failure");assert.equal(result.requests,0);assert.equal(f.adapter.snapshot().fetch_requests,1);assert.equal(f.counts().gates,0);assert.equal(f.counts().sends,0);assert.equal(result.wire.gate_attempted,false);assert.equal(result.usage.status,"not-sent");}finally{await f.close();}
});
for(const value of[false,undefined])test(`missing/unqualified input ${value} has zero process/gate/send`,async()=>{
  const f=fixture({inputQualified:value,omitInputQualification:value===undefined});try{zero(f,await f.attempt.run());}finally{await f.close();}
});
for(const qualification of[{profile:"pi-base"},{enabled:false},{hard_policy_allowed:false},{requires_human:true},{role_allows:false},{automatic_risk_allowed:false}])test(`outer policy ${Object.keys(qualification)[0]} is before process/gate`,async()=>{
  const f=fixture({qualification});try{zero(f,await f.attempt.run());}finally{await f.close();}
});
for(const mode of["second-sdk-fetch","second-child-frame"])test(`${mode} cannot obtain second parent gate or platform entry`,async()=>{
  const f=fixture({mode});try{const result=await f.attempt.run();assert.equal(result.outcome,"transport-failure");assert.equal(result.candidate,null);assert.equal(f.counts().gates,1);assert.equal(f.counts().sends,1);assert.equal(result.requests,1);assert.equal(f.adapter.snapshot().fetch_requests,1);assert.equal(f.childFrames.filter(frame=>frame.type==="fetch").length,mode==="second-child-frame"?2:1);}finally{await f.close();}
});
