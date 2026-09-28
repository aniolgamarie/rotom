"""公开配置的备份优先事务、显式接管和安全恢复。"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid
from contextlib import contextmanager

from .catalog import REPO_ROOT, load_catalog
from .config import MachineSelection, require_current_machine
from .diagnostics import Progress
from .errors import TermcfgError
from .home_targets import atomic_target_bytes, atomic_target_link, inspect_target, read_regular, remove_target
from .lease import operation_lease, repository_lease
from .preview import Preview, PlannedTarget, build_preview
from .secret_boundary import admit_existing
from .state import journal_file, private_dir, read_journal, read_state, state_file, write_json


@contextmanager
def _target_context(component: str, target_id: str, stage: str):
  try:
    yield
  except TermcfgError as exc:
    exc.context.update({"component": component, "target_id": target_id, "stage": stage})
    raise
  except OSError as exc:
    raise TermcfgError(6, "filesystem_failure", "./termcfg status",
                       component=component, target_id=target_id, stage=stage) from exc


def _identity_with_digest(machine: MachineSelection, item: PlannedTarget) -> dict:
  identity = inspect_target(machine.target_home, item.artifact.destination)
  value = identity.as_dict()
  if identity.kind == "file":
    value["digest"] = admit_existing(item.artifact.id,
                                     read_regular(machine.target_home, item.artifact.destination, identity),
                                     known_public_contents={item.artifact.bytes()},
                                     trusted_digest=item.before.digest)
  return value


def _backup_one(machine: MachineSelection, item: PlannedTarget, directory: Path) -> dict:
  before = item.before.as_dict()
  if item.before.kind != "file":
    return {"before": before, "path": None, "digest": None}
  data = read_regular(machine.target_home, item.artifact.destination, item.before)
  if admit_existing(item.artifact.id, data, known_public_contents={item.artifact.bytes()},
                    trusted_digest=item.before.digest) != item.before.digest:
    raise TermcfgError(4, "target_changed_before_backup")
  path = directory / f"{item.artifact.id}.backup"
  from .state import atomic_bytes
  atomic_bytes(path, data)
  if path.stat().st_mode & 0o777 != 0o600 or hashlib.sha256(path.read_bytes()).hexdigest() != item.before.digest:
    raise TermcfgError(6, "backup_verify_failed")
  return {"before": before, "path": str(path), "digest": item.before.digest}


def _verified_backup(machine: MachineSelection, backup: dict) -> bytes | None:
  path = backup.get("path")
  if path is None:
    return None
  candidate = Path(path)
  if not candidate.is_absolute() or candidate.resolve().parent.parent != machine.private_state_root / "backups":
    raise TermcfgError(4, "backup_outside_private_root")
  info = candidate.lstat()
  if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
    raise TermcfgError(4, "unsafe_backup")
  data = candidate.read_bytes()
  if hashlib.sha256(data).hexdigest() != backup["digest"]:
    raise TermcfgError(4, "backup_changed")
  return data


def _restore_one(machine: MachineSelection, relative: Path, backup: dict, *, before_replace=None,
                 expected: dict | None = None) -> None:
  before = backup["before"]
  if before["kind"] == "absent":
    remove_target(machine.target_home, relative, before_remove=before_replace, expected=expected)
  elif before["kind"] == "symlink":
    atomic_target_link(machine.target_home, relative, before["link"], before_replace=before_replace,
                       expected=expected)
  else:
    data = _verified_backup(machine, backup)
    assert data is not None
    atomic_target_bytes(machine.target_home, relative, data, before["mode"], before_replace=before_replace,
                        expected=expected)


def _journal_items(machine: MachineSelection, preview: Preview, changes: list[PlannedTarget]) -> dict:
  transaction_id = uuid.uuid4().hex
  return {"version": 1, "kind": "apply", "transaction_id": transaction_id,
          "phase": "prepared", "plan_id": preview.plan_id,
          "state_before": preview.state,
          "items": [{"target_id": item.artifact.id,
                     "component": item.artifact.component,
                     "relative": str(item.artifact.destination),
                     "before": item.before.as_dict(),
                     "desired": item.artifact.sha256,
                     "mode": item.artifact.mode,
                     "backup": None, "intended_after": None, "after": None, "stage": "pending"}
                    for item in changes]}


def _write_journal(machine: MachineSelection, journal: dict) -> None:
  write_json(journal_file(machine), journal)


def _current_identity(machine: MachineSelection, target_id: str, relative: Path,
                      trusted_digests: tuple[str | None, ...] = ()) -> dict:
  current = inspect_target(machine.target_home, relative)
  identity = current.as_dict()
  if current.kind == "file":
    artifact = next((item for item in load_catalog() if item.id == target_id), None)
    known = {artifact.bytes()} if artifact is not None else set()
    data = read_regular(machine.target_home, relative, current)
    digest = None
    for trusted in trusted_digests:
      try:
        digest = admit_existing(target_id, data, known_public_contents=known,
                                trusted_digest=trusted)
        break
      except TermcfgError:
        continue
    if digest is None:
      digest = admit_existing(target_id, data, known_public_contents=known)
    identity["digest"] = digest
  return identity


def _recovery_identity(machine: MachineSelection, relative: Path, record: dict) -> dict:
  """只与 journal 的受信摘要比较，不把外部改动的摘要存入状态或输出。"""
  current = inspect_target(machine.target_home, relative)
  observed = current.as_dict()
  matching_files = []
  for name in ("before", "after", "intended_after", "recovery_intended"):
    expected = record.get(name)
    if expected is not None and all(observed.get(key) == value for key, value in expected.items() if key != "digest"):
      if current.kind != "file":
        return expected
      if not expected.get("digest"):
        raise TermcfgError(2, "invalid_transaction_journal")
      matching_files.append(expected)
  if matching_files:
    data = read_regular(machine.target_home, relative, current)
    actual = hashlib.sha256(data).hexdigest()
    for expected in matching_files:
      if actual == expected["digest"]:
        return expected
  if observed["kind"] == "absent" and (record.get("expected_restore") or {}).get("kind") == "absent":
    return {"kind": "absent"}
  raise TermcfgError(4, "recovery_target_drift", "./termcfg status")


def _clean_old_backups(machine: MachineSelection, old: dict, current: dict) -> None:
  keep = {value["path"] for component in current.values() for value in component.values() if value.get("path")}
  for component in old.values():
    for backup in component.values():
      path = backup.get("path")
      if path and path not in keep:
        try:
          candidate = Path(path)
          if candidate.resolve().parent.parent != machine.private_state_root / "backups":
            raise TermcfgError(4, "backup_outside_private_root")
          info = candidate.lstat()
          if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise TermcfgError(4, "unsafe_backup")
          candidate.unlink()
          candidate.parent.rmdir()
        except (FileNotFoundError, OSError):
          pass


def _check_approvals(preview: Preview, *, adopted: set[str], confirm_zshenv: str | None) -> None:
  for item in preview.targets:
    if item.action in {"blocked", "conflict"}:
      raise TermcfgError(4, item.reason or "target_conflict", "./termcfg plan")
    if item.action == "adopt-required" and item.artifact.id not in adopted:
      raise TermcfgError(4, "adoption_required", "./termcfg plan")
    if item.custom_zshenv and confirm_zshenv != preview.plan_id:
      raise TermcfgError(4, "zshenv_confirmation_required", "./termcfg plan")
  unknown = adopted - {item.artifact.id for item in preview.targets if item.action == "adopt-required"}
  if unknown:
    raise TermcfgError(2, "invalid_adoption_target")


def _commit_apply(machine: MachineSelection, preview: Preview, progress: Progress) -> dict:
  changes = [item for item in preview.targets if item.action != "unchanged"]
  if not changes:
    return {"changed": [], "unchanged": [item.artifact.id for item in preview.targets],
            "pending_core_effect": preview.state["pending_core_effect"],
            "pending_config_effect": preview.state["pending_config_effect"]}
  private_dir(machine.private_state_root)
  journal = _journal_items(machine, preview, changes)
  transaction_id = journal["transaction_id"]
  backups_dir = machine.private_state_root / "backups" / transaction_id
  private_dir(backups_dir)
  _write_journal(machine, journal)
  try:
    to_backup = [item for item in preview.targets if item.before.kind != "absent"]
    records = {record["target_id"]: record for record in journal["items"]}
    progress.stage("backup", item=f"0/{len(to_backup)}")
    for index, item in enumerate(to_backup, 1):
      progress.stage("backup", component=item.artifact.component, item=f"{index}/{len(to_backup)} {item.artifact.id}")
      with _target_context(item.artifact.component, item.artifact.id, "backup"):
        if _identity_with_digest(machine, item) != item.before.as_dict():
          raise TermcfgError(4, "target_changed_before_backup", "./termcfg plan")
        backup = _backup_one(machine, item, backups_dir)
        record = records.get(item.artifact.id)
        if record is not None:
          record["backup"] = backup
          prior = preview.state["targets"].get(item.artifact.id)
          backup["managed_before"] = prior is not None
          backup["prior_source_digest"] = prior["source_digest"] if prior else None
          _write_journal(machine, journal)
    for item in changes:
      if item.before.kind == "absent":
        record = records[item.artifact.id]
        record["backup"] = {"before": item.before.as_dict(), "path": None,
                            "digest": None, "managed_before": False,
                            "prior_source_digest": None}
        _write_journal(machine, journal)
    journal["phase"] = "backed_up"
    _write_journal(machine, journal)
  except Exception:
    # 尚未开始 HOME 写入；状态和上一版备份指针保持原样。
    journal_file(machine).unlink(missing_ok=True)
    shutil.rmtree(backups_dir, ignore_errors=True)
    raise
  journal["phase"] = "writing"
  _write_journal(machine, journal)
  new_state = json.loads(json.dumps(preview.state))
  changed_components = set()
  try:
    for index, (item, record) in enumerate(zip(changes, journal["items"], strict=True), 1):
      progress.stage("write", component=item.artifact.component, item=f"{index}/{len(changes)} {item.artifact.id}")
      with _target_context(item.artifact.component, item.artifact.id, "write"):
        if _identity_with_digest(machine, item) != item.before.as_dict():
          raise TermcfgError(4, "target_changed_during_write", "./termcfg recover")
        def record_intent(identity):
          record["intended_after"] = identity
          _write_journal(machine, journal)
        atomic_target_bytes(machine.target_home, item.artifact.destination, item.artifact.bytes(),
                            item.artifact.mode, before_replace=record_intent, expected=item.before.as_dict())
        record["after"] = _identity_with_digest(machine, item)
        if record["after"].get("digest") != item.artifact.sha256 or record["after"].get("mode") != item.artifact.mode:
          raise TermcfgError(6, "write_verify_failed", "./termcfg recover")
        record["stage"] = "verified"
        _write_journal(machine, journal)
        new_state["targets"][item.artifact.id] = {"component": item.artifact.component,
                                                   "after": record["after"],
                                                   "source_digest": item.artifact.sha256}
        changed_components.add(item.artifact.component)
    progress.stage("verify")
    old_previous = new_state["previous"]
    new_previous = json.loads(json.dumps(old_previous))
    for component in changed_components:
      new_previous[component] = {record["target_id"]: record["backup"] for record in journal["items"] if record["component"] == component}
    new_state["previous"] = new_previous
    if "mihomo" in changed_components:
      new_state["pending_config_effect"] = True
      new_state["public_config_identity"] = hashlib.sha256("".join(item.artifact.sha256 for item in preview.targets if item.artifact.component == "mihomo").encode()).hexdigest()
    progress.stage("commit")
    write_json(state_file(machine), new_state)
    journal["phase"] = "committed"
    _write_journal(machine, journal)
    journal_file(machine).unlink()
  except Exception:
    if journal["phase"] != "committed":
      journal["phase"] = "recovery_pending"
      _write_journal(machine, journal)
    raise
  cleanup_pending = False
  try:
    _clean_old_backups(machine, old_previous, new_previous)
    for item in preview.targets:
      if item.action == "unchanged":
        (backups_dir / f"{item.artifact.id}.backup").unlink(missing_ok=True)
  except (OSError, TermcfgError):
    cleanup_pending = True
  return {"changed": [item.artifact.id for item in changes],
          "unchanged": [item.artifact.id for item in preview.targets if item.action == "unchanged"],
          "transaction_id": transaction_id,
          "cleanup_pending": cleanup_pending,
          "pending_core_effect": new_state["pending_core_effect"],
          "pending_config_effect": new_state["pending_config_effect"]}


def apply(machine: MachineSelection, components: tuple[str, ...], *, plan_id: str | None,
          adopted: set[str], confirm_zshenv: str | None,
          confirm=None) -> dict:
  """交互确认回调在机器锁内运行；写入前再持仓库共享锁复核。"""
  progress = Progress("apply")
  with operation_lease(machine.machine_id):
    require_current_machine(machine)
    progress.stage("validate")
    from .environment import inspect_environment
    environment = inspect_environment(machine, components)
    if any(not entry["ready"] for entry in environment.values()):
      if any("recovery_pending" in entry["required_blockers"] for entry in environment.values()):
        raise TermcfgError(4, "recovery_pending", "./termcfg recover")
      component = next(name for name, entry in environment.items() if not entry["ready"])
      target_id = next(iter(environment[component]["target_issues"]), None)
      raise TermcfgError(5, "required_environment_missing", "./termcfg doctor --strict",
                         component=component, target_id=target_id, stage="validate")
    preview = build_preview(machine, components)
    if plan_id is not None and plan_id != preview.plan_id:
      raise TermcfgError(2, "plan_id_mismatch", "./termcfg plan")
    if confirm is not None:
      adopted, confirm_zshenv = confirm(preview)
    elif plan_id is None:
      raise TermcfgError(2, "plan_id_required", "./termcfg plan")
    _check_approvals(preview, adopted=adopted, confirm_zshenv=confirm_zshenv)
    with repository_lease(REPO_ROOT, exclusive=False):
      current = build_preview(machine, components)
      if current.plan_id != preview.plan_id:
        raise TermcfgError(4, "snapshot_changed", "./termcfg plan")
      return _commit_apply(machine, current, progress)


def recover(machine: MachineSelection) -> dict:
  """只恢复仍匹配本事务写后字节或写前身份的目标。"""
  with operation_lease(machine.machine_id):
    require_current_machine(machine)
    journal = read_journal(machine)
    if journal is None:
      return {"recovered": False, "reason": "no_recovery_pending"}
    if set(journal) != {"version", "kind", "transaction_id", "phase", "plan_id", "state_before", "items"} or journal["kind"] not in {"apply", "rollback"}:
      raise TermcfgError(2, "invalid_journal")
    if journal["phase"] == "committed":
      journal_file(machine).unlink()
      return {"recovered": False, "reason": "already_committed"}
    # 先全部复核，再恢复任何目标。
    for record in journal["items"]:
      relative = Path(record["relative"])
      identity = _recovery_identity(machine, relative, record)
      current = inspect_target(machine.target_home, relative)
      if identity == record["before"]:
        continue
      if record["after"] is not None and identity == record["after"]:
        continue
      if record.get("intended_after") is not None and identity == record["intended_after"]:
        continue
      if record.get("recovery_intended") is not None and identity == record["recovery_intended"]:
        continue
      expected_restore = record.get("expected_restore")
      if expected_restore is not None:
        if expected_restore["kind"] == "absent" and current.kind == "absent":
          continue
      raise TermcfgError(4, "recovery_target_drift", "./termcfg status")
    journal["phase"] = "recovery_pending"
    _write_journal(machine, journal)
    restored_state = json.loads(json.dumps(journal["state_before"]))
    for record in reversed(journal["items"]):
      relative = Path(record["relative"])
      identity = _recovery_identity(machine, relative, record)
      if identity != record["before"] and identity != record.get("recovery_intended"):
        def record_recovery_intent(expected):
          record["recovery_intended"] = expected
          _write_journal(machine, journal)
        _restore_one(machine, relative, record["backup"], before_replace=record_recovery_intent,
                     expected=identity)
        record["stage"] = "recovered"
        _write_journal(machine, journal)
      if record["target_id"] in restored_state["targets"]:
        restored_identity = _recovery_identity(machine, relative, record)
        restored_state["targets"][record["target_id"]]["after"] = restored_identity
    write_json(state_file(machine), restored_state)
    journal_file(machine).unlink()
    return {"recovered": True, "transaction_id": journal["transaction_id"]}


def rollback_preview(machine: MachineSelection, component: str) -> dict:
  if journal_file(machine).exists():
    raise TermcfgError(4, "recovery_pending", "./termcfg recover")
  state = read_state(machine)
  previous = state["previous"].get(component)
  if not previous:
    raise TermcfgError(4, "no_previous_version", "./termcfg status")
  from .catalog import load_catalog
  catalog = {item.id: item for item in load_catalog()}
  targets = []
  for target_id, backup in previous.items():
    item = catalog.get(target_id)
    record = state["targets"].get(target_id)
    if item is None or item.component != component or record is None:
      raise TermcfgError(2, "invalid_backup_state")
    identity = _current_identity(machine, target_id, item.destination,
                                 (record["after"].get("digest"),))
    if identity != record["after"]:
      raise TermcfgError(4, "rollback_target_drift", "./termcfg status")
    _verified_backup(machine, backup)
    targets.append({"target_id": target_id, "relative": str(item.destination),
                    "current": identity, "restore_kind": backup["before"]["kind"],
                    "backup_digest": backup.get("digest")})
  snapshot = {"kind": "rollback", "component": component, "machine_id": machine.machine_id,
              "state": state, "targets": targets}
  plan_id = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
  return {"plan_id": plan_id, "component": component, "targets": targets,
          "overall_ready": True, "ready": True, "next_command": "./termcfg rollback --component " + component + " --plan-id " + plan_id}


def rollback(machine: MachineSelection, component: str, *, plan_id: str | None, confirm=None) -> dict:
  progress = Progress("rollback")
  with operation_lease(machine.machine_id):
    require_current_machine(machine)
    progress.stage("validate", component=component)
    plan = rollback_preview(machine, component)
    if plan_id is not None and plan_id != plan["plan_id"]:
      raise TermcfgError(2, "plan_id_mismatch", "./termcfg rollback --component " + component + " --plan-only")
    if confirm is not None:
      if not confirm(plan):
        raise TermcfgError(4, "confirmation_declined")
    elif plan_id is None:
      raise TermcfgError(2, "plan_id_required", "./termcfg rollback --component " + component + " --plan-only")
    state = read_state(machine)
    previous = state["previous"][component]
    transaction_id = uuid.uuid4().hex
    backup_dir = machine.private_state_root / "backups" / transaction_id
    private_dir(backup_dir)
    journal = {"version": 1, "kind": "rollback", "transaction_id": transaction_id,
               "phase": "prepared", "plan_id": plan["plan_id"], "state_before": state,
               "items": []}
    _write_journal(machine, journal)
    try:
      progress.stage("backup", component=component)
      for target in plan["targets"]:
        target_id = target["target_id"]
        current = target["current"]
        if _current_identity(machine, target_id, Path(target["relative"]),
                             (current.get("digest"),)) != current:
          raise TermcfgError(4, "rollback_target_drift", "./termcfg rollback --component " + component + " --plan-only")
        current_backup = {"before": current, "path": None, "digest": None,
                          "managed_before": True, "prior_source_digest": state["targets"][target_id]["source_digest"]}
        if current["kind"] == "file":
          data = read_regular(machine.target_home, Path(target["relative"]), inspect_target(machine.target_home, Path(target["relative"])))
          from .state import atomic_bytes
          path = backup_dir / f"{target_id}.backup"
          atomic_bytes(path, data)
          current_backup.update(path=str(path), digest=hashlib.sha256(data).hexdigest())
          _verified_backup(machine, current_backup)
        journal["items"].append({"target_id": target_id, "component": component,
                                 "relative": target["relative"], "before": current,
                                 "desired": previous[target_id].get("digest"),
                                 "expected_restore": previous[target_id]["before"],
                                 "mode": previous[target_id]["before"].get("mode"),
                                 "backup": current_backup, "intended_after": None, "after": None,
                                 "stage": "pending"})
        _write_journal(machine, journal)
      journal["phase"] = "backed_up"
      _write_journal(machine, journal)
    except Exception:
      journal_file(machine).unlink(missing_ok=True)
      shutil.rmtree(backup_dir, ignore_errors=True)
      raise
    journal["phase"] = "writing"
    _write_journal(machine, journal)
    new_state = json.loads(json.dumps(state))
    try:
      for record in journal["items"]:
        target_id = record["target_id"]
        relative = Path(record["relative"])
        identity = _current_identity(machine, target_id, relative,
                                     (record["before"].get("digest"),))
        if identity != record["before"]:
          raise TermcfgError(4, "rollback_target_drift", "./termcfg recover")
        progress.stage("write", component=component, item=target_id)
        old_backup = previous[target_id]
        def record_intent(expected):
          record["intended_after"] = expected
          _write_journal(machine, journal)
        _restore_one(machine, relative, old_backup, before_replace=record_intent,
                     expected=identity)
        restored = _current_identity(machine, target_id, relative,
                                     (old_backup["before"].get("digest"),))
        record["after"] = restored
        record["stage"] = "verified"
        _write_journal(machine, journal)
        if old_backup.get("managed_before"):
          new_state["targets"][target_id] = {"component": component, "after": restored,
                                              "source_digest": old_backup["prior_source_digest"]}
        else:
          new_state["targets"].pop(target_id, None)
      progress.stage("verify", component=component)
      new_state["previous"].pop(component)
      if component == "mihomo":
        new_state["pending_config_effect"] = True
      progress.stage("commit", component=component)
      write_json(state_file(machine), new_state)
      journal["phase"] = "committed"
      _write_journal(machine, journal)
      journal_file(machine).unlink()
    except Exception:
      if journal["phase"] != "committed":
        journal["phase"] = "recovery_pending"
        _write_journal(machine, journal)
      raise
    cleanup_pending = False
    try:
      _clean_old_backups(machine, {component: previous}, new_state["previous"])
      shutil.rmtree(backup_dir)
    except (OSError, TermcfgError):
      cleanup_pending = True
    return {"component": component, "restored": [item["target_id"] for item in plan["targets"]],
            "transaction_id": transaction_id, "cleanup_pending": cleanup_pending,
            "pending_config_effect": new_state["pending_config_effect"]}
