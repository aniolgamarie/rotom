import { expect, test } from "bun:test";
import { safeAttempts } from "./approval-diagnostic";
import { prepareReviewPacket } from "./review-input";
import { baseConfig, fakeHost, model, ready } from "./standalone-fixture";
import { validateStandaloneConfig } from "./standalone";
import { REVIEW_STAGES, resolveReviewTimeouts, reviewCommand, type ReviewRuntime, type StandaloneReview } from "./standalone-reviewer";

const remote = { provider: "remote", model: "fallback" };
const selection = { reviewer: "session" as const, remoteFallback: remote };
const delay = (milliseconds: number) => new Promise<void>(resolve => setTimeout(resolve, milliseconds));
const pending = <T>() => new Promise<T>(() => {});
function response(decision: StandaloneReview["decision"] = "allow") {
  const review = decision === "allow" ? { decision, risk: "low", authorization: "sufficient", reasonCode: "LOW_RISK_AUTHORIZED" } :
    { decision, risk: "unknown", authorization: "unknown", reasonCode: "UNKNOWN_RISK" };
  return new Response(JSON.stringify({ choices: [{ message: { content: JSON.stringify(review) } }] }));
}
function packet() {
  const prepared = prepareReviewPacket({ command: "ls -la", cwd: "/repo", userMessages: ["Run ls -la"] });
  if (prepared.status !== "ready") throw new Error("fixture packet unavailable");
  return prepared.packet;
}
function runtime(overrides: Partial<ReviewRuntime> = {}): ReviewRuntime {
  return { current: () => model(), resolve: () => model("remote", "fallback"), getApiKey: async () => "FIXTURE_HEADER_KEY",
    fetch: async () => response(), deadlines: { primaryMs: 200, remoteMs: 200, totalMs: 500 }, ...overrides };
}

test("public deadlines default to 30s windows and reject invalid or undersized configuration", () => {
  expect(resolveReviewTimeouts()).toEqual({ primaryMs: 30000, remoteMs: 30000, totalMs: 60000 });
  const configured = { primaryMs: 1000, remoteMs: 1000, totalMs: 3000 };
  expect(validateStandaloneConfig({ ...baseConfig, remoteFallback: remote, reviewTimeouts: configured }).reviewTimeouts).toEqual(configured);
  for (const invalid of [{ ...configured, primaryMs: 999 }, { ...configured, remoteMs: 120001 },
    { ...configured, totalMs: 240001 }, { ...configured, totalMs: 1999 }, { ...configured, primaryMs: 1000.5 },
    { ...configured, extra: 1 }]) expect(() => resolveReviewTimeouts(invalid, true)).toThrow();
});

test("primary accepts a finite response beyond the old half-sized window", async () => {
  const result = await reviewCommand(packet(), selection, runtime({ deadlines: { primaryMs: 240, remoteMs: 240, totalMs: 600 },
    fetch: async () => { await delay(160); return response(); } }));
  expect(result.status).toBe("valid"); expect(result.source).toBe("primary");
  expect(result.primary.timing?.budgetMs).toBe(240);
  expect(result.primary.timing?.elapsedMs).toBeGreaterThanOrEqual(120);
  expect(result.remote).toBeUndefined();
});

test("primary expiry leaves the remote its complete separate window", async () => {
  let calls = 0;
  const result = await reviewCommand(packet(), selection, runtime({ deadlines: { primaryMs: 40, remoteMs: 180, totalMs: 400 },
    fetch: async () => { if (++calls === 1) return pending<Response>(); await delay(100); return response(); } }));
  expect(result.source).toBe("remote"); expect(result.primary).toMatchObject({ status: "failure", failureCode: "TIMEOUT",
    timing: { timeoutSource: "primary-budget", lastStage: "response-headers", budgetMs: 40 } });
  expect(result.remote).toMatchObject({ status: "valid", timing: { budgetMs: 180 } });
  expect(result.remote?.timing?.elapsedMs).toBeGreaterThanOrEqual(80);
  expect(result.remote?.timing?.remainingTotalMs).toBeGreaterThan(180);
  expect(calls).toBe(2);
});

test("both local deadline sources remain distinct when neither request settles", async () => {
  const result = await reviewCommand(packet(), selection, runtime({ deadlines: { primaryMs: 30, remoteMs: 50, totalMs: 300 },
    fetch: () => pending<Response>() }));
  expect(result.status).toBe("failure");
  expect(result.primary.timing?.timeoutSource).toBe("primary-budget");
  expect(result.remote?.timing?.timeoutSource).toBe("remote-budget");
});

