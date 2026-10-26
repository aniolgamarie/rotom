"""入口生成与逐写入故障；只操作临时 HOME，不执行生成脚本。"""
import hashlib
import json
import os
from pathlib import Path
import shutil

import pytest

from rotom import entry
from termcfg import transaction
from termcfg.catalog import REPO_ROOT, load_catalog
from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.errors import TermcfgError
from termcfg.preview import build_preview
from termcfg.state import read_journal, read_state


pytestmark = pytest.mark.usefixtures("fake_terminal_commands")


def checkout(tmp_path, name="checkout"):
  root = tmp_path / name
  root.mkdir(mode=0o700)
  for relative in entry.PROTOCOL_SOURCES:
    path = root / relative
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    shutil.copyfile(REPO_ROOT / relative, path)
    path.chmod(0o700 if relative == "rotom" else 0o600)
  environment = root / ".venv"
  (environment / "bin").mkdir(parents=True, mode=0o700)
  (environment / "pyvenv.cfg").write_text("home = /opt/rotom-example-python\nversion = 3.11.11\n")
  python = environment / "bin/python"
  python.write_bytes(b"synthetic interpreter; never execute\n")
  python.chmod(0o700)
  return root


def machine():
  assert main(["init-local", "--component", "zsh"]) == 0
  return read_machine("default")


def deploy(selected, repository):
  plan = build_preview(selected, ("zsh",), entry_repo=repository)
  result = transaction.apply(selected, ("zsh",), plan_id=plan.plan_id,
    adopted=set(), confirm_zshenv=None, entry_repo=repository)
  return plan, result


def test_binding_is_deterministic_fixed_protocol_and_literal_checkout(tmp_path):
  root = checkout(tmp_path, "space 与 unicode")
  binding = entry.create_binding(root)
  assert binding["schema_version"] == binding["launcher_protocol"] == 1
  assert binding["repository"] == str(root)
  assert binding["entry_relative"] == "rotom"
  assert binding["python_relative"] == ".venv/bin/python"
  payload = entry.serialize_binding(binding)
  assert payload == entry.serialize_binding(entry.create_binding(root))
  assert payload.endswith(b"\n") and entry.parse_binding(payload) == binding


def test_prepared_python_rejects_unsafe_intermediate_symlink_directory(tmp_path):
  root = checkout(tmp_path)
  original = root / ".venv/bin"
  private = root / ".venv/prepared-bin"
  original.rename(private)
  intermediate = tmp_path / "unsafe-python-links"
  intermediate.mkdir(mode=0o777)
  intermediate.chmod(0o777)
  (intermediate / "python").symlink_to(private / "python")
  original.symlink_to(intermediate, target_is_directory=True)
  with pytest.raises(TermcfgError) as caught:
    entry.create_binding(root)
  assert caught.value.code == 4


def test_fifo_source_is_opened_nonblocking_then_rejected(tmp_path, monkeypatch):
  from rotom import entry_locator
  path = tmp_path / "fifo"
  os.mkfifo(path, 0o600)
  original = os.open
  def checked(name, flags, *args, **kwargs):
    if name == "fifo":
      assert flags & os.O_NONBLOCK, "不得在核实普通文件前阻塞打开FIFO"
    return original(name, flags, *args, **kwargs)
  monkeypatch.setattr(os, "open", checked)
  with pytest.raises(entry_locator.LocatorError) as caught:
    entry_locator._file(path)
  assert caught.value.code == 4


@pytest.mark.parametrize("mutate", [
  lambda value: value.update(schema_version=True),
  lambda value: value.update(schema_version=1.0),
  lambda value: value.update(schema_version=2),
  lambda value: value.update(launcher_protocol=2),
  lambda value: value.update(entry_relative="other-command"),
  lambda value: value.update(python_relative="/usr/bin/python3"),
  lambda value: value.update(repository="relative/path"),
  lambda value: value.update(extra="unknown"),
])
def test_binding_rejects_unknown_versions_fields_and_arbitrary_execution(tmp_path, mutate):
  binding = entry.create_binding(checkout(tmp_path))
  mutate(binding)
  with pytest.raises(TermcfgError) as caught:
    entry.parse_binding(json.dumps(binding).encode())
  assert caught.value.code == 2


@pytest.mark.parametrize("payload", [b'{"schema_version":1,"schema_version":1}', b'{"schema_version":NaN}', b"\xff"])
def test_binding_rejects_duplicate_nonfinite_and_invalid_utf8(payload):
  with pytest.raises(TermcfgError) as caught:
    entry.parse_binding(payload)
  assert caught.value.code == 2


def test_binding_source_change_invalidates_snapshot_even_when_git_head_is_unchanged(tmp_path):
  root = checkout(tmp_path)
  payload = entry.serialize_binding(entry.create_binding(root))
  path = root / "rotom"
  path.write_bytes(path.read_bytes() + b"\n# reviewed content changed\n")
  with pytest.raises(TermcfgError) as caught:
    entry.parse_binding(payload)
  assert caught.value.code == 4


