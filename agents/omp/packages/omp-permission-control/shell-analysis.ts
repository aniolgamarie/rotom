export type CwdCategory =
  | "repo-root"
  | "repo-subdir"
  | "temporary"
  | "home"
  | "outside-repo"
  | "unknown";
export type EffectKind =
  | "read"
  | "write"
  | "delete"
  | "network-send"
  | "secret-access"
  | "device-access"
  | "execute"
  | "dynamic"
  | "unknown"
  | "state-change";
export type EffectRisk = "low" | "medium" | "high" | "unknown";
export type Connector = "start" | "&&" | "||" | ";" | "|";
export type ShellUnknownReason =
  | "invalid-bytes"
  | "dynamic-syntax"
  | "unsupported-syntax"
  | "unresolved-executable"
  | "shell-state-not-verifiable"
  | "unsupported-command"
  | "unsupported-option"
  | "unresolved-target"
  | "unsafe-target"
  | "git-state-not-verifiable";

export interface ExecutableEvidence {
  argv0: string;
  resolvedPath: string;
  identityDigest: string;
  source: "builtin" | "system";
  noRelevantShadowing: boolean;
  resolutionFingerprint: string;
  verified: boolean;
}

export interface TargetEvidence {
  input: string;
  canonical: string;
  fingerprint: string;
  category: string;
  targetType: "file" | "directory" | "cwd";
  normalized: boolean;
  nonSecret: boolean;
  nonDevice: boolean;
  verified: boolean;
  recursiveReadVerified?: boolean;
  recursiveReadScopeFingerprint?: string;
}

export interface GitEvidence {
  repoRoot: string;
  fingerprint: string;
  verified: boolean;
  pagerDisabled: boolean;
  externalDiffDisabled: boolean;
  textconvDisabled: boolean;
  optionalLocksDisabled: boolean;
  fsmonitorDisabled: boolean;
  hooksDisabled: boolean;
  configOverridesDisabled: boolean;
  configIncludesDisabled: boolean;
  aliasesDisabled: boolean;
  repositoryReadScopeVerified: boolean;
  repositoryReadScopeFingerprint: string;
}

export interface ShellStateEvidence {
  fingerprint: string;
  verified: boolean;
  trapsDisabled: boolean;
  optionsSafe: boolean;
  implicitCommandsAbsent: boolean;
}

export interface ShellAnalysisContext {
  cwd: { path: string; category: CwdCategory; fingerprint: string; verified: boolean };
  shellState: ShellStateEvidence;
  executables: Record<string, ExecutableEvidence | undefined>;
  targets: Record<string, TargetEvidence | undefined>;
  git?: GitEvidence;
}

export interface ShellCommandAnalysis {
  commandId: string;
  connector: Connector;
  argv: string[];
}

export interface ShellEffect {
  effectId: string;
  kind: EffectKind;
  target: string;
  parameters: string[];
  cwdCategory: CwdCategory;
  risk: EffectRisk;
}

export interface ShellAnalysis {
  status: "complete" | "unknown";
  commands: ShellCommandAnalysis[];
  effects: ShellEffect[];
  unknowns: ShellUnknownReason[];
}

type Redirection = { kind: "input" | "output"; target: string };
type ParsedCommand = { connector: Connector; argv: string[]; redirections: Redirection[] };
type LexToken =
  | { kind: "word"; value: string }
  | { kind: "connector"; value: Connector }
  | { kind: "redir"; value: "<" | ">" | ">>" };

const HEX_64 = /^[0-9a-f]{64}$/u;
const CONTROL_WORDS = new Set([
  "if",
  "then",
  "elif",
  "else",
  "fi",
  "for",
  "select",
  "while",
  "until",
  "do",
  "done",
  "case",
  "esac",
  "function",
  "source",
  ".",
  "bash",
  "sh",
  "zsh",
  "eval",
  "exec",
]);
const SUPPORTED = new Set(["pwd", "ls", "head", "wc", "rg", "git"]);

function unique<T>(values: T[]): T[] {
  return [...new Set(values)];
}

