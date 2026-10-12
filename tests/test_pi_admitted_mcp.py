"""MCP经同一manager控制和账本；不启动服务、网络或SDK。"""

from copy import deepcopy

import pytest

from agentcfg.pi_admission_control import FileAdmissionControl
from agentcfg.pi_admitted_mcp import McpOperationAdmissions
from agentcfg.pi_operation_admission import OperationAdmissions
from agentcfg.storage import Conflict
from test_pi_operation_admission import fixture as ledger_fixture
from test_pi_operations import setup


def configured(tmp_path):
  operations, host, cwd, principal = setup(tmp_path)
  doc = host.manifest()
  doc.update(profile_id="pi-base", plugins=["pi-mcp"], native_mcp={"schema_version": 1,
    "loaded_config": {"servers": [], "errors": [], "autoEnableCodemode": False},
    "bindings": {"docs": {"transport": "streamable-http", "network_route": "docs", "authentication": "none"}},
    "allowed_tools": {"docs": ["query"]}})
  doc["options"].update(mcp={"servers": {"docs": {"transport": "streamable-http", "network_route": "docs", "authentication": "none"}}},
    network={"routes": {"docs": {"mode": "direct", "service_ids": ["mcp:docs"]}}})
  doc["permission_policy"]["rules"].append({"id": "mcp-docs", "kind": "command", "effect": "allow",
    "tool_ids": ["mcp"], "operations": ["execute"], "command_ref": "mcp:docs", "approval": "human"})
  current = ledger_fixture()[1]
  current.update(activation_id=host.store.owner["manager_activation_id"], cwd=cwd, runtime_identity=host.runtime_root.name,
    deadline_ms=int(operations.now().timestamp() * 1000) + 60000)
  shared = OperationAdmissions(current["activation_id"], now_ms=lambda: int(operations.now().timestamp() * 1000))
  control = FileAdmissionControl(operations, shared_admissions=shared, mcp_bridge_factory=McpOperationAdmissions)
  control.open(principal, {"control_id": "mcp", "session_id": current["session_id"]})
  body = {"server_name": "docs", "action": "tool", "name": "query", "arguments": {"weight": 0.25}}
  return control, principal, current, body, host


def consumed(f):
  control, principal, current, body, _ = f
  prepared = control.prepare(principal, {"control_id": "mcp", "request_id": "native-tool", "context": current,
    "tool_name": "mcp", "input": body})
  permit = control.issue(principal, {"operation_id": prepared["operation_id"], "context": current})
  ticket = control.consume(principal, {"permit": permit, "context": current})
  return prepared, ticket


def test_mcp_borrows_shared_admissions_and_commits_one_dispatch_before_io(tmp_path):
  f = configured(tmp_path); control, principal, current, body, host = f
  prepared, ticket = consumed(f)
  assert control.bridge.ledger is control.mcp_bridge.ledger
  assert ticket["kind"] == "mcp" and ticket["state"] == "consumed"
  before = host.store.records()
  args = {"operation_id": prepared["operation_id"], "context": current, "input": body}
  assert control.mcp_dispatch(principal, args)["state"] == "sending"
  with pytest.raises(Conflict): control.mcp_dispatch(principal, args)
  assert host.store.records() == before
  result = control.mcp_complete(principal, {"operation_id": prepared["operation_id"], "outcome": "succeeded"})
  assert result["state"] == "succeeded"


@pytest.mark.parametrize("fault", ["arguments", "cancel", "retire", "policy", "route", "context"])
def test_changed_or_cancelled_consumed_call_never_dispatches(tmp_path, fault):
  f = configured(tmp_path); control, principal, current, body, host = f
  prepared, _ = consumed(f)
  if fault == "arguments": body["arguments"]["weight"] = 0.5
  if fault == "cancel": control.cancel_request(principal, {"control_id": "mcp", "request_id": "native-tool"})
  if fault == "retire": control.retire(principal, {"control_id": "mcp"})
  if fault == "policy": host.manifest()["permission_policy"]["rules"][-1]["effect"] = "deny"
  if fault == "route": host.manifest()["options"]["network"]["routes"]["docs"]["service_ids"] = []
  if fault == "context": current["cancel_epoch"] += 1
  with pytest.raises(Conflict): control.mcp_dispatch(principal, {"operation_id": prepared["operation_id"], "context": current, "input": body})
  assert control.mcp_bridge.records[prepared["operation_id"]]["state"] != "sending"
  if fault == "arguments": body["arguments"]["weight"] = 0.25
  if fault == "context": current["cancel_epoch"] -= 1
  if fault in ("arguments", "context"):
    with pytest.raises(Conflict): control.mcp_dispatch(principal, {"operation_id": prepared["operation_id"], "context": current, "input": body})


def test_late_result_after_sending_cancel_stays_unknown_and_never_reissues(tmp_path):
  f = configured(tmp_path); control, principal, current, body, _ = f
  prepared, _ = consumed(f)
  control.mcp_dispatch(principal, {"operation_id": prepared["operation_id"], "context": current, "input": body})
  control.cancel_request(principal, {"control_id": "mcp", "request_id": "native-tool"})
  result = control.mcp_complete(principal, {"operation_id": prepared["operation_id"], "outcome": "succeeded"})
  assert result["state"] == "unknown"
  with pytest.raises(Conflict): control.mcp_dispatch(principal, {"operation_id": prepared["operation_id"], "context": current, "input": body})
