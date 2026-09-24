import { test, assert } from "./recorded-test.ts";
import { setImmediate as flush } from "node:timers/promises";
import { Store } from "../src/store/database.ts";
import { RecoveryController, type InteractiveSnapshot } from "../src/reliability/recovery.ts";
import { configured } from "./fixtures/config.ts";
import { FakeClock, isolatedDirectory } from "./helpers.ts";

test("[S T40] confirmed execution settlement frees an undelivered acknowledgement wait before another quota incident", async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock(); let sends = 0, cancelledListeners = 0;
  const snapshot: InteractiveSnapshot = {sessionId:"session",leafId:"initial",provider:"fixture-provider",model:"fixture-model",idle:true,pendingMessages:false,terminationKnown:true,certified:true,blockedReasons:[]};
  const controller = new RecoveryController(store, configured(), {
    snapshot: () => ({...snapshot}), abort() {},
    continue: async (_intent, signal) => { sends++; snapshot.idle = false; return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => { cancelledListeners++; reject(new Error("ack channel closed after settlement")); }, {once:true});
    }); },
  }, clock, () => 0);
  t.after(() => {controller.dispose();store.close();});
  controller.settled({status:429,message:"quota",stream:"error"}); clock.advance(100); await flush();
  const first = controller.state().intentId!; assert.equal(sends, 1);
  snapshot.idle = true; snapshot.leafId = "first-complete"; controller.settled(null); await flush();
  assert.equal(controller.state().status, "DONE"); assert.equal(store.intent(first)!.status, "settled"); assert.equal(store.claims().length, 0);
  controller.beginUserTurn(); snapshot.leafId = "second-limited";
  controller.settled({status:429,message:"new quota incident",stream:"error"}); clock.advance(100); await flush();
  assert.equal(cancelledListeners, 1); assert.equal(sends, 2); assert.notEqual(controller.state().intentId, first);
  snapshot.idle = true; snapshot.leafId = "second-complete"; controller.settled(null); await flush();
  assert.equal(controller.state().status, "DONE"); assert.equal(cancelledListeners, 2); assert.equal(controller.state().attempts, 2);
});

for (const identity of ["missing", "conflicting"] as const)
test(`[S T40] ${identity} durable continuation identity cannot certify an unacknowledged execution`, async t => {
  const store = new Store(isolatedDirectory(t)), clock = new FakeClock();
  const snapshot: InteractiveSnapshot = {sessionId:"session",leafId:"limited",provider:"fixture-provider",model:"fixture-model",idle:true,pendingMessages:false,terminationKnown:true,certified:true,blockedReasons:[]};
  let aborted = false;
  const controller = new RecoveryController(store, configured(), {
    snapshot:()=>({...snapshot}), abort(){}, continuationIdentity(){if(identity==="conflicting")throw new Error("conflicting native entry");return null;},
    continue:async(_intent,signal)=>new Promise((_resolve,reject)=>{signal.addEventListener("abort",()=>{aborted=true;reject(new Error("closed"));},{once:true});}),
  },clock,()=>0);
  t.after(()=>{controller.dispose();store.close();});
  controller.settled({status:429,message:"quota",stream:"error"});clock.advance(100);await flush();const id=controller.state().intentId!;
  snapshot.leafId="terminal-without-owned-entry";controller.settled(null);await flush();
  assert.equal(controller.state().status,"BLOCKED");assert.equal(controller.state().reason,"continuation_identity_unavailable");assert.equal(aborted,true);
  assert.equal(store.intent(id)!.status,"unknown");assert.equal(store.intent(id)!.nativeId,null);assert.equal(store.claims().length,1);
  assert.throws(()=>controller.resume(),{code:"INTENT_RECONCILIATION_REQUIRED"});
});

import { PiInteractiveAdapter } from "../src/adapters/pi-interactive.ts";

test("[U T40] durable continuation reconciliation requires one matching native scope epoch and leaf", () => {
  const intent = {id:"intent",scopeId:"scope",epoch:3,leafId:"leaf"};
  let entries: unknown[] = [];
  const adapter = Object.create(PiInteractiveAdapter.prototype) as PiInteractiveAdapter;
  Object.assign(adapter, {context:{sessionManager:{getEntries:()=>entries}}});
  assert.equal(adapter.continuationIdentity(intent), null);
  const entry = {id:"native-entry",type:"custom_message",customType:"task-keeper:continuation:v1",details:intent};
  entries = [entry]; assert.deepEqual(adapter.continuationIdentity(intent), {nativeId:"native-entry"});
  for (const changed of [{scopeId:"other"},{epoch:4},{leafId:"other"}]) {
    entries = [{...entry,details:{...intent,...changed}}]; assert.throws(()=>adapter.continuationIdentity(intent),{code:"CONTINUATION_IDENTITY_MISMATCH"});
  }
  entries = [entry,{...entry,id:"another-native-entry"}]; assert.throws(()=>adapter.continuationIdentity(intent),{code:"DUPLICATE_NATIVE_CONTINUATION"});
  entries = [{...entry,id:"../invalid"}]; assert.throws(()=>adapter.continuationIdentity(intent),{code:"INVALID_ID"});
});
