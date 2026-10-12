"""公共工作区内容快照；只读自有目录，不加载 Worker 或委派控制器。"""

import hashlib
import os
from pathlib import Path
import stat

from .activity import digest
from .paths import relative_path
from .storage import Conflict, Tree


def snapshot(root, *, protected_roots=(), source_paths=None):
  """候选内容身份；只读目录句柄，不跟随软链接，也不读取 Git 管理目录。"""
  entries = []
  root = Path(root)
  protected = tuple(path for value in protected_roots if (path := Path(value).resolve(strict=False)) == root or root in path.parents)
  if source_paths is not None:
    with Tree(root, private=False) as tree:
      for name in sorted(set(source_paths)):
        path = relative_path(name)
        if ".git" in path.parts:
          raise Conflict("SNAPSHOT_SCOPE_INVALID")
        absolute = root / path
        if any(absolute == value or value in absolute.parents for value in protected):
          continue
        try:
          with tree.parent(name) as (parent, leaf):
            info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
              entries.append({"path": name, "kind": "symlink", "target": os.readlink(leaf, dir_fd=parent)})
              continue
          raw = tree.read(name)
          if raw is None:
            raise FileNotFoundError()
          entries.append({"path": name, "kind": "file", "sha256": hashlib.sha256(raw[0]).hexdigest(), "executable": raw[1] & 0o111})
        except FileNotFoundError:
          entries.append({"path": name, "kind": "missing"})
    return digest({"schema_version": 1, "files": entries})
  with Tree(Path(root), private=False) as tree:
    def visit(fd, prefix):
      for name in sorted(os.listdir(fd)):
        if name == ".git":
          continue
        relative = prefix + name
        absolute = root / relative
        if any(absolute == value or value in absolute.parents for value in protected):
          entries.append({"path": relative, "kind": "protected"})
          continue
        before = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(before.st_mode):
          child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
          try:
            opened = os.fstat(child)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
              raise Conflict("SNAPSHOT_CHANGED")
            visit(child, relative + "/")
          finally:
            os.close(child)
        elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
          file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
          try:
            opened = os.fstat(file)
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
              raise Conflict("SNAPSHOT_CHANGED")
            value = hashlib.sha256()
            while chunk := os.read(file, 1024 * 1024):
              value.update(chunk)
            after = os.fstat(file)
            if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
              raise Conflict("SNAPSHOT_CHANGED")
            entries.append({"path": relative, "kind": "file", "sha256": value.hexdigest(), "executable": before.st_mode & 0o111})
          finally:
            os.close(file)
        elif stat.S_ISLNK(before.st_mode):
          entries.append({"path": relative, "kind": "symlink", "target": os.readlink(name, dir_fd=fd)})
        else:
          raise Conflict("SNAPSHOT_UNSUPPORTED_FILE")
    if tree.fd is None:
      raise Conflict("ROOT_IDENTITY")
    visit(tree.fd, "")
  return digest({"schema_version": 1, "files": entries})
