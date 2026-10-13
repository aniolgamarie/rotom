import { hasUncertainPatternMatch, matchesNativePattern, matchesNativeRaw, parseGenericCommands,
  privacyWords, visiblePrefixForDenial, type ParsedSimpleCommand } from "./standalone-shell-analysis";

type Rule = { match: string; approval: "allow" | "prompt" | "deny" };
// allow 不授予 smart 免审；送审仅携带完整限制模式，原始索引仍用于本地门控和审计。
export function reviewConfiguredRules(rules: Rule[]): { deny?: string[]; prompt?: string[] } | undefined {
  const deny = rules.filter(rule => rule.approval === "deny").map(rule => rule.match);
  const prompt = rules.filter(rule => rule.approval === "prompt").map(rule => rule.match);
  return deny.length || prompt.length ? { ...(deny.length ? { deny } : {}), ...(prompt.length ? { prompt } : {}) } : undefined;
}

function wrapperTarget(argv: string[]): number | undefined {
  const head = argv[0]?.split("/").at(-1);
  if (!["env", "sudo", "doas", "nohup", "command", "builtin", "timeout", "xargs"].includes(head ?? "")) return undefined;
  if (head === "command" && argv.slice(1).some(arg => arg === "-v" || arg === "-V" || /^-[p]*[vV]/u.test(arg))) return undefined;
  const values = head === "sudo" || head === "doas" ? ["-u", "-g", "--user", "--group"] : head === "env"
    ? ["-u", "-C", "--unset", "--chdir"] : head === "timeout" ? ["-s", "-k", "--signal", "--kill-after"]
      : head === "xargs" ? ["-n", "-I", "-P", "-L", "--max-args", "--replace", "--max-procs", "--max-lines"] : [];
  const switches = head === "env" ? ["-i", "--ignore-environment"] : head === "sudo" || head === "doas"
    ? ["-n", "-E", "-H", "-S", "-k", "--non-interactive", "--preserve-env", "--set-home", "--stdin"] : head === "command"
      ? ["-p"] : head === "timeout" ? ["--foreground", "--preserve-status", "-v", "--verbose"] : head === "xargs"
        ? ["-0", "-r", "-t", "-x", "--null", "--no-run-if-empty", "--verbose", "--exit"] : [];
  let at = 1;
  while (at < argv.length) {
    const arg = argv[at];
    if (arg === "--") { at++; break; }
    if (values.includes(arg)) { if (argv[at + 1] === undefined) return undefined; at += 2; continue; }
    if (switches.includes(arg) || values.some(flag => flag.startsWith("--") && arg.startsWith(flag + "="))) { at++; continue; }
    if (arg.startsWith("-")) return undefined;
    if (head === "env" && /^[A-Za-z_][A-Za-z0-9_]*=/u.test(arg)) { at++; continue; }
    break;
  }
  if (head === "timeout") at++; // 字面时限，不是被执行程序。
  return at < argv.length ? at : undefined;
}
export interface RuleCheck {
  decision: "allow" | "prompt" | "deny";
  matchedRuleIds: number[];
  uncertainRuleIds: number[];
  analysis: "complete" | "unsupported" | "error";
}

