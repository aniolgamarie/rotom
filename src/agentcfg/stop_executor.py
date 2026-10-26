"""候选 manager 请求处理；仅注入通道，没有原生信号或生产接线。

可信工厂负责将 run 绑定到原启动句柄和派发目录。verify 必须重新核实请求
来源、停止批准、有效批次/意图及资源现场；它不是用户交互回调。数据格式、
句柄快照、意图文件和本处理器都不能单独替代这些资格。通道必须有界，
只对给定句柄发一次优雅请求。整个普通 TUI 生命周期没有这里的等待期限。
"""

from copy import deepcopy
import threading
import time

from . import run_owners
from .spawned_host import SpawnedHost
from .stop_dispatches import StopDispatches
from .stop_requests import decode_stop_request, encode_stop_request
from .storage import Conflict


_ERROR = "停止请求现场或派发结果不能确认；保留事实且不重发"


class StopRequestHandler:
  def __init__(self, run_id, host, journal, *, verify, send, clock=None):
    try:
      run_owners._run_id(run_id)
      clock = time.monotonic_ns if clock is None else clock
      if (type(host) is not SpawnedHost or type(journal) is not StopDispatches
          or not all(callable(item) for item in (verify, send, clock))):
        raise ValueError()
      self._bound = host.snapshot()
      self._run, self._host, self._journal = run_id, host, journal
      self._verify, self._send, self._clock = verify, send, clock
      self._last_clock, self._attempted = None, False
      self._lock = threading.Lock()
    except Exception:
      raise Conflict(_ERROR) from None

  def _deadline(self, request):
    now = self._clock()
    if (type(now) is not int or not 0 <= now <= 2**63 - 1
        or self._last_clock is not None and now < self._last_clock):
      raise ValueError()
    # 请求过期仍是一次有效时钟观察，下一请求不能借倒退时钟重新获得预算。
    self._last_clock = now
    if not 0 < request["deadline_ns"] - now <= 300000000000:
      raise ValueError()

  def _check(self, request):
    self._deadline(request)
    if self._host.snapshot() != self._bound:
      raise ValueError()
    if self._verify(deepcopy(request)) is not True:
      raise ValueError()
    # verify/落盘可能耗时或揭露漂移；使用原句柄复核，不重新按 PID 打开。
    if self._host.snapshot() != self._bound:
      raise ValueError()
    self._deadline(request)

  def handle(self, request):
    """只处理本 run 的一次尝试；发送成功事实不等于退出/释放或阶段成功。"""
    locked = False
    try:
      request = decode_stop_request(encode_stop_request(request))
      locked = self._lock.acquire(blocking=False)
      if not locked or self._attempted:
        raise ValueError()
      if (request["run_id"] != self._run or request["manager_identity"] != self._bound["manager_identity"]
          or request["host_identity"] != self._bound["identity"]):
        raise ValueError()
      self._check(request)
      # 从意图写入尝试开始，异常/响应丢失都不能重新派发本处理器。
      self._attempted = True
      attempt = self._journal.begin(request)
      self._check(request)
      if self._send(self._host) is not None:
        raise ValueError()
      # 不因发送后过期而丢弃已发生事实；外层阶段仍须独立判断超时。
      attempt.sent()
      return {"run_id": self._run, "request_id": request["request_id"], "dispatch": "signal_sent"}
    except Exception:
      raise Conflict(_ERROR) from None
    finally:
      if locked:
        self._lock.release()
