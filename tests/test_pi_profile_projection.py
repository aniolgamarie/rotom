"""正式 Base 配置的离线解析与渲染；不安装或启动宿主。"""

from copy import deepcopy
import json

import pytest

from agentcfg.config import LocalConfig, resolve_config
from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError, validate_document
from agentcfg.workspace import load_public_catalog
from test_pi_adapter import ROOT


def resolved(overrides=None, profile="pi-base"):
  catalog, _ = load_public_catalog(repository=ROOT)
  local = LocalConfig({"schema_version": 1, "machine": {"id": "projection-test"},
    "overrides": {"profiles": {profile: overrides or {}}}})
  return resolve_config(catalog, local, profile_id=profile,
    adapter_schemas=catalog.adapter_schemas).data


def test_base_uses_shared_models_without_inheriting_legacy_full_options():
  data = resolved(); profile = data["profile"]
  assert profile["roles"] == {"main": "deepseek_flash_openai"}
  assert profile["providers"] == ["deepseek_openai", "kimi_openai", "glm_openai"]
  assert profile["plugins"] == ["pi-todo", "loop-guard", "colorful-footer"]
  assert profile["skills"] == ["cpp-database-kernel", "neovim-plugin-development", "safe-linux-scripting"]
  assert not {"task_keeper", "model_delegate", "processes", "agent_state", "cursor"} & profile["agent_options"].keys()
  assert profile["agent_options"]["resources"]["roles"] == []
  assert all(not plugin["requires"] for plugin in data["plugins"].values())


def test_base_local_model_and_ui_overrides_are_preserved():
  data = resolved({"roles": {"main": "kimi_k3_openai"}, "plugins": [],
    "agent_options": {"ui": {"quiet_startup": False}}})
  assert data["profile"]["roles"] == {"main": "kimi_k3_openai"}
  assert not data["profile"]["agent_options"]["ui"]["quiet_startup"]
  assert data["plugins"] == {}


@pytest.mark.parametrize("override", [
  {"plugins": ["pi-subagents"]}, {"plugins": ["model-delegate"]},
  {"agent_options": {"task_keeper": {"enabled": False}}},
  {"agent_options": {"model_delegate": {"enabled": False}}},
  {"roles": {"scout": "deepseek_flash_openai"}},
  {"skills": ["model-delegate"]}, {"skills": ["kernel-orchestrate"]},
  {"agent_options": {"resources": {"roles": ["scout"]}}},
  {"agent_options": {"resources": {"extensions": ["exit-command"]}}},
  {"agent_options": {"resources": {"prompts": ["implement"]}}},
  {"agent_options": {"discovery": {"external_skills": ["fixture"]}}},
  {"agent_options": {"runtime": {"engine": "bun"}}},
])
def test_base_rejects_full_and_legacy_configuration_even_when_disabled(override):
  with pytest.raises(ConfigError): resolved(override)


def test_base_does_not_emit_legacy_bridge_or_full_ownership_or_workflow_text():
  data = resolved(); adapter = PiAdapter(ROOT)
  before = deepcopy(data); artifacts = adapter.render(data)
  by_path = {item.target.path: item.content for item in artifacts}
  forbidden = {"pi-home/subagents.json", "pi-home/agentcfg-runtime-api.mjs",
    "pi-home/task-keeper", "codex-home", "cursor-home", "pi-home/cursor-cache"}
  assert not forbidden & by_path.keys()
  assert not forbidden & {item.path for item in adapter.managed_targets(data)}
  assert not forbidden & set(adapter.runtime_guards(data)["files"])
  text = b"\n".join(item.content for item in artifacts if item.target.path.endswith(".md"))
  for word in (b"kernel_task", b"model_delegate", b"kernel-orchestrate", b"subagent", b"fresh reviewer"):
    assert word not in text
  manifest = json.loads(by_path["pi-home/agentcfg-manifest.json"])
  assert manifest["role_bindings"] == {} and manifest["resources"]["roles"] == []
  assert manifest["model_configuration"]["providers"]
  assert {item.target.path for item in artifacts} <= {item.path for item in adapter.managed_targets(data)}
  assert data == before


