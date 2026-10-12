import assert from "node:assert/strict";
import { test as nodeTest } from "node:test";
const test = (name, body) => nodeTest(name, { timeout: 1500 }, body);
import { createSingleRequestFetch } from "../src/wire-fetch.ts";

const bytes = text => new TextEncoder().encode(text);
const options = overrides => ({ send: async () => new Response("ok"), validate: () => true,
  signal: new AbortController().signal, expired: () => false, ...overrides });
const rejected = async (promise, code) => assert.rejects(promise, error => {
  assert.equal(error.code, code); assert.equal(error.message, code); assert.equal(error.cause, undefined); return true;
});
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; };

test("one send manual redirect, immutable request and frozen closed snapshot", async () => {
  const input = "https://synthetic.invalid/secret", init = { method: "POST", body: "private", redirect: "follow" };
  let calls = 0; const wire = createSingleRequestFetch(options({ validate: (a,b) => a===input && b===init,
    send: async (a,b) => { calls++; assert.equal(a,input); assert.equal(b.redirect,"manual"); assert.equal(b.body,"private"); return new Response("ok"); } }));
  const response = await wire.fetch(input,init); assert.ok(response instanceof Response); assert.equal(await response.text(),"ok");
  assert.equal(init.redirect,"follow"); assert.equal(calls,1);
  assert.deepEqual(wire.snapshot(), { invocations:1,requests:1,response_bytes:2,body_complete:true,redirect_blocked:false,second_request_blocked:false,failure_code:null });
  assert.ok(Object.isFrozen(wire.snapshot()));
  await rejected(wire.fetch(input),"PI_RISK_FETCH_INVALID"); assert.equal(wire.snapshot().second_request_blocked,true);
  assert.equal(wire.snapshot().failure_code,"PI_RISK_FETCH_INVALID");
});
for (const result of [false, undefined, 1, Promise.resolve(true)]) test("validator strict true " + String(result), async () => {
  let sent=0; const wire=createSingleRequestFetch(options({validate:()=>result,send:async()=>{sent++;return new Response();}}));
  await rejected(wire.fetch("secret"),"PI_RISK_FETCH_INVALID"); await rejected(wire.fetch("secret"),"PI_RISK_FETCH_INVALID"); assert.equal(sent,0);
});
test("validator throw is sanitized and consumed", async () => {
  const wire=createSingleRequestFetch(options({validate:()=>{throw new Error("secret");}}));
  await rejected(wire.fetch("secret"),"PI_RISK_FETCH_INVALID"); assert.equal(wire.snapshot().requests,0);
});
test("concurrent second invocation is sticky even after first succeeds", async () => {
  const pending=deferred(); const wire=createSingleRequestFetch(options({send:()=>pending.promise})); const first=wire.fetch("a");
  await rejected(wire.fetch("b"),"PI_RISK_FETCH_INVALID"); pending.resolve(new Response("x"));
  const response=await first; await response.text(); assert.equal(wire.snapshot().requests,1); assert.equal(wire.snapshot().failure_code,"PI_RISK_FETCH_INVALID");
});
for (const status of [301,302,307,400,500]) test("HTTP status rejected and body canceled " + status,async()=>{
  let canceled=0;const body=new ReadableStream({cancel(){canceled++;}});const wire=createSingleRequestFetch(options({send:async()=>new Response(body,{status})}));
  await rejected(wire.fetch("secret"),"PI_RISK_FETCH_FAILED"); assert.equal(canceled,1); assert.equal(wire.snapshot().redirect_blocked,status<400);
});
test("send rejection sanitized",async()=>{const wire=createSingleRequestFetch(options({send:async()=>{throw new Error("token URL");}}));await rejected(wire.fetch("secret"),"PI_RISK_FETCH_FAILED");assert.equal(wire.snapshot().requests,1);});
for (const limit of [0,262145,1.5,true,NaN]) test("invalid response limit " + limit,()=>{assert.throws(()=>createSingleRequestFetch(options({responseLimit:limit})),e=>e.code==="PI_RISK_FETCH_INVALID");});
test("reader pulls only on demand, exact limit accepted",async()=>{
  let pulls=0; const chunks=[bytes("ab"),bytes("cd")]; const wire=createSingleRequestFetch(options({responseLimit:4,send:async()=>new Response(new ReadableStream({pull(c){pulls++;if(chunks.length)c.enqueue(chunks.shift());else c.close();}},{highWaterMark:0}))}));
  const response=await wire.fetch("a"); assert.equal(pulls,0);assert.equal(wire.snapshot().response_bytes,0);assert.equal(await response.text(),"abcd");assert.equal(wire.snapshot().body_complete,true);
});
test("overlimit chunk is never enqueued, reader canceled",async()=>{
  let canceled=0; const chunks=[bytes("ab"),bytes("cde")]; const wire=createSingleRequestFetch(options({responseLimit:4,send:async()=>new Response(new ReadableStream({pull(c){c.enqueue(chunks.shift());},cancel(){canceled++;}},{highWaterMark:0}))}));
  const reader=(await wire.fetch("a")).body.getReader();assert.equal(new TextDecoder().decode((await reader.read()).value),"ab");await rejected(reader.read(),"PI_RISK_FETCH_LIMIT");assert.equal(canceled,1);assert.equal(wire.snapshot().response_bytes,2);assert.equal(wire.snapshot().body_complete,false);
});
test("content length over limit cancels before read",async()=>{let canceled=0;const wire=createSingleRequestFetch(options({responseLimit:2,send:async()=>new Response(new ReadableStream({cancel(){canceled++;}}),{headers:{"Content-Length":"3"}})}));await rejected(wire.fetch("a"),"PI_RISK_FETCH_LIMIT");assert.equal(canceled,1);});
test("wrong chunk type and reader error fail fixed",async()=>{
  for(const source of [{pull(c){c.enqueue("secret");}},{pull(c){c.error(new Error("secret"));}}]) {const wire=createSingleRequestFetch(options({send:async()=>new Response(new ReadableStream(source,{highWaterMark:0}))}));await rejected((await wire.fetch("a")).text(),"PI_RISK_FETCH_FAILED");}
});
test("abort before send is zero, validator-triggered abort is zero",async()=>{
  for(const early of [true,false]){const controller=new AbortController();if(early)controller.abort();const wire=createSingleRequestFetch(options({signal:controller.signal,validate:()=>{controller.abort();return true;}}));await rejected(wire.fetch("a"),"PI_RISK_FETCH_CANCELED");assert.equal(wire.snapshot().requests,0);}
});
test("both SDK and control signals cancel stalled read without awaiting cleanup",async()=>{
  for(const which of ["sdk","control"]){const control=new AbortController(),sdk=new AbortController();let canceled=0;const wire=createSingleRequestFetch(options({signal:control.signal,send:async()=>new Response(new ReadableStream({pull(){return new Promise(()=>{});},cancel(){canceled++;return new Promise(()=>{});}},{highWaterMark:0}))}));const response=await wire.fetch("a",{signal:sdk.signal});const reading=response.text();(which==="sdk"?sdk:control).abort();await rejected(reading,"PI_RISK_FETCH_CANCELED");assert.equal(canceled,1);assert.equal(wire.snapshot().requests,1);}
});
test("ignored send abort does not hang and late body is canceled",async()=>{
  const control=new AbortController(),pending=deferred();let canceled=0;const wire=createSingleRequestFetch(options({signal:control.signal,send:()=>pending.promise}));const fetching=wire.fetch("a");control.abort();await rejected(fetching,"PI_RISK_FETCH_CANCELED");pending.resolve(new Response(new ReadableStream({cancel(){canceled++;}})));await new Promise(r=>setImmediate(r));assert.equal(canceled,1);assert.equal(wire.snapshot().body_complete,false);
});
test("expired stall is canceled and expiry predicate failures fixed",async()=>{
  let expired=false;const wire=createSingleRequestFetch(options({expired:()=>expired,send:()=>new Promise(()=>{})}));const promise=wire.fetch("a");expired=true;await rejected(promise,"PI_RISK_FETCH_CANCELED");
  const broken=createSingleRequestFetch(options({expired:()=>{throw new Error("secret");}}));await rejected(broken.fetch("a"),"PI_RISK_FETCH_INVALID");assert.equal(broken.snapshot().requests,0);
});
test("null body completes without listener residue",async()=>{const control=new AbortController();const wire=createSingleRequestFetch(options({signal:control.signal,send:async()=>new Response(null,{status:204})}));await wire.fetch("a");assert.equal(wire.snapshot().body_complete,true);control.abort();assert.equal(wire.snapshot().failure_code,null);});

