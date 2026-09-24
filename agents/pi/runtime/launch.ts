import { installSessionCompatibility } from "./session-compatibility.ts";
import { OrdinaryOperations } from "./ordinary-operations.ts";
import { ReadseekController } from "./readseek-controller.ts";
import { WebRuntime } from "./web-runtime.ts";
import { assertSessionBoundary, compactionOwner } from "./capability-policy.ts";
import { PermissionAccess } from "./permission-access.ts";
import { AsyncLocalStorage } from "node:async_hooks";
// 固定 SDK 启动入口；直接导入本模块不启动宿主，测试通过显式假 SDK 注入。
import { constants, closeSync, fstatSync, lstatSync, mkdirSync, openSync, readFileSync, renameSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createHash, randomUUID } from "node:crypto";
import { installPackagePolicy, loaderOptions, parseArguments, selectResources, restrictExtensions } from "./resource-loader.ts";
import { SupervisorClient } from "./supervisor-client.ts";
import { ManagedBackend } from "./managed-backend.ts";
import { agentStateClient } from "./service-bindings.ts";
import { checkpointClient } from "./checkpoints.ts";
import { inspectGitStatus } from "./git-status.ts";
import { requireOrdinaryHelper } from "./capability-policy.ts";

function failure(code, exitCode = 2) {
  const error = new Error(code);
  error.exitCode = exitCode;
  throw error;
}

export function privateBytes(path) {
  const parent = lstatSync(dirname(path));
  if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== process.getuid() || (parent.mode & 0o777) !== 0o700) failure("pi-private-directory", 4);
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const info = fstatSync(fd);
    if (!info.isFile() || info.nlink !== 1 || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o600) failure("pi-private-file", 4);
    return readFileSync(fd);
  } finally { closeSync(fd); }
}
export function privateFile(path) { return privateBytes(path).toString("utf8"); }

export function writePrivate(path, text) {
  const parent = lstatSync(dirname(path));
  if (!parent.isDirectory() || parent.isSymbolicLink() || parent.uid !== process.getuid() || (parent.mode & 0o777) !== 0o700) failure("pi-private-directory", 4);
  const temporary = path + "." + randomUUID();
  try {
    writeFileSync(temporary, text, { mode: 0o600, flag: "wx" });
    renameSync(temporary, path);
  } finally {
    try { unlinkSync(temporary); } catch (error) { if (error.code !== "ENOENT") throw error; }
  }
}

export function settingsStorage(path, { compaction = "native" } = {}) {
  return {
    withLock(scope, fn) {
      // 宿主租约防止 agentcfg 同时修改；project settings 永远不作为发现或覆盖来源。
      if (scope === "project") {
        if (fn(undefined) !== undefined) failure("pi-project-settings-disabled");
        return;
      }
      if (scope !== "global") failure("pi-settings-scope");
      const current = JSON.parse(privateFile(path));
      const sanitize = value => ({ ...value, packages: [], extensions: [], skills: [], prompts: [], themes: [],
        ...(compaction === "native" ? {} : { compaction: { ...value.compaction, enabled: false } }) });
      const next = fn(JSON.stringify(sanitize(current)));
      if (next !== undefined) writePrivate(path, JSON.stringify(sanitize(JSON.parse(next)), null, 2) + "\n");
    },
  };
}

