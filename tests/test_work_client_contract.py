"""配置诊断必须先于新server；外部attach释放管理锁。"""

from contextlib import contextmanager
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from termcfg.errors import TermcfgError
from termcfg.herdr import Deadline
from termcfg.work_config import WorkSettings, validate_native_config
from termcfg import work


def config_file(monkeypatch):
  path = Path(os.environ["HOME"]) / ".config/herdr/config.toml"
  monkeypatch.setenv("XDG_CONFIG_HOME", str(path.parents[1]))
  path.parent.mkdir(parents=True)
  path.write_text('[terminal]\ndefault_shell="rotom-work-shell"\nshell_mode="non_login"\n'
    '[session]\nresume_agents_on_restore=false\n')
  path.chmod(0o600)
  return path


def test_missing_config_never_invokes_native(monkeypatch):
  path = Path(os.environ["HOME"]) / ".config"
  monkeypatch.setenv("XDG_CONFIG_HOME", str(path))
  monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("missing file used native defaults"))
  with pytest.raises(TermcfgError) as error:
    validate_native_config("/synthetic/herdr", Deadline())
  assert error.value.code == 5


def test_native_diagnostics_nonzero_never_pass_and_do_not_echo_text(monkeypatch):
  path = config_file(monkeypatch)
  calls = []
  def run(argv, **kwargs):
    calls.append((argv, kwargs))
    return SimpleNamespace(returncode=1, stdout=b"synthetic private diagnostic", stderr=b"")
  monkeypatch.setattr("subprocess.run", run)
  with pytest.raises(TermcfgError) as error:
    validate_native_config("/synthetic/herdr", Deadline())
  assert error.value.code == 5
  assert calls[0][0] == ["/synthetic/herdr", "config", "check"]
  assert calls[0][1]["env"]["HERDR_CONFIG_PATH"] == str(path)
  assert "private" not in error.value.reason


def test_native_check_detects_file_change_and_typed_restore(monkeypatch):
  path = config_file(monkeypatch)
  def run(*a, **k):
    path.write_text(path.read_text() + "\n# concurrent change\n")
    return SimpleNamespace(returncode=0)
  monkeypatch.setattr("subprocess.run", run)
  with pytest.raises(TermcfgError): validate_native_config("/synthetic/herdr", Deadline())
  path.write_text(path.read_text().replace("resume_agents_on_restore=false", 'resume_agents_on_restore="false"'))
  monkeypatch.setattr("subprocess.run", lambda *a, **k: pytest.fail("unsafe resume configuration"))
  with pytest.raises(TermcfgError): validate_native_config("/synthetic/herdr", Deadline())


def test_external_enter_releases_lock_before_attach_and_no_nested_tmux(tmp_path, monkeypatch):
  settings = WorkSettings(tmp_path / "local.toml", "herdr", "main")
  held = []
  @contextmanager
  def lock(*a, **k):
    held.append(True)
    try: yield
    finally: held.pop()
  api = SimpleNamespace(socket_path="/synthetic/socket", identity=(3, 4))
  @contextmanager
  def connected(*a, **k):
    assert held and k["start"] is True
    yield api, "/synthetic/herdr"
  monkeypatch.setattr(work, "canonical_checkout", lambda *a: tmp_path)
  monkeypatch.setattr("termcfg.work_config.read_settings", lambda **k: settings)
  monkeypatch.setattr(work, "operation_lock", lock)
  monkeypatch.setattr(work, "connected", connected)
  monkeypatch.setattr(work, "enter_project", lambda *a: None)
  monkeypatch.setattr(work.os, "lstat", lambda *a: SimpleNamespace(st_dev=3, st_ino=4))
  calls = []
  def attach(binary, argv, environment):
    assert not held
    calls.append(argv)
  monkeypatch.setattr(os, "execvpe", attach)
  assert work.main(["enter", "."]) == 0
  assert calls == [["/synthetic/herdr", "session", "attach", "main"]]
  monkeypatch.setenv("TMUX", "synthetic")
  assert work.main(["enter", "."]) == 4
  assert len(calls) == 1
