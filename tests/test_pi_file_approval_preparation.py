"""原临时File bridge准备/消费的审批绑定；无SDK或实际进程。"""
from copy import deepcopy
from pathlib import Path
import hashlib

import pytest

from agentcfg.storage import Conflict
from test_pi_admitted_files import fixture, prepare, issue, no_writer, external


def test_legacy_rule_preparation_has_explicit_human_approval(tmp_path):
  f = fixture(tmp_path)
  prepared = prepare(f, tool="read")
  assert prepared["resolution"]["policy"]["approval"] == "human"
  assert prepared["resolution"]["policy"]["requires_human"] is True
  no_writer(f)


def rule(id="allow", *, operations=("read", "write", "create"), tools=("read", "write", "edit"), approval="deterministic-policy", path=".", match="subtree", effect="allow"):
  result = {"id": id, "kind": "file", "effect": effect, "root_ref": "project", "relative_path": path,
    "match": match, "tool_ids": list(tools), "operations": list(operations)}
  if approval is not None: result["approval"] = approval
  return result


def set_rules(f, *rules):
  f[2].manifest()["permission_policy"]["rules"] = list(rules)


def assert_mode(prepared, mode):
  policy = prepared["resolution"]["policy"]
  assert policy["approval"] == mode
  assert policy["requires_human"] is (mode == "human")


@pytest.mark.parametrize("tool,payload", [
  ("read", {"path": "code.txt"}), ("write", {"path": "code.txt", "content": "approved"}),
  ("write", {"path": "new.txt", "content": "approved"}),
])
def test_explicit_deterministic_read_and_write_create_are_bound_and_consumed_once(tmp_path, tool, payload):
  f = fixture(tmp_path); set_rules(f, rule())
  prepared = prepare(f, tool=tool, payload=payload)
  assert_mode(prepared, "deterministic-policy")
  no_writer(f)
  permit = issue(f, prepared, source="deterministic-policy")
  assert permit["operation_digest"] == prepared["operation_digest"]
  ticket = f[0].consume(f[4], permit)
  assert ticket["state"] == "consumed"
  with pytest.raises(Conflict): f[0].consume(f[4], permit)
  with pytest.raises(Conflict): issue(f, prepared, source="deterministic-policy")
  assert len(external(f[2])) == (0 if tool == "read" else 1)


@pytest.mark.parametrize("read_mode,write_mode,expected", [
  ("human", "deterministic-policy", "human"), ("deterministic-policy", "reviewer", "reviewer"),
  ("deterministic-policy", "deterministic-policy", "deterministic-policy"),
])
def test_edit_aggregates_original_read_and_write_grades(tmp_path, read_mode, write_mode, expected):
  f = fixture(tmp_path)
  set_rules(f, rule("read", operations=("read",), approval=read_mode), rule("write", operations=("write",), approval=write_mode))
  prepared = prepare(f, tool="edit", payload={"path": "code.txt", "edits": [{"oldText": "source", "newText": "edited"}]})
  assert_mode(prepared, expected); no_writer(f)


@pytest.mark.parametrize("source,destination,expected", [
  ("human", "deterministic-policy", "human"), ("deterministic-policy", "reviewer", "reviewer"),
  ("deterministic-policy", "deterministic-policy", "deterministic-policy"),
])
def test_rename_aggregates_both_paths(tmp_path, source, destination, expected):
  f = fixture(tmp_path)
  set_rules(f, rule("source", operations=("rename",), path="code.txt", match="exact", approval=source),
    rule("destination", operations=("rename",), path="renamed.txt", match="exact", approval=destination))
  prepared = prepare(f, tool="rename", payload={"path": "code.txt", "destination": "renamed.txt"})
  assert_mode(prepared, expected); no_writer(f)


@pytest.mark.parametrize("existing", [True, False])
def test_manual_create_on_target_prevents_deterministic_write_even_when_existing(tmp_path, existing):
  f = fixture(tmp_path)
  if not existing: (Path(f[3]) / "code.txt").unlink()
  set_rules(f, rule("overwrite", operations=("write",)),
    rule("create", operations=("create",), approval="human", path="code.txt", match="exact"))
  prepared = prepare(f, payload={"path": "code.txt", "content": "approved"})
  assert_mode(prepared, "human"); no_writer(f)


