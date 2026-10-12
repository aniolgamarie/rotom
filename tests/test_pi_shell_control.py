"""控制面的 Shell 路由；假 bridge 不执行、不分配 Writer。"""

from copy import deepcopy

import pytest

from agentcfg.activity import digest
from agentcfg.pi_admission_control import FileAdmissionControl
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_admission_control import opened, prepare as prepare_file, issued
from test_pi_operation_admission import fixture as ledger_fixture
from test_pi_operations import setup
from test_pi_supervisor import request


class FakeShellBridge:
  def __init__(self, operations, *, context_provider):
    self.operations, self.context_provider = operations, context_provider
    self.permits, self.rows, self.calls, self.issued = {}, {}, [], {}
    self.ticks = 0

  def tick(self):
    self.ticks += 1

  def prepare(self, principal, request_id, tool_name, private_input):
    assert tool_name == "bash"
    assert self.context_provider(request_id)["session_id"] == "session"
    self.calls.append(("prepare", request_id))
    operation_id = "shell-" + request_id
    result = {"operation_id": operation_id, "operation_digest": digest(operation_id), "state": "prepared"}
    self.rows[operation_id] = {"request_id": request_id, "state": "prepared"}
    return result

  def issue(self, principal, operation_id, *, operation_digest, source):
    assert source == "human" and operation_digest == digest(operation_id)
    self.context_provider(self.rows[operation_id]["request_id"])
    self.calls.append(("issue", operation_id))
    permit = {"permit_id": "permit-" + operation_id, "operation_id": operation_id, "source": source}
    self.permits[permit["permit_id"]] = operation_id
    self.issued[permit["permit_id"]] = deepcopy(permit)
    return permit

  def consume(self, principal, permit):
    operation_id = self.permits[permit["permit_id"]]
    self.context_provider(self.rows[operation_id]["request_id"])
    self.calls.append(("consume", operation_id))
    if permit != self.issued[permit["permit_id"]]:
      self.rows[operation_id]["state"] = "revoked"
      raise Conflict("OPERATION_PERMIT_INVALID")
    self.rows[operation_id]["state"] = "consumed"
    return {"operation_id": operation_id, "state": "consumed"}

  def status(self, principal, operation_id):
    self.calls.append(("status", operation_id))
    return {"operation_id": operation_id, "state": self.rows[operation_id]["state"]}

  def revoke(self, principal, operation_id):
    self.calls.append(("revoke", operation_id))
    if self.rows[operation_id]["state"] != "consumed": self.rows[operation_id]["state"] = "revoked"


def fixture(tmp_path, *, shell=True, **limits):
  operations, host, cwd, principal = setup(tmp_path)
  host.manifest()["profile_id"] = "pi-base"
  control = FileAdmissionControl(operations, shell_bridge_factory=FakeShellBridge if shell else None, **limits)
  operations.admission_control = control
  host.service.ordinary_handler = operations.handle
  current = ledger_fixture()[1]
  current.update(activation_id=host.store.owner["manager_activation_id"], profile="pi-base", cwd=cwd,
    runtime_identity=host.runtime_root.name, deadline_ms=int(operations.now().timestamp() * 1000) + 60000)
  def call(method, args):
    return host.service.handle(principal, request("ordinary_admission_" + method, args))
  return control, operations, host, principal, current, call


def prepare_shell(f, *, request_id="shell-request", tool_name="bash", payload=None):
  return f[5]("prepare", {"control_id": "control", "request_id": request_id, "context": f[4],
    "tool_name": tool_name, "input": {"command": "private synthetic script"} if payload is None else payload})


def consume(f, permit):
  return f[5]("consume", {"permit": permit, "context": f[4]})


def test_shell_without_factory_is_unavailable_and_tombstoned(tmp_path):
  f = fixture(tmp_path, shell=False); opened(f)
  assert f[0].shell_bridge is None
  with pytest.raises(Conflict, match="SHELL_BACKEND_UNAVAILABLE"): prepare_shell(f)
  assert f[0].requests["shell-request"]["state"] == "canceled" and f[0].private_bytes == 0
  with pytest.raises(Conflict, match="OPERATION_NOT_PENDING"): prepare_shell(f, tool_name="write")
  f[5]("cancel_request", {"control_id": "control", "request_id": "shell-request"})
  assert f[1].inputs == {}


