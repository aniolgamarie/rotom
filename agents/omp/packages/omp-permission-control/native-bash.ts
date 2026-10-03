import { lstat, realpath } from "node:fs/promises";
import { createHash } from "node:crypto";
import { homedir } from "node:os";
import { basename, dirname, isAbsolute, join, resolve } from "node:path";
import type { ToolSession } from "@oh-my-pi/pi-coding-agent/tools";

export interface PlainBashParams {
  command: string;
  cwd?: string;
  timeout?: number;
}

export interface NativeSettingsSnapshot {
  settings: object;
  fingerprint: string;
  decision: "allow" | "deny" | "prompt";
  reasonCode: "NATIVE_ALLOW" | "NATIVE_DENY" | "NATIVE_PROMPT" | "UNSUPPORTED_EXECUTION_CONTEXT";
  reviewContext: Record<string, string | number | boolean | null>;
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

async function userStartupState(shell: string, home: string): Promise<{ present: boolean; uncertain: boolean;
  marker: string }> {
  const name = basename(shell).toLowerCase();
  const candidates = name.includes("zsh") ? [".zshrc", ".zprofile"] :
    name.includes("fish") ? [join(".config", "fish", "config.fish")] :
      [".bashrc", ".bash_profile", ".bash_login", ".profile"];
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
  const session = {
    cwd: baseCwd,
    hasUI: false,
    getSessionFile: () => null,
    getSessionSpawns: () => null,
    settings,
  } as unknown as ToolSession;
  const approvalDecision = nativeDecision(new modules.BashTool(session).approval({ command: params.command }));
  const reviewContext = {
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
        global: settingsFingerprint(modules, globalSettings) }),
      decision: "deny", reasonCode: "NATIVE_DENY", reviewContext };
  }
  const cwd = targetCwd(baseCwd, params.cwd);
  const shell = settings.getShellConfig();
  const direnv = cwd.path ? await nearestEnvrc(cwd.path) :
    { present: false, uncertain: true, marker: "cwd-unavailable" };
  const systemHome = modules.homeDir();
  const shellHome = shell.env?.HOME ?? systemHome;
  const startup = await userStartupState(shell.shell, shellHome);
  const inheritedFunctions = Object.keys(shell.env ?? {}).some(key => /^BASH_FUNC_.*%%$/u.test(key));
  const differentHome = shellHome !== systemHome;
  if (startup.present || startup.uncertain || inheritedFunctions || differentHome)
    mutable.shellSnapshotUncertain = true;
  const standardShell = /^(?:bash|sh)$/iu.test(basename(shell.shell)) &&
    (canonical(shell.args) === canonical(["-l", "-c"]) || canonical(shell.args) === canonical(["-c"]));
  const mutableContext = settings !== globalSettings || cwd.uncertain || !cwd.path || direnv.uncertain ||
    (modules.cfgBashDirenv.get(settings) !== "off" && direnv.present) || startup.uncertain || startup.present ||
    !standardShell || modules.cfgShellPath.get(settings) !== undefined || shell.prefix !== undefined ||
    inheritedFunctions || differentHome || mutable.shellSnapshotUncertain ||
    (modules.cfgWorktreeClone.get(settings) && /(?:^|[;&|]\s*)git\s+worktree\s+add(?:\s|$)/u.test(params.command));
  const currentFingerprint = digest({ scoped: settingsFingerprint(modules, settings),
    global: settingsFingerprint(modules, globalSettings), direnv: direnv.marker, startup: startup.marker,
    physicalCwd: cwd.path ? await realpath(cwd.path).catch(() => "unresolved") : "unavailable" });
  if (approvalDecision === "deny") {
    return { settings: { scoped: settings, global: globalSettings }, fingerprint: currentFingerprint,
      decision: "deny", reasonCode: "NATIVE_DENY", reviewContext };
  }
  if (approvalDecision === "prompt") {
    return { settings: { scoped: settings, global: globalSettings }, fingerprint: currentFingerprint,
      decision: "prompt", reasonCode: "NATIVE_PROMPT", reviewContext };
  }
  if (mutableContext) {
    return { settings: { scoped: settings, global: globalSettings }, fingerprint: currentFingerprint, decision: "prompt",
      reasonCode: "UNSUPPORTED_EXECUTION_CONTEXT", reviewContext };
  }
  return { settings: { scoped: settings, global: globalSettings }, fingerprint: currentFingerprint, decision: "allow",
    reasonCode: "NATIVE_ALLOW", reviewContext };
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
