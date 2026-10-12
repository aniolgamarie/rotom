// 断网合成观察：真实来源/安装身份由父预检负责，本文件不能签产品准入。
import { types } from "node:util";
import { isAbsolute } from "node:path";
import { spawn } from "node:child_process";
import { setEnvironmentData } from "node:worker_threads";
import { fileURLToPath, pathToFileURL } from "node:url";
import { writeFileSync } from "node:fs";
import { release } from "node:os";
import { createReviewHeaders } from "../agents/pi/packages/risk-review/src/request-headers.ts";
import { createProcessReviewSdk } from "../agents/pi/packages/risk-review/src/sdk-process.ts";
import { createReviewAttempt } from "../agents/pi/packages/risk-review/src/transport.ts";
import { prepareSharedReviewModel } from "../agents/pi/packages/risk-review/src/shared-model.ts";
import { compileSharedReviewSdkContract } from "../agents/pi/packages/risk-review/src/shared-sdk-contract.ts";
const code = "PI_REVIEWER_SDK_PROCESS_PROBE_FAILED";
const ids = ["allow", "ask", "deny", "missing-usage", "wrong-model", "canceled", "response-limit", "hard-deny", "human-required", "text-allow", "input-unqualified"];
function shared(caseId) {
  const reasoning=caseId!=="text-allow",model_id=reasoning?"synthetic-reviewer":"synthetic-text";
  const route={logical_provider:"synthetic-provider",native_route:"synthetic-provider",model_id,auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url:"https://synthetic-review.invalid/v1"},configuration_identity="e".repeat(64);
  const prepared=prepareSharedReviewModel({route,configuration_identity,token_limits:{input_tokens:12000,output_tokens:4096},descriptor:{id:model_id,provider:"synthetic-provider",api:route.api,name:reasoning?"Actual Synthetic DeepSeek":"Actual Synthetic Text",baseUrl:route.base_url,reasoning,input:["text","image"],cost:{input:1,output:2,cacheRead:0.1,cacheWrite:0},contextWindow:1000000,maxTokens:384000,compat:{requiresReasoningContentOnAssistantMessages:true,thinkingFormat:"deepseek"},thinkingLevelMap:{low:"low",medium:"high",high:"high"}}});
  return {prepared,route,configuration_identity};
}
const apiKey = "SYNTHETIC_PROBE_KEY";
function fail() { const error = new Error(code); error.code = code; throw error; }
function configuration(value) {
  const keys=["anchor","platform","arch","release","runtimeVersion","sdkVersion"];
  if (!value || types.isProxy(value) || Object.getPrototypeOf(value)!==Object.prototype) fail();
  const names=Reflect.ownKeys(value);
  if(names.length!==keys.length || names.some(x=>typeof x!=="string" || !keys.includes(x))) fail();
  const copy={};
  for(const key of keys) { const d=Object.getOwnPropertyDescriptor(value,key); if(!d?.enumerable || !Object.hasOwn(d,"value")) fail(); copy[key]=d.value; }
  if(typeof copy.anchor!=="string" || copy.anchor.length>4096 || !isAbsolute(copy.anchor) || copy.anchor.includes("\0") || copy.anchor.split("/").some(x=>x===".."||x===".")) fail();
  return copy;
}
async function closed(adapter) {
  let timer;
  try { await Promise.race([adapter.close(),new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(code)),3000);})]); }
  finally { clearTimeout(timer); }
}
function sse(caseId, model, binding) {
  const decision=["ask","deny"].includes(caseId)?caseId:"allow";
  const reason={allow:"authorized-in-scope",ask:"ambiguous-intent",deny:"outside-user-scope"}[decision];
  const answer=JSON.stringify({schema_version:1,...binding,decision,reason_code:reason});
  const remote=caseId==="wrong-model"?"synthetic-other-model":model;
  const chunk={id:"synthetic-chunk",object:"chat.completion.chunk",created:1,model:remote,
    choices:[{index:0,delta:{role:"assistant",content:answer},finish_reason:null}]};
  const finish={id:"synthetic-chunk",object:"chat.completion.chunk",created:1,model:remote,
    choices:[{index:0,delta:{},finish_reason:"stop"}]};
  const usage={id:"synthetic-chunk",object:"chat.completion.chunk",created:1,model:remote,choices:[],
    usage:{prompt_tokens:5,completion_tokens:3,total_tokens:8}};
  return [chunk,finish,...(caseId==="missing-usage"?[]:[usage])].map(x=>"data: "+JSON.stringify(x)+"\n\n").join("")+"data: [DONE]\n\n";
}
export async function runReviewerProcessProbe(options, seams = {}) {
  try {
    const cfg=configuration(options), {anchor,...platform}=cfg;
    const expectedHeaders=createReviewHeaders({apiKey,timeoutMs:5000,...platform});
    const rows=[];
    const adapterFactory=seams.adapterFactory??createProcessReviewSdk, spawnProcess=seams.spawnProcess??spawn;
    if(typeof adapterFactory!=="function" || typeof spawnProcess!=="function") fail();
    for(const caseId of ids) {
      const packet=shared(caseId),compiled=compileSharedReviewSdkContract(packet),binding={request_id:"1".repeat(32),operation_digest:"a".repeat(64),context_digest:"b".repeat(64),reviewer_identity:compiled.model_identity};
      let started=0, closeObserved=false, stdoutBytes=0, stderrBytes=0, wire=null;
      const processFactory=(url,settings)=>{
        if(url.href!==new URL("../agents/pi/packages/risk-review/src/sdk-process-entry.ts",import.meta.url).href
          || JSON.stringify(settings)!==JSON.stringify({env:{OPENAI_LOG:"off"},execArgv:["--experimental-import-meta-resolve"],argv:["--risk-review-sdk-process","--risk-review-shared-model="+compiled.model_identity],stdio:["ignore","pipe","pipe","pipe","pipe"]}) || started!==0) fail();
        started++;
        const child=spawnProcess(process.execPath,[...settings.execArgv,fileURLToPath(url),...settings.argv],{env:settings.env,stdio:settings.stdio,cwd:"/work"});
        const closed=new Promise(resolve=>child.once("close",()=>{closeObserved=true;resolve();}));
        child.on("error",()=>{}); // 仅固定drain，不输出SDK异常正文。
        child.stdout.on("data",part=>{stdoutBytes+=part.byteLength;});child.stderr.on("data",part=>{stderrBytes+=part.byteLength;});
        return {child,terminate:async()=>{
          if(child.exitCode===null&&child.signalCode===null) child.kill("SIGTERM");
          await closed;
          // leader close不证明整个process scope；可信监督者未集成。
          return false;
        }};
      };
      const adapter=adapterFactory({anchor,processFactory,sharedModel:packet}), abort=new AbortController(); let sends=0, result;
      try {
        const attempt=createReviewAttempt({binding,route:{identity:binding.reviewer_identity,pricing_identity:"d".repeat(64),currency:"USD",
          provider:"synthetic-provider",model:packet.route.model_id,base_url:packet.route.base_url,
          context_window:1000000,max_output_tokens:4096,cost:{input:1,output:2,cacheRead:1,cacheWrite:1}},
          input:{system_prompt:"synthetic policy",user_prompt:"Review only this synthetic authorized change."},
          qualification:{profile:"pi-full",enabled:true,hard_policy_allowed:caseId!=="hard-deny",role_allows:true,
            requires_human:caseId==="human-required",automatic_risk_allowed:true},
          sharedModel:packet,...(caseId==="input-unqualified"?{}:{inputQualification:()=>true}),
          apiKey,expectedHeaders,sdk:adapter.sdk,isCurrent:()=>true,signal:abort.signal,
          deadlineMs:Date.now()+10000,maxDurationMs:5000,responseLimit:caseId==="response-limit"?32:65536,
          send:async(url,init)=>{
            const body=JSON.parse(init.body);wire=Object.freeze({shape:body.thinking?"deepseek-chat-text-disabled":"openai-chat-text",model:body.model,max_tokens:body.max_tokens,thinking:body.thinking??null});
            sends++;
            if(caseId==="canceled") queueMicrotask(()=>abort.abort());
            return new Response(sse(caseId,packet.route.model_id,binding),{headers:{"content-type":"text/event-stream"}});
          }});
        result=await attempt.run();
      } finally { await closed(adapter); }
      const childState=adapter.snapshot(), blocked=["hard-deny","human-required","input-unqualified"].includes(caseId);
      if(result.requests!==(blocked?0:1) || sends!==result.requests || childState.child_started!==!blocked || started!==(blocked?0:1) || closeObserved!==!blocked || childState.process_terminated!==false || stdoutBytes!==0 || stderrBytes!==0) fail();
      const valid=["allow","ask","deny","missing-usage","text-allow"].includes(caseId);
      if(!blocked&&(wire?.shape!==compiled.wire_contract.shape||wire.model!==packet.route.model_id||wire.max_tokens!==4096||JSON.stringify(wire.thinking)!==JSON.stringify(caseId==="text-allow"?null:{type:"disabled"})))fail();
      if(valid && (result.outcome!=="valid" || result.candidate?.decision!==(["ask","deny"].includes(caseId)?caseId:"allow"))) fail();
      if(caseId==="missing-usage" && (result.usage.status!=="unknown" || result.usage.total_tokens!==null)) fail();
      if(["allow","ask","deny","text-allow"].includes(caseId) && (result.usage.status!=="reported" || result.usage.input_tokens!==5 || result.usage.output_tokens!==3 || result.usage.total_tokens!==8)) fail();
      if(!valid && result.candidate!==null) fail();
      if(caseId==="wrong-model" && result.remote_model_verified!==false) fail();
      if(caseId==="canceled" && result.outcome!=="canceled") fail();
      if(caseId==="response-limit" && (result.outcome!=="transport-failure" || result.wire.failure_code!=="PI_RISK_FETCH_LIMIT")) fail();
      if(caseId==="input-unqualified"&&result.outcome!=="transport-failure")fail();
      if(caseId==="hard-deny" && result.outcome!=="policy-blocked" || caseId==="human-required" && result.outcome!=="human-required") fail();
      rows.push(Object.freeze({case_id:caseId,outcome:"observed",transport_outcome:result.outcome,decision:result.candidate?.decision??null,
        model_identity:compiled.model_identity,wire,requests:result.requests,usage:Object.freeze({status:result.usage.status,input_tokens:result.usage.input_tokens,output_tokens:result.usage.output_tokens,total_tokens:result.usage.total_tokens}),
        child_started:childState.child_started,child_close_observed:closeObserved,child_stdout_bytes:stdoutBytes,child_stderr_bytes:stderrBytes,scope_termination:"not-independently-observed"}));
    }
    return Object.freeze({schema_version:1,probe_id:"reviewer-sdk-process-shared-v2",status:"observed",cases:Object.freeze(rows),product_gate:false});
  } catch { fail(); }
}
const environment={HOME:"/work/home",PWD:"/work",PATH:"/work/empty-bin",TMPDIR:"/work/tmp",XDG_CONFIG_HOME:"/work/config",XDG_DATA_HOME:"/work/data",
  XDG_CACHE_HOME:"/work/cache",XDG_STATE_HOME:"/work/state",LC_ALL:"C.UTF-8",PI_PROBE_NATIVE:"1",PI_OFFLINE:"1",OTEL_SDK_DISABLED:"true",
  OPENAI_LOG:"debug",OPENAI_API_KEY:"SYNTHETIC_AMBIENT_AUTH",OPENAI_ADMIN_KEY:"SYNTHETIC_AMBIENT_ADMIN",OPENAI_WEBHOOK_SECRET:"SYNTHETIC_AMBIENT_WEBHOOK",
  OPENAI_ORG_ID:"SYNTHETIC_AMBIENT_ORG",OPENAI_CUSTOM_HEADERS:"X-Review-Sentinel: SYNTHETIC_AMBIENT_HEADER"};
