import assert from "node:assert/strict";
import test from "node:test";
import { compileReviewTransportSettlement } from "../src/transport-settlement.ts";
import { createReviewAttempt } from "../src/transport.ts";
import { parseReviewResponse } from "../src/protocol.ts";
const expected=()=>({request_id:"1".repeat(32),operation_digest:"a".repeat(64),context_digest:"b".repeat(64),reviewer_identity:"c".repeat(64)});
const candidate=(decision="allow")=>parseReviewResponse(JSON.stringify({schema_version:1,...expected(),decision,reason_code:{allow:"authorized-in-scope",ask:"needs-human",deny:"outside-user-scope"}[decision]}),expected());
function actual(decision="allow",extra={}){
  const binding=expected(),headers={authorization:"Bearer SYNTHETIC_PRIVATE",accept:"application/json","content-type":"application/json"};
  const cfg={binding,route:{identity:binding.reviewer_identity,pricing_identity:"d".repeat(64),currency:"USD",provider:"synthetic",model:"model",base_url:"https://synthetic.invalid/v1",context_window:32000,max_output_tokens:1024,cost:{input:1,output:2,cacheRead:1,cacheWrite:1}},
    input:{system_prompt:"policy",user_prompt:"operation"},qualification:{profile:"pi-full",enabled:true,hard_policy_allowed:true,role_allows:true,requires_human:false,automatic_risk_allowed:true},
    apiKey:"SYNTHETIC_PRIVATE",expectedHeaders:headers,isCurrent:()=>true,deadlineMs:Date.now()+10000,maxDurationMs:1000,
    send:()=>new Response("synthetic"),sdk:{normalizeContext:value=>value,async *streamSimple(model,context,o){
      await(await o.fetch(model.baseUrl+"/chat/completions",{method:"POST",headers,body:JSON.stringify({model:model.id,messages:[{role:"system",content:context.systemPrompt},{role:"user",content:context.messages[0].content}],stream:true,stream_options:{include_usage:true},temperature:0,max_tokens:o.maxTokens}),signal:o.signal})).text();
      o.onProviderStreamEvent({model:model.id,usage:{prompt_tokens:5,completion_tokens:3,total_tokens:8}});
      const parsed=candidate(decision);const {source,...wire}=parsed;
      yield{type:"done",message:{api:model.api,provider:model.provider,model:model.id,stopReason:"stop",content:[{type:"text",text:JSON.stringify(wire)}]}};
    }},...extra};return createReviewAttempt(cfg);
}
function sample(outcome="valid"){
  return{schema_version:1,phase:"settled",outcome,candidate:outcome==="valid"?{...candidate()}:null,binding:expected(),requests:outcome==="valid"?1:0,request_count_scope:"local-platform-fetch-invocations",
    wire:{invocations:outcome==="valid"?1:0,requests:outcome==="valid"?1:0,response_bytes:outcome==="valid"?9:0,body_complete:outcome==="valid",redirect_blocked:false,second_request_blocked:false,failure_code:null}};
}
const compile=(s)=>compileReviewTransportSettlement(s,expected());
test("actual createReviewAttempt final allow projects seven-field Python response",async()=>{
  const s=await actual().run(),r=compile(s);assert.equal(r.outcome,"valid");assert.equal(r.platform_requests,1);
  assert.deepEqual(Object.keys(r).sort(),["outcome","platform_requests","response","gate_attempted","gate_acknowledged"].sort());
  const value=JSON.parse(r.response);assert.equal(Object.keys(value).length,7);assert.equal(Object.hasOwn(value,"source"),false);assert.equal(parseReviewResponse(r.response,expected()).decision,"allow");
});

