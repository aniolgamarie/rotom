"""临时旧配置与真实部署的迁移验收；运行期变更只调用正式 CLI。"""
import json
import subprocess
import sys

from .deployment import apply
from .pi_host import HostSupervisor
from .pi_inventory import build_inventory
from .pi_lifecycle import guard
from .runtime import record
from .storage import Conflict, Tree


def prepare_migration_probe(fixture, runtime):
  workspace = fixture["workspace"]
  root = fixture["fixture_root"]
  old = root / "old-pi-home"
  originals = {"settings.json": b'{"theme":"custom-native-fixture"}\n',
    "auth.json": b'{"synthetic":"never-import-this-fixture"}\n',
    ".starter-sync-manifest.json": b'{"synthetic":true}\n',
    "prompts/user-custom.md": b"Keep the original custom prompt.\n"}
  with Tree(old, create=True) as tree:
    for name, content in originals.items(): tree.write_new(name, content)
  inventory = build_inventory(old, repository=workspace.repository)
  if not any(row["code"] == "legacy-manager-marker-preserved" for row in inventory["blockers"]):
    raise Conflict("PI_NATIVE_LEGACY_MARKER_UNVERIFIED")
  candidate = workspace.candidate(runtime.lock_identity)
  launch = record(workspace, workspace.backend.read_lock(workspace.repository))
  occupied = root / "unowned-instance"
  with Tree(occupied, create=True) as tree: tree.write_new("pi-home/settings.json", b'{"theme":"unowned"}')
  try: apply(occupied, root / "unowned-state", candidate, workspace.binding, launch)
  except Conflict: pass
  else: raise Conflict("PI_NATIVE_OWNERSHIP_CONFLICT_MISSING")
  with Tree(occupied) as tree:
    if tree.read("pi-home/settings.json")[0] != b'{"theme":"unowned"}': raise Conflict("PI_NATIVE_UNOWNED_CHANGED")
  return {"old": old, "originals": originals, "candidate": candidate, "launch": launch}


class MigrationConflictSupervisor(HostSupervisor):
  def __init__(self, config, *, lease_fd, fixture, model_started):
    super().__init__(config, lease_fd=lease_fd)
    self.fixture = fixture
    self.model_started = model_started
    self.conflict_results = []

  def poll(self):
    super().poll()
    if self.conflict_results or self.host_exit is not None or not self.model_started(): return
    workspace = self.fixture["workspace"]
    entry = "import sys;sys.path.insert(0,sys.argv.pop(1));from agentcfg.cli import main;raise SystemExit(main())"
    for action in ("apply", "sync", "rollback"):
      result = subprocess.run([sys.executable, "-B", "-I", "-c", entry, str(workspace.repository / "src"),
        "--local", str(workspace.local_path), "--profile", workspace.resolved.data["profile"]["id"], action],
        cwd=self.fixture["project"], env=self.fixture["environment"], capture_output=True, timeout=15)
      # 不保存 CLI 正文；退出码足以验证活动冲突，避免将本地配置写入证据。
      self.conflict_results.append({"action": action, "exit_code": result.returncode})


def finish_migration_probe(fixture, probe, supervisor):
  expected = [{"action": action, "exit_code": 4} for action in ("apply", "sync", "rollback")]
  if supervisor.conflict_results != expected: raise Conflict("PI_NATIVE_ACTIVE_CONFLICT_MISSING")
  with Tree(probe["old"]) as tree:
    if any(tree.read(name)[0] != content for name, content in probe["originals"].items()): raise Conflict("PI_NATIVE_OLD_HOME_CHANGED")
  workspace = fixture["workspace"]
  with Tree(workspace.state_root) as tree: before = tree.read("deployment.json")
  with guard(workspace): result = apply(workspace.instance, workspace.state_root, probe["candidate"], workspace.binding, probe["launch"])
  with Tree(workspace.state_root) as tree: unchanged = before == tree.read("deployment.json")
  # SDK 可以初始化空 auth 存储；空对象不代表从旧 HOME 导入账号。
  with Tree(workspace.instance) as tree: auth = tree.read("pi-home/auth.json")
  if result["changes"] != 0 or not unchanged or auth is not None and json.loads(auth[0]) != {}:
    raise Conflict("PI_NATIVE_MIGRATION_IDEMPOTENCE")
  return {"active_mutations_rejected": True, "unowned_file_preserved": True, "old_home_preserved": True,
    "legacy_marker_detected": True, "apply_idempotent": True, "credentials_not_imported": True}
