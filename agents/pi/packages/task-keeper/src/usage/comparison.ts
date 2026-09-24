import {priceUsage} from "./pricing.ts";
import type {PriceBook} from "../policies/configuration.ts";
import { UsageLedger, decimal, amount, usageBreakdown } from "./ledger.ts";
import { digest } from "../contracts/primitives.ts";
export function modelComparison(ledger:UsageLedger,options:{from?:number;to?:number;comparisonGroup?:string;priceBooks?:PriceBook[];priceAt?:number}={}) {
  const groups=new Map<string,{key:string;comparisonGroup:string|null;workflow:string;inputBand:string;contractDigest:string|null;observedRoles:Set<string>;observedModels:Set<string>;model:string;modelVersion:string|null;sampleIds:string[];terminalSampleIds:string[];quoteIds:Set<string>;started:number;accepted:number;failed:number;cancelled:number;open:number;
    verified:number;terminal:number;unknownOutcome:number;unknown:number;complete:boolean;currency:string|null;total:bigint;costs:bigint[];knownCosts:Record<string,bigint>;openCosts:Record<string,bigint>;openUnknownCosts:number;reasons:Set<string>}>();
  for(const row of ledger.query(options).filter(row=>!options.comparisonGroup||row.task.comparisonGroup===options.comparisonGroup)){
    const {task}=row,facts=ledger.facts(task.id).sort((a,b)=>a.startedAt-b.startedAt||a.id.localeCompare(b.id));
    const pricedFacts=options.priceBooks&&options.priceAt!==undefined?facts.map(f=>({...f,cost:priceUsage(f,options.priceBooks!,f.accountPlanRef??null,options.priceAt)})):facts;
    if(options.priceBooks&&options.priceAt!==undefined){const priced=usageBreakdown(pricedFacts,()=>"all").all;if(priced){row.costs=priced.costs;row.unknownCosts=priced.unknownGenerations;}}
    const main=facts.filter(f=>["parent","implement","inspect","worker","scout"].includes(f.role));
    const models=[...new Set(main.map(f=>`${f.provider}/${f.model}`))],first=main.find(f=>!f.notSent&&f.tokens.input!==null&&f.tokens.cacheRead!==null&&f.tokens.cacheWrite!==null);
    const input=first && first.tokens.input!==null && first.tokens.cacheRead!==null && first.tokens.cacheWrite!==null ? first.tokens.input+first.tokens.cacheRead+first.tokens.cacheWrite : null;
    const band=input===null?"unknown":input<8000?"0-8k":input<32000?"8k-32k":input<128000?"32k-128k":"128k+";
    // Compare the declared task contract, not the roles that happened to finish.
    // Otherwise an early failure would disappear into a cheaper separate group.
    const key=digest([task.comparisonGroup,task.workflow,task.contractDigest,band]);
    const versions=[...new Set(main.map(f=>f.modelVersion??null))],modelVersion=versions.length===1?versions[0]:null;
    const model=models.length===1?models[0]:models.length?"mixed-model":"unknown",id=digest([key,model,modelVersion]);
    let group=groups.get(id);
    if(!group){group={key,comparisonGroup:task.comparisonGroup,workflow:task.workflow,inputBand:band,contractDigest:task.contractDigest,observedRoles:new Set(),observedModels:new Set(),model,modelVersion,sampleIds:[],terminalSampleIds:[],quoteIds:new Set(),started:0,accepted:0,failed:0,cancelled:0,open:0,verified:0,terminal:0,unknownOutcome:0,unknown:0,complete:true,currency:null,total:0n,costs:[],knownCosts:{},openCosts:{},openUnknownCosts:0,reasons:new Set()};groups.set(id,group);}
    for(const fact of facts){group.observedRoles.add(fact.role);group.observedModels.add(`${fact.role}:${fact.provider}/${fact.model}`);}
    if(task.temporary||!task.comparisonGroup||!task.contractDigest)group.reasons.add("unassigned-comparison-contract");
    group.sampleIds.push(task.id);group.started++;if(task.status==="open"){
      group.open++;group.openUnknownCosts+=row.unknownCosts||(!facts.length?1:0);
      for(const [currency,cost] of Object.entries(row.costs))group.openCosts[currency]=(group.openCosts[currency]??0n)+decimal(cost.actual)+decimal(cost.estimated);
      continue;
    }
    for(const [currency,cost] of Object.entries(row.costs))group.knownCosts[currency]=(group.knownCosts[currency]??0n)+decimal(cost.actual)+decimal(cost.estimated);
    group.terminalSampleIds.push(task.id);for(const fact of pricedFacts)if(fact.cost.quoteId)group.quoteIds.add(fact.cost.quoteId);
    group.terminal++;if(task.status==="accepted"){group.accepted++;if(task.resultSource==="verifier")group.verified++;}if(task.status==="failed")group.failed++;if(task.status==="cancelled")group.cancelled++;
    if(task.temporary||!task.comparisonGroup||!task.contractDigest)group.reasons.add("unassigned-comparison-contract");
    if(modelVersion===null)group.reasons.add("unknown-or-mixed-model-version");
    if(band==="unknown")group.reasons.add("unknown-input-size");if(models.length!==1)group.reasons.add("mixed-or-unknown-primary");
    if(task.status==="finished"){group.unknownOutcome++;group.reasons.add("unverified-outcome");}
    const currencies=Object.keys(row.costs);const currency=currencies[0];
    if(row.unknownCosts||row.usageCoverage!==1||task.gaps.length||currencies.length!==1||(!facts.length)){group.unknown++;group.complete=false;group.reasons.add("incomplete-usage-or-cost");continue;}
    if(group.currency && group.currency!==currency){group.complete=false;group.reasons.add("mixed-currency");continue;}
    group.currency=currency;const cost=decimal(row.costs[currency].actual)+decimal(row.costs[currency].estimated);group.total+=cost;group.costs.push(cost);
  }
  return [...groups.values()].map(g=>{
    g.costs.sort((a,b)=>a<b?-1:a>b?1:0);const n=g.costs.length;
    const median=n?(n%2?g.costs[Math.floor(n/2)]:(g.costs[n/2-1]+g.costs[n/2])/2n):null;
    return {key:g.key,comparisonGroup:g.comparisonGroup,workflow:g.workflow,inputBand:g.inputBand,contractDigest:g.contractDigest,observedRoles:[...g.observedRoles].sort(),observedModels:[...g.observedModels].sort(),model:g.model,modelVersion:g.modelVersion,sampleIds:g.sampleIds.sort(),terminalSampleIds:g.terminalSampleIds.sort(),quoteIds:[...g.quoteIds].sort(),valuationAt:options.priceAt??null,started:g.started,accepted:g.accepted,verified:g.verified,failed:g.failed,cancelled:g.cancelled,open:g.open,
      terminal:g.terminal,unknownOutcome:g.unknownOutcome,qualityKnownTasks:g.terminal-g.unknownOutcome,maximumPossibleSuccessRate:g.terminal?(g.accepted+g.unknownOutcome)/g.terminal:null,unknown:g.unknown,currency:g.currency,costScope:"fully-priced-terminal-tasks",knownCosts:Object.fromEntries(Object.entries(g.knownCosts).map(([currency,cost])=>[currency,amount(cost)])),percentileSamples:g.costs.length,openCosts:Object.fromEntries(Object.entries(g.openCosts).map(([currency,cost])=>[currency,amount(cost)])),openUnknownCosts:g.openUnknownCosts,totalCost:amount(g.total),costPerAccepted:g.accepted&&g.complete?amount(g.total/BigInt(g.accepted)):null,
      successRate:g.terminal?g.accepted/g.terminal:null,median:median===null?null:amount(median),p90:n?amount(g.costs[Math.ceil(n*.9)-1]):null,
      comparable:g.complete&&g.reasons.size===0,reasons:[...g.reasons].sort()};
  });
}
