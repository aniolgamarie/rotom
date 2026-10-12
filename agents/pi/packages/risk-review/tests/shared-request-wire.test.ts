import test from "node:test";
import assert from "node:assert/strict";
import { prepareSharedReviewModel } from "../src/shared-model.ts";
import { createSharedReviewRequestValidator } from "../src/shared-request-wire.ts";
function fixture(reasoning=true, systemPrompt="review safely", base_url="https://synthetic.invalid/v1") {
  const route={logical_provider:"synthetic",native_route:"synthetic",model_id:"model",auth_kind:"api-key",owner:"pi-environment",api:"openai-completions",base_url};
  const configuration_identity="a".repeat(64);
  const prepared=prepareSharedReviewModel({route,configuration_identity,token_limits:{input_tokens:100,output_tokens:10},descriptor:{id:"model",provider:"synthetic",api:route.api,name:"Synthetic real name",baseUrl:base_url,reasoning,input:["text","image"],cost:{input:0,output:0,cacheRead:0,cacheWrite:0},contextWindow:1000000,maxTokens:384000,...(reasoning?{compat:{thinkingFormat:"deepseek"}}:{})}});
  return {prepared,route,configuration_identity,systemPrompt,userPrompt:"synthetic objective",expectedHeaders:{authorization:"Bearer SYNTHETIC_KEY",accept:"application/json","content-type":"application/json"}};
}
function body(o, thinking=o.prepared.base_model.reasoning) {
  return {model:"model",messages:[...(o.systemPrompt?[{role:"system",content:o.systemPrompt}]:[]),{role:"user",content:o.userPrompt}],stream:true,stream_options:{include_usage:true},temperature:0,max_tokens:10,...(thinking?{thinking:{type:"disabled"}}:{})};
}
function endpoint(o) {return new URL(o.route.base_url.replace(/\/$/,"")+"/chat/completions").href;}
function init(o, data=body(o)) {return {method:"POST",headers:{...o.expectedHeaders},body:typeof data==="string"?data:JSON.stringify(data)};}
test("explicit DeepSeek disabled wire is accepted",()=>{
  const o=fixture(); const validate=createSharedReviewRequestValidator(o);
  assert.equal(validate(endpoint(o),init(o)),true);
});
const CODE="PI_RISK_REVIEW_SHARED_REQUEST_INVALID";
function rejects(o){assert.throws(()=>createSharedReviewRequestValidator(o),e=>e.code===CODE&&e.message===CODE&&!e.cause);}
for(const reasoning of [true,false])for(const system of ["review safely",""])test(`legal shape reasoning=${reasoning} system=${!!system}`,()=>{
  const o=fixture(reasoning,system),v=createSharedReviewRequestValidator(o);assert.equal(v(endpoint(o),init(o)),true);
  const b=body(o);b.max_tokens=1;assert.equal(v(endpoint(o),init(o,b)),true);
});
for(const thinking of [undefined,null,[],{},"disabled",{type:"enabled"},{type:"disabled",extra:0}])test(`thinking requires exact disabled ${JSON.stringify(thinking)}`,()=>{
  const o=fixture(),b=body(o);if(thinking===undefined)delete b.thinking;else b.thinking=thinking;
  assert.equal(createSharedReviewRequestValidator(o)(endpoint(o),init(o,b)),false);
});
test("nonreasoning does not allow thinking",()=>{const o=fixture(false);assert.equal(createSharedReviewRequestValidator(o)(endpoint(o),init(o,body(o,true))),false);});
for(const branch of ["generic","off-null"])test(`unsupported reasoning ${branch}`,()=>{
  const o=fixture(),base=structuredClone(o.prepared.base_model);if(branch==="generic")delete base.compat;else base.thinkingLevelMap={off:null};
  o.prepared=prepareSharedReviewModel({descriptor:base,route:o.route,configuration_identity:o.configuration_identity,token_limits:{input_tokens:100,output_tokens:10}});rejects(o);
});
for(const [key,tokens]of [["temperature",["-0","0.0","0e0","0.00000000000000000000001"]],["max_tokens",["0","11","1.0","1e0","1.00000000000000001","10.00000000000000001","true"]]])for(const token of tokens)test(`raw numeric ${key} ${token}`,()=>{
  const o=fixture(),raw=JSON.stringify(body(o)).replace(new RegExp('"'+key+'":\\d+'),'"'+key+'":'+token);
  assert.equal(createSharedReviewRequestValidator(o)(endpoint(o),init(o,raw)),false);
});
for(const mutation of ["model","role","prompt","output","tool","effort","store","message-extra","nested-thinking","method","url","signal","header","organization","request-extra"])test(`wire drift ${mutation}`,()=>{
  const o=fixture(),b=body(o),r=init(o);let url=endpoint(o);
  if(mutation==="model")b.model="other";
  if(mutation==="role")b.messages[0].role="developer";
  if(mutation==="prompt")b.messages[1].content="different";
  if(mutation==="output")b.max_tokens=11;
  if(mutation==="tool")b.tools=[];
  if(mutation==="effort")b.reasoning_effort="off";
  if(mutation==="store")b.store=false;
  if(mutation==="message-extra")b.messages[0].extra="ignored?";
  if(mutation==="nested-thinking"){delete b.thinking;b.messages[0].thinking={type:"disabled"};}
  if(mutation==="method")r.method="GET";
  if(mutation==="url")url+="?redirect=1";
  if(mutation==="signal")r.signal={};
  if(mutation==="header")r.headers.authorization="Bearer OTHER";
  if(mutation==="organization")r.headers["openai-organization"]="ambient";
  if(mutation==="request-extra")r.redirect="manual";
  r.body=JSON.stringify(b);assert.equal(createSharedReviewRequestValidator(o)(url,r),false);
});
for(const raw of [
  '{"thinking":{"type":"disabled","type":"disabled"}}',
  '{"thinking":{"type":"disabled","t\\u0079pe":"disabled"}}',
  '{"thinking":{"type":"disabled"},"thinking":{"type":"disabled"}}',
  '{"thinking":{"type":"disabled"},"__proto__":{}}',
  '{"thinking":{"type":"disabled"},"messages":[{"role":"user","role":"user"}]}',
  '{"thinking":{"type":"disabled"},"extra":[[[[[0]]]]]}',
  '{"thinking":{"type":"disabled"},"extra":[0,0,0,0,0,0,0,0,0]}',
  '{"thinking":{"type":"disabled"},"extra":"\\ud800"}',
  '[]','null','NaN','{} trailing',
])test(`malformed closed body ${raw.slice(0,40)}`,()=>{const o=fixture();assert.equal(createSharedReviewRequestValidator(o)(endpoint(o),init(o,raw)),false);});
test("escaped thinking key is the same exact root field",()=>{
 const o=fixture(),raw=JSON.stringify(body(o)).replace('"thinking"','"th\\u0069nking"');assert.equal(createSharedReviewRequestValidator(o)(endpoint(o),init(o,raw)),true);
});
test("raw and decoded Unicode/body byte bounds fail closed",()=>{
 const o=fixture(),v=createSharedReviewRequestValidator(o);
 for(const raw of ["x".repeat(131073),"中".repeat(65536),JSON.stringify(body(o))+"\ud800"])assert.equal(v(endpoint(o),init(o,raw)),false);
 const b=body(o);b.messages[0].content="x".repeat(131073);assert.equal(v(endpoint(o),init(o,b)),false);
});
test("node budget rejects a broad tree",()=>{
 const o=fixture(),b=body(o);b.extra=Array.from({length:8},()=>Array.from({length:8},()=>0));assert.equal(createSharedReviewRequestValidator(o)(endpoint(o),init(o,b)),false);
});
test("endpoint keeps SDK multiple trailing slashes",()=>{
 const o=fixture(true,"","https://synthetic.invalid/v1///"),v=createSharedReviewRequestValidator(o);
 assert.equal(endpoint(o),"https://synthetic.invalid/v1///chat/completions");assert.equal(v(endpoint(o),init(o)),true);
 assert.equal(v("https://synthetic.invalid/v1/chat/completions",init(o)),false);
});
for(const field of ["prepared","route","configuration_identity","systemPrompt","userPrompt","expectedHeaders"])test(`closed config missing ${field}`,()=>{const o=fixture();delete o[field];rejects(o);});
for(const kind of ["getter","proxy","symbol","inherited","extra","null-proto"])test(`config rejects ${kind} without traps`,()=>{
 let calls=0,o=fixture();
 if(kind==="getter")Object.defineProperty(o,"userPrompt",{enumerable:true,get(){calls++;throw Error("SYNTHETIC_PRIVATE");}});
 if(kind==="proxy")o=new Proxy(o,{ownKeys(){calls++;throw Error("SYNTHETIC_PRIVATE");}});
 if(kind==="symbol")o[Symbol("private")]=1;
 if(kind==="inherited")Object.setPrototypeOf(o,{other:1});
 if(kind==="extra")o.secret="SYNTHETIC_PRIVATE";
 if(kind==="null-proto")Object.setPrototypeOf(o,null);
 rejects(o);assert.equal(calls,0);
});
for(const kind of ["init-getter","init-proxy","headers-getter","headers-proxy","body-object"])test(`request rejects ${kind} without traps`,()=>{
 const o=fixture(),v=createSharedReviewRequestValidator(o);let calls=0,r=init(o);
 if(kind==="init-getter")Object.defineProperty(r,"body",{enumerable:true,get(){calls++;throw Error("SYNTHETIC_PRIVATE");}});
 if(kind==="init-proxy")r=new Proxy(r,{ownKeys(){calls++;throw Error("SYNTHETIC_PRIVATE");}});
 if(kind==="headers-getter")Object.defineProperty(r.headers,"authorization",{enumerable:true,get(){calls++;throw Error("SYNTHETIC_PRIVATE");}});
 if(kind==="headers-proxy")r.headers=new Proxy(r.headers,{ownKeys(){calls++;throw Error("SYNTHETIC_PRIVATE");}});
 if(kind==="body-object")r.body={toString(){calls++;throw Error("SYNTHETIC_PRIVATE");}};
 assert.equal(v(endpoint(o),r),false);assert.equal(calls,0);
});
test("captured values cannot drift when caller mutates options",()=>{
 const o=fixture(),original=structuredClone(o),r=init(o),url=endpoint(o),v=createSharedReviewRequestValidator(o);
 o.systemPrompt="changed";o.userPrompt="changed";o.expectedHeaders.authorization="Bearer CHANGED";o.route.base_url="https://other.invalid";
 assert.equal(v(url,r),true);assert.equal(v(endpoint(original),init(o)),false);
 assert.deepEqual(original.prepared,o.prepared);
});
test("constructor errors reveal no synthetic secret or original cause",()=>{
 const o=fixture();o.prepared=structuredClone(o.prepared);o.prepared.sdk_model.headers={Authorization:"SYNTHETIC_PRIVATE"};
 assert.throws(()=>createSharedReviewRequestValidator(o),e=>e.code===CODE&&e.message===CODE&&!e.cause&&!String(e.stack).includes("Bearer SYNTHETIC_PRIVATE"));
});
