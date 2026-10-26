"""manager StopService 组合；默认受管入口仅为已准入 DSH 组合安装。

私人文件与句柄元数据不代替当前批准、意图、资源和期限；verify 由可信工厂提供。
本对象借用原 SpawnedHost，不重建旧 endpoint、不关闭句柄，也不删除持久事实。
"""
from copy import deepcopy
import threading

from . import run_owners
from .spawned_host import SpawnedHost
from .stop_dispatches import StopDispatches
from .stop_executor import StopRequestHandler
from .stop_inbox import StopInbox
from .storage import Conflict


_ERROR = "停止服务现场或单次处理结果不能确认；保留事实且不重试"


def _same(a, b):
  return run_owners._encode(a) == run_owners._encode(b)


class StopService:
  def __init__(self, run_id, host, *, inbox, journal, verify, clock=None):
    try:
      run_owners._run_id(run_id)
      if (type(host) is not SpawnedHost or type(inbox) is not StopInbox or type(journal) is not StopDispatches
          or not callable(verify) or clock is not None and not callable(clock)
          or inbox._registry.binding_digest != journal._binding_digest
          or inbox._registry.root == journal._registry.root):
        raise ValueError()
      bound = host.snapshot()
      endpoint = inbox.create(run_id=run_id, manager_identity=bound["manager_identity"], host_identity=bound["identity"])
      self._run, self._host, self._inbox = run_id, host, inbox
      self._endpoint, self._verify = deepcopy(endpoint), verify
      self._active, self._failed, self._completed = True, False, False
      self._lock = threading.Lock()
      self._handler = StopRequestHandler(run_id, host, journal, verify=self._verify_request,
        send=lambda current: current.send_sigterm_once(), clock=clock)
      if not _same(host.snapshot(), bound):
        raise ValueError()
    except Exception:
      # endpoint 一旦写入便保留；失败不删除、不重建或自动重试。
      raise Conflict(_ERROR) from None

  def _check_active(self):
    if not self._active or self._failed:
      raise ValueError()

  def _verify_request(self, request):
    self._check_active()
    if not _same(self._inbox.describe(deadline_ns=request["deadline_ns"]), self._endpoint):
      raise ValueError()
    approved = self._verify(request)
    # 回调可能触发重入或揭露 endpoint 漂移，不能把内层失败变成外层资格。
    self._check_active()
    if not _same(self._inbox.describe(deadline_ns=request["deadline_ns"]), self._endpoint) or approved is not True:
      raise ValueError()
    return True

  def describe(self):
    """只读原 endpoint 副本；描述不消费请求，不成为停止批准或重建服务的凭据。"""
    locked = False
    try:
      locked = self._lock.acquire(blocking=False)
      if not locked:
        raise ValueError()
      self._check_active()
      endpoint = self._inbox.describe()
      self._check_active()
      if not _same(endpoint, self._endpoint):
        raise ValueError()
      return deepcopy(endpoint)
    except BaseException as error:
      self._failed = True
      if not isinstance(error, Exception):
        raise
      raise Conflict(_ERROR) from None
    finally:
      if locked:
        self._lock.release()

  def __call__(self):
    locked = False
    try:
      locked = self._lock.acquire(blocking=False)
      if not locked:
        raise ValueError()
      self._check_active()
      if self._completed:
        return None
      requests = self._inbox.pending(expected=self._endpoint, poll=True)
      self._check_active()
      if not requests:
        return None
      # StopInbox 返回按 request_id 排序的规范副本；每个服务最多处理一项。
      result = self._handler.handle(requests[0])
      self._check_active()
      self._completed = True
      return result
    except BaseException as error:
      self._failed = True
      if not isinstance(error, Exception):
        raise
      raise Conflict(_ERROR) from None
    finally:
      if locked:
        self._lock.release()

  def close(self):
    self._active = False

  def belongs_to(self, run_id, host):
    return type(run_id) is str and run_id == self._run and host is self._host and self._active and not self._failed

  def __copy__(self):
    return self

  def __deepcopy__(self, memo):
    memo[id(self)] = self
    return self

  def __reduce_ex__(self, protocol):
    raise Conflict(_ERROR)