// 只提取明显的字面执行位置来加强限制；不模拟 Shell、不执行替换，也不据此批准。
function literalCandidates(input: string, depth = 0): ParsedSimpleCommand[] {
  if (depth > 4) return [];
  const text = input.slice(0, 24 * 1024);
  const words = privacyWords(text).slice(0, 256);
  const candidates = [...visiblePrefixForDenial(text)];
  const boundary = (left: number, right: number) => /[;&|\n]/u.test(text.slice(left, right).replace(/\\\r?\n/gu, ""));
  const starts = new Set<number>();
  if (words.length) starts.add(0);
  for (let i = 0; i < words.length; i++) {
    if (i && boundary(words[i - 1].end, words[i].start)) starts.add(i);
  }
  const add = (argv: string[], raw: string[]) => {
    if (!argv.length || /[$`]/u.test(raw[0])) return;
    const uncertain = raw.flatMap((word, index) =>
      !(word.startsWith("'") && word.endsWith("'") && word.slice(1, -1).indexOf("'") === -1) && /[$`~*?[]/u.test(word) ? [index] : []);
    candidates.push({ connector: "start", argv, ...(uncertain.length ? { globs: uncertain } : {}) });
  };
  for (const start of starts) {
    if (start >= words.length) continue;
    if (words[start].raw === words[start].value && ["if", "then", "elif", "else", "do", "!"].includes(words[start].value)) {
      starts.add(start + 1);
      continue;
    }
    let end = start + 1;
    while (end < words.length && !boundary(words[end - 1].end, words[end].start)) end++;
    const segment = words.slice(start, end);
    const argv = segment.map(word => word.value), raw = segment.map(word => word.raw);
    add(argv, raw);
    const head = argv[0].split("/").at(-1);
    let wrapped = argv, wrappedRaw = raw;
    for (let count = 0; count < 8; count++) {
      const at = wrapperTarget(wrapped);
      if (at === undefined) break;
      const xargs = wrapped[0].split("/").at(-1) === "xargs";
      wrapped = wrapped.slice(at); wrappedRaw = wrappedRaw.slice(at);
      if (xargs) { wrapped = [...wrapped, "$XARGS_INPUT"]; wrappedRaw = [...wrappedRaw, "$XARGS_INPUT"]; }
      add(wrapped, wrappedRaw);
    }
    if (["sh", "bash", "zsh", "dash", "ash", "ksh", "mksh"].includes(head ?? "")) {
      const at = argv.findIndex((arg, index) => index > 0 && (/^-[A-Za-z]*c$/u.test(arg) || arg === "--command"));
      if (at > 0 && argv[at + 1] !== undefined) candidates.push(...literalCandidates(argv[at + 1], depth + 1));
    }
    if (head === "find") {
      for (let i = 1; i < argv.length; i++) if (["-exec", "-execdir", "-ok", "-okdir"].includes(argv[i])) {
        let stop = i + 1;
        while (stop < argv.length && ![";", "+"].includes(argv[stop])) stop++;
        add(argv.slice(i + 1, stop), raw.slice(i + 1, stop));
      }
    }
    if (["awk", "gawk", "mawk", "python", "python3"].includes(head ?? "")) {
      for (const script of argv.slice(1)) for (const match of script.matchAll(/\bsystem\s*\(\s*("(?:\\.|[^"\\])*")\s*\)/gu)) {
        try { candidates.push(...literalCandidates(JSON.parse(match[1]), depth + 1)); } catch { /* 非字面程序交给模型。 */ }
      }
    }
    if (head === "sed") for (const script of argv.slice(1)) {
      const match = /(?:^|[;\n])\s*e\s+([^;\n]+)/u.exec(script);
      if (match) candidates.push(...literalCandidates(match[1], depth + 1));
    }
  }
  return candidates;
}

export function checkConfiguredRules(command: string, rules: Rule[]): RuleCheck {
  let analysis: RuleCheck["analysis"] = "unsupported";
  let candidates: ParsedSimpleCommand[] = [];
  try {
    const parsed = parseGenericCommands(command);
    analysis = parsed.status;
    candidates = parsed.status === "complete" ? parsed.commands : rules.some(rule => rule.approval !== "allow") ? literalCandidates(command) : [];
  } catch { analysis = "error"; }
  const matchedRuleIds: number[] = [], uncertainRuleIds: number[] = [];
  for (let index = 0; index < rules.length; index++) {
    const rule = rules[index];
    if (rule.approval === "allow") continue;
    if (matchesNativeRaw(command, rule.match) || candidates.some(candidate => matchesNativePattern(candidate, rule.match))) matchedRuleIds.push(index);
    else if (candidates.some(candidate => hasUncertainPatternMatch(candidate, rule.match))) uncertainRuleIds.push(index);
  }
  // 审计有界展示时，导致拒绝的规则必须先于仅提示的规则，不能被前 64 项挤掉。
  const denyFirst = (left: number, right: number) => Number(rules[right].approval === "deny") - Number(rules[left].approval === "deny") || left - right;
  matchedRuleIds.sort(denyFirst); uncertainRuleIds.sort(denyFirst);
  return { decision: matchedRuleIds.some(index => rules[index].approval === "deny") ? "deny" :
    matchedRuleIds.length ? "prompt" : "allow", matchedRuleIds, uncertainRuleIds, analysis };
}
