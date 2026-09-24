import { sharedWriteResources } from "../src/workspace/shared-resources.ts";
import { fixedWorkflowPlan } from "../src/orchestration/workflow-plan.ts";
import { configured } from "./fixtures/config.ts";
import { applyProjectPolicy } from "../src/config.ts";
import { test, assert, evidence } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { Scheduler, type PlanStep } from "../src/orchestration/scheduler.ts";
import { mkdirSync, symlinkSync } from "node:fs";
import { join } from "node:path";
import { workspaceResource } from "../src/workspace/worktree.ts";
import { isolatedDirectory } from "./helpers.ts";

const spec = (id: string) => ({ id, workScope: "scope", version: 1, objective: "Atomic resource admission", workflow: "fix" as const,
  required: ["check"], optional: [], allowPartial: false, policyDigest: "policy", snapshot: "tree", maxSteps: 8, maxSemanticAttempts: 3 });
const step = (resources: string[]): PlanStep => ({ id: "work", role: "worker", kind: "write", dependencies: [], allowedSkippedDependencies: [], optional: false,
  resources: resources.map(id => ({ id, capacity: 1, units: 1 })) });

test("[S SCH-007 SCH-008 TK04] reverse resource orders admit all-or-none and make progress only after confirmed release", t => {
  const store = new Store(isolatedDirectory(t)), reader = new Store(store.root); t.after(() => { reader.close(); store.close(); });
  const owner = store.claimOwner("scope", "owner"), queue = new Scheduler(store, owner);
  queue.submit(spec("a"), [step(["source", "index"])], 0, 0); queue.submit(spec("b"), [step(["index", "source"])], 0, 0);
  queue.submit(spec("independent"), [step(["other"])], 0, 0);
  const first = queue.dispatch("a", "work", "tree"); store.markSent(owner, first.id);
  for (const id of ["SCH-007", "TK04"]) evidence(id, () => {
    assert.throws(() => queue.dispatch("b", "work", "tree"), { code: "RESOURCE_DENIED" });
    assert.deepEqual(reader.claims().map(claim => [claim.resource_id, claim.intent_id]), [["index", first.id], ["source", first.id]]);
    assert.equal(queue.job("b").dispatched, 0); assert.equal(queue.job("b").steps[0].status, "pending"); assert.equal(queue.job("b").steps[0].intentId, null);
    assert.equal(reader.db.prepare("SELECT count(*) n FROM intents").get()!.n, 1);
  });
  const other = queue.dispatch("independent", "work", "tree"); store.markSent(owner, other.id);
  queue.finish("a", "work", { terminated: false, passed: false, artifactId: null }, 1);
  assert.equal(queue.next(10000), null); assert.throws(() => queue.dispatch("b", "work", "tree"), { code: "RESOURCE_DENIED" });
  assert.equal(queue.job("a").steps[0].status, "unknown"); assert.equal(reader.claims().length, 3);
  queue.finish("a", "work", { terminated: true, passed: false, artifactId: null }, 10001);
  for (const id of ["SCH-007", "SCH-008", "TK04"]) evidence(id, () => {
    assert.equal(queue.next(10002)!.jobId, "b"); assert.deepEqual(reader.claims().map(claim => claim.resource_id), ["other"]);
    assert.equal(reader.intent(first.id)!.status, "settled"); assert.equal(queue.job("independent").steps[0].status, "running");
  });
  const next = queue.dispatch("b", "work", "tree");
  for (const id of ["SCH-007", "SCH-008", "TK04"]) evidence(id, () => {
    assert.equal(queue.job("b").dispatched, 1); assert.equal(reader.claims().filter(claim => claim.intent_id === next.id).length, 2);
    assert.throws(() => queue.dispatch("b", "work", "tree"), { code: "STEP_NOT_READY" });
    assert.equal(reader.claims().length, 3); assert.equal(reader.intent(other.id)!.status, "sent");
  });
});


