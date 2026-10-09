import { parseGenericCommands, visiblePrefixForDenial } from "./standalone-shell-analysis";

export type ContextValue = string | number | boolean | null | ContextValue[] | { [key: string]: ContextValue };
export interface WorktreeHelpers {
  rewriteGitWorktreeAdd(command: string, argv: readonly string[]): string;
  resolveCliEntryCmd?(): string[];
  resolveCliEntry?(): { argv: string[]; identity: { [key: string]: ContextValue } };
  extractLeadingCdTarget(command: string): { path: string; rest: string } | null;
  resolveToCwd(path: string, cwd: string): string;
}
export interface WorktreeAnalysis {
  supported: boolean;
  effectiveCwd: string;
  normalizedCommand: string;
  executionCommand: string;
  cliArgv: string[];
  cliEntryIdentity?: { [key: string]: ContextValue };
  backend: string;
  plan?: { [key: string]: ContextValue };
  rewriteApplied?: boolean;
  unverified?: { [key: string]: ContextValue };
}

// 只核对静态 argv 与公开 helper 的实际输出，不执行命令或重建上游 shell 词法。
export function analyzeWorktree(command: string, cwd: string | undefined, baseCwd: string,
  clone: boolean, backend: string, helpers?: WorktreeHelpers): WorktreeAnalysis {
  const result: WorktreeAnalysis = { supported: true, effectiveCwd: baseCwd,
    normalizedCommand: command, executionCommand: command, cliArgv: [], backend };
  const raw = parseGenericCommands(command);
  const possibleWorktree = (argv: string[]) => {
    const at = argv[1] === "-C" ? 3 : 1;
    return argv[0] === "git" && argv[at] === "worktree" && argv[at + 1] === "add";
  };
  // 不完整解析仅用于保守识别候选，不扩大完整静态审查合同。
  const candidates = raw.status === "complete" ? raw.commands : visiblePrefixForDenial(command);
  const possible = candidates.some(({ argv }) => possibleWorktree(argv));
  const unverified = (evidence: string) => ({ mayRewrite: true, verified: false,
    analysisScope: "unverified-native-rewrite-possible-effects", rewriteEvidence: evidence, backend });
  if (!helpers) {
    result.supported = !clone || !possible;
    if (clone && possible) result.unverified = unverified("helper-unavailable");
    return result;
  }
  let rewriteEvidence = "helper-unavailable";
  let leadingNavigation = false;
  try {
    let effective = cwd;
    if (!effective) {
      const leading = helpers.extractLeadingCdTarget(command);
      if (leading) { effective = leading.path; result.normalizedCommand = leading.rest; leadingNavigation = true; }
    }
    result.effectiveCwd = effective ? helpers.resolveToCwd(effective, baseCwd) : baseCwd;
    result.executionCommand = result.normalizedCommand;
    if (!clone || (!possible && raw.status === "complete")) return result;
    try {
      const entry = helpers.resolveCliEntry?.();
      result.cliArgv = entry ? [...entry.argv] : [...helpers.resolveCliEntryCmd!()];
      if (entry) result.cliEntryIdentity = entry.identity;
      if (!result.cliArgv.length || result.cliArgv.some(value => !value || /[\x00-\x1f\x7f]/u.test(value)))
        throw new Error("invalid cli argv");
    } catch {
      // 纯探测只比较是否可能变换；空 argv 输出不是实际 dispatch，不能形成 plan。
      let mayRewrite = possible;
      try { mayRewrite = helpers.rewriteGitWorktreeAdd(result.normalizedCommand, []) !== result.normalizedCommand; }
      catch { /* 无候选的普通动态语法仍交原通用门控；已知候选保持未知。 */ }
      if (mayRewrite) {
        result.supported = false;
        result.unverified = unverified("entry-unavailable-probe-may-rewrite");
      } else result.rewriteApplied = false;
      return result;
    }
    result.executionCommand = helpers.rewriteGitWorktreeAdd(result.normalizedCommand, result.cliArgv);
    rewriteEvidence = result.executionCommand === result.normalizedCommand ? "unchanged" : "changed";
    result.rewriteApplied = rewriteEvidence === "changed";
    // 官方 helper 已证明不重写：让原始通用语法/模型/native规则判定，不加 clone 门控。
    if (!result.rewriteApplied) return result;
    const normalized = parseGenericCommands(result.normalizedCommand);
    const execution = parseGenericCommands(result.executionCommand);
    if (raw.status !== "complete" || normalized.status !== "complete" || execution.status !== "complete")
      throw new Error("non-static command");
    if (leadingNavigation && raw.commands[0] &&
        (raw.commands[0].globs?.length || raw.commands[0].homeExpansions?.length || raw.commands[0].argv[1]?.startsWith("~")))
      throw new Error("non-static leading navigation");
    if (normalized.commands.length !== execution.commands.length) throw new Error("segment mismatch");
    const operations: ContextValue[] = [];
    const segmentCwd = result.effectiveCwd;
    let precedingNavigation = false;
    for (let i = 0; i < execution.commands.length; i++) {
      const before = normalized.commands[i]; const after = execution.commands[i];
      if (JSON.stringify(before) !== JSON.stringify(after)) {
        if (before.connector !== after.connector || before.redirections?.length || after.redirections?.length || precedingNavigation)
          throw new Error("uncertain rewritten segment context");
        if (after.argv.slice(0, result.cliArgv.length).some((value, at) => value !== result.cliArgv[at]) ||
            after.argv[result.cliArgv.length] !== "worktree" || after.argv[result.cliArgv.length + 1] !== "add")
          throw new Error("unexpected rewrite");
        let at = result.cliArgv.length + 2;
        let repository = segmentCwd; let repositoryArgument: string | null = null;
        let branch: string | null = null; let forceBranch = false; let detach = false; let quiet = false;
        while (at < after.argv.length && after.argv[at] !== "--") {
          const flag = after.argv[at++];
          if (flag === "-C") { repositoryArgument = after.argv[at++]; repository = helpers.resolveToCwd(repositoryArgument, segmentCwd); }
          else if (flag === "-b" || flag === "-B") { forceBranch = flag === "-B"; branch = after.argv[at++]; }
          else if (flag === "--detach") detach = true;
          else if (flag === "-q") quiet = true;
          else throw new Error("unknown rewritten flag");
        }
        if (after.argv[at++] !== "--" || after.argv.length - at < 1 || after.argv.length - at > 2)
          throw new Error("unknown rewritten positionals");
        operations.push({ segment: i, connector: after.connector, argv: after.argv,
          segmentCwd, repositoryArgument, repositoryCwd: repository,
          target: after.argv[at], targetRelativeTo: repository,
          branch, forceBranch, detach, quiet, startPoint: after.argv[at + 1] ?? null,
          pathsAreLexical: true });
      } else if (possibleWorktree(before.argv)) {
        throw new Error("unanalysed worktree segment");
      }
      // 后续 clone 前的内部导航可能条件性执行；只有公开 leading-cd 归一化能证明入口 cwd。
      if (["cd", "pushd", "popd"].includes(before.argv[0])) precedingNavigation = true;
    }
    if (!operations.length) throw new Error("unexplained rewrite");
    result.plan = { rawCommand: command, normalizedCommand: result.normalizedCommand,
      executionCommand: result.executionCommand, cliArgv: result.cliArgv,
      effectiveCwd: result.effectiveCwd, backend, operations, cliEntryIdentity: result.cliEntryIdentity ?? null,
      backendScope: "native-session-intent", executionSettingsScope: "new-cli-repository-cwd-unverified",
      analysisScope: "native-dispatch-and-declared-possible-effects",
      entryCheckScope: "file-identity-observation-not-authentication-or-sandbox",
      entryRace: "file identity is rechecked before delegation; stat-to-spawn race remains",
      effects: ["Creates a worktree and may create a branch; -B may reset the named branch.",
        "Clone materialization may carry source-checkout local and ignored data, including build artifacts; the copied set is not enumerated and is not guaranteed secret-free.",
        "The configured backend is intent, not a success guarantee; auto may select another backend or fall back to ordinary Git checkout.",
        "Repository and target paths are lexical execution data, not filesystem existence or authorization proofs.",
        "A new CLI resolves settings at the repository cwd again; actual clone/backend configuration may differ from native-session intent and is not verified or protected by this parent-settings fingerprint.",
        "Post-checkout hooks may execute local code; hook contents are not inspected or protected by this parent-settings fingerprint. Dispatch analysis is not complete side-effect verification or authorization."] };
  } catch {
    result.supported = false; delete result.plan;
    if (clone && (rewriteEvidence === "changed" ||
        (rewriteEvidence === "helper-unavailable" && possible)))
      result.unverified = unverified(rewriteEvidence);
  }
  return result;
}
