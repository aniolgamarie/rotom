"""Python部署产物与TS消费共用合成协议样本，防止两端各自假设一致。"""
import json

from agentcfg.pi import PiAdapter
from test_pi_model_config import ROOT, fixture


def test_native_model_configuration_matches_shared_protocol_fixture(tmp_path):
  sample = json.loads((ROOT / "tests/fixtures/pi/model-configuration.json").read_text())
  data = fixture(tmp_path)
  data["models"]["main"]["native"] = sample["registry_native"]
  data["profile"]["agent_options"]["model_settings"] = {"main": sample["model_settings"]}
  artifacts = PiAdapter(ROOT).render(data)
  manifest = next(json.loads(item.content) for item in artifacts if item.target.path == "pi-home/agentcfg-manifest.json")
  assert {key: manifest[key] for key in sample["manifest"]} == sample["manifest"]
  providers = {}
  for item in artifacts:
    if item.target.path != "pi-home/models.json": continue
    _, domain, route, field = item.target.selector.split("/")
    assert domain == "providers"
    providers.setdefault(route, {})[field] = json.loads(item.content)
  assert {"providers": providers} == sample["native"]
