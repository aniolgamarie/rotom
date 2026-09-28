"""最近成功版本与独立回滚预览。"""

from pathlib import Path
import json
import threading

import pytest

from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.preview import build_preview
from termcfg.state import read_state, state_file, write_json
from termcfg.transaction import rollback_preview
from termcfg import transaction


pytestmark = pytest.mark.usefixtures("fake_terminal_commands")


def _apply(component):
  machine = read_machine("default")
  plan = build_preview(machine, (component,))
  args = ["apply", "--component", component, "--plan-id", plan.plan_id]
  for target in plan.targets:
    if target.action == "adopt-required":
      args.extend(("--adopt-target", target.artifact.id))
  if any(item.custom_zshenv for item in plan.targets):
    args.extend(("--confirm-zshenv", plan.plan_id))
  return main(args)


def test_first_adoption_rollback_restores_old_file_and_removes_new(isolated_environment):
  assert main(["init-local", "--component", "zsh"]) == 0
  home = isolated_environment.home
  (home / ".zshenv").write_text("export EDITOR=vi\n")
  (home / ".zshenv").chmod(0o640)
  assert _apply("zsh") == 0
  machine = read_machine("default")
  state_with_core = read_state(machine)
  state_with_core["selected_core"] = "a" * 64
  write_json(state_file(machine), state_with_core)
  plan = rollback_preview(machine, "zsh")
  previous_backup = Path(state_with_core["previous"]["zsh"]["zshenv"]["path"])
  assert previous_backup.exists()
  assert {target["target_id"] for target in plan["targets"]} == {"zshrc", "zshenv"}
  assert main(["rollback", "--component", "zsh", "--plan-id", plan["plan_id"]]) == 0
  assert (home / ".zshenv").read_text() == "export EDITOR=vi\n"
  assert (home / ".zshenv").stat().st_mode & 0o777 == 0o640
  assert not (home / ".zshrc").exists()
  state = read_state(machine)
  assert "zsh" not in state["previous"]
  assert "zshenv" not in state["targets"]
  assert state["selected_core"] == "a" * 64
  assert not previous_backup.exists()


def test_non_tty_rollback_requires_fresh_preview_id(isolated_environment, capsys):
  assert main(["init-local", "--component", "zsh"]) == 0
  assert _apply("zsh") == 0
  capsys.readouterr()
  assert main(["rollback", "--component", "zsh", "--json"]) == 2
  assert json.loads(capsys.readouterr().out)["reason"] == "plan_id_required"
  assert main(["rollback", "--component", "zsh", "--plan-only", "--json"]) == 0
  plan = json.loads(capsys.readouterr().out)
  assert plan["plan_id"]
  assert main(["rollback", "--component", "zsh", "--plan-id", "0" * 64]) == 2
  assert main(["rollback", "--component", "zsh", "--plan-id", plan["plan_id"]]) == 0


def test_committed_rollback_cleanup_failure_keeps_committed_state(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "zsh"]) == 0
  assert _apply("zsh") == 0
  machine = read_machine("default")
  plan = rollback_preview(machine, "zsh")
  monkeypatch.setattr(transaction, "_clean_old_backups", lambda *a, **k: (_ for _ in ()).throw(OSError("synthetic cleanup failure")))
  result = transaction.rollback(machine, "zsh", plan_id=plan["plan_id"])
  assert result["cleanup_pending"] is True
  assert not (machine.private_state_root / "journal.json").exists()
  assert "zsh" not in read_state(machine)["previous"]
  assert not (isolated_environment.home / ".zshenv").exists()


def test_rollback_loses_to_active_apply_without_touching_backup(isolated_environment):
  assert main(["init-local", "--component", "zsh"]) == 0
  assert _apply("zsh") == 0
  machine = read_machine("default")
  plan = rollback_preview(machine, "zsh")
  state_file = machine.private_state_root / "state.json"
  journal_file = machine.private_state_root / "journal.json"
  state_bytes = state_file.read_bytes()
  backup_paths = [Path(value["path"]) for value in read_state(machine)["previous"]["zsh"].values() if value["path"]]
  backup_bytes = [path.read_bytes() for path in backup_paths]
  target_bytes = (isolated_environment.home / ".zshenv").read_bytes()
  entered = threading.Event()
  release = threading.Event()
  def held_apply():
    def confirm(_preview):
      entered.set()
      release.wait(5)
      return set(), None
    transaction.apply(machine, ("zsh",), plan_id=None, adopted=set(),
                      confirm_zshenv=None, confirm=confirm)
  thread = threading.Thread(target=held_apply)
  thread.start()
  assert entered.wait(2)
  try:
    assert main(["rollback", "--component", "zsh", "--plan-id", plan["plan_id"]]) == 4
    assert state_file.read_bytes() == state_bytes
    assert [path.read_bytes() for path in backup_paths] == backup_bytes
    assert not journal_file.exists()
    assert (isolated_environment.home / ".zshenv").read_bytes() == target_bytes
  finally:
    release.set()
    thread.join(3)


def test_rollback_loses_to_active_sync_before_writes(isolated_environment, monkeypatch):
  from termcfg import packages
  assert main(["init-local", "--component", "zsh"]) == 0
  assert _apply("zsh") == 0
  machine = read_machine("default")
  plan = rollback_preview(machine, "zsh")
  state_path = machine.private_state_root / "state.json"
  state_bytes = state_path.read_bytes()
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
    assert main(["rollback", "--component", "zsh", "--plan-id", plan["plan_id"]]) == 4
    assert state_path.read_bytes() == state_bytes
    assert (isolated_environment.home / ".zshenv").exists()
    assert not (machine.private_state_root / "journal.json").exists()
  finally:
    release.set()
    thread.join(3)


def test_rollback_rejects_drift(isolated_environment):
  assert main(["init-local", "--component", "zsh"]) == 0
  assert _apply("zsh") == 0
  target = isolated_environment.home / ".zshenv"
  target.write_text("export EDITOR=vim\n")
  machine = read_machine("default")
  from termcfg.errors import TermcfgError
  try:
    rollback_preview(machine, "zsh")
  except TermcfgError as exc:
    assert exc.code == 4
  else:
    raise AssertionError("rollback drift accepted")


@pytest.mark.parametrize("old_kind", ["absent", "symlink"])
def test_rollback_crash_before_after_journal_can_recover(isolated_environment, monkeypatch, old_kind):
  assert main(["init-local", "--component", "zsh"]) == 0
  home = isolated_environment.home
  if old_kind == "symlink":
    (home / ".zshrc").symlink_to("/tmp/starter/shell_config/zshrc.zsh")
  assert _apply("zsh") == 0
  machine = read_machine("default")
  plan = rollback_preview(machine, "zsh")
  original_restore = transaction._restore_one
  called = False
  def interrupt_after_write(machine, relative, backup, **kwargs):
    nonlocal called
    original_restore(machine, relative, backup, **kwargs)
    if not called:
      called = True
      raise OSError("synthetic crash after restore")
  monkeypatch.setattr(transaction, "_restore_one", interrupt_after_write)
  with pytest.raises(OSError):
    transaction.rollback(machine, "zsh", plan_id=plan["plan_id"])
  monkeypatch.setattr(transaction, "_restore_one", original_restore)
  assert transaction.recover(machine)["recovered"] is True
  assert (home / ".zshrc").is_file()
  assert "zsh" in read_state(machine)["previous"]
