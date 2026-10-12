// 仅自有fake adapter/child，实际transport/header/send校验仍运行；不spawn/Worker/SDK。
import test from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { runReviewerProcessProbe } from "../../../scripts/pi-probe-reviewer-sdk-process.mjs";
import { createReviewHeaders } from "../../../agents/pi/packages/risk-review/src/request-headers.ts";
const cfg={anchor:"/synthetic/package.json",platform:"linux",arch:"x64",release:"synthetic",runtimeVersion:"v24.14.0",sdkVersion:"7.19.0"};
function fakeSeams(mode="normal") {
  const calls=[];
  const spawnProcess=(exe,argv,settings)=>{
    calls.push({exe,argv,settings});
    const child=new EventEmitter();child.stdout=new EventEmitter();child.stderr=new EventEmitter();
    child.exitCode=null;child.signalCode=null;
    child.kill=signal=>{
      child.signalCode=signal;
      queueMicrotask(()=>{
        if(mode==="stdout")child.stdout.emit("data",Buffer.from("SYNTHETIC_PRIVATE"));
        if(mode==="stderr")child.stderr.emit("data",Buffer.from("SYNTHETIC_PRIVATE"));
        if(mode!=="missing-close")child.emit("close",null,signal);
      });return true;
    };
    return child;
  };
  const adapterFactory=({processFactory,sharedModel})=>{
    let started=false, scope;
    const sdk={normalizeContext:value=>structuredClone(value),streamSimple:async function*(model,context,options){
      started=true;
      assert.deepEqual(model,sharedModel.prepared.sdk_model);assert.equal(model.maxTokens,384000);assert.equal(options.maxTokens,4096);assert.equal(options.reasoning,"off");assert.deepEqual(model.input,["text","image"]);assert.notEqual(model.name,model.id);
      scope=processFactory(new URL("../../../agents/pi/packages/risk-review/src/sdk-process-entry.ts",import.meta.url),
        {env:{OPENAI_LOG:"off"},execArgv:["--experimental-import-meta-resolve"],argv:["--risk-review-sdk-process","--risk-review-shared-model="+(mode==="bad-marker"?"a".repeat(64):sharedModel.prepared.model_identity)],stdio:["ignore","pipe","pipe","pipe","pipe"]});
      const headers=createReviewHeaders({apiKey:options.apiKey,timeoutMs:options.timeoutMs,platform:cfg.platform,arch:cfg.arch,release:cfg.release,runtimeVersion:cfg.runtimeVersion,sdkVersion:cfg.sdkVersion});
      if(mode==="bad-header") headers.authorization="SYNTHETIC_PRIVATE"; // 冻结阻止修改，固定失败。
      const response=await options.fetch(model.baseUrl+"/chat/completions",{method:"POST",headers,
        body:JSON.stringify({model:model.id,messages:[{role:"system",content:context.systemPrompt},{role:"user",content:context.messages[0].content}],stream:true,stream_options:{include_usage:true},temperature:0,max_tokens:options.maxTokens,...(model.reasoning&&mode!=="missing-thinking"?{thinking:{type:mode==="enabled-thinking"?"enabled":"disabled"}}:{}),...(mode==="tools"?{tools:[]}:{}),...(mode==="bad-cap"?{max_tokens:384000}:{})}),signal:options.signal});
      const raw=await response.text();
      const events=raw.split("\n").filter(x=>x.startsWith("data: ")&&!x.includes("[DONE]")).map(x=>JSON.parse(x.slice(6)));
      for(const event of events)await options.onProviderStreamEvent({model:event.model,...(event.usage?{usage:event.usage}:{})});
      const text=events.flatMap(x=>x.choices).map(x=>x.delta?.content??"").join("");
      yield{type:"done",message:{api:model.api,provider:model.provider,model:model.id,stopReason:"stop",content:[{type:"text",text:mode==="bad-content"?"SYNTHETIC_PRIVATE":text}]}};
    }};
    return{sdk,close:async()=>{if(scope)await scope.terminate();},snapshot:()=>({child_started:started,process_terminated:mode==="false-proof"})};
  };
  return {seams:{adapterFactory,spawnProcess},calls};
}
test("closed eleven-case fake combination preserves no-send and unknown scope", async()=>{
  const {seams,calls}=fakeSeams();const result=await runReviewerProcessProbe(cfg,seams);
  assert.deepEqual(Object.keys(result).sort(),["cases","probe_id","product_gate","schema_version","status"]);
  assert.equal(result.status,"observed");assert.equal(result.cases.length,11);assert.equal(result.product_gate,false);
  assert.equal(calls.length,8);
  for(const [index,row] of result.cases.entries()) {
    assert.equal(row.scope_termination,"not-independently-observed");assert.equal(row.requests,index<7||index===9?1:0);
    assert.equal(row.child_started,index<7||index===9);assert.equal(row.child_close_observed,index<7||index===9);
    assert.equal(row.child_stdout_bytes,0);assert.equal(row.child_stderr_bytes,0);
    assert.match(row.model_identity,/^[a-f0-9]{64}$/);
    if(row.requests) {assert.equal(row.wire.max_tokens,4096);assert.equal(row.wire.shape,row.case_id==="text-allow"?"openai-chat-text":"deepseek-chat-text-disabled");assert.deepEqual(row.wire.thinking,row.case_id==="text-allow"?null:{type:"disabled"});} else assert.equal(row.wire,null);
    assert.equal(Object.isFrozen(row),true);assert.equal(Object.isFrozen(row.usage),true);
  }
  for(const row of result.cases.filter(r=>["hard-deny","human-required","input-unqualified"].includes(r.case_id)))assert.deepEqual(row.usage,{status:"not-sent",input_tokens:0,output_tokens:0,total_tokens:0});
  for(const row of result.cases.slice(3,7))assert.deepEqual(row.usage,{status:"unknown",input_tokens:null,output_tokens:null,total_tokens:null});
  for(const call of calls) {
    assert.deepEqual(call.settings,{env:{OPENAI_LOG:"off"},stdio:["ignore","pipe","pipe","pipe","pipe"],cwd:"/work"});
    assert.equal(call.argv[0],"--experimental-import-meta-resolve");assert.equal(call.argv.at(-2),"--risk-review-sdk-process");assert.match(call.argv.at(-1),/^--risk-review-shared-model=[a-f0-9]{64}$/);
    assert.equal(call.argv.some(x=>x.includes("SYNTHETIC_PROBE_KEY")||x.includes("SYNTHETIC_MAIN_SECRET")),false);
  }
  const text=JSON.stringify(result);
  assert.equal(text.includes("SYNTHETIC_PROBE_KEY"),false);assert.equal(text.includes("synthetic policy"),false);
});
for(const mode of ["stdout","stderr","bad-content","false-proof","bad-header","bad-marker","missing-thinking","enabled-thinking","tools","bad-cap"])test(`reject ${mode} without raw exception`,async()=>{
  const {seams}=fakeSeams(mode);
  await assert.rejects(runReviewerProcessProbe(cfg,seams),error=>error.code==="PI_REVIEWER_SDK_PROCESS_PROBE_FAILED"&&error.message===error.code&&!error.message.includes("SYNTHETIC_PRIVATE"));
});
test("invalid configuration is zero adapter/child",async()=>{
  for(const invalid of [{...cfg,anchor:"relative"},{...cfg,apiKey:"SYNTHETIC_PRIVATE"},{...cfg,platform:"darwin"}]) {
    let calls=0;
    await assert.rejects(runReviewerProcessProbe(invalid,{adapterFactory:()=>{calls++;throw Error("unexpected");},spawnProcess:()=>{calls++;}}));
    assert.equal(calls,0);
  }
});
test("configuration getter and proxy are never executed",async()=>{
  let touched=0;const getter={...cfg};Object.defineProperty(getter,"anchor",{enumerable:true,get(){touched++;return cfg.anchor;}});
  const proxy=new Proxy(cfg,{get(){touched++;throw Error("private");},getPrototypeOf(){touched++;throw Error("private");}});
  for(const value of [getter,proxy])await assert.rejects(runReviewerProcessProbe(value));
  assert.equal(touched,0);
});
test("unconfirmed child close is bounded failure, never observed",async()=>{
  const {seams,calls}=fakeSeams("missing-close");
  await assert.rejects(runReviewerProcessProbe(cfg,seams),error=>error.code==="PI_REVIEWER_SDK_PROCESS_PROBE_FAILED");
  assert.equal(calls.length,1);
});
