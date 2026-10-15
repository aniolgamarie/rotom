"""升级声明与实际原生数据分开，不改数据库或会话来制造兼容。"""
from copy import deepcopy
import pytest
from agentcfg.pi_upgrade import compare_upgrade, manifest_from_state
from agentcfg.pi_evidence import identity_changes
from agentcfg.schema import ConfigError


def test_dependency_role_policy_route_changes_require_new_matching_evidence():
  before = {"role_bindings": {"scout": {"model": "one"}}, "model_bindings": {}, "allowed_models": [],
    "permission_policy": {"default": "deny"}, "options": {"network": {"route": "direct"}}, "plugins": ["pi-subagents"]}
  after = deepcopy(before)
  after["role_bindings"]["scout"]["model"] = "two"
  after["permission_policy"]["rules"] = []
  after["options"]["network"]["route"] = "proxy"
  result = compare_upgrade(before, after, previous_runtime="a" * 64, current_runtime="b" * 64)
  assert result["changed_categories"] == ["dependencies", "roles", "policy", "routes"]
  assert result["evidence"] == "stale"
  assert result["previous_runtime_identity"] == "a" * 64 and result["previous_runtime_lookup"] == "saved-launch-contract"
  assert result["native_data"] == "preserved" and not result["automatic_data_migration"]
  assert result["rollback_boundary"] == "configuration-only"
  assert result["accepted_data_versions"] == {"pi_session": 3, "task_keeper_store": 3}


def test_unchanged_declarations_do_not_fabricate_execution_pass():
  result = compare_upgrade({}, {}, previous_runtime="a" * 64, current_runtime="a" * 64)
  assert result["changed_categories"] == [] and result["evidence"] == "identity-check-required"
  assert result["resume"] == "native-schema-check-required"


@pytest.mark.parametrize("baseline", [None, {"present": False},
  {"present": True, "value": {"bytes": "invalid PRIVATE_CANARY"}},
  {"present": True, "value": {"bytes": "bm90LWpzb24="}},
  {"present": True, "value": {"bytes": "W10="}}])
def test_saved_manifest_corruption_fails_without_falling_back_to_desired(baseline):
  state = {"items": {"manifest": {"path": "pi-home/agentcfg-manifest.json", "selector": None,
    "baseline": baseline, "desired": {"value": {"bytes": "eyJzY2hlbWFfdmVyc2lvbiI6MX0="}}}}}
  with pytest.raises(ConfigError) as error:
    manifest_from_state(state)
  assert "PRIVATE_CANARY" not in str(error.value)
