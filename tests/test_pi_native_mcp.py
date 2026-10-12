"""官方MCP纯配置；真实声明校验与legacy fixture，不连接服务。"""
from copy import deepcopy
import json

import pytest

from agentcfg import pi_mcp
from agentcfg.pi import PiAdapter, key_variable
from agentcfg.schema import ConfigError
from test_pi_adapter import ROOT, pi_data
from test_pi_optional_capabilities import select
from test_pi_profile_projection import resolved


def project(data, allowed=None):
  return pi_mcp.official_configuration(data, allowed_tools={"fixture": ["search"]} if allowed is None else allowed)


def fixture(tmp_path, transport="stdio", auth="none"):
  data = pi_data(tmp_path); select(data, "pi-mcp"); select(data, "pi-permissions")
  options = data["profile"]["agent_options"]
  data["profile"]["mcp"] = ["fixture"]
  if transport == "stdio":
    data["mcp"] = {"fixture": {"transport": transport, "command": "/fixture/server", "args": ["--stdio"]}}
    binding = {"transport": transport, "command_ref": "mcp-fixture"}
    options["paths"] = {"roots": {"project": {"path": str(tmp_path), "purpose": "project"}}}
    options["external_tools"] = {"mcp-fixture": {"executable": "/fixture/server", "version": "1", "args": ["--stdio"], "interactive": True, "project_root": "project"}}
  else:
    data["mcp"] = {"fixture": {"transport": transport, "url": "https://mcp.invalid/service"}}
    if auth != "none": data["mcp"]["fixture"]["credential_ref"] = "secret:mcp-fixture"
    binding = {"transport": transport, "network_route": "mcp-route", "authentication": auth}
    options["network"] = {"routes": {"mcp-route": {"mode": "direct", "provider_ids": [], "service_ids": ["mcp:fixture"]}}}
    if auth == "oauth": binding["oauth"] = {"grant_type": "authorization_code", "client_id": "fixture-client", "scope": "read", "redirect_uri": "http://localhost:8765/callback", "allowed_origins": ["https://auth.invalid"], "auth_server_metadata_url": "https://auth.invalid/.well-known/oauth-authorization-server"}
  options["mcp"] = {"servers": {"fixture": binding}}
  PiAdapter(ROOT).validate(data)
  return data


def test_actual_resolve_unselected_mcp_stays_absent():
  assert project(resolved(profile="pi-default"), {}) is None


def native_fixture(tmp_path):
  data = resolved()
  data["profile"]["mcp"] = ["fixture"]
  data["mcp"] = {"fixture": {"transport": "streamable-http", "url": "https://mcp.invalid/service"}}
  options = data["profile"]["agent_options"]
  options["mcp"] = {"servers": {"fixture": {"transport": "streamable-http", "network_route": "docs", "authentication": "none"}},
    "allowed_tools": {"fixture": ["search"]}}
  options["network"] = {"routes": {"docs": {"mode": "direct", "provider_ids": [], "service_ids": ["mcp:fixture"]}}}
  return data


def test_actual_base_render_connects_native_projection_without_old_plugin_dependencies(tmp_path):
  data = native_fixture(tmp_path)
  adapter = PiAdapter(ROOT); adapter.validate(data)
  manifest = json.loads(next(item.content for item in adapter.render(data) if item.target.path == "pi-home/agentcfg-manifest.json"))
  assert manifest["plugins"] == ["pi-todo", "loop-guard", "colorful-footer"]
  assert "pi-mcp" not in manifest["plugins"] and "pi-subagents" not in manifest["plugins"]
  assert manifest["native_mcp"]["allowed_tools"] == {"fixture": ["search"]}
  assert manifest["native_mcp"]["loaded_config"]["servers"][0]["config"]["headers"] == {"Authorization": ""}
  assert manifest["mcp_config"]["mcpServers"]["fixture"]["url"] == "https://mcp.invalid/service"