def test_complete_candidate_expands_only_domain_skills_and_licenses():
  from agentcfg.render import render_candidate
  catalog, adapters = load_public_catalog(repository=ROOT)
  config = resolve_config(catalog, LocalConfig({"schema_version": 1, "machine": {"id": "projection-test"}}),
    profile_id="pi-base", adapter_schemas=catalog.adapter_schemas)
  candidate = render_candidate(config, adapter=adapters["pi"], adapter_schemas=catalog.adapter_schemas,
    lock_identity="synthetic-offline-lock", skill_root=ROOT, skill_target_root="pi-home/skills")
  skills = {item.target.path: item.content for item in candidate.artifacts if item.target.path.startswith("pi-home/skills/")}
  assert {path.split("/")[2] for path in skills} == set(config.data["profile"]["skills"])
  for name in config.data["profile"]["skills"]:
    assert "pi-home/skills/" + name + "/LICENSE" in skills
    body = skills["pi-home/skills/" + name + "/SKILL.md"]
    assert b"kernel_task" not in body and b"kernel-orchestrate" not in body


@pytest.mark.parametrize("change", ["plugin-row", "plugin-extra", "base-catalog-missing"])
def test_direct_adapter_validation_rejects_catalog_contamination(change):
  data = resolved()
  if change == "plugin-row": data["plugins"]["pi-todo"]["version"] = "0.0.0"
  if change == "plugin-extra":
    data["plugins"]["pi-subagents"] = data["adapter_documents"]["plugins"]["plugins"]["pi-subagents"]
    data["profile"]["plugins"].append("pi-subagents")
  if change == "base-catalog-missing": data["adapter_documents"]["plugins"]["profile_plugins"].pop("pi-base")
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)


@pytest.mark.parametrize("document,key", [("agent", "profile_defaults"), ("plugins", "profile_plugins")])
def test_profile_maps_are_closed_and_missing_modern_projection_never_uses_legacy(document, key):
  catalog, _ = load_public_catalog(repository=ROOT)
  documents = deepcopy(catalog.adapter_documents["pi"])
  value = documents[document]
  value[key]["unknown-profile"] = deepcopy(value[key]["pi-base"])
  with pytest.raises(ConfigError):
    validate_document(document, value, adapter_schemas=catalog.adapter_schemas, adapter_id="pi")
  documents = deepcopy(catalog.adapter_documents["pi"])
  del documents[document][key]["pi-base"]
  with pytest.raises(ConfigError):
    PiAdapter(ROOT).schemas().bundles["pi"].profile_policy(documents, "pi-base")


def test_legacy_profile_keeps_its_original_catalog_options_and_artifacts():
  data = resolved(profile="pi-default")
  assert "pi-subagents" in data["plugins"]
  assert data["profile"]["agent_options"]["model_delegate"]["enabled"] is True
  assert data["profile"]["roles"]["scout"] == "deepseek_flash_openai"
  paths = {item.target.path for item in PiAdapter(ROOT).render(data)}
  assert {"pi-home/subagents.json", "pi-home/agentcfg-runtime-api.mjs"} <= paths


def test_modern_profile_cannot_fall_through_to_legacy_launcher(tmp_path):
  data = resolved()
  launch = PiAdapter(ROOT).launch_spec(data, cwd=tmp_path, runtime_root=tmp_path / "runtime",
    instance_root=tmp_path / "instance", lock_identity="a" * 64)
  assert launch.argv == ("node", "--experimental-import-meta-resolve", str(tmp_path / "runtime/runtime/official-launch.mjs"),
    "--manifest", str(tmp_path / "instance/pi-home/agentcfg-manifest.json"))
  assert not any(arg.endswith("runtime/launch.mjs") for arg in launch.argv)