function isSha256Digest(value: unknown): value is string {
  return typeof value === "string" && value.length === 64 && HEX_64.test(value);
}

function hasForbiddenControl(input: string): boolean {
  for (const ch of input) {
    const code = ch.charCodeAt(0);
    if (
      code <= 0x08 ||
      (code >= 0x0b && code <= 0x0c) ||
      (code >= 0x0e && code <= 0x1f) ||
      code === 0x7f
    )
      return true;
  }
  return false;
}

function unknownAnalysis(
  reason: ShellUnknownReason,
  commands: ShellCommandAnalysis[] = [],
): ShellAnalysis {
  return {
    status: "unknown",
    commands,
    effects: [
      {
        effectId: "effect-1",
        kind: "unknown",
        target: "unknown",
        parameters: [],
        cwdCategory: "unknown",
        risk: "unknown",
      },
    ],
    unknowns: [reason],
  };
}

function lex(input: string): { tokens?: LexToken[]; error?: ShellUnknownReason } {
  if (input.length === 0 || hasForbiddenControl(input)) return { error: "invalid-bytes" };
  if (/[\r\n]/u.test(input)) return { error: "unsupported-syntax" };
  const tokens: LexToken[] = [];
  let word = "";
  let wordStarted = false;
  let quote: "single" | "double" | undefined;
  let atBoundary = true;
  const flush = () => {
    if (wordStarted) tokens.push({ kind: "word", value: word });
    word = "";
    wordStarted = false;
  };
  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (quote === "single") {
      if (ch === "'") quote = undefined;
      else word += ch;
      atBoundary = false;
      continue;
    }
    if (quote === "double") {
      if (ch === '"') {
        quote = undefined;
        atBoundary = false;
        continue;
      }
      if (ch === "$" || ch === "`") return { error: "dynamic-syntax" };
      if (ch === "\\") {
        const next = input[++i];
        if (next === undefined) return { error: "unsupported-syntax" };
        word += '$`"\\'.includes(next) ? next : `\\${next}`;
      } else word += ch;
      atBoundary = false;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch === "'" ? "single" : "double";
      wordStarted = true;
      atBoundary = false;
      continue;
    }
    if (ch === "\\") {
      const next = input[++i];
      if (next === undefined) return { error: "unsupported-syntax" };
      word += next;
      wordStarted = true;
      atBoundary = false;
      continue;
    }
    if (ch === "$" || ch === "`" || ch === "*" || ch === "?" || ch === "[")
      return { error: "dynamic-syntax" };
    if (ch === "(" || ch === ")" || ch === "{" || ch === "}")
      return { error: "unsupported-syntax" };
    if (ch === " " || ch === "\t") {
      flush();
      atBoundary = true;
      continue;
    }
    if (ch === "#" && atBoundary && word.length === 0) {
      flush();
      break;
    }
    if (ch === "~" && !wordStarted) return { error: "dynamic-syntax" };
    if (ch === "&") {
      flush();
      if (input[i + 1] !== "&") return { error: "dynamic-syntax" };
      i++;
      tokens.push({ kind: "connector", value: "&&" });
      atBoundary = true;
      continue;
    }
    if (ch === "|") {
      flush();
      if (input[i + 1] === "|") {
        i++;
        tokens.push({ kind: "connector", value: "||" });
      } else tokens.push({ kind: "connector", value: "|" });
      atBoundary = true;
      continue;
    }
    if (ch === ";") {
      flush();
      if (input[i + 1] === ";") return { error: "unsupported-syntax" };
      tokens.push({ kind: "connector", value: ";" });
      atBoundary = true;
      continue;
    }
    if (ch === "<" || ch === ">") {
      flush();
      if (ch === "<" && input[i + 1] === "<") return { error: "dynamic-syntax" };
      if (ch === ">" && input[i + 1] === ">") {
        i++;
        tokens.push({ kind: "redir", value: ">>" });
      } else tokens.push({ kind: "redir", value: ch });
      atBoundary = true;
      continue;
    }
    word += ch;
    wordStarted = true;
    atBoundary = false;
  }
  if (quote) return { error: "unsupported-syntax" };
  flush();
  return { tokens };
}

