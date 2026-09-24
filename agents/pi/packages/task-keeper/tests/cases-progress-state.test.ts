import { test, assert } from "./recorded-test.ts";
import { Store } from "../src/store/database.ts";
import { projectProgress, type Progress } from "../src/evidence/progress.ts";
import { outcome, type Receipt } from "../src/contracts/task.ts";
import { acceptedCandidate } from "./fixtures/outcome.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[S T83] persisted native completion and task acceptance remain separate until required evidence changes", t => {
  const root = isolatedDirectory(t), store = new Store(root), reader = new Store(root); t.after(() => { reader.close(); store.close(); });
  const { spec, facts } = acceptedCandidate(), completeFacts = structuredClone(facts); facts.checks = facts.checks.filter(check => check.checkId !== "tests");
  const blocked = outcome(spec, facts); store.put("receipts", spec.id, blocked);
  const initial: Progress = { jobId: spec.id, ownerEpoch: 1, nativeStatus: "running", taskStatus: "BLOCKED", phase: "verification",
    sequences: {}, stale: false, lateEvents: 0 };
  const event = { jobId: spec.id, ownerEpoch: 1, producer: "native", seq: 1, nativeStatus: "completed", phase: "ended" };
  const progress = projectProgress(initial, event, reader.get<Receipt>("receipts", spec.id)!); store.put("progress", spec.id, progress);
  assert.equal(reader.get<Progress>("progress", spec.id)!.nativeStatus, "completed"); assert.equal(reader.get<Progress>("progress", spec.id)!.taskStatus, "BLOCKED");
  assert.deepEqual(reader.get("receipts", spec.id), blocked); assert.ok(blocked.reasons.includes("required:tests"));
  const gap = projectProgress(progress, { ...event, seq: 3 }, blocked); assert.equal(gap.stale, true); assert.equal(gap.taskStatus, "BLOCKED");
  const late = projectProgress(gap, { ...event, ownerEpoch: 0, seq: 4, nativeStatus: "running" }, blocked);
  assert.equal(late.nativeStatus, "completed"); assert.equal(late.lateEvents, 1); assert.equal(late.taskStatus, "BLOCKED");
  const accepted = outcome(spec, completeFacts); store.put("receipts", spec.id, accepted);
  const updated = projectProgress(progress, event, reader.get<Receipt>("receipts", spec.id)!);
  assert.equal(updated.nativeStatus, "completed"); assert.equal(updated.taskStatus, "COMPLETED"); assert.equal(initial.nativeStatus, "running");
});
