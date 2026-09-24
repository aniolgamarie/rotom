import { test, assert, evidence } from "./recorded-test.ts";
import { configured } from "./fixtures/config.ts";
import { configurationPolicy } from "../src/config.ts";
import { digest } from "../src/contracts/primitives.ts";
import { recoveryEligibility } from "../src/reliability/eligibility.ts";
import type { InteractiveSnapshot } from "../src/reliability/recovery.ts";

function baseline() {
  const config = configured(), route = config.routes.primary;
  const snapshot: InteractiveSnapshot = { sessionId: "session", leafId: "after-tool", provider: route.provider,
    model: route.model, idle: true, pendingMessages: false, terminationKnown: true, certified: true, blockedReasons: [] };
  const record = { policyDigest: digest([configurationPolicy(config), null]), routeId: "primary", sessionId: "session", leafId: "after-tool" };
  return { config, snapshot, record };
}

test("[U T19] native retry compaction and queued follow-up each independently deny outer recovery", () => {
  for (const patch of [{ idle: false }, { pendingMessages: true }, { blockedReasons: ["compaction"] }]) {
    const f = baseline(), before = structuredClone(f);
    assert.equal(recoveryEligibility(f.config, f.record, f.snapshot), null);
    assert.equal(recoveryEligibility(f.config, f.record, { ...f.snapshot, ...patch }),
      "blockedReasons" in patch ? "execution_or_mutator_unknown" : "not_settled");
    assert.deepEqual(f, before);
    assert.equal(recoveryEligibility(f.config, f.record, f.snapshot), null);
  }
});

test("[U T37] old session leaf and runtime identities cannot resume after a lifecycle change", () => {
  const f = baseline(), before = structuredClone(f);
  for (const patch of [{ sessionId: "new-session" }, { leafId: "fork-leaf" }])
    assert.equal(recoveryEligibility(f.config, f.record, { ...f.snapshot, ...patch }), "session_or_leaf_changed");
  assert.equal(recoveryEligibility(f.config, f.record, { ...f.snapshot, runtimeFingerprint: "reloaded-adapter" }), "policy_changed");
  assert.equal(recoveryEligibility(f.config, f.record, f.snapshot), null);
  assert.deepEqual(f, before);
});

test("[U T41] an unknown writer blocks admission even after all native messages have settled", () => {
  const f = baseline();
  for (const patch of [{ terminationKnown: false }, { blockedReasons: ["external-writer"] }]) {
    const snapshot = { ...f.snapshot, ...patch }, before = structuredClone(snapshot);
    assert.equal(recoveryEligibility(f.config, f.record, snapshot), "execution_or_mutator_unknown");
    assert.deepEqual(snapshot, before);
  }
  assert.equal(recoveryEligibility(f.config, f.record, f.snapshot), null);
});

test("[U CFG-013] explicit resume eligibility cannot remove an unchanged blocker or alter its original record", () => {
  for (const id of ["CFG-013"]) evidence(id, () => {
    const f = baseline();
    for (const patch of [{ certified: false }, { terminationKnown: false }, { pendingMessages: true },
      { blockedReasons: ["external-writer"] }, { leafId: "different-leaf" }]) {
      const snapshot = { ...f.snapshot, ...patch }, before = structuredClone({ record: f.record, snapshot });
      const first = recoveryEligibility(f.config, f.record, snapshot);
      assert.notEqual(first, null);
      for (let attempt = 0; attempt < 3; attempt++) assert.equal(recoveryEligibility(f.config, f.record, snapshot), first);
      assert.deepEqual({ record: f.record, snapshot }, before);
      assert.equal(recoveryEligibility(f.config, f.record, f.snapshot), null);
    }
  });
});

test("[U VAL-016] recovery admission has a legal witness and a separate counterexample for every rejection predicate", () => {
  const cases: Array<{ reason: string; change: (f: ReturnType<typeof baseline>) => void; rebind?: boolean }> = [
    { reason: "interactive_recovery_disabled", change: f => { f.config.enabled = false; } },
    { reason: "interactive_recovery_disabled", change: f => { f.config.features.interactiveRecovery = false; } },
    { reason: "policy_changed", change: f => { f.record.policyDigest = "old-policy"; } },
    { reason: "route_not_allowed", change: f => { f.record.routeId = "missing"; } },
    { reason: "route_not_allowed", change: f => { f.config.allowedRoutes = []; }, rebind: true },
    { reason: "request_gate_not_certified", change: f => { f.config.routes.primary.protected = true; }, rebind: true },
    { reason: "session_or_leaf_changed", change: f => { f.snapshot.sessionId = "other-session"; } },
    { reason: "session_or_leaf_changed", change: f => { f.snapshot.leafId = "other-leaf"; } },
    { reason: "route_changed", change: f => { f.snapshot.provider = "other-provider"; } },
    { reason: "route_changed", change: f => { f.snapshot.model = "other-model"; } },
    { reason: "adapter_not_certified", change: f => { f.snapshot.certified = false; } },
    { reason: "execution_or_mutator_unknown", change: f => { f.snapshot.terminationKnown = false; } },
    { reason: "execution_or_mutator_unknown", change: f => { f.snapshot.blockedReasons = ["mutator"]; } },
    { reason: "not_settled", change: f => { f.snapshot.idle = false; } },
    { reason: "not_settled", change: f => { f.snapshot.pendingMessages = true; } },
  ];
  for (const row of cases) {
    const f = baseline(); assert.equal(recoveryEligibility(f.config, f.record, f.snapshot), null);
    row.change(f);
    if (row.rebind) f.record.policyDigest = digest([configurationPolicy(f.config), null]);
    const before = structuredClone(f);
    assert.equal(recoveryEligibility(f.config, f.record, f.snapshot), row.reason);
    assert.deepEqual(f, before);
  }
});