function parseCommands(tokens: LexToken[]): {
  commands?: ParsedCommand[];
  error?: ShellUnknownReason;
} {
  const commands: ParsedCommand[] = [];
  let connector: Connector = "start";
  let argv: string[] = [];
  let redirections: Redirection[] = [];
  const flush = (): boolean => {
    if (argv.length === 0) return false;
    commands.push({ connector, argv, redirections });
    argv = [];
    redirections = [];
    return true;
  };
  for (let i = 0; i < tokens.length; i++) {
    const token = tokens[i];
    if (token.kind === "connector") {
      if (!flush()) return { error: "unsupported-syntax" };
      connector = token.value;
      continue;
    }
    if (token.kind === "redir") {
      if (token.value !== "<" && argv.at(-1)?.match(/^\d+$/u))
        return { error: "unsupported-syntax" };
      const target = tokens[++i];
      if (!target || target.kind !== "word") return { error: "unsupported-syntax" };
      redirections.push({ kind: token.value === "<" ? "input" : "output", target: target.value });
      continue;
    }
    argv.push(token.value);
  }
  if (!flush()) return { error: "unsupported-syntax" };
  return { commands };
}

/** 仅提供完整语法与选项白名单的候选名字，供宿主检查 shadowing/连续性。
 * 不证明 executable、目标、环境或授权；不能直接用于审批 allow。 */
export function inspectReadCommandNames(input: string): readonly string[] | undefined {
  const commands = inspectReadCommands(input);
  return commands && Object.freeze(commands.map(command => command.argv[0]));
}

/** 宿主据此收集目标/可执行文件证据；此解析结果本身没有放行资格。 */
export function inspectReadCommands(input: string): readonly Readonly<{
  argv: readonly string[]; connector: Connector; targets: readonly string[]; recursive: boolean;
  hasInputRedirection: boolean;
}>[] | undefined {
  const lexical = lex(input);
  if (!lexical.tokens || lexical.error) return undefined;
  const parsed = parseCommands(lexical.tokens);
  if (!parsed.commands || parsed.error) return undefined;
  const validators: Record<string, (argv: string[]) => string[] | undefined> = {
    pwd: pwdTargets, ls: lsTargets, head: headTargets, wc: wcTargets, rg: rgTargets, git: gitTargets,
  };
  if (parsed.commands.some(command => command.redirections.some(redirection => redirection.kind === "output") ||
    !Object.hasOwn(validators, command.argv[0]) ||
    !validators[command.argv[0]]?.(command.argv))) return undefined;
  return Object.freeze(parsed.commands.map(command => Object.freeze({
    argv: Object.freeze([...command.argv]), connector: command.connector,
    hasInputRedirection: command.redirections.some(redirection => redirection.kind === "input"),
    targets: Object.freeze([...validators[command.argv[0]](command.argv)!,
      ...command.redirections.map(redirection => redirection.target)]),
    recursive: command.argv[0] === "rg" || command.argv[0] === "git" ||
      (command.argv[0] === "ls" && command.argv.slice(1).some(arg => /^-[^-]*R/u.test(arg))),
  })));
}

function validExecutable(name: string, context: ShellAnalysisContext): boolean {
  const proof = context.executables[name];
  const shellState = context.shellState;
  if (
    !shellState ||
    !shellState.verified ||
    !shellState.trapsDisabled ||
    !shellState.optionsSafe ||
    !shellState.implicitCommandsAbsent ||
    !isSha256Digest(shellState.fingerprint)
  )
    return false;
  return Boolean(
    proof &&
    proof.argv0 === name &&
    proof.verified &&
    proof.noRelevantShadowing &&
    (proof.source === "builtin" || proof.source === "system") &&
    proof.resolvedPath.length > 0 &&
    isSha256Digest(proof.identityDigest) &&
    isSha256Digest(proof.resolutionFingerprint),
  );
}

