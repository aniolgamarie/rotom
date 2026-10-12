import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync, symlinkSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { main, launch, parseOfficialArguments, resolveOfficialPackages, officialLaunchDiagnostic } from "../official-launch.ts";
import { digest, ProtocolError } from "../managed-types.ts";
import { SupervisorClient } from "../supervisor-client.ts";
import { mayTransformHistory } from "../../packages/runtime-ui/capability-policy.mjs";

test("launcher stderr diagnostic exposes only captured fixed local codes, never foreign error data", () => {
  let known;
  try { parseOfficialArguments(["--unknown-synthetic-option"]); } catch (error) { known = error; }
  known.message = "synthetic-secret/path";
  assert.deepEqual(officialLaunchDiagnostic(known), { message: "Pi official launcher failed: pi-launch-arguments.\n", exitCode: 2 });
  const unknown = new Error("synthetic-secret/path");
  unknown.exitCode = 4;
  const generic = { message: "Pi official launcher failed; check deployment and runtime readiness.\n", exitCode: 5 };
  assert.deepEqual(officialLaunchDiagnostic(unknown), generic);
  assert.deepEqual(officialLaunchDiagnostic({ message: "pi-launch-arguments", exitCode: 4 }), generic);
  assert.deepEqual(officialLaunchDiagnostic(new Proxy({}, { get() { throw new Error("must not inspect"); }, getPrototypeOf() { throw new Error("must not inspect"); } })), generic);
  assert.deepEqual(officialLaunchDiagnostic(new known.constructor("synthetic-secret/path", 4)), generic);
});

for (const stage of ["handshake", "runtime-init", "session-create", "frontend-run"]) {
  test("foreign launcher failure reports fixed " + stage + " stage without reading secret getters", async t => {
    const f = fixture(t), error = new Error("synthetic-secret/rawpath");
    error.exitCode = 4;
    Object.defineProperty(error, "code", { get() { throw new Error("must not read code"); } });
    Object.defineProperty(error, "cause", { get() { throw new Error("must not read cause"); } });
    if (stage === "handshake") f.dependencies.supervisorFactory = () => ({ async call() { throw error; } });
    if (stage === "runtime-init") f.dependencies.initializeRuntime = () => async () => { throw error; };
    if (stage === "session-create") f.dependencies.createRuntime = async () => { throw error; };
    if (stage === "frontend-run") f.dependencies.importModule = async url => url.endsWith("/sdk/dist/index.js")
      ? { ...f.sdk, async runPrintMode() { throw error; } } : f.ai;
    let caught;
    try { await main(["--manifest", f.manifestPath, "--print", "synthetic"], f.dependencies); } catch (value) { caught = value; }
    assert.deepEqual(officialLaunchDiagnostic(caught), { message: "Pi official launcher failed: pi-official-" + stage + "-failed.\n", exitCode: 4 });
  });
}
for (const code of ["PI_CONTROL_UNAVAILABLE", "PI_CONTROL_REJECTED"]) {
  test("handshake reveals only fixed owned protocol class " + code, async t => {
    const f = fixture(t), error = new ProtocolError(code, 4);
    error.message = "synthetic-secret/rawpath";
    Object.defineProperty(error, "cause", { get() { throw new Error("must not read"); } });
    f.dependencies.supervisorFactory = () => ({ async call() { throw error; } });
    await assert.rejects(main(["--manifest", f.manifestPath, "--print"], f.dependencies), caught =>
      officialLaunchDiagnostic(caught).message === "Pi official launcher failed: pi-official-handshake-control-" +
        (code === "PI_CONTROL_UNAVAILABLE" ? "unavailable" : "rejected") + ".\n");
  });
}
test("foreign or accessor-shaped protocol errors cannot publish a control classification", async t => {
  for (const foreign of [{ code: "PI_CONTROL_REJECTED", exitCode: 4 },
    Object.defineProperty(new ProtocolError("PI_CONTROL_UNAVAILABLE", 4), "code", { get() { throw new Error("synthetic-secret"); } }),
    new Proxy({}, { get() { throw new Error("synthetic-secret"); }, getPrototypeOf() { throw new Error("synthetic-secret"); } })]) {
    const f = fixture(t); f.dependencies.supervisorFactory = () => ({ async call() { throw foreign; } });
    await assert.rejects(main(["--manifest", f.manifestPath, "--print"], f.dependencies), caught =>
      officialLaunchDiagnostic(caught).message === "Pi official launcher failed: pi-official-handshake-failed.\n");
  }
});

