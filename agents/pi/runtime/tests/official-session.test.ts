import assert from "node:assert/strict";
import { test } from "node:test";
import { createHash } from "node:crypto";
import { chmodSync, mkdtempSync, mkdirSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createOfficialRuntimeInitializer } from "../official-model-runtime.ts";
import { digest } from "../managed-types.ts";
import { createOfficialSessionFactory, resolveOfficialModel } from "../official-session.ts";
import { createOfficialFileRuntime } from "../official-file-runtime.ts";
import { createOfficialResources } from "../official-resources.ts";

function resourceRuntimeFixture() {
  const f = fileRuntimeFixture();
  Object.assign(f.options.installed, { schema_version: 2, profile_id: "pi-base", lock_identity: "b".repeat(64), slice_identity: "c".repeat(64) });
  return f;
}
const fixedProtocol = code => error => error.code === code && error.exitCode === 4;

test("runtime facade owns current resource observation rather than SDK arbitrary custom fields", async () => {
  const f = resourceRuntimeFixture(); let foreignCalls = 0;
  f.state.result = { resourceSnapshot() { foreignCalls++; throw Error("untrusted SDK custom field"); } };
  const runtime = await createOfficialFileRuntime(f.options, f.target);
  try {
    assert.equal(f.state.native.resourceSnapshot, undefined);
    const creates = f.state.creates, loads = f.state.loads;
    const [first, second] = await Promise.all([runtime.resourceSnapshot(), runtime.resourceSnapshot()]);
    assert.equal(first.profileId, "pi-base"); assert.equal(first.lockIdentity, "b".repeat(64));
    assert.equal(first.sliceIdentity, "c".repeat(64)); assert.equal(first.runtimeIdentity, "a".repeat(64));
    assert.deepEqual(first.observation.inlineExtensions, ["rotom-command-boundary"]);
    assert.deepEqual(first, second); assert.equal(Object.isFrozen(first), true);
    assert.equal(f.state.creates, creates); assert.equal(f.state.loads, loads); assert.equal(foreignCalls, 0);
    f.state.actualModel = { ...f.models[0], baseUrl: "https://changed.invalid" };
    await assert.rejects(runtime.resourceSnapshot(), /pi-session-model-changed/);
  } finally { await runtime.dispose(); }
  await assert.rejects(runtime.resourceSnapshot(), fixedProtocol("PI_SESSION_RETIRED"));
});

for (const method of ["newSession", "switchSession", "fork", "importFromJsonl"]) test(method + " hides transition observation and exposes only the next completed generation", async () => {
  const f = resourceRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  const firstSession = runtime.session; let release;
  f.state.transitionWait = new Promise(resolve => { release = resolve; });
  const transition = runtime[method]();
  try { await assert.rejects(runtime.resourceSnapshot(), fixedProtocol("PI_SESSION_TRANSITION_BUSY")); }
  finally { release(); await transition; }
  try {
    assert.notEqual(runtime.session, firstSession);
    assert.equal((await runtime.resourceSnapshot()).profileId, "pi-base");
  } finally { await runtime.dispose(); }
});

test("beforeInvalidate synchronously retires observation before user callback and failed replacement", async () => {
  const f = resourceRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  let callback;
  runtime.setBeforeSessionInvalidate(() => {
    callback = assert.rejects(runtime.resourceSnapshot(), fixedProtocol("PI_SESSION_TRANSITION_BUSY"));
  });
  f.state.check = () => { throw new Error("synthetic replacement failure"); };
  await assert.rejects(runtime.switchSession(), /synthetic replacement failure/);
  await callback;
  await assert.rejects(runtime.resourceSnapshot(), fixedProtocol("PI_SESSION_NOT_READY"));
  runtime.setBeforeSessionInvalidate(undefined);
  await runtime.dispose();
});

for (const mutation of ["switch", "dispose"]) for (const outcome of ["resolve", "reject"]) test("pending resource snapshot " + outcome + " cannot publish after " + mutation, async () => {
  const f = resourceRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  let release, fail;
  const pendingCheck = new Promise((resolve, reject) => { release = resolve; fail = reject; });
  f.state.check = () => pendingCheck;
  const pending = runtime.resourceSnapshot();
  const assertion = assert.rejects(pending, fixedProtocol("PI_SESSION_RESOURCE_STALE"));
  await Promise.resolve();
  f.state.check = undefined;
  if (mutation === "switch") await runtime.newSession(); else await runtime.dispose();
  if (outcome === "resolve") release(); else fail(new Error("old-generation-private-failure"));
  await assertion;
  if (mutation === "switch") {
    assert.equal((await runtime.resourceSnapshot()).profileId, "pi-base");
    await runtime.dispose();
  }
});

test("native public session replacement without callback cannot reuse old facade observation", async () => {
  const f = resourceRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  f.state.publicSessionOverride = Object.freeze({ unrelated: true });
  await assert.rejects(runtime.resourceSnapshot(), fixedProtocol("PI_SESSION_RESOURCE_STALE"));
  delete f.state.publicSessionOverride;
  assert.equal((await runtime.resourceSnapshot()).profileId, "pi-base");
  await runtime.dispose();
});

test("session envelope rejects a real within-budget observation whose eight-field wrapper exceeds UTF8 cap", async () => {
  const f = fixture(); Object.assign(f.installed, { profile_id: "pi-base", lock_identity: "b".repeat(64), slice_identity: "c".repeat(64) });
  const factories = Array.from({ length: 987 }, (_, index) => ({ name: "n" + "x".repeat(58) + String(index).padStart(4, "0"), factory() {} }));
  const resources = createOfficialResources({ ...f, settingsManager: f.settings.settingsManager, extensionFactories: factories });
  await resources.resourceLoader.reload();
  const observed = resources.observeLoadedResources();
  assert.ok(Buffer.byteLength(JSON.stringify(observed), "utf8") <= 65536);
  const envelope = { schemaVersion: 1, profileId: "pi-base", lockIdentity: "b".repeat(64), sliceIdentity: "c".repeat(64),
    runtimeIdentity: "a".repeat(64), configIdentity: "d".repeat(64), resourcesDigest: observed.resourcesDigest, observation: observed };
  assert.ok(Buffer.byteLength(JSON.stringify(envelope), "utf8") > 65536);
  const result = await createOfficialSessionFactory({ ...f, extensionFactories: factories })({ cwd: f.cwd, sessionManager: f.sessionManager });
  await assert.rejects(result.resourceSnapshot(), /pi-resource-observation-invalid/);
});

test("current resource snapshot binds fixed four identities and live configuration without new creation", async () => {
  const f = fixture(); Object.assign(f.installed, { profile_id: "pi-base", lock_identity: "b".repeat(64), slice_identity: "c".repeat(64) });
  const result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  const creates = f.state.creates, loads = f.state.loads;
  const snapshot = await result.resourceSnapshot();
  assert.deepEqual(Object.keys(snapshot).sort(), ["schemaVersion", "profileId", "lockIdentity", "sliceIdentity", "runtimeIdentity", "configIdentity", "resourcesDigest", "observation"].sort());
  assert.equal(snapshot.schemaVersion, 1); assert.equal(snapshot.profileId, "pi-base");
  assert.equal(snapshot.lockIdentity, "b".repeat(64)); assert.equal(snapshot.sliceIdentity, "c".repeat(64));
  assert.equal(snapshot.runtimeIdentity, "a".repeat(64));
  assert.equal(snapshot.configIdentity, (await result.configurationSnapshot()).configIdentity);
  assert.equal(snapshot.resourcesDigest, snapshot.observation.resourcesDigest);
  assert.equal(snapshot.observation.rolesEvidence, "selection-only");
  const frozen = value => { if (value && typeof value === "object") { assert.equal(Object.isFrozen(value), true); Object.values(value).forEach(frozen); } };
  frozen(snapshot);
  assert.ok(!JSON.stringify(snapshot).includes(f.instanceRoot) && !JSON.stringify(snapshot).includes("synthetic rules"));
  f.state.settings.quietStartup = true;
  assert.notEqual((await result.resourceSnapshot()).configIdentity, snapshot.configIdentity);
  assert.equal(f.state.creates, creates); assert.equal(f.state.loads, loads);
  f.state.check = () => { throw new Error("synthetic-runtime-changed"); };
  await assert.rejects(result.resourceSnapshot(), /synthetic-runtime-changed/);
});

test("resource snapshot identity gaps and cross-profile inputs only reject the new diagnostic seam", async () => {
  for (const fault of ["missing-profile", "wrong-profile", "missing-lock", "wrong-lock", "missing-slice", "wrong-slice"]) {
    const f = fixture(); Object.assign(f.installed, { profile_id: "pi-base", lock_identity: "b".repeat(64), slice_identity: "c".repeat(64) });
    if (fault === "missing-profile") delete f.installed.profile_id;
    if (fault === "wrong-profile") f.installed.profile_id = "pi-full";
    if (fault === "missing-lock") delete f.installed.lock_identity;
    if (fault === "wrong-lock") f.installed.lock_identity = "B".repeat(64);
    if (fault === "missing-slice") delete f.installed.slice_identity;
    if (fault === "wrong-slice") f.installed.slice_identity = "private-invalid-identity";
    const result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
    assert.match((await result.configurationSnapshot()).configIdentity, /^[0-9a-f]{64}$/);
    const checks = f.state.checks;
    await assert.rejects(result.resourceSnapshot(), /pi-session-resource-identity/);
    assert.equal(f.state.checks, checks);
  }
});

