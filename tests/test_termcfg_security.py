"""迁入管理器的秘密权限与旧服务入口限制。"""

import importlib.util
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from termcfg.catalog import REPO_ROOT
from termcfg.config import xdg_path
from termcfg.errors import TermcfgError
from termcfg.lease import operation_lease, repository_lease
from termcfg.state import read_state, state_file, write_json


def _load_legacy_mgr():
  source = REPO_ROOT / "terminals/mihomo/mihomo-mgr.py"
  spec = importlib.util.spec_from_file_location("termcfg_legacy_mgr", source)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_legacy_mgr_private_config_is_0600_under_umask_022(isolated_environment, monkeypatch):
  module = _load_legacy_mgr()
  path = isolated_environment.home / ".config/mihomo-mgr/config.yaml"
  monkeypatch.setenv("MIHOMO_MGR_CONFIG", str(path))
  old = os.umask(0o022)
  try:
    module._save_mgr_config({"secret": "synthetic-private"})
  finally:
    os.umask(old)
  assert path.stat().st_mode & 0o777 == 0o600
  assert path.parent.stat().st_mode & 0o777 == 0o700


def test_legacy_mgr_start_entry_is_disabled(isolated_environment, monkeypatch, capsys):
  module = _load_legacy_mgr()
  monkeypatch.setattr(sys, "argv", ["mihomo-mgr", "start"])
  with pytest.raises(SystemExit) as error:
    module.main()
  assert error.value.code == 2
  assert "legacy_command_disabled" in capsys.readouterr().err


def test_machine_and_repo_lease_paths_never_alias(isolated_environment):
  digest = hashlib.sha256(str(REPO_ROOT.resolve()).encode()).hexdigest()[:32]
  machine_id = "repo-" + digest
  with operation_lease(machine_id):
    with repository_lease(REPO_ROOT, exclusive=True):
      pass
  base = xdg_path("XDG_STATE_HOME") / "termcfg/leases"
  assert (base / "machines" / f"{machine_id}.lock").exists()
  assert (base / "repos" / f"{machine_id}.lock").exists()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode"])
def test_machine_lease_rejects_unsafe_lock_file(isolated_environment, kind):
  base = xdg_path("XDG_STATE_HOME") / "termcfg/leases/machines"
  base.mkdir(parents=True, mode=0o700)
  # 上层目录也必须满足固定私人权限。
  (base.parent.parent).chmod(0o700)
  base.parent.chmod(0o700)
  target = base / "default.lock"
  outside = isolated_environment.root / "outside-lock"
  outside.write_text("synthetic")
  outside.chmod(0o600)
  if kind == "symlink":
    target.symlink_to(outside)
  elif kind == "hardlink":
    os.link(outside, target)
  else:
    target.write_text("synthetic")
    target.chmod(0o644)
  with pytest.raises(TermcfgError) as error:
    with operation_lease("default"):
      pass
  assert error.value.code == 4


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode"])
def test_repository_lease_rejects_unsafe_lock_file(isolated_environment, kind):
  base = xdg_path("XDG_STATE_HOME") / "termcfg/leases/repos"
  base.mkdir(parents=True, mode=0o700)
  (base.parent.parent).chmod(0o700)
  base.parent.chmod(0o700)
  digest = hashlib.sha256(str(REPO_ROOT.resolve()).encode()).hexdigest()[:32]
  target = base / f"repo-{digest}.lock"
  outside = isolated_environment.root / "outside-repo-lock"
  outside.write_text("synthetic")
  outside.chmod(0o600)
  if kind == "symlink":
    target.symlink_to(outside)
  elif kind == "hardlink":
    os.link(outside, target)
  else:
    target.write_text("synthetic")
    target.chmod(0o644)
  with pytest.raises(TermcfgError) as error:
    with repository_lease(REPO_ROOT, exclusive=True):
      pass
  assert error.value.code == 4


def test_machine_and_state_unknown_fields_fail(isolated_environment):
  from termcfg.cli import main
  from termcfg.config import read_machine
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  state = read_state(machine)
  state["unknown"] = "synthetic"
  write_json(state_file(machine), state)
  with pytest.raises(TermcfgError) as error:
    read_state(machine)
  assert error.value.code == 2


