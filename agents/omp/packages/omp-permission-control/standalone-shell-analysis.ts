export interface ParsedSimpleCommand {
  connector: "start" | "&&" | "||" | ";" | "|";
  argv: string[];
}

export type GenericShellParse =
  | { status: "complete"; commands: ParsedSimpleCommand[] }
  | { status: "unsupported"; reason: "unsupported-syntax" };

const SHELL_CONTROL_WORDS = new Set([
  "!", "time", "command", "builtin", "env", "exec", "noglob",
  "if", "then", "elif", "else", "fi", "for", "select", "while", "until",
  "do", "done", "case", "in", "esac", "function", "coproc", "break", "continue", "return",
]);

/**
 * Parse the deliberately small shell grammar needed to apply configured native
 * patterns. Unsupported expansion or redirection is sent to the human reviewer.
 */
export function parseGenericCommands(input: string): GenericShellParse {
  if (!input || /[\r\n\0-\x08\x0b\x0c\x0e-\x1f\x7f]/u.test(input))
    return { status: "unsupported", reason: "unsupported-syntax" };

  const commands: ParsedSimpleCommand[] = [];
  let connector: ParsedSimpleCommand["connector"] = "start";
  let argv: string[] = [];
  let word = "";
  let started = false;
  let quote: "single" | "double" | undefined;

  const pushWord = () => {
    if (started) argv.push(word);
    word = "";
    started = false;
  };
  const pushCommand = () => {
    pushWord();
    if (argv.length === 0) return false;
    if (/^[A-Za-z_][A-Za-z0-9_]*=/u.test(argv[0]) || SHELL_CONTROL_WORDS.has(argv[0])) return false;
    commands.push({ connector, argv });
    argv = [];
    return true;
  };

  for (let i = 0; i < input.length; i++) {
    const ch = input[i];
    if (quote === "single") {
      if (ch === "'") quote = undefined;
      else word += ch;
      started = true;
      continue;
    }
    if (quote === "double") {
      if (ch === '"') quote = undefined;
      else if (ch === "\\") {
        const next = input[++i];
        if (next === undefined) return { status: "unsupported", reason: "unsupported-syntax" };
        word += '$`"\\'.includes(next) ? next : `\\${next}`;
      } else if (ch === "$" || ch === "`") {
        return { status: "unsupported", reason: "unsupported-syntax" };
      } else word += ch;
      started = true;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch === "'" ? "single" : "double";
      started = true;
    } else if (ch === "\\") {
      const next = input[++i];
      if (next === undefined) return { status: "unsupported", reason: "unsupported-syntax" };
      word += next;
      started = true;
    } else if (ch === " " || ch === "\t") pushWord();
    else if (ch === ";" || ch === "|" || ch === "&") {
      let nextConnector: ParsedSimpleCommand["connector"];
      if (ch === "&") {
        if (input[i + 1] !== "&") return { status: "unsupported", reason: "unsupported-syntax" };
        i++;
        nextConnector = "&&";
      } else if (ch === "|" && input[i + 1] === "|") {
        i++;
        nextConnector = "||";
      } else nextConnector = ch;
      if (!pushCommand()) return { status: "unsupported", reason: "unsupported-syntax" };
      connector = nextConnector;
    } else if ("$`(){}<>*?[".includes(ch)) {
      return { status: "unsupported", reason: "unsupported-syntax" };
    } else {
      word += ch;
      started = true;
    }
  }
  if (quote || !pushCommand()) return { status: "unsupported", reason: "unsupported-syntax" };
  return { status: "complete", commands };
}

function globRegex(pattern: string): RegExp {
  let source = "^";
  for (const ch of pattern) {
    if (ch === "*") source += ".*";
    else if (ch === "?") source += ".";
    else source += ch.replace(/[\\^$.*+?()[\]{}|]/u, "\\$&");
  }
  return new RegExp(`${source}$`, "u");
}

export function matchesNativePattern(command: ParsedSimpleCommand, pattern: string): boolean {
  const regex = globRegex(pattern);
  return regex.test(command.argv[0]) || regex.test(command.argv.join(" "));
}
