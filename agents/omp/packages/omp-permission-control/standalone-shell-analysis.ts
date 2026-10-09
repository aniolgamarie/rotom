export interface ParsedSimpleCommand {
  connector: "start" | "&&" | "||" | ";" | "|";
  argv: string[];
  globs?: number[];
  homeExpansions?: number[];
  redirections?: { fd: number; operator: string; target: string }[];
}

export type GenericShellParse =
  | { status: "complete"; commands: ParsedSimpleCommand[] }
  | { status: "unsupported"; reason: "unsupported-syntax" };

const CONTROL = new Set([
  "!", "time", "command", "builtin", "env", "exec", "noglob",
  "if", "then", "elif", "else", "fi", "for", "select", "while", "until",
  "do", "done", "case", "in", "esac", "function", "coproc", "break", "continue", "return",
  "sudo", "doas", "nohup", "timeout", "busybox", "xargs", "source", ".", "eval",
  "trap", "alias", "unalias", "export", "declare", "typeset", "local", "unset", "set", "shift", "getopts", "let",
]);
const SHELLS = new Set(["sh", "bash", "zsh", "dash", "ksh", "fish"]);
const INTERPRETERS = new Set(["python", "python3", "node", "ruby", "perl", "pwsh", "powershell"]);
const REDIRECTS = new Set([">", ">>", "<", ">|", ">&", "<&"]);
const OPERATORS = [";;&", "&>>", "<<-", "<<<", "&&", "||", ">>", "<<", ">&", "<&", "<>", "&>", "|&", ";;", ";&", ">|", ";", "|", "&", ">", "<", "(", ")"];
interface Token { kind: "word" | "operator"; value: string; raw: string; start: number; end: number; glob?: boolean; homeExpansion?: boolean }
const unsupported = (): GenericShellParse => ({ status: "unsupported", reason: "unsupported-syntax" });

function sedHasExecution(args: string[]): boolean {
  if (args.some(a => a.startsWith("-f") || a === "--file" || a.startsWith("--file="))) return true;
  const explicit: string[] = [];
  for (let i = 0; i < args.length; i++) {
    if (["-e", "--expression"].includes(args[i])) explicit.push(args[++i] ?? "");
    else if (args[i].startsWith("--expression=")) explicit.push(args[i].slice(13));
    else if (args[i].startsWith("-e")) explicit.push(args[i].slice(2));
  }
  const scripts = explicit.length ? explicit : [args.find(a => !a.startsWith("-")) ?? ""];
  return scripts.some(a => /(^|[;{}\n])\s*(?:[0-9]+(?:,[0-9]+)?)?e(?:\s|$)|(^|[;{}\n])\s*(?:[0-9]+(?:,[0-9]+)?)?s(.).*\3.*\3[^\n]*e|\/e(?:\s|$)/u.test(a));
}