test("resource snapshot observes only fixed input identities and refuses current resource or model drift", async () => {
  const f = fixture(); Object.assign(f.installed, { profile_id: "pi-base", lock_identity: "b".repeat(64), slice_identity: "c".repeat(64) });
  const create = createOfficialSessionFactory(f);
  f.installed.lock_identity = "d".repeat(64); f.installed.profile_id = "pi-full";
  const result = await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal((await result.resourceSnapshot()).lockIdentity, "b".repeat(64));
  f.state.actualModel = { ...f.models[0], baseUrl: "https://changed.invalid" };
  await assert.rejects(result.resourceSnapshot(), /pi-session-model-changed/);
  delete f.state.actualModel;
  writeFileSync(join(f.instanceRoot, "pi-home/APPEND_SYSTEM.md"), "changed selected append");
  await assert.rejects(result.resourceSnapshot(), /pi-resource-selection-stale/);
});

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "official-session-"));
  const instanceRoot = join(root, "instance"), runtimeRoot = join(root, "runtime"), cwd = join(root, "workspace");
  for (const dir of [join(instanceRoot, "pi-home"), runtimeRoot, cwd]) mkdirSync(dir, { recursive: true });
  chmodSync(join(instanceRoot, "pi-home"), 0o700);
  writeFileSync(join(instanceRoot, "pi-home/AGENTS.md"), "synthetic rules");
  writeFileSync(join(instanceRoot, "pi-home/APPEND_SYSTEM.md"), "synthetic append");
  const config = { api: "openai-completions", baseUrl: "https://one.invalid", models: ["main", "other"].map(id => ({ id, input: ["text"] })) };
  const models = config.models.map(model => ({ ...structuredClone(model), provider: "selected", name: model.id, api: config.api, baseUrl: config.baseUrl,
    reasoning: false, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 128000, maxTokens: 16384 }));
  const variable = "AGENTCFG_PI_CREDENTIAL_" + createHash("sha256").update("synthetic").digest("hex").slice(0, 16).toUpperCase();
  const modelPath = join(instanceRoot, "pi-home/models.json");
  writeFileSync(modelPath, JSON.stringify({ providers: { selected: { ...config, apiKey: "$" + variable } } }), { mode: 0o600 });
  const calls = [], state = { settings: {}, branch: [], context: { messages: [], model: null }, creates: 0, disposes: 0, checks: 0, loads: 0 };
  const modelRuntime = Object.freeze({ getError: () => state.modelError, getModel(provider, id) { calls.push([provider, id]); return models.find(m => m.provider === provider && m.id === id); },
    getModels() { throw Error("unscoped model enumeration"); }, getAvailable() { throw Error("auth discovery"); } });
  const settingsManager = Object.freeze(Object.fromEntries(["getPackages", "getExtensionPaths", "getSkillPaths", "getPromptTemplatePaths", "getThemePaths"].map(name => [name, () => []])));
  const settings = { settingsManager, snapshot: () => structuredClone(state.settings) };
  const sessionManager = Object.freeze({ getCwd: () => cwd, getBranch: () => structuredClone(state.branch), buildSessionContext: () => structuredClone(state.context) });
  const loaderOptions = new WeakMap();
  const loadedExtensions = new WeakMap();
  class Loader {
    constructor(options) { state.loads++; loaderOptions.set(this, options); Object.freeze(this); }
    async reload() {
      state.reload?.(); state.handlers = new Map();
      const rows = loaderOptions.get(this).additionalExtensionPaths.map(path => ({ path, resolvedPath: path,
        handlers: new Map(), tools: state.extensionTools?.get(path) ?? new Map() }));
      for (const input of loaderOptions.get(this).extensionFactories) {
        const handlers = new Map();
        await input.factory({ on(name, handler) {
          state.handlers.set(name, handler);
          const list = handlers.get(name) ?? []; list.push(handler); handlers.set(name, list);
          return () => state.handlers.delete(name);
        } });
        rows.push({ path: "<inline:" + input.name + ">", resolvedPath: "<inline:" + input.name + ">", handlers, tools: state.inlineTools ?? new Map() });
      }
      loadedExtensions.set(this, rows);
    }
    getExtensions() { return { extensions: loadedExtensions.get(this), errors: [] }; }
    getSkills() { return { skills: [], diagnostics: [] }; }
    getPrompts() { return { prompts: [], diagnostics: [] }; }
    getThemes() { return { themes: [], diagnostics: [] }; }
    getAgentsFiles() { return loaderOptions.get(this).agentsFilesOverride(); }
    getSystemPrompt() { return undefined; }
    getSystemPromptSource() { return undefined; }
    getAppendSystemPrompt() { return loaderOptions.get(this).appendSystemPrompt.map(p => readFileSync(p, "utf8")); }
    getAppendSystemPromptSources() { return loaderOptions.get(this).appendSystemPrompt.map(path => ({ path })); }
    extendResources() {}
  }
  Object.freeze(Loader.prototype);
  const sdk = Object.freeze({ DefaultResourceLoader: Loader, async createAgentSessionFromServices(options) {
    state.creates++; state.options = options;
    const session = Object.freeze({ get model() { return state.actualModel ?? options.model; }, get thinkingLevel() { return state.thinking ?? options.thinkingLevel ?? "medium"; },
      getActiveToolNames: () => state.activeTools ?? [...options.tools], dispose: () => state.disposes++,
      abort: async () => { state.aborts = (state.aborts ?? 0) + 1; await state.onAbort?.(); },
      sessionManager: options.sessionManager, bindExtensions: async bindings => state.onBind?.(bindings) });
    return { session, extensionsResult: options.services.resourceLoader.getExtensions(), ...state.result };
  } });
  const groups = ["extensions", "skills", "prompts", "themes", "roles"];
  const manifest = { schema_version: 1, profile_id: "pi-base", engine: "node", bootstrap: false, plugins: [], options: { discovery: { project_resources: false } },
    resources: Object.fromEntries(groups.map(k => [k, []])), resource_ids: Object.fromEntries(groups.map(k => [k, {}])),
    provider_bindings: { selected: { logical_id: "synthetic", auth_kind: "api-key", owner: "pi-environment" } },
    model_configuration: { schema_version: 1, providers: { selected: { logical_id: "synthetic", auth_kind: "api-key", owner: "pi-environment", credential_ref: "secret:SYNTHETIC", config } } },
    model_bindings: { main: { provider: "selected", model: "main" } }, allowed_models: models.map(m => ({ provider: m.provider, model: m.id })) };
  const installed = { runtime_identity: "a".repeat(64), resources: Object.fromEntries(groups.map(k => [k, []])) };
  const controls = { policyDigest: "b".repeat(64), projectConstraintsDigest: "c".repeat(64) };
  const configuration = target => { assert.equal(target, cwd); return { ...controls }; };
  const toolDefinitions = [{ name: "synthetic_read", label: "Synthetic read", description: "fake tool", parameters: {}, execute: async () => ({ content: [] }) }];
  const result = { sdk, manifest, installed, instanceRoot, runtimeRoot, cwd, engine: "node", settings, modelRuntime, sessionManager,
    configuration, toolDefinitions, extensionFactories: [], controls, state, models, calls, modelPath, config };
  Object.defineProperty(result, "runtimeHandle", { enumerable: true, get: () => Object.freeze({ modelRuntime: result.modelRuntime,
    configurationDigest: digest(result.manifest.model_configuration), check: async () => { state.checks++; await state.check?.(); } }) });
  return result;
}

