import {instant,timezone} from "../src/policies/configuration.ts";
import {windowContains,nextWindow} from "../src/policies/calendar.ts";
import {parseConfig} from "../src/config.ts";
import {test,assert,acceptance,observerArtifact} from "./recorded-test.ts";
import {completedState} from "./fixtures/service-state.ts";
import {submission} from "../src/policies/submission.ts";
import {selectModel} from "../src/policies/selection.ts";
import {configured} from "./fixtures/config.ts";
import {opinionBinding} from "../src/policies/opinion.ts";
import {fixedWorkflowPlan} from "../src/orchestration/workflow-plan.ts";
test("[U] trusted submission options are explicit and ordinary goal text stays literal",()=>{
  assert.deepEqual(submission("fix --model something"),{goal:"fix --model something",options:{}});
  assert.deepEqual(submission("--model p/m --second-opinion --group parse -- correct the parser"),{goal:"correct the parser",options:{model:"p/m",secondOpinion:true,comparisonGroup:"parse"}});
  for(const text of ["--auto-model --model p/m -- goal","--second-opinion --no-second-opinion -- goal","--unknown yes -- goal","--not-before tomorrow -- goal"])assert.throws(()=>submission(text));
});
test("[S] scheduled queue pause, resume and stop retain identity without acquiring workspace or model slots",async t=>{
  const f=completedState(t),before=f.store.claims();
  const next=f.service.submit("fix","Run later",{notBefore:Date.now()+3600000,deadline:Date.now()+7200000});
  assert.equal(next.status,"QUEUED");assert.equal(next.cwd,null);assert.equal(next.schedule?.admittedAt,null);assert.deepEqual(f.store.claims(),before);
  f.service.pause(next.id);assert.equal(f.service.get(next.id).status,"PAUSED");await f.service.resume(next.id);assert.equal(f.service.get(next.id).status,"QUEUED");
  assert.equal(f.service.get(next.id).schedule?.notBefore,next.schedule?.notBefore);assert.equal(f.store.list("managed-jobs").length,2);
  f.service.pause(next.id,true);assert.equal(f.service.get(next.id).status,"CANCELLED");assert.deepEqual(f.store.claims(),before);
});
test("[U] automatic rules remain inert for manual choice and eligibility precedes preference",()=>{
  const config=configured();config.routes.backup={...config.routes.primary,model:"other"};config.allowedRoutes.push("backup");
  config.modelPolicy.candidates=["primary","backup"];config.modelPolicy.defaultPreference=["backup","primary"];
  const input={automatic:false,manual:"primary",at:1,eligible:{primary:[],backup:[]}};
  assert.equal(selectModel(config,input).selected,"primary");assert.equal(selectModel(config,{...input,automatic:true}).selected,"backup");
  assert.equal(selectModel(config,{...input,automatic:true,eligible:{primary:[],backup:["not-certified"]}}).selected,"primary");
  config.modelPolicy.ranking="history-cost";
  assert.equal(selectModel(config,{...input,automatic:true}).reason,"history-insufficient-configured-order");
});
test("[S] enabled opinion fixes a read-only required step and cannot delete the original acceptance checks",t=>{
  const f=completedState(t),config=f.config;config.secondOpinion.enabled=true;
  assert.throws(()=>opinionBinding(config),{code:"SECOND_OPINION_READONLY_REQUIRED"});
  config.executionProfiles.reviewer.tools=["read","grep","find","ls"];
  const binding=opinionBinding(config);assert.equal(binding.maxExchanges,2);assert.equal(binding.route,"primary");
  const plan=fixedWorkflowPlan(config,{id:"opinion",workScope:"scope",goal:"fix",workflow:"fix",policyDigest:"policy",snapshot:"tree",workspaceLock:"lock"});
  assert.deepEqual(plan.spec.required,["build","focused-tests","independent-review","second-opinion"]);
  const opinion=plan.steps.find(step=>step.id==="second-opinion")!;assert.equal(opinion.kind,"review");assert.equal(opinion.optional,false);
  assert.deepEqual(opinion.dependencies,["build","focused-tests","extra"]);assert.deepEqual(plan.steps.find(step=>step.id==="independent-review")!.dependencies,["second-opinion"]);
  const disabled=fixedWorkflowPlan(config,{id:"off",workScope:"scope",goal:"fix",workflow:"fix",policyDigest:"policy",snapshot:"tree",workspaceLock:"lock",secondOpinion:false});
  assert.equal(disabled.steps.some(step=>step.id==="second-opinion"),false);assert.ok(disabled.spec.required.includes("independent-review"));
});


