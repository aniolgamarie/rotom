#!/usr/bin/env python3
"""将私有二次脱敏语料按词法场景归并；不解释或执行命令。"""

from collections import Counter
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

spec = importlib.util.spec_from_file_location("history_redaction", Path(__file__).with_name("omp-command-history.py"))
history = importlib.util.module_from_spec(spec)
spec.loader.exec_module(history)

OPERATORS = (";;&", "&>>", "<<-", "<<<", "&&", "||", ">>", "<<", ">&", "<&", "<>", "&>", "|&", ";;", ";&", ">|", ";", "|", "&", ">", "<", "(", ")")
CONTROL = {"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "function", "select", "{" , "}"}
WRITES = {"rm", "mv", "cp", "tee", "touch", "mkdir", "chmod", "chown", "dd", "truncate", "kill", "pkill", "install"}
SUBCOMMANDS = {"git", "docker", "kubectl", "npm", "bun", "uv", "systemctl", "sudo", "env", "command", "xargs"}
WRAPPERS = {"sudo", "env", "command", "exec", "nohup", "doas", "su", "xargs"}
OPTION_VALUES = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "-u", "-g", "-h", "-p", "-I", "--user", "--group", "--host", "--context", "-H", "--kubeconfig", "--directory"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "pwsh", "powershell"}
KNOWN_HEADS = WRITES | SUBCOMMANDS | WRAPPERS | CONTROL | SHELLS | INTERPRETERS | {"eval", "exec", "source", ".", "read", "printf", "echo", "test", "[", "[[", "curl", "wget", "ssh", "scp", "rsync", "cat", "ls", "rg", "grep", "find", "sed", "awk", "head", "tail", "pwd", "sleep", "wc", "sort", "uniq", "cut", "tr", "true", "false"}
CRITICAL_OPTIONS = OPTION_VALUES | {"-r", "-f", "-rf", "-fr", "-i", "-R", "--force", "--recursive", "--no-preserve-root", "--preserve-root", "--delete", "--hard", "--privileged", "--insecure", "-e", "--eval", "--command", "-S", "-lc", "-ec", "-U", "-a", "-P", "--header", "--proxy-user", "--oauth2-bearer", "--password", "--token", "--api-key"}
META = set("*?[]<>;&|$`#{}()")
CATEGORIES = ("invalid-boundary", "control-flow", "dynamic", "heredoc", "redirection", "multiline", "glob", "comment", "compound", "simple")


def literal_class(value):
  if not value:
    return "empty"
  if value in {"/", ".", "..", "/dev/null", "/dev/zero", "/etc/passwd", "/etc/shadow"}:
    return "special:" + value
  if value.startswith("/etc/"):
    return "system-path"
  if re.match(r"[a-zA-Z][a-zA-Z0-9+.-]*://", value):
    return "url:" + ("query" if "?" in value else "plain")
  if re.fullmatch(r"[0-9]+", value):
    return "number"
  if "/" in value:
    return "path:absolute" if value.startswith("/") else "path:relative"
  if any(c.isspace() for c in value):
    return "text-with-space"
  if re.search(r"\.[A-Za-z0-9]{1,8}$", value):
    return "filename"
  return "atom"


