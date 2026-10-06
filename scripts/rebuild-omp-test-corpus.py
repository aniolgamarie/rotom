#!/usr/bin/env python3
"""将私有 Shell 场景重建为仅含固定词表及合成数据的公开测试；不执行命令。"""

from collections import Counter
import argparse
import gzip
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def module(name, filename):
  spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
  result = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(result)
  return result


scenes = module("public_scene_shapes", "omp-history-scenarios.py")
oracle = module("independent_shell_oracle", "omp-shell-test-oracle.py")
WORDS = scenes.KNOWN_HEADS | scenes.CONTROL | oracle.CONTROL | {"API_KEY", "TOKEN", "PASSWORD", "ACCESS_TOKEN", "SECRET", "AUTHORIZATION", "authorization", "cookie", "password", "secret", "api_key", "gawk", "mawk", "nawk", "system", "getline", "print", "BEGIN", "END", "http", "https", "ftp", "file", "ssh", "REDACTED", "REDACTED_PATH", "REDACTED_IP", "REDACTED_EMAIL", "REDACTED_IDENTITY"}
FLAGS = scenes.CRITICAL_OPTIONS | {"-la", "-l", "-a", "-n", "-F", "-E", "--file", "--load", "--exec", "--expression", "-type", "-name", "-maxdepth", "-print", "-print0", "-exec", "-execdir", "-ok", "-okdir", "--", "-o", "-v"}
SPECIAL_PATHS = {"/", ".", "..", "/dev/null", "/dev/zero", "/etc/passwd", "/etc/shadow"}
LITERAL = re.compile(r"(?<![\w/])/(?:dev/null|dev/zero|etc/passwd|etc/shadow)(?![\w/])|[^\W]+", re.UNICODE)


def rebuild(command):
  aliases = {}

  def atom(match):
    value = match[0]
    if value in WORDS or value in SPECIAL_PATHS or (match.start() > 0 and match.string[match.start()-1] == "-" and "-"+value in FLAGS):
      return value
    if value.isdecimal():
      return "1"
    aliases.setdefault(value, "fixture_" + str(len(aliases)+1))
    return aliases[value]

  replacements = []
  ts = oracle.tokens(command)
  for i, (kind, raw, start, end) in enumerate(ts):
    if kind == "operator":
      continue
    # 描述符是公开语法值，不是历史数据；两端编号及根/系统目标保持。
    fd = re.fullmatch(r"\d+", raw) and i+1 < len(ts) and end == ts[i+1][2] and ts[i+1][1] in oracle.REDIRECTS
    quoted_fd = False
    if i > 0 and ts[i-1][1] in {">&", "<&"}:
      try:
        decoded, _ = oracle.word(raw)
        quoted_fd = bool(re.fullmatch(r"\d+", decoded))
      except ValueError:
        pass
    if fd or raw in SPECIAL_PATHS or raw in FLAGS:
      value = str(min(int(raw), 10)) if fd else raw
    elif quoted_fd:
      value = raw if int(decoded) <= 9 else re.sub(r"\d+", "10", raw)
    else:
      option, separator, argument = raw.partition("=")
      secret_option = option.startswith("--") and re.search(r"token|password|passwd|secret|api[_-]?key|credential|authorization|cookie", option, re.I)
      if secret_option and option not in FLAGS:
        value = "--api-key" + ("=" + LITERAL.sub(atom, argument) if separator else "")
      elif separator and option in FLAGS:
        value = option + "=" + LITERAL.sub(atom, argument)
      elif separator and re.fullmatch(scenes.history.SECRET_KEY, option, re.I):
        value = "API_KEY=" + LITERAL.sub(atom, argument)
      else:
        prepared = re.sub(r"(?<![\w-])" + scenes.history.SECRET_KEY + r"(?=[\"']?\s*[:=])", "API_KEY", raw, flags=re.I)
        value = LITERAL.sub(atom, prepared)
      # 非 ASCII 字面标点也属于原始数据；语法只保留已知 ASCII 字符。
      value = "".join(c if ord(c) < 128 else "x" for c in value)
    replacements.append((start, end, value))
  result = command
  for start, end, value in reversed(replacements):
    result = result[:start] + value + result[end:]
  return result


def public_corpus(data):
  if not isinstance(data, dict) or set(data) != {"schemaVersion", "publication", "redactionVersion", "records", "statistics", "selection"} or type(data.get("schemaVersion")) is not int or data.get("schemaVersion") != 2 or data.get("redactionVersion") != 2 or data.get("publication") != "private-review-required":
    raise ValueError("invalid private source")
  rows = data.get("records")
  if not isinstance(rows, list) or len(rows) != data.get("selection", {}).get("scenarioCount"):
    raise ValueError("invalid source counts")
  groups = {}
  source_ids = set()
  scene_ids = set()
  for record in rows:
    if not isinstance(record, dict) or set(record) != {"id", "command", "sources", "occurrences", "scenario"} or not isinstance(record["command"], str) or record["id"] != hashlib.sha256(record["command"].encode()).hexdigest():
      raise ValueError("invalid source row")
    scene_id = record.get("scenario", {}).get("id")
    if record["id"] in source_ids or not isinstance(scene_id, str) or scene_id in scene_ids:
      raise ValueError("duplicate source scene")
    source_ids.add(record["id"])
    scene_ids.add(scene_id)
    command = rebuild(record["command"])
    expected = oracle.expected_parse(command)
    group = groups.get(command)
    if group is None:
      _, category, features = scenes.classify(command)
      group = {"id": hashlib.sha256(command.encode()).hexdigest(), "command": command, "category": category,
        "features": features, "representedScenarios": 0, "expected": expected, "expectedGate": oracle.expected_gate(command)}
      groups[command] = group
    group["representedScenarios"] += 1
  records = sorted(groups.values(), key=lambda r: r["id"])
  return {"schemaVersion": 1, "publication": "synthetic-public", "oracleVersion": 1, "records": records,
    "summary": {"inputScenarios": len(rows), "publicCases": len(records), "mergedRebuiltCases": len(rows)-len(records),
      "representedScenarios": sum(r["representedScenarios"] for r in records),
      "categories": dict(sorted(Counter(r["category"] for r in records).items())),
      "expectedComplete": sum(r["expected"]["status"] == "complete" for r in records),
      "expectedUnsupported": sum(r["expected"]["status"] == "unsupported" for r in records)}}


def public_destination(value):
  output = Path(value).absolute()
  boundary = ROOT / "tests/fixtures/omp/command-scenarios"
  if ".." in output.parts or not output.is_relative_to(boundary) or output.suffix != ".gz" or any(p.is_symlink() for p in output.parents):
    raise ValueError("invalid public output")
  return output


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--input", required=True)
  parser.add_argument("--output", required=True)
  args = parser.parse_args()
  try:
    source = Path(args.input)
    if source.stat().st_size > 64 * 1024 * 1024:
      raise ValueError("source too large")
    payload = source.read_bytes()
    if source.suffix == ".gz":
      with gzip.GzipFile(fileobj=io.BytesIO(payload)) as compressed:
        payload = compressed.read(64 * 1024 * 1024+1)
    if len(payload) > 64 * 1024 * 1024:
      raise ValueError("source too large")
    data = json.loads(payload)
    output = public_destination(args.output)
    result = public_corpus(data)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
    with output.open("xb") as stream:
      stream.write(gzip.compress(encoded, mtime=0))
    print(json.dumps(result["summary"]))
  except (OSError, ValueError, TypeError, KeyError):
    raise SystemExit("public corpus rebuild failed; no source text shown") from None


if __name__ == "__main__":
  main()
