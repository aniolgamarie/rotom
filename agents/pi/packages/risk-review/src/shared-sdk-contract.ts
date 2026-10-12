// 纯重新验证/编译组件；不加载SDK、读取账户/env、执行wire或授予产品资格。
import { types } from "node:util";
import { prepareSharedReviewModel } from "./shared-model.ts";
const INVALID = "PI_RISK_REVIEW_SDK_CONTRACT_INVALID";
const UNSUPPORTED = "PI_RISK_REVIEW_SDK_CONTRACT_UNSUPPORTED";
const MAX_NODES = 128, MAX_DEPTH = 8, MAX_BYTES = 262144;
function fail(code = INVALID): never {
  const error = new Error(code); Object.assign(error, {code}); throw error;
}
function copy(value: unknown) {
  let nodes = 0, bytes = 0;
  const add = (count: number) => { bytes += count; if (bytes > MAX_BYTES) fail(); };
  function string(value: string) {
    if (value.length > 32768 || /\p{Cs}/u.test(value)) fail();
    add(Buffer.byteLength(JSON.stringify(value), "utf8")); return value;
  }
  function visit(value: any, depth: number): any {
    if (++nodes > MAX_NODES || depth > MAX_DEPTH) fail();
    if (value === null) { add(4); return null; }
    if (typeof value === "boolean") { add(5); return value; }
    if (typeof value === "string") return string(value);
    if (typeof value === "number") { if (!Number.isFinite(value)) fail(); add(32); return value; }
    if (!value || typeof value !== "object" || types.isProxy(value)) fail();
    const proto = Object.getPrototypeOf(value);
    if (proto === Array.prototype) {
      const length = Object.getOwnPropertyDescriptor(value, "length")?.value;
      if (!Number.isSafeInteger(length) || length < 0 || length > MAX_NODES || Reflect.ownKeys(value).length !== length + 1) fail();
      const result = []; add(2 + length);
      for (let index = 0; index < length; index++) {
        const property = Object.getOwnPropertyDescriptor(value, String(index));
        if (!property?.enumerable || !Object.hasOwn(property, "value")) fail();
        result.push(visit(property.value, depth + 1));
      }
      return result;
    }
    if (proto !== Object.prototype) fail();
    const keys = Reflect.ownKeys(value);
    if (keys.length > MAX_NODES || keys.some(key => typeof key !== "string")) fail();
    const result = {}; add(2 + keys.length * 2);
    for (const key of keys) {
      const property = Object.getOwnPropertyDescriptor(value, key);
      if (!property?.enumerable || !Object.hasOwn(property, "value")) fail();
      string(key as string);
      Object.defineProperty(result, key, {value:visit(property.value, depth + 1),enumerable:true,writable:true,configurable:true});
    }
    return result;
  }
  return visit(value, 0);
}
function closed(value: any, fields: string[]) {
  if (!value || typeof value !== "object" || Object.getPrototypeOf(value) !== Object.prototype || Object.keys(value).length !== fields.length || fields.some(key => !Object.hasOwn(value,key))) fail();
}
function canonical(value: any): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object") return "{" + Object.keys(value).sort().map(key=>JSON.stringify(key)+":"+canonical(value[key])).join(",") + "}";
  return JSON.stringify(value);
}
function freeze(value: any): any {
  if (value && typeof value === "object") { for (const child of Object.values(value)) freeze(child); Object.freeze(value); }
  return value;
}
function compile(options: unknown) {
  const cfg = copy(options);
  closed(cfg,["prepared","route","configuration_identity"]);
  const prepared = cfg.prepared;
  closed(prepared,["base_model","sdk_model","request_policy","model_identity"]);
  // 全部原始字段都复制为有界own data后，重新构造并比较完整四字段而非只认hash。
  const policy = prepared.request_policy;
  if (!policy || typeof policy !== "object" || Object.getPrototypeOf(policy) !== Object.prototype) fail();
  let checked;
  try {
    checked = prepareSharedReviewModel({descriptor:prepared.base_model,route:cfg.route,configuration_identity:cfg.configuration_identity,
      token_limits:{input_tokens:policy.input_tokens,output_tokens:policy.output_tokens}});
  } catch (error) {
    fail((error as {code?: string})?.code === "PI_RISK_REVIEW_MODEL_UNSUPPORTED" ? UNSUPPORTED : INVALID);
  }
  if (canonical(prepared) !== canonical(checked)) fail();
  const model = checked.sdk_model, base = checked.base_model;
  let shape = "openai-chat-text";
  if (base.reasoning) {
    if (base.compat?.thinkingFormat !== "deepseek" || base.thinkingLevelMap?.off === null) fail(UNSUPPORTED);
    shape = "deepseek-chat-text-disabled";
  }
  return freeze({sdk_model:copy(model),sdk_options:{maxRetries:0,maxTokens:checked.request_policy.output_tokens,temperature:0,reasoning:"off"},
    wire_contract:{schema_version:1,api:"openai-completions",base_url:cfg.route.base_url,model:model.id,shape,output_tokens:checked.request_policy.output_tokens},
    model_identity:checked.model_identity});
}
export function compileSharedReviewSdkContract(options: unknown) {
  try { return compile(options); }
  catch (error) { fail((error as {code?:string})?.code === UNSUPPORTED ? UNSUPPORTED : INVALID); }
}
