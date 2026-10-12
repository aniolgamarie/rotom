"""Shell完整声明能力的保守分类；不接生产、不打开FD、不执行宿主。"""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest

from agentcfg.pi_shell_approval import classify_shell_approval
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


READ = ["read", "list", "search"]
WRITE = ["write", "create", "delete", "rename"]


def command_rule(identity="shell", approval="deterministic-policy", **changes):
  row = {"id": identity, "kind": "command", "effect": "allow", "tool_ids": ["bash"],
    "operations": ["execute"], "command_ref": "tool:shell"}
  if approval is not None: row["approval"] = approval
  return {**row, **changes}


def file_rule(identity, root, operations, approval="deterministic-policy", **changes):
  row = {"id": identity, "kind": "file", "effect": "allow", "tool_ids": ["read"],
    "operations": operations[:], "root_ref": root, "relative_path": ".", "match": "subtree"}
  if approval is not None: row["approval"] = approval
  return {**row, **changes}


@pytest.fixture
def case():
  return {"permission_policy": {"schema_version": 1, "default": "deny", "rules": [command_rule(),
      file_rule("project", "project", READ + WRITE), file_rule("system", "system", READ)]},
    "root_paths": {"project": "/work/project", "system": "/usr"}, "command_ref": "tool:shell",
    "mount_plan": {"schema_version": 1, "platform": "linux-x86_64", "network": "deny", "mounts": [
      {"path": "/work/project", "kind": "directory", "identity": "a" * 64, "role": "workspace", "writable": True},
      {"path": "/usr", "kind": "directory", "identity": "b" * 64, "role": "system", "writable": False},
      {"path": "/usr/bin/bash", "kind": "file", "identity": {"path": "/usr/bin/bash", "device": 1,
        "inode": 2, "uid": 0, "sha256": "c" * 64}, "role": "executable", "writable": False}],
      "symlinks": [{"path": "/bin", "target": "/usr/bin"}],
      "masks": [{"path": "/work/project/private", "kind": "file", "identity": "d" * 64}],
      "cwd": {"path": "/work/project", "identity": "e" * 64}, "seccomp_digest": "f" * 64}}


def test_complete_writable_and_system_tree_can_be_deterministic_without_input_mutation(case):
  before = deepcopy(case)
  assert classify_shell_approval(**case) == "deterministic-policy"
  assert case == before


@pytest.mark.parametrize("grade", ["human", "reviewer", "deterministic-policy", None])
@pytest.mark.parametrize("location", ["command", "project", "system"])
def test_grade_and_default_are_retained_at_every_capability(case, grade, location):
  row = case["permission_policy"]["rules"][["command", "project", "system"].index(location)]
  if grade is None: del row["approval"]
  else: row["approval"] = grade
  assert classify_shell_approval(**case) == (grade or "human")


@pytest.mark.parametrize("grades", [("human", "reviewer"), ("reviewer", "deterministic-policy"),
  ("deterministic-policy", "human")])
def test_overlapping_command_allows_take_highest_grade_in_every_order(case, grades):
  case["permission_policy"]["rules"] += [command_rule("extra-a", grades[0]), command_rule("extra-b", grades[1])]
  expected = "human" if "human" in grades else "reviewer"
  assert classify_shell_approval(**case) == expected
  case["permission_policy"]["rules"].reverse()
  assert classify_shell_approval(**case) == expected


@pytest.mark.parametrize("mutation", ["deny", "none", "other-command", "other-tool"])
def test_original_command_deny_and_matching_require_allow(case, mutation):
  rules = case["permission_policy"]["rules"]
  if mutation == "deny": rules.append(command_rule("deny", None, effect="deny"))
  elif mutation == "none": rules.pop(0)
  elif mutation == "other-command": rules[0]["command_ref"] = "tool:other"
  else: rules[0]["tool_ids"] = ["editor"]
  with pytest.raises(Conflict) as caught: classify_shell_approval(**case)
  assert str(caught.value) == "PERMISSION_DENIED"


def test_unmatched_high_command_and_unmatched_deny_do_not_affect_classification(case):
  case["permission_policy"]["rules"] += [command_rule("other", "human", command_ref="tool:other"),
    command_rule("other-deny", None, command_ref="tool:other", effect="deny"),
    command_rule("editor", "human", tool_ids=["editor"])]
  assert classify_shell_approval(**case) == "deterministic-policy"


