"""本轮专用 Linux cgroup v1 cpuacct；不创建或删除管理员资源。"""
from contextlib import contextmanager
import ctypes
import errno
import json
import math
import hashlib
import os
from pathlib import PurePosixPath
import re
import stat
import time
import uuid


ROLES = ("server", "client", "producer", "driver")
CGROUP_SUPER_MAGIC = 0x27E0EB


class CpuacctError(Exception):
  def __init__(self, reason):
    self.reason = reason
    super().__init__(reason)


def _fail(reason):
  raise CpuacctError(reason)


def _statfs(fd):
  # statfs 的平台结构由足够大的缓冲区承接，只读取首个 long。
  buffer = ctypes.create_string_buffer(512)
  libc = ctypes.CDLL(None, use_errno=True)
  if libc.fstatfs(fd, ctypes.byref(buffer)) != 0:
    _fail("cpuacct_filesystem")
  return ctypes.c_long.from_buffer(buffer).value


def _absolute(value):
  return (isinstance(value, str) and value.startswith("/") and
    str(PurePosixPath(value)) == value and ".." not in PurePosixPath(value).parts)


def _open_dir(path):
  if not _absolute(path):
    _fail("cpuacct_path")
  fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  try:
    for part in PurePosixPath(path).parts[1:]:
      child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
      os.close(fd)
      fd = child
    return fd
  except BaseException:
    os.close(fd)
    raise


def _unique(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      _fail("cpuacct_receipt")
    result[key] = value
  return result


def _receipt(path):
  parent = _open_dir(str(PurePosixPath(path).parent))
  try:
    fd = os.open(PurePosixPath(path).name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
  finally:
    os.close(parent)
  try:
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
        info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
      _fail("cpuacct_receipt_permissions")
    raw = os.read(fd, 65537)
    if len(raw) > 65536:
      _fail("cpuacct_receipt")
    value = json.loads(raw, object_pairs_hook=_unique,
      parse_constant=lambda unused: _fail("cpuacct_receipt"))
  finally:
    os.close(fd)
  return _validate_receipt(value)


def _validate_receipt(value):
  fields = {"schema_version", "method", "uid", "boot_id", "source_cgroup", "scope_path", "scope_dev", "scope_ino", "roles", "admin_token"}
  if not isinstance(value, dict) or set(value) != fields:
    _fail("cpuacct_receipt")
  if (type(value["schema_version"]) is not int or value["schema_version"] != 1 or
      value["method"] != "cpuacct-v1" or type(value["uid"]) is not int or value["uid"] != os.getuid() or
      not _absolute(value["source_cgroup"]) or not _absolute(value["scope_path"]) or
      not isinstance(value["admin_token"], str) or not re.fullmatch("[0-9a-f]{32}", value["admin_token"]) or
      not isinstance(value["boot_id"], str)):
    _fail("cpuacct_receipt")
  try:
    if str(uuid.UUID(value["boot_id"])) != value["boot_id"]:
      _fail("cpuacct_receipt")
  except ValueError:
    _fail("cpuacct_receipt")
  if not isinstance(value["roles"], dict) or set(value["roles"]) != set(ROLES):
    _fail("cpuacct_receipt")
  identities = [{"dev": value["scope_dev"], "ino": value["scope_ino"]}]
  identities.extend(value["roles"].values())
  if any(not isinstance(item, dict) or set(item) != {"dev", "ino"} or
      any(type(item[key]) is not int or item[key] < 0 for key in ("dev", "ino")) for item in identities):
    _fail("cpuacct_receipt")
  return value


def _current():
  entries = []
  try:
    with open("/proc/self/cgroup", encoding="ascii") as stream:
      for line in stream:
        hierarchy, controllers, path = line.rstrip("\n").split(":", 2)
        if "cpuacct" in controllers.split(","):
          entries.append(path)
  except (OSError, ValueError, UnicodeError):
    raise CpuacctError("cpuacct_controller") from None
  if len(entries) != 1 or not _absolute(entries[0]):
    _fail("cpuacct_controller")
  return entries[0]


def _unescape(value):
  return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match[1], 8)), value)


