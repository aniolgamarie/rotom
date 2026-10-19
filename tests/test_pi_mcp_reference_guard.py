"""Pi原生MCP插值引用在比较、备份和恢复前独立保护。"""

import pytest

from agentcfg.adapter import ManagedTarget, Ownership
from agentcfg.native_projection import (reference_guard, validate_item_guard,
  validate_projection, validate_saved_state, transition_guard)
from agentcfg.storage import Conflict


TOKEN = "${AGENTCFG_PI_MCP_0123456789ABCDEF}"


def item(guard=True):
  value = {"path": "pi-home/mcp.json", "selector": "/mcpServers/pi-brave/env/BRAVE_API_KEY"}
  if guard:
    value["guard"] = reference_guard((TOKEN,))
  return value


def test_pi_braced_reference_is_a_distinct_native_contract():
  target = ManagedTarget("pi-home/mcp.json", Ownership.FIELDS, "json",
    "/mcpServers/pi-brave/env/BRAVE_API_KEY", (TOKEN,))
  assert target.reference_tokens == (TOKEN,)
  guard = reference_guard((TOKEN,))
  assert guard == {"kind": "environment-braced-reference", "tokens": [TOKEN]}
  projection = {"present": True, "value": TOKEN}
  validate_item_guard(item(), projection)
  validate_projection(projection, guard)


@pytest.mark.parametrize("value", ["SYNTHETIC_MCP_SECRET", "$AGENTCFG_PI_MCP_0123456789ABCDEF", "!read-secret", ""])
def test_literal_or_command_mcp_secret_is_rejected_before_backup(value):
  with pytest.raises(Conflict):
    validate_projection({"present": True, "value": value}, reference_guard((TOKEN,)))


@pytest.mark.parametrize("slot", ["current", "previous"])
def test_mcp_historical_record_without_guard_cannot_enter_restored_state(slot):
  entry = {**item(False), "baseline": {"present": True, "value": "SYNTHETIC_MCP_SECRET"}}
  current = {"items": {"synthetic": entry}}
  state = {"current": current if slot == "current" else None,
    "previous": {"current": current, "changes": []} if slot == "previous" else None}
  with pytest.raises(Conflict):
    validate_saved_state(state)


def test_omp_and_pi_reference_types_cannot_cross_or_transition():
  with pytest.raises(Conflict):
    validate_item_guard({**item(), "path": "omp-home/mcp.json"}, {"present": True, "value": TOKEN})
  with pytest.raises(Conflict):
    transition_guard(reference_guard((TOKEN,)), reference_guard(("$OTHER",)))
