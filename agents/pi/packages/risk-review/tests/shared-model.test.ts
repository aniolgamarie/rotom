import test from "node:test";
import assert from "node:assert/strict";
import { prepareSharedReviewModel } from "../src/shared-model.ts";
function fixture() {
  return {descriptor:{id:"deepseek-flash",provider:"agentcfg-deepseek",api:"openai-completions",name:"DeepSeek Flash",baseUrl:"https://api.deepseek.com",reasoning:true,input:["text","image"],
    cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:1000000,maxTokens:384000,
    compat:{requiresReasoningContentOnAssistantMessages:true,thinkingFormat:"deepseek"},thinkingLevelMap:{off:null,minimal:"low",low:"low",medium:"high",high:"high",xhigh:"high",max:"high"}},
    route:{logical_provider:"deepseek",native_route:"agentcfg-deepseek",model_id:"deepseek-flash",auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url:"https://api.deepseek.com"},
    configuration_identity:"a".repeat(64),token_limits:{input_tokens:12000,output_tokens:2048}};
}
test("actual-style safe baseline preserved with explicit review request policy",()=>{
  const options=fixture(),before=structuredClone(options),result=prepareSharedReviewModel(options);
  assert.deepEqual(result.base_model,before.descriptor);
  assert.deepEqual(result.sdk_model,{...before.descriptor,compat:{...before.descriptor.compat,supportsStore:false,supportsDeveloperRole:false,supportsUsageInStreaming:true,maxTokensField:"max_tokens"}});
  assert.deepEqual(result.request_policy,{schema_version:1,purpose:"risk-review",input_mode:"single-text",reasoning_mode:"off",max_retries:0,temperature:0,stream:true,include_usage:true,input_tokens:12000,output_tokens:2048});
  assert.deepEqual(options,before);assert.match(result.model_identity,/^[a-f0-9]{64}$/);
});
function rejects(options,code="PI_RISK_REVIEW_MODEL_INVALID") {
  assert.throws(()=>prepareSharedReviewModel(options),error=>error.code===code&&error.message===code&&!error.cause&&!error.message.includes("SYNTHETIC_PRIVATE"));
}
for(const field of ["descriptor","route","configuration_identity","token_limits"])test(`missing required ${field} never supplies defaults`,()=>{
  const options=fixture();delete options[field];rejects(options);
});
for(const field of ["id","provider","api","name","baseUrl","reasoning","input","cost","contextWindow","maxTokens"])test(`descriptor missing ${field}`,()=>{
  const options=fixture();delete options.descriptor[field];rejects(options);
});
for(const field of ["headers","apiKey","token","credential_ref","providerOptions","type"])test(`unknown secret descriptor ${field}`,()=>{
  const options=fixture();options.descriptor[field]="SYNTHETIC_PRIVATE";rejects(options);
});
for(const [field,value] of [["contextWindow",true],["contextWindow",0],["contextWindow",10000001],["contextWindow",1.5],
  ["maxTokens",false],["maxTokens",1000001],["reasoning",1],["name","bad\nname"],["name","bad\ud800"],
  ["input",["image"]],["input",["text","text"]],["input",["text","audio"]],["input",[]]])test(`invalid descriptor ${field}/${JSON.stringify(value)}`,()=>{
    const options=fixture();options.descriptor[field]=value;rejects(options);
});
for(const value of [true,NaN,Infinity,-1,1000001,"1"])test(`invalid SDK cost ${String(value)}`,()=>{
  const options=fixture();options.descriptor.cost.input=value;rejects(options);
});
test("SDK descriptor cost does not become authority pricing",()=>{
  const options=fixture();options.descriptor.cost={input:0.75,output:1.125,cacheRead:0,cacheWrite:4};
  const result=prepareSharedReviewModel(options);assert.deepEqual(result.base_model.cost,options.descriptor.cost);
  assert.equal(Object.hasOwn(result,"pricing"),false);
});
for(const value of ["http://api.deepseek.com","https://user:pass@api.deepseek.com","https://api.deepseek.com?secret=private",
  "https://api.deepseek.com#private","https://api.deepseek.com/$secret","https://api.deepseek.com\\private",
  "https://api.deepseek.com\n", "https://api.deepseek.com:","https://api.deepseek.com:0","https://api.deepseek.com:65536"])test(`strict endpoint ${JSON.stringify(value)}`,()=>{
  const options=fixture();options.descriptor.baseUrl=options.route.base_url=value;rejects(options);
});
for(const [field,value] of [["native_route","other"],["model_id","other"],["base_url","https://other.invalid"],
  ["logical_provider","bad id"],["owner",""],["api",true]])test(`route mismatch/shape ${field}`,()=>{
  const options=fixture();options.route[field]=value;rejects(options);
});
for(const [auth,api,owner] of [["oauth","openai-completions","pi-native"],["api-key","openai-responses","pi-environment"],["api-key","openai-codex-responses","pi-environment"],["api-key","openai-completions","other-owner"]])test(`unsupported route ${auth}/${api}/${owner}`,()=>{
  const options=fixture();Object.assign(options.route,{auth_kind:auth,api,owner});options.descriptor.api=api;
  rejects(options,"PI_RISK_REVIEW_MODEL_UNSUPPORTED");
});
for(const [key,value] of [["supportsStore",false],["supportsReasoningEffort",true],["thinkingFormat","openai"]])test(`unadapted native compat ${key}`,()=>{
  const options=fixture();options.descriptor.compat[key]=value;rejects(options,"PI_RISK_REVIEW_MODEL_UNSUPPORTED");
});
for(const [field,value] of [["input_tokens",true],["input_tokens",0],["input_tokens",10000001],["output_tokens",false],["output_tokens",0],["output_tokens",4097],["output_tokens",1.5]])test(`invalid request cap ${field}/${value}`,()=>{
  const options=fixture();options.token_limits[field]=value;rejects(options);
});
test("request caps cannot exceed context or actual model cap and never clamp",()=>{
  const context=fixture();context.descriptor.contextWindow=384000;context.token_limits.input_tokens=384000;rejects(context);
  const output=fixture();output.descriptor.maxTokens=100;rejects(output);
  assert.equal(output.token_limits.output_tokens,2048);
});
for(const value of ["A".repeat(64),"a".repeat(63),true,null])test(`configuration identity rejects ${typeof value}/${String(value).length}`,()=>{
  const options=fixture();options.configuration_identity=value;rejects(options);
});
test("every returned level deeply frozen and caller not aliased",()=>{
  const options=fixture(),result=prepareSharedReviewModel(options);
  function check(value){if(value&&typeof value==="object"){assert.equal(Object.isFrozen(value),true);for(const child of Object.values(value))check(child);}}
  check(result);assert.deepEqual(Object.keys(result).sort(),["base_model","model_identity","request_policy","sdk_model"]);
  assert.notEqual(result.base_model,options.descriptor);assert.notEqual(result.base_model.input,options.descriptor.input);
  options.descriptor.input.pop();options.descriptor.cost.input=999;options.descriptor.thinkingLevelMap.off="changed";
  assert.deepEqual(result.base_model.input,["text","image"]);assert.equal(result.base_model.cost.input,0);assert.equal(result.base_model.thinkingLevelMap.off,null);
  assert.throws(()=>{result.base_model.input.push("image");});assert.throws(()=>{result.sdk_model.reasoning=false;});
});
test("absent optional compat/map remain absent baseline, only SDK fixed compat added",()=>{
  const options=fixture();delete options.descriptor.compat;delete options.descriptor.thinkingLevelMap;
  const result=prepareSharedReviewModel(options);
  assert.deepEqual(result.base_model,options.descriptor);
  assert.deepEqual(result.sdk_model.compat,{supportsStore:false,supportsDeveloperRole:false,supportsUsageInStreaming:true,maxTokensField:"max_tokens"});
  assert.equal(Object.hasOwn(result.sdk_model,"thinkingLevelMap"),false);
});
test("canonical identity insensitive to object insertion ordering",()=>{
  const options=fixture(),ordered=Object.fromEntries(Object.entries(options).reverse());
  ordered.descriptor=Object.fromEntries(Object.entries(options.descriptor).reverse());ordered.descriptor.cost=Object.fromEntries(Object.entries(options.descriptor.cost).reverse());
  ordered.route=Object.fromEntries(Object.entries(options.route).reverse());
  assert.equal(prepareSharedReviewModel(options).model_identity,prepareSharedReviewModel(ordered).model_identity);
});
for(const variant of ["configuration","name","reasoning","input","cost","caps","map","compat","request","route"])test(`nonsecret identity binds ${variant}`,()=>{
  const options=fixture(),original=prepareSharedReviewModel(options).model_identity;
  if(variant==="configuration")options.configuration_identity="b".repeat(64);
  if(variant==="name")options.descriptor.name="Real different display name";
  if(variant==="reasoning")options.descriptor.reasoning=false;
  if(variant==="input")options.descriptor.input=["text"];
  if(variant==="cost")options.descriptor.cost.input=0.1;
  if(variant==="caps")options.descriptor.maxTokens=100000;
  if(variant==="map")options.descriptor.thinkingLevelMap.medium="medium";
  if(variant==="compat")options.descriptor.compat.requiresReasoningContentOnAssistantMessages=false;
  if(variant==="request")options.token_limits.output_tokens=1000;
  if(variant==="route")options.route.logical_provider="other-logical";
  assert.notEqual(prepareSharedReviewModel(options).model_identity,original);
});
for(const level of ["unknown","max"])test(`closed thinking map invalid ${level}`,()=>{
  const options=fixture();options.descriptor.thinkingLevelMap[level]=level==="unknown"?"high":true;rejects(options);
});
test("oversize thinking text and unknown nested cost rejected",()=>{
  const options=fixture();options.descriptor.thinkingLevelMap.off="x".repeat(4097);rejects(options);
  const cost=fixture();cost.descriptor.cost.secret="SYNTHETIC_PRIVATE";rejects(cost);
});
for(const location of ["options","descriptor","route","tokens","cost","compat","map","input"])test(`getter/proxy ${location} never invoked`,()=>{
  let invoked=0;const trap={get(){invoked++;throw Error("SYNTHETIC_PRIVATE");},getPrototypeOf(){invoked++;throw Error("SYNTHETIC_PRIVATE");},ownKeys(){invoked++;throw Error("SYNTHETIC_PRIVATE");}};
  for(const proxy of [true,false]) {
    const options=fixture();let value,target,key;
    if(location==="options"){target=options;key="descriptor";value=target;}
    if(location==="descriptor"){target=options.descriptor;key="name";value=target;}
    if(location==="route"){target=options.route;key="api";value=target;}
    if(location==="tokens"){target=options.token_limits;key="output_tokens";value=target;}
    if(location==="cost"){target=options.descriptor.cost;key="input";value=target;}
    if(location==="compat"){target=options.descriptor.compat;key="thinkingFormat";value=target;}
    if(location==="map"){target=options.descriptor.thinkingLevelMap;key="off";value=target;}
    if(location==="input"){target=options.descriptor.input;key="0";value=target;}
    if(proxy)value=new Proxy(target,trap);else Object.defineProperty(target,key,{enumerable:true,get(){invoked++;throw Error("SYNTHETIC_PRIVATE");}});
    if(location==="options"){rejects(value);continue;}
    if(location==="descriptor")options.descriptor=value;
    if(location==="route")options.route=value;
    if(location==="tokens")options.token_limits=value;
    if(location==="cost")options.descriptor.cost=value;
    if(location==="compat")options.descriptor.compat=value;
    if(location==="map")options.descriptor.thinkingLevelMap=value;
    if(location==="input")options.descriptor.input=value;
    rejects(options);
  }
  assert.equal(invoked,0);
});
test("symbols/custom prototypes/array species/holes rejected without coercion",()=>{
  const symbol=fixture();symbol.descriptor[Symbol("secret")]=1;rejects(symbol);
  const derived=fixture();derived.descriptor=Object.assign(Object.create({inherited:"private"}),derived.descriptor);rejects(derived);
  const hole=fixture();delete hole.descriptor.input[0];rejects(hole);
  let called=0;const species=fixture();Object.defineProperty(species.descriptor.input,"constructor",{get(){called++;throw Error("private");}});rejects(species);assert.equal(called,0);
});
for(const invalid of ["tokens","route"])test(`invalid shape precedes unsupported compat ${invalid}`,()=>{
  const options=fixture();options.descriptor.compat.supportsStore=false;
  if(invalid==="tokens")options.token_limits.input_tokens=true;else options.route.owner=true;
  rejects(options);
});
test("invalid known compat type cannot be hidden by unsupported extra",()=>{
  const options=fixture();options.descriptor.compat.supportsStore=false;options.descriptor.compat.requiresReasoningContentOnAssistantMessages=1;rejects(options);
});
