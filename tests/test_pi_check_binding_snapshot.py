"""当前 Host 来源查询与执行前置条件；仅临时文件和显式替身。"""

from copy import deepcopy
import os
from pathlib import Path

import pytest

from agentcfg.activity import digest
from agentcfg.pi_auxiliary import check_binding_snapshot, resolve_auxiliary
from agentcfg.pi_checks import compile_check
from agentcfg.paths import PathError
from agentcfg.pi_supervisor import Principal
from agentcfg.pi_trusted_checks import contract_digest, host_context
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from agentcfg.deployment import json_bytes
from test_pi_trusted_checks import fixture
from test_pi_supervisor import fixture as service_fixture, request


def snapshot_fixture(tmp_path):
  f = fixture(tmp_path, inline=False)
  candidate = Path(f.host.config["instance_root"]) / "pi-home/task-keeper/worktrees/task"
  candidate.mkdir(parents=True)
  f.project = candidate
  f.manifest["options"]["paths"]["roots"]["project"]["path"] = str(candidate)
  f.manifest["plugins"] = ["task-keeper"]
  f.manifest["options"]["task_keeper"] = {"enabled": True, "project_root": "project", "check_ids": ["test"]}
  f.host.config["manifest_digest"] = digest(f.manifest)
  f.host.config["policy_digest"] = digest(f.manifest["permission_policy"])
  f.host.manifest = lambda: deepcopy(f.manifest)
  f.payload = {"check_id": "test", "task_id": "task", "cwd": str(candidate)}
  return f


def test_snapshot_is_current_host_only_and_has_no_execution_side_effects(tmp_path, monkeypatch):
  f = snapshot_fixture(tmp_path)
  effects = []
  monkeypatch.setattr("subprocess.run", lambda *a, **k: effects.append(a))
  before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
  first = check_binding_snapshot(f.host, f.payload)
  assert first == check_binding_snapshot(f.host, f.payload)
  assert set(first) == {"schema_version", "check_id", "task_id", "contract_digest"}
  assert first["schema_version"] == 1 and len(first["contract_digest"]) == 64
  assert str(tmp_path) not in str(first)
  assert before == sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
  assert effects == []


def test_semantic_digest_survives_real_lease_changes_but_not_sources(tmp_path):
  f = snapshot_fixture(tmp_path)
  before = check_binding_snapshot(f.host, f.payload)["contract_digest"]
  def actual(lease):
    context = host_context(f.host, f.manifest, lease, "test", f.project)
    return compile_check(f.binding, candidate=f.project, executable=f.exe,
      read_roots=[f.exe, f.trusted], trusted_context=context)
  a = actual({"lease_id": "a" * 32, "grant_generation": 1})
  b = actual({"lease_id": "b" * 32, "grant_generation": 9})
  assert a["binding_digest"] != b["binding_digest"]
  assert contract_digest(a) == contract_digest(b) == before
  f.script.write_text("changed readonly checker implementation")
  assert check_binding_snapshot(f.host, f.payload)["contract_digest"] != before


@pytest.mark.parametrize("case", ["unknown", "wrong-task", "subdir", "symlink", "wrong-profile", "disabled", "unselected", "wrong-project", "writable", "type", "project-denied", "policy-denied"])
def test_query_rejects_caller_expansion_and_wrong_current_host_binding(tmp_path, case):
  f = snapshot_fixture(tmp_path)
  if case == "unknown": f.payload["writer_roots"] = []
  elif case == "wrong-task": f.payload["task_id"] = "../task"
  elif case == "subdir":
    (f.project / "sub").mkdir(); f.payload["cwd"] = str(f.project / "sub")
  elif case == "symlink":
    alias = f.project.with_name("alias"); alias.symlink_to(f.project); f.payload["cwd"] = str(alias)
  elif case == "wrong-profile": f.manifest["profile_id"] = "pi-base"
  elif case == "disabled": f.manifest["options"]["task_keeper"]["enabled"] = False
  elif case == "unselected": f.manifest["plugins"] = []
  elif case == "wrong-project": f.binding["project_root"] = "trusted"
  elif case == "type": f.payload["check_id"] = []
  elif case == "project-denied": f.manifest["options"]["permissions"] = {"denied_roots": ["project"]}
  elif case == "policy-denied":
    f.manifest["permission_policy"]["rules"] = [{"kind": "file", "effect": "deny", "root_ref": "project", "relative_path": "."}]
  else: f.manifest["role_bindings"]["task-keeper-writer"]["write_roots"].append("trusted")
  f.host.config["manifest_digest"] = digest(f.manifest)
  f.host.config["policy_digest"] = digest(f.manifest["permission_policy"])
  with pytest.raises((Conflict, ConfigError, PathError, OSError, ValueError)):
    check_binding_snapshot(f.host, f.payload)


