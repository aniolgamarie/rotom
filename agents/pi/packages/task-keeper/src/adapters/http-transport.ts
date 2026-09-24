// ordinary 交互恢复保留原观测接口；managed 只使用下列有账本的发送边界。
export { ManagedHttpTransport } from "@agentcfg/pi-runtime/managed-http-transport";
import { scrub } from "../reliability/classifier.ts";
import { ContractError, newId } from "../contracts/primitives.ts";

const delegationKey = Symbol.for("task-keeper.http-fetch-delegates.v1");
const registry = globalThis as typeof globalThis & { [key: symbol]: unknown };
const delegates = (registry[delegationKey] ??= new WeakMap<typeof fetch, typeof fetch>()) as WeakMap<typeof fetch, typeof fetch>;
/** Only wrappers created here can attest that every forwarded call retains a known inner guard. */
export function fetchDelegatesTo(expected: unknown, current: typeof fetch = globalThis.fetch): boolean {
  if (typeof expected !== "function") return false;
  const seen = new Set<typeof fetch>();
  for (let depth = 0; depth < 32 && !seen.has(current); depth++) {
    if (current === expected) return true;
    seen.add(current); const parent = delegates.get(current); if (!parent) return false; current = parent;
  }
  return false;
}

export interface HttpTarget { baseUrl: string; model: string; token: number }
export interface HttpAttempt { id: string; url: string; model: string | null; token: number; secrets: string[]; payload?: unknown }
export interface HttpHooks {
  requestTimeoutMs?: () => number;
  requestTimedOut?: (attempt:HttpAttempt) => void;
  priorGuard?: (method: string) => typeof fetch | null;
  before?: (attempt: HttpAttempt) => void;
  recheck?: (attempt: HttpAttempt) => void;
  invokeWithin?: (attempt: HttpAttempt, invoke: () => void) => void;
  response?: (attempt: HttpAttempt, response: { status: number; headers: Record<string, string>; errorBody?: string }) => void;
  error?: (attempt: HttpAttempt, invoked: boolean, error: unknown) => void;
  metering?: (attempt:HttpAttempt,zeroReported:boolean)=>void;
  meteringEnabled?:()=>boolean;
}

/** Bounded lookahead on errors, then return every original byte to the SDK without a tee branch. */
async function observeError(response: Response, secrets: string[]): Promise<{ response: Response; errorBody?: string }> {
  if (response.status < 400 || !response.body) return { response };
  const reader = response.body.getReader(); void reader.closed.catch(() => {});
  const chunks: Uint8Array[] = []; let size = 0, ended = false;
  let pending: Promise<ReadableStreamReadResult<Uint8Array>> | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const expired = Symbol("expired");
  const deadline = new Promise<typeof expired>(resolve => { timer = setTimeout(() => resolve(expired), 250); });
  try {
    while (size <= 8192) {
      pending = reader.read();
      const item = await Promise.race([pending, deadline]);
      if (item === expired) break;
      pending = null;
      if (item.done) { ended = true; break; }
      chunks.push(item.value); size += item.value.byteLength;
    }
  } catch (error) { void reader.cancel().catch(() => {}); throw error; }
  finally { if (timer) clearTimeout(timer); }
  const errorBody = ended && size <= 8192 ? scrub(Buffer.concat(chunks).toString("utf8"), secrets) : undefined;
  let index = 0;
  const body = new ReadableStream<Uint8Array>({
    async pull(controller) {
      if (index < chunks.length) { controller.enqueue(chunks[index++]); return; }
      if (ended) { controller.close(); return; }
      try {
        const next = await (pending ?? reader.read()); pending = null;
        if (next.done) { ended = true; controller.close(); } else controller.enqueue(next.value);
      } catch (error) { controller.error(error); }
    },
    cancel(reason) { return reader.cancel(reason); },
  });
  const forwarded = new Response(body, { status: response.status, statusText: response.statusText, headers: response.headers });
  for (const key of ["url", "redirected", "type"] as const) Object.defineProperty(forwarded, key, { value: response[key] });
  return { response: forwarded, ...(errorBody === undefined ? {} : { errorBody }) };
}