@pytest.mark.parametrize("grade", ["human", "reviewer", None])
@pytest.mark.parametrize("placement", ["masked", "nonselected", "alias", "other-tool", "other-operation"])
def test_all_file_allow_grades_survive_unselected_alias_tool_operation_and_masks(case, grade, placement):
  case["root_paths"].update({"unused": "/unselected", "alias": "/work/project"})
  row = file_rule("restriction", "project", ["read"], grade, relative_path="private", match="exact")
  if placement == "nonselected": row["root_ref"] = "unused"
  elif placement == "alias": row["root_ref"] = "alias"
  elif placement == "other-tool": row["tool_ids"] = ["editor"]
  elif placement == "other-operation": row["operations"] = ["rename"]
  case["permission_policy"]["rules"].append(row)
  assert classify_shell_approval(**case) == (grade or "human")


@pytest.mark.parametrize("operation", READ + WRITE)
def test_missing_any_directory_operation_is_human_even_if_exact_or_child_allows_it(case, operation):
  row = case["permission_policy"]["rules"][1]
  row["operations"].remove(operation)
  case["permission_policy"]["rules"] += [file_rule("exact", "project", [operation], match="exact"),
    file_rule("child", "project", [operation], relative_path="existing", match="subtree")]
  assert classify_shell_approval(**case) == "human"


def test_whole_tree_coverage_combines_separate_operations_and_ancestor_rules(case):
  case["root_paths"]["ancestor"] = "/work"
  case["permission_policy"]["rules"].pop(1)
  for operation in READ + WRITE:
    case["permission_policy"]["rules"].append(file_rule("op-" + operation, "ancestor", [operation]))
  assert classify_shell_approval(**case) == "deterministic-policy"


def test_readonly_workspace_does_not_require_write_operations(case):
  case["mount_plan"]["mounts"][0]["writable"] = False
  case["permission_policy"]["rules"][1]["operations"] = READ[:]
  assert classify_shell_approval(**case) == "deterministic-policy"


def test_future_creation_requires_whole_tree_create_coverage_without_filesystem_inspection(case, monkeypatch):
  case["permission_policy"]["rules"][1]["operations"].remove("create")
  case["permission_policy"]["rules"].append(file_rule("present-only", "project", ["create"],
    relative_path="currently-existing", match="subtree"))
  def forbidden(*args, **kwargs): raise AssertionError("classification inspected filesystem")
  with monkeypatch.context() as guard:
    for name in ("exists", "is_dir", "is_file", "stat", "iterdir", "resolve"):
      guard.setattr(Path, name, forbidden)
    assert classify_shell_approval(**case) == "human"


@pytest.mark.parametrize("missing", ["system", "all-file"])
def test_declared_roots_do_not_grant_missing_system_or_file_coverage(case, missing):
  case["permission_policy"]["rules"] = [row for row in case["permission_policy"]["rules"]
    if row["kind"] == "command" or missing != "all-file" and row["root_ref"] != "system"]
  assert classify_shell_approval(**case) == "human"


@pytest.mark.parametrize("match,relative,expected", [("exact", ".", "deterministic-policy"),
  ("subtree", ".", "deterministic-policy"), ("exact", "other", "human")])
def test_executable_file_accepts_exact_target_or_subtree_ancestor_read(case, match, relative, expected):
  case["mount_plan"]["mounts"] = [row for row in case["mount_plan"]["mounts"] if row["role"] != "system"]
  case["mount_plan"]["symlinks"] = []
  case["root_paths"]["executable"] = "/usr/bin/bash"
  case["permission_policy"]["rules"] = [row for row in case["permission_policy"]["rules"] if row["id"] != "system"]
  case["permission_policy"]["rules"].append(file_rule("executable", "executable", ["read"], match=match, relative_path=relative))
  assert classify_shell_approval(**case) == expected