// 组合测试复用真正的仓库资源/配置/准入代码；SDK与监督RPC仅为公开接口替身。
function fileRuntimeFixture() {
  const f = fixture(), rpc = [], records = new Map();
  const owner = { manager_activation_id: "activation", runtime_identity: f.installed.runtime_identity };
  f.sessionManager = Object.freeze({ ...f.sessionManager, getSessionId: () => "native-session" });
  const state = f.state; state.runtimeCalls = [];
  const supervisor = { async call(method, args) {
    rpc.push([method, structuredClone(args)]);
    if (method === "diagnostic_resource_observation") {
      if (state.observationFailure) throw Object.assign(Error("fixed rejection"), { code: "PI_CONTROL_REJECTED", exitCode: 4 });
      return { schema_version: 1, accepted: true, generation: args.generation };
    }
    if (method === "ordinary_admission_open") return { ...args, state: "open" };
    if (method === "ordinary_admission_retire") {
      if (state.retireFailure) throw Error("private failure");
      return { control_id: args.control_id, state: "retired" };
    }
    if (method === "ordinary_admission_cancel_request") return { request_id: args.request_id, state: "canceled" };
    if (method === "ordinary_admission_prepare") {
      const id = "ledger-" + records.size;
      const prepared = { schema_version: 1, operation_id: id, request_id: args.request_id, context: args.context,
        resolution: { kind: "file", tool_name: args.tool_name, target: { path: join(f.cwd, args.input.path), destination: null },
          read_roots: [{ path: f.cwd, identity: "a".repeat(64) }],
          write_roots: ["write", "edit", "rename"].includes(args.tool_name) ? [{ path: f.cwd, identity: "a".repeat(64) }] : [],
          workspace_keys: ["write", "edit", "rename"].includes(args.tool_name) ? ["b".repeat(64)] : [],
          network: "deny", services: [], backend: "guarded-files-v1", policy: { generation: 1,
            policy_digest: f.controls.policyDigest, ceiling_digest: "a".repeat(64), hard_policy: "allow", requires_human: true } }, private_input_ref: "private-ref", operation_digest: "d".repeat(64) };
      const execution = { operation_id: "physical-" + records.size, request_digest: "e".repeat(64),
        write: false, path: prepared.resolution.target.path, lease_id: null, state: "prepared" };
      records.set(id, { prepared, execution, phase: "prepared" }); return structuredClone(prepared);
    }
    if (method === "ordinary_admission_status") {
      const row = records.get(args.operation_id);
      return { admission: { operation_id: args.operation_id, state: row.phase }, execution: structuredClone(row.execution) };
    }
    if (method === "ordinary_admission_issue") {
      const row = records.get(args.operation_id); row.phase = "permitted";
      return { schema_version: 1, permit_id: "permit", operation_id: args.operation_id,
        operation_digest: row.prepared.operation_digest, source: "human", reviewer_identity: null, context: args.context };
    }
    if (method === "ordinary_admission_consume") {
      const row = records.get(args.permit.operation_id); row.phase = "consumed";
      Object.assign(row.execution, { state: "consumed", lease_id: "host-lease" }); return structuredClone(row.execution);
    }
    if (method === "ordinary_read") return { data_b64: Buffer.from("synthetic content").toString("base64"), total_bytes: 17, content_digest: "f".repeat(64) };
    if (method === "ordinary_finish") return { finished: true };
    throw Error("unexpected RPC " + method);
  } };
  const sdk = { ...f.sdk };
  for (const [factory, name] of [["Read", "read"], ["Write", "write"], ["Edit", "edit"], ["Ls", "ls"], ["Find", "find"], ["Grep", "grep"]]) {
    sdk["create" + factory + "ToolDefinition"] = (cwd, options) => ({ name, label: name, description: name, parameters: {},
      async execute(_id, input) {
        assert.equal(Object.isFrozen(input), true);
        return { content: [{ type: "text", text: (await options.operations.readFile(join(cwd, input.path))).toString() }] };
      } });
  }
  sdk.createBashToolDefinition = () => { throw Error("unselected command factory"); };
  sdk.createAgentSessionRuntime = async (create, target) => {
    let current = await create(target), before, rebind;
    const replace = async (method, args) => {
      state.runtimeCalls.push([method, args]);
      if (state.cancelTransition) return { cancelled: true };
      await current.session.abort();
      before?.(); current.session.dispose();
      if (state.transitionWait) await state.transitionWait;
      current = await create({ ...target, sessionManager: f.sessionManager });
      await rebind?.(current.session);
      return { cancelled: false };
    };
    const native = Object.freeze({
      get session() { return state.publicSessionOverride ?? current.session; }, get services() { return current.services; },
      get cwd() { return current.services.cwd; }, get diagnostics() { return current.diagnostics; },
      get modelFallbackMessage() { return current.modelFallbackMessage; },
      setBeforeSessionInvalidate(fn) { state.nativeCallbackSets = (state.nativeCallbackSets ?? 0) + 1; before = fn; },
      setRebindSession(fn) { rebind = fn; },
      newSession(...args) { return replace("newSession", args); },
      switchSession(...args) { return replace("switchSession", args); },
      fork(...args) { return replace("fork", args); },
      importFromJsonl(...args) { return replace("importFromJsonl", args); },
      async dispose() { before?.(); current.session.dispose(); },
    });
    state.native = native; return native;
  };
  const options = { ...f, sdk: Object.freeze(sdk), supervisor, owner,
    policySnapshot: () => ({ policy_digest: f.controls.policyDigest, generation: 1 }) };
  const target = { cwd: f.cwd, sessionManager: f.sessionManager };
  const ctx = { cwd: f.cwd, sessionManager: f.sessionManager, hasUI: true, ui: { confirm: async () => true } };
  return { ...f, options, target, ctx, rpc, records };
}

async function readRuntimeFile(f, id = "call", tool = f.state.options.customTools.find(tool => tool.name === "read")) {
  return tool.execute(id, { path: "code.txt" }, new AbortController().signal, undefined, f.ctx);
}

function shellRuntimeFixture() {
  const f = fileRuntimeFixture(), rows = new Map();
  f.options.manifest.options.external_tools = { shell: { executable: "/usr/bin/bash", project_root: "project",
    read_roots: ["project"], write_roots: [], timeout_seconds: 30 } };
  f.options.sdk = Object.freeze({ ...f.options.sdk, createBashToolDefinition(cwd, options) {
    assert.equal(cwd, f.cwd); assert.equal(options.exposeSessionEnvironment, false);
    return { name: "bash", label: "Bash", parameters: { type: "object" }, execute() { throw Error("SDK execute forbidden"); } };
  } });
  const previous = f.options.supervisor;
  f.options.supervisor = { async call(method, args) {
    if (method === "ordinary_admission_prepare" && args.tool_name === "bash") {
      f.rpc.push([method, structuredClone(args)]);
      const operation_id = (rows.size + 1).toString(16).padStart(32, "0");
      const prepared = { schema_version: 1, operation_id, request_id: args.request_id, context: args.context,
        private_input_ref: "private-ref", operation_digest: "d".repeat(64), resolution: {
          kind: "shell-command", tool_name: "bash", target: { command_ref: "tool:shell", timeout_ms: 30000,
            executable: { path: "/usr/bin/bash", device: 1, inode: 1, uid: 0, sha256: "a".repeat(64) } },
          read_roots: [{ path: f.cwd, identity: "a".repeat(64) }], write_roots: [], workspace_keys: [],
          network: "deny", services: [], backend: "linux-bwrap-v1", policy: { generation: 1,
            policy_digest: f.controls.policyDigest, ceiling_digest: "b".repeat(64), hard_policy: "allow", requires_human: true } } };
      rows.set(operation_id, prepared); return structuredClone(prepared);
    }
    if (method === "ordinary_admission_status" && rows.has(args.operation_id)) {
      f.rpc.push([method, structuredClone(args)]);
      return { admission: { operation_id: args.operation_id, state: "prepared" }, execution: {
        operation_id: args.operation_id, lease_id: null, kind: "command", tool_name: "bash", state: "prepared", write: false,
        timeout_seconds: 30, command_ref: "tool:shell", request_digest: "d".repeat(64) } };
    }
    return previous.call(method, args);
  } };
  f.ctx.ui.confirm = async title => title === "Approve file operation";
  return f;
}

for (const profile of ["pi-base", "pi-full"]) test(profile + " explicitly selected Shell is composed alongside seven file tools", async () => {
  const f = shellRuntimeFixture(); f.options.manifest.profile_id = profile;
  const runtime = await createOfficialFileRuntime(f.options, f.target);
  try {
    assert.deepEqual(f.state.options.tools.sort(), ["bash", "edit", "find", "grep", "ls", "read", "rename", "write"]);
    const shell = f.state.options.customTools.find(tool => tool.name === "bash");
    await assert.rejects(shell.execute("shell", { command: "synthetic private script" }, new AbortController().signal, undefined, f.ctx), /OPERATION_CANCELED/);
    assert.ok(!f.rpc.some(([method]) => ["start", "ordinary_admission_issue"].includes(method)));
    assert.equal((await readRuntimeFile(f)).content[0].text, "synthetic content");
    assert.throws(() => f.state.handlers.get("user_bash")({}), /PI_COMMAND_ADMISSION_UNAVAILABLE/);
  } finally { await runtime.dispose(); }
});

test("session replacement cancels a pending Shell confirmation and retires both admission controllers", async () => {
  const f = shellRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  const old = f.state.options.customTools.find(tool => tool.name === "bash");
  let confirmed, entered;
  const waiting = new Promise(resolve => { entered = resolve; });
  f.ctx.ui.confirm = () => { entered(); return new Promise(resolve => { confirmed = resolve; }); };
  const rejected = assert.rejects(old.execute("old", { command: "synthetic" }, new AbortController().signal, undefined, f.ctx), /OPERATION_CANCELED/);
  await waiting;
  await runtime.newSession(); confirmed(true); await rejected; await runtime.drain();
  assert.equal(f.rpc.filter(([method]) => method === "ordinary_admission_retire").length, 2);
  assert.ok(!f.rpc.some(([method]) => ["ordinary_admission_issue", "start"].includes(method)));
  await assert.rejects(old.execute("after-retire", { command: "synthetic" }, new AbortController().signal, undefined, f.ctx), /OPERATION_CANCELED/);
  f.ctx.ui.confirm = async () => false;
  await assert.rejects(f.state.options.customTools.find(tool => tool.name === "bash").execute("new", { command: "synthetic" }, new AbortController().signal, undefined, f.ctx), /OPERATION_CANCELED/);
  const opens = f.rpc.filter(([method]) => method === "ordinary_admission_open");
  assert.equal(opens.length, 2); assert.notEqual(opens[0][1].control_id, opens[1][1].control_id);
  await runtime.dispose();
});

