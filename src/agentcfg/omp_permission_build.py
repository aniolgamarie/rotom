"""显式离线构建的纯文件准备；不调用全局 git、包管理器或宿主。"""

from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import tarfile

from .omp_permission_build_inputs import BuildInputUnavailable, _ordinary_path


PERMISSION_CORE_FILES = ("types.ts", "shell-analysis.ts", "policy.ts", "reviewer.ts", "controller.ts",
  "session-commands.ts", "audit.ts")


def permission_plugin_digest(repository):
  repository = Path(repository).absolute()
  root = _ordinary_path(repository / "agents/omp/packages/omp-permission-control", directory=True)
  entries = []
  try:
    for base, directories, files in os.walk(root, followlinks=False):
      for name in directories:
        _ordinary_path(Path(base) / name, directory=True)
      for name in files:
        path = _ordinary_path(Path(base) / name)
        with path.open("rb") as stream:
          checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        entries.append({"path": path.relative_to(repository).as_posix(),
          "target": "packages/omp-permission-control/" + path.relative_to(root).as_posix(),
          "sha256": checksum, "executable": bool(path.stat().st_mode & 0o111)})
    if not entries:
      raise BuildInputUnavailable("omp-build-plugin-missing")
    raw = (json.dumps(sorted(entries, key=lambda item: item["path"]), ensure_ascii=False,
      sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode()
    return hashlib.sha256(raw).hexdigest()
  except OSError:
    raise BuildInputUnavailable("omp-build-plugin-unreadable") from None


def stage_permission_core(plugin_root, source_root):
  """共享纯核心只复制固定源码；实例与执行能力由宿主持有，扩展入口不嵌入。"""
  plugin_root, source_root = Path(plugin_root), Path(source_root)
  target = source_root / "packages/coding-agent/src/permission-control/core"
  if plugin_root.is_symlink() or source_root.is_symlink():
    raise BuildInputUnavailable("omp-build-core-link")
  for root in (plugin_root, target):
    if any(parent.is_symlink() for parent in (root, *root.parents)):
      raise BuildInputUnavailable("omp-build-core-link")
  try:
    files = {}
    for name in PERMISSION_CORE_FILES:
      path = plugin_root / name
      if path.is_symlink() or not path.is_file() or (target / name).exists() or (target / name).is_symlink():
        raise BuildInputUnavailable("omp-build-core-input")
      files[name] = path.read_bytes()
    target.mkdir(parents=True, exist_ok=True)
    for name, value in files.items():
      with (target / name).open("xb") as stream:
        stream.write(value)
  except OSError:
    raise BuildInputUnavailable("omp-build-core-input") from None


def _relative(value):
  path = PurePosixPath(value)
  if not value or path.is_absolute() or ".." in path.parts or "\\" in value or "\0" in value:
    raise BuildInputUnavailable("omp-build-path-boundary")
  return path


def extract_inputs(archive, root, *, strip_root=None):
  """先审查所有成员；链接仅供 workspace 解析，不能成为写入目的地。"""
  root = Path(root).resolve(strict=True)
  try:
    with tarfile.open(archive, "r:*") as stream:
      members = stream.getmembers()
      names, links = set(), set()
      selected = []
      for member in members:
        path = _relative(member.name)
        if strip_root is not None:
          if not path.parts or path.parts[0] != strip_root:
            raise BuildInputUnavailable("omp-build-archive-root")
          if len(path.parts) == 1:
            continue
          member.name = PurePosixPath(*path.parts[1:]).as_posix()
          path = _relative(member.name)
        if member.name in names or not (member.isdir() or member.isfile() or member.issym() or member.islnk()):
          raise BuildInputUnavailable("omp-build-archive-member")
        if member.islnk():
          link = _relative(member.linkname)
          if strip_root is not None:
            if link.parts[0] != strip_root or len(link.parts) < 2:
              raise BuildInputUnavailable("omp-build-archive-root")
            member.linkname = PurePosixPath(*link.parts[1:]).as_posix()
        names.add(member.name)
        if member.issym():
          links.add(path)
        # data_filter 检查绝对路径、逃逸链接、特殊文件；提取时再检查一遍。
        tarfile.data_filter(member, root)
        selected.append(member)
      for member in selected:
        if any(parent in links for parent in PurePosixPath(member.name).parents):
          raise BuildInputUnavailable("omp-build-archive-link-parent")
      stream.extractall(root, members=selected, filter="data")
  except (OSError, ValueError, tarfile.TarError):
    raise BuildInputUnavailable("omp-build-archive-invalid") from None


def apply_patch_bytes(root, raw):
  """只接受精确统一 diff；无 fuzz/offset/命令执行，所有 hunk 通过后才写。"""
  root = Path(root).resolve(strict=True)
  lines = raw.splitlines(keepends=True)
  changed = {}
  i = 0
  try:
    while i < len(lines):
      if lines[i].startswith((b"diff --git ", b"index ", b"new file mode 100644")):
        i += 1
        continue
      if not lines[i].startswith(b"--- ") or i + 1 >= len(lines) or not lines[i + 1].startswith(b"+++ "):
        raise ValueError()
      old = lines[i][4:].strip().decode("utf-8")
      new = lines[i + 1][4:].strip().decode("utf-8")
      if not new.startswith("b/") or old not in ("/dev/null", "a/" + new[2:]):
        raise ValueError()
      name = _relative(new[2:])
      target = root / name
      if name in changed or target.is_symlink() or not target.resolve().is_relative_to(root):
        raise ValueError()
      for parent in target.parents:
        if parent == root: break
        if parent.is_symlink(): raise ValueError()
      if old == "/dev/null":
        if target.exists(): raise ValueError()
        original = []
      else:
        original = target.read_bytes().splitlines(keepends=True)
      output, cursor, hunks = [], 0, 0
      i += 2
      while i < len(lines) and lines[i].startswith(b"@@ "):
        match = re.match(rb"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", lines[i])
        if not match: raise ValueError()
        old_start, old_count, new_start, new_count = [int(value) if value is not None else 1 for value in match.groups()]
        start = old_start if old_count == 0 else old_start - 1
        if start < cursor or start > len(original): raise ValueError()
        output.extend(original[cursor:start])
        if len(output) != (new_start if new_count == 0 else new_start - 1): raise ValueError()
        cursor, removed, added = start, 0, 0
        i += 1
        while removed < old_count or added < new_count:
          line = lines[i]
          kind, body = line[:1], line[1:]
          if kind in (b" ", b"-"):
            if cursor >= len(original) or original[cursor] != body: raise ValueError()
            cursor += 1
            removed += 1
          if kind in (b" ", b"+"):
            output.append(body)
            added += 1
          if kind not in (b" ", b"-", b"+") or removed > old_count or added > new_count: raise ValueError()
          i += 1
        hunks += 1
      if not hunks: raise ValueError()
      output.extend(original[cursor:])
      changed[name] = b"".join(output)
    if not changed: raise ValueError()
  except (OSError, UnicodeError, ValueError, IndexError):
    raise BuildInputUnavailable("omp-build-patch-context") from None
  for name, value in changed.items():
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value)


def deny_network():
  """Linux x64 子进程继承 seccomp；只允许 AF_UNIX，拒绝网络 socket。"""
  import ctypes
  import platform
  import sys
  if sys.platform != "linux" or platform.machine() not in ("x86_64", "amd64"):
    raise BuildInputUnavailable("omp-build-offline-platform")
  class Instruction(ctypes.Structure):
    _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte), ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint)]
  class Program(ctypes.Structure):
    _fields_ = [("length", ctypes.c_ushort), ("instructions", ctypes.POINTER(Instruction))]
  # 拒绝其它 syscall ABI；socket(41) 只有本地 AF_UNIX(1) 可通过。
  instructions = (Instruction * 9)(
    Instruction(0x20, 0, 0, 4), Instruction(0x15, 1, 0, 0xc000003e),
    Instruction(0x06, 0, 0, 0x80000000), Instruction(0x20, 0, 0, 0),
    Instruction(0x15, 0, 3, 41), Instruction(0x20, 0, 0, 16),
    Instruction(0x15, 1, 0, 1), Instruction(0x06, 0, 0, 0x00050000 | 101),
    Instruction(0x06, 0, 0, 0x7fff0000))
  libc = ctypes.CDLL(None, use_errno=True)
  program = Program(len(instructions), instructions)
  if libc.prctl(38, 1, 0, 0, 0) != 0 or libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:
    raise BuildInputUnavailable("omp-build-offline-unavailable")
