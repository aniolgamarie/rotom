"""Herdr 单文件 opt-in，复用 v2 事务；默认不启动第三方程序。"""
import hashlib
import json
import os
from pathlib import Path
import tomllib

import pytest

from termcfg.catalog import REPO_ROOT, load_catalog
from termcfg.cli import main
from termcfg.config import machine_path, read_machine
from termcfg.errors import TermcfgError
from termcfg.preview import build_preview
from termcfg.state import read_journal, read_state, state_file, write_json
from termcfg import transaction


@pytest.fixture
def prepared_herdr(isolated_environment, monkeypatch):
  monkeypatch.setenv("XDG_CONFIG_HOME", str(isolated_environment.home / ".config"))
  (isolated_environment.home / ".config").mkdir(mode=0o700)
  binary = isolated_environment.root / "empty-bin" / "herdr"
  binary.write_text("#!/bin/sh\nexit 99\n")
  binary.chmod(0o700)
  monkeypatch.setenv("PATH", str(REPO_ROOT) + os.pathsep + str(binary.parent))
  assert main(["init-local", "--component", "herdr"]) == 0
  return read_machine("default")


def apply_herdr(machine, *, adopt=False):
  plan = build_preview(machine, ("herdr",))
  return main(["apply", "--component", "herdr", "--plan-id", plan.plan_id,
               *(["--adopt-target", "herdr.config"] if adopt else [])])


def test_catalog_exact_single_file_and_static_intent():
  entries = [entry for entry in load_catalog() if entry.component == "herdr"]
  assert len(entries) == 1
  entry = entries[0]
  assert (entry.id, str(entry.destination), entry.mode) == ("herdr.config", ".config/herdr/config.toml", 0o600)
  assert entry.source == REPO_ROOT / "terminals/herdr/config.toml"
  data = tomllib.loads(entry.bytes().decode())
  assert data == {
    "onboarding": False, "keys": {"prefix": "ctrl+x", "detach": "prefix+d"},
    "terminal": {"default_shell": "rotom-work-shell", "shell_mode": "non_login", "new_cwd": "follow"},
    "ui": {"prompt_new_tab_name": False, "confirm_close": True, "agent_panel_sort": "spaces", "sidebar_collapsed_mode": "hidden", "window_title": "{hostname}: {workspace} / {tab}", "sound": {"enabled": False}, "toast": {"delivery": "off"}},
    "session": {"resume_agents_on_restore": False},
    "update": {"channel": "stable", "version_check": False, "manifest_check": False},
    "experimental": {"pane_history": False},
  }
  assert hashlib.sha256(entry.bytes()).hexdigest() == entry.sha256


def test_old_machine_not_opted_in_and_old_v2_not_rewritten(isolated_environment, fake_terminal_commands):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  write_json(state_file(machine), {"version": 2, "machine_id": "default", "targets": {}, "previous": {"zsh": {}}})
  before = state_file(machine).read_bytes(), machine_path("default").read_bytes()
  assert main(["plan"]) == 0
  assert main(["doctor", "--strict"]) == 0
  assert (state_file(machine).read_bytes(), machine_path("default").read_bytes()) == before
  assert not (machine.target_home / ".config/herdr").exists()


def test_five_noops_stable_plan_no_backup_rotation_and_sentinels(prepared_herdr):
  machine = prepared_herdr
  data = machine.target_home / ".local/share/herdr/session-data"
  data.parent.mkdir(parents=True)
  data.write_text("synthetic untouched session")
  other = machine.target_home / ".config/herdr/private.toml"
  other.parent.mkdir(parents=True)
  other.write_text("synthetic untouched private data")
  assert apply_herdr(machine) == 0
  target = machine.target_home / ".config/herdr/config.toml"
  assert target.stat().st_mode & 0o777 == 0o600
  before = target.stat(), state_file(machine).read_bytes()
  backups = sorted((machine.private_state_root / "backups").rglob("*"))
  plan_id = build_preview(machine, ("herdr",)).plan_id
  for _ in range(5):
    assert build_preview(machine, ("herdr",)).plan_id == plan_id
    assert apply_herdr(machine) == 0
  assert (target.stat().st_ino, target.stat().st_mtime_ns) == (before[0].st_ino, before[0].st_mtime_ns)
  assert state_file(machine).read_bytes() == before[1]
  assert sorted((machine.private_state_root / "backups").rglob("*")) == backups
  assert data.read_text() == "synthetic untouched session"
  assert other.read_text() == "synthetic untouched private data"
  assert set(read_state(machine)["targets"]) == {"herdr.config"}