def test_generated_catalog_is_restricted_and_static_v1_stays_supported(tmp_path):
  catalog = load_catalog()
  generated = [item for item in catalog if getattr(item, "kind", None) == "rotom-entry-binding"]
  assert len(generated) == 1 and generated[0].component == "zsh"
  assert generated[0].destination == Path(".local/share/rotom/entry.json")
  value = {"version": 1, "targets": [json.loads((REPO_ROOT / "terminals/catalog.json").read_text())["targets"][0]]}
  value["targets"][0].pop("kind", None)
  path = tmp_path / "catalog-v1.json"
  path.write_text(json.dumps(value))
  assert len(load_catalog(path)) == 1


def test_entry_repo_cli_is_explicit_zsh_only_and_preview_shows_source(isolated_environment, tmp_path, capsys):
  selected = machine()
  root = checkout(tmp_path)
  assert main(["--json", "plan", "--component", "zsh", "--entry-repo", str(root)]) == 0
  preview = json.loads(capsys.readouterr().out.splitlines()[-1])
  item = next(item for item in preview["targets"] if item["target_id"] == "rotom-entry-binding")
  assert item["entry_binding"] == {"repository": str(root), "previous_repository": None,
    "launcher_protocol": 1, "generator_version": 1}
  assert main(["--json", "apply", "--component", "zsh", "--entry-repo", str(root),
    "--plan-id", preview["plan_id"]]) == 0
  assert entry.parse_binding((selected.target_home / ".local/share/rotom/entry.json").read_bytes())["repository"] == str(root)
  capsys.readouterr()
  assert main(["--json", "plan", "--component", "tmux", "--entry-repo", str(root)]) == 2
  assert json.loads(capsys.readouterr().out)["reason"] == "entry_repo_requires_zsh"


def test_corrupt_backup_is_rejected_before_any_recovery_write(isolated_environment, tmp_path, monkeypatch, sentinel_factory):
  selected = machine()
  repository = checkout(tmp_path)
  (selected.target_home / ".zshenv").write_bytes(b"export EDITOR=vi\n")
  plan = build_preview(selected, ("zsh",), entry_repo=repository)
  original = transaction.write_json
  def interrupted(path, value):
    if path.name == "state.json":
      raise OSError("synthetic state interruption")
    return original(path, value)
  monkeypatch.setattr(transaction, "write_json", interrupted)
  with pytest.raises(TermcfgError):
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id,
      adopted={"zshenv"}, confirm_zshenv=plan.plan_id, entry_repo=repository)
  monkeypatch.setattr(transaction, "write_json", original)
  backup = next(item["backup"] for item in read_journal(selected)["items"] if item["target_id"] == "zshenv")
  Path(backup["path"]).write_bytes(b"synthetic changed backup\n")
  before = sentinel_factory(selected.target_home)
  with pytest.raises(TermcfgError) as caught:
    transaction.recover(selected)
  assert caught.value.code == 4 and read_journal(selected) is not None
  before.assert_unchanged()


@pytest.mark.parametrize("phase", ["rename", "activated"])
def test_caught_interrupt_after_entry_write_reports_pending_fact(isolated_environment, tmp_path, monkeypatch, capsys, phase):
  selected = machine()
  root = checkout(tmp_path)
  plan = build_preview(selected, ("zsh",), entry_repo=root)
  capsys.readouterr()
  original_target = transaction.atomic_target_bytes
  original_journal = transaction._write_journal
  fired = False
  def write(home, relative, *args, **kwargs):
    nonlocal fired
    result = original_target(home, relative, *args, **kwargs)
    if phase == "rename" and relative == Path(".local/share/rotom/entry.json"):
      fired = True
      raise KeyboardInterrupt
    return result
  def journal(machine, value):
    nonlocal fired
    if phase == "activated" and value["phase"] == "activated" and not fired:
      fired = True
      raise KeyboardInterrupt
    return original_journal(machine, value)
  monkeypatch.setattr(transaction, "atomic_target_bytes", write)
  monkeypatch.setattr(transaction, "_write_journal", journal)
  assert main(["--json", "apply", "--component", "zsh", "--entry-repo", str(root),
    "--plan-id", plan.plan_id]) == 130
  result = json.loads(capsys.readouterr().out)
  assert fired and result["entry_activation"] in ("activated", "possibly_activated")
  assert result["side_effect"] == "recovery_pending"
  assert (selected.target_home / ".local/share/rotom/entry.json").exists()
  monkeypatch.setattr(transaction, "atomic_target_bytes", original_target)
  monkeypatch.setattr(transaction, "_write_journal", original_journal)
  assert transaction.recover(selected)["recovered"] is True


