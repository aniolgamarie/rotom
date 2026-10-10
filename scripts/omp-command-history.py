#!/usr/bin/env python3
"""只读提取显式指定的历史日志；产物仍须私下人工审核。"""

import argparse
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import select
import shlex
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit, urlunsplit

SOURCES = ("pi", "codex", "omp")
SECRET_KEY = r"(?:[A-Za-z0-9_]*(?:token|password|passwd|secret|api[_-]?key|credential)[A-Za-z0-9_]*|authorization|cookie)"
VALUE = r'''(?:"[^"\n]*"|'[^'\n]*'|[^\s;&|<>]+)'''
URL = r'''[A-Za-z][A-Za-z0-9+.-]*://[^\s'"<>|;]+'''
URL_UNQUOTED = r'''[A-Za-z][A-Za-z0-9+.-]*://[^\s'"<>|;&]+(?:&(?!&)[^\s'"<>|;&=]+=([^\s'"<>|;&]*))*'''
EMAIL = r"[A-Za-z0-9.!#$%&'*+=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
PERSONAL_PATH = r"(?<![\w/])/(?:var/tmp|home|Users|root|data|mnt|media|tmp|opt|workspaces?|private)(?![\w.-])(?:/[^\s'\";&|<>*?\[\]$`(){}\\]*)?"


def redaction_findings(command, identities=()):
  """独立扫描输出，只返回分类；不输出匹配原文。"""
  findings = set()
  if re.search(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|AKIA[A-Z0-9]{16})\b", command):
    findings.add("known-key")
  if re.search(r"-----BEGIN .*PRIVATE KEY", command):
    findings.add("pem")
  if any(identity and identity in command for identity in identities):
    findings.add("identity")
  if any(identities):
    # 仅做 shell 词法拼接，不执行或展开命令。
    try:
      tokens = shlex.split(command)
    except ValueError:
      findings.add("identity")
    else:
      if any(identity and identity in token for identity in identities for token in tokens):
        findings.add("identity")
  if re.search(PERSONAL_PATH, command):
    findings.add("personal-path")
  # 二次扫描用数字片段+标准库验证，避免与替换器共用同一边界正则。
  for candidate in re.findall(r"[0-9.]+", command):
    try:
      ipaddress.IPv4Address(candidate.strip("."))
      findings.add("ip")
    except ValueError:
      pass
  for match in re.finditer(r"(?<![\w:])[0-9A-Fa-f:]*:[0-9A-Fa-f:]+(?![\w:])", command):
    try:
      ipaddress.IPv6Address(match[0])
      findings.add("ip")
    except ValueError:
      pass
  segments = re.split(r"(\"[^\"\n]*\"|'[^'\n]*')", command)
  url_matches = []
  outside_urls = ""
  for index, segment in enumerate(segments):
    pattern = URL if index % 2 else URL_UNQUOTED
    url_matches.extend(re.finditer(pattern, segment))
    outside_urls += re.sub(pattern, "", segment)
  if re.search(EMAIL, outside_urls):
    findings.add("email")
  if re.search(r"[A-Za-z][A-Za-z0-9+.-]*:REDACTED_EMAIL|://REDACTED_EMAIL", command):
    findings.add("url-marker")
  for match in url_matches:
    try:
      url = urlsplit(match[0])
      if "@" in url.netloc and url.netloc.rsplit("@", 1)[0] != "REDACTED":
        findings.add("url-credential")
      if any(part and part.split("=", 1)[-1] != "REDACTED" for part in url.query.split("&")):
        findings.add("url-query")
      if url.fragment and url.fragment != "REDACTED":
        findings.add("url-query")
    except ValueError:
      findings.add("url-boundary")
  patterns = [
    rf"(?i)\b{SECRET_KEY}\b[\"']?\s*[=:]\s*({VALUE})",
    rf"(?i)--{SECRET_KEY}\b\s*(?:=\s*)?({VALUE})",
    rf"(?i)(?:-H|--header)\s+({VALUE})",
    rf"(?i)\bBearer\s+({VALUE})",
  ]
  if re.search(r"\bcurl\b", command):
    patterns.append(rf"(?<![\w-])(?:--(?:proxy-user|user|oauth2-bearer)(?:=|\s+)|-[uU]\s*)({VALUE})")
  if re.search(r"\b(?:mysql|mariadb|obclient)\b", command):
    patterns.append(rf"(?<![\w-])-p({VALUE})")
  if re.search(r"\b(?:redis-cli|sqlcmd)\b", command):
    patterns.append(rf"(?:-a|-P)\s+({VALUE})")
  for pattern in patterns:
    for match in re.finditer(pattern, command):
      if match[1].strip("\"'") != "REDACTED":
        findings.add("credential")
      elif match[1].startswith(("'", '"')) and match.end() < len(command) and re.match(r"[\w\"'./:+@=-]", command[match.end()]):
        findings.add("credential-tail")
  return findings