def test_same_identity_does_not_make_disjoint_rule_cover_another_mount(case):
  case["mount_plan"]["mounts"].append({"path": "/other", "kind": "directory", "identity": "a" * 64,
    "role": "workspace", "writable": False})
  assert classify_shell_approval(**case) == "human"


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_masks_and_file_denials_cannot_complete_missing_coverage(case, kind):
  case["mount_plan"]["masks"][0]["kind"] = kind
  case["permission_policy"]["rules"][1]["operations"].remove("delete")
  case["permission_policy"]["rules"].append(file_rule("deny-masked", "project", ["delete"], None,
    effect="deny", relative_path="private"))
  assert classify_shell_approval(**case) == "human"


def assert_invalid(case):
  with pytest.raises(ConfigError) as caught: classify_shell_approval(**case)
  assert caught.value.code == "pi-shell-approval-classification"
  assert caught.value.__cause__ is None
  assert caught.value.__suppress_context__
  assert "SYNTHETIC_PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("location", ["policy", "rule", "plan", "mount", "mask", "alias", "cwd", "identity"])
def test_unknown_fields_are_closed_and_error_hides_values(case, location):
  plan = case["mount_plan"]
  value = {"policy": case["permission_policy"], "rule": case["permission_policy"]["rules"][0],
    "plan": plan, "mount": plan["mounts"][0], "mask": plan["masks"][0], "alias": plan["symlinks"][0],
    "cwd": plan["cwd"], "identity": plan["mounts"][-1]["identity"]}[location]
  value["command"] = "SYNTHETIC_PRIVATE"
  assert_invalid(case)


@pytest.mark.parametrize("path", ["relative", "//work/project", "/work//project", "/work/../project", "/work/./project",
  "/work/project/", "/work/back\\slash", "/work/control\x7f", "/work/control\x85", "/work/new\nline", "/work/\ud800", "/" + "a" * 4096])
@pytest.mark.parametrize("location", ["root", "mount", "mask", "alias", "target", "cwd"])
def test_all_absolute_paths_are_bounded_and_canonical(case, path, location):
  if location == "root": case["root_paths"]["project"] = path
  elif location == "mount": case["mount_plan"]["mounts"][0]["path"] = path
  elif location == "mask": case["mount_plan"]["masks"][0]["path"] = path
  elif location == "alias": case["mount_plan"]["symlinks"][0]["path"] = path
  elif location == "target": case["mount_plan"]["symlinks"][0]["target"] = path
  else: case["mount_plan"]["cwd"]["path"] = path
  assert_invalid(case)


def test_exact_absolute_path_length_is_accepted_but_joined_overlong_rule_is_rejected(case):
  case["root_paths"]["long"] = "/" + "a" * 4095
  assert classify_shell_approval(**case) == "deterministic-policy"
  case["permission_policy"]["rules"].append(file_rule("overlong", "long", ["read"], relative_path="child"))
  assert_invalid(case)


@pytest.mark.parametrize("path", ["..", "../escape", "a/../b", "/absolute", "a//b", "a/./b", "a/", "a\\b", "a\x7f", "a\n", "\ud800", "a" * 4097])
def test_file_rule_paths_use_original_relative_path_boundary(case, path):
  case["permission_policy"]["rules"][1]["relative_path"] = path
  assert_invalid(case)


@pytest.mark.parametrize("mutation", ["policy-default", "policy-version", "duplicate-id", "approval-null", "approval-unknown",
  "deny-approval", "rule-operation", "unbound-root", "unbound-deny", "bad-root-id", "roots-list", "command-ref", "check-ref"])
def test_policy_reference_and_original_schema_errors_are_normalized(case, mutation):
  policy, roots = case["permission_policy"], case["root_paths"]
  if mutation == "policy-default": policy["default"] = "allow"
  elif mutation == "policy-version": policy["schema_version"] = True
  elif mutation == "duplicate-id": policy["rules"][1]["id"] = "shell"
  elif mutation == "approval-null": policy["rules"][0]["approval"] = None
  elif mutation == "approval-unknown": policy["rules"][0]["approval"] = "SYNTHETIC_PRIVATE"
  elif mutation == "deny-approval": policy["rules"][1]["effect"] = "deny"
  elif mutation == "rule-operation": policy["rules"][1]["operations"] = ["execute"]
  elif mutation == "unbound-root": policy["rules"][1]["root_ref"] = "absent"
  elif mutation == "unbound-deny": policy["rules"].append(file_rule("unbound", "absent", ["read"], None, effect="deny"))
  elif mutation == "bad-root-id": roots["Bad_ROOT"] = "/other"
  elif mutation == "roots-list": case["root_paths"] = []
  elif mutation == "command-ref": case["command_ref"] = "tool:shell\n"
  else: case["command_ref"] = "check:shell"
  assert_invalid(case)