def test_entry_activation_fact_is_visible_in_human_error():
  from termcfg.presentation import render_result
  rendered = render_result({"command": "apply", "ready": False,
    "entry_activation": "possibly_activated", "side_effect": "recovery_pending"})
  assert "已激活或可能已激活" in rendered and "先 recover" in rendered


def test_interrupt_after_binding_removed_during_rollback_preserves_recovery(isolated_environment, tmp_path, monkeypatch, capsys):
  selected = machine()
  deploy(selected, checkout(tmp_path))
  before = (selected.target_home / ".local/share/rotom/entry.json").read_bytes()
  plan = transaction.rollback_preview(selected, "zsh")
  capsys.readouterr()
  original = transaction.remove_target
  fired = False
  def interrupted(home, relative, *args, **kwargs):
    nonlocal fired
    result = original(home, relative, *args, **kwargs)
    if relative == Path(".local/share/rotom/entry.json"):
      fired = True
      raise KeyboardInterrupt
    return result
  monkeypatch.setattr(transaction, "remove_target", interrupted)
  assert main(["--json", "rollback", "--component", "zsh", "--plan-id", plan["plan_id"]]) == 130
  result = json.loads(capsys.readouterr().out)
  assert fired and result["entry_transition"] == "possibly_removed"
  assert result["side_effect"] == "recovery_pending"
  monkeypatch.setattr(transaction, "remove_target", original)
  assert transaction.recover(selected)["recovered"] is True
  assert (selected.target_home / ".local/share/rotom/entry.json").read_bytes() == before


def test_first_entry_deployment_uses_exact_private_payload_and_v3_state(isolated_environment, tmp_path):
  root = checkout(tmp_path)
  selected = machine()
  plan, result = deploy(selected, root)
  home = selected.target_home
  binding_path = home / ".local/share/rotom/entry.json"
  assert result["changed"][-1] == "rotom-entry-binding"
  assert binding_path.read_bytes() == entry.serialize_binding(entry.create_binding(root))
  assert binding_path.stat().st_mode & 0o777 == 0o600
  assert (home / ".local/bin/rotom").stat().st_mode & 0o777 == 0o700
  assert (home / ".local/share/rotom/zsh/site-functions/_rotom").stat().st_mode & 0o777 == 0o644
  state = read_state(selected)
  assert state["version"] == 3
  saved = state["targets"]["rotom-entry-binding"]["generated"]
  assert saved["kind"] == "rotom-entry-binding"
  payload = selected.private_state_root / saved["payload"]["relative"]
  assert payload.read_bytes() == binding_path.read_bytes()
  assert payload.stat().st_mode & 0o777 == 0o600
  assert hashlib.sha256(payload.read_bytes()).hexdigest() == saved["payload"]["sha256"]
  assert read_journal(selected) is None


def test_existing_binding_is_kept_and_explicit_rebind_is_reviewed(isolated_environment, tmp_path, monkeypatch):
  first = checkout(tmp_path, "first")
  second = checkout(tmp_path, "second")
  selected = machine()
  deploy(selected, first)
  old = (selected.target_home / ".local/share/rotom/entry.json").read_bytes()
  monkeypatch.setattr(entry, "REPO_ROOT", second)
  kept = build_preview(selected, ("zsh",))
  item = next(item for item in kept.targets if item.artifact.id == "rotom-entry-binding")
  assert item.action == "unchanged" and item.artifact.bytes() == old
  changed = build_preview(selected, ("zsh",), entry_repo=second)
  assert changed.plan_id != kept.plan_id
  assert json.loads(next(item for item in changed.targets if item.artifact.id == "rotom-entry-binding").artifact.bytes())["repository"] == str(second)
  with pytest.raises(TermcfgError):
    transaction.apply(selected, ("zsh",), plan_id=kept.plan_id, adopted=set(), confirm_zshenv=None, entry_repo=second)
  assert (selected.target_home / ".local/share/rotom/entry.json").read_bytes() == old


def test_source_changed_after_plan_refuses_all_home_writes(isolated_environment, tmp_path, sentinel_factory):
  root = checkout(tmp_path)
  selected = machine()
  plan = build_preview(selected, ("zsh",), entry_repo=root)
  before = sentinel_factory(selected.target_home)
  (root / "rotom").write_bytes((root / "rotom").read_bytes() + b"\n# changed\n")
  with pytest.raises(TermcfgError):
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None, entry_repo=root)
  before.assert_unchanged()


