"""审批输出上限的公共配置、原生交付和身份绑定；不启动宿主。"""

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


@pytest.mark.parametrize("value", [256, 1024, 2048, 8192])
def test_output_limit_is_delivered_without_mutation_and_bound_to_identity(value):
  data = configured()
  data["profile"]["agent_options"]["permission_control"]["review_max_output_tokens"] = value
  before = deepcopy(data)
  assert resolve_permission_control(data)["reviewMaxOutputTokens"] == value
  adapter = OmpAdapter(REPO)
  delivered = adapter._native_permission(data)
  baseline = adapter._native_permission(configured())
  assert delivered["reviewMaxOutputTokens"] == value
  assert delivered["policyVersion"] != baseline["policyVersion"]
  assert delivered["reviewer"] == baseline["reviewer"]
  assert delivered["nativePatterns"] == baseline["nativePatterns"]
  assert data == before
  Draft202012Validator(NATIVE_PERMISSION_CONTROL).validate(delivered)


@pytest.mark.parametrize("value", [255, 8193, 0, -1, True, False, None, "secret-sentinel", [], {}, 2048.5])
def test_invalid_output_limit_fails_closed_in_resolver_and_contracts(value):
  data = configured()
  data["profile"]["agent_options"]["permission_control"]["review_max_output_tokens"] = value
  with pytest.raises(ConfigError) as error:
    resolve_permission_control(data)
  assert error.value.exit_code == 2
  assert str(error.value) == "配置校验失败: omp-permission-config"
  assert not Draft202012Validator(PERMISSION_CONTROL).is_valid(data["profile"]["agent_options"]["permission_control"])
  delivered = native()
  delivered["reviewMaxOutputTokens"] = value
  assert not Draft202012Validator(NATIVE_PERMISSION_CONTROL).is_valid(delivered)


def test_integral_float_is_not_a_configuration_integer():
  data = configured()
  data["profile"]["agent_options"]["permission_control"]["review_max_output_tokens"] = 2048.0
  with pytest.raises(ConfigError, match="omp-permission-config"):
    resolve_permission_control(data)


def test_legacy_configuration_and_repository_contract_remain_compatible():
  assert "reviewMaxOutputTokens" not in resolve_permission_control(configured())
  Draft202012Validator(NATIVE_PERMISSION_CONTROL).validate(native())
  schema = json.loads((REPO / "schemas/omp-agent.schema.json").read_text())
  public = schema["properties"]["defaults"]["properties"]["agent_options"]["properties"]["permission_control"]
  assert public == OPTIONS["properties"]["permission_control"] == PERMISSION_CONTROL
  assert schema["$defs"]["permissionControl"] == NATIVE_PERMISSION_CONTROL
