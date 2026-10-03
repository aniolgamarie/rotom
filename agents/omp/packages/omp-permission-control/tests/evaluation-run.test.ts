import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { createEvaluationReviewBoundary, runEvaluation, runEvaluationCli } from "../evaluation/run";

const repositoryRoot = resolve(import.meta.dir, "../../../../..");
const fixtureDirectory = resolve(repositoryRoot, "tests/fixtures/omp/permission-control");

test("default fake evaluation consumes all frozen cases without executing commands", async () => {
  const report = await runEvaluation({
    mode: "fake",
    repositoryRoot,
    fixtureDirectory,
    platform: "linux-glibc-x64",
  });

  expect(report.identity.mode).toBe("fake");
  expect(report.identity.transport).toBe("fake");
  for (const key of ["sourceDigest", "policyDigest", "fixtureDigest", "pluginDigest", "hostDigest"] as const)
    expect(report.identity[key]).toMatch(/^[a-f0-9]{64}$/);
  expect(report.contextEvidence).toEqual({
    environment: "frozen-simulated",
    effects: "frozen-simulated",
    messages: "frozen-simulated",
    hostProof: false,
    transportCounting: "review-services-boundary-only",
    adapterInternalRetriesVerified: false,
  });
  expect(report.results).toHaveLength(240);
  expect(report.metrics.primaryCalls).toBe(78);
  expect(report.metrics.commandExecutions).toBe(0);
  expect(report.successCriteria.sc001).toBeNull();
  expect(report.unverified).toContain("real-model-authorization-semantics");
  expect(report.unverified).toContain("real-host-execution");
  expect(report.results.every(row => row.commandExecutions === 0)).toBe(true);
  expect(report.mechanicalCases).toHaveLength(14);
  expect(new Set(report.mechanicalCases.map(item => item.fault))).toEqual(new Set([
    "missing-effect", "duplicate-binding", "unreferenced-message", "out-of-bounds",
    "non-utf8-boundary", "wrong-scope-digest", "old-generation",
  ]));
  expect(report.mechanicalCases.every(item => item.positiveControlAccepted &&
    item.faultRejected && item.modelCalls === 0)).toBe(true);
  expect(report.metricSemantics.compoundCompleteRate).toBe(
    "input-effect-inventory-only; not-model-response-effect-coverage");
});

test("mechanical evidence faults are rejected without calling review services", async () => {
  let calls = 0;
  const report = await runEvaluation({ mode: "real", repositoryRoot, fixtureDirectory,
    platform: "linux-glibc-x64", provider: "fictional", model: "small",
    transport: "openai-completions", services: {
      reviewOnce: async call => {
        calls++; call.onInferenceStarted();
        const envelope = JSON.parse(call.input) as { request: { effects: { effectId: string }[] } };
        return { status: "ok", text: JSON.stringify({ decision: "ask", risk: "unknown",
          authorization: "unknown", effects: envelope.request.effects.map(effect => effect.effectId),
          unknowns: ["ambiguous-authorization"], reasonCode: "USER_CONFIRMATION_REQUIRED",
          evidence: { userMessageIds: [], bindings: [] } }), outputTokens: 32, toolCalls: [] };
      },
      tinyInstalledOnly: async () => ({ status: "unavailable" }),
    } });
  expect(calls).toBe(78);
  for (const observation of report.mechanicalCases) {
    expect(observation.positiveControlAccepted).toBe(true);
    expect(observation.faultRejected).toBe(true);
    expect(observation.modelCalls).toBe(0);
    const row = report.results.find(item => item.id === observation.caseId)!;
    expect(row.outcome).toBe("ask");
    expect(row.primaryCalls).toBe(0);
  }
  for (const id of ["risk-088", "risk-098"])
    expect(report.results.find(item => item.id === id)!.primaryCalls).toBe(1);
});

test("fake reviewer is conservative and never copies the expected fixture decision", async () => {
  const report = await runEvaluation({ mode: "fake", repositoryRoot, fixtureDirectory,
    platform: "linux-glibc-x64" });
  const deterministic = report.results.find(row => row.id === "safe-001")!;
  const reviewed = report.results.find(row => row.id === "safe-021")!;
  expect(deterministic.outcome).toBe("allow");
  expect(deterministic.primaryCalls).toBe(0);
  expect(reviewed.outcome).toBe("ask");
  expect(reviewed.primaryCalls).toBe(1);
  expect(reviewed.unverifiedReasons).toContain("real-inference-not-run");
  const forged = report.results.find(row => row.id === "risk-084")!;
  expect(forged.outcome).toBe("ask");
  expect(forged.primaryCalls).toBe(0);
});

