import { expect, test } from "bun:test";
import { transportCode, callerCancelled, type ReviewRuntime } from "./standalone-reviewer";
const model = { provider: "fictional", id: "reviewer", api: "openai-completions", baseUrl: "https://unused.invalid/v1" };
const valid = (decision = "allow") => JSON.stringify({ decision, risk: decision === "allow" ? "low" : "unknown",
  authorization: decision === "allow" ? "sufficient" : "unknown", reasonCode: decision === "allow" ? "LOW_RISK_AUTHORIZED" : "UNKNOWN_RISK" });
function runtime(fetchImpl: ReviewRuntime["fetch"]): ReviewRuntime {
  return { resolve: () => ({ ...model, id: "remote" }), current: () => model, getApiKey: async () => "fake-key",
    fetch: fetchImpl, deadlines: { totalMs: 30, primaryMs: 10 } };
}
import { prepareReviewPacket, type RawReviewInput } from "./review-input";
import { reviewCommand as reviewPacket } from "./standalone-reviewer";
const input = { command: "echo fixture", cwd: "/fixture", userMessages: ["run the fixture"], reviewer: "session" as const };
function reviewCommand(input: RawReviewInput & { reviewer: "session"; remoteFallback?: { provider: string; model: string } },
  runtime: ReviewRuntime, signal?: AbortSignal) {
  const { reviewer, remoteFallback, ...raw } = input;
  const prepared = prepareReviewPacket(raw);
  if (prepared.status !== "ready") throw new Error("invalid fixture");
  return reviewPacket(prepared.packet, { reviewer, remoteFallback }, runtime, signal);
}
for (const status of [400, 401, 429, 500]) {
  test(`safe HTTP ${status} failure without response text/URLs`, async () => {
    const result = await reviewCommand(input, runtime(async () => new Response("SENSITIVE_CANARY_RESPONSE", { status })));
    expect(result.primary).toMatchObject({ status: "failure", health: "transport", failureCode: "HTTP_NON_OK", httpStatus: status, called: true });
    expect(JSON.stringify(result.primary)).not.toContain("SENSITIVE_CANARY_RESPONSE");
  });
}
for (const [body, failureCode] of [["{broken", "RESPONSE_JSON_INVALID"], ["[]", "RESPONSE_SHAPE_INVALID"],
  [JSON.stringify({ choices: [] }), "RESPONSE_SHAPE_INVALID"],
  [JSON.stringify({ choices: [{ message: { content: "{broken" } }] }), "REVIEW_JSON_INVALID"],
  [JSON.stringify({ choices: [{ message: { content: '{"decision":"bogus"}' } }] }), "REVIEW_SCHEMA_INVALID"]]) {
  test(`safe fixed parser failure ${failureCode}`, async () => {
    const result = await reviewCommand(input, runtime(async () => new Response(body)));
    expect(result.primary).toMatchObject({ status: "failure", health: "invalid", failureCode });
  });
}
test("transport records only own known code, never message/stack/cause/getter", async () => {
  const error = Object.assign(new Error("SECRET_CANARY_MESSAGE"), { code: "ECONNRESET", cause: { key: "SECRET_CANARY_CAUSE" } });
  const result = await reviewCommand(input, runtime(async () => { throw error; }));
  expect(result.primary).toMatchObject({ failureCode: "FETCH_FAILED", transportCode: "ECONNRESET" });
  expect(result.primary).not.toHaveProperty("message"); expect(result.primary).not.toHaveProperty("cause");
  expect(transportCode({ get code() { throw new Error("not read"); } })).toBeUndefined();
  expect(transportCode({ code: "SECRET_CANARY_CODE" })).toBeUndefined();
});
for (const decision of ["ask", "deny"]) {
  test(`primary valid ${decision} never starts remote`, async () => {
    let calls = 0;
    const result = await reviewCommand({ ...input, remoteFallback: { provider: "fictional", model: "remote" } }, runtime(async () => {
      calls++; return new Response(JSON.stringify({ choices: [{ message: { content: valid(decision) } }] }));
    }));
    expect(result.source).toBe("primary"); expect(result.review?.decision).toBe(decision);
    expect(result.remote).toBeUndefined(); expect(calls).toBe(1);
  });
}
test("timeout/cancel preserve fixed shared budget without retries", async () => {
  let calls = 0;
  const r = runtime(async () => { calls++; return new Promise<Response>(() => {}); });
  const timeout = await reviewCommand(input, r);
  expect(timeout.primary).toMatchObject({ health: "timeout", failureCode: "TIMEOUT" }); expect(calls).toBe(1);
  const controller = new AbortController(); controller.abort();
  const cancel = await reviewCommand(input, r, controller.signal);
  expect(cancel.primary).toMatchObject({ health: "cancelled", failureCode: "CANCELLED", called: false });
  expect(calls).toBe(1);
});

