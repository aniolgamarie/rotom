"""公开依赖锁的目录租约与小型可恢复发布；日志仅保存白名单锁文件。"""

import base64
from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path

from .deployment import json_bytes
from .storage import Conflict, Tree, ensure_private


FILES = {
  "dsh": frozenset(("package.json", "package-lock.json", "pnpm-lock.yaml", "manifest.json")),
  "omp": frozenset(("manifest.json", "upstream/bun.lock", "upstream/LICENSE",
                    "upstream/THIRD-PARTY-NOTICES.txt", "upstream/provenance.json", "upstream/NOTICE.md")),
  "pi": frozenset(("manifest.json", "pi-base/package.json", "pi-base/package-lock.json",
                   "pi-pro/package.json", "pi-pro/package-lock.json")),
}


def _digest(data):
  return hashlib.sha256(data).hexdigest() if data is not None else None


def _journal_root(repository, adapter):
  return Path(repository) / ".cache/agentcfg-publication" / adapter


def _adapter(adapter):
  if adapter not in FILES:
    raise Conflict("不支持的依赖锁发布类型")


def _pending(repository, adapter):
  with Tree(_journal_root(repository, adapter)) as journal:
    raw = journal.read("pending.json", max_bytes=64 * 1024 * 1024)
    if raw is not None and raw[1] != 0o600:
      raise Conflict("依赖锁发布日志权限无效")
    return raw


