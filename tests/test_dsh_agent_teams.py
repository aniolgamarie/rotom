"""显式 Teams 组合与受管开关恢复；全部使用虚构运行包，不启动宿主。"""

import json
from pathlib import Path
import tomllib

import pytest

from agentcfg import commands, deployment, native, profile_runtime, runtime as launching
from agentcfg.dependencies import read_lock
from agentcfg.dsh_optional import TEAM_BUNDLE, TEAM_SELECTION_FILE
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree, instance_lock
from agentcfg.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[1]


def local(tmp_path, enabled=False):
  defaults = tomllib.loads((ROOT / "agents/dsh/agent.toml").read_text())["defaults"]
  plugins = [*defaults["plugins"], *(["agent-teams"] if enabled else [])]
  path = tmp_path / "local.toml"
  path.write_text('schema_version=1\n[machine]\nid="team-fixture"\n'
    '[overrides.profiles.dsh-default]\nplugins=' + json.dumps(plugins) + "\n")
  path.chmod(0o600)
  return path


def bundles(profile):
  return json.loads((profile / "package.json").read_bytes())["dsh"]["profile"]["bundles"]


def applied(tmp_path, prepared_runtime):
  path = local(tmp_path)
  workspace = load_workspace(path)
  lock = read_lock(ROOT)
  runtime = prepared_runtime(workspace, lock)
  commands.apply_candidate(workspace, lock, workspace.candidate(lock.identity))
  return path, workspace, lock, runtime


@pytest.mark.parametrize("enabled", [False, True])
def test_team_selection_is_explicit_and_managed(tmp_path, enabled):
  workspace = load_workspace(local(tmp_path, enabled))
  data = workspace.resolved.data
  assert ("agent-teams" in data["plugins"]) is enabled
  projections, selected = profile_runtime.profile_layout(workspace)
  assert TEAM_BUNDLE in projections
  assert (TEAM_BUNDLE in selected) is enabled
  if enabled:
    assert data["plugins"]["agent-teams"]["requires"] == ["tui"]
  candidate = workspace.candidate("synthetic-lock")
  artifact = next(a for a in candidate.artifacts if a.target.path == TEAM_SELECTION_FILE)
  assert json.loads(artifact.content) == {"schema_version": 1, "agent_teams": enabled}
  assert workspace.adapter.runtime_guards(data) == {"files": [TEAM_SELECTION_FILE], "roots": []}
  # 官方 bundle 本身提供行与生命周期；不在受管补丁中重复插入第二套 service。
  patch = native.load(next(a.content for a in candidate.artifacts if a.target.path == "dsh-home/agentcfg.patch.yml"))
  assert not any(row.get("id") in {"agent-team", "tool-agent-team", "ui-agent-team"}
    for operation in patch for row in operation.get("insert", []))


def test_teams_rejected_for_headless_ssh(tmp_path):
  workspace = load_workspace(local(tmp_path, True))
  data = workspace.resolved.data
  data["profile"]["agent_options"].update(execution="ssh", auto_review=False)
  with pytest.raises(ConfigError, match="dsh-ssh-headless-only"):
    workspace.adapter.validate(data)


def test_deployed_selection_controls_prepare_run_and_rollback(tmp_path, prepared_runtime):
  path, off, lock, runtime = applied(tmp_path, prepared_runtime)
  profile = profile_runtime.verify(off, runtime)
  assert TEAM_BUNDLE not in bundles(profile)
  native_sentinel = profile / "synthetic-native-session.txt"
  native_sentinel.write_text("synthetic native state")
  local(tmp_path, True)
  on = load_workspace(path)
  # 未 apply 的机器开关不能提前改变运行组合。
  profile_runtime.prepare(on, runtime)
  assert TEAM_BUNDLE not in bundles(profile)
  commands.apply_candidate(on, lock, on.candidate(lock.identity))
  assert TEAM_BUNDLE in bundles(profile)
  assert profile_runtime.verify(on, runtime) == profile
  local(tmp_path, False)
  changed_not_applied = load_workspace(path)
  assert profile_runtime.verify(changed_not_applied, runtime) == profile
  assert TEAM_BUNDLE in bundles(profile)
  with on.adapter.lifecycle_guard(on):
    deployment.rollback(on.instance, on.state_root, on.binding,
      prepare=lambda launch: commands.prepare_launch(on, launch))
  assert TEAM_BUNDLE not in bundles(profile)
  assert json.loads((on.instance / TEAM_SELECTION_FILE).read_bytes())["agent_teams"] is False
  assert profile_runtime.verify(on, runtime) == profile
  assert native_sentinel.read_text() == "synthetic native state"


