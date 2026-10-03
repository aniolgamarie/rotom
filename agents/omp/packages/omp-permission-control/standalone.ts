import { lstat, readFile } from "node:fs/promises";
import { join } from "node:path";
import type { ExtensionAPI, ExtensionContext } from "@oh-my-pi/pi-coding-agent";
import { matchesNativePattern, parseGenericCommands } from "./standalone-shell-analysis";
import { parseStandaloneJson, reviewCommand, type ReviewAttempt, type ReviewRuntime, type ReviewTarget,
  type ReviewerModel, type ReviewSequenceResult } from "./standalone-reviewer";

type Mode = "smart" | "manual";
type Approval = "allow" | "prompt" | "deny";

export interface StandaloneConfig {
  schemaVersion: 2;
  defaultMode: Mode;
  reviewer: "session" | ReviewTarget;
  remoteFallback?: ReviewTarget;
  fallback?: { provider: "local"; model: "lfm2.5-230m"; installedOnly: true };
  pluginId: "omp-permission-control";
  pluginDigest: string;
  policyVersion: string;
  nativePatterns: Array<{ match: string; approval: Approval }>;
}

interface State {
  mode: Mode;
  generation: number;
  pending: Set<AbortController>;
  primary: LayerState;
  remote: LayerState;
  human: { calls: number; health: "idle" | "approved" | "denied" | "unavailable" };
  last: { outcome: string; source: "primary" | "remote" | "human" | "native" | "none";
    reasonCode: string; chain: Array<"primary" | "remote" | "human" | "native"> };
}

interface LayerState {
  configured: string;
  actualModel?: string;
  calls: number;
  health: "idle" | "ready" | "unavailable" | "unsupported" | "transport" | "invalid" | "cancelled" | "timeout";
}

interface StandaloneDependencies {
  loadConfig?: () => Promise<StandaloneConfig>;
  fetch?: typeof fetch;
}

const HEX64 = /^[0-9a-f]{64}$/u;
const CONFIG_KEYS = new Set(["schemaVersion", "defaultMode", "reviewer", "remoteFallback", "fallback",
  "pluginId", "pluginDigest", "policyVersion", "nativePatterns"]);
const TARGET_KEYS = new Set(["provider", "model"]);

function exactKeys(value: unknown, allowed: Set<string>): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value) &&
    Object.keys(value).every(key => allowed.has(key));
}

function target(value: unknown): value is ReviewTarget {
  return exactKeys(value, TARGET_KEYS) && Object.keys(value).length === 2 &&
    typeof value.provider === "string" && value.provider.length > 0 &&
    typeof value.model === "string" && value.model.length > 0;
}

export function validateStandaloneConfig(value: unknown): StandaloneConfig {
  if (!exactKeys(value, CONFIG_KEYS) || value.schemaVersion !== 2 ||
      (value.defaultMode !== "smart" && value.defaultMode !== "manual") ||
      !(value.reviewer === "session" || target(value.reviewer)) ||
      (value.remoteFallback !== undefined && !target(value.remoteFallback)) ||
      value.pluginId !== "omp-permission-control" || !HEX64.test(String(value.pluginDigest)) ||
      !HEX64.test(String(value.policyVersion)) || !Array.isArray(value.nativePatterns))
    throw new Error("invalid permission-control configuration");
  if (value.fallback !== undefined && (!exactKeys(value.fallback, new Set(["provider", "model", "installedOnly"])) ||
      Object.keys(value.fallback).length !== 3 || value.fallback.provider !== "local" ||
      value.fallback.model !== "lfm2.5-230m" || value.fallback.installedOnly !== true))
    throw new Error("invalid permission-control configuration");
  for (const pattern of value.nativePatterns) {
    if (!exactKeys(pattern, new Set(["match", "approval"])) || Object.keys(pattern).length !== 2 ||
        typeof pattern.match !== "string" || pattern.match.length === 0 ||
        !["allow", "prompt", "deny"].includes(String(pattern.approval)))
      throw new Error("invalid permission-control configuration");
  }
  return value as unknown as StandaloneConfig;
}

export async function loadStandaloneConfig(): Promise<StandaloneConfig> {
  const { getAgentDir } = await import("@oh-my-pi/pi-coding-agent");
  const path = join(getAgentDir(), "permission-control.json");
  const stat = await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("invalid permission-control configuration");
  return validateStandaloneConfig(parseStandaloneJson(await readFile(path, "utf8"), 64 * 1024));
}

function textResult(text: string, details: Record<string, unknown> = {}, isError = false) {
  return { content: [{ type: "text" as const, text }], details, ...(isError ? { isError: true } : {}) };
}

