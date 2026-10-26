"""旧元数据迁移不读取私人代理文件，也不控制任何服务。"""

import json
from pathlib import Path

import pytest

from termcfg.cli import main
from termcfg.config import encode_machine, machine_path, read_machine
from termcfg.errors import TermcfgError
from termcfg.state import private_dir, read_json, read_state, state_file, write_json
from termcfg import migration, transaction


def _legacy(*, proxy=True, state=True):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  if proxy:
    machine_path("default").write_bytes(encode_machine(machine).replace(b'["zsh"]', b'["zsh", "mihomo"]'))
  old = {"version": 1, "machine_id": "default", "selected_core": "a" * 64,
         "public_config_identity": None, "pending_core_effect": True,
         "pending_config_effect": True, "targets": {
           "mihomo-base": {"component": "mihomo", "after": {"kind": "absent"}, "source_digest": "b" * 64}},
         "previous": {"mihomo": {"mihomo-base": {"before": {"kind": "absent"}, "path": None}}}}
  if state:
    write_json(state_file(machine), old)
  return machine, old


def test_migration_retires_only_metadata_and_is_idempotent(isolated_environment, monkeypatch):
  machine, old = _legacy()
  private = machine.private_state_root / "mihomo/private.yaml"
  private.parent.mkdir(mode=0o700)
  private.write_text("synthetic-account-body")
  target = machine.target_home / ".local/bin/mihomo-mgr"
  target.parent.mkdir(parents=True)
  target.write_text("old public file")
  original_open = Path.open
  def guarded_open(path, *args, **kwargs):
    assert path != private
    return original_open(path, *args, **kwargs)
  monkeypatch.setattr(Path, "open", guarded_open)
  assert main(["plan"]) == 4
  assert main(["migrate", "--drop-mihomo"]) == 0
  assert read_machine("default").components == ("zsh",)
  assert read_state(machine) == {"version": 2, "machine_id": "default", "targets": {}, "previous": {}}
  marker = read_json(machine.private_state_root / "drop-mihomo-migration.json")
  assert marker["state_archive"] == old
  assert "synthetic-account-body" not in json.dumps(marker)
  assert target.read_text() == "old public file"
  with original_open(private, "rb") as stream:
    assert stream.read() == b"synthetic-account-body"
  before = state_file(machine).read_bytes()
  assert main(["migrate", "--drop-mihomo"]) == 0
  assert state_file(machine).read_bytes() == before


@pytest.mark.parametrize("proxy,state", [(False, True), (True, False), (False, False)])
def test_migrate_zsh_only_or_missing_state(isolated_environment, proxy, state):
  machine, _ = _legacy(proxy=proxy, state=state)
  assert main(["migrate", "--drop-mihomo"]) == 0
  assert read_state(machine)["version"] == 2
  assert state_file(machine).exists() is state


@pytest.mark.parametrize("boundary", ["state.json", "default.toml", "complete"])
def test_interrupted_migration_resumes(isolated_environment, monkeypatch, boundary):
  machine, _ = _legacy()
  original = migration.atomic_bytes
  original_json = migration.write_json
  interrupted = [False]
  def crash(path, data, **kwargs):
    original(path, data, **kwargs)
    if path.name == boundary and not interrupted[0]:
      interrupted[0] = True
      raise KeyboardInterrupt()
  def crash_complete(path, value):
    if boundary == "complete" and value.get("phase") == "complete" and not interrupted[0]:
      interrupted[0] = True
      raise KeyboardInterrupt()
    original_json(path, value)
  monkeypatch.setattr(migration, "atomic_bytes", crash)
  monkeypatch.setattr(migration, "write_json", crash_complete)
  assert main(["migrate", "--drop-mihomo"]) == 6
  assert main(["plan"]) == 4
  assert main(["migrate", "--drop-mihomo"]) == 0
  assert read_state(machine)["version"] == 2


def test_interrupted_migration_rejects_external_drift(isolated_environment, monkeypatch):
  machine, _ = _legacy()
  original = migration.atomic_bytes
  def crash(path, data, **kwargs):
    original(path, data, **kwargs)
    raise KeyboardInterrupt()
  monkeypatch.setattr(migration, "atomic_bytes", crash)
  assert main(["migrate", "--drop-mihomo"]) == 6
  state = read_json(state_file(machine))
  state["targets"]["external"] = {"component": "zsh", "after": {"kind": "absent"}, "source_digest": "external"}
  write_json(state_file(machine), state)
  before = state_file(machine).read_bytes()
  assert main(["migrate", "--drop-mihomo"]) == 4
  assert state_file(machine).read_bytes() == before