test("expiry before validation and after validation keeps zero sends",async()=>{
  for(const early of [true,false]){let expiry=early,validations=0;const wire=createSingleRequestFetch(options({expired:()=>expiry,validate:()=>{validations++;expiry=true;return true;}}));await rejected(wire.fetch("a"),"PI_RISK_FETCH_CANCELED");assert.equal(wire.snapshot().requests,0);assert.equal(validations,early?0:1);}
});
test("SDK already canceled signal does not send",async()=>{const sdk=new AbortController();sdk.abort();const wire=createSingleRequestFetch(options());await rejected(wire.fetch("a",{signal:sdk.signal}),"PI_RISK_FETCH_CANCELED");assert.equal(wire.snapshot().requests,0);});
test("body expiry cancels stalled reader",async()=>{let expiry=false,canceled=0;const wire=createSingleRequestFetch(options({expired:()=>expiry,send:async()=>new Response(new ReadableStream({pull(){return new Promise(()=>{});},cancel(){canceled++;}},{highWaterMark:0}))}));const reading=(await wire.fetch("a")).text();expiry=true;await rejected(reading,"PI_RISK_FETCH_CANCELED");assert.equal(canceled,1);assert.equal(wire.snapshot().response_bytes,0);});
test("actual decoded body bound overrides smaller content length",async()=>{const wire=createSingleRequestFetch(options({responseLimit:2,send:async()=>new Response("long",{headers:{"content-length":"1"}})}));await rejected((await wire.fetch("a")).text(),"PI_RISK_FETCH_LIMIT");assert.equal(wire.snapshot().response_bytes,0);});
test("consumer body cancel is sticky and does not await original cleanup",async()=>{let canceled=0;const wire=createSingleRequestFetch(options({send:async()=>new Response(new ReadableStream({cancel(){canceled++;return new Promise(()=>{});}},{highWaterMark:0}))}));const response=await wire.fetch("secret");await response.body.cancel();assert.equal(canceled,1);assert.equal(wire.snapshot().failure_code,"PI_RISK_FETCH_CANCELED");assert.equal(wire.snapshot().body_complete,false);});
test("metadata snapshot never includes request, response, URL, headers or exception text",async()=>{const wire=createSingleRequestFetch(options({send:async()=>new Response("private-response",{headers:{"secret-header":"private-value"}})}));await (await wire.fetch("https://secret.invalid",{body:"private-request"})).text();const raw=JSON.stringify(wire.snapshot());for(const secret of ["secret","private","https","header","body"]) assert.equal(raw.includes(secret),secret==="body");assert.deepEqual(Object.keys(wire.snapshot()).sort(),["invocations","requests","response_bytes","body_complete","redirect_blocked","second_request_blocked","failure_code"].sort());});
for(const invalid of [null,undefined,{}, {get send(){throw new Error("secret");}}]) test("factory invalid options fixed " + String(invalid),()=>{assert.throws(()=>createSingleRequestFetch(invalid),e=>e.code==="PI_RISK_FETCH_INVALID" && e.message===e.code && e.cause===undefined);});
for(const [name, expiry] of [["undefined",()=>undefined],["number",()=>1],["resolved Promise",()=>Promise.resolve(false)],["rejected Promise",()=>Promise.reject(new Error("secret"))]]) test("expiry strict sync bool " + name,async()=>{const wire=createSingleRequestFetch(options({expired:expiry}));await rejected(wire.fetch("a"),"PI_RISK_FETCH_INVALID");assert.equal(wire.snapshot().requests,0);});
test("successful completion removes both abort listeners and timer",async()=>{const control=new AbortController(),sdk=new AbortController();let probes=0;const wire=createSingleRequestFetch(options({signal:control.signal,expired:()=>{probes++;return false;}}));await (await wire.fetch("a",{signal:sdk.signal})).text();const before=probes;control.abort();sdk.abort();await new Promise(r=>setTimeout(r,125));assert.equal(probes,before);assert.equal(wire.snapshot().failure_code,null);});
test("synchronous send abort cleans timer and late response",async()=>{const control=new AbortController();let canceled=0;const wire=createSingleRequestFetch(options({signal:control.signal,send:()=>{control.abort();return new Response(new ReadableStream({cancel(){canceled++;}}));}}));await rejected(wire.fetch("a"),"PI_RISK_FETCH_CANCELED");await new Promise(r=>setImmediate(r));assert.equal(canceled,1);assert.equal(wire.snapshot().requests,1);});

test("already redirected 200 response is blocked and canceled",async()=>{
  let canceled=0;const response=new Response(new ReadableStream({cancel(){canceled++;}},{highWaterMark:0}));Object.defineProperty(response,"redirected",{value:true});
  const control=new AbortController();const wire=createSingleRequestFetch(options({signal:control.signal,send:async()=>response}));try{await rejected(wire.fetch("a"),"PI_RISK_FETCH_FAILED");}finally{control.abort();}assert.equal(canceled,1);assert.equal(wire.snapshot().redirect_blocked,true);assert.equal(wire.snapshot().response_bytes,0);
});
