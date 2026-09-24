import {once} from "node:events";
import {test,assert,acceptance,observerArtifact} from "./recorded-test.ts";
import {Store} from "../src/store/database.ts";
import {businessDigest} from "../src/store/maintenance.ts";
import {UsageLedger,sdkUsage} from "../src/usage/ledger.ts";
import {isolatedDirectory} from "./helpers.ts";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
test("[P] explicit v2 to v3 migration preserves unknown writers, budgets and usage aggregates",t=>{
  const root=isolatedDirectory(t),old=new Store(root),owner=old.claimOwner("scope","owner");
  old.prepare(owner,"writer","write",{workspace:"retained"},[{id:"writer-slot",units:1,capacity:1}]);old.markSent(owner,"writer");
  old.reserveRequest(owner,"writer","request",[{id:"scope-budget",ceiling:3}]);old.settleRequest("request","unknown");old.settle("writer","unknown");
  const ledger=new UsageLedger(old),task=ledger.begin({sessionId:"scope",title:"Preserve this task"},1);
  ledger.record(sdkUsage({generationId:"generation",provider:"p",model:"m",role:"worker",startedAt:1,endedAt:2,usage:{input:10,output:2,cacheRead:3,cacheWrite:4},attemptIds:["request"],outcome:"failure",source:"prior-import"}),task.id);
  old.revokeOwner(owner);const before=businessDigest(old.db),totals=ledger.query();old.db.exec("DROP INDEX usage_task_lookup; DROP INDEX usage_started_lookup; PRAGMA user_version=2");old.close();
  assert.throws(()=>new Store(root),{code:"DATABASE_MIGRATION_REQUIRED"});
  const result=spawnSync(process.execPath,["--experimental-strip-types",fileURLToPath(new URL("../scripts/state-maintenance.ts",import.meta.url)),"upgrade",root],{encoding:"utf8"});
  assert.equal(result.status,0,result.stderr);const after=new Store(root);t.after(()=>after.close());
  const receipt=JSON.parse(result.stdout),observed={receipt,before,after:businessDigest(after.db),intents:after.intent("writer"),budget:after.bucket("scope-budget"),totals:new UsageLedger(after).query()};
  acceptance("AC37","v2-to-v3",{level:"P",observer:"separate-maintenance-process-and-SQLite",predicate:"business identity and usage total conserved",artifact:observerArtifact("v2-v3",observed)},()=>{
    assert.equal(receipt.version,3);assert.equal(businessDigest(after.db),before);assert.deepEqual(new UsageLedger(after).query(),totals);
    assert.equal(after.intent("writer")!.status,"unknown");assert.equal(after.claims().length,1);assert.equal(after.bucket("scope-budget")!.reserved,1);
    const next=after.claimOwner("scope","next");assert.throws(()=>after.prepare(next,"duplicate","write",{},[{id:"writer-slot",capacity:1,units:1}]),{code:"RESOURCE_DENIED"});
  });
});

test("[P] v3 migration can be interrupted before commit without losing old facts or allowing blind startup",async t=>{
  const {fork}=await import("node:child_process"),{recoverMaintenance,migrateStore}=await import("../src/store/maintenance.ts");
  const root=isolatedDirectory(t),old=new Store(root),owner=old.claimOwner("scope","old");
  old.prepare(owner,"unknown","write",{workspace:"retained"},[{id:"writer",capacity:1,units:1}]);old.markSent(owner,"unknown");old.settle("unknown","unknown");old.revokeOwner(owner);
  const ledger=new UsageLedger(old),task=ledger.begin({sessionId:"scope",title:"existing"},1);ledger.record(sdkUsage({generationId:"g",provider:"p",model:"m",role:"worker",startedAt:1,endedAt:2,usage:{input:17,output:3,cacheRead:0,cacheWrite:0},attemptIds:["r"],outcome:"success",source:"SDK"}),task.id);
  old.db.exec("DROP INDEX usage_task_lookup; DROP INDEX usage_started_lookup; PRAGMA user_version=2");const before=businessDigest(old.db);old.close();
  const child=fork(fileURLToPath(new URL("./fixtures/maintenance-worker.ts",import.meta.url)),[root,"schema-written"],{execArgv:["--experimental-strip-types"],stdio:["ignore","ignore","pipe","ipc"]});t.after(()=>child.kill("SIGKILL"));
  assert.equal((await once(child,"message"))[0].type,"ready");const reached=once(child,"message");child.send("go");assert.equal((await reached)[0].type,"cut");
  assert.throws(()=>new Store(root),{code:"STORE_MAINTENANCE_REQUIRED"});const exited=once(child,"exit");child.kill("SIGKILL");await exited;
  const restored=recoverMaintenance(root,"rollback");assert.equal(restored.version,2);assert.throws(()=>new Store(root),{code:"DATABASE_MIGRATION_REQUIRED"});migrateStore(root);
  const current=new Store(root);t.after(()=>current.close());const observed={before,after:businessDigest(current.db),facts:new UsageLedger(current).facts(),intent:current.intent("unknown"),claims:current.claims()};
  acceptance("AC37","transaction-cut",{level:"P",observer:"killed-migration-process-and-reopened-SQLite",predicate:"uncommitted migration requires explicit recovery and conserves facts",artifact:observerArtifact("migration-cut",observed)},()=>{
    assert.equal(observed.after,before);assert.equal(observed.facts[0].tokens.input,17);assert.equal(observed.intent!.status,"unknown");assert.equal(observed.claims.length,1);
  });
});