test("total deadline truncates remote and a shorter internal total prevents fallback", async () => {
  const result = await reviewCommand(packet(), selection, runtime({ deadlines: { primaryMs: 25, remoteMs: 200, totalMs: 80 },
    fetch: () => pending<Response>() }));
  expect(result.primary.timing?.timeoutSource).toBe("primary-budget");
  expect(result.remote).toMatchObject({ status: "failure", failureCode: "TIMEOUT", timing: { timeoutSource: "total-budget" } });
  let calls = 0;
  const short = await reviewCommand(packet(), selection, runtime({ deadlines: { primaryMs: 150, remoteMs: 150, totalMs: 30 },
    fetch: () => { calls++; return pending<Response>(); } }));
  expect(short.primary.timing?.timeoutSource).toBe("total-budget");
  expect(short.remote).toBeUndefined(); expect(calls).toBe(1);
});

test("key lookup, headers and body hangs retain their actual last stages", async () => {
  for (const stage of ["key-lookup", "response-headers", "response-body"] as const) {
    const result = await reviewCommand(packet(), { reviewer: "session" }, runtime({
      deadlines: { primaryMs: 40, remoteMs: 100, totalMs: 200 },
      getApiKey: stage === "key-lookup" ? () => pending<string>() : async () => "FIXTURE_HEADER_KEY",
      fetch: stage === "response-headers" ? () => pending<Response>() : async () => new Response(new ReadableStream({ start() {} })),
    }));
    expect(result.primary).toMatchObject({ status: "failure", failureCode: "TIMEOUT", timing: { lastStage: stage, timeoutSource: "primary-budget" } });
    expect(result.primary.timing?.stages.at(-1)?.stage).toBe(stage);
    if (stage === "key-lookup") expect(result.primary.timing?.requestBytes).toBeUndefined();
    else expect(result.primary.timing?.requestBytes).toBeGreaterThan(0);
  }
});

test("successful timing records all phases and exact body bytes without credential metadata", async () => {
  let bodyBytes = 0;
  const result = await reviewCommand(packet(), { reviewer: "session" }, runtime({
    getApiKey: async () => { await delay(10); return "SECRET_CANARY_HEADER_KEY"; },
    fetch: async (_input, init) => {
      bodyBytes = new TextEncoder().encode(init.body as string).length;
      await delay(10);
      const bytes = new Uint8Array(await response().arrayBuffer());
      return new Response(new ReadableStream({ start(controller) { setTimeout(() => { controller.enqueue(bytes); controller.close(); }, 10); } }));
    },
  }));
  expect(result.status).toBe("valid");
  expect(result.primary.timing?.stages.map(item => item.stage)).toEqual([...REVIEW_STAGES]);
  expect(result.primary.timing?.requestBytes).toBe(bodyBytes);
  for (const item of result.primary.timing!.stages) expect(Number.isSafeInteger(item.durationMs) && item.durationMs >= 0).toBe(true);
  for (const stage of ["key-lookup", "response-headers", "response-body"])
    expect(result.primary.timing!.stages.find(item => item.stage === stage)!.durationMs).toBeGreaterThan(0);
  expect(JSON.stringify(safeAttempts(result))).not.toContain("SECRET_CANARY");
  expect(result.primary.timing).not.toHaveProperty("headers");
});

test("caller cancellation and valid ask or deny never start a permissive fallback", async () => {
  let resolves = 0;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort("SECRET_CANARY_CANCEL_REASON"), 20);
  try {
    const cancelled = await reviewCommand(packet(), selection, runtime({ resolve: () => { resolves++; return model("remote", "fallback"); },
      fetch: () => pending<Response>() }), controller.signal);
    expect(cancelled.primary).toMatchObject({ status: "failure", failureCode: "CANCELLED" });
    expect(cancelled.primary.timing).not.toHaveProperty("timeoutSource");
    expect(cancelled.remote).toBeUndefined(); expect(resolves).toBe(0);
    expect(JSON.stringify(safeAttempts(cancelled))).not.toContain("SECRET_CANARY");
  } finally { clearTimeout(timer); }
  for (const decision of ["ask", "deny"] as const) {
    let calls = 0;
    const result = await reviewCommand(packet(), selection, runtime({ resolve: () => { resolves++; return model("remote", "fallback"); },
      fetch: async () => { calls++; return response(decision); } }));
    expect(result.review?.decision).toBe(decision); expect(result.source).toBe("primary");
    expect(result.remote).toBeUndefined(); expect(calls).toBe(1); expect(resolves).toBe(0);
  }
});

