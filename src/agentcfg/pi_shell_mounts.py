"""只读 Linux Shell 挂载计划；不构造 argv、执行挂载或证明后端已可用。

system_roots/mountinfo 是受信组装或测试接缝，不是模型输入或后端证明。
compile_mount_plan 返回时关闭 FD；pin_mount_plan 持有同一组核验后的源直到作用域退出。
持有 FD 不冻结目录树或普通文件内容，执行前仍须复核身份。
"""

from copy import deepcopy
from contextlib import contextmanager, ExitStack
import errno
import hashlib
import os
from pathlib import Path
import platform
import pwd
import re
import stat
import sys

from .activity import digest
from .paths import PathError, _absolute_directory
from .pi_shell_seccomp import compile_filter
from .pi_shell_sources import _directory_identity, pin_shell_sources
from .schema import ConfigError
from .storage import Conflict


MAX_MOUNTINFO = 4 * 1024 * 1024
MAX_DEPTH = 128
ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


def _invalid():
  raise ConfigError("pi-shell-mountinfo")


def _decode(value):
  result, index = [], 0
  while index < len(value):
    if value[index] != "\\":
      result.append(value[index]); index += 1
    else:
      code = value[index + 1:index + 4]
      if code not in ESCAPES: _invalid()
      result.append(ESCAPES[code]); index += 4
  return "".join(result)


def _mount_path(value):
  value = _decode(value)
  path = Path(value)
  if (not path.is_absolute() or str(path) != value or value.startswith("//")
      or ".." in path.parts or "\0" in value): _invalid()
  return value


def _writable_options(value):
  options = value.split(",")
  if (any(not option for option in options) or len(set(options)) != len(options)
      or len(set(options) & {"ro", "rw"}) != 1): _invalid()
  return "rw" in options


def parse_mountinfo(raw):
  """有界解析 mountinfo；仅读取 superblock 的 ro/rw 状态，丢弃 source 与其余选项。"""
  if type(raw) is not str or not raw or len(raw) > MAX_MOUNTINFO: _invalid()
  try:
    if len(raw.encode("utf-8")) > MAX_MOUNTINFO: _invalid()
  except UnicodeError: _invalid()
  if any(ord(char) < 32 and char != "\n" for char in raw): _invalid()
  rows, ids = [], set()
  lines = raw.split("\n")
  if lines[-1] == "": lines.pop()
  for line in lines:
    fields = line.split(" ")
    if any(not value for value in fields) or fields.count("-") != 1: _invalid()
    separator = fields.index("-")
    if separator < 6 or len(fields) != separator + 4: _invalid()
    if any(not re.fullmatch(r"[1-9][0-9]*", value) for value in fields[:2]): _invalid()
    if any(len(value) > 10 or int(value) > 2**32 - 1 for value in fields[:2]): _invalid()
    mount_id, parent_id = map(int, fields[:2])
    device_match = re.fullmatch(r"(0|[1-9][0-9]*):(0|[1-9][0-9]*)", fields[2])
    if not device_match: _invalid()
    if any(len(value) > 10 or int(value) > 2**32 - 1 for value in device_match.groups()): _invalid()
    device = tuple(map(int, device_match.groups()))
    root, point = _mount_path(fields[3]), _mount_path(fields[4])
    mount_writable = _writable_options(fields[5])
    super_writable = _writable_options(fields[separator + 3])
    optional = fields[6:separator]
    categories = set()
    for value in optional:
      if value == "unbindable": category = value
      else:
        match = re.fullmatch(r"(shared|master|propagate_from):([1-9][0-9]*)", value)
        if not match: _invalid()
        if len(match[2]) > 10 or int(match[2]) > 2**32 - 1: _invalid()
        category = match[1]
      if category in categories: _invalid()
      categories.add(category)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", fields[separator + 1]): _invalid()
    _decode(fields[separator + 2]); _decode(fields[separator + 3])
    if mount_id in ids: _invalid()
    ids.add(mount_id)
    rows.append({"mount_id": mount_id, "parent_id": parent_id, "device": list(device),
      "root": root, "mountpoint": point, "writable": mount_writable and super_writable})
  if not rows: _invalid()
  return sorted(rows, key=lambda row: (len(Path(row["mountpoint"]).parts), row["mountpoint"]))


def _snapshot(info):
  return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink,
    info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _mask_identity(info):
  # 整体遮罩目录的内部内容不可见；仍绑定目录身份、属主、类型和权限。
  stable = (info.st_dev, info.st_ino, info.st_uid, info.st_mode)
  return digest(stable if stat.S_ISDIR(info.st_mode) else _snapshot(info))


