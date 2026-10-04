import { lstat, realpath } from "node:fs/promises";
import { createHash } from "node:crypto";
import { homedir } from "node:os";
import { dirname, isAbsolute, join, resolve } from "node:path";
import type { ToolSession } from "@oh-my-pi/pi-coding-agent/tools";

export interface PlainBashParams {
  command: string;
  cwd?: string;
  timeout?: number;
}

export const SHELL_FAMILIES = ["bash", "sh", "zsh", "dash", "ash", "ksh", "mksh", "fish",
  "pwsh", "powershell", "cmd", "unknown"] as const;
export type ShellFamily = (typeof SHELL_FAMILIES)[number];
export type ExecutionRoute = "local-embedded" | "unverified";
export const CONTEXT_REASONS = ["STANDARD_CONTEXT", "SETTINGS_MISMATCH", "CWD_UNCERTAIN", "DIRENV_CONTEXT",
  "SHELL_UNKNOWN", "SHELL_ARGUMENTS", "EXECUTION_ROUTE_UNVERIFIED", "SHELL_PATH_UNVERIFIED", "SHELL_PREFIX",
  "BASH_STARTUP", "BASH_FUNCTIONS", "SHELL_HOME_MISMATCH", "BASH_SNAPSHOT_UNCERTAIN", "WORKTREE_CONTEXT"] as const;
export interface NativeDiagnostics {
  shellFamily: ShellFamily;
  executionRoute: ExecutionRoute;
  contextReason: (typeof CONTEXT_REASONS)[number];
}

export function shellFamily(shell: string): ShellFamily {
  const name = shell.replace(/\\/gu, "/").split("/").at(-1)?.toLowerCase().replace(/\.exe$/u, "");
  return SHELL_FAMILIES.includes(name as ShellFamily) ? name as ShellFamily : "unknown";
}

function standardShellArguments(family: ShellFamily, args: string[]): boolean {
  const shapes = family === "cmd" ? [["/c"]] : family === "pwsh" || family === "powershell"
    ? [["-NoLogo", "-Command"], ["-NoLogo", "-NoProfile", "-Command"]] : [["-l", "-c"], ["-c"]];
  return family !== "unknown" && shapes.some(shape => shape.length === args.length &&
    shape.every((arg, index) => arg === args[index]));
}

// 只核验受管本地启动的公开 argv；不信任缓存到 Settings 的环境副本。
export function executionRoute(marker: string | undefined, argv: readonly string[]): ExecutionRoute {
  if (marker !== "local-native-bash-v1" || argv.length < 2) return "unverified";
  const booleanFlags = new Set(["--help", "-h", "--version", "-v", "--no-title", "--print", "-p",
    "--no-session", "--no-skills"]);
  const valueFlags = new Set(["--provider", "--model", "--smol", "--slow", "--plan", "--thinking",
    "--service-tier", "--max-time", "--profile", "--mode"]);
  // 官方入口 runCli(process.argv.slice(2))：前两个元素为 executable 与入口。
  const args = argv.slice(2);
  for (let index = 0; index < args.length; index++) {
    const arg = args[index];
    if (arg === "--") break;
    if (arg === "acp" || arg === "rpc-ui") return "unverified";
    if (!arg.startsWith("-")) continue;
    const equals = arg.startsWith("--") ? arg.indexOf("=") : -1;
    const flag = equals === -1 ? arg : arg.slice(0, equals);
    if (booleanFlags.has(flag)) {
      if (equals !== -1) return "unverified";
      continue;
    }
    if (!valueFlags.has(flag)) return "unverified";
    const value = equals === -1 ? args[++index] : arg.slice(equals + 1);
    if (value === undefined || value.length === 0 || value === "--") return "unverified";
    if (flag === "--mode" && !["text", "json", "rpc"].includes(value)) return "unverified";
  }
  return "local-embedded";
}

export interface NativeSettingsSnapshot {
  settings: object;
  fingerprint: string;
  decision: "allow" | "deny" | "prompt";
  reasonCode: "NATIVE_ALLOW" | "NATIVE_DENY" | "NATIVE_PROMPT" | "UNSUPPORTED_EXECUTION_CONTEXT";
  reviewContext: Record<string, string | number | boolean | null>;
  diagnostics?: NativeDiagnostics;
}