def test_factory_must_be_callable(tmp_path):
  operations = setup(tmp_path)[0]
  with pytest.raises(ConfigError): FileAdmissionControl(operations, shell_bridge_factory=True)


def test_file_scope_never_routes_file_admission_to_shell_bridge(tmp_path):
  f = fixture(tmp_path); opened(f); prepared = prepare_file(f)
  permit = issued(f, prepared)
  assert consume(f, permit)["state"] == "consumed"
  f[5]("status", {"operation_id": prepared["operation_id"]})
  assert f[0].shell_bridge.calls == []
  assert f[0].shell_bridge.ticks > 0


def test_shell_complete_control_path_has_no_execution_or_private_projection(tmp_path):
  f = fixture(tmp_path); opened(f); prepared = prepare_shell(f)
  assert prepare_shell(f) == prepared
  permit = issued(f, prepared)
  assert consume(f, permit)["state"] == "consumed"
  assert f[5]("status", {"operation_id": prepared["operation_id"]})["state"] == "consumed"
  assert [name for name, _ in f[0].shell_bridge.calls] == ["prepare", "issue", "consume", "status"]
  assert "private synthetic script" not in repr((prepared, permit))
  assert "bridge" not in prepared and "bridge" not in f[4]
  assert not [row for row in f[2].store.records() if row["kind"] == "external"]
  assert f[1].inputs == {} and f[0].private_bytes == 0
  with pytest.raises(Conflict): consume(f, permit)


@pytest.mark.parametrize("original", ["shell", "file"])
def test_forged_operation_id_burns_only_server_selected_bridge(tmp_path, original):
  f = fixture(tmp_path); opened(f)
  shell = prepare_shell(f); file = prepare_file(f)
  first, other = (shell, file) if original == "shell" else (file, shell)
  permit = issued(f, first)
  with pytest.raises(Conflict): consume(f, {**permit, "operation_id": other["operation_id"]})
  assert f[0].operation_requests[first["operation_id"]]["state"] == "consumed"
  assert f[0].operation_requests[other["operation_id"]]["state"] == "prepared"
  assert issued(f, other)["operation_id"] == other["operation_id"]


def test_same_permit_id_in_two_bridges_is_rejected_without_routing(tmp_path):
  f = fixture(tmp_path); opened(f)
  shell = prepare_shell(f); file = prepare_file(f)
  permit = issued(f, shell)
  f[0].bridge.permits[permit["permit_id"]] = file["operation_id"]
  with pytest.raises(Conflict, match="OPERATION_PERMIT_AMBIGUOUS"): consume(f, permit)
  assert not any(name == "consume" for name, _ in f[0].shell_bridge.calls)
  assert f[0].operation_requests[shell["operation_id"]]["state"] == "prepared"
  assert f[0].operation_requests[file["operation_id"]]["state"] == "prepared"


def test_permit_mapping_must_match_request_bridge(tmp_path):
  f = fixture(tmp_path); opened(f); file = prepare_file(f)
  f[0].shell_bridge.permits["cross-bridge"] = file["operation_id"]
  with pytest.raises(Conflict, match="OPERATION_PERMIT_BRIDGE"): consume(f, {"permit_id": "cross-bridge"})
  assert f[0].operation_requests[file["operation_id"]]["state"] == "prepared"


@pytest.mark.parametrize("change", ["tool", "body"])
def test_prepared_request_cannot_switch_tool_or_body(tmp_path, change):
  f = fixture(tmp_path); opened(f); prepared = prepare_shell(f)
  kwargs = {"tool_name": "write"} if change == "tool" else {"payload": {"command": "changed"}}
  with pytest.raises(Conflict, match="OPERATION_IDEMPOTENCY_CONFLICT"): prepare_shell(f, **kwargs)
  assert f[0].shell_bridge.rows[prepared["operation_id"]]["state"] == "revoked"
  with pytest.raises(Conflict): issued(f, prepared)
  assert f[0].private_bytes == 0


