// 全fake process lifecycle/IO；绝不spawn、Worker、SDK或网络。
import assert from "node:assert/strict";
import { test as nativeTest } from "node:test";
const test=(name,fn)=>nativeTest(name,{timeout:8000},fn);
import { EventEmitter } from "node:events";
import { createProcessReviewSdk,processJson,processMessage,processWriter } from "../src/sdk-process.ts";
import { encodeReviewFrame,createReviewFrameReader } from "../src/process-frames.ts";
const error="PI_RISK_REVIEW_PROCESS_INVALID";
const bad=fn=>assert.throws(fn,e=>e.code===error&&e.message===error&&!Object.hasOwn(e,'cause'));
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return{promise,resolve};};
function model(){return{api:'openai-completions',provider:'own-provider',id:'own-model',name:'own-model',baseUrl:'https://own.invalid/v1',reasoning:false,input:['text'],cost:{input:0.1,output:0.2,cacheRead:0,cacheWrite:0},contextWindow:32000,maxTokens:1024,compat:{supportsStore:false,supportsDeveloperRole:false,supportsUsageInStreaming:true,maxTokensField:'max_tokens'}};}
const context=()=>({systemPrompt:'OWN_PRIVATE_PROMPT',messages:[{role:'user',content:'own-user',timestamp:1}]});
const options=()=>({apiKey:'OWN_PRIVATE_KEY',maxRetries:0,maxTokens:1024,temperature:0,timeoutMs:5000,signal:new AbortController().signal,fetch:async()=>new Response('body'),onProviderStreamEvent:()=>{}});
const done=()=>({type:'done',message:{api:'openai-completions',provider:'own-provider',model:'own-model',stopReason:'stop',content:[{type:'text',text:'own-answer'}]}});
function fixture(config={}){
  const child=new EventEmitter(),pipe=new EventEmitter(),input=new EventEmitter(),messages=[],settings=[],terminations=[];
  const decoder=createReviewFrameReader({maxFrameBytes:524288,maxFrames:1000000,maxTotalBytes:8388608});
  pipe.write=(chunk,callback)=>{messages.push(...decoder.push(chunk).map(processJson));queueMicrotask(()=>callback());return true;};
  child.stdio=[null,null,null,pipe,input];child.stdout=new EventEmitter();child.stderr=new EventEmitter();
  const processFactory=(url,value)=>{settings.push({url,value});return{child,terminate(){terminations.push(1);return config.terminate?config.terminate():Promise.resolve(true);}};};
  const adapter=createProcessReviewSdk({anchor:'/own/slice/package.json',processFactory,...config.options});
  const stream=(opts={})=>adapter.sdk.streamSimple(model(),adapter.sdk.normalizeContext(context()),{...options(),...opts});
  const emit=(value)=>input.emit('data',encodeReviewFrame(JSON.stringify({schema_version:1,...value}),{maxFrameBytes:524288}));
  return{child,pipe,input,messages,settings,terminations,adapter,stream,emit};
}
const fetchMessage=()=>({type:'fetch',seq:1,url:'https://own.invalid/v1/chat/completions',init:{method:'POST',headers:{accept:'application/json'},body:'{}'},aborted:false});
test('no idle child; branded fixed context; fixed factory env and argv',async()=>{
  const f=fixture();const c=f.adapter.sdk.normalizeContext(context());assert.equal(f.settings.length,0);assert.ok(Object.isFrozen(c.messages[0]));
  const original=context();const frozen=f.adapter.sdk.normalizeContext(original);original.messages[0].content='changed';assert.equal(frozen.messages[0].content,'own-user');
  const it=f.stream();await tick();assert.equal(f.settings.length,1);
  assert.equal(f.settings[0].url.pathname.endsWith('/sdk-process-entry.ts'),true);
  assert.deepEqual(f.settings[0].value,{env:{OPENAI_LOG:'off'},execArgv:['--experimental-import-meta-resolve'],argv:['--risk-review-sdk-process'],stdio:['ignore','pipe','pipe','pipe','pipe']});
  assert.ok(Object.isFrozen(f.settings[0].value.env));assert.equal(f.messages[0].type,'run');assert.equal(f.messages[0].options.apiKey,'OWN_PRIVATE_KEY');
  await f.adapter.close();assert.equal(f.adapter.snapshot().process_terminated,true);
});
for(const fault of ['unknown','getter','proxy','relative','factory','limit'])test('invalid constructor '+fault+' does not run factory',()=>{
  let count=0;let config={anchor:'/own/package.json',processFactory(){count++;}};
  if(fault==='unknown')config.foo=1;if(fault==='getter')Object.defineProperty(config,'anchor',{get(){count++;},enumerable:true});
  if(fault==='proxy')config=new Proxy(config,{ownKeys(){count++;throw Error('PRIVATE');}});
  if(fault==='relative')config.anchor='relative';if(fault==='factory')config.processFactory=null;if(fault==='limit')config.responseLimit=262145;
  bad(()=>createProcessReviewSdk(config));assert.equal(count,0);
});
test('invalid/unbranded input fails before child and attempt cannot retry',()=>{
  const f=fixture();bad(()=>f.adapter.sdk.streamSimple(model(),context(),options()));assert.equal(f.settings.length,0);bad(()=>f.stream());assert.equal(f.settings.length,0);
});
test('abort before stream creates no child',()=>{
  const f=fixture(),abort=new AbortController();abort.abort();bad(()=>f.stream({signal:abort.signal}));assert.equal(f.settings.length,0);
});
test('one fetch, bounded binary response, serial metadata ack and terminal',async()=>{
  const f=fixture(),seen=[],it=f.stream({fetch:async()=>new Response(Uint8Array.of(0,255,1)),onProviderStreamEvent:v=>seen.push(v)});await tick();
  f.emit(fetchMessage());await tick();assert.equal(f.adapter.snapshot().fetch_requests,1);
  assert.deepEqual(f.messages[1],{schema_version:1,type:'response',seq:1,status:200,headers:{},body:'AP8B'});
  f.emit({type:'raw',seq:1,metadata:{model:'own-model',usage:{prompt_tokens:5}}});await tick();assert.equal(seen.length,1);assert.equal(f.messages[2].type,'raw-ack');
  f.emit({type:'event',seq:1,event:done()});assert.deepEqual((await it.next()).value,done());assert.equal((await it.next()).done,true);
  await f.adapter.close();assert.equal(f.adapter.snapshot().failure_code,null);
  assert.equal(JSON.stringify(f.adapter.snapshot()).includes('PRIVATE'),false);
  assert.equal(f.child.stdout.listenerCount('data'),0);assert.equal(f.child.listenerCount('error'),0);
});
test('response property getters are not called',async()=>{
  const f=fixture(),r=new Response('ok');let calls=0;
  for(const key of ['status','headers','body'])Object.defineProperty(r,key,{get(){calls++;throw Error('PRIVATE');}});
  f.stream({fetch:async()=>r});await tick();f.emit(fetchMessage());await tick();assert.equal(calls,0);assert.equal(f.messages[1].body,'b2s=');await f.adapter.close();
});
test('metadata serial ACK backpressure rejects overlapping raw messages',async()=>{
  const gate=deferred(),f=fixture(),it=f.stream({onProviderStreamEvent:()=>gate.promise});await tick();f.emit(fetchMessage());await tick();
  const result=it.next();f.emit({type:'raw',seq:1,metadata:{model:'own-model'}});f.emit({type:'raw',seq:2,metadata:{}});
  await assert.rejects(result,e=>e.code===error);gate.resolve();await tick();assert.equal(f.messages.some(x=>x.type==='raw-ack'),false);await f.adapter.close();
});
for(const fault of ['duplicate-fetch','raw-before-response','raw-seq','event-seq','unknown','extra','after-terminal'])test('invalid wire sequence '+fault+' sticky',async()=>{
  const f=fixture(),it=f.stream();await tick();const result=it.next();
  if(fault==='duplicate-fetch'){f.emit(fetchMessage());f.emit(fetchMessage());}
  if(fault==='raw-before-response')f.emit({type:'raw',seq:1,metadata:{}});
  if(fault==='raw-seq'){f.emit(fetchMessage());await tick();f.emit({type:'raw',seq:2,metadata:{}});}
  if(fault==='event-seq')f.emit({type:'event',seq:2,event:done()});
  if(fault==='unknown')f.emit({type:'unknown',seq:1});
  if(fault==='extra')f.emit({...fetchMessage(),source:'human'});
  if(fault==='after-terminal'){f.emit({type:'event',seq:1,event:done()});await result;f.emit({type:'event',seq:1,event:done()});}
  if(fault!=='after-terminal')await assert.rejects(result,e=>e.code===error);
  await tick();assert.equal(f.adapter.snapshot().failure_code,error);await assert.rejects(it.next(),e=>e.code===error);await f.adapter.close();
});
test('body cap cancels reader without retry and no response frame',async()=>{
  let canceled=0,sends=0;const f=fixture({options:{responseLimit:4}}),it=f.stream({fetch:async()=>{sends++;return new Response(new ReadableStream({start(c){c.enqueue(Uint8Array.of(1,2,3));c.enqueue(Uint8Array.of(4,5));},cancel(){canceled++;}}));}});await tick();
  const result=it.next();f.emit(fetchMessage());await assert.rejects(result,e=>e.code===error);await tick();
  assert.equal(sends,1);assert.equal(canceled,1);assert.equal(f.messages.filter(x=>x.type==='response').length,0);await f.adapter.close();
});
test('stalled body abort immediately rejects iterator and cancels own reader',async()=>{
  const abort=new AbortController();let canceled=0;const f=fixture(),it=f.stream({signal:abort.signal,fetch:async()=>new Response(new ReadableStream({cancel(){canceled++;}}))});await tick();
  f.emit(fetchMessage());await tick();const result=it.next();abort.abort();await assert.rejects(result,e=>e.code===error);await tick();assert.equal(canceled,1);assert.equal(f.adapter.snapshot().fetch_requests,1);await f.adapter.close();
});
test('send ignoring abort late response is canceled, never delivered',async()=>{
  const pending=deferred(),abort=new AbortController();let canceled=0;const f=fixture(),it=f.stream({signal:abort.signal,fetch:()=>pending.promise});await tick();f.emit(fetchMessage());
  const result=it.next();abort.abort();await assert.rejects(result,e=>e.code===error);
  pending.resolve(new Response(new ReadableStream({cancel(){canceled++;}})));await tick();assert.equal(canceled,1);assert.equal(f.messages.length,1);await f.adapter.close();
});
for(const confirmed of [false,true])test('termination scope confirmation '+confirmed+' is independent of exit',async()=>{
  const gate=deferred(),f=fixture({terminate:()=>gate.promise}),it=f.stream();await tick();f.emit({type:'event',seq:1,event:done()});await it.next();
  const closing=f.adapter.close();f.child.emit('exit',0);assert.equal(f.adapter.snapshot().process_terminated,false);assert.doesNotThrow(()=>f.child.emit('error',Error('OWN_PRIVATE')));
  gate.resolve(confirmed);await closing;assert.equal(f.adapter.snapshot().process_terminated,confirmed);assert.equal(f.terminations.length,1);
  assert.equal(f.adapter.snapshot().failure_code,confirmed?null:error);
  await f.adapter.close();assert.equal(f.terminations.length,1);
});
test('never-resolving terminate remains unknown and abort iterator returns promptly',async()=>{
  const f=fixture({terminate:()=>new Promise(()=>{})}),abort=new AbortController(),it=f.stream({signal:abort.signal});await tick();const result=it.next();abort.abort();await assert.rejects(result,e=>e.code===error);
  f.adapter.close();await tick();assert.equal(f.adapter.snapshot().process_terminated,false);assert.equal(f.adapter.snapshot().termination_started,true);assert.equal(f.terminations.length,1);
});
test('normal terminal followed by abort/return/close retains successful state',async()=>{
  const abort=new AbortController(),f=fixture(),it=f.stream({signal:abort.signal});await tick();f.emit({type:'event',seq:1,event:done()});await it.next();abort.abort();await it.return();await f.adapter.close();
  assert.equal(f.adapter.snapshot().failure_code,null);assert.equal(f.adapter.snapshot().process_terminated,true);
});
test('second stream does not launch or re-send and sets sticky failure',async()=>{
  const f=fixture();f.stream();await tick();bad(()=>f.stream());assert.equal(f.settings.length,1);assert.equal(f.messages.length,1);await f.adapter.close();
});
for(const kind of ['exit','error','pipe-error','eof'])test('unexpected '+kind+' is fixed failure',async()=>{
  const f=fixture(),it=f.stream();await tick();const next=it.next();
  if(kind==='pipe-error')f.input.emit('error',Error('PRIVATE'));else if(kind==='eof')f.input.emit('end');else f.child.emit(kind,Error('PRIVATE'));
  await assert.rejects(next,e=>e.code===error&&!e.message.includes('PRIVATE'));await f.adapter.close();
});
test('writer waits callback plus drain with only one queued slot',async()=>{
  const pipe=new EventEmitter();let callback;pipe.write=(_,cb)=>{callback=cb;return false;};const w=processWriter(pipe);let completed=false;
  const p=w.write({safe:1}).then(()=>completed=true),q=w.write({safe:2});await assert.rejects(w.write({safe:3}),e=>e.code===error);
  callback();await tick();assert.equal(completed,false);pipe.emit('drain');await p;assert.equal(completed,true);
  callback();pipe.emit('drain');await q;assert.equal(pipe.listenerCount('drain'),0);
});
test('writer callback failure and cancel clean pending listeners',async()=>{
  for(const kind of ['error','cancel']){const pipe=new EventEmitter();pipe.write=()=>false;const w=processWriter(pipe),p=w.write({safe:1});
    if(kind==='error')pipe.emit('error',Error('PRIVATE'));else w.cancel();await assert.rejects(p,e=>e.code===error);assert.equal(pipe.listenerCount('drain'),0);}
});
for(const text of ['{"schema_version":1,"schema_version":1}','{"outer":{"a":1,"\\u0061":2}}','{"schema_version":1.00000000000000001}', '{"schema_version":true}', '{"seq":1e0}', '{"seq":1.0}', '{"x":"\\ud800"}','{"x":NaN}', '{"__proto__":{}}', 'x{}', '{"x":'+ '['.repeat(17)+'0'+']'.repeat(17)+'}'])test('closed JSON rejects '+text.slice(0,30),()=>{
  if(text==='{"schema_version":true}')bad(()=>processMessage(processJson(text),'child'));else bad(()=>processJson(text));
});
test('duplicate nested IPC JSON fails before private fetch',async()=>{
  const f=fixture(),it=f.stream();await tick();const result=it.next();f.input.emit('data',encodeReviewFrame('{"schema_version":1,"type":"fetch","seq":1,"init":{"method":"POST","method":"POST"}}',{maxFrameBytes:524288}));
  await assert.rejects(result,e=>e.code===error);assert.equal(f.adapter.snapshot().fetch_requests,0);await f.adapter.close();
});
test('explicit null response cap is invalid',()=>bad(()=>createProcessReviewSdk({anchor:'/own/package.json',processFactory:()=>{},responseLimit:null})));
test('native Buffer body and empty null-body response use exact bounded base64',async()=>{
  for(const response of [new Response(Buffer.from([0,255,2])),new Response(null,{status:204})]){
    const f=fixture(),it=f.stream({fetch:async()=>response});await tick();f.emit(fetchMessage());await tick();
    assert.equal(f.messages[1].body,response.status===204?null:'AP8C');await f.adapter.close();
  }
});
test('all framed byte boundaries accepted without caller alias',async()=>{
  const f=fixture(),it=f.stream();await tick();const encoded=encodeReviewFrame(JSON.stringify({schema_version:1,type:'event',seq:1,event:done()}),{maxFrameBytes:524288});
  for(const byte of encoded){const chunk=Uint8Array.of(byte);f.input.emit('data',chunk);chunk[0]=0;}
  assert.deepEqual((await it.next()).value,done());await f.adapter.close();
});
test('invalid UTF8 and truncated EOF become fixed sticky failures',async()=>{
  for(const fault of ['utf8','partial']){const f=fixture(),it=f.stream();await tick();const p=it.next();
    f.input.emit('data',fault==='utf8'?Uint8Array.of(0,0,0,1,255):Uint8Array.of(0,0));if(fault==='partial')f.input.emit('end');
    await assert.rejects(p,e=>e.code===error);await f.adapter.close();}
});
test('rejecting terminate never claims scope gone and retains error drain',async()=>{
  const f=fixture({terminate:()=>Promise.reject(Error('OWN_PRIVATE'))}),it=f.stream();await tick();f.emit({type:'event',seq:1,event:done()});await it.next();
  await f.adapter.close();assert.equal(f.adapter.snapshot().process_terminated,false);assert.equal(f.adapter.snapshot().failure_code,error);assert.doesNotThrow(()=>f.child.emit('error',Error('PRIVATE')));
});
test('write failure leaves no successful event, terminates only own scope',async()=>{
  const f=fixture();f.pipe.write=()=>{throw Error('OWN_PRIVATE_WRITE');};const it=f.stream();await assert.rejects(it.next(),e=>e.code===error);await f.adapter.close();assert.equal(f.terminations.length,1);
});
test('queued write cancel rejects both promises and no drain remains',async()=>{
  const pipe=new EventEmitter();pipe.write=()=>false;const writer=processWriter(pipe),p=writer.write({a:1}),q=writer.write({b:2});
  writer.cancel();await assert.rejects(p,e=>e.code===error);await assert.rejects(q,e=>e.code===error);assert.equal(pipe.listenerCount('drain'),0);
});
test('stdout/stderr are dropped and their errors remain caught during pending terminate',async()=>{
  const gate=deferred(),f=fixture({terminate:()=>gate.promise}),it=f.stream();await tick();
  f.child.stdout.emit('data',Buffer.from('OWN_PRIVATE_LOG'));f.child.stderr.emit('data',Buffer.from('OWN_PRIVATE_ERROR'));const p=it.next();
  assert.doesNotThrow(()=>f.child.stdout.emit('error',Error('OWN_PRIVATE')));await assert.rejects(p,e=>e.code===error);
  assert.doesNotThrow(()=>f.child.stderr.emit('error',Error('OWN_PRIVATE')));assert.equal(JSON.stringify(f.adapter.snapshot()).includes('OWN_PRIVATE'),false);
  gate.resolve(true);await f.adapter.close();assert.equal(f.child.stdout.listenerCount('data'),0);assert.equal(f.child.stderr.listenerCount('error'),0);
});
test('response peer raw before write callback/drain is a valid causal reply',async()=>{
  const f=fixture(),decode=createReviewFrameReader({maxFrameBytes:524288,maxFrames:100,maxTotalBytes:8388608});let release;
  f.pipe.write=(chunk,callback)=>{
    const message=processJson(decode.push(chunk)[0]);f.messages.push(message);
    if(message.type==='response'){
      release=()=>{callback();f.pipe.emit('drain');};
      f.emit({type:'raw',seq:1,metadata:{model:'own-model'}});return false;
    }
    queueMicrotask(()=>callback());return true;
  };
  const it=f.stream(),next=it.next();next.catch(()=>{});await tick();f.emit(fetchMessage());await tick();
  assert.equal(f.adapter.snapshot().failure_code,null);assert.equal(typeof release,'function');
  assert.equal(f.messages.filter(x=>x.type==='raw-ack').length,0);release();await tick();
  assert.equal(f.messages.filter(x=>x.type==='raw-ack').length,1);
  f.emit({type:'event',seq:1,event:done()});assert.deepEqual((await next).value,done());await f.adapter.close();
});
test('ACK peer rawN+1 before write callback/drain is a valid causal reply',async()=>{
  const f=fixture(),decode=createReviewFrameReader({maxFrameBytes:524288,maxFrames:100,maxTotalBytes:8388608});let release;const seen=[];
  f.pipe.write=(chunk,callback)=>{
    const message=processJson(decode.push(chunk)[0]);f.messages.push(message);
    if(message.type==='raw-ack'&&message.seq===1){
      release=()=>{callback();f.pipe.emit('drain');};
      f.emit({type:'raw',seq:2,metadata:{model:'own-model'}});return false;
    }
    queueMicrotask(()=>callback());return true;
  };
  const it=f.stream({onProviderStreamEvent:metadata=>seen.push(metadata)}),next=it.next();next.catch(()=>{});await tick();f.emit(fetchMessage());await tick();
  f.emit({type:'raw',seq:1,metadata:{model:'own-model'}});await tick();
  assert.equal(f.adapter.snapshot().failure_code,null);assert.equal(seen.length,2);assert.equal(f.messages.filter(x=>x.type==='raw-ack').length,1);
  release();await tick();assert.equal(f.messages.filter(x=>x.type==='raw-ack').length,2);
  f.emit({type:'event',seq:1,event:done()});assert.deepEqual((await next).value,done());await f.adapter.close();
});
test('options token cap above model maximum rejected before child creation',()=>{
  const f=fixture();try{bad(()=>f.stream({maxTokens:2048}));assert.equal(f.settings.length,0);}finally{f.adapter.close();}
});
test('queued write start hook runs only at actual begin and before native write',async()=>{
  const pipe=new EventEmitter(),order=[],callbacks=[];pipe.write=(_,cb)=>{order.push('write');callbacks.push(cb);return false;};
  const writer=processWriter(pipe),a=writer.write({a:1},{onStart:()=>order.push('start-a')}),b=writer.write({b:1},{onStart:()=>order.push('start-b')});
  assert.deepEqual(order,['start-a','write']);callbacks.shift()();pipe.emit('drain');await a;
  assert.deepEqual(order,['start-a','write','start-b','write']);callbacks.shift()();pipe.emit('drain');await b;
});
test('unsolicited rawN+1 while ACK merely queued remains invalid',async()=>{
  const f=fixture(),decode=createReviewFrameReader({maxFrameBytes:524288,maxFrames:100,maxTotalBytes:8388608});
  f.pipe.write=(chunk,callback)=>{
    const m=processJson(decode.push(chunk)[0]);f.messages.push(m);
    if(m.type==='response'){f.emit({type:'raw',seq:1,metadata:{model:'own-model'}});return false;}
    queueMicrotask(()=>callback());return true;
  };
  const it=f.stream(),next=it.next();next.catch(()=>{});await tick();f.emit(fetchMessage());await tick();
  assert.equal(f.messages.some(x=>x.type==='raw-ack'),false);
  f.emit({type:'raw',seq:2,metadata:{model:'own-model'}});await assert.rejects(next,e=>e.code===error);await f.adapter.close();
});
test('native write throw after response onStart is sticky failure with no ACK',async()=>{
  const f=fixture(),decode=createReviewFrameReader({maxFrameBytes:524288,maxFrames:100,maxTotalBytes:8388608});
  f.pipe.write=(chunk,callback)=>{
    const m=processJson(decode.push(chunk)[0]);f.messages.push(m);
    if(m.type==='response')throw Error('OWN_PRIVATE_WRITE_FAILURE');queueMicrotask(()=>callback());return true;
  };
  const it=f.stream(),next=it.next();await tick();f.emit(fetchMessage());await assert.rejects(next,e=>e.code===error);
  f.emit({type:'raw',seq:1,metadata:{}});assert.equal(f.messages.some(x=>x.type==='raw-ack'),false);await f.adapter.close();assert.equal(f.adapter.snapshot().failure_code,error);
});