@pytest.mark.parametrize("changed", ["destination", "mode"])
def test_plan_covers_static_destination_and_desired_mode(isolated_environment, tmp_path, monkeypatch, changed):
  from dataclasses import replace
  import termcfg.preview as preview_module
  selected = machine()
  repository = checkout(tmp_path)
  original = preview_module.load_catalog()
  first = build_preview(selected, ("zsh",), entry_repo=repository)
  modified = tuple(replace(item, **({"destination": Path(".zshrc-reviewed-change")} if changed == "destination"
    else {"mode": 0o600})) if item.id == "zshrc" else item for item in original)
  monkeypatch.setattr(preview_module, "load_catalog", lambda: modified)
  second = build_preview(selected, ("zsh",), entry_repo=repository)
  assert second.plan_id != first.plan_id
  with pytest.raises(TermcfgError) as caught:
    transaction.apply(selected, ("zsh",), plan_id=first.plan_id,
      adopted=set(), confirm_zshenv=None, entry_repo=repository)
  assert caught.value.code == 2 and not (selected.target_home / ".zshrc").exists()


@pytest.mark.parametrize("version", [2, 3])
def test_partial_file_identity_cannot_prove_post_rename_ownership(isolated_environment, tmp_path, monkeypatch, version):
  from termcfg.state import journal_file, write_json
  selected = machine()
  repository = checkout(tmp_path)
  plan = build_preview(selected, ("zsh",), entry_repo=repository)
  original = transaction.atomic_target_bytes
  def interrupted(home, relative, *args, **kwargs):
    result = original(home, relative, *args, **kwargs)
    if relative == Path(".local/share/rotom/entry.json"):
      raise OSError("synthetic after binding rename")
    return result
  monkeypatch.setattr(transaction, "atomic_target_bytes", interrupted)
  with pytest.raises(TermcfgError):
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id,
      adopted=set(), confirm_zshenv=None, entry_repo=repository)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original)
  journal = read_journal(selected)
  journal["version"] = version
  for item in journal["items"]:
    if version == 2:
      item.pop("generated", None)
    if item["target_id"] == "rotom-entry-binding":
      item["intended_after"] = {"kind": "file", "digest": item["desired"]}
  write_json(journal_file(selected), journal)
  path = selected.target_home / ".local/share/rotom/entry.json"
  replacement = path.with_name("replacement")
  replacement.write_bytes(path.read_bytes())
  replacement.chmod(0o600)
  os.replace(replacement, path)
  before = journal_file(selected).read_bytes()
  with pytest.raises(TermcfgError) as caught:
    transaction.recover(selected)
  assert caught.value.code in (2, 4) and path.exists()
  assert journal_file(selected).read_bytes() == before


@pytest.mark.parametrize("target", [".local/bin/rotom", ".local/share/rotom/entry.json"])
def test_unmanaged_entry_links_refused_without_touching_target(isolated_environment, tmp_path, target):
  root = checkout(tmp_path)
  selected = machine()
  path = selected.target_home / target
  path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
  destination = tmp_path / "untouched"
  destination.write_bytes(b"synthetic sentinel")
  path.symlink_to(destination)
  with pytest.raises(TermcfgError):
    plan = build_preview(selected, ("zsh",), entry_repo=root)
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None, entry_repo=root)
  assert path.is_symlink() and destination.read_bytes() == b"synthetic sentinel"


@pytest.mark.parametrize("fault", ["payload", "prepared", "static", "binding_rename", "activated", "state"])
def test_each_generated_transaction_fault_preserves_recoverable_evidence(isolated_environment, tmp_path, monkeypatch, fault):
  root = checkout(tmp_path)
  selected = machine()
  plan = build_preview(selected, ("zsh",), entry_repo=root)
  original_write = transaction._write_journal
  original_target = transaction.atomic_target_bytes
  original_state = transaction.write_json
  original_payload = transaction._write_generated_payload
  fired = False
  def fail_payload(*args, **kwargs):
    nonlocal fired
    if fault == "payload":
      fired = True
      raise OSError("synthetic payload failure")
    return original_payload(*args, **kwargs)
  def fail_journal(machine, journal):
    nonlocal fired
    if not fired and ((fault == "prepared" and journal["phase"] == "prepared")
        or (fault == "activated" and journal["phase"] == "activated")):
      fired = True
      raise OSError("synthetic journal failure")
    return original_write(machine, journal)
  def fail_target(home, relative, *args, **kwargs):
    nonlocal fired
    if not fired and fault == "static" and relative == Path(".local/bin/rotom"):
      fired = True
      raise OSError("synthetic static write failure")
    result = original_target(home, relative, *args, **kwargs)
    if not fired and fault == "binding_rename" and relative == Path(".local/share/rotom/entry.json"):
      fired = True
      raise OSError("synthetic post-rename failure")
    return result
  def fail_state(path, value):
    nonlocal fired
    if fault == "state" and path.name == "state.json":
      fired = True
      raise OSError("synthetic state failure")
    return original_state(path, value)
  monkeypatch.setattr(transaction, "_write_generated_payload", fail_payload)
  monkeypatch.setattr(transaction, "_write_journal", fail_journal)
  monkeypatch.setattr(transaction, "atomic_target_bytes", fail_target)
  monkeypatch.setattr(transaction, "write_json", fail_state)
  with pytest.raises((TermcfgError, OSError)) as caught:
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None, entry_repo=root)
  assert fired, "指定故障窗口未命中，不能把提前失败当作故障注入通过"
  monkeypatch.setattr(transaction, "_write_generated_payload", original_payload)
  monkeypatch.setattr(transaction, "_write_journal", original_write)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original_target)
  monkeypatch.setattr(transaction, "write_json", original_state)
  if fault in ("binding_rename", "activated", "state"):
    assert (selected.target_home / ".local/share/rotom/entry.json").exists()
    assert read_journal(selected) is not None
    assert isinstance(caught.value, TermcfgError)
    assert caught.value.context["entry_activation"] in ("activated", "possibly_activated")
  # 恢复只依据保存的 payload/backup/身份，不需要原 checkout 继续存在。
  shutil.rmtree(root)
  if (selected.private_state_root / "journal.json").exists():
    assert transaction.recover(selected)["recovered"] is True
  assert not (selected.target_home / ".local/share/rotom/entry.json").exists()
  assert read_state(selected)["targets"] == {}