@pytest.mark.parametrize("mutation", ["missing-executable", "exe-write", "system-write", "unknown-role", "unknown-kind",
  "wrong-platform", "wrong-network", "bool-version", "bad-digest", "cwd-outside", "cwd-mask", "exe-mask",
  "mask-outside", "duplicate-mount", "duplicate-mask", "duplicate-alias", "alias-source", "alias-target",
  "masked-alias", "reserved-mount", "root-mount", "tmp-mount", "identity-path", "identity-int", "identity-sha",
  "mounts-dict", "symlinks-dict", "masks-dict", "null-cwd"])
def test_original_compile_argv_shape_and_security_checks_remain_mandatory(case, mutation):
  plan = case["mount_plan"]
  if mutation == "missing-executable": plan["mounts"].pop()
  elif mutation == "exe-write": plan["mounts"][-1]["writable"] = True
  elif mutation == "system-write": plan["mounts"][1]["writable"] = True
  elif mutation == "unknown-role": plan["mounts"][0]["role"] = "other"
  elif mutation == "unknown-kind": plan["mounts"][0]["kind"] = "other"
  elif mutation == "wrong-platform": plan["platform"] = "darwin-arm64"
  elif mutation == "wrong-network": plan["network"] = "allow"
  elif mutation == "bool-version": plan["schema_version"] = True
  elif mutation == "bad-digest": plan["seccomp_digest"] = "SYNTHETIC_PRIVATE"
  elif mutation == "cwd-outside": plan["cwd"]["path"] = "/outside"
  elif mutation == "cwd-mask": plan["masks"][0]["path"] = plan["cwd"]["path"]
  elif mutation == "exe-mask": plan["masks"][0]["path"] = "/usr/bin/bash"
  elif mutation == "mask-outside": plan["masks"][0]["path"] = "/outside"
  elif mutation == "duplicate-mount": plan["mounts"].append(deepcopy(plan["mounts"][0]))
  elif mutation == "duplicate-mask": plan["masks"].append(deepcopy(plan["masks"][0]))
  elif mutation == "duplicate-alias": plan["symlinks"].append(deepcopy(plan["symlinks"][0]))
  elif mutation == "alias-source": plan["symlinks"][0]["path"] = "/work/project/bin"
  elif mutation == "alias-target": plan["symlinks"][0]["target"] = "/outside"
  elif mutation == "masked-alias": plan["masks"].append({"path": "/usr/lib", "kind": "directory", "identity": "a" * 64}); plan["symlinks"][0]["target"] = "/usr/lib"
  elif mutation == "reserved-mount": plan["mounts"][0]["path"] = "/proc/child"
  elif mutation == "root-mount": plan["mounts"][0]["path"] = "/"
  elif mutation == "tmp-mount": plan["mounts"][0]["path"] = "/tmp"
  elif mutation == "identity-path": plan["mounts"][-1]["identity"]["path"] = "/other/bash"
  elif mutation == "identity-int": plan["mounts"][-1]["identity"]["uid"] = -1
  elif mutation == "identity-sha": plan["mounts"][-1]["identity"]["sha256"] = "invalid"
  elif mutation.endswith("-dict"): plan[mutation.removesuffix("-dict")] = {}
  else: plan["cwd"] = None
  assert_invalid(case)


CALLBACKS = []


class NativeDictSubclass(dict):
  def items(self):
    CALLBACKS.append("dict")
    raise AssertionError("custom dict getter executed")


class NativeListSubclass(list):
  def __iter__(self):
    CALLBACKS.append("list")
    raise AssertionError("custom list iterator executed")


class NativeStringSubclass(str):
  def __str__(self):
    CALLBACKS.append("string")
    raise AssertionError("custom string conversion executed")


class GetterObject:
  @property
  def path(self):
    CALLBACKS.append("getter")
    raise AssertionError("custom getter executed")