def _literal(value):
  if type(value) is not str or len(value) > 4096: raise ConfigError("pi-shell-mounts")
  path = Path(value)
  if (not path.is_absolute() or str(path) != value or value.startswith("//") or ".." in path.parts
      or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in value)):
    raise ConfigError("pi-shell-mounts")
  return path


def _scope(path):
  homes = [Path.home(), Path(pwd.getpwuid(os.geteuid()).pw_dir)]
  special = [Path(value) for value in ("/proc", "/dev", "/sys")]
  if (path in (Path("/"), Path("/tmp")) or any(home.is_relative_to(path) for home in homes)
      or any(path.is_relative_to(root) or root.is_relative_to(path) for root in special)):
    raise Conflict("SHELL_MOUNT_SCOPE")


@contextmanager
def _pin_plan(public, *, system_roots, mountinfo, max_entries):
  if sys.platform != "linux" or platform.machine() != "x86_64": raise ConfigError("pi-shell-mount-platform")
  if type(max_entries) is not int or not 1 <= max_entries <= 250000: raise ConfigError("pi-shell-mounts")
  if type(system_roots) not in (tuple, list): raise ConfigError("pi-shell-mounts")
  if mountinfo is None:
    with open("/proc/self/mountinfo", "rb") as stream: raw = stream.read(MAX_MOUNTINFO + 1)
    if len(raw) > MAX_MOUNTINFO: _invalid()
    mountinfo = raw.decode("utf-8")
  table = parse_mountinfo(mountinfo)
  def backing(path, fd=None):
    matches = [row for row in table if path.is_relative_to(Path(row["mountpoint"]))]
    if not matches: raise Conflict("SHELL_MOUNT_DEVICE")
    # 唯一深层记录也可能属于被祖先叠挂遮住的分支，不推测可见层。
    points = [value["mountpoint"] for value in matches]
    if len(points) != len(set(points)): raise Conflict("SHELL_MOUNT_AMBIGUOUS")
    depth = max(len(Path(value["mountpoint"]).parts) for value in matches)
    deepest = [value for value in matches if len(Path(value["mountpoint"]).parts) == depth]
    row = deepest[0]
    if fd is not None:
      device = os.fstat(fd).st_dev
      if list(row["device"]) != [os.major(device), os.minor(device)]: raise Conflict("SHELL_MOUNT_DEVICE")
    coordinate = Path(row["root"]) / path.relative_to(Path(row["mountpoint"]))
    return tuple(row["device"]), coordinate, row["writable"]
  def no_submount(path):
    if any(Path(row["mountpoint"]) != path and Path(row["mountpoint"]).is_relative_to(path) for row in table):
      raise Conflict("SHELL_MOUNT_SUBMOUNT")
  system_fds, system_links = [], []
  with pin_shell_sources(public) as pinned:
    try:
      physical = public["physical"]
      sources = [{**row, "kind": "directory", "role": "workspace"} for row in pinned["roots"]]
      real_systems, links = [], []
      for value in system_roots:
        path = _literal(value)
        _scope(path)
        with _absolute_directory(path.parent) as parent:
          info = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
          if stat.S_ISLNK(info.st_mode):
            links.append((path, _snapshot(info), os.readlink(path.name, dir_fd=parent)))
          elif stat.S_ISDIR(info.st_mode):
            with _absolute_directory(path) as fd:
              owned = os.dup(fd)
            opened_info = os.fstat(owned)
            system_fds.append((owned, (opened_info.st_dev, opened_info.st_ino)))
            real_systems.append(path)
            sources.append({"path": str(path), "fd": owned, "kind": "directory", "role": "system", "writable": False})
          else: raise Conflict("SHELL_MOUNT_SYSTEM")
      writes = [Path(row["path"]) for row in pinned["roots"] if row["writable"]]
      for path, info, target in links:
        resolved = (path.parent / target).resolve(strict=True)
        if not any(resolved.is_relative_to(root) for root in real_systems): raise Conflict("SHELL_MOUNT_SYSTEM_ALIAS")
        with _absolute_directory(resolved) as fd: target_identity = _directory_identity(os.fstat(fd))
        system_links.append((path, info, target, resolved, target_identity))
      aliases = [path for path, _, _ in links]
      if any(write.is_relative_to(root) or root.is_relative_to(write) for write in writes for root in [*real_systems, *aliases]):
        raise Conflict("SHELL_MOUNT_SYSTEM_WRITE")
      directories = {}
      home_coordinates = [backing(home)[:2] for home in (Path.home(), Path(pwd.getpwuid(os.geteuid()).pw_dir))]
      special_coordinates = [(*backing(Path(value))[:2], value != "/tmp") for value in ("/tmp", "/proc", "/dev", "/sys")]
      for source in sources:
        path = Path(source["path"])
        _scope(path); no_submount(path)
        device, coordinate, readonly = backing(path, source["fd"])
        if ".git" in coordinate.parts: raise Conflict("SHELL_MOUNT_GIT_ALIAS")
        if any(device == home_device and home.is_relative_to(coordinate) for home_device, home in home_coordinates):
          raise Conflict("SHELL_MOUNT_SCOPE")
        if any(device == special_device and (special.is_relative_to(coordinate)
            or descendants and coordinate.is_relative_to(special))
            for special_device, special, descendants in special_coordinates):
          raise Conflict("SHELL_MOUNT_SCOPE")
        writable = source["role"] == "workspace" and any(path.is_relative_to(write) for write in writes)
        if writable and not readonly: raise Conflict("SHELL_MOUNT_READONLY")
        old = directories.get(path)
        if old is not None:
          if old["role"] != source["role"]: raise Conflict("SHELL_MOUNT_SYSTEM_WRITE")
          continue
        directories[path] = {**source, "writable": writable, "device": device, "coordinate": coordinate,
          "identity": _directory_identity(os.fstat(source["fd"]))}
      system_coordinates = [(source["device"], source["coordinate"]) for source in directories.values() if source["role"] == "system"]
      if any(source["device"] == device and (source["coordinate"].is_relative_to(coordinate)
          or coordinate.is_relative_to(source["coordinate"])) for source in directories.values()
          if source["writable"] for device, coordinate in system_coordinates):
        raise Conflict("SHELL_MOUNT_SYSTEM_WRITE")
      exe = _literal(physical["executable_identity"]["path"])
      cwd = _literal(physical["cwd"])
      _scope(exe); _scope(cwd)
      exe_backing = backing(exe, pinned["executable_fd"])
      cwd_backing = backing(cwd, pinned["cwd_fd"])
      if any(".git" in coordinate[1].parts for coordinate in (exe_backing, cwd_backing)):
        raise Conflict("SHELL_MOUNT_GIT_ALIAS")
      def policy_coordinate(value):
        path = _literal(value)
        matching = [link for link in system_links if path.is_relative_to(link[0])]
        if matching:
          alias = max(matching, key=lambda link: len(link[0].parts))
          path = alias[3] / path.relative_to(alias[0])
        return backing(path)[:2]
      denials = [policy_coordinate(value) for value in physical["denied_paths"]]
      readonly_coordinates = [policy_coordinate(value) for value in physical["readonly_paths"]]
      if any(source["device"] == device and (source["coordinate"].is_relative_to(coordinate)
          or coordinate.is_relative_to(source["coordinate"])) for source in directories.values()
          if source["writable"] for device, coordinate in readonly_coordinates):
        raise Conflict("SHELL_MOUNT_READONLY")
      masks = {}
      def project_denial(device, coordinate):
        for target in (exe_backing, cwd_backing):
          if device == target[0] and target[1].is_relative_to(coordinate): raise Conflict("PERMISSION_DENIED")
        for path, source in directories.items():
          if device != source["device"]: continue
          if source["coordinate"].is_relative_to(coordinate): raise Conflict("PERMISSION_DENIED")
          if coordinate.is_relative_to(source["coordinate"]):
            masks[path / coordinate.relative_to(source["coordinate"])] = None
      for device, coordinate in denials: project_denial(device, coordinate)
      def masked(path):
        return any(path.is_relative_to(mask) for mask in masks)
      count = 0
      def inventory(fd, path, *, workspace, depth=0):
        nonlocal count
        if depth > MAX_DEPTH: raise Conflict("SHELL_MOUNT_INVENTORY_LIMIT")
        before = _snapshot(os.fstat(fd))
        with os.scandir(fd) as entries:
          names = []
          for entry in entries:
            count += 1
            if count > max_entries: raise Conflict("SHELL_MOUNT_INVENTORY_LIMIT")
            names.append(entry.name)
        for name in sorted(names):
          child = path / name
          info = os.stat(name, dir_fd=fd, follow_symlinks=False)
          if name == ".git":
            if stat.S_ISLNK(info.st_mode): raise Conflict("SHELL_MOUNT_GIT_ALIAS")
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)): raise Conflict("SHELL_MOUNT_OBJECT")
            device, coordinate, _ = backing(child)
            project_denial(device, coordinate)
          if masked(child): continue
          if stat.S_ISLNK(info.st_mode): continue
          if stat.S_ISDIR(info.st_mode):
            try:
              opened = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            except OSError as error:
              if workspace or error.errno not in (errno.EACCES, errno.EPERM): raise
              # 系统不可读子树不遍历：在所有可见物理别名上显式遮罩。
              device, coordinate, _ = backing(child)
              project_denial(device, coordinate)
              continue
            try:
              if _snapshot(os.fstat(opened)) != _snapshot(info): raise Conflict("ROOT_IDENTITY")
              inventory(opened, child, workspace=workspace, depth=depth + 1)
              if _snapshot(os.stat(name, dir_fd=fd, follow_symlinks=False)) != _snapshot(os.fstat(opened)):
                raise Conflict("ROOT_IDENTITY")
            finally: os.close(opened)
          elif not stat.S_ISREG(info.st_mode):
            if workspace: raise Conflict("SHELL_MOUNT_OBJECT")
            # 活动端点/设备不能用普通文件遮罩，拒绝暴露整个最近父目录。
            device, coordinate, _ = backing(path)
            project_denial(device, coordinate)
            break
          elif workspace and info.st_nlink != 1:
            raise Conflict("SHELL_MOUNT_OBJECT")
        if _snapshot(os.fstat(fd)) != before: raise Conflict("ROOT_IDENTITY")
      for path, source in sorted(directories.items(), key=lambda pair: (len(pair[0].parts), str(pair[0]))):
        inventory(source["fd"], path, workspace=source["role"] == "workspace")
      mask_rows = []
      parents = []
      for path in sorted(masks, key=lambda value: (len(value.parts), str(value))):
        if any(path.is_relative_to(parent) for parent in parents): continue
        root = max((root for root in directories if path.is_relative_to(root)), key=lambda value: len(value.parts))
        fd = os.dup(directories[root]["fd"])
        try:
          parts = path.relative_to(root).parts
          for name in parts[:-1]:
            opened = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
            os.close(fd); fd = opened
          info = os.stat(parts[-1], dir_fd=fd, follow_symlinks=False)
          if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)): raise Conflict("SHELL_MOUNT_MASK")
          mask_rows.append({"path": str(path), "kind": "directory" if stat.S_ISDIR(info.st_mode) else "file", "identity": _mask_identity(info)})
          parents.append(path)
        finally: os.close(fd)
      symlinks = []
      for path, expected, target, resolved, target_identity in system_links:
        with _absolute_directory(path.parent) as parent:
          if (_snapshot(os.stat(path.name, dir_fd=parent, follow_symlinks=False)) != expected
              or os.readlink(path.name, dir_fd=parent) != target): raise Conflict("ROOT_IDENTITY")
        if (path.parent / target).resolve(strict=True) != resolved: raise Conflict("ROOT_IDENTITY")
        with _absolute_directory(resolved) as current:
          if _directory_identity(os.fstat(current)) != target_identity: raise Conflict("ROOT_IDENTITY")
        symlinks.append({"path": str(path), "target": str(resolved)})
      for path, source in directories.items():
        with _absolute_directory(path) as current:
          if _directory_identity(os.fstat(current)) != source["identity"]: raise Conflict("ROOT_IDENTITY")
      mounts = [{key: source[key] for key in ("path", "kind", "identity", "writable", "role")}
        for _, source in sorted(directories.items(), key=lambda pair: (len(pair[0].parts), str(pair[0])))]
      mounts.append({"path": str(exe), "kind": "file", "identity": deepcopy(physical["executable_identity"]), "writable": False, "role": "executable"})
      plan = {"schema_version": 1, "platform": "linux-x86_64", "network": "deny", "mounts": mounts,
        "symlinks": sorted(symlinks, key=lambda row: row["path"]), "masks": mask_rows,
        "cwd": {"path": str(cwd), "identity": physical["cwd_identity"]},
        "seccomp_digest": hashlib.sha256(compile_filter("linux-x86_64")).hexdigest()}
      yield {"plan": plan, "source_fds": {
        **{str(path): source["fd"] for path, source in directories.items()}, str(exe): pinned["executable_fd"]}}
    finally:
      for fd, identity in reversed(system_fds):
        try:
          info = os.fstat(fd)
          if (info.st_dev, info.st_ino) == identity: os.close(fd)
        except OSError:
          pass


@contextmanager
def pin_mount_plan(public, *, system_roots=("/usr", "/bin", "/lib", "/lib64"), mountinfo=None, max_entries=250000):
  """在交接作用域内持有计划对应源FD；调用者异常不转换为配置错误。"""
  with ExitStack() as stack:
    try:
      pinned = stack.enter_context(_pin_plan(deepcopy(public), system_roots=system_roots,
        mountinfo=mountinfo, max_entries=max_entries))
    except (OSError, PathError, UnicodeError, ValueError, TypeError, KeyError, RuntimeError):
      raise ConfigError("pi-shell-mounts") from None
    yield pinned


def compile_mount_plan(public, *, system_roots=("/usr", "/bin", "/lib", "/lib64"), mountinfo=None, max_entries=250000):
  """从受信公开投影编译计划；失败不返回部分清单，不创建遮罩占位。"""
  with pin_mount_plan(public, system_roots=system_roots, mountinfo=mountinfo, max_entries=max_entries) as pinned:
    return deepcopy(pinned["plan"])
