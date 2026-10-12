// 仅公开SettingsManager与私有文件原语；跨进程排他由host租约提供，不能独立用作多进程锁。
import { basename, isAbsolute, resolve } from "node:path";
import { optionalPrivateBytes, writePrivate } from "./private-files.ts";
import { strictJson } from "./strict-json.ts";

const fail = (code = "pi-settings-invalid", exitCode = 2) => { const error = new Error(code); error.exitCode = exitCode; throw error; };
const boolean = value => typeof value === "boolean";
const number = value => typeof value === "number" && Number.isFinite(value);
const string = value => typeof value === "string" && !/[\u0000-\u001f\u007f]/.test(value);
// 命令参数可能包含秘密；本阶段editor/shell仅接受单一绝对路径，参数绑定另行设计。
const executablePath = value => string(value) && (value === "" || isAbsolute(value) && !/\s|:/.test(value));
const strings = value => Array.isArray(value) && value.every(string);
const choice = (...values) => value => values.includes(value);
const plain = value => value !== null && typeof value === "object" && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value)) && !Object.getOwnPropertySymbols(value).length
  && Object.values(Object.getOwnPropertyDescriptors(value)).every(item => Object.hasOwn(item, "value") && item.enumerable);
const object = fields => value => plain(value) && Object.entries(value).every(([key, item]) => Object.hasOwn(fields, key) && fields[key](item));
const record = validate => value => plain(value) && Object.entries(value).every(([key, item]) => string(key) && key.length
  && !["__proto__", "constructor", "prototype"].includes(key) && validate(item));
const thinking = choice("off", "minimal", "low", "medium", "high", "xhigh", "max");
const modelCompaction = object({ reserveTokens: number, keepRecentTokens: number });
const fields = {
  lastChangelogVersion: string, defaultProvider: string, defaultModel: string, defaultThinkingLevel: thinking, modelThinkingLevels: record(thinking),
  transport: choice("sse", "websocket", "websocket-cached", "auto"), steeringMode: choice("all", "one-at-a-time"), followUpMode: choice("all", "one-at-a-time"), theme: string,
  compaction: object({ enabled: boolean, reserveTokens: number, keepRecentTokens: number, modelOverrides: record(modelCompaction) }),
  branchSummary: object({ reserveTokens: number, skipPrompt: boolean }),
  retry: object({ enabled: boolean, maxRetries: number, baseDelayMs: number, maxAgentDelayMs: number,
    provider: object({ timeoutMs: number, maxRetries: number, maxRetryDelayMs: number }) }),
  hideThinkingBlock: boolean, showCacheMissNotices: boolean, externalEditor: executablePath, shellPath: executablePath,
  quietStartup: choice(true, false, "header"), defaultProjectTrust: choice("ask", "always", "never"), shellCommandPrefix: string, npmCommand: strings,
  collapseChangelog: boolean, enableInstallTelemetry: boolean, enableAnalytics: boolean, trackingId: string, deviceId: string,
  packages: value => Array.isArray(value) && value.length === 0, extensions: strings, skills: strings, prompts: strings, themes: strings,
  enableSkillCommands: boolean,
  terminal: object({ showImages: boolean, imageWidthCells: number, clearOnShrink: boolean, showTerminalProgress: boolean,
    hyperlinks: choice(true, false, "auto"), images: choice("kitty", "iterm2", "auto", false), trueColor: choice(true, false, "auto") }),
  images: object({ autoResize: boolean, blockImages: boolean }), enabledModels: strings, defaultTools: strings,
  doubleEscapeAction: choice("fork", "tree", "none"), treeFilterMode: choice("default", "no-tools", "user-only", "labeled-only", "all"),
  thinkingBudgets: object({ minimal: number, low: number, medium: number, high: number }), editorPaddingX: number, outputPad: choice(0, 1),
  autocompleteMaxVisible: number, showHardwareCursor: boolean, markdown: object({ codeBlockIndent: string, mermaid: choice("off", "final", "streaming") }),
  warnings: object({ anthropicExtraUsage: boolean }), codemode: object({ mode: choice("on", "only"), inlineBudget: number }), sessionDir: string,
  httpProxy: string, httpIdleTimeoutMs: number, cacheWarming: choice("off", "streaming", "idle"), websocketConnectTimeoutMs: number,
  tuiMode: choice("regular", "fullscreen"), fullscreenExitOutput: choice("transcript", "resume-hint"), fullscreenScrollbar: choice("hidden", "auto", "always"),
  fullscreenCopyOnSelect: boolean, fullscreenWheelScrollLines: value => value === "auto" || number(value),
};
const validate = object(fields);
const policy = Object.freeze({ defaultProjectTrust: "never", enableInstallTelemetry: false, enableAnalytics: false, cacheWarming: "off" });

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (plain(value)) return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}

