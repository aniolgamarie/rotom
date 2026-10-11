import { expect, test } from "bun:test";
import { createApprovalAudit, safeAttempts, safeIdentity, toolCallIdDigest, sessionIdDigest } from "./approval-diagnostic";

test("audit is closed and removes every untrusted text field without hashes", () => {
  const canary = "SENSITIVE_CANARY_VALUE";
  const records: any[] = [];
  const audit = createApprovalAudit((type, data) => records.push({ type, data }));
  const call = audit.begin(canary, canary, canary, 1);
  call.context({ shellFamily: canary, executionRoute: canary, contextReason: canary,
    command: canary, cwd: canary, worktreePlan: { rawCommand: canary }, secret: canary });
  call.approval({ source: canary, reasonCode: canary, chain: [canary] });
  call.gates(canary, "MANUAL_MODE");
  call.review({ status: "failure", primary: { status: "failure", called: true, health: "transport",
    failureCode: canary, transportCode: canary, httpStatus: canary,
    model: { provider: canary, id: canary, api: canary, baseUrl: canary, requestModelId: canary } },
    command: canary, response: canary, headers: { authorization: canary } } as any);
  call.data.command = canary; call.data.prompt = canary; call.data.args = [canary];
  audit.finish(call, canary, canary, canary);
  expect(records).toHaveLength(1);
  expect(JSON.stringify(records)).not.toContain(canary);
  expect(records[0].data.toolCallId).toBeNull();
  expect(Object.keys(records[0].data).sort()).toEqual(["version", "sequence", "toolCallId", "toolCallIdDigest", "sessionIdDigest", "entrypoint", "mode",
    "generation", "source", "nativeContext", "stage", "outcome", "reasonCode", "chain", "preModelGates", "attempts"].sort());
  expect(audit.state.accepted).toBe(1); expect(audit.state.durability).toBe("not-attested");
});
test("safe identity refuses URLs, key-like strings and raw hashes", () => {
  for (const value of ["https://host.example/model", "sk-" + "x".repeat(24), "ghp_" + "x".repeat(24), "a".repeat(64), "KEY_CANARY"])
    expect(safeIdentity(value)).toBeUndefined();
  expect(safeIdentity("zhipu_tf/glm-5.3-flash")).toBe("zhipu_tf/glm-5.3-flash");
});
test("only whitelisted status/code values persist, duplicate finish is suppressed", () => {
  const attempts = safeAttempts({ status: "failure", primary: { status: "failure", called: true, health: "transport",
    failureCode: "HTTP_NON_OK", httpStatus: 429, transportCode: "ECONNRESET" },
    remote: { status: "failure", called: false, health: "timeout", failureCode: "TIMEOUT", httpStatus: 999 } });
  expect(attempts[0]).toMatchObject({ httpStatus: 429, transportCode: "ECONNRESET" });
  expect(attempts[1]).not.toHaveProperty("httpStatus");
  const audit = createApprovalAudit(() => { throw new Error("SECRET_CANARY_DISK"); });
  const call = audit.begin("call_ok", "bash", "smart", 1);
  audit.finish(call, "hook", "blocked", "NATIVE_DENY"); audit.finish(call, "execute", "executed");
  expect(audit.state.failed).toBe(1); expect(audit.state.health).toBe("failed");
  expect(JSON.stringify(audit.state)).not.toContain("SECRET_CANARY_DISK");
});

test("only bounded tool-call identity receives a domain-separated digest", () => {
  const id = "SENSITIVE_CANARY_CALL_ID";
  const digest = toolCallIdDigest(id);
  expect(digest).toMatch(/^[a-f0-9]{64}$/u); expect(digest).not.toContain(id);
  expect(toolCallIdDigest(id)).toBe(digest); expect(toolCallIdDigest(id + "2")).not.toBe(digest);
  expect(toolCallIdDigest("x".repeat(513))).toBeNull(); expect(toolCallIdDigest({ command: id })).toBeNull();
});

test("session identity digest is separately domain-bound and rejects paths", () => {
  expect(sessionIdDigest("session-1")).not.toBe(toolCallIdDigest("session-1"));
  expect(sessionIdDigest("session-1")).toMatch(/^[a-f0-9]{64}$/u);
  expect(sessionIdDigest("/private/session/path")).toBeNull(); expect(sessionIdDigest("x".repeat(513))).toBeNull();
});
test("analysis and input observations are closed metadata, never pre-model gates", () => {
  const records: any[] = [], audit = createApprovalAudit((_type, data) => records.push(data));
  const call = audit.begin("call_metadata", "bash", "smart", 1);
  call.analysis("unsupported", [70, 0], []);
  call.data.analysis.command = "SECRET_CANARY_RAW";
  call.data.reviewInput = { redacted: true, omittedMessages: 3, authorizationHistoryComplete: false, body: "SECRET_CANARY_RAW" };
  audit.finish(call, "hook", "blocked", "USER_CONFIRMATION_REQUIRED");
  expect(records[0].analysis).toEqual({ status: "unsupported", matchedRuleIds: [70, 0], uncertainRuleIds: [] });
  expect(records[0].reviewInput).toEqual({ redacted: true, omittedMessages: 3, authorizationHistoryComplete: false });
  expect(records[0].preModelGates).toEqual([]);
  expect(JSON.stringify(records)).not.toContain("SECRET_CANARY_RAW");
});

test("output truncation is retained as a fixed closed failure code without response metadata", () => {
  const records: any[] = [], audit = createApprovalAudit((_type, data) => records.push(data));
  const call = audit.begin("call_truncated", "bash", "smart", 1);
  call.review({ status: "failure", primary: { status: "failure", called: true, health: "invalid",
    failureCode: "REVIEW_OUTPUT_TRUNCATED", body: "SENSITIVE_CANARY_BODY", response: "SENSITIVE_CANARY_BODY",
    stopReason: "SENSITIVE_CANARY_BODY", usage: { output_tokens: 1024 }, headers: { authorization: "SENSITIVE_CANARY_BODY" } } } as any);
  audit.finish(call, "hook", "blocked", "REVIEW_UNAVAILABLE");
  expect(records[0].attempts).toEqual([{ target: "primary", status: "failure", called: true, failureCode: "REVIEW_OUTPUT_TRUNCATED" }]);
  expect(JSON.stringify(records)).not.toContain("SENSITIVE_CANARY_BODY");
  expect(JSON.stringify(records)).not.toContain("output_tokens");
  expect(records[0].attempts[0]).not.toHaveProperty("stopReason");
});
