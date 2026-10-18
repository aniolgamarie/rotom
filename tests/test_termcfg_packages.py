"""锁定插件安装只使用虚构字节与假下载。"""

import hashlib
import io
import os
import tarfile
import json
import threading
import time

import pytest

from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.errors import TermcfgError
from termcfg import packages
from termcfg.state import read_state


def test_locked_plugin_sync_activates_only_declared_files(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  content = b"synthetic plugin entry\n"
  output = io.BytesIO()
  with tarfile.open(fileobj=output, mode="w:gz") as archive:
    member = tarfile.TarInfo("zinit-" + "a" * 40 + "/zinit.zsh")
    member.size = len(content)
    member.mode = 0o600
    archive.addfile(member, io.BytesIO(content))
  data = output.getvalue()
  asset = {"id": "zinit", "repo": "zdharma-continuum/zinit", "commit": "a" * 40,
           "platform": "all", "url": "https://codeload.github.com/zdharma-continuum/zinit/tar.gz/" + "a" * 40,
           "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
           "archive": "tar.gz", "entry": "zinit.zsh",
           "resources": [{"path": "zinit.zsh", "sha256": hashlib.sha256(content).hexdigest(), "mode": "0600"}]}
  packages._validate_plugin_asset(asset)
  monkeypatch.setattr(packages, "_read_lock_raw", lambda component: ({"assets": {"zsh": [asset], "tmux": []}}, "b" * 64))
  monkeypatch.setattr(packages, "_download", lambda *a, **k: data)
  result = packages.sync(machine, "zsh")
  current = packages._plugin_group_root("zsh") / "current"
  assert result["prepared"] == ["zinit"]
  assert current.is_symlink()
  assert (current / "zinit/zinit.zsh").read_bytes() == content
  assert (current / "zinit/zinit.zsh").stat().st_mode & 0o777 == 0o600


def test_slow_fake_download_emits_heartbeat_without_leaking_url(isolated_environment, monkeypatch, capsys):
  from termcfg.diagnostics import Progress
  class SlowResponse:
    def __init__(self):
      self.calls = 0
    def __enter__(self):
      return self
    def __exit__(self, *args):
      return False
    def read(self, amount):
      self.calls += 1
      if self.calls == 1:
        time.sleep(1.7)
        return b"synthetic bytes"
      return b""
  monkeypatch.setattr(packages.urllib.request, "urlopen", lambda *a, **k: SlowResponse())
  assert packages._download("https://invalid.example/private-url", expected_size=15,
                            timeout=10, progress=Progress("sync"), component="zsh") == b"synthetic bytes"
  stderr = capsys.readouterr().err
  assert stderr.count("sync | download | zsh") >= 2
  assert "private-url" not in stderr


def test_fake_download_length_and_total_timeout_are_diagnosed(isolated_environment, monkeypatch):
  from termcfg.diagnostics import Progress
  class Response:
    def __init__(self, *, slow=False):
      self.slow = slow
      self.calls = 0
    def __enter__(self):
      return self
    def __exit__(self, *args):
      return False
    def read(self, amount):
      self.calls += 1
      if self.calls == 1:
        if self.slow:
          time.sleep(0.1)
        return b"short"
      return b""
  monkeypatch.setattr(packages.urllib.request, "urlopen", lambda *a, **k: Response())
  with pytest.raises(TermcfgError) as error:
    packages._download("https://invalid.example/fake", expected_size=6,
                       timeout=10, progress=Progress("sync"), component="zsh")
  assert error.value.reason == "asset_length_mismatch"
  monkeypatch.setattr(packages.urllib.request, "urlopen", lambda *a, **k: Response(slow=True))
  with pytest.raises(TermcfgError) as error:
    packages._download("https://invalid.example/fake", expected_size=None,
                       timeout=0.05, progress=Progress("sync"), component="zsh")
  assert error.value.reason == "download_total_timeout"


def test_same_machine_second_sync_rejected_before_package_write(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  entered = threading.Event()
  release = threading.Event()
  def held_plugin_sync(*args, **kwargs):
    entered.set()
    release.wait(5)
    return {"component": "zsh", "prepared": [], "next_command": "./termcfg doctor"}
  monkeypatch.setattr(packages, "_sync_plugins", held_plugin_sync)
  thread = threading.Thread(target=lambda: packages.sync(machine, "zsh"))
  thread.start()
  assert entered.wait(2)
  try:
    with pytest.raises(TermcfgError) as error:
      packages.sync(machine, "zsh")
    assert error.value.code == 4
    assert not (machine.private_state_root / "state.json").exists()
  finally:
    release.set()
    thread.join(3)



def _plugin_fixture(isolated_environment, monkeypatch):
  content = b"# synthetic plugin\n"
  stream = io.BytesIO()
  with tarfile.open(fileobj=stream, mode="w:gz") as archive:
    member = tarfile.TarInfo("source/zinit.zsh")
    member.size = len(content)
    member.mode = 0o644
    archive.addfile(member, io.BytesIO(content))
  data = stream.getvalue()
  asset = {"id": "zinit", "repo": "zdharma-continuum/zinit", "commit": "a" * 40,
           "platform": "all", "url": "https://codeload.github.com/zdharma-continuum/zinit/tar.gz/" + "a" * 40,
           "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "archive": "tar.gz",
           "entry": "zinit.zsh", "resources": [{"path": "zinit.zsh", "sha256": hashlib.sha256(content).hexdigest(), "mode": "0600"}]}
  lock = isolated_environment.root / "plugins.json"
  lock.write_text(json.dumps({"version": 1, "component": "plugins", "assets": {"zsh": [asset], "tmux": []}}))
  monkeypatch.setattr(packages, "lock_path", lambda component: lock)
  return lock, data


def test_two_plugin_lock_maintainers_detect_stale_snapshot(isolated_environment, monkeypatch):
  lock, data = _plugin_fixture(isolated_environment, monkeypatch)
  barrier = threading.Barrier(2)
  def download(*args, **kwargs):
    barrier.wait(timeout=5)
    return data
  monkeypatch.setattr(packages, "_download", download)
  results = []
  def maintainer():
    try:
      packages.lock_plugin("zsh", "zinit", "b" * 40)
      results.append(0)
    except TermcfgError as exc:
      results.append(exc.code)
  threads = [threading.Thread(target=maintainer) for _ in range(2)]
  for thread in threads:
    thread.start()
  for thread in threads:
    thread.join(8)
  assert all(not thread.is_alive() for thread in threads)
  assert sorted(results) == [0, 4]
  assert packages._read_lock_raw("zsh")[0]["assets"]["zsh"][0]["commit"] == "b" * 40


def test_plugin_lock_during_confirmation_invalidates_preview(isolated_environment, fake_terminal_commands, monkeypatch):
  from termcfg import preview, transaction
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  lock, data = _plugin_fixture(isolated_environment, monkeypatch)
  monkeypatch.setattr(preview, "_lock_digest", lambda *args: hashlib.sha256(lock.read_bytes()).hexdigest())
  monkeypatch.setattr(packages, "_download", lambda *args, **kwargs: data)
  def confirm(plan):
    packages.lock_plugin("zsh", "zinit", "b" * 40)
    return set(), None
  with pytest.raises(TermcfgError) as error:
    transaction.apply(machine, ("zsh",), plan_id=None, adopted=set(), confirm_zshenv=None, confirm=confirm)
  assert error.value.code == 4
  assert not (machine.target_home / ".zshrc").exists()


def test_plugin_lock_update_during_sync_rejects_old_snapshot(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  lock, data = _plugin_fixture(isolated_environment, monkeypatch)
  changed = [False]
  def download(*args, **kwargs):
    if not changed[0]:
      changed[0] = True
      packages.lock_plugin("zsh", "zinit", "b" * 40)
    return data
  monkeypatch.setattr(packages, "_download", download)
  with pytest.raises(TermcfgError) as error:
    packages.sync(machine, "zsh")
  assert error.value.code == 4
  assert not (packages._plugin_group_root("zsh") / "current").exists()


def test_interrupted_plugin_lock_preserves_old_bytes(isolated_environment, monkeypatch):
  lock, _ = _plugin_fixture(isolated_environment, monkeypatch)
  before = lock.read_bytes()
  monkeypatch.setattr(packages, "_download", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))
  with pytest.raises(KeyboardInterrupt):
    packages.lock_plugin("zsh", "zinit", "b" * 40)
  assert lock.read_bytes() == before


def test_plugin_lock_conflicts_with_apply_repository_read_lease(isolated_environment, fake_terminal_commands, monkeypatch):
  from termcfg import transaction
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  lock, data = _plugin_fixture(isolated_environment, monkeypatch)
  before = lock.read_bytes()
  monkeypatch.setattr(packages, "_download", lambda *args, **kwargs: data)
  entered = threading.Event()
  release = threading.Event()
  original = transaction._commit_apply
  def held(*args, **kwargs):
    entered.set()
    release.wait(5)
    return original(*args, **kwargs)
  monkeypatch.setattr(transaction, "_commit_apply", held)
  plan = build_preview(machine, ("zsh",))
  results = []
  thread = threading.Thread(target=lambda: results.append(transaction.apply(machine, ("zsh",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None)))
  thread.start()
  assert entered.wait(2)
  try:
    with pytest.raises(TermcfgError) as error:
      packages.lock_plugin("zsh", "zinit", "b" * 40)
    assert error.value.code == 4
    assert lock.read_bytes() == before
  finally:
    release.set()
    thread.join(5)
  assert results and results[0]["changed"]


@pytest.mark.parametrize("json_mode", [False, True])
def test_cached_group_interrupt_reports_completed_activation(isolated_environment, monkeypatch, capsys, json_mode):
  assert main(["--machine", "workstation", "init-local", "--component", "zsh"]) == 0
  machine = read_machine("workstation")
  lock, data = _plugin_fixture(isolated_environment, monkeypatch)
  old_lock = lock.read_bytes()
  monkeypatch.setattr(packages, "_download", lambda *args, **kwargs: data)
  packages.sync(machine, "zsh")
  current = packages._plugin_group_root("zsh") / "current"
  first_group = os.readlink(current)
  changed = json.loads(old_lock)
  asset = changed["assets"]["zsh"][0]
  asset["commit"] = "b" * 40
  asset["url"] = asset["url"].replace("a" * 40, "b" * 40)
  lock.write_text(json.dumps(changed))
  packages.sync(machine, "zsh")
  assert os.readlink(current) != first_group
  lock.write_bytes(old_lock)
  capsys.readouterr()
  def no_download(*args, **kwargs):
    pytest.fail("cached group must not download again")
  monkeypatch.setattr(packages, "_download", no_download)
  activate = packages._activate_plugin_group
  def interrupt_after_activation(*args):
    activate(*args)
    raise KeyboardInterrupt()
  monkeypatch.setattr(packages, "_activate_plugin_group", interrupt_after_activation)
  words = ["--machine", "workstation", "sync", "--component", "zsh"]
  assert main([*words, *(["--json"] if json_mode else [])]) == 6
  text = capsys.readouterr().out
  assert os.readlink(current) == first_group
  if json_mode:
    result = json.loads(text)
    assert result["reason"] == "interrupted" and result["stage"] == "activate"
    assert result["side_effect"] == "private_package_or_selection_may_have_changed"
    assert result["machine_id"] == "workstation"
  else:
    assert "包选择未激活" not in text
    assert "激活选择可能已改变" in text
    assert "HOME 配置未由 sync 部署" in text
