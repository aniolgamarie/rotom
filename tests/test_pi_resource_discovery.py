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
