// 现代实例的实际CLI入口；只组合SDK根公开接口。参数不提供资源/账号/会话路径旁路。
// 正常退出和返回/抛错路径经facade.dispose；RPC重入shutdown/TUI硬退出不能保证drain，
// 仍依赖外层manager死亡观察与监督者租约恢复。此边界未由真实宿主验收证明。
import { lstatSync, realpathSync, readFileSync, existsSync } from "node:fs";
import { AsyncLocalStorage } from "node:async_hooks";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { types } from "node:util";
import { privateBytes } from "./private-files.ts";
import { strictJson } from "./strict-json.ts";
import { digest, sha, ProtocolError } from "./managed-types.ts";
import { SupervisorClient, inheritedControlDirectory } from "./supervisor-client.ts";
import { createOfficialRuntimeInitializer } from "./official-model-runtime.ts";
import { createOfficialFileRuntime } from "./official-file-runtime.ts";

const runtimeSymbol = Symbol.for("agentcfg.pi.runtime.v1");
const levels = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
const help = "agentcfg run pi -- [--print | --mode rpc] [--thinking LEVEL] [--] [prompt ...]";
const launchDiagnostics = new WeakMap();
const launchCodes = new Set([
  "DELEGATE_TASK_ISSUER_UNAVAILABLE", "pi-deployment-stale", "pi-engine-version", "pi-installed-profile",
  "pi-instance-environment", "pi-launch-arguments", "pi-launch-context", "pi-launch-json", "pi-manifest-argument",
  "pi-official-cleanup-failed", "pi-official-launch-failed", "pi-official-main-failed", "pi-project-context",
  "pi-runtime-context-conflict", "pi-sdk-esm-resolver-unavailable", "pi-sdk-incompatible", "pi-sdk-mode-result",
  "pi-sdk-path", "pi-sdk-version", "pi-supervisor-identity",
  "pi-official-handshake-failed", "pi-official-runtime-init-failed", "pi-official-session-create-failed", "pi-official-frontend-run-failed",
  "pi-official-handshake-control-unavailable", "pi-official-handshake-control-rejected"
]);
class LaunchError extends Error {
  constructor(code, exitCode) {
    super(code); this.exitCode = exitCode;
    if (launchCodes.has(code) && Number.isInteger(exitCode) && [2, 3, 4, 5, 6].includes(exitCode)) {
      launchDiagnostics.set(this, { message: "Pi official launcher failed: " + code + ".\n", exitCode });
    }
  }
}
export function officialLaunchDiagnostic(error) {
  // 仅自有异常的原捕获静态码；不读取foreign message/cause/属性或调用其钩子。
  const known = launchDiagnostics.get(error);
  return known ? { ...known } : { message: "Pi official launcher failed; check deployment and runtime readiness.\n", exitCode: 5 };
}
function failureExit(error) {
  if (!error || typeof error !== "object" || types.isProxy(error)) return 5;
  const own = Object.getOwnPropertyDescriptor(error, "exitCode");
  return own && Object.hasOwn(own, "value") && [2, 3, 4, 5, 6].includes(own.value) ? own.value : 5;
}
function handshakeFailure(error) {
  if (!error || typeof error !== "object" || types.isProxy(error)
      || Object.getPrototypeOf(error) !== ProtocolError.prototype) return undefined;
  const code = Object.getOwnPropertyDescriptor(error, "code"), exit = Object.getOwnPropertyDescriptor(error, "exitCode");
  if (!code || !exit || !Object.hasOwn(code, "value") || !Object.hasOwn(exit, "value")
      || ![2, 3, 4, 5, 6].includes(exit.value)) return undefined;
  if (code.value === "PI_CONTROL_UNAVAILABLE") return "pi-official-handshake-control-unavailable";
  if (code.value === "PI_CONTROL_REJECTED") return "pi-official-handshake-control-rejected";
}
const fail = (code, exitCode = 2) => { throw new LaunchError(code, exitCode); };
const plain = value => value !== null && typeof value === "object" && Object.getPrototypeOf(value) === Object.prototype;
const text = value => typeof value === "string" && value.length > 0 && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value);
const location = path => text(path) && isAbsolute(path) && resolve(path) === path;
const inside = (root, path) => { const rel = relative(root, path); return rel === "" || !isAbsolute(rel) && rel !== ".." && !rel.startsWith(".." + sep); };
const freeze = value => { if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); } return value; };
const copy = value => freeze(structuredClone(value));
function disableBackgroundProbes(env = process.env) {
  // 本入口属于专用宿主进程；异步原生mode可能仍存活，因此退出时不恢复这些开关。
  // 公开offline开关仅禁后台目录/版本探测，不是阻断用户授权的模型请求或网络沙箱。
  for (const target of [process.env, env]) {
    target.PI_OFFLINE = "1";
    target.PI_SKIP_VERSION_CHECK = "1";
    delete target.TMUX;
  }
}
function privateDirectory(path) {
  const info = lstatSync(path);
  if (!location(path) || realpathSync(path) !== path || !info.isDirectory() || info.isSymbolicLink()
      || info.uid !== process.getuid() || (info.mode & 0o777) !== 0o700) fail("pi-instance-environment", 4);
}
function relativeFile(path) {
  if (!text(path) || isAbsolute(path) || path.includes("\\") || path.split("/").some(part => !part || part === "." || part === "..")) fail("pi-sdk-path");
  return path;
}
function jsonBytes(path) {
  return privateBytes(path, 1024 * 1024);
}
function decode(bytes) {
  try { return strictJson(new TextDecoder("utf8", { fatal: true }).decode(bytes)); }
  catch { fail("pi-launch-json", 2); }
}
function checkInstalled(installed, manifest) {
  const fields = ["schema_version", "profile_id", "engine", "entrypoint", "package_path", "sdk_package", "sdk_version", "ai_package", "ai_version",
    "resources", "lock_identity", "slice_identity", "runtime_identity", "toolchains", "platform"];
  if (!plain(installed) || Object.keys(installed).length !== fields.length || fields.some(key => !Object.hasOwn(installed, key))
      || installed.schema_version !== 2 || !["pi-base", "pi-full"].includes(installed.profile_id)
      || !plain(manifest) || manifest.profile_id !== installed.profile_id || installed.engine !== "node" || manifest.engine !== "node"
      || !plain(installed.resources) || !plain(installed.toolchains) || !plain(manifest.permission_policy)
      || ["lock_identity", "slice_identity", "runtime_identity"].some(key => !sha(installed[key]))
      || ["sdk_package", "ai_package"].some(key => !text(installed[key]) || !/^(?:@[a-z0-9._-]+\/)?[a-z0-9._-]+$/.test(installed[key]))
      || ["sdk_version", "ai_version"].some(key => !/^\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?$/.test(installed[key]))) fail("pi-installed-profile", 2);
  relativeFile(installed.entrypoint); relativeFile(installed.package_path);
  if (!installed.package_path.endsWith("/package.json") && installed.package_path !== "package.json") fail("pi-sdk-path");
}

