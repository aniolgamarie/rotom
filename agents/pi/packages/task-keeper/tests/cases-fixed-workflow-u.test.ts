import { test, assert } from "./recorded-test.ts";
import { fixedWorkflowPlan } from "../src/orchestration/workflow-plan.ts";
import { validatePlan } from "../src/orchestration/scheduler.ts";
import { configured } from "./fixtures/config.ts";
import { requestBudgetAvailable } from "../src/contracts/budget.ts";
import { resourceClaimPlan } from "../src/contracts/resources.ts";
import { applyProjectPolicy } from "../src/config.ts";

function fixture() {
  const config = configured();
  for (const id of ["build", "focused-tests", "lint", "optional-check"]) config.verificationBindings[id] = {
    executable: "trusted-check", args: [], environment: {}, timeoutMs: 1000, kind: "tests", parser: "json", minimumTests: 1, inputs: [] };
  return { config, input: { id: "job", workScope: "scope", goal: "Preserve root acceptance", workflow: "fix" as const,
    policyDigest: "policy", snapshot: "tree", workspaceLock: "workspace-source" } };
}

test("[U CFG-004] writer upper bound disables fix at zero and preserves the single writer support boundary", () => {
  const { config, input } = fixture();
  for (const limit of [0, 1, 4]) {
    config.limits.writersPerJob = limit;
    if (limit === 0) assert.throws(() => fixedWorkflowPlan(config, input), { code: "WRITERS_DISABLED" });
    else assert.equal(fixedWorkflowPlan(config, input).steps.filter(step => step.kind === "write").length, 1);
    assert.equal(fixedWorkflowPlan(config, { ...input, workflow: "inspect" }).steps.filter(step => step.kind === "write").length, 0);
  }
  const restricted = applyProjectPolicy(config, { limits: { writersPerJob: 0 } });
  assert.equal(restricted.limits.writersPerJob, 0);
  assert.throws(() => fixedWorkflowPlan(restricted, input), { code: "WRITERS_DISABLED" });
  assert.equal(config.limits.writersPerJob, 4);
});

test("[U RTB-012] fixed local verification demands only compute and frozen workspace when model budget is exhausted", () => {
  const { config, input } = fixture();
  const { steps } = fixedWorkflowPlan(config, input);
  for (const step of steps.filter(step => step.kind === "verify")) {
    assert.deepEqual(step.resources.map(d => d.id), ["heavy-verifiers", "workspace-source"]);
    const observations = step.resources.map(d => ({ id: d.id, capacity: d.capacity, used: 0 }));
    for (const budget of [{ used: 4, reserved: 0, ceiling: 4 }, { used: 1, reserved: 3, ceiling: 4 }]) {
      const before = structuredClone(budget); assert.equal(requestBudgetAvailable(budget), false);
      assert.deepEqual(resourceClaimPlan(step.resources, observations), step.resources);
      assert.deepEqual(budget, before);
    }
  }
  assert.ok(steps.some(step => step.kind === "review" && !step.optional));
});

test("[U T77] direct plans retain mandatory build tests and independent review even when configuration omits them", () => {
  const { config, input } = fixture(); config.workflow.recipes = ["direct"];
  for (const required of [[], ["lint"]]) {
    config.workflow.requiredChecks.fix = required; const before = structuredClone(config), { spec, steps } = fixedWorkflowPlan(config, input);
    for (const id of ["build", "focused-tests", "independent-review", ...required]) {
      assert.ok(spec.required.includes(id)); assert.equal(steps.find(step => step.id === id)!.optional, false);
    }
    assert.deepEqual(steps.find(step => step.id === "implement")!.dependencies, ["baseline:build"]);
    assert.ok(steps.find(step => step.id === "independent-review")!.dependencies.includes("focused-tests"));
    assert.deepEqual(steps.find(step => step.id === "independent-review")!.allowedSkippedDependencies, []);
    assert.equal(spec.maxSteps, config.limits.dispatchedStepsPerJob); assert.equal(spec.maxSemanticAttempts, config.limits.semanticAttemptsPerImplementationTask);
    assert.doesNotThrow(() => validatePlan(steps, spec.maxSteps)); assert.deepEqual(config, before);
  }
});

test("[U WFL-002] bounded inspect plans require one scout and one independent review without allocating a writer", () => {
  const { config, input } = fixture(), before = structuredClone(config);
  const { spec, steps } = fixedWorkflowPlan(config, { ...input, workflow: "inspect" });
  assert.deepEqual(steps.map(step => [step.id, step.kind, step.role]), [["inspect", "read", "scout"], ["scope-evidence-review", "review", "reviewer"]]);
  assert.deepEqual(spec.required, ["scope-evidence-review"]); assert.deepEqual(steps[1].dependencies, ["inspect"]);
  assert.ok(steps.every(step => !step.optional)); assert.equal(steps.some(step => step.kind === "write"), false);
  assert.deepEqual(config, before); assert.doesNotThrow(() => validatePlan(steps, spec.maxSteps));
});

test("[U] legacy recipe names cannot bypass an explicit disabled second-opinion switch", () => {
  const { config, input } = fixture(); config.workflow.recipes=["critique"];config.workflow.optionalChecks.fix=["optional-check"];
  const {spec,steps}=fixedWorkflowPlan(config,input),review=steps.find(step=>step.id==="independent-review")!;
  assert.equal(steps.some(step=>step.id==="optional-critique"||step.id==="second-opinion"),false);assert.equal(review.optional,false);
  assert.deepEqual(review.allowedSkippedDependencies,["optional-check"]);assert.ok(spec.required.includes("build"));assert.ok(spec.required.includes("focused-tests"));assert.ok(spec.required.includes("independent-review"));
  delete config.verificationBindings.build;assert.throws(()=>fixedWorkflowPlan(config,input),{code:"CHECK_BINDING_REQUIRED",message:"build"});
});