def test_public_identical_adoption_and_rollback(prepared_herdr):
  machine = prepared_herdr
  entry = next(item for item in load_catalog() if item.id == "herdr.config")
  target = machine.target_home / entry.destination
  target.parent.mkdir(parents=True)
  target.write_bytes(entry.bytes())
  target.chmod(0o640)
  plan = build_preview(machine, ("herdr",))
  assert plan.targets[0].action == "adopt-required"
  assert apply_herdr(machine) == 4
  assert apply_herdr(machine, adopt=True) == 0
  state = read_state(machine)
  backup = Path(state["previous"]["herdr"]["herdr.config"]["path"])
  assert backup.read_bytes() == entry.bytes()
  assert backup.stat().st_mode & 0o777 == 0o600
  rollback = transaction.rollback_preview(machine, "herdr")
  assert main(["rollback", "--component", "herdr", "--plan-id", rollback["plan_id"]]) == 0
  assert target.read_bytes() == entry.bytes()
  assert target.stat().st_mode & 0o777 == 0o640
  assert "herdr.config" not in read_state(machine)["targets"]


def test_external_drift_preserved(prepared_herdr):
  machine = prepared_herdr
  assert apply_herdr(machine) == 0
  target = machine.target_home / ".config/herdr/config.toml"
  target.write_text("# synthetic external edit\n")
  assert apply_herdr(machine) == 4
  with pytest.raises(TermcfgError):
    transaction.rollback_preview(machine, "herdr")
  assert target.read_text() == "# synthetic external edit\n"


def test_unclassified_existing_config_never_adopted(prepared_herdr):
  target = prepared_herdr.target_home / ".config/herdr/config.toml"
  target.parent.mkdir(parents=True)
  target.write_text('custom = "unclassified"\n')
  assert apply_herdr(prepared_herdr, adopt=True) == 4
  assert target.read_text() == 'custom = "unclassified"\n'
  assert not (prepared_herdr.private_state_root / "backups").exists()


def test_unsafe_parent_no_overwrite(prepared_herdr):
  parent = prepared_herdr.target_home / ".config/herdr"
  parent.mkdir(mode=0o777)
  parent.chmod(0o777)
  with pytest.raises(TermcfgError) as error:
    build_preview(prepared_herdr, ("herdr",))
  assert error.value.code == 4
  assert not (parent / "config.toml").exists()


def test_interrupted_write_dotted_journal_id_recovers(prepared_herdr, monkeypatch):
  machine = prepared_herdr
  original = transaction.atomic_target_bytes
  def interrupted(*args, **kwargs):
    original(*args, **kwargs)
    raise OSError("synthetic crash after replace")
  monkeypatch.setattr(transaction, "atomic_target_bytes", interrupted)
  assert apply_herdr(machine) == 6
  journal = read_journal(machine)
  assert journal["version"] == 2
  assert journal["items"][0]["target_id"] == "herdr.config"
  with pytest.raises(TermcfgError) as error:
    build_preview(machine, ("herdr",))
  assert error.value.reason == "recovery_pending"
  monkeypatch.setattr(transaction, "atomic_target_bytes", original)
  assert main(["recover"]) == 0
  assert read_state(machine)["targets"] == {}
  assert not (machine.target_home / ".config/herdr/config.toml").exists()


@pytest.mark.parametrize("name", ["HERDR_CONFIG_PATH", "XDG_CONFIG_HOME"])
def test_redirected_config_fails_two_without_writes(prepared_herdr, monkeypatch, name):
  machine = prepared_herdr
  monkeypatch.setenv(name, str(machine.target_home / "outside"))
  # XDG 修改后机器文件不再可定位；直接验证已保存的选择而非改写选择。
  with pytest.raises(TermcfgError) as error:
    build_preview(machine, ("herdr",))
  assert error.value.code == 2
  from termcfg.environment import inspect_environment
  with pytest.raises(TermcfgError) as error:
    inspect_environment(machine, ("herdr",))
  assert error.value.code == 2
  assert not (machine.target_home / "outside").exists()


