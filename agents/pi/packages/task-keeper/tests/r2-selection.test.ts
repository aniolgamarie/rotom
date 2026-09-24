import {test,assert,acceptance,observerArtifact} from "./recorded-test.ts";
import {configured} from "./fixtures/config.ts";
import {Store} from "../src/store/database.ts";
import {UsageLedger,sdkUsage} from "../src/usage/ledger.ts";
import {modelComparison} from "../src/usage/comparison.ts";
import {selectModel} from "../src/policies/selection.ts";
import {isolatedDirectory} from "./helpers.ts";
import {businessDigest} from "../src/store/maintenance.ts";
function setup(root:string){const config=configured();config.routes.backup={...config.routes.primary,model:"backup"};config.allowedRoutes.push("backup");config.modelPolicy.candidates=["primary","backup"];config.modelPolicy.defaultPreference=["primary","backup"];config.modelPolicy.ranking="history-cost";const store=new Store(root),ledger=new UsageLedger(store);return{config,store,ledger};}
function sample(ledger:UsageLedger,id:string,model:string,cost:number|null,status:"accepted"|"failed"|"finished"="accepted",currency="USD"){
  const task=ledger.begin({id,sessionId:id,title:id,workflow:"fix",comparisonGroup:"same",contractDigest:"same-contract"},1);
  const fact=sdkUsage({generationId:id,provider:"fixture-provider",model,modelVersion:"v1",role:"worker",startedAt:1,endedAt:2,usage:{input:10,output:1,cacheRead:0,cacheWrite:0,...(cost===null?{}:{cost:{total:cost}})},attemptIds:[id],outcome:status==="failed"?"failure":"success",source:"fixed-history-fixture"});if(fact.cost.amount!==null)fact.cost.currency=currency;ledger.record(fact,task.id);ledger.finish(task.id,status,"verifier",3);
}
function select(f:ReturnType<typeof setup>,eligible:Record<string,string[]>={primary:[],backup:[]}){const history=modelComparison(f.ledger);return selectModel(f.config,{automatic:true,manual:null,at:100,eligible,history,comparisonKey:history[0]?.key,modelVersions:{primary:"v1",backup:"v1"}});}
function credit(variant:string,observed:unknown,check:()=>void){acceptance("AC23",variant,{level:"S",observer:"fixed-history-ledger-and-pure-decision",predicate:variant,artifact:observerArtifact(`history-${variant}`,observed)},check);}
test("[S] historical cost cannot override hard capability and includes failed investment",t=>{
  const f=setup(isolatedDirectory(t));t.after(()=>f.store.close());
  for(let i=0;i<5;i++){sample(f.ledger,`a-${i}`,"fixture-model",2);sample(f.ledger,`b-${i}`,"backup",10);}sample(f.ledger,"a-failed","fixture-model",100,"failed");
  const failureInclusive=select(f);credit("failure-inclusive",{history:modelComparison(f.ledger),failureInclusive},()=>{assert.equal(failureInclusive.selected,"backup");assert.equal(failureInclusive.reason,"history-cost");assert.equal(failureInclusive.sampleIds.length,11);});
  const hard=select(f,{primary:[],backup:["profile-not-certified"]});credit("hard-capability",hard,()=>{assert.equal(hard.selected,"primary");assert.ok(hard.rejected.some(row=>row.id==="backup"&&row.reasons.includes("profile-not-certified")));});
});
test("[S] sample counts 4, 5 and 6 have a fixed threshold and missing costs force configured fallback",t=>{
  const observed:Array<{count:number;result:ReturnType<typeof select>}>=[];
  for(const count of [4,5,6]){const f=setup(isolatedDirectory(t));t.after(()=>f.store.close());for(let i=0;i<count;i++){sample(f.ledger,`a-${i}`,"fixture-model",10);sample(f.ledger,`b-${i}`,"backup",1);}observed.push({count,result:select(f)});}
  credit("low-sample",observed,()=>{assert.equal(observed[0].result.selected,"primary");assert.equal(observed[0].result.reason,"history-insufficient-configured-order");assert.equal(observed[1].result.selected,"backup");assert.equal(observed[2].result.selected,"backup");});
  const f=setup(isolatedDirectory(t));t.after(()=>f.store.close());for(let i=0;i<5;i++){sample(f.ledger,`a-${i}`,"fixture-model",10);sample(f.ledger,`b-${i}`,"backup",i===4?null:1);}const result=select(f);
  credit("unknown",result,()=>{assert.equal(result.selected,"primary");assert.equal(result.reason,"history-insufficient-configured-order");});
});
test("[S] mixed currencies cannot be ranked as if they were one unit",t=>{
  const f=setup(isolatedDirectory(t));t.after(()=>f.store.close());for(let i=0;i<5;i++){sample(f.ledger,`a-${i}`,"fixture-model",10);sample(f.ledger,`b-${i}`,"backup",1,"accepted","CNY");}const result=select(f);
  credit("currency",result,()=>{assert.equal(result.selected,"primary");assert.equal(result.reason,"history-insufficient-configured-order");});
});
test("[S] a known quality failure stays excluded despite missing prices and fallback preference",t=>{
  const f=setup(isolatedDirectory(t));t.after(()=>f.store.close());f.config.modelPolicy.defaultPreference=["backup","primary"];
  for(let i=0;i<5;i++){sample(f.ledger,`a-${i}`,"fixture-model",10);sample(f.ledger,`b-${i}`,"backup",null,"failed");}sample(f.ledger,"b-unverified","backup",null,"finished");
  const before=businessDigest(f.store.db),result=select(f),after=businessDigest(f.store.db);
  credit("quality-floor",{result,before,after},()=>{assert.equal(result.selected,"primary");assert.ok(result.rejected.some(row=>row.id==="backup"&&row.reasons.includes("below-minimum-success-rate")));assert.equal(before,after);});
});
