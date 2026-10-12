"""规则元数据与纯审批分类；不改变执行许可或默认政策。"""
from copy import deepcopy
from itertools import permutations, product

import pytest

from agentcfg.pi_catalog import validate
from agentcfg.schema import ConfigError


MODES = ("human", "reviewer", "deterministic-policy")


def rule(kind="file", effect="allow"):
  value = {"id": "fixture", "kind": kind, "effect": effect, "tool_ids": ["bash" if kind == "command" else "read"],
    "operations": ["execute" if kind == "command" else "read"]}
  value.update({"command_ref": "tool:build"} if kind == "command" else {"root_ref": "project", "relative_path": ".", "match": "subtree"})
  return value


@pytest.mark.parametrize("kind", ["file", "command"])
@pytest.mark.parametrize("mode", MODES)
def test_allow_rule_accepts_explicit_approval_without_rewriting(kind, mode):
  policy = {"schema_version": 1, "default": "deny", "rules": [{**rule(kind), "approval": mode}]}
  before = deepcopy(policy)
  validate("permission-policy", policy)
  assert policy == before


def test_original_rules_are_not_given_an_implicit_field():
  policy = {"schema_version": 1, "default": "deny", "rules": [rule()]}
  before = deepcopy(policy); validate("permission-policy", policy)
  assert policy == before and "approval" not in policy["rules"][0]


@pytest.mark.parametrize("effect,mode", [(effect, mode) for effect in ("allow", "deny") for mode in (None, True, 1, {}, [], "unknown")] + [("deny", mode) for mode in MODES])
def test_invalid_metadata_and_deny_approval_fail_closed(effect, mode):
  with pytest.raises(ConfigError):
    validate("permission-policy", {"schema_version": 1, "default": "deny", "rules": [{**rule(effect=effect), "approval": mode}]})


def test_unknown_rule_field_still_rejected():
  with pytest.raises(ConfigError):
    validate("permission-policy", {"schema_version": 1, "default": "deny", "rules": [{**rule(), "approval": "human", "source": "reviewer"}]})


@pytest.mark.parametrize("values", [list(values) for length in (1, 2, 3) for values in product(MODES, repeat=length)])
def test_aggregation_is_most_restrictive_and_order_independent(values):
  from agentcfg.pi_policy_approval import aggregate_approval
  before = values[:]
  expected = next(mode for mode in MODES if mode in values)
  for order in set(permutations(values)):
    assert aggregate_approval(list(order)) == expected
  assert values == before


class ListSubclass(list):
  pass


class StringSubclass(str):
  pass


@pytest.mark.parametrize("values", [None, (), [], [None], [True], [1], ["unknown"], [StringSubclass("human")], ListSubclass(["human"]), ["human"] * 4097, ["SYNTHETIC_PRIVATE"]])
def test_aggregation_rejects_non_native_or_invalid_data_safely(values):
  from agentcfg.pi_policy_approval import aggregate_approval
  with pytest.raises(ConfigError) as error: aggregate_approval(values)
  assert error.value.code == "pi-policy-approval-classification"
  assert "SYNTHETIC_PRIVATE" not in str(error.value)


def test_aggregation_allows_exact_capacity_and_repeated_modes():
  from agentcfg.pi_policy_approval import aggregate_approval
  assert aggregate_approval(["reviewer"] * 4096) == "reviewer"
