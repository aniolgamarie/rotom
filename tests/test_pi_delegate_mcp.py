"""MCP stdio核心仅使用假的监督调用，先验证生命周期、工具边界和重放。"""
import base64
from copy import deepcopy
import hashlib

from agentcfg.pi_delegate_mcp import DelegateMcp


def fixture(writable=False):
  calls = []
  content = b"original text"
  valid = [True]
  def control(method, args):
    calls.append((method, deepcopy(args)))
    if method == "authorize": return {"valid": valid[0], "grant_generation": 1}
    if args["action"]["operation"] == "read":
      return {"data_b64": base64.b64encode(content).decode(), "offset": 0, "total_bytes": len(content), "content_digest": hashlib.sha256(content).hexdigest()}
    return {"changed": True}
  request = {"run_id": "run", "lease_id": "lease", "grant_generation": 1, "request_digest": "a" * 64,
    "mode": "implement" if writable else "review", "execution_mode": "delegate-write" if writable else "delegate-readonly"}
  grant = {"allowed_tools": ["tk_read", "tk_grep", "tk_find", "tk_ls", *(["tk_write", "tk_edit"] if writable else [])]}
  return DelegateMcp(request, grant, control), calls, valid


def initialize(server):
  result = server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fixture", "version": "1"}}})
  assert result["result"]["capabilities"] == {"tools": {}}
  assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_readonly_tools_require_initialization_and_each_action_needs_current_grant():
  server, calls, valid = fixture()
  assert "error" in server.handle({"jsonrpc": "2.0", "id": -1, "method": "tools/list"})
  initialize(server)
  tools = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
  assert {tool["name"] for tool in tools} == {"read", "list", "search"}
  invoke = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "read", "arguments": {"path": "code.txt"}}}
  assert server.handle(invoke)["result"]["isError"] is False
  before = len(calls)
  assert "error" in server.handle(invoke) and len(calls) == before
  valid[0] = False
  assert server.handle({**invoke, "id": 3})["result"]["isError"] is True
  assert calls[-1][0] == "authorize"


def test_edit_uses_fresh_digest_and_cannot_accept_extra_permission_fields():
  server, calls, _ = fixture(writable=True); initialize(server)
  args = {"path": "code.txt", "old_text": "original", "new_text": "updated"}
  invoke = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "edit", "arguments": args}}
  assert server.handle(invoke)["result"]["isError"] is False
  action = calls[-1][1]["action"]
  assert action["tool_id"] == "tk_edit" and action["expected_digest"] == hashlib.sha256(b"original text").hexdigest()
  assert base64.b64decode(action["data_b64"]) == b"updated text"
  before = len(calls)
  assert server.handle({**invoke, "id": 2, "params": {"name": "edit", "arguments": {**args, "allow_workspace_write": True}}})["result"]["isError"] is True
  assert len(calls) == before


def test_stdio_entry_keeps_stdout_protocol_only_and_never_echoes_control_capability(tmp_path, monkeypatch):
  from io import BytesIO
  import json
  from pathlib import Path
  import runpy
  from types import SimpleNamespace
  from agentcfg.activity import digest
  from agentcfg.deployment import json_bytes
  from agentcfg.storage import Tree
  from test_model_delegate_contract import request
  source = Path(__file__).resolve().parents[1] / "scripts/pi-delegate-mcp.py"
  main = runpy.run_path(str(source))["main"]
  value = request("codex"); value["cwd"] = str(tmp_path); monkeypatch.chdir(tmp_path)
  body = {"schema_version": 2, "request": value, "grant": {"allowed_tools": ["tk_read", "tk_find", "tk_grep", "tk_ls"]}}
  body["definition_digest"] = digest(body)
  with Tree(tmp_path) as tree: tree.write_state("input.json", json_bytes({"schema_version": 2, "input": body}))
  messages = [
    {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "fake", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"}, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
  ]
  output = BytesIO()
  def control(_endpoint, capability, message):
    assert capability == "synthetic-private-capability"
    return {"ok": True, "result": {"role": "worker", "lease_id": value["lease_id"], "runtime_identity": value["runtime_identity"]}
      if message["method"] == "handshake" else {"valid": True, "grant_generation": value["grant_generation"]}}
  monkeypatch.setitem(main.__globals__, "control_request", control)
  monkeypatch.setattr(main.__globals__["sys"], "argv", ["broker", "--input", str(tmp_path / "input.json")])
  monkeypatch.setattr(main.__globals__["sys"], "stdin", SimpleNamespace(buffer=BytesIO(b"".join(json_bytes(message) for message in messages))))
  monkeypatch.setattr(main.__globals__["sys"], "stdout", SimpleNamespace(buffer=output))
  monkeypatch.setenv("AGENTCFG_SUPERVISOR_ENDPOINT", str(tmp_path / "endpoint"))
  monkeypatch.setenv("AGENTCFG_DELEGATE_MCP_CAPABILITY", "synthetic-private-capability")
  assert main() == 0
  replies = [json.loads(line) for line in output.getvalue().splitlines()]
  assert [reply["id"] for reply in replies] == [0, 1]
  assert b"synthetic-private-capability" not in output.getvalue()
  assert {tool["name"] for tool in replies[1]["result"]["tools"]} == {"read", "list", "search"}


def test_command_mcp_dispatches_once_then_waits_for_same_owned_operation(monkeypatch):
  calls = []
  count = [0]
  def control(method, args):
    calls.append((method, deepcopy(args)))
    if method == "authorize": return {"valid": True, "grant_generation": 1}
    if method == "delegate_command_list": return {"commands": [{"command_ref": "tool:check", "write": False, "timeout_seconds": 5}]}
    if method == "delegate_command_start": return {"operation_id": "owned-operation", "state": "running"}
    if method == "delegate_command_status":
      count[0] += 1
      return {"operation_id": "owned-operation", "state": "running" if count[0] == 1 else "completed", "exit_code": 8}
    raise AssertionError(method)
  server, _, _ = fixture()
  server = DelegateMcp(server.request, {"allowed_tools": ["bash"]}, control)
  initialize(server)
  monkeypatch.setattr("time.sleep", lambda _seconds: None)
  reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "command", "arguments": {"command_ref": "tool:check"}}})
  assert reply["result"]["isError"] is False
  assert sum(name == "delegate_command_start" for name, _ in calls) == 1 and count[0] == 2
  assert '"exit_code":8' in reply["result"]["content"][0]["text"]
  before = len(calls)
  reply = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "command", "arguments": {"command_ref": "tool:check", "argv": ["other"]}}})
  assert reply["result"]["isError"] is True and len(calls) == before


def test_read_pagination_only_defers_an_incomplete_utf8_character_between_pages():
  import json
  server, _, _ = fixture()
  page = [b"A\xe4\xb8", 4]
  def control(method, args):
    if method == "authorize": return {"valid": True, "grant_generation": 1}
    return {"data_b64": base64.b64encode(page[0]).decode(), "offset": 0, "total_bytes": page[1], "content_digest": "a" * 64}
  server = DelegateMcp(server.request, {"allowed_tools": ["tk_read"]}, control); initialize(server)
  def read(identity):
    return server.handle({"jsonrpc": "2.0", "id": identity, "method": "tools/call", "params": {"name": "read", "arguments": {"path": "code"}}})["result"]
  result = json.loads(read(1)["content"][0]["text"])
  assert result["content"] == "A" and result["next_offset"] == 1
  page[:] = [b"A\xe4\xb8", 3]
  assert read(2)["isError"] is True
  page[:] = [b"A\xff", 5]
  assert read(3)["isError"] is True
