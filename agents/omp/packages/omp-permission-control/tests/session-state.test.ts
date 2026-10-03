import { expect, test } from "bun:test";
import { PermissionLedger } from "../controller";

test("new and restored sessions start from profile defaults", () => {
  const old = new PermissionLedger("old", "smart");
  old.setMode("manual");
  expect(old.snapshot().mode_source).toBe("session-command");
  for (const sessionId of ["new", "restored"]) {
    const state = new PermissionLedger(sessionId, "smart").snapshot();
    expect(state.active_mode).toBe("smart");
    expect(state.configured_mode).toBe("smart");
    expect(state.mode_source).toBe("profile-default");
    expect(state.generation).toBe(0);
    expect(state.pending_permit_id).toBeUndefined();
  }
});
test("read-only state snapshots are frozen and cannot configure health", () => {
  const ledger = new PermissionLedger("session", "smart");
  const state = ledger.snapshot();
  expect(state.bridge_health).toBe("unavailable");
  expect(state.fallback_state).toBe("disabled");
  expect(Object.isFrozen(state)).toBe(true);
  expect(Object.isFrozen(state.coverage)).toBe(true);
  expect(ledger.explain()).toEqual({ state: "no-decision-in-session" });
  expect(ledger.snapshot()).toEqual(state);
  expect(ledger.generation).toBe(0);
});
test("incomplete or unknown host fields cannot make smart health appear valid", () => {
  const ledger = new PermissionLedger("session", "smart");
  for (const value of [{ ...ledger.hostState(), native_protection: {} },
    { ...ledger.hostState(), unexpected: "SECRET_SENTINEL" }]) {
    expect(() => ledger.setHostState(value as any)).toThrow("PERMISSION_REQUEST_INVALID");
  }
  expect(ledger.generation).toBe(0);
  expect(JSON.stringify(ledger.snapshot())).not.toContain("SECRET_SENTINEL");
});
test("a health or reviewer change invalidates outstanding processing immediately", async () => {
  const ledger = new PermissionLedger("session", "smart");
  let began!: () => void;
  const started = new Promise<void>((resolve) => { began = resolve; });
  const pending = ledger.runSerialized(async () => { began(); return await new Promise<never>(() => {}); });
  const rejected = pending.catch((error) => error);
  await started;
  const before = performance.now();
  ledger.setHostState({ ...ledger.hostState(), bridge_health: "degraded" });
  expect(await rejected).toMatchObject({ message: "PERMISSION_REQUEST_INVALID" });
  expect(performance.now() - before).toBeLessThan(1000);
  expect(ledger.snapshot().bridge_health).toBe("degraded");
  const generation = ledger.generation;
  ledger.setHostState(ledger.hostState());
  expect(ledger.generation).toBe(generation);
});
test("status reads during review never extend or restart it", async () => {
  const ledger = new PermissionLedger("session", "manual");
  let began!: () => void;
  const started = new Promise<void>((resolve) => { began = resolve; });
  const pending = ledger.runSerialized(async () => { began(); return await new Promise<never>(() => {}); });
  const rejected = pending.catch((error) => error);
  await started;
  const generation = ledger.generation;
  expect(ledger.snapshot().pending).toBe("reviewing");
  for (let i = 0; i < 10; i++) { ledger.snapshot(); ledger.explain(); }
  expect(ledger.generation).toBe(generation);
  ledger.setMode("manual");
  expect(await rejected).toMatchObject({ message: "PERMISSION_REQUEST_INVALID" });
  expect(ledger.generation).toBe(generation + 1);
});
