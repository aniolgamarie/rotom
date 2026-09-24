import { test, assert } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";
import type { TestContext } from "node:test";

function fixture(t:TestContext,deadline:number|null=null){
  const store=new Store(isolatedDirectory(t)),peer=new Store(store.root),clock=new FakeClock(),config=configured();config.recovery.maxWaitMs=deadline;
  store.db.exec("PRAGMA busy_timeout=1");
  const snapshot:InteractiveSnapshot={sessionId:"session",leafId:"leaf",provider:"fixture-provider",model:"fixture-model",idle:true,pendingMessages:false,terminationKnown:true,certified:true,blockedReasons:[]};
  let sends=0;const states:unknown[]=[];
  const controller=new RecoveryController(store,config,{snapshot:()=>({...snapshot}),abort(){},continue:async()=>{sends++;return{nativeId:"original"};}},clock,()=>0,state=>states.push(state));
  t.after(()=>{if(peer.db.isTransaction)peer.db.exec("ROLLBACK");controller.dispose();peer.close();store.close();});
  controller.settled({status:429,message:"original quota",stream:"error"});
  return{store,peer,clock,controller,snapshot,sends:()=>sends,states};
}

for(const cancel of [false,true])test(`[S] real pre-dispatch SQLite contention ${cancel?"respects user pause":"yields without consuming an attempt"}`,async t=>{
  const f=fixture(t),before=f.controller.state(),transaction=f.store.transaction.bind(f.store);let errorCode:number|undefined;
  f.store.transaction=((...args:Parameters<Store["transaction"]>)=>{
    f.peer.db.exec("BEGIN IMMEDIATE");
    try{return transaction(...args);}catch(error){errorCode=(error as {errcode:number}).errcode;throw error;}
    finally{f.peer.db.exec("ROLLBACK");f.store.transaction=transaction;}
  }) as Store["transaction"];
  f.clock.advance(100);await flush();const deferred=f.controller.state();
  assert.equal(errorCode,5);assert.equal(deferred.status,"WAITING_QUOTA");assert.equal(deferred.reason,"state_store_contended");
  assert.equal(deferred.lastDispatchError!.code,"ERR_SQLITE_ERROR");assert.equal(deferred.lastDispatchError!.sqliteCode,5);
  assert.equal(deferred.attempts,0);assert.equal(deferred.intentId,null);assert.equal(deferred.incidentId,before.incidentId);
  assert.equal(f.store.claims().length,0);assert.equal(f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n,0);assert.equal(f.sends(),0);
  if(cancel){f.controller.pause();f.clock.advance(1000);await flush();assert.equal(f.sends(),0);assert.equal(f.controller.state().status,"PAUSED");return;}
  f.clock.advance(99);await flush();assert.equal(f.sends(),0);f.clock.advance(1);await flush();assert.equal(f.sends(),1);
  assert.equal(f.controller.state().attempts,1);f.snapshot.leafId="done";f.controller.settled(null);assert.equal(f.controller.state().status,"DONE");
});

test("[S] SQLite contention cannot bypass the overall wait deadline",async t=>{
  const f=fixture(t,50);f.peer.db.exec("BEGIN IMMEDIATE");f.clock.advance(50);await flush();
  assert.equal(f.controller.state().status,"BLOCKED");assert.equal(f.controller.state().reason,"recovery_deadline_exhausted");
  assert.equal(f.controller.state().lastDispatchError!.sqliteCode,5);assert.equal(f.sends(),0);assert.equal(f.clock.pending,0);
  f.peer.db.exec("ROLLBACK");f.clock.advance(10000);await f.controller.tick();assert.equal(f.sends(),0);
});

test("[S] a non-contention SQLite error remains blocked with its original diagnostic",async t=>{
  const f=fixture(t);f.store.prepare=()=>{f.store.db.exec("SELECT * FROM intentionally_missing_table");throw new Error("unreachable");};
  f.clock.advance(100);await flush();assert.equal(f.controller.state().status,"BLOCKED");
  assert.equal(f.controller.state().lastDispatchError!.sqliteCode,1);assert.match(f.controller.state().lastDispatchError!.message,/no such table/);
  assert.equal(f.clock.pending,0);assert.equal(f.sends(),0);f.clock.advance(10000);await f.controller.tick();assert.equal(f.sends(),0);
});

test("[S] a status write failure after intent commit cannot schedule a fresh execution",async t=>{
  const f=fixture(t);let busy:unknown;
  f.peer.db.exec("BEGIN IMMEDIATE");try{f.store.db.exec("BEGIN IMMEDIATE");}catch(error){busy=error;}finally{f.peer.db.exec("ROLLBACK");}
  assert.equal((busy as {errcode:number}).errcode,5);
  const put=f.store.put.bind(f.store);let injected=false, runningWrites=0;
  f.store.put=(namespace,id,value)=>{
    if(namespace==="recovery"&&(value as {status:string}).status==="RUNNING"&&++runningWrites===2){injected=true;throw busy;}
    return put(namespace,id,value);
  };
  f.clock.advance(100);await flush();const state=f.controller.state();
  assert.equal(injected,true);assert.equal(state.status,"BLOCKED");assert.equal(state.lastDispatchError!.sqliteCode,5);
  assert.ok(state.intentId);assert.equal(f.store.intent(state.intentId)!.status,"prepared");assert.equal(f.store.claims().length,1);
  assert.equal(state.attempts,1);assert.equal(f.sends(),0);assert.equal(f.clock.pending,0);
  await assert.rejects(async()=>f.controller.resume(),{code:"INTENT_RECONCILIATION_REQUIRED"});
  f.clock.advance(10000);await f.controller.tick();assert.equal(f.sends(),0);assert.equal(f.store.claims().length,1);
});
