"""原PreparedOperation与持久scope的受信私有绑定，不签许可或启用产品factory。

service→Admission→account锁序由可信调用者保证。Admission锁内的borrowed hook
要求外层已持service mutex，不反调Admission或取得service锁，不等待RPC/SDK。
本地缓存不是authority证明；issue/consume每次重新核验持久scope及原manager。
唯一性仅覆盖此binder的一份Admission；多bridge独立map不证明全activation唯一。
"""
from copy import deepcopy
import re

from .activity import digest
from .pi_operation_admission import context, resolution
from .schema import ConfigError
from .storage import Conflict


FIELDS = {"schema_version", "operation_id", "request_id", "context", "resolution", "private_input_ref", "operation_digest"}
META = {"control_id", "confirmation_ref", "tool_call_id", "request_ref"}
REFS = {"session_scope", "intent_ref", "request_ref"}
_ABSENT = object()


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_OPERATION_SCOPE_INVALID") from None


def _hex(value, count=32):
  if type(value) is not str or not re.fullmatch("[0-9a-f]{%d}" % count, value): _invalid()


def _plain(value, depth=0, budget=None):
  # 先拒绝自定义类型，避免验证/深拷贝触发getter、coercion或自有dict方法。
  if budget is None: budget = [0]
  budget[0] += 1
  if depth > 32 or budget[0] > 65536: _invalid()
  if value is None or type(value) in (bool, int, str): return
  if type(value) is list:
    for item in value: _plain(item, depth + 1, budget)
    return
  if type(value) is dict:
    for key, item in value.items():
      if type(key) is not str: _invalid()
      _plain(item, depth + 1, budget)
    return
  _invalid()


def _prepared(value):
  _plain(value)
  if type(value) is not dict or set(value) != FIELDS or type(value["schema_version"]) is not int or value["schema_version"] != 1: _invalid()
  for key in ("operation_id", "request_id", "private_input_ref"): _hex(value[key])
  _hex(value["operation_digest"], 64)
  try:
    context(value["context"]); resolution(value["resolution"])
    if digest({key: item for key, item in value.items() if key != "operation_digest"}) != value["operation_digest"]: _invalid()
  except Exception: _invalid()
  return deepcopy(value)


def _metadata(value):
  _plain(value)
  if type(value) is not dict or set(value) != META: _invalid()
  for key in META:
    if key == "tool_call_id":
      if type(value[key]) is not str or not re.fullmatch("[!-~]{1,512}", value[key]): _invalid()
    else: _hex(value[key])
  return deepcopy(value)


def _scopes(value):
  _plain(value)
  if type(value) is not dict or set(value) != REFS: _invalid()
  for item in value.values(): _hex(item)
  return deepcopy(value)


