import { test } from "node:test";
import assert from "node:assert/strict";
import { createEvidenceRecord, reduceEvidence, summarizeEvidence, type EvidenceRecord,
  type CurrentEvidenceContext, type VerifiedArtifactFact } from "../src/evidence/records.ts";

const sha = "a".repeat(64), changed = "b".repeat(64);
function fixture(): { record: EvidenceRecord; current: CurrentEvidenceContext; artifact: VerifiedArtifactFact } {
  const record: EvidenceRecord = {
    schemaVersion: 1, jobId: "job-1", attemptId: "attempt-1", checkId: "check-1", layer: "checker",
    origin: { profileId: "pi-full", runtimeIdentity: sha, configDigest: sha, platform: "linux", architecture: "x64",
      snapshot: "snapshot-1", inputSnapshotDigest: sha, specVersion: 1, policyDigest: sha, bindingDigest: sha,
      environmentDigest: sha, contractDigest: sha, cwdIdentity: sha, entryIdentity: sha, argvDigest: sha },
    execution: { startedAt: 100, endedAt: 200, protocolStatus: "completed", exitCode: 0,
      counts: { tests: 1, passed: 1, failed: 0, skipped: 0 }, terminalObserved: true, termination: "confirmed",
      processIdentity: sha, notSent: false, unknowns: [] },
    result: { status: "passed", reason: "verified" },
    artifact: { id: "artifact-1", source: "verifier", digest: sha, bytes: 100 },
  };
  return { record, current: { jobId: record.jobId, attemptId: record.attemptId, checkId: record.checkId,
    origin: structuredClone(record.origin), requiredLayer: "checker", oraclePassed: true },
    artifact: { ...record.artifact!, jobId: record.jobId, snapshot: record.origin.snapshot, readable: true } };
}
const reduced = (record: unknown) => { const { current, artifact } = fixture(); return reduceEvidence(record, current, artifact); };

test("complete nonzero, zero, skipped, assertion and required-ID failures remain current and in denominator", () => {
  const { record } = fixture();
  const variants: EvidenceRecord[] = [
    { ...record, execution: { ...record.execution, exitCode: 2 }, result: { status: "failed", reason: "nonzero_exit" } },
    ...[{ tests: 0, passed: 0, failed: 0, skipped: 0 }, { tests: 2, passed: 0, failed: 0, skipped: 2 },
      { tests: 2, passed: 1, failed: 1, skipped: 0 }].map(counts => ({ ...record,
      execution: { ...record.execution, counts }, result: { status: "failed", reason: "required_tests_not_passed" } } as EvidenceRecord)),
    { ...record, result: { status: "failed", reason: "semantic_assertion_failed" } },
    { ...record, result: { status: "failed", reason: "required_test_ids_not_passed" } },
  ];
  const views = variants.map(reduced);
  for (const item of views) {
    assert.equal(item.validity, "current"); assert.equal(item.result, "failed"); assert.equal(item.supportsPassed, false);
  }
  const summary = summarizeEvidence(views);
  assert.equal(summary.total, 6); assert.equal(summary.current, 6); assert.equal(summary.failed, 6);
  assert.deepEqual(summary.rows.map(row => row.counts), variants.map(item => item.execution.counts));
  // 非零程序事实不可因生产者误报 passed 而支持成功。
  assert.equal(reduced({ ...record, execution: { ...record.execution, exitCode: 1 } }).result, "failed");
});

test("explicit unknown terminal/process observations stay current unknown; omitted facts are invalid", () => {
  const { record } = fixture();
  for (const patch of [{ termination: "unknown" }, { terminalObserved: false }, { terminalObserved: null }]) {
    const item = reduced({ ...record, execution: { ...record.execution, ...patch }, result: { status: "unknown", reason: "execution_unknown" } });
    assert.equal(item.validity, "current"); assert.equal(item.result, "unknown"); assert.equal(item.supportsPassed, false);
    assert.equal(reduced({ ...record, execution: { ...record.execution, ...patch } }).result, "unknown");
  }
  const startup = { ...record, execution: { ...record.execution, startedAt: null, endedAt: null, exitCode: null,
    terminalObserved: null, termination: "unknown", processIdentity: null, protocolStatus: "unknown",
    unknowns: ["PROCESS_IDENTITY_UNOBSERVED"] }, result: { status: "unknown", reason: "execution_unknown" } };
  assert.equal(reduced(startup).validity, "current"); assert.equal(reduced(startup).result, "unknown");
  for (const field of ["terminalObserved", "termination", "processIdentity", "startedAt", "endedAt"]) {
    const input: any = structuredClone(record); delete input.execution[field];
    assert.equal(reduced(input).validity, "invalid");
  }
  assert.equal(reduced({ ...record, execution: { ...record.execution, processIdentity: null } }).validity, "invalid");
  // 可核验失败不能因明确未知终止被隐藏成 invalid。
  const failure = reduced({ ...record, result: { status: "failed", reason: "nonzero_exit" },
    execution: { ...record.execution, exitCode: 3, termination: "unknown" } });
  assert.equal(failure.validity, "current"); assert.equal(failure.result, "failed");
});

