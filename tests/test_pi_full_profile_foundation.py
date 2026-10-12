"""Full普通基础及现代高级候选隔离；默认不启动宿主，不签高级资格。"""
import json
import pytest
from agentcfg.schema import ConfigError
from pathlib import Path
from agentcfg.config import LocalConfig, resolve_config
from agentcfg.pi import PiAdapter
from agentcfg.pi_vendor import read_inputs
from agentcfg.workspace import load_public_catalog
ROOT = Path(__file__).resolve().parents[1]
ADVANCED = {"pi-subagents", "model-delegate", "task-keeper", "permissions", "smart-compact", "pi-mcp"}

def resolve(profile, override=None):
  catalog, _ = load_public_catalog(repository=ROOT)
  local = LocalConfig({"schema_version": 1, "machine": {"id": "full-foundation-test"}, "overrides": {"profiles": {profile: override or {}}}})
  return resolve_config(catalog, local, profile_id=profile, adapter_schemas=catalog.adapter_schemas).data

def test_real_full_projection_has_only_explicit_shared_ordinary_foundation():
  base, full = resolve("pi-base"), resolve("pi-full")
  assert full["profile"]["id"] == "pi-full"
  assert full["profile"]["roles"] == base["profile"]["roles"]
  assert {k: v for k, v in full["plugins"].items() if k in base["plugins"]} == base["plugins"]
  assert set(full["plugins"]) - set(base["plugins"]) == {"model-delegate", "task-keeper"}
  assert not {"pi-subagents", "permissions", "smart-compact", "pi-mcp"}.intersection(full["plugins"])
  assert full["profile"]["agent_options"]["model_delegate"]["enabled"] is False
  assert full["profile"]["agent_options"]["task_keeper"]["enabled"] is False
  assert not {"processes", "agent_state", "durable"}.intersection(full["profile"]["agent_options"])
  assert full["profile"]["agent_options"]["resources"]["roles"] == []

def test_actual_full_render_has_separate_profile_and_public_tool_owners():
  data = resolve("pi-full")
  rows = {x.target.path: x.content for x in PiAdapter(ROOT).render(data)}
  manifest = json.loads(rows["pi-home/agentcfg-manifest.json"])
  assert manifest["profile_id"] == "pi-full"
  assert set(manifest["plugin_capabilities"]) == {"pi-todo", "loop-guard", "colorful-footer", "model-delegate", "task-keeper"}
  assert manifest["role_bindings"] == {}
  assert "pi-home/subagents.json" not in rows

def test_real_full_candidate_inputs_bind_same_six_sources_without_advanced_claims():
  _, inputs = read_inputs(ROOT, family="modern", current_profiles=("pi-base",))
  base, full = inputs["profiles"]["pi-base"], inputs["profiles"]["pi-full"]
  assert set(full["source_ids"]) - set(base["source_ids"]) == {"model-delegate-modern", "task-keeper-modern"}
  assert {row["path"] for row in base["runtime_files"]} <= {row["path"] for row in full["runtime_files"]}
  bindings = inputs["capability_bindings"]
  selection = bindings["selections"]["pi-full"]
  assert selection["profile"] == "pi-full" and selection["state"] == "candidate"
  assert selection["bindings"][:6] == bindings["selections"]["pi-base"]["bindings"]
  assert len(selection["bindings"]) == 8
  for row in selection["bindings"][6:]:
    assert bindings["providers"][row["provider_id"]]["verified_host_versions"] == []
  assert full["npm_resolution_seed"]["source"] == "agents/pi/build/resolutions/pi-full.package-lock.json"


@pytest.mark.parametrize("override", [
  {"plugins": ["task-keeper"]},
  {"plugins": ["legacy-model-delegate"]},
  {"agent_options": {"durable": {"enabled": False}}},
])
def test_missing_full_advanced_components_and_unknown_options_fail_closed(override):
  with pytest.raises(ConfigError):
    PiAdapter(ROOT).render(resolve("pi-full", override))
