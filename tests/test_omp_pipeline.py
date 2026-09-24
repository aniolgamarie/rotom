from pathlib import Path
import json
import shutil
from types import SimpleNamespace

import pytest

from agentcfg.omp import OmpAdapter, classify_operation
from agentcfg import runtime
from agentcfg import deployment
from agentcfg import commands
from agentcfg.omp_identity import native_identity
from agentcfg.render import RenderCandidate
from agentcfg.storage import Conflict, Tree
from agentcfg.workspace import load_workspace
from agentcfg.commands import current_plan
from agentcfg.omp_dependencies import OmpBackend, sha

from test_omp_adapter import REPO, omp_data
from test_omp_runtime_foundation import clear_omp_identity_environment, isolate_runtime_discovery, runtime_workspace


def full_workspace(tmp_path):
  repository = tmp_path / "repository"
  for name in ("shared", "profiles"):
    shutil.copytree(REPO / name, repository / name)
  shutil.copytree(REPO / "agents/omp", repository / "agents/omp")
  for agent in ("dsh", "pi"):
    target = repository / "agents" / agent
    target.mkdir(parents=True)
    for name in ("agent.toml", "bindings.toml", "plugins.toml"):
      shutil.copy2(REPO / "agents" / agent / name, target / name)
    if (REPO / "agents" / agent / "content.toml").exists():
      shutil.copy2(REPO / "agents" / agent / "content.toml", target / "content.toml")
  shutil.copytree(REPO / "locks/omp", repository / "locks/omp")
  shutil.copytree(REPO / "tests/fixtures/omp", repository / "tests/fixtures/omp")
  shutil.copy2(repository / "tests/fixtures/omp/registry.toml", repository / "shared/omp-validation.toml")
  shutil.copy2(repository / "tests/fixtures/omp/profiles/omp-validation.toml",
    repository / "profiles/omp-validation.toml")
  # 临时验收仓库新增profile后显式形成独立合成锁；不冒充正式锁或真实资产证据。
  manifest_path = repository / "locks/omp/manifest.json"
  manifest = json.loads(manifest_path.read_bytes())
  resources, packages, recipe = OmpBackend()._resources(repository)
  body = {key: value for key, value in manifest.items() if key != "identity"}
  body.update(resources=resources, packages=packages, recipe=recipe)
  manifest_path.write_bytes(deployment.json_bytes({"identity": sha(deployment.json_bytes(body)), **body}))
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  local = private / "local.toml"
  local.write_text('schema_version=1\n[machine]\nid="test"\ndefault_profile="omp-validation"\n'
    f'[machine.paths]\ninstances_root="{private / "instances"}"\nstate_root="{private / "state"}"\ncache_root="{private / "cache"}"\n'
    '[secrets]\nomp_smoke_placeholder="rotom-smoke-not-a-secret"\n')
  local.chmod(0o600)
  return load_workspace(local, "omp-validation", repository=repository)


def test_normal_session_adds_no_title_but_information_operations_are_neutral():
  adapter = OmpAdapter(REPO)
  data = omp_data()
  ordinary = adapter.launch_spec(data, cwd=Path("/work"), runtime_root=Path("/runtime"),
    instance_root=Path("/instance"), lock_identity="lock")
  assert ordinary.argv[-1] != "--no-title"
  assert adapter.operation_arguments(()) == ("--no-title",)
  assert adapter.operation_arguments(("--help",)) == ("--help",)
  assert adapter.operation_arguments(("--version",)) == ("--version",)
  assert adapter.operation_arguments(("--provider", "gateway", "--", "--help", "--no-title")) == (
    "--no-title", "--provider", "gateway", "--", "--help", "--no-title")
  assert classify_operation(("--provider", "gateway", "--", "--help")) == "session"


def test_default_doctor_is_static_and_reports_identity_source_and_login_scope():
  report = OmpAdapter(REPO).doctor({})
  assert set(report) >= {"native-auth-is-profile-scoped", "project-discovery-denied-by-default"}


def test_default_doctor_does_not_spawn_read_auth_or_open_network(tmp_path, monkeypatch, capsys):
  workspace, lock = runtime_workspace(tmp_path)
  workspace.agent = "omp"
  lock.metadata = {}
  identity = native_identity(workspace.profile, workspace.instance)
  auth = identity.agent_dir / "auth.json"
  auth.write_text("SECRET_SENTINEL")
  workspace.backend.read_lock = lambda repository: lock
  workspace.backend.toolchain = lambda selected: []
  workspace.candidate = lambda lock_identity: RenderCandidate("generation", workspace.adapter.render(workspace.resolved.data))
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("doctor spawned")))
  monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("doctor network")))
  assert commands.cmd_doctor(SimpleNamespace(live=False)) == 0
  assert auth.read_text() == "SECRET_SENTINEL"
  assert "SECRET_SENTINEL" not in capsys.readouterr().out


def test_information_operation_uses_neutral_home_without_session_argument(tmp_path, monkeypatch, fake_subprocess):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  workspace, _ = runtime_workspace(tmp_path)
  cwd = tmp_path / "project"
  cwd.mkdir()
  (cwd / ".env").write_text("must-not-be-read")
  fake_subprocess.queue(returncode=0)
  assert runtime.run(workspace, cwd=cwd, arguments=("--help",)) == 0
  call = fake_subprocess.calls[0]
  assert call["argv"][-1] == "--help" and "--no-title" not in call["argv"]
  assert call["cwd"] == native_identity(workspace.profile, workspace.instance).home


