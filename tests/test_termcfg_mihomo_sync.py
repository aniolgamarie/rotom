"""锁定 core 安装只使用虚构字节与假下载。"""

import gzip
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


def _asset():
  archive = gzip.compress(b"synthetic-core-not-executable")
  asset = {"version": "v1.0.0", "platform": "linux-x86_64", "name": "mihomo-linux-amd64-compatible-v1.0.0.gz",
           "url": "https://github.com/MetaCubeX/mihomo/releases/download/v1.0.0/mihomo-linux-amd64-compatible-v1.0.0.gz",
           "size": len(archive), "sha256": hashlib.sha256(archive).hexdigest(),
           "archive": "gzip-single", "entry": "mihomo", "resources": []}
  return asset, archive


def test_sync_verifies_archive_and_private_modes(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  asset, archive = _asset()
  monkeypatch.setattr(packages, "_read_lock_raw", lambda component: ({"assets": {"linux-x86_64": asset}}, "synthetic-snapshot"))
  monkeypatch.setattr(packages, "_download", lambda *a, **k: archive)
  outcome = packages.sync(machine, "mihomo")
  directory = packages.package_path(machine, asset)
  assert outcome["pending_core_effect"] is True
  assert directory.stat().st_mode & 0o777 == 0o700
  assert (directory / "mihomo").stat().st_mode & 0o777 == 0o700
  assert (directory / "archive.gz").stat().st_mode & 0o777 == 0o600
  assert read_state(machine)["selected_core"] == asset["sha256"]
  assert not (isolated_environment.home / ".config/termcfg/mihomo/base.yaml").exists()


def test_sync_rejects_wrong_digest_before_activation(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  asset, archive = _asset()
  monkeypatch.setattr(packages, "_read_lock_raw", lambda component: ({"assets": {"linux-x86_64": asset}}, "synthetic-snapshot"))
  monkeypatch.setattr(packages, "_download", lambda *a, **k: archive + b"tamper")
  with pytest.raises(TermcfgError) as error:
    packages.sync(machine, "mihomo")
  assert error.value.code == 5
  assert not packages.package_path(machine, asset).exists()
  assert read_state(machine)["selected_core"] is None


def test_sync_accepts_standard_0755_xdg_data_root(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  (isolated_environment.home / "data").chmod(0o755)
  asset, archive = _asset()
  monkeypatch.setattr(packages, "_read_lock_raw", lambda component: ({"assets": {"linux-x86_64": asset}}, "synthetic-snapshot"))
  monkeypatch.setattr(packages, "_download", lambda *a, **k: archive)
  assert packages.sync(machine, "mihomo")["pending_core_effect"] is True


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


def test_sync_rejects_lock_update_during_download(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  asset, archive = _asset()
  identity = ["old"]
  monkeypatch.setattr(packages, "_read_lock_raw", lambda component: ({"assets": {"linux-x86_64": asset}}, identity[0]))
  def download(*args, **kwargs):
    identity[0] = "new"
    return archive
  monkeypatch.setattr(packages, "_download", download)
  with pytest.raises(TermcfgError) as error:
    packages.sync(machine, "mihomo")
  assert error.value.code == 4
  assert read_state(machine)["selected_core"] is None
  assert not packages.package_path(machine, asset).exists()


def test_two_lock_maintainers_detect_stale_snapshot(isolated_environment, monkeypatch):
  asset, archive = _asset()
  lock = isolated_environment.root / "mihomo-lock.json"
  lock.write_text(json.dumps({"version": 1, "component": "mihomo", "assets": {"linux-x86_64": asset}}))
  monkeypatch.setattr(packages, "lock_path", lambda component: lock)
  release = {"tag_name": "v1.0.0", "assets": [{"name": asset["name"],
             "browser_download_url": asset["url"], "size": asset["size"],
             "digest": "sha256:" + asset["sha256"]}]}
  both_read = threading.Barrier(2)
  def fake_download(url, **kwargs):
    if url.startswith(packages.OFFICIAL_API):
      both_read.wait(timeout=5)
      return json.dumps(release).encode()
    return archive
  monkeypatch.setattr(packages, "_download", fake_download)
  results = []
  def maintainer():
    try:
      packages.lock_mihomo("v1.0.0")
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
  assert packages._read_lock_raw("mihomo")[0]["assets"]["linux-x86_64"]["sha256"] == asset["sha256"]


def test_maintainer_lock_during_interactive_apply_invalidates_preview(isolated_environment,
                                                                       fake_terminal_commands, monkeypatch):
  from termcfg import preview, transaction
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  asset, archive = _asset()
  lock = isolated_environment.root / "mihomo-lock.json"
  lock.write_text(json.dumps({"version": 1, "component": "mihomo", "assets": {"linux-x86_64": asset}}))
  monkeypatch.setattr(packages, "lock_path", lambda component: lock)
  monkeypatch.setattr(preview, "_lock_digest", lambda: hashlib.sha256(lock.read_bytes()).hexdigest())
  release = {"tag_name": "v1.0.0", "assets": [{"name": asset["name"],
             "browser_download_url": asset["url"], "size": asset["size"],
             "digest": "sha256:" + asset["sha256"]}]}
  monkeypatch.setattr(packages, "_download", lambda url, **kwargs: json.dumps(release).encode() if url.startswith(packages.OFFICIAL_API) else archive)
  def confirm(_plan):
    packages.lock_mihomo("v1.0.0")
    return set(), None
  with pytest.raises(TermcfgError) as error:
    transaction.apply(machine, ("zsh",), plan_id=None, adopted=set(),
                      confirm_zshenv=None, confirm=confirm)
  assert error.value.code == 4
  assert not (isolated_environment.home / ".zshrc").exists()
  assert not (machine.private_state_root / "state.json").exists()
  assert not (machine.private_state_root / "journal.json").exists()
  assert not (machine.private_state_root / "backups").exists()


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
                            timeout=10, progress=Progress("sync"), component="mihomo") == b"synthetic bytes"
  stderr = capsys.readouterr().err
  assert stderr.count("sync | download | mihomo") >= 2
  assert "private-url" not in stderr


def test_interrupted_lock_preserves_old_bytes(isolated_environment, monkeypatch):
  asset, _ = _asset()
  lock = isolated_environment.root / "mihomo-lock.json"
  lock.write_text(json.dumps({"version": 1, "component": "mihomo", "assets": {"linux-x86_64": asset}}))
  before = lock.read_bytes()
  monkeypatch.setattr(packages, "lock_path", lambda component: lock)
  monkeypatch.setattr(packages, "_download", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
  with pytest.raises(KeyboardInterrupt):
    packages.lock_mihomo("v1.0.0")
  assert lock.read_bytes() == before


def test_real_lock_update_during_fake_sync_download_rejects_old_snapshot(isolated_environment,
                                                                          monkeypatch):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  asset, archive = _asset()
  lock = isolated_environment.root / "mihomo-lock.json"
  lock.write_text(json.dumps({"version": 1, "component": "mihomo", "assets": {"linux-x86_64": asset}}))
  monkeypatch.setattr(packages, "lock_path", lambda component: lock)
  release = {"tag_name": "v1.0.0", "assets": [{"name": asset["name"],
             "browser_download_url": asset["url"], "size": asset["size"],
             "digest": "sha256:" + asset["sha256"]}]}
  changed = [False]
  def fake_download(url, **kwargs):
    if url.startswith(packages.OFFICIAL_API):
      return json.dumps(release).encode()
    if not changed[0]:
      changed[0] = True
      packages.lock_mihomo("v1.0.0")
    return archive
  monkeypatch.setattr(packages, "_download", fake_download)
  with pytest.raises(TermcfgError) as error:
    packages.sync(machine, "mihomo")
  assert error.value.code == 4
  assert read_state(machine)["selected_core"] is None
  assert not packages.package_path(machine, asset).exists()


def test_maintainer_lock_conflicts_with_active_apply_repository_read_lease(isolated_environment,
                                                                           fake_terminal_commands, monkeypatch):
  from termcfg import transaction
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  asset, archive = _asset()
  lock = isolated_environment.root / "mihomo-lock.json"
  lock.write_text(json.dumps({"version": 1, "component": "mihomo", "assets": {"linux-x86_64": asset}}))
  original_lock = lock.read_bytes()
  monkeypatch.setattr(packages, "lock_path", lambda component: lock)
  release = {"tag_name": "v1.0.0", "assets": [{"name": asset["name"],
             "browser_download_url": asset["url"], "size": asset["size"],
             "digest": "sha256:" + asset["sha256"]}]}
  monkeypatch.setattr(packages, "_download", lambda url, **kwargs: json.dumps(release).encode() if url.startswith(packages.OFFICIAL_API) else archive)
  entered = threading.Event()
  release_apply = threading.Event()
  original_commit = transaction._commit_apply
  def held_commit(*args, **kwargs):
    entered.set()
    release_apply.wait(5)
    return original_commit(*args, **kwargs)
  monkeypatch.setattr(transaction, "_commit_apply", held_commit)
  outcome = []
  thread = threading.Thread(target=lambda: outcome.append(transaction.apply(machine, ("zsh",),
                            plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None)))
  thread.start()
  assert entered.wait(2)
  try:
    with pytest.raises(TermcfgError) as error:
      packages.lock_mihomo("v1.0.0")
    assert error.value.code == 4
    assert lock.read_bytes() == original_lock
    assert not (isolated_environment.home / ".zshrc").exists()
  finally:
    release_apply.set()
    thread.join(3)
  assert outcome and outcome[0]["changed"]


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
                       timeout=10, progress=Progress("sync"), component="mihomo")
  assert error.value.reason == "asset_length_mismatch"
  monkeypatch.setattr(packages.urllib.request, "urlopen", lambda *a, **k: Response(slow=True))
  with pytest.raises(TermcfgError) as error:
    packages._download("https://invalid.example/fake", expected_size=None,
                       timeout=0.05, progress=Progress("sync"), component="mihomo")
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