@pytest.mark.parametrize("method", ["cancel_request", "retire"])
def test_cancellation_routes_both_bridges_and_blocks_late_issue(tmp_path, method):
  f = fixture(tmp_path); opened(f); shell = prepare_shell(f); file = prepare_file(f)
  issued(f, shell)
  if method == "cancel_request":
    for request_id in ("shell-request", "request"):
      f[5](method, {"control_id": "control", "request_id": request_id})
  else: f[5](method, {"control_id": "control"})
  assert f[0].shell_bridge.rows[shell["operation_id"]]["state"] == "revoked"
  assert f[5]("status", {"operation_id": file["operation_id"]})["execution"]["state"] == "revoked"
  for value in (shell, file):
    with pytest.raises(Conflict): issued(f, value)
  assert f[0].private_bytes == 0


def test_cancel_before_preparation_does_not_call_any_bridge(tmp_path):
  f = fixture(tmp_path); opened(f)
  f[5]("cancel_request", {"control_id": "control", "request_id": "shell-request"})
  with pytest.raises(Conflict): prepare_shell(f)
  assert f[0].shell_bridge.calls == []


def test_rpc_cannot_supply_factory_or_approval_source(tmp_path):
  f = fixture(tmp_path); opened(f); prepared = prepare_shell(f)
  with pytest.raises(ConfigError):
    f[5]("issue", {"operation_id": prepared["operation_id"], "context": f[4], "source": "reviewer"})
  with pytest.raises(ConfigError):
    f[5]("prepare", {"control_id": "control", "request_id": "other", "context": f[4],
      "tool_name": "bash", "input": {}, "shell_bridge_factory": "untrusted"})
  assert issued(f, prepared)["source"] == "human"
  assert "other" not in f[0].requests


def test_shell_capacity_and_failed_request_tombstone_are_preserved(tmp_path):
  f = fixture(tmp_path, max_requests=1, max_private_bytes=96); opened(f)
  with pytest.raises(Conflict, match="OPERATION_CAPACITY"):
    prepare_shell(f, payload={"command": "x" * 200})
  assert f[0].private_bytes == 0 and f[0].shell_bridge.calls == []
  with pytest.raises(Conflict, match="OPERATION_NOT_PENDING"): prepare_shell(f)
  with pytest.raises(Conflict, match="OPERATION_CAPACITY"): prepare_file(f)


def test_unknown_tools_still_use_file_validation(tmp_path):
  f = fixture(tmp_path); opened(f)
  with pytest.raises((ConfigError, Conflict)): prepare_shell(f, tool_name="unrecognized")
  assert f[0].shell_bridge.calls == [] and f[0].requests["shell-request"]["state"] == "canceled"


def test_private_capacity_is_shared_until_cancel_and_tombstones_survive(tmp_path):
  f = fixture(tmp_path, max_private_bytes=140); opened(f); prepare_shell(f)
  assert f[0].private_bytes > 0
  with pytest.raises(Conflict, match="OPERATION_CAPACITY"):
    prepare_shell(f, request_id="too-large", payload={"command": "x" * 80})
  assert [name for name, _ in f[0].shell_bridge.calls] == ["prepare"]
  f[5]("cancel_request", {"control_id": "control", "request_id": "shell-request"})
  assert f[0].private_bytes == 0
  with pytest.raises(Conflict, match="OPERATION_NOT_PENDING"): prepare_shell(f, request_id="too-large")
  assert prepare_shell(f, request_id="fresh")["state"] == "prepared"


def test_stale_context_revokes_shell_before_late_issue(tmp_path):
  f = fixture(tmp_path); opened(f); prepared = prepare_shell(f)
  with pytest.raises(Conflict, match="OPERATION_CONTEXT_STALE"):
    f[5]("issue", {"operation_id": prepared["operation_id"], "context": {**f[4], "cancel_epoch": 1}})
  assert f[0].shell_bridge.rows[prepared["operation_id"]]["state"] == "revoked"
  assert f[0].private_bytes == 0
  with pytest.raises(Conflict): issued(f, prepared)


def test_retirement_preserves_consumed_shell_state(tmp_path):
  f = fixture(tmp_path); opened(f); prepared = prepare_shell(f); consume(f, issued(f, prepared))
  f[5]("retire", {"control_id": "control"})
  assert f[5]("status", {"operation_id": prepared["operation_id"]})["state"] == "consumed"
  with pytest.raises(Conflict): issued(f, prepared)
