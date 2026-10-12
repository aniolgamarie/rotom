// 新进程专用私密FD入口；SDK仍仅由W公开resolver在其自有Worker加载。
import { createReadStream, createWriteStream } from "node:fs";
import { pathToFileURL } from "node:url";
import { createIsolatedReviewSdk } from "./sdk-worker.ts";
import { FRAME_LIMITS, processFailure, processJson, processMessage, processWriter } from "./sdk-process.ts";
import { createReviewFrameReader } from "./process-frames.ts";
const discard=fn=>{try{Promise.resolve(fn()).catch(()=>{});}catch{}};
export function startSdkProcess({input,output,createSdk=createIsolatedReviewSdk,sharedModelIdentity}) {
  if(sharedModelIdentity!==undefined&&(typeof sharedModelIdentity!=="string"||!/^[a-f0-9]{64}$/.test(sharedModelIdentity)))throw processFailure();
  const decoder=createReviewFrameReader(FRAME_LIMITS),writer=processWriter(output),controller=new AbortController();
  let used=false,closed=false,terminal=false,adapter,iterator,fetchUsed=false,pendingResponse,pendingRaw,rawSeq=0;
  const send=message=>writer.write({schema_version:1,...message});
  function cleanup(){if(closed)return;closed=true;controller.abort();pendingResponse?.reject(processFailure());pendingResponse=undefined;pendingRaw?.reject(processFailure());pendingRaw=undefined;input.removeListener('data',onData);input.removeListener('end',onEnd);discard(()=>iterator?.return?.());discard(()=>adapter?.close());}
  function failed(){if(closed)return;terminal=true;discard(()=>send({type:'event',seq:1,event:{type:'error'}}));cleanup();}
  function onError(){failed();}
  function onEnd(){if(closed)return;try{decoder.end();}catch{}failed();}
  async function perform(m){
    try{
      adapter=createSdk({anchor:m.anchor,...(sharedModelIdentity===undefined?{}:{sharedModel:m.sharedModel})});const context=adapter.sdk.normalizeContext(m.context);
      iterator=adapter.sdk.streamSimple(m.model,context,{...m.options,signal:controller.signal,
        fetch:async(url,init)=>{
          if(fetchUsed||closed)throw processFailure();fetchUsed=true;
          const request=processMessage({schema_version:1,type:'fetch',seq:1,url,init:{method:init.method,headers:init.headers,body:init.body},aborted:init.signal.aborted},'child');
          let result;const promise=new Promise((resolve,reject)=>{pendingResponse={resolve,reject};});promise.catch(()=>{});
          try{await writer.write(request);result=await promise;}catch{pendingResponse=undefined;throw processFailure();}
          return new Response(result.body===null?null:Buffer.from(result.body,'base64'),{status:result.status,headers:result.headers});
        },onProviderStreamEvent:async(metadata)=>{
          if(pendingRaw||closed||!fetchUsed||pendingResponse)throw processFailure();
          const message=processMessage({schema_version:1,type:'raw',seq:++rawSeq,metadata},'child');
          const promise=new Promise((resolve,reject)=>{pendingRaw={resolve,reject,seq:rawSeq};});
          // rejection在写等待前就设handler，取消不能制造未处理promise拒绝。
          promise.catch(()=>{});await writer.write(message);await promise;
        }});
      for await(const event of iterator){if(closed)break;if(terminal)throw processFailure();
        const message=processMessage({schema_version:1,type:'event',seq:1,event},'child');terminal=true;await writer.write(message);
      }
      if(!terminal&&!closed)failed();
    }catch{failed();}
  }
  function accept(message){
    try{
      if(closed)throw processFailure();const m=processMessage(message,'parent',sharedModelIdentity);
      if(m.type==='run'){if(used)throw processFailure();used=true;discard(()=>perform(m));}
      else if(m.type==='response'){if(!used||terminal||!pendingResponse)throw processFailure();const pending=pendingResponse;pendingResponse=undefined;pending.resolve(m);}
      else if(m.type==='raw-ack'){if(terminal||!pendingRaw||m.seq!==pendingRaw.seq)throw processFailure();const pending=pendingRaw;pendingRaw=undefined;pending.resolve();}
      else cleanup();
    }catch{failed();}
  }
  function onData(chunk){if(closed)return;try{for(const text of decoder.push(chunk))accept(processJson(text));}catch{failed();}}
  input.on('data',onData);input.on('end',onEnd);input.on('error',onError);output.on('error',onError);
  return Object.freeze({close(){cleanup();writer.cancel();},snapshot(){return Object.freeze({used,closed,terminal,fetch_used:fetchUsed,raw_pending:!!pendingRaw});}});
}
function main(){
  // 固定legacy/bound两种argv和唯一环境；不从私密run包选择模式，不派生key或headers。
  if(![3,4].includes(process.argv.length)||process.argv.length===4&&!/^--risk-review-shared-model=[a-f0-9]{64}$/.test(process.argv[3])||process.argv[2]!=='--risk-review-sdk-process'||Object.keys(process.env).length!==1||process.env.OPENAI_LOG!=='off')throw processFailure();
  startSdkProcess({...(process.argv.length===4?{sharedModelIdentity:process.argv[3].slice("--risk-review-shared-model=".length)}:{}),input:createReadStream(null,{fd:3,autoClose:true}),output:createWriteStream(null,{fd:4,autoClose:true})});
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){try{main();}catch{process.exitCode=5;}}
