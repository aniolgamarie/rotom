import { expect, test } from "bun:test";
import { createApprovalAudit, reviewFailureSummary, safeAttempts, safeIdentity, toolCallIdDigest, sessionIdDigest } from "./approval-diagnostic";

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

function timing(overrides: Record<string, unknown> = {}) {
  return { budgetMs: 30000, remainingTotalMs: 60000, elapsedMs: 30000, lastStage: "response-headers",
    stages: [{ stage: "resolve-target", durationMs: 1 }, { stage: "response-headers", durationMs: 29999 }],
    requestBytes: 128, timeoutSource: "primary-budget", ...overrides };
}
function failedSequence(primaryTiming?: unknown, remoteTiming?: unknown): any {
  return { status: "failure", primary: { status: "failure", called: true, health: "timeout", failureCode: "TIMEOUT",
    ...(primaryTiming === undefined ? {} : { timing: primaryTiming }) },
    ...(remoteTiming === undefined ? {} : { remote: { status: "failure", called: true, health: "timeout",
      failureCode: "TIMEOUT", timing: remoteTiming } }) };
}
test("bounded attempt timing survives both filters and distinguishes local and total deadlines", () => {
  for (const source of ["remote-budget", "total-budget"]) {
    const primary = timing(), remote = timing({ budgetMs: 20000, remainingTotalMs: 20000, elapsedMs: 20000,
      lastStage: "response-body", stages: [{ stage: "response-body", durationMs: 20000 }], timeoutSource: source });
    const result = failedSequence(primary, remote), records: any[] = [];
    const audit = createApprovalAudit((_type, data) => records.push(data)), call = audit.begin("call_timing", "bash", "smart", 1);
    call.review(result); audit.finish(call, "hook", "blocked", "REVIEW_UNAVAILABLE");
    expect(safeAttempts(result).map(item => item.timing)).toEqual([primary, remote]);
    expect(records[0].attempts.map((item: any) => item.timing)).toEqual([primary, remote]);
    expect(records[0].version).toBe(1);
    expect(reviewFailureSummary(result)).toBe(`主审：等待响应头，30.0s，主审预算到期；备用：读取响应体，20.0s，${source === "remote-budget" ? "备用预算到期" : "总预算到期"}`);
  }
});
test("timing is optional for legacy failures and valid decisions have fixed summaries", () => {
  expect(reviewFailureSummary()).toBe("");
  expect(reviewFailureSummary(failedSequence())).toBe("主审：审查超时");
  expect(safeAttempts(failedSequence())[0]).not.toHaveProperty("timing");
  for (const decision of ["allow", "ask", "deny"]) {
    const result: any = { status: "valid", primary: { status: "valid", called: true, model: {}, timing: timing({ timeoutSource: undefined }),
      review: { decision, risk: "unknown", authorization: "unknown", reasonCode: "UNKNOWN_RISK", reason: "SECRET_CANARY_REASON" } } };
    const audit = createApprovalAudit(() => {}), call = audit.begin("call_valid", "bash", "smart", 1);
    call.review(result); audit.finish(call, "hook", "approved", "LOW_RISK_AUTHORIZED");
    expect(audit.state.last.attempts).toEqual(safeAttempts(result));
    expect(safeAttempts(result)[0].timing?.elapsedMs).toBe(30000);
    expect(reviewFailureSummary(result)).toBe(`主审：${decision === "allow" ? "允许" : decision === "deny" ? "拒绝" : "需人工确认"}`);
  }
});
test("timing rejects invalid core numbers and unknown stages without leaking arbitrary text", () => {
  for (const [key, values] of Object.entries({ budgetMs: [-1, 240001, Infinity, 0.5, "SECRET_CANARY"],
    remainingTotalMs: [240001, Number.MAX_SAFE_INTEGER], elapsedMs: [86400001, NaN],
    lastStage: ["SECRET_CANARY", "command"], stages: [null, Array(7).fill({ stage: "response-body", durationMs: 1 })] })) {
    for (const value of values) expect(safeAttempts(failedSequence(timing({ [key]: value })))[0]).not.toHaveProperty("timing");
  }
  const result = failedSequence(timing({ budgetMs: 0, remainingTotalMs: 240000, elapsedMs: 86400000,
    stages: [{ stage: "SECRET_CANARY", durationMs: 2 }, { stage: "response-body", durationMs: 86400001 },
      { stage: "decision-parse", durationMs: 86400000, command: "SECRET_CANARY" }],
    requestBytes: 65537, timeoutSource: "SECRET_CANARY", command: "SECRET_CANARY", headers: "SECRET_CANARY" }));
  const cleaned = safeAttempts(result)[0].timing!;
  expect(cleaned.stages).toEqual([{ stage: "decision-parse", durationMs: 86400000 }]);
  expect(cleaned).not.toHaveProperty("requestBytes"); expect(cleaned).not.toHaveProperty("timeoutSource");
  expect(JSON.stringify(safeAttempts(result)) + reviewFailureSummary(result)).not.toContain("SECRET_CANARY");
  expect(safeAttempts(failedSequence(timing({ requestBytes: 65536 })))[0].timing?.requestBytes).toBe(65536);
  for (const value of [-1, 0.1, Number.MAX_SAFE_INTEGER, "SECRET_CANARY"])
    expect(safeAttempts(failedSequence(timing({ requestBytes: value })))[0].timing).not.toHaveProperty("requestBytes");
});
test("own data fields avoid all getters during attempts, summaries and final audit", () => {
  let getterCalls = 0;
  const get = () => { getterCalls++; throw new Error("SECRET_CANARY_GETTER"); };
  const rawTiming: any = timing();
  for (const key of ["requestBytes", "timeoutSource", "command"]) Object.defineProperty(rawTiming, key, { get });
  Object.defineProperty(rawTiming.stages[0], "durationMs", { get });
  const result = failedSequence(rawTiming);
  for (const key of ["model", "transportCode", "httpStatus", "reason", "headers"]) Object.defineProperty(result.primary, key, { get });
  Object.defineProperty(result, "remote", { get });
  const records: any[] = [], audit = createApprovalAudit((_type, data) => records.push(data));
  const call = audit.begin("call_getters", "bash", "smart", 1);
  call.review(result);
  const nested = call.data.attempts[0].timing;
  Object.defineProperty(nested, "requestBytes", { get });
  Object.defineProperty(call.data.attempts[0], "provider", { get });
  nested.endpoint = "SECRET_CANARY_ENDPOINT";
  audit.finish(call, "hook", "blocked", "REVIEW_UNAVAILABLE");
  expect(records).toHaveLength(1);
  expect(records[0].attempts[0].timing.stages).toEqual([{ stage: "response-headers", durationMs: 29999 }]);
  expect(reviewFailureSummary(result)).toBe("主审：等待响应头，30.0s，审查超时");
  expect(getterCalls).toBe(0);
  expect(JSON.stringify(records)).not.toContain("SECRET_CANARY");
  const inherited: any = Object.create({ timing: timing(), failureCode: "TIMEOUT" });
  inherited.status = "failure";
  expect(safeAttempts({ primary: inherited } as any)[0]).toEqual({ target: "primary", status: "failure", called: false, failureCode: "REQUEST_FAILED" });
});
test("unknown failure text and timing misplaced fields cannot enter fixed summaries or audits", () => {
  const result = failedSequence(timing());
  result.primary.failureCode = "SECRET_CANARY_FAILURE"; result.primary.error = "SECRET_CANARY_ERROR";
  result.primary.elapsedMs = "SECRET_CANARY_MISPLACED"; result.primary.timing.body = "SECRET_CANARY_BODY";
  const audit = createApprovalAudit(() => {}), call = audit.begin("call_misplaced", "bash", "smart", 1);
  call.review(result); call.data.attempts[0].timing.elapsedMs = "SECRET_CANARY_MUTATION";
  audit.finish(call, "hook", "blocked", "REVIEW_UNAVAILABLE");
  expect(audit.state.last.attempts[0]).not.toHaveProperty("timing");
  expect(JSON.stringify(audit.state.last) + reviewFailureSummary(result)).not.toContain("SECRET_CANARY");
  expect(reviewFailureSummary({ primary: { status: "failure", failureCode: "SECRET_CANARY", error: "SECRET_CANARY" } } as any)).toBe("主审：请求失败");
});

test("all six review stages remain bounded fixed labels", () => {
  const stages = ["resolve-target", "key-lookup", "response-headers", "response-body", "response-parse", "decision-parse"];
  const labels = ["解析审查目标", "查找凭据", "等待响应头", "读取响应体", "解析响应", "解析决定"];
  for (let index = 0; index < stages.length; index++) {
    const result = failedSequence(timing({ lastStage: stages[index], elapsedMs: 0, timeoutSource: undefined,
      stages: stages.map(stage => ({ stage, durationMs: 0 })) }));
    expect(safeAttempts(result)[0].timing?.stages).toHaveLength(6);
    expect(reviewFailureSummary(result)).toBe(`主审：${labels[index]}，0.0s，审查超时`);
  }
});
