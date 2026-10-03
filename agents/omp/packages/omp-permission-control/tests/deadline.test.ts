import { expect, test } from "bun:test";
import { buildReviewRequest, reviewWithFallback } from "../reviewer";
import { FakeClock, prepared, askReply, input } from "./review-fixture";
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

test("host context preparation and envelope share the original request and budget", () => {
  const value = buildReviewRequest(input(), () => 20_000, { requestId: "host-request-1", startedAt: 0 });
  expect(value.request.request_id).toBe("host-request-1");
  expect(value.request.deadline).toBe(30_000);
  expect(() => buildReviewRequest(input(), () => 30_001, { requestId: "host-request-2", startedAt: 0 }))
    .toThrow("REVIEW_BUDGET_EXCEEDED");
  expect(() => buildReviewRequest(input(), () => 0, { requestId: "host-request-3", startedAt: 1 }))
    .toThrow("REVIEW_CONTEXT_INVALID");
});

test("primary gets 25 seconds and tiny only the remaining five", async () => {
  const clock = new FakeClock(); let tiny = 0; let primarySignal!: AbortSignal;
  const pending = reviewWithFallback(prepared({}, clock.now), {
    reviewOnce: async (request) => { request.onInferenceStarted(); primarySignal = request.signal; return new Promise<never>(() => {}); },
    tinyInstalledOnly: async (request) => { request.onInferenceStarted(); tiny++; expect(request.deadline).toBe(30_000); return new Promise<never>(() => {}); },
  }, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 }, clock);
  await flush(); clock.advance(25_000); await flush();
  expect(primarySignal.aborted).toBe(true); expect(tiny).toBe(1);
  clock.advance(5_000); const result = await pending;
  expect(result.outcome).toBe("ask"); expect(result.primaryState).toBe("timeout");
  expect(result.fallbackState).toBe("timeout"); expect(clock.timers.size).toBe(0);
});
test("preprocessing time reduces total remaining budget", async () => {
  const clock = new FakeClock(); const value = prepared({}, clock.now); clock.advance(20_000);
  let tiny = 0;
  const pending = reviewWithFallback(value, {
    reviewOnce: async (request) => { request.onInferenceStarted(); expect(request.deadline).toBe(30_000); return new Promise<never>(() => {}); },
    tinyInstalledOnly: async () => { tiny++; return { status: "unavailable" }; },
  }, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 }, clock);
  await flush(); clock.advance(10_000);
  expect((await pending).outcome).toBe("ask"); expect(tiny).toBe(0);
});
test("cancellation and stale generation discard late results without fallback", async () => {
  for (const change of ["cancel", "generation"] as const) {
    const clock = new FakeClock(); const abort = new AbortController(); let generation = 0; let tiny = 0;
    let finish!: (value: ReturnType<typeof askReply>) => void;
    const pending = reviewWithFallback(prepared({ signal: abort.signal }), {
      reviewOnce: async (request) => { request.onInferenceStarted(); return new Promise((resolve) => { finish = resolve; }); },
      tinyInstalledOnly: async () => { tiny++; return { status: "unavailable" }; },
    }, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => generation, signal: abort.signal }, clock);
    await flush(); if (change === "cancel") abort.abort(); else generation++;
    finish(askReply()); const result = await pending;
    expect(result.outcome).toBe("ask"); expect(result.primaryState).toBe("cancelled"); expect(tiny).toBe(0);
  }
});