test("[S] usage replay and revisions after reopening contribute once and retained artifact loss is explicit",async t=>{
  const {Artifacts}=await import("../src/store/artifacts.ts"),{unlinkSync}=await import("node:fs"),{join}=await import("node:path");
  const root=isolatedDirectory(t),initial=new Store(root),ledger=new UsageLedger(initial),task=ledger.begin({sessionId:"s",title:"task"},1);
  const fact=sdkUsage({generationId:"generation",provider:"p",model:"m",role:"worker",startedAt:1,endedAt:2,usage:{input:10,output:2,cacheRead:0,cacheWrite:0},attemptIds:["request"],outcome:"success",source:"SDK"});ledger.record(fact,task.id);initial.close();
  const reopened=new Store(root);t.after(()=>reopened.close());const next=new UsageLedger(reopened);const result=next.record(fact,task.id);
  acceptance("AC37","replay-import",{level:"S",observer:"reopened-ledger-and-original-source-fact",predicate:"same source record cannot contribute twice",artifact:observerArtifact("usage-replay",{result,rows:next.query()})},()=>{assert.equal(result,"duplicate");assert.equal(next.facts().length,1);assert.equal(next.query()[0].tokens.input,10);});
  const revised={...fact,id:"corrected",revision:2,supersedes:fact.id,tokens:{...fact.tokens,input:12}};next.record(revised,task.id);const after=next.query();
  acceptance("AC37","usage-revision",{level:"S",observer:"raw-revisions-and-single-current-contribution",predicate:"revision replaces aggregate contribution but retains original fact",artifact:observerArtifact("usage-revision",{after,raw:reopened.list("usage-facts")})},()=>{assert.equal(after[0].tokens.input,12);assert.equal(next.facts().length,1);assert.equal(reopened.list("usage-facts").length,2);});
  const artifacts=new Artifacts(reopened),artifact=artifacts.pin(task.id,"snapshot","retained acceptance proof","runtime");unlinkSync(join(root,"artifacts",artifact.id));
  acceptance("AC37","missing-artifact",{level:"S",observer:"removed-file-and-retained-ledger",predicate:"missing evidence cannot reset usage or masquerade as a valid artifact",artifact:observerArtifact("missing-artifact",{artifact,rows:next.query()})},()=>{
    assert.throws(()=>artifacts.read(artifact.id,task.id,"snapshot"),{code:"ARTIFACT_MISSING_OR_CHANGED"});assert.equal(next.query()[0].tokens.input,12);assert.ok(reopened.get("artifacts",artifact.id));
  });
});

test("[P] new usage facts prevent rollback of a committed migration",async t=>{
  const {migrateStore,recoverMaintenance}=await import("../src/store/maintenance.ts"),{DatabaseSync}=await import("node:sqlite"),{join}=await import("node:path");
  const root=isolatedDirectory(t),old=new Store(root);old.db.exec("DROP INDEX usage_task_lookup; DROP INDEX usage_started_lookup; PRAGMA user_version=2");old.close();
  assert.throws(()=>migrateStore(root,point=>{if(point==="committed")throw new Error("hold migration fence");}),/hold migration fence/);
  const write=spawnSync(process.execPath,["--input-type=module","-e",`import {DatabaseSync} from "node:sqlite";const db=new DatabaseSync(process.argv[1]);db.prepare("INSERT INTO records VALUES(?,?,?)").run("usage-facts","later",JSON.stringify({generationId:"late-generation",tokens:{input:8}}));db.close();`,join(root,"runtime.db")],{encoding:"utf8"});
  assert.equal(write.status,0,write.stderr);
  acceptance("AC37","rollback-refused-after-new-facts",{level:"P",observer:"independent-SQLite-writer-and-maintenance-recovery",predicate:"rollback may not discard newly recorded consumption",artifact:observerArtifact("rollback-new-usage",{namespace:"usage-facts",id:"later",input:8})},()=>{
    assert.throws(()=>recoverMaintenance(root,"rollback"),{code:"MAINTENANCE_SOURCE_CHANGED"});assert.throws(()=>new Store(root),{code:"STORE_MAINTENANCE_REQUIRED"});
  });
});
