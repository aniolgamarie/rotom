import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync,mkdirSync,writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createOfficialResources } from "../official-resources.ts";
function fixture() {
 const root=mkdtempSync(join(tmpdir(),"command-guard-")),instanceRoot=join(root,"instance"),runtimeRoot=join(root,"runtime"),cwd=join(root,"project");
 for(const p of [instanceRoot,runtimeRoot,cwd])mkdirSync(p);
 const put=(base,path,body="selected")=>{const p=join(base,path);mkdirSync(join(p,".."),{recursive:true});writeFileSync(p,body);return p;};
 const disk=put(runtimeRoot,"packages/disk/index.mjs"),rules=put(instanceRoot,"pi-home/AGENTS.md"),append=put(instanceRoot,"pi-home/APPEND_SYSTEM.md");
 const state={rows:null,mutate:null,reloads:0};const options=new WeakMap();
 class Loader {
  constructor(o){options.set(this,o);Object.freeze(this);}
  async reload(){state.reloads++;const o=options.get(this);state.rows=[{path:join(runtimeRoot,"packages/disk"),resolvedPath:disk,handlers:new Map()}];
   for(const f of o.extensionFactories){const handlers=new Map();await f.factory({on(name,fn){const list=handlers.get(name)??[];list.push(fn);handlers.set(name,list);}});state.rows.push({path:`<inline:${f.name}>`,resolvedPath:`<inline:${f.name}>`,handlers});}
   state.mutate?.(state.rows);
  }
  getExtensions(){return {extensions:state.rows,errors:[],...(state.extra??{})};}
  getSkills(){return {skills:[],diagnostics:[]};} getPrompts(){return {prompts:[],diagnostics:[]};} getThemes(){return {themes:[],diagnostics:[]};}
  getAgentsFiles(){return {agentsFiles:[{path:rules,content:"selected"}]};}getSystemPrompt(){return undefined;}getSystemPromptSource(){return undefined;}
  getAppendSystemPrompt(){return ["selected"];}getAppendSystemPromptSources(){return [{path:append}];}extendResources(){}
 }
 Object.freeze(Loader.prototype);Object.freeze(Loader);
 const deny=()=>{throw Error("FIXED_DENY");};
 return {sdk:Object.freeze({DefaultResourceLoader:Loader}),manifest:{schema_version:1,engine:"node",bootstrap:false,plugins:["disk"],resources:{extensions:[],roles:[],skills:[],prompts:[],themes:[]},resource_ids:{extensions:{},roles:{},skills:{},prompts:{},themes:{}},options:{discovery:{project_resources:false}},project_resources:[],external_skills:[]},
 installed:{resources:{extensions:[{id:"disk",capability_id:"disk",path:"packages/disk"}],roles:[],skills:[],prompts:[],themes:[]}},instanceRoot,runtimeRoot,cwd,engine:"node",
 settingsManager:Object.freeze(Object.fromEntries(["getPackages","getExtensionPaths","getSkillPaths","getPromptTemplatePaths","getThemePaths"].map(k=>[k,()=>[]]))),
 extensionFactories:[{name:"rotom-command-boundary",factory:pi=>pi.on("user_bash",deny)}],commandGuard:{name:"rotom-command-boundary",handler:deny},deny,state};
}
test("selected disk user_bash cannot precede fixed guard",async()=>{
 const f=fixture();f.state.mutate=rows=>rows[0].handlers.set("user_bash",[()=>({result:{output:"unsafe"}})]);
 const {resourceLoader}=createOfficialResources(f);
 await assert.rejects(resourceLoader.reload(),/pi-resource-command-guard-conflict/);
});
test("exact original guard and empty nonowners accepted, maps untouched",async()=>{
 const f=fixture();f.state.mutate=rows=>{rows[0].handlers.set("user_bash",[]);rows[0].handlers.set("input",[()=>{}]);};
 const {resourceLoader}=createOfficialResources(f);await resourceLoader.reload();
 const rows=resourceLoader.getExtensions().extensions;
 assert.equal(rows[0].handlers.get("user_bash")[0],f.deny);assert.deepEqual(rows[1].handlers.get("user_bash"),[]);
 assert.throws(()=>rows[0].handlers.get("user_bash")[0](),/FIXED_DENY/);
 assert(Object.isFrozen(f.sdk));assert(Object.isFrozen(f.sdk.DefaultResourceLoader.prototype));
});
for(const side of ["before","after"])test(`nonowner ${side} guard conflict even after guard`,async()=>{
 const f=fixture();if(side==="after")f.extensionFactories.push({name:"late-extension",factory:pi=>pi.on("user_bash",()=>{})});
 else f.state.mutate=rows=>rows[0].handlers.set("user_bash",[()=>{}]);
 const {resourceLoader}=createOfficialResources(f);await assert.rejects(resourceLoader.reload(),/pi-resource-command-guard-conflict/);
 assert.throws(()=>resourceLoader.getExtensions(),/pi-resource-not-loaded/);
});
for(const fault of ["missing","empty","double","duplicate-guard","wrong-resolved","no-map","fake-map","map-proxy","map-getter","array-hole","array-getter","array-proxy","array-symbol","nonfunction","fn-proxy","row-getter","row-proxy"])test(`guard rejects ${fault} with no getter/proxy side effects`,async()=>{
 const f=fixture();let calls=0;
 const trap=()=>{calls++;throw Error("SYNTHETIC_PRIVATE");};
 f.state.mutate=rows=>{
  const g=rows[1];
  if(fault==="missing")g.handlers.delete("user_bash");
  if(fault==="empty")g.handlers.set("user_bash",[]);
  if(fault==="double")g.handlers.set("user_bash",[f.deny,f.deny]);
  if(fault==="duplicate-guard")rows.push({...g});
  if(fault==="wrong-resolved")g.resolvedPath="<inline:other>";
  if(fault==="no-map")delete g.handlers;
  if(fault==="fake-map")g.handlers={get:trap};
  if(fault==="map-proxy")g.handlers=new Proxy(g.handlers,{get:trap,getPrototypeOf:trap});
  if(fault==="map-getter")Object.defineProperty(g.handlers,"get",{get:trap});
  if(fault.startsWith("array-")){
   const list=[f.deny];if(fault==="array-hole")delete list[0];
   if(fault==="array-getter")Object.defineProperty(list,"0",{get:trap,enumerable:true});
   if(fault==="array-symbol")list[Symbol("private")]=1;
   g.handlers.set("user_bash",fault==="array-proxy"?new Proxy(list,{get:trap,getPrototypeOf:trap}):list);
  }
  if(fault==="nonfunction")g.handlers.set("user_bash",["not function"]);
  if(fault==="fn-proxy")g.handlers.set("user_bash",[new Proxy(f.deny,{apply:trap})]);
  if(fault==="row-getter")Object.defineProperty(g,"handlers",{get:trap,enumerable:true});
  if(fault==="row-proxy")rows[1]=new Proxy(g,{ownKeys:trap,get:trap});
 };
 const {resourceLoader}=createOfficialResources(f);await assert.rejects(resourceLoader.reload(),e=>e.message==="pi-resource-command-guard-invalid");
 assert.equal(calls,0);assert.throws(()=>resourceLoader.getExtensions(),/pi-resource-not-loaded/);
});
for(const fault of ["undefined","null","object","hole","proxy","getter","nonfunction"])test(`nonowner malformed user_bash ${fault} rejects`,async()=>{
 const f=fixture();let calls=0;const trap=()=>{calls++;throw Error("PRIVATE");};
 f.state.mutate=rows=>{
  let list= fault==="undefined"?undefined:fault==="null"?null:fault==="object"?{}:[()=>{}];
  if(fault==="hole")delete list[0];if(fault==="proxy")list=new Proxy(list,{get:trap});
  if(fault==="getter")Object.defineProperty(list,"0",{get:trap,enumerable:true});
  if(fault==="nonfunction")list=[0];rows[0].handlers.set("user_bash",list);
 };
 const {resourceLoader}=createOfficialResources(f);await assert.rejects(resourceLoader.reload(),/pi-resource-command-guard-invalid/);assert.equal(calls,0);
});
for(const fault of ["missing-name","missing-handler","unknown","proxy","getter","symbol","null-proto","wrong-name","proxy-function","nonfunction"])test(`trusted capability config ${fault} rejected before loader`,()=>{
 const f=fixture();let calls=0;const trap=()=>{calls++;throw Error("PRIVATE");};
 if(fault==="missing-name")delete f.commandGuard.name;
 if(fault==="missing-handler")delete f.commandGuard.handler;
 if(fault==="unknown")f.commandGuard.extra=true;
 if(fault==="proxy")f.commandGuard=new Proxy(f.commandGuard,{ownKeys:trap});
 if(fault==="getter")Object.defineProperty(f.commandGuard,"name",{enumerable:true,get:trap});
 if(fault==="symbol")f.commandGuard[Symbol("private")]=1;
 if(fault==="null-proto")Object.setPrototypeOf(f.commandGuard,null);
 if(fault==="wrong-name")f.commandGuard.name="not-selected";
 if(fault==="proxy-function")f.commandGuard.handler=new Proxy(f.deny,{apply:trap});
 if(fault==="nonfunction")f.commandGuard.handler={};
 assert.throws(()=>createOfficialResources(f),/pi-resource-command-guard-invalid/);assert.equal(calls,0);assert.equal(f.state.reloads,0);
});
test("captured private capability cannot be changed by caller after construction",async()=>{
 const f=fixture(),{resourceLoader}=createOfficialResources(f);f.commandGuard.handler=()=>{};f.commandGuard.name="changed";
 await resourceLoader.reload();assert.equal(resourceLoader.getExtensions().extensions[0].handlers.get("user_bash")[0],f.deny);
});
for(const getter of ["getExtensions","getSkills","getPrompts","getThemes","getAgentsFiles","getSystemPrompt","getAppendSystemPrompt"])test(`later handler registration invalidates ${getter}`,async()=>{
 const f=fixture(),{resourceLoader}=createOfficialResources(f);await resourceLoader.reload();
 f.state.rows[0].handlers.set("user_bash",[()=>{}]);assert.throws(()=>resourceLoader[getter](),/pi-resource-command-guard-conflict/);
});
test("later reload failure clears ready, original valid state can reload",async()=>{
 const f=fixture(),{resourceLoader}=createOfficialResources(f);await resourceLoader.reload();
 f.state.mutate=rows=>rows[0].handlers.set("user_bash",[()=>{}]);await assert.rejects(resourceLoader.reload(),/pi-resource-command-guard-conflict/);
 assert.throws(()=>resourceLoader.getExtensions(),/pi-resource-not-loaded/);
 f.state.mutate=null;await resourceLoader.reload();assert.equal(resourceLoader.getExtensions().extensions.length,2);
});
test("extendResources validates mutated registration before native extension",async()=>{
 const f=fixture(),{resourceLoader}=createOfficialResources(f);await resourceLoader.reload();f.state.rows[0].handlers.set("user_bash",[()=>{}]);
 assert.throws(()=>resourceLoader.extendResources({}),/pi-resource-command-guard-conflict/);
});
test("unbound standalone retains metadata-only loader compatibility",async()=>{
 const f=fixture();delete f.commandGuard;f.state.mutate=rows=>{for(const row of rows)delete row.handlers;};
 const {resourceLoader}=createOfficialResources(f);await resourceLoader.reload();assert.equal(resourceLoader.getExtensions().extensions.length,2);
});
test("missing loaded guard fails instead of relying on declared inline name",async()=>{
 const f=fixture();f.state.mutate=rows=>rows.pop();const {resourceLoader}=createOfficialResources(f);
 await assert.rejects(resourceLoader.reload(),/pi-resource-command-guard-invalid/);
});
test("handlers object accessor is never read",async()=>{
 const f=fixture();let calls=0;f.state.mutate=rows=>Object.defineProperty(rows[0],"handlers",{enumerable:true,get(){calls++;throw Error("PRIVATE");}});
 const {resourceLoader}=createOfficialResources(f);await assert.rejects(resourceLoader.reload(),/pi-resource-command-guard-invalid/);assert.equal(calls,0);
});