test("selected manual Shell without UI prepares then cancels without issue or execution", async () => {
  const f = shellRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  f.ctx.hasUI = false;
  try {
    await assert.rejects(f.state.options.customTools.find(tool => tool.name === "bash").execute("no-ui", { command: "synthetic" }, new AbortController().signal, undefined, f.ctx), /OPERATION_ADMISSION_REQUIRED/);
    const methods = f.rpc.map(([method]) => method);
    assert.equal(methods.filter(method => method === "ordinary_admission_prepare").length, 1);
    assert.equal(methods.filter(method => method === "ordinary_admission_cancel_request").length, 1);
    for (const method of ["ordinary_admission_issue", "ordinary_admission_issue_deterministic", "ordinary_admission_consume", "ordinary_shell_take_input", "start"]) {
      assert.equal(methods.includes(method), false);
    }
  } finally { await runtime.dispose(); }
});

test("selected Shell missing its public definition fails composition without native session", async () => {
  const f = shellRuntimeFixture(); f.options.sdk = Object.freeze({ ...f.options.sdk, createBashToolDefinition: undefined });
  await assert.rejects(createOfficialFileRuntime(f.options, f.target), /ORDINARY_SHELL_UNAVAILABLE/);
  assert.equal(f.state.creates, 0);
});

test("official file runtime composes seven admitted tools and executes frozen input through manager RPC", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  assert.deepEqual(f.state.options.tools.sort(), ["edit", "find", "grep", "ls", "read", "rename", "write"]);
  assert.equal(f.state.options.noTools, "all");
  assert.equal((await readRuntimeFile(f)).content[0].text, "synthetic content");
  assert.deepEqual(f.rpc.map(row => row[0]), ["ordinary_admission_open", "ordinary_admission_prepare", "ordinary_admission_status",
    "ordinary_admission_issue", "ordinary_admission_consume", "ordinary_read", "ordinary_finish"]);
  assert.equal(f.rpc.find(row => row[0] === "ordinary_admission_prepare")[1].context.config_identity.length, 64);
  assert.equal(Object.isFrozen(runtime), true); assert.notEqual(runtime, f.state.native);
  await runtime.dispose();
});

test("public TUI editor boundary intercepts stock submit callback and unsafe keys", async () => {
  const f = fileRuntimeFixture(); let component, listener, submits = 0, notices = 0, detached = 0;
  class Editor {
    actionHandlers = new Map(); text = ""; borderColor = value => value;
    getText() { return this.text; }
    setText(value) { this.text = value; }
    getExpandedText() { return this.text; }
    handleInput(value) { if (value === "enter") this.onSubmit?.(this.text); }
    render() { return [this.text]; }
    invalidate() {}
    setAutocompleteProvider() {}
    setPaddingX() {}
    setAutocompleteMaxVisible() {}
    insertTextAtCursor(value) { this.text += value; }
    addToHistory() {}
    setWorkingStatusIndicator() {}
  }
  f.options.sdk = Object.freeze({ ...f.options.sdk, CustomEditor: Editor });
  const runtime = await createOfficialFileRuntime(f.options, f.target);
  const ui = { notify() { notices++; }, setEditorComponent(factory) {
    component = factory({}, {}, { matches: (data, key) => data === key });
    // 原SDK在公开factory后赋入真实submit回调。
    component.onSubmit = () => { submits++; };
  }, onTerminalInput(callback) { listener = callback; return () => { detached++; }; } };
  try {
    const start = f.state.handlers.get("session_start"); assert.equal(typeof start, "function");
    await start({}, { mode: "rpc", sessionManager: f.sessionManager, hasUI: true, ui: {} }); assert.equal(component, undefined);
    await start({}, { mode: "tui", sessionManager: f.sessionManager, hasUI: true, ui });
    for (const command of ["/export", "/export jsonl /outside/sentinel", "/share", "/bug details", "/debug", "/copy", "  /export /tmp/sentinel  "]) {
      component.setText(command); component.handleInput("enter"); component.onSubmit(command);
    }
    assert.equal(submits, 0); assert.equal(notices, 14);
    for (const command of ["ordinary prompt", "/mcp", "/compact", "/session"]) {
      component.setText(command); component.handleInput("enter");
    }
    assert.equal(submits, 4);
    for (const key of ["app.editor.external", "app.clipboard.pasteImage", "app.message.copy", "\x1b[<2;1;1M"]) assert.deepEqual(listener(key), { consume: true });
    assert.equal(listener("ordinary character"), undefined);
    const before = notices; component.onPasteImage(); assert.equal(notices, before + 1);
    await f.state.handlers.get("session_shutdown")({});
    assert.equal(detached, 0);
    assert.deepEqual(listener("app.editor.external"), { consume: true });
    // 后续handler仍等待时旧listener保持；新factory真正成功后才退役旧listener。
    await start({}, { mode: "tui", sessionManager: f.sessionManager, hasUI: true, ui });
    assert.equal(detached, 1);
    assert.deepEqual(f.rpc, []);
  } finally { await runtime.dispose(); }
});

test("swallowed native extension startup error cannot open an unguarded TUI", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  f.state.onBind = async () => {
    try { await f.state.handlers.get("session_start")({}, { mode: "tui", sessionManager: f.sessionManager, hasUI: true, ui: {} }); }
    catch { /* 模拟原SDK记录extension错误后继续返回。 */ }
  };
  try {
    await assert.rejects(runtime.session.bindExtensions({ mode: "tui" }), /PI_FRONTEND_BOUNDARY_UNAVAILABLE/);
    await runtime.session.bindExtensions({ mode: "rpc" });
    assert.deepEqual(f.rpc, []);
  } finally { await runtime.dispose(); }
});

test("a no-op UI editor setter does not count as an installed frontend boundary", async () => {
  const f = fileRuntimeFixture(); f.options.sdk = Object.freeze({ ...f.options.sdk, CustomEditor: class {} });
  const runtime = await createOfficialFileRuntime(f.options, f.target);
  f.state.onBind = () => f.state.handlers.get("session_start")({}, { mode: "tui", sessionManager: f.sessionManager, hasUI: true,
    ui: { setEditorComponent() {}, onTerminalInput() { return () => {}; }, notify() {} } });
  try {
    await assert.rejects(runtime.session.bindExtensions({ mode: "tui" }), /PI_FRONTEND_BOUNDARY_UNAVAILABLE/);
    assert.deepEqual(f.rpc, []);
  } finally { await runtime.dispose(); }
});

for (const profile of ["pi-base", "pi-full"]) test(profile + " frontend export facade denies direct IO without changing native session", async () => {
  const f = fileRuntimeFixture(); f.options.manifest.profile_id = profile;
  const runtime = await createOfficialFileRuntime(f.options, f.target);
  try {
    const native = f.state.native.session;
    assert.notEqual(runtime.session, native);
    assert.equal(Object.isFrozen(native), true);
    assert.equal(Object.isFrozen(runtime.session), true);
    for (const method of ["exportToHtml", "exportToJsonl"]) {
      for (const args of [[], ["/outside/sentinel"], [".env"], ["code.txt"]]) {
        assert.throws(() => runtime.session[method](...args), error => error.code === "PI_EXPORT_ADMISSION_UNAVAILABLE" && error.exitCode === 5);
      }
      assert.equal(native[method], undefined);
    }
    assert.equal(runtime.session.model, native.model);
    assert.deepEqual(runtime.session.getActiveToolNames(), native.getActiveToolNames());
    // Public getters and receiver-bound methods work; no private member is exposed.
    assert.equal(runtime.session._extensionRunner, undefined);
    const calls = f.state.aborts ?? 0;
    await runtime.session.abort(); assert.equal(f.state.aborts, calls + 1);
    const old = runtime.session; let rebound;
    runtime.setRebindSession(async session => { rebound = session; });
    await runtime.newSession();
    assert.equal(rebound, runtime.session); assert.notEqual(rebound, old);
    assert.throws(() => rebound.exportToJsonl(), /PI_EXPORT_ADMISSION_UNAVAILABLE/);
    assert.throws(() => old.exportToHtml(), /PI_EXPORT_ADMISSION_UNAVAILABLE/);
    assert.deepEqual(f.rpc.filter(([method]) => method !== "ordinary_admission_retire"), []);
  } finally { await runtime.dispose(); }
});

for (const profile of ["pi-base", "pi-full"]) test(profile + " rejects frontend user_bash until a managed command route is available", async () => {
  const f = fileRuntimeFixture(); f.options.manifest.profile_id = profile;
  const runtime = await createOfficialFileRuntime(f.options, f.target);
  try {
    assert.equal(typeof f.state.handlers.get("user_bash"), "function");
    for (const excludeFromContext of [false, true]) {
      assert.throws(() => f.state.handlers.get("user_bash")({ type: "user_bash", command: "synthetic-private-command",
        cwd: f.cwd, excludeFromContext }, f.ctx), error => error.message === "PI_COMMAND_ADMISSION_UNAVAILABLE");
    }
    assert.deepEqual(f.rpc, []);
    const previous = f.state.handlers.get("user_bash");
    await f.state.options.services.resourceLoader.reload();
    // guard绑定模块私有固定函数；reload必须重新登记同一受信函数身份。
    assert.equal(f.state.handlers.get("user_bash"), previous);
    assert.throws(() => f.state.handlers.get("user_bash")({}), /PI_COMMAND_ADMISSION_UNAVAILABLE/);
    assert.deepEqual(f.rpc, []);
  } finally { await runtime.dispose(); }
});

