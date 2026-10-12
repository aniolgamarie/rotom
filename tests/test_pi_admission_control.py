"""受信manager通道到文件账本；临时HOME、合成身份、假进程。"""

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from threading import Barrier

import pytest

from agentcfg.pi_admission_control import FileAdmissionControl
from agentcfg.activity import digest
from agentcfg.deployment import json_bytes
from agentcfg.pi_supervisor import Principal
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_operation_admission import fixture as ledger_fixture
from test_pi_operations import setup
from test_pi_supervisor import request


def fixture(tmp_path, **limits):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["profile_id"] = "pi-base"
  control = FileAdmissionControl(operations, **limits)
  operations.admission_control = control
  host.service.ordinary_handler = operations.handle
  current = ledger_fixture()[1]
  current.update(activation_id=host.store.owner["manager_activation_id"], profile="pi-base", cwd=cwd,
    runtime_identity=host.runtime_root.name, deadline_ms=int(operations.now().timestamp() * 1000) + 60000)
  def call(method, args, caller=principal):
    return host.service.handle(caller, request("ordinary_admission_" + method, args))
  return control, operations, host, principal, current, call


def opened(f, control_id="control"):
  return f[5]("open", {"control_id": control_id, "session_id": f[4]["session_id"]})


def prepare(f, *, control_id="control", request_id="request", current=None, payload=None):
  return f[5]("prepare", {"control_id": control_id, "request_id": request_id, "context": current or f[4],
    "tool_name": "write", "input": payload or {"path": "new.txt", "content": "synthetic-private-text"}})


def issued(f, prepared, current=None):
  return f[5]("issue", {"operation_id": prepared["operation_id"], "context": current or f[4]})


def test_rpc_prepare_issue_consume_only_once_and_no_body_in_public_results(tmp_path):
  f = fixture(tmp_path); opened(f)
  prepared = prepare(f)
  assert prepare(f) == prepared
  assert not [row for row in f[2].store.records() if row["kind"] == "external"]
  permit = issued(f, prepared)
  assert permit["source"] == "human"
  ticket = f[5]("consume", {"permit": permit, "context": f[4]})
  assert ticket["state"] == "consumed" and ticket["write"]
  with pytest.raises(Conflict): f[5]("consume", {"permit": permit, "context": f[4]})
  status = f[5]("status", {"operation_id": prepared["operation_id"]})
  assert status["execution"] == ticket and status["admission"]["state"] == "consumed"
  assert "synthetic-private-text" not in repr((prepared, permit, ticket, status))
  assert not (Path(f[4]["cwd"]) / "new.txt").exists()


@pytest.mark.parametrize("when", ["before-open", "before-prepare", "after-prepare", "after-issue"])
def test_cancel_tombstone_prevents_delayed_prepare_or_permission(tmp_path, when):
  f = fixture(tmp_path)
  if when != "before-open": opened(f)
  prepared = prepare(f) if when in ("after-prepare", "after-issue") else None
  permit = issued(f, prepared) if when == "after-issue" else None
  assert f[5]("cancel_request", {"control_id": "control", "request_id": "request"}) == {"request_id": "request", "state": "canceled"}
  if when == "before-open": opened(f)
  with pytest.raises(Conflict): prepare(f)
  if prepared:
    with pytest.raises(Conflict): issued(f, prepared)
    assert f[5]("status", {"operation_id": prepared["operation_id"]})["execution"]["state"] == "revoked"
  if permit:
    with pytest.raises(Conflict): f[5]("consume", {"permit": permit, "context": f[4]})
  assert not [row for row in f[2].store.records() if row["kind"] == "external"]


@pytest.mark.parametrize("when", ["before-open", "after-open", "after-prepare", "after-consume"])
def test_retirement_never_reopens_control_or_discards_consumed_writer(tmp_path, when):
  f = fixture(tmp_path)
  if when != "before-open": opened(f)
  prepared = prepare(f) if when in ("after-prepare", "after-consume") else None
  ticket = f[5]("consume", {"permit": issued(f, prepared), "context": f[4]}) if when == "after-consume" else None
  result = f[5]("retire", {"control_id": "control"})
  assert result == {"control_id": "control", "state": "retired"}
  assert f[5]("retire", {"control_id": "control"}) == result
  with pytest.raises(Conflict): opened(f)
  with pytest.raises(Conflict): prepare(f)
  if prepared:
    status = f[5]("status", {"operation_id": prepared["operation_id"]})
    assert status["execution"]["state"] == ("consumed" if ticket else "revoked")
  if ticket:
    lease = f[2].store.read(ticket["lease_id"])
    assert lease["state"] == "allocating"
    assert f[2].store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"