async function main() {
  let result={schema_version:1,probe_id:"reviewer-sdk-process-shared-v2",status:"failed",cases:[],product_gate:false};
  let timer;
  try {
    if(process.argv.length!==3 || process.argv[2]!=="--native-reviewer-sdk-process-probe" || Object.keys(process.env).length!==Object.keys(environment).length
      || Object.entries(environment).some(([key,value])=>process.env[key]!==value)) fail();
    // 硬截止只用于专用探针进程，不把终止请求冒充Worker已结束。
    timer=setTimeout(()=>{
      try { writeFileSync("/work/reviewer-process-result.json",JSON.stringify(result)+"\n",{flag:"wx",mode:0o600}); } catch {}
      process.stdout.write(JSON.stringify({schema_version:1,status:"failed",cases:0,product_gate:false})+"\n");
      process.exit(5);
    },60000);
    setEnvironmentData("synthetic-main-secret","SYNTHETIC_MAIN_SECRET");
    process.env.SYNTHETIC_MAIN_KEY="SYNTHETIC_MAIN_SECRET";
    result=await runReviewerProcessProbe({anchor:"/candidate/package.json",platform:process.platform,arch:process.arch,release:release(),runtimeVersion:process.version,sdkVersion:"7.19.0"});
  } catch { process.exitCode=5; }
  finally { clearTimeout(timer); }
  try { writeFileSync("/work/reviewer-process-result.json",JSON.stringify(result)+"\n",{flag:"wx",mode:0o600}); }
  catch { process.exitCode=5; result={schema_version:1,probe_id:"reviewer-sdk-process-shared-v2",status:"failed",cases:[],product_gate:false}; }
  process.stdout.write(JSON.stringify({schema_version:1,status:result.status,cases:result.cases.length,product_gate:false})+"\n");
}
if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) await main();