class JsExtractor:
  TIMEOUT = 10
  MAX_RESPONSE = 16 * 1024 * 1024

  def __init__(self, bun, module):
    for value in (bun, module):
      if not Path(value).is_absolute() or not Path(value).is_file():
        raise ValueError("parser requires explicit absolute files")
    self.argv = [bun, str(Path(__file__).resolve().parent / "extract-omp-history-js.ts"), "--parser-module", module]
    self.process = None
    self.pending = b""

  def parse(self, script):
    if self.process is None:
      # 固定解析器读管道中的文本；绝不把日志源码交给 bun 执行。
      self.process = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
      os.set_blocking(self.process.stdin.fileno(), False)
      os.set_blocking(self.process.stdout.fileno(), False)
    process = self.process
    deadline = time.monotonic() + self.TIMEOUT
    request = memoryview((json.dumps({"script": script}) + "\n").encode())
    while request:
      remaining = deadline - time.monotonic()
      if remaining <= 0 or not select.select([], [process.stdin.fileno()], [], remaining)[1]:
        raise ValueError("parser timeout")
      try:
        written = os.write(process.stdin.fileno(), request)
      except BlockingIOError:
        continue
      if not written:
        raise ValueError("parser protocol failed")
      request = request[written:]
    while b"\n" not in self.pending:
      remaining = deadline - time.monotonic()
      if remaining <= 0 or not select.select([process.stdout.fileno()], [], [], remaining)[0]:
        raise ValueError("parser timeout")
      try:
        chunk = os.read(process.stdout.fileno(), 65536)
      except BlockingIOError:
        continue
      if not chunk:
        raise ValueError("parser protocol failed")
      self.pending += chunk
      if len(self.pending) > self.MAX_RESPONSE:
        raise ValueError("parser response too large")
    line, self.pending = self.pending.split(b"\n", 1)
    try:
      response = json.loads(line)
    except (ValueError, UnicodeError):
      raise ValueError("parser protocol failed") from None
    if not isinstance(response, dict) or set(response) != {"commands", "unsupported", "malformed"}:
      raise ValueError("parser protocol failed")
    if (not isinstance(response["commands"], list)
        or not all(isinstance(command, str) for command in response["commands"])
        or type(response["unsupported"]) is not int or response["unsupported"] < 0
        or type(response["malformed"]) is not bool
        or (response["malformed"] and response["commands"])):
      raise ValueError("parser protocol failed")
    return response

  def close(self):
    if self.process is None:
      return
    process, self.process = self.process, None
    try:
      process.stdin.close()
      try:
        status = process.wait(timeout=5)
      except subprocess.TimeoutExpired:
        process.terminate()
        try:
          process.wait(timeout=2)
        except subprocess.TimeoutExpired:
          process.kill()
          process.wait(timeout=2)
        raise ValueError("parser did not stop") from None
      if status:
        raise ValueError("parser failed")
    finally:
      process.stdout.close()

def mask_value(value):
  if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
    return value[0] + "REDACTED" + value[-1]
  return "REDACTED"