test("[U] calendar acceptance covers offsets, inclusive starts, exclusive ends, weekdays and both DST transitions",()=>{
  const errorCode=(call:()=>unknown)=>{try{call();return "accepted";}catch(error){return (error as {code?:string}).code??"unexpected-error";}};
  const offset={local:"2026-09-14T10:00:00+08:00",utc:"2026-09-14T02:00:00Z"};
  const observed=[instant(offset.local),instant(offset.utc),errorCode(()=>instant("2026-09-14T10:00"))];
  acceptance("AC19","offset-input",{level:"U",observer:"fixed-UTC-calendar-oracle",predicate:"offset resolves to specified UTC instant",artifact:observerArtifact("calendar-offset",{offset,observed})},()=>assert.deepEqual(observed,[Date.UTC(2026,8,14,2),Date.UTC(2026,8,14,2),"ABSOLUTE_TIME_REQUIRED"]));
  const zones=["Imaginary/Zone","+08:00"],errors=zones.map(zone=>errorCode(()=>timezone(zone)));
  acceptance("AC19","invalid-timezone",{level:"U",observer:"public-timezone-validator",predicate:"invalid IANA inputs rejected",artifact:observerArtifact("calendar-zone",{zones,errors})},()=>assert.deepEqual(errors,["INVALID_TIMEZONE","INVALID_TIMEZONE"]));
  const rows=[
    {variant:"start-inclusive",window:{days:[1],start:"10:00",end:"11:00"},time:"2026-09-14T10:00:00+08:00",expected:true},
    {variant:"end-exclusive",window:{days:[1],start:"10:00",end:"11:00"},time:"2026-09-14T11:00:00+08:00",expected:false},
    {variant:"cross-midnight",window:{days:[1],start:"23:00",end:"02:00"},time:"2026-09-15T01:00:00+08:00",expected:true},
    {variant:"weekday",window:{days:[1],start:"10:00",end:"11:00"},time:"2026-09-15T10:30:00+08:00",expected:false},
  ];
  for(const row of rows){const actual=windowContains(row.window,instant(row.time),"Asia/Shanghai");acceptance("AC19",row.variant,{level:"U",observer:"fixed-calendar-truth-table",predicate:row.variant,artifact:observerArtifact(`calendar-${row.variant}`,{...row,actual})},()=>assert.equal(actual,row.expected));}
  const start="2026-03-08T01:59:00-05:00",deadline="2026-03-08T04:00:00-04:00",window={days:[7],start:"02:00",end:"03:00"};
  const gap=nextWindow([window],instant(start),"America/New_York",instant(deadline));
  acceptance("AC19","dst-gap",{level:"U",observer:"fixed-UTC-DST-interval",predicate:"nonexistent local hour has no eligible instant",artifact:observerArtifact("calendar-gap",{start,deadline,window,actual:gap})},()=>assert.equal(gap,null));
  const foldTimes=["2026-11-01T01:45:00-04:00","2026-11-01T01:45:00-05:00"],fold=foldTimes.map(time=>windowContains({days:[7],start:"01:30",end:"02:00"},instant(time),"America/New_York"));
  acceptance("AC19","dst-fold",{level:"U",observer:"two-distinct-UTC-instances-of-local-fold",predicate:"both copies of local hour are eligible",artifact:observerArtifact("calendar-fold",{foldTimes,actual:fold})},()=>assert.deepEqual(fold,[true,true]));
  const requestWindow={timePolicy:{admissionBoundary:"request-attempt"}},rejected=errorCode(()=>parseConfig(requestWindow));
  acceptance("AC20","request-window-rejected",{level:"U",observer:"public-config-parser",predicate:"unsupported per-request window rejected before work",artifact:observerArtifact("request-window",{input:requestWindow,rejected})},()=>assert.equal(rejected,"REQUEST_WINDOW_NOT_SUPPORTED"));
});


