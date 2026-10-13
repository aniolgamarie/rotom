"""本地MCP协议和完整主题资源；不启动进程或读取账号。"""

import importlib.util
import hashlib
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


@pytest.mark.parametrize("name, digest", [
  ("dark-catppuccin", "582dcc4e035c93c54b9027733b04f218d1d35ab147f049ef4795ac6860240ce0"),
  ("light-catppuccin", "a80fe381d86a4f46d4bc5c5ea2b3e5cf703d0207ab4914cd087538df7a2e2da6"),
])
def test_official_catppuccin_themes_preserve_original_bytes_and_validate(name, digest):
  from agentcfg.omp import _validate_theme
  content = (ROOT / "agents/omp/resources/themes" / (name + ".json")).read_bytes()
  assert hashlib.sha256(content).hexdigest() == digest
  theme = _validate_theme(content)
  assert theme["name"] == name
  assert len(theme["terminal"]["ansi"]) == 16
  assert "link" in theme["colors"]
  if name == "dark-catppuccin":
    assert "toolText" in theme["colors"]


@pytest.mark.parametrize("mutation", [
  lambda theme: theme["terminal"].update(unknown="SECRET_CANARY_THEME"),
  lambda theme: theme["terminal"].update(ansi=theme["terminal"]["ansi"][:-1]),
  lambda theme: theme["terminal"].update(ansi=theme["terminal"]["ansi"] + ["base"]),
  lambda theme: theme["terminal"].update(background="SECRET_CANARY_THEME"),
  lambda theme: theme["terminal"].update(foreground="#gggggg"),
  lambda theme: theme["terminal"]["ansi"].__setitem__(0, "SECRET_CANARY_THEME"),
  lambda theme: theme["terminal"]["ansi"].__setitem__(0, 256),
  lambda theme: theme["colors"].update(link="SECRET_CANARY_THEME"),
  lambda theme: theme["colors"].update(toolText="#gggggg"),
])
def test_terminal_and_optional_theme_colors_reject_invalid_values_without_echo(mutation):
  from agentcfg.omp import _validate_theme
  from agentcfg.schema import ConfigError
  theme = json.loads((ROOT / "agents/omp/resources/themes/dark-catppuccin.json").read_bytes())
  mutation(theme)
  with pytest.raises(ConfigError) as error:
    _validate_theme(json.dumps(theme).encode())
  assert error.value.code == "omp-theme-invalid"
  assert "SECRET_CANARY_THEME" not in str(error.value)


@pytest.mark.parametrize("profile", ["omp-default", "omp-kernel"])
def test_default_and_kernel_resolve_and_render_catppuccin_theme_pair(tmp_path, profile):
  from agentcfg.adapter import RenderContext
  from agentcfg.config import LocalConfig, resolve_config
  from agentcfg.omp import OmpAdapter
  from test_model_defaults import catalog
  loaded = catalog()
  local = LocalConfig({"schema_version": 1, "machine": {"id": "theme-test"}, "local_values": {
    "tf_openai_url": "https://tf.example.invalid/v1", "tf_anthropic_url": "https://tf.example.invalid/anthropic"}})
  resolved = resolve_config(loaded, local, profile_id=profile, adapter_schemas=loaded.adapter_schemas)
  options = resolved.data["profile"]["agent_options"]
  assert options["resources"]["themes"] == ["dark-catppuccin", "light-catppuccin"]
  assert options["ui"]["theme_dark"] == "dark-catppuccin"
  assert options["ui"]["theme_light"] == "light-catppuccin"
  rendered = OmpAdapter(ROOT).render_with_context(resolved.data, RenderContext("f" * 64, tmp_path / "runtime"))
  selectors = {item.target.selector: json.loads(item.content) for item in rendered
    if item.target.selector in ("/theme/dark", "/theme/light")}
  assert selectors == {"/theme/dark": "dark-catppuccin", "/theme/light": "light-catppuccin"}
  resources = {Path(item.target.path).name: item.content for item in rendered if "/themes/" in item.target.path}
  for name in ("dark-catppuccin", "light-catppuccin"):
    assert resources[name + ".json"] == (ROOT / "agents/omp/resources/themes" / (name + ".json")).read_bytes()


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
