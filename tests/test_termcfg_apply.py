"""备份优先、接管、漂移与中断恢复。"""

import json
import io
import hashlib
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.preview import build_preview
from termcfg.state import read_state
from termcfg import transaction
from termcfg.lease import operation_lease


pytestmark = pytest.mark.usefixtures("fake_terminal_commands")


def _setup(*components):
  assert main(["init-local", *[part for component in components for part in ("--component", component)]]) == 0
  machine = read_machine("default")
  return machine


def _apply(machine, components, *, adopted=(), zshenv=False):
  plan = build_preview(machine, components)
  args = ["apply", *[part for component in components for part in ("--component", component)], "--plan-id", plan.plan_id]
  for target in adopted:
    args.extend(("--adopt-target", target))
  if zshenv:
    args.extend(("--confirm-zshenv", plan.plan_id))
  return main(args)


def test_backup_failure_in_second_component_prevents_all_overwrites(isolated_environment, monkeypatch):
  machine = _setup("zsh", "tmux")
  home = isolated_environment.home
  (home / ".zshenv").write_text("export EDITOR=vi\n")
  from termcfg.catalog import REPO_ROOT
  (home / ".tmux.conf").write_bytes((REPO_ROOT / "terminals/tmux/tmux.conf").read_bytes())
  tmux_original = (home / ".tmux.conf").read_bytes()
  original = (home / ".zshenv").read_bytes()
  original_backup = transaction._backup_one
  def fail_second(machine, item, directory):
    if item.artifact.component == "tmux":
      raise OSError("simulated backup failure")
    return original_backup(machine, item, directory)
  monkeypatch.setattr(transaction, "_backup_one", fail_second)
  with pytest.raises(transaction.TermcfgError) as error:
    transaction.apply(machine, ("zsh", "tmux"), plan_id=build_preview(machine, ("zsh", "tmux")).plan_id,
                      adopted={"zshenv", "tmux-conf"}, confirm_zshenv=build_preview(machine, ("zsh", "tmux")).plan_id)
  assert error.value.context == {"component": "tmux", "target_id": "tmux-conf", "stage": "backup"}
  assert (home / ".zshenv").read_bytes() == original
  assert not (home / ".zshrc").exists()
  assert (home / ".tmux.conf").read_bytes() == tmux_original
  assert read_state(machine)["targets"] == {}


def test_apply_adoption_backup_and_noop(isolated_environment):
  machine = _setup("zsh")
  home = isolated_environment.home
  (home / ".zshenv").write_text("export EDITOR=vi\n")
  assert _apply(machine, ("zsh",), adopted=("zshenv",), zshenv=True) == 0
  state = read_state(machine)
  backup = state["previous"]["zsh"]["zshenv"]
  assert (home / ".zshenv").read_bytes() != b"export EDITOR=vi\n"
  assert backup["path"] is not None
  assert __import__("pathlib").Path(backup["path"]).read_bytes() == b"export EDITOR=vi\n"
  inode = (home / ".zshenv").stat().st_ino
  assert _apply(machine, ("zsh",)) == 0
  assert (home / ".zshenv").stat().st_ino == inode
  assert read_state(machine)["previous"] == state["previous"]


def test_drift_is_refused_without_overwrite(isolated_environment):
  machine = _setup("zsh")
  assert _apply(machine, ("zsh",)) == 0
  target = isolated_environment.home / ".zshenv"
  target.write_text("export EDITOR=emacs\n")
  before = target.read_bytes()
  assert _apply(machine, ("zsh",)) == 4
  assert target.read_bytes() == before


