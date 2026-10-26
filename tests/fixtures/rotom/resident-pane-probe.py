"""P-PANE 单周期假模型；不提供端点、PTY、子进程、信号或生产恢复许可。"""

from copy import deepcopy
from dataclasses import dataclass

from agentcfg.run_owners import ReleaseObservation
from agentcfg.storage import Conflict


_ERROR = "合成驻留状态不能确认；保留未知且不重放"
_BINDING_FIELDS = {"container_id", "generation", "manager_identity", "manager_code_identity",
  "control_protocol", "endpoint_identity", "terminal_ref", "old_run"}
_REQUEST_FIELDS = {"request_id", "container_id", "generation", "op_id", "new_run",
  "deployment_digest", "session_ref", "terminal_ref"}


def _text(value):
  return type(value) is str and bool(value)


def _manager(value):
  return (type(value) is dict and set(value) == {"pid", "birth_id"}
    and type(value["pid"]) is int and value["pid"] > 0 and _text(value["birth_id"]))


def _terminal(value):
  return (type(value) is dict and set(value) == {"server_id", "server_generation", "pane_id", "cwd"}
    and type(value["server_generation"]) is int and value["server_generation"] > 0
    and all(_text(value[key]) for key in ("server_id", "pane_id", "cwd")))


def _session(value):
  return (type(value) is dict and set(value) == {"agent", "backend", "native_home_ref", "native_ref"}
    and all(_text(value[key]) for key in ("agent", "backend", "native_ref"))
    and type(value["native_home_ref"]) is dict and set(value["native_home_ref"]) == {"kind", "ref"}
    and all(_text(child) for child in value["native_home_ref"].values()))


def _binding_shape(value):
  return (type(value) is dict and set(value) == _BINDING_FIELDS
    and type(value["generation"]) is int and value["generation"] > 0
    and all(_text(value[key]) for key in ("container_id", "manager_code_identity", "control_protocol", "old_run"))
    and _manager(value["manager_identity"]) and _terminal(value["terminal_ref"])
    and type(value["endpoint_identity"]) is dict and set(value["endpoint_identity"]) == {"endpoint_id", "generation"}
    and _text(value["endpoint_identity"]["endpoint_id"])
    and type(value["endpoint_identity"]["generation"]) is int and value["endpoint_identity"]["generation"] > 0)


@dataclass(frozen=True)
class LeaseObservation:
  """受信假观察输入；三个 true 不冒充实际租约释放证明。"""

  run_id: str
  manager_identity: dict
  instance_released: bool
  native_home_released: bool
  runtime_released: bool


class ResidentPaneProbe:
  def __init__(self, binding, *, current_binding, run_context, approved_resume=None):
    if not _binding_shape(binding) or not callable(current_binding):
      raise Conflict(_ERROR)
    self._binding = deepcopy(binding)
    self._current_binding = current_binding
    self._run_context = run_context
    self._phase = "running"
    self._current_run = binding["old_run"]
    self._session_sealed = False
    self._approved = None
    self._request_id = None
    self._dispatch_complete = False
    self._audit = []
    if approved_resume is not None:
      self.prepare_resume(approved_resume)

  def snapshot(self):
    return {"phase": self._phase, "current_run": self._current_run,
      "session_sealed": self._session_sealed, "request_id": self._request_id,
      "has_run_context": self._run_context is not None, "audit": list(self._audit)}

  def _check_binding(self):
    current = self._current_binding()
    if not _binding_shape(current) or current != self._binding:
      raise Conflict(_ERROR)

  def _exact_manager(self, value):
    return _manager(value) and value == self._binding["manager_identity"]

  def park(self, release_observer, lease_observer, *, session_sealed):
    if (self._phase != "running" or self._current_run != self._binding["old_run"]
        or type(session_sealed) is not bool):
      raise Conflict(_ERROR)
    self._phase = "parking"
    try:
      self._check_binding()
      release = release_observer(self._binding["old_run"])
      self._check_binding()
      if (type(release) is not ReleaseObservation or release.run_id != self._binding["old_run"]
          or not self._exact_manager(release.manager_identity)
          or release.complete is not True or release.all_related_exited is not True):
        raise Conflict(_ERROR)
      leases = lease_observer(self._binding["old_run"])
      self._check_binding()
      if (type(leases) is not LeaseObservation or leases.run_id != self._binding["old_run"]
          or not self._exact_manager(leases.manager_identity)
          or any(value is not True for value in (leases.instance_released, leases.native_home_released, leases.runtime_released))):
        raise Conflict(_ERROR)
      self._run_context = None
      self._session_sealed = session_sealed
      self._audit.append("old-run-released")
      self._phase = "parked"
    except Exception:
      self._phase = "unknown"
    return self.snapshot()

  def _request_shape(self, request):
    return (type(request) is dict and set(request) == _REQUEST_FIELDS
      and type(request["generation"]) is int and request["generation"] > 0
      and all(_text(request[key]) for key in ("request_id", "container_id", "op_id", "new_run", "deployment_digest"))
      and len(request["deployment_digest"]) == 64
      and all(char in "0123456789abcdef" for char in request["deployment_digest"])
      and _session(request["session_ref"]) and _terminal(request["terminal_ref"])
      and request["container_id"] == self._binding["container_id"]
      and request["generation"] == self._binding["generation"]
      and request["terminal_ref"] == self._binding["terminal_ref"]
      and request["new_run"] != self._binding["old_run"])

  def prepare_resume(self, approved_request):
    # 仅消费测试给出的明确批准；不生成或推断实际维护许可。
    if (self._phase not in ("running", "parked") or self._approved is not None
        or self._request_id is not None or not self._request_shape(approved_request)):
      raise Conflict(_ERROR)
    self._approved = deepcopy(approved_request)

  def resume(self, request, *, persist_intent, consume_permit, launch_once):
    if (self._phase != "parked" or not self._session_sealed or self._request_id is not None
        or self._approved is None or not self._request_shape(request) or request != self._approved):
      raise Conflict(_ERROR)
    try:
      self._check_binding()
    except Exception:
      self._phase = "unknown"
      raise Conflict(_ERROR) from None
    self._request_id = request["request_id"]
    self._phase = "resume_pending"
    try:
      persist_intent(deepcopy(self._approved))
      self._check_binding()
      if consume_permit(deepcopy(self._approved)) is not True:
        raise Conflict(_ERROR)
      self._check_binding()
      launch_once(deepcopy(self._approved))
      self._check_binding()
      self._dispatch_complete = True
      self._audit.append("new-run-dispatched")
    except Exception:
      self._phase = "unknown"
      raise Conflict(_ERROR) from None
    return self.snapshot()

  def confirm_loaded(self, observer):
    if self._phase == "unknown":
      return self.snapshot()
    if self._phase != "resume_pending" or not self._dispatch_complete:
      raise Conflict(_ERROR)
    try:
      self._check_binding()
      observation = observer()
      self._check_binding()
      if (type(observation) is not dict or set(observation) != {"kind", "run_id", "session_ref"}
          or observation["run_id"] != self._approved["new_run"]
          or not _session(observation["session_ref"]) or observation["session_ref"] != self._approved["session_ref"]
          or observation["kind"] not in ("queued", "loaded")):
        raise Conflict(_ERROR)
      if observation["kind"] == "loaded":
        self._current_run = self._approved["new_run"]
        self._phase = "running"
        self._audit.append("new-session-loaded")
    except Exception:
      self._phase = "unknown"
    return self.snapshot()
