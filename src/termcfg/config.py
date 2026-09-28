"""机器选择的严格读取与私人写入。"""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import tomllib

from .errors import TermcfgError


COMPONENTS = frozenset(("zsh", "tmux", "mihomo"))
MACHINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def xdg_path(name: str) -> Path:
  value = os.environ.get(name)
  default = {"XDG_CONFIG_HOME": ".config", "XDG_STATE_HOME": ".local/state", "XDG_DATA_HOME": ".local/share"}[name]
  return Path(value) if value else Path.home() / default


def machine_path(machine_id: str) -> Path:
  if not MACHINE_ID.fullmatch(machine_id):
    raise TermcfgError(2, "invalid_machine_id")
  return xdg_path("XDG_CONFIG_HOME") / "termcfg" / "machines" / f"{machine_id}.toml"


def _owned_directory(path: Path, *, private: bool = False) -> None:
  if not path.is_absolute() or path.is_symlink() or not path.is_dir():
    raise TermcfgError(2, "invalid_directory")
  info = path.stat()
  if info.st_uid != os.getuid() or (private and stat.S_IMODE(info.st_mode) != 0o700):
    raise TermcfgError(2, "unsafe_directory")


@dataclass(frozen=True)
class MachineSelection:
  machine_id: str
  target_home: Path
  private_state_root: Path
  components: tuple[str, ...]

  @classmethod
  def from_dict(cls, data: dict, *, expected_id: str | None = None):
    if set(data) != {"machine_id", "target_home", "private_state_root", "components"}:
      raise TermcfgError(2, "invalid_machine_fields")
    machine_id = data["machine_id"]
    if not isinstance(machine_id, str) or not MACHINE_ID.fullmatch(machine_id) or (expected_id and machine_id != expected_id):
      raise TermcfgError(2, "invalid_machine_id")
    values = data["components"]
    if (not isinstance(values, list) or any(not isinstance(v, str) for v in values) or
        len(set(values)) != len(values) or any(v not in COMPONENTS for v in values)):
      raise TermcfgError(2, "invalid_components")
    if not isinstance(data["target_home"], str) or not isinstance(data["private_state_root"], str):
      raise TermcfgError(2, "invalid_machine_path")
    home = Path(data["target_home"])
    private = Path(data["private_state_root"])
    if home != home.resolve() or private != private.resolve():
      raise TermcfgError(2, "noncanonical_machine_path")
    _owned_directory(home)
    if not private.is_absolute() or private.is_relative_to(Path(__file__).resolve().parents[2]) or private == home:
      raise TermcfgError(2, "invalid_private_state_root")
    if private.exists():
      _owned_directory(private, private=True)
    return cls(machine_id, home, private, tuple(values))


def read_machine(machine_id: str) -> MachineSelection:
  path = machine_path(machine_id)
  try:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
      raise TermcfgError(2, "unsafe_machine_file")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0))
    try:
      checked = os.fstat(fd)
      if (checked.st_dev, checked.st_ino) != (info.st_dev, info.st_ino):
        raise TermcfgError(4, "machine_file_changed")
      with os.fdopen(fd, "rb", closefd=False) as stream:
        value = tomllib.load(stream)
    finally:
      os.close(fd)
    return MachineSelection.from_dict(value, expected_id=machine_id)
  except FileNotFoundError as exc:
    raise TermcfgError(2, "machine_missing", "./termcfg init-local --component zsh") from exc
  except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
    raise TermcfgError(2, "invalid_machine_file") from exc


def require_current_machine(machine: MachineSelection) -> None:
  if read_machine(machine.machine_id) != machine:
    raise TermcfgError(4, "machine_selection_changed", "./termcfg status")


def encode_machine(machine: MachineSelection) -> bytes:
  components = ", ".join(json.dumps(value) for value in machine.components)
  return (f'machine_id = {json.dumps(machine.machine_id)}\n'
          f'target_home = {json.dumps(str(machine.target_home))}\n'
          f'private_state_root = {json.dumps(str(machine.private_state_root))}\n'
          f'components = [{components}]\n').encode()