export interface NativeBashRuntime {
  capture(baseCwd: string, params: PlainBashParams): Promise<NativeSettingsSnapshot>;
  recheck(settings: object, baseCwd: string, params: PlainBashParams): Promise<NativeSettingsSnapshot>;
}

interface SettingsLike {
  readonly revision: number;
  getShellConfig(): { shell: string; args: string[]; prefix?: string; env?: Record<string, string> };
}

interface SettingLike<T> {
  get(settings: SettingsLike): T;
}

interface NativeModules {
  homeDir(): string;
  executionRoute?(): ExecutionRoute;
  executionRouteFingerprint?(): string;
  legacyShellAllowed?(): boolean;
  findScopedSettings(cwd?: string): SettingsLike | undefined;
  isSettingsInitialized(): boolean;
  getGlobalSettings(): Promise<SettingsLike>;
  BashTool: new (session: ToolSession) => { approval(args: unknown): unknown };
  cfgToolsApproval: SettingLike<Record<string, unknown>>;
  cfgToolsMaxTimeout: SettingLike<number>;
  cfgAsyncEnabled: SettingLike<boolean>;
  cfgLaunchEnabled: SettingLike<boolean>;
  cfgBashAllowCompoundCommands: SettingLike<boolean>;
  cfgBashAutoBackgroundEnabled: SettingLike<boolean>;
  cfgBashAutoBackgroundThresholdMs: SettingLike<number>;
  cfgBashPatterns: SettingLike<unknown[]>;
  cfgBashInterceptorEnabled: SettingLike<boolean>;
  cfgBashInterceptorPatterns: SettingLike<unknown[]>;
  cfgBashDirenv: SettingLike<string>;
  cfgBashDirenvLoadTimeoutMs: SettingLike<number>;
  cfgShellPath: SettingLike<string | undefined>;
  cfgWorktreeClone: SettingLike<boolean>;
}

function canonical(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  return `{${Object.entries(value as Record<string, unknown>).sort(([a], [b]) => a.localeCompare(b))
    .map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",")}}`;
}

function digest(value: unknown): string {
  return createHash("sha256").update(canonical(value)).digest("hex");
}

type FileState = { kind: "missing" } | { kind: "file"; marker: string } | { kind: "uncertain"; marker: string };

async function fileState(path: string): Promise<FileState> {
  try {
    const stat = await lstat(path);
    const marker = `${path}:${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeMs}:${stat.ctimeMs}`;
    if (stat.isSymbolicLink()) return { kind: "uncertain", marker: `symlink:${marker}` };
    return stat.isFile() ? { kind: "file", marker } : { kind: "uncertain", marker: `non-file:${marker}` };
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return { kind: "missing" };
    return { kind: "uncertain", marker: `unreadable:${path}` };
  }
}

