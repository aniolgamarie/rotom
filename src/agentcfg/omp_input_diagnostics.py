"""仅提取 OMP 结构化阻塞事件和终端标志，不读取按键或输出日志原文。"""

import json
import os
import re
import stat
from collections import deque
from pathlib import Path

from .omp_identity import native_identity
from .storage import Conflict, Tree


_LOG_NAME = re.compile(r"^omp\.\d{4}-\d{2}-\d{2}\.\d+\.log(?:\.\d+)?$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,3})?[+-]\d{2}:\d{2}$")
_PHASES = frozenset({"layout", "paint", "render", "ui.select-filter", "unknown"})
_MAX_LOGS = 5
_MAX_BYTES = 1024 * 1024
_MAX_EVENTS = 20


def _event(line):
  if len(line) > 8192:
    return None
  try:
    row = json.loads(line)
  except (ValueError, UnicodeError):
    return None
  if not isinstance(row, dict) or row.get("message") != "ui.loop-blocked":
    return None
  blocked, cpu, pid = row.get("blockedMs"), row.get("cpuMs"), row.get("pid")
  if any(type(value) is not int or value < 0 or value > 1_000_000_000 for value in (blocked, cpu, pid)):
    return None
  timestamp = row.get("timestamp")
  phase = row.get("phase")
  return {"timestamp": timestamp if isinstance(timestamp, str) and _TIMESTAMP.fullmatch(timestamp) else None,
    "pid": pid, "blocked_ms": blocked, "cpu_ms": cpu,
    "phase": phase if isinstance(phase, str) and phase in _PHASES else "unknown"}


def _tail(tree, name):
  """固定目录与文件身份，按打开时大小有界读取；允许原生日志继续追加。"""
  with tree.parent(name) as (parent, entry):
    before = os.stat(entry, dir_fd=parent, follow_symlinks=False)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
        or before.st_nlink != 1 or before.st_mode & 0o022):
      raise Conflict("OMP日志文件不安全")
    fd = os.open(entry, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
    try:
      opened = os.fstat(fd)
      if (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_uid, opened.st_nlink) != (
          before.st_dev, before.st_ino, before.st_mode, before.st_uid, before.st_nlink):
        raise Conflict("OMP日志在打开时变化")
      offset = max(0, opened.st_size - _MAX_BYTES)
      starts_at_line = offset == 0 or os.pread(fd, 1, offset - 1) in (b"\n", b"\r")
      content = os.pread(fd, opened.st_size - offset, offset)
    finally:
      os.close(fd)
  lines = content.splitlines()
  return lines[1:] if not starts_at_line and lines else lines


def inspect(workspace):
  report = {"logs_present": False, "logs_checked": 0,
    "loop_blocks": [], "note": "Vim 输入状态由 OMP 状态栏显示；本报告不记录按键"}
  identity = native_identity(workspace.profile, workspace.instance)
  root = identity.agent_dir.parent / "logs"
  try:
    with Tree(root, private=False) as tree:
      if tree.fd is None:
        return report
      report["logs_present"] = True
      candidates = []
      for entry in os.scandir(tree.fd):
        if not _LOG_NAME.fullmatch(entry.name):
          continue
        try:
          if entry.is_file(follow_symlinks=False):
            candidates.append((entry.stat(follow_symlinks=False).st_mtime_ns, entry.name))
        except OSError:
          continue
      names = [name for _, name in sorted(candidates, reverse=True)[:_MAX_LOGS]]
      events = []
      for name in names:
        recent = deque(maxlen=_MAX_EVENTS)
        try:
          lines = _tail(tree, name)
        except (OSError, Conflict):
          report["logs_status"] = "some-logs-unavailable"
          continue
        for raw in lines:
          event = _event(raw)
          if event is not None:
            recent.append(event)
        report["logs_checked"] += 1
        events.extend(recent)
      report["loop_blocks"] = sorted(events, key=lambda row: row["timestamp"] or "")[-_MAX_EVENTS:]
  except (OSError, Conflict):
    report["logs_status"] = "unavailable-or-unsafe"
  return report
