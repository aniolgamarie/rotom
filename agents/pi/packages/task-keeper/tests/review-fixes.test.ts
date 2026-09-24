import {mkdirSync,writeFileSync} from "node:fs";
import {join} from "node:path";
import {SubagentsAdapter} from "../src/adapters/subagents.ts";
import {test,assert} from "./recorded-test.ts";
import {configured} from "./fixtures/config.ts";
import {parseConfig,comparisonPolicyDigest,configurationPolicyDigest} from "../src/config.ts";
import {UsageCapture} from "../src/usage/capture.ts";
import {UsageLedger,sdkUsage} from "../src/usage/ledger.ts";
import {usageAccountPlan,repricingView} from "../src/usage/pricing.ts";
import {modelComparison} from "../src/usage/comparison.ts";
import {selectModel} from "../src/policies/selection.ts";
import {Store} from "../src/store/database.ts";
import {isolatedDirectory,listenLoopback} from "./helpers.ts";
import {installHttpTransport} from "../src/adapters/http-transport.ts";
import {createServer} from "node:http";
import {setTimeout as delay} from "node:timers/promises";
import type {PriceBook} from "../src/policies/configuration.ts";
const quote:PriceBook={id:"plan",provider:"p",model:"m",accountPlanRef:"subscription",currency:"CNY",source:"user quote",effectiveFrom:"2026-01-01T00:00:00Z",effectiveUntil:null,timing:"request-start",timezone:"UTC",rates:{input:"2",output:"1",cacheRead:"0",cacheWrite:"0"},windows:[]};
test("[S] unrelated quotes preserve SDK estimates and bound plans survive capture and repricing",t=>{
 const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());
 const config=parseConfig({usage:{accountPlans:[{provider:"p",accountPlanRef:"default"},{provider:"p",model:"m",accountPlanRef:"subscription"}]}});
 assert.equal(usageAccountPlan(config.usage,"p","other"),"default");assert.equal(usageAccountPlan(config.usage,"p","m"),"subscription");assert.equal(usageAccountPlan(config.usage,"other","m"),null);
 assert.throws(()=>parseConfig({usage:{accountPlans:[{provider:"p",accountPlanRef:"a"},{provider:"p",accountPlanRef:"b"}]}}),{code:"DUPLICATE_ACCOUNT_PLAN_BINDING"});
 for(const bound of [false,true]){const id=String(bound),capture=new UsageCapture(store),task=ledger.begin({sessionId:id,title:id});
 capture.begin({sessionId:id,taskId:task.id,provider:"p",model:"m",role:"parent",accountPlanRef:bound?usageAccountPlan(config.usage,"p","m"):null,quotes:[bound?quote:{...quote,provider:"other"}]},true);capture.attempt(id);
 const fact=capture.end({input:1000000,output:1000000,cacheRead:0,cacheWrite:0,cost:{total:.5}},"success")!;
 assert.equal(fact.cost.kind,"estimated");assert.equal(fact.cost.amount,bound?"3":"0.5");assert.equal(fact.cost.currency,bound?"CNY":"USD");
 if(bound){assert.equal(fact.accountPlanRef,"subscription");const next=repricingView([fact],[{...quote,id:"new",rates:{...quote.rates,input:"4"}}],Date.now());assert.equal(next.amounts.CNY,"5");assert.equal(fact.cost.amount,"3");}
 }
});
test("[S] enabling historical selection reuses measured samples without changing execution authorization",t=>{
 const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());const config=configured();config.routes.backup={...config.routes.primary,model:"backup"};config.allowedRoutes.push("backup");config.modelPolicy.candidates=["primary","backup"];config.modelPolicy.defaultPreference=["primary","backup"];config.modelPolicy.ranking="history-cost";
 const contract=comparisonPolicyDigest(config),oldAuthority=configurationPolicyDigest(config);
 for(const [model,cost] of [["fixture-model",10],["backup",1]] as const)for(let i=0;i<5;i++){const id=`${model}-${i}`,task=ledger.begin({id,sessionId:id,title:id,workflow:"fix",comparisonGroup:"same",contractDigest:contract},100);ledger.record(sdkUsage({generationId:id,provider:"fixture-provider",model,modelVersion:"v1",role:"worker",startedAt:100,endedAt:101,usage:{input:1000,output:100,cacheRead:0,cacheWrite:0,cost:{total:cost}},attemptIds:[id],outcome:"success",source:"fixture"}),task.id);ledger.finish(task.id,"accepted","verifier",102);}
 config.modelPolicy.automaticSelection=true;assert.equal(comparisonPolicyDigest(config),contract);assert.notEqual(configurationPolicyDigest(config),oldAuthority);
 const rows=modelComparison(ledger).filter(r=>r.contractDigest===comparisonPolicyDigest(config));assert.equal(rows.length,2);
 const selected=selectModel(config,{automatic:true,manual:null,at:200,eligible:{primary:[],backup:[]},history:rows,comparisonKey:rows[0].key,modelVersions:{primary:"v1",backup:"v1"}});assert.equal(selected.selected,"backup");assert.equal(selected.reason,"history-cost");
 config.routes.newCandidate={...config.routes.primary,model:"new-candidate"};config.allowedRoutes.push("newCandidate");config.projectRouteApprovals["*"].push("newCandidate");assert.equal(comparisonPolicyDigest(config),contract);
 config.limits.semanticAttemptsPerImplementationTask++;assert.notEqual(comparisonPolicyDigest(config),contract);
});
for(const mode of ["headers","stream","complete","cancel"] as const)test(`[A] request deadline handles ${mode} and leaves the next request independent`,async t=>{
 let calls=0,timeouts=0;const server=createServer((req,res)=>{req.resume();calls++;if(calls>1||mode==="complete"){res.end("done");return;}if(mode!=="headers"){res.writeHead(200,{"content-type":"text/event-stream"});res.flushHeaders();res.write("data: partial\n\n");}});await listenLoopback(server);const baseUrl=`http://127.0.0.1:${(server.address() as {port:number}).port}/v1`;
 const transport=installHttpTransport(()=>({baseUrl,model:"m",token:1}),{requestTimeoutMs:()=>150,requestTimedOut:()=>{timeouts++;}},false,false);t.after(()=>{transport.dispose();server.closeAllConnections();server.close();});
 const send=()=>transport.fetch(baseUrl+"/chat/completions",{method:"POST",body:'{"model":"m"}'});
 if(mode==="headers")await assert.rejects(send(),{code:"REQUEST_TIMEOUT"});
 else{const response=await send();if(mode==="stream")await assert.rejects(response.text());else if(mode==="cancel")await response.body!.cancel();else assert.equal(await response.text(),"done");}
 await delay(200);assert.equal(timeouts,mode==="headers"||mode==="stream"?1:0);assert.equal(await(await send()).text(),"done");assert.equal(calls,2);
});