class ReviewerOperationScopeBindings:
  def __init__(self, admissions, scope_control, principal, *, max_operations=4096, owner=None):
    if type(max_operations) is not int or not 1 <= max_operations <= 4096: _invalid()
    self._admissions, self._control, self._principal = admissions, scope_control, deepcopy(principal)
    self.mutex, self.max_operations = scope_control.mutex, max_operations
    self._bindings, self._requests = {}, {}
    self._scope_owner = object() if owner is None else owner
    self._scope_binder_token = object()
    with self.mutex:
      admissions._claim_reviewer_scope_owner(self._scope_owner, binder=self._scope_binder_token)

  def _retire(self, entry, *, revoke=False):
    entry["state"] = "retired"
    if revoke:
      # 只有已经核对原Admission投影的可信槽可撤销；未知/伪造输入不产生副作用。
      self._admissions.revoke(entry["prepared"]["operation_id"])

  def bind(self, prepared, metadata):
    with self.mutex:
      supplied = _prepared(prepared)
      identifier = supplied["operation_id"]
      entry = self._bindings.get(identifier)
      try: original = self._admissions.prepared(identifier)
      except Exception:
        if entry is not None: self._retire(entry, revoke=True)
        raise Conflict("REVIEW_OPERATION_SCOPE_UNAVAILABLE") from None
      if original != supplied:
        if entry is not None: self._retire(entry, revoke=True)
        raise Conflict("REVIEW_OPERATION_SCOPE_BINDING")
      if entry is None:
        if len(self._bindings) >= self.max_operations:
          self._admissions.revoke(identifier)
          raise Conflict("REVIEW_OPERATION_SCOPE_CAPACITY")
        entry = {"prepared": original, "metadata": None, "refs": None, "state": "reserved"}
        self._bindings[identifier] = entry
      try:
        previous = self._requests.get(original["request_id"])
        if previous is not None and previous != identifier:
          self._retire(self._bindings[previous], revoke=True)
          raise Conflict("REVIEW_OPERATION_SCOPE_REQUEST_REUSED")
        self._requests[original["request_id"]] = identifier
        metadata = _metadata(metadata)
        if entry["state"] == "retired": raise Conflict("REVIEW_OPERATION_SCOPE_RETIRED")
        if entry["prepared"] != original or entry["metadata"] is not None and entry["metadata"] != metadata:
          raise Conflict("REVIEW_OPERATION_SCOPE_BINDING")
        entry["metadata"] = metadata
        current = original["context"]
        if current["profile"] != "pi-full" or current["activation_id"] != self._control._owner["manager_activation_id"]:
          raise Conflict("REVIEW_OPERATION_SCOPE_BINDING")
        refs = _scopes(self._control._operation_binding_borrowed(self._principal, metadata, session_id=current["session_id"]))
        if current["user_intent_ref"] != refs["intent_ref"] or original["request_id"] != refs["request_ref"]:
          raise Conflict("REVIEW_OPERATION_SCOPE_BINDING")
        if entry["refs"] is not None and entry["refs"] != refs: raise Conflict("REVIEW_OPERATION_SCOPE_BINDING")
        entry.update(refs=deepcopy(refs), state="bound")
        return deepcopy(refs)
      except Exception:
        self._retire(entry, revoke=True)
        raise Conflict("REVIEW_OPERATION_SCOPE_UNQUALIFIED") from None

  def _local(self, prepared):
    value = _prepared(prepared)
    entry = self._bindings.get(value["operation_id"])
    if entry is None or entry["state"] != "bound": raise Conflict("REVIEW_OPERATION_SCOPE_RETIRED")
    if entry["prepared"] != value: raise Conflict("REVIEW_OPERATION_SCOPE_BINDING")
    return entry

  def scopes_for_prepared(self, prepared):
    """只查本地原映射，不把它当live authority资格。"""
    with self.mutex:
      return deepcopy(self._local(prepared)["refs"])

  def _current_borrowed(self, prepared, *, scopes=_ABSENT, current=_ABSENT):
    entry = None
    try:
      # 仅定位已知本地槽；不反调prepared/status/revoke或service锁。
      if type(prepared) is dict and type(prepared.get("operation_id")) is str:
        entry = self._bindings.get(prepared["operation_id"])
      checked = self._local(prepared)
      if scopes is not _ABSENT:
        if _scopes(scopes) != checked["refs"]: _invalid()
      if current is not _ABSENT:
        _plain(current)
        if context(current) != checked["prepared"]["context"]: _invalid()
      refs = _scopes(self._control._operation_binding_borrowed(self._principal, checked["metadata"],
        session_id=checked["prepared"]["context"]["session_id"]))
      if refs != checked["refs"]: _invalid()
      return True
    except Exception:
      if entry is not None: self._retire(entry)
      return False

  def scope_current(self, prepared, scopes):
    with self.mutex:
      return self._current_borrowed(prepared, scopes=scopes)

  def reviewer_current_borrowed(self, prepared, current):
    """Admission hook：调用者必须已持service mutex；只读本地及账户短锁。"""
    return self._current_borrowed(prepared, current=current)