export function constrainModels(runtime, manifest, managedRequestScope) {
  const get = runtime.getModel.bind(runtime);
  const permitted = model => {
    if (manifest.bootstrap || !model || !manifest.allowed_models.some(item => item.provider === model.provider && item.model === model.id)) return false;
    const bound = get(model.provider, model.id);
    return bound && bound.api === model.api && bound.baseUrl === model.baseUrl;
  };
  for (const name of ["getModels", "getAvailableSnapshot"]) {
    const original = runtime[name].bind(runtime);
    runtime[name] = (...args) => original(...args).filter(permitted);
  }
  const available = runtime.getAvailable.bind(runtime);
  runtime.getAvailable = async (...args) => (await available(...args)).filter(permitted);
  runtime.getModel = (...args) => { const model = get(...args); return permitted(model) ? model : undefined; };
  for (const name of ["prepareRequest", "stream", "complete", "streamSimple", "completeSimple", "fetchDeferred", "cancelDeferred"]) {
    const original = runtime[name].bind(runtime);
    runtime[name] = (model, ...args) => {
      const scope = managedRequestScope?.getStore();
      if (scope) { scope.recordDenial?.("UNBUDGETED_PARENT_HELPER_DENIED"); failure("pi-managed-parent-helper-denied", 5); }
      if (!permitted(model)) failure(manifest.bootstrap ? "pi-main-model-unbound" : "pi-model-not-selected");
      return original(model, ...args);
    };
  }
  return runtime;
}

export function compileRoles(sdk, manifest, selection, agentDir) {
  const directory = join(agentDir, "generated-roles");
  try { mkdirSync(directory, { mode: 0o700 }); } catch (error) { if (error.code !== "EEXIST") throw error; }
  const roles = [];
  for (const resource of selection.resources.roles) {
    const binding = manifest.role_bindings[resource.id];
    if (!binding || (resource.scope === "project" && binding.managed)) failure("pi-role-binding");
    const { body } = sdk.parseFrontmatter(readFileSync(resource.path, "utf8"));
    const header = { name: resource.id, description: "agentcfg role " + resource.id,
      model: binding.model.provider + "/" + binding.model.model, tools: binding.tools.join(", "),
      extensions: false, skills: false, inherit_context: false, prompt_mode: "replace",
      allowed_subagents: false, memory: false, persist_session: false, isolation: "off" };
    if (binding.thinking !== undefined) header.thinking = binding.thinking;
    const path = join(directory, resource.id + ".md");
    writePrivate(path, "---\n" + Object.entries(header).map(([key, value]) => key + ": " + JSON.stringify(value)).join("\n") + "\n---\n\n" + body);
    roles.push({ id: resource.id, path, source_digest: resource.digest, compiled_digest: createHash("sha256").update(readFileSync(path)).digest("hex"), ...binding });
  }
  const path = join(agentDir, "loaded-role-manifest.json");
  writePrivate(path, JSON.stringify({ schema_version: 1, roles, loaded_manifest_digest: selection.digest }) + "\n");
  return path;
}

function assertLoaded(loader, selection) {
  const extensions = loader.getExtensions();
  if (extensions.errors.length) failure("pi-extension-load-failed", 5);
  const expected = selection.resources.extensions.map(entry => entry.path).sort();
  const actual = extensions.extensions.map(entry => entry.resolvedPath).sort();
  if (JSON.stringify(actual) !== JSON.stringify(expected)) failure("pi-extension-load-mismatch", 5);
  for (const [kind, method] of [["skills", "getSkills"], ["prompts", "getPrompts"], ["themes", "getThemes"]]) {
    const loaded = loader[method]();
    if (loaded.diagnostics.some(item => item.type === "error")) failure("pi-resource-load-failed", 5);
    if (loaded[kind].length !== selection.resources[kind].length) failure("pi-resource-load-mismatch", 5);
  }
}