function targetProof(
  input: string,
  context: ShellAnalysisContext,
  recursiveRead = false,
): TargetEvidence | undefined {
  const proof = context.targets[input];
  if (
    !proof ||
    proof.input !== input ||
    !proof.verified ||
    !proof.normalized ||
    !proof.nonSecret ||
    !proof.nonDevice ||
    !new Set(["file", "directory", "cwd"]).has(proof.targetType) ||
    !proof.canonical ||
    !isSha256Digest(proof.fingerprint) ||
    (recursiveRead &&
      (!proof.recursiveReadVerified || !isSha256Digest(proof.recursiveReadScopeFingerprint)))
  )
    return undefined;
  return proof;
}

function pwdTargets(argv: string[]): string[] | undefined {
  return argv.length === 1 || (argv.length === 2 && (argv[1] === "-L" || argv[1] === "-P"))
    ? ["cwd"]
    : undefined;
}

function lsTargets(argv: string[]): string[] | undefined {
  const short = new Set("al1dhRtSinF".split(""));
  const targets: string[] = [];
  let options = true;
  for (const arg of argv.slice(1)) {
    if (options && arg === "--") {
      options = false;
      continue;
    }
    if (options && arg === "--color=never") continue;
    if (
      options &&
      arg.startsWith("-") &&
      arg.length > 1 &&
      !arg.startsWith("--") &&
      arg
        .slice(1)
        .split("")
        .every((ch) => short.has(ch))
    )
      continue;
    if (options && arg.startsWith("-")) return undefined;
    options = false;
    targets.push(arg);
  }
  return targets.length > 0 ? targets : ["cwd"];
}

function lsRequestsRecursiveRead(argv: string[]): boolean {
  for (const arg of argv.slice(1)) {
    if (arg === "--") return false;
    if (!arg.startsWith("-") || arg.startsWith("--")) continue;
    if (arg.slice(1).includes("R")) return true;
  }
  return false;
}

function headTargets(argv: string[]): string[] | undefined {
  const targets: string[] = [];
  for (let i = 1; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "-n" || arg === "-c") {
      const count = argv[++i];
      if (!count || !/^[1-9][0-9]*$/u.test(count)) return undefined;
    } else if (arg.startsWith("-")) return undefined;
    else targets.push(arg);
  }
  return targets;
}

function wcTargets(argv: string[]): string[] | undefined {
  const targets: string[] = [];
  let sawMode = false;
  for (const arg of argv.slice(1)) {
    if (/^-[lwcmL]+$/u.test(arg)) {
      sawMode = true;
      continue;
    }
    if (arg.startsWith("-")) return undefined;
    targets.push(arg);
  }
  return sawMode ? targets : undefined;
}

function rgTargets(argv: string[]): string[] | undefined {
  const flags = new Set([
    "--fixed-strings",
    "--line-number",
    "--files",
    "--count",
    "--hidden",
    "--word-regexp",
    "--ignore-case",
    "--files-with-matches",
  ]);
  const valueFlags = new Set(["--context", "--max-count"]);
  let files = false;
  const positional: string[] = [];
  for (let i = 1; i < argv.length; i++) {
    const arg = argv[i];
    if (flags.has(arg)) {
      if (arg === "--files") files = true;
      continue;
    }
    if (valueFlags.has(arg)) {
      const value = argv[++i];
      if (!value || !/^[0-9]+$/u.test(value)) return undefined;
      continue;
    }
    if (/^--(?:context|max-count)=[0-9]+$/u.test(arg)) continue;
    if (arg === "--") {
      positional.push(...argv.slice(i + 1));
      break;
    }
    if (arg.startsWith("-")) return undefined;
    positional.push(arg);
  }
  if (files) return positional.length > 0 ? positional : ["cwd"];
  if (positional.length === 0) return undefined;
  const targets = positional.slice(1);
  return targets.length > 0 ? targets : ["cwd"];
}