test("public late registration cannot handle user_bash ahead of observed guard", async () => {
  const f = fixture(), { resourceLoader } = createOfficialResources(f);
  await resourceLoader.reload();
  // 原生runner已取得公开数组后，另一个扩展通过合法pi.on追加自己的handler。
  const observed = resourceLoader.getExtensions(), disk = f.state.rows[0], guard = f.state.rows[1];
  let handled = 0;
  disk.handlers.set("user_bash", [() => { handled++; return { result: { output: "unsafe synthetic" } }; }]);
  const dispatch = async () => {
    for (const extension of observed.extensions) {
      for (const handler of [...(extension.handlers.get("user_bash") ?? [])]) {
        const result = await handler({ command: "synthetic", cwd: f.cwd, excludeFromContext: false }, {});
        if (result?.operations || result?.result) return result;
      }
    }
  };
  await assert.rejects(dispatch(), /FIXED_DENY/);
  assert.equal(handled, 0);
  assert.notEqual(observed.extensions[0], guard);
  assert.equal(observed.extensions[0].handlers.get("user_bash")[0], f.deny);
  assert.equal(f.state.rows[0], disk);
  assert.equal(f.state.rows[1], guard);
  assert.throws(() => resourceLoader.getExtensions(), /pi-resource-command-guard-conflict/);
});

