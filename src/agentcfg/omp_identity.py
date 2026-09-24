"""OMP 受管身份与物理实例租约。"""

from contextlib import contextmanager
from dataclasses import dataclass
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import stat

from .deployment import json_bytes
from .storage import Conflict, Tree, ensure_private


@dataclass(frozen=True)
class NativeIdentity:
  profile_id: str
  profile_hash: str
  native_name: str
  instance_root: Path
  home: Path
  agent_dir: Path
  xdg_config: Path
  xdg_data: Path
  xdg_cache: Path
  xdg_state: Path
  layout_version: int = 1


def native_identity(profile_id, instance_root):
  from .paths import PathError, safe_id
  safe_id(profile_id)
  if profile_id == "default" or profile_id.strip() != profile_id:
    raise PathError("OMP受管profile不得使用原生保留名或首尾空白")
  digest = hashlib.sha256(profile_id.encode("utf-8")).hexdigest()
  instance = Path(instance_root)
  home = instance / "user-home"
  name = "rotom-" + digest[:24]
  return NativeIdentity(profile_id, digest, name, instance, home,
    home / ".omp/profiles" / name / "agent", home / ".config", home / ".local/share", home / ".cache", home / ".local/state")


def ownership(workspace):
  identity = native_identity(workspace.profile, workspace.instance)
  return {"schema_version": 1, "identity": {"profile_id": identity.profile_id,
    "profile_sha256": identity.profile_hash, "native_name": identity.native_name,
    "instance_realpath": str(workspace.instance.absolute()), "home": str(identity.home),
    "agent_dir": str(identity.agent_dir), "xdg_config": str(identity.xdg_config),
    "xdg_data": str(identity.xdg_data), "xdg_cache": str(identity.xdg_cache),
    "xdg_state": str(identity.xdg_state), "layout_version": identity.layout_version},
    "machine_id": workspace.binding["machine"], "local_path": workspace.binding["local"],
    "state_realpath": str(workspace.state_root.absolute())}


def validate_layout(identity):
  """拒绝会让原生 profile 根从隔离 HOME 重定向的已存在布局。"""
  alternatives = (identity.xdg_config / "omp/profiles" / identity.native_name,
                  identity.xdg_data / "omp/profiles" / identity.native_name,
                  identity.xdg_cache / "omp/profiles" / identity.native_name,
                  identity.xdg_state / "omp/profiles" / identity.native_name)
  if any(path.exists() or path.is_symlink() for path in alternatives):
    raise Conflict("OMP检测到冲突的XDG profile目录")
  for path in (identity.instance_root, identity.home, identity.agent_dir):
    if path.is_symlink():
      raise Conflict("OMP身份目录不得为符号链接")


def _validate_saved_owner(raw, expected):
  try:
    saved = json.loads(raw[0])
    nonce = saved.pop("owner_nonce", None)
    if raw[1] != 0o600 or saved != expected or not isinstance(nonce, str) or len(nonce) != 32:
      raise ValueError()
  except Exception:
    raise Conflict("OMP实例已由其他管理身份占用") from None


def _preflight_existing_instance(workspace, expected):
  """在创建物理锁前拒绝未归属内容，避免失败接管留下任何痕迹。"""
  if not workspace.instance.exists() and not workspace.instance.is_symlink():
    return
  with Tree(workspace.instance) as tree:
    raw = tree.read(".agentcfg-omp-owner.json")
    entries = set(os.listdir(tree.fd))
    if raw is not None:
      _validate_saved_owner(raw, expected)
    elif entries - {".agentcfg-omp.lock"}:
      raise Conflict("OMP实例非空且没有可核验所有者")


@contextmanager
def lifecycle_guard(workspace, *, create=False):
  expected = ownership(workspace)
  if create:
    _preflight_existing_instance(workspace, expected)
    ensure_private(workspace.instance)
  elif not workspace.instance.exists() or workspace.instance.is_symlink():
    raise Conflict("OMP实例尚未由apply建立所有权")
  validate_layout(native_identity(workspace.profile, workspace.instance))
  lock_path = workspace.instance / ".agentcfg-omp.lock"
  flags = os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT if create else 0)
  try:
    fd = os.open(lock_path, flags, 0o600)
  except FileNotFoundError:
    raise Conflict("OMP实例尚未由apply建立所有权") from None
  except OSError:
    raise Conflict("OMP物理实例锁路径无效") from None
  try:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1):
      raise Conflict("OMP物理实例锁身份或权限无效")
    try:
      try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN):
          raise Conflict("OMP实例已有活动进程") from None
        raise Conflict("当前文件系统无法提供OMP物理实例锁") from None
      with Tree(workspace.instance) as tree:
        raw = tree.read(".agentcfg-omp-owner.json")
        if raw is not None:
          _validate_saved_owner(raw, expected)
        elif not create:
          raise Conflict("OMP实例尚未由apply建立所有权")
        else:
          if set(os.listdir(tree.fd)) != {".agentcfg-omp.lock"}:
            raise Conflict("OMP实例非空且没有可核验所有者")
          tree.write_state(".agentcfg-omp-owner.json", json_bytes({**expected, "owner_nonce": secrets.token_hex(16)}))
        yield fd
    finally:
      os.close(fd)
  except BaseException:
    if fd >= 0:
      try:
        os.close(fd)
      except OSError:
        pass
    raise
