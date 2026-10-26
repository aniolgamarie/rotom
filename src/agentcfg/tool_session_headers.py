"""Pi/OMP 受管会话头的有界只读投影；OMP 可含固定标题槽，不读取正文。"""

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time

from . import run_owners
from .dsh_sessions import scope_key
from .omp_identity import native_identity
from .paths import PathError, _open_directory
from .sessions import KnownSession, SessionError, SessionRef
from .storage import Conflict, Tree


_HEADER_LIMIT = 16384
_OMP_TITLE_SLOT_BYTES = 256
_SCAN_LIMIT = 4096
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass(frozen=True)
class HeaderTarget:
  known: KnownSession
  path: Path
  header_digest: str
  file_identity: tuple


def _scope(workspace):
  if workspace.agent == "pi":
    home = workspace.instance / "pi-home"
    return home / "sessions", "pi-home", home, 1
  if workspace.agent == "omp":
    identity = native_identity(workspace.profile, workspace.instance)
    return identity.agent_dir / "sessions", "omp-managed-home", identity.home, 2
  raise SessionError(2, "invalid_header_scope")


def _safe(info, *, directory=False):
  if (info.st_uid != os.geteuid() or info.st_mode & 0o022
      or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
      or not directory and info.st_nlink != 1):
    raise SessionError(4, "unsafe_session_path")


def _first_line(fd):
  # 不使用带缓冲的 readline，避免预读换行后的会话正文。
  line = bytearray()
  for _ in range(_HEADER_LIMIT + 1):
    byte = os.read(fd, 1)
    if not byte or byte == b"\n":
      return bytes(line), byte == b"\n"
    line.extend(byte)
  raise SessionError(5, "session_header_too_large")


def _decode_line(raw):
  try:
    return json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=run_owners._pairs,
      parse_constant=run_owners._invalid_constant)
  except (ValueError, UnicodeError, RecursionError):
    raise SessionError(5, "invalid_session_header") from None


def _read_header(fd, agent):
  raw, terminated = _first_line(fd)
  value = _decode_line(raw)
  if agent == "omp" and type(value) is dict and value.get("type") == "title":
    # 固定 OMP 版本的公开 serializeTitleSlot：恰为 256 UTF-8 字节（含 LF）。
    # 校验后才能跳一行；标题只用于识别物理前缀，不投影，也不绑定恢复身份。
    fields = {"type", "v", "title", "updatedAt", "pad"}
    if (not terminated or len(raw) + 1 != _OMP_TITLE_SLOT_BYTES
        or not raw.startswith(b"{") or not raw.endswith(b"}")
        or set(value) not in (fields, fields | {"source"})
        or type(value["v"]) is not int or value["v"] != 1
        or any(type(value[key]) is not str for key in ("title", "updatedAt", "pad"))
        or set(value["pad"]) - {" "}
        or "source" in value and value["source"] not in ("auto", "user")):
      raise SessionError(5, "invalid_session_title_slot")
    raw, _ = _first_line(fd)
    value = _decode_line(raw)
  return raw, value


