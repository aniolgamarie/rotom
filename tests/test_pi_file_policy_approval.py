"""实际FilePolicy授权后的分类，保持原根/deny/租约边界。"""
from copy import deepcopy
from itertools import permutations

import pytest

from agentcfg.pi_guarded_files import FilePolicy, root_identity
from agentcfg.storage import Conflict
from test_pi_guarded_files import fixture


MISSING = object()


def compiled(tmp_path, approval=MISSING, *, extra=(), deep=False, broad_in_ceiling=True, workspace=True, **options):
  root, files, state, calls = fixture(tmp_path)
  original = files.policy
  policy = deepcopy(original.policy)
  if approval is not MISSING: policy["rules"][0]["approval"] = approval
  policy["rules"].extend(extra)
  roots, ceiling, grant = map(deepcopy, (original.roots, original.ceiling, original.grant))
  if deep:
    roots["source"] = {"path": str(root / "src"), "identity": root_identity(root / "src")}
    for value in (ceiling, grant):
      value["read_roots"] = ["project", "source"] if broad_in_ceiling else ["source"]
      value["write_roots"] = value["read_roots"][:]
  target = FilePolicy(policy=policy, roots=roots, ceiling=ceiling, grant=grant, mode="managed",
    verify=lambda *args: state["valid"], workspace=lambda *args: workspace, **options)
  return root, target, state


def allow(id="deep", approval="deterministic-policy", *, root="source", tools=("tk_read",), operations=("read",), path="."):
  return {"id": id, "kind": "file", "effect": "allow", "approval": approval, "tool_ids": list(tools),
    "operations": list(operations), "root_ref": root, "relative_path": path, "match": "subtree"}


def test_authorized_target_reports_explicit_approval(tmp_path):
  root, policy, _ = compiled(tmp_path, "reviewer")
  assert policy.authorize("read", "read", root / "src/a.txt")["approval"] == "reviewer"


@pytest.mark.parametrize("approval", [MISSING, "human", "reviewer", "deterministic-policy"])
def test_single_rule_and_legacy_default_are_classified_without_extra_authority(tmp_path, approval):
  root, policy, _ = compiled(tmp_path, approval)
  target = policy.authorize("read", "read", root / "src/a.txt")
  assert target["approval"] == ("human" if approval is MISSING else approval)
  assert set(target) == {"root_ref", "relative_path", "root", "path", "approval"}
  assert target["root_ref"] == "project" and target["relative_path"] == "src/a.txt"


@pytest.mark.parametrize("broad_in_ceiling", [True, False])
def test_broad_human_rule_survives_deeper_root_and_ceiling_filter(tmp_path, broad_in_ceiling):
  root, policy, _ = compiled(tmp_path, "human", extra=[allow()], deep=True, broad_in_ceiling=broad_in_ceiling)
  before = deepcopy(policy.policy)
  target = policy.authorize("read", "read", root / "src/a.txt")
  assert target["root_ref"] == "source" and target["relative_path"] == "a.txt"
  assert target["approval"] == "human" and policy.policy == before


@pytest.mark.parametrize("order", list(permutations(("human", "reviewer", "deterministic-policy"))))
def test_matching_rules_aggregate_independent_of_order(tmp_path, order):
  root, policy, _ = compiled(tmp_path, "deterministic-policy")
  policy.policy["rules"] = [allow("r" + str(i), mode, root="project", path="src") for i, mode in enumerate(order)]
  assert policy.authorize("read", "read", root / "src/a.txt")["approval"] == "human"


@pytest.mark.parametrize("extra", [
  allow("write-only", "human", root="project", tools=("tk_write",), operations=("write",), path="src"),
  allow("different-operation", "human", root="project", operations=("search",), path="src"),
  allow("different-path", "human", root="project", path="src2"),
])
def test_unmatched_tool_operation_or_target_does_not_raise_classification(tmp_path, extra):
  root, policy, _ = compiled(tmp_path, "deterministic-policy", extra=[extra])
  assert policy.authorize("read", "read", root / "src/a.txt")["approval"] == "deterministic-policy"


@pytest.mark.parametrize("operation", ["list", "search"])
def test_explicit_subtree_enumeration_can_keep_deterministic_approval(tmp_path, operation):
  root, policy, _ = compiled(tmp_path, "deterministic-policy")
  policy.policy["rules"][0]["operations"].append(operation)
  assert policy.authorize("read", operation, root / "src")["approval"] == "deterministic-policy"


@pytest.mark.parametrize("operation", ["list", "search"])
@pytest.mark.parametrize("approval", ["human", "reviewer"])
def test_enumeration_aggregates_stricter_potential_descendant_without_listing(tmp_path, operation, approval, monkeypatch):
  root, policy, _ = compiled(tmp_path, "deterministic-policy", extra=[allow("child", approval, root="project", operations=(operation,), path="src/future")])
  policy.policy["rules"][0]["operations"].append(operation)
  with monkeypatch.context() as patch:
    patch.setattr("agentcfg.pi_guarded_files.os.listdir", lambda *_: pytest.fail("classification must not enumerate"))
    assert policy.authorize("read", operation, root / "src")["approval"] == approval
  assert not (root / "src/future").exists()


@pytest.mark.parametrize("operation", ["list", "search"])
def test_exact_root_rule_does_not_implicitly_approve_subtree(tmp_path, operation):
  root, policy, _ = compiled(tmp_path, "deterministic-policy")
  policy.policy["rules"][0].update(match="exact", operations=[operation])
  assert policy.authorize("read", operation, root / "src")["approval"] == "human"