export function parseOfficialArguments(argv) {
  if (!Array.isArray(argv) || argv.some(value => typeof value !== "string" || value.includes("\0") || /\p{Cs}/u.test(value))) fail("pi-launch-arguments");
  const result = { mode: "tui", thinking: undefined, help: false, messages: [] };
  let separated = false, chosenMode = false;
  for (let index = 0; index < argv.length; index++) {
    const arg = argv[index];
    if (separated) { result.messages.push(arg); continue; }
    if (arg === "--") { separated = true; continue; }
    if (arg === "--help" || arg === "-h") { result.help = true; continue; }
    if (arg === "--print") {
      if (chosenMode) fail("pi-launch-arguments");
      result.mode = "print"; chosenMode = true; continue;
    }
    if (arg === "--mode") {
      if (chosenMode || argv[++index] !== "rpc") fail("pi-launch-arguments");
      result.mode = "rpc"; chosenMode = true; continue;
    }
    if (arg === "--thinking") {
      if (result.thinking !== undefined || !levels.includes(argv[++index])) fail("pi-launch-arguments");
      result.thinking = argv[index]; continue;
    }
    if (arg.startsWith("-")) fail("pi-launch-arguments");
    result.messages.push(arg);
  }
  if (result.mode === "rpc" && result.messages.length) fail("pi-launch-arguments");
  return result;
}

