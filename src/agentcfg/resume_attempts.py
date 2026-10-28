"""单次恢复的私人请求/派发事实；不保存正文，不授予恢复或加载资格。

调用者已持运行物理租约并登记新 owner。intent 必须在启动前落盘；启动后的
记账失败不能终止宿主或覆盖原生退出码。旧 intent 没有安全重放含义。
"""

from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict
import errno
import fcntl
import hashlib
import json
import os
import time

from . import run_owners, storage
from .control_deadline import ControlDeadline
from .paths import PathError
from .sessions import KnownSession, SessionRef, _resume_target
from .storage import Conflict, LockBusy, Tree


_FIELDS = {"schema_version", "binding_digest", "run_id", "manager_identity", "requested",
  "dispatch", "exit_code", "load_confirmation", "continue_status"}


class PendingResume(Conflict):
  """可信范围内已有尚未完成的同会话请求；引用不是重放许可。"""

  def __init__(self, run_ids):
    self.run_ids = tuple(sorted(set(run_ids)))
    for run_id in self.run_ids:
      run_owners._run_id(run_id)
    super().__init__("同一会话的恢复请求仍待核验；保留原请求，不重复派发")


@contextmanager
def _claim_lock(fd):
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  except OSError as error:
    if error.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
      raise LockBusy("恢复请求元数据忙") from None
    raise Conflict("恢复请求元数据锁不能核验") from None
  try:
    yield
  finally:
    fcntl.flock(fd, fcntl.LOCK_UN)


def _clock():
  value = time.time_ns()
  if type(value) is not int or value <= 0:
    raise Conflict("恢复观察时间无效")
  return value


def _exit_code(value):
  if type(value) is not int or not 0 <= value <= 255:
    raise Conflict("原生退出码无效")
  return value