def _header(tree, relative, workspace, kind, home):
  with tree.parent(str(relative)) as (parent, name):
    before = os.stat(name, dir_fd=parent, follow_symlinks=False)
    _safe(before)
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    try:
      opened = os.fstat(fd)
      _safe(opened)
      identity = (opened.st_dev, opened.st_ino)
      if identity != (before.st_dev, before.st_ino):
        raise SessionError(4, "session_header_changed")
      raw, value = _read_header(fd, workspace.agent)
      current = os.stat(name, dir_fd=parent, follow_symlinks=False)
      _safe(current)
      if identity != (current.st_dev, current.st_ino):
        raise SessionError(4, "session_header_changed")
    finally:
      os.close(fd)
  try:
    if (type(value) is not dict or value.get("type") != "session"
        or type(value.get("id")) is not str or _UUID.fullmatch(value["id"]) is None
        or type(value.get("timestamp")) is not str
        or "version" in value and (type(value["version"]) is not int or value["version"] <= 0)):
      raise ValueError()
    timestamp = datetime.fromisoformat(value["timestamp"].replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
      raise ValueError()
    cwd = run_owners._absolute(value["cwd"])
    if not cwd.is_dir():
      raise SessionError(5, "session_cwd_unavailable")
  except (KeyError, TypeError, ValueError, UnicodeError, RecursionError):
    raise SessionError(5, "invalid_session_header") from None
  known = KnownSession(SessionRef(workspace.agent, "managed", run_owners.native_home_key(
    {"kind": kind, "path": str(home)}), value["id"]), scope_key(workspace.binding),
    workspace.profile, str(cwd), "historical", "historical", time.time_ns(), None)
  return HeaderTarget(known, tree.root / relative, hashlib.sha256(raw).hexdigest(), identity)


def candidates(workspace):
  """只扫描固定原生目录：Pi 平铺，OMP 最多一层 cwd 桶；异常即停止。"""
  root, kind, home, depth = _scope(workspace)
  result, ids, count = [], set(), [0]
  try:
    # 先逐段核验受管祖先，即使根缺失也不能将悬空链接误判为没有会话。
    with Tree(workspace.instance, private=False) as instance:
      if instance.fd is None:
        return ()
      _safe(os.fstat(instance.fd), directory=True)
      try:
        with instance.parent(str(root.relative_to(workspace.instance) / "header-check")) as (fd, _):
          _safe(os.fstat(fd), directory=True)
      except FileNotFoundError:
        return ()
    with Tree(root, private=False) as tree:
      if tree.fd is None:
        return ()
      _safe(os.fstat(tree.fd), directory=True)

      def scan(fd, prefix, remaining):
        with os.scandir(fd) as entries:
          for entry in entries:
            count[0] += 1
            if count[0] > _SCAN_LIMIT:
              raise SessionError(5, "session_scan_limit")
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
              raise SessionError(4, "unsafe_session_path")
            relative = prefix / entry.name
            if stat.S_ISDIR(info.st_mode) and remaining > 1:
              _safe(info, directory=True)
              child = _open_directory(fd, entry.name)
              try:
                scan(child, relative, remaining - 1)
              finally:
                os.close(child)
            elif entry.name.endswith(".jsonl"):
              target = _header(tree, relative, workspace, kind, home)
              if target.known.ref.native_ref in ids:
                raise SessionError(4, "duplicate_session_id")
              ids.add(target.known.ref.native_ref)
              result.append(target)
      scan(tree.fd, Path(), depth)
    return tuple(sorted(result, key=lambda target: target.known.ref.native_ref))
  except (Conflict, PathError):
    raise SessionError(4, "unsafe_session_path") from None
  except OSError:
    raise SessionError(4, "session_header_unavailable") from None


def lookup(workspace, native_ref):
  """精确 UUID；不会接受路径、前缀或 latest。"""
  if type(native_ref) is not str or _UUID.fullmatch(native_ref) is None:
    raise SessionError(2, "invalid_session_id")
  matches = [target for target in candidates(workspace) if target.known.ref.native_ref == native_ref]
  if not matches:
    raise SessionError(5, "session_not_found")
  return matches[0]


def recheck(workspace, target):
  """复核 scope、文件身份和真实会话头；允许标题更新或正文追加，不推造加载证明。"""
  if type(target) is not HeaderTarget:
    raise SessionError(2, "invalid_header_target")
  current = lookup(workspace, target.known.ref.native_ref)
  if (current.path != target.path or current.file_identity != target.file_identity
      or current.header_digest != target.header_digest
      or current.known.ref != target.known.ref or current.known.scope != target.known.scope
      or current.known.profile != target.known.profile or current.known.cwd != target.known.cwd):
    raise SessionError(4, "session_header_changed")
  return current