def redact(command, identities=()):
  # 不能可靠判定边界的源码和密钥整条隔离，原文仅留在内存。
  try:
    shlex.split(command)
  except ValueError:
    return None
  if re.search(r"[A-Za-z]:\\(?:Users|Documents and Settings)\\", command):
    return None
  if re.search(r"-----BEGIN .*PRIVATE KEY", command):
    return None
  if "<<" in command:
    literal = re.fullmatch(r"cat\s+<<'([A-Za-z_]+)'\n([A-Za-z0-9 .,!\n-]*)\n\1\n?", command)
    if literal is None:
      return None
  if "\n" in command and re.search(r"\b(?:python\d*|node|ruby|perl)\b[^\n]*(?:-c|-e)\b", command):
    return None
  dynamic = command.replace("$(pwd)", "")
  if re.search(r"\$\(|`|\$\{", dynamic):
    return None

  # 引号片段后接字面后缀或另一片段时，旧正则只能遮半段；整条隔离。
  sensitive = [
    rf"(?i)\b{SECRET_KEY}\b[\"']?\s*[=:]\s*({VALUE})",
    rf"(?i)--{SECRET_KEY}\b\s*(?:=\s*)?({VALUE})",
    rf"(?i)(?:-H|--header)\s+({VALUE})",
    rf"(?i)\bBearer\s+({VALUE})",
  ]
  if re.search(r"\b(?:mysql|mariadb|obclient)\b", command):
    sensitive.append(rf"(?<![\w-])-p({VALUE})")
  if re.search(r"\b(?:redis-cli|sqlcmd)\b", command):
    sensitive.append(rf"(?:-a|-P)\s+({VALUE})")
  for pattern in sensitive:
    for match in re.finditer(pattern, command):
      value = match[1]
      if re.search(r"[$`\\]", value):
        return None
      # 未加引号开头的词也可能含带空格的引号片段，不能只遮到空格。
      context = None
      escaped = False
      for char in command[:match.start(1)]:
        if escaped:
          escaped = False
        elif char == "\\" and context != "'":
          escaped = True
        elif char == context:
          context = None
        elif context is None and char in "\"'":
          context = char
      # Header 内层匹配可能带上外层 shell 的关闭引号。
      checked = value[:-1] if context and value.endswith(context) and not value.startswith(context) else value
      try:
        shlex.split(checked)
      except ValueError:
        return None
      if value.startswith(("'", '\"')) and match.end() < len(command):
        if re.match(r"[\w\"'./:+@=-]", command[match.end()]):
          return None

  # curl 的认证值不是通用 secret 字段，完整遮盖用户名、密码和 OAuth 凭据。
  if re.search(r"\bcurl\b", command):
    auth = re.compile(rf"(?<![\w-])((?:--(?:proxy-user|user|oauth2-bearer)(?:=|\s+)|-[uU]\s*))({VALUE})(?=\s|[;&|<>]|$)")
    flags = re.findall(r"(?<![\w-])(?:--(?:proxy-user|user|oauth2-bearer)(?=[=\s]|$)|-[uU](?=$|\s|[^\s-]))", command)
    matches = list(auth.finditer(command))
    if len(matches) != len(flags):
      return None
    for match in matches:
      value = match[2]
      quoted = len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"
      if re.search(r"[$`\\]", value) or value.startswith("-"):
        return None
      if not quoted and re.search(r"[\"'*?\[\]{}()]", value):
        return None
    command = auth.sub(lambda match: match[1] + mask_value(match[2]), command)

  secret_values = re.finditer(rf"(?i)\b{SECRET_KEY}\b[\"']?\s*[=:]\s*({VALUE})", command)
  if any(re.search(r"[$`\\]", match[1]) for match in secret_values):
    return None
  if any(char in command for char in "$\\") and re.search(rf"(?i)--{SECRET_KEY}\b|(?:-H|--header)\s|\b(?:mysql|mariadb|obclient|redis-cli|sqlcmd)\b", command):
    return None

  command = re.sub(
    rf"(?i)(\b{SECRET_KEY}\b[\"']?\s*[=:]\s*)({VALUE})",
    lambda m: m[1] + mask_value(m[2]), command,
  )
  command = re.sub(
    rf"(?i)((?:--(?:{SECRET_KEY})\b|\bPGPASSWORD=)\s*(?:=\s*)?)({VALUE})",
    lambda m: m[1] + mask_value(m[2]), command,
  )
  command = re.sub(
    r'''(?i)((?:-H|--header)\s+)("[^"\n]*"|'[^'\n]*'|[^\s;&|<>]+)''',
    lambda m: m[1] + mask_value(m[2]), command,
  )
  # 数据库 CLI 的短密码参数有不同的边界约定。
  if re.search(r"\b(?:mysql|mariadb|obclient)\b", command):
    command = re.sub(rf"(?<![\w-])(-p)({VALUE})", lambda m: m[1] + mask_value(m[2]), command)
  if re.search(r"\b(?:redis-cli|sqlcmd)\b", command):
    command = re.sub(rf"((?:-a|-P)\s+)({VALUE})", lambda m: m[1] + mask_value(m[2]), command)

  command = re.sub(rf"(?i)(\bBearer\s+)({VALUE})", lambda m: m[1] + mask_value(m[2]), command)
  command = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|AKIA[A-Z0-9]{16})\b", "REDACTED", command)

  def mask_url(match):
    try:
      url = urlsplit(match[0])
      host = url.netloc.rsplit("@", 1)[-1]
      if "@" in url.netloc:
        host = "REDACTED@" + host
      # 无等号的查询片段也可能是短凭据，不保留其字面值。
      query = "&".join(part.split("=", 1)[0] + "=REDACTED" if "=" in part else "REDACTED" for part in url.query.split("&")) if url.query else ""
      return urlunsplit((url.scheme, host, url.path, query, "REDACTED" if url.fragment else ""))
    except ValueError:
      return "REDACTED_URL"

  # 裸 URL 中无等号的 & 后缀按 shell 控制边界保留；带引号时属于 URL。
  chunks = re.split(r"(\"[^\"\n]*\"|'[^'\n]*')", command)
  for index, chunk in enumerate(chunks):
    for match in re.finditer(URL if index % 2 else URL_UNQUOTED, chunk):
      if index % 2:
        if chunks[index - 1] and not re.search(r"[\s;&|<>]$", chunks[index - 1]):
          return None
        if chunks[index + 1] and not re.match(r"[\s;&|<>]", chunks[index + 1]):
          return None
      elif match.end() == len(chunk) and index + 1 < len(chunks):
        return None
  command = "".join(re.sub(URL if index % 2 else URL_UNQUOTED, mask_url, chunk) for index, chunk in enumerate(chunks))
  # URL userinfo 的 marker 不得被邮箱替换吞掉 scheme://。
  chunks = re.split(r"(\"[^\"\n]*\"|'[^'\n]*')", command)
  masked_chunks = []
  for index, chunk in enumerate(chunks):
    pattern = URL if index % 2 else URL_UNQUOTED
    cursor = 0
    masked = ""
    for match in re.finditer(pattern, chunk):
      masked += re.sub(EMAIL, "REDACTED_EMAIL", chunk[cursor:match.start()]) + match[0]
      cursor = match.end()
    masked_chunks.append(masked + re.sub(EMAIL, "REDACTED_EMAIL", chunk[cursor:]))
  command = "".join(masked_chunks)
  command = re.sub(r"(?:[0-9]{1,3}\.){3}[0-9]{1,3}", "REDACTED_IP", command)
  # IPv6 使用标准库验证，避免把 shell 的冒号语法误作地址。
  def mask_ipv6(match):
    try:
      ipaddress.IPv6Address(match[0])
      return "REDACTED_IP"
    except ValueError:
      return match[0]
  command = re.sub(r"(?<![\w:])[0-9A-Fa-f:]*:[0-9A-Fa-f:]+(?![\w:])", mask_ipv6, command)
  command = re.sub(PERSONAL_PATH, "/REDACTED_PATH", command)
  for identity in identities:
    if identity:
      command = command.replace(identity, "REDACTED_IDENTITY")
  if any(identities):
    # 原文字面替换无法覆盖引号或反斜线拼接出的身份，整条隔离。
    try:
      tokens = shlex.split(command)
    except ValueError:
      return None
    if any(identity and identity in token for identity in identities for token in tokens):
      return None
  # 剩余的未知高熵串不能当作已覆盖秘密公开输出。
  for token in re.findall(r"[A-Za-z0-9_+/=-]{24,}", command):
    # 已遮盖的认证参数包含数字和连接符，不能误计为未知凭据。
    if re.fullmatch(r"--(?:user|proxy-user|oauth2-bearer)=REDACTED", token):
      continue
    entropy = -sum((token.count(char) / len(token)) * math.log2(token.count(char) / len(token)) for char in set(token))
    if len(set(token)) >= 12 and entropy >= 3.5:
      return None
  return command