def lex(command):
  tokens = []
  features = set()
  i = 0
  while i < len(command):
    char = command[i]
    if char in "\r\n":
      features.add("multiline")
      tokens.append(("operator", "newline", ()))
      i += 2 if command[i:i+2] == "\r\n" else 1
      continue
    if char.isspace():
      i += 1
      continue
    if char == "#":
      end = command.find("\n", i)
      end = len(command) if end < 0 else end
      marks = tuple(c for c in command[i+1:end] if c in META)
      tokens.append(("comment", "", marks))
      features.add("comment")
      i = end
      continue
    operator = next((op for op in OPERATORS if command.startswith(op, i)), None)
    if operator:
      tokens.append(("operator", operator, ()))
      if operator in {">", "<", ">>", ">&", "<&", "<>", "&>", "&>>", ">|"}:
        features.add("redirection")
      elif operator in {"<<", "<<-", "<<<"}:
        features.add("heredoc")
      else:
        features.add("compound")
      i += len(operator)
      continue
    cooked = []
    pieces = []
    while i < len(command):
      char = command[i]
      if char.isspace() or any(command.startswith(op, i) for op in OPERATORS):
        break
      if char in "'\"":
        quote = char
        start = i
        i += 1
        text = []
        escaped = []
        while i < len(command) and command[i] != quote:
          if quote == '"' and command[i] == "\\" and i+1 < len(command):
            escaped.append(command[i+1] if command[i+1] in META or command[i+1].isspace() else "literal")
            text.append(command[i+1])
            i += 2
          else:
            text.append(command[i])
            i += 1
        if i == len(command):
          features.add("invalid-boundary")
          pieces.append(("unclosed-single" if quote == "'" else "unclosed-double", (), ()))
        else:
          i += 1
        value = "".join(text)
        cooked.append(value)
        kind = "single" if quote == "'" else "double"
        marks = tuple(c for c in value if c in META)
        pieces.append((kind + ("-empty" if i == start+2 else ""), marks, tuple(escaped)))
        features.add("quote:" + kind)
        if quote == '"' and ("$" in value or "`" in value):
          features.add("dynamic")
      elif char == "\\":
        if i+1 == len(command):
          features.add("invalid-boundary")
          pieces.append(("trailing-escape", (), ()))
          i += 1
        else:
          escaped = command[i+1]
          cooked.append(escaped)
          pieces.append(("escape", (escaped if escaped in META or escaped.isspace() else "literal",), ()))
          features.add("escape")
          i += 2
      else:
        start = i
        while i < len(command) and not command[i].isspace() and command[i] not in "'\"\\" and not any(command.startswith(op, i) for op in OPERATORS):
          i += 1
        value = command[start:i]
        cooked.append(value)
        marks = tuple(c for c in value if c in META)
        if any(c in value for c in "*?["):
          # 普通字面片段归一化，通配符前后的位置和字符类仍保留。
          marks += ("glob-shape:" + re.sub(r"[^*?\[\]{}]+", "L", value),)
        pieces.append(("unquoted", marks, ()))
        if any(c in value for c in "*?["):
          features.add("glob")
        if "$" in value or "`" in value:
          features.add("dynamic")
    if len(pieces) > 1:
      features.add("concatenation")
    value = "".join(cooked)
    if value.isdigit() and len(pieces) == 1 and pieces[0][0] == "unquoted" and i < len(command) and command[i] in "<>":
      pieces.append(("adjacent-fd", (), ()))
    tokens.append(("word", value, tuple(pieces)))
  if any(ord(c) < 32 and c not in "\t\r\n" for c in command):
    features.add("invalid-boundary")
  return tokens, features


