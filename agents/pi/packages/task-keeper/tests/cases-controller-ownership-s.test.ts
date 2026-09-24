import { test, assert, evidence } from "./recorded-test.ts";
import { TaskService } from "../src/orchestration/service.ts";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { completedState } from "./fixtures/service-state.ts";

test("[S EXE-009 T49] another dispatcher cannot claim a live scope or reset its existing task", async t => {
  const f = completedState(t), internal = f.service as unknown as {pi:ExtensionAPI;context:ExtensionContext};
  const owner = f.store.owner(f.owner.scopeId), job = f.service.get(f.jobId), plan = f.store.get("jobs", f.jobId), claims = f.store.claims();
  for (const id of ["EXE-009", "T49"]) evidence(id, () => {
    assert.throws(() => new TaskService(internal.pi, f.store, f.config, internal.context), {code:"OWNER_CONFLICT"});
    assert.deepEqual(f.store.owner(f.owner.scopeId), owner); assert.deepEqual(f.service.get(f.jobId), job);
    assert.deepEqual(f.store.get("jobs", f.jobId), plan); assert.deepEqual(f.store.claims(), claims);
    assert.equal(f.store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0);
  });
  await f.service.dispose();
  const successor = new TaskService(internal.pi, f.store, f.config, internal.context);
  try { for (const id of ["EXE-009", "T49"]) evidence(id, () => {
    const current = f.store.owner(f.owner.scopeId)!; assert.equal(current.active, true); assert.ok(current.epoch > owner!.epoch); assert.notEqual(current.token, owner!.token);
    assert.equal(successor.get(f.jobId).id, job.id); assert.equal(successor.get(f.jobId).workScope, job.workScope);
    assert.equal(f.store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0);
  }); } finally { await successor.dispose(); }
});
