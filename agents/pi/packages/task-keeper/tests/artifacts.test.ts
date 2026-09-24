import { test, assert } from "./recorded-test.ts";
import { writeFileSync, unlinkSync } from "node:fs";
import { join } from "node:path";
import { Store } from "../src/store/database.ts";
import { Artifacts } from "../src/store/artifacts.ts";
import { projectProgress, type Progress } from "../src/evidence/progress.ts";
import { isolatedDirectory } from "./helpers.ts";

test("[T47 T54 T55] pinned artifacts retain scope/source and detect missing or modified evidence", (t) => {
  const store = new Store(isolatedDirectory(t)); t.after(() => store.close());
  const artifacts = new Artifacts(store);
  const ref = artifacts.pin("job-1", "tree-1", "claim is not verification", "claim");
  assert.equal(artifacts.read(ref.id, "job-1", "tree-1").artifact.source, "claim");
  assert.throws(() => artifacts.read(ref.id, "job-2", "tree-1"));
  assert.throws(() => artifacts.read(ref.id, "job-1", "tree-2"));
  assert.deepEqual(artifacts.pin("job-1", "tree-1", "claim is not verification", "claim"), ref);
  writeFileSync(join(store.root, "artifacts", ref.id), "tampered");
  assert.throws(() => artifacts.read(ref.id, "job-1", "tree-1"));
  assert.throws(() => artifacts.pin("job-1", "tree-1", "claim is not verification", "claim"));
  unlinkSync(join(store.root, "artifacts", ref.id));
  assert.throws(() => artifacts.read(ref.id, "job-1", "tree-1"));
});

test("[T15 T38 T83] progress cannot turn native completion into accepted outcome", () => {
  const initial: Progress = { jobId: "job-1", ownerEpoch: 2, nativeStatus: "running", taskStatus: "BLOCKED", phase: "verify", sequences: {}, stale: false, lateEvents: 0 };
  const receipt = { jobId: "job-1", specVersion: 1, snapshot: "tree", status: "BLOCKED" as const, nativeStatus: "completed", reasons: ["required:tests"], optionalGaps: [], failureHistory: [] };
  const event = { jobId: "job-1", ownerEpoch: 2, producer: "p", seq: 1, nativeStatus: "completed", phase: "end" };
  const result = projectProgress(initial, event, receipt);
  assert.equal(result.nativeStatus, "completed"); assert.equal(result.taskStatus, "BLOCKED");
  assert.deepEqual(projectProgress(result, event, receipt), result);
  const late = projectProgress(result, { ...event, ownerEpoch: 1, nativeStatus: "running" }, receipt);
  assert.equal(late.lateEvents, 1); assert.equal(late.nativeStatus, "completed");
  assert.equal(projectProgress(result, { ...event, seq: 3 }, receipt).stale, true);
});
