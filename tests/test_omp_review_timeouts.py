"""权限审查预算的公共配置、交付契约和策略身份；不启动宿主。"""

from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

from agentcfg.omp import OmpAdapter, OPTIONS
from agentcfg.omp_settings import NATIVE_PERMISSION_CONTROL, PERMISSION_CONTROL, resolve_permission_control
from agentcfg.schema import ConfigError
from test_omp_permission_control import configured, native


REPO = Path(__file__).resolve().parents[1]
DEFAULTS = {"primary_ms": 30000, "remote_ms": 30000, "total_ms": 60000}
NATIVE_DEFAULTS = {"primaryMs": 30000, "remoteMs": 30000, "totalMs": 60000}


def configure_timeouts(timeouts, remote=False):
  data = configured()
  config = data["profile"]["agent_options"]["permission_control"]
  config["review_timeouts"] = timeouts
  if remote:
    config["remote_fallback_model"] = "review-small"
  return data


@pytest.mark.parametrize("remote", [False, True])
def test_defaults_match_explicit_configuration_without_mutating_inputs(remote):
  implicit = configured()
  if remote:
    implicit["profile"]["agent_options"]["permission_control"]["remote_fallback_model"] = "review-small"
  explicit = configure_timeouts(deepcopy(DEFAULTS), remote)
  before = deepcopy(explicit)
  adapter = OmpAdapter(REPO)
  assert resolve_permission_control(implicit)["reviewTimeouts"] == NATIVE_DEFAULTS
  assert adapter._native_permission(implicit) == adapter._native_permission(explicit)
  assert explicit == before
  resolved = resolve_permission_control(explicit)
  resolved["reviewTimeouts"]["primaryMs"] = 1000
  assert explicit == before


@pytest.mark.parametrize("remote,timeouts", [
  (False, {"primary_ms": 1000, "remote_ms": 120000, "total_ms": 1000}),
  (False, {"primary_ms": 120000, "remote_ms": 1000, "total_ms": 240000}),
  (True, {"primary_ms": 1000, "remote_ms": 1000, "total_ms": 2000}),
  (True, {"primary_ms": 120000, "remote_ms": 120000, "total_ms": 240000}),
])
def test_valid_budget_boundaries_and_mapping(remote, timeouts):
  data = configure_timeouts(timeouts, remote)
  delivered = OmpAdapter(REPO)._native_permission(data)
  assert delivered["reviewTimeouts"] == {"primaryMs": timeouts["primary_ms"],
    "remoteMs": timeouts["remote_ms"], "totalMs": timeouts["total_ms"]}
  Draft202012Validator(NATIVE_PERMISSION_CONTROL).validate(delivered)


@pytest.mark.parametrize("key", DEFAULTS)
@pytest.mark.parametrize("value", [999, 0, -1, 240001, True, False, None, "secret-sentinel", [], {}])
def test_invalid_budget_value_rejected_by_resolver_and_schemas(key, value):
  timeouts = {**DEFAULTS, key: value}
  data = configure_timeouts(timeouts)
  with pytest.raises(ConfigError) as error:
    resolve_permission_control(data)
  assert error.value.exit_code == 2
  assert str(error.value) == "配置校验失败: omp-permission-config"
  public = data["profile"]["agent_options"]["permission_control"]
  assert not Draft202012Validator(PERMISSION_CONTROL).is_valid(public)
  native_value = native()
  native_key = {"primary_ms": "primaryMs", "remote_ms": "remoteMs", "total_ms": "totalMs"}[key]
  native_value["reviewTimeouts"] = {**NATIVE_DEFAULTS, native_key: value}
  assert not Draft202012Validator(NATIVE_PERMISSION_CONTROL).is_valid(native_value)


