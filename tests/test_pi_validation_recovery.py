"""恢复原生探测的授权门槛；默认测试不启动固定 actor 或发送信号。"""
import importlib.util
from pathlib import Path

import pytest

from agentcfg.schema import ConfigError


def module():
  source = Path(__file__).resolve().parents[1] / "scripts/pi-native-recovery.py"
  spec = importlib.util.spec_from_file_location("native_recovery_fixture", source)
  result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
  return result


def test_recovery_actor_cannot_run_without_native_authorization(monkeypatch):
  monkeypatch.delenv("AGENTCFG_NATIVE_VALIDATION", raising=False)
  with pytest.raises(ConfigError, match="authorization"): module().main(["--worker-marker", "/fixture/recovery-worker.json"])


@pytest.mark.parametrize("args", [["--worker-marker", "relative/recovery-worker.json"], ["--owner-input", "/fixture/arbitrary.json"]])
def test_recovery_actor_rejects_unbound_paths_before_process_actions(monkeypatch, args):
  monkeypatch.setenv("AGENTCFG_NATIVE_VALIDATION", "1")
  value = module(); monkeypatch.setattr(value.sys, "platform", "linux")
  with pytest.raises(ConfigError, match="path"): value.main(args)
