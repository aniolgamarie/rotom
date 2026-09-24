"""可选能力的选择、版本与可发现资源必须独立核验。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from agentcfg.pi import PiAdapter
from agentcfg.pi_dependencies import PiBackend
from agentcfg.schema import ConfigError
from agentcfg.process import DependencyError
from agentcfg.storage import Tree
from test_pi_adapter import ROOT, pi_data
from test_pi_release_gate import save


def select(data, name):
  data["plugins"][name] = data["adapter_documents"]["plugins"]["plugins"][name]
  data["profile"]["plugins"].append(name)
  if name == "pi-cursor":
    data["providers"]["cursor"] = {"protocol": "oauth-dynamic", "auth_kind": "oauth"}
    data["profile"]["providers"].append("cursor")
    data["profile"]["agent_options"].update(cursor={"endpoint": "https://agentn.us.api5.cursor.sh", "network_route": "cursor-direct"},
      network={"routes": {"cursor-direct": {"mode": "direct", "provider_ids": ["cursor"]}}})


def test_cursor_requires_bun_and_cannot_be_added_to_managed_node_profile(tmp_path):
  data = pi_data(tmp_path); select(data, "pi-cursor")
  with pytest.raises(ConfigError, match="plugin-combination"): PiAdapter(ROOT).validate(data)
  data["profile"]["agent_options"]["runtime"]["engine"] = "bun"
  PiAdapter(ROOT).validate(data)
  data["profile"]["agent_options"]["task_keeper"]["enabled"] = True
  with pytest.raises(ConfigError, match="managed-engine"): PiAdapter(ROOT).validate(data)


def test_unselected_optional_packages_are_not_needed_for_core_render(tmp_path):
  data = pi_data(tmp_path)
  artifacts = PiAdapter(ROOT).render(data)
  manifest = json.loads(next(item.content for item in artifacts if item.target.path.endswith("agentcfg-manifest.json")))
  assert "openspec" not in manifest["plugins"] and "pi-cursor" not in manifest["plugins"]


def test_openspec_resources_are_full_versioned_skills_not_npm_marker():
  package = ROOT / "agents/pi/packages/openspec-resources"
  metadata = json.loads((package / "package.json").read_text())
  assert metadata["dependencies"] == {"@fission-ai/openspec": "1.11.0"}
  manifest = json.loads((ROOT / "agents/pi/runtime/openspec-resources.json").read_text())
  assert len(manifest["skills"]) == 12
  for directory in manifest["skills"]:
    text = (package / directory / "SKILL.md").read_text()
    assert 'generatedBy: "1.11.0"' in text and len(text) > 500
  source = json.loads((package / "SOURCE.json").read_text())
  assert source["integrity"].startswith("sha512-")
  for path, checksum in source["files"].items(): assert hashlib.sha256((package / path).read_bytes()).hexdigest() == checksum


def test_openspec_command_uses_selected_runtime_and_rejects_missing_or_wrong_version(tmp_path, monkeypatch):
  backend = PiBackend(); data = pi_data(tmp_path)
  workspace = SimpleNamespace(resolved=SimpleNamespace(data=data), instance=tmp_path, profile="pi-fixture")
  monkeypatch.setattr(backend, "runtime_identity", lambda *_: "runtime")
  monkeypatch.setattr(backend, "root", lambda *_: tmp_path / "runtime")
  monkeypatch.setattr(backend, "status", lambda *_: "installed")
  lock = SimpleNamespace(metadata={"profile_slices": {"pi-fixture": {"package_path": "pi-fixture/package.json"}}})
  with pytest.raises(DependencyError, match="未选择"): backend.openspec_argv(workspace, lock)
  select(data, "openspec")
  with pytest.raises(DependencyError, match="入口不完整"): backend.openspec_argv(workspace, lock)

  save(tmp_path / "runtime", "pi-fixture/node_modules/@fission-ai/openspec/package.json", {"version": "1.11.0"})
  with Tree(tmp_path / "runtime") as tree: tree.write_state("pi-fixture/node_modules/@fission-ai/openspec/bin/openspec.js", b"fixture only")
  assert backend.openspec_argv(workspace, lock) == ["node", str(tmp_path / "runtime/pi-fixture/node_modules/@fission-ai/openspec/bin/openspec.js")]
  with Tree(tmp_path / "runtime") as tree: tree.write_state("pi-fixture/node_modules/@fission-ai/openspec/package.json", b'{"version":"1.13.0"}')
  with pytest.raises(DependencyError, match="入口不完整"): backend.openspec_argv(workspace, lock)


def test_superpowers_retains_all_skill_support_files_and_executable_modes():
  from agentcfg.pi_vendor import build_archive
  package = ROOT / "agents/pi/packages/superpowers-vendor"
  source = json.loads((package / "SOURCE.json").read_text())
  derived = {"package.json", ".pi/extensions/superpowers.ts", "skills/using-superpowers/references/pi-tools.md"}
  assert len(list((package / "skills").glob("*/SKILL.md"))) == 14
  for name, expected in source["files"].items():
    path = package / name
    if name not in derived:
      assert hashlib.sha256(path.read_bytes()).hexdigest() == expected["sha256"]
    assert bool(path.stat().st_mode & 0o111) == expected["executable"]
  recipes = json.loads((ROOT / "agents/pi/build/recipes.json").read_text())
  archive, record = build_archive(ROOT, recipes["sources"]["superpowers"])
  assert record["commit"] == source["commit"]
  assert record["archive_digest"] == hashlib.sha256(archive).hexdigest()


def test_mcp_stdio_requires_matching_explicit_interactive_command_and_never_imports_global_config(tmp_path):
  from agentcfg.pi_mcp import configuration
  data = pi_data(tmp_path)
  select(data, "pi-mcp")
  with pytest.raises(ConfigError, match="service-binding-required"):
    configuration(data)
  options = data["profile"]["agent_options"]
  options["mcp"] = {"servers": {"fixture": {"transport": "stdio", "command_ref": "mcp-fixture"}}}
  options["external_tools"] = {"mcp-fixture": {"executable": "/fixture/server", "args": ["--stdio"], "interactive": True}}
  data["mcp"] = {"fixture": {"transport": "stdio", "command": "/fixture/server", "args": ["--stdio"]}}
  result = configuration(data)
  assert set(result["mcpServers"]) == {"fixture"}
  assert result["settings"]["sampling"] is False and result["settings"]["hostConfigDiscovery"] == "off"
  data["mcp"]["fixture"]["args"] = ["--changed"]
  with pytest.raises(ConfigError, match="command-binding-required"):
    configuration(data)
  data["plugins"].pop("pi-mcp")
  with pytest.raises(ConfigError, match="not-selected"):
    configuration(data)


def test_mcp_http_projects_only_declared_service_route_and_credential_reference(tmp_path):
  from agentcfg.pi import key_variable
  from agentcfg.adapter import SecretRef
  data = pi_data(tmp_path); select(data, "pi-permissions"); select(data, "pi-mcp")
  data["profile"]["mcp"] = ["fixture"]
  data["mcp"] = {"fixture": {"transport": "streamable-http", "url": "https://mcp.invalid/service", "credential_ref": "secret:mcp"}}
  options = data["profile"]["agent_options"]
  options["mcp"] = {"servers": {"fixture": {"transport": "streamable-http", "network_route": "mcp-route", "authentication": "bearer"}}}
  options["network"] = {"routes": {"mcp-route": {"mode": "direct", "provider_ids": [], "service_ids": ["mcp:fixture"]}}}
  adapter = PiAdapter(ROOT); adapter.validate(data)
  manifest = json.loads(next(a.content for a in adapter.render(data) if a.target.path.endswith("agentcfg-manifest.json")))
  server = manifest["mcp_config"]["mcpServers"]["fixture"]
  assert server["bearerTokenEnv"] == key_variable("mcp:fixture") and server["oauth"] is False
  launch = adapter.launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime", instance_root=tmp_path / "instance", lock_identity="fixture")
  assert any(row.name == key_variable("mcp:fixture") and row.value == SecretRef("secret:mcp") for row in launch.environment)
  options["network"]["routes"]["mcp-route"]["service_ids"] = []
  with pytest.raises(ConfigError, match="http-route-required"):
    adapter.validate(data)


def test_btw_explicit_model_cannot_fall_back_to_a_different_selected_main(tmp_path):
  data = pi_data(tmp_path); select(data, "pi-btw")
  data["profile"]["agent_options"]["btw"] = {"model": "agentcfg-fictional/fictional-chat"}
  PiAdapter(ROOT).validate(data)
  data["profile"]["agent_options"]["btw"]["model"] = "agentcfg-fictional/missing"
  with pytest.raises(ConfigError, match="pi-helper-model-unbound"):
    PiAdapter(ROOT).validate(data)


def test_mcp_sampling_is_explicit_and_model_must_be_in_current_selection(tmp_path):
  from agentcfg.pi_mcp import configuration
  data = pi_data(tmp_path); select(data, "pi-mcp"); select(data, "pi-permissions")
  options = data["profile"]["agent_options"]
  options["mcp"] = {"servers": {"fixture": {"transport": "streamable-http", "network_route": "mcp-direct", "authentication": "none"}},
    "sampling": {"enabled": True, "model": "agentcfg-fictional/fictional-chat", "max_tokens": 512, "auto_approve": False}}
  data["mcp"] = {"fixture": {"transport": "streamable-http", "url": "https://mcp.invalid/service"}}
  data["profile"]["mcp"] = ["fixture"]
  options["network"] = {"routes": {"mcp-direct": {"mode": "direct", "provider_ids": [], "service_ids": ["mcp:fixture"]}}}
  adapter = PiAdapter(ROOT)
  adapter.validate(data)
  projected = configuration(data)
  assert projected["settings"]["sampling"] is True and projected["settings"]["samplingAutoApprove"] is False
  options["mcp"]["sampling"]["model"] = "unselected/private-model"
  with pytest.raises(ConfigError, match="pi-helper-model-unbound"): adapter.validate(data)
  options["mcp"]["sampling"]["enabled"] = False
  with pytest.raises(ConfigError, match="pi-mcp-sampling-not-selected"): configuration(data)


def test_mcp_oauth_and_direct_tools_require_explicit_origin_account_and_tool_bindings(tmp_path):
  from agentcfg.pi_mcp import configuration
  from agentcfg.pi import key_variable
  data = pi_data(tmp_path); select(data, "pi-permissions"); select(data, "pi-mcp")
  data["profile"]["mcp"] = ["fixture"]
  data["mcp"] = {"fixture": {"transport": "streamable-http", "url": "https://mcp.invalid/service", "credential_ref": "secret:mcp-client"}}
  options = data["profile"]["agent_options"]
  binding = {"transport": "streamable-http", "network_route": "mcp-route", "authentication": "oauth",
    "direct_tools": {"enabled": True, "tools": ["search"]},
    "oauth": {"grant_type": "client_credentials", "client_id": "fixture-client", "allowed_origins": ["https://auth.invalid"],
      "auth_server_metadata_url": "https://auth.invalid/.well-known/oauth-authorization-server"}}
  options["mcp"] = {"servers": {"fixture": binding}}
  options["network"] = {"routes": {"mcp-route": {"mode": "direct", "provider_ids": [], "service_ids": ["mcp:fixture"]}}}
  PiAdapter(ROOT).validate(data)
  server = configuration(data)["mcpServers"]["fixture"]
  assert server["auth"] == "oauth" and server["directTools"] == ["search"]
  assert server["oauth"]["clientSecret"] == "${" + key_variable("mcp:fixture") + "}"
  rendered = PiAdapter(ROOT).render(data)
  manifest = json.loads(next(row.content for row in rendered if row.target.path.endswith("agentcfg-manifest.json")))
  assert manifest["mcp_config"]["mcpServers"]["fixture"]["oauth"]["clientSecret"] == server["oauth"]["clientSecret"]
  binding["oauth"]["auth_server_metadata_url"] = "https://unselected.invalid/metadata"
  with pytest.raises(ConfigError, match="pi-mcp-oauth-origin"): configuration(data)
  binding["oauth"].pop("auth_server_metadata_url")
  binding["oauth"]["client_id"] = "${UNSELECTED_SECRET}"
  with pytest.raises(ConfigError, match="pi-mcp-oauth-literal"): configuration(data)
  binding["oauth"]["client_id"] = "fixture-client"
  binding["oauth"]["grant_type"] = "authorization_code"
  with pytest.raises(ConfigError, match="pi-mcp-oauth-redirect-required"): configuration(data)
  binding["oauth"]["redirect_uri"] = "https://callback.invalid/mcp"
  assert configuration(data)["mcpServers"]["fixture"]["oauth"]["redirectUri"] == "https://callback.invalid/mcp"
  binding["oauth"]["redirect_uri"] = "http://localhost:8765/callback"
  assert configuration(data)["mcpServers"]["fixture"]["oauth"]["redirectUri"] == "http://localhost:8765/callback"
  binding["oauth"]["redirect_uri"] = "http://public.invalid:8765/callback"
  with pytest.raises(ConfigError): configuration(data)
