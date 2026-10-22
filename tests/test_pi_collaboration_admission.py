"""Pro 仅有基础配方；协作未准入时必须明确失败。"""

import json

import pytest

from agentcfg.schema import ConfigError
from agentcfg.workspace import load_workspace
from test_pi_reboot_configuration import local, REPOSITORY


def test_pro_reports_not_ready_and_does_not_enable_a_delegator(tmp_path):
  workspace = load_workspace(local(tmp_path / "pro.toml", profile="pi-pro"), repository=REPOSITORY)
  feature = workspace.adapter.feature_readiness(workspace.resolved.data)["collaboration"]
  assert feature["status"] == "not_ready" and feature["decision"] == "held"
  assert feature["candidate"] == "@mjakl/pi-subagent@3.1.0"
  assert workspace.resolved.data["profile"]["agent_options"]["collaboration"]["enabled"] is False
  assert workspace.resolved.data["profile"]["plugins"] == ["pi-footer"]


def test_enabling_unadmitted_collaboration_is_exit_two(tmp_path):
  extra = '[overrides.profiles.pi-pro.agent_options.collaboration]\nenabled=true\n'
  with pytest.raises(ConfigError) as caught:
    load_workspace(local(tmp_path / "pro.toml", profile="pi-pro", extra=extra), repository=REPOSITORY)
  assert caught.value.exit_code == 2 and caught.value.code == "pi-collaboration-not-ready"


def test_an_unready_pro_does_not_change_base_or_enter_its_lock(tmp_path):
  from agentcfg.pi_dependencies import PiBackend
  base = load_workspace(local(tmp_path / "base.toml"), repository=REPOSITORY)
  before = base.candidate("synthetic-config-check")
  with pytest.raises(ConfigError):
    load_workspace(local(tmp_path / "pro.toml", profile="pi-pro",
      extra='[overrides.profiles.pi-pro.agent_options.collaboration]\nenabled=true\n'), repository=REPOSITORY)
  assert base.candidate("synthetic-config-check") == before
  lock = PiBackend().read_lock(REPOSITORY)
  for profile in ("pi-base", "pi-pro"):
    assert not any("subagent" in key or "model-delegate" in key for key in json.loads(lock.pairs[profile][1])["packages"])
