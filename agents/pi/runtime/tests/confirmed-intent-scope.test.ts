// 私有ALS因果测试，不加载SDK/宿主，也不证明产品持久allocator。
import assert from "node:assert/strict";
import { AsyncResource } from "node:async_hooks";
import { test as nativeTest } from "node:test";
import { createConfirmedIntentScope } from "../confirmed-intent-scope.ts";
const test=(name,fn)=>nativeTest(name,{timeout:2000},fn);
const code="PI_CONFIRMED_INTENT_SCOPE_INVALID";
const defer=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return{promise,resolve,reject};};
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(changes={}) {
  const current={profile:"pi-full",session_id:"session",cwd:"/project",runtime_identity:"a".repeat(64),config_identity:"b".repeat(64),policy_generation:1,cancel_epoch:0};
  const clock={wall:1000,mono:100};const calls={confirm:0,intent:0,request:0,submit:0};let control;
  const ctx={hasUI:true,cwd:"/project",isIdle:()=>true,hasPendingMessages:()=>false,sessionManager:{getSessionId:()=>current.session_id},ui:{confirm:async(...args)=>{calls.confirm++;calls.dialog=args;return true;}}};
  const config={enabled:true,current:()=>({...current}),allocateIntent:async()=>{calls.intent++;return{session_scope:"1".repeat(32),intent_ref:"2".repeat(32)};},allocateRequest:value=>{calls.request++;calls.requestArgs=value;return"3".repeat(32);},
    submit:async objective=>{calls.submit++;control.onInput({type:"input",source:"extension",text:objective});control.onAgentStart();await Promise.resolve();calls.binding=control.bindingForTool("sdk-tool");control.onAgentSettled();},
    confirmationMessage:"Confirm this objective",now:()=>clock.wall,monotonic:()=>clock.mono,confirmTimeoutMs:500,scopeTimeoutMs:1000,maxRequests:10,...changes};
  control=createConfirmedIntentScope(config);return{control,ctx,config,current,clock,calls};
}
test("confirmed exact original input/start/tools/settled produces one closed scope",async()=>{
  const f=fixture(),objective="private objective\n中文\t\"x\"";assert.equal(f.control.bindingForTool("outside"),null);
  const result=await f.control.run(objective,f.ctx);assert.deepEqual(result,{status:"settled",code:null});
  assert.equal(f.calls.confirm,1);assert.equal(f.calls.intent,1);assert.equal(f.calls.submit,1);
  assert.equal(f.calls.dialog.join(" ").includes(JSON.stringify(objective)),true);
  assert.deepEqual(f.calls.binding,{session_scope:"1".repeat(32),intent_ref:"2".repeat(32),request_ref:"3".repeat(32)});assert.ok(Object.isFrozen(f.calls.binding));
  assert.deepEqual(Object.keys(result).sort(),["code","status"]);assert.equal(JSON.stringify(result).includes(objective),false);assert.equal(f.control.bindingForTool("sdk-tool"),null);
});
for(const which of ["base","off","noUI","busy","queued"])test("zero-submit path "+which,async()=>{
  const f=fixture(which==="off"?{enabled:false}:{});
  if(which==="base")f.current.profile="pi-base";if(which==="noUI")f.ctx.hasUI=false;if(which==="busy")f.ctx.isIdle=()=>false;if(which==="queued")f.ctx.hasPendingMessages=()=>true;
  const r=await f.control.run("objective",f.ctx);assert.notEqual(r.status,"settled");assert.equal(f.calls.confirm,0);assert.equal(f.calls.intent,0);assert.equal(f.calls.submit,0);
});
for(const value of [false,undefined,1,"yes",{}])test("confirmation must exact true "+typeof value,async()=>{
  const f=fixture();f.ctx.ui.confirm=async()=>value;const r=await f.control.run("objective",f.ctx);assert.equal(r.status,"declined");assert.equal(f.calls.intent,0);assert.equal(f.calls.submit,0);
});
for(const objective of ["", "\0", "\ud800", "x".repeat(16385), "中".repeat(6000), 1, new String("x")])test("invalid objective remains private "+typeof objective,async()=>{
  const f=fixture();const r=await f.control.run(objective,f.ctx);assert.equal(r.status,"failed");assert.equal(r.code,code);assert.equal(f.calls.confirm,0);
});
test("external input while confirmation pending prevents late allocation",async()=>{
  const gate=defer(),f=fixture();f.ctx.ui.confirm=()=>{f.calls.confirm++;return gate.promise;};const pending=f.control.run("objective",f.ctx);await tick();
  f.control.onInput({type:"input",source:"interactive",text:"external"});gate.resolve(true);assert.equal((await pending).status,"retired");assert.equal(f.calls.intent,0);
});
test("unrelated start during confirmation prevents late true",async()=>{
  const gate=defer(),f=fixture();f.ctx.ui.confirm=()=>gate.promise;const p=f.control.run("objective",f.ctx);f.control.onAgentStart();gate.resolve(true);
  assert.equal((await p).status,"retired");assert.equal(f.calls.intent,0);
});
test("confirmation timeout returns before late UI answer and does not allocate",async()=>{
  const gate=defer(),f=fixture({confirmTimeoutMs:5});f.ctx.ui.confirm=()=>gate.promise;const p=f.control.run("objective",f.ctx);const r=await p;
  assert.equal(r.status,"retired");gate.resolve(true);await tick();assert.equal(f.calls.intent,0);assert.equal(f.calls.submit,0);
});
test("invalidate while durable allocator pending cannot revive late reply",async()=>{
  const gate=defer(),f=fixture({allocateIntent:()=>gate.promise});const p=f.control.run("objective",f.ctx);await tick();f.control.invalidate();gate.resolve({session_scope:"1".repeat(32),intent_ref:"2".repeat(32)});
  assert.equal((await p).status,"retired");assert.equal(f.calls.submit,0);
});
for(const field of ["session_id","cwd","config_identity","runtime_identity","cancel_epoch","policy_generation"])test("current "+field+" changes after confirmation before submit",async()=>{
  const f=fixture();f.ctx.ui.confirm=async()=>{f.current[field]=typeof f.current[field]==="number"?f.current[field]+1:field==="cwd"?"/other":field==="session_id"?"other":"f".repeat(64);return true;};
  const r=await f.control.run("objective",f.ctx);assert.equal(r.status,"retired");assert.equal(f.calls.intent,0);assert.equal(f.calls.submit,0);
});
test("context becomes busy or queued after allocate prevents submit",async()=>{
  for(const change of ["busy","queue"]){const f=fixture({allocateIntent:async()=>{if(change==="busy")f.ctx.isIdle=()=>false;else f.ctx.hasPendingMessages=()=>true;return{session_scope:"1".repeat(32),intent_ref:"2".repeat(32)};}});
    assert.equal((await f.control.run("objective",f.ctx)).status,"retired");assert.equal(f.calls.submit,0);}
});
test("submit Promise resolves before start: not-started; late inherited timer has no authority",async()=>{
  let late;const f=fixture({submit:async objective=>{late=()=>{f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();return f.control.bindingForTool("late");};queueMicrotask(()=>{});}});
  const r=await f.control.run("objective",f.ctx);assert.equal(r.status,"not-started");assert.equal(late(),null);
});
test("void submit never reports started success despite synchronous events",async()=>{
  const f=fixture({submit:objective=>{f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();f.control.onAgentSettled();}});
  const r=await f.control.run("objective",f.ctx);assert.equal(r.status,"failed");assert.equal(r.code,code);
});
test("start without original settle is retired when Promise exits",async()=>{
  const f=fixture({submit:async objective=>{f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();await Promise.resolve();}});
  assert.equal((await f.control.run("objective",f.ctx)).status,"retired");
});
for(const event of ["duplicate-input","duplicate-start","foreign-source","images","streaming","unknown","getter","unrelated-settled"])test("invalid causal event "+event+" cannot bind",async()=>{
  let after;let trap=0;const outside=new AsyncResource("outside-scope");const f=fixture({submit:async objective=>{
    f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();await Promise.resolve();assert.notEqual(f.control.bindingForTool("first"),null);
    if(event==="duplicate-start")f.control.onAgentStart();
    else if(event==="unrelated-settled"){outside.runInAsyncScope(()=>f.control.onAgentSettled());await tick();}
    else{const next={type:"input",source:"extension",text:objective};if(event==="foreign-source")next.source="interactive";if(event==="images")next.images=[{}];if(event==="streaming")next.streamingBehavior="followUp";if(event==="unknown")next.extra="PRIVATE";if(event==="getter")Object.defineProperty(next,"text",{get(){trap++;throw Error("PRIVATE");},enumerable:true});f.control.onInput(next);}
    after=f.control.bindingForTool("second");f.control.onAgentSettled();}});
  assert.equal((await f.control.run("objective",f.ctx)).status,"retired");assert.equal(after,null);assert.equal(trap,0);
});
test("memoized tool ID calls trusted durable allocator once and emits no tool ID",async()=>{
  let bindings;const f=fixture({submit:async objective=>{f.control.onInput({type:"input",source:"extension",text:objective,images:[],streamingBehavior:undefined});f.control.onAgentStart();await Promise.resolve();bindings=[f.control.bindingForTool("call"),f.control.bindingForTool("call")];f.control.onAgentSettled();}});
  assert.equal((await f.control.run("objective",f.ctx)).status,"settled");assert.deepEqual(bindings[0],bindings[1]);assert.equal(f.calls.request,1);assert.deepEqual(f.calls.requestArgs,{session_scope:"1".repeat(32),intent_ref:"2".repeat(32),tool_call_id:"call"});
});
test("capacity retires without evicting/reminting tool refs",async()=>{
  const f=fixture({maxRequests:1,submit:async objective=>{f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();await Promise.resolve();assert.notEqual(f.control.bindingForTool("one"),null);assert.equal(f.control.bindingForTool("two"),null);assert.equal(f.control.bindingForTool("one"),null);f.control.onAgentSettled();}});
  assert.equal((await f.control.run("objective",f.ctx)).status,"retired");assert.equal(f.calls.request,1);
});
for(const badId of ["","x".repeat(513),"中".repeat(200),"x\n","\ud800","x\u200b"])test("invalid tool ID never allocates "+badId.length,async()=>{
  const f=fixture({submit:async objective=>{f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();await Promise.resolve();assert.equal(f.control.bindingForTool(badId),null);f.control.onAgentSettled();}});
  await f.control.run("objective",f.ctx);assert.equal(f.calls.request,0);
});
test("dual wall/monotonic expiry and current cancellation invalidate running tools",async()=>{
  for(const kind of ["wall","mono","cancel","backwards"]){const f=fixture({scopeTimeoutMs:50,submit:async objective=>{
    f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();await Promise.resolve();assert.notEqual(f.control.bindingForTool("first"),null);
    if(kind==="wall")f.clock.wall+=50;else if(kind==="mono")f.clock.mono+=50;else if(kind==="cancel")f.current.cancel_epoch++;else f.clock.wall--;
    assert.equal(f.control.bindingForTool("after"),null);f.control.onAgentSettled();}});assert.equal((await f.control.run("objective",f.ctx)).status,"retired");}
});
test("busy latch stays until actual submit Promise exits even after invalidate",async()=>{
  const gate=defer(),f=fixture({submit:()=>gate.promise});const p=f.control.run("first",f.ctx);await tick();f.control.invalidate();
  assert.deepEqual(await f.control.run("second",f.ctx),{status:"busy",code:null});assert.equal(f.calls.confirm,1);gate.resolve();assert.equal((await p).status,"not-started");
  f.config.submit;f.control.retire();assert.equal((await f.control.run("third",f.ctx)).status,"retired");
});
for(const fault of ["intent-error","intent-shape","request-error","request-shape","confirm-error","submit-error"])test("trusted callback faults "+fault+" fixed private result",async()=>{
  const f=fixture();if(fault==="confirm-error")f.ctx.ui.confirm=async()=>{throw Error("PRIVATE");};
  // constructor captures trusted callbacks; create a fresh owned controller for allocator/submit variants。
  const changes={};if(fault==="intent-error")changes.allocateIntent=async()=>{throw Error("PRIVATE");};if(fault==="intent-shape")changes.allocateIntent=async()=>({session_scope:"x",intent_ref:"y"});
  if(fault==="request-error")changes.allocateRequest=()=>{throw Error("PRIVATE");};if(fault==="request-shape")changes.allocateRequest=()=>true;
  if(fault==="submit-error")changes.submit=async()=>{throw Error("PRIVATE");};
  const g=Object.keys(changes).length?fixture(changes):f;const r=await g.control.run("objective",g.ctx);assert.equal(r.status,"failed");assert.equal(r.code,code);assert.equal(JSON.stringify(r).includes("PRIVATE"),false);
});
test("late ALS async chain after original settled cannot revive binding",async()=>{
  const gate=defer();let late;const f=fixture({submit:async objective=>{f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();late=gate.promise.then(()=>f.control.bindingForTool("late"));f.control.onAgentSettled();}});
  assert.equal((await f.control.run("objective",f.ctx)).status,"settled");gate.resolve();assert.equal(await late,null);
});
for (const change of [{extra:true},{enabled:1},{now:null},{monotonic:1},{confirmTimeoutMs:60001},{confirmTimeoutMs:0},{scopeTimeoutMs:300001},{maxRequests:4097},{maxRequests:1.5},{confirmationMessage:"\ud800"},{submit:undefined}]) test("closed constructor rejects "+Object.keys(change).join(),()=>{
  const f=fixture();assert.throws(()=>createConfirmedIntentScope({...f.config,...change}),e=>e.code===code&&e.message===code);
});
test("constructor getter and Proxy fail before traps",()=>{
  const f=fixture();let traps=0;const getter={...f.config};Object.defineProperty(getter,"enabled",{get(){traps++;return true;}});
  assert.throws(()=>createConfirmedIntentScope(getter));assert.throws(()=>createConfirmedIntentScope(new Proxy(f.config,{ownKeys(){traps++;return[];}})));assert.equal(traps,0);
});
for (const change of [{extra:true},{policy_generation:true},{cancel_epoch:-1},{cwd:"/project/.."},{cwd:"/project/"},{session_id:"a\n"},{runtime_identity:{toString(){throw Error("PRIVATE");}}}]) test("strict current fails closed "+Object.keys(change),async()=>{
  const f=fixture();Object.assign(f.current,change);assert.deepEqual(await f.control.run("objective",f.ctx),{status:"failed",code});assert.equal(f.calls.confirm,0);assert.equal(f.calls.intent,0);
});
test("run exit makes inherited timer binding null without early invalidation revival",async()=>{
  const gate=defer();let late;const f=fixture({submit:async objective=>{
    f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();await Promise.resolve();
    late=gate.promise.then(()=>{f.control.onAgentStart();f.control.onAgentSettled();return f.control.bindingForTool("late");});
    f.control.invalidate();f.control.onAgentSettled();
  }});assert.equal((await f.control.run("objective",f.ctx)).status,"retired");gate.resolve();assert.equal(await late,null);
});
test("retire pending confirmation is permanent; late answer cannot allocate",async()=>{
  const gate=defer(),f=fixture();f.ctx.ui.confirm=()=>gate.promise;const p=f.control.run("objective",f.ctx);f.control.retire();assert.equal((await p).status,"retired");gate.resolve(true);await tick();assert.equal(f.calls.intent,0);assert.equal((await f.control.run("other",f.ctx)).status,"retired");
});
test("normal running busy SDK state does not replace causal current checks",async()=>{
  const f=fixture({submit:async objective=>{f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();await Promise.resolve();f.ctx.isIdle=()=>false;assert.notEqual(f.control.bindingForTool("tool"),null);f.control.onAgentSettled();}});
  assert.equal((await f.control.run("objective",f.ctx)).status,"settled");
});
test("void submit cannot allocate a transient binding before its return type is known",async()=>{
  let inside;const f=fixture({submit:objective=>{f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();inside=f.control.bindingForTool("before-return");}});
  const r=await f.control.run("objective",f.ctx);assert.equal(inside,null);assert.equal(f.calls.request,0);assert.deepEqual(r,{status:"failed",code});assert.equal(f.control.bindingForTool("after-return"),null);
});
test("Promise acceptance gate permits only post-return in-marker tool reads",async()=>{
  let before,after;const f=fixture({submit:async objective=>{
    f.control.onInput({type:"input",source:"extension",text:objective});f.control.onAgentStart();before=f.control.bindingForTool("before");
    await Promise.resolve();after=f.control.bindingForTool("after");f.control.onAgentSettled();
  }});assert.equal((await f.control.run("objective",f.ctx)).status,"settled");assert.equal(before,null);assert.notEqual(after,null);assert.equal(f.calls.request,1);
});
test("durable intent allocator must return an actual Promise",async()=>{
  const f=fixture({allocateIntent:()=>({session_scope:"1".repeat(32),intent_ref:"2".repeat(32)})});assert.deepEqual(await f.control.run("objective",f.ctx),{status:"failed",code});assert.equal(f.calls.submit,0);
});
test("request allocator must remain synchronous, no promise reference granted",async()=>{
  const f=fixture({allocateRequest:()=>Promise.resolve("3".repeat(32))});assert.deepEqual(await f.control.run("objective",f.ctx),{status:"failed",code});assert.equal(f.calls.binding,null);
});
test("callback error after reentrant settle cannot convert allocator fault into success",async()=>{
  const f=fixture({allocateRequest:()=>{f.control.onAgentSettled();throw Error("PRIVATE");}});assert.deepEqual(await f.control.run("objective",f.ctx),{status:"failed",code});assert.equal(f.calls.binding,null);
});
test("confirmation timeout aborts the supplied public UI dialog signal", async () => {
  let options, closed = 0;
  const f = fixture({ confirmTimeoutMs: 5 });
  f.ctx.ui.confirm = (_title, _message, value) => {
    options = value;
    return new Promise(resolve => {
      value?.signal?.addEventListener("abort", () => { closed++; resolve(false); }, { once: true });
    });
  };
  assert.equal((await f.control.run("objective", f.ctx)).status, "retired");
  assert.ok(options?.signal instanceof AbortSignal);
  assert.equal(options.timeout, 5);
  assert.equal(options.signal.aborted, true);
  assert.equal(closed, 1);
  assert.equal(f.calls.intent, 0);
  assert.equal(f.calls.submit, 0);
});
test("invalidating a pending UI dialog dismisses it before late approval", async () => {
  let options, closed = 0;
  const f = fixture();
  f.ctx.ui.confirm = (_title, _message, value) => {
    options = value;
    return new Promise(resolve => {
      value?.signal?.addEventListener("abort", () => { closed++; resolve(true); }, { once: true });
    });
  };
  const running = f.control.run("objective", f.ctx);
  f.control.invalidate();
  assert.equal((await running).status, "retired");
  assert.equal(options?.signal?.aborted, true);
  assert.equal(closed, 1);
  assert.equal(f.calls.intent, 0);
});
test("rejected Promise from a synchronous request allocator is observed privately", async () => {
  const f = fixture({ allocateRequest: () => Promise.reject(new Error("SYNTHETIC_ADAPTER_FAILURE")) });
  assert.deepEqual(await f.control.run("objective", f.ctx), { status: "failed", code });
  assert.equal(f.calls.binding, null);
  // Node测试引擎会把未观察拒绝记为失败，等待一轮事件循环使这项错误可观察。
  await tick();
});