export async function launch({ sdk, manifest, installed, instanceRoot, runtimeRoot, cwd, engine, supervisor, argv = [], extensionScope = null }) {
  const args = parseArguments(argv);
  if (args.help) return { help: "agentcfg run pi -- [--print] [--thinking LEVEL] [--] [prompt ...]", code: 0 };
  if (manifest.bootstrap && (args.print || args.messages.length)) failure("pi-main-model-unbound");
  if (!supervisor) failure("pi-supervisor-required", 4);
  const owner = await supervisor.call("handshake", {});
  const managedRequestScope = new AsyncLocalStorage();
  if (owner.role !== "manager" || owner.runtime_identity !== installed.runtime_identity || owner.slice_identity !== installed.slice_identity) failure("pi-supervisor-identity", 4);
  globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = Object.freeze({ supervisor, owner: Object.freeze(owner),
    manifest, installed, instanceRoot, runtimeRoot, managedRequestScope });
  const agentDir = join(instanceRoot, "pi-home");
  const settingsManager = sdk.SettingsManager.fromStorage(settingsStorage(join(agentDir, "settings.json"), { compaction: compactionOwner(manifest) }));
  const create = async ({ cwd: effectiveCwd, sessionManager, sessionStartEvent }) => {
    let selection = selectResources({ manifest, installed: installed.resources, instanceRoot, runtimeRoot, cwd: effectiveCwd, engine });
    if (extensionScope !== null) selection = restrictExtensions(selection, extensionScope);
    process.env.AGENTCFG_PI_ROLE_MANIFEST = compileRoles(sdk, manifest, selection, agentDir);
    const managedContext = { cwd: effectiveCwd, resources: selection.resources, models: { current: null }, supervisor, owner: Object.freeze(owner), manifest, installed, instanceRoot, runtimeRoot, managedRequestScope,
      roleManifest: JSON.parse(privateFile(process.env.AGENTCFG_PI_ROLE_MANIFEST)) };
    managedContext.extensionApi = Object.freeze({ agentStateClient, checkpointClient, inspectGitStatus, assertSessionBoundary, requireOrdinaryHelper });
    managedContext.permissionAccess = new PermissionAccess(managedContext);
    const mimeModule = await import(pathToFileURL(join(dirname(resolve(runtimeRoot, installed.entrypoint)), "utils/mime.js")).href);
    managedContext.ordinaryOperations = new OrdinaryOperations(sdk, managedContext, { mime: mimeModule.detectSupportedImageMimeType });
    let readseekInstalled = false;
    if (manifest.plugins.includes("pi-readseek")) {
      try {
        const programs = JSON.parse(privateFile(join(runtimeRoot, "runtime/commands.json"))).programs;
        const native = lstatSync(join(runtimeRoot, "bin/readseek"));
        readseekInstalled = programs.readseek?.entrypoint === "runtime/readseek-process.mjs" && native.isFile() && !native.isSymbolicLink();
      } catch { /* 未安装能力保留不可用状态，调用时给出明确失败。 */ }
    }
    managedContext.readseek = new ReadseekController(managedContext, { installed: readseekInstalled });
    managedContext.web = new WebRuntime(managedContext);
    if (manifest.options?.task_keeper?.enabled) managedContext.managedBackend = new ManagedBackend(managedContext);
    globalThis[Symbol.for("agentcfg.pi.runtime.v1")] = Object.freeze(managedContext);
    installPackagePolicy(sdk, selection);
    const modelRuntime = constrainModels(await sdk.ModelRuntime.create({ authPath: join(agentDir, "auth.json"), modelsPath: join(agentDir, "models.json"), allowModelNetwork: false }), manifest, managedRequestScope);
    managedContext.models.current = modelRuntime;
    if (compactionOwner(manifest) !== "native") settingsManager.setCompactionEnabled(false);
    const services = await sdk.createAgentSessionServices({ cwd: effectiveCwd, agentDir, settingsManager, modelRuntime, resourceLoaderOptions: loaderOptions(selection) });
    if (services.diagnostics.some(item => item.type === "error")) failure("pi-services-not-ready", 5);
    assertLoaded(services.resourceLoader, selection);
    const main = manifest.model_bindings.main;
    const model = main ? services.modelRuntime.getModel(main.provider, main.model) : undefined;
    if (!manifest.bootstrap && !model) failure("pi-main-model-unavailable", 5);
    const result = await sdk.createAgentSessionFromServices({ services, sessionManager, sessionStartEvent, model,
      thinkingLevel: args.thinking, scopedModels: services.modelRuntime.getModels().map(model => ({ model })),
      ...(manifest.bootstrap ? { noTools: "all" } : !manifest.plugins.includes("pi-permissions") ? { noTools: "builtin" } : {}) });
    if (args.thinking && result.session.thinkingLevel !== args.thinking) failure("pi-thinking-level-unsupported", 2);
    const nativeReload = result.session.reload?.bind(result.session);
    if (nativeReload) result.session.reload = async (...args) => {
      await assertSessionBoundary(managedContext);
      return nativeReload(...args);
    };
    // bootstrap 的 UI 仍可登录；模型请求和后台 helper 不得借原生默认模型绕过绑定。
    if (manifest.bootstrap) result.session.prompt = async () => failure("pi-main-model-unbound");
    writePrivate(join(agentDir, "loaded-manifest.json"), JSON.stringify({ ...selection, loaded_manifest_digest: selection.digest,
      slice_identity: installed.slice_identity, tools: result.session.getActiveToolNames(), roles_verified: false,
      verification: "loaded-only" }, null, 2) + "\n");
    return { ...result, services, diagnostics: services.diagnostics };
  };
  installSessionCompatibility(sdk, join(agentDir, "sessions"));
  const sessionManager = sdk.SessionManager.create(cwd, join(agentDir, "sessions"));
  const runtime = await sdk.createAgentSessionRuntime(create, { cwd, agentDir, sessionManager });
  try {
    if (args.print) return { code: await sdk.runPrintMode(runtime, { mode: "text", messages: args.messages }) };
    const mode = new sdk.InteractiveMode(runtime, { initialMessages: args.messages });
    await mode.run();
    return { code: 0 };
  } finally { await runtime.dispose(); }
}

