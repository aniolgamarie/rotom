import { expect, test } from "bun:test";
import { selectReviewer } from "../controller";
import { reviewWithFallback } from "../reviewer";
import { askReply, FakeClock, prepared } from "./review-fixture";

const small = { provider: "fixture", id: "cheap", api: "openai-completions" };
const main = { provider: "fixture", id: "main", api: "anthropic-messages" };
test("explicit selected reviewer and default session model resolve without credentials", () => {
  const explicit = selectReviewer({ provider: "fixture", model: "cheap" }, main, [small, main]);
  expect(explicit).toEqual({ state: "ready", source: "explicit-profile", model: small });
  expect(selectReviewer("session", main, [small, main])).toEqual({ state: "ready", source: "session-default", model: main });
  const tainted = { ...main, apiKey: "SECRET_SENTINEL" };
  const selected = selectReviewer("session", tainted, [tainted]);
  expect(JSON.stringify(selected)).not.toContain("SECRET_SENTINEL");
  expect(Object.isFrozen(selected.model)).toBe(true);
});
test("missing, ambiguous and unsupported reviewers fail closed", () => {
  expect(selectReviewer("session", undefined, [small]).state).toBe("unavailable");
  expect(selectReviewer({ provider: "fixture", model: "other" }, main, [small]).state).toBe("unavailable");
  expect(selectReviewer({ provider: "fixture", model: "cheap" }, main, [small, small]).state).toBe("unavailable");
  const unsupported = { ...small, api: "openai-responses" };
  expect(selectReviewer("session", unsupported, [unsupported]).state).toBe("unsupported");
});
test("one bounded primary call, no tools, no retries and no tiny on valid ask", async () => {
  const value = prepared(); const clock = new FakeClock(); let primary = 0; let tiny = 0;
  const services = {
    reviewOnce: async (request: any) => {
      request.onInferenceStarted(); primary++; expect(request.maxOutputTokens).toBe(512); expect(request.maxOutputBytes).toBe(4096);
      expect(request.model).toEqual({ provider: "fixture", model: "cheap" });
      expect(request).not.toHaveProperty("apiKey"); expect(request).not.toHaveProperty("tools"); return askReply();
    }, tinyInstalledOnly: async () => { tiny++; throw Error("must not run"); },
  };
  const result = await reviewWithFallback(value, services, { verifiedUserMessageIds: new Set(["user-1"]),
    currentGeneration: () => 0 }, clock);
  expect(result.outcome).toBe("ask"); expect(primary).toBe(1); expect(tiny).toBe(0);
  const again = await reviewWithFallback(value, services, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 }, clock);
  expect(again.primaryState).toBe("already-attempted"); expect(primary).toBe(1);
});
test("manual, cancellation and unsupported transport do not invoke tiny", async () => {
  for (const mode of ["manual", "smart"] as const) {
    let calls = 0; let tiny = 0;
    const result = await reviewWithFallback(prepared({ mode }), {
      reviewOnce: async () => { calls++; return { status: "unsupported" }; },
      tinyInstalledOnly: async () => { tiny++; return { status: "unavailable" }; },
    }, { verifiedUserMessageIds: new Set(["user-1"]), currentGeneration: () => 0 }, new FakeClock());
    expect(result.outcome).toBe("ask"); expect(tiny).toBe(0); expect(calls).toBe(mode === "manual" ? 0 : 1);
    expect(result.actualModel).toBe("not-called"); expect(result.primaryCalls).toBe(0);
  }
});
