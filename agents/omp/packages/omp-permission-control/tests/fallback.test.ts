import { expect, test } from "bun:test";
import { decodeTinyReview, reviewWithFallback } from "../reviewer";
import { askReply, FakeClock, prepared } from "./review-fixture";

test.each(["ask", "deny"] as const)("tiny accepts only bounded %s", (decision) => {
  expect(decodeTinyReview(JSON.stringify({ decision, reasonCode: "FALLBACK_HUMAN_REQUIRED" }), 20, []).decision).toBe(decision);
});
test.each([
  '{"decision":"allow","reasonCode":"FALLBACK_HUMAN_REQUIRED"}',
  '{"decision":"ask","reasonCode":"free text"}',
  '{"decision":"ask","decision":"deny","reasonCode":"FALLBACK_HUMAN_REQUIRED"}',
  '{"decision":"ask","reasonCode":"FALLBACK_HUMAN_REQUIRED","extra":1}',
  '```json\n{"decision":"ask","reasonCode":"FALLBACK_HUMAN_REQUIRED"}\n```',
])("tiny rejects invalid output without repair: %s", (raw) => {
  expect(() => decodeTinyReview(raw, 20, [])).toThrow("INVALID_REVIEW_OUTPUT");
});
test("tiny output size, tokens and tools are hard bounds", () => {
  const raw = '{"decision":"ask","reasonCode":"FALLBACK_HUMAN_REQUIRED"}';
  expect(() => decodeTinyReview(" ".repeat(1024) + raw, 20, [])).toThrow();
  expect(() => decodeTinyReview(raw, 129, [])).toThrow();
  expect(() => decodeTinyReview(raw, 20, [{}])).toThrow();
});
test.each(["service-failure", "invalid-output"])("%s can invoke exactly one installed-only tiny", async (failure) => {
  let calls = 0;
  const result = await reviewWithFallback(prepared(), {
    reviewOnce: async (request) => { request.onInferenceStarted(); return failure === "invalid-output" ? { ...askReply(), text: "bad" } : { status: "service-failure" }; },
    tinyInstalledOnly: async (request) => { request.onInferenceStarted(); calls++; expect(request.installedOnly).toBe(true);
      expect(request.maxOutputTokens).toBe(128); expect(request.maxOutputBytes).toBe(1024);
      expect(new TextEncoder().encode(request.input).length).toBeLessThanOrEqual(8192);
      return { status: "ok", text: '{"decision":"deny","reasonCode":"FALLBACK_MATERIAL_RISK"}', outputTokens: 20, toolCalls: [] }; },
  }, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 }, new FakeClock());
  expect(result.outcome).toBe("deny"); expect(calls).toBe(1); expect(result.tinyCalls).toBe(1);
});
test("tiny allow and unavailable stay ask; valid primary deny never falls back", async () => {
  for (const tinyStatus of ["ok", "unavailable"] as const) {
    const result = await reviewWithFallback(prepared(), {
      reviewOnce: async (request) => { request.onInferenceStarted(); return { status: "service-failure" }; },
      tinyInstalledOnly: async (request) => { if (tinyStatus === "ok") request.onInferenceStarted(); return tinyStatus === "ok" ? { status: "ok", text: '{"decision":"allow","reasonCode":"FALLBACK_HUMAN_REQUIRED"}', outputTokens: 20, toolCalls: [] } : { status: "unavailable" }; },
    }, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 }, new FakeClock());
    expect(result.outcome).toBe("ask"); expect(result.tinyCalls).toBe(tinyStatus === "ok" ? 1 : 0);
  }
  let tiny = 0;
  const denied = await reviewWithFallback(prepared(), {
    reviewOnce: async (request) => { request.onInferenceStarted(); return { ...askReply(), text: askReply().text.replace('"ask"', '"deny"') }; },
    tinyInstalledOnly: async () => { tiny++; return { status: "unavailable" }; },
  }, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 }, new FakeClock());
  expect(denied.outcome).toBe("deny"); expect(tiny).toBe(0);
});

test("host auth timeout may fall back without counting primary inference; host cancellation cannot", async () => {
  for (const status of ["timeout", "cancelled"] as const) {
    let tiny = 0;
    const result = await reviewWithFallback(prepared(), {
      reviewOnce: async () => ({ status }),
      tinyInstalledOnly: async (request) => {
        request.onInferenceStarted(); tiny++;
        return { status: "ok", text: '{"decision":"ask","reasonCode":"FALLBACK_HUMAN_REQUIRED"}', outputTokens: 20, toolCalls: [] };
      },
    }, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 }, new FakeClock());
    expect(result.outcome).toBe("ask");
    expect(result.primaryState).toBe(status); expect(result.primaryCalls).toBe(0);
    expect(result.actualModel).toBe(status === "timeout" ? "local/lfm2.5-230m" : "not-called");
    expect(result.modelSource).toBe(status === "timeout" ? "fallback" : "not-called");
    expect(result.tinyCalls).toBe(status === "timeout" ? 1 : 0);
    expect(tiny).toBe(status === "timeout" ? 1 : 0);
  }
});
