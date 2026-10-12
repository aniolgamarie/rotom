// 只在显式授权的新candidate只读namespace执行；默认import不加载SDK。
import assert from "node:assert/strict";
import fs from "node:fs";
import { createHash } from "node:crypto";
export function validatePlan(plan) {
  assert.deepEqual(Object.keys(plan).sort(), ["lock_identity", "package_path", "runtime_identity", "runtime_files", "slice_identity"].sort());
  for (const key of ["lock_identity", "runtime_identity", "slice_identity"]) assert(/^[a-f0-9]{64}$/.test(plan[key]));
  assert(/^pi-base-[a-f0-9]{64}\/package\.json$/.test(plan.package_path));
  assert(Array.isArray(plan.runtime_files) && plan.runtime_files.length === 120);
  for (const row of plan.runtime_files) assert(/^[a-f0-9]{64}$/.test(row.digest) && !row.path.includes("..") && !row.path.startsWith("/"));
  return structuredClone(plan);
}
if (process.argv[2] === "--native-rebind") {
  try {
    const plan = validatePlan(JSON.parse(fs.readFileSync("/probe/plan.json", "utf8")));
    const profile = JSON.parse(fs.readFileSync("/candidate/runtime/profile.json", "utf8"));
    for (const key of ["lock_identity", "runtime_identity", "slice_identity", "package_path"]) assert.equal(profile[key], plan[key]);
    assert.equal(profile.profile_id, "pi-base");
    for (const row of plan.runtime_files) assert.equal(createHash("sha256").update(fs.readFileSync("/candidate/" + row.path)).digest("hex"), row.digest);
    const prefix = "/candidate/" + plan.package_path.slice(0, -"package.json".length);
    const sdk = await import(prefix + "node_modules/@earendil-works/pi-coding-agent/dist/index.js");
    const ai = await import(prefix + "node_modules/@earendil-works/pi-ai/dist/index.js");
    const { createOfficialRuntimeInitializer } = await import("/candidate/runtime/official-model-runtime.mjs");
    assert.equal(sdk.VERSION, "1.0.1");
    const instanceRoot = "/work/instance", directory = instanceRoot + "/pi-home";
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const variable = "AGENTCFG_PI_CREDENTIAL_" + createHash("sha256").update("synthetic").digest("hex").slice(0, 16).toUpperCase();
    const binding = { logical_id: "synthetic", auth_kind: "api-key", owner: "pi-environment" }, route = "agentcfg-synthetic-init";
    const config = { api: "openai-completions", baseUrl: "https://synthetic.invalid/unused", models: [{ id: "selected", input: ["text"], contextWindow: 8192, maxTokens: 512 }] };
    const manifest = { profile_id: "pi-base", provider_bindings: { [route]: binding }, model_configuration: { schema_version: 1, providers: { [route]: { ...binding, credential_ref: "secret:SYNTHETIC", config } } }, allowed_models: [{ provider: route, model: "selected" }] };
    fs.writeFileSync(directory + "/models.json", JSON.stringify({ providers: { [route]: { ...config, apiKey: "$" + variable } } }), { mode: 0o600, flag: "wx" });
    const initialize = createOfficialRuntimeInitializer({ sdk, ai, manifest, instanceRoot }), runtime = await initialize();
    assert(runtime.modelRuntime instanceof sdk.ModelRuntime); await runtime.check();
    const auth = await runtime.modelRuntime.getAuth(runtime.modelRuntime.getModel(route, "selected"));
    assert.equal(auth.auth.apiKey, process.env[variable]); await runtime.check();
    assert.equal(await initialize(), runtime);
    process.stdout.write(JSON.stringify({ status: "observed", compiled_default_initializer: true, original_sdk_create: true,
      generated_profile_identity_match: true, runtime_files_verified: 120, runtime_identity: profile.runtime_identity,
      selected_synthetic_env_consumed: true, model_send_requested: false, activated: false }) + "\n");
  } catch { process.stderr.write("CANDIDATE_INITIALIZER_REBIND_FAILED\n"); process.exitCode = 2; }
}
