"""角色和项目资源必须通过声明进入清单，磁盘存在不授予加载资格。"""

import json
from pathlib import Path
from copy import deepcopy

import pytest
import yaml

from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from test_pi_adapter import ROOT, pi_data


def test_compiled_role_uses_exact_model_and_tool_ceiling(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["roles"]["scout"] = "main"
  data["profile"]["agent_options"]["resources"]["roles"] = ["scout"]
  adapter = PiAdapter(ROOT)
  adapter.validate_selected(data)
  artifacts = adapter.render(data)
  role = next(a.content.decode() for a in artifacts if a.target.path == "pi-home/agents/scout.md")
  header = yaml.safe_load(role.split("---", 2)[1])
  assert header["model"] == "agentcfg-fictional/fictional-chat"
  assert header["tools"] == "read, grep, find, ls"
  assert header["extensions"] is False and header["allowed_subagents"] is False
  assert header["inherit_context"] is False


def test_selected_ordinary_role_cannot_silently_fall_back_when_main_is_bound(tmp_path):
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["resources"]["roles"] = ["scout"]
  with pytest.raises(ConfigError, match="pi-role-model-unbound"):
    PiAdapter(ROOT).validate_selected(data)


def test_project_resource_paths_are_explicit_and_managed_override_is_always_rejected(tmp_path):
  data = pi_data(tmp_path)
  resources = data["adapter_documents"]["agent"]["resources"]
  resources["local-prompt"] = {"kind": "prompt", "path": ".pi/prompts/local.md", "scope": "project"}
  data["profile"]["agent_options"]["resources"]["prompts"] = ["local-prompt"]
  adapter = PiAdapter(ROOT)
  with pytest.raises(ConfigError):
    adapter.validate(data)
  data["profile"]["agent_options"]["discovery"]["project_resources"] = True
  manifest = json.loads(next(a.content for a in adapter.render(data) if a.target.path.endswith("agentcfg-manifest.json")))
  assert manifest["project_resources"] == [{"id": "local-prompt", "kind": "prompts", "path": ".pi/prompts/local.md"}]
  assert manifest["resources"]["prompts"] == []
  resources["local-prompt"]["override"] = "task-keeper-reader"
  with pytest.raises(ConfigError):
    adapter.validate(data)


def test_published_profiles_explicitly_select_every_array_and_do_not_enable_cursor_on_node():
  import tomllib
  for name in ("pi-default", "pi-managed", "pi-codex", "pi-cursor"):
    profile = tomllib.loads((ROOT / "profiles" / (name + ".toml")).read_text())
    assert all(isinstance(profile[key], list) for key in ("providers", "models", "rules", "skills", "plugins", "mcp"))
    assert set(profile["agent_options"]["resources"]) == {"roles", "themes", "prompts", "extensions"}
    if name == "pi-managed":
      assert profile["agent_options"]["model_delegate"]["enabled"] is False
      assert "task-keeper" in profile["plugins"]
    else:
      assert "model-delegate" in profile["plugins"] and "model-delegate" in profile["skills"]
    assert (profile["agent_options"]["runtime"]["engine"] == "bun") == (name == "pi-cursor")


@pytest.mark.parametrize("name", ["commit", "debug", "docs", "explain", "perf", "pr", "refactor", "security", "test"])
def test_modern_ordinary_prompt_is_loaded_only_by_explicit_selection(name):
  from agentcfg.config import LocalConfig, resolve_config
  from agentcfg.render import render_candidate
  from agentcfg.workspace import load_public_catalog
  catalog, adapters = load_public_catalog(repository=ROOT)
  selected = "ordinary-" + name
  local = LocalConfig({"schema_version": 1, "machine": {"id": "ordinary-prompt-test"},
    "overrides": {"profiles": {"pi-base": {"agent_options": {"resources": {"prompts": [selected]}}}}}})
  config = resolve_config(catalog, local, profile_id="pi-base", adapter_schemas=catalog.adapter_schemas)
  candidate = render_candidate(config, adapter=adapters["pi"], adapter_schemas=catalog.adapter_schemas,
    lock_identity="synthetic-offline-lock", skill_root=ROOT, skill_target_root="pi-home/skills")
  prompts = {a.target.path: a.content for a in candidate.artifacts if a.target.path.startswith("pi-home/prompts/")}
  assert set(prompts) == {"pi-home/prompts/" + name + ".md"}
  body = prompts["pi-home/prompts/" + name + ".md"]
  assert body == (ROOT / "agents/pi/prompts/ordinary" / (name + ".md")).read_bytes()
  for unavailable in (b"kernel_task", b"model_delegate", b"fresh reviewer"):
    assert unavailable not in body
  manifest = json.loads(next(a.content for a in candidate.artifacts if a.target.path.endswith("agentcfg-manifest.json")))
  assert manifest["resources"]["prompts"] == ["pi-home/prompts/" + name + ".md"]
  assert manifest["resource_ids"]["prompts"] == {selected: "pi-home/prompts/" + name + ".md"}


@pytest.mark.parametrize("change", ["unknown-id", "legacy", "kind", "project", "traversal", "noncanonical", "absolute", "suffix"])
def test_base_available_prompts_cannot_authorize_other_resources(change):
  from test_pi_profile_projection import resolved
  data = resolved()
  declaration = data["adapter_documents"]["agent"]
  available = declaration["profile_available_resources"]["pi-base"]
  resource = declaration["resources"]["ordinary-debug"]
  available["prompts"] = ["ordinary-debug"]
  if change == "unknown-id": available["prompts"] = ["not-declared"]
  elif change == "legacy": available["prompts"] = ["debug"]
  elif change == "kind": resource["kind"] = "extension"
  elif change == "project": resource["scope"] = "project"
  elif change == "traversal": resource["path"] = "agents/pi/prompts/ordinary/../debug.md"
  elif change == "noncanonical": resource["path"] = "agents/pi/prompts/ordinary//debug.md"
  elif change == "absolute": resource["path"] = "/agents/pi/prompts/ordinary/debug.md"
  elif change == "suffix": resource["path"] = "agents/pi/prompts/ordinary/debug.ts"
  # 即使本次没有选择该项，也不能让坏声明进入未来Base可选集合。
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate_selected(data)


@pytest.mark.parametrize("available", [
  {"pi-full": {"prompts": []}}, {"pi-base": {"roles": []}},
  {"pi-base": {"extensions": []}}, {"pi-base": {"themes": []}},
  {"pi-base": {"prompts": ["ordinary-debug", "ordinary-debug"]}},
  {"pi-base": {"prompts": [True]}},
])
def test_available_prompt_metadata_schema_stays_closed(available):
  import tomllib
  from agentcfg.schema import validate_document
  declaration = tomllib.loads((ROOT / "agents/pi/agent.toml").read_text())
  declaration["profile_available_resources"] = available
  from agentcfg.workspace import load_public_catalog
  catalog, _ = load_public_catalog(repository=ROOT)
  with pytest.raises(ConfigError):
    validate_document("agent", declaration, adapter_schemas=catalog.adapter_schemas, adapter_id="pi")


def test_legacy_profile_still_renders_original_optional_prompt_routes(tmp_path):
  names = ["commit", "debug", "docs", "explain", "perf", "pr", "refactor", "security", "test"]
  data = pi_data(tmp_path)
  data["profile"]["agent_options"]["resources"]["prompts"] = names
  artifacts = PiAdapter(ROOT).render(data)
  prompts = {a.target.path: a.content for a in artifacts if a.target.path.startswith("pi-home/prompts/")}
  assert set(prompts) == {"pi-home/prompts/" + name + ".md" for name in names}
  for name in names:
    assert prompts["pi-home/prompts/" + name + ".md"] == (ROOT / "agents/pi/prompts" / (name + ".md")).read_bytes()