@pytest.mark.parametrize("phase", ["prepare", "issue", "consume"])
@pytest.mark.parametrize("field,value", [("session_id", "changed"), ("config_identity", "e" * 64),
  ("cancel_epoch", 1), ("policy_generation", 2), ("user_intent_ref", "changed"), ("unexpected", True)])
def test_changed_or_malformed_context_permanently_revokes_request(tmp_path, phase, field, value):
  f = fixture(tmp_path); opened(f); prepared = prepare(f)
  permit = issued(f, prepared) if phase == "consume" else None
  changed = {**f[4], field: value}
  with pytest.raises((ConfigError, Conflict)):
    if phase == "prepare": prepare(f, current=changed)
    elif phase == "issue": issued(f, prepared, changed)
    else: f[5]("consume", {"permit": permit, "context": changed})
  with pytest.raises(Conflict): issued(f, prepared)
  with pytest.raises(Conflict): prepare(f)
  assert f[5]("status", {"operation_id": prepared["operation_id"]})["execution"]["state"] == "revoked"


@pytest.mark.parametrize("role", ["worker", "delegate", "user"])
@pytest.mark.parametrize("method,args", [("open", {"control_id": "control", "session_id": "session"}),
  ("retire", {"control_id": "control"}), ("cancel_request", {"control_id": "control", "request_id": "request"})])
def test_non_manager_cannot_publish_or_invalidate_control(tmp_path, role, method, args):
  f = fixture(tmp_path)
  with pytest.raises(Conflict): f[5](method, args, Principal(role, f[3].lease_id, f[3].grant_generation))
  assert f[0].controls == {} and f[0].requests == {}


def test_unknown_fields_cannot_forge_approval_source(tmp_path):
  f = fixture(tmp_path); opened(f); prepared = prepare(f)
  with pytest.raises(ConfigError):
    f[5]("issue", {"operation_id": prepared["operation_id"], "context": f[4], "source": "reviewer"})
  assert f[5]("status", {"operation_id": prepared["operation_id"]})["admission"]["state"] == "prepared"


def test_failed_preparation_cannot_rebind_request_body(tmp_path):
  f = fixture(tmp_path); opened(f)
  with pytest.raises((ConfigError, Conflict)):
    prepare(f, payload={"path": "../forbidden.txt", "content": "secret"})
  with pytest.raises(Conflict): prepare(f)
  assert f[1].inputs == {}


def test_capacity_counts_tombstones_and_private_inputs(tmp_path):
  f = fixture(tmp_path, max_controls=1, max_requests=1, max_private_bytes=256); opened(f)
  with pytest.raises(Conflict, match="OPERATION_CAPACITY"): opened(f, "other")
  with pytest.raises(Conflict, match="OPERATION_CAPACITY"):
    prepare(f, payload={"path": "new.txt", "content": "x" * 512})
  f[5]("cancel_request", {"control_id": "control", "request_id": "request"})
  with pytest.raises(Conflict, match="OPERATION_CAPACITY"): prepare(f, request_id="other")
  assert f[1].inputs == {}


@pytest.mark.parametrize("method", ["open", "prepare", "issue", "consume"])
def test_closing_rejects_new_admission_but_allows_retirement_and_status(tmp_path, method):
  f = fixture(tmp_path); opened(f); prepared = prepare(f); permit = issued(f, prepared)
  f[2].service.closing = True
  args = {"open": {"control_id": "other", "session_id": f[4]["session_id"]},
    "prepare": {"control_id": "control", "request_id": "other", "context": f[4], "tool_name": "write", "input": {}},
    "issue": {"operation_id": prepared["operation_id"], "context": f[4]},
    "consume": {"permit": permit, "context": f[4]}}[method]
  with pytest.raises(Conflict): f[5](method, args)
  f[5]("retire", {"control_id": "control"})
  assert f[5]("status", {"operation_id": prepared["operation_id"]})["execution"]["state"] == "revoked"


def test_concurrent_consume_reserves_exactly_one_writer(tmp_path):
  f = fixture(tmp_path); opened(f); prepared = prepare(f); permit = issued(f, prepared)
  barrier = Barrier(2)
  def consume(_):
    barrier.wait(timeout=5)
    try: return f[5]("consume", {"permit": permit, "context": f[4]})
    except Conflict: return None
  with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(consume, range(2)))
  assert len([row for row in results if row is not None]) == 1
  assert len([row for row in f[2].store.records() if row["kind"] == "external"]) == 1