def _mount(source):
  mounts = []
  for line in open("/proc/self/mountinfo", encoding="ascii"):
    before, after = line.rstrip("\n").split(" - ", 1)
    left, right = before.split(), after.split()
    if right[0] != "cgroup" or "cpuacct" not in right[2].split(","):
      continue
    root, mountpoint = _unescape(left[3]), _unescape(left[4])
    if not _absolute(root) or not _absolute(mountpoint):
      _fail("cpuacct_mount")
    if source == root or source.startswith(root.rstrip("/") + "/"):
      relative = source[len(root):].lstrip("/")
      mounts.append(mountpoint.rstrip("/") + ("/" + relative if relative else ""))
  if len(mounts) != 1:
    _fail("cpuacct_mount")
  return mounts[0]


def _boot_id():
  with open("/proc/sys/kernel/random/boot_id", encoding="ascii") as stream:
    return stream.read().strip()


def _single_thread():
  try:
    return len(os.listdir("/proc/self/task")) == 1
  except OSError:
    raise CpuacctError("cpuacct_threads") from None


def _member_identity(pid, group):
  try:
    def starttime():
      with open("/proc/" + str(pid) + "/stat", encoding="ascii") as stream:
        fields = stream.read().rsplit(")", 1)[1].split()
        return int(fields[19])
    start = starttime()
    with open("/proc/" + str(pid) + "/cgroup", encoding="ascii") as stream:
      paths = [line.rstrip("\n").split(":", 2)[2] for line in stream
        if "cpuacct" in line.split(":", 2)[1].split(",")]
    if paths != [group] or starttime() != start:
      _fail("cpuacct_member_identity")
    return {"pid": pid, "starttime": start}
  except (OSError, ValueError, IndexError):
    raise CpuacctError("cpuacct_member_identity") from None