const CODE="PI_RISK_REVIEW_SETTLEMENT_INVALID";
const invalid=(s,e=expected())=>assert.throws(()=>compileReviewTransportSettlement(s,e),error=>error.code===CODE&&error.message===CODE&&!error.cause&&!error.message.includes("SYNTHETIC_PRIVATE"));
for(const decision of["allow","ask","deny"])test(`actual final ${decision} reports candidate without source or metadata`,async()=>{
  const result=compile(await actual(decision,{beforeSend:()=>true}).run());
  assert.equal(JSON.parse(result.response).decision,decision);assert.equal(result.gate_attempted,true);assert.equal(result.gate_acknowledged,true);
  assert(Object.isFrozen(result));assert.equal(Object.getPrototypeOf(result),Object.prototype);assert.equal(JSON.stringify(result).includes("SYNTHETIC_PRIVATE"),false);
});
for(const outcome of["not-called","policy-blocked","human-required","canceled","timeout","discarded","transport-failure","protocol-failure"])test(`nonvalid ${outcome} keeps facts and null response`,()=>{
  const s=sample(outcome),r=compile(s);assert.deepEqual(r,{outcome,platform_requests:0,response:null,gate_attempted:false,gate_acknowledged:false});
  s.outcome="valid";s.requests=1;s.binding.request_id="2".repeat(32);s.wire.requests=1;
  assert.equal(r.outcome,outcome);assert.equal(r.platform_requests,0);
});
for(const phase of["prepared","running",undefined])test(`phase ${phase} is not a final report`,()=>{const s=sample();s.phase=phase;invalid(s);});
for(const value of[true,false,null,undefined,2,-1,1.5,NaN,Infinity])test(`count ${String(value)} cannot substitute child fetch or unknown`,()=>{const s=sample();s.requests=value;s.wire.requests=value;invalid(s);});
for(const field of["schema_version","outcome","request_count_scope","wire-count","fetch_requests","unknown"])test(`snapshot shape ${field} rejects`,()=>{
  const s=sample();if(field==="schema_version")s.schema_version=true;else if(field==="outcome")s.outcome="invented";else if(field==="request_count_scope")s.request_count_scope="child-fetch-frames";else if(field==="wire-count")s.wire.requests=0;else s[field]=1;invalid(s);
});
for(const field of["gate_attempted","gate_acknowledged","ack-without-attempt","wrong-bool","wire-extra","wire-missing"])test(`wire flags/closed facts ${field}`,()=>{
  const s=sample();s.wire.gate_attempted=true;s.wire.gate_acknowledged=true;
  if(field==="gate_attempted"||field==="gate_acknowledged")delete s.wire[field];
  if(field==="ack-without-attempt")s.wire.gate_attempted=false;
  if(field==="wrong-bool")s.wire.gate_attempted=1;
  if(field==="wire-extra")s.wire.fetch_requests=1;
  if(field==="wire-missing")delete s.wire.invocations;
  invalid(s);
});
test("actual not-called final zero snapshot has no gate flags and projects false",async()=>{
  const a=actual("allow",{qualification:{profile:"pi-base",enabled:true,hard_policy_allowed:true,role_allows:true,requires_human:false,automatic_risk_allowed:true}}),s=await a.run();
  assert.equal(Object.hasOwn(s.wire,"gate_attempted"),false);assert.deepEqual(compile(s),{outcome:"not-called",platform_requests:0,response:null,gate_attempted:false,gate_acknowledged:false});
});
test("late gate acknowledgement after canceled wait is not a platform entry",{timeout:2000},async()=>{
  let enter,ack;const entered=new Promise(resolve=>{enter=resolve;}),pending=new Promise(resolve=>{ack=resolve;}),signal=new AbortController();
  const a=actual("allow",{signal:signal.signal,beforeSend:()=>{enter();return pending;}});
  const running=a.run();await entered;signal.abort();await running;ack(true);await new Promise(resolve=>setImmediate(resolve));
  const result=compile(a.snapshot());assert.equal(result.outcome,"canceled");assert.equal(result.platform_requests,0);assert.equal(result.response,null);assert.equal(result.gate_attempted,true);assert.equal(result.gate_acknowledged,true);
});
for(const field of["request_id","operation_digest","context_digest","reviewer_identity"])test(`expected original ${field} immutable binding`,()=>{
  const s=sample(),e=expected();e[field]=(field==="request_id"?"2":"d").repeat(field==="request_id"?32:64);invalid(s,e);
  const value=sample();value.candidate={...value.candidate,[field]:e[field]};invalid(value);
});
for(const change of["source","source-extra","toJSON","unknown","bad-reason","schema-bool","unicode","nonvalid-candidate"])test(`candidate ${change} is safely recaptured and revalidated`,()=>{
  const s=sample();let calls=0;s.candidate={...s.candidate};
  if(change==="source")s.candidate.source="human";
  if(change==="source-extra")s.candidate.permit="SYNTHETIC_PRIVATE";
  if(change==="toJSON")s.candidate.toJSON=()=>{calls++;throw Error("SYNTHETIC_PRIVATE");};
  if(change==="unknown")s.candidate.authorization="SYNTHETIC_PRIVATE";
  if(change==="bad-reason")s.candidate.reason_code="needs-human";
  if(change==="schema-bool")s.candidate.schema_version=true;
  if(change==="unicode")s.candidate.reason_code="\ud800";
  if(change==="nonvalid-candidate")s.outcome="canceled";
  invalid(s);assert.equal(calls,0);
});
for(const target of["snapshot","wire","binding","expected","candidate"])for(const kind of["getter","proxy"])test(`${target} ${kind} never executes trap`,()=>{
  const s=sample();let e=expected(),calls=0;const trap=()=>{calls++;throw Error("SYNTHETIC_PRIVATE");};
  let value=target==="expected"?e:target==="snapshot"?s:s[target];
  if(kind==="getter")Object.defineProperty(value,target==="snapshot"?"outcome":target==="wire"?"requests":target==="candidate"?"source":"request_id",{enumerable:true,get:trap});
  else value=new Proxy(value,{get:trap,ownKeys:trap,getPrototypeOf:trap});
  let actualSnapshot=s;if(target==="expected")e=value;else if(target==="snapshot")actualSnapshot=value;else s[target]=value;
  invalid(actualSnapshot,e);assert.equal(calls,0);
});
for(const target of["snapshot","wire","candidate","binding","expected"])test(`${target} symbols/inheritance/hidden data reject`,()=>{
  for(const fault of["symbol","inherited","hidden"]){let s=sample(),e=expected(),value=target==="expected"?e:target==="snapshot"?s:s[target];
    if(fault==="symbol")value[Symbol("private")]=1;
    if(fault==="inherited")Object.setPrototypeOf(value,{private:"SYNTHETIC_PRIVATE"});
    if(fault==="hidden")Object.defineProperty(value,"hidden",{value:1});
    invalid(s,e);
  }
});
test("known non-authority metadata is not traversed or serialized",()=>{
  const s=sample();let reads=0;s.usage=new Proxy({},{get(){reads++;throw Error("SYNTHETIC_PRIVATE");}});s.records={get private(){reads++;throw Error("SYNTHETIC_PRIVATE");}};
  const r=compile(s);assert.equal(reads,0);assert.equal(Object.hasOwn(r,"usage"),false);assert.equal(Object.hasOwn(r,"records"),false);
});
test("projection is independently frozen and preserves caller data",()=>{
  const s=sample(),e=expected(),before=structuredClone(s),r=compileReviewTransportSettlement(s,e);
  assert.deepEqual(s,before);assert.deepEqual(e,expected());assert.equal(Object.isFrozen(r),true);
  s.candidate={...s.candidate,decision:"deny",reason_code:"outside-user-scope"};e.request_id="2".repeat(32);
  assert.equal(JSON.parse(r.response).decision,"allow");assert.equal(JSON.parse(r.response).request_id,"1".repeat(32));
  assert.throws(()=>{r.platform_requests=0;},TypeError);
});


test("candidate oversized primitive fails before unbounded serialization",()=>{
  const s=sample();s.candidate.reason_code="SYNTHETIC_PRIVATE".repeat(10000);invalid(s);
});
