"""实网准入在任何宿主或账号操作之前核验；默认测试仅使用报告与对象替身。"""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
import pytest

from agentcfg.pi_scope import initial_scope, OPTIONAL
from agentcfg.pi_validation_runtime import ValidationRuntime
from agentcfg.schema import ConfigError
from test_pi_release_gate import seal, save
import agentcfg.pi_validation_live as live


def args(tmp_path):
  return SimpleNamespace(allow_host=True, allow_live=True, case="codex-receipts", live_item="pi-codex.live-codex",
    profile="pi-codex", scope=tmp_path / "scope.json", runtime=tmp_path / "runtime", native_report=tmp_path / "native.json",
    local=tmp_path / "local.toml", project=tmp_path / "project")


@pytest.mark.parametrize("selected,reason", [(True, "live-candidate-unfrozen"), (False, "live-capability-not-selected")])
def test_unfrozen_or_unselected_live_item_does_not_inspect_runtime_or_read_accounts(tmp_path, monkeypatch, selected, reason):
  scope = initial_scope(optional_selected={key: selected for key in OPTIONAL})
  save(tmp_path, "scope.json", scope)
  monkeypatch.setattr(live, "inspect_runtime", lambda _: pytest.fail("no runtime inspection before selection"))
  monkeypatch.setattr(live, "load_workspace", lambda *a, **k: pytest.fail("no account configuration read before selection"))
  value = live.execute(args(tmp_path))
  assert value["status"] == "not-run" and value["reason"] == reason and value["results"] == []


def test_live_case_cannot_relabel_another_selected_capability(tmp_path):
  scope = initial_scope(optional_selected=dict.fromkeys(OPTIONAL, True))
  with pytest.raises(ConfigError): live.selected_item(scope, scenario="pi-default.live-web", profile="pi-default", case="codex-receipts")
  with pytest.raises(ConfigError): live.selected_item(scope, scenario="pi-codex.live-codex", profile="pi-default", case="codex-receipts")
  with pytest.raises(ConfigError): live.selected_item(scope, scenario="pi-codex.invented", profile="pi-codex", case="codex-receipts")


def native_report(runtime):
  return {"schema_version": 1, "tier": "native", "case": "codex-receipts", "status": "passed",
    "runtime": runtime.public_identity(), "source_digest": "d" * 64,
    "started_at": "2026-09-19T01:00:00Z", "finished_at": "2026-09-19T01:00:01Z",
    "results": [{"scenario_id": scenario, "status": "passed", "facts": {"fixture": True}, "execution": {"exit_code": 0, "termination_confirmed": True}}
      for scenario in ("codex-native-readonly", "codex-native-write", "codex-native-control")]}


@pytest.mark.parametrize("fault", [None, "runtime", "failed", "missing-case", "physical"])
def test_live_native_gate_requires_the_current_runtime_and_every_native_case(tmp_path, fault):
  runtime = ValidationRuntime(tmp_path, "pi-codex", "node", "linux-x86_64", "a" * 64, "b" * 64, "c" * 64, "fixture", {"node": "v24.14.0"})
  value = native_report(runtime)
  if fault == "runtime": value["runtime"]["runtime_identity"] = "e" * 64
  if fault == "failed": value["status"] = value["results"][0]["status"] = "failed"
  if fault == "missing-case": value["results"].pop()
  if fault == "physical": value["results"][0]["execution"]["termination_confirmed"] = False
  if fault in ("missing-case", "physical"):
    with pytest.raises(ConfigError): live.native_prerequisite(value, runtime, "codex-receipts")
  else:
    assert live.native_prerequisite(value, runtime, "codex-receipts") == {None: None, "runtime": "native-runtime-mismatch", "failed": "native-scenarios-not-passed"}[fault]


def test_live_requires_both_authorizations_before_scope_read(tmp_path, monkeypatch):
  value = args(tmp_path)
  monkeypatch.setattr(live, "inspect_context", lambda _: pytest.fail("must not inspect"))
  for host, account in ((False, True), (True, False)):
    value.allow_host, value.allow_live = host, account
    with pytest.raises(ConfigError): live.execute(value)