@pytest.mark.parametrize("location", ["state", "machine", "journal", "marker"])
def test_migration_strict_unknown_fields(isolated_environment, location):
  machine, old = _legacy()
  if location == "machine":
    with machine_path("default").open("ab") as stream:
      stream.write(b'unknown = "value"\n')
  elif location == "state":
    old["unknown"] = True
    write_json(state_file(machine), old)
  elif location == "journal":
    write_json(machine.private_state_root / "journal.json", {"unknown": True})
  else:
    write_json(machine.private_state_root / "drop-mihomo-migration.json", {"unknown": True})
  before = state_file(machine).read_bytes()
  assert main(["migrate", "--drop-mihomo"]) == 2
  assert state_file(machine).read_bytes() == before


def test_legacy_pending_journal_recover_before_migrate(isolated_environment, monkeypatch):
  machine, old = _legacy()
  journal = {"version": 1, "kind": "apply", "transaction_id": "a" * 32,
             "phase": "prepared", "plan_id": "b" * 64, "state_before": old,
             "items": [{"target_id": "mihomo-base", "component": "mihomo",
                        "relative": ".config/termcfg/mihomo/base.yaml", "before": {"kind": "absent"},
                        "desired": None, "mode": None, "backup": None, "after": None, "stage": "pending"}]}
  write_json(machine.private_state_root / "journal.json", journal)
  monkeypatch.setattr(transaction, "load_catalog", lambda: (_ for _ in ()).throw(AssertionError("catalog read")))
  assert main(["migrate", "--drop-mihomo"]) == 4
  assert main(["recover"]) == 0
  assert read_state(machine, legacy=True)["version"] == 1
  assert main(["migrate", "--drop-mihomo"]) == 0


def test_terminal_commands_have_no_core_lock(isolated_environment, fake_terminal_commands):
  from termcfg.catalog import REPO_ROOT
  assert not (REPO_ROOT / "locks/termcfg/mihomo.json").exists()
  assert main(["components"]) == 0
  assert main(["init-local", "--component", "tmux"]) == 0
  assert main(["plan"]) == 0
  assert main(["doctor", "--strict"]) == 0
  assert main(["status"]) == 0
  assert main(["service", "status"]) == 2
  assert main(["sync", "--component", "mihomo"]) == 2


def test_different_machine_leases_do_not_protect_shared_home(isolated_environment):
  # 有界复现现有边界，未引入未经设计的 HOME 全局锁。
  from termcfg.lease import operation_lease
  with operation_lease("first"):
    with operation_lease("second"):
      pass


def test_completed_migration_does_not_replay_after_terminal_apply(isolated_environment, fake_terminal_commands):
  machine, _ = _legacy()
  assert main(["migrate", "--drop-mihomo"]) == 0
  from termcfg.preview import build_preview
  plan = build_preview(read_machine("default"), ("zsh",))
  assert main(["apply", "--plan-id", plan.plan_id]) == 0
  before = state_file(machine).read_bytes()
  assert main(["migrate", "--drop-mihomo"]) == 0
  assert state_file(machine).read_bytes() == before


def test_preview_hashes_only_selected_plugin_dependencies(isolated_environment, monkeypatch, fake_terminal_commands):
  from termcfg import packages
  from termcfg.preview import build_preview
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  lock, digest = packages._read_lock_raw("zsh")
  monkeypatch.setattr(packages, "_read_lock_raw", lambda component: (lock, digest))
  before = build_preview(machine, ("zsh",)).plan_id
  lock["assets"]["tmux"] = []
  assert build_preview(machine, ("zsh",)).plan_id == before
  lock["assets"]["zsh"] = []
  assert build_preview(machine, ("zsh",)).plan_id != before