export function resolveOfficialPackages({ installed, runtimeRoot }) {
  try {
    if (!location(runtimeRoot) || realpathSync(runtimeRoot) !== runtimeRoot) fail("pi-sdk-path");
    // Node24的公开parentURL参数需要固定flag；缺失时不能退回require条件或checkout查找。
    if (!process.execArgv.includes("--experimental-import-meta-resolve")) fail("pi-sdk-esm-resolver-unavailable", 5);
    const packagePath = join(runtimeRoot, relativeFile(installed.package_path));
    const sliceRoot = dirname(packagePath);
    const entry = join(runtimeRoot, relativeFile(installed.entrypoint));
    if (!inside(runtimeRoot, realpathSync(packagePath))) fail("pi-sdk-path");
    const resolvePackage = (name, anchor) => fileURLToPath(import.meta.resolve(name, pathToFileURL(anchor).href));
    const sdkEntry = resolvePackage(installed.sdk_package, packagePath);
    if (sdkEntry !== entry || realpathSync(sdkEntry) !== entry || !inside(sliceRoot, sdkEntry)) fail("pi-sdk-path");
    const aiEntry = resolvePackage(installed.ai_package, sdkEntry);
    if (!inside(sliceRoot, aiEntry) || !inside(sliceRoot, realpathSync(aiEntry))) fail("pi-sdk-path");
    const version = (entryPath, name, expected) => {
      let directory = dirname(realpathSync(entryPath));
      while (inside(sliceRoot, directory)) {
        const path = join(directory, "package.json");
        if (existsSync(path)) {
          if (!inside(runtimeRoot, realpathSync(path))) fail("pi-sdk-path");
          const document = JSON.parse(readFileSync(path, "utf8"));
          if (document.name !== name || document.version !== expected) fail("pi-sdk-version", 5);
          return;
        }
        if (directory === sliceRoot) break;
        directory = dirname(directory);
      }
      fail("pi-sdk-version", 5);
    };
    version(sdkEntry, installed.sdk_package, installed.sdk_version);
    version(aiEntry, installed.ai_package, installed.ai_version);
    return Object.freeze({ sdkEntry, aiEntry });
  } catch (error) { if (launchDiagnostics.has(error)) throw error; fail("pi-sdk-path", 5); }
}