test("primary window timeout uses the remaining shared budget for one remote attempt", async () => {
  let calls = 0;
  const r = runtime(async () => { calls++; return calls === 1 ? new Promise<Response>(() => {}) :
    new Response(JSON.stringify({ choices: [{ message: { content: valid() } }] })); });
  r.deadlines = { totalMs: 50, primaryMs: 5 };
  const result = await reviewCommand({ ...input, remoteFallback: { provider: "fictional", model: "remote" } }, r);
  expect(result.primary).toMatchObject({ failureCode: "TIMEOUT", health: "timeout" });
  expect(result.remote?.status).toBe("valid"); expect(result.source).toBe("remote"); expect(calls).toBe(2);
});
test("exhausted total budget labels primary timeout and does not start remote", async () => {
  let calls = 0;
  const r = runtime(async () => { calls++; return new Promise<Response>(() => {}); });
  r.deadlines = { totalMs: 15, primaryMs: 15 };
  const result = await reviewCommand({ ...input, remoteFallback: { provider: "fictional", model: "remote" } }, r);
  expect(result.primary).toMatchObject({ failureCode: "TIMEOUT" });
  expect(result.remote).toBeUndefined(); expect(calls).toBe(1);
});

test("already-cancelled caller never resolves target/key/fetch and elapsed total never resolves fallback", async () => {
  let current = 0, resolves = 0, keys = 0, calls = 0;
  const r: ReviewRuntime = { current: () => { current++; return model; }, resolve: () => { resolves++; return { ...model, id: "remote" }; },
    getApiKey: async () => { keys++; return "fake-key"; }, fetch: async () => { calls++; return new Promise<Response>(() => {}); },
    deadlines: { totalMs: 15, primaryMs: 15 } };
  const controller = new AbortController(); controller.abort();
  const args = { ...input, remoteFallback: { provider: "fictional", model: "remote" } };
  await reviewCommand(args, r, controller.signal);
  expect({ current, resolves, keys, calls }).toEqual({ current: 0, resolves: 0, keys: 0, calls: 0 });
  const result = await reviewCommand(args, r);
  expect(result.primary).toMatchObject({ failureCode: "TIMEOUT" }); expect(result.remote).toBeUndefined();
  expect({ current, resolves, keys, calls }).toEqual({ current: 1, resolves: 0, keys: 1, calls: 1 });
});

test("first abort identity prevents late caller cancellation from relabeling a timeout", () => {
  const deadline = new AbortController(), caller = new AbortController();
  const combined = AbortSignal.any([deadline.signal, caller.signal]);
  const timeoutReason = {}; deadline.abort(timeoutReason); caller.abort({});
  expect(callerCancelled(combined, caller.signal)).toBe(false);
  const firstCaller = new AbortController(), laterDeadline = new AbortController();
  const other = AbortSignal.any([firstCaller.signal, laterDeadline.signal]);
  firstCaller.abort({}); laterDeadline.abort({});
  expect(callerCancelled(other, firstCaller.signal)).toBe(true);
});


test("caller cancellation during the active primary never resolves or looks up fallback", async () => {
  const controller = new AbortController();
  let current = 0, resolves = 0, keys = 0, calls = 0;
  const r: ReviewRuntime = {
    current: () => { current++; return model; },
    resolve: () => { resolves++; return { ...model, id: "remote" }; },
    getApiKey: async () => { keys++; return "fake-key"; },
    fetch: async () => { calls++; controller.abort(); return new Promise<Response>(() => {}); },
    deadlines: { totalMs: 50, primaryMs: 30 },
  };
  const result = await reviewCommand({ ...input, remoteFallback: { provider: "fictional", model: "remote" } }, r, controller.signal);
  expect(result.primary).toMatchObject({ failureCode: "CANCELLED", health: "cancelled", called: true });
  expect(result.remote).toBeUndefined();
  expect({ current, resolves, keys, calls }).toEqual({ current: 1, resolves: 0, keys: 1, calls: 1 });
});