def test_legacy_recovery_restores_written_target_without_catalog(isolated_environment, fake_terminal_commands, monkeypatch):
  from termcfg import preview
  from termcfg.catalog import load_catalog
  from termcfg.preview import build_preview
  from termcfg.state import read_journal
  # 先按旧纯静态catalog建立真实v2事务，不能把包含生成payload的v3日志伪降版。
  legacy_catalog = tuple(item for item in load_catalog() if item.id in {"zshrc", "zshenv"})
  monkeypatch.setattr(preview, "load_catalog", lambda: legacy_catalog)
  monkeypatch.setattr(transaction, "load_catalog", lambda: legacy_catalog)
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  original = transaction.atomic_target_bytes
  def crash(*args, **kwargs):
    original(*args, **kwargs)
    raise OSError("synthetic interruption")
  monkeypatch.setattr(transaction, "atomic_target_bytes", crash)
  assert main(["apply", "--plan-id", plan.plan_id]) == 6
  assert (machine.target_home / ".zshrc").exists()
  journal = read_journal(machine)
  assert journal["version"] == 2 and all("generated" not in item for item in journal["items"])
  journal["version"] = 1
  journal["state_before"].update(version=1, selected_core=None, public_config_identity=None,
                                 pending_core_effect=False, pending_config_effect=False)
  write_json(machine.private_state_root / "journal.json", journal)
  machine_path("default").write_bytes(encode_machine(machine).replace(b'["zsh"]', b'["zsh", "mihomo"]'))
  def forbidden_catalog():
    raise AssertionError("catalog read")
  monkeypatch.setattr(transaction, "load_catalog", forbidden_catalog)
  monkeypatch.setattr(preview, "load_catalog", forbidden_catalog)
  assert main(["recover"]) == 0
  assert not (machine.target_home / ".zshrc").exists()
  assert main(["migrate", "--drop-mihomo"]) == 0


def test_migration_preserves_backup_bytes_and_omits_machine_comments(isolated_environment, monkeypatch):
  import os
  machine, old = _legacy()
  backup = machine.private_state_root / "backups" / ("c" * 32) / "mihomo-base.backup"
  private_dir(backup.parent)
  backup.write_bytes(b"synthetic-backup-sentinel")
  old["previous"]["mihomo"]["mihomo-base"]["path"] = str(backup)
  write_json(state_file(machine), old)
  with machine_path("default").open("ab") as stream:
    stream.write(b"# synthetic-private-comment\n")
  original_open = os.open
  original_path_open = Path.open
  def guarded_open(path, *args, **kwargs):
    assert Path(path) != backup
    return original_open(path, *args, **kwargs)
  monkeypatch.setattr(os, "open", guarded_open)
  assert main(["migrate", "--drop-mihomo"]) == 0
  marker = read_json(machine.private_state_root / "drop-mihomo-migration.json")
  assert marker["state_archive"]["previous"]["mihomo"]["mihomo-base"]["path"] == str(backup)
  assert "synthetic-private-comment" not in json.dumps(marker)
  with original_path_open(backup, "rb") as stream:
    assert stream.read() == b"synthetic-backup-sentinel"


@pytest.mark.parametrize("boundary", ["state_capture", "machine_capture", "state_appeared", "state_recheck", "machine_recheck"])
def test_migration_refuses_pre_marker_snapshot_races(isolated_environment, monkeypatch, boundary):
  machine, old = _legacy(state=boundary != "state_appeared")
  original = migration._contents
  chosen_path = machine_path("default") if boundary.startswith("machine") else state_file(machine)
  chosen_call = 2 if boundary.endswith("recheck") else 1
  calls = [0]
  written = []
  def racing_contents(path):
    if path == chosen_path:
      calls[0] += 1
      if calls[0] == chosen_call:
        if boundary.startswith("machine"):
          data = encode_machine(machine).replace(b'["zsh"]', b'["zsh", "tmux", "mihomo"]')
          path.write_bytes(data)
        else:
          changed = ({"version": 2, "machine_id": "default", "targets": {}, "previous": {}}
                     if boundary == "state_appeared" else {**old, "pending_core_effect": False})
          write_json(path, changed)
        written.append(original(path))
    return original(path)
  monkeypatch.setattr(migration, "_contents", racing_contents)
  assert main(["migrate", "--drop-mihomo"]) == 4
  assert written and original(chosen_path) == written[0]
  assert not (machine.private_state_root / "drop-mihomo-migration.json").exists()


def test_current_previous_component_keys_are_strict(isolated_environment):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  value = read_state(machine)
  value["previous"]["mihomo"] = {}
  write_json(state_file(machine), value)
  with pytest.raises(TermcfgError) as error:
    read_state(machine)
  assert error.value.reason == "invalid_private_state"