def test_drift_after_binding_activation_keeps_pending_and_never_claims_byte_ownership(isolated_environment, tmp_path, monkeypatch):
  root = checkout(tmp_path)
  selected = machine()
  plan = build_preview(selected, ("zsh",), entry_repo=root)
  original = transaction.atomic_target_bytes
  def interrupt(home, relative, *args, **kwargs):
    result = original(home, relative, *args, **kwargs)
    if relative == Path(".local/share/rotom/entry.json"):
      raise OSError("synthetic after binding activation")
    return result
  monkeypatch.setattr(transaction, "atomic_target_bytes", interrupt)
  with pytest.raises((TermcfgError, OSError)):
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None, entry_repo=root)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original)
  path = selected.target_home / ".local/share/rotom/entry.json"
  replacement = path.with_name("replacement.json")
  replacement.write_bytes(path.read_bytes())
  replacement.chmod(0o600)
  os.replace(replacement, path)
  with pytest.raises(TermcfgError) as caught:
    transaction.recover(selected)
  assert caught.value.code == 4
  assert read_journal(selected) is not None and path.exists()


def test_entry_repository_is_only_valid_with_zsh(isolated_environment, tmp_path):
  selected = machine()
  with pytest.raises(TermcfgError) as caught:
    build_preview(selected, ("tmux",), entry_repo=checkout(tmp_path))
  assert caught.value.code == 2


def test_legacy_v2_pending_journal_recovers_without_migration(isolated_environment):
  from termcfg.state import private_dir, write_json, journal_file
  selected = machine()
  private_dir(selected.private_state_root)
  original = {"version": 2, "machine_id": selected.machine_id, "targets": {}, "previous": {}}
  journal = {"version": 2, "kind": "apply", "transaction_id": "a" * 32,
    "phase": "prepared", "plan_id": "b" * 64, "state_before": original, "items": []}
  write_json(journal_file(selected), journal)
  assert read_journal(selected)["version"] == 2
  assert transaction.recover(selected)["recovered"] is True
  assert read_state(selected) == original


def test_generated_state_never_downgrades_during_first_install_rollback(isolated_environment, tmp_path):
  selected = machine()
  deploy(selected, checkout(tmp_path))
  plan = transaction.rollback_preview(selected, "zsh")
  transaction.rollback(selected, "zsh", plan_id=plan["plan_id"])
  assert not (selected.target_home / ".local/share/rotom/entry.json").exists()
  assert read_state(selected)["version"] == 3


def test_entry_noop_preserves_backup_and_payload_identity(isolated_environment, tmp_path):
  selected = machine()
  deploy(selected, checkout(tmp_path))
  original = read_state(selected)
  path = selected.target_home / ".local/share/rotom/entry.json"
  inode = path.stat().st_ino
  plan = build_preview(selected, ("zsh",))
  result = transaction.apply(selected, ("zsh",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None)
  assert result["changed"] == []
  assert path.stat().st_ino == inode and read_state(selected) == original


def test_ambiguous_post_rename_without_identity_proof_stays_pending(isolated_environment, tmp_path, monkeypatch):
  selected = machine()
  root = checkout(tmp_path)
  plan = build_preview(selected, ("zsh",), entry_repo=root)
  original = transaction.atomic_target_bytes
  def lost_intent(home, relative, *args, **kwargs):
    if relative == Path(".local/share/rotom/entry.json"):
      kwargs.pop("before_replace", None)
      original(home, relative, *args, **kwargs)
      raise OSError("synthetic lost durable identity evidence")
    return original(home, relative, *args, **kwargs)
  monkeypatch.setattr(transaction, "atomic_target_bytes", lost_intent)
  with pytest.raises((TermcfgError, OSError)):
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None, entry_repo=root)
  monkeypatch.setattr(transaction, "atomic_target_bytes", original)
  with pytest.raises(TermcfgError) as caught:
    transaction.recover(selected)
  assert caught.value.code == 4 and read_journal(selected) is not None