test("[S] an adapter caller cannot manufacture an initial route choice",async t=>{
 const store=new Store(isolatedDirectory(t));t.after(()=>store.close());const config=configured();config.features.managedWorkflows=true;config.roles.worker={route:"primary",profileRef:"worker"};config.routes.backup={...config.routes.primary,model:"backup"};config.allowedRoutes.push("backup");
 const adapter=new SubagentsAdapter({} as never,store,config,store.claimOwner("scope","owner"));
 await assert.rejects((adapter as any).executeOwned({jobId:"not-authorized",stepId:"implement",role:"worker",routeId:"backup",cwd:store.root,task:"unapproved"},{}),{code:"ROUTE_OVERRIDE_DISABLED"});assert.equal(store.list("child-grants").length,0);
});

test("[V] coverage excludes fully covered test copies instead of inflating production totals",async t=>{
 const modulePath="../scripts/coverage-reporter.mjs",{coverageView}=await import(modulePath),root=isolatedDirectory(t);mkdirSync(join(root,"src"));writeFileSync(join(root,"src/a.ts"),"// observed source\n");
 const counts={totalLineCount:10,coveredLineCount:5,totalBranchCount:4,coveredBranchCount:1,totalFunctionCount:2,coveredFunctionCount:1};
 const result=coverageView({files:[{path:join(root,"src/a.ts"),...counts},{path:join(root,"test-copy/src/a.ts"),...counts,coveredLineCount:10},{path:"/outside/src/a.ts",...counts,coveredLineCount:10}]},root);
 assert.equal(result.excludedFiles,2);assert.equal(result.files.length,1);assert.equal(result.totals.linePercent,50);assert.equal(result.totals.branchPercent,25);assert.equal(result.complete,false);assert.equal(result.nativePiSubprocessCoverage,"not-collected");
});