for (const api of ["openai-completions", "anthropic-messages"]) test(`all ${api} primary/fallback bodies reuse the same sanitized packet`, async () => {
  const prepared = prepareReviewPacket({ command: "curl --token CANARY_COMMAND https://fixture.invalid", cwd: "/fixture",
    userMessages: ["Authorization: read-only query; password=CANARY_USER"],
    executionContext: { shellFamily: "zsh", plan: [{ apiKey: "CANARY_NESTED", target: "https://fixture.invalid" }] } });
  expect(prepared.status).toBe("ready");
  if (prepared.status !== "ready") throw 0;
  const prompts: string[] = [], bodies: string[] = [];
  const r: ReviewRuntime = { current: () => ({ ...model, api }), resolve: () => ({ ...model, id: "remote", api }),
    getApiKey: async () => "fictional-provider-key", fetch: async (_url, init) => {
      bodies.push(init.body as string);
      const body = JSON.parse(init.body as string);
      prompts.push(body.messages.at(-1).content);
      if (bodies.length === 1) return new Response("opaque failure", { status: 500 });
      return new Response(JSON.stringify(api === "anthropic-messages" ? { content: [{ type: "text", text: valid() }] } :
        { choices: [{ message: { content: valid() } }] }));
    } };
  const result = await reviewPacket(prepared.packet, { reviewer: "session", remoteFallback: { provider: "fictional", model: "remote" } }, r);
  expect(result.source).toBe("remote"); expect(prompts.length).toBe(2); expect(prompts[0]).toBe(prompts[1]);
  expect(JSON.parse(prompts[0])).toEqual({ command: "curl --token [REDACTED] https://fixture.invalid", cwd: "/fixture",
    genuineUserMessages: ["Authorization: read-only query; password=[REDACTED]"],
    executionContext: { shellFamily: "zsh", plan: [{ apiKey: "[REDACTED]", target: "https://fixture.invalid" }] },
    privacy: { redacted: true, detection: "credential-slots-and-known-formats" },
    contextSelection: { omittedMessages: 0, authorizationHistoryComplete: true } });
  for (const body of bodies) expect(body).not.toContain("CANARY_");
  expect(JSON.stringify(result)).not.toContain("CANARY_");
});

test("forged/raw packet rejected before model/key/fetch; no compatibility branch", async () => {
  let calls = 0;
  const r: ReviewRuntime = { current: () => { calls++; return model; }, resolve: () => { calls++; return model; },
    getApiKey: async () => { calls++; return "fake-key"; }, fetch: async () => { calls++; throw new Error("CANARY"); } };
  const forged = { command: "token=CANARY", cwd: "/fixture", genuineUserMessages: ["CANARY"] };
  const result = await reviewPacket(forged as any, { reviewer: "session" }, r);
  expect(result).toEqual({ status: "failure", primary: { status: "failure", called: false, health: "invalid", failureCode: "INPUT_INVALID" } });
  expect(calls).toBe(0); expect(JSON.stringify(result)).not.toContain("CANARY");
});