@contextmanager
def _lease(repository, adapter, *, exclusive, create=False):
  _adapter(adapter)
  repository = Path(repository)
  if create:
    with Tree(repository, private=False) as checkout:
      with checkout.parent(f"locks/{adapter}/.publication-probe", create=True):
        pass
  with Tree(repository / "locks" / adapter, private=False) as tree:
    if tree.fd is None:
      raise FileNotFoundError()
    try:
      fcntl.flock(tree.fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
    except OSError as exc:
      if exc.errno in (errno.EAGAIN, errno.EACCES):
        raise Conflict("依赖锁正在被读取或发布；稍后重试") from None
      raise
    try:
      yield tree
    finally:
      fcntl.flock(tree.fd, fcntl.LOCK_UN)


@contextmanager
def reader_lease(repository, adapter):
  """调用方可将租约保持至完整消费结束；不创建私人日志容器。"""
  with _lease(repository, adapter, exclusive=False) as tree:
    if _pending(repository, adapter) is not None:
      raise Conflict("依赖锁发布待恢复；请显式重新执行 lock")
    yield tree


def _decode_journal(raw, adapter):
  try:
    value = json.loads(raw)
    if (set(value) != {"version", "adapter", "files"} or type(value["version"]) is not int or
        value["version"] != 1 or value["adapter"] != adapter or not isinstance(value["files"], list) or
        not value["files"] or len(value["files"]) > len(FILES[adapter])):
      raise ValueError()
    seen = set()
    for item in value["files"]:
      if set(item) != {"path", "before", "before_mode", "after", "after_mode"}:
        raise ValueError()
      if item["path"] not in FILES[adapter] or item["path"] in seen:
        raise ValueError()
      seen.add(item["path"])
      if item["before"] is not None:
        if not isinstance(item["before"], str):
          raise ValueError()
        base64.b64decode(item["before"], validate=True)
        if type(item["before_mode"]) is not int or not 0 <= item["before_mode"] <= 0o777:
          raise ValueError()
      elif item["before_mode"] is not None:
        raise ValueError()
      if item["after"] is not None:
        if not isinstance(item["after"], str) or len(item["after"]) != 64 or any(c not in "0123456789abcdef" for c in item["after"]):
          raise ValueError()
        if type(item["after_mode"]) is not int or not 0 <= item["after_mode"] <= 0o777:
          raise ValueError()
      elif item["after_mode"] is not None:
        raise ValueError()
    if "manifest.json" not in seen or value["files"][-1]["path"] != "manifest.json":
      raise ValueError()
    return value
  except (ValueError, TypeError, KeyError):
    raise Conflict("依赖锁发布日志无效；拒绝恢复未知文件") from None


def _restore(tree, journal, value, pending):
  # 先检查所有目标，避免发现外部漂移前已经回滚其他文件。
  snapshots = {}
  for item in value["files"]:
    current = tree.read(item["path"])
    before = base64.b64decode(item["before"]) if item["before"] is not None else None
    observed = (_digest(current[0]), current[1]) if current else (None, None)
    if observed not in {(_digest(before), item["before_mode"]), (item["after"], item["after_mode"])}:
      raise Conflict("依赖锁发布目标发生外部漂移；保留日志，拒绝覆盖")
    snapshots[item["path"]] = current
  for item in reversed(value["files"]):
    current = snapshots[item["path"]]
    before = base64.b64decode(item["before"]) if item["before"] is not None else None
    if ((current[0] if current else None), (current[1] if current else None)) == (before, item["before_mode"]):
      continue
    tree.replace(item["path"], before, item["before_mode"] if item["before_mode"] is not None else 0o600,
                 expected=current[2] if current else None)
  journal.replace("pending.json", None, expected=pending[2])


class Publisher:
  def __init__(self, repository, adapter, tree):
    self.repository = Path(repository)
    self.adapter = adapter
    self.tree = tree

  def recover(self):
    with Tree(_journal_root(self.repository, self.adapter)) as journal:
      pending = journal.read("pending.json", max_bytes=64 * 1024 * 1024)
      if pending is None:
        return
      if pending[1] != 0o600:
        raise Conflict("依赖锁发布日志权限无效")
      _restore(self.tree, journal, _decode_journal(pending[0], self.adapter), pending)

  def publish(self, files, *, validate):
    """files 只接受白名单公开锁文件；最后写 manifest，验证成功后清除日志。"""
    if (not isinstance(files, dict) or not files or set(files) - FILES[self.adapter] or
        "manifest.json" not in files or any(value is not None and not isinstance(value, bytes) for value in files.values())):
      raise Conflict("依赖锁发布文件集合无效")
    names = sorted(set(files) - {"manifest.json"}) + ["manifest.json"]
    snapshots, entries = {}, []
    for name in names:
      current = self.tree.read(name)
      snapshots[name] = current
      entries.append({"path": name,
        "before": base64.b64encode(current[0]).decode() if current else None,
        "before_mode": current[1] if current else None,
        "after": _digest(files[name]),
        "after_mode": (current[1] if current else 0o644) if files[name] is not None else None})
    value = {"version": 1, "adapter": self.adapter, "files": entries}
    encoded = json_bytes(value)
    if len(encoded) > 64 * 1024 * 1024:
      raise Conflict("依赖锁发布日志超过大小边界")
    _decode_journal(encoded, self.adapter)
    root = _journal_root(self.repository, self.adapter)
    ensure_private(root.parent)
    ensure_private(root)
    # 首次创建容器也必须先持久化父目录项，再发布恢复日志。
    for directory in (root.parent, root.parent.parent, self.repository):
      with Tree(directory, private=False) as parent:
        os.fsync(parent.fd)
    with Tree(root) as journal:
      journal.write_new("pending.json", encoded)
      try:
        for item in entries:
          current = snapshots[item["path"]]
          self.tree.replace(item["path"], files[item["path"]], item["after_mode"] if item["after_mode"] is not None else 0o600,
                            expected=current[2] if current else None)
        result = validate()
        pending = journal.read("pending.json")
        if pending is None or pending[0] != encoded:
          raise Conflict("依赖锁发布日志发生变化")
        journal.replace("pending.json", None, expected=pending[2])
        return result
      except Exception:
        pending = journal.read("pending.json")
        if pending is None or pending[0] != encoded:
          raise Conflict("依赖锁发布日志发生变化；拒绝恢复") from None
        _restore(self.tree, journal, value, pending)
        raise


@contextmanager
def publisher_lease(repository, adapter):
  """发布租约先于任何实例/运行包锁；显式解析前先恢复旧代。"""
  with _lease(repository, adapter, exclusive=True, create=True) as tree:
    publisher = Publisher(repository, adapter, tree)
    publisher.recover()
    yield publisher