/** Optional metering presence observer. Pull-driven, bounded, and forwards every original byte. */
function observeMetering(response:Response,notify:(zero:boolean)=>void):Response {
  if(!response.body || !response.headers.get("content-type")?.includes("text/event-stream"))return response;
  const original=response.body,decoder=new TextDecoder();let reader:ReadableStreamDefaultReader<Uint8Array>|null=null,pending="",discarding=false;
  const line=(value:string)=>{if(!value.startsWith("data:"))return;try{const data=JSON.parse(value.slice(5).trim()),usage=data?.usage;
    if(usage && typeof usage==="object" && Object.hasOwn(usage,"prompt_tokens") && Object.hasOwn(usage,"completion_tokens"))notify(usage.prompt_tokens===0&&usage.completion_tokens===0&&(usage.prompt_tokens_details?.cached_tokens??usage.prompt_cache_hit_tokens??usage.cached_tokens??0)===0&&(usage.prompt_tokens_details?.cache_write_tokens??0)===0);
  }catch{/* Non-usage or malformed frames remain byte-for-byte available to the SDK. */}};
  const feed=(text:string)=>{for(const fragment of text.split(/(?<=\n)/)){const ends=fragment.endsWith("\n");if(!discarding){pending+=fragment;if(pending.length>65536){pending="";discarding=true;}}
    if(ends){if(!discarding)line(pending.trimEnd());pending="";discarding=false;}}};
  const body=new ReadableStream<Uint8Array>({async pull(controller){try{if(!reader){reader=original.getReader();void reader.closed.catch(()=>{});}const next=await reader.read();if(next.done){feed(decoder.decode());if(pending&&!discarding)line(pending);controller.close();}else{feed(decoder.decode(next.value,{stream:true}));controller.enqueue(next.value);}}catch(error){controller.error(error);}},cancel(reason){return reader?reader.cancel(reason):original.cancel(reason);}},{highWaterMark:0});
  const forwarded=new Response(body,{status:response.status,statusText:response.statusText,headers:response.headers});
  for(const key of ["url","redirected","type"] as const)Object.defineProperty(forwarded,key,{value:response[key]});return forwarded;
}

/** Keep the attempt deadline through the last response byte, including an idle stream. */
function deadlineBody(response:Response,finish:()=>void,onError:(error:unknown)=>void):Response {
  if(!response.body){finish();return response;}
  const original=response.body;let reader:ReadableStreamDefaultReader<Uint8Array>|null=null;
  const body=new ReadableStream<Uint8Array>({async pull(controller){
    try{reader??=original.getReader();void reader.closed.catch(()=>{});const next=await reader.read();
      if(next.done){finish();controller.close();}else controller.enqueue(next.value);
    }catch(error){finish();onError(error);controller.error(error);}
  },async cancel(reason){finish();await (reader?reader.cancel(reason):original.cancel(reason));}},{highWaterMark:0});
  const result=new Response(body,{status:response.status,statusText:response.statusText,headers:response.headers});
  for(const key of ["url","redirected","type"] as const)Object.defineProperty(result,key,{value:response[key]});return result;
}

