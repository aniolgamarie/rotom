"""重复中断后的 journal 仍提供逐目标恢复事实。"""

import pytest
import json
import os

from termcfg import transaction
from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.preview import build_preview
from termcfg.state import read_journal, read_state


pytestmark = pytest.mark.usefixtures("fake_terminal_commands")


def test_recovery_can_resume_after_second_interrupt(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  original_write = transaction.atomic_target_bytes
  def crash_apply(*args, **kwargs):
    original_write(*args, **kwargs)
    raise OSError("synthetic apply interruption")
  monkeypatch.setattr(transaction, "atomic_target_bytes", crash_apply)
  with pytest.raises(transaction.TermcfgError):
    transaction.apply(machine, ("zsh",), plan_id=plan.plan_id,
                      adopted=set(), confirm_zshenv=None)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original_write)
  journal = read_journal(machine)
  assert journal is not None and journal["phase"] == "recovery_pending"
  assert journal["items"][0]["stage"] == "pending"
  original_restore = transaction._restore_one
  def crash_recovery(*args, **kwargs):
    original_restore(*args, **kwargs)
    raise OSError("synthetic recovery interruption")
  monkeypatch.setattr(transaction, "_restore_one", crash_recovery)
  with pytest.raises(OSError):
    transaction.recover(machine)
  monkeypatch.setattr(transaction, "_restore_one", original_restore)
  interrupted = read_journal(machine)
  assert interrupted is not None and interrupted["phase"] == "recovery_pending"
  assert interrupted["items"][0]["recovery_intended"] == {"kind": "absent"}
  assert transaction.recover(machine)["recovered"] is True
  assert read_journal(machine) is None
  assert read_state(machine)["targets"] == {}
  assert not (isolated_environment.home / ".zshrc").exists()


def test_external_change_blocks_recovery_and_keeps_journal(isolated_environment, monkeypatch):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  original_write = transaction.atomic_target_bytes
  def crash_apply(*args, **kwargs):
    original_write(*args, **kwargs)
    raise OSError("synthetic apply interruption")
  monkeypatch.setattr(transaction, "atomic_target_bytes", crash_apply)
  with pytest.raises(transaction.TermcfgError):
    transaction.apply(machine, ("zsh",), plan_id=plan.plan_id,
                      adopted=set(), confirm_zshenv=None)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original_write)
  (isolated_environment.home / ".zshrc").write_text("external edit\n")
  with pytest.raises(transaction.TermcfgError) as error:
    transaction.recover(machine)
  assert error.value.code == 4
  assert read_journal(machine) is not None


def test_same_length_external_change_with_restored_mtime_blocks_recovery(isolated_environment,
                                                                         monkeypatch):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  original_write = transaction.atomic_target_bytes
  def crash_apply(*args, **kwargs):
    original_write(*args, **kwargs)
    raise OSError("synthetic apply interruption")
  monkeypatch.setattr(transaction, "atomic_target_bytes", crash_apply)
  with pytest.raises(transaction.TermcfgError):
    transaction.apply(machine, ("zsh",), plan_id=plan.plan_id,
                      adopted=set(), confirm_zshenv=None)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original_write)
  journal = read_journal(machine)
  assert journal is not None
  target = isolated_environment.home / journal["items"][0]["relative"]
  original = target.read_bytes()
  forged = b"X" * len(original)
  assert forged != original
  target.write_bytes(forged)
  original_mtime_ns = journal["items"][0]["intended_after"]["mtime_ns"]
  os.utime(target, ns=(original_mtime_ns, original_mtime_ns))
  assert target.stat().st_mtime_ns == original_mtime_ns
  with pytest.raises(transaction.TermcfgError) as error:
    transaction.recover(machine)
  assert error.value.code == 4
  assert target.read_bytes() == forged
  assert read_journal(machine) is not None


def test_recover_and_rescue_status_work_when_public_source_is_broken(isolated_environment,
                                                                    monkeypatch, capsys):
  from termcfg.catalog import SourceArtifact
  from termcfg.errors import TermcfgError
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  original_write = transaction.atomic_target_bytes
  def crash_apply(*args, **kwargs):
    original_write(*args, **kwargs)
    raise OSError("synthetic apply interruption")
  monkeypatch.setattr(transaction, "atomic_target_bytes", crash_apply)
  with pytest.raises(TermcfgError):
    transaction.apply(machine, ("zsh",), plan_id=plan.plan_id,
                      adopted=set(), confirm_zshenv=None)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original_write)
  monkeypatch.setattr(SourceArtifact, "bytes", lambda self: (_ for _ in ()).throw(TermcfgError(5, "source_digest_mismatch")))
  from termcfg import cli
  monkeypatch.setattr(cli, "_read_lock_raw", lambda component: (_ for _ in ()).throw(TermcfgError(2, "invalid_asset_lock")))
  capsys.readouterr()
  assert main(["status", "--component", "zsh", "--json"]) == 0
  status = json.loads(capsys.readouterr().out)
  assert status["recovery_pending"] is True
  assert status["source_diagnostic"] == "source_digest_mismatch"
  assert main(["recover", "--json"]) == 0
  assert json.loads(capsys.readouterr().out)["recovered"] is True
  assert read_journal(machine) is None