for (const mode of ["write", "verify"] as const)
test(`[S ${mode === "write" ? "TK05" : "TK06"}] an aliased workspace cannot admit a writer while ${mode} still owns the source`, t => {
  const root = isolatedDirectory(t), cwd = join(root, "source"), alias = join(root, "alias"); mkdirSync(cwd); symlinkSync(cwd, alias);
  const store = new Store(join(root, "state")); t.after(() => store.close());
  const owner = store.claimOwner("scope", "owner"), resource = workspaceResource(cwd), aliased = workspaceResource(alias);
  assert.equal(resource, aliased);
  store.prepare(owner, "existing", mode, { jobId: "first" }, [{ id: resource, units: 1, capacity: 1 }]); store.markSent(owner, "existing");
  for (const status of ["sent", "unknown"] as const) {
    if (status === "unknown") store.settle("existing", "unknown");
    assert.throws(() => store.prepare(owner, "contender", "write", { jobId: "second" }, [{ id: aliased, units: 1, capacity: 1 }]), { code: "RESOURCE_DENIED" });
    assert.equal(store.intent("contender"), null); assert.equal(store.intent("existing")!.status, status);
    assert.equal(store.claims().length, 1); assert.equal(store.claims()[0].intent_id, "existing");
  }
  store.settle("existing", "terminated");
  assert.equal(store.prepare(owner, "contender", "write", { jobId: "second" }, [{ id: aliased, units: 1, capacity: 1 }]).status, "prepared");
  assert.equal(store.claims().length, 1); assert.equal(store.claims()[0].intent_id, "contender");
});


test("[S SCH-009 TK05 TK06] declared shared directories bind fixed writers and verifiers to the same atomic exclusion", t => {
  const root = isolatedDirectory(t), source = join(root, "shared"), alias = join(root, "alias"); mkdirSync(source); symlinkSync(source, alias);
  const config = configured();
  for (const id of ["build", "focused-tests"]) config.verificationBindings[id] = { executable: process.execPath, args: [], environment: {}, timeoutMs: 1000,
    kind: id === "build" ? "build" : "tests", parser: "json", minimumTests: 1, sharedMutableDirectories: id === "build" ? [source, alias] : [alias] };
  const independent = join(root, "independent"); mkdirSync(independent);
  const independentDemand = sharedWriteResources({ build: { ...config.verificationBindings.build, sharedMutableDirectories: [independent] } }).build;
  const resources = sharedWriteResources(config.verificationBindings), shared = resources.build[0];
  const input = { id: "job", workScope: "scope", goal: "Shared outputs", workflow: "fix" as const, policyDigest: "policy", snapshot: "tree", workspaceLock: "workspace", sharedWriteResources: resources };
  const { steps } = fixedWorkflowPlan(config, input), writer = steps.find(step => step.kind === "write")!, verifier = steps.find(step => step.id === "build")!;
  for (const id of ["SCH-009", "TK05", "TK06"]) evidence(id, () => {
    assert.equal(resources.build.length, 1); assert.deepEqual(resources.build, resources["focused-tests"]);
    assert.equal(writer.resources.filter(resource => resource.id === shared.id).length, 1);
    assert.equal(verifier.resources.filter(resource => resource.id === shared.id).length, 1);
    assert.ok(steps.find(step => step.id === "baseline:build")!.resources.some(resource => resource.id === shared.id));
    assert.ok(steps.filter(step => step.kind === "review").every(step => !step.resources.some(resource => resource.id === shared.id)));
  });
  const store = new Store(join(root, "state")); t.after(() => store.close()); const owner = store.claimOwner("scope", "owner");
  for (const [index, first] of [writer, verifier].entries()) {
    const held = `held-${index}`, pending = `pending-${index}`, other = first === writer ? verifier : writer;
    store.prepare(owner, held, first.kind, {}, first.resources); store.markSent(owner, held);
    assert.equal(store.prepare(owner, `independent-${index}`, "verify", {}, independentDemand).status, "prepared");
    store.settle(`independent-${index}`, "not_sent");
    for (const state of ["sent", "unknown"] as const) {
      if (state === "unknown") store.settle(held, "unknown");
      for (const id of ["SCH-009", "TK05", "TK06"]) evidence(id, () => {
        assert.throws(() => store.prepare(owner, pending, other.kind, {}, other.resources), { code: "RESOURCE_DENIED" });
        assert.equal(store.intent(pending), null); assert.ok(store.claims().every(claim => claim.intent_id === held));
      });
    }
    store.settle(held, "terminated"); assert.equal(store.prepare(owner, pending, other.kind, {}, other.resources).status, "prepared"); store.settle(pending, "not_sent");
  }
  assert.deepEqual(sharedWriteResources({}), {});
  config.verificationBindings.build.sharedMutableDirectories = ["relative"];
  assert.throws(() => sharedWriteResources(config.verificationBindings), { code: "SHARED_DIRECTORY_MUST_BE_ABSOLUTE" });
  config.verificationBindings.build.sharedMutableDirectories = [join(root, "missing")];
  assert.throws(() => sharedWriteResources(config.verificationBindings), { code: "SHARED_DIRECTORY_UNAVAILABLE" });
  assert.throws(() => applyProjectPolicy(config, { verificationBindings: { build: { sharedMutableDirectories: [source] } } }), { code: "UNKNOWN_FIELD" });
});
