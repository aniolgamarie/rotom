"""固定原账户的服务索引只读观察；不提供初始化、写入或接管权限。"""

from dataclasses import dataclass
import os
import pwd
import stat
import sys

from .pi_durable_registration_record import DirectoryIdentity
from .pi_durable_service_index import ServiceIndexSnapshot, decode_service_index
from .storage import Conflict


# 测试只替换本模块别名，不改变全局系统模块。
_geteuid = os.geteuid
_getpwuid = pwd.getpwuid
_open = os.open
_stat = os.stat
_fstat = os.fstat
_read = os.read
_close = os.close
_PLATFORM = sys.platform
_PASSWD = pwd.struct_passwd
_STAT_RESULT = os.stat_result
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_CONTROL = ".agentcfg-pi-durable"
_FILE = "index.json"
_MAX_BYTES = 16 * 1024 * 1024
_U64 = 2**64 - 1


@dataclass(frozen=True, slots=True)
class ServiceIndexInspection:
  account_home: str
  account_identity: DirectoryIdentity
  state: str
  index_identity: DirectoryIdentity | None
  snapshot: ServiceIndexSnapshot | None

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False


def _invalid():
  raise ValueError("invalid service index inspection")


def _reject():
  error = Conflict("Durable服务索引无法安全读取")
  try:
    raise error
  except Conflict:
    error.__cause__ = None
    error.__context__ = None
    raise


def _integer(value, minimum, maximum):
  if type(value) is not int: _invalid()
  if not minimum <= value <= maximum: _invalid()
  return value


def _path(value):
  if type(value) is not str: _invalid()
  if not 1 <= len(value) <= 4096: _invalid()
  if (not value.startswith("/") or value == "/" or "\\" in value
      or any(part in ("", ".", "..") for part in value[1:].split("/"))): _invalid()
  if any(ord(char) < 32 or 0x7f <= ord(char) <= 0x9f or 0xd800 <= ord(char) <= 0xdfff for char in value): _invalid()
  if len(value.encode("utf-8")) > 4096: _invalid()
  return value


def _account(uid):
  entry = _getpwuid(uid)
  if type(entry) is not _PASSWD: _invalid()
  if _integer(entry.pw_uid, 0, 2**32 - 2) != uid: _invalid()
  return _path(entry.pw_dir)


def _metadata(info):
  if type(info) is not _STAT_RESULT: _invalid()
  values = (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
    info.st_size, info.st_mtime_ns, info.st_ctime_ns)
  for value in values:
    if type(value) is not int: _invalid()
  _integer(values[0], 0, _U64)
  _integer(values[1], 1, _U64)
  _integer(values[2], 0, 2**32 - 1)
  _integer(values[3], 0, 2**32 - 2)
  if values[4] < 1 or values[5] < 0: _invalid()
  return values


def _directory(info, uid, *, account=False, private=False):
  values = _metadata(info)
  if not stat.S_ISDIR(values[2]): _invalid()
  if account or private:
    if values[3] != uid or values[2] & 0o022: _invalid()
    if private and stat.S_IMODE(values[2]) != 0o700: _invalid()
  else:
    if values[3] not in (0, uid): _invalid()
    if values[2] & 0o022 and not values[2] & stat.S_ISVTX: _invalid()
  return values


def _directory_key(values):
  return values[0], values[1], values[3], values[2]


def _identity(values):
  return DirectoryIdentity(values[0], values[1], values[3])


def _file(info, uid):
  values = _metadata(info)
  if (not stat.S_ISREG(values[2]) or stat.S_IMODE(values[2]) != 0o600
      or values[3] != uid or values[4] != 1 or not 0 < values[5] <= _MAX_BYTES): _invalid()
  return values


class _Handles:
  """只登记本次新开fd；关闭前移除，失败不重试可能已复用的数字。"""
  __slots__ = ("fds",)

  def __init__(self):
    self.fds = []

  def open(self, name, flags, **kwargs):
    fd = _open(name, flags, **kwargs)
    if type(fd) is not int or fd < 0: _invalid()
    try:
      self.fds.append(fd)
    except Exception:
      # 原生open已成功但登记失败；此fd不在旧栈，单独尝试关闭一次。
      try:
        _close(fd)
      except Exception:
        pass
      raise
    return fd

  def close(self, fd):
    self.fds.remove(fd)
    _close(fd)

  def close_all(self):
    failed = False
    while self.fds:
      fd = self.fds.pop()
      try:
        _close(fd)
      except Exception:
        failed = True
    return failed


