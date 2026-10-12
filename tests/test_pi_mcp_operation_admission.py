"""MCP借用同一一次许可；服务参数只在私有内存，绝不执行网络/服务器。"""

from copy import deepcopy
import hashlib
import json

import pytest

from agentcfg.pi_operation_admission import resolution
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_operation_admission import fixture


def mcp_fixture():
  ledger, current, resolved, _, clock = fixture()
  resolved.update(kind="mcp", tool_name="mcp", backend="native-mcp-v1", network="managed-route",
    services=["mcp:docs"], read_roots=[], write_roots=[], workspace_keys=[],
    target={"server_names": ["docs"], "action": "tool", "name": "query", "binding_digest": "1" * 64})
  resolved["policy"].update(requires_human=True, approval="human")
  return ledger, current, resolved, {"arguments": {"threshold": 0.25, "token": "synthetic-mcp-private"}}, clock


def test_mcp_uses_existing_ledger_without_public_arguments_or_body_hash():
  ledger, current, resolved, private, _ = mcp_fixture()
  prepared = ledger.prepare("native-call", current=current, resolved=resolved, private_input=private)
  assert ledger.prepare("native-call", current=current, resolved=resolved, private_input=deepcopy(private)) == prepared
  visible = json.dumps(prepared)
  assert "synthetic-mcp-private" not in visible
  assert hashlib.sha256(b"synthetic-mcp-private").hexdigest() not in visible
  permit = ledger.issue(prepared["operation_id"], operation_digest=prepared["operation_digest"],
    current=current, source="human")
  consumed = ledger.consume(permit, current=current, resolved=resolved)
  assert consumed["private_input"] == private
  with pytest.raises(Conflict): ledger.consume(permit, current=current, resolved=resolved)


@pytest.mark.parametrize("fault", ["unknown-network", "extra-service", "wrong-name", "extra-target", "local-writer", "extra-server"])
def test_mcp_projection_cannot_smuggle_other_services_or_writer(fault):
  resolved = mcp_fixture()[2]
  if fault == "unknown-network": resolved["network"] = "all"
  if fault == "extra-service": resolved["services"].append("mcp:foreign")
  if fault == "wrong-name": resolved["target"]["name"] = "not safe\n"
  if fault == "extra-target": resolved["target"]["arguments"] = {"token": "synthetic-mcp-private"}
  if fault == "local-writer": resolved["workspace_keys"] = ["2" * 64]
  if fault == "extra-server": resolved["target"]["server_names"].append("other")
  with pytest.raises(ConfigError): resolution(resolved)


def test_mcp_numeric_arguments_do_not_relax_file_identity_or_parameters():
  ledger, current, resolved, private, _ = mcp_fixture()
  private["arguments"]["large"] = 1e20
  ledger.prepare("native-call", current=current, resolved=resolved, private_input=private)
  old = fixture()
  with pytest.raises(ConfigError): old[0].prepare("file", current=old[1], resolved=old[2], private_input={"offset": 0.25})
  for value in (float("nan"), float("inf")):
    with pytest.raises(ConfigError): ledger.prepare("invalid", current=current, resolved=resolved, private_input={"value": value})
  bad = deepcopy(current); bad["policy_generation"] = 1.0
  with pytest.raises(ConfigError): ledger.prepare("identity", current=bad, resolved=resolved, private_input={})


def test_mcp_changed_parameters_conflict_and_expired_or_cancelled_permits_do_not_dispatch():
  ledger, current, resolved, private, clock = mcp_fixture()
  prepared = ledger.prepare("native-call", current=current, resolved=resolved, private_input=private)
  changed = deepcopy(private); changed["arguments"]["threshold"] = 0.5
  with pytest.raises(Conflict, match="IDEMPOTENCY_CONFLICT"):
    ledger.prepare("native-call", current=current, resolved=resolved, private_input=changed)
  permit = ledger.issue(prepared["operation_id"], operation_digest=prepared["operation_digest"], current=current, source="human")
  clock[0] = current["deadline_ms"]
  with pytest.raises(Conflict): ledger.consume(permit, current=current, resolved=resolved)
