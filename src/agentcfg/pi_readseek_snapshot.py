"""只向原生工具提供通过当前 FilePolicy 的文件副本，不挂载业务树或 Git 元数据。"""
import hashlib
import os
from pathlib import Path
import stat

from .activity import digest
from .paths import _absolute_directory, relative_path
from .pi_guarded_files import physical_inside
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


def export_snapshot(files, tool, source_root, snapshot_root, *, selected_paths=None, operation="read",
    max_files=10000, max_bytes=128 * 1024 * 1024, scan_relative="."):
  if (operation not in ("read", "search") or type(max_files) is not int or not 1 <= max_files <= 100000
      or type(max_bytes) is not int or not 1 <= max_bytes <= 1024 * 1024 * 1024):
    raise ConfigError("readseek-snapshot-limits")
  source = Path(source_root).resolve(strict=True)
  target = Path(snapshot_root).absolute()
  if physical_inside(target, source) or physical_inside(source, target): raise Conflict("READSEEK_SNAPSHOT_OVERLAP")
  files.policy.current()
  paths, skipped, seen = [], 0, set()
  if selected_paths is not None:
    if (not isinstance(selected_paths, list) or len(selected_paths) > max_files
        or any(not isinstance(name, str) for name in selected_paths)):
      raise ConfigError("readseek-snapshot-selection")
    paths = [relative_path(name).as_posix() for name in selected_paths]
    if len(set(paths)) != len(paths): raise ConfigError("readseek-snapshot-selection")
  else:
    def visit(fd, prefix):
      nonlocal skipped
      try: files.policy.authorize(tool, operation, str(source / prefix))
      except Conflict as error:
        if str(error) != "PERMISSION_DENIED": raise
        skipped += 1; return
      info = os.fstat(fd)
      key = (info.st_dev, info.st_ino)
      if key in seen: raise Conflict("READSEEK_DIRECTORY_CYCLE")
      seen.add(key)
      if len(seen) + len(paths) > max_files * 4 + 1000: raise Conflict("READSEEK_SNAPSHOT_LIMIT")
      for name in sorted(os.listdir(fd)):
        if name in (".git", ".readseek", "node_modules", "target"): continue
        path = name if not prefix else prefix + "/" + name
        relative_path(path)
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
          child = os.open(name, os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
          try: visit(child, path)
          finally: os.close(child)
        elif stat.S_ISREG(info.st_mode):
          paths.append(path)
          if len(paths) > max_files: raise Conflict("READSEEK_SNAPSHOT_LIMIT")
        else:
          skipped += 1
    prefix = "" if scan_relative == "." else relative_path(scan_relative).as_posix()
    with _absolute_directory(source / prefix) as descriptor: visit(descriptor, prefix)
  total, entries = 0, []
  with Tree(target, create=True) as output:
    if os.listdir(output.fd): raise Conflict("READSEEK_SNAPSHOT_NOT_EMPTY")
    for name in sorted(paths):
      try:
        body, modified = files.read_snapshot(tool, str(source / name), operation=operation)
      except Conflict as error:
        if str(error) != "PERMISSION_DENIED": raise
        skipped += 1; continue
      total += len(body)
      if total > max_bytes: raise Conflict("READSEEK_SNAPSHOT_LIMIT")
      output.write_new(name, body)
      with output.parent(name) as (fd, leaf):
        source_fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try: os.utime(source_fd, ns=(modified, modified))
        finally: os.close(source_fd)
      entries.append({"path": name, "size": len(body), "sha256": hashlib.sha256(body).hexdigest()})
  result = {"schema_version": 1, "source_root": str(source), "snapshot_root": str(target),
    "entries": entries, "total_bytes": total, "scope_complete": skipped == 0, "skipped": skipped}
  result["snapshot_digest"] = digest(result)
  return result


def verify_snapshot_source(files, tool, snapshot, *, operation="read"):
  """计算期间源文件变化会使写计划失效；不把旧副本当成当前业务文件。"""
  if operation not in ("read", "search"): raise ConfigError("readseek-snapshot-operation")
  closed(snapshot, ("schema_version", "source_root", "snapshot_root", "entries", "total_bytes", "scope_complete", "skipped", "snapshot_digest"))
  if snapshot["schema_version"] != 1 or not isinstance(snapshot["entries"], list): raise ConfigError("readseek-snapshot")
  if snapshot["snapshot_digest"] != digest({key: value for key, value in snapshot.items() if key != "snapshot_digest"}):
    raise Conflict("READSEEK_SNAPSHOT_IDENTITY")
  files.policy.current()
  root = Path(snapshot["source_root"])
  for row in snapshot["entries"]:
    closed(row, ("path", "size", "sha256"))
    path = root / relative_path(row["path"])
    body = files.read(tool, str(path), operation=operation)
    if len(body) != row["size"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
      raise Conflict("READSEEK_SOURCE_CHANGED")
