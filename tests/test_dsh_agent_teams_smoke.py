"""显式 native Teams 入口的拒绝路径，不启动第三方宿主。"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import dependencies, runtime_packages


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("team_smoke", ROOT / "scripts/smoke-dsh-agent-teams.py")
smoke = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(smoke)


def test_teams_native_requires_explicit_authorization(tmp_path):
  evidence = tmp_path / "evidence"
  with pytest.raises(SystemExit) as caught:
    smoke.main(["--runtime", str(tmp_path / "runtime"), "--evidence", str(evidence)])
  assert caught.value.code == 2
  assert not evidence.exists()


def test_teams_native_rejects_unsealed_runtime_before_fixture(tmp_path, monkeypatch):
  evidence = tmp_path / "evidence"
  monkeypatch.setattr(dependencies, "read_lock", lambda *_: SimpleNamespace(identity="fictional-lock"))
  monkeypatch.setattr(runtime_packages, "status", lambda *_: "damaged")
  with pytest.raises(SystemExit) as caught:
    smoke.main(["--allow-host", "--runtime", str(tmp_path / "runtime"), "--evidence", str(evidence)])
  assert caught.value.code == 2
  assert not evidence.exists()