export async function launch({ sdk, ai, manifest, installed, instanceRoot, runtimeRoot, cwd, engine, supervisor, argv = [], verifyDeployment,
  initializeRuntime = createOfficialRuntimeInitializer, createRuntime = createOfficialFileRuntime, taskKeeperIssuer }) {
  const args = parseOfficialArguments(argv);
  if (args.help) return { help, code: 0 };
  if (typeof verifyDeployment !== "function" || typeof supervisor?.call !== "function" || engine !== "node") fail("pi-launch-context", 4);
  checkInstalled(installed, manifest);
  disableBackgroundProbes();
  const frozenManifest = copy(manifest), frozenInstalled = copy(installed);
  verifyDeployment();
  let runtime, context, managedRequestScope, stage = "pi-official-handshake-failed";
  try {
    if (globalThis[runtimeSymbol] !== undefined) fail("pi-runtime-context-conflict", 4);
    const owner = copy(await supervisor.call("handshake", {}));
    if (owner.role !== "manager" || owner.runtime_identity !== installed.runtime_identity || owner.slice_identity !== installed.slice_identity
        || !text(owner.manager_activation_id) || !text(owner.instance_id) || !text(owner.owner_nonce)
        || owner.protected_roots !== undefined && (!Array.isArray(owner.protected_roots) || owner.protected_roots.some(path => !location(path)))) fail("pi-supervisor-identity", 4);
    verifyDeployment();
    const configuration = currentCwd => {
      verifyDeployment();
      if (!location(currentCwd)) fail("pi-project-context", 4);
      return { policyDigest: digest(frozenManifest.permission_policy), projectConstraintsDigest: digest({ cwd: currentCwd,
        permissions: frozenManifest.options?.permissions ?? {}, paths: frozenManifest.options?.paths ?? {}, protectedRoots: owner.protected_roots ?? [] }) };
    };
    const policySnapshot = () => { verifyDeployment(); return Object.freeze({ generation: 1, policy_digest: digest(frozenManifest.permission_policy) }); };
    // 自有异步上下文供所选UI识别受管请求；未来内部请求必须显式通过run进入。
    managedRequestScope = new AsyncLocalStorage();
    context = Object.freeze({ owner, manifest: frozenManifest, installed: frozenInstalled, supervisor, instanceRoot, runtimeRoot, managedRequestScope });
    globalThis[runtimeSymbol] = context;
    stage = "pi-official-runtime-init-failed";
    const initialize = initializeRuntime({ sdk, ai, manifest: frozenManifest, instanceRoot });
    const runtimeHandle = await initialize();
    verifyDeployment();
    stage = "pi-official-session-create-failed";
    if (typeof sdk?.SessionManager?.create !== "function") fail("pi-sdk-incompatible", 5);
    const sessionManager = sdk.SessionManager.create(cwd, join(instanceRoot, "pi-home/sessions"));
    runtime = await createRuntime({ sdk, manifest: frozenManifest, installed: frozenInstalled, instanceRoot, runtimeRoot, engine, supervisor, owner,
      runtimeHandle, configuration, policySnapshot, managedRequestScope, taskKeeperIssuer, thinkingLevel: args.thinking, extensionFactories: [] }, { cwd, agentDir: join(instanceRoot, "pi-home"), sessionManager });
    verifyDeployment();
    stage = "pi-official-frontend-run-failed";
    if (args.mode === "print") {
      if (typeof sdk.runPrintMode !== "function") fail("pi-sdk-incompatible", 5);
      const code = await sdk.runPrintMode(runtime, { mode: "text", messages: args.messages });
      if (!Number.isInteger(code) || code < 0 || code > 255) fail("pi-sdk-mode-result", 5);
      return { code };
    }
    if (args.mode === "rpc") {
      if (typeof sdk.runRpcMode !== "function") fail("pi-sdk-incompatible", 5);
      // 官方RPC自身退出前调用公开runtime.dispose；自然process.exit不返回此finally。
      await sdk.runRpcMode(runtime);
      return { code: 0 };
    }
    if (typeof sdk.InteractiveMode !== "function") fail("pi-sdk-incompatible", 5);
    const mode = new sdk.InteractiveMode(runtime, { initialMessages: args.messages });
    await mode.run();
    return { code: 0 };
  } catch (error) {
    if (launchDiagnostics.has(error)) throw error;
    fail(stage === "pi-official-handshake-failed" ? handshakeFailure(error) ?? stage : stage, failureExit(error));
  } finally {
    try { if (runtime) await runtime.dispose(); }
    catch { fail("pi-official-cleanup-failed", 4); }
    finally {
      managedRequestScope?.disable();
      if (context && globalThis[runtimeSymbol] === context) delete globalThis[runtimeSymbol];
    }
  }
}

