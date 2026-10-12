"""现代主会话仅使用原生压缩与独立资源；真实压缩/恢复由独立SDK探针验证。"""
from copy import deepcopy
import json

import pytest

from agentcfg.pi import PiAdapter
from agentcfg.schema import ConfigError
from test_pi_model_config import ROOT, fixture


def manifest(data):
  return next(json.loads(row.content) for row in PiAdapter(ROOT).render(data)
    if row.target.path == "pi-home/agentcfg-manifest.json")


def test_base_native_compaction_has_no_second_owner_or_full_resources(tmp_path):
  data = fixture(tmp_path)
  defaults = data["adapter_documents"]["agent"]["profile_defaults"]["pi-base"]
  data["profile"]["agent_options"]["compaction"] = deepcopy(defaults["agent_options"]["compaction"])
  value = manifest(data)
  assert value["options"]["compaction"] == {"owner": "native"}
  assert "pi-smart-compact" not in value["plugins"]
  assert "task_keeper" not in value["options"]
  assert not value["resources"]["roles"]
  assert not value["resources"]["extensions"]
  assert value["model_bindings"] == {"main": {"provider": "agentcfg-fictional", "model": "fictional-chat"}}


@pytest.mark.parametrize("owner", ["smart-compact", "other-owner"])
def test_base_cannot_select_an_uninstalled_compaction_owner(tmp_path, owner):
  data = fixture(tmp_path)
  data["profile"]["agent_options"]["compaction"] = {"owner": owner}
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)


def test_base_cannot_load_legacy_compactor_as_a_second_extension(tmp_path):
  data = fixture(tmp_path)
  data["profile"]["plugins"].append("pi-smart-compact")
  data["plugins"]["pi-smart-compact"] = deepcopy(data["adapter_documents"]["plugins"]["plugins"]["pi-smart-compact"])
  with pytest.raises(ConfigError): PiAdapter(ROOT).validate(data)


def test_rendering_main_session_does_not_claim_account_or_session_file_ownership(tmp_path):
  data = fixture(tmp_path)
  artifacts = PiAdapter(ROOT).render(data)
  paths = {row.target.path for row in artifacts}
  assert "pi-home/auth.json" not in paths
  assert not any("sessions" in path.split("/") for path in paths)
  assert not any("compaction" in (row.target.selector or "") for row in artifacts)
  # 这里只验产物的所有权边界；实际持久会话/压缩恢复另验SDK。


def test_legacy_profile_keeps_explicit_compactor_selection_without_modern_promotion(tmp_path):
  data = fixture(tmp_path, "pi-fixture")
  data["profile"]["plugins"].append("pi-smart-compact")
  data["plugins"]["pi-smart-compact"] = deepcopy(data["adapter_documents"]["plugins"]["plugins"]["pi-smart-compact"])
  data["profile"]["agent_options"].update(compaction={"owner": "smart-compact"}, smart_compact={"autoTriggerStrategy": "settled"})
  PiAdapter(ROOT).validate(data)
  value = manifest(data)
  assert value["options"]["compaction"]["owner"] == "smart-compact"
  assert "pi-smart-compact" in value["plugins"]
  assert "model_configuration" not in value
