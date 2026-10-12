// 私有单Worker桥；receipt/anchor真实性来自可信caller，不在这里自证。
import { Worker } from "node:worker_threads";
import { types } from "node:util";
import { isAbsolute, normalize } from "node:path";
import { compileSharedReviewSdkContract } from "./shared-sdk-contract.ts";
export const SDK_ERROR = "PI_RISK_REVIEW_SDK_INVALID";
export function sdkFailure() { const error = new Error(SDK_ERROR); error.code = SDK_ERROR; return error; }
export function sdkData(value, keys, optional = []) {
  if (!value || typeof value !== "object" || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype) throw sdkFailure();
  const names = Reflect.ownKeys(value);
  if (names.some(k => typeof k !== "string" || !keys.includes(k)) || keys.some(k => !optional.includes(k) && !names.includes(k))) throw sdkFailure();
  const copy = {};
  for (const key of names) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key);
    if (!descriptor.enumerable || !Object.hasOwn(descriptor, "value")) throw sdkFailure();
    copy[key] = descriptor.value;
  }
  return copy;
}
export function sdkText(value, bound, empty = false) {
  return typeof value === "string" && (empty || value.length > 0) && value.length <= bound
    && !/[\p{Cs}]/u.test(value) && Buffer.byteLength(value, "utf8") <= bound;
}
export function sdkArray(value, maximum) {
  if (!Array.isArray(value) || types.isProxy(value) || Object.getPrototypeOf(value) !== Array.prototype
    || value.length > maximum || Reflect.ownKeys(value).length !== value.length + 1) throw sdkFailure();
  return Array.from({ length: value.length }, (_, i) => {
    const descriptor = Object.getOwnPropertyDescriptor(value, String(i));
    if (!descriptor?.enumerable || !Object.hasOwn(descriptor, "value")) throw sdkFailure();
    return descriptor.value;
  });
}
const integer = (v, low, high) => Number.isSafeInteger(v) && v >= low && v <= high;
function sharedContract(value) {
  try { return compileSharedReviewSdkContract(value); } catch { throw sdkFailure(); }
}
function freezeShared(value) {
  if (value && typeof value === "object") { Object.values(value).forEach(freezeShared); Object.freeze(value); }
  return value;
}
export function copySdkModel(value, sharedModel) {
  if (sharedModel !== undefined) {
    sharedContract(sharedModel);
    const cfg = sdkData(sharedModel, ["prepared", "route", "configuration_identity"]);
    const prepared = sdkData(cfg.prepared, ["base_model", "sdk_model", "request_policy", "model_identity"]);
    return sharedContract({ ...cfg, prepared: { ...prepared, sdk_model: value } }).sdk_model;
  }
  const model = sdkData(value, ["api", "provider", "id", "name", "baseUrl", "reasoning", "input", "cost", "contextWindow", "maxTokens", "compat"]);
  if (model.api !== "openai-completions" || !sdkText(model.provider,128) || !sdkText(model.id,128) || model.name !== model.id
    || !sdkText(model.baseUrl,2048) || model.reasoning !== false || !integer(model.contextWindow,4097,10000000) || !integer(model.maxTokens,1,4096)) throw sdkFailure();
  const input = sdkArray(model.input,1); if (input.length !== 1 || input[0] !== "text") throw sdkFailure();
  const cost = sdkData(model.cost,["input","output","cacheRead","cacheWrite"]);
  if (Object.values(cost).some(v => typeof v !== "number" || !Number.isFinite(v) || v < 0 || v > 1000000)) throw sdkFailure();
  const compat = sdkData(model.compat,["supportsStore","supportsDeveloperRole","supportsUsageInStreaming","maxTokensField"]);
  if (compat.supportsStore !== false || compat.supportsDeveloperRole !== false || compat.supportsUsageInStreaming !== true || compat.maxTokensField !== "max_tokens") throw sdkFailure();
  return {...model,input,cost,compat};
}
export function copySdkContext(value) {
  const context = sdkData(value,["systemPrompt","messages"]); const messages = sdkArray(context.messages,1);
  if (!sdkText(context.systemPrompt,32768,true) || messages.length !== 1) throw sdkFailure();
  const message = sdkData(messages[0],["role","content","timestamp"]);
  if (message.role !== "user" || !sdkText(message.content,32768) || typeof message.timestamp !== "number" || !Number.isFinite(message.timestamp)) throw sdkFailure();
  return {systemPrompt:context.systemPrompt,messages:[message]};
}
export function copySdkOptions(value, sharedModel) {
  const contract = sharedModel === undefined ? null : sharedContract(sharedModel);
  const options = sdkData(value,["apiKey","maxRetries","maxTokens","temperature","timeoutMs", ...(contract ? ["reasoning"] : [])]);
  if (!sdkText(options.apiKey,8192) || options.maxRetries !== 0 || !integer(options.maxTokens,1,4096)
    || options.temperature !== 0 || !integer(options.timeoutMs,1,300000)) throw sdkFailure();
  if (contract && (options.reasoning !== "off" || options.maxTokens !== contract.sdk_options.maxTokens
      || options.maxRetries !== contract.sdk_options.maxRetries || options.temperature !== contract.sdk_options.temperature)) throw sdkFailure();
  return options;
}
export function copySdkHeaders(value) {
  if (types.isProxy(value)) throw sdkFailure();
  const entries = value instanceof Headers ? [...Headers.prototype.entries.call(value)]
    : Object.entries(sdkData(value,Reflect.ownKeys(value)));
  if (entries.length > 32) throw sdkFailure();
  const headers = {}; let length = 0;
  for (const [key,text] of entries) {
    if (!sdkText(key,128) || !/^[a-zA-Z0-9-]+$/.test(key) || !sdkText(text,key.toLowerCase() === "authorization" ? 8199 : 8192,true) || /[\r\n]/.test(text)
      || Object.hasOwn(headers,key.toLowerCase())) throw sdkFailure();
    length += key.length + Buffer.byteLength(text,"utf8"); if (length > 32768) throw sdkFailure();
    headers[key.toLowerCase()] = text;
  }
  return headers;
}
export function copySdkMetadata(value) {
  const data = sdkData(value,["model","usage"],["model","usage"]);
  if (Object.hasOwn(data,"model") && !sdkText(data.model,128)) throw sdkFailure();
  if (Object.hasOwn(data,"usage")) {
    const usage = sdkData(data.usage,["prompt_tokens","completion_tokens","total_tokens","prompt_tokens_details"],["prompt_tokens","completion_tokens","total_tokens","prompt_tokens_details"]);
    for (const key of ["prompt_tokens","completion_tokens","total_tokens"]) if (Object.hasOwn(usage,key) && !integer(usage[key],0,10010000)) throw sdkFailure();
    if (Object.hasOwn(usage,"prompt_tokens_details")) {
      usage.prompt_tokens_details = sdkData(usage.prompt_tokens_details,["cached_tokens"],["cached_tokens"]);
      if (Object.hasOwn(usage.prompt_tokens_details,"cached_tokens") && !integer(usage.prompt_tokens_details.cached_tokens,0,10000000)) throw sdkFailure();
    }
    data.usage = usage;
  }
  return data;
}
export function copySdkEvent(value) {
  const event = sdkData(value,["type","message"],["message"]);
  if (event.type === "error" || event.type === "toolcall") { if (Object.hasOwn(event,"message")) throw sdkFailure(); return event; }
  if (event.type !== "done") throw sdkFailure();
  const message = sdkData(event.message,["api","provider","model","stopReason","content"]);
  for (const key of ["api","provider","model","stopReason"]) if (!sdkText(message[key],128)) throw sdkFailure();
  let length = 0;
  message.content = sdkArray(message.content,16).map(item => {
    const part = sdkData(item,["type","text"],["text"]);
    if (part.type === "thinking") { if (Object.hasOwn(part,"text")) throw sdkFailure(); return part; }
    if (part.type !== "text" || !sdkText(part.text,8192,true)) throw sdkFailure();
    length += Buffer.byteLength(part.text,"utf8"); if (length > 8192) throw sdkFailure(); return part;
  });
  return {type:"done",message};
}
const discard = fn => { try { Promise.resolve(fn()).catch(()=>{}); } catch {} };
export function createIsolatedReviewSdk(options) {
  const cfg = sdkData(options,["anchor","workerFactory","sharedModel"],["workerFactory","sharedModel"]);
  if (!sdkText(cfg.anchor,4096) || cfg.anchor.includes("\0") || !isAbsolute(cfg.anchor) || normalize(cfg.anchor) !== cfg.anchor || !cfg.anchor.endsWith("/package.json")
    || cfg.workerFactory !== undefined && (typeof cfg.workerFactory !== "function" || types.isProxy(cfg.workerFactory))) throw sdkFailure();
  const factory = cfg.workerFactory ?? ((url, settings) => new Worker(url, settings));
  let sharedModel, contract;
  if (cfg.sharedModel !== undefined) {
    // 同步全量own-data验证先于clone；不得触发未知getter或降到legacy模式。
    contract = sharedContract(cfg.sharedModel);
    sharedModel = freezeShared(structuredClone(cfg.sharedModel));
  }
  const contexts = new WeakSet();
  const state = {phase:"prepared",worker_started:false,termination_started:false,worker_terminated:false,fetch_requests:0,failure_code:null,product_gate:false};
  let used = false, closed = false, worker, terminatePromise, signal, onAbort, fetchController, queued, waiting, terminal = false, rawPending = false, rawSeq = 0;
  const snapshot = () => Object.freeze({...state});
  const dropOutput = () => {};
  const releaseOutput = () => {
    for(const output of [worker?.stdout,worker?.stderr]) output?.removeListener("data",dropOutput);
  };
  const detach = () => {
    signal?.removeEventListener("abort",onAbort);
    if (worker) { worker.removeListener("message",onMessage); worker.removeListener("exit",onExit); }
  };
  const releaseErrors = () => {
    worker?.removeListener("error",onError); worker?.removeListener("messageerror",onError);
  };
  const terminate = () => {
    if (terminatePromise) return terminatePromise;
    detach(); fetchController?.abort();
    if (!worker) return Promise.resolve();
    state.termination_started = true;
    discard(()=>worker.postMessage({schema_version:1,type:"cancel",seq:1}));
    try { terminatePromise = Promise.resolve(worker.terminate()).then(()=>{state.worker_terminated=true;releaseOutput();releaseErrors();},()=>{state.failure_code=SDK_ERROR;}); }
    catch { state.failure_code=SDK_ERROR; terminatePromise=Promise.resolve(); }
    return terminatePromise;
  };
  const fail = () => {
    state.failure_code = SDK_ERROR; state.phase = "failed"; terminal = true; queued = undefined;
    if (waiting) { waiting.reject(sdkFailure()); waiting=undefined; }
    discard(terminate);
  };
  let fetchFn, rawCallback;
  const send = (message, transfer=[]) => { worker.postMessage({schema_version:1,...message},transfer); };
  const onError = () => {
    // terminate尚未确认时仍吞掉Worker原错误；不得成为无监听error或递归terminate。
    if(!state.termination_started) fail();
  };
  const onExit = () => { if (!state.termination_started) fail(); };
  const onMessage = async incoming => {
    if (closed || state.failure_code !== null) return;
    try {
      const message = sdkData(incoming,["schema_version","type","seq","url","init","aborted","metadata","event"],["url","init","aborted","metadata","event"]);
      if (message.schema_version !== 1 || !integer(message.seq,1,1000000)) throw sdkFailure();
      if (message.type === "fetch") {
        sdkData(incoming,["schema_version","type","seq","url","init","aborted"],["aborted"]);
        if (terminal || message.seq !== 1 || state.fetch_requests !== 0 || !sdkText(message.url,2048)
          || Object.hasOwn(message,"aborted") && typeof message.aborted !== "boolean") throw sdkFailure();
        const init = sdkData(message.init,["method","headers","body"]);
        if (init.method !== "POST" || !sdkText(init.body,131072)) throw sdkFailure();
        init.headers = copySdkHeaders(init.headers); fetchController = new AbortController(); init.signal=fetchController.signal;
        if (message.aborted || signal.aborted) throw sdkFailure();
        state.fetch_requests++;
        const response = await fetchFn(message.url,init);
        if (types.isProxy(response) || !(response instanceof Response)) throw sdkFailure();
        if (state.failure_code !== null || closed || terminal) { if(response.body) discard(()=>response.body.cancel()); return; }
        try {
          const headers = {}; for (const [key,value] of Headers.prototype.entries.call(response.headers)) headers[key]=value;
          const copyHeaders = copySdkHeaders(headers);
          send({type:"response",seq:1,status:response.status,headers:copyHeaders,body:response.body},response.body?[response.body]:[]);
        } catch { if(response.body)discard(()=>response.body.cancel()); throw sdkFailure(); }
      } else if (message.type === "fetch-abort") {
        sdkData(incoming,["schema_version","type","seq"]);
        if (message.seq !== 1 || state.fetch_requests !== 1) throw sdkFailure(); fetchController?.abort(); fail();
      } else if (message.type === "raw") {
        sdkData(incoming,["schema_version","type","seq","metadata"]);
        if (rawPending || message.seq !== rawSeq+1) throw sdkFailure();
        rawPending=true; rawSeq=message.seq; const metadata=copySdkMetadata(message.metadata);
        await rawCallback(metadata); rawPending=false;
        if (!closed && state.failure_code === null) send({type:"raw-ack",seq:rawSeq});
      } else if (message.type === "event") {
        sdkData(incoming,["schema_version","type","seq","event"]);
        if (terminal || rawPending || message.seq !== 1) throw sdkFailure();
        queued=copySdkEvent(message.event); terminal=true; state.phase="settled";
        if(waiting){waiting.resolve({done:false,value:queued});waiting=undefined;queued=undefined;}
      } else throw sdkFailure();
    } catch { fail(); }
  };
  const normalizeContext = value => {
    if (closed) throw sdkFailure(); const copy=copySdkContext(value);
    Object.freeze(copy.messages[0]);Object.freeze(copy.messages);Object.freeze(copy);contexts.add(copy);return copy;
  };
  const streamSimple = (value,context,options) => {
    if (used || closed) throw sdkFailure(); used=true;
    try {
      const model=copySdkModel(value,sharedModel);
      if (!contexts.has(context)) throw sdkFailure(); const copiedContext=copySdkContext(context);
      const opts=sdkData(options,["apiKey","signal","fetch","maxRetries","maxTokens","temperature","timeoutMs","onProviderStreamEvent",...(contract?["reasoning"]:[])]);
      if (types.isProxy(opts.signal) || !(opts.signal instanceof AbortSignal) || [opts.fetch,opts.onProviderStreamEvent].some(fn=>typeof fn!=="function"||types.isProxy(fn))) throw sdkFailure();
      const privateOptions=copySdkOptions({apiKey:opts.apiKey,maxRetries:opts.maxRetries,maxTokens:opts.maxTokens,temperature:opts.temperature,timeoutMs:opts.timeoutMs,...(contract?{reasoning:opts.reasoning}:{})},sharedModel);
      if(privateOptions.maxTokens>model.maxTokens)throw sdkFailure(); signal=opts.signal;fetchFn=opts.fetch;rawCallback=opts.onProviderStreamEvent;
      onAbort=()=>{
        // 正常终态已交付后，transport finally的abort只清理Worker；不抹掉真正的sticky失败。
        if(terminal && state.failure_code===null) discard(terminate); else fail();
      };signal.addEventListener("abort",onAbort,{once:true});if(signal.aborted)throw sdkFailure();
      worker=factory(new URL("./sdk-worker-entry.ts",import.meta.url),{env:{OPENAI_LOG:"off"},execArgv:["--experimental-import-meta-resolve"],argv:[],stdout:true,stderr:true,
        workerData:{schema_version:1,anchor:cfg.anchor,...(contract?{shared_model_identity:contract.model_identity}:{})},resourceLimits:{maxOldGenerationSizeMb:64,maxYoungGenerationSizeMb:16,stackSizeMb:4}});
      state.worker_started=true;state.phase="running";
      worker.on("message",onMessage);worker.on("error",onError);worker.on("exit",onExit);worker.on("messageerror",onError);
      for(const output of [worker.stdout,worker.stderr]) { output?.on("data",dropOutput);output?.resume?.(); }
      send({type:"run",seq:1,model,context:copiedContext,options:privateOptions,...(contract?{sharedModel}:{})});
    } catch { fail();throw sdkFailure(); }
    let taken=false;
    const iterator={next(){
      if(state.failure_code!==null)return Promise.reject(sdkFailure());
      if(queued){const value=queued;queued=undefined;taken=true;return Promise.resolve({done:false,value});}
      if(terminal&&taken)return Promise.resolve({done:true});
      if(terminal){taken=true;return Promise.resolve({done:true});}
      if(waiting){fail();return Promise.reject(sdkFailure());}
      return new Promise((resolve,reject)=>{waiting={resolve:result=>{taken=true;resolve(result);},reject};});
    },async return(){closed=true;terminal=true;state.phase=state.failure_code?"failed":"closed";if(waiting){waiting.resolve({done:true});waiting=undefined;}await terminate();return {done:true};},[Symbol.asyncIterator](){return this;}};
    return iterator;
  };
  const close=async()=>{closed=true;terminal=true;state.phase=state.failure_code?"failed":"closed";queued=undefined;if(waiting){waiting.resolve({done:true});waiting=undefined;}await terminate();};
  return Object.freeze({sdk:Object.freeze({normalizeContext,streamSimple}),close,snapshot});
}
