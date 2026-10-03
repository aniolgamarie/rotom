import { describe, expect, test } from "bun:test";
import { buildReviewRequest, decodeReview, type ReviewValidationContext } from "../reviewer";

const digest = "a".repeat(64);
const chineseMessage = "请查看 README 和目录。";
const byteLength = (text: string): number => new TextEncoder().encode(text).length;
function context(): ReviewValidationContext {
  return {
    effects: [{ effectId: "effect-1", scopeDigest: digest }, { effectId: "effect-2", scopeDigest: "b".repeat(64) }],
    messages: [{ messageId: "user-1", text: chineseMessage }],
    verifiedUserMessageIds: new Set(["user-1"]),
    generation: 1, currentGeneration: 1, contextComplete: true, redactionComplete: true,
    outputTokens: 120, toolCalls: [],
  };
}
function reply(): any {
  return {
    decision: "allow", risk: "low", authorization: "sufficient",
    effects: ["effect-1", "effect-2"], unknowns: [], reasonCode: "LOW_RISK_AUTHORIZED",
    evidence: { userMessageIds: ["user-1"], bindings: [
      { effectId: "effect-1", userMessageId: "user-1", startByte: 0, endByte: byteLength(chineseMessage), scopeDigest: digest },
      { effectId: "effect-2", userMessageId: "user-1", startByte: 0, endByte: byteLength(chineseMessage), scopeDigest: "b".repeat(64) },
    ] },
  };
}

