import {installHttpTransport} from "../src/adapters/http-transport.ts";
import {ContractError} from "../src/contracts/primitives.ts";
import {createServer} from "node:http";
import {listenLoopback} from "./helpers.ts";
import {UsageCapture} from "../src/usage/capture.ts";
import { test,assert,acceptance,observerArtifact } from "./recorded-test.ts";
import { UsageLedger,sdkUsage,decimal,amount,type UsageFact } from "../src/usage/ledger.ts";
import { modelComparison } from "../src/usage/comparison.ts";
import { Store } from "../src/store/database.ts";
import { isolatedDirectory } from "./helpers.ts";
import { parseConfig } from "../src/config.ts";
import { priceUsage } from "../src/usage/pricing.ts";
import { instant } from "../src/policies/configuration.ts";
import { nextWindow,windowContains } from "../src/policies/calendar.ts";
const fact=(id:string,model="m",tokens=10):UsageFact=>sdkUsage({generationId:id,provider:"p",model,modelVersion:"fixture-version",role:"parent",startedAt:100,endedAt:101,usage:{input:tokens,output:0,cacheRead:0,cacheWrite:0,cost:{total:tokens}},attemptIds:[`request-${id}`],outcome:"success",source:"fixture"});
test("[S] usage revisions and reassignment preserve global totals and original request budgets",t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());
  const a=ledger.begin({sessionId:"session",title:"A"}),b=ledger.begin({sessionId:"session",title:"B"});
  const owner=store.claimOwner("scope","token");store.prepare(owner,"intent","request",{});store.reserveRequest(owner,"intent","request",[{id:"budget",ceiling:2}]);store.settleRequest("request","sent");
  const budget=store.bucket("budget"),usage=fact("generation");assert.equal(ledger.record(usage,a.id),"inserted");assert.equal(ledger.record(usage,a.id),"duplicate");assert.equal(ledger.facts().length,1);
  assert.throws(()=>ledger.record({...usage,tokens:{...usage.tokens,input:20}},a.id),{code:"USAGE_FACT_CONFLICT"});
  assert.equal(ledger.record({...usage,id:"revised",revision:2,supersedes:usage.id,tokens:{...usage.tokens,input:20}},a.id),"revised");
  assert.equal(ledger.query({taskId:a.id})[0].tokens.input,20);assert.equal(store.list("usage-facts").length,2);
  assert.throws(()=>ledger.link(usage.generationId,b.id),{code:"USAGE_LINK_CONFLICT"});ledger.link(usage.generationId,b.id,"user-reassignment");
  assert.equal(ledger.query({taskId:a.id})[0].generations,0);assert.equal(ledger.query({taskId:b.id})[0].tokens.input,20);
  assert.deepEqual(store.bucket("budget"),budget);assert.equal(ledger.facts().length,1);assert.equal(store.list("usage-link-audit").length,2);
});
test("[U S] task cost comparison accounts for all rounds and failure investment with exact decimals",t=>{
  assert.equal(amount(decimal("0.1")+decimal("0.2")),"0.3");
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());
  for(const [model,rounds,size] of [["one-pass",1,10],["multi-pass",5,5]] as const){
    const task=ledger.begin({sessionId:model,title:model,comparisonGroup:"same-goal",contractDigest:"same-tools",workflow:"fix"},100);
    for(let n=0;n<rounds;n++)ledger.record(fact(`${model}-${n}`,model,size),task.id);
    ledger.finish(task.id,"accepted","verifier",200);
  }
  const failure=ledger.begin({sessionId:"failure",title:"failed task",comparisonGroup:"same-goal",contractDigest:"same-tools",workflow:"fix"},100);
  ledger.record(fact("failed","multi-pass",7),failure.id);ledger.finish(failure.id,"failed","verifier",200);
  const rows=modelComparison(ledger);assert.equal(rows.length,2);
  assert.equal(rows.find(row=>row.model==="p/one-pass")!.costPerAccepted,"10");
  const multi=rows.find(row=>row.model==="p/multi-pass")!;assert.equal(multi.totalCost,"32");assert.equal(multi.costPerAccepted,"32");assert.equal(multi.successRate,.5);assert.equal(multi.median,"16");assert.equal(multi.p90,"25");
  const missing=sdkUsage({generationId:"failed-zero",provider:"p",model:"m",role:"parent",startedAt:1,endedAt:2,usage:{input:0,output:0,cacheRead:0,cacheWrite:0,cost:{total:0}},attemptIds:["sent-but-unmetered"],outcome:"failure",source:"SDK"});
  assert.equal(missing.cost.kind,"unknown");assert.equal(missing.tokens.input,null);
});
test("[U] price windows honor explicit time zones and cache buckets without changing original observations",()=>{
  const quote={id:"q",provider:"p",model:"m",accountPlanRef:null,currency:"CNY",source:"user-price",effectiveFrom:"2026-01-01T00:00:00Z",effectiveUntil:"2027-01-01T00:00:00Z",timing:"request-start",timezone:"Asia/Shanghai",
    rates:{input:"2",output:"4",cacheRead:"0.5",cacheWrite:"1"},windows:[{window:{days:[1,2,3,4,5,6,7],start:"00:00",end:"08:00"},rates:{input:"1",output:"2",cacheRead:"0.25",cacheWrite:"0.5"}}]};
  const config=parseConfig({usage:{priceBooks:[quote]}}),input=fact("prices");input.startedAt=instant("2026-09-14T07:00:00+08:00");input.endedAt=input.startedAt+1;
  input.tokens={input:1000000,output:1000000,cacheRead:1000000,cacheWrite:1000000};const original=structuredClone(input);
  assert.equal(priceUsage(input,config.usage.priceBooks).amount,"3.75");input.startedAt+=3600000;input.endedAt+=3600000;
  assert.equal(priceUsage(input,config.usage.priceBooks).amount,"7.5");assert.deepEqual(input.cost,original.cost);
  assert.throws(()=>parseConfig({usage:{priceBooks:[quote,{...quote,id:"overlap"}]}}),{code:"OVERLAPPING_PRICE_BOOKS"});
  assert.throws(()=>parseConfig({usage:{priceBooks:[{...quote,windows:[...quote.windows,...quote.windows]}]}}),{code:"OVERLAPPING_PRICE_WINDOWS"});
});
test("[U] calendar rejects ambiguous dates and respects midnight, weekdays and DST folds",()=>{
  for(const time of ["tomorrow", "2026-09-14T10:00", "2026-02-30T10:00:00Z", "2026-09-14T24:00:00Z"])assert.throws(()=>instant(time));
  const overnight={days:[1],start:"23:00",end:"02:00"};
  assert.equal(windowContains(overnight,instant("2026-09-15T01:00:00+08:00"),"Asia/Shanghai"),true);
  assert.equal(windowContains(overnight,instant("2026-09-15T02:00:00+08:00"),"Asia/Shanghai"),false);
  const fold={days:[7],start:"01:30",end:"02:00"};
  assert.equal(windowContains(fold,instant("2026-11-01T01:45:00-04:00"),"America/New_York"),true);
  assert.equal(windowContains(fold,instant("2026-11-01T01:45:00-05:00"),"America/New_York"),true);
  const start=instant("2026-03-08T01:59:00-05:00"),deadline=instant("2026-03-08T04:00:00-04:00");
  assert.equal(nextWindow([{days:[7],start:"02:00",end:"03:00"}],start,"America/New_York",deadline),null);
});
test("[S] tasks failing before review stay in the declared team's total investment",t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());
  const ok=ledger.begin({sessionId:"ok",title:"Reviewed",comparisonGroup:"task",contractDigest:"A-plus-B",workflow:"fix"},100);
  ledger.record(fact("main","A",10),ok.id);ledger.record({...fact("review","B",5),role:"second-opinion"},ok.id);ledger.finish(ok.id,"accepted","verifier",200);
  const failed=ledger.begin({sessionId:"bad",title:"Failed before B",comparisonGroup:"task",contractDigest:"A-plus-B",workflow:"fix"},100);
  ledger.record(fact("early-failure","A",7),failed.id);ledger.finish(failed.id,"failed","verifier",200);
  const report=modelComparison(ledger);assert.equal(report.length,1);assert.equal(report[0].totalCost,"22");assert.equal(report[0].costPerAccepted,"22");assert.equal(report[0].successRate,.5);
});
test("[S] final SDK usage across retries is not fabricated into per-attempt charges",t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());const task=ledger.begin({sessionId:"retry",title:"Retry"});
  const aggregate=sdkUsage({generationId:"aggregate",provider:"p",model:"m",role:"parent",startedAt:1,endedAt:2,usage:{input:10,output:5,cacheRead:0,cacheWrite:0,cost:{total:.1}},attemptIds:["first","second"],outcome:"success",source:"SDK-final"});
  ledger.record(aggregate,task.id);const row=ledger.query()[0];assert.equal(row.generations,1);assert.equal(row.attempts,2);assert.equal(row.tokens.input,10);
  assert.equal(row.costs.USD.estimated,"0.1");assert.equal(row.unknownCosts,1);assert.equal(row.usageCoverage,0);assert.equal(aggregate.coverage,"final-response-only");
});


