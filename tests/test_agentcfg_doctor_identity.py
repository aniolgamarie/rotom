"""真实 OMP identity collector → 展示层；不代表完整 CLI/生命周期安全路径验收。"""

from contextlib import contextmanager
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from agentcfg import presentation
from agentcfg.interaction_diagnostics import readiness
from agentcfg.omp import OmpAdapter
from agentcfg.omp_identity import native_identity, validate_layout
from agentcfg.storage import Conflict

from test_agentcfg_interaction import CANARY, doctor_payload, no_state, render


@pytest.fixture
def identity_workspace(tmp_path):
  # 仅为 collector 构造它实际读取的数据；不创建部署、所有权或锁，也不替换任何 guard。
  data = {"profile": {"agent_options": {"discovery": {
    "project_resources": False, "project_roots": []}}}}
  workspace = SimpleNamespace(profile="omp-synthetic", instance=tmp_path / "instance",
    resolved=SimpleNamespace(data=data), adapter=OmpAdapter(tmp_path))
  return workspace, native_identity(workspace.profile, workspace.instance)


def collect_doctor(workspace, **updates):
  payload = doctor_payload(agent="omp", profile=workspace.profile,
    identity=workspace.adapter.identity_diagnostics(workspace), **updates)
  payload["readiness"] = readiness(payload)
  return payload


@contextmanager
def no_identity_io(monkeypatch):
  def forbidden(*args, **kwargs):
    raise AssertionError("identity 展示不得重新探测路径或读取文件")
  with no_state(monkeypatch), monkeypatch.context() as patch:
    for name in ("open", "stat", "lstat", "readlink", "listdir", "scandir"):
      patch.setattr(os, name, forbidden)
    for name in ("is_symlink", "is_dir", "resolve", "absolute"):
      patch.setattr(Path, name, forbidden)
    yield


def assert_no_identity_values(text, identity):
  for key in ("native_name", "profile_sha256", "home", "agent_dir", "state_home"):
    assert identity[key] not in text
  for path in identity["xdg"].values():
    assert path not in text
  execution = identity.get("planned_execution_environment")
  if isinstance(execution, dict):
    for key in ("home", "config_dir"):
      value = execution.get(key)
      if isinstance(value, str) and value:
        assert value not in text
    for value in execution.get("xdg", {}).values():
      if isinstance(value, str) and value:
        assert value not in text
  assert CANARY not in text


@pytest.mark.parametrize("root", ["xdg_config", "xdg_data", "xdg_cache", "xdg_state"])
@pytest.mark.parametrize("live", [False, True])
def test_real_alternate_layout_conflict_overrides_healthy_title(identity_workspace, root, live, monkeypatch):
  workspace, identity = identity_workspace
  alternate = getattr(identity, root) / "omp/profiles" / identity.native_name
  alternate.mkdir(parents=True)
  with pytest.raises(Conflict, match="XDG"):
    validate_layout(identity)
  payload = collect_doctor(workspace, live=live)
  assert payload["identity"]["layout_conflict"] == "xdg-or-identity-layout-conflict"
  assert payload["readiness"]["status"] == "offline-ready"
  payload["identity"]["unknown"] = {"path": CANARY}
  original = deepcopy(payload)
  with no_identity_io(monkeypatch):
    text = render(payload)
  title = "doctor：在线检查完成，仍需处理" if live else "doctor：需要处理"
  assert text.splitlines()[0] == title
  assert "身份前置" in text and "XDG 或身份布局冲突" in text
  assert "身份或计划环境仍有冲突" in text
  assert "仅计划，非已部署环境验证" in text
  assert_no_identity_values(text, payload["identity"])
  assert payload == original
  assert alternate.is_dir()


def test_real_planned_environment_conflict_is_not_deployed_evidence(identity_workspace, isolated_environment, monkeypatch):
  workspace, identity = identity_workspace
  alternate = Path(isolated_environment.env["XDG_DATA_HOME"]) / "omp/profiles" / identity.native_name
  alternate.mkdir(parents=True)
  payload = collect_doctor(workspace)
  assert payload["identity"]["layout_conflict"] is None
  assert payload["identity"]["planned_execution_environment"] == {
    "scope": "planned-not-deployed", "status": "path-conflict"}
  original = deepcopy(payload)
  with no_identity_io(monkeypatch):
    text = render(payload)
  assert text.splitlines()[0] == "doctor：需要处理"
  assert "计划路径冲突" in text and "仅计划，非已部署环境验证" in text
  assert "身份前置" in text
  assert_no_identity_values(text, payload["identity"])
  assert payload == original


