"""P-EXIT 的纯假通道模型；不提供真实停止后端、观察器或全局事务。"""

from copy import deepcopy
from dataclasses import dataclass

from agentcfg.run_owners import ReleaseObservation
from agentcfg.storage import Conflict


_ERROR = "合成停止通道不能确认；保留未知状态"


def _identity(value):
  if (type(value) is not dict or set(value) != {"pid", "birth_id"}
      or type(value["pid"]) is not int or value["pid"] <= 0
      or type(value["birth_id"]) is not str or not value["birth_id"]):
    raise Conflict(_ERROR)
  return deepcopy(value)


@dataclass(frozen=True)
class BoundHost:
  """由测试的 launch-time 绑定提供；opaque handle 不从 PID 推导。"""

  run_id: str
  manager_identity: dict
  host_identity: dict
  handle: object


class StopProbe:
  """单绑定、单次 dispatch 尝试；unknown 吸收，不恢复或扩大停止范围。"""

  def __init__(self, binding, *, transport=None, current_manager, persist_intent):
    if (type(binding) is not BoundHost or type(binding.run_id) is not str or not binding.run_id
        or binding.handle is None or transport is None
        or not callable(current_manager) or not callable(persist_intent)
        or any(not callable(getattr(transport, name, None))
          for name in ("identify", "send_graceful", "host_exited"))):
      raise Conflict(_ERROR)
    manager, host = _identity(binding.manager_identity), _identity(binding.host_identity)
    if manager["pid"] == host["pid"]:
      raise Conflict(_ERROR)
    self._binding = BoundHost(binding.run_id, manager, host, binding.handle)
    self._transport = transport
    self._current_manager = current_manager
    self._persist_intent = persist_intent
    self._phase = "bound"
    self._request_id = None
    self._signal_sent = False
    self._host_exited = False

  def snapshot(self):
    return {"phase": self._phase, "request_id": self._request_id,
      "signal_sent": self._signal_sent, "host_exited": self._host_exited}

  def _check_manager(self):
    if _identity(self._current_manager()) != self._binding.manager_identity:
      raise Conflict(_ERROR)

  def _check_bound(self):
    self._check_manager()
    if _identity(self._transport.identify(self._binding.handle)) != self._binding.host_identity:
      raise Conflict(_ERROR)
    self._check_manager()

  def request_stop(self, request_id, *, run_id, manager_identity, host_identity):
    if (self._phase != "bound" or self._request_id is not None
        or type(request_id) is not str or not request_id
        or run_id != self._binding.run_id
        or _identity(manager_identity) != self._binding.manager_identity
        or _identity(host_identity) != self._binding.host_identity):
      raise Conflict(_ERROR)
    try:
      self._check_bound()
      self._request_id = request_id
      self._phase = "dispatch_intent"
      self._persist_intent({"schema_version": 1, "kind": "fake-stop-intent", "request_id": request_id,
        "run_id": self._binding.run_id, "manager_identity": deepcopy(self._binding.manager_identity),
        "host_identity": deepcopy(self._binding.host_identity)})
      self._check_bound()
      self._transport.send_graceful(self._binding.handle)
      self._signal_sent = True
      self._phase = "signal_sent"
    except Exception:
      self._phase = "unknown"
      raise Conflict(_ERROR) from None
    return self.snapshot()

  def observe_host_exit(self):
    if self._phase not in ("signal_sent", "host_exited"):
      raise Conflict(_ERROR)
    try:
      self._check_bound()
      exited = self._transport.host_exited(self._binding.handle)
      if type(exited) is not bool:
        raise Conflict(_ERROR)
      if exited:
        self._host_exited = True
        self._phase = "host_exited"
    except Exception:
      self._phase = "unknown"
    return self.snapshot()

  def observe_release(self, observer):
    if self._phase == "unknown":
      return self.snapshot()
    if self._phase not in ("signal_sent", "host_exited"):
      raise Conflict(_ERROR)
    try:
      self._check_manager()
      observation = observer(self._binding.run_id)
      self._check_manager()
      if (type(observation) is not ReleaseObservation
          or observation.run_id != self._binding.run_id
          or _identity(observation.manager_identity) != self._binding.manager_identity
          or observation.complete is not True or observation.all_related_exited is not True):
        raise Conflict(_ERROR)
      self._phase = "released"
    except Exception:
      self._phase = "unknown"
    return self.snapshot()

  def timeout(self):
    # 普通等待到期只更新可观察状态；没有升级、重发或停止 manager 的操作。
    if self._phase != "released":
      try:
        self._check_manager()
      except Exception:
        self._phase = "unknown"
    return self.snapshot()