test("[S] late usage retains its generation's original task or an explicit audited correction",t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store),capture=new UsageCapture(store);t.after(()=>store.close());
  const first=ledger.begin({sessionId:"session",title:"First"},1);
  capture.begin({sessionId:"session",provider:"p",model:"m",role:"parent"},true,2);capture.attempt("in-flight");ledger.finish(first.id,"finished","user",3);
  const second=ledger.begin({sessionId:"session",title:"Next"},4);const completed=capture.end({input:10,output:1,cacheRead:0,cacheWrite:0},"success",5)!;
  acceptance("AC11","late-usage",{level:"S",observer:"durable-inflight-generation-and-task-links",predicate:"a late terminal belongs to the group selected before the request",artifact:observerArtifact("late-usage",{completed,rows:ledger.query()})},()=>{
    assert.equal(ledger.facts(first.id).length,1);assert.equal(ledger.facts(second.id).length,0);assert.equal(ledger.task(first.id).status,"finished");assert.equal(ledger.facts(first.id)[0].tokens.input,10);
  });
  ledger.link(completed.generationId,second.id,"user-reassignment");assert.equal(ledger.record(completed,first.id),"duplicate");assert.equal(ledger.facts(first.id).length,0);assert.equal(ledger.facts(second.id).length,1);
  const implicit=ledger.current("unassigned",6);ledger.record({...fact("unassigned"),startedAt:6,endedAt:7},implicit.id);
  acceptance("AC11","ambiguous-segment",{level:"S",observer:"unassigned-group-and-comparison-query",predicate:"unassigned conversation cannot become a comparable task",artifact:observerArtifact("ambiguous-group",{implicit,comparison:modelComparison(ledger)})},()=>{
    assert.equal(implicit.temporary,true);assert.equal(implicit.comparisonGroup,null);assert.ok(modelComparison(ledger).find(row=>row.sampleIds.includes(implicit.id))!.reasons.includes("unassigned-comparison-contract"));
  });
});