class CpuacctGroups:
  def __init__(self, receipt_path, *, _producer=False):
    self._fds = []
    self._closed = False
    self._previous = None
    self._producer = _producer
    try:
      receipt = _receipt(os.fspath(receipt_path))
      self.receipt_digest = hashlib.sha256(json.dumps(receipt, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
      if receipt["boot_id"] != _boot_id():
        _fail("cpuacct_boot")
      self._source = receipt["source_cgroup"]
      self._group = self._source.rstrip("/") + "/rotom-bench-" + receipt["admin_token"]
      allowed = {self._group + "/server", self._group + "/producer"} if _producer else {self._source}
      if _current() not in allowed:
        _fail("cpuacct_source")
      source_path = _mount(self._source)
      expected = source_path.rstrip("/") + "/rotom-bench-" + receipt["admin_token"]
      if receipt["scope_path"] != expected:
        _fail("cpuacct_scope")
      self._parent = self._keep(_open_dir(source_path))
      if _statfs(self._parent) != CGROUP_SUPER_MAGIC:
        _fail("cpuacct_filesystem")
      self._name = "rotom-bench-" + receipt["admin_token"]
      self._scope = self._directory(self._parent, self._name, receipt["scope_dev"], receipt["scope_ino"])
      self._roles = {}
      for role in ROLES:
        identity = receipt["roles"][role]
        directory = self._directory(self._scope, role, identity["dev"], identity["ino"])
        files = {}
        for name in ("cgroup.procs", "cpuacct.usage_user", "cpuacct.usage_sys"):
          flags = os.O_RDWR if name == "cgroup.procs" else os.O_RDONLY
          fd = self._keep(os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory))
          info = os.fstat(fd)
          if not stat.S_ISREG(info.st_mode) or info.st_dev != identity["dev"] or _statfs(fd) != CGROUP_SUPER_MAGIC:
            _fail("cpuacct_file")
          if name == "cgroup.procs":
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
              _fail("cpuacct_file_permissions")
          elif info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o222:
            _fail("cpuacct_file_permissions")
          files[name] = fd
        self._roles[role] = (directory, files)
    except BaseException as error:
      self.close()
      if isinstance(error, (OSError, ValueError, TypeError, KeyError, UnicodeError)):
        raise CpuacctError("cpuacct_unavailable") from None
      raise

  def _keep(self, fd):
    self._fds.append(fd)
    return fd

  def _directory(self, parent, name, dev, ino):
    fd = self._keep(os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent))
    info = os.fstat(fd)
    if (info.st_dev, info.st_ino) != (dev, ino) or info.st_uid != 0 or info.st_mode & 0o022 or _statfs(fd) != CGROUP_SUPER_MAGIC:
      _fail("cpuacct_directory")
    return fd

  def _check(self):
    if self._closed:
      _fail("cpuacct_closed")
    try:
      if any(_statfs(fd) != CGROUP_SUPER_MAGIC for fd in self._fds):
        _fail("cpuacct_filesystem")
      entries = [(self._parent, self._name, self._scope)]
      entries.extend((self._scope, role, directory) for role, (directory, files) in self._roles.items())
      for parent, name, fd in entries:
        current, pinned = os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(fd)
        if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
          _fail("cpuacct_replaced")
      for directory, files in self._roles.values():
        for name, fd in files.items():
          current, pinned = os.stat(name, dir_fd=directory, follow_symlinks=False), os.fstat(fd)
          if (current.st_dev, current.st_ino) != (pinned.st_dev, pinned.st_ino):
            _fail("cpuacct_replaced")
      for fd in [self._scope] + [directory for directory, files in self._roles.values()]:
        info = os.fstat(fd)
        if info.st_uid != 0 or info.st_mode & 0o022:
          _fail("cpuacct_directory")
      for directory, files in self._roles.values():
        for name, fd in files.items():
          info = os.fstat(fd)
          if name == "cgroup.procs":
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
              _fail("cpuacct_file_permissions")
          elif info.st_uid != 0 or info.st_mode & 0o222:
            _fail("cpuacct_file_permissions")
    except OSError:
      raise CpuacctError("cpuacct_unavailable") from None

  def check_driver_descriptors(self):
    """离线复核只豁免本实例固定的内核句柄；不关闭或重新打开任何 FD。"""
    self._check()
    try:
      expected = [self._parent, self._scope]
      for role in ROLES:
        directory, files = self._roles[role]
        expected.append(directory)
        expected.extend(files[name] for name in ("cgroup.procs", "cpuacct.usage_user", "cpuacct.usage_sys"))
      if (len(self._fds) != 18 or len(set(self._fds)) != 18 or len(expected) != 18 or
          set(self._fds) != set(expected)):
        _fail("cpuacct_descriptor_registry")
      expected = set(expected)
      if any(os.get_inheritable(fd) for fd in expected):
        _fail("cpuacct_descriptor_inheritable")
      seen = set()
      for name in os.listdir("/proc/self/fd"):
        fd = int(name)
        try:
          os.fstat(fd)
        except OSError as error:
          if error.errno == errno.EBADF:
            continue
          raise
        if fd in expected:
          if fd in seen:
            _fail("cpuacct_descriptor_registry")
          seen.add(fd)
        elif fd > 2 or fd < 0:
          _fail("cpuacct_unknown_descriptor")
      if seen != expected:
        _fail("cpuacct_descriptor_missing")
    except (OSError, ValueError, TypeError, KeyError):
      raise CpuacctError("cpuacct_descriptor_audit") from None

  def read(self):
    self._check()
    result = {}
    try:
      for role, (directory, files) in self._roles.items():
        values = {}
        for field, name in (("user_ns", "cpuacct.usage_user"), ("system_ns", "cpuacct.usage_sys")):
          raw = os.pread(files[name], 129, 0)
          if len(raw) > 128 or not re.fullmatch(rb"[0-9]+\n?", raw):
            _fail("cpuacct_counter")
          values[field] = int(raw)
          if self._previous is not None and values[field] < self._previous[role][field]:
            _fail("cpuacct_counter_regressed")
        result[role] = values
    except OSError:
      raise CpuacctError("cpuacct_unavailable") from None
    self._previous = result
    return {role: dict(values) for role, values in result.items()}

  def _member_pids(self, role):
    """每次新建只读 open context，避免固定 cgroup.procs 句柄的成员缓存。"""
    self._check()
    if role not in ROLES:
      _fail("cpuacct_role")
    directory, files = self._roles[role]
    try:
      fd = os.open("cgroup.procs", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
      try:
        def checked():
          pinned = os.fstat(files["cgroup.procs"])
          fresh = os.fstat(fd)
          named = os.stat("cgroup.procs", dir_fd=directory, follow_symlinks=False)
          for info in (pinned, fresh, named):
            if (info.st_dev, info.st_ino) != (pinned.st_dev, pinned.st_ino):
              _fail("cpuacct_replaced")
            if not stat.S_ISREG(info.st_mode):
              _fail("cpuacct_members")
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
              _fail("cpuacct_file_permissions")
          if _statfs(fd) != CGROUP_SUPER_MAGIC:
            _fail("cpuacct_filesystem")
        checked()
        chunks, total = [], 0
        while True:
          chunk = os.read(fd, 131073 - total)
          if not chunk:
            break
          total += len(chunk)
          if total > 131072:
            _fail("cpuacct_members")
          chunks.append(chunk)
        self._check()
        checked()
        raw = b"".join(chunks)
        if len(raw) > 131072 or (raw and not re.fullmatch(rb"(?:[1-9][0-9]*\n)+", raw)):
          _fail("cpuacct_members")
        pids = [int(item) for item in raw.splitlines()]
        if len(pids) != len(set(pids)):
          _fail("cpuacct_members")
        return pids
      finally:
        os.close(fd)
    except (OSError, ValueError):
      raise CpuacctError("cpuacct_members") from None

  def members(self):
    """只读成员身份；不接受外部 PID，不把成员私密身份放入公开报告。"""
    return {role: [_member_identity(pid, self._group + "/" + role) for pid in self._member_pids(role)]
      for role in self._roles}

  def wait_case_empty(self, timeout=5):
    """已停止本轮 server 后只等三个子组为空，不查询退出成员的 proc 身份。"""
    if type(timeout) not in (int, float) or not 0 < timeout <= 5 or not math.isfinite(timeout):
      _fail("cpuacct_case_cleanup_timeout")
    deadline = time.monotonic() + timeout
    while True:
      if time.monotonic() > deadline:
        _fail("cpuacct_case_cleanup_timeout")
      empty = True
      for role in ("server", "client", "producer"):
        pids = self._member_pids(role)
        empty = empty and not pids
      now = time.monotonic()
      if now > deadline:
        _fail("cpuacct_case_cleanup_timeout")
      if empty:
        return
      if now >= deadline:
        _fail("cpuacct_case_cleanup_timeout")
      time.sleep(min(0.01, deadline - now))

  def join_self(self, role):
    self._check()
    if role not in ROLES:
      _fail("cpuacct_role")
    allowed = {self._source, self._group + "/driver"}
    if self._producer and role == "producer":
      allowed = {self._group + "/server", self._group + "/producer"}
    if _current() not in allowed:
      _fail("cpuacct_source")
    self._write(role)

  def _write(self, role):
    try:
      fd = self._roles[role][1]["cgroup.procs"]
      os.lseek(fd, 0, os.SEEK_SET)
      if os.write(fd, b"0") != 1:
        _fail("cpuacct_join")
    except OSError:
      raise CpuacctError("cpuacct_join") from None

  @contextmanager
  def spawn(self, role):
    if not _single_thread():
      _fail("cpuacct_threads")
    self.join_self(role)
    try:
      yield
    finally:
      # 目标组中等待 Popen 返回后，必须用同一个已固定 FD 恢复。
      self._write("driver")

  def close(self):
    for fd in reversed(self._fds):
      os.close(fd)
    self._fds.clear()
    self._closed = True

  def __enter__(self):
    return self

  def __exit__(self, *unused):
    self.close()


def join_producer(receipt_path):
  with CpuacctGroups(receipt_path, _producer=True) as groups:
    groups.join_self("producer")
    if _current() != groups._group + "/producer":
      _fail("cpuacct_source")
    return {"method": "cpuacct-v1", "role": "producer", "delegation_digest": groups.receipt_digest}
