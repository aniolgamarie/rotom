"""doctor证据分层：假后端与显式可达性观察不替代加载、账号或运行。"""

from copy import deepcopy
import io
import json
from types import SimpleNamespace

import pytest

from agentcfg import commands, presentation
from agentcfg.schema import ConfigError


@pytest.fixture
def doctor_context(tmp_path, monkeypatch):
  scenario = {"dependencies": "installed", "deployed": True, "pending": False,
    "lock_missing": False, "drift": [], "conflicts": [], "changes": [], "runtime_matches": True}
  calls = []
  lock = SimpleNamespace(identity="synthetic-lock", metadata={})
  def read_lock(repository):
    if scenario["lock_missing"]:
      raise ConfigError("synthetic-lock-missing")
    return lock
  def candidate(identity):
    calls.append("candidate")
    return object()
  def plan(*args):
    calls.append("plan")
    return SimpleNamespace(**{key: scenario[key] for key in ("drift", "conflicts", "changes")})
  def live(data):
    calls.append("reachability")
    return [{"location_id": "route:" + "a" * 20, "status": "reachable", "http_status": 200}]
  backend = SimpleNamespace(read_lock=read_lock, toolchain=lambda lock: {},
    status=lambda *args: scenario["dependencies"])
  workspace = SimpleNamespace(agent="synthetic", profile="synthetic-profile", repository=tmp_path,
    state_root=tmp_path / "state", instance=tmp_path / "instance", backend=backend,
    resolved=SimpleNamespace(data={"machine": {}, "providers": {}}), candidate=candidate,
    adapter=SimpleNamespace(doctor=lambda projection: (), live_diagnostics=live),
    secret_store=SimpleNamespace(resolve=lambda *a, **k: pytest.fail("doctor不得读取秘密正文")))
  class StateTree:
    def __init__(self, *args, **kwargs):
      pass
    def __enter__(self):
      return self
    def __exit__(self, *args):
      pass
    def read(self, path):
      assert path == "pending.json"
      return b"synthetic pending" if scenario["pending"] else None
  def saved(tree):
    return {"previous": None, "current": {"launch": {"lock_identity": "synthetic-lock"}}
      if scenario["deployed"] else None}
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  monkeypatch.setattr(commands, "Tree", StateTree)
  monkeypatch.setattr(commands.deployment, "read_state", saved)
  monkeypatch.setattr(commands, "dependency_status", lambda *args: scenario["dependencies"])
  monkeypatch.setattr(commands.runtime, "runtime_identity", lambda *args: "synthetic-lock"
    if scenario["runtime_matches"] else "changed-runtime")
  monkeypatch.setattr(commands, "current_plan", plan)
  monkeypatch.setattr(commands, "write_diagnostics", lambda *args: None)
  args = SimpleNamespace(live=False, input=False, environment=False, format="json",
    machine="synthetic", local=None, profile=workspace.profile)
  return scenario, args, calls


def doctor(context, capsys):
  _, args, _ = context
  code = commands.cmd_doctor(args)
  return code, json.loads(capsys.readouterr().out)


def assert_unexecuted_layers(payload):
  assert payload["verification"]["loading"] == "not_run"
  assert payload["verification"]["account"] == "not_inspected"
  assert payload["verification"]["runtime"] == "not_run"


@pytest.mark.parametrize("input_diagnostics", [False, True])
def test_installed_and_current_deployment_do_not_prove_native_execution(doctor_context, capsys, input_diagnostics):
  _, args, calls = doctor_context
  args.input = input_diagnostics
  code, result = doctor(doctor_context, capsys)
  assert code == 0
  assert result["dependencies"] == "installed"
  readiness = result["input_diagnostics"]["readiness"] if input_diagnostics else result["readiness"]
  assert readiness["status"] == "offline-ready"
  assert result["verification"] == {"configuration": "passed", "dependencies": "passed",
    "deployment": "passed", "loading": "not_run", "account": "not_inspected", "runtime": "not_run"}
  assert calls == ["candidate", "plan"]


@pytest.mark.parametrize("status,expected", [("damaged", "failed"), ("missing", "not_run"),
  ("sync-required", "not_run"), ("unknown", "not_run")])
def test_dependency_stage_preserves_existing_status(doctor_context, capsys, status, expected):
  scenario, _, _ = doctor_context
  scenario["dependencies"] = status
  code, result = doctor(doctor_context, capsys)
  assert code == 0 and result["dependencies"] == status
  assert result["verification"]["dependencies"] == expected
  assert result["readiness"]["status"] == "action-required"
  assert_unexecuted_layers(result)