// 仅扫描词法结构；不扩展变量/路径、不求值，也不执行命令。
function tokenize(input: string, partial = false, privacy = false): Token[] | undefined {
  const tokens: Token[] = [];
  const failure = () => partial ? tokens : undefined;
  let i = 0;
  while (i < input.length) {
    const start = i;
    if (input[i] === "\n" || input[i] === "\r") {
      i += input.slice(i, i+2) === "\r\n" ? 2 : 1;
      tokens.push({ kind: "operator", value: "\n", raw: input.slice(start, i), start, end: i });
      continue;
    }
    if (input[i] === " " || input[i] === "\t") { i++; continue; }
    if (input[i] === "#") {
      while (i < input.length && input[i] !== "\n") i++;
      if (privacy) {
        const raw = input.slice(start, i);
        tokens.push({ kind: "word", value: raw.replace(/["']/gu, "").replace(/\\(.)/gu, "$1"), raw, start, end: i });
      }
      continue;
    }
    const operator = OPERATORS.find(op => input.startsWith(op, i));
    if (operator) {
      i += operator.length;
      tokens.push({ kind: "operator", value: operator, raw: operator, start, end: i });
      continue;
    }
    let value = "";
    let quote: "'" | '"' | undefined;
    let glob = false;
    let homeExpansion = false;
    let started = false;
    while (i < input.length) {
      const c = input[i];
      if (quote === "'") {
        if (c === "'") quote = undefined;
        else value += c;
        i++;
      } else if (c === "\\") {
        const next = input[i+1];
        if (next === undefined) {
          if (!privacy) return failure();
          value += "\\"; started = true; i++; break;
        }
        if (next === "\n") { i += 2; continue; }
        started = true;
        if (quote === '"' && !'$`"\\'.includes(next)) value += "\\";
        value += next;
        i += 2;
      } else if (quote === '"') {
        if (c === '"') quote = undefined;
        else if ((c === "$" || c === "`") && !privacy) return failure();
        else value += c;
        i++;
      } else if (c === "'" || c === '"') {
        quote = c;
        started = true;
        i++;
      } else if (" \t\r\n".includes(c) || OPERATORS.some(op => input.startsWith(op, i))) break;
      else if (c === "~" && !privacy) {
        if (homeExpansion && value.startsWith("~/")) { value += c; i++; continue; }
        const next = input[i+1];
        if (started || next !== undefined && next !== "/" && !" \t\r\n".includes(next) && !OPERATORS.some(op => input.startsWith(op, i+1))) return failure();
        homeExpansion = true;
        started = true;
        value += c;
        i++;
      } else if ("$`{}".includes(c) && !privacy) return failure();
      else {
        if (c === "#" && !started) break;
        started = true;
        if ("*?[".includes(c)) glob = true;
        value += c;
        i++;
      }
    }
    if (quote && !privacy) return failure();
    if (started) tokens.push({ kind: "word", value, raw: input.slice(start, i), start, end: i, glob, homeExpansion });
  }
  return tokens;
}

export function privacyWords(input: string): { value: string; raw: string; start: number; end: number }[] {
  // 仅拼接引号/转义以发现凭据；保留动态字符，不展开，也绝不用这个视图批准。
  return (tokenize(input, false, true) ?? []).filter(t => t.kind === "word");
}

export function parseGenericCommands(input: string): GenericShellParse {
  if (!input || /[\r\0-\x08\x0b\x0c\x0e-\x1f\x7f]/u.test(input)) return unsupported();
  const tokens = tokenize(input);
  if (!tokens) return unsupported();
  const commands: ParsedSimpleCommand[] = [];
  let connector: ParsedSimpleCommand["connector"] = "start";
  let argv: string[] = [];
  let globs: number[] = [];
  let homeExpansions: number[] = [];
  let redirections: NonNullable<ParsedSimpleCommand["redirections"]> = [];
  let needWord = false;
  const flush = () => {
    const head = argv[0]?.split("/").at(-1) ?? "";
    // command只开放不执行命令的-v/-V查询；路径同名程序及其他wrapper继续拒绝。
    const query = argv[0] === "command" && ["-v", "-V"].includes(argv[1]);
    const queryStart = argv[2] === "--" ? 3 : 2;
    const validQuery = query && argv.length > queryStart && !globs.length && !homeExpansions.length &&
      argv.slice(queryStart).every(name => Boolean(name) && (queryStart === 3 || !name.startsWith("-")));
    if (!argv.length || (CONTROL.has(head) && !validQuery) || /^[A-Za-z_][A-Za-z0-9_]*=/u.test(argv[0]) || globs.includes(0) || homeExpansions.includes(0)) return false;
    // 内嵌程序会隐藏后续命令，不能让它绕过配置的 deny/prompt。
    if ((SHELLS.has(head) && argv.slice(1).some(a => /^-[A-Za-z]*c/u.test(a) || a === "--command" || a.startsWith("--command="))) ||
      (INTERPRETERS.has(head) && argv.slice(1).some(a => a.startsWith("-c") || a.startsWith("-e") || ["--eval", "--command"].includes(a) || /^--(?:eval|command)=/u.test(a)))) return false;
    if (head === "find" && argv.some(a => ["-exec", "-execdir", "-ok", "-okdir"].includes(a))) return false;
    if (["awk", "gawk", "mawk", "nawk"].includes(head) && argv.slice(1).some(a => /system\s*\(|\||@/u.test(a) || /^-(?:f|l|E)/u.test(a) || ["--file", "--load", "--exec"].includes(a) || /^--(?:file|load|exec)=/u.test(a))) return false;
    if (head === "sed" && sedHasExecution(argv.slice(1))) return false;
    commands.push({ connector, argv, ...(globs.length ? { globs } : {}), ...(homeExpansions.length ? { homeExpansions } : {}), ...(redirections.length ? { redirections } : {}) });
    argv = []; globs = []; homeExpansions = []; redirections = [];
    return true;
  };
  for (let i = 0; i < tokens.length; i++) {
    let token = tokens[i];
    let fd: number | undefined;
    const next = tokens[i+1];
    if (token.kind === "word" && /^\d+$/u.test(token.raw) && next?.kind === "operator" && token.end === next.start && REDIRECTS.has(next.value)) {
      fd = Number(token.raw);
      token = tokens[++i];
    }
    if (token.kind === "operator" && REDIRECTS.has(token.value)) {
      const target = tokens[++i];
      const source = fd ?? (token.value.startsWith("<") ? 0 : 1);
      if (!target || target.kind !== "word" || !target.value || target.glob || target.homeExpansion || source > 9 ||
          ([">&", "<&"].includes(token.value) && (!/^\d+$|^-$/u.test(target.value) || (target.value !== "-" && Number(target.value) > 9)))) return unsupported();
      redirections.push({ fd: source, operator: token.value, target: target.value });
      continue;
    }
    if (token.kind === "operator") {
      if (![";", "\n", "&&", "||", "|"].includes(token.value)) return unsupported();
      if (!argv.length) {
        if (token.value === "\n" && !redirections.length) continue;
        return unsupported();
      }
      if (!flush()) return unsupported();
      connector = token.value === "\n" ? ";" : token.value as ParsedSimpleCommand["connector"];
      needWord = ["&&", "||", "|"].includes(token.value);
    } else {
      if (token.glob) globs.push(argv.length);
      if (token.homeExpansion) homeExpansions.push(argv.length);
      argv.push(token.homeExpansion ? token.raw : token.value);
      needWord = false;
    }
  }
  if (argv.length) { if (!flush()) return unsupported(); }
  else if (redirections.length || needWord) return unsupported();
  return commands.length ? { status: "complete", commands } : unsupported();
}

function globRegex(pattern: string): RegExp {
  let source = "^";
  for (const ch of pattern) {
    if (ch === "*") source += ".*";
    else if (ch === "?") source += ".";
    else source += ch.replace(/[\\^$.*+?()[\]{}|]/u, "\\$&");
  }
  return new RegExp(source + "$", "u");
}

export function matchesNativePattern(command: ParsedSimpleCommand, pattern: string): boolean {
  const regex = globRegex(pattern);
  const argv = command.argv.join(" ");
  const redirects = command.redirections?.map(r => String(r.fd) + r.operator + r.target).join(" ");
  const implicit = command.redirections?.map(r => (r.fd === (r.operator.startsWith("<") ? 0 : 1) ? "" : String(r.fd)) + r.operator + " " + r.target).join(" ");
  const compact = command.redirections?.map(r => (r.fd === (r.operator.startsWith("<") ? 0 : 1) ? "" : String(r.fd)) + r.operator + r.target).join(" ");
  const effects = command.redirections?.flatMap(r => [String(r.fd) + r.operator + r.target,
    (r.fd === (r.operator.startsWith("<") ? 0 : 1) ? "" : String(r.fd)) + r.operator + " " + r.target,
    (r.fd === (r.operator.startsWith("<") ? 0 : 1) ? "" : String(r.fd)) + r.operator + r.target]) ?? [];
  return regex.test(command.argv[0]) || regex.test(argv) || [redirects, implicit, compact, ...effects].some(r => Boolean(r && regex.test(argv + " " + r)));
}

export function matchesNativeRaw(input: string, pattern: string): boolean { return new RegExp(globRegex(pattern).source, "su").test(input); }

export function visiblePrefixForDenial(input: string): ParsedSimpleCommand[] {
  // 仅用于加强 deny，绝不凭部分分析批准：后续动态/错误不能遮住已知的前缀。
  const tokens = (tokenize(input.slice(0, 24 * 1024), true) ?? []).slice(0, 256);
  let visible: ParsedSimpleCommand[] = [];
  for (const token of tokens) {
    if (token.kind !== "word" && ![";", "\n", "&&", "||", "|"].includes(token.value)) continue;
    const end = token.kind === "word" ? token.end : token.start;
    const result = parseGenericCommands(input.slice(0, end));
    if (result.status === "complete") visible = result.commands;
  }
  return visible;
}

export function hasUncertainPatternMatch(command: ParsedSimpleCommand, pattern: string): boolean {
  // 通配符与HOME参数均未扩展，精确 native 限制可能作用于解析后的参数。
  // 宽泛 deny 已在 matchesNativePattern 中先处理；潜在交集保守转人工。
  return Boolean((command.globs?.length || command.homeExpansions?.length) && pattern.includes(" ") && globRegex(pattern.split(/\s+/u)[0]).test(command.argv[0]));
}