test("state sequences use core cancellation but leave unsupported observations unverified", async () => {
  const report = await runEvaluation({ mode: "fake", repositoryRoot, fixtureDirectory,
    platform: "linux-glibc-x64" });
  const cancelled = report.results.find(row => row.id === "fault-006")!;
  const timeout = report.results.find(row => row.id === "fault-001")!;
  expect(cancelled.outcome).toBe("cancelled");
  expect(cancelled.checks.cancelLatencyMs).toBe(0);
  expect(timeout.outcome).toBe("ask");
  expect(timeout.checks.automaticMs).toBeNull();
  expect(timeout.unverifiedReasons).toContain("event-observation-unavailable");
  expect(timeout.unverifiedReasons).toContain("automatic-deadline-not-observed");
  expect(timeout.checks.statusComplete).toBe(true);
  expect(timeout.unverifiedReasons).not.toContain("status-not-observed");
  expect(timeout.primaryCalls).toBe(0);
});

test("real review boundary leaves inference accounting to the selected adapter", async () => {
  let callbacks = 0; let delegated = 0;
  const boundary = createEvaluationReviewBoundary({ mode: "real", services: {
    reviewOnce: async request => {
      delegated++; request.onInferenceStarted();
      return { status: "unavailable" };
    },
    tinyInstalledOnly: async () => ({ status: "unavailable" }),
  } });
  const abort = new AbortController();
  const result = await boundary.reviewOnce({ requestId: "single", model: { provider: "p", model: "m" },
    input: "{}", maxOutputTokens: 1, maxOutputBytes: 2, deadline: performance.now() + 1_000,
    signal: abort.signal, onInferenceStarted: () => { callbacks++; } });
  expect(result.status).toBe("unavailable");
  expect(delegated).toBe(1);
  expect(callbacks).toBe(1);
});

test("incomplete real CLI selection fails before importing the explicit service module", async () => {
  let imports = 0;
  await expect(runEvaluationCli([
    "--mode", "real", "--service-module", "/explicit/reviewer.ts", "--provider", "provider",
    "--transport", "openai-completions", "--repository-root", repositoryRoot,
    "--fixtures", fixtureDirectory,
  ], { loadServiceModule: async () => { imports++; throw new Error("SHOULD_NOT_IMPORT"); } }))
    .rejects.toThrow("INVALID_EVALUATION_ARGUMENTS");
  expect(imports).toBe(0);
});

test("unknown CLI arguments fail before any service or output side effect", async () => {
  let imports = 0;
  await expect(runEvaluationCli(["--unknown"], {
    loadServiceModule: async () => { imports++; throw new Error("SHOULD_NOT_IMPORT"); },
  })).rejects.toThrow("INVALID_EVALUATION_ARGUMENTS");
  expect(imports).toBe(0);
});

test("unknown mode and invalid real preflight fail before adapter import", async () => {
  await expect(runEvaluation({ mode: "unknown", repositoryRoot, fixtureDirectory,
    platform: "linux-glibc-x64" } as never)).rejects.toThrow("INVALID_EVALUATION_ARGUMENTS");
  for (const args of [
    ["--platform", "bad platform", "--fixtures", fixtureDirectory, "--repository-root", repositoryRoot],
    ["--platform", "linux-glibc-x64", "--fixtures", fixtureDirectory, "--repository-root", tmpdir()],
  ]) {
    let imports = 0;
    await expect(runEvaluationCli(["--mode", "real", "--service-module", "/explicit/reviewer.ts",
      "--provider", "provider", "--model", "model", "--transport", "openai-completions", ...args], {
      loadServiceModule: async () => { imports++; throw new Error("SHOULD_NOT_IMPORT"); },
    })).rejects.toThrow();
    expect(imports).toBe(0);
  }
});

test("fake CLI writes only an explicit new report outside identity-covered inputs", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "omp-evaluation-output-"));
  const output = resolve(directory, "report.json");
  try {
    const report = await runEvaluationCli(["--mode", "fake", "--repository-root", repositoryRoot,
      "--fixtures", fixtureDirectory, "--platform", "linux-glibc-x64", "--output", output]);
    expect(JSON.parse(readFileSync(output, "utf8")).identity).toEqual(report.identity);
    await expect(runEvaluationCli(["--mode", "fake", "--repository-root", repositoryRoot,
      "--fixtures", fixtureDirectory, "--platform", "linux-glibc-x64", "--output", output]))
      .rejects.toThrow("EVALUATION_OUTPUT_FAILED");
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("CLI rejects output inside the frozen fixture or plugin tree", async () => {
  for (const output of [resolve(fixtureDirectory, "report.json"),
    resolve(repositoryRoot, "agents/omp/packages/omp-permission-control/report.json")]) {
    await expect(runEvaluationCli(["--mode", "fake", "--repository-root", repositoryRoot,
      "--fixtures", fixtureDirectory, "--output", output])).rejects.toThrow("INVALID_EVALUATION_ARGUMENTS");
  }
});

test("output boundary resolves a symlinked parent before identity checks", async () => {
  const directory = mkdtempSync(resolve(tmpdir(), "omp-evaluation-link-"));
  const link = resolve(directory, "covered");
  try {
    symlinkSync(resolve(repositoryRoot, "agents/omp/packages/omp-permission-control"), link, "dir");
    await expect(runEvaluationCli(["--mode", "fake", "--repository-root", repositoryRoot,
      "--fixtures", fixtureDirectory, "--output", resolve(link, "report.json")]))
      .rejects.toThrow("INVALID_EVALUATION_ARGUMENTS");
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
