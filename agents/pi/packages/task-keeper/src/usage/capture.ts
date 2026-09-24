import { priceUsage } from "./pricing.ts";
import type { PriceBook } from "../policies/configuration.ts";
import { UsageLedger, sdkUsage, type UsageFact } from "./ledger.ts";
import { newId, digest } from "../contracts/primitives.ts";
import type { Store } from "../store/database.ts";
export class UsageCapture {
  private ledger:UsageLedger;
  private store:Store;
  private lastGeneration:{taskId:string;generationId:string}|null=null;
  private active: {id:string;taskId:string;startedAt:number;provider:string;model:string;accountPlanRef?:string|null;modelVersion?:string|null;role:string;attemptIds:string[];quotes:PriceBook[];last:UsageFact;responses:Record<string,number>;zeroReported:Set<string>} | null = null;
  constructor(store:Store){this.store=store;this.ledger=new UsageLedger(store);}
  begin(input:{sessionId:string;provider:string;model:string;accountPlanRef?:string|null;modelVersion?:string|null;role:string;taskId?:string;quotes?:PriceBook[]},enabled:boolean,now=Date.now()):void {
    if(this.active)this.end(undefined,"unknown",now);
    if(!enabled){const taskId=input.taskId??this.ledger.activeTask(input.sessionId)?.id;if(taskId && this.ledger.hasTask(taskId))this.ledger.gap(taskId,"usage-disabled");return;}
    if(input.taskId && !this.ledger.hasTask(input.taskId)){
      const job=this.store.get<{goal:string;parentSessionId:string;workflow:string;createdAt:number;options?:{comparisonGroup?:string}}>("managed-jobs",input.taskId);
      if(job){this.ledger.begin({id:input.taskId,sessionId:job.parentSessionId,title:job.goal,workflow:job.workflow,comparisonGroup:job.options?.comparisonGroup??null},job.createdAt);this.ledger.gap(input.taskId,"usage-history-unavailable-at-enable");}
    }
    const task=input.taskId?this.ledger.task(input.taskId):this.ledger.current(input.sessionId,now);
    const id=newId("generation"),pending=sdkUsage({generationId:id,provider:input.provider,model:input.model,modelVersion:input.modelVersion??null,accountPlanRef:input.accountPlanRef??null,role:input.role,startedAt:now,endedAt:now,usage:undefined,attemptIds:[],outcome:"unknown",source:"runtime-generation-start"});
    this.ledger.record(pending,task.id);
    this.active={id,taskId:task.id,startedAt:now,provider:input.provider,model:input.model,modelVersion:input.modelVersion??null,accountPlanRef:input.accountPlanRef??null,role:input.role,attemptIds:[],quotes:structuredClone(input.quotes??[]),last:pending,responses:{},zeroReported:new Set()};
  }
  tool(id:string,failed:boolean|null):void {
    const link=this.active?{taskId:this.active.taskId,generationId:this.active.id}:this.lastGeneration;if(!link)return;
    const key=digest([id,link.generationId]);
    const old=this.store.get<{taskId:string;generationId:string;failed:boolean|null}>("usage-tools",key);
    if(old && failed===null)return;
    this.store.put("usage-tools",key,{id,...(old??link),failed,at:Date.now()});
  }
  notSent(id:string):void {
    if(!this.active)return;this.attempt(id);this.store.put("usage-send-proofs",id,{generationId:this.active.id,id,source:"transport-invocation-not-performed",at:Date.now()});
  }
  metering(id:string,zero:boolean):void {if(!this.active)return;if(zero)this.active.zeroReported.add(id);else this.active.zeroReported.delete(id);}
  response(id:string,status:number):void {if(this.active)this.active.responses[id]=status;}
  hasActive():boolean {return this.active!==null;}
  attempt(id:string):void {
    if(!this.active || this.active.attemptIds.includes(id))return;
    const active=this.active;active.attemptIds.push(id);
    const next={...active.last,id:newId("usage-pending"),revision:active.last.revision+1,supersedes:active.last.id,attemptIds:[...active.attemptIds],source:"runtime-request-observation"};
    this.ledger.record(next,active.taskId);active.last=next;
  }
  end(usage:unknown,outcome:UsageFact["outcome"],now=Date.now(),scope:"generation"|"operation-aggregate"="generation"):UsageFact|null {
    const active=this.active;if(!active)return null;this.active=null;
    const fact=sdkUsage({generationId:active.id,provider:active.provider,model:active.model,modelVersion:active.modelVersion??null,accountPlanRef:active.accountPlanRef??null,role:active.role,startedAt:active.startedAt,endedAt:now,
      usage,outcome,attemptIds:active.attemptIds,source:"native-SDK-generation"});
    if(active.attemptIds.length>0 && active.attemptIds.every(id=>active.zeroReported.has(id))){fact.tokens={input:0,output:0,cacheRead:0,cacheWrite:0};fact.coverage="aggregate";}
    if(scope === "operation-aggregate"){
      fact.source="native-operation-aggregate";
      if(fact.coverage!=="unknown" && active.attemptIds.length>0 && active.attemptIds.every(id=>active.responses[id]>=200&&active.responses[id]<400))fact.coverage="aggregate";
    }
    fact.revision=active.last.revision+1;fact.supersedes=active.last.id;
    fact.id=newId("usage-terminal");
    if(active.quotes.length)fact.cost=priceUsage(fact,active.quotes);
    fact.notSentProofs=active.attemptIds.filter(id=>this.store.get<{generationId:string}>("usage-send-proofs",id)?.generationId===active.id);
    if(active.attemptIds.length>0 && fact.notSentProofs.length===active.attemptIds.length){
      fact.notSent=true;fact.notSentProofs=[...active.attemptIds];fact.tokens={input:0,output:0,cacheRead:0,cacheWrite:0};fact.coverage="complete";
      fact.cost={kind:"actual",amount:"0",currency:null,source:"verified-not-sent",quoteId:null};
    }
    this.ledger.record(fact,active.taskId);this.lastGeneration={taskId:active.taskId,generationId:active.id};if(fact.coverage==="unknown")this.ledger.gap(active.taskId,"unobserved-generation-usage");return fact;
  }
}
/** Accounting gaps must not suppress native termination or recovery facts. */
export function observeUsage(store:Store|null,body:()=>unknown):void {
  try{body();}catch(error){
    try{store?.put("usage-capture-errors",newId("usage-gap"),{code:typeof (error as {code?:unknown})?.code === "string"?(error as {code:string}).code:"USAGE_CAPTURE_FAILED",at:Date.now()});}
    catch{/* The execution ledger still owns admission; no accounting success is fabricated. */}
  }
}
