"""旧状态原位保留，新Base显式部署；不读历史正文或启动宿主。"""

import json
from pathlib import Path

import pytest

from agentcfg import cli, commands, run_owners
from agentcfg.pi_inventory import build_inventory
from agentcfg.pi_lifecycle import guard
from agentcfg.storage import Conflict
from test_pi_inventory import native_home
from test_pi_reboot_pipeline import pipeline, prepare
from test_pi_reboot_dependencies import fake_npm, recipe_repository


ROOT = Path(__file__).resolve().parents[1]


def test_old_home_proposal_and_new_instance_never_share_a_writer(pipeline, tmp_path, sentinel_factory):
  old = native_home(tmp_path)
  (old / ".starter-sync-manifest.json").write_text("opaque old manager sentinel")
  original = sentinel_factory(old)
  report = build_inventory(old, repository=ROOT)
  assert report["proposed_overrides"] == {}
  assert any(row["code"] == "legacy-manager-marker-preserved" for row in report["blockers"])
  workspace, backend, lock, _, launched = pipeline
  prepare(workspace, backend, lock)
  before = (workspace.state_root / "deployment.json").read_bytes()
  result = commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  assert result["changes"] == 0
  assert (workspace.state_root / "deployment.json").read_bytes() == before
  assert workspace.instance != old and not (workspace.instance / "pi-home/auth.json").exists()
  assert not (workspace.instance / "pi-home/prompts/private-name.md").exists()
  assert not launched
  original.assert_unchanged()


def test_unowned_native_file_and_symlink_refuse_takeover(pipeline, tmp_path, sentinel_factory):
  workspace, _, lock, _, launched = pipeline
  home = workspace.instance / "pi-home"
  home.mkdir(parents=True, mode=0o700)
  settings = home / "settings.json"
  settings.write_text('{"theme":"user-owned"}')
  settings.chmod(0o600)
  marker = sentinel_factory(home)
  with pytest.raises(Conflict): commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  marker.assert_unchanged()
  settings.unlink()
  outside = tmp_path / "outside.json"
  outside.write_text('{"sentinel":true}')
  settings.symlink_to(outside)
  with pytest.raises(Conflict): commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  assert outside.read_text() == '{"sentinel":true}' and not launched


@pytest.mark.parametrize("unknown", [False, True])
def test_active_or_unknown_main_blocks_configuration_and_dependency_maintenance(pipeline, unknown):
  workspace, backend, lock, _, launched = pipeline
  prepare(workspace, backend, lock)
  identity = {"pid": 1234, "birth_id": "synthetic-boot:987"}
  owners = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  with guard(workspace, shared=True, create=False):
    run = owners.register(identity)
    if unknown: owners.mark_unknown(run, identity)
  before = (workspace.state_root / "deployment.json").read_bytes()
  with pytest.raises(Conflict): commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  with pytest.raises(Conflict): backend.sync(workspace, lock)
  assert (workspace.state_root / "deployment.json").read_bytes() == before
  assert owners.snapshot()[run]["state"] == ("unknown" if unknown else "active")
  assert not launched