def test_unsafe_target_ancestor_refuses_without_overwriting_other_home(isolated_environment, tmp_path):
  selected = machine()
  root = checkout(tmp_path)
  other = tmp_path / "other-home"
  other.mkdir(mode=0o700)
  (selected.target_home / ".local").symlink_to(other)
  with pytest.raises(TermcfgError) as caught:
    build_preview(selected, ("zsh",), entry_repo=root)
  assert caught.value.code == 4 and list(other.iterdir()) == []


def test_binding_payload_directory_must_be_private(isolated_environment, tmp_path):
  selected = machine()
  root = checkout(tmp_path)
  parent = selected.target_home / ".local/share/rotom"
  parent.mkdir(parents=True, mode=0o755)
  parent.chmod(0o755)
  with pytest.raises(TermcfgError) as caught:
    build_preview(selected, ("zsh",), entry_repo=root)
  assert caught.value.code == 4 and not (parent / "entry.json").exists()


def test_static_only_deployment_keeps_state_v2(isolated_environment):
  selected = machine()
  plan = build_preview(selected, ("tmux",))
  transaction.apply(selected, ("tmux",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None)
  assert read_state(selected)["version"] == 2
  assert not (selected.target_home / ".local/share/rotom").exists()


def test_binding_directory_fsync_failure_after_rename_recovers_by_saved_identity(isolated_environment, tmp_path, monkeypatch):
  import stat
  selected = machine()
  root = checkout(tmp_path)
  plan = build_preview(selected, ("zsh",), entry_repo=root)
  original = os.fsync
  target = selected.target_home / ".local/share/rotom/entry.json"
  fired = False
  def fail(fd):
    nonlocal fired
    observed = os.fstat(fd)
    if not fired and target.exists() and stat.S_ISDIR(observed.st_mode):
      parent = target.parent.stat()
      if (observed.st_dev, observed.st_ino) == (parent.st_dev, parent.st_ino):
        fired = True
        raise OSError("synthetic binding directory fsync failure")
    return original(fd)
  monkeypatch.setattr(os, "fsync", fail)
  with pytest.raises((TermcfgError, OSError)):
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id, adopted=set(), confirm_zshenv=None, entry_repo=root)
  assert fired and read_journal(selected) is not None
  monkeypatch.setattr(os, "fsync", original)
  assert transaction.recover(selected)["recovered"] is True
  assert not target.exists()


def test_missing_bound_checkout_requires_explicit_repair_without_scanning(isolated_environment, tmp_path):
  selected = machine()
  first = checkout(tmp_path, "first")
  second = checkout(tmp_path, "second")
  deploy(selected, first)
  shutil.rmtree(first)
  with pytest.raises(TermcfgError):
    build_preview(selected, ("zsh",))
  # 显式审阅的新来源可修复丢失源码；不能要求先执行旧 checkout。
  plan = build_preview(selected, ("zsh",), entry_repo=second)
  item = next(item for item in plan.targets if item.artifact.id == "rotom-entry-binding")
  assert json.loads(item.artifact.bytes())["repository"] == str(second)


def installed_entry(home, repository):
  launcher = home / ".local/bin/rotom"
  launcher.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
  shutil.copyfile(REPO_ROOT / "terminals/zsh/rotom", launcher)
  launcher.chmod(0o700)
  binding = home / ".local/share/rotom/entry.json"
  binding.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
  binding.write_bytes(entry.serialize_binding(entry.create_binding(repository)))
  binding.chmod(0o600)
  return launcher, binding


def test_installed_locator_uses_its_own_layout_with_other_home_xdg_and_cwd(isolated_environment, tmp_path, monkeypatch):
  repository = checkout(tmp_path, "source space 与 unicode")
  launcher, _ = installed_entry(isolated_environment.home, repository)
  other = tmp_path / "other-home"
  other.mkdir(mode=0o700)
  bait = other / ".local/share/rotom/entry.json"
  bait.parent.mkdir(parents=True, mode=0o700)
  bait.write_bytes(b"invalid foreign binding must not be read")
  monkeypatch.setenv("HOME", str(other))
  monkeypatch.setenv("XDG_CONFIG_HOME", str(other / "config"))
  monkeypatch.setenv("XDG_DATA_HOME", str(other / "data"))
  monkeypatch.chdir(other)
  python, argv = entry.resolve_installed_invocation(launcher, ("run", "pi", "--", "literal $(value)", "中文 value"))
  assert python == str(repository / ".venv/bin/python")
  assert tuple(argv) == (python, "-I", "-B", str(repository / "rotom"), "run", "pi", "--", "literal $(value)", "中文 value")


