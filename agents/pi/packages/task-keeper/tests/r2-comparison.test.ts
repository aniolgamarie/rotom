import {test,assert,acceptance,observerArtifact} from "./recorded-test.ts";
import {Store} from "../src/store/database.ts";
import {UsageLedger,sdkUsage,type UsageTask} from "../src/usage/ledger.ts";
import {modelComparison} from "../src/usage/comparison.ts";
import {isolatedDirectory} from "./helpers.ts";
function add(ledger:UsageLedger,id:string,status:UsageTask["status"],cost:number|null,group="same",contract="same-team"){
  const task=ledger.begin({id,sessionId:id,title:id,workflow:"fix",comparisonGroup:group,contractDigest:contract},1);
  ledger.record(sdkUsage({generationId:id,provider:"p",model:"m",modelVersion:"v1",role:"worker",startedAt:1,endedAt:2,usage:{input:10,output:1,cacheRead:0,cacheWrite:0,...(cost===null?{}:{cost:{total:cost}})},attemptIds:[id],outcome:status==="failed"?"failure":status==="cancelled"?"cancelled":"success",source:"fixed-usage-fixture"}),task.id);
  if(status!=="open")ledger.finish(task.id,status,"verifier",3);return task;
}
function credit(variant:string,data:unknown,body:()=>void){acceptance("AC14",variant,{level:"S",observer:"fixed-task-ledger-and-serialized-public-query",predicate:variant,artifact:observerArtifact(`comparison-${variant}`,data)},body);}
test("[S] comparison includes every outcome and keeps open investment separate from terminal efficiency",t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());
  add(ledger,"accepted","accepted",10);add(ledger,"failed","failed",20);add(ledger,"cancelled","cancelled",30);add(ledger,"open","open",40);
  const rows=ledger.query(),report=JSON.parse(JSON.stringify(modelComparison(ledger)))[0];
  credit("all-outcomes",{rows,report},()=>{assert.equal(rows.length,4);assert.equal(report.started,4);assert.equal(report.accepted,1);assert.equal(report.failed,1);assert.equal(report.cancelled,1);assert.equal(report.open,1);assert.equal(report.totalCost,"60");assert.equal(report.costPerAccepted,"60");assert.equal(report.openCosts.USD,"40");assert.deepEqual(report.sampleIds,["accepted","cancelled","failed","open"]);});
  credit("median-p90",report,()=>{assert.equal(report.percentileSamples,3);assert.equal(report.median,"20");assert.equal(report.p90,"30");});
  const failedOnly=modelComparison(ledger,{from:1,to:2}).map(row=>({...row}));assert.equal(failedOnly.length,1);
});
test("[S] zero successes and unknown costs cannot be reported as a complete low-cost strategy",t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());
  add(ledger,"one","failed",10);add(ledger,"two","cancelled",20);let report=modelComparison(ledger)[0];
  credit("zero-success",report,()=>{assert.equal(report.accepted,0);assert.equal(report.costPerAccepted,null);assert.equal(report.totalCost,"30");});
  add(ledger,"three","accepted",null);report=modelComparison(ledger)[0];
  credit("partial-data",report,()=>{assert.equal(report.comparable,false);assert.equal(report.unknown,1);assert.equal(report.costPerAccepted,null);assert.equal(report.knownCosts.USD,"30");assert.ok(report.reasons.includes("incomplete-usage-or-cost"));});
});
test("[S] declared task groups and team contracts remain separate even for the same primary model",t=>{
  const store=new Store(isolatedDirectory(t)),ledger=new UsageLedger(store);t.after(()=>store.close());
  add(ledger,"base","accepted",1,"parser","A-plus-B");add(ledger,"other-group","accepted",2,"ui","A-plus-B");add(ledger,"other-team","accepted",3,"parser","A-only");
  const report=modelComparison(ledger),parser=modelComparison(ledger,{comparisonGroup:"parser"});
  credit("different-group",report,()=>{assert.equal(report.length,3);assert.equal(parser.length,2);assert.ok(parser.every(row=>row.comparisonGroup==="parser"));assert.equal(parser.some(row=>row.sampleIds.includes("other-group")),false);});
  credit("different-team",parser,()=>{assert.equal(new Set(parser.map(row=>row.contractDigest)).size,2);assert.ok(parser.every(row=>row.started===1));assert.notEqual(parser[0].key,parser[1].key);});
});
