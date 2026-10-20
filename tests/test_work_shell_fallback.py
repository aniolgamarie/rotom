"""无启动意图时只转交普通shell。"""

from pathlib import Path

import pytest

from termcfg.errors import TermcfgError
from termcfg.work_shell import fallback_shell, main


def test_fallback_execs_literal_shell(tmp_path, monkeypatch):
  path = tmp_path / "shell with space"
  path.write_text("synthetic")
  path.chmod(0o700)
  monkeypatch.setenv("SHELL", str(path))
  observed = []
  monkeypatch.setattr("os.execvpe", lambda *args: observed.append(args))
  fallback_shell()
  assert observed[0][0] == str(path)
  assert observed[0][1] == [str(path)]
  assert "ROTOM_WORK_LAUNCH_V1" not in observed[0][2]


def test_recursive_shell_rejected(monkeypatch):
  root = Path(__file__).resolve().parents[1]
  monkeypatch.setenv("SHELL", str(root / "rotom-work-shell"))
  with pytest.raises(TermcfgError) as error:
    fallback_shell()
  assert error.value.code == 2


def test_malformed_payload_cannot_exec_target(tmp_path, monkeypatch, capsys):
  path = tmp_path / "fallback"
  path.write_text("synthetic")
  path.chmod(0o700)
  monkeypatch.setenv("SHELL", str(path))
  monkeypatch.setenv("ROTOM_WORK_LAUNCH_V1", '{"command":"forbidden"}')
  observed = []
  monkeypatch.setattr("os.execvpe", lambda *args: observed.append(args))
  main()
  assert len(observed) == 1 and observed[0][0] == str(path)
  assert "ROTOM_WORK_LAUNCH_V1" not in observed[0][2]
  assert "work_launch" in capsys.readouterr().err
