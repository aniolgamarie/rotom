"""固定 bubblewrap 源码准备；不下载、不编译、不执行，也不提取任意归档路径。"""

import hashlib
import io
import lzma
import os
from pathlib import Path
import stat
import tarfile

from .paths import relative_path
from .schema import ConfigError
from .storage import Tree


VERSION = "0.13.0"
ARCHIVE_SHA256 = "4734237473c0e5d695e4e9034a34e43b2dbf5164655bd13fa59ae376b2b7a765"
SOURCE_URL = "https://github.com/containers/bubblewrap/releases/download/v0.13.0/bubblewrap-0.13.0.tar.xz"
MAX_ARCHIVE = 2 * 1024 * 1024
MAX_REGULAR = 4 * 1024 * 1024
MAX_ENTRIES = 256


def source_entries(raw):
  """先验证固定摘要，再返回排序的普通文件；仅两个原版许可别名物化为文件。"""
  try:
    if type(raw) is not bytes or not raw or len(raw) > MAX_ARCHIVE or hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA256:
      raise ValueError()
    # 在tar解析PAX元数据前限制总展开量；不能让元数据绕过regular内容预算。
    limit = MAX_REGULAR + MAX_ENTRIES * 4096 + 10240
    decoder = lzma.LZMADecompressor(format=lzma.FORMAT_XZ, memlimit=64 * 1024 * 1024)
    unpacked = decoder.decompress(raw, max_length=limit + 1)
    if len(unpacked) > limit or not decoder.eof or decoder.unused_data:
      raise ValueError()
    prefix = "bubblewrap-" + VERSION
    records, files, aliases = {}, {}, []
    total, count = 0, 0
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as archive:
      for member in archive:
        count += 1
        if count > MAX_ENTRIES or member.mode & ~0o777 or member.issparse():
          raise ValueError()
        name = member.name
        if name == prefix:
          if member.type != tarfile.DIRTYPE or "" in records:
            raise ValueError()
          records[""] = "directory"
          continue
        if not name.startswith(prefix + "/"):
          raise ValueError()
        name = name[len(prefix) + 1:]
        path = relative_path(name)
        if path.is_absolute() or name in records:
          raise ValueError()
        if any(records.get(parent.as_posix()) not in (None, "directory") for parent in path.parents if parent.as_posix() != "."):
          raise ValueError()
        kind = "directory" if member.type == tarfile.DIRTYPE else "file"
        if kind != "directory" and any(existing.startswith(name + "/") for existing in records):
          raise ValueError()
        records[name] = kind
        if member.type == tarfile.DIRTYPE:
          if member.size != 0: raise ValueError()
          continue
        if member.type == tarfile.SYMTYPE:
          if name not in ("COPYING.LIB", "LICENSE") or member.linkname != "COPYING" or member.size != 0:
            raise ValueError()
          aliases.append(name)
          continue
        if member.type not in (tarfile.REGTYPE, tarfile.AREGTYPE) or member.size < 0:
          raise ValueError()
        total += member.size
        if total > MAX_REGULAR:
          raise ValueError()
        stream = archive.extractfile(member)
        if stream is None: raise ValueError()
        with stream:
          data = stream.read(member.size + 1)
        if len(data) != member.size:
          raise ValueError()
        files[name] = (data, 0o755 if member.mode & 0o111 else 0o644)
    if not files:
      raise ValueError()
    if aliases:
      if "COPYING" not in files: raise ValueError()
      for name in aliases:
        files[name] = files["COPYING"]
    if sum(len(data) for data, _ in files.values()) > MAX_REGULAR:
      raise ValueError()
    return tuple((name, *files[name]) for name in sorted(files))
  except Exception:
    raise ConfigError("pi-bwrap-source-invalid") from None


def prepare_source(raw, target):
  """只向不存在或空的私人目录写新文件；失败保留现场，不覆盖或删除。"""
  entries = source_entries(raw)
  try:
    target = Path(target)
    if not target.is_absolute() or ".." in target.parts or target == Path("/"):
      raise ValueError()
    with Tree(target, create=True) as tree:
      if os.listdir(tree.fd):
        raise ValueError()
      for name, data, mode in entries:
        tree.write_new(name, data)
        if mode & 0o111:
          # Tree新建文件默认600；私人源码只保留执行位，不能恢复组/其他用户访问。
          with tree.parent(name) as (parent, leaf):
            before = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            try:
              opened = os.fstat(fd)
              if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or opened.st_uid != os.geteuid()
                  or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
                raise ValueError()
              os.fchmod(fd, 0o700)
              os.fsync(fd)
            finally:
              os.close(fd)
    return tuple(name for name, _, _ in entries)
  except Exception:
    raise ConfigError("pi-bwrap-source-target") from None
