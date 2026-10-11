import { mock } from "bun:test";
import { existsSync, lstatSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { basename, dirname, join, resolve } from "node:path";
import { baseConfig, fakeHost, fakeNativeRuntime } from "../agents/omp/packages/omp-permission-control/standalone-fixture";

const SDK_RELATIVE = ".cache/omp-upgrade-1886-20261009/materials/source/oh-my-pi-f068751e2f1dbdbc195977776d47a26db8697495";
function sdkSource(): string | undefined {
  const repository = resolve(import.meta.dir, "..");
  const override = process.env.OMP_OFFICIAL_SDK_ROOT;
  const candidates = override !== undefined ? [resolve(repository, override)] : [join(repository, SDK_RELATIVE)];
  // 已知仓库worktree布局的父clone；不调用Git、不读取全局配置。
  if (override === undefined && basename(dirname(repository)) === "worktrees" && basename(dirname(dirname(repository))) === ".cache")
    candidates.push(join(resolve(repository, "../../.."), SDK_RELATIVE));
  return candidates.find(path => existsSync(join(path, "packages/coding-agent/src/extensibility/extensions/wrapper.ts")));
}
export const SOURCE = sdkSource();
// 锁定已核对的官方f068源：在任何SDK执行导入之前核验完整的运行时纯模块闭包。
const SOURCE_HASHES: Record<string, string> = {
  "packages/agent/src/tool-context.ts": "0dd69a0810450138b958762e05064f91c5593942d0cb38171a793e71bddbcf30",
  "packages/utils/src/abortable.ts": "d57f211accb863e33a2efee693e93819ddc21b3aa2f40e7c5cb8961fd7922007",
  "packages/utils/src/sanitize-text.ts": "a7f2c4a5fb9e7fa6dbdc6dfd36d6dc7faf7abe36e6478c5ca6ed62177484d862",
  "packages/utils/src/fs-error.ts": "cc119ca2c39dd8c7d84df2580719abe6608bec6d06fc19726c0a6ec4ad264eb8",
  "packages/utils/src/type-guards.ts": "86a5fb728ab7635711ea82c2de2dacbcc849e56acd7e4bfaf5041d555a9090dd",
  "packages/ai/src/utils/block-symbols.ts": "5d9f39486f98c1cc34f7b7f7a556c3c42eca7bd37f1f0e834b467972d5ff6db1",
  "packages/ai/src/utils/schema/wire.ts": "139d589619a13e3ba00040e9e673ba2b856ddf917de9dcc6c94f368a7f3a68b5",
  "packages/ai/src/utils/schema/draft.ts": "0bbf70e3d1db2ce735cc820447a9b943b4a868ca3f71fa392fe7e52ff111ca50",
  "packages/ai/src/utils/schema/equality.ts": "e82829d6a592b4acaee73af6b71e2c9f0fcbe6f546f5f7639d0101efc02554c8",
  "packages/ai/src/utils/schema/types.ts": "8e6f8d41e7a370337d96fbb152219001090f61898af6a20efafdbd586160c01d",
  "packages/ai/src/utils/schema/stamps.ts": "96348540f3a1ebb2df9c009ca7592782d8824ad4e2456f2aaece63bd98c93d1e",
  "packages/tui/src/tools/hashline-format.ts": "f6f93702785f3d755dfd0b1d96b3c26e0bd036847e1bba31e402c69bde76c2e4",
  "packages/coding-agent/src/extensibility/extensions/wrapper.ts": "718fe4df14b5a4963fd377c2cc2dd5222fd04b0b45fbe148410174b6c08fbbb3",
  "packages/coding-agent/src/extensibility/extensions/runner.ts": "cdf3f8b2d80da336a443c6cbd5616f84859624b8d73fd5b8347b5572fed5f28c",
  "packages/coding-agent/src/extensibility/extensions/managed-timers.ts": "562a1583c180bd1606f0bb980dc96094c85908c86ec78270e4f4aef7548ee79c",
  "packages/coding-agent/src/extensibility/extensions/model-api.ts": "41ca9b0fcf23430462f23eb68736322fdd5e797271183c2a7ec1cbd2547c64cc",
  "packages/coding-agent/src/extensibility/shared-events.ts": "c587e7ae812ea914dfd899d3bc46393fa294b3beac1078737abd817863edb1cb",
  "packages/coding-agent/src/extensibility/tool-event-input.ts": "b75bb3b14320fb0f60e17ca24b26c838f02ec471decba34e1644470cc280768f",
  "packages/coding-agent/src/extensibility/tool-proxy.ts": "3579adf7dfc51c23c2f2a7bf246fbcb5bf61b4bf6f02f9a0a17d6fc1c0b05032",
  "packages/coding-agent/src/tools/approval.ts": "29e268c49d0d91809af26abc92bf42cd634c20757a80a862bab28cc498ec3db1",
  "packages/coding-agent/src/tools/essential-tools.ts": "ca9858d0744b7fbc01bd58877c7f957b62c98067d8357b341be17a84eef0185e",
  "packages/coding-agent/src/tools/file-write-fallback.ts": "6caf5e4b68d507e20a179918c153237319411bdad5a73e40da1e2a43b6dc196e",
  "packages/coding-agent/src/tools/bash-interceptor.ts": "fad71d2b47a5ff7b2f521b2337760439573672af8a59514e10a97499191c705e",
  "packages/coding-agent/src/tools/bash-worktree-rewrite.ts": "cb681abf8f57403f586be0dace0ce0c858e3f8ad10ee305e4b5c19b63752a48c",
  "packages/coding-agent/src/tools/shell-tokenize.ts": "5bc580a82421fea443cebc7f97026b876544bc0d28df16a8e36ec71955363a44",
};
function verifySource(root: string): Record<string, string> | undefined {
  const actual: Record<string, string> = {};
  for (const [path, expected] of Object.entries(SOURCE_HASHES)) {
    const target = join(root, path);
    let stat;
    try { stat = lstatSync(target); } catch (error) {
      if ((error as { code?: string }).code === "ENOENT") return undefined;
      throw error;
    }
    if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("OFFICIAL_SDK_SOURCE_INVALID");
    const hash = createHash("sha256").update(readFileSync(target)).digest("hex");
    if (hash !== expected) throw new Error("OFFICIAL_SDK_SOURCE_HASH_MISMATCH");
    actual[path] = hash;
  }
  return actual;
}
const modulePath = (path: string) => {
  if (!SOURCE) throw new Error("OFFICIAL_SDK_SOURCE_UNAVAILABLE");
  return join(SOURCE, "packages/coding-agent/src", path);
};
const unexpected = () => { throw new Error("UNEXPECTED_EXTERNAL_IO"); };

export async function officialModules() {
  if (!SOURCE) return undefined;
  const hashes = verifySource(SOURCE);
  if (!hashes) return undefined;
  // 纯函数和包装/runner本体从原SDK导入；只替换外部IO、设置、provider与发现边界。
  const core = await import(join(SOURCE, "packages/agent/src/tool-context.ts"));
  const abort = await import(join(SOURCE, "packages/utils/src/abortable.ts"));
  const sanitize = await import(join(SOURCE, "packages/utils/src/sanitize-text.ts"));
  const fsErrors = await import(join(SOURCE, "packages/utils/src/fs-error.ts"));
  const guards = await import(join(SOURCE, "packages/utils/src/type-guards.ts"));
  const blockSymbols = await import(join(SOURCE, "packages/ai/src/utils/block-symbols.ts"));
  mock.module("@oh-my-pi/pi-agent-core", () => core);
  mock.module("@oh-my-pi/pi-ai/utils/block-symbols", () => blockSymbols);
  mock.module("@oh-my-pi/pi-utils", () => ({ ...abort, ...sanitize, ...fsErrors, ...guards,
    logger: { error: () => {}, warn: () => {}, debug: () => {}, info: () => {} }, structuredCloneJSON: unexpected }));
  mock.module("@oh-my-pi/pi-utils/procmgr", () => ({ refreshShellConfigCache: () => {} }));
  mock.module("@oh-my-pi/pi-tui/theme", () => ({ theme: {} }));
  mock.module("@oh-my-pi/pi-natives", () => ({ hashlineFileHash: unexpected, hashlineFormatHeader: unexpected,
    hashlineFormatNumberedLines: unexpected, hashlineIsReadTruncationNotice: unexpected, hashlineStripPrefixes: unexpected }));
  const hashline = await import(join(SOURCE, "packages/tui/src/tools/hashline-format.ts"));
  mock.module("@oh-my-pi/pi-tui/tools/hashline-format", () => hashline);
  const schema = await import(join(SOURCE, "packages/ai/src/utils/schema/wire.ts"));
  mock.module("@oh-my-pi/pi-ai/utils/schema", () => schema);
  mock.module(modulePath("config/settings.ts"), () => ({ withActiveSettings: (_settings: unknown, operation: () => unknown) => operation() }));
  mock.module(modulePath("tools/settings.ts"), () => ({
    cfgToolsApproval: { get: (settings: any) => settings.policies },
    cfgToolsApprovalMode: { get: (settings: any) => settings.approvalMode },
  }));
  mock.module(modulePath("extensibility/settings.ts"), () => ({ cfgExtensionHandlersToolCallTimeoutMs: { get: (settings: any) => settings.toolCallTimeoutMs } }));
  mock.module(modulePath("config/model-resolver.ts"), () => ({ getModelMatchPreferences: () => ({}),
    resolveModelRoleValue: (spec: string, models: any[]) => ({ model: models.find(model => `${model.provider}/${model.id}` === spec) }) }));
  mock.module(modulePath("capability/rule.ts"), () => ({ MAIN_AGENT_RULE_NAME: "main" }));
  mock.module(modulePath("registry/agent-registry.ts"), () => ({ MAIN_AGENT_ID: "main" }));
  mock.module(modulePath("tools/path-utils.ts"), () => ({ resolveSyscallTarget: unexpected }));
  mock.module(modulePath("exec/settings.ts"), () => ({ DEFAULT_BASH_INTERCEPTOR_RULES: [] }));
  const [wrapper, runner, interceptor, worktree] = await Promise.all([
    import(modulePath("extensibility/extensions/wrapper.ts")), import(modulePath("extensibility/extensions/runner.ts")),
    import(modulePath("tools/bash-interceptor.ts")), import(modulePath("tools/bash-worktree-rewrite.ts")),
  ]);
  return { wrapper, runner, interceptor, worktree, hashes };
}

export async function officialHarness(modules: NonNullable<Awaited<ReturnType<typeof officialModules>>>, options: {
  nativeDecision?: "allow" | "prompt" | "deny";
  select?: string;
  selectImpl?: (...args: any[]) => Promise<string | undefined>;
  fetchImpl?: (url: string, init: RequestInit) => Promise<Response>;
  nativeImpl?: (...args: any[]) => Promise<any>;
  otherHandler?: (event: any, context: any) => any;
  preflight?: (id: string, tool: any, params: any) => any;
  worktreePlan?: object;
  hostPolicy?: "allow" | "prompt" | "deny";
} = {}) {
  const native = fakeNativeRuntime({ decision: options.nativeDecision ?? "allow",
    reasonCode: options.nativeDecision === "deny" ? "NATIVE_DENY" : options.nativeDecision === "prompt" ? "NATIVE_PROMPT" : "NATIVE_ALLOW",
    diagnostics: { shellFamily: "zsh", executionRoute: "local-embedded", contextReason: "STANDARD_CONTEXT" },
    reviewContext: { sameSettingsInstance: true, nativeDecision: options.nativeDecision ?? "allow", ...(options.worktreePlan ? { worktreePlan: options.worktreePlan } : {}) } });
  const h = await fakeHost({ config: { ...baseConfig, nativeBash: true }, nativeRuntime: native.runtime,
    select: options.select ?? "Approve", selectImpl: options.selectImpl, fetchImpl: options.fetchImpl,
    lifecycle: { pollIntervalMs: 5, contextTimeoutMs: 100, queueTimeoutMs: 1000 } });
  const extension = (path: string) => ({ path, resolvedPath: path, handlers: new Map<string, any[]>(), tools: new Map(),
    commands: new Map(), flags: new Map(), shortcuts: new Map(), messageRenderers: new Map(), composerShapes: new Map(),
    assistantThinkingRenderers: [], fileWriteFallbackHandlers: [], fileDeleteFallbackHandlers: [] });
  const plugin = extension("fixture-permission-plugin");
  for (const [name, handler] of h.events) plugin.handlers.set(name, [handler]);
  for (const [name, definition] of h.tools) plugin.tools.set(name, { definition, extensionPath: plugin.path });
  const other = extension("fixture-other-extension");
  if (options.otherHandler) other.handlers.set("tool_call", [options.otherHandler]);
  const settings = { toolCallTimeoutMs: 30, approvalMode: "write", policies: { permission_bash: options.hostPolicy ?? "allow" } };
  const current = h.ctx.models.current();
  const registry = { ...h.ctx.modelRegistry, getAvailable: () => [current] };
  const session = { ...h.ctx.sessionManager, getCwd: () => h.ctx.cwd };
  const runner = new modules.runner.ExtensionRunner([plugin, other], { flagValues: new Map() }, "/fixture", session, registry, undefined, settings);
  const errors: any[] = [];
  runner.onError((event: any) => { errors.push({ event: event.event, error: event.error }); });
  runner.initialize({ appendEntry: h.host.appendEntry, getAllTools: h.host.getAllTools, getActiveTools: h.host.getActiveTools,
    setActiveTools: h.host.setActiveTools, getCommands: () => [], getThinkingLevel: () => "off" },
    { getModel: () => current, isIdle: () => true, abort: () => {}, hasPendingMessages: () => false,
      shutdown: () => {}, getContextUsage: () => undefined, compact: unexpected, getSystemPrompt: () => "fixture" },
    undefined, h.ctx.ui, "interactive");
  const nativeCalls: any[] = [];
  runner.setNativeToolResolver((name: string) => name === "bash" ? { tool: { name: "bash",
    execute: async (...args: any[]) => {
      nativeCalls.push(args);
      args[3]?.({ content: [{ type: "text", text: "fixture-progress" }] });
      return options.nativeImpl ? options.nativeImpl(...args) : { content: [{ type: "text", text: "native-fixture-ok" }], details: { fixture: true } };
    } }, makeContext: () => ({ settings, sessionManager: session }) } : undefined);
  if (options.preflight) runner.setToolCallPreflight({ before: options.preflight });
  await runner.emit({ type: "session_start" });
  const adapter = modules.wrapper.wrapRegisteredTool(plugin.tools.get("bash"), runner);
  const tool = new modules.wrapper.ExtensionToolWrapper(adapter, runner);
  // fake Cursor piBash dispatch保持官方direct-wrapper路径；不启动Cursor传输/OAuth。
  const piBash = (id: string, params: any, signal?: AbortSignal, onUpdate?: any) =>
    tool.execute(id, params, signal, onUpdate, { settings, sessionManager: session });
  return { h, runner, tool, piBash, nativeCalls, errors, settings,
    cleanup: async () => { await runner.emit({ type: "session_shutdown" }); runner.clearManagedTimers(); runner.disposeFileFallbacks(); } };
}