def test_real_planned_ready_remains_explicitly_limited(identity_workspace, monkeypatch):
  workspace, _ = identity_workspace
  payload = collect_doctor(workspace)
  report = payload["identity"]
  assert report["layout_conflict"] is None
  assert report["planned_execution_environment"]["status"] == "ready"
  original = deepcopy(payload)
  with no_identity_io(monkeypatch):
    text = render(payload)
  assert text.splitlines()[0] == "doctor：离线就绪"
  assert "仅计划，非已部署环境验证" in text and "计划路径检查通过" in text
  assert "身份前置" not in text
  assert_no_identity_values(text, report)
  assert payload == original


@pytest.mark.parametrize("mode, tty", [("json", True), ("auto", False)])
def test_real_conflict_keeps_exact_json_and_readiness(identity_workspace, mode, tty, monkeypatch, capsys):
  workspace, identity = identity_workspace
  (identity.xdg_config / "omp/profiles" / identity.native_name).mkdir(parents=True)
  payload = collect_doctor(workspace)
  payload["identity"]["unknown"] = {"value": CANARY}
  original = deepcopy(payload)
  expected = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
  args = SimpleNamespace(format=mode, machine="workstation", profile=workspace.profile)
  monkeypatch.setattr(sys.stdout, "isatty", lambda: tty)
  with no_identity_io(monkeypatch):
    assert presentation.emit_result(payload, args=args) is None
  result = capsys.readouterr()
  assert result.out == expected and not result.err
  assert payload == original
  assert payload["readiness"]["status"] == "offline-ready"


@pytest.mark.parametrize("value", [CANARY, [CANARY], {"unknown": CANARY}, 42, None])
def test_unknown_identity_fields_are_not_projected(identity_workspace, value, monkeypatch):
  workspace, _ = identity_workspace
  payload = collect_doctor(workspace)
  payload["identity"].update(layout_conflict=value, unknown={"value": CANARY},
    planned_execution_environment={"scope": value, "status": value, "home": CANARY})
  original = deepcopy(payload)
  with no_identity_io(monkeypatch):
    text = render(payload)
  assert_no_identity_values(text, payload["identity"])
  assert "身份前置" not in text and "计划路径检查通过" not in text
  assert payload == original


@pytest.mark.parametrize("value", [CANARY, [CANARY], {"unknown": CANARY}, None])
def test_unknown_planned_status_and_identity_shapes_are_safe(identity_workspace, value, monkeypatch):
  workspace, _ = identity_workspace
  payload = collect_doctor(workspace)
  payload["identity"]["planned_execution_environment"]["status"] = value
  with no_identity_io(monkeypatch):
    text = render(payload)
    payload["identity"] = value
    malformed = render(payload)
  assert CANARY not in text and CANARY not in malformed
  assert "计划路径检查通过" not in text
  assert "身份前置" not in text and "身份前置" not in malformed


@pytest.mark.parametrize("pending, lock_bad", [(False, False), (False, True), (True, True)])
def test_conflict_keeps_recovery_lock_priority_and_all_service_ids(identity_workspace, pending, lock_bad, monkeypatch):
  workspace, identity = identity_workspace
  (identity.xdg_config / "omp/profiles" / identity.native_name).mkdir(parents=True)
  services = [{"location_id": "service:" + f"{index:020x}", "status": "unverified",
    "reason": "native-service-not-inspected", "url": CANARY} for index in range(12)]
  payload = collect_doctor(workspace, recovery_pending=pending, dependencies="sync-required",
    live=True, service_checks=services)
  if lock_bad:
    payload["lock"] = "missing-or-invalid"
    payload["readiness"]["blockers"].append("lock-missing-or-invalid")
    payload["readiness"]["next_commands"].append("lock --agent omp")
  original = deepcopy(payload)
  with no_identity_io(monkeypatch):
    text = render(payload)
  identity_position = text.index("身份前置")
  sync = "./agentcfg --machine workstation --profile omp-synthetic sync"
  assert identity_position < text.index(sync)
  if pending:
    apply = "./agentcfg --machine workstation --profile omp-synthetic apply"
    assert text.index("恢复前置") < text.index("锁前置") < identity_position
    assert text.index(apply) < text.index("恢复完成后") < text.index(sync)
  elif lock_bad:
    assert text.index("锁前置") < identity_position
    assert "依赖锁恢复并重新诊断后再评估" in text
  else:
    assert "身份或计划环境冲突处理并重新诊断后再评估" in text
    assert "下一步:" not in text
  for service in services:
    assert service["location_id"] in text
  assert "原生服务未检查" in text and "当前依赖需要同步" in text
  assert_no_identity_values(text, payload["identity"])
  assert "最多 8 项" not in text
  assert payload == original
