"""审批后的文件操作消费接入真实租约层；进程仍全部使用替身。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import base64

import pytest

from agentcfg.activity import digest
from agentcfg.pi_supervisor import Principal
from agentcfg.deployment import json_bytes
from agentcfg.pi_resource_reads import tree_digest
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_activity import identity
from test_pi_operations import setup


def request(cwd, name="write", operation_id="deferred", **payload):
  return {"operation_id": operation_id, "role_id": "main", "cwd": cwd, "tool_name": name,
    "input": payload or {"path": "new.txt", "content": "private body sentinel"}}


def prepare(operations, principal, args):
  return operations.handle(principal, "ordinary_prepare_deferred", args)


def consume(operations, principal, ticket):
  return operations.handle(principal, "ordinary_consume", {"operation_id": ticket["operation_id"]})


def status(operations, principal, ticket):
  return operations.handle(principal, "ordinary_status", {"operation_id": ticket["operation_id"]})


def finish(operations, principal, ticket):
  return operations.handle(principal, "ordinary_finish", {"operation_id": ticket["operation_id"]})


def test_prepare_has_no_writer_or_persisted_operation_and_consumes_once(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  args = request(cwd)
  before = host.store.records()
  ticket = prepare(operations, principal, args)
  assert ticket["state"] == "prepared" and ticket["lease_id"] is None
  assert host.store.records() == before
  assert not (host.root / "activity/ordinary-operations").exists()
  assert prepare(operations, principal, deepcopy(args)) == ticket
  with pytest.raises(Conflict, match="NOT_CONSUMED"):
    operations.stage_write(principal, {"operation_id": ticket["operation_id"], "content": args["input"]["content"], "expected_digest": None})
  consumed = consume(operations, principal, ticket)
  assert consumed["state"] == "consumed" and consumed["lease_id"]
  assert {k: v for k, v in consumed.items() if k not in ("lease_id", "state")} == {k: v for k, v in ticket.items() if k not in ("lease_id", "state")}
  lease = host.store.read(consumed["lease_id"])
  assert lease["state"] == "allocating"
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  assert operations.record(ticket["operation_id"])["grant"]["grant_generation"] == lease["grant_generation"]
  assert status(operations, principal, ticket) == consumed
  with pytest.raises(Conflict, match="ALREADY_CONSUMED"):
    consume(operations, principal, ticket)
  assert len(host.store.records()) == len(before) + 1
  operations.stage_write(principal, {"operation_id": ticket["operation_id"], "content": args["input"]["content"], "expected_digest": None})
  host.store.processes.current[203] = identity(203)
  host.store.start(lease["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  operations.perform(Principal("worker", lease["lease_id"], lease["grant_generation"]), {"operation_id": ticket["operation_id"]})
  assert (Path(cwd) / "new.txt").read_text() == args["input"]["content"]
  persisted = (host.root / "activity/ordinary-operations" / (ticket["operation_id"] + ".json")).read_text()
  assert args["input"]["content"] not in persisted and digest(args) not in persisted


@pytest.mark.parametrize("name,payload", [("read", {"path": "code.txt"}), ("ls", {"path": "."}),
  ("find", {"pattern": "*.txt"}), ("grep", {"pattern": "source"})])
def test_read_tools_reuse_parent_only_after_consumption(tmp_path, name, payload):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["permission_policy"]["rules"][0].update(tool_ids=["read", "ls", "find", "grep"], operations=["read", "list", "search"])
  ticket = prepare(operations, principal, request(cwd, name, **payload))
  args = {"operation_id": ticket["operation_id"]}
  io = (lambda: operations.read(principal, {**args, "offset": 0, "limit": 65536})) if name == "read" else lambda: operations.listing(principal, args)
  with pytest.raises(Conflict, match="NOT_CONSUMED"): io()
  consumed = consume(operations, principal, ticket)
  assert consumed["lease_id"] == principal.lease_id and len(host.store.records()) == 1
  result = io()
  if name == "read": assert base64.b64decode(result["data_b64"]) == b"source"
  else: assert any(row["path"] == "code.txt" for row in result["entries"])


def test_abandon_and_expiry_never_create_writer_or_allow_replay(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  now = datetime.now(timezone.utc)
  operations.now = lambda: now
  for reason in ("abandon", "expiry"):
    args = request(cwd, operation_id=reason)
    ticket = prepare(operations, principal, args)
    if reason == "abandon": finish(operations, principal, ticket)
    else:
      now += timedelta(seconds=301)
      operations.tick()
    assert status(operations, principal, ticket)["state"] in ("finished", "expired")
    with pytest.raises(Conflict): consume(operations, principal, ticket)
    assert prepare(operations, principal, args)["state"] in ("finished", "expired")
    with pytest.raises(Conflict, match="OPERATION_CONFLICT"):
      prepare(operations, principal, {**args, "input": {**args["input"], "content": "changed"}})
  assert len(host.store.records()) == 1 and not (Path(cwd) / "new.txt").exists()


@pytest.mark.parametrize("change", ["policy", "ceiling", "options", "root", "cwd", "parent"])
def test_changed_context_is_rejected_before_writer(tmp_path, change):
  operations, host, cwd, principal = setup(tmp_path)
  child = Path(cwd) / "sub"; child.mkdir()
  ticket = prepare(operations, principal, request(str(child)))
  if change == "policy": host.manifest()["permission_policy"]["rules"] = []
  if change == "ceiling": host.manifest()["role_bindings"]["scout"]["tools"] = []
  if change == "options": host.manifest()["options"]["permissions"] = {"denied_roots": ["project"]}
  if change == "root":
    root = Path(cwd); root.rename(root.with_name("moved")); root.mkdir(); (root / "sub").mkdir()
  if change == "cwd": child.rename(child.with_name("moved")); child.mkdir()
  if change == "parent": host.store.request_cancel(principal.lease_id, host.store.owner)
  with pytest.raises(Conflict): consume(operations, principal, ticket)
  assert len(host.store.records()) == 1
  assert status(operations, principal, ticket)["state"] == "revoked"
  with pytest.raises(Conflict): consume(operations, principal, ticket)


def test_hard_deny_and_rename_destination_checked_before_prepare(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  for args in (request(cwd, path=".git/config", content="no"), request(cwd, "rename", path="code.txt", destination="new.txt")):
    with pytest.raises(Conflict): prepare(operations, principal, args)
  assert len(host.store.records()) == 1 and not operations.inputs


def test_rename_consumes_one_writer_and_executes_bound_destination(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["permission_policy"]["rules"][0]["operations"].append("rename")
  ticket = prepare(operations, principal, request(cwd, "rename", path="code.txt", destination="renamed.txt"))
  assert len(host.store.records()) == 1
  lease = host.store.read(consume(operations, principal, ticket)["lease_id"])
  host.store.processes.current[203] = identity(203)
  host.store.start(lease["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  operations.perform(Principal("worker", lease["lease_id"], lease["grant_generation"]), {"operation_id": ticket["operation_id"]})
  assert (Path(cwd) / "renamed.txt").read_text() == "source"


def test_allocate_commit_then_error_is_unknown_and_cannot_be_forgotten(tmp_path, monkeypatch):
  operations, host, cwd, principal = setup(tmp_path)
  ticket = prepare(operations, principal, request(cwd))
  allocate = host.store.allocate
  def lost(**kwargs):
    allocate(**kwargs)
    raise OSError("synthetic lost allocation result")
  monkeypatch.setattr(host.store, "allocate", lost)
  with pytest.raises(OSError): consume(operations, principal, ticket)
  lease = next(row for row in host.store.records() if row["kind"] == "external")
  before = deepcopy(host.store.records())
  observed = status(operations, principal, ticket)
  assert observed["state"] == "unknown" and observed["lease_id"] == lease["lease_id"]
  assert operations.inputs[ticket["operation_id"]]["lease_id"] is None
  assert host.store.records() == before
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  for method in (consume, finish):
    with pytest.raises(Conflict): method(operations, principal, ticket)
  assert len(host.store.records()) == 2


@pytest.mark.parametrize("fault", ["foreign-owner", "different-policy", "different-roots", "ambiguous"])
def test_unknown_allocation_status_rejects_mismatched_or_ambiguous_record(tmp_path, monkeypatch, fault):
  operations, host, cwd, principal = setup(tmp_path)
  ticket = prepare(operations, principal, request(cwd))
  allocate = host.store.allocate
  def lost(**kwargs):
    allocate(**kwargs)
    raise OSError("synthetic lost allocation result")
  monkeypatch.setattr(host.store, "allocate", lost)
  with pytest.raises(OSError): consume(operations, principal, ticket)
  records = deepcopy(host.store.records())
  lease = next(row for row in records if row["kind"] == "external")
  if fault == "foreign-owner": lease["owner_nonce"] = "different"
  if fault == "different-policy": lease["policy_digest"] = "f" * 64
  if fault == "different-roots": lease["planned_workspaces"] = []
  if fault == "ambiguous": records.append(deepcopy(lease))
  monkeypatch.setattr(host.store, "records", lambda: deepcopy(records))
  with pytest.raises(Conflict, match="ALLOCATION_IDENTITY"): status(operations, principal, ticket)
  assert operations.inputs[ticket["operation_id"]]["state"] == "unknown"
  assert operations.inputs[ticket["operation_id"]]["lease_id"] is None


def test_no_cross_manager_access_and_legacy_prepare_cannot_bypass_consumption(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  args = request(cwd)
  ticket = prepare(operations, principal, args)
  for method in (consume, status, finish):
    with pytest.raises(Conflict): method(operations, Principal("worker", principal.lease_id, principal.grant_generation), ticket)
    with pytest.raises(Conflict): method(operations, Principal("manager", "different", 1), ticket)
  with pytest.raises(Conflict): operations.prepare(principal, args)
  assert len(host.store.records()) == 1


def test_file_metadata_and_staging_require_the_bound_manager(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  read_ticket = consume(operations, principal, prepare(operations, principal, request(cwd, "read", path="code.txt")))
  write_ticket = consume(operations, principal, prepare(operations, principal, request(cwd, operation_id="write")))
  foreign = Principal("manager", "different", 1)
  with pytest.raises(Conflict, match="MANAGER_REQUIRED"):
    operations.metadata(foreign, {"operation_id": read_ticket["operation_id"]})
  with pytest.raises(Conflict, match="MANAGER_REQUIRED"):
    operations.read(foreign, {"operation_id": read_ticket["operation_id"], "offset": 0, "limit": 65536})
  with pytest.raises(Conflict, match="MANAGER_REQUIRED"):
    operations.stage_write(foreign, {"operation_id": write_ticket["operation_id"], "content": "private body sentinel", "expected_digest": None})


@pytest.mark.parametrize("change", ["policy", "ceiling", "parent"])
def test_changes_after_consume_still_prevent_staging(tmp_path, change):
  operations, host, cwd, principal = setup(tmp_path)
  ticket = consume(operations, principal, prepare(operations, principal, request(cwd)))
  if change == "policy": host.manifest()["permission_policy"]["rules"] = []
  if change == "ceiling": host.manifest()["role_bindings"]["scout"]["tools"] = []
  if change == "parent": host.store.request_cancel(principal.lease_id, host.store.owner)
  with pytest.raises(Conflict):
    operations.stage_write(principal, {"operation_id": ticket["operation_id"], "content": "private body sentinel", "expected_digest": None})
  with pytest.raises(Conflict, match="TERMINATION_UNKNOWN"): finish(operations, principal, ticket)
  host.store.abort_allocation(ticket["lease_id"], host.store.owner)
  assert finish(operations, principal, ticket) == {"finished": True}


@pytest.mark.parametrize("changed", [False, True])
def test_selected_resource_consumes_parent_and_rechecks_loaded_content(tmp_path, changed):
  operations, host, cwd, principal = setup(tmp_path)
  root = Path(host.config["instance_root"])
  with Tree(root, create=True) as tree:
    tree.write_state("pi-home/skills/fixture/SKILL.md", b"# synthetic skill")
  skill = root / "pi-home/skills/fixture"
  host.manifest()["resources"] = {"skills": ["pi-home/skills/fixture"]}
  with Tree(root) as tree:
    tree.write_state("pi-home/loaded-manifest.json", json_bytes({"resources": {"skills": [{"id": "fixture", "path": str(skill), "digest": tree_digest(skill), "scope": "instance"}]}}))
  ticket = prepare(operations, principal, request(cwd, "read", path=str(skill / "SKILL.md")))
  assert ticket["state"] == "prepared" and ticket["lease_id"] is None
  if changed:
    (skill / "SKILL.md").write_text("# changed")
    with pytest.raises(Conflict): consume(operations, principal, ticket)
    assert status(operations, principal, ticket)["state"] == "revoked"
  else:
    consumed = consume(operations, principal, ticket)
    assert consumed["lease_id"] == principal.lease_id
    result = operations.read(principal, {"operation_id": ticket["operation_id"], "offset": 0, "limit": 65536})
    assert base64.b64decode(result["data_b64"]) == b"# synthetic skill"
  assert len(host.store.records()) == 1


@pytest.mark.parametrize("limit", ["count", "bytes"])
def test_terminal_tombstones_are_bounded_and_never_evicted_for_replay(tmp_path, limit):
  operations, host, cwd, principal = setup(tmp_path)
  args = request(cwd)
  if limit == "count": operations.max_deferred_operations = 1
  else: operations.max_deferred_bytes = len(operations.private_request(args))
  ticket = prepare(operations, principal, args)
  finish(operations, principal, ticket)
  with pytest.raises(Conflict, match="CAPACITY"): prepare(operations, principal, request(cwd, operation_id="another"))
  assert prepare(operations, principal, args)["state"] == "finished"
  assert len(host.store.records()) == 1


def test_metadata_persistence_failure_preserves_unknown_claim(tmp_path, monkeypatch):
  operations, host, cwd, principal = setup(tmp_path)
  ticket = prepare(operations, principal, request(cwd))
  original = Tree.write_immutable
  def fail(tree, path, data, *args, **kwargs):
    if path.startswith("activity/ordinary-operations/"): raise OSError("synthetic metadata failure")
    return original(tree, path, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "write_immutable", fail)
  with pytest.raises(OSError): consume(operations, principal, ticket)
  observed = status(operations, principal, ticket)
  assert observed["state"] == "unknown" and observed["lease_id"]
  lease = host.store.read(observed["lease_id"])
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  with pytest.raises(Conflict): finish(operations, principal, ticket)
  with pytest.raises(Conflict): consume(operations, principal, ticket)
  assert not (Path(cwd) / "new.txt").exists()


@pytest.mark.parametrize("body", ["a" * 1025, "\0" * 1025, "汉" * 1025], ids=["ascii", "escaped", "unicode"])
def test_private_body_capacity_is_checked_before_allocating_serialized_copy(tmp_path, monkeypatch, body):
  import json
  operations, host, cwd, principal = setup(tmp_path)
  operations.max_deferred_bytes = 1024
  def serialization_forbidden(*args, **kwargs):
    pytest.fail("oversized input reached JSON serialization")
  monkeypatch.setattr(json.JSONEncoder, "iterencode", serialization_forbidden)
  with pytest.raises(Conflict, match="CAPACITY"):
    operations.private_request(request(cwd, content=body, path="new.txt"))


@pytest.mark.parametrize("value", [float("nan"), 1.5, 2**53, "\ud800", {1: "coerced key"}])
def test_private_request_rejects_noncanonical_values(tmp_path, value):
  operations, host, cwd, principal = setup(tmp_path)
  with pytest.raises(ConfigError): operations.private_request({"value": value})
