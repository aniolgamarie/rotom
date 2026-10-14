#!/usr/bin/env python3
"""检查公开文档链接及少量本机标识；不读取账号文件，不输出匹配正文。"""

import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = ("README.md", "README.zh-CN.md", "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md")
SKIP_PARTS = {".git", ".cache", ".venv", "node_modules", "vendor", "upstream"}
PRIVATE_NAMES = {"auth.json", "oauth.json", "credentials.json", "secrets.toml", "settings.local.json"}
TEXT_SUFFIXES = {".md", ".py", ".ts", ".toml", ".json", ".yaml", ".yml", ".sh", ".example"}
GENERIC_USER = r"(?:PrivateIdentity[0-9]+|user|private-user|example-user|alice|bob|example|developer|runner|test(?:er)?|fake|sandbox|agentcfg|codex|nobody)"
PRIVATE_PATHS = (
  re.compile(r"/(?:home|Users)/(?!" + GENERIC_USER + r"(?:/|\b))[A-Za-z0-9][A-Za-z0-9_.-]*/"),
  re.compile(r"/data/\d+/(?!" + GENERIC_USER + r"(?:/|\b))[A-Za-z0-9][A-Za-z0-9_.-]*/"),
)
LINK = re.compile(r"!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")


def public_text(path):
  if path.name in PRIVATE_NAMES or path.name.startswith(".env"):
    return False
  if set(path.parts) & SKIP_PARTS or any("vendor" in part for part in path.parts):
    return False
  if path.parts and path.parts[0] == "locks":
    # 固定锁/来源由各后端独立校验；这里不改写上游材料。
    return False
  if path.name in {"LICENSE", "NOTICE", "THIRD-PARTY-NOTICES.txt"}:
    return False
  return path.suffix in TEXT_SUFFIXES


def fenced_lines(text):
  fence = None
  for number, line in enumerate(text.splitlines(), 1):
    marker = re.match(r"\s*(`{3,}|~{3,})", line)
    if marker:
      if fence is None:
        fence = marker[1][0]
      elif marker[1][0] == fence:
        fence = None
      continue
    if fence is None:
      yield number, line


def headings(text):
  result, counts = set(), {}
  for _, line in fenced_lines(text):
    match = re.match(r"#{1,6}\s+(.+?)\s*#*\s*$", line)
    if not match:
      continue
    title = re.sub(r"<[^>]*>", "", match[1]).lower()
    title = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
    count = counts.get(title, 0)
    counts[title] = count + 1
    result.add(title + ("-" + str(count) if count else ""))
  return result


def inspect(repository, paths):
  findings = []
  for relative in sorted(set(paths)):
    path = Path(relative)
    target = repository / path
    if not public_text(path):
      continue
    if (path.is_absolute() or ".." in path.parts
        or any(repository.joinpath(*path.parts[:index]).is_symlink() for index in range(1, len(path.parts) + 1))):
      findings.append({"path": relative, "line": 0, "category": "unsafe-public-path"})
      continue
    if not target.exists():
      continue
    if not target.is_file():
      findings.append({"path": relative, "line": 0, "category": "unsafe-public-path"})
      continue
    text = target.read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), 1):
      if any(pattern.search(line) for pattern in PRIVATE_PATHS):
        findings.append({"path": relative, "line": number, "category": "machine-specific-path"})
    if relative not in DOCUMENTS and not relative.startswith("docs/"):
      continue
    for number, line in fenced_lines(text):
      for match in LINK.finditer(line):
        value = match[1].strip("<>")
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc or value.startswith("/"):
          continue
        local = (target.parent / unquote(parsed.path)).resolve() if parsed.path else target.resolve()
        if not local.is_relative_to(repository.resolve()) or not local.exists():
          findings.append({"path": relative, "line": number, "category": "broken-local-link"})
        elif parsed.fragment and local.suffix == ".md":
          if unquote(parsed.fragment) not in headings(local.read_text(encoding="utf-8")):
            findings.append({"path": relative, "line": number, "category": "missing-heading"})
  return findings


def main():
  tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
  added = [path.relative_to(ROOT).as_posix() for path in (ROOT / "docs").rglob("*.md")]
  findings = inspect(ROOT, [name for name in tracked if name] + list(DOCUMENTS) + added)
  print(json.dumps({"status": "FAIL" if findings else "PASS", "findings": findings}, indent=2))
  return 1 if findings else 0


if __name__ == "__main__":
  raise SystemExit(main())
