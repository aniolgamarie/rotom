import { expect, test } from "bun:test";
import { createAuditRecord, appendAudit, type AuditInput } from "../audit";
import { redactReviewText, buildReviewRequest } from "../reviewer";
import { input as reviewInput } from "./review-fixture";

test("review redaction removes known raw and encoded secrets before any envelope", () => {
  const secret = "SECRET_SENTINEL_$abc/123";
  const sources = [secret, encodeURIComponent(secret), Buffer.from(secret).toString("base64"),
    "Authorization: Bearer unknown-token-value", 'api_key="unknown-private-value"', '{"api_key":"unknown-private-value"}',
    "-----BEGIN PRIVATE KEY-----\nprivate-value",
    "https://name:password@example.invalid/", "-----BEGIN PRIVATE KEY-----\nprivate-value\n-----END PRIVATE KEY-----"];
  for (const source of sources) {
    const view = redactReviewText(source, [secret]);
    expect(view.changed).toBe(true);
    expect(view.text).not.toContain(secret);
    expect(view.text).not.toContain("unknown-private-value");
    expect(view.text).not.toContain("unknown-token-value");
    expect(view.text).not.toContain("private-value");
    expect(() => buildReviewRequest(reviewInput({ operation: view.text, redaction_complete: !view.changed })))
      .toThrow("REVIEW_CONTEXT_INVALID");
  }
});
test("review redaction is bounded and never claims arbitrary semantic completeness", () => {
  expect(redactReviewText("pwd && ls .", [])).toEqual({ text: "pwd && ls .", changed: false, bounded: true });
  const overflow = redactReviewText("x".repeat(25 * 1024), []);
  expect(overflow.changed).toBe(true); expect(overflow.bounded).toBe(false);
  expect(overflow.text).toBe("[REVIEW_CONTEXT_UNAVAILABLE]");
  expect(redactReviewText("safe", Array(257).fill("private"))).toEqual(overflow);
});

function input(): AuditInput {
  return { request_id: crypto.randomUUID(), decision_id: crypto.randomUUID(), operation_digest: "a".repeat(64),
    outcome: "ask", source: "reviewer", reason_code: "USER_CONFIRMATION_REQUIRED", active_mode: "smart",
    policy_version: "b".repeat(64), actual_reviewer: "fixture/cheap", reviewer_source: "explicit-profile",
    fallback_configured: true, fallback_called: false, coverage: "eligible", coverage_reasons: [],
    health: { bridge: "healthy", model: "healthy", tiny: "unavailable" }, primary_calls: 1,
    primary_model: "fixture/cheap", tiny_calls: 0,
    elapsed_ms: 250, permit: "none" };
}
test("audit is a frozen closed record with buckets and no raw operation", () => {
  const record = createAuditRecord(input());
  expect(record.schema_version).toBe(1);
  expect(record.elapsed_bucket).toBe("under-1s");
  expect(record).not.toHaveProperty("elapsed_ms");
  expect(record).not.toHaveProperty("command");
  expect(Object.isFrozen(record)).toBe(true);
});
test.each(["args", "env", "authorization", "provider_error", "model_output", "cwd", "command"])(
  "unknown %s body is rejected without exposing its secret", (field) => {
    try { createAuditRecord({ ...input(), [field]: "SECRET_SENTINEL" } as AuditInput); throw Error("expected failure"); }
    catch (error) { expect(String(error)).toBe("Error: PERMISSION_AUDIT_INVALID"); }
  },
);
test("human attribution preserves original ask chain and decision", () => {
  const value = input();
  value.human = { human_decision_id: crypto.randomUUID(), ask_decision_id: value.decision_id,
    source: "human", outcome: "allow" };
  value.permit = "consumed";
  const record = createAuditRecord(value);
  expect(record.outcome).toBe("ask"); expect(record.human?.source).toBe("human");
  expect(record.human?.outcome).toBe("allow");
  expect(() => createAuditRecord({ ...value, human: { ...value.human!, ask_decision_id: crypto.randomUUID() } })).toThrow();
});
test("model calls and actual identity cannot disagree", () => {
  const value = input();
  expect(() => createAuditRecord({ ...value, primary_calls: 0 })).toThrow();
  expect(() => createAuditRecord({ ...value, primary_calls: 2 })).toThrow();
  expect(() => createAuditRecord({ ...value, tiny_calls: 1 })).toThrow();
  expect(() => createAuditRecord({ ...value, reason_code: "SECRET_SENTINEL" } as unknown as AuditInput)).toThrow();
  expect(createAuditRecord({ ...value, primary_calls: 0, primary_model: undefined,
    actual_reviewer: "not-called", reviewer_source: "not-called" }).primary_calls).toBe(0);
  const fallback = createAuditRecord({ ...value, source: "fallback", fallback_called: true, tiny_calls: 1,
    primary_calls: 0, primary_model: undefined, fallback_model: "local/lfm2.5-230m",
    actual_reviewer: "local/lfm2.5-230m", reviewer_source: "fallback", health: {
      bridge: "healthy", model: "degraded", tiny: "healthy" } });
  expect(fallback.primary_calls).toBe(0);
  expect(fallback.tiny_calls).toBe(1);
  const remote = createAuditRecord({ ...value, source: "remote-fallback", primary_calls: 1, remote_configured: true,
    remote_called: true, remote_calls: 1, remote_model: "remote/reviewer",
    actual_reviewer: "remote/reviewer", reviewer_source: "remote-fallback",
    health: { ...value.health, remote: "healthy" } });
  expect(remote.remote_calls).toBe(1);
  expect(remote.source).toBe("remote-fallback");
  expect(() => createAuditRecord({ ...value, remote_configured: "yes" as unknown as boolean })).toThrow();
});
test("audit write failure only degrades health; provider exception stays private", async () => {
  let degraded = 0;
  const result = await appendAudit(createAuditRecord(input()), async () => { throw Error("SECRET_SENTINEL"); }, () => { degraded++; });
  expect(result).toEqual({ stored: false, health: "degraded" }); expect(degraded).toBe(1);
});
