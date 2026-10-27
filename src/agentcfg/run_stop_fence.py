"""与 owner 登记共锁的持久停止意图；只阻断新运行/维护，不授予控制或写入许可。

兄弟文件避免混入历史 owner 格式。任何存在性均保留保护；本模块没有删除、
超时释放或重放接口。可选人工快照先持久保存，再由 v2 意图绑定摘要；
明确批准及完整资源/控制核验仍由上层完成，快照和意图都不是许可。
"""
from contextlib import contextmanager
import hashlib
import json
import os
import re

from . import run_owners, storage, stop_locks
from .storage import Conflict, Tree


_ERROR = "停止意图或运行集合不能确认；保留保护且不重试"
_FIELDS = {"schema_version", "kind", "binding_digest", "registry_physical", "batch_id", "plan_id", "records_digest"}


@contextmanager
def _boundary():
  try:
    yield
  except Exception:
    raise Conflict(_ERROR) from None


def _name(registry):
  if type(registry) is not run_owners.Registry:
    raise ValueError()
  return registry.root.name + ".stop-fence.json"


def _physical(tree):
  if tree is None or tree.fd is None:
    raise ValueError()
  info = os.fstat(tree.fd)
  return {"device": info.st_dev, "inode": info.st_ino}


def _digest(value):
  return hashlib.sha256(run_owners._encode(value)).hexdigest()


def _assert_missing(parent, name):
  try:
    with parent.parent(name) as (fd, leaf):
      os.stat(leaf, dir_fd=fd, follow_symlinks=False)
  except FileNotFoundError:
    return
  raise ValueError()


def assert_unfenced(registry):
  """调用方已持同一 owner 锁；只查存在性，损坏/链接也阻断，不读取正文。"""
  with _boundary(), Tree(registry.root.parent) as parent:
    if parent.fd is None:
      return
    _assert_missing(parent, _name(registry))


def _snapshot_name(registry, batch_id):
  _name(registry)
  run_owners._run_id(batch_id)
  return registry.root.name + ".stop-snapshot-" + batch_id + ".json"


def _read_snapshot(parent, registry, batch_id, owner):
  from . import run_stop_snapshot as codec
  raw = parent.read(_snapshot_name(registry, batch_id), max_bytes=codec._MAX_BYTES)
  if raw is None:
    return None
  if raw[1] != 0o600:
    raise ValueError()
  value = codec.decode_snapshot(raw[0])
  if (value["batch_id"] != batch_id or value["binding_digest"] != registry.binding_digest
      or run_owners._encode(value["binding"]) != run_owners._encode(registry.binding)
      or run_owners._encode(value["registry_physical"]) != run_owners._encode(_physical(owner))):
    raise ValueError()
  return value, raw[0]


def _check_snapshot(value, registry, physical, records, batch_id, plan_id):
  if (value["batch_id"] != batch_id or value["plan_id"] != plan_id
      or value["binding_digest"] != registry.binding_digest
      or run_owners._encode(value["binding"]) != run_owners._encode(registry.binding)
      or run_owners._encode(value["registry_physical"]) != run_owners._encode(physical)
      or value["records_digest"] != _digest(records)
      or run_owners._encode(value["records"]) != run_owners._encode(
        {run: records[run] for run in value["selected_runs"]})):
    raise ValueError()


def _check_snapshot_link(parent, registry, owner, value):
  saved = _read_snapshot(parent, registry, value["batch_id"], owner)
  if saved is None:
    raise ValueError()
  snapshot, raw = saved
  if (hashlib.sha256(raw).hexdigest() != value["snapshot_digest"]
      or snapshot["plan_id"] != value["plan_id"] or snapshot["records_digest"] != value["records_digest"]):
    raise ValueError()
  return snapshot