def test_apply_crash_after_atomic_replace_is_recoverable(isolated_environment, monkeypatch):
  machine = _setup("zsh")
  original = transaction.atomic_target_bytes
  called = False
  def interrupt_after_replace(*args, **kwargs):
    nonlocal called
    original(*args, **kwargs)
    if not called:
      called = True
      raise OSError("synthetic crash after replace")
  monkeypatch.setattr(transaction, "atomic_target_bytes", interrupt_after_replace)
  with pytest.raises(transaction.TermcfgError):
    transaction.apply(machine, ("zsh",), plan_id=build_preview(machine, ("zsh",)).plan_id,
                      adopted=set(), confirm_zshenv=None)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original)
  assert transaction.recover(machine)["recovered"] is True
  assert not (isolated_environment.home / ".zshrc").exists()
  assert not (isolated_environment.home / ".zshenv").exists()
  assert read_state(machine)["targets"] == {}


def test_concurrent_apply_loses_machine_lock_before_writes(isolated_environment):
  machine = _setup("zsh")
  plan = build_preview(machine, ("zsh",))
  ready = threading.Event()
  release = threading.Event()
  def holder():
    with operation_lease(machine.machine_id):
      ready.set()
      release.wait(5)
  thread = threading.Thread(target=holder)
  thread.start()
  assert ready.wait(2)
  try:
    assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id]) == 4
    assert not (isolated_environment.home / ".zshrc").exists()
    assert read_state(machine)["targets"] == {}
  finally:
    release.set()
    thread.join(2)


def test_repository_snapshot_change_during_confirmation_prevents_backup(isolated_environment, monkeypatch):
  machine = _setup("zsh")
  from termcfg import preview as preview_module
  identity = ["old"]
  monkeypatch.setattr(preview_module, "_lock_digest", lambda: identity[0])
  def confirm(plan):
    identity[0] = "new"
    return set(), None
  with pytest.raises(transaction.TermcfgError) as error:
    transaction.apply(machine, ("zsh",), plan_id=None, adopted=set(),
                      confirm_zshenv=None, confirm=confirm)
  assert error.value.code == 4
  assert not (isolated_environment.home / ".zshrc").exists()
  assert not (machine.private_state_root / "journal.json").exists()


def test_interactive_apply_needs_no_copied_ids(isolated_environment, monkeypatch):
  machine = _setup("zsh")
  class TtyInput(io.StringIO):
    def isatty(self):
      return True
  monkeypatch.setattr("sys.stdin", TtyInput())
  answers = iter(("yes",))
  monkeypatch.setattr("builtins.input", lambda: next(answers))
  assert main(["apply", "--component", "zsh"]) == 0
  assert (isolated_environment.home / ".zshenv").exists()
  assert read_state(machine)["targets"]


def test_declined_zshenv_confirmation_keeps_all_zsh_targets(isolated_environment, monkeypatch):
  machine = _setup("zsh")
  target = isolated_environment.home / ".zshenv"
  target.write_text("export EDITOR=vi\n")
  class TtyInput(io.StringIO):
    def isatty(self):
      return True
  monkeypatch.setattr("sys.stdin", TtyInput())
  answers = iter(("yes", "no"))
  monkeypatch.setattr("builtins.input", lambda: next(answers))
  assert main(["apply", "--component", "zsh"]) == 4
  assert target.read_text() == "export EDITOR=vi\n"
  assert not (isolated_environment.home / ".zshrc").exists()
  assert read_state(machine)["targets"] == {}


def test_first_backup_failure_json_identifies_target(isolated_environment, monkeypatch, capsys):
  machine = _setup("zsh")
  (isolated_environment.home / ".zshenv").write_text("export EDITOR=vi\n")
  preview = build_preview(machine, ("zsh",))
  def fail_backup(*args, **kwargs):
    raise OSError("synthetic private failure")
  monkeypatch.setattr(transaction, "_backup_one", fail_backup)
  capsys.readouterr()
  assert main(["apply", "--component", "zsh", "--plan-id", preview.plan_id,
               "--adopt-target", "zshenv", "--confirm-zshenv", preview.plan_id,
               "--json"]) == 6
  result = json.loads(capsys.readouterr().out)
  assert (result["component"], result["target_id"], result["stage"]) == ("zsh", "zshenv", "backup")
  assert "synthetic private failure" not in json.dumps(result)


