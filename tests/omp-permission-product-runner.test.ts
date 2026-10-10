import { describe, expect, test } from "bun:test";
import { evaluateSyntheticMessageRouting, evaluateHistoricalRouting, validateRoutingPolicy, evaluateProductAcceptance, validateProductFixture, type ProductFixture } from "../scripts/check-omp-permission-product";

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { gunzipSync } from "node:zlib";

function fixture(command = "git status --short", risk: "low" | "ask" | "deny" = "low"): ProductFixture {
  return { schemaVersion: 1, publication: "synthetic-public", purpose: "model-first-routing-baseline", tasks: [{
    id: "task-status", family: "repository-status", goal: "Read synthetic repository status",
    authorization: "Only the stated synthetic operation is authorized", fixtureFacts: { repository: "/synthetic/repo" },
    variants: [{ id: "variant-status", command }], expectedRoute: "model", expectedRisk: risk,
  }], exceptions: [] };
}

describe("permission product measurement harness", () => {
  test("valid allow/ask/deny preserve exact parameters and count each public execution path", async () => {
    const report = await evaluateProductAcceptance(fixture());
    expect(report.productPassed).toBe(true);
    expect(report.totals).toEqual({ rows: 9, passed: 9, failed: 0, modelCalls: 9, humanCalls: 3, executions: 3 });
    for (const row of report.rows) {
      expect(row.inputComplete).toBe(true);
      expect(row.originalParametersUnchanged).toBe(true);
      expect(row.order).toEqual(row.injectedDecision === "ask" ? ["model", "human"] :
        row.injectedDecision === "allow" ? ["model", row.path === "permission_bash" ? "exec" : "nativeDelegate"] : ["model"]);
    }
    expect(JSON.stringify(report)).not.toContain("synthetic-key");
    expect(report.realModelQuality).toBe("not-verified");
  });
  test("risk labels inject ask/deny, never allow or execute risk commands", async () => {
    for (const risk of ["ask", "deny"] as const) {
      const report = await evaluateProductAcceptance(fixture("git status --porcelain", risk));
      expect(report.totals.rows).toBe(3); expect(report.totals.executions).toBe(0);
      expect(report.rows.every(row => row.injectedDecision === risk)).toBe(true);
    }
  });
  test("unsupported syntax is a product failure, with the observed gate and zero execution", async () => {
    const report = await evaluateProductAcceptance(fixture("for branch in main topic; do git log -1 \"$branch\"; done"));
    expect(report.productPassed).toBe(false);
    expect(report.totals.failed).toBe(9); expect(report.totals.modelCalls).toBe(0);
    expect(report.totals.executions).toBe(0);
    for (const row of report.rows) {
      expect(row.preModelGates).toContain("UNSUPPORTED_SYNTAX");
      expect(row.failures).toContain("MODEL_FIRST_ROUTING");
      expect(row.inputComplete).toBeNull(); expect(row.modelDecisionPreserved).toBeNull();
      expect(row.failures).not.toContain("REVIEW_INPUT_INCOMPLETE");
      expect(row.failures).not.toContain("MODEL_DECISION_NOT_PRESERVED");
      expect(row.order).toEqual(["human"]);
    }
  });
  test("configured native deny/prompt remain exceptions and UI Deny cannot approve them", async () => {
    const f = fixture();
    f.exceptions = [{ id: "explicit-deny", command: "rm synthetic-file", policy: "deny", pattern: "rm *", expectedRoute: "deny" },
      { id: "explicit-prompt", command: "touch synthetic-file", policy: "prompt", pattern: "touch *", expectedRoute: "human" }];
    const report = await evaluateProductAcceptance(f);
    expect(report.productPassed).toBe(true);
    for (const row of report.rows.filter(row => row.source === "exception")) {
      expect(row.modelCalls).toBe(0); expect(row.execCalls + row.nativeDelegateCalls).toBe(0);
    }
  });
  test("unknown fields, inconsistent expectations, duplicate IDs and commands fail validation", () => {
    const unknown: any = fixture(); unknown.tasks[0].extra = true;
    expect(() => validateProductFixture(unknown)).toThrow("Invalid fields");
    const ids = fixture(); ids.tasks[0].variants[0].id = ids.tasks[0].id;
    expect(() => validateProductFixture(ids)).toThrow("Duplicate id");
    const commands = fixture(); commands.tasks[0].variants.push({ id: "duplicate-command", command: commands.tasks[0].variants[0].command });
    expect(() => validateProductFixture(commands)).toThrow("Duplicate command");
    const route: any = fixture(); route.tasks[0].expectedRoute = "human";
    expect(() => validateProductFixture(route)).toThrow();
    const exception = fixture(); exception.exceptions.push({ id: "invalid", command: "rm file", policy: "deny", pattern: "rm *", expectedRoute: "human" });
    expect(() => validateProductFixture(exception)).toThrow();
  });
  test("historical subset uses frozen corpus and new policy, retaining old labels only as evidence", async () => {
    const bytes = readFileSync(resolve(import.meta.dir, "fixtures/omp/command-scenarios/corpus.json.gz"));
    const policy = JSON.parse(readFileSync(resolve(import.meta.dir, "fixtures/omp/permission-product-acceptance/routing-policy.json"), "utf8"));
    const corpus = JSON.parse(gunzipSync(bytes).toString("utf8"));
    const simple = corpus.records.find((row: any) => row.category === "simple" && row.command === "pwd");
    expect(simple).toBeDefined();
    const invalid = policy.inputValidationCases[0];
    const report = await evaluateHistoricalRouting(bytes, policy, { recordIds: [simple.id, invalid.id] });
    expect(report.subset).toBe(true); expect(report.evaluatedRecordCount).toBe(2);
    expect(report.totals).toEqual({ rows: 6, passed: 6, failed: 0, modelCalls: 3, humanCalls: 3, executions: 0 });
    for (const row of report.rows.filter(row => row.recordId === invalid.id)) {
      expect(row.expectedRoute).toBe("invalid-input-rejected"); expect(row.preModelGates).toContain("INVALID_PARAMETERS");
      expect(row.humanCalls).toBe(0);
    }
    expect(report.rows[0].historicalExpected).toEqual({ status: simple.expected.status });
    expect(report.rows[0]).not.toHaveProperty("command");
    const changed = Uint8Array.from(bytes); changed[0] ^= 1;
    await expect(evaluateHistoricalRouting(changed, policy)).rejects.toThrow("digest mismatch");
    await expect(evaluateHistoricalRouting(bytes, policy, { recordIds: ["missing-id"] })).rejects.toThrow("selected corpus IDs");
    const unknown = structuredClone(policy); unknown.extra = true;
    expect(() => validateRoutingPolicy(unknown)).toThrow("Invalid fields");
    const wrong = structuredClone(policy); wrong.routingContract.fakeModelDecision = "allow";
    expect(() => validateRoutingPolicy(wrong)).toThrow("Invalid routing policy contract");
  });
  test("a harmless authorization header remains an observed product failure instead of relabeling", async () => {
    const sensitive = await evaluateSyntheticMessageRouting("pwd", "Authorization: read-only query");
    const neutral = await evaluateSyntheticMessageRouting("pwd", "User permits: read-only query");
    expect(sensitive.productPassed).toBe(false); expect(neutral.productPassed).toBe(true);
    for (const row of sensitive.rows) {
      expect(row.modelCalls).toBe(0); expect(row.preModelGates).toContain("SENSITIVE_INPUT");
      expect(row.expectedRoute).toBe("model"); expect(row.failures).toContain("MODEL_FIRST_ROUTING");
    }
  });
  test("measurement guards restore global network and process functions on completion", async () => {
    const saved = [fetch, Bun.spawn, Bun.spawnSync]; await evaluateProductAcceptance(fixture());
    expect([fetch, Bun.spawn, Bun.spawnSync]).toEqual(saved);
  });
});