test("a late primary allow cannot replace the remote decision", async () => {
  let settlePrimary!: (value: Response) => void, calls = 0;
  const primaryResponse = new Promise<Response>(resolve => { settlePrimary = resolve; });
  const result = await reviewCommand(packet(), selection, runtime({ deadlines: { primaryMs: 25, remoteMs: 200, totalMs: 400 },
    fetch: async () => {
      if (++calls === 1) return primaryResponse;
      settlePrimary(response("allow")); await delay(40); return response("ask");
    } }));
  expect(result.source).toBe("remote"); expect(result.review?.decision).toBe("ask");
  expect(result.primary).toMatchObject({ status: "failure", failureCode: "TIMEOUT" });
  await delay(10);
  expect(result.review?.decision).toBe("ask"); expect(calls).toBe(2);
});

test("synchronous response work past the monotonic deadline cannot become valid", async () => {
  const result = await reviewCommand(packet(), selection, runtime({ deadlines: { primaryMs: 10, remoteMs: 100, totalMs: 20 },
    fetch: async () => {
      const started = performance.now();
      while (performance.now() - started < 40) { /* 模拟阻塞微任务，计时器尚未派发。 */ }
      return response();
    } }));
  expect(result.status).toBe("failure");
  expect(result.primary).toMatchObject({ status: "failure", failureCode: "TIMEOUT" });
  expect(result.primary.timing?.timeoutSource).toBe("primary-budget");
  expect(result.remote).toBeUndefined();
});

test("standalone human title, status and safe audit expose separate configured budgets", async () => {
  const reviewTimeouts = { primaryMs: 1000, remoteMs: 1000, totalMs: 3000 };
  const h = await fakeHost({ config: { ...baseConfig, remoteFallback: remote, reviewTimeouts }, select: "Deny",
    fetchImpl: () => pending<Response>() });
  const tool = await ready(h);
  const result = await tool.execute("call_deadline_ui", { command: "ls -la" }, undefined, undefined, h.ctx);
  expect(result.isError).toBe(true); expect(h.execCalls).toHaveLength(0); expect(h.invokeCalls).toHaveLength(0);
  expect(h.fetchCalls).toHaveLength(2); expect(h.selectCalls).toHaveLength(1);
  const title = h.selectCalls[0][0];
  expect(title).toContain("主审：等待响应头"); expect(title).toContain("主审预算到期");
  expect(title).toContain("备用：等待响应头"); expect(title).toContain("备用预算到期");
  expect(h.auditEntries).toHaveLength(1);
  expect(h.auditEntries[0].data.attempts).toEqual([
    expect.objectContaining({ target: "primary", failureCode: "TIMEOUT", timing: expect.objectContaining({ budgetMs: 1000, timeoutSource: "primary-budget", lastStage: "response-headers" }) }),
    expect.objectContaining({ target: "remote", failureCode: "TIMEOUT", timing: expect.objectContaining({ budgetMs: 1000, timeoutSource: "remote-budget", lastStage: "response-headers" }) }),
  ]);
  await h.commands.get("permission-control").handler("status", h.ctx);
  const status = JSON.parse(h.notices.at(-1)!);
  expect(status.reviewTimeouts).toEqual(reviewTimeouts);
  expect(status.diagnostic.attempts).toEqual(h.auditEntries[0].data.attempts);
  expect(JSON.stringify(h.auditEntries)).not.toContain("test-key");
});

for (const key of ["FIXTURE_HEADER_KEY", undefined]) {
  test(`synchronous expired key lookup returning ${key ? "a key" : "no key"} never sends a request`, async () => {
    let calls = 0;
    const result = await reviewCommand(packet(), selection, runtime({ deadlines: { primaryMs: 10, remoteMs: 100, totalMs: 20 },
      getApiKey: async () => {
        const started = performance.now();
        while (performance.now() - started < 40) { /* 模拟认证阻塞，截止计时器尚未派发。 */ }
        return key;
      },
      fetch: async () => { calls++; return response(); },
    }));
    expect(result.status).toBe("failure");
    expect(result.primary).toMatchObject({ status: "failure", called: false, failureCode: "TIMEOUT",
      timing: { timeoutSource: "primary-budget", lastStage: "key-lookup" } });
    expect(result.remote).toBeUndefined(); expect(calls).toBe(0);
  });
}