function boundedOutput(value: string): string {
  const limit = 64 * 1024;
  const encoded = new TextEncoder().encode(value);
  return encoded.length <= limit ? value : `${new TextDecoder().decode(encoded.slice(0, limit))}\n[output truncated]`;
}

function userMessages(ctx: ExtensionContext): string[] {
  const messages: string[] = [];
  for (const entry of ctx.sessionManager.getBranch()) {
    if (entry.type !== "message" || entry.message.role !== "user" || entry.message.synthetic ||
        entry.message.attribution === "agent") continue;
    const content = entry.message.content;
    const text = typeof content === "string" ? content : content
      .filter(part => part.type === "text").map(part => part.text).join("\n");
    if (text) messages.push(text);
  }
  return messages;
}

function containsSensitiveText(command: string, cwd: string, messages: string[]): boolean {
  const text = [command, cwd, ...messages].join("\n");
  return /(?:api[_-]?key|access[_-]?token|secret|password|authorization)\s*[:=]\s*\S+/iu.test(text) ||
    /\b(?:sk-[A-Za-z0-9_-]{16,}|gh[opusr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b/u.test(text);
}

function nativeApproval(config: StandaloneConfig, command: string): Approval | "unsupported" {
  const parsed = parseGenericCommands(command);
  if (parsed.status !== "complete") return "unsupported";
  let result: Approval = "allow";
  for (const simple of parsed.commands) {
    for (const pattern of config.nativePatterns) {
      if (!matchesNativePattern(simple, pattern.match)) continue;
      if (pattern.approval === "deny") return "deny";
      if (pattern.approval === "prompt") result = "prompt";
    }
  }
  return result;
}

function redactSensitive(value: string): string {
  return value
    .replace(/((?:api[_-]?key|access[_-]?token|secret|password|authorization)\s*[:=]\s*)\S+/giu,
      "$1[REDACTED]")
    .replace(/\b(?:sk-[A-Za-z0-9_-]{16,}|gh[opusr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b/gu, "[REDACTED]");
}

async function humanApprove(ctx: ExtensionContext, command: string, cwd: string,
  signal?: AbortSignal): Promise<boolean> {
  if (!ctx.hasUI || signal?.aborted) return false;
  try {
    const title = `Allow permission_bash?\ncwd: ${JSON.stringify(redactSensitive(cwd))}\n` +
      `command: ${JSON.stringify(redactSensitive(command))}`;
    return await ctx.ui.select(title, ["Approve", "Deny"], { signal }) === "Approve";
  } catch {
    return false;
  }
}

function configuredTarget(value: "session" | ReviewTarget | undefined): string {
  if (!value) return "disabled";
  return value === "session" ? "session" : `${value.provider}/${value.model}`;
}

function attemptState(configured: string, attempt: ReviewAttempt | undefined): LayerState {
  if (!attempt) return { configured, calls: 0, health: configured === "disabled" ? "unavailable" : "idle" };
  return {
    configured,
    actualModel: attempt.model ? `${attempt.model.provider}/${attempt.model.id}` : undefined,
    calls: attempt.called ? 1 : 0,
    health: attempt.status === "valid" ? "ready" : attempt.health,
  };
}

function recordReview(state: State, config: StandaloneConfig, result: ReviewSequenceResult):
  Array<"primary" | "remote"> {
  const primary = attemptState(configuredTarget(config.reviewer), result.primary);
  state.primary = { ...primary, calls: state.primary.calls + primary.calls };
  if (result.remote) {
    const remote = attemptState(configuredTarget(config.remoteFallback), result.remote);
    state.remote = { ...remote, calls: state.remote.calls + remote.calls };
  }
  return ["primary", ...(result.remote ? ["remote" as const] : [])];
}

function modelIdentity(model: { provider: string; id: string } | undefined): string {
  return model ? `${model.provider}/${model.id}` : "unavailable";
}

function abortPending(state: State): void {
  for (const controller of state.pending) controller.abort();
  state.pending.clear();
}

function reviewRuntime(ctx: ExtensionContext, fetchImpl: typeof fetch): ReviewRuntime {
  const adapt = (model: ReturnType<typeof ctx.models.current>): ReviewerModel | undefined => model && ({
    provider: model.provider, id: model.id, api: model.api, baseUrl: model.baseUrl,
    requestModelId: model.requestModelId,
  });
  return {
    current: () => adapt(ctx.models.current()),
    resolve: spec => adapt(ctx.models.resolve(spec)),
    getApiKey: async (model, signal) => {
      const resolved = ctx.models.resolve(`${model.provider}/${model.id}`);
      return resolved ? ctx.modelRegistry.getApiKey(resolved, ctx.sessionManager.getSessionId(), { signal }) : undefined;
    },
    fetch: (input, init) => fetchImpl(input, init),
  };
}

export function createStandalonePlugin(dependencies: StandaloneDependencies = {}) {
  return function standalonePermissionControl(omp: ExtensionAPI): void {
    let config: StandaloneConfig | undefined;
    const state: State = {
      mode: "manual", generation: 0, pending: new Set(),
      primary: { configured: "unavailable", calls: 0, health: "unavailable" },
      remote: { configured: "disabled", calls: 0, health: "unavailable" },
      human: { calls: 0, health: "idle" },
      last: { outcome: "unavailable", source: "none", reasonCode: "NOT_REVIEWED", chain: [] },
    };
    const load = dependencies.loadConfig ?? loadStandaloneConfig;
    let queue = Promise.resolve();

    const acquire = async (signal: AbortSignal): Promise<(() => void) | undefined> => {
      const previous = queue;
      let release!: () => void;
      const gate = new Promise<void>(resolve => { release = resolve; });
      queue = previous.then(() => gate);
      if (signal.aborted) {
        void previous.then(release);
        return undefined;
      }
      try {
        await new Promise<void>((resolve, reject) => {
          const abort = () => reject(new Error("cancelled"));
          signal.addEventListener("abort", abort, { once: true });
          previous.then(() => { signal.removeEventListener("abort", abort); resolve(); });
        });
      } catch {
        void previous.then(release);
        return undefined;
      }
      if (signal.aborted) { release(); return undefined; }
      return release;
    };

    const reset = async () => {
      abortPending(state);
      state.generation++;
      try {
        const registrations = omp.getAllTools().filter(tool => tool.name === "permission_bash");
        if (registrations.length !== 1) throw new Error("permission_bash registration conflict");
        config = await load();
        state.mode = config.defaultMode;
        state.primary = attemptState(configuredTarget(config.reviewer), undefined);
        state.remote = attemptState(configuredTarget(config.remoteFallback), undefined);
        state.human = { calls: 0, health: "idle" };
        state.last = { outcome: "ready", source: "none", reasonCode: "NOT_REVIEWED", chain: [] };
        const active = omp.getActiveTools();
        if (active.includes("bash"))
          await omp.setActiveTools([...new Set([...active.filter(name => name !== "bash"), "permission_bash"])]);
      } catch {
        config = undefined;
        state.mode = "manual";
        state.primary = { configured: "unavailable", calls: 0, health: "unavailable" };
        state.remote = { configured: "disabled", calls: 0, health: "unavailable" };
        state.last = { outcome: "blocked", source: "none", reasonCode: "CONFIG_UNAVAILABLE", chain: [] };
      }
    };

    omp.on("session_start", reset);
    omp.on("session_switch", reset);
    omp.on("session_branch", reset);
    omp.on("session_shutdown", () => { abortPending(state); state.generation++; });

    omp.registerCommand("permission-control", {
      description: "Set or inspect standalone permission control",
      handler: async (args, ctx) => {
        const command = args.trim();
        if (command === "smart" || command === "manual") {
          abortPending(state);
          state.generation++;
          state.mode = command;
          ctx.ui.notify(JSON.stringify({ mode: state.mode, generation: state.generation }), "info");
        } else if (command === "status") {
          ctx.ui.notify(JSON.stringify({ mode: state.mode, generation: state.generation,
            configuration: config ? "ready" : "unavailable",
            primary: state.primary, remote: state.remote, human: state.human,
            fallback: config?.fallback ? "unavailable" : "disabled", pending: state.pending.size,
            nativeProtection: "configured-patterns-plus-native-bash-prompt" }), "info");
        } else if (command === "explain") {
          ctx.ui.notify(JSON.stringify(state.last), "info");
        } else {
          ctx.ui.notify("/permission-control smart\n/permission-control manual\n/permission-control status\n/permission-control explain", "info");
        }
      },
    });

    const Type = omp.typebox.Type;
    omp.registerTool({
      name: "permission_bash",
      label: "Permission Bash",
      description: "Run raw non-interactive Bash after standalone permission review. Service, job, PTY, and native Bash behavior are separate.",
      approval: { tier: "exec", policy: "allow" },
      loadMode: "essential",
      parameters: Type.Object({
        command: Type.String(),
        cwd: Type.Optional(Type.String()),
        timeout: Type.Optional(Type.Number({ minimum: 0, maximum: 120 })),
      }, { additionalProperties: false }),
      async execute(_toolCallId, params, signal, _onUpdate, ctx) {
        if (!config || typeof params.command !== "string" || !params.command ||
            (params.cwd !== undefined && typeof params.cwd !== "string") ||
            (params.timeout !== undefined && (!Number.isFinite(params.timeout) || params.timeout < 0 || params.timeout > 120)))
          return textResult("permission_bash blocked", { reasonCode: "INVALID_OR_UNAVAILABLE" }, true);

        const queuedGeneration = state.generation;
        const pending = new AbortController();
        state.pending.add(pending);
        const combined = signal ? AbortSignal.any([signal, pending.signal]) : pending.signal;
        const release = await acquire(combined);
        if (!release || combined.aborted || state.generation !== queuedGeneration) {
          state.pending.delete(pending);
          return textResult("permission_bash blocked", { reasonCode: "STALE_REVIEW" }, true);
        }
        const startGeneration = state.generation;
        const startSession = ctx.sessionManager.getSessionId();
        const startModel = modelIdentity(ctx.models.current());
        const cwd = params.cwd ?? ctx.cwd;
        let approved = false;
        let source: State["last"]["source"] = "human";
        let reasonCode = "USER_CONFIRMATION_REQUIRED";
        let decisionChain: State["last"]["chain"] = [];
        try {
          const native = nativeApproval(config, params.command);
          if (native === "deny") {
            state.last = { outcome: "denied", source: "native", reasonCode: "NATIVE_DENY", chain: ["native"] };
            return textResult("permission_bash denied", { reasonCode: "NATIVE_DENY" }, true);
          }
          const messages = userMessages(ctx);
          const needsHuman = state.mode === "manual" || native === "prompt" || native === "unsupported" ||
            messages.length === 0 || containsSensitiveText(params.command, cwd, messages);
          if (needsHuman) {
            decisionChain = native === "prompt" ? ["native", "human"] : ["human"];
            state.human.calls++;
            approved = await humanApprove(ctx, params.command, cwd, combined);
            state.human.health = ctx.hasUI ? (approved ? "approved" : "denied") : "unavailable";
            reasonCode = native === "unsupported" ? "UNSUPPORTED_SYNTAX" : "USER_CONFIRMATION_REQUIRED";
          } else {
            const result = await reviewCommand({ command: params.command, cwd, userMessages: messages,
              reviewer: config.reviewer, remoteFallback: config.remoteFallback },
              reviewRuntime(ctx, dependencies.fetch ?? globalThis.fetch), combined);
            const reviewChain = recordReview(state, config, result);
            decisionChain = reviewChain;
            if (result.status === "valid") {
              source = result.source ?? "primary";
              reasonCode = result.review!.reasonCode;
              if (result.review!.decision === "allow") approved = true;
              else if (result.review!.decision === "ask") {
                state.human.calls++;
                approved = await humanApprove(ctx, params.command, cwd, combined);
                state.human.health = ctx.hasUI ? (approved ? "approved" : "denied") : "unavailable";
                source = "human";
                decisionChain = [...reviewChain, "human"];
              }
            } else {
              state.human.calls++;
              approved = await humanApprove(ctx, params.command, cwd, combined);
              state.human.health = ctx.hasUI ? (approved ? "approved" : "denied") : "unavailable";
              source = "human";
              decisionChain = [...reviewChain, "human"];
            }
          }

          if (!approved || combined.aborted || state.generation !== startGeneration ||
              ctx.sessionManager.getSessionId() !== startSession || modelIdentity(ctx.models.current()) !== startModel) {
            state.last = { outcome: "blocked", source, reasonCode: approved ? "STALE_REVIEW" : reasonCode,
              chain: decisionChain };
            return textResult("permission_bash blocked", { reasonCode: state.last.reasonCode }, true);
          }
          const result = await omp.exec("bash", ["--noprofile", "--norc", "-c", params.command], {
            cwd, signal: combined, timeout: params.timeout === undefined ? undefined : params.timeout * 1000,
          });
          state.last = { outcome: result.code === 0 ? "executed" : "failed", source, reasonCode,
            chain: decisionChain };
          const output = [result.stdout, result.stderr].filter(Boolean).map(boundedOutput).join("\n");
          return textResult(output || `(exit ${result.code})`, { code: result.code, killed: result.killed }, result.code !== 0);
        } catch {
          state.last = { outcome: "blocked", source, reasonCode: "RUNTIME_FAILURE",
            chain: decisionChain };
          return textResult("permission_bash blocked", { reasonCode: "RUNTIME_FAILURE" }, true);
        } finally {
          state.pending.delete(pending);
          release();
        }
      },
    });
  };
}

export default createStandalonePlugin();
