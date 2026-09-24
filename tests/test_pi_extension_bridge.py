"""第一方实例扩展不借全局 npm 解析 helper，桥本身受部署漂移保护。"""
import pytest

from agentcfg.pi import PiAdapter
from agentcfg.pi_extension_bridge import extension_source, bridge_source, HELPERS
from agentcfg.schema import ConfigError
from test_pi_adapter import pi_data, ROOT


def test_rendered_extension_uses_the_managed_local_bridge(tmp_path):
  data = pi_data(tmp_path)
  options = data["profile"]["agent_options"]
  options["resources"]["extensions"] = ["gentle-agent-state"]
  options["agent_state"] = {"mode": "osc", "title": "fixture"}
  adapter = PiAdapter(ROOT)
  artifacts = {row.target.path: row.content for row in adapter.render(data)}
  extension = artifacts["pi-home/extensions/gentle-agent-state.ts"].decode()
  assert "@agentcfg/pi-runtime/" not in extension and "../agentcfg-runtime-api.mjs" in extension
  assert artifacts["pi-home/agentcfg-runtime-api.mjs"] == bridge_source()
  assert "pi-home/agentcfg-runtime-api.mjs" in adapter.runtime_guards(data)["files"]
  assert "args[0] !== runtime" in bridge_source().decode()
  assert all(name in bridge_source().decode() for name in HELPERS)


def test_unknown_runtime_helper_is_not_silently_left_to_global_resolution():
  with pytest.raises(ConfigError, match="helper-unbound"):
    extension_source(b'import { privateThing } from "@agentcfg/pi-runtime/invented";')