function targetCwd(baseCwd: string, cwd: string | undefined): { path?: string; uncertain: boolean } {
  if (cwd && /^[a-z][a-z0-9+.-]*:\/\//iu.test(cwd)) return { uncertain: true };
  return { path: cwd ? (isAbsolute(cwd) ? cwd : resolve(baseCwd, cwd)) : baseCwd, uncertain: false };
}

async function nearestEnvrc(start: string): Promise<{ present: boolean; uncertain: boolean; marker: string }> {
  let current: string;
  try {
    current = await realpath(resolve(start));
  } catch {
    return { present: false, uncertain: true, marker: `cwd-unresolved:${resolve(start)}` };
  }
  const redirected = current !== resolve(start);
  while (true) {
    const state = await fileState(join(current, ".envrc"));
    if (state.kind === "file") return { present: true, uncertain: redirected, marker: state.marker };
    if (state.kind === "uncertain") return { present: false, uncertain: true, marker: state.marker };
    const parent = dirname(current);
    if (parent === current) return { present: false, uncertain: redirected, marker: `none:${current}` };
    current = parent;
  }
}

async function userStartupState(home: string): Promise<{ present: boolean; uncertain: boolean;
  marker: string }> {
  const candidates = [".bashrc", ".bash_profile", ".bash_login", ".profile"];
  const markers: string[] = [];
  let present = false;
  let uncertain = false;
  for (const candidate of candidates) {
    const state = await fileState(join(home, candidate));
    markers.push(state.kind === "missing" ? `missing:${candidate}` : state.marker);
    present ||= state.kind === "file";
    uncertain ||= state.kind === "uncertain";
  }
  return { present, uncertain, marker: markers.join("|") };
}

function nativeDecision(approval: unknown): "allow" | "deny" | "prompt" {
  if (approval === "exec" || approval === "write" || approval === "read") return "allow";
  if (!approval || typeof approval !== "object" || Array.isArray(approval)) return "prompt";
  const value = approval as Record<string, unknown>;
  if (value.tier !== "exec" && value.tier !== "write" && value.tier !== "read") return "prompt";
  if (value.policy === "deny") return "deny";
  if (value.policy === "prompt" || value.override === true) return "prompt";
  if (value.policy === undefined || value.policy === "allow") return "allow";
  return "prompt";
}

function settingsFingerprint(modules: NativeModules, settings: SettingsLike): string {
  const shell = settings.getShellConfig();
  return digest({
    revision: settings.revision,
    approval: modules.cfgToolsApproval.get(settings),
    patterns: modules.cfgBashPatterns.get(settings),
    compound: modules.cfgBashAllowCompoundCommands.get(settings),
    shell: { shell: shell.shell, args: shell.args, prefix: shell.prefix ?? null, env: shell.env ?? {} },
    shellPath: modules.cfgShellPath.get(settings) ?? null,
    interceptor: modules.cfgBashInterceptorEnabled.get(settings),
    interceptorPatterns: modules.cfgBashInterceptorPatterns.get(settings),
    direnv: modules.cfgBashDirenv.get(settings),
    direnvTimeout: modules.cfgBashDirenvLoadTimeoutMs.get(settings),
    autoBackground: modules.cfgBashAutoBackgroundEnabled.get(settings),
    autoBackgroundThreshold: modules.cfgBashAutoBackgroundThresholdMs.get(settings),
    maxTimeout: modules.cfgToolsMaxTimeout.get(settings),
    async: modules.cfgAsyncEnabled.get(settings),
    launch: modules.cfgLaunchEnabled.get(settings),
    worktreeClone: modules.cfgWorktreeClone.get(settings),
  });
}

async function analyze(modules: NativeModules, settings: SettingsLike, baseCwd: string,
  params: PlainBashParams, globalSettings: SettingsLike,
  mutable: { shellSnapshotUncertain: boolean }): Promise<NativeSettingsSnapshot> {
  const policies = modules.cfgToolsApproval.get(settings);
  const shell = settings.getShellConfig();
  const family = shellFamily(shell.shell);
  const route = modules.executionRoute?.() ?? "unverified";
  const routeFingerprint = modules.executionRouteFingerprint?.() ?? route;
  const legacyShellAllowed = modules.legacyShellAllowed?.() ?? modules.executionRoute === undefined;
  const diagnostics: NativeDiagnostics = { shellFamily: family, executionRoute: route,
    contextReason: "STANDARD_CONTEXT" };
  const session = {
    cwd: baseCwd,
    hasUI: false,
    getSessionFile: () => null,
    getSessionSpawns: () => null,
    settings,
  } as unknown as ToolSession;
  const approvalDecision = nativeDecision(new modules.BashTool(session).approval({ command: params.command }));
  const reviewContext = {
    ...diagnostics,
    sameSettingsInstance: settings === globalSettings,
    nativeDecision: approvalDecision,
    compoundCommands: modules.cfgBashAllowCompoundCommands.get(settings),
    interceptorEnabled: modules.cfgBashInterceptorEnabled.get(settings),
    direnvMode: modules.cfgBashDirenv.get(settings),
    autoBackgroundEnabled: modules.cfgBashAutoBackgroundEnabled.get(settings),
    autoBackgroundThresholdMs: modules.cfgBashAutoBackgroundThresholdMs.get(settings),
    toolsMaxTimeout: modules.cfgToolsMaxTimeout.get(settings),
    worktreeClone: modules.cfgWorktreeClone.get(settings),
  };
  if (policies.bash === "deny") {
    return { settings: { scoped: settings, global: globalSettings },
      fingerprint: digest({ scoped: settingsFingerprint(modules, settings),
        global: settingsFingerprint(modules, globalSettings), route, routeFingerprint, legacyShellAllowed }),
      decision: "deny", reasonCode: "NATIVE_DENY", reviewContext, diagnostics };
  }
  const cwd = targetCwd(baseCwd, params.cwd);
  const direnv = cwd.path ? await nearestEnvrc(cwd.path) :
    { present: false, uncertain: true, marker: "cwd-unavailable" };
  const systemHome = modules.homeDir();
  const shellHome = shell.env?.HOME ?? systemHome;
  // 只有 Bash 本地路径生成 snapshot；未证明路由的旧 sh 保留原有保护。
  const snapshotContext = family === "bash" || (family === "sh" && route === "unverified");
  const startup = snapshotContext ? await userStartupState(shellHome) :
    { present: false, uncertain: false, marker: "not-executed" };
  const inheritedFunctions = Object.keys(shell.env ?? {}).some(key => /^BASH_FUNC_.*%%$/u.test(key));
  const differentHome = shellHome !== systemHome;
  if (snapshotContext && (startup.present || startup.uncertain || inheritedFunctions || differentHome))
    mutable.shellSnapshotUncertain = true;
  const configuredShellPath = modules.cfgShellPath.get(settings);
  const contextReason: NativeDiagnostics["contextReason"] = settings !== globalSettings ? "SETTINGS_MISMATCH" :
    cwd.uncertain || !cwd.path || direnv.uncertain ? "CWD_UNCERTAIN" :
    modules.cfgBashDirenv.get(settings) !== "off" && direnv.present ? "DIRENV_CONTEXT" :
    family === "unknown" ? "SHELL_UNKNOWN" :
    !standardShellArguments(family, shell.args) ? "SHELL_ARGUMENTS" :
    route !== "local-embedded" && !(legacyShellAllowed && (family === "bash" || family === "sh"))
      ? "EXECUTION_ROUTE_UNVERIFIED" :
    configuredShellPath !== undefined && (route !== "local-embedded" || family === "bash" ||
      shellFamily(configuredShellPath) !== family) ? "SHELL_PATH_UNVERIFIED" :
    shell.prefix !== undefined ? "SHELL_PREFIX" :
    startup.uncertain || startup.present ? "BASH_STARTUP" :
    snapshotContext && inheritedFunctions ? "BASH_FUNCTIONS" :
    snapshotContext && differentHome ? "SHELL_HOME_MISMATCH" :
    snapshotContext && mutable.shellSnapshotUncertain ? "BASH_SNAPSHOT_UNCERTAIN" :
    modules.cfgWorktreeClone.get(settings) && /(?:^|[;&|]\s*)git\s+worktree\s+add(?:\s|$)/u.test(params.command)
      ? "WORKTREE_CONTEXT" : "STANDARD_CONTEXT";
  diagnostics.contextReason = contextReason;
  reviewContext.contextReason = contextReason;
  const currentFingerprint = digest({ scoped: settingsFingerprint(modules, settings),
    global: settingsFingerprint(modules, globalSettings), direnv: direnv.marker, startup: startup.marker,
    route, routeFingerprint, legacyShellAllowed,
    physicalCwd: cwd.path ? await realpath(cwd.path).catch(() => "unresolved") : "unavailable" });
  if (approvalDecision === "deny") {
    return { settings: { scoped: settings, global: globalSettings }, fingerprint: currentFingerprint,
      decision: "deny", reasonCode: "NATIVE_DENY", reviewContext, diagnostics };
  }
  if (approvalDecision === "prompt") {
    return { settings: { scoped: settings, global: globalSettings }, fingerprint: currentFingerprint,
      decision: "prompt", reasonCode: "NATIVE_PROMPT", reviewContext, diagnostics };
  }
  if (contextReason !== "STANDARD_CONTEXT") {
    return { settings: { scoped: settings, global: globalSettings }, fingerprint: currentFingerprint, decision: "prompt",
      reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", reviewContext, diagnostics };
  }
  return { settings: { scoped: settings, global: globalSettings }, fingerprint: currentFingerprint, decision: "allow",
    reasonCode: "NATIVE_ALLOW", reviewContext, diagnostics };
}

export function createNativeBashRuntime(modules: NativeModules): NativeBashRuntime {
  const mutable = { shellSnapshotUncertain: false };
  return {
    async capture(baseCwd, params) {
      const settings = modules.findScopedSettings(baseCwd);
      if (!settings) throw new Error("scoped settings unavailable");
      if (!modules.isSettingsInitialized()) throw new Error("global settings unavailable");
      const globalSettings = await modules.getGlobalSettings();
      return analyze(modules, settings, baseCwd, params, globalSettings, mutable);
    },
    async recheck(settings, baseCwd, params) {
      if (!modules.isSettingsInitialized()) throw new Error("global settings unavailable");
      const refs = settings as { scoped?: SettingsLike; global?: SettingsLike };
      const globalSettings = await modules.getGlobalSettings();
      if (!refs.scoped || !refs.global || refs.global !== globalSettings)
        throw new Error("settings identity changed");
      return analyze(modules, refs.scoped, baseCwd, params, globalSettings, mutable);
    },
  };
}

export async function loadNativeBashRuntime(): Promise<NativeBashRuntime> {
  const [config, bash, toolSettings, execSettings, taskSettings] = await Promise.all([
    import("@oh-my-pi/pi-coding-agent/config/settings"),
    import("@oh-my-pi/pi-coding-agent/tools/bash"),
    import("@oh-my-pi/pi-coding-agent/tools/settings"),
    import("@oh-my-pi/pi-coding-agent/exec/settings"),
    import("@oh-my-pi/pi-coding-agent/task/settings"),
  ]);
  return createNativeBashRuntime({
    homeDir: homedir,
    executionRoute: () => executionRoute(process.env.ROTOM_PERMISSION_CONTROL_EXECUTION_ROUTE, process.argv),
    executionRouteFingerprint: () => digest({ marker: process.env.ROTOM_PERMISSION_CONTROL_EXECUTION_ROUTE ?? null,
      argv: process.argv }),
    legacyShellAllowed: () => process.env.ROTOM_PERMISSION_CONTROL_EXECUTION_ROUTE === undefined &&
      executionRoute("local-native-bash-v1", process.argv) === "local-embedded",
    findScopedSettings: config.findScopedSettings,
    isSettingsInitialized: config.isSettingsInitialized,
    getGlobalSettings: config.Settings.init,
    BashTool: bash.BashTool,
    cfgToolsApproval: toolSettings.cfgToolsApproval,
    cfgToolsMaxTimeout: toolSettings.cfgToolsMaxTimeout,
    cfgAsyncEnabled: toolSettings.cfgAsyncEnabled,
    cfgLaunchEnabled: toolSettings.cfgLaunchEnabled,
    cfgBashAllowCompoundCommands: execSettings.cfgBashAllowCompoundCommands,
    cfgBashAutoBackgroundEnabled: execSettings.cfgBashAutoBackgroundEnabled,
    cfgBashAutoBackgroundThresholdMs: execSettings.cfgBashAutoBackgroundThresholdMs,
    cfgBashPatterns: execSettings.cfgBashPatterns,
    cfgBashInterceptorEnabled: execSettings.cfgBashInterceptorEnabled,
    cfgBashInterceptorPatterns: execSettings.cfgBashInterceptorPatterns,
    cfgBashDirenv: execSettings.cfgBashDirenv,
    cfgBashDirenvLoadTimeoutMs: execSettings.cfgBashDirenvLoadTimeoutMs,
    cfgShellPath: execSettings.cfgShellPath,
    cfgWorktreeClone: taskSettings.cfgWorktreeClone,
  } as unknown as NativeModules);
}