def test_unproven_external_stricter_rule_keeps_enumeration_human(tmp_path):
  root, policy, _ = compiled(tmp_path, "deterministic-policy", extra=[allow("sibling", "reviewer", root="project", operations=("search",), path="src2")])
  policy.policy["rules"][0]["operations"].append("search")
  assert policy.authorize("read", "search", root / "src")["approval"] == "human"


@pytest.mark.parametrize("ceiling,required,accepted", [
  ("deterministic-policy", "human", False), ("deterministic-policy", "reviewer", False),
  ("reviewer", "human", False), ("reviewer", "deterministic-policy", True),
  ("human", "reviewer", True), ("human", "deterministic-policy", True),
])
def test_consumed_approval_ceiling_is_checked_at_actual_authorization(tmp_path, ceiling, required, accepted):
  root, policy, _ = compiled(tmp_path, required, approval_ceiling=ceiling)
  if accepted:
    assert policy.authorize("read", "read", root / "src/a.txt")["approval"] == required
  else:
    with pytest.raises(Conflict, match="OPERATION_APPROVAL_REQUIRED"):
      policy.authorize("read", "read", root / "src/a.txt")


def test_late_stricter_child_aborts_search_before_reading_its_body(tmp_path, monkeypatch):
  from agentcfg.pi_guarded_files import GuardedFiles
  root, policy, _ = compiled(tmp_path, "deterministic-policy", approval_ceiling="deterministic-policy")
  policy.policy["rules"][0]["operations"].append("search")
  original = policy.authorize
  def late(tool, operation, path):
    if str(path).endswith("a.txt"):
      policy.policy["rules"].append(allow("late", "human", root="project", operations=("search",), path="src/a.txt"))
    return original(tool, operation, path)
  monkeypatch.setattr(policy, "authorize", late)
  files = GuardedFiles(policy, mutation=lambda *_: pytest.fail("readonly search must not mutate"))
  monkeypatch.setattr(files, "read", lambda *_args, **_kwargs: pytest.fail("stricter child body must not be read"))
  with pytest.raises(Conflict, match="OPERATION_APPROVAL_REQUIRED"):
    files.search("read", root / "src", "original", "grep")


@pytest.mark.parametrize("operation,tool", [("read", "read"), ("write", "write"), ("create", "write"), ("delete", "write"), ("rename", "edit")])
def test_direct_targets_can_keep_explicit_deterministic_policy(tmp_path, operation, tool):
  root, policy, _ = compiled(tmp_path, "deterministic-policy")
  if operation not in policy.policy["rules"][0]["operations"]:
    policy.policy["rules"][0]["operations"].append(operation)
  assert policy.authorize(tool, operation, root / "src/a.txt")["approval"] == "deterministic-policy"


@pytest.mark.parametrize("failure", ["deny", "ceiling", "grant", "workspace", "stale", "git", "protected", "readonly", "denied"])
def test_classification_cannot_bypass_original_authorization(failure, tmp_path):
  root, policy, state = compiled(tmp_path, "deterministic-policy")
  tool, operation, path = "write", "write", root / "src/a.txt"
  if failure == "deny":
    deny = {**policy.policy["rules"][0], "id": "deny", "effect": "deny"}; deny.pop("approval")
    policy.policy["rules"].append(deny)
  elif failure == "ceiling": policy.ceiling["write_roots"] = []
  elif failure == "grant": policy.grant["write_roots"] = []
  elif failure == "workspace": policy.workspace = lambda *args: False
  elif failure == "stale": state["valid"] = False
  elif failure == "git": path = root / "src/.git/config"
  elif failure == "protected": policy.secrets = (root / "src",)
  elif failure == "readonly": policy.readonly.add("project")
  elif failure == "denied": policy.denied.add("project")
  with pytest.raises(Conflict): policy.authorize(tool, operation, path)
  assert (root / "src/a.txt").read_text() == "original"


def test_nonlexical_physical_root_alias_cannot_hide_human_rule(tmp_path, monkeypatch):
  from agentcfg import pi_guarded_files
  root, policy, _ = compiled(tmp_path, "deterministic-policy")
  alias = tmp_path / "physical-alias"; alias.mkdir()
  policy.roots["alias"] = {"path": str(alias), "identity": root_identity(alias)}
  policy.policy["rules"].append(allow("alias-human", "human", root="alias"))
  original_same_object = pi_guarded_files.same_object
  # 模拟两条独立字面路径指向同目录inode；不创建或跟随业务symlink。
  def same_object(left, right):
    if {left, right} == {root / "src", alias}: return True
    return original_same_object(left, right)
  monkeypatch.setattr(pi_guarded_files, "same_object", same_object)
  target = policy.authorize("read", "read", root / "src/a.txt")
  assert target["root_ref"] == "project" and target["approval"] == "human"


def test_deny_precedes_even_human_aggregation(tmp_path, monkeypatch):
  from agentcfg import pi_policy_approval
  root, policy, _ = compiled(tmp_path, "deterministic-policy")
  deny = {**policy.policy["rules"][0], "id": "deny", "effect": "deny"}; deny.pop("approval")
  policy.policy["rules"].append(deny)
  monkeypatch.setattr(pi_policy_approval, "aggregate_approval", lambda _: pytest.fail("denied target must never be classified"))
  with pytest.raises(Conflict, match="PERMISSION_DENIED"): policy.authorize("read", "read", root / "src/a.txt")
