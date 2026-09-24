import { test, assert, evidence } from "./recorded-test.ts";
import { completedState } from "./fixtures/service-state.ts";
import { fixedWorkflowPlan } from "../src/orchestration/workflow-plan.ts";

test("[S SCH-004 TK02] a check that creates a duplicate/self-dependent step is refused before queuing another job", t => {
  const f=completedState(t);f.config.workflow.requiredChecks.fix.push("implement");f.config.verificationBindings.implement={...f.config.verificationBindings.build};
  const preview=fixedWorkflowPlan(f.config,{id:"preview",workScope:f.owner.scopeId,goal:"invalid plan",workflow:"fix",policyDigest:"policy",snapshot:"preview",workspaceLock:"preview"});
  assert.equal(preview.steps.filter(step=>step.id==="implement").length,2);assert.ok(preview.steps.some(step=>step.id==="implement"&&step.dependencies.includes("implement")));
  const jobs=f.store.list("managed-jobs"),intents=f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n;
  for(const id of ["SCH-004","TK02"]) evidence(id,()=>{
    assert.throws(()=>f.service.submit("fix","Reject the invalid dependency plan"),{code:"DUPLICATE_STEP"});
    assert.deepEqual(f.store.list("managed-jobs"),jobs);assert.equal(f.store.db.prepare("SELECT count(*) n FROM intents").get()!.n,intents);
  });
  f.config.workflow.requiredChecks.fix=f.config.workflow.requiredChecks.fix.filter(id=>id!=="implement");
  const accepted=f.service.submit("fix","Valid fixed plan");assert.equal(accepted.status,"QUEUED");assert.equal(f.store.list("managed-jobs").length,jobs.length+1);
});
