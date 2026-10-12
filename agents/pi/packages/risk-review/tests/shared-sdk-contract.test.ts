import test from "node:test";
import assert from "node:assert/strict";
import { prepareSharedReviewModel } from "../src/shared-model.ts";
import { compileSharedReviewSdkContract } from "../src/shared-sdk-contract.ts";
function fixture() {
  const route={logical_provider:"deepseek",native_route:"agentcfg-deepseek",model_id:"deepseek-flash",auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url:"https://api.deepseek.com"};
  const configuration_identity="a".repeat(64);
  const prepared=prepareSharedReviewModel({route,configuration_identity,token_limits:{input_tokens:12000,output_tokens:2048},descriptor:{id:route.model_id,provider:route.native_route,api:route.api,name:"DeepSeek Flash",baseUrl:route.base_url,reasoning:true,input:["text","image"],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:1000000,maxTokens:384000,
    compat:{requiresReasoningContentOnAssistantMessages:true,thinkingFormat:"deepseek"},thinkingLevelMap:{low:"low",medium:"high",high:"high"}}});
  return {prepared,route,configuration_identity};
}
test("explicit DeepSeek reasoning-off preserves actual safe Model",()=>{
  const options=fixture(),result=compileSharedReviewSdkContract(options);
  assert.deepEqual(result.sdk_model,options.prepared.sdk_model);
  assert.equal(result.sdk_model.reasoning,true);assert.deepEqual(result.sdk_model.input,["text","image"]);
  assert.equal(result.sdk_model.name,"DeepSeek Flash");assert.equal(result.sdk_model.maxTokens,384000);
  assert.deepEqual(result.sdk_options,{maxRetries:0,maxTokens:2048,temperature:0,reasoning:"off"});
  assert.deepEqual(result.wire_contract,{schema_version:1,api:"openai-completions",base_url:options.route.base_url,model:options.route.model_id,shape:"deepseek-chat-text-disabled",output_tokens:2048});
  assert.equal(result.model_identity,options.prepared.model_identity);
});
const INVALID="PI_RISK_REVIEW_SDK_CONTRACT_INVALID",UNSUPPORTED="PI_RISK_REVIEW_SDK_CONTRACT_UNSUPPORTED";
function rejects(options,code=INVALID){assert.throws(()=>compileSharedReviewSdkContract(options),error=>error.code===code&&error.message===code&&!error.cause&&!error.message.includes("SYNTHETIC_PRIVATE"));}
function rebuild(options,edit){
  const base=structuredClone(options.prepared.base_model);edit(base);
  options.prepared=prepareSharedReviewModel({descriptor:base,route:options.route,configuration_identity:options.configuration_identity,
    token_limits:{input_tokens:options.prepared.request_policy.input_tokens,output_tokens:options.prepared.request_policy.output_tokens}});
  return options;
}
test("generic nonreasoning needs no endpoint inference or native map",()=>{
  const options=rebuild(fixture(),base=>{base.reasoning=false;delete base.compat;delete base.thinkingLevelMap;});
  const result=compileSharedReviewSdkContract(options);assert.equal(result.wire_contract.shape,"openai-chat-text");
  assert.deepEqual(result.sdk_model,options.prepared.sdk_model);assert.equal(result.sdk_options.reasoning,"off");
});
for(const branch of ["no-compat","empty-compat","off-null","other-format"])test(`reasoning branch ${branch} is explicit unsupported`,()=>{
  const options=fixture();
  if(branch!=="other-format")rebuild(options,base=>{
    if(branch==="no-compat")delete base.compat;
    if(branch==="empty-compat")base.compat={};
    if(branch==="off-null")base.thinkingLevelMap.off=null;
  });else{options.prepared=structuredClone(options.prepared);options.prepared.base_model.compat.thinkingFormat="openai";}
  rejects(options,UNSUPPORTED);
});
test("explicit non-null off supported, original map not rewritten",()=>{
  const options=rebuild(fixture(),base=>{base.thinkingLevelMap.off="off";});
  const result=compileSharedReviewSdkContract(options);assert.equal(result.wire_contract.shape,"deepseek-chat-text-disabled");assert.equal(result.sdk_model.thinkingLevelMap.off,"off");
});
for(const field of ["base_model","sdk_model","request_policy","model_identity"])test(`prepared missing ${field}`,()=>{
  const options=structuredClone(fixture());delete options.prepared[field];rejects(options);
});
for(const field of ["prepared","route","configuration_identity"])test(`options missing ${field}`,()=>{
  const options=fixture();delete options[field];rejects(options);
});
for(const variant of ["identity","base-name","sdk-name","base-and-sdk-name","base-cost","sdk-reasoning","sdk-image","sdk-cap","sdk-nativecompat","sdk-reviewcompat","sdk-map","policy-reasoning","policy-input-mode","policy-output","policy-version","policy-extra","route-logical","route-model","route-url","configuration","prepared-extra","options-extra","base-header","sdk-header"])test(`complete prepared binding rejects drift ${variant}`,()=>{
  const options=structuredClone(fixture());const p=options.prepared;
  if(variant==="identity")p.model_identity="b".repeat(64);
  if(variant==="base-name")p.base_model.name="changed actual name";
  if(variant==="sdk-name")p.sdk_model.name="changed SDK name";
  if(variant==="base-and-sdk-name")p.base_model.name=p.sdk_model.name="same tampered name";
  if(variant==="base-cost")p.base_model.cost.input=1;
  if(variant==="sdk-reasoning")p.sdk_model.reasoning=false;
  if(variant==="sdk-image")p.sdk_model.input=["text"];
  if(variant==="sdk-cap")p.sdk_model.maxTokens=2048;
  if(variant==="sdk-nativecompat")p.sdk_model.compat.requiresReasoningContentOnAssistantMessages=false;
  if(variant==="sdk-reviewcompat")p.sdk_model.compat.supportsStore=true;
  if(variant==="sdk-map")p.sdk_model.thinkingLevelMap.medium="medium";
  if(variant==="policy-reasoning")p.request_policy.reasoning_mode="on";
  if(variant==="policy-input-mode")p.request_policy.input_mode="image";
  if(variant==="policy-output")p.request_policy.output_tokens=2047;
  if(variant==="policy-version")p.request_policy.schema_version=true;
  if(variant==="policy-extra")p.request_policy.apiKey="SYNTHETIC_PRIVATE";
  if(variant==="route-logical")options.route.logical_provider="other-logical";
  if(variant==="route-model")options.route.model_id="other-model";
  if(variant==="route-url")options.route.base_url="https://other.invalid";
  if(variant==="configuration")options.configuration_identity="b".repeat(64);
  if(variant==="prepared-extra")p.sdk_options={apiKey:"SYNTHETIC_PRIVATE"};
  if(variant==="options-extra")options.sdk_options={apiKey:"SYNTHETIC_PRIVATE"};
  if(variant==="base-header")p.base_model.headers={authorization:"SYNTHETIC_PRIVATE"};
  if(variant==="sdk-header")p.sdk_model.headers={authorization:"SYNTHETIC_PRIVATE"};
  rejects(options);
});
for(const variant of ["tokens-bool","tokens-output-over","tokens-input-zero","cost-infinite","policy-null","sdk-null","base-null","model-identity-type","configuration-type"])test(`invalid data ${variant}`,()=>{
  const options=structuredClone(fixture());const p=options.prepared;
  if(variant==="tokens-bool")p.request_policy.input_tokens=true;
  if(variant==="tokens-output-over")p.request_policy.output_tokens=4097;
  if(variant==="tokens-input-zero")p.request_policy.input_tokens=0;
  if(variant==="cost-infinite")p.base_model.cost.input=Infinity;
  if(variant==="policy-null")p.request_policy=null;
  if(variant==="sdk-null")p.sdk_model=null;
  if(variant==="base-null")p.base_model=null;
  if(variant==="model-identity-type")p.model_identity=true;
  if(variant==="configuration-type")options.configuration_identity=true;
  rejects(options);
});
test("canonical insertion order preserves contract without mutating caller",()=>{
  function reverse(value){if(Array.isArray(value))return value.map(reverse);if(value&&typeof value==="object")return Object.fromEntries(Object.entries(value).reverse().map(([k,v])=>[k,reverse(v)]));return value;}
  const original=fixture(),options=reverse(original),before=structuredClone(options),result=compileSharedReviewSdkContract(options);
  assert.deepEqual(result,compileSharedReviewSdkContract(original));assert.deepEqual(options,before);
});
test("exact frozen output and independent deep clone",()=>{
  const options=structuredClone(fixture()),result=compileSharedReviewSdkContract(options);
  function check(value){if(value&&typeof value==="object"){assert.equal(Object.isFrozen(value),true);for(const child of Object.values(value))check(child);}}
  check(result);assert.deepEqual(Object.keys(result).sort(),["model_identity","sdk_model","sdk_options","wire_contract"]);
  options.prepared.sdk_model.input.pop();options.prepared.sdk_model.compat.thinkingFormat="changed";
  assert.deepEqual(result.sdk_model.input,["text","image"]);assert.equal(result.sdk_model.compat.thinkingFormat,"deepseek");
  assert.throws(()=>{result.sdk_options.reasoning="high";});assert.throws(()=>{result.sdk_model.input.push("image");});
});
for(const location of ["options","prepared","base","sdk","policy","route","cost","compat","map","input"])test(`own data only, getter/Proxy ${location} untouched`,()=>{
  let called=0;
  for(const proxy of [true,false]){
    const options=structuredClone(fixture());let target,key,set;
    if(location==="options"){target=options;key="prepared";set=value=>value;}
    if(location==="prepared"){target=options.prepared;key="model_identity";set=value=>{options.prepared=value;return options;};}
    if(location==="base"){target=options.prepared.base_model;key="name";set=value=>{options.prepared.base_model=value;return options;};}
    if(location==="sdk"){target=options.prepared.sdk_model;key="name";set=value=>{options.prepared.sdk_model=value;return options;};}
    if(location==="policy"){target=options.prepared.request_policy;key="output_tokens";set=value=>{options.prepared.request_policy=value;return options;};}
    if(location==="route"){target=options.route;key="api";set=value=>{options.route=value;return options;};}
    if(location==="cost"){target=options.prepared.base_model.cost;key="input";set=value=>{options.prepared.base_model.cost=value;return options;};}
    if(location==="compat"){target=options.prepared.sdk_model.compat;key="supportsStore";set=value=>{options.prepared.sdk_model.compat=value;return options;};}
    if(location==="map"){target=options.prepared.base_model.thinkingLevelMap;key="medium";set=value=>{options.prepared.base_model.thinkingLevelMap=value;return options;};}
    if(location==="input"){target=options.prepared.sdk_model.input;key="0";set=value=>{options.prepared.sdk_model.input=value;return options;};}
    let value=target;
    if(proxy)value=new Proxy(target,{get(){called++;throw Error("SYNTHETIC_PRIVATE");},getPrototypeOf(){called++;throw Error("SYNTHETIC_PRIVATE");},ownKeys(){called++;throw Error("SYNTHETIC_PRIVATE");}});
    else Object.defineProperty(target,key,{enumerable:true,get(){called++;throw Error("SYNTHETIC_PRIVATE");}});
    rejects(set(value));
  }
  assert.equal(called,0);
});
for(const variant of ["symbol","inherited","nonenumerable","hole","array-method","depth","nodes","bytes","cycle","async","function","surrogate"])test(`bounded copying rejects ${variant}`,()=>{
  const options=structuredClone(fixture());const p=options.prepared;
  if(variant==="symbol")p[Symbol("private")]=1;
  if(variant==="inherited")options.prepared=Object.assign(Object.create({private:"secret"}),p);
  if(variant==="nonenumerable")Object.defineProperty(p,"model_identity",{value:p.model_identity,enumerable:false});
  if(variant==="hole")delete p.sdk_model.input[0];
  if(variant==="array-method")Object.defineProperty(p.sdk_model.input,"map",{get(){throw Error("SYNTHETIC_PRIVATE");}});
  if(variant==="depth"){let value={};p.extra=value;for(let i=0;i<9;i++)value=value.child={};}
  if(variant==="nodes")p.extra=Array(128).fill(null);
  if(variant==="bytes")p.extra=Array(9).fill("x".repeat(32768));
  if(variant==="cycle")p.extra=p;
  if(variant==="async")p.sdk_model=Promise.resolve({});
  if(variant==="function")p.sdk_model=()=>{throw Error("SYNTHETIC_PRIVATE");};
  if(variant==="surrogate")p.sdk_model.name="bad\ud800";
  rejects(options);
});
test("maximum generated thinking map remains bounded and unchanged",()=>{
  const options=rebuild(fixture(),base=>{base.thinkingLevelMap={off:"off",minimal:"low",low:"low",medium:"high",high:"high",xhigh:"high",max:"high"};});
  const result=compileSharedReviewSdkContract(options);assert.deepEqual(result.sdk_model.thinkingLevelMap,options.prepared.base_model.thinkingLevelMap);
});
