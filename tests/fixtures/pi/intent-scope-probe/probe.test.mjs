// 只导入自有纯记录函数；不加载SDK、不启动宿主、不读取账号或写/work。
import assert from "node:assert/strict";
import { test } from "node:test";
import { observeCase } from "../../../../scripts/pi-probe-intent-scope.mjs";

test("started case retains failure and partial counters without original error", async () => {
  const report = { cases: [] };
  await assert.rejects(observeCase(report, "confirmed-idle", async state => {
    state.confirm_calls = 1;
    state.model_requests = 1;
    throw new Error("SYNTHETIC_PRIVATE_ERROR");
  }));
  assert.equal(report.cases.length, 1);
  assert.equal(report.cases[0].outcome, "failed");
  assert.equal(report.cases[0].confirm_calls, 1);
  assert.equal(report.cases[0].model_requests, 1);
  assert.equal(JSON.stringify(report).includes("SYNTHETIC_PRIVATE_ERROR"), false);
});

test("case remains failed until its full asynchronous body completes", async () => {
  const report = { cases: [] };
  let done;
  const gate = new Promise(resolve => { done = resolve; });
  const running = observeCase(report, "declined", async state => {
    state.confirm_calls = 1;
    await gate;
    state.command_status = "declined";
  });
  assert.equal(report.cases[0].outcome, "failed");
  done();
  const observed = await running;
  assert.equal(observed.outcome, "observed");
  assert.equal(observed.command_status, "declined");
});

test("failed cleanup does not overwrite a previously observed different case", async () => {
  const report = { cases: [] };
  await observeCase(report, "base", async () => {});
  await assert.rejects(observeCase(report, "off", async state => {
    state.command_status = "not-called";
    throw new Error("synthetic cleanup failure");
  }));
  assert.deepEqual(report.cases.map(value => [value.case_id, value.outcome]), [["base", "observed"], ["off", "failed"]]);
});

test("unknown scene cannot invoke body or enter the fixed report", async () => {
  const report = { cases: [] };
  let calls = 0;
  await assert.rejects(observeCase(report, "unknown", async () => { calls++; }));
  assert.equal(calls, 0);
  assert.deepEqual(report.cases, []);
});

test("same scene cannot overwrite its preserved failed counters", async () => {
  const report = { cases: [] };
  await assert.rejects(observeCase(report, "canceled", async state => { state.model_requests = 1; throw new Error("failed"); }));
  await assert.rejects(observeCase(report, "canceled", async () => {}));
  assert.equal(report.cases.length, 1);
  assert.equal(report.cases[0].outcome, "failed");
  assert.equal(report.cases[0].model_requests, 1);
});

import { observeAsyncTool } from "../../../../scripts/pi-probe-intent-scope.mjs";
import { createConfirmedIntentScope } from "../../../../agents/pi/runtime/confirmed-intent-scope.ts";
for (const caseId of ["async-confirmed", "async-late-resolve", "async-late-reject"]) test("actual self-owned async execute continuation "+caseId, async () => {
  const report={cases:[]}, calls=[];let control,resolve,reject;
  await observeCase(report,caseId,async state=>{
    control=createConfirmedIntentScope({enabled:true,current:()=>({profile:"pi-full",session_id:"session",cwd:"/project",runtime_identity:"d".repeat(64),config_identity:"e".repeat(64),policy_generation:1,cancel_epoch:0}),allocateIntent:async()=>({session_scope:"a".repeat(32),intent_ref:"b".repeat(32)}),allocateRequestAsync:request=>{
      calls.push(request);assert(Object.isFrozen(request));assert.equal(request.tool_call_id,"scope-call/1");
      return caseId==="async-confirmed"?Promise.resolve("c".repeat(32)):new Promise((done,fail)=>{resolve=done;reject=fail;});
    },confirmationMessage:"Synthetic confirmation",submit:async objective=>{
      control.onInput({type:"input",source:"extension",text:objective});control.onAgentStart();await Promise.resolve();
      await observeAsyncTool(control,"scope-call/1",state,()=>{
        assert.equal(calls.length,1);
        if(caseId!=="async-confirmed"){
          control.invalidate();
          if(caseId==="async-late-resolve")resolve("c".repeat(32));else {const marker="SYNTHETIC_PRIVATE_ERROR";reject(Error(marker));}
          state.async_late_results++;
        }
      });
      control.onAgentSettled();
    }});
    const ctx={hasUI:true,cwd:"/project",isIdle:()=>true,hasPendingMessages:()=>false,sessionManager:{getSessionId:()=>"session"},ui:{confirm:async()=>true}};
    state.command_status=(await control.run("synthetic objective",ctx)).status;
  });
  const row=report.cases[0];assert.equal(row.outcome,"observed");assert.equal(calls.length,1);assert.deepEqual(calls[0],{session_scope:"a".repeat(32),intent_ref:"b".repeat(32),tool_call_id:"scope-call/1"});
  assert.equal(row.async_binding_waits,caseId==="async-confirmed"?2:1);assert.equal(row.async_late_results,caseId==="async-confirmed"?0:1);assert.equal(row.scoped_tool_calls,caseId==="async-confirmed"?1:0);assert.equal(row.unscoped_tool_calls,caseId==="async-confirmed"?0:1);assert.equal(row.command_status,caseId==="async-confirmed"?"settled":"retired");
  assert.equal(await control.bindingForToolAsync("scope-call/1"),null);assert.equal(JSON.stringify(report).includes("SYNTHETIC_PRIVATE_ERROR"),false);
});
test("malformed synthetic slash ID is rejected before requesting capability",async()=>{let calls=0;const state={case_id:"async-confirmed"};await assert.rejects(observeAsyncTool({bindingForToolAsync(){calls++;}},"bad id",state));assert.equal(calls,0);});
