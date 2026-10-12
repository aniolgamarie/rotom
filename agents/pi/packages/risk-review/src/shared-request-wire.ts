// 纯wire适配：保留数字词法，仅在显式DeepSeek分支删除已验证的thinking。
import { types } from "node:util";
import { compileSharedReviewSdkContract } from "./shared-sdk-contract.ts";
import { createReviewRequestValidator } from "./request-wire.ts";
const CODE="PI_RISK_REVIEW_SHARED_REQUEST_INVALID";
function fail():never {const error=new Error(CODE);Object.assign(error,{code:CODE});throw error;}
function fields(value:any, plainOnly=false) {
  if(!value||typeof value!=="object"||types.isProxy(value))fail();
  const proto=Object.getPrototypeOf(value);
  if(proto!==Object.prototype&&(plainOnly||proto!==null))fail();
  const out=Object.create(null);
  for(const key of Reflect.ownKeys(value)) {
    const d=Object.getOwnPropertyDescriptor(value,key);
    if(typeof key!=="string"||!d?.enumerable||!Object.hasOwn(d,"value"))fail();
    out[key]=d.value;
  }
  return out;
}
function exact(value:any,keys:string[]) {return Object.keys(value).length===keys.length&&keys.every(k=>Object.hasOwn(value,k));}
class Numeric {token:string;constructor(token:string){this.token=token;}}
function parse(raw:any) {
  if(typeof raw!=="string"||!raw.length||raw.length>131072||/\p{Cs}/u.test(raw)||Buffer.byteLength(raw,"utf8")>131072)fail();
  let i=0,nodes=0;
  function space(){while(i<raw.length&&/[ \t\r\n]/.test(raw[i]))i++;}
  function string(){
    const start=i++;let escaped=false;
    while(i<raw.length){const c=raw[i++];if(!escaped&&c==='"'){
      const v=JSON.parse(raw.slice(start,i));if(/\p{Cs}/u.test(v))fail();return v;
    }if(!escaped&&c==="\\")escaped=true;else escaped=false;}
    fail();
  }
  function value(depth:number):any {
    if(depth>4||++nodes>64)fail();space();const c=raw[i];
    if(c==='"')return string();
    if(c==="{"){
      i++;space();const out=Object.create(null);if(raw[i]==="}"){i++;return out;}
      while(true){space();if(raw[i]!=='"')fail();const key=string();
        if(["__proto__","constructor","prototype"].includes(key)||Object.hasOwn(out,key))fail();
        space();if(raw[i++]!==":")fail();out[key]=value(depth+1);space();const end=raw[i++];
        if(end==="}")return out;if(end!==",")fail();}
    }
    if(c==="["){
      i++;space();const out=[];if(raw[i]==="]"){i++;return out;}
      while(true){if(out.length>=8)fail();out.push(value(depth+1));space();const end=raw[i++];if(end==="]")return out;if(end!==",")fail();}
    }
    for(const [word,v]of [["true",true],["false",false],["null",null]])if(raw.startsWith(word,i)){i+=word.length;return v;}
    const number=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(raw.slice(i));
    if(!number)fail();i+=number[0].length;return new Numeric(number[0]);
  }
  const out=value(0);space();if(i!==raw.length)fail();return out;
}
function encode(value:any):string {
  if(value instanceof Numeric)return value.token;
  if(Array.isArray(value))return "["+value.map(encode).join(",")+"]";
  if(value&&typeof value==="object")return "{"+Object.keys(value).map(k=>JSON.stringify(k)+":"+encode(value[k])).join(",")+"}";
  return JSON.stringify(value);
}
export function createSharedReviewRequestValidator(options:any) {
  try {
    const cfg=fields(options,true);
    if(!exact(cfg,["prepared","route","configuration_identity","systemPrompt","userPrompt","expectedHeaders"]))fail();
    const contract=compileSharedReviewSdkContract({prepared:cfg.prepared,route:cfg.route,configuration_identity:cfg.configuration_identity});
    const wire=contract.wire_contract;
    const endpoint=new URL(wire.base_url.replace(/\/$/,"")+"/chat/completions").href;
    const validate=createReviewRequestValidator({endpoint,model:wire.model,systemPrompt:cfg.systemPrompt,userPrompt:cfg.userPrompt,maxTokens:wire.output_tokens,expectedHeaders:cfg.expectedHeaders});
    if(wire.shape==="openai-chat-text")return (input:any,init:any):boolean=>validate(input,init);
    if(wire.shape!=="deepseek-chat-text-disabled")fail();
    return (input:any,init:any):boolean=>{
      try {
        const request=fields(init);const data=parse(request.body);
        if(!data||typeof data!=="object"||Array.isArray(data)||data instanceof Numeric||!Object.hasOwn(data,"thinking"))return false;
        const thinking=data.thinking;
        if(!thinking||typeof thinking!=="object"||Array.isArray(thinking)||thinking instanceof Numeric||!exact(thinking,["type"])||thinking.type!=="disabled")return false;
        delete data.thinking;
        // Numeric.token原样写回，浮点/指数/舍入不可能转换成获准整数。
        return validate(input,{...request,body:encode(data)});
      }catch{return false;}
    };
  }catch{fail();}
}
