import { configurationPolicyDigest } from "../src/config.ts";
import { test, assert } from "./recorded-test.ts";
import { routeRequirements, type RuntimeModel } from "../src/adapters/route-requirements.ts";
import { modelBindingDigest } from "../src/adapters/capabilities.ts";
import { TaskService, type ManagedJob } from "../src/orchestration/service.ts";
import { Store, type Owner } from "../src/store/database.ts";
import { digest } from "../src/contracts/primitives.ts";
import { configured } from "./fixtures/config.ts";
import { isolatedDirectory } from "./helpers.ts";
import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
const model: RuntimeModel = { api: "openai-completions", provider: "fixture-provider", id: "fixture-model", baseUrl: "http://fixture.invalid/v1", reasoning: true, contextWindow: 32000, maxTokens: 1000,
  thinkingLevelMap: { high: "high" }, input: ["text"] };
const profile = { tools: ["read", "grep", "find", "ls"], requiredCapabilities: ["readonly"], thinking: "high", timeoutMs: 1000, toolTimeoutMs: 1000, maxModelTurns: 10, minimumContextTokens: 16000 };
test("[U RTB-002] thinking is checked against each route's own mapping and advertised context", () => {
  assert.equal(routeRequirements(model, profile, "reviewer", false).eligible, true);
  for (const change of [{ reasoning: false }, { thinkingLevelMap: { high: null } }, { api: "uncertified-api" }, { contextWindow: 8000 }, { contextWindow: NaN }]) {
    assert.equal(routeRequirements({ ...model, ...change }, profile, "reviewer", false).eligible, false);
  }
  const mapped = routeRequirements({ ...model, thinkingLevelMap: { high: "provider-high-value" } }, profile, "reviewer", false);
  assert.equal(mapped.thinking?.mapped, "provider-high-value"); assert.notEqual(mapped.bindingDigest, modelBindingDigest(model));
  assert.equal(routeRequirements(model, { ...profile, thinking: "max" }, "reviewer", false).eligible, false);
  assert.equal(routeRequirements({ ...model, thinkingLevelMap: { max: "maximum" } }, { ...profile, thinking: "max" }, "reviewer", false).eligible, true);
  assert.equal(routeRequirements(model, { ...profile, tools: [...profile.tools, "bash"] }, "reviewer", false).eligible, false);
});
test("[U EXE-002] an admitted job seals model semantics; later catalog changes invalidate dispatch but prices do not", async t => {
  const root = isolatedDirectory(t), store = new Store(root), config = configured(); let actual: RuntimeModel = structuredClone(model);
  const context = { cwd: root, modelRegistry: { find: () => actual }, sessionManager: { getBranch: () => [], getSessionId: () => "session", getSessionFile: () => root + "/session.jsonl", getHeader: () => null } } as unknown as ExtensionContext;
  const service = new TaskService({ appendEntry() {} } as unknown as ExtensionAPI, store, config, context);
  const internal = service as unknown as { owner: Owner; admitted: (id: string, epoch: number) => void; wake: () => void };
  internal.wake = () => {}; t.after(async () => { await service.dispose(); store.close(); });
  store.put("managed-jobs", "job", { id: "job", workflow: "fix", workScope: internal.owner.scopeId, status: "RUNNING", sourceCwd: root, controlEpoch: 1, policyDigest: configurationPolicyDigest(config), modelBindings: { primary: modelBindingDigest(model) } });
  internal.admitted("job", 1);
  const changes = [{ reasoning: false }, { contextWindow: 40000 }, { maxTokens: 2000 }, { thinkingLevelMap: { high: null } }, { headers: { "x-routing": "changed" } },
    { compat: { supportsReasoningEffort: false } }, { samplingParams: { temperature: 0.9 } }, { input: ["image"] }, { api: "another-api" }, { baseUrl: "http://other.invalid" }];
  for (const change of changes) {
    actual = { ...model, ...change }; assert.throws(() => internal.admitted("job", 1), { code: "MODEL_BINDINGS_CHANGED_REQUIRES_RECONCILIATION" });
    actual = structuredClone(model); internal.admitted("job", 1);
  }
  actual = { ...model, cost: { input: 999 } } as RuntimeModel; assert.doesNotThrow(() => internal.admitted("job", 1));
  // Avoid exercising unrelated workflow teardown with this deliberately minimal job fixture.
  store.put("managed-jobs", "job", { ...store.get<ManagedJob>("managed-jobs", "job"), status: "COMPLETED" });
});