describe("strict reviewer response and per-effect evidence", () => {
  test("accepts a complete bound response without interpreting natural-language meaning", () => {
    expect(decodeReview(JSON.stringify(reply()), context()).decision).toBe("allow");
  });
  test("rejects a UTF-8-valid partial-word citation on allow", () => {
    const text = "Please inspect repository.";
    const ctx = context();
    ctx.messages = [{ messageId: "user-1", text }];
    const value = reply();
    for (const binding of value.evidence.bindings) binding.endByte = byteLength("Please inspect repos");
    expect(() => decodeReview(JSON.stringify(value), ctx)).toThrow("INVALID_REVIEW_OUTPUT");
  });
  test("accepts whole-message allow citations for Chinese and ASCII", () => {
    expect(decodeReview(JSON.stringify(reply()), context()).decision).toBe("allow");
    const text = "Please inspect the repository.";
    const ctx = context();
    ctx.messages = [{ messageId: "user-1", text }];
    const value = reply();
    for (const binding of value.evidence.bindings) binding.endByte = byteLength(text);
    expect(decodeReview(JSON.stringify(value), ctx).decision).toBe("allow");
  });
  test("whole-message structure does not make negative text semantically authorizing", () => {
    const text = "Do not inspect the repository.";
    const ctx = context();
    ctx.messages = [{ messageId: "user-1", text }];
    const value = reply();
    for (const binding of value.evidence.bindings) binding.endByte = byteLength(text);
    // The strict decoder verifies provenance and complete citations; the reviewer still owns semantics.
    expect(decodeReview(JSON.stringify(value), ctx).decision).toBe("allow");
  });
  for (const outcome of ["ask", "deny"] as const) {
    test(`${outcome} may have empty evidence and remains a valid response`, () => {
      const value = { ...reply(), decision: outcome, risk: "unknown", authorization: "unknown",
        reasonCode: "USER_CONFIRMATION_REQUIRED", evidence: { userMessageIds: [], bindings: [] } };
      expect(decodeReview(JSON.stringify(value), context()).decision).toBe(outcome);
    });
    test(`${outcome} may retain a valid partial citation`, () => {
      const value = { ...reply(), decision: outcome, risk: "unknown", authorization: "unknown",
        reasonCode: "USER_CONFIRMATION_REQUIRED" };
      for (const binding of value.evidence.bindings) binding.endByte = 3;
      expect(decodeReview(JSON.stringify(value), context()).decision).toBe(outcome);
    });
  }
  const cases: Array<[string, (value: any) => void]> = [
    ["extra top field", v => { v.rawReason = "not allowed"; }],
    ["missing field", v => { delete v.risk; }],
    ["unknown outcome", v => { v.decision = "approve"; }],
    ["free-form reason", v => { v.reasonCode = "Looks fine to me"; }],
    ["medium allow", v => { v.risk = "medium"; }],
    ["insufficient allow", v => { v.authorization = "insufficient"; }],
    ["wrong allow reason", v => { v.reasonCode = "MATERIAL_RISK"; }],
    ["unknown on allow", v => { v.unknowns = ["unresolved-target"]; }],
    ["missing pipeline effect", v => { v.effects.pop(); }],
    ["invented effect", v => { v.effects[1] = "effect-other"; }],
    ["duplicate effect", v => { v.effects[1] = "effect-1"; }],
    ["extra evidence field", v => { v.evidence.quote = "please"; }],
    ["missing evidence field", v => { delete v.evidence.bindings; }],
    ["empty allow evidence", v => { v.evidence = { userMessageIds: [], bindings: [] }; }],
    ["duplicate message", v => { v.evidence.userMessageIds.push("user-1"); }],
    ["uncited message", v => { v.evidence.userMessageIds.push("user-unused"); }],
    ["unlisted message", v => { v.evidence.userMessageIds = []; }],
    ["unknown message", v => { v.evidence.bindings[0].userMessageId = "tool-1"; }],
    ["duplicate binding", v => { v.evidence.bindings[1] = { ...v.evidence.bindings[0] }; }],
    ["missing binding", v => { v.evidence.bindings.pop(); }],
    ["extra binding field", v => { v.evidence.bindings[0].text = "请"; }],
    ["missing binding field", v => { delete v.evidence.bindings[0].scopeDigest; }],
    ["negative quote", v => { v.evidence.bindings[0].startByte = -1; }],
    ["fractional quote", v => { v.evidence.bindings[0].startByte = 0.5; }],
    ["empty quote", v => { v.evidence.bindings[0].endByte = 0; }],
    ["out of bounds quote", v => { v.evidence.bindings[0].endByte = 10000; }],
    ["mid UTF-8 quote", v => { v.evidence.bindings[0].startByte = 1; }],
    ["wrong effect target digest", v => { v.evidence.bindings[0].scopeDigest = "c".repeat(64); }],
    ["newline digest", v => { v.evidence.bindings[0].scopeDigest += "\n"; }],
  ];
  for (const [name, change] of cases) {
    test(`rejects ${name}`, () => {
      const value = reply(); change(value);
      expect(() => decodeReview(JSON.stringify(value), context())).toThrow("INVALID_REVIEW_OUTPUT");
    });
  }
  for (const raw of [
    "```json\n{}\n```", "{} trailing", "prefix {}", "null", "[]", "{\"risk\":NaN}",
    "{\"decision\":\"allow\",\"decision\":\"deny\"}",
    "{\"evidence\":{\"bindings\":[],\"bindings\":[]}}",
    "{\"decision\":1,\"decisio\\u006e\":2}", "{\"x\":01}",
  ]) {
    test(`rejects malformed or duplicate JSON ${raw.slice(0, 25)}`, () => {
      expect(() => decodeReview(raw, context())).toThrow("INVALID_REVIEW_OUTPUT");
    });
  }
  test("tool/file/synthetic user IDs cannot become genuine user evidence", () => {
    const ctx = context(); ctx.verifiedUserMessageIds = new Set();
    expect(() => decodeReview(JSON.stringify(reply()), ctx)).toThrow("INVALID_REVIEW_OUTPUT");
  });
  test("checks supplied evidence even when the response asks", () => {
    const value = reply(); value.decision = "ask"; value.evidence.bindings[0].startByte = 1;
    expect(() => decodeReview(JSON.stringify(value), context())).toThrow("INVALID_REVIEW_OUTPUT");
  });
  test("rejects incomplete later context, redaction loss, and stale generation", () => {
    for (const change of [{ contextComplete: false }, { redactionComplete: false }, { currentGeneration: 2 }]) {
      expect(() => decodeReview(JSON.stringify(reply()), { ...context(), ...change })).toThrow("REVIEW_CONTEXT_INVALID");
    }
  });
  test("enforces actual output token and byte ceilings and forbids tool calls", () => {
    const raw = JSON.stringify(reply());
    for (const change of [{ outputTokens: 513 }, { outputTokens: -1 }, { outputTokens: NaN }, { toolCalls: [{}] }]) {
      expect(() => decodeReview(raw, { ...context(), ...change })).toThrow("INVALID_REVIEW_OUTPUT");
    }
    expect(() => decodeReview(" ".repeat(4096) + raw, context())).toThrow("INVALID_REVIEW_OUTPUT");
  });
  test("unknown enums and duplicate unknowns fail even in ask responses", () => {
    for (const unknowns of [["new-unknown"], ["missing-context", "missing-context"]]) {
      const value = { ...reply(), decision: "ask", unknowns };
      expect(() => decodeReview(JSON.stringify(value), context())).toThrow("INVALID_REVIEW_OUTPUT");
    }
  });
  test("never echoes hostile field names or provider bodies in errors", () => {
    const value = reply(); value["secret-sentinel-unknown-key"] = "credential-sentinel";
    try { decodeReview(JSON.stringify(value), context()); throw new Error("expected rejection"); }
    catch (error) { expect(String(error)).toBe("ReviewContractError: INVALID_REVIEW_OUTPUT"); }
  });
});

