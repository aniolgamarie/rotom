"""人工审阅步骤的合成替身：只向全新目标部署，不迁移认证。"""

import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest
import yaml

from agentcfg import commands, deployment, omp_dependencies, runtime
from agentcfg.omp_identity import native_identity
from agentcfg.omp_inventory import build_inventory, write_inventory
from agentcfg.storage import Conflict, Tree, ensure_private
from agentcfg.workspace import load_workspace
from test_omp_inventory import old_source
from test_omp_pipeline import full_workspace
from test_omp_runtime_foundation import clear_omp_identity_environment, isolate_runtime_discovery
from omp_fixtures import omp_native_home


def synthetic_sync(workspace, monkeypatch):
  content = b"synthetic standalone fixture, never executed\n"
  assets = {name: {"url": "https://example.invalid/" + name, "sha256": omp_dependencies.sha(content)}
    for name in omp_dependencies.ASSETS}
  monkeypatch.setattr(omp_dependencies, "ASSETS", assets)
  manifest_path = workspace.repository / "locks/omp/manifest.json"
  body = json.loads(manifest_path.read_bytes())
  body.pop("identity")
  body["assets"] = assets
  resources, packages, recipe = workspace.backend._resources(workspace.repository)
  body.update(resources=resources, packages=packages, recipe=recipe)
  manifest_path.write_bytes(deployment.json_bytes({"identity": omp_dependencies.sha(deployment.json_bytes(body)), **body}))
  lock = workspace.backend.read_lock(workspace.repository)
  with Tree(workspace.cache / "downloads", create=True) as cache:
    cache.write_new(omp_dependencies.sha(content), content)
  workspace.backend.sync(workspace, lock)
  return lock


def test_reviewed_inventory_deploys_complete_skill_into_new_environment_only(old_source, tmp_path, sentinel_factory, monkeypatch):
  workspace = full_workspace(tmp_path / "target")
  old = sentinel_factory(old_source)
  report, proposal, resources = build_inventory(old_source, adapter=workspace.adapter, data=workspace.resolved.data)
  assert all(item["disposition"] and item["reason"] for item in report["items"])
  result = write_inventory(workspace, old_source)
  # 此处模拟人工审阅：仅批准sample完整技能和已有动作，没有自动导入入口。
  candidate_root = Path(result["proposal"]) / "resources/skills/sample"
  approved = workspace.repository / "shared/skills/reviewed-sample"
  shutil.copytree(candidate_root, approved)
  for resource in resources:
    if resource["path"].startswith("skills/sample/"):
      (approved / resource["path"].removeprefix("skills/sample/")).chmod(0o700 if resource["executable"] else 0o600)
  (workspace.repository / "shared/reviewed.toml").write_text(
    'schema_version=1\n[skills.reviewed-sample]\npath="shared/skills/reviewed-sample"\n')
  proposal["overrides"]["profiles"][workspace.profile]["skills"] = ["reviewed-sample"]
  workspace = load_workspace(workspace.local_path, workspace.profile, repository=workspace.repository, proposal=proposal)
  lock = synthetic_sync(workspace, monkeypatch)
  assert not workspace.instance.exists()
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity), workspace.binding, runtime.record(workspace, lock))
  identity = native_identity(workspace.profile, workspace.instance)
  deployed = identity.agent_dir / "skills/reviewed-sample"
  assert (deployed / "SKILL.md").read_bytes() == (old_source / "skills/sample/SKILL.md").read_bytes()
  assert (deployed / "scripts/check.sh").stat().st_mode & 0o777 == 0o700
  assert not (identity.agent_dir / "auth.db").exists()
  assert not (identity.agent_dir / "sessions").exists()
  for path in workspace.state_root.rglob("*"):
    if path.is_file():
      assert b"SECRET_INVENTORY_947" not in path.read_bytes()
  old.assert_unchanged()