test("[U] time preference uses priority then declaration order and falls back without crossing eligibility",()=>{
  const config=configured();config.routes.backup={...config.routes.primary,model:"other"};config.allowedRoutes.push("backup");config.modelPolicy.candidates=["primary","backup"];config.modelPolicy.defaultPreference=["primary"];
  config.timePolicy.timezone="UTC";config.modelPolicy.preferByTime=[{priority:1,window:{days:[1],start:"08:00",end:"12:00"},orderedCandidates:["backup","primary"]}];
  const input={automatic:true,manual:null,at:Date.UTC(2026,8,14,9),eligible:{primary:[],backup:[]}};
  const ordered=selectModel(config,input);acceptance("AC22","ordered-rules",{level:"U",observer:"fixed-time-selector-input",predicate:"matching rule chooses declared order",artifact:observerArtifact("ordered-rule",{policy:config.modelPolicy,input,result:ordered})},()=>{assert.equal(ordered.selected,"backup");assert.equal(ordered.reason,"time-preference:0");});
  config.modelPolicy.preferByTime.push({priority:2,window:{days:[1],start:"09:00",end:"10:00"},orderedCandidates:["primary"]},{priority:2,window:{days:[1],start:"09:00",end:"10:00"},orderedCandidates:["backup"]});
  const overlap=selectModel(config,input);acceptance("AC22","overlap-priority",{level:"U",observer:"overlapping-priority-and-stable-index",predicate:"higher priority then first declaration wins",artifact:observerArtifact("overlap-rule",{policy:config.modelPolicy,result:overlap})},()=>{assert.equal(overlap.selected,"primary");assert.equal(overlap.reason,"time-preference:1");});
  const none=selectModel(config,{...input,at:Date.UTC(2026,8,15,9)});acceptance("AC22","no-match",{level:"U",observer:"nonmatching-weekday-and-default-order",predicate:"no time match uses configured default",artifact:observerArtifact("no-time-rule",none)},()=>{assert.equal(none.selected,"primary");assert.equal(none.reason,"configured-order");});
  const unavailable=selectModel(config,{...input,eligible:{primary:["not-certified"],backup:["quota-cooldown"]}});acceptance("AC22","all-unavailable",{level:"U",observer:"all-candidate-hard-rejections",predicate:"no unapproved substitute is invented",artifact:observerArtifact("unavailable-models",unavailable)},()=>{assert.equal(unavailable.selected,null);assert.equal(unavailable.rejected.length,2);assert.equal(unavailable.reason,"no-eligible-authorized-model");});
});

test("[S] changing a start window leaves running work authorized and requires user resume for the queued task",async t=>{
  const f=completedState(t),running=f.service.get(f.jobId),queued=f.service.submit("fix","later",{notBefore:Date.now()+3600000,deadline:Date.now()+7200000});
  const identity=running.policyDigest;f.config.timePolicy.timezone="UTC";f.config.timePolicy.windows=[{days:[1,2,3,4,5,6,7],start:"00:00",end:"23:59"}];
  f.service.pause(queued.id);await assert.rejects(f.service.resume(queued.id),{code:"START_POLICY_CHANGE_REQUIRES_USER_RESUME"});
  await f.service.resume(queued.id,true);assert.equal(f.service.get(queued.id).status,"QUEUED");assert.equal(f.store.list("start-policy-authorizations").length,1);
  assert.equal(f.service.get(queued.id).policyDigest,identity);assert.equal(f.service.get(f.jobId).status,"RUNNING");f.finalize();assert.equal(f.service.get(f.jobId).status,"COMPLETED");
});