test("same snapshot with changed version, inputs, runtime, config, policy, checker or entry is stale", () => {
  const { record, current, artifact } = fixture();
  for (const [key, value] of Object.entries({ specVersion: 2, inputSnapshotDigest: changed, runtimeIdentity: changed,
    configDigest: changed, policyDigest: changed, bindingDigest: changed, contractDigest: changed,
    environmentDigest: changed, cwdIdentity: changed, entryIdentity: changed, argvDigest: changed,
    profileId: "pi-base", platform: "darwin", architecture: "arm64", snapshot: "snapshot-2" })) {
    const before = structuredClone(record);
    const item = reduceEvidence(record, { ...current, origin: { ...current.origin, [key]: value } }, artifact);
    assert.equal(item.validity, "stale", key); assert.equal(item.result, "passed"); assert.equal(item.supportsPassed, false);
    assert.deepEqual(item.counts, record.execution.counts); assert.deepEqual(record, before);
  }
  for (const field of ["jobId", "attemptId", "checkId"]) {
    assert.equal(reduceEvidence(record, { ...current, [field]: "changed-id" }, artifact).validity, "invalid");
  }
  const failed = { ...record, result: { status: "failed", reason: "semantic_assertion_failed" } } as EvidenceRecord;
  const historical = reduceEvidence(failed, { ...current, origin: { ...current.origin, specVersion: 2 } }, artifact);
  assert.equal(historical.validity, "stale"); assert.equal(historical.result, "failed");
});

test("historical nonzero and empty test facts stay failed even when the producer claimed pass", () => {
  const { record, current, artifact } = fixture();
  for (const execution of [{ ...record.execution, exitCode: 1 },
    { ...record.execution, counts: { tests: 0, passed: 0, failed: 0, skipped: 0 } },
    { ...record.execution, counts: { tests: 2, passed: 0, failed: 0, skipped: 2 } }]) {
    const input = { ...record, execution };
    const original = reduceEvidence(input, current, artifact);
    const historical = reduceEvidence(input, { ...current, origin: { ...current.origin, specVersion: 2 } }, artifact);
    assert.equal(original.result, "failed");
    assert.equal(historical.validity, "stale"); assert.equal(historical.result, "failed");
    assert.equal(historical.supportsPassed, false);
    assert.equal(summarizeEvidence([historical]).failed, 1);
    assert.deepEqual(historical.counts, execution.counts);
  }
});

test("missing, unreadable, wrong-scope or changed artifact is invalid, preserving observable failure", () => {
  const { record, current, artifact } = fixture();
  for (const fact of [null, { ...artifact, readable: false }, { ...artifact, jobId: "other-job" },
    { ...artifact, snapshot: "other-snapshot" }, { ...artifact, id: "other-artifact" },
    { ...artifact, source: "runtime" as const }, { ...artifact, digest: changed }, { ...artifact, bytes: 101 }]) {
    const item = reduceEvidence(record, current, fact);
    assert.equal(item.validity, "invalid"); assert.equal(item.supportsPassed, false);
  }
  assert.equal(reduced({ ...record, artifact: null }).validity, "invalid");
  const failure = reduceEvidence({ ...record, result: { status: "failed", reason: "semantic_assertion_failed" } }, current, null);
  assert.equal(failure.result, "failed"); assert.deepEqual(failure.counts, record.execution.counts);
});

