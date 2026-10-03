import { expect, test } from "bun:test";
import { PermissionLedger } from "../controller";
import permissionControl, { handleSessionCommand, PERMISSION_USAGE, type PermissionRegistration } from "../index";

test("entry registers only a review candidate and genuine-command handler with the host bridge", () => {
  const registrations: PermissionRegistration[] = [];
  permissionControl({ registerPermissionController: value => { registrations.push(value); } });
  expect(registrations).toHaveLength(1);
  expect(Object.keys(registrations[0]).sort()).toEqual(["bridgeAbi", "command", "pluginId", "review"]);
  expect(registrations[0].pluginId).toBe("omp-permission-control");
  expect(registrations[0].bridgeAbi).toBe("permission-control/v1");
  expect(Object.isFrozen(registrations[0])).toBe(true);
  expect(registrations[0]).not.toHaveProperty("createPermit");
  expect(registrations[0]).not.toHaveProperty("execute");
});
test("entry fails closed when the official host lacks the registration ABI", () => {
  expect(() => permissionControl({} as any)).toThrow("PERMISSION_CONTROLLER_UNAVAILABLE");
});

test("only four exact subcommands are accepted and invalid input leaves state alone", () => {
  const ledger = new PermissionLedger("session", "smart");
  const before = ledger.snapshot();
  for (const command of ["", "Smart", "status extra", "manual now", "guard", "approval", "s", "status\nmanual"]) {
    expect(handleSessionCommand(command, ledger)).toBe(PERMISSION_USAGE);
    expect(ledger.snapshot()).toEqual(before);
  }
  expect(PERMISSION_USAGE.split("\n")).toEqual([
    "/permission-control smart", "/permission-control manual", "/permission-control status", "/permission-control explain",
  ]);
});
test("manual, status and explain use fixed outputs without model calls or generation drift", () => {
  const ledger = new PermissionLedger("session", "smart");
  expect(handleSessionCommand("manual", ledger)).toContain("not-called-in-manual");
  const before = ledger.snapshot();
  const status = JSON.parse(handleSessionCommand("status", ledger));
  for (const key of ["configuredMode", "activeMode", "modeSource", "reviewer", "reviewerSource",
    "reviewerHealth", "fallback", "fallbackLimit", "fallbackHealth", "coverage", "executionLimits", "nativeProtection",
    "childAndHeadless", "bridge", "policyVersion", "pending", "unverified"]) expect(status).toHaveProperty(key);
  expect(status.fallbackLimit).toBe("ask-or-deny-only; installed-only; never-allow");
  expect(status.childAndHeadless).toBe("native-prompt-or-block; no-smart-permit-inheritance; no-yolo");
  expect(JSON.parse(handleSessionCommand("explain", ledger))).toEqual({ state: "no-decision-in-session" });
  expect(ledger.snapshot()).toEqual(before);
});
test("unhealthy smart command invalidates and reports unavailable instead of success", () => {
  const ledger = new PermissionLedger("session", "manual");
  const result = JSON.parse(handleSessionCommand("smart", ledger));
  expect(result.state).toBe("smart-unavailable");
  expect(ledger.mode).toBe("manual");
  expect(ledger.generation).toBe(1);
});
test("healthy remote fallback can enable smart while primary is unavailable", () => {
  const ledger = new PermissionLedger("session", "manual");
  ledger.setHostState({ ...ledger.hostState(), reviewer: "unavailable", remote_fallback: "remote/reviewer",
    remote_fallback_state: "ready", bridge_health: "healthy", identity_verified: true,
    policy_version: "a".repeat(64), native_protection: { bashPrompt: true, denyPreserved: true,
      commandPromptPreserved: true, criticalSafetyPreserved: true, taskPrompt: true, evalPrompt: true, noYolo: true } });
  const result = JSON.parse(handleSessionCommand("smart", ledger));
  expect(result.state).toBe("mode-updated"); expect(ledger.mode).toBe("smart");
  const status = JSON.parse(handleSessionCommand("status", ledger));
  expect(status.remoteFallback).toBe("remote/reviewer");
  expect(status.remoteFallbackHealth).toBe("ready");
});
test("unsupported primary identity remains visible while a ready remote enables smart", () => {
  const ledger = new PermissionLedger("session", "manual");
  ledger.setHostState({ ...ledger.hostState(), reviewer: "cursor-agent/cursor-composer-1.5",
    reviewer_state: "unsupported", remote_fallback: "remote/reviewer", remote_fallback_state: "ready",
    bridge_health: "healthy", identity_verified: true, policy_version: "a".repeat(64),
    native_protection: { bashPrompt: true, denyPreserved: true, commandPromptPreserved: true,
      criticalSafetyPreserved: true, taskPrompt: true, evalPrompt: true, noYolo: true } });
  expect(JSON.parse(handleSessionCommand("smart", ledger)).state).toBe("mode-updated");
  const status = JSON.parse(handleSessionCommand("status", ledger));
  expect(status.reviewer).toBe("cursor-agent/cursor-composer-1.5");
  expect(status.reviewerHealth).toBe("unsupported");
  expect(status.remoteFallbackHealth).toBe("ready");
});
