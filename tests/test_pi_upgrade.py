"""升级声明与实际原生数据分开，不改数据库或会话来制造兼容。"""
from copy import deepcopy
from agentcfg.pi_upgrade import compare_upgrade
from agentcfg.pi_evidence import identity_changes


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
