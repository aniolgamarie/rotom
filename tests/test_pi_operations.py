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


def setup(tmp_path, *, plugins=(), resources=()):
  _, host, args, _ = fixture(tmp_path)
  host.manifest()["plugins"] = list(plugins)
  host.manifest()["resource_ids"] = {"extensions": {name: "synthetic-selected-path" for name in resources}}
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
  host.manifest()["resource_ids"]["skills"] = {"fixture": "pi-home/skills/fixture"}
  with Tree(root) as tree: tree.write_state("pi-home/loaded-manifest.json", json_bytes({"resources": {"skills": [{"id": "fixture", "path": str(skill), "digest": tree_digest(skill), "scope": "instance"}]}}))
  request = {"operation_id": "skill", "role_id": "main", "cwd": cwd, "tool_name": "read", "input": {"path": str(skill / "SKILL.md")}}
  ticket = operations.prepare(principal, request)
  data = operations.read(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  assert base64.b64decode(data["data_b64"]) == b"# fixture instructions"
  with pytest.raises(Conflict): operations.prepare(principal, {**request, "operation_id": "account", "input": {"path": str(root / "pi-home/auth.json")}})
  (skill / "SKILL.md").write_bytes(b"changed after loading")
  with pytest.raises(Conflict): operations.read(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
  assert (root / "pi-home/auth.json").read_bytes() == b"synthetic private account sentinel"


def base_fixture(tmp_path, *, allow=False):
  """真正解析Base选择；只借原store/worktree替身，不构造Full controller/包。"""
  import json
  from agentcfg.pi import PiAdapter
  from agentcfg.pi_admitted_files import FileOperationAdmissions
  from agentcfg.pi_supervisor import SupervisorService
  from agentcfg.workspace_leases import WorkspaceLeases
  from test_pi_activity import make_store
  from test_pi_operation_admission import fixture as context_fixture
  from test_pi_profile_projection import resolved
  from test_pi_workspace_leases import worktree
  from test_pi_adapter import ROOT

  source = worktree(tmp_path); (source / "code.txt").write_text("source")
  data = resolved({"agent_options": {"paths": {"roots": {"project": {"path": str(source), "purpose": "project"}}}}})
  # 正控是显式自有测试策略，不把Base默认deny声称为自动Writer许可。
  if allow:
    data["adapter_documents"]["agent"]["policies"]["project-default"]["rules"] = [{"id": "own-project", "kind": "file", "effect": "allow",
      "root_ref": "project", "relative_path": ".", "match": "subtree", "tool_ids": ["read", "write", "edit", "ls", "find", "grep"],
      "operations": ["read", "write", "create", "list", "search"]}]
  adapter = PiAdapter(ROOT); adapter.validate(data)
  manifest = json.loads(next(row.content for row in adapter.render(data) if row.target.path == "pi-home/agentcfg-manifest.json"))
  store, processes = make_store(tmp_path / "controller"); store.workspaces = WorkspaceLeases("fixture-boot")
  runtime = tmp_path / ("c" * 64); runtime.mkdir(); instance = tmp_path / "instance"; instance.mkdir()
  host = SimpleNamespace(store=store, root=store.root, runtime_root=runtime, manifest=lambda: manifest,
    config={"instance_root": str(instance), "lock_identity": "a" * 64, "slice_identity": "b" * 64})
  def no_spawn(*_): raise AssertionError("ordinary baseline must not launch any process")
  host.service = SupervisorService(store, no_spawn, no_spawn)
  operations = OrdinaryOperations(host); host.service.ordinary_handler = operations.handle
  parent = store.allocate(kind="host", execution_id="parent", task_id=None, attempt_id="parent", lock_identity="a" * 64,
    slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest=None, planned_workspaces=[])
  processes.current[202] = identity(202); store.start(parent["lease_id"], store.owner, spawn=lambda _: identity(202))
  principal = Principal("manager", parent["lease_id"], parent["grant_generation"])
  current = context_fixture()[1]; current.update(activation_id=store.owner["manager_activation_id"], profile="pi-base", cwd=str(source),
    runtime_identity=runtime.name, deadline_ms=int(operations.now().timestamp() * 1000) + 60000)
  bridge = FileOperationAdmissions(operations, context_provider=lambda _: deepcopy(current))
  assert manifest["profile_id"] == "pi-base" and set(manifest["plugins"]) == {"pi-todo", "loop-guard", "colorful-footer"}
  assert manifest["role_bindings"] == {} and manifest["resources"]["roles"] == []
  assert not {"task_keeper", "model_delegate", "processes", "agent_state"} & manifest["options"].keys()
  assert operations.checkpoints is operations.readseek is operations.web_browser is operations.web_files is None
  assert host.service.delegate_handler is None
  assert not list(runtime.iterdir())
  return bridge, operations, host, source, principal


def base_admit(f, request_id, tool, payload):
  bridge, _, _, _, principal = f
  prepared = bridge.prepare(principal, request_id, tool, payload)
  permit = bridge.issue(principal, prepared["operation_id"], operation_digest=prepared["operation_digest"], source="human")
  return bridge.consume(principal, permit)


def base_writer(f, ticket, content, expected=None):
  _, operations, host, _, principal = f
  lease = host.store.read(ticket["lease_id"])
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  operations.stage_write(principal, {"operation_id": ticket["operation_id"], "content": content, "expected_digest": expected})
  host.store.processes.current[203] = identity(203)
  host.store.start(lease["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "active"
  return Principal("worker", lease["lease_id"], lease["grant_generation"])


def test_resolved_base_default_policy_denies_ordinary_io_without_full_services(tmp_path):
  f = base_fixture(tmp_path)
  for tool, payload in [("read", {"path": "code.txt"}), ("write", {"path": "new.txt", "content": "blocked"}),
      ("find", {"pattern": "*.txt"}), ("edit", {"path": "code.txt", "edits": []})]:
    with pytest.raises(Conflict, match="PERMISSION_DENIED"):
      base_admit(f, "denied-" + tool, tool, payload)
  assert not [row for row in f[2].store.records() if row["kind"] == "external"]
  assert not (f[3] / "new.txt").exists() and (f[3] / "code.txt").read_text() == "source"


def test_resolved_base_explicit_project_io_uses_original_admissions_and_workspace_writer(tmp_path):
  import hashlib
  f = base_fixture(tmp_path, allow=True); _, operations, host, root, principal = f
  ticket = base_admit(f, "read", "read", {"path": "code.txt"})
  assert base64.b64decode(operations.read(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})["data_b64"]) == b"source"
  for tool, payload in [("ls", {}), ("find", {"pattern": "**/*.txt"}), ("grep", {"pattern": "source"})]:
    ticket = base_admit(f, tool, tool, payload)
    assert operations.listing(principal, {"operation_id": ticket["operation_id"]})["entries"] == [{"path": "code.txt", "directory": False}]
    if tool == "grep": assert base64.b64decode(operations.read(principal, {"operation_id": ticket["operation_id"], "relative_path": "code.txt", "offset": 0, "limit": 65536})["data_b64"]) == b"source"
  assert not [row for row in host.store.records() if row["kind"] == "external"]
  for tool, path, content, expected in [("write", "new.txt", "new", None), ("edit", "code.txt", "edited", hashlib.sha256(b"source").hexdigest())]:
    payload = {"path": path, "content": content} if tool == "write" else {"path": path, "edits": [{"oldText": "source", "newText": "edited"}]}
    ticket = base_admit(f, tool, tool, payload); worker = base_writer(f, ticket, content, expected)
    assert operations.perform(worker, {"operation_id": ticket["operation_id"]})["changed"] is True
    assert (root / path).read_text() == content
    host.store.processes.current.pop(203); assert host.store.finish(ticket["lease_id"], host.store.owner)["state"] == "reclaimed"
  assert host.store.processes.signals == []


@pytest.mark.parametrize("tool", ["read", "find", "write", "edit"])
def test_resolved_base_io_errors_propagate_as_fixed_control_failure_without_success_or_mutation(tmp_path, monkeypatch, tool):
  import errno
  import hashlib
  import os
  from agentcfg.storage import Tree
  from test_pi_supervisor import request
  f = base_fixture(tmp_path, allow=True); _, operations, host, root, principal = f
  payload = {"path": "code.txt"} if tool == "read" else {"pattern": "*.txt"} if tool == "find" else {"path": "code.txt", "content": "must not write"} if tool == "write" else {"path": "code.txt", "edits": []}
  ticket = base_admit(f, "fails", tool, payload)
  if tool in ("write", "edit"):
    worker = base_writer(f, ticket, "must not write", hashlib.sha256(b"source").hexdigest() if tool == "edit" else None)
    token = host.service.issue_capability("worker", worker.lease_id); method = "ordinary_perform"; args = {"operation_id": ticket["operation_id"]}
    original = Tree.replace
    def replace(tree, *args, **kwargs):
      if tree.root == root: raise OSError(errno.EIO, "synthetic-private-io-detail")
      return original(tree, *args, **kwargs)
    monkeypatch.setattr(Tree, "replace", replace)
  else:
    token = host.service.issue_capability("manager", principal.lease_id)
    args = {"operation_id": ticket["operation_id"]}; method = "ordinary_list"
    if tool == "read":
      method = "ordinary_read"; args.update(offset=0, limit=65536); original = Tree.open_read
      def open_read(tree, *args, **kwargs):
        if tree.root == root: raise OSError(errno.EIO, "synthetic-private-io-detail")
        return original(tree, *args, **kwargs)
      monkeypatch.setattr(Tree, "open_read", open_read)
    else:
      original = os.listdir; expected = root.stat()
      def listing(fd):
        info = os.fstat(fd) if type(fd) is int else None
        if info and (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino): raise OSError(errno.EIO, "synthetic-private-io-detail")
        return original(fd)
      monkeypatch.setattr(os, "listdir", listing)
  reply = host.service.reply(token, os.geteuid(), request(method, args))
  assert reply == {"schema_version": 1, "ok": False, "exit_code": 6, "error": "PI_CONTROL_REJECTED"}
  assert "synthetic-private-io-detail" not in repr(reply) and (root / "code.txt").read_text() == "source"
  assert not (host.root / "activity/ordinary-results" / (ticket["operation_id"] + ".json")).exists()
  if tool in ("write", "edit"):
    lease = host.store.read(ticket["lease_id"])
    assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "active"