test("TUI callback replacement cannot overwrite synchronous admission retirement", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  const old = f.state.options.customTools.find(tool => tool.name === "read"); let uiResets = 0;
  runtime.setBeforeSessionInvalidate(() => { throw Error("replaced callback"); });
  runtime.setBeforeSessionInvalidate(() => { uiResets++; });
  assert.equal(f.state.nativeCallbackSets, 1);
  await runtime.newSession(); await runtime.drain();
  await assert.rejects(readRuntimeFile(f, "old", old), /OPERATION_CANCELED/);
  assert.equal(uiResets, 1);
  assert.equal((await readRuntimeFile(f, "new")).content[0].text, "synthetic content");
  await runtime.dispose(); assert.equal(uiResets, 2);
});

test("cancelled native replacement keeps the current admission session alive", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  f.state.cancelTransition = true;
  assert.deepEqual(await runtime.newSession(), { cancelled: true });
  assert.equal(f.rpc.some(row => row[0] === "ordinary_admission_retire"), false);
  assert.equal((await readRuntimeFile(f)).content[0].text, "synthetic content");
  await runtime.dispose();
});

test("native UI callback error propagates after admission has already retired", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  const old = f.state.options.customTools.find(tool => tool.name === "read");
  runtime.setBeforeSessionInvalidate(() => { throw Error("synthetic UI failure"); });
  await assert.rejects(runtime.newSession(), /synthetic UI failure/);
  await assert.rejects(readRuntimeFile(f, "old", old), /OPERATION_CANCELED/);
  runtime.setBeforeSessionInvalidate(undefined); await runtime.dispose();
});

test("late UI confirmation after runtime disposal never issues or consumes permission", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  let yes, entered; const shown = new Promise(resolve => { entered = resolve; });
  f.ctx.ui.confirm = () => { entered(); return new Promise(resolve => { yes = resolve; }); };
  const execution = readRuntimeFile(f); const rejected = assert.rejects(execution, /OPERATION_CANCELED/);
  await shown; await runtime.dispose(); yes(true); await rejected;
  assert.equal(f.rpc.some(row => ["ordinary_admission_issue", "ordinary_admission_consume", "ordinary_read"].includes(row[0])), false);
});

test("runtime disposal retires local permission before awaiting native tool abort and disposal", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  const old = f.state.options.customTools.find(tool => tool.name === "read");
  f.state.onAbort = async () => {
    assert.equal(f.state.disposes, 0);
    await assert.rejects(readRuntimeFile(f, "inside-abort", old), /OPERATION_CANCELED/);
  };
  await runtime.dispose();
  assert.equal(f.state.aborts, 1); assert.equal(f.state.disposes, 1);
});

test("native abort failure leaves local permission retired and does not pretend session disposal succeeded", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  const old = f.state.options.customTools.find(tool => tool.name === "read");
  f.state.onAbort = async () => { throw Error("synthetic abort failed"); };
  await assert.rejects(runtime.dispose(), /synthetic abort failed/);
  await assert.rejects(runtime.dispose(), /synthetic abort failed/);
  await assert.rejects(readRuntimeFile(f, "after-abort-failure", old), /OPERATION_CANCELED/);
  assert.equal(f.state.disposes, 0); assert.equal(f.state.aborts, 1);
});

test("configuration changed while UI is open cannot execute through the composed session", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  f.ctx.ui.confirm = async () => { f.state.settings.theme = "changed"; return true; };
  await assert.rejects(readRuntimeFile(f), /OPERATION_CONTEXT_STALE/);
  assert.equal(f.rpc.some(row => row[0] === "ordinary_admission_issue"), false);
  await runtime.dispose();
});

test("concurrent session transitions fail closed and cleanup failure is not successful disposal", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  let finish; f.state.transitionWait = new Promise(resolve => { finish = resolve; });
  const first = runtime.newSession();
  await assert.rejects(runtime.fork("entry"), /PI_SESSION_TRANSITION_BUSY/);
  await assert.rejects(runtime.dispose(), /PI_SESSION_TRANSITION_BUSY/);
  finish(); await first;
  f.state.retireFailure = true;
  await assert.rejects(runtime.dispose(), /OPERATION_RETIRE_INCOMPLETE/);
  await assert.rejects(runtime.newSession(), /PI_SESSION_RETIRED/);
});

for (const method of ["switchSession", "fork", "importFromJsonl"]) test("public runtime " + method + " forwards exact arguments and rebinds admitted tools", async () => {
  const f = fileRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  const args = ["synthetic-path", { synthetic: true }]; let rebinds = 0;
  runtime.setRebindSession(async session => { assert.equal(session, runtime.session); rebinds++; });
  await runtime[method](...args);
  assert.deepEqual(f.state.runtimeCalls, [[method, args]]); assert.equal(rebinds, 1);
  assert.equal(runtime.cwd, f.cwd); assert.equal(runtime.services.cwd, f.cwd); assert.deepEqual(runtime.diagnostics, []);
  await runtime.dispose();
});

test("missing native file factory rejects the composition before SDK session creation", async () => {
  const f = fileRuntimeFixture(); f.options.sdk = Object.freeze({ ...f.options.sdk, createGrepToolDefinition: undefined });
  await assert.rejects(createOfficialFileRuntime(f.options, f.target), /PI_SESSION_FILE_TOOLS_INCOMPLETE/);
  assert.equal(f.state.creates, 0);
  assert.equal(f.rpc.some(row => row[0] === "ordinary_admission_prepare"), false);
});