function requestInput(): any {
  return {
    session_id: "session-1", generation: 1, session_salt: "s".repeat(64),
    operation: "pwd", final_args: { command: "pwd", cwd: "/repo" },
    prepared_execution_id: Object.freeze({ kind: "host-plan" }),
    execution_binding: { digest, local_ref: Object.freeze({ kind: "host-binding" }) },
    transformation_summary: { version: 1, transformations: ["effective-params"] },
    execution_context: { cwd: "/repo", shell: { path: "/bin/bash", args: [], identityDigest: digest },
      backend: "native", environmentDigest: digest, targetFingerprint: digest },
    effects: [{ effectId: "effect-1", kind: "read", target: "/repo", parameters: ["pwd"], cwdCategory: "repo-root", risk: "low" }],
    native_constraints: [{ source: "tool-default", policy: "prompt" }],
    authorization_evidence: [{ messageId: "user-1", text: "Please inspect the current directory." },
      { messageId: "user-2", text: "Do not modify anything or send data." }],
    verified_user_message_ids: new Set(["user-1", "user-2"]),
    context_complete: true, redaction_complete: true, restriction_state: "unknown",
    mode: "smart", policy_version: digest,
    reviewer: { provider: "fictional", model: "small" }, reviewer_source: "explicit-profile",
  };
}

