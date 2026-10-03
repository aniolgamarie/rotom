import { expect, test } from "bun:test";
import { reviewWithFallback, type ModelReply } from "../reviewer";
import { synthesizeReview } from "../policy";
import { askReply, FakeClock, input, prepared } from "./review-fixture";

const remote = { provider: "remote", model: "reviewer", api: "openai-completions" };
const context = { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 };
const fullReply = (value: ReturnType<typeof prepared>, decision: "allow" | "deny", scopeDigest?: string) => {
  const effect = value.request.effects[0]; const message = value.request.authorization_evidence[0];
  return { status: "ok" as const, outputTokens: 96, toolCalls: [], text: JSON.stringify(decision === "allow"
    ? { decision, risk: "low", authorization: "sufficient", effects: [effect.effectId], unknowns: [],
        reasonCode: "LOW_RISK_AUTHORIZED", evidence: { userMessageIds: [message.messageId], bindings: [{
          effectId: effect.effectId, userMessageId: message.messageId, startByte: 0,
          endByte: message.utf8ByteLength, scopeDigest: scopeDigest ?? effect.scopeDigest }] } }
    : { decision, risk: "high", authorization: "insufficient", effects: [effect.effectId], unknowns: [],
        reasonCode: "MATERIAL_RISK", evidence: { userMessageIds: [], bindings: [] } }) };
};

test.each(["timeout", "service-failure", "invalid-output", "unsupported", "unavailable"] as const)(
  "primary %s invokes one remote reviewer with the complete bounded envelope",
  async (failure) => {
    const value = prepared({ remote_fallback: remote });
    let remoteCalls = 0;
    const result = await reviewWithFallback(value, {
      reviewOnce: async request => {
        if (failure !== "unsupported" && failure !== "unavailable") request.onInferenceStarted();
        return failure === "invalid-output"
          ? { status: "ok", text: "bad", outputTokens: 1, toolCalls: [] }
          : { status: failure } as ModelReply;
      },
      remoteReviewOnce: async request => {
        request.onInferenceStarted(); remoteCalls++;
        expect(request.model).toEqual(remote);
        expect(request.input).toBe(value.envelope);
        expect(request.maxOutputTokens).toBe(512);
        expect(request.maxOutputBytes).toBe(4096);
        return askReply();
      },
      tinyInstalledOnly: async () => { throw new Error("tiny must not run after valid remote"); },
    }, context, new FakeClock());
    expect(remoteCalls).toBe(1);
    expect(result).toMatchObject({ outcome: "ask", remoteState: "valid", remoteCalls: 1,
      actualModel: "remote/reviewer", modelSource: "remote-fallback" });
    expect(result.remote?.decision).toBe("ask");
  },
);

test.each(["ask", "deny"] as const)("valid primary %s never invokes remote", async decision => {
  let remoteCalls = 0;
  const reply = askReply();
  const primary = { ...reply, text: reply.text.replace('"ask"', `"${decision}"`) };
  const result = await reviewWithFallback(prepared({ remote_fallback: remote }), {
    reviewOnce: async request => { request.onInferenceStarted(); return primary; },
    remoteReviewOnce: async () => { remoteCalls++; return askReply(); },
    tinyInstalledOnly: async () => ({ status: "unavailable" }),
  }, context, new FakeClock());
  expect(remoteCalls).toBe(0);
  expect(result.remoteCalls).toBe(0);
});

test("valid primary allow is terminal before later mechanical policy checks", async () => {
  const value = prepared({ remote_fallback: remote });
  const effect = value.request.effects[0];
  const message = value.request.authorization_evidence[0];
  let remoteCalls = 0;
  const result = await reviewWithFallback(value, {
    reviewOnce: async request => {
      request.onInferenceStarted();
      return { status: "ok", outputTokens: 80, toolCalls: [], text: JSON.stringify({ decision: "allow", risk: "low",
        authorization: "sufficient", effects: [effect.effectId], unknowns: [], reasonCode: "LOW_RISK_AUTHORIZED",
        evidence: { userMessageIds: [message.messageId], bindings: [{ effectId: effect.effectId,
          userMessageId: message.messageId, startByte: 0, endByte: message.utf8ByteLength,
          scopeDigest: effect.scopeDigest }] } }) };
    },
    remoteReviewOnce: async () => { remoteCalls++; return askReply(); },
    tinyInstalledOnly: async () => ({ status: "unavailable" }),
  }, context, new FakeClock());
  expect(result.outcome).toBe("allow"); expect(result.primaryState).toBe("valid"); expect(remoteCalls).toBe(0);
  const policy = synthesizeReview({ mode: "smart", effects: value.request.effects, analysisComplete: true,
    nativeConstraints: value.request.native_constraints, hardProhibited: false,
    restrictionFacts: { generation: 0, currentGeneration: 0, contextComplete: true,
      uninterpretedUserText: true, structuredRestrictions: [] },
    mechanical: { coverageVerified: true, healthVerified: true, contextComplete: true,
      redactionComplete: true, targetProofVerified: true, generationVerified: true } }, result.primary, false);
  expect(policy.outcome).toBe("ask"); expect(remoteCalls).toBe(0);
});