def test_committed_apply_cleanup_failure_does_not_request_recovery(isolated_environment, monkeypatch):
  machine = _setup("zsh")
  plan = build_preview(machine, ("zsh",))
  monkeypatch.setattr(transaction, "_clean_old_backups", lambda *a, **k: (_ for _ in ()).throw(OSError("synthetic cleanup failure")))
  result = transaction.apply(machine, ("zsh",), plan_id=plan.plan_id,
                             adopted=set(), confirm_zshenv=None)
  assert result["cleanup_pending"] is True
  assert not (machine.private_state_root / "journal.json").exists()
  assert read_state(machine)["targets"]
  assert (isolated_environment.home / ".zshenv").exists()


def test_successive_public_updates_keep_only_immediate_previous_backup(isolated_environment, monkeypatch):
  from termcfg import preview as preview_module, environment
  from termcfg.catalog import SourceArtifact, load_catalog
  machine = _setup("zsh")
  original = next(item for item in load_catalog() if item.id == "zshrc").bytes()
  assert _apply(machine, ("zsh",)) == 0
  entries = load_catalog()
  current = [entries]
  generated = {}
  source_bytes = SourceArtifact.bytes
  def selected_bytes(self):
    return generated[self.sha256] if self.sha256 in generated else source_bytes(self)
  monkeypatch.setattr(SourceArtifact, "bytes", selected_bytes)
  monkeypatch.setattr(preview_module, "load_catalog", lambda: current[0])
  monkeypatch.setattr(environment, "load_catalog", lambda: current[0])
  previous_path = None
  for version in (1, 2):
    data = f"# synthetic public version {version}\n".encode()
    digest = hashlib.sha256(data).hexdigest()
    generated[digest] = data
    current[0] = tuple(replace(item, sha256=digest) if item.id == "zshrc" else item for item in entries)
    plan = build_preview(machine, ("zsh",))
    assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id]) == 0
    state = read_state(machine)
    latest = Path(state["previous"]["zsh"]["zshrc"]["path"])
    assert latest.read_bytes() == (original if version == 1 else b"# synthetic public version 1\n")
    if previous_path is not None:
      assert not previous_path.exists()
    previous_path = latest
  assert (isolated_environment.home / ".zshrc").read_bytes() == b"# synthetic public version 2\n"


def test_state_commit_failure_leaves_recoverable_journal(isolated_environment, monkeypatch):
  machine = _setup("zsh")
  plan = build_preview(machine, ("zsh",))
  original_write = transaction.write_json
  def fail_state(path, value):
    if path.name == "state.json":
      raise OSError("synthetic state commit failure")
    return original_write(path, value)
  monkeypatch.setattr(transaction, "write_json", fail_state)
  with pytest.raises(OSError):
    transaction.apply(machine, ("zsh",), plan_id=plan.plan_id,
                      adopted=set(), confirm_zshenv=None)
  monkeypatch.setattr(transaction, "write_json", original_write)
  assert (machine.private_state_root / "journal.json").exists()
  assert transaction.recover(machine)["recovered"] is True
  assert read_state(machine)["targets"] == {}
  assert not (isolated_environment.home / ".zshenv").exists()


def test_selected_component_does_not_touch_unselected_or_session_data(isolated_environment):
  machine = _setup("zsh")
  home = isolated_environment.home
  unselected = home / ".tmux.conf"
  unselected.write_text("synthetic unmanaged tmux config\n")
  session = home / ".local/share/tmux/session-data"
  session.parent.mkdir(parents=True)
  session.write_text("synthetic session\n")
  private = machine.private_state_root / "mihomo/private.yaml"
  private.parent.mkdir(parents=True, mode=0o700)
  private.write_text("secret: synthetic-private\n")
  private.chmod(0o600)
  before = (unselected.read_bytes(), session.read_bytes(), private.read_bytes())
  assert _apply(machine, ("zsh",)) == 0
  assert (unselected.read_bytes(), session.read_bytes(), private.read_bytes()) == before