test("explicit shared main binding is resolved without model enumeration or auth probing", () => {
  const f = fixture(); assert.equal(resolveOfficialModel(f), f.models[0]); assert.deepEqual(f.calls, [["selected", "main"]]);
});
test("manual default from native settings and restored selection take precedence", () => {
  const f = fixture(); f.state.settings = { defaultProvider: "selected", defaultModel: "other" };
  assert.equal(resolveOfficialModel(f), f.models[1]);
  f.state.branch = [{ type: "model_change", provider: "selected", modelId: "main" }];
  assert.equal(resolveOfficialModel(f), f.models[0]);
});
test("restore uses last public model_change even when assistant names a different physical model", () => {
  const f = fixture(); f.state.context = { messages: [{}], model: { provider: "physical", modelId: "unselected" } };
  f.state.branch = [{ type: "model_change", provider: "selected", modelId: "main" }, { type: "message", message: { role: "assistant", provider: "physical", model: "unselected" } },
    { type: "model_change", provider: "selected", modelId: "other" }];
  assert.equal(resolveOfficialModel(f), f.models[1]);
});
test("old sessions without model_change use public context model without scanning message bodies", () => {
  const f = fixture(); f.state.context = { messages: [{}], model: { provider: "selected", modelId: "other" } };
  assert.equal(resolveOfficialModel(f), f.models[1]);
});
test("unavailable virtual selection refuses restore even if a physical response is still available", () => {
  const f = fixture(); f.state.branch = [{ type: "model_change", provider: "selected", modelId: "removed-virtual" }];
  f.manifest.allowed_models.push({ provider: "selected", model: "removed-virtual" });
  f.state.context = { messages: [{}], model: { provider: "selected", modelId: "other" } };
  assert.throws(() => resolveOfficialModel(f), /pi-main-model-unavailable/);
  assert.deepEqual(f.calls, [["selected", "removed-virtual"]]);
});
test("registered virtual selection stays explicit instead of adopting its physical response", () => {
  const f = fixture(); f.models[0].api = "pi-virtual";
  f.state.branch = [{ type: "model_change", provider: "selected", modelId: "main" }];
  f.state.context = { messages: [{}], model: { provider: "selected", modelId: "other" } };
  assert.equal(resolveOfficialModel(f), f.models[0]);
});
for (const fault of ["bootstrap", "missing-main", "partial-default", "unselected-default", "missing-restore", "unselected-restore", "unavailable", "wrong-runtime-model", "duplicate-binding"]) test("model " + fault + " never falls back", () => {
  const f = fixture();
  if (fault === "bootstrap") f.manifest.bootstrap = true;
  if (fault === "missing-main") f.manifest.model_bindings.main = undefined;
  if (fault === "partial-default") f.state.settings.defaultProvider = "selected";
  if (fault === "unselected-default") f.state.settings = { defaultProvider: "foreign", defaultModel: "other" };
  if (fault === "missing-restore") f.state.context.messages = [{}];
  if (fault === "unselected-restore") f.state.branch = [{ type: "model_change", provider: "foreign", modelId: "other" }];
  if (fault === "unavailable") f.models.length = 0;
  if (fault === "wrong-runtime-model") f.modelRuntime = { getModel: () => ({ provider: "foreign", id: "main" }) };
  if (fault === "duplicate-binding") f.manifest.allowed_models.push({ ...f.manifest.allowed_models[0] });
  assert.throws(() => resolveOfficialModel(f), /pi-(main|model|session)-/);
  assert.equal(f.calls.length <= 1, true);
});
test("official factory composes public services, exact tools, model, resources and effective ConfigIdentity", async () => {
  const f = fixture(), create = createOfficialSessionFactory(f);
  const result = await create({ cwd: f.cwd, agentDir: join(f.instanceRoot, "pi-home"), sessionManager: f.sessionManager });
  assert.equal(result.session.model, f.models[0]); assert.equal(result.services.modelRuntime, f.modelRuntime);
  assert.equal(result.services.settingsManager, f.settings.settingsManager);
  assert.deepEqual(f.state.options.tools, ["synthetic_read"]); assert.equal(f.state.options.noTools, "all");
  assert.deepEqual(f.state.options.customTools, f.toolDefinitions);
  assert.equal(f.state.options.model, f.models[0]); assert.equal(f.state.options.scopedModels.length, 2);
  const snapshot = await result.configurationSnapshot();
  assert.match(snapshot.configIdentity, /^[0-9a-f]{64}$/); assert.equal(snapshot.runtimeIdentity, f.installed.runtime_identity);
  assert.deepEqual(snapshot.model, { provider: "selected", model: "main" });
  assert.equal(Object.isFrozen(snapshot), true); assert.equal(Object.isFrozen(snapshot.model), true);
  assert.equal((await result.configurationSnapshot()).configIdentity, snapshot.configIdentity);
});
test("identity changes with current model, thinking, settings, policy or project constraints", async () => {
  const f = fixture(), result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  const seen = new Set(); const add = async () => { const value = (await result.configurationSnapshot()).configIdentity; assert.equal(seen.has(value), false); seen.add(value); };
  await add(); f.state.actualModel = f.models[1]; await add(); f.state.thinking = "high"; await add(); f.state.settings.theme = "synthetic"; await add();
  f.controls.policyDigest = "d".repeat(64); await add(); f.controls.projectConstraintsDigest = "e".repeat(64); await add();
});
test("resource drift makes current configuration unavailable and does not silently refresh identity", async () => {
  const f = fixture(), result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  writeFileSync(join(f.instanceRoot, "pi-home/AGENTS.md"), "changed");
  await assert.rejects(() => result.configurationSnapshot(), /pi-resource-selection-stale/);
});
test("live model outside shared bindings cannot receive configuration identity", async () => {
  const f = fixture(), result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  f.state.actualModel = { provider: "foreign", id: "other" }; await assert.rejects(() => result.configurationSnapshot(), /pi-model-not-selected/);
});
test("model absence fails before loading extensions or creating a session", async () => {
  const f = fixture(); f.models.length = 0; let reloads = 0; f.state.reload = () => reloads++;
  await assert.rejects(createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager }), /pi-main-model-unavailable/);
  assert.equal(reloads, 0); assert.equal(f.state.creates, 0);
});
for (const fault of ["fallback", "model", "thinking", "resource"]) test("session creation " + fault + " mismatch disposes the unused session", async () => {
  const f = fixture();
  if (fault === "fallback") f.state.result = { modelFallbackMessage: "native fallback" };
  if (fault === "model") f.state.actualModel = f.models[1];
  if (fault === "thinking") f.state.thinking = "off";
  if (fault === "resource") f.state.reload = () => writeFileSync(join(f.instanceRoot, "pi-home/AGENTS.md"), "changed");
  await assert.rejects(createOfficialSessionFactory({ ...f, thinkingLevel: "high" })({ cwd: f.cwd, sessionManager: f.sessionManager }));
  assert.equal(f.state.disposes, fault === "resource" ? 0 : 1);
});
test("new factory invocation resolves fresh cwd resources and does not mutate SDK methods", async () => {
  const f = fixture(), create = createOfficialSessionFactory(f), original = f.sdk.createAgentSessionFromServices;
  await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  f.state.settings = { defaultProvider: "selected", defaultModel: "other" };
  const second = await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal(second.session.model, f.models[1]); assert.equal(f.state.creates, 2); assert.equal(f.sdk.createAgentSessionFromServices, original);
});
test("public provider may return fresh model objects with stable fields", async () => {
  const f = fixture(); f.modelRuntime = Object.freeze({ getError: () => undefined, getModel: (provider, id) => ({ ...f.models.find(m => m.provider === provider && m.id === id) }) });
  const result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal(result.session.model.id, "main"); assert.match((await result.configurationSnapshot()).configIdentity, /^[0-9a-f]{64}$/);
});
test("model route changing during extension load prevents session creation", async () => {
  const f = fixture(); f.modelRuntime = { getError: () => undefined, getModel: (provider, id) => ({ ...f.models.find(m => m.provider === provider && m.id === id), baseUrl: f.state.url ?? "https://one.invalid" }) };
  f.state.reload = () => { f.state.url = "https://two.invalid"; };
  await assert.rejects(createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager }), /pi-session-model-changed/);
  assert.equal(f.state.creates, 0);
});
for (const field of ["headers", "compat", "samplingParams", "baseUrl"]) test("in-place model " + field + " change invalidates configuration without hashing private model fields", async () => {
  const f = fixture(); f.models[0].headers = { Authorization: "synthetic-marker-not-real" };
  const result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal(JSON.stringify(await result.configurationSnapshot()).includes("synthetic-marker"), false);
  f.models[0][field] = field === "baseUrl" ? "https://changed.invalid" : { changed: "synthetic-marker-new" };
  await assert.rejects(() => result.configurationSnapshot(), error => error.message === "pi-session-model-changed");
});
test("model metadata does not enter any configuration digest", async () => {
  const f = fixture(); f.models[0].headers = { Authorization: "synthetic-first" };
  const first = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  const snapshot = await first.configurationSnapshot(); f.models[0].headers.Authorization = "synthetic-second";
  const second = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.deepEqual(await second.configurationSnapshot(), snapshot);
  await assert.rejects(() => first.configurationSnapshot(), /pi-session-model-changed/);
});
test("current tools must be a subset of the explicitly supplied definitions", async () => {
  const f = fixture(), result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  f.state.activeTools = ["bash"]; await assert.rejects(() => result.configurationSnapshot(), /pi-session-tools-changed/);
  f.state.activeTools = []; assert.match((await result.configurationSnapshot()).configIdentity, /^[0-9a-f]{64}$/);
});
test("factory reads managed private settings through the official storage adapter by default", async () => {
  const f = fixture(), agentDir = join(f.instanceRoot, "pi-home"), path = join(agentDir, "settings.json");
  chmodSync(agentDir, 0o700);
  writeFileSync(path, JSON.stringify({ defaultProvider: "selected", defaultModel: "other", enableAnalytics: true, cacheWarming: "idle" }), { mode: 0o600 });
  let calls = 0;
  const SettingsManager = Object.freeze({ fromStorage(storage, options) {
    calls++; assert.deepEqual(options, { projectTrusted: false });
    let value; storage.withLock("global", text => { value = JSON.parse(text); });
    return Object.freeze({ ...f.settings.settingsManager, getSettings: () => structuredClone(value) });
  } });
  const result = await createOfficialSessionFactory({ ...f, settings: undefined, sdk: Object.freeze({ ...f.sdk, SettingsManager }) })({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal(calls, 1); assert.equal(result.session.model.id, "other");
  const effective = result.services.settingsManager.getSettings();
  assert.equal(effective.enableAnalytics, false); assert.equal(effective.cacheWarming, "off"); assert.equal(effective.defaultProjectTrust, "never");
  assert.match((await result.configurationSnapshot()).configIdentity, /^[0-9a-f]{64}$/);
  writeFileSync(path, JSON.stringify({ defaultProvider: "selected", defaultModel: "main" }));
  await assert.rejects(() => result.configurationSnapshot(), /pi-settings-stale/);
});
test("factory keeps its selected install declaration when a caller replaces the input object", async () => {
  const f = fixture(), create = createOfficialSessionFactory(f);
  f.installed.resources = null; f.manifest.model_bindings.main.model = "unselected";
  const result = await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal(result.session.model.id, "main"); assert.match((await result.configurationSnapshot()).configIdentity, /^[0-9a-f]{64}$/);
});
for (const fault of ["no-tools", "duplicate-tools", "bad-context", "bad-runtime", "foreign-agent-dir", "foreign-session-cwd"]) test("factory rejects " + fault + " before SDK session creation", async () => {
  const f = fixture(), options = { cwd: f.cwd, sessionManager: f.sessionManager };
  if (fault === "no-tools") delete f.toolDefinitions;
  if (fault === "duplicate-tools") f.toolDefinitions.push(f.toolDefinitions[0]);
  if (fault === "bad-context") f.controls.policyDigest = "unknown";
  if (fault === "bad-runtime") f.installed.runtime_identity = "unknown";
  if (fault === "foreign-agent-dir") options.agentDir = f.cwd;
  if (fault === "foreign-session-cwd") options.cwd = f.instanceRoot;
  await assert.rejects(async () => createOfficialSessionFactory(f)(options)); assert.equal(f.state.creates, 0);
});

function saveModelConfig(f) {
  const disk = JSON.parse(readFileSync(f.modelPath, "utf8"));
  disk.providers.selected = { ...structuredClone(f.config), apiKey: disk.providers.selected.apiKey };
  writeFileSync(f.modelPath, JSON.stringify(disk));
}
for (const field of ["api", "baseUrl", "reasoning", "thinkingLevelMap", "compat", "credential_ref"]) test("redeployment of " + field + " changes identity even for the same model ID", async () => {
  const f = fixture();
  const first = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  const before = await first.configurationSnapshot();
  if (["api", "baseUrl"].includes(field)) {
    f.config[field] = field === "api" ? "openai-responses" : "https://second.invalid/v2";
    for (const model of f.models) model[field] = f.config[field];
  } else if (field === "credential_ref") f.manifest.model_configuration.providers.selected.credential_ref = "secret:different";
  else {
    const value = field === "reasoning" ? true : field === "thinkingLevelMap" ? { high: "max", off: null } : { thinkingFormat: "deepseek" };
    f.config.models[0][field] = value; f.models[0][field] = structuredClone(value);
  }
  saveModelConfig(f);
  const second = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  const after = await second.configurationSnapshot();
  assert.deepEqual(before.model, after.model); assert.notEqual(before.configIdentity, after.configIdentity);
  assert.equal(before.runtimeIdentity, after.runtimeIdentity);
  if (field !== "credential_ref") await assert.rejects(() => first.configurationSnapshot());
});
for (const phase of ["before-load", "during-load", "after-create", "snapshot"]) test("SDK model configuration errors at " + phase + " cannot reuse a fallback model", async () => {
  const f = fixture(), marker = "synthetic-private-error-marker";
  if (phase === "before-load") f.state.modelError = marker;
  if (phase === "during-load") f.state.reload = () => { f.state.modelError = marker; };
  if (phase === "after-create") {
    const original = f.sdk;
    f.sdk = { ...original, async createAgentSessionFromServices(options) { const result = await original.createAgentSessionFromServices(options); f.state.modelError = marker; return result; } };
  }
  const run = () => createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  if (phase === "snapshot") {
    const result = await run(); f.state.modelError = marker;
    await assert.rejects(() => result.configurationSnapshot(), error => error.message === "pi-model-runtime-error");
  } else {
    await assert.rejects(run(), error => error.message === "pi-model-runtime-error");
    assert.equal(f.state.creates, phase === "after-create" ? 1 : 0);
    assert.equal(f.state.disposes, phase === "after-create" ? 1 : 0);
  }
});
for (const field of ["api", "baseUrl", "thinkingLevelMap", "compat"]) test("undeclared initial " + field + " drift refuses before loading any extension", async () => {
  const f = fixture(); let reloads = 0; f.state.reload = () => reloads++;
  f.models[0][field] = field === "api" ? "wrong-api" : field === "baseUrl" ? "https://different.invalid" : field === "compat" ? { supportsStore: true } : { high: null };
  await assert.rejects(createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager }), /pi-model-config-mismatch/);
  assert.equal(reloads, 0); assert.equal(f.state.creates, 0);
});
test("private models file drift after session creation invalidates identity", async () => {
  const f = fixture(), result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  const disk = JSON.parse(readFileSync(f.modelPath, "utf8")); disk.providers.selected.headers = { Authorization: "synthetic-marker" };
  writeFileSync(f.modelPath, JSON.stringify(disk));
  await assert.rejects(() => result.configurationSnapshot(), error => error.message === "pi-model-config-stale");
});
test("a missing configured API-key secondary model does not silently narrow the accepted configuration", async () => {
  const f = fixture(); f.models.pop();
  await assert.rejects(createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager }), /pi-main-model-unavailable/);
  assert.equal(f.state.creates, 0);
});
test("SDK model lookup exceptions do not escape with provider or credential text", async () => {
  const f = fixture(); f.modelRuntime = { getError: () => undefined, getModel() { throw new Error("synthetic-private-marker"); } };
  await assert.rejects(createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager }), error => error.message === "pi-model-runtime-error");
  assert.equal(f.state.creates, 0);
});
test("model lookup reporting a deferred SDK error refuses before any extension load", async () => {
  const f = fixture(), original = f.modelRuntime; let reloads = 0;
  f.state.reload = () => reloads++;
  f.modelRuntime = { getError: () => f.state.modelError, getModel(provider, id) {
    const model = original.getModel(provider, id); f.state.modelError = "synthetic-private-late-error"; return model;
  } };
  await assert.rejects(createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager }), error => error.message === "pi-model-runtime-error");
  assert.equal(reloads, 0); assert.equal(f.state.creates, 0);
});
test("a deferred SDK lookup error also invalidates an existing session snapshot immediately", async () => {
  const f = fixture(), original = f.modelRuntime;
  f.modelRuntime = { getError: () => f.state.modelError, getModel(provider, id) {
    const model = original.getModel(provider, id);
    if (f.state.lateError) f.state.modelError = "synthetic-private-late-error";
    return model;
  } };
  const result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  f.state.lateError = true;
  await assert.rejects(() => result.configurationSnapshot(), error => error.message === "pi-model-runtime-error");
});