def test_unknown_allocation_remains_protected_after_status_cancel_and_retire(tmp_path, monkeypatch):
  f = fixture(tmp_path); opened(f); prepared = prepare(f); permit = issued(f, prepared)
  original = f[2].store.allocate
  def lost(**args):
    original(**args)
    raise OSError("synthetic lost allocation response")
  monkeypatch.setattr(f[2].store, "allocate", lost)
  with pytest.raises(OSError): f[5]("consume", {"permit": permit, "context": f[4]})
  for method, args in [("status", {"operation_id": prepared["operation_id"]}),
      ("cancel_request", {"control_id": "control", "request_id": "request"}), ("retire", {"control_id": "control"})]:
    f[5](method, args)
  observed = f[5]("status", {"operation_id": prepared["operation_id"]})
  assert observed["admission"]["state"] == "consumed" and observed["execution"]["state"] == "unknown"
  lease = f[2].store.read(observed["execution"]["lease_id"])
  assert lease["state"] == "allocating"
  assert f[2].store.workspaces.read(lease["planned_workspaces"][0])["state"] == "reserved"
  with pytest.raises(Conflict): f[5]("consume", {"permit": permit, "context": f[4]})
  assert len([row for row in f[2].store.records() if row["kind"] == "external"]) == 1


@pytest.mark.parametrize("field", ["instance_id", "supervisor_activation_id", "manager_activation_id", "owner_nonce"])
def test_control_requires_actual_manager_owner(tmp_path, monkeypatch, field):
  f = fixture(tmp_path)
  read = f[2].store.read
  monkeypatch.setattr(f[2].store, "read", lambda key: {**read(key), field: "other"})
  with pytest.raises(Conflict, match="OPERATION_CONTROL_OWNER"): opened(f)
  assert not f[0].controls


def test_cross_control_request_reuse_cannot_rebind_or_cancel_original(tmp_path):
  f = fixture(tmp_path); opened(f); opened(f, "other"); prepared = prepare(f)
  with pytest.raises(Conflict): prepare(f, control_id="other")
  with pytest.raises(Conflict): f[5]("cancel_request", {"control_id": "other", "request_id": "request"})
  assert issued(f, prepared)["source"] == "human"


@pytest.mark.parametrize("field,value", [("activation_id", "other"), ("profile", "pi-full"),
  ("runtime_identity", "e" * 64), ("role_id", "scout"), ("deadline_ms", 2**53-1), ("deadline_ms", 1)])
def test_context_must_match_host_and_bounded_deadline(tmp_path, field, value):
  f = fixture(tmp_path); opened(f)
  with pytest.raises(Conflict): prepare(f, current={**f[4], field: value})
  with pytest.raises(Conflict): prepare(f)
  assert not [row for row in f[2].store.records() if row["kind"] == "external"]


def test_mutated_permit_uses_issued_mapping_and_burns_only_that_operation(tmp_path):
  f = fixture(tmp_path); opened(f); prepared = prepare(f); other = prepare(f, request_id="other")
  permit = issued(f, prepared)
  with pytest.raises(Conflict):
    f[5]("consume", {"permit": {**permit, "operation_id": other["operation_id"]}, "context": f[4]})
  assert f[5]("status", {"operation_id": prepared["operation_id"]})["execution"]["state"] == "revoked"
  assert issued(f, other)["operation_id"] == other["operation_id"]


def test_retire_marks_every_request_even_if_one_physical_revoke_fails(tmp_path, monkeypatch):
  f = fixture(tmp_path); opened(f); first = prepare(f); second = prepare(f, request_id="second")
  revoke = f[0].bridge.revoke
  def failed(principal, operation_id):
    if operation_id == first["operation_id"]: raise OSError("synthetic failure")
    return revoke(principal, operation_id)
  monkeypatch.setattr(f[0].bridge, "revoke", failed)
  with pytest.raises(Conflict, match="OPERATION_RETIRE_INCOMPLETE"): f[5]("retire", {"control_id": "control"})
  for value in (first, second):
    with pytest.raises(Conflict): issued(f, value)
  assert f[0].private_bytes == 0
  monkeypatch.setattr(f[0].bridge, "revoke", revoke)
  f[5]("retire", {"control_id": "control"})
  assert f[5]("status", {"operation_id": first["operation_id"]})["execution"]["state"] == "revoked"


@pytest.mark.parametrize("profile", ["pi-base", "pi-full", "legacy"])
def test_actual_host_installs_control_only_for_modern_profiles(tmp_path, monkeypatch, profile):
  from agentcfg.pi_host import HostSupervisor
  from test_pi_host_capabilities import configured
  config, file = configured(tmp_path, monkeypatch, [])
  manifest = json.loads(file.read_bytes()); manifest["profile_id"] = profile
  file.write_bytes(json_bytes(manifest)); config["manifest_digest"] = digest(manifest)
  host = HostSupervisor(config, lease_fd=None)
  assert isinstance(host.operations.admission_control, FileAdmissionControl) == (profile != "legacy")
  assert (host.operations.admission is not None) == (profile != "legacy")
  assert not host.children and not host.store.records()