@pytest.mark.parametrize("key", ["primary_ms", "remote_ms"])
def test_primary_and_remote_upper_bound(key):
  data = configure_timeouts({**DEFAULTS, key: 120001})
  with pytest.raises(ConfigError, match="^配置校验失败: omp-permission-config$"):
    resolve_permission_control(data)
  assert not Draft202012Validator(PERMISSION_CONTROL).is_valid(
    data["profile"]["agent_options"]["permission_control"])
  native_value = native()
  native_value["reviewTimeouts"] = {**NATIVE_DEFAULTS, key.replace("_ms", "Ms"): 120001}
  assert not Draft202012Validator(NATIVE_PERMISSION_CONTROL).is_valid(native_value)


@pytest.mark.parametrize("key", DEFAULTS)
def test_resolver_rejects_integral_floats(key):
  with pytest.raises(ConfigError, match="^配置校验失败: omp-permission-config$"):
    resolve_permission_control(configure_timeouts({**DEFAULTS, key: float(DEFAULTS[key])}))


@pytest.mark.parametrize("change", ["primary_ms", "remote_ms", "total_ms", "unknown", "null", "list"])
def test_budget_object_is_complete_and_closed(change):
  timeouts = deepcopy(DEFAULTS)
  if change in DEFAULTS:
    del timeouts[change]
  elif change == "unknown":
    timeouts["secret-sentinel"] = "secret-sentinel"
  elif change == "null":
    timeouts = None
  else:
    timeouts = []
  data = configure_timeouts(timeouts)
  with pytest.raises(ConfigError) as error:
    resolve_permission_control(data)
  assert str(error.value) == "配置校验失败: omp-permission-config"
  assert not Draft202012Validator(PERMISSION_CONTROL).is_valid(
    data["profile"]["agent_options"]["permission_control"])
  native_value = native()
  native_value["reviewTimeouts"] = ({key.replace("_ms", "Ms"): value for key, value in timeouts.items()}
    if isinstance(timeouts, dict) else timeouts)
  assert not Draft202012Validator(NATIVE_PERMISSION_CONTROL).is_valid(native_value)


@pytest.mark.parametrize("remote,total", [(False, 29999), (True, 59999)])
def test_total_budget_must_cover_configured_reviewers(remote, total):
  data = configure_timeouts({**DEFAULTS, "total_ms": total}, remote)
  with pytest.raises(ConfigError) as error:
    resolve_permission_control(data)
  assert str(error.value) == "配置校验失败: omp-permission-review-timeouts"
  assert error.value.exit_code == 2


@pytest.mark.parametrize("key", DEFAULTS)
def test_each_timeout_is_bound_to_policy_identity(key):
  adapter = OmpAdapter(REPO)
  baseline = adapter._native_permission(configured())
  data = configure_timeouts({**DEFAULTS, key: DEFAULTS[key] + 1000})
  delivered = adapter._native_permission(data)
  assert delivered["policyVersion"] != baseline["policyVersion"]
  assert delivered["reviewer"] == baseline["reviewer"] == "session"
  assert delivered["nativePatterns"] == baseline["nativePatterns"]
  assert "nativeBash" not in delivered
  data["profile"]["agent_options"]["runtime"]["tools"]["approval"]["bash"] = "allow"
  with pytest.raises(ConfigError, match="^配置校验失败: omp-permission-native-protection$"):
    resolve_permission_control(data)


def test_repository_and_adapter_export_same_timeout_contracts():
  schema = json.loads((REPO / "schemas/omp-agent.schema.json").read_text())
  public = schema["properties"]["defaults"]["properties"]["agent_options"]["properties"]["permission_control"]
  assert public == OPTIONS["properties"]["permission_control"] == PERMISSION_CONTROL
  assert schema["$defs"]["permissionControl"] == NATIVE_PERMISSION_CONTROL
  # 旧 schemaVersion 2 交付物没有预算字段，仍可合法读取。
  legacy = native()
  assert "reviewTimeouts" not in legacy
  Draft202012Validator(NATIVE_PERMISSION_CONTROL).validate(legacy)