def test_installed_locator_refuses_link_or_unsupported_layout(isolated_environment, tmp_path):
  repository = checkout(tmp_path)
  launcher, _ = installed_entry(isolated_environment.home, repository)
  copied = tmp_path / "rotom"
  shutil.copyfile(launcher, copied)
  copied.chmod(0o700)
  with pytest.raises(TermcfgError):
    entry.resolve_installed_invocation(copied, ("--help",))
  original = launcher.with_name("source")
  launcher.rename(original)
  launcher.symlink_to(original)
  with pytest.raises(TermcfgError):
    entry.resolve_installed_invocation(launcher, ("--help",))


def test_locator_fake_exec_preserves_stdin_argv_and_exit_without_execution(isolated_environment, tmp_path, monkeypatch):
  from rotom import entry_locator
  repository = checkout(tmp_path)
  launcher, _ = installed_entry(isolated_environment.home, repository)
  class Unreadable:
    def read(self, *a):
      pytest.fail("locator read stdin")
    readline = read
  monkeypatch.setattr("sys.stdin", Unreadable())
  calls = []
  def fake_exec(binary, argv):
    calls.append((binary, tuple(argv)))
    raise SystemExit(23)
  monkeypatch.setattr(entry_locator.os, "execv", fake_exec)
  with pytest.raises(SystemExit) as caught:
    entry_locator.main([str(launcher), "--help", "literal with space"])
  assert caught.value.code == 23
  assert calls[0][1][-2:] == ("--help", "literal with space")
  assert "python3 -I -S -B" in launcher.read_text()


def test_missing_prepared_environment_is_not_replaced_or_searched(tmp_path, sentinel_factory):
  repository = checkout(tmp_path)
  shutil.rmtree(repository / ".venv")
  before = sentinel_factory(tmp_path)
  with pytest.raises(TermcfgError) as caught:
    entry.create_binding(repository)
  assert caught.value.code == 5
  before.assert_unchanged()


def test_protocol_source_link_is_rejected(tmp_path):
  repository = checkout(tmp_path)
  source = repository / "rotom"
  other = tmp_path / "other-source"
  source.rename(other)
  source.symlink_to(other)
  with pytest.raises(TermcfgError) as caught:
    entry.create_binding(repository)
  assert caught.value.code == 4


def test_generated_catalog_cannot_choose_arbitrary_target_or_command(tmp_path):
  value = json.loads((REPO_ROOT / "terminals/catalog.json").read_text())
  item = next(item for item in value["targets"] if item.get("kind") == "rotom-entry-binding")
  item["destination"] = ".config/unrelated-tool/config.json"
  item["command"] = "arbitrary command"
  path = tmp_path / "catalog.json"
  path.write_text(json.dumps(value))
  with pytest.raises(TermcfgError) as caught:
    load_catalog(path)
  assert caught.value.code == 2


@pytest.mark.parametrize("payload", [
  b'{"version":2,"version":2,"machine_id":"default","targets":{},"previous":{}}',
  b'{"version":NaN,"machine_id":"default","targets":{},"previous":{}}',
  b'{"version":true,"machine_id":"default","targets":{},"previous":{}}',
  b'{"version":4,"machine_id":"default","targets":{},"previous":{}}',
])
def test_state_reader_rejects_duplicate_nonfinite_boolean_or_unknown_version(isolated_environment, payload):
  from termcfg.state import private_dir, state_file
  selected = machine()
  private_dir(selected.private_state_root)
  path = state_file(selected)
  path.write_bytes(payload)
  path.chmod(0o600)
  with pytest.raises(TermcfgError) as caught:
    read_state(selected)
  assert caught.value.code == 2 and path.read_bytes() == payload


def test_old_reader_rejects_generated_v3_state(isolated_environment, tmp_path):
  from jsonschema import Draft202012Validator
  selected = machine()
  deploy(selected, checkout(tmp_path))
  schema = json.loads((REPO_ROOT / "tests/fixtures/rotom/term-state-v2.schema.json").read_text())
  assert not Draft202012Validator(schema).is_valid(read_state(selected))