def extract(event, source, js_parser=None, counters=None):
  if not isinstance(event, dict):
    return [], "malformed"
  if source in ("pi", "omp"):
    message = event.get("message", event)
    if not isinstance(message, dict):
      return [], "malformed"
    if message.get("role") != "assistant":
      return [], "nonCommand"
    content = message.get("content")
    if not isinstance(content, list):
      return [], "malformed"
    commands = []
    unsupported = False
    for item in content:
      if not isinstance(item, dict):
        return [], "malformed"
      if item.get("type") != "toolCall":
        if item.get("name") in ("bash", "permission_bash"):
          unsupported = True
        continue
      if item.get("name") not in ("bash", "permission_bash"):
        continue
      args = item.get("arguments")
      if not isinstance(args, dict) or not isinstance(args.get("command"), str):
        unsupported = True
      else:
        commands.append(args["command"])
    return commands, "unsupportedCommandCarrier" if unsupported else (None if commands else "nonCommand")
  if event.get("type") != "response_item":
    return [], "nonCommand"
  payload = event.get("payload")
  if not isinstance(payload, dict):
    return [], "malformed"
  if payload.get("type") == "custom_tool_call":
    name = payload.get("name")
    short_name = name.rsplit(".", 1)[-1] if isinstance(name, str) else ""
    if short_name == "exec" and js_parser is not None and isinstance(payload.get("input"), str):
      response = js_parser.parse(payload["input"])
      counters["jsScripts"] += 1
      counters["jsLiteralCommands"] += len(response["commands"])
      counters["jsUnresolvedCalls"] += response["unsupported"]
      counters["jsMalformedScripts"] += int(response["malformed"])
      if response["malformed"]:
        return [], "malformed"
      if response["unsupported"]:
        return response["commands"], "unsupportedCommandCarrier"
      return response["commands"], None if response["commands"] else "nonCommand"
    if short_name in ("exec", "exec_command", "shell", "shell_command", "terminal", "bash", "permission_bash"):
      return [], "unsupportedCommandCarrier"
    if short_name in ("apply_patch", "read_file", "write_stdin", "view_image"):
      return [], "nonCommand"
    # 未知工具只识别命令字段形状，不执行或解释 JS 源码。
    for field in ("input", "arguments"):
      carrier = payload.get(field)
      if isinstance(carrier, str):
        try:
          carrier = json.loads(carrier)
        except json.JSONDecodeError:
          if re.search(r"\b(?:cmd|command)\b[\"']?\s*:", carrier):
            return [], "unsupportedCommandCarrier"
          continue
      if isinstance(carrier, dict) and ("cmd" in carrier or "command" in carrier):
        return [], "unsupportedCommandCarrier"
    return [], "nonCommand"
  if payload.get("type") != "function_call" or payload.get("name") not in ("exec_command", "shell_command", "shell", "terminal"):
    return [], "nonCommand"
  try:
    arguments = payload["arguments"]
    args = arguments if isinstance(arguments, dict) else json.loads(arguments)
  except (KeyError, TypeError, json.JSONDecodeError):
    return [], "malformed"
  if not isinstance(args, dict):
    return [], "malformed"
  if "cmd" in args and "command" in args:
    return [], "unsupportedCommandCarrier"
  value = args.get("cmd", args.get("command"))
  if isinstance(value, str):
    return [value], None
  if isinstance(value, list) and len(value) == 3 and all(isinstance(part, str) for part in value):
    if Path(value[0]).name in ("sh", "bash", "zsh", "dash") and value[1] in ("-c", "-lc"):
      return [value[2]], None
  return [], "unsupportedCommandCarrier"