test("same primary and remote model is skipped and unsupported may use the full automatic budget", async () => {
  const clock = new FakeClock(); let remoteCalls = 0;
  const same = { provider: "fixture", model: "cheap", api: "openai-completions" };
  const skipped = await reviewWithFallback(prepared({ remote_fallback: same, fallback: undefined }), {
    reviewOnce: async () => ({ status: "unsupported" }),
    remoteReviewOnce: async () => { remoteCalls++; return askReply(); },
    tinyInstalledOnly: async () => ({ status: "unavailable" }),
  }, context, clock);
  expect(remoteCalls).toBe(0); expect(skipped.remoteState).toBe("not-called");

  const value = prepared({ remote_fallback: remote, fallback: undefined }, clock.now);
  const result = await reviewWithFallback(value, {
    reviewOnce: async () => ({ status: "unsupported" }),
    remoteReviewOnce: async request => {
      request.onInferenceStarted(); expect(request.deadline).toBe(30_000); return askReply();
    },
    tinyInstalledOnly: async () => ({ status: "unavailable" }),
  }, context, clock);
  expect(result.remoteState).toBe("valid");

  const withTinyReserve = await reviewWithFallback(prepared({ remote_fallback: remote }, clock.now), {
    reviewOnce: async () => ({ status: "unsupported" }),
    remoteReviewOnce: async request => {
      request.onInferenceStarted(); expect(request.deadline).toBe(25_000); return askReply();
    },
    tinyInstalledOnly: async () => ({ status: "unavailable" }),
  }, context, clock);
  expect(withTinyReserve.primaryCalls).toBe(0);
  expect(withTinyReserve.remoteCalls).toBe(1);
});

test("remote failure reaches tiny only after the 12.5 plus 12.5 second automatic budget", async () => {
  const clock = new FakeClock(); let tinyCalls = 0; let primarySignal!: AbortSignal; let remoteSignal!: AbortSignal;
  const pending = reviewWithFallback(prepared({ remote_fallback: remote }, clock.now), {
    reviewOnce: async request => {
      request.onInferenceStarted(); primarySignal = request.signal;
      expect(request.deadline).toBe(12_500); return new Promise<never>(() => {});
    },
    remoteReviewOnce: async request => {
      request.onInferenceStarted(); remoteSignal = request.signal;
      expect(request.deadline).toBe(25_000); return new Promise<never>(() => {});
    },
    tinyInstalledOnly: async request => {
      request.onInferenceStarted(); tinyCalls++;
      expect(request.deadline).toBe(30_000);
      return { status: "ok", text: '{"decision":"deny","reasonCode":"FALLBACK_MATERIAL_RISK"}',
        outputTokens: 16, toolCalls: [] };
    },
  }, context, clock);
  for (let i = 0; i < 8; i++) await Promise.resolve();
  clock.advance(12_500); for (let i = 0; i < 8; i++) await Promise.resolve();
  expect(primarySignal.aborted).toBe(true);
  clock.advance(12_500); for (let i = 0; i < 8; i++) await Promise.resolve();
  expect(remoteSignal.aborted).toBe(true);
  const result = await pending;
  expect(tinyCalls).toBe(1);
  expect(result).toMatchObject({ outcome: "deny", primaryState: "timeout", remoteState: "timeout",
    fallbackState: "valid", primaryCalls: 1, remoteCalls: 1, tinyCalls: 1,
    actualModel: "local/lfm2.5-230m", modelSource: "fallback" });
});

test("an ok primary reply without an inference start is unavailable and reaches remote", async () => {
  let remoteCalls = 0;
  const result = await reviewWithFallback(prepared({ remote_fallback: remote }), {
    reviewOnce: async () => askReply(),
    remoteReviewOnce: async request => { request.onInferenceStarted(); remoteCalls++; return askReply(); },
    tinyInstalledOnly: async () => ({ status: "unavailable" }),
  }, context, new FakeClock());
  expect(result.primaryState).toBe("unavailable"); expect(result.primaryCalls).toBe(0);
  expect(result.remoteState).toBe("valid"); expect(remoteCalls).toBe(1);
});