def install(registry, *, batch_id, plan_id, expected_records, before_publish=None, recovery_snapshot=None, deadline_ns=None):
  """内部阻断事务，返回 None；不核验用户批准、资源闭包或停止能力。

  上层必须已按原顺序持有实例/状态 SH，并持续至本事务完成，以排除正在执行的
  EX 维护；本函数不取得物理锁或验证借入锁模式，不能独自宣称完整停止接受。
  before_publish 仅允许短可信内存/独立元数据操作，不得交互或调用宿主，也不得取得
  Domain、Registry/owner 或物理锁；不能在此调用另一套 live 接受事务。
  它在同一 owner 锁内完整复核后执行；其副作用和可能发布的意图永不自动撤回。
  可选 recovery_snapshot 仅保存所选运行的人工恢复参考；同批已存在的快照拒绝重用。
  发布快照后失败会留下孤儿，不表示已接受/已停止，亦不从文件补造批准或自动重试。
  """
  with _boundary():
    name = _name(registry)
    run_owners._run_id(batch_id)
    if (type(plan_id) is not str or re.fullmatch(r"[0-9a-f]{64}", plan_id) is None
        or type(expected_records) is not dict or not expected_records
        or before_publish is not None and not callable(before_publish)):
      raise ValueError()
    # 固定调用时的完整集合，回调不能通过修改传入对象改变比较目标。
    expected = run_owners._encode(expected_records)
    snapshot, snapshot_raw = None, None
    if recovery_snapshot is not None:
      from . import run_stop_snapshot as codec
      snapshot_raw = codec.encode_snapshot(recovery_snapshot)
      snapshot = codec.decode_snapshot(snapshot_raw)
    guard = registry._locked(nonblocking=True) if deadline_ns is None else stop_locks.locked(registry, deadline_ns)
    with guard as owner, Tree(registry.root.parent) as parent:
      physical = _physical(owner)
      records, _ = registry._records(owner)
      if run_owners._encode(records) != expected:
        raise ValueError()
      assert_unfenced(registry)
      if snapshot is not None:
        _check_snapshot(snapshot, registry, physical, records, batch_id, plan_id)
        _assert_missing(parent, _snapshot_name(registry, batch_id))
      if before_publish is not None:
        before_publish()
      records, _ = registry._records(owner)
      if run_owners._encode(records) != expected or _physical(owner) != physical:
        raise ValueError()
      if snapshot is not None:
        parent.write_new(_snapshot_name(registry, batch_id), snapshot_raw)
        storage.sync_directory_ancestors(parent.root)
        saved_snapshot = _read_snapshot(parent, registry, batch_id, owner)
        if saved_snapshot is None or saved_snapshot[1] != snapshot_raw:
          raise ValueError()
        records, _ = registry._records(owner)
        if run_owners._encode(records) != expected or _physical(owner) != physical:
          raise ValueError()
      value = {"schema_version": 1, "kind": "run-stop-fence", "binding_digest": registry.binding_digest,
        "registry_physical": physical, "batch_id": batch_id, "plan_id": plan_id,
        "records_digest": _digest(records)}
      if snapshot is not None:
        value.update(schema_version=2, snapshot_digest=hashlib.sha256(snapshot_raw).hexdigest())
      encoded = run_owners._encode(value)
      parent.write_new(name, encoded)
      storage.sync_directory_ancestors(parent.root)
      saved = parent.read(name, max_bytes=16384)
      registry._verify_root(owner)
      if saved is None or saved[1] != 0o600 or saved[0] != encoded:
        raise ValueError()
      if snapshot is not None:
        _check_snapshot_link(parent, registry, owner, value)
        registry._verify_root(owner)


def _read_locked(registry, owner, parent):
  """调用方维持同一 owner 锁；不额外取锁，复用严格历史读取。"""
  raw = parent.read(_name(registry), max_bytes=16384)
  if raw is None:
    return None
  if raw[1] != 0o600:
    raise ValueError()
  value = json.loads(raw[0], object_pairs_hook=run_owners._pairs,
    parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
  if (type(value) is not dict or type(value.get("schema_version")) is not int
      or value["schema_version"] not in (1, 2)
      or set(value) != (_FIELDS | {"snapshot_digest"} if value["schema_version"] == 2 else _FIELDS)
      or value["kind"] != "run-stop-fence"
      or value["binding_digest"] != registry.binding_digest
      or run_owners._encode(value["registry_physical"]) != run_owners._encode(_physical(owner))):
    raise ValueError()
  run_owners._run_id(value["batch_id"])
  for field in ("plan_id", "records_digest"):
    if type(value[field]) is not str or re.fullmatch(r"[0-9a-f]{64}", value[field]) is None:
      raise ValueError()
  if value["schema_version"] == 2:
    if type(value["snapshot_digest"]) is not str or re.fullmatch(r"[0-9a-f]{64}", value["snapshot_digest"]) is None:
      raise ValueError()
    _check_snapshot_link(parent, registry, owner, value)
  registry._verify_root(owner)
  return value


def read(registry):
  """只读历史阻断事实；不要求 owner 仍与接受时相同，不返回可执行令牌。"""
  with _boundary():
    _name(registry)
    with registry._locked(nonblocking=True) as owner, Tree(registry.root.parent) as parent:
      return _read_locked(registry, owner, parent)


def read_snapshot(registry, batch_id):
  """只读人工恢复参考，允许孤儿快照；不表示已接受批次、已停止或可继续。

  完整意图关联须另读 read()；两者都不提供批准、控制或自动恢复许可。
  """
  with _boundary():
    _snapshot_name(registry, batch_id)
    with registry._locked(nonblocking=True) as owner, Tree(registry.root.parent) as parent:
      saved = _read_snapshot(parent, registry, batch_id, owner)
      if saved is None:
        return None
      registry._verify_root(owner)
      return saved[0]
