"""单次恢复的私人请求/派发事实；不保存正文，不授予恢复或加载资格。

调用者已持运行物理租约并登记新 owner。intent 必须在启动前落盘；启动后的
记账失败不能终止宿主或覆盖原生退出码。旧 intent 没有安全重放含义。
"""

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
import time

from . import run_owners, storage
from .paths import PathError
from .sessions import KnownSession, SessionRef, _resume_target
from .storage import Conflict, Tree


_FIELDS = {"schema_version", "binding_digest", "run_id", "manager_identity", "requested",
  "dispatch", "exit_code", "load_confirmation", "continue_status"}


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

  def begin(self, target, owner):
    """新 owner 后、spawn 前保存 intent；重复 run 或落盘结果不明均禁止重放。"""
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
    record = {"schema_version": 1, "binding_digest": self.binding_digest, "run_id": run_id,
      "manager_identity": deepcopy(owner["manager_identity"]),
      "requested": {"session": asdict(target.ref), "cwd": target.cwd, "previous_run_id": target.run_id},
      "dispatch": {"state": "intent", "observed_at_ns": _clock()}, "exit_code": None,
      "load_confirmation": "unknown", "continue_status": "not_sent"}
    self._validate(run_id, record)
    with self._locked(create=True) as tree:
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
