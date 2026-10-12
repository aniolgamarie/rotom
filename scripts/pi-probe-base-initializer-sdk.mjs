// 仅准备不会加载SDK；native入口须未来单独授权及冻结计划，本文不启动子进程。
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash } from "node:crypto";
import { isDeepStrictEqual, types } from "node:util";
// 此helper只在native入口按固定fixture位置import；默认plan函数不读取candidate。

export const CASES = Object.freeze(["api-key-default", "native-oauth-source", "native-auth-format-denied"]);
const ENV = Object.freeze({ HOME: "/work/home", PWD: "/work", PATH: "/work/empty-bin", PI_PROBE_NATIVE: "1", PI_OFFLINE: "1", OTEL_SDK_DISABLED: "true", TMPDIR: "/work/tmp", XDG_CONFIG_HOME: "/work/config", XDG_DATA_HOME: "/work/data", XDG_CACHE_HOME: "/work/cache", XDG_STATE_HOME: "/work/state", LC_ALL: "C.UTF-8", ["AGENTCFG_PI_CREDENTIAL_" + createHash("sha256").update("synthetic").digest("hex").slice(0, 16).toUpperCase()]: "own-synthetic-initializer-key" });
const deny = () => { throw new Error("BASE_INITIALIZER_SDK_PROBE_PLAN_INVALID"); };
const closed = (value, keys) => {
  if (!value || types.isProxy(value) || Object.getPrototypeOf(value) !== Object.prototype || Reflect.ownKeys(value).some(key => typeof key !== "string")
      || Object.keys(value).sort().join() !== [...keys].sort().join()
      || Object.values(Object.getOwnPropertyDescriptors(value)).some(item => !item.enumerable || !Object.hasOwn(item, "value"))) deny();
};
const exact = (left, right) => { if (!isDeepStrictEqual(left, right)) deny(); };
const absolute = value => typeof value === "string" && path.isAbsolute(value) && path.normalize(value) === value && !/[\p{Cc}\p{Cf}]/u.test(value) && value !== "/";
export function validatePlan(plan, { requireFrozen = false } = {}) {
  closed(plan, ["schema_version", "probe_id", "state", "versions", "source_root", "candidate_root", "node_root", "work_root", "cases", "provider", "sentinels", "source_pins", "candidate_pins", "candidate_inventory", "limits"]);
  if (plan.schema_version !== 1 || plan.probe_id !== "base-initializer-sdk-1.0.1" || !["requires-final-freeze", "frozen"].includes(plan.state) || requireFrozen && plan.state !== "frozen") deny();
  closed(plan.versions, ["pi", "pi_ai", "node"]); exact(plan.versions, { pi: "1.0.1", pi_ai: "1.0.2", node: "24.14.0" });
  exact([plan.source_root, plan.candidate_root, plan.node_root, plan.work_root], ["/source", "/candidate", "/node", "/work"]); exact(plan.cases, CASES);
  closed(plan.provider, ["id", "model", "api", "base_url", "native_provider", "native_model"]);
  exact(plan.provider, {"id": "agentcfg-synthetic-init", "model": "selected", "api": "openai-completions", "base_url": "https://synthetic.invalid/unused", "native_provider": "openai-codex", "native_model": "gpt-5.3-codex-spark"});
  exact(plan.sentinels, ["OWN_FAILED_TASK_SENTINEL", "OWN_UNFINISHED_TASK_SENTINEL"]);
  closed(plan.limits, ["case_timeout_ms", "total_timeout_ms", "max_result_bytes"]); exact(plan.limits, { case_timeout_ms: 5000, total_timeout_ms: 60000, max_result_bytes: 65536 });
  for (const [kind, prefix] of [["source_pins", "agents/pi/runtime/"], ["candidate_pins", "node_modules/@earendil-works/"]]) {
    const pins = plan[kind];
    if (!pins || types.isProxy(pins) || Object.getPrototypeOf(pins) !== Object.prototype || Object.keys(pins).length > 512
      || Reflect.ownKeys(pins).some(key => typeof key !== "string")
      || Object.values(Object.getOwnPropertyDescriptors(pins)).some(item => !item.enumerable || !Object.hasOwn(item, "value"))) deny();
    for (const [name, sha] of Object.entries(pins)) if (!name.startsWith(prefix) || path.normalize(name) !== name || name.split("/").includes("..") || !/^[a-f0-9]{64}$/.test(sha)) deny();
  }
  if (plan.candidate_inventory !== null) {
    closed(plan.candidate_inventory, ["fixture", "sha256", "entries", "file_count", "bytes"]);
    const receipt = plan.candidate_inventory;
    if (receipt.fixture !== "candidate-inventory.json" || !/^[a-f0-9]{64}$/.test(receipt.sha256)
      || !Number.isSafeInteger(receipt.entries) || receipt.entries < 1 || receipt.entries > 65536
      || !Number.isSafeInteger(receipt.file_count) || receipt.file_count < 1 || receipt.file_count > receipt.entries
      || !Number.isSafeInteger(receipt.bytes) || receipt.bytes < 0 || receipt.bytes > 512 * 1024 * 1024) deny();
  }
  if (plan.state === "frozen") {
    if (plan.candidate_inventory === null) deny();
    for (const name of ["official-model-scope.ts", "official-model-runtime.ts", "official-session.ts"]) if (!plan.source_pins["agents/pi/runtime/" + name]) deny();
    for (const pkg of ["pi-coding-agent", "pi-ai"]) if (!plan.candidate_pins[`node_modules/@earendil-works/${pkg}/package.json`]) deny();
  }
  return structuredClone(plan);
}
export function buildInvocation({ plan, sourceRoot, candidateRoot, nodeRoot, workRoot, worker, fixtureRoot }) {
  validatePlan(plan, { requireFrozen: true });
  const mounts = [sourceRoot, candidateRoot, nodeRoot, workRoot, worker, fixtureRoot];
  if (mounts.some(value => !absolute(value)) || new Set(mounts).size !== mounts.length || !/^\/(tmp|data)\//.test(workRoot)
      || [sourceRoot, candidateRoot, nodeRoot, fixtureRoot].some(root => workRoot === root || workRoot.startsWith(root + "/"))) deny();
  // 当前系统bwrap不支持--clearenv；外层必须使用返回的空env，guest再核对完整ENV。
  const argv = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session", "--cap-drop", "ALL",
    "--ro-bind", "/usr", "/usr", "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
    "--ro-bind", sourceRoot, "/source", "--ro-bind", candidateRoot, "/candidate", "--ro-bind", nodeRoot, "/node",
    "--dir", "/probe", "--ro-bind", worker, "/probe/worker.mjs", "--ro-bind", fixtureRoot, "/probe/fixture",
    "--symlink", "/candidate/node_modules", "/probe/node_modules", "--bind", workRoot, "/work"];
  for (const [name, value] of Object.entries(ENV)) argv.push("--setenv", name, value);
  argv.push("--chdir", "/work", "/node/bin/node", "--max-old-space-size=512", "/probe/worker.mjs", "--native-base-initializer-sdk-probe");
  return { argv, env: {} };
}
const hash = bytes => createHash("sha256").update(bytes).digest("hex");
function verifyPins(root, pins) {
  for (const [name, digest] of Object.entries(pins)) {
    const file = path.join(root, name), stat = fs.lstatSync(file);
    assert(stat.isFile() && !stat.isSymbolicLink() && fs.realpathSync(file) === file && stat.size <= 4 * 1024 * 1024);
    assert.equal(hash(fs.readFileSync(file)), digest);
  }
}
// 自有外层冻结准备：只读核全树并返回计划，不写文件、不spawn、不importSDK。
export async function prepareFrozenPlan({ plan, sourceRoot, candidateRoot, receiptPath, receiptSha256 }) {
  const fixed = validatePlan(plan);
  if (![sourceRoot, candidateRoot, receiptPath].every(absolute) || fs.realpathSync(sourceRoot) !== sourceRoot) deny();
  const helper = new URL("../tests/fixtures/pi/base-initializer-sdk-probe/candidate-inventory.mjs", import.meta.url);
  const { verifyCandidateInventory } = await import(helper.href);
  const measured = verifyCandidateInventory({ candidateRoot, receiptPath, receiptSha256 });
  fixed.candidate_inventory = { fixture: "candidate-inventory.json", ...measured };
  fixed.source_pins = {};
  const runtime = path.join(sourceRoot, "agents/pi/runtime");
  for (const name of fs.readdirSync(runtime)) if (name.endsWith(".ts")) {
    const file = path.join(runtime, name), info = fs.lstatSync(file);
    if (!info.isFile() || info.isSymbolicLink() || fs.realpathSync(file) !== file || info.size > 4 * 1024 * 1024) deny();
    fixed.source_pins["agents/pi/runtime/" + name] = hash(fs.readFileSync(file));
  }
  fixed.candidate_pins = {};
  for (const pkg of ["pi-coding-agent", "pi-ai"]) {
    const name = `node_modules/@earendil-works/${pkg}/package.json`;
    fixed.candidate_pins[name] = hash(fs.readFileSync(path.join(candidateRoot, name)));
  }
  fixed.state = "frozen"; return validatePlan(fixed, { requireFrozen: true });
}
const bounded = async (value, ms = 5000) => {
  let timer; try { return await Promise.race([value, new Promise((_resolve, reject) => { timer = setTimeout(() => reject(Error("BASE_INITIALIZER_SDK_PROBE_TIMEOUT")), ms); })]); }
  finally { clearTimeout(timer); }
};
async function runNative() {
  assert.equal(process.argv.length, 3); assert.equal(process.argv[2], "--native-base-initializer-sdk-probe");
  exact(Object.keys(process.env).sort(), Object.keys(ENV).sort());
  for (const [name, value] of Object.entries(ENV)) assert.equal(process.env[name], value);
  assert.equal(process.platform, "linux"); assert.equal(process.version, "v24.14.0");
  const plan = validatePlan(JSON.parse(fs.readFileSync("/probe/fixture/plan.json", "utf8")), { requireFrozen: true });
  verifyPins("/source", plan.source_pins); verifyPins("/candidate", plan.candidate_pins);
  const { verifyCandidateInventory } = await import("./fixture/candidate-inventory.mjs");
  exact(verifyCandidateInventory({ candidateRoot: "/candidate", receiptPath: "/probe/fixture/candidate-inventory.json",
    receiptSha256: plan.candidate_inventory.sha256, receiptRootName: "pi-base-1e4f9e6dc96d1083ed6b201deef2356cea8dcf743839db887f703f7ae386a76f" }),
  { sha256: plan.candidate_inventory.sha256, entries: plan.candidate_inventory.entries, file_count: plan.candidate_inventory.file_count, bytes: plan.candidate_inventory.bytes });
  const sdk = await import("@earendil-works/pi-coding-agent"), ai = await import("@earendil-works/pi-ai");
  assert.equal(sdk.VERSION, "1.0.1");
  const { createOfficialRuntimeInitializer } = await import(pathToFileURL("/source/agents/pi/runtime/official-model-runtime.ts").href);
  const result = { schema_version: 1, probe_id: plan.probe_id, status: "failed", cases: [] };
  let stage = "setup";
  function fixture(name, native = false, credential) {
    const instanceRoot = "/work/" + name, directory = instanceRoot + "/pi-home";
    fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
    const p = plan.provider, route = native ? p.native_provider : p.id;
    const binding = { logical_id: native ? "codex" : "synthetic", auth_kind: native ? "oauth" : "api-key", owner: native ? "pi-native" : "pi-environment" };
    const config = native ? null : { api: p.api, baseUrl: p.base_url,
      models: [{ id: p.model, input: ["text"], contextWindow: 8192, maxTokens: 512 }] };
    const manifest = { profile_id: "pi-base", provider_bindings: { [route]: binding },
      model_configuration: { schema_version: 1, providers: { [route]: { ...binding, credential_ref: native ? null : "secret:SYNTHETIC", config } } },
      allowed_models: [{ provider: route, model: native ? p.native_model : p.model }] };
    const nativeConfig = { providers: native ? {} : { [route]: { ...config, apiKey: "$AGENTCFG_PI_CREDENTIAL_" + hash("synthetic").slice(0, 16).toUpperCase() } } };
    fs.writeFileSync(directory + "/models.json", JSON.stringify(nativeConfig), { mode: 0o600, flag: "wx" });
    if (credential !== undefined) fs.writeFileSync(directory + "/auth.json", JSON.stringify(credential), { mode: 0o600, flag: "wx" });
    return { instanceRoot, directory, manifest, route, modelId: native ? p.native_model : p.model };
  }
  const configFd = directory => fs.readdirSync("/proc/self/fd").some(fd => {
    try { const file = "/proc/self/fd/" + fd, name = fs.readlinkSync(file), stat = fs.statSync(file);
      return name.startsWith(directory + "/.agentcfg-model-config-") && name.endsWith(" (deleted)")
        && stat.isFile() && stat.nlink === 0 && stat.uid === process.getuid() && (stat.mode & 0o777) === 0o600;
    } catch { return false; }
  });
  async function scenario(id, body) {
    try { const observations = await bounded(body()); result.cases.push({ case_id: id, outcome: "observed", observations }); }
    catch (error) { result.cases.push({ case_id: id, outcome: "failed", observations: { stage,
      failure_class: /^(pi-runtime-|pi-model-|pi-main-model-|MODEL_SCOPE_)[A-Za-z0-9_-]{1,80}$/.test(error?.message ?? "") ? error.message : error?.code === "ERR_ASSERTION" ? "assertion" : "public-sdk-initializer-failed" } }); throw Error("BASE_INITIALIZER_SDK_PROBE_CASE_FAILED"); }
  }
  try {
    await scenario("api-key-default", async () => {
      const sentinel = { "unselected-native": { type: "oauth", access: "synthetic-unselected-access", refresh: "synthetic-unselected-refresh", expires: Date.now() + 3600000 } };
      const f = fixture("api-key", false, sentinel), authPath = f.directory + "/auth.json", before = fs.readFileSync(authPath);
      fs.utimesSync(authPath, 1, 1); const atime = fs.statSync(authPath).atimeMs;
      stage = "api-key-constructor";
      const initialize = createOfficialRuntimeInitializer({ sdk, ai, manifest: f.manifest, instanceRoot: f.instanceRoot });
      stage = "api-key-initialize"; const handle = await initialize();
      assert.equal(await initialize(), handle); assert(handle.modelRuntime instanceof sdk.ModelRuntime);
      stage = "api-key-check"; await handle.check();
      assert(configFd(f.directory));
      assert.deepEqual(handle.modelRuntime.getModels(f.route).map(model => model.id), [f.modelId]);
      assert.deepEqual(await handle.modelRuntime.listCredentials(), []);
      stage = "api-key-get-auth";
      const auth = await handle.modelRuntime.getAuth(handle.modelRuntime.getModel(f.route, f.modelId));
      assert.equal(auth.auth.apiKey, process.env["AGENTCFG_PI_CREDENTIAL_" + hash("synthetic").slice(0, 16).toUpperCase()]);
      await handle.check();
      assert.equal(fs.statSync(authPath).atimeMs, atime); assert.deepEqual(fs.readFileSync(authPath), before);
      return { original_sdk_create: true, initializer_cached: true, runtime_instanceof: true, held_unlinked_private_config: true,
        scoped_model_count: 1, credential_metadata_count: 0, selected_env_key_consumed: true, auth_sentinel_atime_and_bytes_unchanged: true,
        model_send_calls: 0, account_refresh_calls: 0 };
    });
    await scenario("native-oauth-source", async () => {
      const missing = fixture("native-missing", true);
      stage = "native-missing-initialize";
      const noAccount = await createOfficialRuntimeInitializer({ sdk, ai, manifest: missing.manifest, instanceRoot: missing.instanceRoot })();
      await noAccount.check(); assert.deepEqual(await noAccount.modelRuntime.listCredentials(), []);
      const missingModelPresent = noAccount.modelRuntime.getModel(missing.route, missing.modelId) !== undefined;
      const f = fixture("native-configured", true, { [missing.route]: { type: "oauth", access: "synthetic-native-access", refresh: "synthetic-native-refresh", expires: Date.now() + 3600000 } });
      const authPath = f.directory + "/auth.json", before = fs.readFileSync(authPath);
      stage = "native-configured-initialize";
      const handle = await createOfficialRuntimeInitializer({ sdk, ai, manifest: f.manifest, instanceRoot: f.instanceRoot })();
      stage = "native-configured-check"; await handle.check();
      assert(handle.modelRuntime instanceof sdk.ModelRuntime); assert(configFd(f.directory));
      assert.deepEqual(await handle.modelRuntime.listCredentials(), [{ providerId: f.route, type: "oauth" }]);
      assert(handle.modelRuntime.getModel(f.route, f.modelId));
      assert.deepEqual(fs.readFileSync(authPath), before);
      assert.deepEqual(fs.readdirSync(f.directory).sort(), ["auth.json", "models.json"]);
      return { original_sdk_create: true, runtime_instanceof: true, selected_builtin_provider: f.route, selected_builtin_model: f.modelId,
        missing_account_metadata_count: 0, missing_model_present: missingModelPresent, original_auth_path_metadata: true,
        auth_bytes_unchanged: true, no_credential_copy_file: true, model_send_calls: 0, account_refresh_requested: false,
        get_auth_not_called: true, real_oauth_qualified: false };
    });
    await scenario("native-auth-format-denied", async () => {
      const f = fixture("native-malformed", true, { [plan.provider.native_provider]: { type: "oauth", access: "synthetic-incomplete" } });
      const before = fs.readFileSync(f.directory + "/auth.json"); stage = "native-format-constructor";
      assert.throws(() => createOfficialRuntimeInitializer({ sdk, ai, manifest: f.manifest, instanceRoot: f.instanceRoot }),
        error => error.message === "pi-runtime-auth-format" && error.exitCode === 2);
      assert.deepEqual(fs.readFileSync(f.directory + "/auth.json"), before);
      assert(!configFd(f.directory));
      return { fixed_error: "pi-runtime-auth-format", exit_code: 2, rejected_before_sdk_create: true, auth_bytes_unchanged: true };
    });
    result.status = "observed";
  } finally {
    for (const id of CASES) if (!result.cases.some(item => item.case_id === id)) result.cases.push({ case_id: id, outcome: "not-run", observations: {} });
    const bytes = JSON.stringify(result) + "\n"; assert(Buffer.byteLength(bytes) <= plan.limits.max_result_bytes);
    fs.writeFileSync("/work/probe-result.json", bytes, { mode: 0o600, flag: "wx" }); process.stdout.write(bytes);
  }
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv[2] !== "--native-base-initializer-sdk-probe") { process.stderr.write("BASE_INITIALIZER_SDK_PROBE_REQUIRES_AUTHORIZATION_AND_FROZEN_PLAN\n"); process.exitCode = 2; }
  else {
    const deadline = setTimeout(() => { process.stderr.write("BASE_INITIALIZER_SDK_PROBE_TIMEOUT\n"); process.exit(2); }, 60000);
    try { await runNative(); } catch { process.stderr.write("BASE_INITIALIZER_SDK_PROBE_FAILED\n"); process.exitCode = 2; } finally { clearTimeout(deadline); }
  }
}