function reviewEnvelope(api: string, content: unknown, limited: boolean) {
  return api === "anthropic-messages"
    ? { content: [{ type: "text", text: content }], stop_reason: limited ? "max_tokens" : "end_turn" }
    : { choices: [{ message: { content }, finish_reason: limited ? "length" : "stop" }] };
}
for (const api of ["anthropic-messages", "openai-completions"]) {
  test(`${api} sends shared 1024 output budget`, async () => {
    let body: any;
    const r = runtime(async (_url, init) => { body = JSON.parse(init.body as string);
      return new Response(JSON.stringify(reviewEnvelope(api, valid(), false))); });
    r.current = () => ({ ...model, api });
    const result = await reviewCommand(input, r);
    expect(result.status).toBe("valid"); expect(body.max_tokens).toBe(1024);
    expect(body).not.toHaveProperty("temperature");
    expect(Object.keys(body).sort()).toEqual(api === "anthropic-messages"
      ? ["max_tokens", "messages", "model", "system"] : ["max_tokens", "messages", "model"]);
  });
  for (const [label, content] of [["empty", ""], ["null", null], ["partial JSON", '{"decision":"allow",'],
    ["incomplete schema", '{"decision":"allow"}']] as const) {
    test(`${api} explicit limit and ${label} is closed output-truncated failure`, async () => {
      const r = runtime(async () => new Response(JSON.stringify(reviewEnvelope(api, content, true))));
      r.current = () => ({ ...model, api });
      const result = await reviewCommand(input, r);
      expect(result.primary).toMatchObject({ status: "failure", called: true, health: "invalid", failureCode: "REVIEW_OUTPUT_TRUNCATED" });
      expect(result.remote).toBeUndefined();
    });
  }
  for (const decision of ["allow", "ask", "deny"]) test(`${api} explicit limit preserves complete strict ${decision} without fallback`, async () => {
    let calls = 0;
    const r = runtime(async () => { calls++; return new Response(JSON.stringify(reviewEnvelope(api, valid(decision), true))); });
    r.current = () => ({ ...model, api });
    const result = await reviewCommand({ ...input, remoteFallback: { provider: "fictional", model: "remote" } }, r);
    expect(result.status).toBe("valid"); expect(result.review?.decision).toBe(decision);
    expect(result.source).toBe("primary"); expect(result.remote).toBeUndefined(); expect(calls).toBe(1);
  });
  test(`${api} usage at its output budget does not imply truncation`, async () => {
    const envelope = { ...reviewEnvelope(api, "{broken", false), usage: { output_tokens: 1024, completion_tokens: 1024 } };
    const r = runtime(async () => new Response(JSON.stringify(envelope))); r.current = () => ({ ...model, api });
    expect((await reviewCommand(input, r)).primary).toMatchObject({ failureCode: "REVIEW_JSON_INVALID" });
  });
  test(`${api} truncated primary uses one configured remote with the identical packet`, async () => {
    const otherApi = api === "anthropic-messages" ? "openai-completions" : "anthropic-messages";
    const prompts: string[] = [];
    const r = runtime(async (_url, init) => {
      const body = JSON.parse(init.body as string); prompts.push(body.messages.at(-1).content);
      return new Response(JSON.stringify(reviewEnvelope(prompts.length === 1 ? api : otherApi,
        prompts.length === 1 ? null : valid("ask"), prompts.length === 1)));
    });
    r.current = () => ({ ...model, api }); r.resolve = () => ({ ...model, id: "remote", api: otherApi });
    const result = await reviewCommand({ ...input, remoteFallback: { provider: "fictional", model: "remote" } }, r);
    expect(result.primary).toMatchObject({ failureCode: "REVIEW_OUTPUT_TRUNCATED", called: true });
    expect(result.source).toBe("remote"); expect(result.review?.decision).toBe("ask");
    expect(prompts).toHaveLength(2); expect(prompts[0]).toBe(prompts[1]);
  });
}
for (const content of [[], [{ type: "thinking", thinking: "SENSITIVE_CANARY_REASONING" }], [{ type: "redacted_thinking", data: "SENSITIVE_CANARY_REASONING" }]]) {
  test("Anthropic explicit max_tokens with no text is truncated without retaining reasoning", async () => {
    const r = runtime(async () => new Response(JSON.stringify({ content, stop_reason: "max_tokens" })));
    r.current = () => ({ ...model, api: "anthropic-messages" });
    const result = await reviewCommand(input, r);
    expect(result.primary).toMatchObject({ failureCode: "REVIEW_OUTPUT_TRUNCATED", health: "invalid" });
    expect(JSON.stringify(result)).not.toContain("SENSITIVE_CANARY_REASONING");
  });
}
for (const [api, envelope] of [
  ["anthropic-messages", { content: [{ type: "unknown", text: "SENSITIVE_CANARY_RESPONSE" }], stop_reason: "max_tokens" }],
  ["anthropic-messages", { content: [{ type: "text", text: valid() }, { type: "text", text: "" }], stop_reason: "max_tokens" }],
  ["anthropic-messages", { content: [{ type: "text" }], stop_reason: "max_tokens" }],
  ["anthropic-messages", { content: null, stop_reason: "max_tokens" }],
  ["anthropic-messages", { content: [{ type: "thinking", thinking: "SENSITIVE_CANARY_RESPONSE" }], stop_reason: "end_turn" }],
  ["openai-completions", { choices: [{ message: { content: valid(), tool_calls: [] }, finish_reason: "length" }] }],
  ["openai-completions", { choices: [{ message: { content: [] }, finish_reason: "length" }] }],
  ["openai-completions", { choices: [null], finish_reason: "length" }],
  ["openai-completions", reviewEnvelope("openai-completions", null, false)],
] as const) test(`${api} nonstandard response remains shape error despite limit metadata`, async () => {
  const r = runtime(async () => new Response(JSON.stringify(envelope))); r.current = () => ({ ...model, api });
  const result = await reviewCommand(input, r);
  expect(result.primary).toMatchObject({ failureCode: "RESPONSE_SHAPE_INVALID" });
  expect(JSON.stringify(result)).not.toContain("SENSITIVE_CANARY_RESPONSE");
});
