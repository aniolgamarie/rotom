"""独立测试词法 oracle；使用 shlex 解码单词，不调用生产解析器或 Shell。"""

import re
import shlex

OPERATORS = (";;&", "&>>", "<<-", "<<<", "&&", "||", ">>", "<<", ">&", "<&", "<>", "&>", "|&", ";;", ";&", ">|", ";", "|", "&", ">", "<", "(", ")")
CONTROL = set("! time command builtin env exec noglob if then elif else fi for select while until do done case in esac function coproc break continue return sudo doas nohup timeout busybox xargs source . eval".split())
CONTROL.update("trap alias unalias export declare typeset local unset set shift getopts let".split())
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "pwsh", "powershell"}
REDIRECTS = {">", ">>", "<", ">|", ">&", "<&"}


def expected_gate(text):
  original = text
  views = []
  for kind, raw, _, _ in tokens(text):
    if kind == "word":
      try:
        lexer = shlex.shlex(raw.replace("\\\n", ""), posix=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        views.append(" ".join(lexer))
      except ValueError:
        views.append(raw)
    elif kind == "comment":
      views.append(re.sub(r"\\(.)", r"\1", raw.replace("'", "").replace('"', "")))
  text += "\n" + " ".join(views)
  field = r"(?:(?:token|password|passwd|secret|api[_-]?key|credential|authorization|cookie)[A-Za-z0-9_-]*)"
  sensitive = (re.search(field + r"[\"']?\s*[:=]\s*\S+|--[A-Za-z0-9_-]*" + field + r"\s+\S+", text, re.I)
    or re.search(r"\b(?:Bearer|Basic)\s+\S+|[A-Za-z][A-Za-z0-9+.-]*://[^\s/\"'<>]+@", text, re.I)
    or (re.search(r"\bcurl\b", text) and re.search(r"(?<![\w-])(?:--(?:user|proxy-user|oauth2-bearer)(?:=|\s+)|-[uU]\s*)\S+", text))
    or re.search(r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[opusr]_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16})\b", text))
  return "model" if expected_parse(original)["status"] == "complete" and not sensitive else "human"


def sed_has_execution(args):
  if any(a.startswith("-f") or a == "--file" or a.startswith("--file=") for a in args):
    return True
  explicit = []
  i = 0
  while i < len(args):
    a = args[i]
    if a in {"-e", "--expression"}:
      i += 1
      explicit.append(args[i] if i < len(args) else "")
    elif a.startswith("--expression="):
      explicit.append(a.split("=", 1)[1])
    elif a.startswith("-e"):
      explicit.append(a[2:])
    i += 1
  programs = explicit or [next((a for a in args if not a.startswith("-")), "")]
  return any(re.search(r"(^|[;{}\n])\s*(?:[0-9]+(?:,[0-9]+)?)?e(?:\s|$)|(^|[;{}\n])\s*(?:[0-9]+(?:,[0-9]+)?)?s(.).*\3.*\3[^\n]*e|/e(?:\s|$)", a) for a in programs)


def tokens(text):
  result = []
  i = 0
  while i < len(text):
    if text[i] in "\r\n":
      end = i+2 if text[i:i+2] == "\r\n" else i+1
      result.append(("operator", "\n", i, end))
      i = end
    elif text[i] in " \t":
      i += 1
    elif text[i] == "#":
      end = text.find("\n", i)
      end = len(text) if end < 0 else end
      result.append(("comment", text[i:end], i, end))
      i = end
    elif (op := next((o for o in OPERATORS if text.startswith(o, i)), None)):
      result.append(("operator", op, i, i+len(op)))
      i += len(op)
    else:
      start = i
      quote = None
      meaningful = False
      while i < len(text):
        c = text[i]
        if c == "\\" and quote != "'":
          if text[i+1:i+2] != "\n":
            meaningful = True
          i += 2
          continue
        if quote:
          if c == quote:
            quote = None
        elif c in "'\"":
          quote = c
          meaningful = True
        elif c in " \t\r\n" or any(text.startswith(o, i) for o in OPERATORS) or (c == "#" and not meaningful):
          break
        else:
          meaningful = True
        i += 1
      result.append(("word", text[start:i], start, min(i, len(text))))
  return result


def word(raw):
  quote = None
  glob = False
  i = 0
  while i < len(raw):
    c = raw[i]
    if c == "\\" and quote != "'":
      if i+1 >= len(raw):
        raise ValueError("truncated escape")
      i += 2
      continue
    if c == quote:
      quote = None
    elif not quote and c in "'\"":
      quote = c
    elif quote != "'" and c in "$`":
      raise ValueError("dynamic")
    elif not quote and c in "{}()~":
      raise ValueError("expansion or control")
    elif not quote and c in "*?[":
      glob = True
    i += 1
  if quote:
    raise ValueError("unclosed quote")
  # shlex 不会把续行自动抹掉；先按 Shell 规则删除非单引号续行。
  cleaned = []
  quote = None
  i = 0
  while i < len(raw):
    c = raw[i]
    if c == "\\" and quote != "'":
      if raw[i+1:i+2] == "\n":
        i += 2
        continue
      # shlex 只特别处理双引号中的 quote/backslash；Shell 还去掉 \$/\` 的反斜线。
      cleaned.append(raw[i+1] if quote == '"' and raw[i+1] in "$`" else raw[i:i+2])
      i += 2
      continue
    if c == quote:
      quote = None
    elif not quote and c in "'\"":
      quote = c
    cleaned.append(c)
    i += 1
  values = shlex.split("".join(cleaned), comments=False, posix=True)
  if len(values) != 1:
    raise ValueError("invalid word")
  return values[0], glob


def expected_parse(text):
  unsupported = {"status": "unsupported", "reason": "unsupported-syntax"}
  if not text or re.search(r"[\r\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", text):
    return unsupported
  try:
    ts = [t for t in tokens(text) if t[0] != "comment" and not (t[0] == "word" and not t[1].replace("\\\n", ""))]
    commands = []
    argv = []
    globs = []
    redirects = []
    connector = "start"
    need_word = False

    def flush():
      head = argv[0].rsplit("/", 1)[-1] if argv else ""
      if not argv or head in CONTROL or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]) or 0 in globs:
        raise ValueError("unsupported command boundary")
      if (head in SHELLS and any(re.match(r"-[A-Za-z]*c", a) or a == "--command" or a.startswith("--command=") for a in argv[1:])) or (head in INTERPRETERS and any(a.startswith(("-c", "-e")) or a in {"--eval", "--command"} or re.match(r"--(?:eval|command)=", a) for a in argv[1:])):
        raise ValueError("embedded program")
      if head == "find" and any(a in {"-exec", "-execdir", "-ok", "-okdir"} for a in argv):
        raise ValueError("find command execution")
      if head in {"awk", "gawk", "mawk", "nawk"} and any(re.search(r"system\s*\(|\||@", a) or re.match(r"-(?:f|l|E)", a) or a in {"--file", "--load", "--exec"} or re.match(r"--(?:file|load|exec)=", a) for a in argv[1:]):
        raise ValueError("awk command execution")
      if head == "sed" and sed_has_execution(argv[1:]):
        raise ValueError("sed command execution")
      item = {"connector": connector, "argv": list(argv)}
      if globs:
        item["globs"] = list(globs)
      if redirects:
        item["redirections"] = list(redirects)
      commands.append(item)
      argv.clear()
      globs.clear()
      redirects.clear()

    i = 0
    while i < len(ts):
      kind, raw, start, end = ts[i]
      fd = None
      if kind == "word" and re.fullmatch(r"\d+", raw) and i+1 < len(ts) and end == ts[i+1][2] and ts[i+1][1] in REDIRECTS:
        fd = int(raw)
        i += 1
        kind, raw, start, end = ts[i]
      if kind == "operator" and raw in REDIRECTS:
        if i+1 >= len(ts) or ts[i+1][0] != "word":
          raise ValueError("missing redirect target")
        target, glob = word(ts[i+1][1])
        if not target or glob or (raw in {">&", "<&"} and not re.fullmatch(r"\d+|-", target)):
          raise ValueError("dynamic redirect")
        source = fd if fd is not None else (0 if raw.startswith("<") else 1)
        if source > 9 or (raw in {">&", "<&"} and target != "-" and int(target) > 9):
          raise ValueError("unsupported descriptor")
        redirects.append({"fd": source, "operator": raw, "target": target})
        i += 2
        continue
      if kind == "operator":
        if raw not in {";", "\n", "&&", "||", "|"}:
          raise ValueError("unsupported operator")
        if not argv:
          if raw == "\n" and not redirects:
            i += 1
            continue
          raise ValueError("empty command")
        flush()
        connector = ";" if raw == "\n" else raw
        need_word = raw in {"&&", "||", "|"}
      else:
        value, glob = word(raw)
        if glob:
          globs.append(len(argv))
        argv.append(value)
        need_word = False
      i += 1
    if argv:
      flush()
    elif redirects or need_word:
      raise ValueError("incomplete command")
    return {"status": "complete", "commands": commands} if commands else unsupported
  except (ValueError, IndexError):
    return unsupported
