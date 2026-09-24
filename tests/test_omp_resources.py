"""本地MCP协议和完整主题资源；不启动进程或读取账号。"""

import importlib.util
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def echo(monkeypatch):
  import sys
  monkeypatch.setattr(sys, "dont_write_bytecode", True)
  spec = importlib.util.spec_from_file_location("rotom_echo_mcp", ROOT / "agents/omp/packages/echo-mcp/server.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def request(method, params=None, identity=1):
  return {"jsonrpc": "2.0", "id": identity, "method": method, "params": params or {}}


def test_mcp_initialize_list_and_call(echo):
  initialized = echo.handle(request("initialize", {"protocolVersion": "2025-11-25"}))
  assert initialized["result"]["protocolVersion"] == "2025-11-25"
  assert initialized["result"]["capabilities"] == {"tools": {}}
  listed = echo.handle(request("tools/list"))
  assert [tool["name"] for tool in listed["result"]["tools"]] == ["echo"]
  assert listed["result"]["tools"][0]["inputSchema"]["additionalProperties"] is False
  result = echo.handle(request("tools/call", {"name": "echo", "arguments": {"text": "你好 ROTOM_OMP_ECHO_OK"}}))
  assert result["result"] == {"content": [{"type": "text", "text": "你好 ROTOM_OMP_ECHO_OK"}], "isError": False}


def test_mcp_notifications_and_invalid_input(echo):
  assert echo.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
  assert echo.handle(request("not-a-method"))["error"]["code"] == -32601
  assert echo.handle(request("tools/call", {"name": "echo", "arguments": {"text": 42}}))["error"]["code"] == -32602
  assert echo.handle(request("tools/call", {"name": "echo", "arguments": {"text": "x", "hidden": True}}))["error"]["code"] == -32602
  assert echo.handle(["invalid"])["error"]["code"] == -32600


def test_theme_is_complete_and_unknown_fields_fail():
  schema = json.loads((ROOT / "schemas/omp-theme.schema.json").read_bytes())
  theme = json.loads((ROOT / "agents/omp/resources/themes/rotom-dark.json").read_bytes())
  validator = Draft202012Validator(schema)
  validator.validate(theme)
  assert theme["name"] == "rotom-dark"
  assert len(theme["colors"]) >= 50
  assert theme["vars"]
  incomplete = {**theme, "colors": {"accent": "#ffffff"}}
  assert not validator.is_valid(incomplete)
  assert not validator.is_valid({**theme, "unknown": True})


def test_mcp_stdio_framing_without_spawning(echo):
  import io
  incoming = io.StringIO("\n".join((json.dumps(request("ping", identity="hello")),
    '{"jsonrpc":"2.0","method":"notifications/initialized"}', 'invalid-secret-sentinel')) + "\n")
  outgoing = io.StringIO()
  echo.serve(incoming, outgoing)
  lines = outgoing.getvalue().splitlines()
  assert len(lines) == 2
  assert json.loads(lines[0]) == {"jsonrpc": "2.0", "id": "hello", "result": {}}
  assert json.loads(lines[1])["error"]["code"] == -32700
  assert "invalid-secret-sentinel" not in outgoing.getvalue()
