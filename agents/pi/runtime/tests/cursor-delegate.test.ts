import assert from "node:assert/strict";
import { test } from "node:test";
import { runPiDelegate } from "../delegate-pi.ts";

test("Cursor readonly delegation fails before SDK creation or transport when public audit API is absent", async () => {
  let sessions = 0;
  const model = { provider: "cursor", id: "fixture", api: "cursor-native" };
  await assert.rejects(runPiDelegate({ sdk: { async createAgentSession() { sessions++; } },
    input: { request: { backend: "pi", execution_boundary: "agentcfg-tools", execution_mode: "delegate-readonly", mode: "review",
      requested_model: { provider_id: "cursor", model_id: "fixture" }, grant_generation: 1 },
      grant: { allowed_tools: [], expires_at: "2026-10-16T00:00:00Z" } },
    modelRuntime: { getModel: () => model }, tools: [], supervisor: { async call() { return { valid: true, grant_generation: 1 }; } },
    now: () => Date.parse("2026-10-15T00:00:00Z") }), /DELEGATE_MODEL_UNSUPPORTED/);
  assert.equal(sessions, 0);
});
