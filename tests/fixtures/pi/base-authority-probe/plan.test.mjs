import assert from "node:assert/strict";
import { test } from "node:test";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { syntheticCredentialReference } from "../../../../scripts/pi-probe-base-authority.mjs";
import { createOfficialModelConfiguration } from "../../../../agents/pi/runtime/official-models.ts";
test("own synthetic model reference passes original configuration checker and wrong macro fails", () => {
 const root = fs.mkdtempSync(path.join(os.tmpdir(), "own-authority-model-")); fs.chmodSync(root, 0o700);
 try {
  const config = { api: "synthetic-base", baseUrl: "https://synthetic.invalid/unused", models: [{ id: "main", input: ["text"], contextWindow: 16384, maxTokens: 2048 }] };
  const binding = { logical_id: "synthetic", auth_kind: "api-key", owner: "pi-environment" };
  const manifest = { provider_bindings: { "synthetic-base": binding }, allowed_models: [{ provider: "synthetic-base", model: "main" }], model_configuration: { schema_version: 1, providers: { "synthetic-base": { ...binding, credential_ref: "secret:SYNTHETIC", config } } } };
  fs.mkdirSync(path.join(root, "pi-home"), { mode: 0o700 }); const file = path.join(root, "pi-home/models.json");
  fs.writeFileSync(file, JSON.stringify({ providers: { "synthetic-base": { ...config, apiKey: syntheticCredentialReference() } } }), { mode: 0o600 });
  createOfficialModelConfiguration({ manifest, path: file }).checkFile();
  fs.writeFileSync(file, JSON.stringify({ providers: { "synthetic-base": { ...config, apiKey: "$AGENTCFG_PI_CREDENTIAL_SYNTHETIC" } } }));
  assert.throws(() => createOfficialModelConfiguration({ manifest, path: file }), /pi-model-config-stale/);
 } finally { fs.rmSync(root, { recursive: true, force: true }); }
});