def test_manager_channel_generation_and_roles_gate_query(tmp_path):
  service, token, _, calls = service_fixture(tmp_path)
  invoked = []
  service.check_binding_snapshot_handler = lambda args: invoked.append(args) or {"contract_digest": "a" * 64}
  args = {"check_id": "test", "task_id": "task", "cwd": "/synthetic"}
  assert service.reply(token, os.geteuid(), request("check_binding_snapshot", args))["ok"]
  for role in ("worker", "delegate", "user", "task-keeper-source"):
    with pytest.raises(Conflict): service.handle(Principal(role), request("check_binding_snapshot", args))
  with pytest.raises(ConfigError): service.handle(Principal("manager"), request("check_binding_snapshot", {**args, "role": "manager"}))
  service.closing = True
  with pytest.raises(Conflict): service.handle(Principal("manager"), request("check_binding_snapshot", args))
  service.closing = False
  principal = service.authenticate(token, os.geteuid())
  service.store.request_cancel(principal.lease_id, service.store.owner)
  assert service.reply(token, os.geteuid(), request("check_binding_snapshot", args))["ok"] is False
  assert invoked == [args] and calls == []


def test_changed_query_digest_rejected_before_capability_directory_or_input_write(tmp_path, monkeypatch):
  from types import SimpleNamespace
  f = snapshot_fixture(tmp_path)
  expected = check_binding_snapshot(f.host, f.payload)["contract_digest"]
  runtime = tmp_path / "runtime"; runtime.mkdir(mode=0o700)
  state = tmp_path / "state"; state.mkdir(mode=0o700)
  with Tree(runtime) as tree: tree.write_state("runtime/commands.json", json_bytes({"programs": {"check": {"kind": "check"}}}))
  repo = tmp_path / "repo"; (repo / "scripts").mkdir(parents=True)
  (repo / "scripts/pi-project-check").write_text("inert helper")
  effects = []
  f.host.runtime_root = runtime; f.host.root = state; f.host.repository = repo
  f.host.server = SimpleNamespace(endpoint=tmp_path / "endpoint")
  f.host.service = SimpleNamespace(issue_capability=lambda *args: effects.append(args) or "synthetic")
  lease = {"lease_id": "b" * 32, "grant_generation": 1, "kind": "check", "task_id": "task", "planned_workspaces": [{"workspace_key": "fake"}]}
  with pytest.raises(Conflict, match="CHECK_CONTRACT_REQUIRED"):
    resolve_auxiliary(f.host, lease, "check", f.payload)
  assert effects == [] and not (state / "activity/auxiliary-homes").exists()
  # helper来源在效果前核验；不可因无helper回退系统PATH。
  monkeypatch.setattr("agentcfg.pi_pid_namespace.host_namespace_binary", lambda current: runtime / "bin/pi-bwrap")
  with pytest.raises(Conflict, match="CHECK_NAMESPACE_HELPER_UNAVAILABLE"):
    resolve_auxiliary(f.host, lease, "check", {**f.payload, "contract_digest": expected})
  assert effects == [] and not (state / "activity/auxiliary-homes").exists()
  f.script.write_text("changed after prepared snapshot")
  with pytest.raises(Conflict, match="CHECK_CONTRACT_CHANGED"):
    resolve_auxiliary(f.host, lease, "check", {**f.payload, "contract_digest": expected})
  assert effects == []
  assert not (state / "activity/auxiliary-homes").exists()
  assert not (state / "activity/auxiliary-inputs").exists()