def test_default_explicit_override_allowed_and_target_home_used(prepared_herdr, monkeypatch):
  machine = prepared_herdr
  monkeypatch.setenv("HERDR_CONFIG_PATH", str(machine.target_home / ".config/herdr/config.toml"))
  monkeypatch.setenv("HOME", str(machine.target_home / "different-caller"))
  assert build_preview(machine, ("herdr",)).targets[0].artifact.id == "herdr.config"
  from termcfg.environment import inspect_environment
  assert inspect_environment(machine, ("herdr",))["herdr"]["ready"] is True


def test_doctor_missing_binary_and_wrong_launcher_fail_without_process(prepared_herdr, monkeypatch):
  from termcfg import doctor
  from termcfg.environment import inspect_environment
  monkeypatch.setenv("PATH", str(REPO_ROOT))
  result = inspect_environment(prepared_herdr, ("herdr",))["herdr"]
  assert "herdr_binary_not_prepared" in result["required_blockers"]
  monkeypatch.setattr(doctor, "resolve_executable", lambda name: "/tmp/example/other-launcher" if name == "rotom-work-shell" else "/tmp/example/herdr")
  result = inspect_environment(prepared_herdr, ("herdr",))["herdr"]
  assert "herdr_launcher_source_mismatch" in result["required_blockers"]


def test_herdr_has_no_plugin_sync_or_lock(prepared_herdr, monkeypatch):
  from termcfg import cli, packages
  def forbidden(*args, **kwargs):
    pytest.fail("Herdr must not reach plugin operations or downloads")
  monkeypatch.setattr(cli, "sync", forbidden)
  monkeypatch.setattr(cli, "lock_plugin", forbidden)
  monkeypatch.setattr(packages, "_download", forbidden)
  assert main(["sync", "--component", "herdr"]) == 2
  assert main(["lock", "--component", "herdr", "--version", "a" * 40]) == 2
  for operation in (lambda: packages.lock_path("herdr"),
                    lambda: packages._read_lock_raw("herdr"),
                    lambda: packages.sync(prepared_herdr, "herdr"),
                    lambda: packages.lock_plugin("herdr", "example", "a" * 40)):
    with pytest.raises(TermcfgError) as error:
      operation()
    assert error.value.code == 2


def test_old_v2_pending_is_read_without_migration(isolated_environment, fake_terminal_commands):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  state = {"version": 2, "machine_id": "default", "targets": {}, "previous": {"zsh": {}}}
  write_json(state_file(machine), state)
  journal_path = machine.private_state_root / "journal.json"
  write_json(journal_path, {"version": 2, "kind": "apply", "transaction_id": "a" * 32,
    "phase": "prepared", "plan_id": "b" * 64, "state_before": state, "items": []})
  before = state_file(machine).read_bytes(), journal_path.read_bytes()
  assert read_journal(machine)["version"] == 2
  assert main(["plan"]) == 4
  assert main(["doctor", "--strict"]) == 4
  assert (state_file(machine).read_bytes(), journal_path.read_bytes()) == before
  assert "herdr" not in read_state(machine)["previous"]


def test_doctor_missing_venv_and_source_are_reported(prepared_herdr, monkeypatch, tmp_path):
  from termcfg import doctor
  monkeypatch.setattr(doctor, "REPO_ROOT", tmp_path)
  launcher = tmp_path / "rotom-work-shell"
  launcher.write_text("# synthetic executable sentinel\n")
  launcher.chmod(0o700)
  monkeypatch.setattr(doctor, "resolve_executable", lambda name: str(launcher) if name == "rotom-work-shell" else "/tmp/example/herdr")
  result = doctor.inspect_herdr(prepared_herdr.target_home)
  assert "herdr_venv_not_prepared" in result["required_blockers"]
  assert "herdr_launcher_source_missing" in result["required_blockers"]
  assert result["unverified"] == ["herdr_native_config_and_handshake_not_verified"]


def test_mixed_machine_sync_only_calls_explicit_plugin_component(prepared_herdr, monkeypatch):
  from termcfg import cli
  assert main(["init-local", "--edit", "--component", "zsh", "--component", "tmux", "--component", "herdr"]) == 0
  calls = []
  def fake_sync(machine, component, **kwargs):
    calls.append((machine.components, component))
    return {"component": component, "changed": False}
  monkeypatch.setattr(cli, "sync", fake_sync)
  assert main(["sync", "--component", "zsh"]) == 0
  assert main(["sync", "--component", "tmux"]) == 0
  assert calls == [(("zsh", "tmux", "herdr"), "zsh"), (("zsh", "tmux", "herdr"), "tmux")]
