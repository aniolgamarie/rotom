#!/usr/bin/env python3
"""只从显式实例解析冻结客户端；无 HOME 搜索、全局宿主或旧 runner fallback。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

sys.dont_write_bytecode = True


def private(path):
  path = Path(path).absolute()
  if path.resolve(strict=True) != path:
    raise ValueError()
  fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
  try:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid() or info.st_mode & 0o022:
      raise ValueError()
    with os.fdopen(fd, "rb", closefd=False) as stream:
      value = stream.read(16 * 1024 * 1024 + 1)
    if len(value) > 16 * 1024 * 1024:
      raise ValueError()
    return value
  finally:
    os.close(fd)


def main():
  args = list(sys.argv[1:])
  batch = "--batch-client" in args
  if batch: args.remove("--batch-client")
  if "--help" in args or "-h" in args:
    print("run-model.sh start|resume|status|cancel|poll|wait|probe --instance ABSOLUTE_INSTANCE [options]\n"
      "start: --backend pi|codex --mode review|investigate|implement --provider ID --model ID --cwd DIR --prompt-file FILE\n"
      "control: --run-id ID [--after CURSOR] [--wait-seconds 0..60]\n"
      "write: --allow-workspace-write --worktree-root DIR (requires explicit-write profile)\n"
      "display: --detach | --observe; all execution uses the frozen instance supervisor")
    return 0
  parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
  parser.add_argument("--instance", type=Path)
  selected, _ = parser.parse_known_args(args)
  instance = selected.instance
  if instance is None:
    source = Path(__file__).resolve()
    if source.parents[3].name != "pi-home":
      raise ValueError()
    instance = source.parents[4]
    args += ["--instance", str(instance)]
  instance = instance.absolute()
  bound = json.loads(private(instance / ".agentcfg-instance.json"))
  if bound.get("schema_version") != 1:
    raise ValueError()
  state = json.loads(private(Path(bound["state_root"]) / "deployment.json"))
  current = state["current"]
  if state["version"] != 1 or current["binding"] != bound["binding"]:
    raise ValueError()
  identity = current["launch"].get("runtime_identity", current["launch"]["lock_identity"])
  if not re.fullmatch(r"[a-f0-9]{64}", identity):
    raise ValueError()
  runtime = instance / "runtimes" / identity
  receipt = json.loads(private(runtime / ".agentcfg-receipt.json"))
  if receipt.get("identity") != identity or receipt.get("schema_version") != 1 or receipt.get("status") != "installed":
    raise ValueError()
  entry = "supervisor/scripts/model-delegate-batch.py" if batch else "supervisor/scripts/model-delegate.py"
  client = runtime / entry
  actual_sources = list((runtime / "supervisor").rglob("*"))
  if any(path.name == "__pycache__" or path.suffix == ".pyc" for path in actual_sources):
    raise ValueError()
  expected_python = {name for name in receipt["files"] if name.startswith("supervisor/") and name.endswith(".py")}
  if {path.relative_to(runtime).as_posix() for path in actual_sources if path.suffix == ".py"} != expected_python:
    raise ValueError()
  # 导入客户端前核对 Python 执行闭包；完整运行包校验由受信客户端复用 agentcfg 完成。
  for name, expected in receipt["files"].items():
    if name.startswith("supervisor/") and name.endswith(".py"):
      path = Path(name)
      if path.is_absolute() or ".." in path.parts or expected.get("kind") != "file":
        raise ValueError()
      if hashlib.sha256(private(runtime / path)).hexdigest() != expected["sha256"]:
        raise ValueError()
  if entry not in receipt["files"]:
    raise ValueError()
  locations = {item["name"]: item["literal"] for item in current["launch"]["environment"] if "literal" in item}
  python = Path(locations["AGENTCFG_REPOSITORY"]) / ".venv/bin/python"
  if not python.is_file():
    raise ValueError()
  os.execv(str(python), [str(python), "-B", "-I", str(client), *args])
  return 6


if __name__ == "__main__":
  try:
    sys.exit(main())
  except Exception:
    sys.stderr.write("DELEGATE_INSTANCE_OR_RUNTIME_UNAVAILABLE\n")
    sys.exit(5)
