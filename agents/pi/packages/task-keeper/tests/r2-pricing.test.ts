import {test,assert,acceptance,observerArtifact} from "./recorded-test.ts";
import {priceUsage,repricingView} from "../src/usage/pricing.ts";
import {sdkUsage,UsageLedger,type UsageFact} from "../src/usage/ledger.ts";
import {parseConfig} from "../src/config.ts";
import type {PriceBook} from "../src/policies/configuration.ts";
import {Store} from "../src/store/database.ts";
import {isolatedDirectory} from "./helpers.ts";
const quote=():PriceBook=>({id:"q1",provider:"p",model:"m",accountPlanRef:null,currency:"CNY",source:"synthetic-price-table",effectiveFrom:"2026-01-01T00:00:00Z",effectiveUntil:"2027-01-01T00:00:00Z",timing:"request-start",timezone:"UTC",rates:{input:"1",output:"2",cacheRead:"0.1",cacheWrite:"0.2"},windows:[]});
const usage=():UsageFact=>sdkUsage({generationId:"g",provider:"p",model:"m",modelVersion:"fixture-v1",role:"parent",startedAt:Date.UTC(2026,8,14,6),endedAt:Date.UTC(2026,8,14,6)+1,usage:{input:1000000,output:1000000,cacheRead:1000000,cacheWrite:1000000},attemptIds:["r"],outcome:"success",source:"fixture-SDK-usage"});
function credit(variant:string,observed:unknown,check:()=>void,level="U"){acceptance("AC13",variant,{level,observer:level==="S"?"SQLite-currency-ledger":"fixed-price-and-time-oracle",predicate:variant,artifact:observerArtifact(`price-${variant}`,observed)},check);}
test("[U] direct, estimated, unknown and independent cache prices retain their distinct source",()=>{
  const actual=usage();actual.cost={kind:"actual",amount:"1.25",currency:"CNY",source:"synthetic-invoice",quoteId:null};
  const retained=priceUsage(actual,[]);credit("direct-cost",{actual,retained},()=>assert.deepEqual(retained,actual.cost));
  const input=usage(),estimated=priceUsage(input,[quote()]);credit("estimated-cost",{input,estimated},()=>{assert.equal(estimated.kind,"estimated");assert.equal(estimated.amount,"3.3");assert.deepEqual(estimated.quoteSnapshot,quote());assert.equal(input.cost.kind,"unknown");});
  const zero=sdkUsage({generationId:"subscription",provider:"p",model:"m",role:"parent",startedAt:1,endedAt:2,usage:{input:100,output:10,cacheRead:0,cacheWrite:0,cost:{total:0}},attemptIds:["r"],outcome:"success",source:"SDK"});
  credit("unknown-subscription",zero,()=>{assert.equal(zero.cost.kind,"unknown");assert.equal(zero.cost.amount,null);assert.equal(zero.tokens.input,100);assert.equal(zero.rawUsage!.catalogCost,"0");});
  const different=usage();different.tokens={input:1000000,output:2000000,cacheRead:3000000,cacheWrite:4000000};const priced=priceUsage(different,[quote()]);
  credit("cache-buckets",{different,priced},()=>{assert.equal(priced.amount,"6.1");assert.equal(priced.currency,"CNY");});
});
test("[U] peak/off-peak, expiry and overlapping quotes follow explicit time rules",()=>{
  const q=quote();q.windows=[{window:{days:[1,2,3,4,5,6,7],start:"00:00",end:"08:00"},rates:{input:"0.5",output:"1",cacheRead:"0.05",cacheWrite:"0.1"}}];
  const low=usage(),high={...low,startedAt:Date.UTC(2026,8,14,9),endedAt:Date.UTC(2026,8,14,9)+1};const prices=[priceUsage(low,[q]),priceUsage(high,[q])];
  credit("peak-offpeak",{q,low,high,prices},()=>assert.deepEqual(prices.map(price=>price.amount),["1.65","3.3"]));
  const expired={...q,effectiveUntil:"2026-02-01T00:00:00Z"},unpriced=priceUsage(low,[expired]);credit("quote-expired",{expired,unpriced},()=>{assert.equal(unpriced.kind,"unknown");assert.equal(unpriced.quoteId,null);});
  const error=(call:()=>unknown)=>{try{call();return "accepted";}catch(e){return(e as {code:string}).code;}};
  const versionOverlap=error(()=>parseConfig({usage:{priceBooks:[q,{...q,id:"q2"}]}})),windowOverlap=error(()=>parseConfig({usage:{priceBooks:[{...q,windows:[...q.windows,...q.windows]}]}}));
  credit("quote-overlap",{versionOverlap,windowOverlap},()=>{assert.equal(versionOverlap,"OVERLAPPING_PRICE_BOOKS");assert.equal(windowOverlap,"OVERLAPPING_PRICE_WINDOWS");});
});
test("[S] currency subtotals never combine and historical repricing leaves source facts unchanged",t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());const task=ledger.begin({sessionId:"s",title:"currencies"},1);
  for(const [id,currency,amount] of [["one","CNY","1.1"],["two","USD","2.2"]]){const fact={...usage(),id,generationId:id,cost:{kind:"actual" as const,amount,currency,source:"synthetic-invoice",quoteId:null}};ledger.record(fact,task.id);}
  const row=ledger.query()[0];credit("currency",row,()=>{assert.equal(row.costs.CNY.actual,"1.1");assert.equal(row.costs.USD.actual,"2.2");assert.equal(Object.keys(row.costs).length,2);},"S");
  const fact=usage();fact.cost=priceUsage(fact,[quote()]);const original=structuredClone(fact),future={...quote(),id:"q2",effectiveFrom:"2027-01-01T00:00:00Z",effectiveUntil:null,rates:{input:"2",output:"4",cacheRead:"0.2",cacheWrite:"0.4"}};
  const projection=repricingView([fact],[future],Date.UTC(2027,0,1));credit("historical-reprice",{original,projection,after:fact},()=>{assert.deepEqual(fact,original);assert.equal(fact.cost.amount,"3.3");assert.equal(projection.amounts.CNY,"6.6");assert.deepEqual(projection.quoteIds,["q2"]);assert.equal(projection.kind,"estimated-view");assert.equal(projection.originalFactsChanged,false);},"S");
});
