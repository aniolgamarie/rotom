// 只在私有Worker中加载公开SDK入口。单纯import本文件不加载SDK/创建Worker。
import { isMainThread, parentPort, workerData } from "node:worker_threads";
import { pathToFileURL, fileURLToPath } from "node:url";
import { isAbsolute, normalize, dirname, relative, sep } from "node:path";
import { lstatSync, realpathSync } from "node:fs";
import { types } from "node:util";
import { compileSharedReviewSdkContract } from "./shared-sdk-contract.ts";
import { sdkData, sdkText, sdkArray, sdkFailure, copySdkModel, copySdkContext,
  copySdkOptions, copySdkHeaders, copySdkMetadata, copySdkEvent } from "./sdk-worker.ts";
const discard = fn => { try { Promise.resolve(fn()).catch(()=>{}); } catch {} };
function own(value,key) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) throw sdkFailure();
  const descriptor=Object.getOwnPropertyDescriptor(value,key);
  if (!descriptor || !Object.hasOwn(descriptor,"value")) return undefined;
  return descriptor.value;
}
function metadata(value) {
  const result={};const model=own(value,"model");if(sdkText(model,128))result.model=model;
  const raw=own(value,"usage");
  if(raw !== undefined && raw !== null) {
    const usage={};
    for(const key of ["prompt_tokens","completion_tokens","total_tokens"]){const n=own(raw,key);if(Number.isSafeInteger(n)&&n>=0&&n<=10010000)usage[key]=n;}
    const details=own(raw,"prompt_tokens_details");
    if(details!==undefined&&details!==null){const n=own(details,"cached_tokens");if(Number.isSafeInteger(n)&&n>=0&&n<=10000000)usage.prompt_tokens_details={cached_tokens:n};}
    result.usage=usage;
  }
  return copySdkMetadata(result);
}
function terminalEvent(event) {
  const type=own(event,"type");
  if(type==="error")return {type:"error"};
  if(typeof type==="string"&&type.startsWith("toolcall"))return {type:"toolcall"};
  if(type!=="done") {
    if(!["start","text_start","text_delta","text_end","thinking_start","thinking_delta","thinking_end"].includes(type))throw sdkFailure();
    return null;
  }
  const message=own(event,"message");
  const copy={};for(const key of ["api","provider","model","stopReason"])copy[key]=own(message,key);
  copy.content=sdkArray(own(message,"content"),16).map(item=>{
    const part=own(item,"type");
    if(part==="thinking")return {type:"thinking"};
    if(part!=="text")throw sdkFailure();return {type:"text",text:own(item,"text")};
  });
  return copySdkEvent({type:"done",message:copy});
}
export async function loadPublicSdk(anchor, seams = {}) {
  // Node24公开但需固定flag的parentURL参数；不以单参checkout解析或dist路径回退。
  const resolve = seams.resolve ?? ((specifier,parentURL) => import.meta.resolve(specifier,parentURL));
  const importer = seams.importer ?? (url => import(url));
  try {
    const slice = dirname(anchor), parentURL = pathToFileURL(anchor).href;
    const root = lstatSync(slice,{bigint:true}), anchorStat = lstatSync(anchor,{bigint:true});
    if(!root.isDirectory() || root.isSymbolicLink() || realpathSync(slice)!==slice
      || !anchorStat.isFile() || anchorStat.isSymbolicLink() || realpathSync(anchor)!==anchor)throw sdkFailure();
    const rootKeys=["dev","ino","uid","mode"];
    const fileKeys=["dev","ino","uid","mode","nlink","size","mtimeNs","ctimeNs"];
    const targets=[];
    const check=()=>{
      const now=lstatSync(slice,{bigint:true}), nowAnchor=lstatSync(anchor,{bigint:true});
      if(realpathSync(slice)!==slice || !now.isDirectory() || !nowAnchor.isFile()
        || rootKeys.some(key=>now[key]!==root[key]) || fileKeys.some(key=>nowAnchor[key]!==anchorStat[key]))throw sdkFailure();
      for(const target of targets){
        if(realpathSync(target.path)!==target.path)throw sdkFailure();
        const current=lstatSync(target.path,{bigint:true});
        if(!current.isFile() || fileKeys.some(key=>current[key]!==target.stat[key]))throw sdkFailure();
      }
    };
    // 先核对两个公开入口；缺包借祖先或URL越界必须零import。
    for(const specifier of ["@earendil-works/pi-ai/api/openai-completions","@earendil-works/pi-ai/utils/transcript"]){
      const resolved=resolve(specifier,parentURL);
      if(typeof resolved!=="string")throw sdkFailure();
      const url=new URL(resolved);
      if(url.protocol!=="file:" || url.search || url.hash)throw sdkFailure();
      const path=fileURLToPath(url);
      if(!isAbsolute(path) || normalize(path)!==path || pathToFileURL(path).href!==url.href)throw sdkFailure();
      const actual=realpathSync(path), inside=relative(slice,actual);
      if(!inside || isAbsolute(inside) || inside===".." || inside.startsWith(".."+sep))throw sdkFailure();
      const stat=lstatSync(actual,{bigint:true});if(!stat.isFile() || stat.isSymbolicLink())throw sdkFailure();
      targets.push({path:actual,url:pathToFileURL(actual).href,stat});
    }
    check();
    const provider=await importer(targets[0].url);check();
    const transcript=await importer(targets[1].url);check();
    if(typeof provider.streamSimple!=="function"||typeof transcript.normalizeContext!=="function")throw sdkFailure();
    return {streamSimple:provider.streamSimple,normalizeContext:transcript.normalizeContext};
  }catch{throw sdkFailure();}
}
// load为自有纯fake测试接缝；默认Worker始终走上面的公开resolver。
export function startSdkWorker({port,data,load=loadPublicSdk}) {
  const cfg=sdkData(data,["schema_version","anchor","shared_model_identity"],["shared_model_identity"]);
  if(cfg.schema_version!==1||!sdkText(cfg.anchor,4096)||cfg.anchor.includes("\0")||!isAbsolute(cfg.anchor)||normalize(cfg.anchor)!==cfg.anchor||!cfg.anchor.endsWith("/package.json"))throw sdkFailure();
  const bound=Object.hasOwn(cfg,"shared_model_identity");
  if(bound&&(typeof cfg.shared_model_identity!=="string"||!/^[a-f0-9]{64}$/.test(cfg.shared_model_identity)))throw sdkFailure();
  let running=false,finished=false,fetchUsed=false,fetchPending,rawPending,rawSeq=0,iterator,body,cleaned=false;
  const controller=new AbortController();
  const send=(message)=>port.postMessage({schema_version:1,...message});
  const cleanup=()=>{
    if(cleaned)return;cleaned=true;controller.abort();fetchPending?.remove();
    if(fetchPending){fetchPending.reject(sdkFailure());fetchPending=undefined;}
    if(rawPending){rawPending.reject(sdkFailure());rawPending=undefined;}
    if(body)discard(()=>body.cancel());
    discard(()=>iterator?.return?.());
  };
  const failure=()=>{if(finished)return;finished=true;cleanup();try{send({type:"event",seq:1,event:{type:"error"}});}catch{}};
  const bridgeFetch=(url,init)=>{
    if(fetchUsed||finished)throw sdkFailure();fetchUsed=true;
    const request=sdkData(init,["method","headers","body","signal"],["signal"]);
    if(!sdkText(url,2048)||request.method!=="POST"||!sdkText(request.body,131072)
      ||request.signal!==undefined&&(types.isProxy(request.signal)||!(request.signal instanceof AbortSignal)))throw sdkFailure();
    const headers=copySdkHeaders(request.headers), signal=request.signal;
    if(signal?.aborted||controller.signal.aborted)throw sdkFailure();
    return new Promise((resolve,reject)=>{
      const abort=()=>{try{send({type:"fetch-abort",seq:1});}catch{}failure();};
      const remove=()=>signal?.removeEventListener("abort",abort);
      fetchPending={resolve,reject,remove};signal?.addEventListener("abort",abort,{once:true});
      try{send({type:"fetch",seq:1,url,init:{method:"POST",headers,body:request.body},aborted:false});}
      catch{failure();}
    });
  };
  const onRaw=async event=>{
    if(finished||rawPending||rawSeq>=1000000)throw sdkFailure();
    const minimal=metadata(event);rawSeq++;
    await new Promise((resolve,reject)=>{rawPending={resolve,reject};try{send({type:"raw",seq:rawSeq,metadata:minimal});}catch{failure();}});
  };
  const run=async message=>{
    try{
      const sharedModel=bound?message.sharedModel:undefined;
      if(bound){
        const contract=compileSharedReviewSdkContract(sharedModel);
        if(contract.model_identity!==cfg.shared_model_identity)throw sdkFailure();
      }
      const model=copySdkModel(message.model,sharedModel),context=copySdkContext(message.context),options=copySdkOptions(message.options,sharedModel);
      if(options.maxTokens>model.maxTokens)throw sdkFailure();
      const sdk=await load(cfg.anchor);
      if(finished)return;
      const normalized=sdk.normalizeContext(context);
      const stream=sdk.streamSimple(model,normalized,{...options,signal:controller.signal,fetch:bridgeFetch,onProviderStreamEvent:onRaw});
      iterator=stream[Symbol.asyncIterator]();
      while(!finished){
        const next=await iterator.next();if(finished)return;
        if(!next||next.done)throw sdkFailure();const event=terminalEvent(next.value);
        if(event!==null){finished=true;send({type:"event",seq:1,event});cleanup();return;}
      }
    }catch{failure();}
  };
  const receive=value=>{
    try{
      const message=sdkData(value,["schema_version","type","seq","model","context","options","status","headers","body","sharedModel"],["model","context","options","status","headers","body","sharedModel"]);
      if(message.schema_version!==1||!Number.isSafeInteger(message.seq)||message.seq<1)throw sdkFailure();
      if(message.type==="cancel"){
        sdkData(value,["schema_version","type","seq"]);if(message.seq!==1)throw sdkFailure();finished=true;cleanup();return;
      }
      if(finished)throw sdkFailure();
      if(message.type==="run"){
        sdkData(value,["schema_version","type","seq","model","context","options",...(bound?["sharedModel"]:[])]);
        if(running||message.seq!==1)throw sdkFailure();running=true;discard(()=>run(message));
      }else if(message.type==="response"){
        sdkData(value,["schema_version","type","seq","status","headers","body"]);
        if(message.seq!==1||!fetchPending||!Number.isInteger(message.status)||message.status<200||message.status>599
          ||message.body!==null&&(types.isProxy(message.body)||!(message.body instanceof ReadableStream)))throw sdkFailure();
        const headers=copySdkHeaders(message.headers);body=message.body;
        const pending=fetchPending;fetchPending=undefined;pending.remove();pending.resolve(new Response(body,{status:message.status,headers}));
      }else if(message.type==="raw-ack"){
        sdkData(value,["schema_version","type","seq"]);if(!rawPending||message.seq!==rawSeq)throw sdkFailure();
        const pending=rawPending;rawPending=undefined;pending.resolve();
      }else throw sdkFailure();
    }catch{failure();}
  };
  const onClose=()=>{finished=true;cleanup();};
  port.on("message",receive);port.on("messageerror",failure);port.on("close",onClose);
  return Object.freeze({close:()=>{finished=true;cleanup();port.removeListener("message",receive);port.removeListener("messageerror",failure);port.removeListener("close",onClose);}});
}
if(!isMainThread)startSdkWorker({port:parentPort,data:workerData});
