import { describe, expect, test } from "bun:test";
import { PermissionLedger, type ExecutionBinding } from "../controller";

const hash = "a".repeat(64);
function binding(overrides: Partial<ExecutionBinding> = {}): ExecutionBinding {
  return {
    request_id: crypto.randomUUID(), session_id: "session", generation: 0,
    prepared_execution_id: Object.freeze({}), execution_ref: Object.freeze({}),
    execution_digest: hash, operation_digest: hash, argv_digest: hash, cwd: "/project",
    shell_digest: hash, backend: "native", target_digest: hash, authorization_digest: hash,
    mode: "smart", policy_version: hash, reviewer_identity: "provider/model",
    plugin_digest: hash, runtime_identity: "runtime", health_digest: hash,
    ...overrides,
  };
}
const allow = { outcome: "allow", source: "low-risk-rule", reason_code: "DETERMINISTIC_LOW_RISK" } as const;
const ask = { outcome: "ask", source: "native-protection", reason_code: "USER_CONFIRMATION_REQUIRED" } as const;
function granted(ledger = new PermissionLedger("session", "smart"), b = binding(), signal?: AbortSignal) {
  const request = ledger.beginRequest(b, signal);
  const decision = ledger.recordDecision(request, allow);
  const permit = ledger.createPermit(request, decision);
  return { ledger, b, request, decision, permit };
}

describe("host-owned one-use execution permits", () => {
  test("consume invokes backend synchronously once and exposes immutable state", () => {
    const { ledger, b, permit } = granted();
    let starts = 0;
    const result = ledger.consume(permit, b, () => { starts++; return Promise.resolve("done"); });
    expect(starts).toBe(1);
    expect(permit.state).toBe("consumed");
    expect(Object.isFrozen(permit)).toBe(true);
    expect(() => ledger.consume(permit, b, () => starts++)).toThrow();
    expect(starts).toBe(1);
    return expect(result).resolves.toBe("done");
  });
  test("copied objects and another session cannot consume a permit", () => {
    const { ledger, b, permit } = granted();
    expect(() => ledger.consume({ ...permit }, b, () => {})).toThrow();
    expect(() => new PermissionLedger("other", "smart").consume(permit, b, () => {})).toThrow();
    expect(permit.state).toBe("pending");
  });
  for (const [key, value] of Object.entries(binding({ request_id: "changed", session_id: "other", generation: 1,
    execution_digest: "b".repeat(64), operation_digest: "b".repeat(64), argv_digest: "b".repeat(64),
    cwd: "/other", shell_digest: "b".repeat(64), backend: "pty", target_digest: "b".repeat(64),
    authorization_digest: "b".repeat(64), mode: "manual", policy_version: "b".repeat(64),
    reviewer_identity: "other/model", plugin_digest: "b".repeat(64), runtime_identity: "other",
    health_digest: "b".repeat(64) }))) {
    test(`changing ${key} invalidates before execution`, () => {
      const { ledger, b, permit } = granted();
      let starts = 0;
      expect(() => ledger.consume(permit, { ...b, [key]: value }, () => starts++)).toThrow();
      expect(starts).toBe(0);
      expect(permit.state).toBe("invalidated");
    });
  }
  test("original caller cancellation invalidates immediately", () => {
    const abort = new AbortController();
    const { ledger, b, permit } = granted(undefined, undefined, abort.signal);
    abort.abort();
    expect(permit.state).toBe("invalidated");
    expect(() => ledger.consume(permit, b, () => {})).toThrow();
  });
  test("mode changes and repeated same-mode commands invalidate without queue waits", () => {
    const { ledger, b, request, permit } = granted();
    ledger.setMode("smart");
    expect(ledger.generation).toBe(1);
    expect(request.signal.aborted).toBe(true);
    expect(permit.state).toBe("invalidated");
    expect(() => ledger.recordDecision(request, allow)).toThrow();
    expect(() => ledger.consume(permit, b, () => {})).toThrow();
  });
  test("ask requires a live host UI response on the exact ask chain", () => {
    const ledger = new PermissionLedger("session", "smart");
    const b = binding();
    const request = ledger.beginRequest(b);
    const decision = ledger.recordDecision(request, ask);
    expect(() => ledger.createPermit(request, decision)).toThrow();
    const human = ledger.recordHuman(request, decision, "allow", b);
    expect(() => ledger.createPermit(request, decision, { ...human })).toThrow();
    const permit = ledger.createPermit(request, decision, human);
    expect(permit.grant_source).toBe("human");
    expect(permit.ask_decision_id).toBe(decision.decision_id);
    expect(permit.human_decision_id).toBe(human.human_decision_id);
    expect(ledger.consume(permit, b, () => "started")).toBe("started");
  });
  test("late human response and denial cannot grant", () => {
    const ledger = new PermissionLedger("session", "smart");
    const b = binding();
    const request = ledger.beginRequest(b);
    const decision = ledger.recordDecision(request, ask);
    const human = ledger.recordHuman(request, decision, "deny", b);
    expect(() => ledger.createPermit(request, decision, human)).toThrow();
    ledger.invalidate("authorization-changed");
    expect(() => ledger.recordHuman(request, decision, "allow", b)).toThrow();
  });
  test("one pending permit and one final decision per request", () => {
    const { ledger, b, request, decision, permit } = granted();
    expect(() => ledger.recordDecision(request, allow)).toThrow();
    expect(() => ledger.createPermit(request, decision)).toThrow();
    const second = ledger.beginRequest(binding());
    const otherDecision = ledger.recordDecision(second, allow);
    expect(() => ledger.createPermit(second, decision)).toThrow();
    expect(() => ledger.createPermit(second, otherDecision)).toThrow();
    ledger.consume(permit, b, () => {});
    expect(ledger.createPermit(second, otherDecision).state).toBe("pending");
  });
  test("backend failure never restores a consumed permit", () => {
    const { ledger, b, permit } = granted();
    expect(() => ledger.consume(permit, b, () => { throw Error("backend"); })).toThrow("backend");
    expect(permit.state).toBe("consumed");
  });
  test("a changed human binding cannot later be restored to revive approval", () => {
    const ledger = new PermissionLedger("session", "smart");
    const b = binding();
    const request = ledger.beginRequest(b);
    const decision = ledger.recordDecision(request, ask);
    expect(() => ledger.recordHuman(request, decision, "allow", { ...b, cwd: "/other" })).toThrow();
    expect(() => ledger.recordHuman(request, decision, "allow", b)).toThrow();
    expect(request.signal.aborted).toBe(true);
  });
  test("deny and unhealthy or fallback candidates never create an automatic permit", () => {
    const ledger = new PermissionLedger("session", "smart");
    const denied = ledger.beginRequest(binding());
    const decision = ledger.recordDecision(denied, { ...ask, outcome: "deny" });
    expect(() => ledger.createPermit(denied, decision)).toThrow();
    for (const details of [{ health_result: "degraded" }, { fallback_result: "ask" }] as const) {
      const request = ledger.beginRequest(binding());
      expect(() => ledger.recordDecision(request, allow, details)).toThrow();
    }
  });
});