describe("bounded complete review request", () => {
  test("starts deadline before preprocessing, binds effects, and includes later restrictions", () => {
    const input = requestInput();
    input.authorization_evidence[0].utf8ByteLength = 1;
    let now = 10;
    const { request, envelope } = buildReviewRequest(input, () => now++);
    expect(request.deadline).toBe(30010);
    expect(request.prepared_execution_id).toBe(input.prepared_execution_id);
    expect(request.execution_binding.local_ref).toBe(input.execution_binding.local_ref);
    expect(request.request_id.length).toBeGreaterThan(0);
    expect(request.operation_digest).toMatch(/^[a-f0-9]{64}$/);
    expect(request.effects[0].scopeDigest).toMatch(/^[a-f0-9]{64}$/);
    expect(envelope).toContain("Do not modify anything or send data.");
    const instructions = (JSON.parse(envelope) as { instructions: string }).instructions;
    expect(instructions).toContain('"effects":["effect-1"]');
    expect(instructions).toContain('"decision":"ask"');
    expect(instructions).toContain("startByte=0");
    const parsed = JSON.parse(envelope) as { request: { authorization_evidence: Array<Record<string, unknown>> } };
    expect(parsed.request.authorization_evidence).toEqual([
      { messageId: "user-1", text: "Please inspect the current directory.", utf8ByteLength: 37 },
      { messageId: "user-2", text: "Do not modify anything or send data.", utf8ByteLength: 36 },
    ]);
    expect(instructions).not.toContain('"effects":[{"effectId"');
    expect(envelope).not.toContain(input.session_salt);
    expect(envelope).not.toContain("local_ref");
    expect(new TextEncoder().encode(envelope).length).toBeLessThanOrEqual(24 * 1024);
  });
  test("requires references to resolve from user context without command backfilling", () => {
    const { envelope } = buildReviewRequest(requestInput(), () => 0);
    const instructions = (JSON.parse(envelope) as { instructions: string }).instructions;
    expect(instructions).toContain("resolve uniquely from genuine user messages alone");
    expect(instructions).toContain("Never use the proposed operation or effects to disambiguate");
    expect(instructions).toContain("unless the user explicitly grants freedom to choose among them");
    expect(instructions).toContain("permission to inspect an unspecified candidate does not grant selection authority");
    expect(instructions).toContain("require an explicit delegation to choose");
    expect(instructions).toContain("ambiguous-authorization");
  });
  test("does not retain mutable arrays supplied by the caller", () => {
    const input = requestInput();
    const { request } = buildReviewRequest(input, () => 0);
    input.effects[0].parameters.push("different");
    input.authorization_evidence[1].text = "Changed after review started";
    expect(request.effects[0].parameters).toEqual(["pwd"]);
    expect(request.authorization_evidence[1].text).toBe("Do not modify anything or send data.");
    expect(Object.isFrozen(request.effects[0])).toBe(true);
  });
  test("scope digests bind object, parameters, cwd and execution context", () => {
    const first = buildReviewRequest(requestInput(), () => 0).request;
    for (const change of [
      (v: any) => { v.effects[0].target = "/another"; },
      (v: any) => { v.effects[0].parameters = ["pwd", "-P"]; },
      (v: any) => { v.execution_context.cwd = "/another"; },
      (v: any) => { v.execution_context.environmentDigest = "b".repeat(64); },
      (v: any) => { v.final_args.command = "pwd -P"; },
      (v: any) => { v.session_salt = "t".repeat(64); },
    ]) {
      const input = requestInput(); change(input);
      expect(buildReviewRequest(input, () => 0).request.effects[0].scopeDigest).not.toBe(first.effects[0].scopeDigest);
    }
  });
  test("missing provenance, redaction loss and omitted later context fail before inference", () => {
    for (const change of [
      { verified_user_message_ids: new Set(["user-1"]) },
      { context_complete: false }, { redaction_complete: false },
    ]) {
      expect(() => buildReviewRequest({ ...requestInput(), ...change }, () => 0)).toThrow("REVIEW_CONTEXT_INVALID");
    }
  });
  test("input above 24KiB is rejected whole rather than truncated", () => {
    const input = requestInput(); input.authorization_evidence[0].text = "x".repeat(24 * 1024);
    expect(() => buildReviewRequest(input, () => 0)).toThrow("REVIEW_INPUT_TOO_LARGE");
  });
  test("preprocessing that exhausts 30 seconds cannot create a request for inference", () => {
    let count = 0;
    expect(() => buildReviewRequest(requestInput(), () => count++ === 0 ? 0 : 30001)).toThrow("REVIEW_BUDGET_EXCEEDED");
  });
  test("original cancellation remains visible on the frozen request", () => {
    const input = requestInput();
    const controller = new AbortController(); input.signal = controller.signal;
    const { request } = buildReviewRequest(input, () => 0);
    input.signal = new AbortController().signal;
    controller.abort();
    expect(Object.isFrozen(request)).toBe(true);
    expect(request.cancel_state).toBe("cancelled");
  });
});