def test_invalid_machine_component_value_fails_as_config_error(isolated_environment):
  from termcfg.config import MachineSelection
  with pytest.raises(TermcfgError) as error:
    MachineSelection.from_dict({"machine_id": "default", "target_home": str(isolated_environment.home),
                                "private_state_root": str(isolated_environment.home / "state/termcfg/machines/default"),
                                "components": [{"unexpected": "value"}]})
  assert error.value.code == 2


def test_machine_id_path_escape_rejected_before_file_write(isolated_environment):
  from termcfg.cli import main
  assert main(["--machine", "../escape", "init-local", "--component", "zsh"]) == 2
  assert not (isolated_environment.home / "config/escape.toml").exists()


def test_symlinked_target_parent_blocks_plan_without_touching_outside(isolated_environment,
                                                                       fake_terminal_commands, capsys):
  from termcfg.cli import main
  assert main(["init-local", "--component", "tmux"]) == 0
  outside = isolated_environment.root / "outside"
  outside.mkdir()
  sentinel = outside / "sentinel"
  sentinel.write_text("untouched\n")
  (isolated_environment.home / ".config").symlink_to(outside, target_is_directory=True)
  capsys.readouterr()
  assert main(["plan", "--component", "tmux", "--json"]) == 4
  result = json.loads(capsys.readouterr().out)
  assert result["reason"] == "unsafe_target_parent"
  assert sentinel.read_text() == "untouched\n"


def test_private_target_content_is_absent_from_error_json(isolated_environment, capsys):
  from termcfg.cli import main
  assert main(["init-local", "--component", "zsh"]) == 0
  (isolated_environment.home / ".zshenv").write_text("export API_KEY=synthetic-private\n")
  capsys.readouterr()
  assert main(["plan", "--component", "zsh", "--json"]) == 0
  output = capsys.readouterr().out
  result = json.loads(output)
  assert result["overall_ready"] is False
  assert "synthetic-private" not in output
  assert "possible_private_content" in output


def test_stale_machine_selection_rejected_after_lease_acquisition(isolated_environment,
                                                                    fake_terminal_commands):
  from termcfg.cli import main
  from termcfg.config import read_machine
  from termcfg.preview import build_preview
  from termcfg import transaction
  assert main(["init-local", "--component", "zsh"]) == 0
  old = read_machine("default")
  plan = build_preview(old, ("zsh",))
  assert main(["init-local", "--edit", "--component", "tmux"]) == 0
  with pytest.raises(TermcfgError) as error:
    transaction.apply(old, ("zsh",), plan_id=plan.plan_id,
                      adopted=set(), confirm_zshenv=None)
  assert error.value.reason == "machine_selection_changed"
  assert not (isolated_environment.home / ".zshrc").exists()


def test_recovery_rejects_forged_journal_target(isolated_environment, fake_terminal_commands,
                                                monkeypatch):
  from termcfg.cli import main
  from termcfg.config import read_machine
  from termcfg.preview import build_preview
  from termcfg import transaction
  from termcfg.state import journal_file, read_journal, write_json
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  original = transaction.atomic_target_bytes
  def crash(*args, **kwargs):
    original(*args, **kwargs)
    raise OSError("synthetic interruption")
  monkeypatch.setattr(transaction, "atomic_target_bytes", crash)
  with pytest.raises(TermcfgError):
    transaction.apply(machine, ("zsh",), plan_id=plan.plan_id,
                      adopted=set(), confirm_zshenv=None)
  journal = read_journal(machine)
  journal["items"][0]["relative"] = "../outside"
  write_json(journal_file(machine), journal)
  with pytest.raises(TermcfgError) as error:
    transaction.recover(machine)
  assert error.value.code == 2


def test_final_target_recheck_preserves_external_change(isolated_environment):
  from termcfg.home_targets import atomic_target_bytes, inspect_target
  target = isolated_environment.home / ".zshrc"
  target.write_text("original\n")
  expected = inspect_target(isolated_environment.home, Path(".zshrc")).as_dict()
  def external_change(_identity):
    target.write_text("external change\n")
  with pytest.raises(TermcfgError) as error:
    atomic_target_bytes(isolated_environment.home, Path(".zshrc"), b"manager update\n", 0o600,
                        before_replace=external_change, expected=expected)
  assert error.value.code == 4
  assert target.read_text() == "external change\n"
