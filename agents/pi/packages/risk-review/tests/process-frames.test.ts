// 纯字节协议；不启动进程/SDK/Worker，也不证明JSON或RPC来源。
import assert from "node:assert/strict";
import { test } from "node:test";
import { encodeReviewFrame, createReviewFrameReader } from "../src/process-frames.ts";
const code="PI_RISK_REVIEW_FRAME_INVALID";
const limits=()=>({maxFrameBytes:524288,maxFrames:100,maxTotalBytes:8388608});
const reader=(extra={})=>createReviewFrameReader({...limits(),...extra});
const invalid=(fn)=>assert.throws(fn,e=>e instanceof Error && e.message===code && e.code===code && !Object.hasOwn(e,"cause"));
const join=(...parts)=>{const out=new Uint8Array(parts.reduce((n,p)=>n+p.length,0));let pos=0;for(const p of parts){out.set(p,pos);pos+=p.length;}return out;};
const frame=(text,cap=524288)=>encodeReviewFrame(text,{maxFrameBytes:cap});
test("big endian encoder is fresh and UTF8 preserving",()=>{
  const a=frame("a中🙂"),b=frame("a中🙂");assert.notEqual(a,b);
  assert.deepEqual([...a.slice(0,4)],[0,0,0,8]);assert.equal(new TextDecoder().decode(a.slice(4)),"a中🙂");
  a[4]=0;assert.equal(b[4],97);
});
test("one-byte fragmentation handles every UTF8 and header boundary",()=>{
  const r=reader(),data=join(frame("a中🙂"),frame("second"));const out=[];
  for(const byte of data)out.push(...r.push(Uint8Array.of(byte)));
  assert.deepEqual(out,["a中🙂","second"]);assert.deepEqual(r.end(),{frames:2,bytes:data.length,buffered_bytes:0,failed:false,finished:true});
});
test("many frames in one chunk and arbitrary empty push",()=>{
  const r=reader();assert.deepEqual(r.push(new Uint8Array()),[]);
  assert.deepEqual(r.push(join(frame("one"),frame("二"),frame("three"))),["one","二","three"]);r.end();
});
test("large maximum frame fragmented without aliasing caller",()=>{
  const r=reader(),original="x".repeat(524287)+"z", data=frame(original),out=[];
  for(let p=0;p<data.length;p+=257){const chunk=data.slice(p,p+257);out.push(...r.push(chunk));chunk.fill(0);}
  assert.deepEqual(out,[original]);assert.equal(r.end().bytes,524292);
});
test("EOF empty and repeated end are idempotent and snapshots frozen copies",()=>{
  const r=reader(),before=r.snapshot();assert.ok(Object.isFrozen(before));
  assert.deepEqual(r.end(),{frames:0,bytes:0,buffered_bytes:0,failed:false,finished:true});
  assert.deepEqual(r.end(),r.snapshot());assert.notEqual(r.snapshot(),r.snapshot());assert.equal(before.finished,false);
});
for(const cut of [1,2,3,4,5,6]) test("partial EOF is sticky at byte "+cut,()=>{
  const r=reader();r.push(frame("abc").slice(0,cut));assert.equal(r.snapshot().buffered_bytes,cut);
  invalid(()=>r.end());invalid(()=>r.end());invalid(()=>r.push(new Uint8Array()));assert.equal(r.snapshot().failed,true);
});
for(const header of [[0,0,0,0],[0,8,0,1],[255,255,255,255]]) test("invalid declared length "+header.join(","),()=>{
  const r=reader();invalid(()=>r.push(Uint8Array.from(header)));assert.equal(r.snapshot().bytes,4);invalid(()=>r.end());
});
for(const raw of [[0xc0,0xaf],[0xed,0xa0,0x80],[0xf4,0x90,0x80,0x80],[0xe2,0x82],[0xff]]) test("fatal UTF8 "+raw.join(","),()=>{
  const r=reader();invalid(()=>r.push(Uint8Array.from([0,0,0,raw.length,...raw])));assert.equal(r.snapshot().failed,true);invalid(()=>r.push(frame("ok")));
});
test("frame budget checked before receiving another payload",()=>{
  const r=reader({maxFrames:1});assert.deepEqual(r.push(frame("first")),["first"]);
  invalid(()=>r.push(Uint8Array.of(0,0,0,1)));assert.equal(r.snapshot().frames,1);
});
test("total budget counts header and permits exact boundary",()=>{
  const r=reader({maxTotalBytes:5});assert.deepEqual(r.push(frame("a")),["a"]);assert.equal(r.end().bytes,5);
  const s=reader({maxTotalBytes:4});invalid(()=>s.push(frame("a")));assert.equal(s.snapshot().bytes,5);
});
test("declared pending payload cannot reserve beyond remaining total budget",()=>{
  const r=reader({maxTotalBytes:6});invalid(()=>r.push(Uint8Array.of(0,0,0,3)));assert.equal(r.snapshot().bytes,4);
});
test("remaining budget after earlier frame accounts full next header",()=>{
  const r=reader({maxTotalBytes:10});assert.deepEqual(r.push(frame("a")),["a"]);
  invalid(()=>r.push(Uint8Array.of(0,0,0,2)));assert.equal(r.snapshot().bytes,9);
});
test("budget rejects whole received chunk without delivering partial successes",()=>{
  const r=reader({maxTotalBytes:9});invalid(()=>r.push(join(frame("a"),frame("b"))));assert.equal(r.snapshot().frames,0);
});
for(const raw of ["", "\ud800", "\udfff", "a\ud800b", 1, null, {}, new String("x")])test("encoder rejects invalid input "+String(typeof raw),()=>invalid(()=>frame(raw)));
test("encoding cap measures bytes, not UTF16 units",()=>{invalid(()=>frame("中",2));assert.equal(frame("中",3).length,7);});
for(const target of ["encoder","reader"])for(const fault of ["unknown","getter","proxy","symbol","null-proto","array"])test(target+" options reject "+fault+" without traps",()=>{
  let touched=0;let opts=target==="encoder"?{maxFrameBytes:20}:limits();
  if(fault==="unknown")opts.extra=1;
  if(fault==="getter")Object.defineProperty(opts,"maxFrameBytes",{enumerable:true,get(){touched++;return 20;}});
  if(fault==="proxy")opts=new Proxy(opts,{ownKeys(){touched++;throw Error("PRIVATE");}});
  if(fault==="symbol")opts[Symbol("secret")]=1;
  if(fault==="null-proto")opts=Object.assign(Object.create(null),opts);
  if(fault==="array")opts=[];
  invalid(()=>target==="encoder"?encodeReviewFrame("x",opts):createReviewFrameReader(opts));assert.equal(touched,0);
});
for(const [key,values]of Object.entries({maxFrameBytes:[0,524289,true,1.1,NaN],maxFrames:[0,1000001,true,Infinity],maxTotalBytes:[0,8388609,true,1.1]}))for(const value of values)test("invalid "+key+"="+value,()=>invalid(()=>reader({[key]:value})));
for(const value of [null,[],new Uint16Array(3),new DataView(new ArrayBuffer(3)),"private"])test("nonbyte chunk is sticky "+typeof value,()=>{
  const r=reader();invalid(()=>r.push(value));invalid(()=>r.push(frame("okay")));invalid(()=>r.end());
});
test("Proxy chunk rejected before any trap",()=>{
  let calls=0;const r=reader(),value=new Proxy(new Uint8Array(3),{get(){calls++;throw Error("PRIVATE");},getPrototypeOf(){calls++;throw Error("PRIVATE");}});
  invalid(()=>r.push(value));assert.equal(calls,0);
});
test("byte arrays intrinsic access avoids own getters, custom methods and species",()=>{
  const r=reader(),chunk=frame("okay");let calls=0;
  for(const key of ["length","byteLength","buffer","subarray","slice","constructor"])Object.defineProperty(chunk,key,{get(){calls++;throw Error("PRIVATE");}});
  assert.deepEqual(r.push(chunk),["okay"]);assert.equal(calls,0);r.end();
});
test("native Buffer accepted without invoking patched methods or species",()=>{
  const r=reader(),chunk=Buffer.from(frame("buffer"));let calls=0;
  Object.defineProperty(chunk,"constructor",{get(){calls++;throw Error("PRIVATE");}});
  Object.defineProperty(chunk,"subarray",{get(){calls++;throw Error("PRIVATE");}});
  assert.deepEqual(r.push(chunk),["buffer"]);assert.equal(calls,0);
});
test("typedarray subclass rejected without species",()=>{
  let calls=0;class Evil extends Uint8Array {static get [Symbol.species](){calls++;throw Error("PRIVATE");}}
  const r=reader();invalid(()=>r.push(new Evil(5)));assert.equal(calls,0);
});
test("push after end, even empty, is sticky and privacy-preserving",()=>{
  const r=reader();r.push(frame("SECRET_BODY_SENTINEL"));r.end();invalid(()=>r.push(new Uint8Array()));invalid(()=>r.end());
  const snapshot=r.snapshot();assert.deepEqual(Object.keys(snapshot).sort(),["buffered_bytes","bytes","failed","finished","frames"]);
  assert.equal(JSON.stringify(snapshot).includes("SECRET_BODY_SENTINEL"),false);assert.equal(snapshot.failed,true);
});
test("BOM is text, not discarded decoder metadata",()=>{
  const r=reader();assert.deepEqual(r.push(frame("\ufeffpayload")),["\ufeffpayload"]);r.end();
});
test("native byte view offset excludes unrelated backing data",()=>{
  const raw=frame("view"),backing=new Uint8Array(raw.length+20);backing.fill(255);backing.set(raw,7);
  const r=reader();assert.deepEqual(r.push(new Uint8Array(backing.buffer,7,raw.length)),["view"]);
  assert.equal(r.end().bytes,raw.length);
});
test("header and pending payload budgets survive all split combinations",()=>{
  const raw=join(frame("é"),frame("abc"));
  for(let cut=0;cut<=raw.length;cut++) {
    const r=reader({maxTotalBytes:raw.length});
    const decoded=[...r.push(raw.slice(0,cut)),...r.push(raw.slice(cut))];
    assert.deepEqual(decoded,["é","abc"]);assert.equal(r.end().bytes,raw.length);
  }
});