@pytest.mark.parametrize("fault", [None, "identity", "generation", "launch", "project"])
def test_live_context_binds_exact_current_deployment_and_scope_without_executing(tmp_path, monkeypatch, fault):
  from agentcfg.storage import ensure_private
  value = args(tmp_path); value.project.mkdir()
  runtime = ValidationRuntime(value.runtime, "pi-codex", "node", "linux-x86_64", "a" * 64, "b" * 64, "c" * 64, "fixture", {"node": "v24.14.0"})
  identity = {name: letter * 64 for name, letter in zip(("lock_digest", "runtime_digest", "policy_digest", "resource_digest", "machine_contract_digest"), "bacde")}
  scope = initial_scope(optional_selected=dict.fromkeys(OPTIONAL, True))
  for item in scope["items"]:
    if item["scenario_id"] == value.live_item and item["platform"]["os"] == "linux" and item["platform"]["architecture"] == "x86_64": item["identity"] = identity
  save(tmp_path, "scope.json", seal(scope)); save(tmp_path, "native.json", native_report(runtime))
  state = tmp_path / "state"; ensure_private(state)
  data = {"profile": {"agent_options": {"paths": {"roots": {"project": {"purpose": "project", "path": str(value.project)}}}}}}
  workspace = SimpleNamespace(agent="pi", state_root=state, binding={"fixture": True}, repository=tmp_path, resolved=SimpleNamespace(data=data),
    candidate=lambda _: SimpleNamespace(generation="current"))
  lock = SimpleNamespace(identity=runtime.lock_identity)
  workspace.backend = SimpleNamespace(read_lock=lambda _: lock, runtime_identity=lambda *_: runtime.identity, root=lambda *_: runtime.root)
  launch = {"runtime_identity": runtime.identity, "lock_identity": runtime.lock_identity, "fixture_contract": "current"}
  current = {"binding": workspace.binding, "generation": "stale" if fault == "generation" else "current", "launch": deepcopy(launch)}
  if fault == "launch": current["launch"]["fixture_contract"] = "undeployed-source"
  if fault == "project": value.project = tmp_path / "outside"; value.project.mkdir()
  monkeypatch.setattr(live, "inspect_runtime", lambda _: runtime)
  monkeypatch.setattr(live, "load_workspace", lambda *a, **k: workspace)
  monkeypatch.setattr(live, "read_state", lambda _: {"current": current})
  monkeypatch.setattr(live, "record", lambda *_: launch)
  monkeypatch.setattr(live, "diagnostic_identity", lambda _: {**identity, "policy_digest": "f" * 64} if fault == "identity" else identity)
  monkeypatch.setattr(live, "execute_delegate", lambda context, **kwargs: {"scenario_id": context["item"]["scenario_id"], "status": "not-run", "reason": "fixture-only"})
  if fault == "project":
    with pytest.raises(ConfigError, match="project-unbound"): live.inspect_context(value)
  else:
    context = live.inspect_context(value)
    if fault: assert context["reason"] == ("live-scope-identity-stale" if fault == "identity" else "live-configuration-not-deployed")
    else:
      assert context["workspace"] is workspace and context["runtime"] is runtime
      assert live.execute(value)["status"] == "not-run"  # 通过准入不冒充执行器已完成。


def test_native_prerequisite_is_sealed_identity_equality_not_install_path(tmp_path):
  """同一软件运行包身份安装到不同目录：身份字段全等即可复用；任何身份字段变化必须拒绝。"""
  first = ValidationRuntime(tmp_path / "inst-a", "pi-codex", "node", "linux-x86_64", "a" * 64, "b" * 64, "c" * 64, "fixture", {"node": "v24.14.0"})
  second = ValidationRuntime(tmp_path / "elsewhere" / "inst-b", "pi-codex", "node", "linux-x86_64", "a" * 64, "b" * 64, "c" * 64, "fixture", {"node": "v24.14.0"})
  assert first.root != second.root
  value = native_report(first)
  assert live.native_prerequisite(value, second, "codex-receipts") is None
  for field, replacement in (("lock_identity", "9" * 64), ("runtime_identity", "8" * 64), ("slice_identity", "7" * 64),
      ("platform", "linux-arm64"), ("engine", "bun")):
    moved = deepcopy(value)
    moved["runtime"][field] = replacement
    assert live.native_prerequisite(moved, second, "codex-receipts") == "native-runtime-mismatch"
  moved = deepcopy(value)
  moved["runtime"]["toolchains"] = {"node": "v99.0.0"}
  assert live.native_prerequisite(moved, second, "codex-receipts") == "native-runtime-mismatch"