test("only independently required current oracle pass supports passed; reviewer cannot hide checker failure", () => {
  const { record, current, artifact } = fixture();
  assert.equal(reduceEvidence(record, current, artifact).supportsPassed, true);
  assert.equal(reduceEvidence(record, { ...current, oraclePassed: false }, artifact).supportsPassed, false);
  for (const layer of ["reviewer", "worker", "terminal"] as const) {
    const source = layer === "reviewer" ? "reviewer" : "runtime";
    const item = reduceEvidence({ ...record, layer, artifact: { ...record.artifact, source } }, current, { ...artifact, source });
    assert.equal(item.validity, "current"); assert.equal(item.supportsPassed, false);
  }
  assert.equal(reduced({ ...record, layer: "claim" }).validity, "invalid");
  assert.equal(reduced({ ...record, artifact: { ...record.artifact, source: "claim" } }).validity, "invalid");
  const reviewer = reduceEvidence({ ...record, layer: "reviewer", artifact: { ...record.artifact, source: "reviewer" } },
    { ...current, requiredLayer: "reviewer" }, { ...artifact, source: "reviewer" });
  assert.equal(reviewer.supportsPassed, true);
  const failed = reduced({ ...record, result: { status: "failed", reason: "semantic_assertion_failed" } });
  const summary = summarizeEvidence([reviewer, failed]);
  assert.equal(summary.total, 2); assert.equal(summary.failed, 1); assert.equal(summary.supportsPassed, false);
  assert.equal(summarizeEvidence([]).supportsPassed, false);
  const stale = reduceEvidence(record, { ...current, origin: { ...current.origin, specVersion: 2 } }, artifact);
  assert.equal(summarizeEvidence([reviewer, stale]).supportsPassed, false);
  assert.deepEqual(summary.rows.map(row => row.result), ["passed", "failed"]);
});

test("not-sent is representable but cannot pass; closed schema rejects malformed input without getter evaluation", () => {
  const { record, current } = fixture();
  const notSent = { ...record, execution: { ...record.execution, startedAt: null, endedAt: null, protocolStatus: "not_sent",
    exitCode: null, counts: null, terminalObserved: false, termination: "confirmed", processIdentity: null, notSent: true },
    result: { status: "not_run", reason: "not_sent" }, artifact: null };
  for (const status of ["not_run", "unknown"]) {
    const item = reduceEvidence({ ...notSent, result: { status, reason: "not_sent" } }, current, null);
    assert.equal(item.validity, "current"); assert.equal(item.result, status); assert.equal(item.supportsPassed, false);
  }
  assert.equal(reduced({ ...notSent, result: { status: "passed", reason: "verified" } }).validity, "invalid");
  let getterCalls = 0;
  const malicious = structuredClone(record);
  Object.defineProperty(malicious.execution, "terminalObserved", { enumerable: true, get() { getterCalls++; return true; } });
  assert.equal(reduced(malicious).validity, "invalid"); assert.equal(getterCalls, 0);
  const unknownGetter: any = structuredClone(record);
  Object.defineProperty(unknownGetter, "secret", { enumerable: true, get() { getterCalls++; return "secret"; } });
  assert.equal(reduced(unknownGetter).validity, "invalid"); assert.equal(getterCalls, 0);
  const old: any = structuredClone(record); delete old.origin.inputSnapshotDigest;
  const symbol: any = structuredClone(record); symbol[Symbol("hidden")] = true;
  for (const input of [old, symbol, { ...record, schemaVersion: 2 }, { ...record, unexpected: true },
    { ...record, origin: { ...record.origin, configDigest: "bad-hash" } }, { ...record, jobId: "../secret" }, { ...record, jobId: ".." },
    { ...record, result: { status: "passed", reason: "arbitrary raw body" } },
    { ...record, result: { status: "passed", reason: "semantic_assertion_failed" } },
    { ...record, execution: { ...record.execution, endedAt: 99 } },
    { ...record, execution: { ...record.execution, unknowns: ["TERMINATION_UNKNOWN", "TERMINATION_UNKNOWN"] } },
    { ...record, origin: Object.assign(Object.create({ inherited: true }), record.origin) },
    ...[Infinity, NaN, 1.5, Number.MAX_SAFE_INTEGER + 1].map(tests => ({ ...record,
      execution: { ...record.execution, counts: { ...record.execution.counts, tests } } }))]) {
    assert.equal(reduced(input).validity, "invalid");
  }
  const before = structuredClone(record), frozen = createEvidenceRecord(record), item = reduced(record);
  assert.deepEqual(record, before); assert.notEqual(frozen, record); assert.notEqual(frozen.origin, record.origin);
  assert.equal(Object.isFrozen(frozen), true); assert.equal(Object.isFrozen(frozen.execution.unknowns), true);
  assert.throws(() => (frozen.origin as any).specVersion = 999, TypeError);
  assert.equal(item.record?.origin.specVersion, 1);
});