/** Actual fetch boundary: no routing/header changes; metering observation is opt-in. */
export function installHttpTransport(target: () => HttpTarget | null, hooks: HttpHooks, denyOtherPosts: boolean | (() => boolean) = false, installGlobally = true) {
  const original = globalThis.fetch;
  let active = true, retiredProtected = false;
  const guarded = () => typeof denyOtherPosts === "function" ? denyOtherPosts() : denyOtherPosts;
  const synchronous = (fn: ((...args: any[]) => unknown) | undefined, ...args: unknown[]) => {
    if (!fn) return;
    if (fn.constructor.name === "AsyncFunction") throw new ContractError("ASYNC_HTTP_HOOK_NOT_SUPPORTED");
    const result = fn(...args);
    if (result && typeof (result as { then?: unknown }).then === "function") {
      void Promise.resolve(result).catch(() => {});
      throw new ContractError("ASYNC_HTTP_HOOK_NOT_SUPPORTED");
    }
  };
  const wrapped: typeof fetch = async (input, init) => {
    const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
    const priorGuard = hooks.priorGuard?.(method);
    if (priorGuard) return priorGuard(input, init);
    const protectedScope = guarded();
    if (!active) {
      if ((protectedScope || retiredProtected) && method === "POST") throw new ContractError("RETIRED_HTTP_SCOPE");
      return original(input, init);
    }
    const configured = target();
    const url = new URL(typeof input === "string" || input instanceof URL ? input : input.url);
    const expected = configured ? new URL(`${configured.baseUrl.replace(/\/$/, "")}/chat/completions`) : null;
    const matches = configured && expected && method === "POST" && url.origin === expected.origin && url.pathname === expected.pathname;
    if (!matches) {
      if (protectedScope && method === "POST") throw new ContractError("UNAPPROVED_HTTP_ROUTE");
      return original(input, init);
    }
    let model: string | null = null, payload: unknown;
    if (typeof init?.body === "string") {
      try { const body = JSON.parse(init.body); payload = body; if (typeof body.model === "string") model = body.model; } catch { /* Unsupported payloads cannot pass a strict gate. */ }
    }
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    const secrets: string[] = [];
    for (const key of ["authorization", "x-api-key", "api-key"]) {
      const value = headers.get(key); if (value) secrets.push(value, value.replace(/^Bearer\s+/i, ""));
    }
    const attempt: HttpAttempt = { id: newId("request"), url: `${url.origin}${url.pathname}`, model, token: configured.token, secrets, payload };
    const signal = init?.signal ?? (input instanceof Request ? input.signal : null);
    let invoked = false;
    let response: Response | null = null;
    let inFlight: Promise<Response> | undefined;
    let invocationOpen = false;
    let timer:ReturnType<typeof setTimeout>|undefined;let timeoutController:AbortController|undefined;let errorReported=false;
    const finish=()=>{if(timer){clearTimeout(timer);timer=undefined;}};
    const reportError=(error:unknown)=>{if(!errorReported){errorReported=true;synchronous(hooks.error,attempt,invoked,error);}};
    try {
      if (signal?.aborted) throw new ContractError("REQUEST_CANCELLED_BEFORE_SEND");
      synchronous(hooks.before, attempt);
      if (signal?.aborted) throw new ContractError("REQUEST_CANCELLED_BEFORE_SEND");
      synchronous(hooks.recheck, attempt);
      if (signal?.aborted) throw new ContractError("REQUEST_CANCELLED_BEFORE_SEND");
      const invoke = () => {
        if (!invocationOpen || invoked) throw new ContractError("HTTP_INVOCATION_SCOPE_CLOSED");
        if (signal?.aborted) throw new ContractError("REQUEST_CANCELLED_BEFORE_SEND");
        const timeout=hooks.requestTimeoutMs?.();
        if(timeout!==undefined){
          if(!Number.isSafeInteger(timeout)||timeout<=0||timeout>2147483647)throw new ContractError("INVALID_REQUEST_TIMEOUT");
          timeoutController=new AbortController();timer=setTimeout(()=>{
            const error=new ContractError("REQUEST_TIMEOUT");timeoutController!.abort(error);
            try{synchronous(hooks.requestTimedOut,attempt);}catch{/* Timeout still aborts the transport if recording fails. */}
          },timeout);timer.unref();
        }
        invoked = true;
        const requestSignal=timeoutController?AbortSignal.any([timeoutController.signal,...(signal?[signal]:[])]):signal;
        inFlight = original(input, (protectedScope||timeoutController) ? { ...init, ...(requestSignal?{signal:requestSignal}:{}), ...(protectedScope?{redirect:"error" as const}:{}) } : init);
      };
      invocationOpen = true;
      try {
        if (hooks.invokeWithin) synchronous(hooks.invokeWithin, attempt, invoke); else invoke();
        if (!invoked) throw new ContractError("HTTP_INVOCATION_NOT_PERFORMED");
      } finally { invocationOpen = false; }
      response = await inFlight!;
      const headers: Record<string, string> = {};
      for (const name of ["retry-after", "date", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"]) {
        const value = response.headers.get(name); if (value !== null) headers[name] = value;
      }
      if(timeoutController)response=deadlineBody(response,finish,reportError);
      const observed = await observeError(response, secrets); response = observed.response;
      const errorBody = observed.errorBody;
      synchronous(hooks.response, attempt, { status: response.status, headers, ...(errorBody === undefined ? {} : { errorBody }) });
      return hooks.metering && (hooks.meteringEnabled?.()??true) && response.status<400 ? observeMetering(response,zero=>synchronous(hooks.metering,attempt,zero)) : response;
    } catch (error) {
      finish();
      if (!response && inFlight) void inFlight.then(value => value.body?.cancel()).catch(() => {});
      if (response?.body && !response.body.locked) await response.body.cancel().catch(() => {});
      reportError(error);
      throw error;
    }
  };
  delegates.set(wrapped, original);
  if (installGlobally) globalThis.fetch = wrapped;
  return {
    fetch: wrapped,
    intact: () => active && (!installGlobally || globalThis.fetch === wrapped),
    dispose: () => { retiredProtected ||= guarded(); active = false; if (installGlobally && globalThis.fetch === wrapped) globalThis.fetch = original; },
  };
}