function freeze(value) {
  if (value !== null && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}

// 已核对官方1.0.1的四类旧存储别名；仅只读投影，不调用宿主私有迁移或改写原盘。
function normalizeLegacy(value) {
  if (!plain(value)) fail();
  const result = { ...value };
  const conflict = () => fail("pi-settings-conflicting-legacy");
  if (Object.hasOwn(result, "queueMode")) {
    if (Object.hasOwn(result, "steeringMode")) conflict();
    if (!fields.steeringMode(result.queueMode)) fail();
    result.steeringMode = result.queueMode; delete result.queueMode;
  }
  if (Object.hasOwn(result, "websockets")) {
    if (Object.hasOwn(result, "transport")) conflict();
    if (!boolean(result.websockets)) fail();
    result.transport = result.websockets ? "websocket" : "sse"; delete result.websockets;
  }
  if (plain(result.skills)) {
    const skills = result.skills;
    if (Object.hasOwn(skills, "enableSkillCommands") && Object.hasOwn(result, "enableSkillCommands")) conflict();
    if (!object({ enableSkillCommands: boolean, customDirectories: value => Array.isArray(value) && value.length === 0 })(skills)) fail();
    if (Object.hasOwn(skills, "enableSkillCommands")) result.enableSkillCommands = skills.enableSkillCommands;
    result.skills = [];
  }
  if (plain(result.retry) && Object.hasOwn(result.retry, "maxDelayMs")) {
    const retry = result.retry;
    if (plain(retry.provider) && Object.hasOwn(retry.provider, "maxRetryDelayMs")) conflict();
    if (!number(retry.maxDelayMs) || Object.hasOwn(retry, "provider") && !plain(retry.provider)) fail();
    result.retry = { ...retry, provider: { ...retry.provider, maxRetryDelayMs: retry.maxDelayMs } };
    delete result.retry.maxDelayMs;
  }
  return result;
}

function effective(value, phase) {
  if (phase === "read") value = normalizeLegacy(value);
  if (!validate(value)) fail();
  for (const key of ["packages", "extensions", "skills", "prompts", "themes"]) if (value[key]?.length) fail();
  for (const key of ["httpProxy", "shellCommandPrefix", "npmCommand", "trackingId", "deviceId"]) if (value[key]?.length) fail("pi-settings-sensitive-value");
  if (value.defaultProjectTrust !== undefined && value.defaultProjectTrust !== "never") fail("pi-settings-runtime-policy");
  for (const [key, expected] of Object.entries(policy)) {
    if (phase === "effective" ? value[key] !== expected : phase === "write" && Object.hasOwn(value, key) && value[key] !== expected) fail("pi-settings-runtime-policy");
  }
  return canonical({ ...value, ...policy });
}

function parse(text) {
  try { return strictJson(text); } catch { fail(); }
}

export function createOfficialSettings({ sdk, path }) {
  if (typeof path !== "string" || !isAbsolute(path) || resolve(path) !== path || !string(path)
      || ["auth.json", "models.json"].includes(basename(path).toLowerCase())) fail("pi-settings-path");
  const read = () => {
    try {
      const bytes = optionalPrivateBytes(path, 1024 * 1024);
      if (bytes === undefined) return undefined;
      return new TextDecoder("utf8", { fatal: true }).decode(bytes);
    } catch {
      fail("pi-settings-private", 4);
    }
  };
  const readEffective = text => effective(text === undefined ? {} : parse(text), "read");
  // 先独立验证；官方SettingsManager可能把储存错误记入队列，不能因此默认成功。
  readEffective(read());
  let locked = false;
  const storage = Object.freeze({ withLock(scope, fn) {
    if (!["global", "project"].includes(scope) || typeof fn !== "function") fail();
    if (locked) fail("pi-settings-reentry", 4);
    locked = true;
    try {
      if (scope === "project") { if (fn(undefined) !== undefined) fail("pi-settings-project-write", 4); return; }
      const current = read(), normalized = JSON.stringify(readEffective(current));
      const next = fn(normalized);
      if (next !== undefined) {
        const value = effective(parse(next), "write");
        if (read() !== current) fail("pi-settings-stale", 4);
        writePrivate(path, JSON.stringify(value));
      }
    } finally { locked = false; }
  } });
  if (typeof sdk?.SettingsManager?.fromStorage !== "function") fail("pi-settings-sdk-incompatible", 5);
  const settingsManager = sdk.SettingsManager.fromStorage(storage, { projectTrusted: false });
  if (typeof settingsManager?.getSettings !== "function") fail("pi-settings-sdk-incompatible", 5);
  const snapshot = () => {
    const disk = readEffective(read()), manager = effective(settingsManager.getSettings(), "effective");
    if (JSON.stringify(manager) !== JSON.stringify(disk)) fail("pi-settings-stale", 4);
    return freeze(manager);
  };
  snapshot();
  return Object.freeze({ settingsManager, snapshot });
}