for (const phase of ["initial", "reload", "create"]) test("runtime check at " + phase + " prevents unsafe session delivery", async () => {
  const f = fixture();
  f.state.changed = phase === "initial";
  f.state.check = () => { if (f.state.changed) throw new Error("synthetic-runtime-changed"); };
  if (phase === "reload") f.state.reload = () => { f.state.changed = true; };
  if (phase === "create") {
    const original = f.sdk;
    f.sdk = { ...original, async createAgentSessionFromServices(options) {
      const result = await original.createAgentSessionFromServices(options); f.state.changed = true; return result;
    } };
  }
  await assert.rejects(createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager }), /synthetic-runtime-changed/);
  assert.equal(f.state.loads, phase === "initial" ? 0 : 1);
  assert.equal(f.state.creates, phase === "create" ? 1 : 0);
  assert.equal(f.state.disposes, phase === "create" ? 1 : 0);
});
test("snapshot waits for runtime check and refuses a failed check", async () => {
  const f = fixture(), result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  let release, delivered = false;
  const barrier = new Promise(resolve => { release = resolve; });
  f.state.check = () => barrier;
  const pending = Promise.resolve(result.configurationSnapshot()).then(snapshot => { delivered = true; return snapshot; });
  await Promise.resolve(); assert.equal(delivered, false);
  release(); assert.match((await pending).configIdentity, /^[0-9a-f]{64}$/);
  f.state.check = () => { throw new Error("synthetic-runtime-changed"); };
  await assert.rejects(async () => result.configurationSnapshot(), /synthetic-runtime-changed/);
});
test("configuration digest mismatch refuses resources and SDK creation", async () => {
  const f = fixture();
  await assert.rejects(createOfficialSessionFactory({ ...f, runtimeHandle: { ...f.runtimeHandle, configurationDigest: "0".repeat(64) } })({ cwd: f.cwd, sessionManager: f.sessionManager }), /pi-session-model-configuration/);
  assert.equal(f.state.loads, 0); assert.equal(f.state.creates, 0);
});
test("each new session rechecks runtime even with one factory", async () => {
  const f = fixture(), create = createOfficialSessionFactory(f);
  await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal(f.state.checks, 6);
  f.state.check = () => { throw new Error("synthetic-runtime-changed"); };
  await assert.rejects(create({ cwd: f.cwd, sessionManager: f.sessionManager }), /synthetic-runtime-changed/);
  assert.equal(f.state.loads, 2); assert.equal(f.state.creates, 2);
});

for (const field of ["missing", "check", "configurationDigest", "modelRuntime"]) test("runtime handle rejects " + field + " without optional bypass", () => {
  const f = fixture(), handle = { ...f.runtimeHandle };
  if (field === "check") handle.check = undefined;
  if (field === "configurationDigest") handle.configurationDigest = "unknown";
  if (field === "modelRuntime") handle.modelRuntime = {};
  assert.throws(() => createOfficialSessionFactory({ ...f, runtimeHandle: field === "missing" ? undefined : handle }), /pi-session-(runtime-handle|sdk-incompatible)/);
  assert.equal(f.state.loads, 0); assert.equal(f.state.creates, 0);
});
test("factory captures runtime handle members rather than later caller replacements", async () => {
  const f = fixture(), handle = { ...f.runtimeHandle }, create = createOfficialSessionFactory({ ...f, runtimeHandle: handle });
  handle.check = () => { throw new Error("replacement must not run"); };
  handle.modelRuntime = {}; handle.configurationDigest = "0".repeat(64);
  await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal(f.state.checks, 3); assert.equal(f.state.creates, 1);
});
test("initial runtime failure occurs before default settings storage construction", async () => {
  const f = fixture(); let settingsCalls = 0;
  f.state.check = () => { throw new Error("synthetic-runtime-changed"); };
  const sdk = Object.freeze({ ...f.sdk, SettingsManager: Object.freeze({ fromStorage() { settingsCalls++; throw new Error("unexpected storage access"); } }) });
  await assert.rejects(createOfficialSessionFactory({ ...f, sdk, settings: undefined })({ cwd: f.cwd, sessionManager: f.sessionManager }), /synthetic-runtime-changed/);
  assert.equal(settingsCalls, 0); assert.equal(f.state.loads, 0); assert.equal(f.state.creates, 0);
});
test("real self-owned runtime initializer composes with sessions and detects credential override", async () => {
  const f = fixture(); let credentials = [], runtimeCreates = 0;
  class ScopedRuntime {
    getModel(...args) { return f.modelRuntime.getModel(...args); }
    getError() { return f.modelRuntime.getError(); }
    getProvider() { throw Error("unexpected provider discovery"); }
    getAuth() { throw Error("unexpected auth resolution"); }
    checkAuth() { throw Error("unexpected auth check"); }
    async listCredentials() { return structuredClone(credentials); }
  }
  Object.freeze(ScopedRuntime.prototype);
  const runtime = new ScopedRuntime();
  const sdk = Object.freeze({ ...f.sdk, ModelRuntime: Object.freeze({ async create(options) {
    runtimeCreates++; assert.equal(options.allowModelNetwork, false); assert.equal(options.refreshOnCreate, false);
    assert.deepEqual(JSON.parse(readFileSync(options.modelsPath, "utf8")), JSON.parse(readFileSync(f.modelPath, "utf8")));
    return runtime;
  } }) });
  class InMemoryModelsStore {}
  class InMemoryCredentialStore {}
  Object.freeze(InMemoryModelsStore.prototype); Object.freeze(InMemoryCredentialStore.prototype);
  const initialize = createOfficialRuntimeInitializer({ sdk, ai: Object.freeze({ InMemoryModelsStore, InMemoryCredentialStore }), manifest: f.manifest, instanceRoot: f.instanceRoot });
  const handle = await initialize(); assert.equal(await initialize(), handle);
  const create = createOfficialSessionFactory({ ...f, sdk, runtimeHandle: handle });
  const first = await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  const second = await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.equal(runtimeCreates, 1);
  assert.deepEqual(await first.configurationSnapshot(), await second.configurationSnapshot());
  credentials = [{ providerId: "selected", type: "api_key" }];
  await assert.rejects(first.configurationSnapshot(), /pi-runtime-auth-owner-conflict/);
  await assert.rejects(second.configurationSnapshot(), /pi-runtime-auth-owner-conflict/);
});