async function main(argv) {
  if (argv[0] !== "--manifest" || !argv[1] || !isAbsolute(argv[1])) failure("pi-manifest-argument");
  const manifestPath = argv[1];
  const instanceRoot = dirname(dirname(manifestPath));
  if (manifestPath !== join(instanceRoot, "pi-home/agentcfg-manifest.json")
      || process.env.HOME !== join(instanceRoot, "user-home") || process.env.PI_CODING_AGENT_DIR !== join(instanceRoot, "pi-home")
      || process.env.PI_CODING_AGENT_SESSION_DIR !== join(instanceRoot, "pi-home/sessions")) failure("pi-instance-environment", 4);
  const runtimeRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  process.env.PI_SKIP_VERSION_CHECK = "1";
  const installed = JSON.parse(privateFile(join(runtimeRoot, "runtime/profile.json")));
  const manifest = JSON.parse(privateFile(manifestPath));
  const supervisor = new SupervisorClient({ python: process.env.AGENTCFG_PYTHON, client: process.env.AGENTCFG_SUPERVISOR_CLIENT,
    endpoint: process.env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: process.env.AGENTCFG_SUPERVISOR_CAPABILITY });
  delete process.env.AGENTCFG_SUPERVISOR_CAPABILITY;
  const engine = typeof globalThis.Bun !== "undefined" ? "bun" : "node";
  const actual = engine === "bun" ? globalThis.Bun.version : process.version;
  const platform = process.platform + "-" + (process.arch === "x64" ? "x86_64" : process.arch);
  if (installed.platform !== platform || installed.engine !== engine || manifest.engine !== engine || installed.toolchains[engine] !== actual) failure("pi-engine-version", 5);
  const entry = resolve(runtimeRoot, installed.entrypoint);
  const rel = relative(runtimeRoot, entry);
  if (isAbsolute(rel) || rel === ".." || rel.startsWith(".." + sep)) failure("pi-sdk-path");
  // Python 层先验证完整运行收据，本入口只导入该切片精确 SDK。
  const sdk = await import(pathToFileURL(entry).href);
  const result = await launch({ sdk, manifest, installed, instanceRoot, runtimeRoot, cwd: process.cwd(), engine, supervisor, argv: argv.slice(2) });
  if (result.help) process.stdout.write(result.help + "\n");
  return result.code;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = await main(process.argv.slice(2)); }
  catch (error) {
    process.stderr.write("Pi managed launcher failed; check agentcfg configuration, bindings and runtime readiness.\n");
    process.exitCode = Number.isInteger(error?.exitCode) ? error.exitCode : 5;
  }
}
