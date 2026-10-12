import assert from "node:assert/strict";
import { test as nativeTest } from "node:test";
import { AsyncResource } from "node:async_hooks";
import { createConfirmedIntentScope } from "../confirmed-intent-scope.ts";
const test=(name,fn)=>nativeTest(name,{timeout:2000},fn);
const CODE="PI_CONFIRMED_INTENT_SCOPE_INVALID";
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const tick=()=>new Promise(r=>setImmediate(r));
function fixture({legacy=false,allocate,body=async()=>{},...changes}={}) {
 const current={profile:"pi-full",session_id:"session",cwd:"/project",runtime_identity:"a".repeat(64),config_identity:"b".repeat(64),policy_generation:1,cancel_epoch:0},clock={wall:1000,mono:100},calls=[];let control;
 const ctx={hasUI:true,cwd:"/project",isIdle:()=>true,hasPendingMessages:()=>false,sessionManager:{getSessionId:()=>current.session_id},ui:{confirm:async()=>true}};
 const allocator=value=>{calls.push(value);return allocate?allocate(value):legacy?"3".repeat(32):Promise.resolve("3".repeat(32));};
 const config={enabled:true,current:()=>({...current}),allocateIntent:async()=>({session_scope:"1".repeat(32),intent_ref:"2".repeat(32)}),...(legacy?{allocateRequest:allocator}:{allocateRequestAsync:allocator}),confirmationMessage:"Confirm objective",now:()=>clock.wall,monotonic:()=>clock.mono,confirmTimeoutMs:500,scopeTimeoutMs:1000,maxRequests:10,submit:async objective=>{control.onInput({type:"input",source:"extension",text:objective});control.onAgentStart();await Promise.resolve();await body({control,current,clock,calls});control.onAgentSettled();},...changes};
 control=createConfirmedIntentScope(config);return {control,current,clock,calls,ctx,config,run:()=>control.run("objective",ctx)};
}
test("old synchronous branch cannot deliver an asynchronous durable allocation",async()=>{
 let bound;const f=fixture({legacy:true,allocate:()=>Promise.resolve("3".repeat(32)),body:async({control})=>{bound=control.bindingForTool("call");}});
 assert.equal((await f.run()).status,"failed");assert.equal(bound,null);
});
test("async success memoizes one frozen binding for concurrent same ID",async()=>{
 const gate=defer();let values;const f=fixture({allocate:()=>gate.promise,body:async({control,calls})=>{
  assert.equal(control.bindingForTool("sync"),null);const first=control.bindingForToolAsync("same"),second=control.bindingForToolAsync("same");assert.equal(calls.length,1);assert(Object.isFrozen(calls[0]));gate.resolve("3".repeat(32));values=await Promise.all([first,second]);assert.equal(values[0],values[1]);assert(Object.isFrozen(values[0]));assert.equal(await control.bindingForToolAsync("same"),values[0]);
 }});assert.equal((await f.run()).status,"settled");assert.deepEqual(values[0],{session_scope:"1".repeat(32),intent_ref:"2".repeat(32),request_ref:"3".repeat(32)});assert.equal(f.calls.length,1);assert.equal(await f.control.bindingForToolAsync("same"),null);
});
test("synchronous mode async method is inert",async()=>{const f=fixture({legacy:true,body:async({control,calls})=>{assert.equal(await control.bindingForToolAsync("call"),null);assert.equal(calls.length,0);assert.notEqual(control.bindingForTool("call"),null);}});assert.equal((await f.run()).status,"settled");});
test("distinct and nested IDs have distinct pending slots",async()=>{
 let nested;const gates={outer:defer(),inner:defer()};const f=fixture({allocate:value=>{if(value.tool_call_id==="outer")nested=f.control.bindingForToolAsync("inner");return gates[value.tool_call_id].promise;},body:async({control,calls})=>{const first=control.bindingForToolAsync("outer");assert.equal(calls.length,2);gates.outer.resolve("3".repeat(32));gates.inner.resolve("4".repeat(32));assert.notEqual((await first).request_ref,(await nested).request_ref);}});assert.equal((await f.run()).status,"settled");
});
test("nested same ID occupies one slot before callback returns",async()=>{let nested;const f=fixture({allocate:()=>{nested=f.control.bindingForToolAsync("same");return Promise.resolve("3".repeat(32));},body:async({control,calls})=>{const binding=await control.bindingForToolAsync("same");assert.equal(await nested,binding);assert.equal(calls.length,1);}});assert.equal((await f.run()).status,"settled");});
for(const fault of ["throw","reject","thenable","string","wrong-ref","proxy-promise"])test("invalid async allocator "+fault,async()=>{
 let getter=0;const marker="SYNTHETIC_PRIVATE";const f=fixture({allocate:()=>{if(fault==="throw")throw Error(marker);if(fault==="reject")return Promise.reject(Error(marker));if(fault==="thenable")return {get then(){getter++;throw Error(marker);}};if(fault==="string")return "3".repeat(32);if(fault==="wrong-ref")return Promise.resolve("wrong");return new Proxy(Promise.resolve("3".repeat(32)),{});},body:async({control})=>{assert.equal(await control.bindingForToolAsync("call"),null);assert.equal(await control.bindingForToolAsync("call"),null);}});assert.deepEqual(await f.run(),{status:"failed",code:CODE});assert.equal(getter,0);assert.equal(f.calls.length,1);
});
for(const reason of ["invalidate","retire","settled","input","start","config","epoch","wall","mono","backwards"])test("pending async allocation loses ability on "+reason,async()=>{
 const gate=defer();const f=fixture({allocate:()=>gate.promise,body:async({control,current,clock})=>{
  const pending=control.bindingForToolAsync("call");
  if(reason==="invalidate")control.invalidate();if(reason==="retire")control.retire();if(reason==="settled")control.onAgentSettled();if(reason==="input")control.onInput({type:"input",source:"extension",text:"objective"});if(reason==="start")control.onAgentStart();
  if(reason==="config")current.config_identity="f".repeat(64);if(reason==="epoch")current.cancel_epoch++;if(reason==="wall")clock.wall+=1000;if(reason==="mono")clock.mono+=1000;if(reason==="backwards")clock.wall--;
  if(["config","epoch","wall","mono","backwards"].includes(reason))assert.equal(await control.bindingForToolAsync("probe"),null);
  assert.equal(await pending,null);gate.resolve("3".repeat(32));await tick();assert.equal(await control.bindingForToolAsync("call"),null);
 }});assert.equal((await f.run()).status,reason==="settled"?"settled":"retired");assert.equal(f.calls.length,1);
});
test("never resolving allocation stops promptly and observes late rejection",async()=>{const gate=defer();const f=fixture({allocate:()=>gate.promise,body:async({control})=>{const pending=control.bindingForToolAsync("call");control.invalidate();assert.equal(await pending,null);gate.reject(Error("SYNTHETIC_PRIVATE"));await tick();}});assert.equal((await f.run()).status,"retired");});
test("run exit cancels async waiter without awaiting allocator",async()=>{const gate=defer();let pending;const f=fixture({allocate:()=>gate.promise,body:async({control})=>{pending=control.bindingForToolAsync("call");}});assert.equal((await f.run()).status,"settled");assert.equal(await pending,null);gate.resolve("3".repeat(32));await tick();assert.equal(await f.control.bindingForToolAsync("call"),null);});
test("capacity counts pending plus memo without eviction/retry",async()=>{const gate=defer();const f=fixture({maxRequests:2,allocate:v=>v.tool_call_id==="memo"?Promise.resolve("3".repeat(32)):gate.promise,body:async({control})=>{assert.notEqual(await control.bindingForToolAsync("memo"),null);const wait=control.bindingForToolAsync("pending");assert.equal(await control.bindingForToolAsync("third"),null);assert.equal(await wait,null);assert.equal(await control.bindingForToolAsync("memo"),null);}});assert.equal((await f.run()).status,"retired");assert.equal(f.calls.length,2);});
test("external ALS cannot allocate while original running",async()=>{const outside=new AsyncResource("outside");const f=fixture({body:async({control,calls})=>{assert.equal(await outside.runInAsyncScope(()=>control.bindingForToolAsync("outside")),null);assert.equal(calls.length,0);assert.notEqual(await control.bindingForToolAsync("inside"),null);}});assert.equal((await f.run()).status,"settled");outside.emitDestroy();});
for(const id of ["","x".repeat(513),"x\n","x\u200b","\ud800"])test("invalid async ID allocates zero "+id.length,async()=>{const f=fixture({body:async({control})=>assert.equal(await control.bindingForToolAsync(id),null)});assert.equal((await f.run()).status,"retired");assert.equal(f.calls.length,0);});
for(const fault of ["neither","both","proxy","undefined"])test("constructor exactly one allocator "+fault,()=>{const f=fixture();const cfg={...f.config};delete cfg.allocateRequestAsync;if(fault==="both"){cfg.allocateRequest=()=>"3".repeat(32);cfg.allocateRequestAsync=async()=>"3".repeat(32);}if(fault==="proxy")cfg.allocateRequestAsync=new Proxy(async()=>"3".repeat(32),{apply(){assert.fail("proxy called");}});if(fault==="undefined")cfg.allocateRequestAsync=undefined;assert.throws(()=>createConfirmedIntentScope(cfg),e=>e.code===CODE);});
test("submitAccepted blocks async allocation before actual Promise return",async()=>{let control,early;const f=fixture({submit:objective=>{control.onInput({type:"input",source:"extension",text:objective});control.onAgentStart();early=control.bindingForToolAsync("early");return undefined;}});control=f.control;assert.equal((await f.run()).status,"failed");assert.equal(await early,null);assert.equal(f.calls.length,0);});
for(const id of ["tool call","中文","tool\u00a0call"])test("async persistent Store ASCII ID boundary "+JSON.stringify(id),async()=>{const f=fixture({body:async({control})=>assert.equal(await control.bindingForToolAsync(id),null)});assert.equal((await f.run()).status,"retired");assert.equal(f.calls.length,0);});
test("async nested slash IDs preserve exact allocator input",async()=>{const f=fixture({body:async({control,calls})=>{assert.notEqual(await control.bindingForToolAsync("nested/tool-call:1"),null);assert.equal(calls[0].tool_call_id,"nested/tool-call:1");}});assert.equal((await f.run()).status,"settled");});
