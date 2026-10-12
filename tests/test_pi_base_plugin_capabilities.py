"""真实Base声明与渲染的离线能力映射；不运行SDK。"""
from copy import deepcopy
import json

import pytest

from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from test_pi_profile_projection import resolved, ROOT
from test_pi_base_recipe import selection_inputs

EXPECTED = {"pi-todo": {"capability_id": "todo", "model_tools": ["todo"]},
  "loop-guard": {"capability_id": "loop-protection", "model_tools": []},
  "colorful-footer": {"capability_id": "footer", "model_tools": []}}


def test_real_base_render_maps_user_plugins_to_declared_installed_owners():
  data = resolved()
  manifest = json.loads(next(item.content for item in PiAdapter(ROOT).render(data)
    if item.target.path == "pi-home/agentcfg-manifest.json"))
  assert manifest["plugins"] == list(EXPECTED)
  assert manifest["plugin_capabilities"] == EXPECTED
  bindings, lock = selection_inputs()
  rows = lock.metadata["profile_slices"]["pi-base"]["resource_manifest"]["extensions"]
  for plugin, declaration in EXPECTED.items():
    assert any(row["id"] == plugin and row["capability_id"] == declaration["capability_id"] for row in rows)
  assert bindings["selections"]["pi-base"]["state"] == "current"


def test_legacy_manifest_does_not_gain_capability_projection():
  data = resolved(profile="pi-default")
  manifest = json.loads(next(item.content for item in PiAdapter(ROOT).render(data)
    if item.target.path == "pi-home/agentcfg-manifest.json"))
  assert "plugin_capabilities" not in manifest


@pytest.mark.parametrize("change", ["missing", "unknown", "type", "duplicate-cap", "duplicate-tool"])
def test_modern_metadata_fail_closed_even_if_selected_catalog_matches(change):
  data = resolved()
  rows = data["plugins"]
  rows["pi-todo"].update(deepcopy(EXPECTED["pi-todo"]))
  if change == "missing": rows["pi-todo"].pop("capability_id")
  if change == "unknown": rows["pi-todo"]["model_tools_extra"] = []
  if change == "type": rows["pi-todo"]["model_tools"] = "todo"
  if change == "duplicate-cap": rows["loop-guard"]["capability_id"] = "todo"
  if change == "duplicate-tool": rows["loop-guard"]["model_tools"] = ["todo"]
  data["adapter_documents"]["plugins"]["profile_plugins"]["pi-base"] = deepcopy(rows)
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)