@pytest.mark.parametrize("existing", [True, False])
def test_manual_create_on_intermediate_parent_is_always_aggregated(tmp_path, existing):
  f = fixture(tmp_path); root = Path(f[3])
  (root / "nested").mkdir(); (root / "nested/child").mkdir()
  if existing: (root / "nested/child/output.txt").write_text("old")
  set_rules(f, rule("write", operations=("write",)), rule("create", operations=("create",)),
    rule("manual-parent", operations=("create",), approval="human", path="nested", match="exact"))
  prepared = prepare(f, payload={"path": "nested/child/output.txt", "content": "approved"})
  assert_mode(prepared, "human"); no_writer(f)


@pytest.mark.parametrize("tool", ["ls", "find", "grep"])
def test_enumeration_keeps_human_floor(tmp_path, tool):
  f = fixture(tmp_path); set_rules(f, rule(operations=("read", "list", "search"), tools=("ls", "find", "grep")))
  payload = {"path": "."} if tool == "ls" else {"path": ".", "pattern": "source"}
  assert_mode(prepare(f, tool=tool, payload=payload), "human"); no_writer(f)


def start_and_perform_write(f, ticket):
  from agentcfg.pi_supervisor import Principal
  from test_pi_activity import identity
  f[1].stage_write(f[4], {"operation_id": ticket["operation_id"], "content": "approved", "expected_digest": None})
  lease = f[2].store.read(ticket["lease_id"])
  f[2].store.processes.current[203] = identity(203)
  f[2].store.start(ticket["lease_id"], f[2].store.owner, spawn=lambda _: identity(203))
  worker = Principal("worker", ticket["lease_id"], lease["grant_generation"])
  return f[1].perform(worker, {"operation_id": ticket["operation_id"]})


@pytest.mark.parametrize("remove_after_consume", [False, True])
def test_write_only_without_create_is_human_and_io_keeps_create_hard_denial(tmp_path, remove_after_consume):
  f = fixture(tmp_path); set_rules(f, rule(operations=("write",)))
  prepared = prepare(f, payload={"path": "code.txt", "content": "approved"})
  assert_mode(prepared, "human")
  ticket = f[0].consume(f[4], issue(f, prepared))
  if remove_after_consume:
    (Path(f[3]) / "code.txt").unlink()
    with pytest.raises(Conflict, match="PERMISSION_DENIED"): start_and_perform_write(f, ticket)
    assert not (Path(f[3]) / "code.txt").exists()
  else:
    assert start_and_perform_write(f, ticket)["changed"] is True
    assert (Path(f[3]) / "code.txt").read_text() == "approved"
  assert len(external(f[2])) == 1
  with pytest.raises(Conflict): f[0].consume(f[4], issue(f, prepared))


def test_selected_resource_read_remains_human(tmp_path):
  from agentcfg.storage import Tree
  from agentcfg.deployment import json_bytes
  from agentcfg.pi_resource_reads import tree_digest
  f = fixture(tmp_path); set_rules(f, rule())
  root = Path(f[2].config["instance_root"])
  with Tree(root, create=True) as tree: tree.write_state("pi-home/skills/fixture/SKILL.md", b"# synthetic skill")
  skill = root / "pi-home/skills/fixture"
  f[2].manifest()["resources"] = {"skills": ["pi-home/skills/fixture"]}
  with Tree(root) as tree:
    tree.write_state("pi-home/loaded-manifest.json", json_bytes({"resources": {"skills": [
      {"id": "fixture", "path": str(skill), "digest": tree_digest(skill), "scope": "instance"}]}}))
  prepared = prepare(f, tool="read", payload={"path": str(skill / "SKILL.md")})
  assert_mode(prepared, "human"); no_writer(f)


@pytest.mark.parametrize("change", ["mode", "deny", "ceiling"])
def test_consume_fresh_refuses_policy_or_ceiling_drift_before_writer(tmp_path, change):
  f = fixture(tmp_path); set_rules(f, rule())
  prepared = prepare(f); permit = issue(f, prepared, source="deterministic-policy")
  if change == "mode": f[2].manifest()["permission_policy"]["rules"][0]["approval"] = "human"
  elif change == "deny": f[2].manifest()["permission_policy"]["rules"][0].update(effect="deny"); f[2].manifest()["permission_policy"]["rules"][0].pop("approval")
  else: f[2].manifest()["options"]["paths"]["roots"]["project"]["purpose"] = "read"
  with pytest.raises(Conflict): f[0].consume(f[4], permit)
  no_writer(f)
  with pytest.raises(Conflict): f[0].consume(f[4], permit)


def test_default_classification_does_not_expand_role_tool_ceiling(tmp_path):
  f = fixture(tmp_path)
  f[5]["role_id"] = "scout"
  with pytest.raises(Conflict): prepare(f)
  no_writer(f)
