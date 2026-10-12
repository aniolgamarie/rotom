#!/usr/bin/env python3
"""显式重建两个全新 HOME；共享缓存需明确声明，不启动模型宿主。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--allow-install", action="store_true")
  parser.add_argument("--cache", required=True, type=Path, help="本任务专用下载缓存根，可共享")
  parser.add_argument("--evidence", required=True, type=Path)
  args = parser.parse_args()
  if not args.allow_install:
    parser.error("需要 --allow-install；此入口消费固定锁并执行真实安装器")
  repo = Path(__file__).resolve().parents[1]
  sys.path.insert(0, str(repo / "src"))
  from agentcfg import commands, dependencies, runtime_packages
  from agentcfg.storage import Tree, ensure_private
  from agentcfg.workspace import load_workspace
  lock = dependencies.read_lock(repo)
  evidence, shared = args.evidence.absolute(), args.cache.absolute()
  ensure_private(shared)
  evidence.mkdir(mode=0o700, parents=True, exist_ok=True)
  output = evidence / "result.json"
  if output.exists():
    parser.error("使用新的空证据目录")
  inherited_path = os.environ.get("PATH", "")
  cases = []
  result = {"kind": "two-fresh-homes-shared-download-cache", "lock_identity": lock.identity,
    "recipe": lock.metadata["recipe"], "platform": sys.platform, "overall": "FAIL"}
  try:
    for number in (1, 2):
      with tempfile.TemporaryDirectory(prefix="rotom-dsh-rebuild-", dir="/dev/shm") as directory:
        root = Path(directory)
        env = {"PATH": inherited_path, "HOME": str(root / "home"), "XDG_CONFIG_HOME": str(root / "config"),
          "XDG_DATA_HOME": str(root / "data"), "XDG_STATE_HOME": str(root / "state"),
          "XDG_CACHE_HOME": str(shared), "DSH_HOME": str(root / "unused-dsh"), "TMPDIR": str(root / "tmp")}
        for name, value in env.items():
          if name != "PATH":
            ensure_private(Path(value))
        os.environ.clear()
        os.environ.update(env)
        local = root / "machine.toml"
        local.write_text('schema_version=1\n[machine]\nid="rebuild-' + str(number) + '"\n')
        local.chmod(0o600)
        workspace = load_workspace(local, repository=repo)
        started = time.monotonic()
        first = workspace.backend.sync(workspace, lock)
        second = workspace.backend.sync(workspace, lock)
        candidate = workspace.candidate(lock.identity)
        commands.apply_candidate(workspace, lock, candidate)
        state = {path.name: path.read_bytes() for path in workspace.state_root.glob("*.json")}
        repeated = commands.apply_candidate(workspace, lock, candidate)
        assert repeated["changes"] == 0
        assert {path.name: path.read_bytes() for path in workspace.state_root.glob("*.json")} == state
        assert not (workspace.state_root / "pending.json").exists()
        with Tree(workspace.instance) as tree:
          assert workspace.adapter.capture_projection(tree)["theme"]["theme"] == "rotom-poimandres"
        status = runtime_packages.status(workspace.backend.root(workspace, lock.identity), lock.identity)
        assert first["changed"] and not second["changed"] and status == "installed"
        case = {"home": number, "fresh": True, "shared_download_cache": True,
          "candidate_digest": candidate.generation, "seconds": round(time.monotonic() - started, 2),
          "sync": first, "repeat_sync": second, "repeat_apply_changes": repeated["changes"], "status": status}
        cases.append(case)
        print(json.dumps(case), flush=True)
    result["overall"] = "PASS"
  except Exception:
    # 不输出未知原生异常正文，失败详情保留在脱敏安装器日志中。
    result["error"] = "REBUILD_OR_IDEMPOTENCE_FAILED"
  source = {name: hashlib.sha256((repo / name).read_bytes()).hexdigest() for name in
    ("scripts/smoke-dsh-rebuild.py", "src/agentcfg/dependencies.py", "src/agentcfg/dsh.py", "src/agentcfg/deployment.py")}
  result.update(cases=cases, source_files=source)
  output.write_text(json.dumps(result, indent=2) + "\n")
  print(json.dumps({"overall": result["overall"], "evidence": str(evidence)}))
  return 0 if result["overall"] == "PASS" else 1


if __name__ == "__main__":
  raise SystemExit(main())