@pytest.mark.parametrize("fault", ["missing", "foreign", "wildcard", "unselected", "scripting"])
def test_base_native_manifest_requires_explicit_exact_scope(tmp_path, fault):
  data = native_fixture(tmp_path); options = data["profile"]["agent_options"]["mcp"]
  if fault == "missing": options.pop("allowed_tools")
  if fault == "foreign": options["allowed_tools"] = {"foreign": ["search"]}
  if fault == "wildcard": options["allowed_tools"] = {"fixture": ["*"]}
  if fault == "unselected": data["profile"]["mcp"] = []; data["mcp"] = {}
  if fault == "scripting": options["scripting"] = {"enabled": True, "tool_ref": "script"}
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)


def test_native_allowlist_does_not_silently_extend_legacy_configuration(tmp_path):
  data = fixture(tmp_path)
  data["profile"]["agent_options"]["mcp"]["allowed_tools"] = {"fixture": ["search"]}
  with pytest.raises(ConfigError, match="pi-mcp-native-tools-unselected"): pi_mcp.configuration(data)


def test_stdio_is_explicit_detached_configuration_and_preserves_legacy(tmp_path):
  data = fixture(tmp_path); before = deepcopy(data); old = pi_mcp.configuration(data)
  result = project(data); row = result["loaded_config"]["servers"][0]
  assert set(result) == {"schema_version", "loaded_config", "bindings", "allowed_tools"}
  assert result["loaded_config"] == {"servers": [row], "errors": [], "autoEnableCodemode": False}
  assert row["name"] == "fixture" and row["scope"] == "extension"
  assert row["config"] == {"type": "stdio", "command": "/fixture/server", "args": ["--stdio"], "cwd": str(tmp_path), "env": {}, "exposure": "hidden", "toolExposure": {"search": "codemode"}}
  assert result["bindings"] == {"fixture": {"transport": "stdio", "command_ref": "mcp-fixture", "authentication": "none"}}
  result["allowed_tools"]["fixture"].append("foreign")
  assert data == before and pi_mcp.configuration(data) == old


@pytest.mark.parametrize("transport,auth", [("sse", "none"), ("streamable-http", "bearer"), ("streamable-http", "oauth")])
def test_http_no_secret_reads_and_supported_oauth_projection(tmp_path, monkeypatch, transport, auth):
  data = fixture(tmp_path, transport, auth)
  # 投影不得读取credential/环境值；合成sentinel绝不进入DTO。
  monkeypatch.setenv(key_variable("mcp:fixture"), "SYNTHETIC-NOT-A-CREDENTIAL")
  if auth == "oauth": data["profile"]["agent_options"]["mcp"]["callback_max_seconds"] = 120
  def forbidden(*_args, **_kwargs): raise AssertionError("projection attempted a read")
  with monkeypatch.context() as guarded:
    import builtins
    import os
    from pathlib import Path
    guarded.setattr(builtins, "open", forbidden)
    guarded.setattr(Path, "read_bytes", forbidden)
    guarded.setattr(Path, "read_text", forbidden)
    guarded.setattr(os, "getenv", forbidden)
    result = project(data)
  config = result["loaded_config"]["servers"][0]["config"]
  assert config["type"] == "http" and config["url"] == "https://mcp.invalid/service"
  assert "auth" not in config and "SYNTHETIC-NOT-A-CREDENTIAL" not in json.dumps(result)
  assert result["bindings"]["fixture"]["transport"] == transport
  if auth == "none": assert config["headers"] == {"Authorization": ""} and "oauth" not in config
  if auth == "bearer": assert config["headers"] == {"Authorization": "Bearer ${" + key_variable("mcp:fixture") + "}"}
  if auth == "oauth":
    assert result["bindings"]["fixture"]["oauth_policy"] == {"allowed_origins": ["https://auth.invalid"], "callback_max_seconds": 120}
    data["profile"]["agent_options"]["mcp"]["servers"]["fixture"]["oauth"]["allowed_origins"].append("https://later.invalid")
    assert result["bindings"]["fixture"]["oauth_policy"]["allowed_origins"] == ["https://auth.invalid"]
    assert config["oauth"] == {"clientId": "fixture-client", "scope": "read", "authServerMetadataUrl": "https://auth.invalid/.well-known/oauth-authorization-server", "callbackUrl": "http://localhost:8765/callback", "clientSecret": "${" + key_variable("mcp:fixture") + "}"}
  if auth != "none": assert result["bindings"]["fixture"]["credential_ref"] == "secret:mcp-fixture"


