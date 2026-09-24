"""普通工具的实际文件IO复用同一权限与写租约，所有进程仅用替身。"""

from copy import deepcopy
from types import SimpleNamespace
import base64
from pathlib import Path
import pytest

from agentcfg.pi_operations import OrdinaryOperations
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict
from test_pi_delegate import fixture
from test_pi_activity import identity


def setup(tmp_path):
  _, host, args, _ = fixture(tmp_path)
  policy = host.manifest()["permission_policy"]
  policy["rules"] = [{"id": "project", "kind": "file", "effect": "allow", "root_ref": "project", "relative_path": ".", "match": "subtree",
    "tool_ids": ["read", "write", "edit"], "operations": ["read", "write", "create"]}]
  host.manifest()["role_bindings"] = {"scout": {"managed": False, "tools": ["read"], "read_roots": ["project"], "write_roots": []}}
  parent = host.store.allocate(kind="host", execution_id="parent", task_id=None, attempt_id="parent", lock_identity="a" * 64,
    slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest=None, planned_workspaces=[])
  host.store.processes.current[202] = identity(202)
  host.store.start(parent["lease_id"], host.store.owner, spawn=lambda _: identity(202))
  principal = Principal("manager", parent["lease_id"], parent["grant_generation"])
  return OrdinaryOperations(host), host, args["cwd"], principal


def test_ordinary_read_requires_declared_root_and_cannot_be_reclassified_as_managed(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  request = {"operation_id": "read", "role_id": "scout", "cwd": cwd, "tool_name": "read", "input": {"path": "code.txt"}}
  ticket = operations.prepare(principal, request)
  assert base64.b64decode(operations.read(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})["data_b64"]) == b"source"
  with pytest.raises(Conflict):
    operations.prepare(principal, {**request, "operation_id": "write", "tool_name": "write", "input": {"path": "code.txt", "content": "forbidden"}})
  with pytest.raises(Conflict):
    operations.prepare(Principal("worker"), request)


