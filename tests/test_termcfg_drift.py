"""来源与目标同时变化时保留用户改动和旧备份。"""

from dataclasses import replace
import hashlib
import os
from pathlib import Path

import pytest

from termcfg import environment, preview
from termcfg.catalog import SourceArtifact, load_catalog
from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.errors import TermcfgError
from termcfg.state import read_state
from termcfg.transaction import rollback_preview


pytestmark = pytest.mark.usefixtures("fake_terminal_commands")


def _managed_zsh():
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = preview.build_preview(machine, ("zsh",))
  assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id]) == 0
  return machine


def test_source_and_target_change_together_do_not_advance_baseline(isolated_environment, monkeypatch):
  machine = _managed_zsh()
  state_before = read_state(machine)
  target = isolated_environment.home / ".zshenv"
  target.write_text("export EDITOR=vim\n")
  old = load_catalog()
  new_bytes = b"# synthetic new public zshrc\n"
  new_digest = hashlib.sha256(new_bytes).hexdigest()
  altered = tuple(replace(item, sha256=new_digest) if item.id == "zshrc" else item for item in old)
  original_bytes = SourceArtifact.bytes
  def synthetic_source(self):
    return new_bytes if self.id == "zshrc" and self.sha256 == new_digest else original_bytes(self)
  monkeypatch.setattr(SourceArtifact, "bytes", synthetic_source)
  monkeypatch.setattr(preview, "load_catalog", lambda: altered)
  monkeypatch.setattr(environment, "load_catalog", lambda: altered)
  plan = preview.build_preview(machine, ("zsh",))
  assert any(item.action == "conflict" for item in plan.targets)
  assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id]) == 4
  assert read_state(machine) == state_before
  assert target.read_text() == "export EDITOR=vim\n"
  assert not (machine.private_state_root / "journal.json").exists()


@pytest.mark.parametrize("mutation", ["mode", "symlink", "hardlink"])
def test_target_identity_mutation_rejected_without_backup_loss(isolated_environment, mutation):
  machine = _managed_zsh()
  state_before = read_state(machine)
  target = isolated_environment.home / ".zshrc"
  if mutation == "mode":
    target.chmod(0o600 if target.stat().st_mode & 0o777 != 0o600 else 0o644)
  elif mutation == "symlink":
    target.unlink()
    target.symlink_to("/tmp/starter/shell_config/zshrc.zsh")
  else:
    (isolated_environment.home / "hardlink-sentinel").hardlink_to(target)
  with pytest.raises(TermcfgError):
    preview.build_preview(machine, ("zsh",)) if mutation == "hardlink" else rollback_preview(machine, "zsh")
  assert read_state(machine) == state_before


def test_rollback_preview_rejects_private_drift(isolated_environment):
  machine = _managed_zsh()
  target = isolated_environment.home / ".zshenv"
  target.write_text("export API_KEY=synthetic-private\n")
  with pytest.raises(TermcfgError) as error:
    rollback_preview(machine, "zsh")
  assert error.value.reason == "possible_private_content"


def test_foreign_owned_target_is_rejected_before_read(isolated_environment, monkeypatch):
  machine = _managed_zsh()
  target = isolated_environment.home / ".zshrc"
  original_lstat = Path.lstat
  def foreign_lstat(path):
    info = original_lstat(path)
    if path == target:
      fields = list(info)
      fields[4] = os.getuid() + 1
      return os.stat_result(fields)
    return info
  monkeypatch.setattr(Path, "lstat", foreign_lstat)
  with pytest.raises(TermcfgError) as error:
    preview.build_preview(machine, ("zsh",))
  assert error.value.reason == "target_owner_conflict"
