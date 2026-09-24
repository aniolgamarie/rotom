import type { PriceBook } from "../policies/configuration.ts";
import { Store } from "../store/database.ts";
import { ContractError, digest, newId, finiteInteger, canonical } from "../contracts/primitives.ts";
export const TOKEN_BUCKETS = ["input", "output", "cacheRead", "cacheWrite"] as const;
export type Tokens = Record<typeof TOKEN_BUCKETS[number], number | null>;
export interface UsageTask {
  id: string; sessionId: string; title: string; workflow: string; comparisonGroup: string | null;
  contractDigest: string | null; startedAt: number; finishedAt: number | null;
  status: "open" | "finished" | "accepted" | "failed" | "cancelled";
  resultSource: "user" | "verifier" | "unverified"; temporary: boolean; gaps: string[];
}
export interface UsageFact {
  id: string; revision: number; supersedes: string | null; generationId: string; provider: string; model: string; modelVersion?:string|null;
  role: string; source: string; accountPlanRef?:string|null; startedAt: number; endedAt: number; tokens: Tokens;
  attemptIds: string[]; coverage: "complete" | "aggregate" | "final-response-only" | "unknown";
  outcome: "success" | "failure" | "cancelled" | "unknown";
  notSent?:boolean; notSentProofs?:string[];
  rawUsage?: { buckets:Tokens; totalTokens:number|null; normalization:string; catalogCost?:string|null };
  cost: { kind: "actual" | "estimated" | "unknown"; amount: string | null; currency: string | null; source: string; quoteId: string | null; quoteSnapshot?: PriceBook };
}
export interface UsageLink { generationId: string; taskId: string; assignedAt: number; source: string }
/** Decimal arithmetic uses a fixed 18-place integer, with rounding only at presentation. */
export function decimal(value: string): bigint {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,18})?$/.test(value)) throw new ContractError("INVALID_DECIMAL_AMOUNT");
  const [whole, fraction = ""] = value.split("."); return BigInt(whole) * 10n ** 18n + BigInt(fraction.padEnd(18,"0"));
}
export function amount(value: bigint): string {
  if(value < 0n) throw new ContractError("NEGATIVE_AMOUNT");
  const whole=value/10n**18n, fractional=(value%10n**18n).toString().padStart(18,"0").replace(/0+$/,"");
  return fractional ? `${whole}.${fractional}` : String(whole);
}
export class UsageLedger {
  private store: Store;
  constructor(store: Store) { this.store=store; }
  private atomic<T>(body:()=>T):T {return this.store.db.isTransaction?body():this.store.transaction(body);}
  hasGeneration(id:string):boolean {return this.store.get("usage-generations",id)!==null;}
  hasTask(id:string):boolean {return this.store.get("usage-tasks",id)!==null;}
  task(id: string): UsageTask { const task=this.store.get<UsageTask>("usage-tasks",id);if(!task)throw new ContractError("USAGE_TASK_NOT_FOUND");return task; }
  begin(input: Pick<UsageTask,"sessionId"|"title"> & Partial<Pick<UsageTask,"id"|"workflow"|"comparisonGroup"|"contractDigest"|"temporary">>, now=Date.now()): UsageTask {
    finiteInteger(now);if(!input.sessionId || !input.title.trim())throw new ContractError("USAGE_TASK_IDENTITY_REQUIRED");
    return this.atomic(()=>{
      const id=input.id ?? newId("usage-task");const prior=this.store.get<UsageTask>("usage-tasks",id);if(prior)return prior;
      const task:UsageTask={id,sessionId:input.sessionId,title:input.title,workflow:input.workflow??"conversation",comparisonGroup:input.comparisonGroup??null,
        contractDigest:input.contractDigest??null,temporary:input.temporary??false,startedAt:now,finishedAt:null,status:"open",resultSource:"unverified",gaps:[]};
      this.store.put("usage-tasks",id,task);this.store.put("usage-active",input.sessionId,{taskId:id});return task;
    });
  }
  activeTask(sessionId:string):UsageTask|null {const value=this.store.get<{taskId:string}>("usage-active",sessionId);return value?this.task(value.taskId):null;}
  current(sessionId:string,now=Date.now()):UsageTask {
    const active=this.store.get<{taskId:string}>("usage-active",sessionId), task=active?this.task(active.taskId):null;
    return task?.status==="open" ? task : this.begin({sessionId,title:"Unassigned conversation",temporary:true},now);
  }
  finish(id:string,status:UsageTask["status"],source:UsageTask["resultSource"],now=Date.now()):UsageTask {
    if(status==="open" || (status==="accepted" && source==="unverified"))throw new ContractError("USAGE_RESULT_AUTHORITY_REQUIRED");
    finiteInteger(now);
    return this.atomic(()=>{const task=this.task(id),execution=this.store.get<{status:string}>("managed-jobs",id);
      if(now<task.startedAt)throw new ContractError("INVALID_USAGE_TIME");
      if(status === "accepted" && execution && execution.status!=="COMPLETED")throw new ContractError("REQUIRED_ACCEPTANCE_NOT_SATISFIED");
      if(status === "accepted" && execution?.status==="COMPLETED")source="verifier";
      const previous={status:task.status,resultSource:task.resultSource,finishedAt:task.finishedAt};
      task.status=status;task.resultSource=source;task.finishedAt=now;this.store.put("usage-tasks",id,task);
      this.store.put("usage-result-audit",newId("result"),{taskId:id,previous,status,source,at:now});return task;});
  }
  bindContract(id:string,contractDigest:string):void {
    this.atomic(()=>{const task=this.task(id);if(task.contractDigest===contractDigest)return;
      if(this.facts(id).length){this.gap(id,"execution-contract-changed");return;}
      const previous=task.contractDigest;task.contractDigest=contractDigest;this.store.put("usage-tasks",id,task);
      this.store.put("usage-contract-audit",newId("contract"),{taskId:id,previous,contractDigest,at:Date.now()});
    });
  }
  gap(id:string,reason:string):void {this.atomic(()=>{const task=this.task(id);if(!task.gaps.includes(reason)){task.gaps.push(reason);this.store.put("usage-tasks",id,task);}});}
  link(generationId:string,taskId:string,source="capture",now=Date.now()):void {
    this.atomic(()=>{
      this.task(taskId);const old=this.store.get<UsageLink>("usage-links",generationId);
      if(old?.taskId===taskId)return;
      if(old && source!=="user-reassignment")throw new ContractError("USAGE_LINK_CONFLICT");
      const next={generationId,taskId,source,assignedAt:now};this.store.put("usage-links",generationId,next);
      this.store.put("usage-link-audit",newId("link"),{generationId,previous:old??null,next});
    });
  }
  record(fact:UsageFact,taskId:string):"inserted"|"duplicate"|"revised" {
    finiteInteger(fact.revision,1);finiteInteger(fact.startedAt);finiteInteger(fact.endedAt);
    if(fact.endedAt<fact.startedAt || !fact.generationId || !fact.id || !fact.provider || !fact.model)throw new ContractError("INVALID_USAGE_IDENTITY");
    for(const key of TOKEN_BUCKETS)if(fact.tokens[key]!==null)finiteInteger(fact.tokens[key]!);
    if(new Set(fact.attemptIds).size!==fact.attemptIds.length)throw new ContractError("DUPLICATE_USAGE_ATTEMPT");
    if(fact.cost.amount!==null)decimal(fact.cost.amount);
    if(fact.notSent && (!fact.attemptIds.length || fact.attemptIds.some(id=>!fact.notSentProofs?.includes(id)||this.store.get<{generationId:string}>("usage-send-proofs",id)?.generationId!==fact.generationId)))throw new ContractError("USAGE_NOT_SENT_PROOF_REQUIRED");
    if(fact.cost.kind!=="unknown" && (fact.cost.amount===null || (!fact.cost.currency && !(fact.notSent && fact.cost.amount==="0")) || !fact.cost.source))throw new ContractError("INCOMPLETE_USAGE_COST");
    try { return this.atomic(()=>{
      const old=this.store.get<UsageFact>("usage-generations",fact.generationId), hash=digest(fact);
      const previous=this.store.get<{hash:string}>("usage-facts",fact.id);
      if(previous){if(previous.hash!==hash)throw new ContractError("USAGE_FACT_CONFLICT");if(this.store.get<UsageLink>("usage-links",fact.generationId)?.source!=="user-reassignment")this.link(fact.generationId,taskId);return "duplicate";}
      if(old && (["provider","model","role","startedAt"] as const).some(key=>old[key]!==fact[key]))throw new ContractError("USAGE_GENERATION_IDENTITY_CONFLICT");
      if(old && ((old.modelVersion??null)!==(fact.modelVersion??null) || (old.accountPlanRef??null)!==(fact.accountPlanRef??null)))throw new ContractError("USAGE_GENERATION_IDENTITY_CONFLICT");
      if(old && (fact.revision!==old.revision+1 || fact.supersedes!==old.id))throw new ContractError("USAGE_REVISION_CONFLICT");
      if(!old && (fact.revision!==1 || fact.supersedes!==null))throw new ContractError("USAGE_REVISION_MISSING");
      const link=this.store.get<UsageLink>("usage-links",fact.generationId);
      if(!old || link?.source!=="user-reassignment")this.link(fact.generationId,taskId);
      this.store.put("usage-facts",fact.id,{hash,fact});this.store.put("usage-generations",fact.generationId,fact);
      return old?"revised":"inserted";
    }); } catch(error){
      if(error instanceof ContractError && ["USAGE_FACT_CONFLICT","USAGE_GENERATION_IDENTITY_CONFLICT","USAGE_REVISION_CONFLICT","USAGE_LINK_CONFLICT"].includes(error.code)){
        const incoming=digest(fact),id=digest([fact.generationId,fact.id,incoming]);
        if(!this.store.get("usage-conflicts",id))this.store.put("usage-conflicts",id,{generationId:fact.generationId,sourceRecordId:fact.id,incomingDigest:incoming,code:error.code,at:Date.now()});
      }
      throw error;
    }
  }
  facts(taskId?:string):UsageFact[] {
    const selected=taskId?new Set(this.store.list<UsageLink>("usage-links").filter(row=>row.value.taskId===taskId).map(row=>row.id)):null;
    return this.store.list<UsageFact>("usage-generations").filter(row=>!selected || selected.has(row.id)).map(row=>row.value);
  }
  query(options:{from?:number;to?:number;taskId?:string}={}) {
    const tasks=this.store.list<UsageTask>("usage-tasks").map(row=>row.value).filter(task=>(!options.taskId || task.id===options.taskId)&&task.startedAt>=(options.from??0)&&task.startedAt<(options.to??Infinity));
    return tasks.map(task=>{
      const facts=this.facts(task.id), tokens:Tokens={input:0,output:0,cacheRead:0,cacheWrite:0};
      const knownTokens={input:0,output:0,cacheRead:0,cacheWrite:0};
      const costs:Record<string,{actual:bigint;estimated:bigint}>={};let unknownCosts=0;
      for(const fact of facts){for(const key of TOKEN_BUCKETS)if(fact.tokens[key]!==null)knownTokens[key]+=fact.tokens[key]!;for(const key of TOKEN_BUCKETS)tokens[key]=tokens[key]===null||fact.tokens[key]===null?null:tokens[key]!+fact.tokens[key]!;
        if(fact.notSent)continue;
        if(fact.coverage==="final-response-only" || fact.cost.kind==="unknown" || fact.cost.amount===null || !fact.cost.currency)unknownCosts++;
        if(fact.cost.kind==="unknown" || fact.cost.amount===null || !fact.cost.currency)continue;
        const sums=costs[fact.cost.currency]??={actual:0n,estimated:0n};sums[fact.cost.kind]+=decimal(fact.cost.amount);
      }
      for(const key of TOKEN_BUCKETS){finiteInteger(knownTokens[key]);if(tokens[key]!==null)finiteInteger(tokens[key]!);}
      const tools=this.store.list<{taskId:string;generationId?:string;failed:boolean|null}>("usage-tools").filter(row=>(row.value.generationId?this.store.get<UsageLink>("usage-links",row.value.generationId)?.taskId:row.value.taskId)===task.id).map(row=>row.value);
      const managed=this.store.list<{id:string;analyticsTaskId?:string;semanticAttempts?:number;opinion?:{exchanges:number}}>("managed-jobs").map(row=>row.value).filter(job=>(job.analyticsTaskId??job.id)===task.id);
      const generationIds=new Set(facts.map(fact=>fact.generationId)),conflicts=this.store.list<{generationId:string;code:string;sourceRecordId:string}>("usage-conflicts").filter(row=>generationIds.has(row.value.generationId));
      const viewTask={...task,gaps:[...new Set([...task.gaps.filter(gap=>gap!=="unobserved-generation-usage"||facts.some(fact=>fact.coverage==="unknown")),...(conflicts.length?["usage-conflict"]:[])])]};
      const missingPeriod=viewTask.gaps.some(gap=>["usage-disabled","usage-history-unavailable-at-enable"].includes(gap));
      if(missingPeriod){for(const bucket of TOKEN_BUCKETS)tokens[bucket]=null;unknownCosts++;}
      return {task:viewTask,conflicts,tokens,knownTokens,notSentGenerations:facts.filter(f=>f.notSent).length,zeroCostProven:facts.length>0&&facts.every(f=>f.notSent),generations:facts.length,rounds:{primary:facts.filter(f=>["parent","implement","inspect","worker","scout"].includes(f.role)).length,secondOpinion:facts.filter(f=>f.role==="second-opinion").length,requiredReview:facts.filter(f=>["independent-review","scope-evidence-review"].includes(f.role)).length,canary:facts.filter(f=>f.role==="canary").length,branchSummary:facts.filter(f=>f.role==="branch-summary").length,compaction:facts.filter(f=>f.role==="compaction").length,repairs:managed.reduce((sum,job)=>sum+Math.max(0,(job.semanticAttempts??1)-1),0),exchanges:managed.reduce((sum,job)=>sum+(job.opinion?.exchanges??0),0),tools:tools.length,failedTools:tools.filter(tool=>tool.failed===true).length,unknownTools:tools.filter(tool=>tool.failed===null).length},roles:[...new Set(facts.map(f=>f.role))],models:[...new Set(facts.map(f=>`${f.provider}/${f.model}`))],
        successfulGenerations:facts.filter(f=>f.outcome==="success").length,failedGenerations:facts.filter(f=>f.outcome==="failure").length,
        attempts:[...new Set(facts.flatMap(f=>f.attemptIds))].length,notSentAttempts:[...new Set(facts.flatMap(f=>f.attemptIds.filter(id=>this.store.get<{generationId:string}>("usage-send-proofs",id)?.generationId===f.generationId)))].length,byRole:usageBreakdown(facts,f=>f.role),byModel:usageBreakdown(facts,f=>`${f.provider}/${f.model}`),unknownCosts,usageComplete:facts.length>0&&!viewTask.gaps.length&&facts.every(f=>["complete","aggregate"].includes(f.coverage)),usageCoverage:missingPeriod?null:facts.length?facts.filter(f=>["complete","aggregate"].includes(f.coverage)).length/facts.length:0,
        costs:Object.fromEntries(Object.entries(costs).map(([currency,sums])=>[currency,{actual:amount(sums.actual),estimated:amount(sums.estimated)}]))};
    });
  }
}
/** SDK costs are catalog estimates, not invoices. An absent bucket is unknown, never zero. */
export function sdkUsage(input:{accountPlanRef?:string|null;generationId:string;provider:string;model:string;modelVersion?:string|null;role:string;startedAt:number;endedAt:number;usage:unknown;attemptIds:string[];outcome:UsageFact["outcome"];source:string}):UsageFact {
  const usage=(input.usage??{}) as Record<string,unknown>;
  const tokens=Object.fromEntries(TOKEN_BUCKETS.map(key=>[key,Number.isSafeInteger(usage[key])&&Number(usage[key])>=0?Number(usage[key]):null])) as Tokens;
  const rawUsage={buckets:structuredClone(tokens),totalTokens:Number.isSafeInteger(usage.totalTokens)?Number(usage.totalTokens):null,normalization:"Pi-0.84.4-exclusive-cache-buckets"};
  // Pi initializes these buckets to zero even when the provider sends no usage.
  // Without a separate metering receipt, an all-zero observation cannot prove free execution.
  if(TOKEN_BUCKETS.every(key=>tokens[key]===0))for(const key of TOKEN_BUCKETS)tokens[key]=null;
  const sdkCost=usage.cost as {total?:unknown}|undefined, total=sdkCost?.total;
  // Decimal strings preserve the SDK observation's given precision; downstream arithmetic stays exact.
  const catalogCost=typeof total==="number"&&Number.isFinite(total)&&total>=0?total.toLocaleString("en-US",{useGrouping:false,maximumFractionDigits:18}):null;
  const value=TOKEN_BUCKETS.every(key=>tokens[key]!==null)&&catalogCost!==null&&decimal(catalogCost)>0n?catalogCost:null;
  const {usage:_usage,...identity}=input;
  return {...identity,modelVersion:input.modelVersion??null,id:`usage-${digest([input.generationId,canonical(tokens),value])}`,revision:1,supersedes:null,tokens,rawUsage:{...rawUsage,catalogCost},
    coverage:TOKEN_BUCKETS.every(key=>tokens[key]!==null)?input.attemptIds.length>1?"final-response-only":"aggregate":"unknown",
    cost:{kind:value===null?"unknown":"estimated",amount:value,currency:value===null?null:"USD",source:value===null?(catalogCost==="0"?"SDK zero without an explicit billing quote":"unobserved"):"Pi SDK catalog estimate",quoteId:null}};
}

