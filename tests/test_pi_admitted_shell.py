"""Shell准入接真实租约存储；后端/进程是明确替身，不执行Shell或helper。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg.pi_admitted_shell import ShellOperationAdmissions
from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_activity import identity
from test_pi_operation_admission import fixture as ledger_fixture
from test_pi_operations import setup


def fixture(tmp_path, *, write=True, backend=True, profile="pi-base", reviewer_policy=False):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["profile_id"] = profile
  executable = tmp_path / "synthetic-shell"
  executable.write_bytes(b"synthetic shell, never execute")
  executable.chmod(0o700)
  host.manifest()["options"]["external_tools"] = {"shell": {"executable": str(executable), "version": "fixture",
    "project_root": "project", "read_roots": ["project"], "write_roots": ["project"] if write else [], "timeout_seconds": 30}}
  host.manifest()["permission_policy"]["rules"].append({"id": "shell", "kind": "command", "effect": "allow",
    "tool_ids": ["bash"], "operations": ["execute"], "command_ref": "tool:shell"})
  if reviewer_policy:
    # 仅明确合成的reviewer桥夹具；原production分类器仍逐规则/挂载复核。
    host.manifest()["permission_policy"]["rules"][0].update(approval="reviewer",
      operations=["read", "list", "search", "write", "create", "delete", "rename"])
    host.manifest()["permission_policy"]["rules"][-1]["approval"] = "reviewer"
    host.manifest()["options"]["paths"]["roots"]["fixture-checker"] = {
      "path": str(executable.parent), "purpose": "read"}
    host.manifest()["permission_policy"]["rules"].append({"id": "fixture-checker", "kind": "file",
      "effect": "allow", "root_ref": "fixture-checker", "relative_path": executable.name, "match": "exact",
      "tool_ids": ["read"], "operations": ["read"], "approval": "reviewer"})
  current = ledger_fixture()[1]
  current.update(activation_id=host.store.owner["manager_activation_id"], profile=profile, cwd=cwd,
    runtime_identity=host.runtime_root.name, deadline_ms=int(operations.now().timestamp() * 1000) + 60000)
  observations = []
  backend_proof = {"runtime_identity": host.runtime_root.name, "helper_identity": "1" * 64, "plan_digest": "2" * 64}
  def preflight(public):
    observations.append(deepcopy(public))
    result = deepcopy(backend_proof)
    if reviewer_policy:
      from agentcfg.activity import digest
      from agentcfg.pi_shell_mounts import compile_mount_plan
      from test_pi_shell_mounts import baseline
      result["mount_plan"] = compile_mount_plan(public, system_roots=(),
        mountinfo=baseline({"cwd": current["cwd"]}))
      result["plan_digest"] = digest(result["mount_plan"])
    return result
  bridge = ShellOperationAdmissions(operations, context_provider=lambda _: deepcopy(current), binding_name="shell",
    backend_preflight=preflight if backend else None)
  return bridge, operations, host, principal, current, observations, backend_proof


def prepare(f, request_id="shell-call", command="printf '%s' 'private-script-sentinel' | cat > out\ncat out"):
  return f[0].prepare(f[3], request_id, "bash", {"command": command})


def issue(f, prepared):
  return f[0].issue(f[3], prepared["operation_id"], operation_digest=prepared["operation_digest"], source="human")


def external(f):
  return [row for row in f[2].store.records() if row["kind"] == "external"]


def consume(f, prepared):
  return f[0].consume(f[3], issue(f, prepared))


def running_worker(f, ticket):
  f[2].store.processes.current[203] = identity(203)
  lease = f[2].store.start(ticket["lease_id"], f[2].store.owner, spawn=lambda _: identity(203))
  return Principal("worker", lease["lease_id"], lease["grant_generation"])


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_prepare_and_issue_do_not_write_or_allocate(tmp_path, profile):
  f = fixture(tmp_path, profile=profile)
  before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
  prepared = prepare(f)
  assert prepare(f) == prepared
  assert prepared["resolution"]["workspace_keys"]
  issue(f, prepared)
  assert external(f) == []
  assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
  assert "private-script-sentinel" not in json.dumps(f[5])


@pytest.mark.parametrize("write", [False, True])
def test_consume_allocates_one_independent_external_lease_and_binds_parent(tmp_path, write):
  f = fixture(tmp_path, write=write); prepared = prepare(f)
  permit = issue(f, prepared)
  ticket = f[0].consume(f[3], permit)
  assert ticket["state"] == "consumed" and ticket["kind"] == "command" and ticket["tool_name"] == "bash"
  assert ticket["lease_id"] != f[3].lease_id and ticket["write"] is write
  lease, = external(f)
  assert lease["parent_execution_id"] == f[2].store.read(f[3].lease_id)["execution_id"]
  assert bool(lease["planned_workspaces"]) is write
  assert lease["state"] == "allocating" and not lease["spawn_committed"]
  with pytest.raises(Conflict): f[0].consume(f[3], permit)
  assert external(f) == [lease]
  disk = b"\n".join(p.read_bytes() for p in f[2].root.rglob("*") if p.is_file())
  script = "printf '%s' 'private-script-sentinel' | cat > out\ncat out"
  assert b"private-script-sentinel" not in disk
  assert hashlib.sha256(script.encode()).hexdigest().encode() not in disk


def test_backend_missing_or_changed_cannot_allocate(tmp_path):
  f = fixture(tmp_path, backend=False)
  with pytest.raises(Conflict, match="SHELL_BACKEND_UNAVAILABLE"): prepare(f)
  assert external(f) == []
  other = fixture(tmp_path / "other"); prepared = prepare(other); permit = issue(other, prepared)
  other[6]["helper_identity"] = "3" * 64
  with pytest.raises(Conflict): other[0].consume(other[3], permit)
  assert external(other) == []
  with pytest.raises(Conflict): other[0].consume(other[3], permit)


@pytest.mark.parametrize("change", ["script", "timeout", "role"])
def test_same_request_cannot_change_input_or_trusted_context(tmp_path, change):
  f = fixture(tmp_path); prepare(f)
  private = {"command": "printf '%s' 'private-script-sentinel' | cat > out\ncat out"}
  if change == "script": private["command"] = "different"
  elif change == "timeout": private["timeout"] = 1
  else: f[4]["role_id"] = "other"
  with pytest.raises((Conflict, ConfigError)): f[0].prepare(f[3], "shell-call", "bash", private)
  assert external(f) == []


def test_lost_allocation_return_is_located_without_retry_or_release(tmp_path, monkeypatch):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  original = f[2].store.allocate
  calls = []
  def lost(**args):
    calls.append(args)
    original(**args)
    raise OSError("synthetic lost allocation reply")
  monkeypatch.setattr(f[2].store, "allocate", lost)
  with pytest.raises(OSError): f[0].consume(f[3], permit)
  lease, = external(f)
  status = f[0].status(f[3], prepared["operation_id"])
  assert status["admission"]["state"] == "consumed"
  assert status["execution"]["state"] == "unknown" and status["execution"]["lease_id"] == lease["lease_id"]
  assert f[2].store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  assert external(f) == [lease] and len(calls) == 1
  with pytest.raises(Conflict): f[0].consume(f[3], permit)
  with pytest.raises(Conflict): f[0].take_input(Principal("worker", lease["lease_id"], lease["grant_generation"]), prepared["operation_id"])


@pytest.mark.parametrize("fault", ["policy", "owner", "duplicate"])
def test_unknown_allocation_locator_rejects_foreign_or_ambiguous_identity(tmp_path, monkeypatch, fault):
  f = fixture(tmp_path); prepared = prepare(f); permit = issue(f, prepared)
  original = f[2].store.allocate
  def lost(**args): original(**args); raise OSError("lost")
  monkeypatch.setattr(f[2].store, "allocate", lost)
  with pytest.raises(OSError): f[0].consume(f[3], permit)
  rows = deepcopy(f[2].store.records())
  row = next(r for r in rows if r["kind"] == "external")
  if fault == "policy": row["policy_digest"] = "9" * 64
  elif fault == "owner": row["owner_nonce"] = "foreign"
  else: rows.append(deepcopy(row))
  monkeypatch.setattr(f[2].store, "records", lambda: rows)
  with pytest.raises(Conflict, match="ALLOCATION_IDENTITY"): f[0].status(f[3], prepared["operation_id"])


def test_record_write_failure_keeps_allocated_writer_unknown(tmp_path, monkeypatch):
  f = fixture(tmp_path); prepared = prepare(f)
  original = Tree.write_immutable
  def fail_record(self, path, data, *args, **kwargs):
    if str(path).startswith("activity/ordinary-shell-operations/"): raise OSError("synthetic publication failure")
    return original(self, path, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "write_immutable", fail_record)
  with pytest.raises(OSError): consume(f, prepared)
  lease, = external(f)
  assert f[0].status(f[3], prepared["operation_id"])["execution"]["state"] == "unknown"
  assert f[2].store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"


def test_only_bound_running_worker_can_take_private_script_once(tmp_path):
  f = fixture(tmp_path); prepared = prepare(f); ticket = consume(f, prepared)
  with pytest.raises(Conflict): f[0].take_input(f[3], prepared["operation_id"])
  pending = Principal("worker", ticket["lease_id"], 1)
  with pytest.raises(Conflict): f[0].take_input(pending, prepared["operation_id"])
  worker = running_worker(f, ticket)
  with pytest.raises(Conflict): f[0].take_input(Principal("worker", f[3].lease_id, worker.grant_generation), prepared["operation_id"])
  result = f[0].take_input(worker, prepared["operation_id"])
  assert result["command"] == "printf '%s' 'private-script-sentinel' | cat > out\ncat out"
  assert result["lease_id"] == ticket["lease_id"] and result["operation_id"] == prepared["operation_id"]
  assert "command" not in result["physical"] and "argv" not in result["physical"]
  with pytest.raises(Conflict): f[0].take_input(worker, prepared["operation_id"])


@pytest.mark.parametrize("change", ["worker-dead", "generation", "parent-dead", "revoke", "policy", "backend", "closing"])
def test_private_input_is_not_delivered_after_revocation_or_stale_execution(tmp_path, change):
  f = fixture(tmp_path); prepared = prepare(f); ticket = consume(f, prepared); worker = running_worker(f, ticket)
  if change == "worker-dead": f[2].store.processes.current.pop(203)
  elif change == "generation": worker = Principal("worker", worker.lease_id, worker.grant_generation + 1)
  elif change == "parent-dead": f[2].store.processes.current.pop(202)
  elif change == "revoke": f[0].revoke(f[3], prepared["operation_id"])
  elif change == "policy": f[2].manifest()["permission_policy"]["rules"] = []
  elif change == "closing": f[2].service.closing = True
  else: f[6]["plan_digest"] = "9" * 64
  with pytest.raises((Conflict, ConfigError)): f[0].take_input(worker, prepared["operation_id"])
  assert external(f)[0]["state"] == "running"


@pytest.mark.parametrize("before", ["prepare", "permit", "consume"])
def test_revoke_never_allocates_or_releases_unknown_or_consumed_writer(tmp_path, before):
  f = fixture(tmp_path); prepared = prepare(f)
  permit = issue(f, prepared) if before != "prepare" else None
  ticket = f[0].consume(f[3], permit) if before == "consume" else None
  f[0].revoke(f[3], prepared["operation_id"])
  if ticket:
    lease, = external(f)
    assert lease["state"] == "allocating"
    assert f[2].store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  else:
    assert external(f) == []
    with pytest.raises(Conflict): issue(f, prepared)


@pytest.mark.parametrize("field", ["args", "interactive", "unknown"])
def test_shell_cannot_inherit_fixed_command_extra_execution_semantics(tmp_path, field):
  f = fixture(tmp_path)
  binding = f[2].manifest()["options"]["external_tools"]["shell"]
  binding[field] = ["-c", "other"] if field == "args" else True
  with pytest.raises(ConfigError): prepare(f)
  assert external(f) == []


def shared_control(f):
  from agentcfg.pi_admission_control import FileAdmissionControl
  from test_pi_supervisor import request
  control = FileAdmissionControl(f[1], shell_bridge_factory=lambda operations, **kwargs:
    ShellOperationAdmissions(operations, **kwargs, binding_name="shell", backend_preflight=f[0].backend_preflight))
  f[1].admission_control = control
  f[2].service.ordinary_handler = f[1].handle
  def call(method, args, principal=None):
    return f[2].service.handle(principal or f[3], request(method, args))
  call("ordinary_admission_open", {"control_id": "main-control", "session_id": f[4]["session_id"]})
  return control, call


def shared_prepare(f, call, *, request_id="real-shell", tool="bash", private=None):
  return call("ordinary_admission_prepare", {"control_id": "main-control", "request_id": request_id,
    "context": f[4], "tool_name": tool, "input": private or {"command": "printf 'private RPC script'"}})


def shared_consume(f, call, prepared):
  permit = call("ordinary_admission_issue", {"operation_id": prepared["operation_id"], "context": f[4]})
  return call("ordinary_admission_consume", {"permit": permit, "context": f[4]})


def test_real_shared_control_and_worker_rpc_deliver_only_consumed_shell_input(tmp_path):
  f = fixture(tmp_path); control, call = shared_control(f)
  prepared = shared_prepare(f, call)
  assert external(f) == []
  ticket = shared_consume(f, call, prepared)
  assert call("ordinary_admission_status", {"operation_id": prepared["operation_id"]})["execution"] == ticket
  assert control.private_bytes == 0
  worker = running_worker(f, ticket)
  with pytest.raises(Conflict): call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]})
  result = call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)
  assert result["command"] == "printf 'private RPC script'"
  with pytest.raises(Conflict): call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)


@pytest.mark.parametrize("replace_root", [False, True])
def test_private_worker_handoff_prepares_real_fds_without_retry_or_execution(tmp_path, replace_root):
  from agentcfg.pi_shell_script import sealed_script
  from agentcfg.pi_shell_sources import pin_shell_sources
  import os
  f = fixture(tmp_path); control, call = shared_control(f)
  prepared = shared_prepare(f, call)
  ticket = shared_consume(f, call, prepared)
  worker = running_worker(f, ticket)
  value = call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)
  assert value["resolution"] == prepared["resolution"]
  project = Path(f[4]["cwd"])
  if replace_root:
    project.rename(project.with_name(project.name + "-moved")); project.mkdir()
    with pytest.raises((Conflict, ConfigError)):
      with pin_shell_sources({key: value[key] for key in ("resolution", "physical")}): pytest.fail("stale root handed off")
  else:
    with pin_shell_sources({key: value[key] for key in ("resolution", "physical")}) as sources:
      with sealed_script(value["command"]) as script_fd:
        assert os.read(script_fd, 65537) == b"printf 'private RPC script'"
        assert os.fstat(sources["cwd_fd"]).st_ino == project.stat().st_ino
  with pytest.raises(Conflict): call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)
  assert external(f)[0]["state"] == "running"
  assert external(f)[0]["lease_id"] == ticket["lease_id"]


def test_real_file_and_shell_share_control_without_cross_consuming(tmp_path):
  f = fixture(tmp_path, write=False); control, call = shared_control(f)
  file = shared_prepare(f, call, request_id="file", tool="read", private={"path": "code.txt"})
  shell = shared_prepare(f, call)
  file_ticket = shared_consume(f, call, file)
  shell_ticket = shared_consume(f, call, shell)
  assert file_ticket["lease_id"] == f[3].lease_id
  assert shell_ticket["lease_id"] != f[3].lease_id
  worker = running_worker(f, shell_ticket)
  with pytest.raises(Conflict): call("ordinary_shell_take_input", {"operation_id": file["operation_id"]}, worker)
  assert call("ordinary_shell_take_input", {"operation_id": shell["operation_id"]}, worker)["command"]


@pytest.mark.parametrize("when", ["before-consume", "after-consume"])
def test_real_control_retirement_revokes_shell_input_but_does_not_release_writer(tmp_path, when):
  f = fixture(tmp_path); control, call = shared_control(f)
  prepared = shared_prepare(f, call)
  ticket = shared_consume(f, call, prepared) if when == "after-consume" else None
  call("ordinary_admission_retire", {"control_id": "main-control"})
  with pytest.raises(Conflict): shared_consume(f, call, prepared)
  if ticket:
    worker = running_worker(f, ticket)
    with pytest.raises(Conflict): call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)
    assert external(f)[0]["state"] == "running"
  else: assert external(f) == []


def test_control_retirement_preserves_writer_after_lost_allocation_reply(tmp_path, monkeypatch):
  f = fixture(tmp_path); control, call = shared_control(f)
  prepared = shared_prepare(f, call)
  allocate = f[2].store.allocate
  def lost(**args):
    allocate(**args)
    raise OSError("synthetic lost allocation reply")
  monkeypatch.setattr(f[2].store, "allocate", lost)
  with pytest.raises(OSError): shared_consume(f, call, prepared)
  lease, = external(f)
  writer = f[2].store.workspaces.read(lease["planned_workspaces"][0])
  call("ordinary_admission_retire", {"control_id": "main-control"})
  status = call("ordinary_admission_status", {"operation_id": prepared["operation_id"]})
  assert status["execution"]["state"] == "unknown" and status["execution"]["lease_id"] == lease["lease_id"]
  assert external(f) == [lease]
  assert f[2].store.workspaces.read(lease["planned_workspaces"][0]) == writer
  assert writer["state"] == "reserved"
  assert control.shell_bridge.records[prepared["operation_id"]]["private"] is None
  worker = Principal("worker", lease["lease_id"], lease["grant_generation"])
  with pytest.raises(Conflict): call("ordinary_shell_take_input", {"operation_id": prepared["operation_id"]}, worker)


def test_default_supervisor_does_not_expose_a_shell_input_channel(tmp_path):
  f = fixture(tmp_path)
  with pytest.raises(Conflict, match="SHELL_BACKEND_UNAVAILABLE"):
    f[1].handle(f[3], "ordinary_shell_take_input", {"operation_id": "unknown"})