test("[A S] rejected transport admission proves zero usage without clearing independent budget facts",async t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store),capture=new UsageCapture(store);t.after(()=>store.close());
  const task=ledger.begin({sessionId:"s",title:"not sent"}),owner=store.claimOwner("scope","owner");store.prepare(owner,"intent","read",{},[{id:"slot",capacity:1,units:1}]);
  let requests=0;const server=createServer((req,res)=>{requests++;req.resume();res.end("unexpected");});await listenLoopback(server);t.after(()=>{server.closeAllConnections();server.close();});
  const baseUrl=`http://127.0.0.1:${(server.address() as {port:number}).port}/v1`;let rejectedRequest="";
  capture.begin({sessionId:"s",taskId:task.id,provider:"p",model:"m",role:"parent"},true);
  const transport=installHttpTransport(()=>({baseUrl,model:"m",token:1}),{before:attempt=>{rejectedRequest=attempt.id;capture.attempt(attempt.id);store.reserveRequest(owner,"intent",attempt.id,[{id:"budget",ceiling:1}]);},recheck:()=>{throw new ContractError("USER_CANCELLED");},error:(attempt,invoked)=>{assert.equal(invoked,false);capture.notSent(attempt.id);store.settleRequest(attempt.id,"not_sent");store.settle("intent","not_sent");}},false,false);
  await assert.rejects(transport.fetch(baseUrl+"/chat/completions",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({model:"m",messages:[]})}),{code:"USER_CANCELLED"});capture.end(undefined,"cancelled");
  const row=ledger.query({taskId:task.id})[0];
  for(const [ac,name] of [["AC12","not-sent"],["AC09","not-sent-release"]])acceptance(ac,name,{level:"A",observer:"actual-transport-final-recheck-and-SQLite-accounting",predicate:name,artifact:observerArtifact(name,{row,requests,request:store.request(rejectedRequest),budget:store.bucket("budget"),claims:store.claims()})},()=>{assert.equal(requests,0);assert.equal(row.notSentGenerations,1);assert.equal(row.zeroCostProven,true);assert.equal(row.tokens.input,0);assert.equal(row.tokens.output,0);assert.equal(store.request(rejectedRequest)!.state,"not_sent");assert.equal(store.bucket("budget")!.used,0);assert.equal(store.bucket("budget")!.reserved,0);assert.equal(store.claims().length,0);});
});