/** Breakdowns share the same facts; role/model subtotals are views, never new charges. */
export function usageBreakdown(facts:UsageFact[],key:(fact:UsageFact)=>string){
  const groups=new Map<string,UsageFact[]>();for(const fact of facts){const id=key(fact);groups.set(id,[...(groups.get(id)??[]),fact]);}
  return Object.fromEntries([...groups].map(([id,rows])=>{
    const knownTokens={input:0,output:0,cacheRead:0,cacheWrite:0},costs:Record<string,{actual:bigint;estimated:bigint}>={};let unknown=0;
    for(const fact of rows){for(const bucket of TOKEN_BUCKETS)knownTokens[bucket]+=fact.tokens[bucket]??0;
      if(fact.notSent)continue;
      if(fact.coverage==="unknown"||fact.coverage==="final-response-only"||fact.cost.kind==="unknown"||fact.cost.amount===null||!fact.cost.currency)unknown++;
      if(fact.cost.kind!=="unknown"&&fact.cost.amount!==null&&fact.cost.currency){const sums=costs[fact.cost.currency]??={actual:0n,estimated:0n};sums[fact.cost.kind]+=decimal(fact.cost.amount);}
    }
    for(const bucket of TOKEN_BUCKETS)finiteInteger(knownTokens[bucket]);
    return[id,{generations:rows.length,knownTokens,unknownGenerations:unknown,modelVersions:[...new Set(rows.map(f=>f.modelVersion??null))],
      costs:Object.fromEntries(Object.entries(costs).map(([currency,cost])=>[currency,{actual:amount(cost.actual),estimated:amount(cost.estimated)}]))}];
  }));
}