class ResumeAttempts:
  """同一物理实例的辅助事实目录；绝不写入 RunRecord 的会话观察字段。"""

  def __init__(self, root, binding):
    self._registry = run_owners.Registry(root, binding)
    self.root = self._registry.root
    self.binding = deepcopy(self._registry.binding)
    self.binding_digest = self._registry.binding_digest

  @contextmanager
  def _locked(self, *, create=False):
    # 与 owner 使用同一短目录锁协议，但放在独立目录；不持此锁获取物理/owner锁。
    with self._registry._locked(create=create) as tree:
      yield tree

  @contextmanager
  def _admission(self, owners, *, create=False):
    """先快照 owner 并释放短锁，再串行认领 attempt；两者不同时持锁。"""
    deadline = ControlDeadline(2)
    while True:
      entered = False
      try:
        if deadline.expired():
          raise Conflict("恢复请求元数据忙；保留原记录并重新查询")
        with Tree(owners.root) as owner_tree:
          if owner_tree.fd is None:
            raise Conflict("恢复运行的归属记录缺失")
          with _claim_lock(owner_tree.fd):
            owners._verify_root(owner_tree)
            records, _ = owners._records(owner_tree)
          # idle_confirmed 是不可重启的终态；旧 active/unknown 快照只会保守拒绝。
          # 此后出现的新 intent 若不在 owner 快照中同样拒绝；由 attempt 锁保证唯一认领。
          # 保留 owner 目录句柄核对物理身份，扫描/持久化时不占用 OMP 的 owner NB 入口。
          with Tree(self.root, create=create) as tree:
            guard = _claim_lock(tree.fd) if tree.fd is not None else nullcontext()
            with guard:
              owners._verify_root(owner_tree)
              if tree.fd is not None:
                self._registry._verify_root(tree)
              if deadline.expired():
                raise Conflict("恢复请求元数据预算耗尽；保留原记录")
              entered = True
              yield records, tree if tree.fd is not None else None
              owners._verify_root(owner_tree)
              if tree.fd is not None:
                self._registry._verify_root(tree)
        return
      except LockBusy:
        # body、写入或提交中的异常不能成为重放依据。
        if entered:
          raise
        left = deadline.remaining()
        if left <= 0:
          raise Conflict("恢复请求元数据忙；保留原记录并重新查询") from None
        time.sleep(min(0.01, left))
      except (OSError, PathError):
        raise Conflict("恢复请求目录或归属不能安全核验；保留原记录") from None

  def _pending(self, tree, target, owners):
    if tree is None:
      return
    names = os.listdir(tree.fd)
    pending = []
    session = asdict(target.ref)
    for name in sorted(names):
      if not name.endswith(".json"):
        raise Conflict("恢复请求目录含未知记录；保留原记录")
      run_id = name[:-5]
      run_owners._run_id(run_id)
      record, _ = self._read(tree, run_id)
      if record is None:
        raise Conflict("恢复请求记录在核验中消失")
      if record["requested"]["session"] != session:
        continue
      owner = owners.get(run_id)
      if owner is None or owner.get("schema_version") != 2:
        pending.append(run_id)
        continue
      self._project(owner, record)
      observation = owner.get("process_observation", {})
      if (run_owners.record_state(owner) != "idle_confirmed"
          or observation.get("kind") != "complete_release" or observation.get("coverage") != "complete"
          or record["dispatch"]["state"] != "launched" or record["exit_code"] is None):
        pending.append(run_id)
    if pending:
      raise PendingResume(pending)

  def check_pending(self, target, owner):
    """只读预检不授予派发资格；begin 仍须在同一锁边界重新核验。"""
    self._check_owner(target, owner)
    registry = run_owners.Registry(self.root.parent / "run-owners", self.binding)
    with self._admission(registry) as (records, tree):
      if records.get(owner["run_id"]) != owner:
        raise Conflict("恢复运行的归属发生变化")
      self._pending(tree, target, records)

  def _validate(self, run_id, record):
    try:
      run_owners._run_id(run_id)
      run_owners._no_float(record)
      if (type(record) is not dict or set(record) != _FIELDS
          or type(record["schema_version"]) is not int or record["schema_version"] != 1
          or record["binding_digest"] != self.binding_digest or record["run_id"] != run_id
          or record["load_confirmation"] != "unknown" or record["continue_status"] != "not_sent"):
        raise ValueError()
      run_owners._manager(record["manager_identity"])
      request = record["requested"]
      if type(request) is not dict or set(request) != {"session", "cwd", "previous_run_id"}:
        raise ValueError()
      SessionRef(**request["session"])
      run_owners._absolute(request["cwd"])
      if request["previous_run_id"] is not None:
        run_owners._run_id(request["previous_run_id"])
      if request["previous_run_id"] == run_id:
        raise ValueError()
      dispatch = record["dispatch"]
      if (type(dispatch) is not dict or set(dispatch) != {"state", "observed_at_ns"}
          or dispatch["state"] not in ("intent", "launched")
          or type(dispatch["observed_at_ns"]) is not int or dispatch["observed_at_ns"] <= 0):
        raise ValueError()
      if record["exit_code"] is not None:
        _exit_code(record["exit_code"])
        if dispatch["state"] != "launched":
          raise ValueError()
    except Exception:
      raise Conflict("恢复请求记录损坏、来源不完整或绑定不匹配") from None

  def _read(self, tree, run_id):
    run_owners._run_id(run_id)
    if tree is None:
      return None, None
    raw = tree.read(run_id + ".json", max_bytes=65536)
    if raw is None:
      return None, None
    if raw[1] != 0o600:
      raise Conflict("恢复请求记录权限不符")
    try:
      value = json.loads(raw[0], object_pairs_hook=run_owners._pairs,
        parse_constant=run_owners._invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
      raise Conflict("恢复请求记录格式无效") from None
    self._validate(run_id, value)
    return value, raw

  def read(self, run_id):
    """只读指定 run；缺目录不创建，不扫描其他 scope，也不推导当前会话。"""
    with self._locked() as tree:
      record, _ = self._read(tree, run_id)
      return record

  def for_owner(self, owner):
    """将受保护请求投影为只读状态；必须与独立 owner 身份及存储范围一致。"""
    if owner.get("schema_version") != 2:
      return None
    self._registry._validate_record(owner["run_id"] + ".json", owner)
    return self._project(owner, self.read(owner["run_id"]))

  def for_validated_owners(self, owners):
    """仅接收 Registry.snapshot 的已校验结果；同目录一次观察，不重新校验整个 owner。"""
    result = {run_id: None for run_id in owners}
    if not any(owner["schema_version"] == 2 for owner in owners.values()):
      return result
    with self._locked() as tree:
      if tree is None:
        return result
      for run_id, owner in owners.items():
        if owner["schema_version"] != 2:
          continue
        try:
          record, _ = self._read(tree, run_id)
          result[run_id] = self._project(owner, record)
        except (Conflict, PathError, OSError):
          result[run_id] = {"status": "unknown", "source": "resume-request-unavailable"}
    return result

  def _project(self, owner, record):
    if record is None:
      return None
    request = record["requested"]
    ref = request["session"]
    if (run_owners._encode(record["manager_identity"]) != run_owners._encode(owner["manager_identity"])
        or ref["agent"] != owner["agent"] or ref["backend"] != owner["backend"]
        or ref["native_home_ref"] != run_owners.native_home_key(owner["native_home_ref"])
        or request["cwd"] != owner["start_cwd"]["path"]):
      raise Conflict("恢复请求记录与运行归属不匹配")
    status = ("unknown" if record["dispatch"]["state"] == "intent" else
      "failed" if record["exit_code"] not in (None, 0) else "launch_dispatched")
    return {"status": status, "source": "resume-attempt-record",
      "requested_session": ref, "requested_cwd": request["cwd"],
      "previous_run_id": request["previous_run_id"], "dispatch": record["dispatch"]["state"],
      "observed_at_ns": record["dispatch"]["observed_at_ns"], "exit_code": record["exit_code"],
      "load_confirmation": "unknown", "continue_status": "not_sent"}

  def _check_owner(self, target, owner):
    try:
      if type(target) is not KnownSession or type(owner) is not dict or owner.get("schema_version") != 2:
        raise ValueError()
      run_id = owner["run_id"]
      self._registry._validate_record(run_id + ".json", owner)
      _resume_target(target, "here", None)
      scope = hashlib.sha256(run_owners._encode({key: self.binding[key]
        for key in ("machine", "local")})).hexdigest()
      if (owner["lifecycle_state"] != "active" or target.run_id == run_id
          or target.scope != scope or target.profile != owner["profile"]
          or target.ref.agent != owner["agent"] or target.ref.backend != owner["backend"]
          or target.ref.native_home_ref != run_owners.native_home_key(owner["native_home_ref"])
          or target.cwd != owner["start_cwd"]["path"]):
        raise ValueError()
    except Exception:
      raise Conflict("恢复请求与本次运行登记不匹配") from None

  def begin(self, target, owner):
    """新 owner 后、spawn 前核验并认领；同会话未决请求不因新run而失效。"""
    self._check_owner(target, owner)
    run_id = owner["run_id"]
    record = {"schema_version": 1, "binding_digest": self.binding_digest, "run_id": run_id,
      "manager_identity": deepcopy(owner["manager_identity"]),
      "requested": {"session": asdict(target.ref), "cwd": target.cwd, "previous_run_id": target.run_id},
      "dispatch": {"state": "intent", "observed_at_ns": _clock()}, "exit_code": None,
      "load_confirmation": "unknown", "continue_status": "not_sent"}
    self._validate(run_id, record)
    registry = run_owners.Registry(self.root.parent / "run-owners", self.binding)
    with self._admission(registry, create=True) as (records, tree):
      if records.get(run_id) != owner:
        raise Conflict("恢复运行的归属发生变化")
      self._pending(tree, target, records)
      encoded = run_owners._encode(record)
      tree.write_new(run_id + ".json", encoded)
      storage.sync_directory_ancestors(self.root.parent)
      _, saved = self._read(tree, run_id)
      self._registry._verify_root(tree)
      if saved is None or saved[0] != encoded:
        raise Conflict("恢复请求发布后发生变化；保留事实且禁止重放")
      info = os.fstat(tree.fd)
      root_identity = (info.st_dev, info.st_ino)
    return _Attempt(self, record, root_identity)


class _Attempt:
  """仅原始调用者持有的单次记账句柄，不可从保存 JSON 构造或重放启动。"""

  def __init__(self, store, record, root_identity):
    self._store = store
    self._record = deepcopy(record)
    self._root_identity = root_identity
    self._spawned = False
    self._finished = False

  def _advance(self, code=None):
    store, original = self._store, self._record
    with store._locked() as tree:
      if tree is None:
        raise Conflict("恢复请求容器已消失")
      info = os.fstat(tree.fd)
      if (info.st_dev, info.st_ino) != self._root_identity:
        raise Conflict("恢复请求容器身份变化")
      record, raw = store._read(tree, original["run_id"])
      immutable = _FIELDS - {"dispatch", "exit_code"}
      if (record is None or record["exit_code"] is not None
          or any(run_owners._encode(record[key]) != run_owners._encode(original[key]) for key in immutable)):
        raise Conflict("恢复请求身份变化或已记录退出")
      record["dispatch"] = {"state": "launched", "observed_at_ns": _clock()}
      record["exit_code"] = code
      store._validate(original["run_id"], record)
      tree.replace(original["run_id"] + ".json", run_owners._encode(record), expected=raw[2])

  def launched(self):
    if self._spawned or self._finished:
      raise Conflict("恢复启动观察不能重复提交")
    # 内存事实先于可能失败的保存；退出时仍能补记已经观察到的同一次启动。
    self._spawned = True
    self._advance()

  def exited(self, code):
    code = _exit_code(code)
    if not self._spawned or self._finished:
      raise Conflict("恢复退出观察缺少本次启动或已记录")
    self._finished = True
    self._advance(code)
