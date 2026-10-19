"""默认原生回退与候选状态栏边界；不加载第三方组件。"""

import json

import pytest

from agentcfg.schema import ConfigError
from agentcfg.workspace import load_workspace
from test_pi_reboot_configuration import local, REPOSITORY


def test_native_fallback_is_explicitly_not_information_parity(tmp_path):
  workspace = load_workspace(local(tmp_path / "local.toml"), repository=REPOSITORY)
  status = workspace.adapter.feature_readiness(workspace.resolved.data)["status_bar"]
  assert status == {"status": "not_selected", "decision": "admitted", "candidate": "pi-footer@0.5.1",
    "fallback": "native", "information_parity": "not_verified"}


def test_held_powerline_is_absent_from_both_complete_locks():
  from agentcfg.pi_dependencies import PiBackend
  lock = PiBackend().read_lock(REPOSITORY)
  for profile, raw in lock.pairs.items():
    packages = json.loads(raw[1])["packages"]
    assert not any("pi-powerline-footer" in name for name in packages)


@pytest.mark.parametrize("extra", [
  '[overrides.profiles.pi-base]\nplugins=["pi-powerline-footer"]\n',
  '[overrides.profiles.pi-base.agent_options.ui]\nfastRender=false\n',
  '[overrides.profiles.pi-base.agent_options.powerline]\nenabled=false\n',
])
def test_held_or_invented_footer_configuration_is_rejected(tmp_path, extra):
  path = local(tmp_path / "local.toml")
  if extra.startswith('[overrides.profiles.pi-base]\n'):
    path.write_text(path.read_text().replace('[overrides.profiles.pi-base]\n', extra))
  else:
    path.write_text(path.read_text().replace('\n[secrets]', '\n' + extra + '\n[secrets]'))
  with pytest.raises(ConfigError): load_workspace(path, repository=REPOSITORY)
