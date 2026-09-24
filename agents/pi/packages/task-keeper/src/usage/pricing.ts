import { decimal, amount, TOKEN_BUCKETS, type UsageFact } from "./ledger.ts";
import { instant, type PriceBook, type R2Fields } from "../policies/configuration.ts";
import { windowContains } from "../policies/calendar.ts";
/** Repricing returns a view; it never revises the source usage or historical quote. */
export function priceUsage(fact:UsageFact,quotes:PriceBook[],accountPlanRef:string|null=fact.accountPlanRef??null,repricedAt?:number):UsageFact["cost"] {
  if(fact.notSent || (fact.cost.kind==="actual" && repricedAt===undefined))return structuredClone(fact.cost);
  const matching=quotes.filter(q=>q.provider===fact.provider&&q.model===fact.model&&q.accountPlanRef===accountPlanRef&&q.timing!=="unknown");
  for(const quote of matching){
    const at=repricedAt??(quote.timing==="request-start"?fact.startedAt:fact.endedAt);
    if(at<instant(quote.effectiveFrom)||(quote.effectiveUntil!==null&&at>=instant(quote.effectiveUntil)))continue;
    const window=quote.windows.find(row=>windowContains(row.window,at,quote.timezone)),rates=window?.rates??quote.rates;
    let total=0n;
    for(const bucket of TOKEN_BUCKETS){
      if(fact.tokens[bucket]===null||rates[bucket]===null)return{kind:"unknown",amount:null,currency:quote.currency,source:quote.source,quoteId:quote.id,quoteSnapshot:structuredClone(quote)};
      total+=BigInt(fact.tokens[bucket]!)*decimal(rates[bucket]!);
    }
    return{kind:"estimated",amount:amount(total/1000000n),currency:quote.currency,source:quote.source,quoteId:quote.id,quoteSnapshot:structuredClone(quote)};
  }
  if(repricedAt===undefined && accountPlanRef===null && fact.cost.kind==="estimated" && fact.cost.source==="Pi SDK catalog estimate")return structuredClone(fact.cost);
  return{kind:"unknown",amount:null,currency:null,source:"no applicable price book",quoteId:null};
}


export function repricingView(facts:UsageFact[],quotes:PriceBook[],at:number){
  const currencies:Record<string,bigint>={},quoteIds=new Set<string>();let unknown=0;
  for(const fact of facts){if(fact.notSent)continue;const cost=priceUsage(fact,quotes,fact.accountPlanRef??null,at);if(cost.quoteId)quoteIds.add(cost.quoteId);
    if(fact.coverage==="final-response-only"||cost.amount===null||!cost.currency)unknown++;
    if(cost.amount===null||!cost.currency)continue;currencies[cost.currency]=(currencies[cost.currency]??0n)+decimal(cost.amount);
  }
  return{at,kind:"estimated-view",generations:facts.length,unknownGenerations:unknown,quoteIds:[...quoteIds].sort(),amounts:Object.fromEntries(Object.entries(currencies).map(([currency,cost])=>[currency,amount(cost)])),originalFactsChanged:false};
}

/** Explicit user binding only; model-specific plans override the provider default. */
export function usageAccountPlan(usage:R2Fields["usage"],provider:string,model:string):string|null {
  const rows=(usage.accountPlans??[]).filter(row=>row.provider===provider);
  return (rows.find(row=>row.model===model)??rows.find(row=>row.model===undefined))?.accountPlanRef??null;
}