def test_repeated_apply_preserves_unmanaged_native_field_without_state_rotation(tmp_path):
  workspace, lock = runtime_workspace(tmp_path)
  identity = native_identity(workspace.profile, workspace.instance)
  config = identity.agent_dir / "config.yml"
  original = config.read_text()
  config.write_text(original + "nativePreference: keep\n")
  before_target = config.read_bytes()
  state_path = workspace.state_root / "deployment.json"
  before_state = state_path.read_bytes()
  candidate = RenderCandidate("generation", workspace.adapter.render(workspace.resolved.data))
  result = deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding,
    runtime.record(workspace, lock))
  assert not result["drift"] and not result["conflicts"]
  assert config.read_bytes() == before_target
  assert state_path.read_bytes() == before_state


def test_full_fixture_validate_render_and_plan_need_no_owner_or_installed_package(tmp_path):
  workspace = full_workspace(tmp_path)
  lock = workspace.backend.read_lock(workspace.repository)
  candidate = workspace.candidate(lock.identity)
  runtime_root = workspace.backend.root(workspace, runtime.runtime_identity(workspace, lock))
  assert candidate.artifacts and not workspace.instance.exists() and not runtime_root.exists()
  plan = current_plan(workspace, lock, candidate)
  assert plan.changes and not plan.conflicts
  assert not workspace.instance.exists() and not runtime_root.exists()


def test_owner_initialization_interruption_is_reusable_for_first_apply(tmp_path):
  workspace, lock = runtime_workspace(tmp_path)
  fresh = SimpleNamespace(**vars(workspace))
  fresh.instance = tmp_path / "fresh/instance"
  fresh.state_root = tmp_path / "fresh/state"
  with pytest.raises(RuntimeError):
    with workspace.adapter.apply_lifecycle_guard(fresh):
      raise RuntimeError("synthetic interruption")
  assert (fresh.instance / ".agentcfg-omp-owner.json").is_file()
  candidate = RenderCandidate("generation", fresh.adapter.render(fresh.resolved.data))
  with fresh.adapter.apply_lifecycle_guard(fresh):
    deployment.apply(fresh.instance, fresh.state_root, candidate, fresh.binding, runtime.record(fresh, lock))
  assert (fresh.state_root / "deployment.json").is_file()


def test_omp_managed_conflict_and_rollback_consume_backup_without_auth_changes(tmp_path):
  workspace, lock = runtime_workspace(tmp_path)
  original = workspace.adapter.render(workspace.resolved.data)
  changed = tuple(type(item)(item.target, b"false" if item.target.selector == "/skills/enablePiUser" else item.content,
    item.mode) for item in original)
  candidate = RenderCandidate("changed", changed)
  deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, runtime.record(workspace, lock))
  identity = native_identity(workspace.profile, workspace.instance)
  auth = identity.agent_dir / "auth.json"
  auth.write_text("SECRET_SENTINEL")
  deployment.rollback(workspace.instance, workspace.state_root, workspace.binding)
  assert auth.read_text() == "SECRET_SENTINEL"
  state = json.loads((workspace.state_root / "deployment.json").read_bytes())
  assert state["previous"] is None
  with pytest.raises(Conflict):
    deployment.rollback(workspace.instance, workspace.state_root, workspace.binding)


def test_omp_apply_pending_recovery_finishes_without_touching_unmanaged_data(tmp_path):
  workspace, lock = runtime_workspace(tmp_path)
  original = workspace.adapter.render(workspace.resolved.data)
  changed = tuple(type(item)(item.target, b"false" if item.target.selector == "/skills/enablePiUser" else item.content,
    item.mode) for item in original)
  candidate = RenderCandidate("pending-change", changed)
  identity = native_identity(workspace.profile, workspace.instance)
  session = identity.agent_dir / "session.json"
  session.write_text("SECRET_SENTINEL")
  with Tree(workspace.state_root) as state, Tree(workspace.instance) as target:
    old = deployment.read_state(state)
    planned = deployment.plan(target, old, candidate, workspace.binding, runtime.record(workspace, lock))
    after = {"version": 1, "current": planned.current,
      "previous": {"current": old["current"], "changes": planned.changes}, "owner": old["owner"]}
    state.write_state("pending.json", deployment.json_bytes({"after_state": after, "changes": planned.changes}))
    deployment.write_changes(target, planned.changes)
  deployment.apply(workspace.instance, workspace.state_root, candidate, workspace.binding, runtime.record(workspace, lock))
  assert not (workspace.state_root / "pending.json").exists()
  assert session.read_text() == "SECRET_SENTINEL"


def test_omp_committed_rollback_pending_is_recovered_and_backup_stays_consumed(tmp_path):
  workspace, lock = runtime_workspace(tmp_path)
  original = workspace.adapter.render(workspace.resolved.data)
  changed = tuple(type(item)(item.target, b"false" if item.target.selector == "/skills/enablePiUser" else item.content,
    item.mode) for item in original)
  deployment.apply(workspace.instance, workspace.state_root, RenderCandidate("changed", changed),
    workspace.binding, runtime.record(workspace, lock))
  identity = native_identity(workspace.profile, workspace.instance)
  session = identity.agent_dir / "session.json"
  session.write_text("SECRET_SENTINEL")
  with Tree(workspace.state_root) as state, Tree(workspace.instance) as target:
    old = deployment.read_state(state)
    backup = old["previous"]
    changes = [deployment.reverse_change(change) for change in backup["changes"]]
    after = {"version": 1, "current": backup["current"], "previous": None, "owner": old["owner"]}
    state.write_state("pending.json", deployment.json_bytes({"after_state": after, "changes": changes}))
    deployment.write_changes(target, changes)
    state.write_state("deployment.json", deployment.json_bytes(after))
  with pytest.raises(Conflict, match="没有上一版"):
    deployment.rollback(workspace.instance, workspace.state_root, workspace.binding)
  assert not (workspace.state_root / "pending.json").exists()
  assert session.read_text() == "SECRET_SENTINEL"