def test_explicit_direct_scope_and_resource_only_empty_list(tmp_path):
  data = fixture(tmp_path)
  binding = data["profile"]["agent_options"]["mcp"]["servers"]["fixture"]
  binding["direct_tools"] = {"enabled": True, "tools": ["search"]}
  assert project(data)["loaded_config"]["servers"][0]["config"]["toolExposure"] == {"search": "direct"}
  binding["direct_tools"] = {"enabled": True, "tools": ["foreign"]}
  with pytest.raises(ConfigError, match="pi-mcp-official-direct-tools-scope"): project(data)
  binding["direct_tools"] = {"enabled": True}
  with pytest.raises(ConfigError, match="pi-mcp-official"): project(data)
  binding.pop("direct_tools")
  assert project(data, {"fixture": []})["loaded_config"]["servers"][0]["config"]["toolExposure"] == {}


@pytest.mark.parametrize("allowed", [{}, {"foreign": []}, {"fixture": True}, {"fixture": ["*"]}, {"fixture": ["search", "search"]}, {"fixture": ["bad\nname"]}, {"fixture": ["x"] * 65},
  {"fixture": ["has__separator"]}, {"fixture": ["a-b", "a_b"]}, {"fixture": ["x" * 55]}, {"fixture": ["非ASCII"]}])
def test_explicit_allowlist_rejects_unknown_scope_and_types(tmp_path, allowed):
  with pytest.raises(ConfigError, match="pi-mcp-official"): project(fixture(tmp_path), allowed)


@pytest.mark.parametrize("fault", ["command", "route", "unknown", "cwd", "collision", "sampling", "scripting", "apps", "elicitation", "grant", "https-callback"])
def test_unsupported_or_unbound_semantics_never_silently_adapt(tmp_path, fault):
  http = fault in {"route", "grant", "https-callback"}
  data = fixture(tmp_path, "streamable-http" if http else "stdio", "oauth" if fault in {"grant", "https-callback"} else "none")
  options = data["profile"]["agent_options"]
  if fault == "command": data["mcp"]["fixture"]["command"] = "/foreign/server"
  if fault == "route": options["network"]["routes"]["mcp-route"]["service_ids"] = []
  if fault == "unknown": options["mcp"]["servers"]["fixture"]["foreign"] = "SYNTHETIC-PRIVATE"
  if fault == "cwd": options["external_tools"]["mcp-fixture"].pop("project_root")
  if fault == "collision":
    for name in ["server-a", "server_a"]:
      data["mcp"][name] = deepcopy(data["mcp"]["fixture"])
      options["mcp"]["servers"][name] = deepcopy(options["mcp"]["servers"]["fixture"])
  if fault == "sampling": options["mcp"]["sampling"] = {"enabled": True}
  if fault == "scripting":
    options["mcp"]["scripting"] = {"enabled": True, "tool_ref": "script"}
    options["external_tools"]["script"] = {"executable": "/fixture/node", "version": "24", "args": [], "interactive": False}
  if fault == "elicitation": options["mcp"]["elicitation"] = True
  if fault == "apps": options["mcp"]["apps"] = {"enabled": True, "browser_network": "user-browser"}
  if fault == "grant":
    oauth = options["mcp"]["servers"]["fixture"]["oauth"]
    oauth["grant_type"] = "client_credentials"; oauth.pop("redirect_uri")
  if fault == "https-callback": options["mcp"]["servers"]["fixture"]["oauth"]["redirect_uri"] = "https://callback.invalid/mcp"
  with pytest.raises(ConfigError) as failure: project(data, {name: ["search"] for name in data["mcp"]})
  assert "SYNTHETIC-PRIVATE" not in str(failure.value)

def test_oauth_default_deadline_remains_explicitly_absent_and_invalid_deadline_rejected(tmp_path):
  data = fixture(tmp_path, "streamable-http", "oauth")
  policy = project(data)["bindings"]["fixture"]["oauth_policy"]
  assert set(policy) == {"allowed_origins"}
  data["profile"]["agent_options"]["mcp"]["callback_max_seconds"] = None
  with pytest.raises(ConfigError, match="pi-mcp-official"): project(data)
