import { configurationPolicyDigest } from "../src/config.ts";
import { test, assert, evidence } from "./recorded-test.ts";
import { join } from "node:path";
import { writeFileSync } from "node:fs";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { TaskService, type ManagedJob } from "../src/orchestration/service.ts";
import { Store, type Owner } from "../src/store/database.ts";
import { Scheduler } from "../src/orchestration/scheduler.ts";
import { digest } from "../src/contracts/primitives.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";

for (const condition of ["unavailable-network", "healthy", "network", "telemetry", "context", "thinking", "approval"] as const) {
  test(`[S ${condition === "unavailable-network" ? "RTB-006 T34" : condition === "thinking" ? "RTB-002" : "RTB-001"}] recovery candidate ${condition} retains hard admission and configured ordering`, async t => {
    const root = isolatedDirectory(t), config = configured(), store = new Store(root);
    config.features.crossProviderFailover = true;
    config.executionProfiles.worker = { tools: ["read", "grep", "find", "ls", "write", "edit"], requiredCapabilities: ["events"],
      thinking: "high", timeoutMs: 1000, maxModelTurns: 10, toolTimeoutMs: 1000, minimumContextTokens: 16000 };
    config.roles.worker = { route: "primary", profileRef: "worker" };
    for (const id of ["first", "second"]) {
      config.routes[id] = { ...config.routes.primary, model: id, protected: true, quotaGroup: id, network: id };
      config.network[id] = { type: "direct" }; config.quotaGroups[id] = config.quotaGroups.pool;
      config.allowedRoutes.push(id); config.projectRouteApprovals["*"].push(id);
    }
    config.recovery.chain = [{ id: "short", route: "primary", wait: { mode: "bounded", maxMs: 1 } },
      { id: "first", route: "first", wait: { mode: "bounded", maxMs: 1000 } },
      { id: "second", route: "second", wait: { mode: "bounded", maxMs: 1000 } },
      { id: "tail", route: "primary", wait: { mode: "forever" } }];
    if (condition === "unavailable-network") for (const id of ["local", "first", "second"]) config.network[id] = { type: "socks5h", endpoint: "socks5h://127.0.0.1:1" };
    if (condition === "network") config.network.first = { type: "socks5h", endpoint: "socks5h://127.0.0.1:1" };
    if (condition === "telemetry") {
      config.routes.first.telemetry = "quota";
      config.telemetryBindings.quota = { path: join(root, "quota.json"), accountBinding: config.routes.first.accountBinding,
        bucket: "first", source: "fixture", freshnessMs: 1000, minimumRemaining: 1 };
      writeFileSync(join(root, "quota.json"), JSON.stringify({ account: "different-account", bucket: "first", source: "fixture", observedAt: Date.now(), remaining: 100, resetAt: null }), { mode: 0o600 });
    }
    if (condition === "approval") config.projectRouteApprovals["*"] = ["primary", "second"];
    const model = { api: "openai-completions", provider: "fixture-provider", id: "fixture-model", baseUrl: "http://fixture.invalid", reasoning: true,
      contextWindow: 32000, maxTokens: 1000, thinkingLevelMap: { high: "high" } };
    const context = { cwd: root, modelRegistry: { find: (_provider: string, id: string) => ({ ...model, id,
      ...(id === "first" && condition === "context" ? { contextWindow: 8000 } : {}),
      ...(id === "first" && condition === "thinking" ? { thinkingLevelMap: { high: null } } : {}) }) },
      sessionManager: { getBranch: () => [], getSessionId: () => "session", getSessionFile: () => join(root, "session"), getHeader: () => null } } as unknown as ExtensionContext;
    const service = new TaskService({ appendEntry() {} } as unknown as ExtensionAPI, store, config, context);
    const internals = service as unknown as { owner: Owner; wake: () => void; advanceWait: (job: ManagedJob) => void };
    internals.wake = () => {}; t.after(async () => { await service.dispose(); store.close(); });
    const scheduler = new Scheduler(store, internals.owner), policyDigest = configurationPolicyDigest(config);
    scheduler.submit({ id: "job", workScope: internals.owner.scopeId, version: 1, objective: "bounded", workflow: "fix", required: ["implement"], optional: [],
      allowPartial: false, policyDigest, snapshot: "snapshot", maxSteps: 16, maxSemanticAttempts: 3 },
      [{ id: "implement", kind: "write", role: "worker", dependencies: [], allowedSkippedDependencies: [], optional: false, resources: [] }], 0, 0);
    const intent = scheduler.dispatch("job", "implement", "snapshot");
    scheduler.finish("job", "implement", { terminated: true, passed: false, artifactId: null }, 1); scheduler.pause("job");
    store.put("incidents", "pool", { id: "incident", status: "OPEN", failures: 1, notBefore: Date.now() + 60000 });
    const job = { id: "job", workScope: internals.owner.scopeId, workflow: "fix", sourceCwd: root, cwd: root, projectId: "repo", status: "WAITING_QUOTA",
      policyDigest, controlEpoch: 1, modelBindings: {}, jobLease: null, failures: [], checks: [], outputs: {}, verification: {}, receipt: null,
      semanticAttempts: 1, snapshot: "snapshot", recovery: { stepId: "implement", primaryRoute: "primary", incidentId: "incident", networkAttempts: 0,
        stage: { chainDigest: digest(config.recovery.chain), incidentId: "incident", stageId: "short", stageEnteredAt: 0, deadline: 1 } } } as unknown as ManagedJob;
    store.put("managed-jobs", "job", job); internals.advanceWait(job);
    if (condition === "unavailable-network") {
      const updated = service.get("job"), assessment = store.get<{rejected:Array<{id:string;reasons:string[]}>}>("route-assessments", "job")!;
      for (const id of ["RTB-006", "T34"]) evidence(id, () => {
        assert.equal(updated.status, "BLOCKED"); assert.equal(updated.routes?.implement, undefined);
        assert.equal(updated.reason, "no_authorized_final_route");
        assert.deepEqual(assessment.rejected.map(route=>route.id).sort(), ["first", "primary", "second"]);
        assert.ok(assessment.rejected.every(route=>route.reasons.includes("network_not_certified")));
        assert.equal(scheduler.job("job").dispatched, 1); assert.equal(scheduler.job("job").steps[0].status, "failed");
        assert.equal(store.intent(intent.id)!.status, "settled"); assert.equal(store.claims().length, 0);
        assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0);
        assert.equal(store.get<{failures:number}>("incidents", "pool")!.failures, 1); assert.equal(store.list("transport-incidents").length, 0);
        assert.equal(updated.recovery!.incidentId, "incident"); assert.equal(updated.semanticAttempts, 1);
        for (const network of Object.values(config.network)) assert.equal(network.type, "socks5h");
      });
      return;
    }
    const updated = service.get("job"); assert.equal(updated.routes?.implement, condition === "healthy" ? "first" : "second");
    assert.equal(updated.status, "RUNNING"); assert.equal(updated.recovery?.incidentId, "incident");
    assert.equal(scheduler.job("job").dispatched, 1); assert.equal(scheduler.job("job").steps[0].status, "pending");
    assert.equal(store.intent(intent.id)?.status, "settled");
    assert.equal(store.db.prepare("SELECT count(*) n FROM requests").get()!.n, 0);
    if (condition !== "healthy") {
      const assessment = store.get<{ rejected: Array<{ id: string; reasons: string[] }> }>("route-assessments", "job")!;
      const reasons: Record<string, string> = { network: "network_not_certified", telemetry: "quota_telemetry_not_eligible", context: "required_context_not_available", thinking: "thinking_level_not_supported", approval: "route_not_approved" };
      assert.ok(assessment.rejected.some(r => r.id === "first" && r.reasons.includes(reasons[condition])));
    }
  });
}