describe("review through start serialization", () => {
  test("queue serializes review but releases at start, not command completion", async () => {
    const ledger = new PermissionLedger("session", "smart");
    const events: string[] = [];
    let releaseReview!: () => void;
    let complete!: () => void;
    const review = new Promise<void>((resolve) => { releaseReview = resolve; });
    const completion = new Promise<void>((resolve) => { complete = resolve; });
    const first = ledger.runSerialized(async () => {
      events.push("review-1"); await review; events.push("start-1"); return { completion };
    });
    const second = ledger.runSerialized(async () => {
      events.push("review-2"); return { completion: Promise.resolve() };
    });
    await Promise.resolve(); await Promise.resolve();
    expect(events).toEqual(["review-1"]);
    releaseReview(); await second;
    expect(events).toEqual(["review-1", "start-1", "review-2"]);
    complete(); await first;
  });
  test("mode cancellation releases a hung reviewer and rejects late result", async () => {
    const ledger = new PermissionLedger("session", "smart");
    let started!: () => void;
    const running = new Promise<void>((resolve) => { started = resolve; });
    const first = ledger.runSerialized(async (signal) => {
      started(); await new Promise<void>((resolve) => signal.addEventListener("abort", () => resolve()));
      return { completion: Promise.resolve("late") };
    });
    const rejected = first.catch((error) => error);
    await running; ledger.setMode("manual");
    expect((await rejected).message).toBe("PERMISSION_REQUEST_INVALID");
    expect(await ledger.runSerialized(async () => ({ completion: Promise.resolve("next") }))).toBe("next");
  });
});

test("failed serialized staging revokes pending permit and permits the next request", async () => {
  const ledger = new PermissionLedger("session", "smart");
  let first: ReturnType<typeof granted> | undefined;
  await expect(ledger.runSerialized(async signal => {
    first = granted(ledger, binding(), signal);
    throw new Error("STAGE_FAILED");
  })).rejects.toThrow("STAGE_FAILED");
  expect(first!.request.signal.aborted).toBe(true);
  expect(first!.permit.state).toBe("invalidated");
  expect(ledger.generation).toBe(0);
  let successfulSignal: AbortSignal | undefined;
  expect(await ledger.runSerialized(async signal => {
    successfulSignal = signal;
    const next = granted(ledger, binding(), signal);
    return { completion: ledger.consume(next.permit, next.b, () => Promise.resolve("started")) };
  })).toBe("started");
  expect(successfulSignal!.aborted).toBe(false);
});
