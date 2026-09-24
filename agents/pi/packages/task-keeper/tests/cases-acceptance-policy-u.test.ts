import { test, assert, evidence } from "./recorded-test.ts";
import { evaluateVerification, type VerificationFacts } from "../src/verification/runner.ts";
import { dependenciesSatisfied, type QueuedStep } from "../src/orchestration/scheduler.ts";
import { capabilityStatus, executionRequirements, type AdapterIdentity, type Certification } from "../src/adapters/capabilities.ts";
import { digest } from "../src/contracts/primitives.ts";

const facts: VerificationFacts = { stdout: '{"tests":2,"passed":2,"failed":0,"skipped":0}', truncated: false, timedOut: false,
  cancelled: false, spawnFailed: false, exitCode: 0, terminationConfirmed: true, admissionError: null, lingering: 0,
  launcherExitCode: 0, started: true, terminalObserved: true };
const tests = { kind: "tests" as const, parser: "json" as const, minimumTests: 2 };

test("[U WFL-004 T44] exit zero requires enough actually passed tests and unambiguous counts", () => {
  for (const [stdout, status, reason] of [
    [facts.stdout, "passed", "verified"],
    ['{"tests":0,"passed":0,"failed":0,"skipped":0}', "failed", "required_tests_not_passed"],
    ['{"tests":2,"passed":0,"failed":0,"skipped":2}', "failed", "required_tests_not_passed"],
    ['{"tests":1,"passed":1,"failed":0,"skipped":0}', "failed", "required_tests_not_passed"],
    ['{"tests":2,"passed":1,"failed":1,"skipped":0}', "failed", "required_tests_not_passed"],
    ['{"tests":2,"passed":1,"failed":0,"skipped":0}', "unknown", "test_count_unknown"],
    ['{"tests":2,"passed":2,"failed":0}', "unknown", "test_count_unknown"],
    ["Done", "unknown", "test_count_unknown"],
  ]) for (const id of ["WFL-004", "T44"]) evidence(id, () => {
    const result = evaluateVerification(tests, { ...facts, stdout }); assert.equal(result.status, status); assert.equal(result.reason, reason);
  });
});

test("[U T51] timeout and incomplete termination outrank passing output and zero exit", () => {
  for (const id of ["T51"]) evidence(id, () => {
    assert.equal(evaluateVerification(tests, facts).status, "passed");
    const unknown = evaluateVerification(tests, { ...facts, timedOut: true, terminationConfirmed: false });
    assert.equal(unknown.status, "unknown"); assert.equal(unknown.reason, "external_processes_not_confirmed_stopped");
    const terminated = evaluateVerification(tests, { ...facts, timedOut: true });
    assert.equal(terminated.status, "failed"); assert.equal(terminated.reason, "timeout"); assert.equal(terminated.failureCategory, "unknown");
  });
});

test("[U WFL-006] independent process defects never turn into quality failures eligible for model upgrade", () => {
  for (const id of ["WFL-006"]) evidence(id, () => {
    const quality = { ...facts, stdout: '{"tests":2,"passed":1,"failed":1,"skipped":0,"failureCategory":"implementation"}' };
    assert.equal(evaluateVerification(tests, quality).failureCategory, "implementation");
    for (const [change, status, reason] of [
      [{ spawnFailed: true, exitCode: null }, "failed", "spawn_failed"],
      [{ cancelled: true }, "failed", "cancelled"],
      [{ timedOut: true }, "failed", "timeout"],
      [{ terminationConfirmed: false }, "unknown", "external_processes_not_confirmed_stopped"],
      [{ admissionError: "owner_changed" }, "failed", "owner_changed"],
      [{ lingering: 1 }, "failed", "unfinished_descendants_terminated"],
      [{ launcherExitCode: 1 }, "failed", "supervisor_failed"],
      [{ started: false }, "unknown", "command_terminal_not_observed"],
      [{ terminalObserved: false }, "unknown", "command_terminal_not_observed"],
      [{ truncated: true }, "unknown", "output_truncated"],
    ] as Array<[Partial<VerificationFacts>, string, string]>) {
      const result = evaluateVerification(tests, { ...quality, ...change });
      assert.equal(result.status, status); assert.equal(result.reason, reason); assert.notEqual(result.failureCategory, "implementation");
    }
    const environment = evaluateVerification(tests, { ...quality, stdout: quality.stdout.replace("implementation", "environment") });
    assert.equal(environment.failureCategory, "environment");
  });
});

test("[U SCH-003 SCH-005 TK01] only passed evidence or explicitly skippable optional evidence satisfies dependencies", () => {
  const dependent = { dependencies: ["upstream"], allowedSkippedDependencies: [] as string[] };
  for (const status of ["pending", "running", "failed", "unknown"] as QueuedStep["status"][]) {
    for (const id of ["SCH-003", "TK01"]) evidence(id, () => {
      assert.equal(dependenciesSatisfied([{ id: "upstream", status, optional: false }], dependent), false);
      assert.equal(dependenciesSatisfied([{ id: "upstream", status, optional: false }], { dependencies: [], allowedSkippedDependencies: [] }), true);
    });
  }
  evidence("SCH-005", () => {
    assert.equal(dependenciesSatisfied([{ id: "upstream", status: "passed", optional: false }], dependent), true);
    for (const optional of [false, true]) for (const allowed of [false, true]) {
      assert.equal(dependenciesSatisfied([{ id: "upstream", status: "skipped", optional }], { ...dependent, allowedSkippedDependencies: allowed ? ["upstream"] : [] }), optional && allowed);
    }
    assert.equal(dependenciesSatisfied([], dependent), false);
  });
});

test("[U EXE-012 T52 VAL-008] missing critical evidence disables that capability without disabling a separately certified P1", () => {
  const identity: AdapterIdentity = { adapter: "fixture", version: "1", runtime: "1", profileDigest: "profile", transportDigest: "transport", mode: "foreground" };
  const required = executionRequirements("interactive", false);
  const certification: Certification = { identityDigest: digest(identity), capabilities: Object.fromEntries(required.map(cap => [cap, { supported: true, testEvidence: [`independent-${cap}`], level: "A" as const }])) };
  for (const id of ["EXE-012", "T52"]) evidence(id, () => {
    assert.equal(capabilityStatus(identity, certification, required).eligible, true);
    for (const unavailable of [{ supported: false, testEvidence: ["old"], level: "A" as const },
      { supported: true, testEvidence: [], level: "A" as const }, { supported: true, testEvidence: ["model says Done"], level: "U" as const }]) {
      const result = capabilityStatus(identity, { ...certification, capabilities: { ...certification.capabilities, events: unavailable } }, required);
      assert.equal(result.eligible, false); assert.deepEqual(result.missing, ["events"]);
    }
  });
  evidence("VAL-008", () => {
    assert.equal(capabilityStatus(identity, certification, required).eligible, true);
    assert.deepEqual(capabilityStatus(identity, certification, executionRequirements("interactive", true)), { eligible: false, missing: ["requestGate"] });
    const strict: Certification = { ...certification, capabilities: { ...certification.capabilities, requestGate: { supported: true, testEvidence: ["receiver-and-ledger"], level: "P" } } };
    assert.equal(capabilityStatus(identity, strict, executionRequirements("interactive", true)).eligible, true);
    assert.equal(capabilityStatus({ ...identity, transportDigest: "changed" }, strict, required).eligible, false);
  });
});