function validGitEvidence(context: ShellAnalysisContext): boolean {
  const git = context.git;
  return Boolean(
    git &&
    git.verified &&
    git.repoRoot &&
    isSha256Digest(git.fingerprint) &&
    git.pagerDisabled &&
    git.externalDiffDisabled &&
    git.textconvDisabled &&
    git.optionalLocksDisabled &&
    git.fsmonitorDisabled &&
    git.hooksDisabled &&
    git.configOverridesDisabled &&
    git.configIncludesDisabled &&
    git.aliasesDisabled &&
    git.repositoryReadScopeVerified &&
    isSha256Digest(git.repositoryReadScopeFingerprint),
  );
}

function gitTargets(argv: string[]): string[] | undefined {
  const sub = argv[1];
  if (!sub || !new Set(["status", "diff", "log"]).has(sub)) return undefined;
  const targets: string[] = [];
  let afterDashDash = false;
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--") {
      if (afterDashDash) return undefined;
      afterDashDash = true;
      continue;
    }
    if (afterDashDash) {
      targets.push(arg);
      continue;
    }
    if (sub === "status" && new Set(["--short", "--porcelain=v2", "--branch"]).has(arg)) continue;
    if (sub === "diff" && new Set(["--stat", "--name-only", "--check"]).has(arg)) continue;
    if (sub === "log" && new Set(["--oneline", "--graph", "--decorate"]).has(arg)) continue;
    if (sub === "log" && arg === "-n") {
      const value = argv[++i];
      if (!value || !/^[1-9][0-9]*$/u.test(value)) return undefined;
      continue;
    }
    if (sub === "log" && /^-n[1-9][0-9]*$/u.test(arg)) continue;
    return undefined;
  }
  return targets.length > 0 ? targets : ["cwd"];
}

function analyzeCommand(
  command: ParsedCommand,
  context: ShellAnalysisContext,
  commandIndex: number,
): { effects: Omit<ShellEffect, "effectId">[]; unknowns: ShellUnknownReason[] } {
  const [name] = command.argv;
  const unknowns: ShellUnknownReason[] = [];
  const effects: Omit<ShellEffect, "effectId">[] = [];
  if (!name || CONTROL_WORDS.has(name) || /^[A-Za-z_][A-Za-z0-9_]*=/u.test(name)) {
    unknowns.push("unsupported-syntax");
  } else if (!SUPPORTED.has(name)) {
    unknowns.push("unsupported-command");
  } else if (!validExecutable(name, context)) {
    const proof = context.executables[name];
    const state = context.shellState;
    if (
      proof?.verified &&
      proof.noRelevantShadowing &&
      isSha256Digest(proof.identityDigest) &&
      isSha256Digest(proof.resolutionFingerprint) &&
      (!state?.verified ||
        !state.trapsDisabled ||
        !state.optionsSafe ||
        !state.implicitCommandsAbsent ||
        !isSha256Digest(state.fingerprint))
    ) {
      unknowns.push("shell-state-not-verifiable");
    } else unknowns.push("unresolved-executable");
  }
  let targets: string[] | undefined;
  if (unknowns.length === 0) {
    targets =
      name === "pwd"
        ? pwdTargets(command.argv)
        : name === "ls"
          ? lsTargets(command.argv)
          : name === "head"
            ? headTargets(command.argv)
            : name === "wc"
              ? wcTargets(command.argv)
              : name === "rg"
                ? rgTargets(command.argv)
                : gitTargets(command.argv);
    if (!targets) unknowns.push("unsupported-option");
    const hasInput = command.redirections.some((redirection) => redirection.kind === "input");
    const readsPipeline = command.connector === "|";
    const readsImplicitStdin =
      targets &&
      !hasInput &&
      readsPipeline &&
      ((name === "head" && targets.length === 0) ||
        (name === "wc" && targets.length === 0) ||
        (name === "rg" && targets.length === 1 && targets[0] === "cwd"));
    if (
      targets &&
      (hasInput || readsImplicitStdin) &&
      ((name === "head" && targets.length === 0) ||
        (name === "wc" && targets.length === 0) ||
        (name === "rg" && targets.length === 1 && targets[0] === "cwd"))
    )
      targets = [];
    if (readsImplicitStdin) {
      const upstreamCommandId = `command-${commandIndex}`;
      effects.push({
        kind: "read",
        target: `pipe:${upstreamCommandId}`,
        parameters: [...command.argv],
        cwdCategory: context.cwd.category,
        risk: "low",
      });
    }
    if (targets && targets.length === 0 && !hasInput && !readsImplicitStdin)
      unknowns.push("unresolved-target");
    if (name === "git" && !validGitEvidence(context)) unknowns.push("git-state-not-verifiable");
  }
  if (unknowns.length === 0 && targets) {
    for (const target of targets) {
      const initialProof = context.targets[target];
      const recursiveRead =
        (name === "ls" && lsRequestsRecursiveRead(command.argv)) ||
        (name === "rg" && initialProof?.targetType !== "file");
      const proof = targetProof(target, context, recursiveRead);
      if (!proof) {
        unknowns.push(context.targets[target] ? "unsafe-target" : "unresolved-target");
        continue;
      }
      effects.push({
        kind: "read",
        target: proof.canonical,
        parameters: [...command.argv],
        cwdCategory: context.cwd.category,
        risk: "low",
      });
    }
  }
  if (unknowns.length > 0) {
    effects.push({
      kind: "unknown",
      target: name || "unknown",
      parameters: [...command.argv],
      cwdCategory: context.cwd.category,
      risk: "unknown",
    });
  }
  for (const redirection of command.redirections) {
    const proof = targetProof(redirection.target, context);
    if (!proof) {
      unknowns.push(context.targets[redirection.target] ? "unsafe-target" : "unresolved-target");
      effects.push({
        kind: "unknown",
        target: redirection.target,
        parameters: [redirection.kind],
        cwdCategory: context.cwd.category,
        risk: "unknown",
      });
    } else {
      effects.push({
        kind: redirection.kind === "input" ? "read" : "write",
        target: proof.canonical,
        parameters: [redirection.kind, redirection.target],
        cwdCategory: context.cwd.category,
        risk: redirection.kind === "input" ? "low" : "medium",
      });
    }
  }
  return { effects, unknowns: unique(unknowns) };
}