def test_active_v2_pending_is_not_upgraded_or_mixed_with_new_entry(isolated_environment, tmp_path, monkeypatch):
  from termcfg.state import private_dir, write_json, journal_file
  selected = machine()
  private_dir(selected.private_state_root)
  journal = {"version": 2, "kind": "apply", "transaction_id": "a" * 32,
    "phase": "prepared", "plan_id": "b" * 64,
    "state_before": {"version": 2, "machine_id": selected.machine_id, "targets": {}, "previous": {}}, "items": []}
  write_json(journal_file(selected), journal)
  before = journal_file(selected).read_bytes()
  repository = checkout(tmp_path)
  monkeypatch.setattr(entry, "create_binding", lambda *a, **k: pytest.fail("pending transaction considered new entry"))
  with pytest.raises(TermcfgError) as caught:
    transaction.apply(selected, ("zsh",), plan_id="b" * 64,
      adopted=set(), confirm_zshenv=None, entry_repo=repository)
  assert caught.value.code == 4
  assert journal_file(selected).read_bytes() == before
  assert not (selected.target_home / ".local/bin/rotom").exists()


def test_payload_backups_and_prepared_journal_are_durable_before_home_write(isolated_environment, tmp_path, monkeypatch):
  selected = machine()
  repository = checkout(tmp_path)
  old_zshenv = selected.target_home / ".zshenv"
  old_zshenv.write_bytes(b"export EDITOR=vi\n")
  plan = build_preview(selected, ("zsh",), entry_repo=repository)
  sync = os.fsync
  synced = set()
  def observe_sync(fd):
    value = os.fstat(fd)
    result = sync(fd)
    synced.add((value.st_dev, value.st_ino))
    return result
  monkeypatch.setattr(os, "fsync", observe_sync)
  original = transaction.atomic_target_bytes
  order = []
  def write(home, relative, *args, **kwargs):
    journal = read_journal(selected)
    assert journal["version"] == 3
    assert all(item["backup"] is not None for item in journal["items"])
    saved = next(item["generated"] for item in journal["items"] if item["target_id"] == "rotom-entry-binding")
    payload = selected.private_state_root / saved["payload"]["relative"]
    journal_path = selected.private_state_root / "journal.json"
    backup = next(item["backup"] for item in journal["items"] if item["target_id"] == "zshenv")
    backup_path = Path(backup["path"])
    assert backup_path.read_bytes() == b"export EDITOR=vi\n"
    assert hashlib.sha256(backup_path.read_bytes()).hexdigest() == backup["digest"]
    for path in (payload, payload.parent, payload.parent.parent, journal_path, journal_path.parent,
        backup_path, backup_path.parent, backup_path.parent.parent):
      value = path.stat()
      assert (value.st_dev, value.st_ino) in synced
    assert payload.stat().st_mode & 0o777 == 0o600
    assert hashlib.sha256(payload.read_bytes()).hexdigest() == saved["payload"]["sha256"]
    order.append(str(relative))
    return original(home, relative, *args, **kwargs)
  monkeypatch.setattr(transaction, "atomic_target_bytes", write)
  transaction.apply(selected, ("zsh",), plan_id=plan.plan_id,
    adopted={"zshenv"}, confirm_zshenv=plan.plan_id, entry_repo=repository)
  assert order[-1] == ".local/share/rotom/entry.json"


def test_interrupted_rebind_restores_saved_old_binding_without_either_checkout(isolated_environment, tmp_path, monkeypatch):
  selected = machine()
  first = checkout(tmp_path, "first")
  second = checkout(tmp_path, "second")
  deploy(selected, first)
  previous = read_state(selected)
  paths = (".local/bin/rotom", ".local/share/rotom/entry.json", ".zshrc", ".zshenv")
  originals = {relative: ((selected.target_home / relative).read_bytes(),
    (selected.target_home / relative).stat().st_mode & 0o777) for relative in paths}
  plan = build_preview(selected, ("zsh",), entry_repo=second)
  original_write = transaction._write_journal
  fired = False
  def interrupt(machine, journal):
    nonlocal fired
    if not fired and journal["phase"] == "activated":
      fired = True
      raise OSError("synthetic rebind activation journal interruption")
    return original_write(machine, journal)
  monkeypatch.setattr(transaction, "_write_journal", interrupt)
  with pytest.raises(TermcfgError) as caught:
    transaction.apply(selected, ("zsh",), plan_id=plan.plan_id,
      adopted=set(), confirm_zshenv=None, entry_repo=second)
  assert fired and caught.value.context["entry_activation"] in ("activated", "possibly_activated")
  monkeypatch.setattr(transaction, "_write_journal", original_write)
  shutil.rmtree(first)
  shutil.rmtree(second)
  assert transaction.recover(selected)["recovered"] is True
  for relative, (contents, mode) in originals.items():
    path = selected.target_home / relative
    assert path.read_bytes() == contents and path.stat().st_mode & 0o777 == mode
  actual = read_state(selected)
  assert actual["version"] == 3 and actual["previous"] == previous["previous"]
  assert actual["targets"].keys() == previous["targets"].keys()
  for target, record in previous["targets"].items():
    assert actual["targets"][target]["source_digest"] == record["source_digest"]
  assert actual["targets"]["rotom-entry-binding"]["generated"] == previous["targets"]["rotom-entry-binding"]["generated"]