def test_ordinary_source_write_uses_real_workspace_lease_and_durable_io_intent(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  request = {"operation_id": "write", "role_id": "main", "cwd": cwd, "tool_name": "write", "input": {"path": "new.txt", "content": "new business file"}}
  ticket = operations.prepare(principal, request)
  lease = host.store.read(ticket["lease_id"])
  assert lease["planned_workspaces"] and lease["state"] == "allocating"
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  operations.stage_write(principal, {"operation_id": ticket["operation_id"], "content": "new business file", "expected_digest": None})
  host.store.processes.current[203] = identity(203)
  host.store.start(lease["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  result = operations.perform(Principal("worker", lease["lease_id"], lease["grant_generation"]), {"operation_id": ticket["operation_id"]})
  assert result["changed"] and (Path(cwd) / "new.txt").read_text() == "new business file"
  host.store.request_cancel(lease["lease_id"], host.store.owner)
  with pytest.raises(Conflict):
    operations.perform(Principal("worker", lease["lease_id"], lease["grant_generation"]), {"operation_id": ticket["operation_id"]})
  # 普通操作可以写原业务checkout；没有借用Task Keeper的task grant或候选假设。
  assert operations.record(ticket["operation_id"])["grant"]["execution_mode"] == "ordinary"


def test_directory_search_respects_explicit_roots_denials_and_project_ignore(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["permission_policy"]["rules"][0].update(tool_ids=["read", "write", "edit", "ls", "find", "grep"], operations=["read", "write", "create", "list", "search"])
  root = Path(cwd); (root / "src").mkdir(); (root / "src/a.ts").write_text("source")
  (root / "node_modules").mkdir(); (root / "node_modules/ignored.ts").write_text("ignored")
  (root / ".gitignore").write_text("node_modules/\n")
  (root / "escape").symlink_to(tmp_path)
  ticket = operations.prepare(principal, {"operation_id": "find", "role_id": "main", "cwd": cwd, "tool_name": "find", "input": {"pattern": "**/*.ts"}})
  result = operations.listing(principal, {"operation_id": ticket["operation_id"]})
  assert result == {"entries": [{"path": "src/a.ts", "directory": False}], "truncated": False}


def test_expired_unused_approval_releases_reservation_without_starting_a_process(tmp_path):
  from datetime import datetime, timedelta, timezone
  operations, host, cwd, principal = setup(tmp_path)
  now = datetime.now(timezone.utc)
  operations.now = lambda: now
  ticket = operations.prepare(principal, {"operation_id": "expires", "role_id": "main", "cwd": cwd,
    "tool_name": "write", "input": {"path": "new.txt", "content": "never written"}})
  lease = host.store.read(ticket["lease_id"])
  now += timedelta(seconds=301)
  with pytest.raises(Conflict, match="GRANT_STALE"):
    operations.stage_write(principal, {"operation_id": ticket["operation_id"], "content": "never written", "expected_digest": None})
  operations.tick()
  assert not (Path(cwd) / "new.txt").exists()
  assert host.store.read(ticket["lease_id"])["state"] == "failed"
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "released"
  assert not operations.inputs


def test_rename_checks_both_paths_and_requires_explicit_rename_permission(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  request = {"operation_id": "rename-denied", "role_id": "main", "cwd": cwd, "tool_name": "rename", "input": {"path": "code.txt", "destination": "renamed.txt"}}
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    operations.prepare(principal, request)
  assert (Path(cwd) / "code.txt").read_text() == "source"
  policy = host.manifest()["permission_policy"]
  policy["rules"][0]["operations"].append("rename")
  policy["rules"].append({"id": "deny-destination", "kind": "file", "effect": "deny", "tool_ids": ["edit"], "operations": ["rename"],
    "root_ref": "project", "relative_path": "denied.txt", "match": "exact"})
  with pytest.raises(Conflict, match="PERMISSION_DENIED"):
    operations.prepare(principal, {**request, "operation_id": "destination-denied", "input": {"path": "code.txt", "destination": "denied.txt"}})
  ticket = operations.prepare(principal, {**request, "operation_id": "rename-approved"})
  lease = host.store.read(ticket["lease_id"])
  assert len(lease["planned_workspaces"]) == 1
  host.store.processes.current[203] = identity(203)
  host.store.start(lease["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  result = operations.perform(Principal("worker", lease["lease_id"], lease["grant_generation"]), {"operation_id": ticket["operation_id"]})
  assert result == {"renamed": True}
  assert not (Path(cwd) / "code.txt").exists()
  assert (Path(cwd) / "renamed.txt").read_text() == "source"


def test_selected_skill_is_readable_without_exposing_private_instance_siblings(tmp_path):
  from agentcfg.deployment import json_bytes
  from agentcfg.pi_resource_reads import tree_digest
  from agentcfg.storage import Tree
  operations, host, cwd, principal = setup(tmp_path)
  root = Path(host.config["instance_root"])
  with Tree(root, create=True) as tree:
    tree.write_state("pi-home/skills/fixture/SKILL.md", b"# fixture instructions")
    tree.write_state("pi-home/auth.json", b"synthetic private account sentinel")
  skill = root / "pi-home/skills/fixture"
  host.manifest()["resources"] = {"skills": ["pi-home/skills/fixture"]}
  with Tree(root) as tree: tree.write_state("pi-home/loaded-manifest.json", json_bytes({"resources": {"skills": [{"id": "fixture", "path": str(skill), "digest": tree_digest(skill), "scope": "instance"}]}}))
  request = {"operation_id": "skill", "role_id": "main", "cwd": cwd, "tool_name": "read", "input": {"path": str(skill / "SKILL.md")}}
  ticket = operations.prepare(principal, request)
  data = operations.read(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  assert base64.b64decode(data["data_b64"]) == b"# fixture instructions"
  with pytest.raises(Conflict): operations.prepare(principal, {**request, "operation_id": "account", "input": {"path": str(root / "pi-home/auth.json")}})
  (skill / "SKILL.md").write_bytes(b"changed after loading")
  with pytest.raises(Conflict): operations.read(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  assert (root / "pi-home/auth.json").read_bytes() == b"synthetic private account sentinel"