const symbol = Symbol.for("agentcfg.pi.runtime.v1");
function fixture(t) {
  const ambient = Object.fromEntries(["PI_OFFLINE", "PI_SKIP_VERSION_CHECK", "TMUX"].map(name => [name, process.env[name]]));
  t.after(() => {
    for (const [name, value] of Object.entries(ambient)) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
  });
  const root = mkdtempSync(join(tmpdir(), "official-launch-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const instanceRoot = join(root, "instance"), runtimeRoot = join(root, "runtime");
  for (const directory of [instanceRoot, join(instanceRoot, "pi-home"), join(instanceRoot, "user-home"), runtimeRoot,
    join(runtimeRoot, "runtime"), join(runtimeRoot, "slice")]) mkdirSync(directory, { mode: 0o700 });
  const manifest = { schema_version: 1, profile_id: "pi-base", engine: "node", plugins: [], options: { permissions: {}, paths: {} },
    permission_policy: { schema_version: 1, default: "deny", rules: [] } };
  const installed = { schema_version: 2, profile_id: "pi-base", engine: "node", sdk_package: "@fixture/sdk", sdk_version: "1.0.1",
    ai_package: "@fixture/ai", ai_version: "1.0.2", package_path: "slice/package.json", entrypoint: "slice/node_modules/@fixture/sdk/dist/index.js", resources: {},
    lock_identity: "a".repeat(64), slice_identity: "b".repeat(64), runtime_identity: "c".repeat(64),
    toolchains: { node: process.version }, platform: process.platform + "-" + (process.arch === "x64" ? "x86_64" : process.arch) };
  const manifestPath = join(instanceRoot, "pi-home/agentcfg-manifest.json");
  const save = (path, value) => writeFileSync(path, JSON.stringify(value) + "\n", { mode: 0o600 });
  save(manifestPath, manifest); save(join(runtimeRoot, "runtime/profile.json"), installed);
  save(join(runtimeRoot, "slice/package.json"), { name: "synthetic-slice", dependencies: { "@fixture/sdk": "1.0.1" } });
  for (const [name, version, entry] of [["sdk", "1.0.1", "dist/index.js"], ["ai", "1.0.2", "index.js"]]) {
    const directory = join(runtimeRoot, "slice/node_modules/@fixture", name);
    mkdirSync(join(directory, "dist"), { recursive: true, mode: 0o700 });
    save(join(directory, "package.json"), { name: "@fixture/" + name, version, type: "module",
      exports: { ".": { types: "./index.d.ts", import: "./" + entry } } });
    writeFileSync(join(directory, entry), "export const synthetic = true;\n");
  }
  const owner = { role: "manager", runtime_identity: installed.runtime_identity, slice_identity: installed.slice_identity,
    instance_id: "fixture", manager_activation_id: "manager", owner_nonce: "nonce", protected_roots: [] };
  const events = [], ai = Object.freeze({ synthetic: true });
  const sdk = Object.freeze({
    SessionManager: Object.freeze({ create(cwd, directory) { events.push(["session", cwd, directory]); return Object.freeze({}); } }),
    InteractiveMode: class { constructor(runtime, options) { events.push(["tui", runtime, options]); } async run() { events.push("run-tui"); } },
    async runPrintMode(runtime, options) { events.push(["print", runtime, options]); return 7; },
    async runRpcMode(runtime) { events.push(["rpc", runtime]); },
  });
  const runtime = Object.freeze({ async dispose() { events.push("dispose"); } });
  let options;
  const supervisor = { async call(method, args) { events.push([method, args]); return structuredClone(owner); } };
  const dependencies = {
    runtimeRoot, cwd: root,
    env: { HOME: join(instanceRoot, "user-home"), PI_CODING_AGENT_DIR: join(instanceRoot, "pi-home"),
      PI_CODING_AGENT_SESSION_DIR: join(instanceRoot, "pi-home/sessions"), AGENTCFG_PYTHON: join(root, "python"),
      AGENTCFG_SUPERVISOR_CLIENT: join(root, "client"), AGENTCFG_SUPERVISOR_ENDPOINT: join(root, "control"), AGENTCFG_SUPERVISOR_CAPABILITY: "synthetic" },
    supervisorFactory(config) { events.push(["supervisor", config]); return supervisor; },
    async importModule(url) { events.push(["import", url]); return url.endsWith("/sdk/dist/index.js") ? sdk : ai; },
    initializeRuntime(input) { events.push(["initializer", input]); return async () => { events.push("initialize"); return Object.freeze({ synthetic: true }); }; },
    async createRuntime(input, target) { options = input; events.push(["create", target]); return runtime; },
    writeOutput(text) { events.push(["output", text]); },
  };
  return { root, instanceRoot, runtimeRoot, manifestPath, manifest, installed, owner, sdk, ai, supervisor, dependencies, events, runtime, save,
    get options() { return options; } };
}

test("help validates syntax but never reads account or initializes SDK", async t => {
  const f = fixture(t); rmSync(f.manifestPath);
  assert.equal(await main(["--manifest", f.manifestPath, "--help"], f.dependencies), 0);
  assert.deepEqual(f.events.map(row => row[0]), ["output"]);
});

test("public import-only SDK and AI exports resolve inside the selected slice without import", t => {
  const f = fixture(t);
  for (const [name, entry] of [["sdk", "dist/index.js"], ["ai", "index.js"]]) {
    const path = join(f.runtimeRoot, "slice/node_modules/@fixture", name, "package.json");
    const document = JSON.parse(readFileSync(path, "utf8"));
    document.exports = { ".": { types: "./index.d.ts", import: "./" + entry } };
    f.save(path, document);
  }
  const result = resolveOfficialPackages({ installed: f.installed, runtimeRoot: f.runtimeRoot });
  assert.equal(result.sdkEntry, join(f.runtimeRoot, f.installed.entrypoint));
  assert.equal(result.aiEntry, join(f.runtimeRoot, "slice/node_modules/@fixture/ai/index.js"));
  assert.deepEqual(f.events, []);
});

test("public ESM resolution selects import when a different require export also exists", t => {
  const f = fixture(t);
  for (const [name, entry] of [["sdk", "dist/index.js"], ["ai", "index.js"]]) {
    const directory = join(f.runtimeRoot, "slice/node_modules/@fixture", name);
    const path = join(directory, "package.json"), document = JSON.parse(readFileSync(path, "utf8"));
    document.exports = { ".": { import: "./" + entry, require: "./wrong-require.cjs" } };
    f.save(path, document); writeFileSync(join(directory, "wrong-require.cjs"), "throw new Error('must not load');\n");
  }
  const result = resolveOfficialPackages({ installed: f.installed, runtimeRoot: f.runtimeRoot });
  assert.equal(result.sdkEntry, join(f.runtimeRoot, f.installed.entrypoint));
  assert.equal(result.aiEntry, join(f.runtimeRoot, "slice/node_modules/@fixture/ai/index.js"));
  assert.deepEqual(f.events, []);
});

test("public resolver rejects an AI package borrowed from outside the selected slice", t => {
  const f = fixture(t);
  rmSync(join(f.runtimeRoot, "slice/node_modules/@fixture/ai"), { recursive: true });
  const directory = join(f.runtimeRoot, "node_modules/@fixture/ai"); mkdirSync(directory, { recursive: true, mode: 0o700 });
  f.save(join(directory, "package.json"), { name: "@fixture/ai", version: "1.0.2", type: "module",
    exports: { ".": { import: "./index.js" } } });
  writeFileSync(join(directory, "index.js"), "throw new Error('outside slice');\n");
  assert.throws(() => resolveOfficialPackages({ installed: f.installed, runtimeRoot: f.runtimeRoot }), error => error.message === "pi-sdk-path");
  assert.deepEqual(f.events, []);
});

for (const argv of [["--model", "private-marker"], ["--extension", "private-marker"], ["--unknown"], ["--thinking"],
  ["--thinking", "extreme"], ["--mode", "private-marker"], ["--print", "--mode", "rpc"], ["--mode", "rpc", "prompt"], ["--manifest", "/foreign"], ["--thinking", "low", "--thinking", "high"]]) {
  test("unknown/protected arguments fail before initialization: " + argv[0], async t => {
    const f = fixture(t);
    await assert.rejects(main(["--manifest", f.manifestPath, ...argv], f.dependencies), error => error.exitCode === 2 && !error.message.includes("private-marker"));
    assert.deepEqual(f.events, []);
  });
}

test("separator preserves opaque prompt parameters", () => {
  assert.deepEqual(parseOfficialArguments(["--thinking", "high", "--", "--model", "ordinary text"]),
    { mode: "tui", thinking: "high", help: false, messages: ["--model", "ordinary text"] });
});

for (const [argv, mode, code] of [[[], "tui", 0], [["--print", "hello"], "print", 7], [["--mode", "rpc"], "rpc", 0]]) {
  test("main dispatches public " + mode + " and disposes its runtime", async t => {
    const f = fixture(t);
    assert.equal(await main(["--manifest", f.manifestPath, ...argv], f.dependencies), code);
    assert.equal(f.events.filter(row => row[0] === mode).length, 1);
    assert.equal(f.events.filter(row => row === "initialize").length, 1);
    assert.equal(f.events.at(-1), "dispose");
    assert.equal(globalThis[symbol], undefined);
    assert.deepEqual(f.options.extensionFactories, []);
  });
}

test("handshake mismatch blocks initializer and SDK sessions", async t => {
  const f = fixture(t); f.owner.runtime_identity = "d".repeat(64);
  await assert.rejects(main(["--manifest", f.manifestPath], f.dependencies));
  assert.equal(f.events.some(row => row === "initialize" || row[0] === "create"), false);
});

test("main fixed instance path and environment reject before supervisor/module import", async t => {
  const f = fixture(t); f.dependencies.env.HOME = f.root;
  await assert.rejects(main(["--manifest", f.manifestPath], f.dependencies));
  await assert.rejects(main(["--manifest", join(f.instanceRoot, "pi-home/../manifest.json")], f.dependencies));
  assert.deepEqual(f.events, []);
});

test("installed version/profile/unknown fields cannot select another runtime", async t => {
  const f = fixture(t);
  for (const change of [{ schema_version: 1 }, { profile_id: "pi-full" }, { platform: "foreign" }, { unknown: "private-marker" }, { toolchains: { node: "v0.0.0" } }]) {
    f.save(join(f.runtimeRoot, "runtime/profile.json"), { ...f.installed, ...change });
    await assert.rejects(main(["--manifest", f.manifestPath], f.dependencies), error => !error.message.includes("private-marker"));
    assert.equal(f.events.some(row => row === "initialize"), false);
  }
});

test("public resolution rejects mismatched entrypoint/version and external symlink", t => {
  const f = fixture(t);
  assert.equal(resolveOfficialPackages({ installed: f.installed, runtimeRoot: f.runtimeRoot }).sdkEntry, join(f.runtimeRoot, f.installed.entrypoint));
  for (const change of [{ entrypoint: "slice/node_modules/@fixture/sdk/dist/foreign.js" }, { sdk_version: "9.0.0" }, { ai_version: "9.0.0" }]) {
    assert.throws(() => resolveOfficialPackages({ installed: { ...f.installed, ...change }, runtimeRoot: f.runtimeRoot }));
  }
  const sdkRoot = join(f.runtimeRoot, "slice/node_modules/@fixture/sdk");
  rmSync(sdkRoot, { recursive: true });
  const foreign = join(f.root, "foreign"); mkdirSync(join(foreign, "dist"), { recursive: true });
  f.save(join(foreign, "package.json"), { name: "@fixture/sdk", version: "1.0.1", exports: "./dist/index.js" });
  writeFileSync(join(foreign, "dist/index.js"), "export const foreign = true;\n"); symlinkSync(foreign, sdkRoot);
  assert.throws(() => resolveOfficialPackages({ installed: f.installed, runtimeRoot: f.runtimeRoot }));
});

test("configuration checks original deployment bytes without hashing secrets", async t => {
  const f = fixture(t);
  await main(["--manifest", f.manifestPath, "--print"], f.dependencies);
  const expected = { policyDigest: digest(f.manifest.permission_policy), projectConstraintsDigest: digest({ cwd: f.root,
    permissions: {}, paths: {}, protectedRoots: [] }) };
  assert.deepEqual(f.options.configuration(f.root), expected);
  f.save(f.manifestPath, { ...f.manifest, marker: "synthetic-private-marker" });
  assert.throws(() => f.options.configuration(f.root), error => !error.message.includes("synthetic-private-marker"));
});

test("UI global has frozen selected context and cannot replace another activation", async t => {
  const f = fixture(t), foreign = Object.freeze({ sentinel: true });
  globalThis[symbol] = foreign; t.after(() => { delete globalThis[symbol]; });
  await assert.rejects(main(["--manifest", f.manifestPath], f.dependencies));
  assert.equal(globalThis[symbol], foreign);
  delete globalThis[symbol];
  f.dependencies.createRuntime = async options => {
    const context = globalThis[symbol];
    assert.equal(context.supervisor, f.supervisor);
    assert.deepEqual(context.manifest, f.manifest);
    assert.deepEqual(context.installed, f.installed);
    assert(Object.isFrozen(context) && Object.isFrozen(context.manifest.options));
    return f.runtime;
  };
  assert.equal(await main(["--manifest", f.manifestPath], f.dependencies), 0);
  assert.equal(globalThis[symbol], undefined);
});

test("actual launcher context isolates managed history transformations across awaits", async t => {
  const f = fixture(t);
  let scope, observed = false;
  f.dependencies.createRuntime = async () => {
    const context = globalThis[symbol];
    scope = context.managedRequestScope;
    assert.equal(mayTransformHistory(context), true);
    await scope.run(Object.freeze({ requestId: "managed-test" }), async () => {
      await Promise.resolve();
      assert.equal(mayTransformHistory(context), false);
      observed = true;
    });
    assert.equal(mayTransformHistory(context), true);
    return f.runtime;
  };
  assert.equal(await main(["--manifest", f.manifestPath], f.dependencies), 0);
  assert.equal(observed, true);
  assert.equal(scope.getStore(), undefined);
  assert.equal(globalThis[symbol], undefined);
});

test("mode failure is redacted and runtime cleanup still runs", async t => {
  const f = fixture(t);
  f.dependencies.importModule = async url => url.endsWith("/sdk/dist/index.js") ? Object.freeze({ ...f.sdk,
    async runPrintMode() { throw new Error("synthetic-secret-body"); } }) : f.ai;
  await assert.rejects(main(["--manifest", f.manifestPath, "--print"], f.dependencies), error => !error.message.includes("synthetic-secret-body"));
  assert.equal(f.events.at(-1), "dispose"); assert.equal(globalThis[symbol], undefined);
});

test("launch requires live deployment verifier even for injected runtime", async t => {
  const f = fixture(t);
  await assert.rejects(launch({ sdk: f.sdk, ai: f.ai, manifest: f.manifest, installed: f.installed, instanceRoot: f.instanceRoot,
    runtimeRoot: f.runtimeRoot, cwd: f.root, engine: "node", supervisor: f.supervisor, initializeRuntime: f.dependencies.initializeRuntime,
    createRuntime: f.dependencies.createRuntime }));
  assert.deepEqual(f.events, []);
});

for (const phase of ["import", "initializer", "create", "dispose"]) {
  test("failure at " + phase + " remains fixed and clears only owned global", async t => {
    const f = fixture(t);
    const marker = "synthetic-private-error-body";
    if (phase === "import") f.dependencies.importModule = async () => { throw new Error(marker); };
    if (phase === "initializer") f.dependencies.initializeRuntime = () => async () => { throw new Error(marker); };
    if (phase === "create") f.dependencies.createRuntime = async () => { throw new Error(marker); };
    if (phase === "dispose") f.dependencies.createRuntime = async () => Object.freeze({ async dispose() { throw new Error(marker); } });
    await assert.rejects(main(["--manifest", f.manifestPath], f.dependencies), error => !error.message.includes(marker) && [4, 5].includes(error.exitCode));
    assert.equal(globalThis[symbol], undefined);
  });
}

test("deployment change during async initialization blocks session creation", async t => {
  const f = fixture(t);
  f.dependencies.initializeRuntime = () => async () => {
    f.save(f.manifestPath, { ...f.manifest, marker: "synthetic-secret" });
    return Object.freeze({ synthetic: true });
  };
  await assert.rejects(main(["--manifest", f.manifestPath], f.dependencies), error => error.message === "pi-deployment-stale");
  assert.equal(f.events.some(row => row[0] === "session" || row[0] === "create"), false);
  assert.equal(globalThis[symbol], undefined);
});

test("configuration and policy refuse even a formatting-only deployment rewrite", async t => {
  const f = fixture(t); await main(["--manifest", f.manifestPath, "--print"], f.dependencies);
  assert.equal(f.options.policySnapshot().policy_digest, digest(f.manifest.permission_policy));
  writeFileSync(f.manifestPath, JSON.stringify(f.manifest, null, 2) + "\n");
  assert.throws(() => f.options.configuration(f.root), /pi-deployment-stale/);
  assert.throws(() => f.options.policySnapshot(), /pi-deployment-stale/);
});

test("package root resolution cannot fall back to an ancestor node_modules", t => {
  const f = fixture(t);
  const source = join(f.runtimeRoot, "slice/node_modules/@fixture/sdk");
  const outside = join(f.root, "node_modules/@fixture/sdk");
  mkdirSync(join(outside, "dist"), { recursive: true });
  f.save(join(outside, "package.json"), { name: "@fixture/sdk", version: "1.0.1", exports: "./dist/index.js" });
  writeFileSync(join(outside, "dist/index.js"), "export const foreign = true;\n");
  rmSync(source, { recursive: true });
  assert.throws(() => resolveOfficialPackages({ installed: f.installed, runtimeRoot: f.runtimeRoot }), /pi-sdk-path/);
});

for (const fault of ["mode", "symlink", "hardlink", "duplicate-json", "utf8"]) {
  test("private launch input rejects " + fault + " before SDK loading", async t => {
    const f = fixture(t);
    if (fault === "mode") {
      const { chmodSync } = await import("node:fs"); chmodSync(f.manifestPath, 0o644);
    }
    if (fault === "symlink") {
      const target = join(f.instanceRoot, "pi-home/copy.json"); f.save(target, f.manifest);
      rmSync(f.manifestPath); symlinkSync(target, f.manifestPath);
    }
    if (fault === "hardlink") {
      const { linkSync } = await import("node:fs"); linkSync(f.manifestPath, join(f.instanceRoot, "pi-home/alias.json"));
    }
    if (fault === "duplicate-json") writeFileSync(f.manifestPath, '{"profile_id":"pi-base","profile_id":"pi-base"}');
    if (fault === "utf8") writeFileSync(f.manifestPath, Buffer.from([0xff]));
    await assert.rejects(main(["--manifest", f.manifestPath], f.dependencies));
    assert.deepEqual(f.events, []);
  });
}

test("UI cancellation rejects safely and still invokes facade disposal", async t => {
  const f = fixture(t);
  f.dependencies.importModule = async url => url.endsWith("/sdk/dist/index.js") ? Object.freeze({ ...f.sdk,
    InteractiveMode: class { async run() { throw new DOMException("synthetic-private-prompt", "AbortError"); } } }) : f.ai;
  await assert.rejects(main(["--manifest", f.manifestPath], f.dependencies), error => !error.message.includes("synthetic-private-prompt"));
  assert.equal(f.events.at(-1), "dispose"); assert.equal(globalThis[symbol], undefined);
});

test("thinking level reaches session factory and prompt parameters reach public mode", async t => {
  const f = fixture(t);
  await main(["--manifest", f.manifestPath, "--thinking", "high", "--print", "--", "--model", "ordinary text"], f.dependencies);
  assert.equal(f.options.thinkingLevel, "high");
  assert.deepEqual(f.events.find(row => row[0] === "print")[2], { mode: "text", messages: ["--model", "ordinary text"] });
});

for (const guardState of ["valid", "missing"]) test("main self-owned file runtime checks public command guard " + guardState, async t => {
  const f = fixture(t);
  const protocol = JSON.parse(readFileSync(new URL("../../../../tests/fixtures/pi/model-configuration.json", import.meta.url), "utf8"));
  const groups = ["extensions", "skills", "prompts", "themes", "roles"];
  Object.assign(f.manifest, structuredClone(protocol.manifest), { bootstrap: false,
    model_bindings: { main: structuredClone(protocol.manifest.allowed_models[0]) },
    resources: Object.fromEntries(groups.map(name => [name, []])), resource_ids: Object.fromEntries(groups.map(name => [name, {}])) });
  f.installed.resources = Object.fromEntries(groups.map(name => [name, []]));
  f.save(f.manifestPath, f.manifest); f.save(join(f.runtimeRoot, "runtime/profile.json"), f.installed);
  f.save(join(f.instanceRoot, "pi-home/models.json"), protocol.native);
  writeFileSync(join(f.instanceRoot, "pi-home/AGENTS.md"), "Synthetic rules\n", { mode: 0o600 });
  writeFileSync(join(f.instanceRoot, "pi-home/APPEND_SYSTEM.md"), "Synthetic append\n", { mode: 0o600 });
  let modelCreates = 0, sessionCreates = 0, aborted = 0, disposed = 0, selected;
  const model = Object.freeze(structuredClone(protocol.effective_model));
  // 真实SDK方法在原型上；不可冻结own methods后要求Proxy替换其值。
  class ModelRuntimeFixture {
    getError() { return undefined; }
    getModel() { return model; }
    async listCredentials() { return []; }
    getProvider() { throw new Error("unexpected synthetic provider access"); }
    async getAuth() { throw new Error("unexpected synthetic auth access"); }
    async checkAuth() { throw new Error("unexpected synthetic auth refresh"); }
  }
  Object.freeze(ModelRuntimeFixture.prototype);
  const modelRuntime = new ModelRuntimeFixture();
  const sessionManager = Object.freeze({ getCwd: () => f.root, getSessionId: () => "native-session",
    getBranch: () => [], buildSessionContext: () => ({ messages: [], model: null }) });
  const loaderOptions = new WeakMap();
  const loadedExtensions = new WeakMap();
  class Loader {
    constructor(options) { loaderOptions.set(this, options); Object.freeze(this); }
    async reload() {
      const rows = [];
      for (const row of loaderOptions.get(this).extensionFactories) {
        const handlers = new Map();
        await row.factory({ on(name, handler) {
          const list = handlers.get(name) ?? []; list.push(handler); handlers.set(name, list);
        } });
        if (guardState === "missing") handlers.delete("user_bash");
        rows.push({ path: "<inline:" + row.name + ">", resolvedPath: "<inline:" + row.name + ">", handlers });
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
    getAppendSystemPrompt() { return loaderOptions.get(this).appendSystemPrompt.map(path => readFileSync(path, "utf8")); }
    getAppendSystemPromptSources() { return loaderOptions.get(this).appendSystemPrompt.map(path => ({ path })); }
    extendResources() {}
  }
  Object.freeze(Loader.prototype);
  const sdk = { ...f.sdk, DefaultResourceLoader: Loader,
    ModelRuntime: Object.freeze({ async create(options) {
      modelCreates++;
      assert.equal(options.allowModelNetwork, false); assert.equal(options.refreshOnCreate, false);
      assert.deepEqual(JSON.parse(readFileSync(options.modelsPath, "utf8")), protocol.native);
      return modelRuntime;
    } }),
    SessionManager: Object.freeze({ create: () => sessionManager }),
    SettingsManager: Object.freeze({ fromStorage(storage, options) {
      assert.deepEqual(options, { projectTrusted: false });
      let value; storage.withLock("global", text => { value = JSON.parse(text); });
      return Object.freeze({ getSettings: () => structuredClone(value),
        ...Object.fromEntries(["getPackages", "getExtensionPaths", "getSkillPaths", "getPromptTemplatePaths", "getThemePaths"].map(name => [name, () => []])) });
    } }),
    async createAgentSessionFromServices(options) {
      sessionCreates++; selected = options;
      assert.deepEqual(options.tools.toSorted(), ["edit", "find", "grep", "ls", "read", "rename", "write"]);
      assert.equal(options.noTools, "all");
      return { session: Object.freeze({ model, thinkingLevel: "medium", getActiveToolNames: () => [...options.tools],
        async abort() { aborted++; }, dispose() { disposed++; } }), extensionsResult: options.services.resourceLoader.getExtensions() };
    },
    async createAgentSessionRuntime(create, target) {
      const result = await create(target);
      return Object.freeze({ session: result.session, services: result.services, cwd: target.cwd,
        setBeforeSessionInvalidate() {}, setRebindSession() {}, async dispose() { result.session.dispose(); } });
    },
    async runPrintMode(runtime) {
      assert.equal(runtime.session.model, model);
      assert.equal(globalThis[symbol].manifest.profile_id, "pi-base");
      assert(selected.customTools.every(tool => typeof tool.execute === "function"));
      return 0;
    },
  };
  for (const [factory, name] of [["Read", "read"], ["Write", "write"], ["Edit", "edit"], ["Ls", "ls"], ["Find", "find"], ["Grep", "grep"]]) {
    sdk["create" + factory + "ToolDefinition"] = () => ({ name, label: name, description: name, parameters: {}, execute: async () => ({ content: [] }) });
  }
  sdk.createBashToolDefinition = () => { throw new Error("unselected Full factory"); };
  Object.freeze(sdk);
  class Store {} Object.freeze(Store.prototype);
  const ai = Object.freeze({ InMemoryModelsStore: Store, InMemoryCredentialStore: Store });
  f.dependencies.importModule = async url => url.endsWith("/sdk/dist/index.js") ? sdk : ai;
  f.dependencies.supervisorFactory = () => ({ async call(method, args) {
    if (method === "handshake") return structuredClone(f.owner);
    if (method === "ordinary_admission_retire") return { ...args, state: "retired" };
    throw new Error("unexpected synthetic RPC");
  } });
  delete f.dependencies.initializeRuntime; delete f.dependencies.createRuntime;
  if (guardState === "missing") {
    await assert.rejects(main(["--manifest", f.manifestPath, "--print"], f.dependencies), error => error.exitCode === 5);
    assert.equal(modelCreates, 1); assert.equal(sessionCreates, 0); assert.equal(aborted, 0); assert.equal(disposed, 0);
    assert.equal(globalThis[symbol], undefined); return;
  }
  assert.equal(await main(["--manifest", f.manifestPath, "--print"], f.dependencies), 0);
  assert.equal(modelCreates, 1); assert.equal(sessionCreates, 1); assert.equal(aborted, 1); assert.equal(disposed, 1);
  assert.equal(globalThis[symbol], undefined);
});

test("main authenticates through real SupervisorClient with only fake private transport", async t => {
  const f = fixture(t), methods = [];
  f.dependencies.supervisorFactory = options => new SupervisorClient({ ...options, invoke: async ({ request }) => {
    methods.push(request.method);
    assert.equal(request.method, "handshake"); assert.deepEqual(request.args, {});
    return JSON.stringify({ schema_version: 1, ok: true, result: f.owner });
  } });
  assert.equal(await main(["--manifest", f.manifestPath, "--print"], f.dependencies), 7);
  assert.deepEqual(methods, ["handshake"]);
});

test("ordinary multiline prompt stays private opaque message text", () => {
  assert.deepEqual(parseOfficialArguments(["--print", "first line\nsecond line"]).messages, ["first line\nsecond line"]);
});

test("cleanup preserves a foreign global installed after its own context", async t => {
  const f = fixture(t), foreign = Object.freeze({ foreign: true });
  t.after(() => { delete globalThis[symbol]; });
  f.dependencies.importModule = async url => url.endsWith("/sdk/dist/index.js") ? Object.freeze({ ...f.sdk,
    async runPrintMode() { globalThis[symbol] = foreign; return 0; } }) : f.ai;
  assert.equal(await main(["--manifest", f.manifestPath, "--print"], f.dependencies), 0);
  assert.equal(globalThis[symbol], foreign); assert.equal(f.events.at(-1), "dispose");
});

test("main disables background catalog/version and tmux probes before SDK imports and all callbacks", async t => {
  const f = fixture(t), observed = [];
  Object.assign(process.env, { PI_OFFLINE: "0", PI_SKIP_VERSION_CHECK: "0", TMUX: "synthetic-private-tmux" });
  Object.assign(f.dependencies.env, { PI_OFFLINE: "0", PI_SKIP_VERSION_CHECK: "0", TMUX: "synthetic-private-tmux" });
  const check = phase => {
    observed.push(phase);
    for (const env of [process.env, f.dependencies.env]) {
      assert.equal(env.PI_OFFLINE, "1"); assert.equal(env.PI_SKIP_VERSION_CHECK, "1"); assert.equal(env.TMUX, undefined);
    }
  };
  const imported = f.dependencies.importModule, initialized = f.dependencies.initializeRuntime, created = f.dependencies.createRuntime;
  const sdk = Object.freeze({ ...f.sdk, InteractiveMode: class { async run() { check("mode"); } } });
  f.dependencies.importModule = async url => { check("import"); await imported(url); return url.endsWith("/sdk/dist/index.js") ? sdk : f.ai; };
  f.dependencies.initializeRuntime = input => { check("initializer"); return initialized(input); };
  f.dependencies.createRuntime = async (...args) => { check("runtime"); return created(...args); };
  assert.equal(await main(["--manifest", f.manifestPath], f.dependencies), 0);
  assert.deepEqual(observed, ["import", "import", "initializer", "runtime", "mode"]);
  check("after-return");
});

test("direct launch establishes public probe switches and keeps them after failure", async t => {
  const f = fixture(t), observed = [];
  Object.assign(process.env, { PI_OFFLINE: "0", PI_SKIP_VERSION_CHECK: "0", TMUX: "synthetic-private-tmux" });
  await assert.rejects(launch({ sdk: f.sdk, ai: f.ai, manifest: f.manifest, installed: f.installed, instanceRoot: f.instanceRoot,
    runtimeRoot: f.runtimeRoot, cwd: f.root, engine: "node", supervisor: f.supervisor, verifyDeployment() {},
    initializeRuntime() {
      observed.push("initializer");
      assert.equal(process.env.PI_OFFLINE, "1"); assert.equal(process.env.PI_SKIP_VERSION_CHECK, "1"); assert.equal(process.env.TMUX, undefined);
      return async () => { throw new Error("synthetic-private-initialization-error"); };
    }, createRuntime: f.dependencies.createRuntime }), error => error.message === "pi-official-runtime-init-failed");
  assert.deepEqual(observed, ["initializer"]);
  assert.equal(process.env.PI_OFFLINE, "1"); assert.equal(process.env.PI_SKIP_VERSION_CHECK, "1"); assert.equal(process.env.TMUX, undefined);
});

test("help does not alter ambient or injected probe environment", async t => {
  const f = fixture(t);
  const values = { PI_OFFLINE: "0", PI_SKIP_VERSION_CHECK: "0", TMUX: "synthetic-private-tmux" };
  Object.assign(process.env, values); Object.assign(f.dependencies.env, values);
  assert.equal(await main(["--manifest", f.manifestPath, "--help"], f.dependencies), 0);
  assert.deepEqual(await launch({ argv: ["--help"] }), { code: 0, help: "agentcfg run pi -- [--print | --mode rpc] [--thinking LEVEL] [--] [prompt ...]" });
  for (const [name, value] of Object.entries(values)) {
    assert.equal(process.env[name], value); assert.equal(f.dependencies.env[name], value);
  }
});