def _open_account(handles, home, uid):
  parent = handles.open("/", _DIRECTORY_FLAGS)
  _directory(_fstat(parent), uid)
  for name in home[1:].split("/"):
    before = _directory(_stat(name, dir_fd=parent, follow_symlinks=False), uid)
    child = handles.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    opened = _directory(_fstat(child), uid)
    if _directory_key(before) != _directory_key(opened): _invalid()
    handles.close(parent)
    parent = child
  values = _directory(_fstat(parent), uid, account=True)
  return parent, _identity(values)


def _first_stat(name, parent):
  # 仅固定basename的首次stat允许进入缺失分支。
  try:
    info = _stat(name, dir_fd=parent, follow_symlinks=False)
  except FileNotFoundError:
    return None
  if type(info) is not _STAT_RESULT: _invalid()
  return info


def _still_missing(name, parent):
  missing = False
  try:
    _stat(name, dir_fd=parent, follow_symlinks=False)
  except FileNotFoundError:
    missing = True
  if not missing: _invalid()


def _check_file(parent, source, original, uid):
  if _file(_fstat(source), uid) != original: _invalid()
  if _file(_stat(_FILE, dir_fd=parent, follow_symlinks=False), uid) != original: _invalid()


def _bytes(source):
  chunks = []
  total = 0
  while total <= _MAX_BYTES:
    amount = min(64 * 1024, _MAX_BYTES + 1 - total)
    chunk = _read(source, amount)
    if type(chunk) is not bytes or len(chunk) > amount: _invalid()
    if not chunk: return b"".join(chunks)
    total += len(chunk)
    if total > _MAX_BYTES: _invalid()
    chunks.append(chunk)
  _invalid()


def _inspect(handles):
  if type(_PLATFORM) is not str or _PLATFORM != "linux": _invalid()
  uid = _integer(_geteuid(), 0, 2**32 - 2)
  home = _account(uid)
  account, account_identity = _open_account(handles, home, uid)
  control_info = _first_stat(_CONTROL, account)
  control = None
  source = None
  index_identity = None
  snapshot = None
  state = "absent"
  if control_info is not None:
    original_control = _directory(control_info, uid, private=True)
    control = handles.open(_CONTROL, _DIRECTORY_FLAGS, dir_fd=account)
    opened = _directory(_fstat(control), uid, private=True)
    if _directory_key(opened) != _directory_key(original_control): _invalid()
    index_identity = _identity(opened)
    state = "incomplete"
    file_info = _first_stat(_FILE, control)
    if file_info is not None:
      original_file = _file(file_info, uid)
      source = handles.open(_FILE, _FILE_FLAGS, dir_fd=control)
      if _file(_fstat(source), uid) != original_file: _invalid()
      data = _bytes(source)
      if len(data) != original_file[5]: _invalid()
      _check_file(control, source, original_file, uid)
      snapshot = decode_service_index(data)
      if type(snapshot) is not ServiceIndexSnapshot: _invalid()
      _check_file(control, source, original_file, uid)
      if (snapshot.account_home != home or snapshot.account_identity != account_identity
          or snapshot.index_identity != index_identity): _invalid()
      state = "present"
  if _identity(_directory(_fstat(account), uid, account=True)) != account_identity: _invalid()
  reopened, current_account = _open_account(handles, home, uid)
  if current_account != account_identity: _invalid()
  handles.close(reopened)
  if control is None:
    _still_missing(_CONTROL, account)
  else:
    current = _directory(_stat(_CONTROL, dir_fd=account, follow_symlinks=False), uid, private=True)
    opened = _directory(_fstat(control), uid, private=True)
    if _directory_key(current) != _directory_key(opened) or _identity(opened) != index_identity: _invalid()
    if source is None:
      _still_missing(_FILE, control)
    else:
      _check_file(control, source, original_file, uid)
  if _account(uid) != home: _invalid()
  return ServiceIndexInspection(home, account_identity, state, index_identity, snapshot)


def inspect_service_index():
  handles = _Handles()
  failed = False
  try:
    result = _inspect(handles)
  except Exception:
    failed = True
  finally:
    if handles.close_all(): failed = True
  if failed: _reject()
  return result
