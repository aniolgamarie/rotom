"""旧来源只生成提案，新实例显式采纳；默认不执行旧同步器或原生宿主。"""

import json
import pytest
from pathlib import Path

from agentcfg import cli, commands
from agentcfg.pi_inventory import build_inventory
from test_pi_inventory import native_home
from test_pi_pipeline import fixture_workspace

ROOT = Path(__file__).resolve().parents[1]


def test_old_home_proposal_and_new_instance_never_share_a_writer(tmp_path, monkeypatch, capsys, sentinel_factory):
  old = native_home(tmp_path)
  (old / "prompts/user-custom.md").write_text("keep custom source")
  (old / ".starter-sync-manifest.json").write_text("old manager sentinel")
  original = sentinel_factory(old)
  report = build_inventory(old, repository=ROOT)
  assert any(row["reason"] == "unmanaged-preserved" for row in report["items"])
  assert any(row["code"] == "legacy-manager-marker-preserved" for row in report["blockers"])
  local, w = fixture_workspace(tmp_path / "new", monkeypatch)
  args = ["--local", str(local)]
  assert cli.main([*args, "apply"]) == 0
  before = (w.state_root / "deployment.json").read_bytes()
  assert cli.main([*args, "apply"]) == 0
  assert json.loads(capsys.readouterr().out.splitlines()[-1])["changes"] == 0
  assert (w.state_root / "deployment.json").read_bytes() == before
  assert w.instance != old and not (w.instance / "pi-home/auth.json").exists()
  assert not (w.instance / "pi-home/prompts/user-custom.md").exists()
  original.assert_unchanged()
  # 命令行不存在可以绕过来源审阅的自动导入/执行旧同步器入口。
  with pytest.raises(SystemExit) as caught:
    cli.main([*args, "apply-import", str(old)])
  assert caught.value.code == 2
  original.assert_unchanged()


def test_unowned_native_file_and_symlink_refuse_takeover(tmp_path, monkeypatch, sentinel_factory):
  local, w = fixture_workspace(tmp_path, monkeypatch)
  home = w.instance / "pi-home"; home.mkdir(parents=True, mode=0o700)
  settings = home / "settings.json"; settings.write_text('{"theme":"user-owned"}'); settings.chmod(0o600)
  marker = sentinel_factory(home)
  assert cli.main(["--local", str(local), "apply"]) == 4
  marker.assert_unchanged()
  settings.unlink()
  outside = tmp_path / "outside.json"; outside.write_text('{"sentinel":true}')
  settings.symlink_to(outside)
  assert cli.main(["--local", str(local), "apply"]) == 4
  assert outside.read_text() == '{"sentinel":true}'


@pytest.mark.parametrize("kind", ["worker", "check", "codex", "external"])
def test_all_mutations_reject_owned_child_activity_after_parent_exit(tmp_path, monkeypatch, kind):
  from test_pi_activity import make_store, identity
  local, w = fixture_workspace(tmp_path, monkeypatch)
  args = ["--local", str(local)]
  assert cli.main([*args, "apply"]) == 0
  store, processes = make_store(tmp_path / "controller")
  store.root = w.state_root
  child = identity(201); processes.current[201] = child
  lease = store.allocate(kind=kind, execution_id="child", task_id=None, attempt_id="attempt", lock_identity="a" * 64,
    slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest=None, planned_workspaces=[])
  store.start(lease["lease_id"], store.owner, spawn=lambda _: child)
  processes.current.pop(101)  # 父控制者消失不能使子活动消失。
  before = (w.state_root / "deployment.json").read_bytes()
  for command in ("apply", "sync", "rollback"):
    assert cli.main([*args, command]) == 4
  assert (w.state_root / "deployment.json").read_bytes() == before
  assert processes.signals == []
