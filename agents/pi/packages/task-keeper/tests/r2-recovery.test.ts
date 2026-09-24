import { test, assert, acceptance, observerArtifact } from "./recorded-test.ts";
import { parseConfig } from "../src/config.ts";
import { resolveRecoveryTarget, resolveRecoveryPolicy, localRetryDelay } from "../src/policies/recovery.ts";
import { classify } from "../src/reliability/classifier.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { Store } from "../src/store/database.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";
import { setImmediate as flush } from "node:timers/promises";
function record(ac: string, variant: string, facts: unknown, body: () => void, level = "U") {
  acceptance(ac, variant, { level, observer: level === "S" ? "sqlite-and-controller-dispatch" : "independent-policy-expectations", predicate: `${ac}.${variant}`, artifact: observerArtifact(`${ac}-${variant}`, facts) }, body);
}
test("[U] layered recovery policies replace curves and retain field and rule provenance across provider names", () => {
  for (const provider of ["alpha", "renamed-provider"]) {
    const config = parseConfig({ recovery: { policies: { defaults: { rules: [{code:"LIMIT",category:"frequency_limit"}] }, providers: {
      [provider]: { quotaBackoff: ["5m"], rules: [{code:"LIMIT",category:"resource_pressure"}], models: { slow: {quotaBackoff:["1h"], rules:[{code:"LIMIT",category:"window_quota"}]} } }
    } } } });
    for (const [variant, target, interval, source, category] of [
      ["defaults", {provider:"elsewhere",model:"any"},60000,"defaults","frequency_limit"],
      ["provider", {provider,model:"any"},300000,`provider:${provider}`,"resource_pressure"],
      ["model", {provider,model:"slow"},3600000,`model:${provider}/slow`,"window_quota"],
      ["unrelated-model", {provider,model:"other"},300000,`provider:${provider}`,"resource_pressure"],
    ] as const) {
      const result = resolveRecoveryPolicy(config, target);
      const check = () => { assert.equal(result.intervals[0],interval); assert.equal(result.sources.quotaBackoff,source);
        assert.equal(classify({code:"LIMIT",message:"limit",stream:"error"},result.policy.rules,0).category,category);
        assert.equal(result.sources.requestTimeout,"defaults"); assert.equal(result.policy.maxNetworkAttempts,2); };
      if (provider === "alpha") record("AC03",variant,result,check); else check();
    }
    if(provider === "renamed-provider")record("AC03","renamed-provider",resolveRecoveryPolicy(config,{provider,model:"slow"}),()=>{
      assert.equal(resolveRecoveryPolicy(config,{provider,model:"slow"}).intervals[0],3600000);
    });
  }
});
test("[S] same quota pool preserves independent five-minute and hour retry clocks and shared two-hour server floor", async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(), sent: string[] = [];
  const config = parseConfig({enabled:true,features:{interactiveRecovery:true},quotaGroups:{shared:{classifier:"http",rules:[],baseIntervalMs:1,tailIntervalsMs:[1]}},
    quotaBindings:[{provider:"p",quotaGroup:"shared"}],recovery:{policies:{defaults:{positiveJitterRatio:0},providers:{p:{models:{fast:{quotaBackoff:["5m"]},slow:{quotaBackoff:["1h"]}}}}}}});
  const snapshot = (model: string): InteractiveSnapshot => ({sessionId:model,leafId:"failed",provider:"p",model,idle:true,pendingMessages:false,terminationKnown:true,certified:true,blockedReasons:[],transportIdentity:"endpoint"});
  const fastSnapshot=snapshot("fast"), slowSnapshot=snapshot("slow");
  const make=(state:InteractiveSnapshot)=>new RecoveryController(store,config,{snapshot:()=>({...state}),abort(){},continue:async()=>{sent.push(state.model);return{nativeId:`${state.model}-${sent.length}`};}},clock,()=>0);
  const fast=make(fastSnapshot),slow=make(slowSnapshot);t.after(()=>{fast.dispose();slow.dispose();store.close();});
  fast.settled({status:429,message:"limit",stream:"error"});slow.settled({status:429,message:"limit",stream:"error"});
  record("AC04","local-5m-and-1h",{fast:fast.state(),slow:slow.state(),shared:store.get("incidents","shared")},()=>{
    assert.equal(fast.state().notBefore,1300000);assert.equal(slow.state().notBefore,4600000);
    assert.equal(store.get<{notBefore:number}>("incidents","shared")!.notBefore,0);assert.equal(fast.state().quotaGroup,slow.state().quotaGroup);
  },"S");
  clock.advance(299999);await flush();assert.deepEqual(sent,[]);clock.advance(1);await flush();assert.deepEqual(sent,["fast"]);
  fastSnapshot.leafId="failed-again";fast.settled({status:429,message:"shared wait",headers:{"retry-after":"7200"},stream:"error"});
  const floor=8500000;
  clock.advance(3300000);await flush();assert.deepEqual(sent,["fast"]);
  record("AC04","shared-2h-floor",{fast:fast.state(),slow:slow.state()},()=>{assert.equal(fast.state().notBefore,floor);assert.equal(slow.state().notBefore,floor);assert.equal(store.get<{notBefore:number}>("incidents","shared")!.notBefore,floor);},"S");
  clock.advance(floor-clock.now()-1);await flush();assert.deepEqual(sent,["fast"]);clock.advance(1);await flush();assert.equal(sent.length,2);
  record("AC04","before-at-after",{sent,now:clock.now(),claims:store.claims()},()=>{assert.equal(sent.length,2);assert.equal(store.claims().filter(claim=>claim.resource_id==="quota-shared").length,1);},"S");
});
test("[U] local jitter cannot truncate a server floor and quota identity does not depend on retry policy",()=>{
  const config=parseConfig({recovery:{policies:{defaults:{quotaBackoff:["1h"],positiveJitterRatio:1}}}}),target={provider:"p",model:"m",transportIdentity:"endpoint"};
  const before=resolveRecoveryTarget(config,target);
  record("AC04","jitter-cap",before,()=>{assert.equal(localRetryDelay(before,0,1),3600000);assert.equal(localRetryDelay(before,99,1),3600000);});
  config.recovery.policies.defaults.quotaBackoff=["5m"];
  assert.equal(resolveRecoveryTarget(config,target).route.quotaGroup,before.route.quotaGroup);
  assert.equal(resolveRecoveryTarget(config,{...target,transportIdentity:"changed"}).route.quotaGroup,before.route.quotaGroup);
  assert.notEqual(resolveRecoveryTarget(config,{...target,transportIdentity:"changed"}).route.transportDomain,before.route.transportDomain);
});
test("[S] current-model identity changes revoke queued recovery and legacy shared floors survive new policies", async t=>{
  const store=new Store(isolatedDirectory(t)),clock=new FakeClock();
  const config=parseConfig({enabled:true,features:{interactiveRecovery:true},quotaGroups:{old:{classifier:"http",rules:[],baseIntervalMs:100,tailIntervalsMs:[100]}},quotaBindings:[{provider:"p",quotaGroup:"old"}],recovery:{policies:{defaults:{quotaBackoff:["5m"],positiveJitterRatio:0}}}});
  const snapshot:InteractiveSnapshot={sessionId:"identity",leafId:"leaf",provider:"p",model:"one",transportIdentity:"endpoint",idle:true,pendingMessages:false,terminationKnown:true,certified:true,blockedReasons:[]};
  let sends=0;const controller=new RecoveryController(store,config,{snapshot:()=>({...snapshot}),abort(){},continue:async()=>{sends++;return{nativeId:"native"};}},clock,()=>0);
  t.after(()=>{controller.dispose();store.close();});
  const floor=clock.now()+7200000;store.put("incidents","old",{id:"legacy-incident",status:"OPEN",notBefore:floor,failures:4});
  controller.settled({status:429,message:"quota",stream:"error"});
  record("AC04","legacy-floor",controller.state(),()=>{assert.equal(controller.state().notBefore,floor);assert.equal(controller.state().incidentId,"legacy-incident");assert.equal(controller.state().quotaGroup,"old");},"S");
  snapshot.model="two";clock.advance(7200000);await flush();
  record("AC03","identity-change",controller.state(),()=>{assert.equal(sends,0);assert.equal(controller.state().status,"BLOCKED");assert.equal(controller.state().reason,"route_not_allowed");assert.equal(controller.state().history.length,1);},"S");
});
for(const variant of ["temporary","permanent","network-limit","unknown-reset-pause","unknown-reset-wait","unknown-writer"] as const)
test(`[S] generic recovery classification ${variant} respects policy and execution evidence`,async t=>{
  const store=new Store(isolatedDirectory(t)),clock=new FakeClock();
  const config=parseConfig({enabled:true,features:{interactiveRecovery:true},recovery:{policies:{defaults:{quotaBackoff:["100ms"],positiveJitterRatio:0,maxNetworkAttempts:0,
    unknownReset:variant==="unknown-reset-wait"?"configured-backoff":"pause",rules:[{code:"Window",category:"window_quota"},{code:"Retryable",category:"resource_pressure"}]}}}});
  const snapshot:InteractiveSnapshot={sessionId:variant,leafId:"failure",provider:"generic",model:"generic",idle:true,pendingMessages:false,terminationKnown:variant!=="unknown-writer",certified:true,blockedReasons:[]};
  let sent=0;const controller=new RecoveryController(store,config,{snapshot:()=>({...snapshot}),abort(){},continue:async()=>{sent++;return{nativeId:"continued"};}},clock,()=>0);
  t.after(()=>{controller.dispose();store.close();});
  controller.settled({status:variant==="permanent"?401:variant==="network-limit"?503:429,code:variant.startsWith("unknown-reset")?"Window":"Retryable",message:"observed error",stream:"error"});
  // A binding rule for resource pressure does not turn a selected network sample into quota.
  if(variant==="network-limit"){
    controller.beginUserTurn();snapshot.leafId="network";controller.settled({status:503,message:"network unavailable",stream:"error"});
  }
  clock.advance(100);await flush();const state=controller.state();
  record("AC05",variant,{state,sent},()=>{
    const expected=variant==="temporary"||variant==="unknown-reset-wait";
    assert.equal(sent,expected?1:0);assert.equal(state.status,expected?"RUNNING":"BLOCKED");
    if(variant==="permanent")assert.equal(state.reason,"auth_billing_policy");
    if(variant==="unknown-reset-pause")assert.equal(state.reason,"quota_reset_unknown");
    if(variant==="network-limit"){assert.equal(state.reason,"network_attempts_exhausted");assert.equal(state.networkAttempts,1);}
    if(variant==="unknown-writer")assert.equal(state.reason,"execution_or_mutator_unknown");
  },"S");
});
for(const [variant,interval,ms] of [["1h","1h",3600000],["2h","2h",7200000]] as const)
test(`[S] local ${variant} retry waits through the exact boundary without repeated ticks`,async t=>{
  const store=new Store(isolatedDirectory(t)),clock=new FakeClock(),start=clock.now();
  const config=parseConfig({enabled:true,features:{interactiveRecovery:true},recovery:{policies:{defaults:{quotaBackoff:[interval],maxLocalInterval:interval,positiveJitterRatio:0}}}});
  let calls=0;const controller=new RecoveryController(store,config,{snapshot:()=>({sessionId:variant,leafId:"failed",provider:"p",model:"m",idle:true,pendingMessages:false,terminationKnown:true,certified:true,blockedReasons:[]}),abort(){},continue:async()=>{calls++;return{nativeId:"once"};}},clock,()=>0);
  t.after(()=>{controller.dispose();store.close();});controller.settled({status:429,message:"limit",stream:"error"});
  clock.advance(ms-1);await flush();assert.equal(calls,0);clock.advance(1);await flush();await controller.tick();await controller.tick();
  record("AC07",variant,{state:controller.state(),now:clock.now(),calls},()=>{assert.equal(controller.state().notBefore,start+ms);assert.equal(calls,1);assert.equal(controller.state().attempts,1);},"S");
});
