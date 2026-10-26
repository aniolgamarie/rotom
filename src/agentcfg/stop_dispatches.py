"""当前 manager 的单 run 停止派发记账；不发送信号或授予控制许可。

可信调用者负责现场身份、批准、有效批次、期限及原物理租约。这里仅在
发送前不可覆盖保存意图，返回本进程的一次结果记账对象。没有结果代表
可能已发送，不能重放；发送结果不证明进程、后代、会话或资源已释放。
本模块不读取 owner/协调域，不在元数据锁内获取物理锁或执行用户回调。
"""

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
import threading

from . import run_owners, storage, stop_locks
from .stop_requests import decode_stop_request, encode_stop_request
from .storage import Conflict, Tree


_ERROR = "停止派发记账不能确认；保留已有事实且不重发"
_TOKEN = object()


@contextmanager
def _boundary():
  try:
    yield
  except Exception:
    raise Conflict(_ERROR) from None


def _physical(tree):
  info = os.fstat(tree.fd)
  return info.st_dev, info.st_ino


def _decode(raw):
  if raw[1] != 0o600:
    raise ValueError()
  value = json.loads(raw[0], object_pairs_hook=run_owners._pairs,
    parse_constant=run_owners._invalid_constant)
  run_owners._no_float(value)
  if type(value) is not dict or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
    raise ValueError()
  return value


class _Attempt:
  """只记录当次发送调用成功返回；不是发送许可，不能从旧文件恢复。"""

  def __init__(self, token, journal, request, raw, physical):
    if token is not _TOKEN:
      raise Conflict(_ERROR)
    self._journal, self._request = journal, deepcopy(request)
    self._raw, self._physical = raw, physical
    self._pid, self._used, self._lock = os.getpid(), False, threading.Lock()

  def __copy__(self):
    return self

  def __deepcopy__(self, memo):
    memo[id(self)] = self
    return self

  def __reduce_ex__(self, protocol):
    raise Conflict(_ERROR)

  def sent(self):
    locked = False
    with _boundary():
      try:
        locked = self._lock.acquire(blocking=False)
        if not locked or self._used or self._pid != os.getpid():
          raise ValueError()
        # 从结果写入尝试开始便不重试；错误不能把原信号调用变成未发生。
        self._used = True
        self._journal._sent(self)
      finally:
        if locked:
          self._lock.release()


class StopDispatches:
  def __init__(self, root, binding, *, wait_for_lock=False):
    with _boundary():
      if type(wait_for_lock) is not bool:
        raise ValueError()
      self._wait_for_lock = wait_for_lock
      self._registry = run_owners.Registry(root, binding)
      self.root, self.binding = self._registry.root, deepcopy(self._registry.binding)
      self._binding_digest = self._registry.binding_digest

  def _read(self, tree, run_id):
    run_owners._run_id(run_id)
    if tree is None:
      return None
    raw = tree.read(run_id + ".json", max_bytes=32768)
    result_raw = tree.read(run_id + ".sent.json", max_bytes=1024)
    if raw is None:
      if result_raw is not None:
        raise ValueError()
      return None
    value = _decode(raw)
    if (set(value) != {"schema_version", "kind", "binding_digest", "request"}
        or value["kind"] != "stop-dispatch-intent" or value["binding_digest"] != self._binding_digest):
      raise ValueError()
    request = decode_stop_request(encode_stop_request(value["request"]))
    if request["run_id"] != run_id:
      raise ValueError()
    if result_raw is not None:
      result = _decode(result_raw)
      if (set(result) != {"schema_version", "kind", "request_id", "intent_digest", "status"}
          or result["kind"] != "stop-signal-result" or result["request_id"] != request["request_id"]
          or result["intent_digest"] != hashlib.sha256(raw[0]).hexdigest() or result["status"] != "sent"):
        raise ValueError()
    return request, raw[0], result_raw is not None

  def read(self, run_id, *, deadline_ns=None):
    """只读原始派发事实；不重建结果记账对象或发送许可。"""
    with _boundary():
      run_owners._run_id(run_id)
      if deadline_ns is not None:
        # 首次派发前目录可以尚未创建；只读检查不能创建空 journal。
        with Tree(self.root) as observed:
          if observed.fd is None:
            return None
      guard = (self._registry._locked(nonblocking=True) if deadline_ns is None
        else stop_locks.locked(self._registry, deadline_ns))
      with guard as tree:
        saved = self._read(tree, run_id)
        if saved is None:
          return None
        return {"request": saved[0], "dispatch": "signal_sent" if saved[2] else "unknown"}

  def begin(self, request):
    """当前 manager 在发送前调用；未知/已有 run 拒绝，不恢复或覆盖。"""
    with _boundary():
      request = decode_stop_request(encode_stop_request(request))
      if run_owners.current_process_identity() != request["manager_identity"]:
        raise ValueError()
      raw = run_owners._encode({"schema_version": 1, "kind": "stop-dispatch-intent",
        "binding_digest": self._binding_digest, "request": request})
      guard = (stop_locks.locked(self._registry, request["deadline_ns"], create=True) if self._wait_for_lock
        else self._registry._locked(create=True, nonblocking=True))
      with guard as tree:
        if self._read(tree, request["run_id"]) is not None:
          raise ValueError()
        if run_owners.current_process_identity() != request["manager_identity"]:
          raise ValueError()
        physical = _physical(tree)
        tree.write_new(request["run_id"] + ".json", raw)
        storage.sync_directory_ancestors(self._registry.root.parent)
        saved = self._read(tree, request["run_id"])
        self._registry._verify_root(tree)
        if saved is None or saved[1] != raw or saved[2]:
          raise ValueError()
        return _Attempt(_TOKEN, self, request, raw, physical)

  def _sent(self, attempt):
    if (type(attempt) is not _Attempt or attempt._journal is not self
        or run_owners.current_process_identity() != attempt._request["manager_identity"]):
      raise ValueError()
    run_id = attempt._request["run_id"]
    guard = (stop_locks.locked(self._registry, attempt._request["deadline_ns"], allow_expired_once=True)
      if self._wait_for_lock else self._registry._locked(nonblocking=True))
    with guard as tree:
      if tree is None or _physical(tree) != attempt._physical:
        raise ValueError()
      saved = self._read(tree, run_id)
      if saved is None or saved[1] != attempt._raw or saved[2]:
        raise ValueError()
      raw = run_owners._encode({"schema_version": 1, "kind": "stop-signal-result",
        "request_id": attempt._request["request_id"],
        "intent_digest": hashlib.sha256(attempt._raw).hexdigest(), "status": "sent"})
      tree.write_new(run_id + ".sent.json", raw)
      saved = self._read(tree, run_id)
      self._registry._verify_root(tree)
      if saved is None or saved[1] != attempt._raw or not saved[2]:
        raise ValueError()
