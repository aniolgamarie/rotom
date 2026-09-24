import { test, assert, matrixCase } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";

for (const terminal of ["complete","error","truncated","timeout"] as const)
test(`[S ${terminal === "complete" ? "REC-018" : terminal === "timeout" ? "REC-012" : "REC-017"}] modeled HTTP200 and ${terminal} retain the actual recovery state boundary`, async t => matrixCase("stream-terminals",terminal,async()=>{
  const store=new Store(isolatedDirectory(t)),clock=new FakeClock(),headers:Array<{status:number}>=[],actions:string[]=[];
  const snapshot:InteractiveSnapshot={sessionId:"session",leafId:"limited",provider:"fixture-provider",model:"fixture-model",idle:true,pendingMessages:false,terminationKnown:true,certified:true,blockedReasons:[]};
  const controller=new RecoveryController(store,configured(),{snapshot:()=>({...snapshot}),abort(){actions.push("abort");},
    // This is an explicit S adapter model. Physical HTTP/SDK observations have separate A/P/E cases.
    continue:async intent=>{actions.push(intent.id);headers.push({status:200});return{nativeId:"native-request"};}},clock,()=>0);
  t.after(()=>{controller.dispose();store.close();});
  controller.settled({status:429,message:"initial quota",stream:"error"});clock.advance(100);await flush();
  const running=controller.state(),intent=running.intentId!;assert.ok(intent);assert.equal(running.status,"RUNNING");assert.equal(running.attempts,1);
  assert.deepEqual(headers,[{status:200}]);assert.equal(store.intent(intent)!.status,"acked");assert.equal(store.claims().length,1);
  if(terminal==="timeout"){
    clock.advance(499);await flush();assert.equal(controller.state().status,"RUNNING");clock.advance(1);await flush();
    assert.equal(controller.state().status,"BLOCKED");assert.equal(controller.state().reason,"request_timeout_termination_unknown");
    assert.equal(store.intent(intent)!.status,"unknown");assert.equal(store.claims().length,1);assert.equal(actions.filter(value=>value==="abort").length,1);
    assert.throws(()=>controller.resume(),{code:"INTENT_RECONCILIATION_REQUIRED"});clock.advance(10000);await controller.tick();
    assert.equal(controller.state().attempts,1);assert.equal(headers.length,1);
  }else{
    snapshot.leafId="stream-terminal";
    controller.settled({status:200,message:terminal==="complete"?"completed":`fixture ${terminal}`,stream:terminal==="complete"?"complete":terminal==="truncated"?"incomplete":"error",responseObserved:true});
    assert.equal(store.intent(intent)!.status,"settled");assert.equal(store.intent(intent)!.nativeId,"native-request");assert.equal(store.claims().length,0);
    if(terminal==="complete"){
      assert.equal(controller.state().status,"DONE");assert.equal(store.get<{status:string}>("incidents","pool")!.status,"CLOSED");
      controller.settled({status:200,message:"completed",stream:"complete"});assert.equal(controller.state().attempts,1);
    }else{
      assert.equal(controller.state().status,terminal==="error"?"BLOCKED":"WAITING_QUOTA");
      assert.equal(controller.state().history.at(-1)!.message,`fixture ${terminal}`);assert.equal(store.get<{status:string}>("incidents","pool")!.status,"OPEN");
      controller.pause();clock.advance(10000);await controller.tick();assert.equal(controller.state().attempts,1);
    }
    assert.equal(headers.length,1);assert.equal(actions.length,1);
  }
  assert.equal(store.db.prepare("SELECT count(*) n FROM intents WHERE kind='continue'").get()!.n,1);
  if(process.env.TASK_KEEPER_TEST_RECORD_DIR){const path=join(dirname(process.env.TASK_KEEPER_TEST_RECORD_DIR),"state-stream-observers");mkdirSync(path,{recursive:true});writeFileSync(join(path,`${terminal}.json`),JSON.stringify({kind:"state-simulation",headers,actions,running,final:controller.state(),intent:store.intent(intent),claims:store.claims()},null,2));}
}));
