"""派生命令使用真实临时租约和文件；执行与身份观察全部为替身。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg.activity import digest, protected
from agentcfg.deployment import json_bytes
from agentcfg.pi_delegate_commands import command_binding
from agentcfg.pi_supervisor import Principal
from agentcfg.storage import Conflict, Tree
from test_pi_activity import identity
from test_pi_delegate_files import writer


def fixture(tmp_path, *, writable=True):
  executable = tmp_path / "tools/check"; executable.parent.mkdir(); executable.write_text("fixture, never execute"); executable.chmod(0o700)
  def configure(host):
    manifest = host.manifest()
    manifest["options"]["external_tools"] = {"check": {"executable": str(executable), "args": ["--fixed"], "project_root": "project",
      "read_roots": ["project"], "write_roots": ["project"] if writable else [], "timeout_seconds": 10}}
    manifest["permission_policy"]["rules"].append({"id": "command", "kind": "command", "effect": "allow", "tool_ids": ["bash"], "operations": ["execute"], "command_ref": "tool:check"})
    with Tree(host.runtime_root) as tree: tree.write_state("supervisor/scripts/pi-project-check", b"fake check entry")
  controller, host, source, candidate, request, write = writer(tmp_path, configure=configure)
  from agentcfg.pi_delegate_commands import DelegateCommands
  controller.commands = DelegateCommands(controller)
  original_input = controller.input
  def prototype_input(run_id):
    value = original_input(run_id)
    value["grant"]["allowed_tools"].append("bash")
    value["grant"]["grant_digest"] = digest({key: item for key, item in value["grant"].items() if key != "grant_digest"})
    return value
  controller.input = prototype_input
  host.server = SimpleNamespace(endpoint=tmp_path / "private/control")
  host.service.issue_capability = lambda *_args: "synthetic-command-capability"
  spawned = []
  def spawn(command, lease):
    spawned.append(command)
    host.store.processes.current[202] = identity(202)
    return identity(202)
  host.spawn = spawn
  args = {"run_id": request["run_id"], "lease_id": request["lease_id"], "grant_generation": request["grant_generation"], "operation_id": "command-one", "command_ref": "tool:check"}
  principal = Principal("worker", request["lease_id"], request["grant_generation"])
  return controller, host, source, candidate, request, write, args, principal, spawned


def test_write_command_uses_candidate_parent_lease_and_fixed_argv_only(tmp_path):
  controller, host, source, candidate, request, write, args, principal, spawned = fixture(tmp_path)
  bound = command_binding(controller, principal, args)
  assert bound["check"]["cwd"] == str(candidate)
  assert bound["check"]["write_roots"] == [str(candidate)]
  assert str(source) not in bound["check"]["read_roots"]
  assert bound["check"]["argv"][1:] == ["--fixed"] and bound["check"]["network"] == "none"
  started = controller.commands.start(principal, args)
  assert started["state"] == "running" and len(spawned) == 1
  child = next(row for row in host.store.records() if row["execution_id"].startswith("delegate-command-"))
  assert child["parent_execution_id"] == request["run_id"] and child["planned_workspaces"] == []
  assert host.store.workspaces.read(host.store.workspaces.identify(candidate))["execution_lease_id"] == request["lease_id"]
  with pytest.raises(Conflict, match="ALREADY_DISPATCHED"):
    controller.commands.start(principal, args)
  with pytest.raises(Conflict, match="MUTATION_UNSETTLED"): write("concurrent")
  assert len(spawned) == 1 and (source / "code.txt").read_text() == "source"
  host.store.processes.current.pop(201)
  with pytest.raises(Conflict, match="派生执行"):
    host.store.finish(request["lease_id"], host.store.owner)
  controller.commands.tick()
  assert host.store.read(child["lease_id"])["state"] == "cancel_requested"
  assert protected(host.store.read(request["lease_id"]))


def test_command_rejects_unbound_argv_original_root_and_revoked_grant(tmp_path):
  from agentcfg.schema import ConfigError
  controller, host, source, _, request, _, args, principal, spawned = fixture(tmp_path)
  with pytest.raises(Conflict, match="UNBOUND"): command_binding(controller, principal, {**args, "command_ref": "sh -c dangerous"})
  with pytest.raises(ConfigError): command_binding(controller, principal, {**args, "argv": ["override"]})
  manifest = host.manifest()
  manifest["options"]["paths"]["roots"]["original"] = {"path": str(source), "purpose": "read"}
  manifest["options"]["external_tools"]["check"]["read_roots"].append("original")
  with pytest.raises(Conflict, match="ORIGINAL_ROOT"): command_binding(controller, principal, args)
  host.store.request_cancel(request["lease_id"], host.store.owner)
  with pytest.raises(Conflict, match="GRANT_REVOKED"): command_binding(controller, principal, args)
  assert spawned == []


def test_command_receipt_waits_for_physical_termination_and_verified_captured_output(tmp_path):
  import hashlib
  from agentcfg.pi_delegate_files import verify_mutations
  from agentcfg.pi_worker_files import snapshot
  controller, host, _, candidate, request, write, args, principal, _ = fixture(tmp_path)
  started = controller.commands.start(principal, args)
  query = {key: args[key] for key in ("run_id", "lease_id", "grant_generation")}; query["operation_id"] = started["operation_id"]
  child = next(row for row in host.store.records() if row["execution_id"].startswith("delegate-command-"))
  assert controller.commands.status(principal, query)["state"] == "running"
  (candidate / "code.txt").write_text("changed by fake bound command")
  host.store.processes.current.pop(202)
  host.store.finish(child["lease_id"], host.store.owner)
  with pytest.raises(Conflict, match="EXIT_UNKNOWN"): controller.commands.status(principal, query)
  with Tree(host.root) as tree:
    tree.write_state("activity/exits/" + child["lease_id"] + ".json", json_bytes({"schema_version": 1, "lease_id": child["lease_id"], "process_identity": child["process_identity"], "exit_code": 7}))
  with Tree(host.root / "activity/outputs" / child["lease_id"], create=True) as tree:
    streams = {}
    for name, data in (("stdout", b"failure detail"), ("stderr", b"")):
      tree.write_state(name, data)
      streams[name] = {"sha256": hashlib.sha256(data).hexdigest(), "truncated": False, "failed": False}
    tree.write_state("capture.json", json_bytes({"complete": True, "streams": streams}))
  result = controller.commands.status(principal, query)
  assert result["state"] == "completed" and result["exit_code"] == 7 and result["stdout"] == "failure detail"
  assert controller.commands.status(principal, query) == result
  assert verify_mutations(controller.root, request, snapshot(candidate))["sequence"] == 1
  assert write("after-command")["changed"]


def test_derived_command_cannot_exceed_the_existing_supervisor_capacity(tmp_path):
  controller, host, _, _, request, _, args, principal, spawned = fixture(tmp_path)
  parent = host.store.read(request["lease_id"])
  other = host.store.allocate(kind="external", execution_id="other", task_id=None, attempt_id="other",
    lock_identity=parent["lock_identity"], slice_identity=parent["slice_identity"], policy_digest=parent["policy_digest"], candidate_digest=None, planned_workspaces=[])
  host.store.processes.current[203] = identity(203)
  host.store.start(other["lease_id"], host.store.owner, spawn=lambda _lease: identity(203))
  with pytest.raises(Conflict, match="CAPACITY_BUSY"):
    controller.commands.start(principal, args)
  assert spawned == [] and len(host.store.records()) == 2


def test_offline_parent_proof_also_requires_the_referenced_child_evidence(tmp_path):
  from agentcfg.model_delegate import saved_termination
  controller, host, _, _, request, _, args, principal, _ = fixture(tmp_path, writable=False)
  controller.commands.start(principal, args)
  child = next(row for row in host.store.records() if row["execution_id"].startswith("delegate-command-"))
  host.store.processes.current.pop(202)
  host.store.finish(child["lease_id"], host.store.owner)
  host.store.processes.current.pop(201)
  host.store.finish(request["lease_id"], host.store.owner)
  proof = saved_termination(host.root, request)
  assert proof["termination_verified"] and proof["resources_reclaimed"]
  assert proof["termination_evidence"]["external_work_ids"] == ["execution-lease:" + child["lease_id"]]
  (host.root / "activity/leases" / (child["lease_id"] + ".json")).unlink()
  proof = saved_termination(host.root, request)
  assert not proof["termination_verified"] and not proof["resources_reclaimed"]


def test_unknown_command_start_is_kept_and_parent_cancel_does_not_release_workspace(tmp_path):
  controller, host, _, candidate, request, _, args, principal, _ = fixture(tmp_path)
  def lost_ack(_command, _lease): raise OSError("synthetic lost acknowledgement")
  host.spawn = lost_ack
  with pytest.raises(Conflict): controller.commands.start(principal, args)
  child = next(row for row in host.store.records() if row["execution_id"].startswith("delegate-command-"))
  assert child["state"] == "unknown" and protected(child)
  with pytest.raises(Conflict, match="ALREADY_DISPATCHED"):
    controller.commands.start(principal, args)
  host.store.request_cancel(request["lease_id"], host.store.owner)
  controller.commands.tick()
  assert protected(host.store.read(child["lease_id"]))
  workspace = host.store.workspaces.read(host.store.workspaces.identify(candidate))
  assert workspace["state"] != "released" and workspace["execution_lease_id"] == request["lease_id"]
  assert host.store.read(request["lease_id"])["grant_generation"] > request["grant_generation"]