def log_files(root):
  path = Path(root)
  if path.is_symlink():
    raise ValueError("input symlink rejected")
  if path.is_file() and path.suffix == ".jsonl":
    return [path]
  if path.is_dir():
    return sorted(p for p in path.rglob("*.jsonl") if not p.is_symlink() and not any(parent.is_symlink() for parent in p.parents))
  raise ValueError("input must be a JSONL file or directory")


def output_path(value):
  path = Path(os.path.abspath(value))
  repo = Path(__file__).resolve().parents[1]
  cache = repo / ".cache"
  if path.is_relative_to(repo) and not path.is_relative_to(cache):
    raise ValueError("public repository output rejected")
  temporary = Path(os.path.abspath(tempfile.gettempdir()))
  canonical_temporary = temporary.resolve()
  # 仅规范化系统临时根（如 macOS /var）；其下用户指定的 symlink 仍拒绝。
  if path.is_relative_to(temporary):
    path = canonical_temporary / path.relative_to(temporary)
  if path.is_relative_to(repo) and not path.is_relative_to(cache):
    raise ValueError("public repository output rejected")
  allowed = (cache, canonical_temporary, Path("/tmp").resolve())
  candidates = [base for base in allowed if path.is_relative_to(base) and path != base]
  if not candidates:
    raise ValueError("output must be under repository .cache or system temporary root")
  if path.exists() or path.is_symlink():
    raise ValueError("output already exists")
  for parent in path.parents:
    if parent.is_symlink():
      raise ValueError("output symlink rejected")
  # 仅创建私有目录；不改动系统临时根或仓库已有目录的权限。
  boundary = max(candidates, key=lambda base: len(base.parts))
  if path.parent == boundary:
    raise ValueError("output requires a private subdirectory")
  missing = []
  parent = path.parent
  while not parent.exists():
    missing.append(parent)
    parent = parent.parent
  for directory in reversed(missing):
    directory.mkdir(mode=0o700)
  if stat.S_IMODE(path.parent.stat().st_mode) & 0o077:
    raise ValueError("output directory must be private (0700)")
  return path


