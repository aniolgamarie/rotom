// 本模块目前仅自有fake进程IO组合；默认guard禁止spawn，真实进程隔离待root窄入口。
import assert from "node:assert/strict";
import { test as nativeTest } from "node:test";
const test=(name,fn)=>nativeTest(name,{timeout:8000},fn);
import { PassThrough } from "node:stream";
import { EventEmitter } from "node:events";
import { createProcessReviewSdk } from "../src/sdk-process.ts";
import { startSdkProcess } from "../src/sdk-process-entry.ts";
import { createReviewAttempt } from "../src/transport.ts";
const binding={request_id:'1'.repeat(32),operation_digest:'a'.repeat(64),context_digest:'b'.repeat(64),reviewer_identity:'c'.repeat(64)};
function combo(mode='valid',qual={}){
  let started=0,imports=0,sends=0,stopped=0,entry;
  const p2c=new PassThrough(),c2p=new PassThrough(),child=new EventEmitter();child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdio=[null,null,null,p2c,c2p];
  const adapter=createProcessReviewSdk({anchor:'/own/slice/package.json',processFactory(){started++;
    entry=startSdkProcess({input:p2c,output:c2p,createSdk(){imports++;return{sdk:{normalizeContext:x=>x,
      async *streamSimple(model,ctx,opts){
        const r=await opts.fetch(model.baseUrl+'/chat/completions',{method:'POST',headers:{authorization:'Bearer '+opts.apiKey,accept:'application/json','content-type':'application/json'},
          body:JSON.stringify({model:model.id,messages:[{role:'system',content:ctx.systemPrompt},{role:'user',content:ctx.messages[0].content}],stream:true,stream_options:{include_usage:true},temperature:0,max_tokens:opts.maxTokens}),signal:opts.signal});
        await r.text();await opts.onProviderStreamEvent({model:model.id,...(mode==='missing'?{}:{usage:{prompt_tokens:5,completion_tokens:3,total_tokens:8}})});
        yield{type:'done',message:{api:model.api,provider:model.provider,model:model.id,stopReason:'stop',content:[{type:'text',text:ctx.messages[0].content}]}};
      }},close:async()=>{}};}});
    return{child,terminate:async()=>{stopped++;entry.close();return true;}};}});
  const attempt=createReviewAttempt({binding,route:{identity:binding.reviewer_identity,pricing_identity:'d'.repeat(64),currency:'USD',provider:'own-provider',model:'own-model',base_url:'https://own.invalid/v1',context_window:32000,max_output_tokens:1024,cost:{input:1,output:2,cacheRead:1,cacheWrite:1}},
    input:{system_prompt:'own policy',user_prompt:JSON.stringify({schema_version:1,...binding,decision:'allow',reason_code:'authorized-in-scope'})},
    qualification:{profile:'pi-full',enabled:true,hard_policy_allowed:true,role_allows:true,requires_human:false,automatic_risk_allowed:true,...qual},
    apiKey:'OWN_PRIVATE_KEY',expectedHeaders:{authorization:'Bearer OWN_PRIVATE_KEY',accept:'application/json','content-type':'application/json'},sdk:adapter.sdk,
    send:async()=>{sends++;return new Response('own-body');},isCurrent:()=>true,deadlineMs:Date.now()+10000,maxDurationMs:5000});
  return{attempt,adapter,facts:()=>({started,imports,sends,stopped})};
}
test('fake entry-private pipes roundtrip exact validator, response and raw ACK',async()=>{
  const f=combo(),r=await f.attempt.run();assert.equal(r.outcome,'valid');assert.equal(r.candidate.decision,'allow');assert.equal(r.requests,1);assert.equal(r.usage.total_tokens,8);
  await f.adapter.close();assert.deepEqual(f.facts(),{started:1,imports:1,sends:1,stopped:1});assert.equal(f.adapter.snapshot().failure_code,null);assert.equal(f.adapter.snapshot().process_terminated,true);
});
test('fake entry missing raw usage remains unknown',async()=>{
  const f=combo('missing'),r=await f.attempt.run();assert.equal(r.outcome,'valid');assert.equal(r.usage.status,'unknown');assert.equal(r.usage.total_tokens,null);await f.adapter.close();
});
for(const[qualification,outcome]of[[{profile:'pi-base'},'not-called'],[{hard_policy_allowed:false},'policy-blocked'],[{requires_human:true},'human-required']])test('T qualification '+outcome+' zero fake process/import/send',async()=>{
  const f=combo('valid',qualification),r=await f.attempt.run();assert.equal(r.outcome,outcome);assert.deepEqual(f.facts(),{started:0,imports:0,sends:0,stopped:0});await f.adapter.close();
});
test('entry rejects unknown run without SDK construction',async()=>{
  const input=new PassThrough(),output=new PassThrough();let calls=0;const packets=[];
  const {createReviewFrameReader,encodeReviewFrame}=await import('../src/process-frames.ts');
  const decoder=createReviewFrameReader({maxFrameBytes:524288,maxFrames:100,maxTotalBytes:8388608});
  output.on('data',chunk=>packets.push(...decoder.push(chunk).map(JSON.parse)));
  const entry=startSdkProcess({input,output,createSdk(){calls++;throw Error('PRIVATE');}});
  input.write(encodeReviewFrame('{"schema_version":1,"type":"run","seq":1,"anchor":"/own/package.json","extra":true}',{maxFrameBytes:524288}));
  await new Promise(resolve=>setImmediate(resolve));assert.equal(calls,0);assert.equal(entry.snapshot().closed,true);
  assert.deepEqual(packets,[{schema_version:1,type:'event',seq:1,event:{type:'error'}}]);entry.close();
});
test('entry duplicate JSON, wrong raw ACK and cancellation never forge done',async()=>{
  for(const text of ['{"schema_version":1,"schema_version":1,"type":"cancel","seq":1}', '{"schema_version":1,"type":"raw-ack","seq":2}']){
    const input=new PassThrough(),output=new PassThrough();let calls=0;const packets=[];
    const {createReviewFrameReader,encodeReviewFrame}=await import('../src/process-frames.ts');
    const decoder=createReviewFrameReader({maxFrameBytes:524288,maxFrames:100,maxTotalBytes:8388608});output.on('data',chunk=>packets.push(...decoder.push(chunk).map(JSON.parse)));
    const entry=startSdkProcess({input,output,createSdk(){calls++;}});input.write(encodeReviewFrame(text,{maxFrameBytes:524288}));await new Promise(resolve=>setImmediate(resolve));
    assert.equal(calls,0);assert.deepEqual(packets,[{schema_version:1,type:'event',seq:1,event:{type:'error'}}]);entry.close();
  }
});
