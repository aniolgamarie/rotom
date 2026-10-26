"""严格的非秘密状态、同目录原子写入和私人备份目录。"""

import json
import os
from pathlib import Path
import stat
import tempfile

from jsonschema import Draft202012Validator

from .catalog import REPO_ROOT, _relative_path
from .config import MachineSelection
from .errors import TermcfgError
from .guidance import hint


def private_dir(path: Path) -> None:
  if path.exists() or path.is_symlink():
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
      raise TermcfgError(4, "unsafe_private_directory")
    return
  if not path.parent.exists():
    private_dir(path.parent)
  try:
    path.mkdir(mode=0o700)
    for directory in (path, path.parent):
      fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
      try:
        os.fsync(fd)
      finally:
        os.close(fd)
  except FileExistsError:
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
      raise TermcfgError(4, "unsafe_private_directory")


def state_file(machine: MachineSelection) -> Path:
  return machine.private_state_root / "state.json"


def journal_file(machine: MachineSelection) -> Path:
  return machine.private_state_root / "journal.json"


def journal_exists(machine: MachineSelection) -> bool:
  path = journal_file(machine)
  return path.exists() or path.is_symlink()


def require_no_pending_recovery(machine: MachineSelection) -> None:
  if journal_exists(machine):
    raise TermcfgError(4, "recovery_pending", hint("recover"))


def blank_state(machine: MachineSelection) -> dict:
  return {"version": 2, "machine_id": machine.machine_id, "targets": {}, "previous": {}}


def read_json(path: Path) -> dict | None:
  try:
    info = path.lstat()
  except FileNotFoundError:
    return None
  if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
    raise TermcfgError(4, "unsafe_private_file")
  try:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
      checked = os.fstat(fd)
      if (checked.st_dev, checked.st_ino) != (info.st_dev, info.st_ino):
        raise TermcfgError(4, "private_file_changed")
      with os.fdopen(fd, "r", encoding="utf-8", closefd=False) as stream:
        value = json.load(stream, object_pairs_hook=_strict_pairs,
          parse_constant=_invalid_number, parse_float=_invalid_number)
    finally:
      os.close(fd)
  except (OSError, ValueError) as exc:
    raise TermcfgError(2, "invalid_private_state") from exc
  if not isinstance(value, dict):
    raise TermcfgError(2, "invalid_private_state")
  return value


def _strict_pairs(pairs):
  value = {}
  for key, item in pairs:
    if key in value:
      raise ValueError("duplicate field")
    value[key] = item
  return value


def _invalid_number(value):
  raise ValueError("unsupported number")


def _validate_generated(machine, target_id, generated):
  if generated is None:
    return
  if target_id != "rotom-entry-binding":
    raise ValueError("generated target mismatch")
  if any(type(generated[key]) is not int or generated[key] != 1 for key in ("schema_version", "generator_version")):
    raise ValueError("generated version mismatch")
  if type(generated["payload"]["mode"]) is not int:
    raise ValueError("generated mode mismatch")
  relative = _relative_path(generated["payload"]["relative"])
  if str(relative) != generated["payload"]["relative"]:
    raise ValueError("generated path mismatch")


def read_state(machine: MachineSelection, *, legacy: bool = False) -> dict:
  if not legacy:
    marker = read_json(machine.private_state_root / "drop-mihomo-migration.json")
    if marker is not None:
      from .migration import _validate_marker
      _validate_marker(marker, machine.machine_id, machine)
      if marker["phase"] != "complete":
        raise TermcfgError(4, "migration_pending", hint("migrate", "--drop-mihomo"))
  value = read_json(state_file(machine))
  if value is None:
    return blank_state(machine)
  try:
    if type(value.get("version")) is not int or value["version"] not in (1, 2, 3):
      raise ValueError("unsupported version")
    schema = json.loads((REPO_ROOT / "schemas/termcfg" / ("legacy-state-v1.schema.json" if value.get("version") == 1 else "state.schema.json")).read_text())
    Draft202012Validator(schema).validate(value)
    for target_id, record in value["targets"].items():
      _validate_generated(machine, target_id, record.get("generated"))
    for backups in value["previous"].values():
      for target_id, backup in backups.items():
        _validate_generated(machine, target_id, backup.get("prior_generated"))
  except TermcfgError:
    raise
  except Exception as exc:
    raise TermcfgError(2, "invalid_private_state") from exc
  if value["version"] == 1 and not legacy:
    raise TermcfgError(4, "legacy_migration_required", hint("status"))
  if value["machine_id"] != machine.machine_id:
    raise TermcfgError(2, "state_machine_mismatch")
  backup_root = machine.private_state_root / "backups"
  for collection in value["previous"].values():
    for backup in collection.values():
      path_value = backup.get("path")
      if path_value is not None and (not Path(path_value).is_absolute() or
                                     Path(path_value).resolve().parent.parent != backup_root):
        raise TermcfgError(4, "backup_outside_private_root")
  return value


def read_journal(machine: MachineSelection) -> dict | None:
  value = read_json(journal_file(machine))
  if value is None:
    return None
  try:
    if type(value.get("version")) is not int or value["version"] not in (1, 2, 3):
      raise ValueError("unsupported version")
    schema = json.loads((REPO_ROOT / "schemas/termcfg" / ("legacy-state-v1.schema.json" if value.get("version") == 1 else "state.schema.json")).read_text())
    journal_schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/journal"}
    Draft202012Validator(journal_schema).validate(value)
    Draft202012Validator(schema).validate(value["state_before"])
    if type(value["state_before"].get("version")) is not int or value["state_before"]["version"] > value["version"]:
      raise ValueError("journal version mismatch")
    if value["state_before"]["machine_id"] != machine.machine_id:
      raise ValueError("machine mismatch")
    seen = set()
    backup_root = machine.private_state_root / "backups"
    for item in value["items"]:
      target_id = item["target_id"]
      relative = _relative_path(item["relative"])
      if (not isinstance(target_id, str) or not target_id or len(target_id) > 64 or
          any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_." for character in target_id) or
          target_id in seen or str(relative) != item["relative"]):
        raise ValueError("journal target mismatch")
      seen.add(target_id)
      _validate_generated(machine, target_id, item.get("generated"))
      if item.get("generated") is not None and (item["relative"] != ".local/share/rotom/entry.json" or
          item["component"] != "zsh" or item["generated"]["payload"]["sha256"] != item["desired"]):
        raise ValueError("generated journal mismatch")
      backup = item.get("backup")
      if backup and backup.get("path") is not None:
        candidate = Path(backup["path"])
        if not candidate.is_absolute() or candidate.resolve().parent.parent != backup_root:
          raise ValueError("journal backup outside private root")
    for collection in value["state_before"]["previous"].values():
      for backup in collection.values():
        if backup.get("path") is not None:
          candidate = Path(backup["path"])
          if not candidate.is_absolute() or candidate.resolve().parent.parent != backup_root:
            raise ValueError("journal state backup outside private root")
  except Exception as exc:
    raise TermcfgError(2, "invalid_transaction_journal") from exc
  return value


def atomic_bytes(path: Path, data: bytes, *, mode: int = 0o600) -> None:
  fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
  try:
    os.fchmod(fd, mode)
    with os.fdopen(fd, "wb") as stream:
      stream.write(data)
      stream.flush()
      os.fsync(stream.fileno())
    os.replace(name, path)
    directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
      os.fsync(directory_fd)
    finally:
      os.close(directory_fd)
  finally:
    if os.path.exists(name):
      os.unlink(name)


def write_json(path: Path, value: dict) -> None:
  private_dir(path.parent)
  atomic_bytes(path, (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode())