def test_full_fixture_synthetic_sync_apply_run_capture_and_noop(tmp_path, monkeypatch, fake_subprocess, capsys):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace = full_workspace(tmp_path)
  lock = synthetic_sync(workspace, monkeypatch)
  candidate = workspace.candidate(lock.identity)
  monkeypatch.setattr(commands, "workspace", lambda _: workspace)
  assert commands.cmd_apply(SimpleNamespace()) == 0
  state_path = workspace.state_root / "deployment.json"
  before = state_path.read_bytes()
  assert commands.cmd_apply(SimpleNamespace()) == 0
  assert state_path.read_bytes() == before
  cwd = tmp_path / "work"
  cwd.mkdir()
  fake_subprocess.queue(returncode=27)
  assert runtime.run(workspace, cwd=cwd) == 27
  assert fake_subprocess.calls[0]["argv"][-1] == "--no-title"
  assert len(fake_subprocess.calls[0]["pass_fds"]) == 3
  assert commands.cmd_capture(SimpleNamespace()) == 0
  assert (workspace.cache / "proposals/capture.json").exists()
  assert "rotom-smoke-not-a-secret" not in capsys.readouterr().out
  assert candidate.artifacts


def test_inventory_does_not_authorize_nonempty_target_takeover(old_source, tmp_path, sentinel_factory):
  workspace = full_workspace(tmp_path)
  write_inventory(workspace, old_source)
  ensure_private(workspace.instance)
  (workspace.instance / "foreign-auth").write_bytes(b"do-not-touch")
  sentinel = sentinel_factory(workspace.instance)
  with pytest.raises(Conflict):
    with workspace.adapter.apply_lifecycle_guard(workspace):
      pytest.fail("unowned nonempty instance accepted")
  sentinel.assert_unchanged()


def test_two_managed_profiles_keep_each_other_and_old_native_tools_unchanged(tmp_path, omp_native_home, monkeypatch, fake_subprocess, sentinel_factory):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace = full_workspace(tmp_path / "manager")
  other_profile = workspace.repository / "profiles/omp-secondary.toml"
  other_profile.write_text((workspace.repository / "profiles/omp-validation.toml").read_text().replace(
    'id = "omp-validation"', 'id = "omp-secondary"'))
  workspace = load_workspace(workspace.local_path, workspace.profile, repository=workspace.repository)
  other = load_workspace(workspace.local_path, "omp-secondary", repository=workspace.repository)
  lock = synthetic_sync(workspace, monkeypatch)
  for selected in (workspace, other):
    with selected.adapter.apply_lifecycle_guard(selected):
      deployment.apply(selected.instance, selected.state_root, selected.candidate(lock.identity), selected.binding, runtime.record(selected, lock))
  other_identity = native_identity(other.profile, other.instance)
  (other_identity.agent_dir / "auth.db").write_bytes(b"SECOND_PROFILE_AUTH_SENTINEL")
  (other_identity.agent_dir / "sessions").mkdir()
  (other_identity.agent_dir / "sessions/sentinel").write_bytes(b"SECOND_PROFILE_SESSION_SENTINEL")
  sentinels = [sentinel_factory(root) for root in (omp_native_home, other.instance, other.state_root, workspace.repository)]
  cwd = tmp_path / "work"
  cwd.mkdir()
  fake_subprocess.queue(returncode=0)
  assert runtime.run(workspace, cwd=cwd) == 0
  assert fake_subprocess.calls[0]["env"]["HOME"] != str(other_identity.home)
  for sentinel in sentinels:
    sentinel.assert_unchanged()


def test_reviewed_migration_pending_recovers_without_changing_old_source(old_source, tmp_path, sentinel_factory):
  workspace = full_workspace(tmp_path)
  write_inventory(workspace, old_source)
  sentinel = sentinel_factory(old_source)
  lock = workspace.backend.read_lock(workspace.repository)
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity), workspace.binding, runtime.record(workspace, lock))
  workspace.resolved.data["profile"]["agent_options"]["ui"]["keybindings"]["app.model.cycleForward"] = "Ctrl+O"
  candidate = workspace.candidate(lock.identity)
  with Tree(workspace.state_root) as state, Tree(workspace.instance) as target:
    old = deployment.read_state(state)
    plan = deployment.plan(target, old, candidate, workspace.binding, runtime.record(workspace, lock))
    after = {"version": 1, "current": plan.current,
      "previous": {"current": old["current"], "changes": plan.changes}, "owner": old["owner"]}
    state.write_state("pending.json", deployment.json_bytes({"after_state": after, "changes": plan.changes}))
    deployment.write_changes(target, plan.changes)
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, runtime.record(workspace, lock))
  assert not (workspace.state_root / "pending.json").exists()
  sentinel.assert_unchanged()
