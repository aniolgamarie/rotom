"""显式退役旧代理所有权；只读写非秘密元数据，不接触代理文件。"""

import hashlib
import json
import os
from pathlib import Path
import tomllib
import stat

from .config import MachineSelection, encode_machine, machine_path, read_machine
from .errors import TermcfgError
from .lease import operation_lease
from .state import (atomic_bytes, journal_exists, private_dir, read_json, read_state,
                    state_file, write_json)


def _digest(data):
  return hashlib.sha256(data).hexdigest() if data is not None else None


def _json_bytes(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode()


def _contents(path):
  try:
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
  except FileNotFoundError:
    return None
  try:
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
      raise TermcfgError(4, "unsafe_private_file")
    with os.fdopen(fd, "rb", closefd=False) as stream:
      return stream.read()
  finally:
    os.close(fd)


def migrate(machine_id: str) -> dict:
  with operation_lease(machine_id):
    machine = read_machine(machine_id, legacy=True)
    if journal_exists(machine):
      from .state import read_journal
      read_journal(machine)
      raise TermcfgError(4, "recovery_pending", "./termcfg recover")
    marker_path = machine.private_state_root / "drop-mihomo-migration.json"
    marker = read_json(marker_path)
    if marker is None:
      state_existed = state_file(machine).exists() or state_file(machine).is_symlink()
      before = read_state(machine, legacy=True)
      state_raw = _contents(state_file(machine))
      after = {"version": 2, "machine_id": machine_id,
               "targets": {key: value for key, value in before["targets"].items()
                           if value["component"] != "mihomo"},
               "previous": {key: value for key, value in before["previous"].items()
                            if key != "mihomo"}}
      updated = MachineSelection(machine.machine_id, machine.target_home, machine.private_state_root,
                                 tuple(value for value in machine.components if value != "mihomo"))
      machine_raw = _contents(machine_path(machine_id))
      try:
        if (machine_raw is None or state_existed != (state_raw is not None) or
            MachineSelection.from_dict(tomllib.loads(machine_raw.decode()), expected_id=machine_id, legacy=True) != machine or
            (json.loads(state_raw) if state_raw is not None else before) != before):
          raise ValueError()
      except (ValueError, TypeError, TermcfgError) as exc:
        raise TermcfgError(4, "migration_metadata_drift") from exc
      # 归档仅保存严格读取后的元数据；TOML 注释和私人代理文件正文不进入归档。
      marker = {"version": 1, "machine_id": machine_id, "phase": "prepared",
                "machine_before": _digest(machine_raw),
                "machine_after": _digest(encode_machine(updated)),
                "machine_archive": encode_machine(machine).decode(),
                "machine_result": encode_machine(updated).decode(),
                "state_before": _digest(state_raw),
                "state_after": _digest(_json_bytes(after)) if state_raw is not None else None,
                "state_archive": before if state_raw is not None else None,
                "state_result": after if state_raw is not None else None}
      private_dir(machine.private_state_root)
      # 最后复核捕获的字节；非协作写入者仍须遵守运维排他约定。
      if (_digest(_contents(state_file(machine))) != marker["state_before"] or
          _digest(_contents(machine_path(machine_id))) != marker["machine_before"]):
        raise TermcfgError(4, "migration_metadata_drift")
      write_json(marker_path, marker)
    _validate_marker(marker, machine_id, machine)
    if marker["phase"] == "complete":
      # 完成后正常 apply 可以推进状态；再次迁移不回放归档。
      if "mihomo" in machine.components or read_state(machine, legacy=True)["version"] != 2:
        raise TermcfgError(4, "migration_metadata_drift")
      return {"migrated": False, "reason": "already_migrated", "next_command": "./termcfg plan"}
    current_machine = _contents(machine_path(machine_id))
    current_state = _contents(state_file(machine))
    if (_digest(current_machine) not in {marker["machine_before"], marker["machine_after"]} or
        _digest(current_state) not in {marker["state_before"], marker["state_after"]}):
      raise TermcfgError(4, "migration_metadata_drift", "./termcfg status")
    # 每次写入前再次 CAS；操作租约序列化本工具，外部修改不能静默丢弃。
    if _digest(current_state) != marker["state_after"]:
      if _digest(_contents(state_file(machine))) != marker["state_before"]:
        raise TermcfgError(4, "migration_metadata_drift")
      atomic_bytes(state_file(machine), _json_bytes(marker["state_result"]))
    if _digest(_contents(machine_path(machine_id))) not in {marker["machine_before"], marker["machine_after"]}:
      raise TermcfgError(4, "migration_metadata_drift")
    if _digest(current_machine) != marker["machine_after"]:
      atomic_bytes(machine_path(machine_id), marker["machine_result"].encode())
    if (_digest(_contents(state_file(machine))) != marker["state_after"] or
        _digest(_contents(machine_path(machine_id))) != marker["machine_after"]):
      raise TermcfgError(4, "migration_metadata_drift")
    marker["phase"] = "complete"
    write_json(marker_path, marker)
    return {"migrated": True, "next_command": "./termcfg plan"}


def _validate_marker(marker, machine_id, machine):
  fields = {"version", "machine_id", "phase", "machine_before", "machine_after",
            "machine_archive", "machine_result", "state_before", "state_after",
            "state_archive", "state_result"}
  try:
    from jsonschema import Draft202012Validator
    from .catalog import REPO_ROOT
    if set(marker) != fields or marker["version"] != 1 or marker["machine_id"] != machine_id or marker["phase"] not in {"prepared", "complete"}:
      raise ValueError()
    machines = {}
    for key in ("machine_archive", "machine_result"):
      parsed = MachineSelection.from_dict(tomllib.loads(marker[key]), expected_id=machine_id,
                                          legacy=key == "machine_archive")
      machines[key] = parsed
      if parsed.target_home != machine.target_home or parsed.private_state_root != machine.private_state_root:
        raise ValueError()
    original = machines["machine_archive"]
    result = machines["machine_result"]
    if result.components != tuple(value for value in original.components if value != "mihomo"):
      raise ValueError()
    for key in ("machine_before", "machine_after", "state_before", "state_after"):
      digest = marker[key]
      if digest is not None and (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError()
    if marker["machine_after"] != _digest(marker["machine_result"].encode()):
      raise ValueError()
    for key in ("state_archive", "state_result"):
      value = marker[key]
      if value is not None:
        name = "legacy-state-v1.schema.json" if value.get("version") == 1 else "state.schema.json"
        schema = json.loads((REPO_ROOT / "schemas/termcfg" / name).read_text())
        Draft202012Validator(schema).validate(value)
        if value["machine_id"] != machine_id:
          raise ValueError()
    archive = marker["state_archive"]
    expected = ({"version": 2, "machine_id": machine_id,
                 "targets": {key: value for key, value in archive["targets"].items() if value["component"] != "mihomo"},
                 "previous": {key: value for key, value in archive["previous"].items() if key != "mihomo"}}
                if archive is not None else None)
    if marker["state_result"] != expected or (marker["state_before"] is None) != (archive is None):
      raise ValueError()
    if archive is not None:
      for collection in archive["previous"].values():
        for backup in collection.values():
          if backup.get("path") is not None:
            candidate = Path(backup["path"])
            if not candidate.is_absolute() or candidate.resolve().parent.parent != machine.private_state_root / "backups":
              raise ValueError()
    if marker["state_after"] != (_digest(_json_bytes(marker["state_result"])) if marker["state_result"] is not None else None):
      raise ValueError()
  except Exception as exc:
    raise TermcfgError(2, "invalid_migration_marker") from exc
