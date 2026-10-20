"""系统3.8仅转交，业务环境用范围而非补丁版本比较。"""

import ast
from pathlib import Path
import runpy

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("entry", ["work", "rotom-work-shell"])
def test_bootstrap_syntax_accepts_python38_and_missing_environment_is_preparation_error(tmp_path, entry):
  text = (ROOT / entry).read_text()
  ast.parse(text, feature_version=(3, 8))
  namespace = runpy.run_path(str(ROOT / entry), run_name="entry_fixture")
  main = namespace["main"]
  main.__globals__["PYTHON"] = tmp_path / "missing/bin/python"
  assert main() == 5


@pytest.mark.parametrize("entry", ["work", "rotom-work-shell"])
def test_bootstrap_exec_failure_is_stable_preparation_error(tmp_path, monkeypatch, capsys, entry):
  namespace = runpy.run_path(str(ROOT / entry), run_name="entry_fixture")
  main = namespace["main"]
  prepared = tmp_path / "python"
  prepared.write_text("synthetic")
  prepared.chmod(0o700)
  main.__globals__["PYTHON"] = prepared
  monkeypatch.setattr(main.__globals__["sys"], "prefix", str(tmp_path / "other-environment"))
  def unavailable(*a): raise OSError("synthetic private path must not escape")
  monkeypatch.setattr(main.__globals__["os"], "execv", unavailable)
  assert main() == 5
  assert "private path" not in capsys.readouterr().err


@pytest.mark.parametrize("role,expected", [(None, 30), ("shell", 30), ("edit", 30), ("build", 30), ("debug", 30), ("codex", 30), ("pi", 60), ("dsh", 60)])
def test_cli_operation_deadline_only_extends_managed_agents(tmp_path, monkeypatch, role, expected):
  from contextlib import contextmanager
  from types import SimpleNamespace
  import time
  from termcfg import work
  from termcfg.errors import TermcfgError
  monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
  monkeypatch.setenv("HERDR_SOCKET_PATH", "/synthetic/herdr.sock")
  monkeypatch.setattr("termcfg.work_config.read_settings", lambda **kwargs: SimpleNamespace())
  monkeypatch.setattr(work, "_caller_scope", lambda *args: "w1:p1")
  monkeypatch.setattr(work, "canonical_checkout", lambda *args: tmp_path)
  seen = []
  @contextmanager
  def inspect(deadline):
    seen.append(deadline.expires_at - time.monotonic())
    raise TermcfgError(5, "synthetic_stop_before_native")
    yield
  monkeypatch.setattr(work, "operation_lock", inspect)
  args = ["enter", str(tmp_path)] if role is None else ["open", role, "--new"]
  assert work.main(args) == 5
  assert expected - 1 < seen[0] <= expected