test("guard-first projection preserves public metadata and other extension order", async () => {
  const f = fixture(), runtime = { flagValues: {} }, warnings = [], errors = [];
  f.state.extra = { runtime, warnings, errors };
  f.extensionFactories.push({ name: "second", factory() {} }, { name: "third", factory() {} });
  const { resourceLoader } = createOfficialResources(f);
  await resourceLoader.reload();
  const observed = resourceLoader.getExtensions(), original = [...f.state.rows];
  assert.equal(observed.runtime, runtime);
  assert.equal(observed.warnings, warnings);
  assert.equal(observed.errors, errors);
  assert.notEqual(observed.extensions[0], original[1]);
  assert.equal(observed.extensions[0].path, original[1].path);
  assert.deepEqual(observed.extensions.slice(1), [original[0], original[2], original[3]]);
  assert.deepEqual(f.state.rows, original);
  assert(Object.isFrozen(observed));
  assert(Object.isFrozen(observed.extensions));
});

for (const kind of ["sdk-wrapper", "unrelated-callback"]) test(kind + " is never used as the trusted command guard", async () => {
  const f = fixture(); let wrapperCalls = 0;
  const registered = (...args) => { wrapperCalls++; return kind === "sdk-wrapper" ? f.deny(...args) : { result: { output: "unsafe" } }; };
  f.state.mutate = rows => rows[1].handlers.set("user_bash", [registered]);
  const { resourceLoader } = createOfficialResources(f);
  await resourceLoader.reload();
  const originalGuard = f.state.rows[1], observed = resourceLoader.getExtensions();
  assert.equal(originalGuard.handlers.get("user_bash")[0], registered);
  assert.notEqual(observed.extensions[0].handlers, originalGuard.handlers);
  assert.throws(() => observed.extensions[0].handlers.get("user_bash")[0]({}), /FIXED_DENY/);
  assert.equal(wrapperCalls, 0);
  // runner已取得的自有投影仍固定拒绝，不共享后续SDK注册数组。
  originalGuard.handlers.set("user_bash", [() => { wrapperCalls++; return { result: {} }; }]);
  assert.throws(() => observed.extensions[0].handlers.get("user_bash")[0]({}), /FIXED_DENY/);
  assert.equal(wrapperCalls, 0);
});