test("primary exhaustion at the automatic boundary skips remote but still uses reserved tiny time", async () => {
  const clock = new FakeClock(); const value = prepared({ remote_fallback: remote }, clock.now);
  clock.advance(20_000);
  let remoteCalls = 0; let tinyCalls = 0;
  const pending = reviewWithFallback(value, {
    reviewOnce: async request => { request.onInferenceStarted(); expect(request.deadline).toBe(25_000);
      return new Promise<never>(() => {}); },
    remoteReviewOnce: async () => { remoteCalls++; return askReply(); },
    tinyInstalledOnly: async request => { request.onInferenceStarted(); tinyCalls++; expect(request.deadline).toBe(30_000);
      return { status: "unavailable" }; },
  }, context, clock);
  for (let i = 0; i < 8; i++) await Promise.resolve();
  clock.advance(5_000); for (let i = 0; i < 8; i++) await Promise.resolve();
  const result = await pending;
  expect(result.primaryState).toBe("timeout"); expect(result.remoteState).toBe("timeout");
  expect(result.remoteCalls).toBe(0); expect(remoteCalls).toBe(0); expect(tinyCalls).toBe(1);
});

test("configured explicit primary remains primary when the session model differs", () => {
  const built = input({ reviewer: { provider: "explicit", model: "fixed" }, reviewer_source: "explicit-profile",
    remote_fallback: remote });
  expect(built.reviewer).toEqual({ provider: "explicit", model: "fixed" });
  expect(built.remote_fallback).toEqual(remote);
});

test("a fully bound remote allow is the final model result and can pass mechanical policy", async () => {
  const value = prepared({ remote_fallback: remote }); let tinyCalls = 0;
  const result = await reviewWithFallback(value, {
    reviewOnce: async request => { request.onInferenceStarted(); return { status: "service-failure" }; },
    remoteReviewOnce: async request => { request.onInferenceStarted(); return fullReply(value, "allow"); },
    tinyInstalledOnly: async () => { tinyCalls++; return { status: "unavailable" }; },
  }, context, new FakeClock());
  expect(result).toMatchObject({ outcome: "allow", remoteState: "valid", remoteCalls: 1,
    modelSource: "remote-fallback", actualModel: "remote/reviewer" });
  expect(tinyCalls).toBe(0);
  const policy = synthesizeReview({ mode: "smart", effects: value.request.effects, analysisComplete: true,
    nativeConstraints: value.request.native_constraints, hardProhibited: false,
    restrictionFacts: { generation: 0, currentGeneration: 0, contextComplete: true,
      uninterpretedUserText: true, structuredRestrictions: [] },
    mechanical: { coverageVerified: true, healthVerified: true, contextComplete: true,
      redactionComplete: true, targetProofVerified: true, generationVerified: true } }, result.remote, true,
    "remote-fallback");
  expect(policy.outcome).toBe("allow"); expect(policy.source).toBe("remote-fallback");
});

test("valid remote deny terminates before tiny while invalid remote evidence fails closed", async () => {
  const deniedValue = prepared({ remote_fallback: remote }); let tinyCalls = 0;
  const denied = await reviewWithFallback(deniedValue, {
    reviewOnce: async request => { request.onInferenceStarted(); return { status: "service-failure" }; },
    remoteReviewOnce: async request => { request.onInferenceStarted(); return fullReply(deniedValue, "deny"); },
    tinyInstalledOnly: async () => { tinyCalls++; return { status: "unavailable" }; },
  }, context, new FakeClock());
  expect(denied.outcome).toBe("deny"); expect(denied.remoteState).toBe("valid"); expect(tinyCalls).toBe(0);

  const invalidValue = prepared({ remote_fallback: remote });
  const invalid = await reviewWithFallback(invalidValue, {
    reviewOnce: async request => { request.onInferenceStarted(); return { status: "service-failure" }; },
    remoteReviewOnce: async request => { request.onInferenceStarted(); return fullReply(invalidValue, "allow", "f".repeat(64)); },
    tinyInstalledOnly: async request => { request.onInferenceStarted(); tinyCalls++;
      return { status: "unavailable" }; },
  }, context, new FakeClock());
  expect(invalid.outcome).toBe("ask"); expect(invalid.remoteState).toBe("invalid-output");
  expect(invalid.fallbackState).toBe("unavailable"); expect(tinyCalls).toBe(1);
});

test("cancelling a remote review discards its late result and never reaches tiny", async () => {
  const abort = new AbortController(); let finish!: (reply: ReturnType<typeof askReply>) => void; let tinyCalls = 0;
  const value = prepared({ remote_fallback: remote, signal: abort.signal });
  const pending = reviewWithFallback(value, {
    reviewOnce: async request => { request.onInferenceStarted(); return { status: "service-failure" }; },
    remoteReviewOnce: async request => { request.onInferenceStarted();
      return new Promise(resolve => { finish = resolve; }); },
    tinyInstalledOnly: async () => { tinyCalls++; return { status: "unavailable" }; },
  }, { ...context, signal: abort.signal }, new FakeClock());
  for (let i = 0; i < 8; i++) await Promise.resolve();
  abort.abort(); finish(askReply());
  const result = await pending;
  expect(result.outcome).toBe("ask"); expect(result.remoteState).toBe("cancelled"); expect(tinyCalls).toBe(0);
});