test("modern file runtime detects image MIME only from admitted supervisor bytes", async () => {
  const f = fileRuntimeFixture();
  const bytes = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+c4M8AAAAASUVORK5CYII=", "base64");
  const original = f.options.supervisor.call.bind(f.options.supervisor);
  f.options.supervisor.call = async (method, args) => method === "ordinary_read"
    ? { data_b64: bytes.toString("base64"), total_bytes: bytes.length, content_digest: "f".repeat(64) }
    : original(method, args);
  f.options.sdk = Object.freeze({ ...f.options.sdk, createReadToolDefinition: (cwd, options) => ({ name: "read", label: "read", description: "read", parameters: {},
    async execute(_id, input) {
      const path = join(cwd, input.path);
      const mime = await options.operations.detectImageMimeType(path);
      assert.equal(mime, "image/png");
      return { content: [{ type: "image", mimeType: mime, data: (await options.operations.readFile(path)).toString("base64") }] };
    } }) });
  const runtime = await createOfficialFileRuntime(f.options, f.target);
  try {
    const result = await readRuntimeFile(f, "image-call");
    assert.equal(result.content[0].type, "image"); assert.equal(result.content[0].mimeType, "image/png");
    assert.equal(result.content[0].data, bytes.toString("base64"));
  } finally { await runtime.dispose(); }
});

function todoFixture() {
  const f = fixture(), path = join(f.runtimeRoot, "todo.js");
  writeFileSync(path, "// synthetic extension; never executed");
  f.manifest.plugins = ["pi-todo"];
  f.manifest.plugin_capabilities = { "pi-todo": { capability_id: "todo", model_tools: ["todo"] } };
  f.installed.resources.extensions = [{ id: "pi-todo", capability_id: "todo", path: "todo.js" }];
  const registered = { definition: { name: "todo", execute: async () => ({ content: [] }) }, sourceInfo: {} };
  f.state.extensionTools = new Map([[path, new Map([["todo", registered]])]]);
  return Object.assign(f, { registered, todoPath: path });
}

test("explicit selected Todo remains an SDK extension tool and joins the active allowlist", async () => {
  const f = todoFixture(), create = createOfficialSessionFactory(f);
  f.manifest.plugin_capabilities["pi-todo"].model_tools = [];
  const result = await create({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.deepEqual(f.state.options.tools, ["synthetic_read", "todo"]);
  assert.deepEqual(f.state.options.customTools.map(tool => tool.name), ["synthetic_read"]);
  await result.configurationSnapshot();
  f.state.extensionTools.get(f.todoPath).set("todo", { ...f.registered });
  await assert.rejects(result.configurationSnapshot(), /pi-session-extension-tools/);
});

for (const change of ["drop", "definition", "execute", "late-collision"]) test("public extension tools invalidate old configuration on " + change, async () => {
  const f = todoFixture();
  f.extensionFactories = [{ name: "synthetic-collision", factory() {} }];
  f.state.inlineTools = new Map();
  const result = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  if (change === "drop") f.state.extensionTools.get(f.todoPath).clear();
  if (change === "definition") f.registered.definition = { ...f.registered.definition };
  if (change === "execute") f.registered.definition.execute = async () => ({ content: [] });
  if (change === "late-collision") f.state.inlineTools.set("todo", f.registered);
  await assert.rejects(result.configurationSnapshot(), /pi-session-extension-tools/);
});

test("undeclared extension tools stay excluded and declarations bind ConfigIdentity even when disabled", async () => {
  const f = todoFixture(); f.state.activeTools = ["synthetic_read"];
  const first = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  const before = await first.configurationSnapshot();
  f.manifest.plugin_capabilities["pi-todo"].model_tools = [];
  const second = await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.deepEqual(f.state.options.tools, ["synthetic_read"]);
  const after = await second.configurationSnapshot();
  assert.notEqual(before.configIdentity, after.configIdentity);
  assert.equal(before.runtimeIdentity, after.runtimeIdentity);
});

for (const problem of ["wrong-cap", "missing", "wrong-name", "noncallable", "collision", "own-collision"]) test("explicit extension tool rejects " + problem + " before SDK creation", async () => {
  const f = todoFixture();
  if (problem === "wrong-cap") f.installed.resources.extensions[0].capability_id = "foreign";
  if (problem === "missing") f.state.extensionTools.get(f.todoPath).clear();
  if (problem === "wrong-name") f.registered.definition.name = "different";
  if (problem === "noncallable") f.registered.definition.execute = null;
  if (problem === "collision") {
    f.extensionFactories = [{ name: "synthetic-collision", factory() {} }];
    f.state.inlineTools = new Map([["todo", f.registered]]);
  }
  if (problem === "own-collision") f.toolDefinitions[0].name = "todo";
  await assert.rejects(createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager }), /pi-(resource|session-extension-tools)/);
  assert.equal(f.state.creates, 0);
});

test("public SDK tool composition also works when user ID equals its capability ID", async () => {
  const f = todoFixture(); f.manifest.plugins = ["todo"];
  f.manifest.plugin_capabilities = { todo: f.manifest.plugin_capabilities["pi-todo"] };
  await createOfficialSessionFactory(f)({ cwd: f.cwd, sessionManager: f.sessionManager });
  assert.ok(f.state.options.tools.includes("todo"));
});

test("resource publisher binds ready and completed transitions without extra inference or SDK loads", async () => {
  const f = resourceRuntimeFixture();
  const runtime = await createOfficialFileRuntime(f.options, f.target);
  const first = f.rpc.filter(row => row[0] === "diagnostic_resource_observation");
  assert.equal(first.length, 1); assert.equal(first[0][1].kind, "loaded");
  assert.equal(first[0][1].session_id, "native-session");
  assert.equal(first[0][1].generation, 1);
  assert.equal(first[0][1].snapshot.observation.rolesEvidence, "selection-only");
  await runtime.newSession();
  const rows = f.rpc.filter(row => row[0] === "diagnostic_resource_observation");
  assert.equal(rows.some(row => row[1].kind === "retired" && row[1].generation === 1), true);
  assert.equal(rows.some(row => row[1].kind === "loaded" && row[1].generation === 2), true);
  assert.equal(f.state.runtimeCalls.some(row => row[0] === "prompt"), false);
  await runtime.dispose();
  assert.equal(f.rpc.filter(row => row[0] === "diagnostic_resource_observation" && row[1].kind === "retired" && row[1].generation === 2).length, 1);
});
test("resource metadata rejection cannot publish a replacement or reopen the retired session", async () => {
  const f = resourceRuntimeFixture(), runtime = await createOfficialFileRuntime(f.options, f.target);
  f.state.observationFailure = true;
  await assert.rejects(runtime.newSession());
  await assert.rejects(runtime.resourceSnapshot());
  await assert.rejects(runtime.dispose());
});

test("private semantic model descriptions include real OAuth roles with config=null and exclude headers/body hashes",async()=>{
 const f=fixture(),sentinel="private OAuth header fixture never exported";
 f.manifest.provider_bindings.selected={logical_id:"synthetic",auth_kind:"oauth",owner:"pi-native"};f.manifest.model_configuration.providers.selected={logical_id:"synthetic",auth_kind:"oauth",owner:"pi-native",credential_ref:null,config:null};
 f.manifest.model_bindings.task_keeper_reader={provider:"selected",model:"other"};writeFileSync(f.modelPath,JSON.stringify({providers:{}}),{mode:0o600});
 f.models[0].headers={Authorization:sentinel};f.models[1].headers={Authorization:sentinel};
 const result=await createOfficialSessionFactory(f)({cwd:f.cwd,sessionManager:f.sessionManager}),rows=await result.semanticModelDescriptions();
 assert.deepEqual(rows.map(row=>row.role_id),["main","task_keeper_reader"]);assert.equal(rows[1].description.contextWindow,128000);
 const body=JSON.stringify(rows);assert.equal(body.includes("headers"),false);assert.equal(body.includes(sentinel),false);assert.equal(body.includes(createHash("sha256").update(sentinel).digest("hex")),false);assert.ok(Object.isFrozen(rows));
 f.models[1].maxTokens++;await assert.rejects(result.semanticModelDescriptions(),/pi-session-model-changed/);
});
test("private role description getter observes original configuration guard and takes no caller role/model",async()=>{
 const f=fixture(),result=await createOfficialSessionFactory(f)({cwd:f.cwd,sessionManager:f.sessionManager});const first=await result.semanticModelDescriptions();
 assert.equal(first.length,1);f.state.check=()=>{throw Error("original runtime source stale");};await assert.rejects(result.semanticModelDescriptions(),/original runtime source stale/);
});