@pytest.mark.parametrize("value", [NativeDictSubclass(), NativeListSubclass(), NativeStringSubclass("tool:shell"),
  GetterObject(), (), 1.0, float("nan"), b"SYNTHETIC_PRIVATE", {1: "value"}, 2**53])
def test_non_native_types_and_proxy_equivalents_are_rejected_without_callbacks(case, value):
  CALLBACKS.clear()
  case["root_paths"] = value
  assert_invalid(case)
  assert CALLBACKS == []


@pytest.mark.parametrize("location", ["command", "root", "rule", "identity"])
def test_nested_custom_values_are_rejected_before_callback_or_implicit_conversion(case, location):
  CALLBACKS.clear()
  if location == "command": case["command_ref"] = NativeStringSubclass("tool:shell")
  elif location == "root": case["root_paths"]["project"] = GetterObject()
  elif location == "rule": case["permission_policy"]["rules"][0] = NativeDictSubclass()
  else: case["mount_plan"]["mounts"][-1]["identity"] = NativeListSubclass()
  assert_invalid(case)
  assert CALLBACKS == []


def test_cyclic_and_overdeep_inputs_are_safely_rejected(case):
  cycle = []; cycle.append(cycle)
  case["mount_plan"]["mounts"] = cycle
  assert_invalid(case)
  deep = []
  for _ in range(34): deep = [deep]
  case["mount_plan"]["mounts"] = deep
  assert_invalid(case)


@pytest.mark.parametrize("location", ["rules", "roots", "mounts", "masks", "symlinks"])
def test_collection_capacity_is_4096(case, location):
  if location == "rules": case["permission_policy"]["rules"] = [command_rule("r-" + str(i)) for i in range(4097)]
  elif location == "roots": case["root_paths"] = {"r-" + str(i): "/other" for i in range(4097)}
  else: case["mount_plan"][location] = [None] * 4097
  assert_invalid(case)


def test_exact_rule_capacity_is_accepted_without_overflowing_grade_aggregator(case):
  case["permission_policy"]["rules"] += [command_rule("extra-" + str(i)) for i in range(4093)]
  assert len(case["permission_policy"]["rules"]) == 4096
  assert classify_shell_approval(**case) == "deterministic-policy"


def test_exact_root_capacity_is_accepted(case):
  case["root_paths"].update({"extra-" + str(i): "/unused" for i in range(4094)})
  assert classify_shell_approval(**case) == "deterministic-policy"


def test_aggregate_json_input_capacity_is_one_mib(case):
  case["permission_policy"]["rules"][0]["tool_ids"] = ["tool-" + str(i) for i in range(100000)]
  assert len(json.dumps(case).encode()) > 1024 * 1024
  assert_invalid(case)


def test_pure_classification_performs_no_filesystem_write_fd_process_or_model_activity(case, monkeypatch):
  from agentcfg import pi_shell_approval
  from agentcfg.activity import ExecutionStore
  from agentcfg.storage import Tree
  before = deepcopy(case)
  def forbidden(*args, **kwargs): raise AssertionError("classification performed side effect")
  with monkeypatch.context() as guard:
    for name in ("open", "close", "fstat", "dup", "write", "read", "memfd_create", "stat", "lstat", "scandir"):
      guard.setattr(os, name, forbidden)
    guard.setattr(Path, "write_bytes", forbidden)
    guard.setattr(Path, "write_text", forbidden)
    guard.setattr(subprocess, "Popen", forbidden)
    guard.setattr(Tree, "write_state", forbidden)
    guard.setattr(ExecutionStore, "allocate", forbidden)
    original = pi_shell_approval.compile_argv
    calls = []
    def compiler(plan, **descriptors):
      values = [*descriptors["source_fds"].values(), *descriptors["mask_fds"].values(),
        descriptors["script_fd"], descriptors["seccomp_fd"]]
      assert all(type(fd) is int and fd > 2 for fd in values)
      assert len(values) == len(set(values))
      calls.append((plan, descriptors))
      return original(plan, **descriptors)
    guard.setattr(pi_shell_approval, "compile_argv", compiler)
    assert classify_shell_approval(**case) == "deterministic-policy"
    assert len(calls) == 1 and calls[0][0] is not case["mount_plan"]
    assert case == before