// 依赖注入仅供自有离线测试；直接执行main始终使用真实文件核验、私有监督通道和公开SDK根。
export async function main(argv, { runtimeRoot = resolve(dirname(fileURLToPath(import.meta.url)), ".."), env = process.env, cwd = process.cwd(),
  supervisorFactory = options => new SupervisorClient(options), importModule = url => import(url),
  initializeRuntime = createOfficialRuntimeInitializer, createRuntime = createOfficialFileRuntime, writeOutput = text => process.stdout.write(text) } = {}) {
  try {
    if (!Array.isArray(argv) || argv[0] !== "--manifest" || !location(argv[1])) fail("pi-manifest-argument");
    const manifestPath = argv[1], instanceRoot = dirname(dirname(manifestPath));
    if (manifestPath !== join(instanceRoot, "pi-home/agentcfg-manifest.json")) fail("pi-manifest-argument");
    const args = parseOfficialArguments(argv.slice(2));
    if (args.help) { writeOutput(help + "\n"); return 0; }
    if (env.HOME !== join(instanceRoot, "user-home") || env.PI_CODING_AGENT_DIR !== join(instanceRoot, "pi-home")
        || env.PI_CODING_AGENT_SESSION_DIR !== join(instanceRoot, "pi-home/sessions")) fail("pi-instance-environment", 4);
    for (const directory of [instanceRoot, env.HOME, env.PI_CODING_AGENT_DIR, runtimeRoot, join(runtimeRoot, "runtime")]) privateDirectory(directory);
    if (existsSync(env.PI_CODING_AGENT_SESSION_DIR)) privateDirectory(env.PI_CODING_AGENT_SESSION_DIR);
    if (!location(cwd) || realpathSync(cwd) !== cwd) fail("pi-project-context", 4);
    const original = jsonBytes(manifestPath), manifest = decode(original), installed = decode(jsonBytes(join(runtimeRoot, "runtime/profile.json")));
    checkInstalled(installed, manifest);
    const platform = process.platform + "-" + (process.arch === "x64" ? "x86_64" : process.arch);
    if (installed.platform !== platform || installed.toolchains.node !== process.version) fail("pi-engine-version", 5);
    const packages = resolveOfficialPackages({ installed, runtimeRoot });
    const directory = inheritedControlDirectory(env);
    const supervisor = supervisorFactory({ python: env.AGENTCFG_PYTHON, client: env.AGENTCFG_SUPERVISOR_CLIENT, ...directory,
      endpoint: env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: env.AGENTCFG_SUPERVISOR_CAPABILITY });
    delete env.AGENTCFG_SUPERVISOR_CAPABILITY;
    let taskKeeperIssuer;
    const taskCapability = env.AGENTCFG_TASK_KEEPER_SOURCE_CAPABILITY;
    delete env.AGENTCFG_TASK_KEEPER_SOURCE_CAPABILITY;
    if (manifest.profile_id === "pi-full" && manifest.plugins?.includes("task-keeper") && manifest.options?.task_keeper?.enabled) {
      if (!text(taskCapability)) fail("DELEGATE_TASK_ISSUER_UNAVAILABLE", 5);
      const issuerClient = supervisorFactory({ python: env.AGENTCFG_PYTHON, client: env.AGENTCFG_SUPERVISOR_CLIENT, ...directory,
        endpoint: env.AGENTCFG_SUPERVISOR_ENDPOINT, capability: taskCapability });
      taskKeeperIssuer = Object.freeze({ async open(facts) {
        const result = await issuerClient.call("delegate_task_source_v3", { facts });
        if (!text(result.source_ref)) fail("DELEGATE_TASK_ISSUER_UNAVAILABLE", 5);
        return result.source_ref;
      }, async retire(source_ref) { return issuerClient.call("delegate_task_source_retire_v3", { source_ref }); } });
    }
    const verifyDeployment = () => {
      try { if (!jsonBytes(manifestPath).equals(original)) fail("pi-deployment-stale", 4); }
      catch { fail("pi-deployment-stale", 4); }
    };
    disableBackgroundProbes(env);
    const sdk = await importModule(pathToFileURL(packages.sdkEntry).href), ai = await importModule(pathToFileURL(packages.aiEntry).href);
    const result = await launch({ sdk, ai, manifest, installed, instanceRoot, runtimeRoot, cwd, engine: "node", supervisor,
      argv: argv.slice(2), verifyDeployment, initializeRuntime, createRuntime, taskKeeperIssuer });
    return result.code;
  } catch (error) {
    if (launchDiagnostics.has(error)) throw error;
    fail("pi-official-main-failed", failureExit(error));
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { process.exitCode = await main(process.argv.slice(2)); }
  catch (error) {
    const diagnostic = officialLaunchDiagnostic(error);
    process.stderr.write(diagnostic.message);
    process.exitCode = diagnostic.exitCode;
  }
}