@pytest.mark.parametrize("problem", ["pending", "drift", "conflicts", "changes", "runtime-mismatch", "not-deployed"])
def test_deployment_stage_never_passes_unresolved_current_state(doctor_context, capsys, problem):
  scenario, _, calls = doctor_context
  if problem == "runtime-mismatch":
    scenario["runtime_matches"] = False
  elif problem == "not-deployed":
    scenario["deployed"] = False
  else:
    scenario[problem] = True if problem == "pending" else ["synthetic difference"]
  code, result = doctor(doctor_context, capsys)
  assert code == 0
  assert result["verification"]["deployment"] == ("not_run" if problem == "not-deployed" else "blocked")
  if problem in ("pending", "not-deployed"):
    assert calls == []
  assert_unexecuted_layers(result)


@pytest.mark.parametrize("deployed", [False, True])
def test_missing_lock_has_explicit_blocked_evidence_without_native_inspection(doctor_context, capsys, deployed):
  scenario, args, calls = doctor_context
  scenario.update(lock_missing=True, deployed=deployed)
  args.live = True
  code, result = doctor(doctor_context, capsys)
  assert code == 2
  assert result["lock"] == "missing-or-invalid"
  assert result["readiness"]["blockers"] == ["lock-missing-or-invalid"]
  assert result["verification"]["configuration"] == "passed"
  assert result["verification"]["dependencies"] == "blocked"
  assert result["verification"]["deployment"] == ("blocked" if deployed else "not_run")
  assert calls == [] and result["live"] is False
  assert_unexecuted_layers(result)


def test_live_reachability_never_promotes_loading_account_or_runtime(doctor_context, capsys):
  _, args, calls = doctor_context
  _, offline = doctor(doctor_context, capsys)
  args.live = True
  _, live = doctor(doctor_context, capsys)
  assert live["live"] is True and offline["live"] is False
  assert live["service_checks"][0]["status"] == "reachable"
  assert live["verification"] == offline["verification"]
  assert live["readiness"] == offline["readiness"]
  assert calls.count("reachability") == 1
  assert_unexecuted_layers(live)


def test_human_verification_uses_fixed_labels_and_preserves_json(doctor_context, capsys, monkeypatch):
  _, payload = doctor(doctor_context, capsys)
  expected = deepcopy(payload)
  stream = io.StringIO()
  monkeypatch.setattr(presentation.sys, "stdout", stream)
  presentation.emit_result(payload, args=SimpleNamespace(format="human"))
  output = stream.getvalue()
  assert "配置声明  已验证" in output and "依赖准备  已验证" in output
  assert "配置部署  已验证" in output and "资源加载  未执行" in output
  assert "账号验证  未检查" in output and "运行验证  未执行" in output
  assert payload == expected


@pytest.mark.parametrize("missing_lock", [False, True])
def test_feature_declarations_survive_doctor_without_promoting_verification(doctor_context, capsys, missing_lock):
  scenario, args, _ = doctor_context
  scenario["lock_missing"] = missing_lock
  workspace = commands.workspace(args)
  features = {"status_bar": {"status": "not_ready", "decision": "held"},
    "collaboration": {"status": "not_ready", "decision": "held"},
    "optional_modules": {"status": "not_selected", "decision": "candidate", "selected": []}}
  workspace.adapter.feature_readiness = lambda data: deepcopy(features)
  code, payload = doctor(doctor_context, capsys)
  assert code == (2 if missing_lock else 0)
  assert payload["feature_readiness"] == features
  assert_unexecuted_layers(payload)


def test_human_feature_declarations_use_fixed_labels_without_candidate_echo(doctor_context, capsys, monkeypatch):
  _, payload = doctor(doctor_context, capsys)
  payload["feature_readiness"] = {"status_bar": {"status": "not_ready", "decision": "held",
    "candidate": "SYNTHETIC_UNTRUSTED_LABEL"}, "collaboration": {"status": "not_ready", "decision": "held"},
    "optional_modules": {"status": "not_selected", "decision": "candidate", "selected": []}}
  stream = io.StringIO()
  monkeypatch.setattr(presentation.sys, "stdout", stream)
  presentation.emit_result(payload, args=SimpleNamespace(format="human"))
  output = stream.getvalue()
  assert "不代表已加载" in output and "状态栏信息对齐" in output and "Pro调查协作" in output
  assert "未就绪；暂停准入" in output and "未选择；候选" in output
  assert "SYNTHETIC_UNTRUSTED_LABEL" not in output
  payload["verification"]["runtime"] = "SECRET_CANARY"
  payload["verification"]["SECRET_CANARY"] = "passed"
  stream = io.StringIO()
  monkeypatch.setattr(presentation.sys, "stdout", stream)
  presentation.emit_result(payload, args=SimpleNamespace(format="human"))
  assert "SECRET_CANARY" not in stream.getvalue()