export function analyzeShell(
  commandBytes: Uint8Array,
  context: ShellAnalysisContext,
): ShellAnalysis {
  if (commandBytes[0] === 0xef && commandBytes[1] === 0xbb && commandBytes[2] === 0xbf)
    return unknownAnalysis("invalid-bytes");
  let input: string;
  try {
    input = new TextDecoder("utf-8", { fatal: true }).decode(commandBytes);
  } catch {
    return unknownAnalysis("invalid-bytes");
  }
  if (!context.cwd.verified || !context.cwd.path || !isSha256Digest(context.cwd.fingerprint))
    return unknownAnalysis("unresolved-target");
  const lexed = lex(input);
  if (!lexed.tokens) return unknownAnalysis(lexed.error ?? "unsupported-syntax");
  const parsed = parseCommands(lexed.tokens);
  if (!parsed.commands) return unknownAnalysis(parsed.error ?? "unsupported-syntax");
  const commands: ShellCommandAnalysis[] = parsed.commands.map((command, index) => ({
    commandId: `command-${index + 1}`,
    connector: command.connector,
    argv: [...command.argv],
  }));
  const effects: ShellEffect[] = [];
  const unknowns: ShellUnknownReason[] = [];
  for (const [index, command] of parsed.commands.entries()) {
    const analyzed = analyzeCommand(command, context, index);
    unknowns.push(...analyzed.unknowns);
    for (const effect of analyzed.effects)
      effects.push({ effectId: `effect-${effects.length + 1}`, ...effect });
  }
  if (effects.length === 0) return unknownAnalysis("unsupported-syntax", commands);
  return {
    status: unknowns.length === 0 ? "complete" : "unknown",
    commands,
    effects,
    unknowns: unique(unknowns),
  };
}