def classify(command, depth=0):
  tokens, features = lex(command)
  shape = []
  head = None
  position = 0
  redirect_target = False
  redirect_operator = None
  subcommand_seen = False
  option_value = False
  payload = None
  visible_interpreter = None
  operands = {}
  for index, (kind, value, pieces) in enumerate(tokens):
    if kind == "comment":
      shape.append((kind, pieces))
      continue
    if kind == "operator":
      shape.append((kind, value))
      redirect_target = value in {">", "<", ">>", ">&", "<&", "<>", "&>", "&>>", ">|", "<<", "<<-", "<<<"}
      redirect_operator = value if redirect_target else None
      if value in {";", "|", "&&", "||", "&", "newline", "(", ")", "|&", ";;", ";&", ";;&"}:
        head = None
        position = 0
        subcommand_seen = False
        option_value = False
        payload = None
        visible_interpreter = None
        operands = {}
      continue
    next_operator = tokens[index+1][1] if index+1 < len(tokens) and tokens[index+1][0] == "operator" else ""
    if not redirect_target and value.rsplit("/", 1)[-1] in SHELLS | INTERPRETERS:
      # 未知 launcher 也可能启动解释器；疑似脚本内容保守地区分，不依赖 wrapper 清单。
      visible_interpreter = value.rsplit("/", 1)[-1]
    if value.isdigit() and pieces and pieces[-1][0] == "adjacent-fd" and next_operator in {">", "<", ">>", ">&", "<&", "<>"}:
      label = "fd:" + value
    elif redirect_target:
      label = "target:fd:" + value if redirect_operator in {">&", "<&"} and value.isdigit() else "target:" + literal_class(value)
      redirect_target = False
    elif payload:
      if payload == "shell" and depth < 3:
        nested, _, nested_features = classify(value, depth+1)
        label = "nested-shell:" + nested
        if "write-command" in nested_features:
          features.add("nested-write")
      else:
        label = "opaque-code:" + hashlib.sha256(value.encode()).hexdigest()
      features.add("embedded-code")
      payload = None
      option_value = False
      position += 1
    elif option_value:
      label = "option-value:" + literal_class(value)
      option_value = False
      position += 1
    elif re.match(r"[A-Za-z_][A-Za-z0-9_]*=", value):
      label = "assignment:" + value.split("=", 1)[0] + "=" + literal_class(value.split("=", 1)[1])
      features.add("assignment")
      position += 1
    elif head is None:
      head = value.rsplit("/", 1)[-1]
      label = "head:" + (head if head in KNOWN_HEADS else "other")
      if head in CONTROL:
        features.add("control-flow")
      if head in WRITES:
        features.add("write-command")
      if head in {"sudo", "su", "doas"}:
        features.add("privilege-command")
      position = 1
      if head == "eval":
        payload = "shell"
    elif value.startswith("-") and value != "-":
      option, separator, argument = value.partition("=")
      normalized_option = option if option in CRITICAL_OPTIONS or re.search(history.SECRET_KEY, option, re.I) else ("long" if option.startswith("--") else "short")
      label = "option:" + normalized_option + ("=" + literal_class(argument) if separator else "")
      option_value = not separator and option in OPTION_VALUES
      interpreter = head if head in SHELLS | INTERPRETERS else visible_interpreter
      if (interpreter in SHELLS and (re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", option) or option == "--command")) or (head == "env" and option == "-S"):
        payload = "shell"
      elif interpreter in INTERPRETERS and option in {"-c", "-e", "--eval", "--command"}:
        payload = "opaque"
      if separator and payload:
        # 内联程序参数也保留内容差异，不误当成下一个普通参数。
        label += ":inline-code:" + hashlib.sha256(argument.encode()).hexdigest()
        features.add("embedded-code")
        payload = None
      position += 1
    elif head in WRAPPERS:
      label = "wrapped-head:" + value
      head = value.rsplit("/", 1)[-1]
      subcommand_seen = False
      if head in WRITES:
        features.add("write-command")
      if head == "eval":
        payload = "shell"
      position += 1
    elif head in SUBCOMMANDS and not subcommand_seen:
      label = "subcommand:" + value
      subcommand_seen = True
      position += 1
    else:
      label = literal_class(value)
      if head in {"cp", "mv", "ln", "install"}:
        operands.setdefault(value, len(operands))
        label += ":operand:" + str(operands[value])
      position += 1
    # 引号内的普通数据不按内容或重复标点分场景；保留标点种类和片段次序。
    normalized_pieces = tuple((scope, tuple(sorted(set(marks))) if scope.startswith(("single", "double")) else marks, escaped)
      for scope, marks, escaped in pieces)
    shape.append(("word", label, normalized_pieces))
  category = next((c for c in CATEGORIES if c in features), "simple")
  signature = json.dumps(shape, ensure_ascii=True, separators=(",", ":"))
  return hashlib.sha256(signature.encode()).hexdigest(), category, sorted(features)


def compact(data, identities=()):
  required = {"schemaVersion", "publication", "redactionVersion", "records", "statistics"}
  if not isinstance(data, dict) or set(data) != required or type(data["schemaVersion"]) is not int or type(data["redactionVersion"]) is not int or data["schemaVersion"] != 1 or data["redactionVersion"] != 2 or data["publication"] != "private-review-required":
    raise ValueError("invalid candidate version")
  if not isinstance(data["records"], list) or set(data["statistics"]) != set(history.SOURCES):
    raise ValueError("invalid candidates")
  groups = {}
  seen = set()
  input_occurrences = 0
  for record in data["records"]:
    if not isinstance(record, dict) or set(record) != {"id", "command", "sources", "occurrences"}:
      raise ValueError("invalid candidate record")
    command = record["command"]
    if not isinstance(command, str) or command in seen or record["id"] != hashlib.sha256(command.encode()).hexdigest():
      raise ValueError("invalid command identity")
    if not isinstance(record["sources"], list) or not record["sources"] or any(s not in history.SOURCES for s in record["sources"]) or len(set(record["sources"])) != len(record["sources"]):
      raise ValueError("invalid sources")
    if type(record["occurrences"]) is not int or record["occurrences"] < 1:
      raise ValueError("invalid occurrences")
    if history.redaction_findings(command, identities):
      raise ValueError("second pass rejected candidate")
    seen.add(command)
    input_occurrences += record["occurrences"]
    scene_id, category, features = classify(command)
    group = groups.get(scene_id)
    if group is None:
      group = {"id": record["id"], "command": command, "sources": [], "occurrences": 0,
        "scenario": {"id": scene_id, "category": category, "features": features, "members": 0}}
      groups[scene_id] = group
    elif (len(command.encode()), command) < (len(group["command"].encode()), group["command"]):
      group["command"], group["id"] = command, record["id"]
    group["occurrences"] += record["occurrences"]
    group["scenario"]["members"] += 1
    group["sources"] = [s for s in history.SOURCES if s in set(group["sources"] + record["sources"])]
  counters = {"files", "events", "extracted", "unsupportedCommandCarrier", "malformed", "redactionSkipped", "dynamicCommandSkipped", "nonCommand", "jsScripts", "jsLiteralCommands", "jsUnresolvedCalls", "jsMalformedScripts", "secondPassSkipped"}
  for source in history.SOURCES:
    values = data["statistics"][source]
    if not isinstance(values, dict) or set(values) != counters or any(type(v) is not int or v < 0 for v in values.values()):
      raise ValueError("invalid statistics")
  if sum(s["extracted"] for s in data["statistics"].values()) != input_occurrences:
    raise ValueError("occurrence mismatch")
  records = [groups[key] for key in sorted(groups)]
  if any(history.redaction_findings(r["command"], identities) for r in records):
    raise ValueError("second pass rejected representative")
  return {"schemaVersion": 2, "publication": "private-review-required", "redactionVersion": 2,
    "records": records, "statistics": data["statistics"],
    "selection": {"classificationVersion": 1, "inputUniqueCommands": len(seen), "scenarioCount": len(records),
      "removedDuplicateCommands": len(seen)-len(records), "preservedOccurrences": input_occurrences,
      "secondPassChecked": len(seen), "secondPassFailures": 0,
      "categories": dict(sorted(Counter(r["scenario"]["category"] for r in records).items()))}}


def main(argv=None):
  import argparse
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--input", required=True)
  parser.add_argument("--output", required=True)
  parser.add_argument("--identity-term", action="append", default=[])
  args = parser.parse_args(argv)
  try:
    destination = history.output_path(args.output)
    result = compact(json.loads(Path(args.input).read_text()), args.identity_term)
    import os
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    encoded = (json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    with os.fdopen(descriptor, "wb") as stream:
      # 固定时间戳且不写原始文件名，可重复压缩以降低私有语料存储量。
      stream.write(gzip.compress(encoded, mtime=0) if destination.suffix == ".gz" else encoded)
    print(json.dumps(result["selection"]))
    return 0
  except (OSError, ValueError, TypeError):
    print("scenario compaction failed: invalid or insufficiently redacted input", file=sys.stderr)
    return 2


if __name__ == "__main__":
  raise SystemExit(main())
