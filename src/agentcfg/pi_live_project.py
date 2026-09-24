"""实网工作流专用小项目；必须创建新路径，不把业务仓库改成测试夹具。"""
import hashlib
import os
from pathlib import Path
import secrets
import re
import shutil
import tempfile

from .deployment import json_bytes
from .process import checked, DependencyError
from .storage import Conflict, Tree, ensure_private


FILES = {"code.txt": b"changed\n", "test_live_fixture.py": b'from pathlib import Path\n\ndef test_live_fix():\n  assert Path("code.txt").read_text() == "changed\\n"\n'}


def prepare_project(root, *, run=checked, git=None):
  root = Path(root).absolute()
  if root.exists() or root.is_symlink(): raise Conflict("PI_LIVE_PROJECT_EXISTS")
  git = git or shutil.which("git")
  if not git: raise DependencyError("实网测试项目需要 Git")
  ensure_private(root)
  marker = {"schema_version": 1, "kind": "agentcfg-live-managed", "nonce": secrets.token_hex(32),
    "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in FILES.items()}}
  with Tree(root) as tree:
    for name, raw in FILES.items(): tree.write_new(name, raw)
    tree.write_new("agentcfg-live-project.json", json_bytes(marker))
  with tempfile.TemporaryDirectory(prefix="agentcfg-live-git-home-") as home:
    env = {"HOME": home, "PATH": os.defpath, "LANG": "C.UTF-8", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
    base = [git, "-c", "core.hooksPath=/dev/null", "-c", "init.templateDir="]
    for command in (["init", "--initial-branch=main", "--object-format=sha1"], ["add", "--", *FILES, "agentcfg-live-project.json"],
        ["-c", "user.name=agentcfg live fixture", "-c", "user.email=live@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "live acceptance fixture"]):
      run([*base, *command], cwd=root, env=env)
  return {"schema_version": 1, "status": "prepared", "kind": "live-project", "project": str(root), "model_calls": 0}


def inspect_project(root):
  import json
  root = Path(root).absolute()
  with Tree(root) as tree:
    raw = tree.read("agentcfg-live-project.json")
    if raw is None: raise Conflict("PI_LIVE_PROBE_PROJECT_REQUIRED")
    marker = json.loads(raw[0])
    if (set(marker) != {"schema_version", "kind", "nonce", "files"} or type(marker["schema_version"]) is not int or marker["schema_version"] != 1
        or not isinstance(marker["nonce"], str) or not re.fullmatch("[a-f0-9]{64}", marker["nonce"])
        or marker["kind"] != "agentcfg-live-managed" or marker["files"] != {name: hashlib.sha256(data).hexdigest() for name, data in FILES.items()}):
      raise Conflict("PI_LIVE_PROBE_PROJECT_REQUIRED")
    for name, wanted in FILES.items():
      present = tree.read(name)
      if present is None or present[0] != wanted: raise Conflict("PI_LIVE_PROBE_PROJECT_CHANGED")
  if {path.name for path in root.iterdir()} != {".git", "agentcfg-live-project.json", *FILES}: raise Conflict("PI_LIVE_PROBE_PROJECT_CHANGED")
  return marker