def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  for source in SOURCES:
    parser.add_argument(f"--{source}-root", action="append", default=[])
  parser.add_argument("--output", required=True)
  parser.add_argument("--identity-term", action="append", default=[])
  parser.add_argument("--bun")
  parser.add_argument("--js-parser-module")
  args = parser.parse_args(argv)
  js_parser = None
  try:
    if bool(args.bun) != bool(args.js_parser_module):
      raise ValueError("both parser arguments are required")
    if args.bun:
      js_parser = JsExtractor(args.bun, args.js_parser_module)
    if not any(getattr(args, f"{source}_root") for source in SOURCES):
      raise ValueError("at least one explicit input root is required")
    destination = output_path(args.output)
    records = {}
    statistics = {}
    for source in SOURCES:
      counters = dict.fromkeys(("files", "events", "extracted", "unsupportedCommandCarrier", "malformed", "redactionSkipped", "secondPassSkipped", "dynamicCommandSkipped", "nonCommand", "jsScripts", "jsLiteralCommands", "jsUnresolvedCalls", "jsMalformedScripts"), 0)
      statistics[source] = counters
      files = set()
      for root in getattr(args, f"{source}_root"):
        files.update(log_files(root))
      for path in sorted(files):
        counters["files"] += 1
        with path.open(encoding="utf-8", errors="replace") as handle:
          for line in handle:
            counters["events"] += 1
            try:
              event = json.loads(line)
            except json.JSONDecodeError:
              counters["malformed"] += 1
              continue
            commands, status = extract(event, source, js_parser, counters)
            if status:
              counters[status] += 1
            for command in commands:
              safe = redact(command, args.identity_term)
              if safe is None:
                if re.search(r"\$(?:\(|\{|[A-Za-z_])|`|<<", command):
                  counters["dynamicCommandSkipped"] += 1
                counters["redactionSkipped"] += 1
                continue
              if redaction_findings(safe, args.identity_term):
                counters["secondPassSkipped"] += 1
                counters["redactionSkipped"] += 1
                continue
              counters["extracted"] += 1
              if safe not in records:
                records[safe] = {"id": hashlib.sha256(safe.encode()).hexdigest(), "command": safe, "sources": [], "occurrences": 0}
              record = records[safe]
              if source not in record["sources"]:
                record["sources"].append(source)
              record["occurrences"] += 1
    if js_parser is not None:
      js_parser.close()
    artifact = {"schemaVersion": 1, "publication": "private-review-required", "records": list(records.values()), "statistics": statistics, "redactionVersion": 2}
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
      json.dump(artifact, handle, ensure_ascii=False, indent=2)
      handle.write("\n")
    print(json.dumps({"records": len(records), "statistics": statistics, "publication": "private-review-required"}))
    return 0
  except (OSError, ValueError, subprocess.SubprocessError):
    # 异常不得包含输入路径、原始日志或秘密。
    print("history extraction failed: invalid input/output or filesystem operation", file=sys.stderr)
    return 2
  finally:
    if js_parser is not None:
      try:
        js_parser.close()
      except (OSError, ValueError, subprocess.SubprocessError):
        pass


if __name__ == "__main__":
  raise SystemExit(main())
