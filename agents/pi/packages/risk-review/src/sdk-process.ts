// 工厂监督的独立进程桥；无默认spawn，不将child exit冒充scope已终止。
import { types } from "node:util";
import { isAbsolute, normalize } from "node:path";
import { encodeReviewFrame, createReviewFrameReader } from "./process-frames.ts";
import { sdkData, sdkText, copySdkModel, copySdkContext, copySdkOptions, copySdkHeaders, copySdkMetadata, copySdkEvent } from "./sdk-worker.ts";
import { compileSharedReviewSdkContract } from "./shared-sdk-contract.ts";
export const PROCESS_ERROR = "PI_RISK_REVIEW_PROCESS_INVALID";
export function processFailure() { const e=new Error(PROCESS_ERROR);e.code=PROCESS_ERROR;return e; }
const fail=()=>{throw processFailure();};
export const FRAME_LIMITS=Object.freeze({maxFrameBytes:524288,maxFrames:1000000,maxTotalBytes:8388608});
const integer=(v)=>Number.isSafeInteger(v)&&v>0&&v<=1000000;
const discard=(fn)=>{try{Promise.resolve(fn()).catch(()=>{});}catch{}};
export function processJson(text) {
  // 有界递归parser，仅用于此私密wire；每层重复键在JSON.parse之前拒绝。
  try {
    if(!sdkText(text,524288))fail();let pos=0,nodes=0;
    const ws=()=>{while(/[\x20\x09\x0a\x0d]/.test(text[pos]??"x"))pos++;};
    function string() {
      const start=pos++;while(pos<text.length){const c=text[pos++];if(c==='"'){const v=JSON.parse(text.slice(start,pos));if(!sdkText(v,524288,true))fail();return v;}if(c==='\\')pos++;else if(c.charCodeAt(0)<32)fail();}fail();
    }
    function value(depth,key="") {
      if(depth>16||++nodes>4096)fail();ws();const c=text[pos];
      if(c==='"')return string();
      if(c==='{'){
        pos++;ws();const out={},seen=new Set();if(text[pos]==='}'){pos++;return out;}
        for(;;){ws();if(text[pos]!=='"')fail();const k=string();if(k==='__proto__'||seen.has(k))fail();seen.add(k);ws();if(text[pos++]!==':')fail();out[k]=value(depth+1,k);ws();const next=text[pos++];if(next==='}')return out;if(next!==',')fail();}
      }
      if(c==='['){pos++;ws();const out=[];if(text[pos]===']'){pos++;return out;}for(;;){out.push(value(depth+1));ws();const next=text[pos++];if(next===']')return out;if(next!==',')fail();}}
      for(const [token,v]of[["true",true],["false",false],["null",null]])if(text.startsWith(token,pos)){pos+=token.length;return v;}
      const token=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(text.slice(pos))?.[0];
      if(!token)fail();pos+=token.length;
      if(key==='schema_version'&&token!=='1'||key==='seq'&&!/^[1-9][0-9]*$/.test(token))fail();
      const number=Number(token);if(!Number.isFinite(number))fail();return number;
    }
    const result=value(0);ws();if(pos!==text.length)fail();return result;
  }catch{fail();}
}
export function processMessage(value,direction,sharedModelIdentity) {
  if(sharedModelIdentity!==undefined&&(typeof sharedModelIdentity!=="string"||!/^[a-f0-9]{64}$/.test(sharedModelIdentity)))fail();
  try {
    const head=sdkData(value,["schema_version","type","seq","anchor","model","context","options","status","headers","body","url","init","aborted","metadata","event","sharedModel"],
      ["anchor","model","context","options","status","headers","body","url","init","aborted","metadata","event","sharedModel"]);
    if(head.schema_version!==1||!integer(head.seq))fail();
    const exact=(keys)=>sdkData(value,["schema_version","type","seq",...keys]);
    if(direction==='parent'&&head.type==='run') {
      const m=exact(["anchor","model","context","options",...(sharedModelIdentity===undefined?[]:["sharedModel"])]);
      // marker由可信launcher固定；不得从run包自行推断或降级为legacy，并非来源签名。
      if(sharedModelIdentity!==undefined&&compileSharedReviewSdkContract(m.sharedModel).model_identity!==sharedModelIdentity)fail();
      if(m.seq!==1||!sdkText(m.anchor,4096)||!isAbsolute(m.anchor)||normalize(m.anchor)!==m.anchor||m.anchor.includes('\0')||!m.anchor.endsWith('/package.json'))fail();
      return {...m,model:copySdkModel(m.model,m.sharedModel),context:copySdkContext(m.context),options:copySdkOptions(m.options,m.sharedModel)};
    }
    if(direction==='parent'&&head.type==='response'){
      const m=exact(["status","headers","body"]);
      if(m.seq!==1||!Number.isSafeInteger(m.status)||m.status<200||m.status>599||m.body!==null&&!sdkText(m.body,349528,true))fail();
      if(m.body!==null&&Buffer.from(m.body,'base64').toString('base64')!==m.body)fail();
      return {...m,headers:copySdkHeaders(m.headers)};
    }
    if(direction==='parent'&&head.type==='raw-ack')return exact([]);
    if(direction==='parent'&&head.type==='cancel'){const m=exact([]);if(m.seq!==1)fail();return m;}
    if(direction==='child'&&head.type==='fetch'){
      const m=exact(["url","init","aborted"]),init=sdkData(m.init,["method","headers","body"]);
      if(m.seq!==1||typeof m.aborted!=='boolean'||!sdkText(m.url,2048)||init.method!=='POST'||!sdkText(init.body,131072))fail();
      return {...m,init:{...init,headers:copySdkHeaders(init.headers)}};
    }
    if(direction==='child'&&head.type==='raw'){const m=exact(["metadata"]);return {...m,metadata:copySdkMetadata(m.metadata)};}
    if(direction==='child'&&head.type==='event'){const m=exact(["event"]);if(m.seq!==1)fail();return {...m,event:copySdkEvent(m.event)};}
    fail();
  }catch{fail();}
}
export function processWriter(output) {
  let busy=false,failed=false,bytes=0,frames=0,pending,queued;
  function cancel(){failed=true;const q=queued;queued=undefined;q?.reject(processFailure());pending?.();}
  function begin(frame,resolve,reject,onStart){
    busy=true;
    let done=false,callback=false,drained=false,returned=false;
    const finish=(error)=>{
      if(done)return;if(!error&&(!callback||!drained||!returned))return;
      done=true;busy=false;pending=undefined;output.removeListener('drain',onDrain);output.removeListener('error',onError);
      if(error){failed=true;reject(processFailure());const q=queued;queued=undefined;q?.reject(processFailure());}
      else {resolve();const q=queued;queued=undefined;if(q)begin(q.frame,q.resolve,q.reject,q.onStart);}
    };
    const onDrain=()=>{drained=true;finish();},onError=()=>finish(true);pending=()=>finish(true);
    output.on('drain',onDrain);output.on('error',onError);
    try{onStart?.();const accepted=output.write(frame,error=>{callback=true;finish(error);});returned=true;if(accepted)drained=true;finish();}catch{finish(true);}
  }
  function write(value,{onStart}={}){
    // 同步pipe允许对端在write callback前回应；固定一个排队槽，不增长队列。
    // onStart仅内部可信状态钩子：排队时不执行，真正write前才转移状态。
    if(failed||busy&&queued||onStart!==undefined&&typeof onStart!=='function')return Promise.reject(processFailure());
    let frame;try{frame=encodeReviewFrame(JSON.stringify(value),{maxFrameBytes:FRAME_LIMITS.maxFrameBytes});if(bytes+frame.length>FRAME_LIMITS.maxTotalBytes||frames>=FRAME_LIMITS.maxFrames)fail();}catch{return Promise.reject(processFailure());}
    bytes+=frame.length;frames++;
    return new Promise((resolve,reject)=>{if(busy)queued={frame,resolve,reject,onStart};else begin(frame,resolve,reject,onStart);});
  }
  return Object.freeze({write,cancel});
}

