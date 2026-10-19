"""仅登记主运行归属；不调度任务、不恢复执行、不以父退出证明后代释放。

调用方必须先持有同一实例的物理准入锁，再访问元数据：register/mark_unknown持SH，
assert_inactive持EX。reconcile自行进入调用方提供的可信物理EX context manager，
随后才获得元数据EX锁。该顺序避免核实空闲后又有新运行登记的竞争。
同binding的合法active/unknown记录允许新增运行；unknown仅表示既有运行存活性未知，
不表示owner来源不可信。两者均阻止维护，新增运行不能清除旧归属或证明旧后代退出。
metadata锁不替代物理锁；此模块不接受TOML或用户确认开关作为完整释放证据。
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

from .paths import PathError
from .storage import Conflict, Tree


_RUN_ID = re.compile(r"[0-9a-f]{32}")
_STATES = {"active", "unknown", "idle_confirmed"}
_RESOURCES = ["instance", "runtime", "native-home"]
_OBSERVATIONS = {"active": ("manager_registered", "unknown"),
  "unknown": ("manager_scope_ended", "unknown"), "idle_confirmed": ("complete_release", "complete")}


def _run_id(value):
  if type(value) is not str or not _RUN_ID.fullmatch(value):
    raise Conflict("运行归属标识无效")
  return value


def _encode(value):
  return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
    separators=(",", ":")) + "\n").encode("utf-8")


def _manager(value):
  if (type(value) is not dict or type(value.get("pid")) is not int or value["pid"] <= 0
      or type(value.get("birth_id")) is not str or not value["birth_id"] or "\0" in value["birth_id"]):
    raise Conflict("运行进程身份缺失或无效")
  try:
    # 保存全部可确认身份字段，比较时不能只匹配PID。
    copied = json.loads(_encode(value))
  except (TypeError, ValueError, UnicodeError, RecursionError):
    raise Conflict("运行进程身份不可序列化") from None
  if copied != value:
    raise Conflict("运行进程身份格式不稳定")
  return copied


def _observation(state):
  # 时间仅记录观察时刻，不参与超时、空闲推断或归属清除。
  kind, coverage = _OBSERVATIONS[state]
  observed_at_ns = time.time_ns()
  if type(observed_at_ns) is not int or observed_at_ns <= 0:
    raise Conflict("运行观察时间无效")
  return {"kind": kind, "observed_at_ns": observed_at_ns, "coverage": coverage}


def _pairs(items):
  value = {}
  for key, item in items:
    if key in value:
      raise ValueError()
    value[key] = item
  return value


def _invalid_constant(value):
  raise ValueError()


@dataclass(frozen=True)
class ReleaseObservation:
  """可信内部observer的一次完整观察；不是公共配置或用户保证。"""

  run_id: str
  manager_identity: dict
  all_related_exited: bool
  complete: bool


def current_process_identity():
  """Linux公开/proc身份；缺可靠出生信息则拒绝，不猜测其他平台支持。"""
  if sys.platform != "linux":
    raise Conflict("当前平台尚无可靠的主进程身份来源")
  try:
    boot = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    if str(uuid.UUID(boot)) != boot:
      raise ValueError()
    def read_stat():
      value = Path("/proc/self/stat").read_text(encoding="ascii")
      prefix, separator, tail = value.rpartition(")")
      if not separator or int(prefix.split("(", 1)[0].strip()) != os.getpid():
        raise ValueError()
      start = tail.split()[19]
      if not start.isdecimal() or int(start) <= 0:
        raise ValueError()
      return start
    start = read_stat()
    if start != read_stat() or boot != Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip():
      raise ValueError()
    return {"pid": os.getpid(), "birth_id": "linux:" + boot + ":" + start}
  except (OSError, ValueError, IndexError, UnicodeError):
    raise Conflict("无法可靠确认当前主进程出生身份") from None


class Registry:
  def __init__(self, root: Path, binding: dict):
    if (not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts
        or root == Path("/") or type(binding) is not dict):
      raise Conflict("运行归属容器或绑定无效")
    try:
      self.binding_digest = hashlib.sha256(_encode(binding)).hexdigest()
    except (TypeError, ValueError, UnicodeError, RecursionError):
      raise Conflict("运行归属绑定不可序列化") from None
    self.root = root

  def _verify_root(self, tree):
    # 等待元数据锁和observer返回后仍重新核对当前路径的目录inode及0700边界。
    with Tree(self.root) as current:
      if current.fd is None:
        raise Conflict("运行归属目录已消失")
      before, after = os.fstat(tree.fd), os.fstat(current.fd)
      if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise Conflict("运行归属目录身份已变化")

  @contextmanager
  def _locked(self, *, create=False):
    try:
      with Tree(self.root, create=create) as tree:
        if tree.fd is None:
          yield None
          return
        # 短元数据操作阻塞串行；调用者先持物理锁，不在此反向获取物理锁。
        fcntl.flock(tree.fd, fcntl.LOCK_EX)
        try:
          self._verify_root(tree)
          yield tree
        finally:
          fcntl.flock(tree.fd, fcntl.LOCK_UN)
    except (OSError, PathError):
      raise Conflict("无法安全访问运行归属元数据") from None

  def _validate_record(self, name, record):
    if (type(record) is not dict
        or set(record) != {"schema_version", "binding_digest", "run_id", "manager_identity", "session_ref", "state",
          "affected_resources", "observation"}
        or type(record["schema_version"]) is not int or record["schema_version"] != 1
        or record["binding_digest"] != self.binding_digest
        or type(record["run_id"]) is not str or not _RUN_ID.fullmatch(record["run_id"])
        or name != record["run_id"] + ".json"
        or type(record["state"]) is not str or record["state"] not in _STATES
        or (record["session_ref"] is not None and (type(record["session_ref"]) is not str
          or not record["session_ref"] or "\0" in record["session_ref"]))):
      raise Conflict("运行归属记录损坏或绑定不匹配")
    observation = record["observation"]
    kind, coverage = _OBSERVATIONS[record["state"]]
    if (type(record["affected_resources"]) is not list or record["affected_resources"] != _RESOURCES
        or type(observation) is not dict or set(observation) != {"kind", "observed_at_ns", "coverage"}
        or observation["kind"] != kind or observation["coverage"] != coverage
        or type(observation["observed_at_ns"]) is not int or observation["observed_at_ns"] <= 0):
      raise Conflict("运行资源范围或观察记录无效")
    _manager(record["manager_identity"])

  def _records(self, tree):
    if tree is None:
      return {}, {}
    records, originals = {}, {}
    for name in sorted(os.listdir(tree.fd)):
      if not name.endswith(".json") or not _RUN_ID.fullmatch(name[:-5]):
        raise Conflict("运行归属目录包含未知记录")
      raw = tree.read(name, max_bytes=65536)
      if raw is None or raw[1] != 0o600:
        raise Conflict("运行归属记录缺失或权限不符")
      try:
        record = json.loads(raw[0], object_pairs_hook=_pairs, parse_constant=_invalid_constant)
      except (ValueError, UnicodeError, RecursionError):
        raise Conflict("运行归属记录格式无效") from None
      self._validate_record(name, record)
      records[record["run_id"]] = record
      originals[record["run_id"]] = raw
    self._verify_root(tree)
    return records, originals

  def register(self, manager_identity, session_ref=None):
    """调用者持物理SH；同binding的active/unknown均保留且允许并行。"""
    manager = _manager(manager_identity)
    run_id = uuid.uuid4().hex
    record = {"schema_version": 1, "binding_digest": self.binding_digest, "run_id": run_id,
      "manager_identity": manager, "session_ref": session_ref, "state": "active",
      "affected_resources": list(_RESOURCES), "observation": _observation("active")}
    self._validate_record(run_id + ".json", record)
    with self._locked(create=True) as tree:
      self._records(tree)
      tree.write_new(run_id + ".json", _encode(record))
    return run_id

  def mark_unknown(self, run_id, expected_identity):
    """调用者仍持物理SH；仅更新身份完全匹配的本次运行。"""
    _run_id(run_id)
    expected = _manager(expected_identity)
    with self._locked() as tree:
      records, originals = self._records(tree)
      record = records.get(run_id)
      if (record is None or _encode(record["manager_identity"]) != _encode(expected)
          or record["state"] == "idle_confirmed"):
        raise Conflict("运行归属或出生身份不匹配")
      if record["state"] == "unknown":
        return
      record["state"] = "unknown"
      record["observation"] = _observation("unknown")
      tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])

  def finish_current(self, run_id, expected_identity, observation):
    """调用者仍持物理SH；本次完整内核观察只能结束本次active记录。

    不同主运行仍可登记，其active/unknown不会被本次观察清除。旧unknown
    的后续核实仍只能经过reconcile的物理EX维护路径。
    """
    _run_id(run_id)
    expected = _manager(expected_identity)
    with self._locked() as tree:
      records, originals = self._records(tree)
      record = records.get(run_id)
      if (record is None or record["state"] != "active"
          or _encode(record["manager_identity"]) != _encode(expected)
          or type(observation) is not ReleaseObservation or observation.run_id != run_id
          or _encode(_manager(observation.manager_identity)) != _encode(expected)
          or observation.all_related_exited is not True or observation.complete is not True):
        raise Conflict("当前运行没有完整且身份匹配的后代释放观察")
      record["state"] = "idle_confirmed"
      record["observation"] = _observation("idle_confirmed")
      tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])

  def snapshot(self):
    with self._locked() as tree:
      records, _ = self._records(tree)
      return deepcopy(records)

  def assert_inactive(self):
    """调用者持物理EX；不因PID死亡、超时或父退出清除归属。"""
    with self._locked() as tree:
      records, _ = self._records(tree)
      if any(record["state"] != "idle_confirmed" for record in records.values()):
        raise Conflict("存在活动或未知运行；共享资源维护被阻止")

  def reconcile(self, run_id, *, maintenance_guard, observe=None):
    """先获得可信物理EX，再锁元数据；observer接收副本，不得重入Registry。"""
    _run_id(run_id)
    if maintenance_guard is None or not hasattr(maintenance_guard, "__enter__"):
      raise Conflict("核实运行归属需要物理排他维护准入")
    with maintenance_guard:
      with self._locked() as tree:
        records, originals = self._records(tree)
        record = records.get(run_id)
        if record is None or not callable(observe):
          raise Conflict("没有完整的运行释放观察")
        try:
          result = observe(deepcopy(record))
        except Exception:
          raise Conflict("无法完整核实相关运行及后代资源释放") from None
        if (type(result) is not ReleaseObservation or result.run_id != run_id
            or _encode(_manager(result.manager_identity)) != _encode(record["manager_identity"])
            or result.all_related_exited is not True or result.complete is not True):
          raise Conflict("运行释放观察不完整或身份不匹配")
        self._verify_root(tree)
        record["state"] = "idle_confirmed"
        record["observation"] = _observation("idle_confirmed")
        tree.replace(run_id + ".json", _encode(record), expected=originals[run_id][2])
        return deepcopy(record)