@pytest.mark.parametrize("failure,committed", [("package", True), ("commit-owner", False)])
def test_interrupted_enable_recovers_committed_selection(tmp_path, prepared_runtime, monkeypatch, failure, committed):
  path, off, lock, runtime = applied(tmp_path, prepared_runtime)
  profile = profile_runtime.verify(off, runtime)
  local(tmp_path, True)
  on = load_workspace(path)
  original = Tree.write_state
  def fail_once(self, name, data):
    if self.root == profile and (name == "package.json" if failure == "package"
        else name == ".agentcfg-package-owner.json" and "pending_modules" not in json.loads(data)):
      raise OSError("synthetic team preparation interruption")
    return original(self, name, data)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_state", fail_once)
    with pytest.raises(OSError):
      commands.apply_candidate(on, lock, on.candidate(lock.identity))
  assert (on.state_root / "pending.json").exists()
  with on.adapter.lifecycle_guard(on), Tree(on.instance) as target, Tree(on.state_root) as state, instance_lock(state):
    deployment.recover(target, state, prepare=lambda launch: commands.prepare_launch(on, launch))
  assert not (on.state_root / "pending.json").exists()
  # package 更新发生在配置提交后的最终准备；恢复必须完成已提交的 ON。
  # 提交前的 owner 故障则回到旧 OFF，不能从当前机器配置提前开启。
  assert (TEAM_BUNDLE in bundles(profile)) is committed
  assert json.loads((on.instance / TEAM_SELECTION_FILE).read_bytes())["agent_teams"] is committed
  commands.apply_candidate(on, lock, on.candidate(lock.identity))
  assert TEAM_BUNDLE in bundles(profile)
  assert profile_runtime.verify(on, runtime) == profile


def test_native_bundle_mutation_is_not_adopted(tmp_path, prepared_runtime):
  _path, workspace, _lock, runtime = applied(tmp_path, prepared_runtime)
  profile = profile_runtime.verify(workspace, runtime)
  path = profile / "package.json"
  document = json.loads(path.read_bytes())
  document["dsh"]["profile"]["bundles"].append(TEAM_BUNDLE)
  raw = deployment.json_bytes(document)
  path.write_bytes(raw)
  with pytest.raises(Conflict):
    profile_runtime.prepare(workspace, runtime)
  with pytest.raises(Conflict):
    profile_runtime.verify(workspace, runtime)
  assert path.read_bytes() == raw


@pytest.mark.parametrize("value", [None, [], {}, {"schema_version": True, "agent_teams": True},
  {"schema_version": 1, "agent_teams": 1}, {"schema_version": 1, "agent_teams": False, "unknown": True}])
def test_invalid_deployed_switch_is_rejected(tmp_path, prepared_runtime, value):
  _path, workspace, _lock, runtime = applied(tmp_path, prepared_runtime)
  (workspace.instance / TEAM_SELECTION_FILE).write_bytes(deployment.json_bytes(value))
  with pytest.raises(Conflict, match="Teams 开关无效"):
    profile_runtime.prepare(workspace, runtime)


def test_active_instance_blocks_team_transition(tmp_path, prepared_runtime):
  path, off, lock, _runtime = applied(tmp_path, prepared_runtime)
  local(tmp_path, True)
  on = load_workspace(path)
  original = (off.instance / TEAM_SELECTION_FILE).read_bytes()
  with off.adapter.run_lifecycle_guard(off):
    with pytest.raises(Conflict):
      commands.apply_candidate(on, lock, on.candidate(lock.identity))
  assert (off.instance / TEAM_SELECTION_FILE).read_bytes() == original


@pytest.mark.parametrize("mutation", ["delete", "toggle"])
def test_run_rejects_deployed_switch_drift_before_process(tmp_path, prepared_runtime, fake_subprocess, mutation):
  _path, workspace, _lock, runtime = applied(tmp_path, prepared_runtime)
  profile = profile_runtime.verify(workspace, runtime)
  manifest = (profile / "package.json").read_bytes()
  selection = workspace.instance / TEAM_SELECTION_FILE
  if mutation == "delete":
    selection.unlink()
  else:
    selection.write_bytes(deployment.json_bytes({"schema_version": 1, "agent_teams": True}))
  with pytest.raises(Conflict, match="受管启动资源发生漂移"):
    launching.run(workspace, cwd=tmp_path)
  assert not fake_subprocess.calls
  assert (profile / "package.json").read_bytes() == manifest