function freeze(value){if(value&&typeof value==='object'){for(const item of Object.values(value))freeze(item);Object.freeze(value);}return value;}
const responseGet=(key,value)=>Object.getOwnPropertyDescriptor(Response.prototype,key).get.call(value);
export function createProcessReviewSdk(configuration) {
  let cfg,sharedModel,compiled;
  try{cfg=sdkData(configuration,["anchor","processFactory","responseLimit","sharedModel"],["responseLimit","sharedModel"]);
    if(!sdkText(cfg.anchor,4096)||!isAbsolute(cfg.anchor)||normalize(cfg.anchor)!==cfg.anchor||cfg.anchor.includes('\0')||!cfg.anchor.endsWith('/package.json')
      ||typeof cfg.processFactory!=='function'||types.isProxy(cfg.processFactory))fail();
    // 先完整own-data验证，再同步复制捕获；私密包不能由后续调用方修改。
    if(Object.hasOwn(cfg,"sharedModel")){compiled=compileSharedReviewSdkContract(cfg.sharedModel);sharedModel=freeze(structuredClone(cfg.sharedModel));}
    if(cfg.responseLimit===undefined)cfg.responseLimit=65536;if(!Number.isSafeInteger(cfg.responseLimit)||cfg.responseLimit<1||cfg.responseLimit>262144)fail();
  }catch{fail();}
  const contexts=new WeakSet(),state={phase:'prepared',child_started:false,termination_started:false,process_terminated:false,fetch_requests:0,failure_code:null,product_gate:false};
  let used=false,closed=false,terminal=false,child,scope,writer,signal,onAbort,fetchController,bodyReader,waiting,queued,termination;
  let rawPending=false,rawSeq=0,fetchPending=false,responseSent=false,fetchFn,rawCallback,decoder;
  const snapshot=()=>Object.freeze({...state}),drop=()=>{};
  function release(){for(const output of [child?.stdout,child?.stderr]){output?.removeListener('data',drop);output?.removeListener('error',onError);}child?.removeListener('error',onError);child?.removeListener('exit',onExit);
    for(const pipe of [child?.stdio?.[3],child?.stdio?.[4]])pipe?.removeListener('error',onError);}
  function terminate(){
    if(termination)return termination;
    signal?.removeEventListener('abort',onAbort);child?.stdio?.[4]?.removeListener('data',onData);child?.stdio?.[4]?.removeListener('end',onEnd);
    fetchController?.abort();if(bodyReader)discard(()=>bodyReader.cancel());writer?.cancel();
    if(!child)return Promise.resolve();state.termination_started=true;
    // 即使factory同步完成也先设置单次标记，error不能递归启动第二次terminate。
    termination=Promise.resolve();
    try{termination=Promise.resolve(scope.terminate()).then(gone=>{if(gone===true){state.process_terminated=true;release();}else{state.failure_code=PROCESS_ERROR;}},()=>{state.failure_code=PROCESS_ERROR;});}
    catch{state.failure_code=PROCESS_ERROR;}
    return termination;
  }
  function failed(){state.failure_code=PROCESS_ERROR;state.phase='failed';terminal=true;queued=undefined;waiting?.reject(processFailure());waiting=undefined;discard(terminate);}
  function onError(){if(!state.termination_started)failed();}
  function onExit(){if(!state.termination_started)failed();}
  function onEnd(){if(closed||state.termination_started)return;try{decoder.end();}catch{}failed();}
  const send=async(message,onStart)=>{await writer.write(processMessage({schema_version:1,...message},'parent',compiled?.model_identity),{onStart});};
  async function accept(message){
    try{
      const m=processMessage(message,'child');if(closed||state.failure_code!==null)return;
      if(m.type==='fetch'){
        if(terminal||state.fetch_requests!==0||fetchPending||m.aborted||signal.aborted)fail();
        fetchPending=true;fetchController=new AbortController();state.fetch_requests++;
        const response=await fetchFn(m.url,{...m.init,signal:fetchController.signal});
        if(types.isProxy(response)||!(response instanceof Response))fail();
        const body=responseGet('body',response);
        if(closed||state.failure_code!==null){if(body)discard(()=>ReadableStream.prototype.cancel.call(body));return;}
        const status=responseGet('status',response),headers=copySdkHeaders(responseGet('headers',response));
        let text=null;
        if(body){bodyReader=ReadableStream.prototype.getReader.call(body);const bytes=new Uint8Array(cfg.responseLimit);let usedBytes=0;
          for(;;){const item=await bodyReader.read();if(closed||state.failure_code!==null)return;
            const part=sdkData(item,['done','value'],['value']);if(typeof part.done!=='boolean')fail();if(part.done)break;
            if(types.isProxy(part.value)||![Uint8Array.prototype,Buffer.prototype].includes(Object.getPrototypeOf(part.value)))fail();
            const count=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Uint8Array.prototype),'byteLength').get.call(part.value);
            if(usedBytes+count>cfg.responseLimit)fail();for(let i=0;i<count;i++)bytes[usedBytes+i]=part.value[i];usedBytes+=count;
          }
          text=Buffer.from(bytes.buffer,0,usedBytes).toString('base64');bodyReader.releaseLock();bodyReader=undefined;
        }
        if(closed||state.failure_code!==null)return;
        await send({type:'response',seq:1,status,headers,body:text},()=>{fetchPending=false;responseSent=true;});
      }else if(m.type==='raw'){
        if(terminal||!responseSent||rawPending||m.seq!==rawSeq+1)fail();rawPending=true;rawSeq=m.seq;
        await rawCallback(m.metadata);if(closed||state.failure_code!==null)return;
        await send({type:'raw-ack',seq:m.seq},()=>{rawPending=false;});
      }else{
        if(terminal||fetchPending||rawPending)fail();terminal=true;state.phase='settled';queued=m.event;
        if(waiting){waiting.resolve({value:queued,done:false});queued=undefined;waiting=undefined;}
      }
    }catch{failed();}
  }
  function onData(chunk){if(closed||state.failure_code!==null)return;try{for(const text of decoder.push(chunk)){const message=processJson(text);discard(()=>accept(message));}}catch{failed();}}
  function normalizeContext(value){try{if(closed)fail();const copy=freeze(copySdkContext(value));contexts.add(copy);return copy;}catch{fail();}}
  function streamSimple(value,context,options){
    if(used||closed){failed();throw processFailure();}used=true;
    try{
      const model=freeze(copySdkModel(value,sharedModel));if(!contexts.has(context))fail();const copy=freeze(copySdkContext(context));
      const opts=sdkData(options,['apiKey','maxRetries','maxTokens','temperature','timeoutMs','signal','fetch','onProviderStreamEvent',...(compiled?['reasoning']:[])]);
      const privateOptions=freeze(copySdkOptions({apiKey:opts.apiKey,maxRetries:opts.maxRetries,maxTokens:opts.maxTokens,temperature:opts.temperature,timeoutMs:opts.timeoutMs,...(compiled?{reasoning:opts.reasoning}:{})},sharedModel));
      if(privateOptions.maxTokens>model.maxTokens)fail();
      if(types.isProxy(opts.signal)||!(opts.signal instanceof AbortSignal)||typeof opts.fetch!=='function'||types.isProxy(opts.fetch)||typeof opts.onProviderStreamEvent!=='function'||types.isProxy(opts.onProviderStreamEvent))fail();
      signal=opts.signal;fetchFn=opts.fetch;rawCallback=opts.onProviderStreamEvent;
      if(signal.aborted)fail();
      scope=sdkData(cfg.processFactory(new URL('./sdk-process-entry.ts',import.meta.url),freeze({env:{OPENAI_LOG:'off'},execArgv:['--experimental-import-meta-resolve'],argv:['--risk-review-sdk-process',...(compiled?['--risk-review-shared-model='+compiled.model_identity]:[])],stdio:['ignore','pipe','pipe','pipe','pipe']})),['child','terminate']);
      if(typeof scope.terminate!=='function'||types.isProxy(scope.terminate))fail();
      child=scope.child;if(!child||!child.stdio?.[3]||!child.stdio?.[4])fail();state.child_started=true;state.phase='running';
      decoder=createReviewFrameReader(FRAME_LIMITS);writer=processWriter(child.stdio[3]);
      child.on('error',onError);child.on('exit',onExit);for(const output of [child.stdout,child.stderr]){output?.on('data',drop);output?.on('error',onError);}
      for(const pipe of [child.stdio[3],child.stdio[4]])pipe.on('error',onError);child.stdio[4].on('data',onData);child.stdio[4].on('end',onEnd);
      onAbort=()=>{if(terminal&&state.failure_code===null)discard(terminate);else failed();};signal.addEventListener('abort',onAbort,{once:true});if(signal.aborted)onAbort();
      if(state.failure_code===null)discard(()=>send({type:'run',seq:1,anchor:cfg.anchor,model,context:copy,options:privateOptions,...(compiled?{sharedModel}:{})}).catch(failed));
      return Object.freeze({[Symbol.asyncIterator](){return this;},next(){if(state.failure_code!==null)return Promise.reject(processFailure());if(queued){const value=queued;queued=undefined;return Promise.resolve({value,done:false});}if(terminal)return Promise.resolve({done:true,value:undefined});if(waiting){failed();return Promise.reject(processFailure());}return new Promise((resolve,reject)=>{waiting={resolve,reject};});},return(){if(!terminal)failed();closed=true;return Promise.resolve(terminate()).then(()=>({done:true,value:undefined}));}});
    }catch{failed();throw processFailure();}
  }
  function close(){if(!terminal&&child)failed();closed=true;return terminate();}
  return Object.freeze({sdk:Object.freeze({normalizeContext,streamSimple}),close,snapshot});
}
