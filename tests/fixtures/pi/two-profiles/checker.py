"""只读日常oracle；仅匹配未来受管父侧采集的合成observations。

不启动工具、不写产物。JSON及其identity不能自证真实执行、隔离或终止。
"""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import sys

HERE = Path(__file__).resolve().parent
MAX_JSON_BYTES = 512 * 1024
MAX_TEXT_BYTES = 8192
SCENARIO = "daily-mvcc-boundary-v1"
# 固定预期位于项目写范围之外，不接受程序或模型自报pass。
CASES = (
  (7, 0, b"missing\n"), (7, 1, b"missing\n"), (7, 2, b"value=11\n"),
  (7, 3, b"value=11\n"), (7, 4, b"value=11\n"), (7, 5, b"value=22\n"),
  (7, 8, b"value=22\n"), (7, 9, b"missing\n"), (7, 10, b"missing\n"),
  (9, 2, b"missing\n"), (9, 3, b"value=90\n"), (9, 6, b"value=90\n"),
  (9, 7, b"value=99\n"), (11, 4, b"missing\n"), (11, 5, b"value=110\n"),
  (404, 100, b"missing\n"),
)


def invalid():
  raise ValueError("DAILY_OBSERVATION_INVALID")


def closed(value, keys):
  if type(value) is not dict or set(value) != set(keys): invalid()


def text(value, *, required=False):
  if type(value) is not str or required and not value: invalid()
  try:
    if len(value.encode("utf8")) > MAX_TEXT_BYTES: invalid()
  except UnicodeError: invalid()
  return value


def snapshot(info):
  return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def bounded_bytes(path, limit):
  fd = None
  try:
    if type(limit) is not int or not 1 <= limit <= MAX_JSON_BYTES: invalid()
    info = Path(path).lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_size > limit: invalid()
    # 检查和open之间若被换为FIFO，也不能等待writer而无限阻塞。
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    if snapshot(os.fstat(fd)) != snapshot(info): invalid()
    parts, count = [], 0
    while count <= limit:
      part = os.read(fd, min(65536, limit + 1 - count))
      if not part: break
      count += len(part); parts.append(part)
    if count > limit or count != info.st_size or snapshot(os.fstat(fd)) != snapshot(info): invalid()
    return b"".join(parts)
  except Exception:
    invalid()
  finally:
    if fd is not None: os.close(fd)


def object_pairs(pairs):
  result = {}
  for key, value in pairs:
    if key in result: invalid()
    result[key] = value
  return result


def parsed(path, limit):
  try:
    return json.loads(bounded_bytes(path, limit), object_pairs_hook=object_pairs, parse_constant=lambda _: invalid())
  except Exception: invalid()


def record(value, kind, keys=()):
  closed(value, ("kind", "exit_code", "stdout", "stderr", *keys))
  if value["kind"] != kind or type(value["exit_code"]) is not int or value["exit_code"] != 0: invalid()
  text(value["stdout"], required=kind in ("program", "shell")); text(value["stderr"])


def verify_observations(value, *, expected_input_identity):
  try:
    closed(value, ("schema_version", "scenario_id", "case", "input_identity", "records", "files"))
    if type(expected_input_identity) is not str or re.fullmatch("[0-9a-f]{64}", expected_input_identity) is None: invalid()
    if type(value["schema_version"]) is not int or value["schema_version"] != 2 or value["scenario_id"] != SCENARIO:
      invalid()
    if value["input_identity"] != expected_input_identity or value["case"] not in ("cpp", "shell", "editor"):
      invalid()
    case = value["case"]; records = value["records"]; failures = []
    if type(records) is not list: invalid()
    if case == "cpp":
      closed(value["files"], ())
      if len(records) != 1 + len(CASES): invalid()
      record(records[0], "compiler")
      expected = {(key, timestamp): body.decode("ascii") for key, timestamp, body in CASES}
      seen = set()
      for row in records[1:]:
        record(row, "program", ("key", "snapshot"))
        if type(row["key"]) is not int or type(row["snapshot"]) is not int: invalid()
        pair = (row["key"], row["snapshot"])
        if pair not in expected or pair in seen: invalid()
        seen.add(pair)
        if row["stdout"] != expected[pair]: failures.append({"key": pair[0], "snapshot": pair[1]})
      if seen != set(expected): invalid()
      checks = len(CASES)
    else:
      if len(records) != 1: invalid()
      record(records[0], case)
      name = "shell-lines.txt" if case == "shell" else "editor-note.txt"
      closed(value["files"], (name,))
      content = text(value["files"][name], required=True)
      expected = "alpha\nbeta\ngamma\n" if case == "shell" else "visibility: checked\nboundary: inclusive\n"
      if content != expected: failures.append({"file": name})
      if case == "shell" and records[0]["stdout"] != expected: failures.append({"stream": "stdout"})
      checks = 2 if case == "shell" else 1
    return {"case": case, "result": "mismatch" if failures else "matched", "checks": checks, "failures": failures}
  except Exception: invalid()


def load_observations(path, *, expected_input_identity):
  return verify_observations(parsed(path, MAX_JSON_BYTES), expected_input_identity=expected_input_identity)


def project_path(raw):
  path = Path(raw)
  if not path.is_absolute() or str(path) != raw or ".." in path.parts or path == Path("/tmp") or not path.is_relative_to("/tmp"):
    invalid()
  for ancestor in reversed((path, *path.parents)):
    if not stat.S_ISDIR(ancestor.lstat().st_mode): invalid()
  if path.stat().st_uid != os.getuid() or path.stat().st_mode & 0o777 != 0o700 or HERE.is_relative_to(path): invalid()
  return path


def static(root):
  document = parsed(HERE / "scenario.json", 65536)
  closed(document, ("schema_version", "scenario_id", "checks", "profiles", "platform", "editable", "readonly_oracle", "cpp", "shell", "editor", "execution", "native", "live"))
  if type(document["schema_version"]) is not int or document["schema_version"] != 1 or document["scenario_id"] != SCENARIO:
    invalid()
  if any(document[key] != "not-run" for key in ("execution", "native", "live")) or document["cpp"]["minimum_checks"] != len(CASES): invalid()
  if not bounded_bytes(root / "main.cpp", 65536) or not bounded_bytes(root / "editor-note.txt", 65536): invalid()
  return {"scenario_id": SCENARIO, "result": "not-run", "checks": 0, "layer": "static"}


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument("--project-root", required=True)
  parser.add_argument("--observations")
  parser.add_argument("--expected-input-identity")
  args = parser.parse_args()
  try:
    root = project_path(args.project_root)
    result = static(root)
    if bool(args.observations) != bool(args.expected_input_identity): invalid()
    if args.observations:
      # checker在写根外；输入identity来自可信父侧冻结输入，不取自JSON本身。
      result = load_observations(args.observations, expected_input_identity=args.expected_input_identity)
    print(json.dumps(result, sort_keys=True))
    return 1 if result["result"] == "mismatch" else 0
  except Exception:
    print("DAILY_OBSERVATION_INVALID", file=sys.stderr)
    return 5


if __name__ == "__main__":
  raise SystemExit(main())
