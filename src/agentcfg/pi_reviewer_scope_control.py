"""受信manager私有scope RPC；不bootstrap、不确认真人、不签许可或启用产品。

所有入口仅handle，锁顺序service.mutex→账户短锁；Store不反调控制器。
分配失回执保留原nonce/槽，清理先撤内存再持久墓碑，不推断物理停止。
"""
from copy import deepcopy
import re

from .activity import OWNER_KEYS, digest
from .schema import ConfigError
from .storage import Conflict


METHODS = tuple("ordinary_reviewer_scope_" + name for name in
  ("open", "allocate_intent", "allocate_request", "verify", "retire_intent", "retire_session"))


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_SCOPE_CONTROL_INVALID") from None


def _ref(value):
  if type(value) is not str or not re.fullmatch("[0-9a-f]{32}", value): _invalid()


def _text(value):
  if type(value) is not str or not re.fullmatch("[!-~]{1,512}", value): _invalid()


class ReviewerScopeControl:
  def __init__(self, host, scope_store, *, max_controls=128, max_intents=4096, max_requests=4096):
    for value, maximum in ((max_controls, 128), (max_intents, 4096), (max_requests, 4096)):
      if type(value) is not int or not 1 <= value <= maximum: _invalid()
    self.host, self._store, self.mutex = host, scope_store, host.service.mutex
    self._owner = deepcopy(host.store.owner)
    if set(self._owner) != set(OWNER_KEYS): _invalid()
    self.max_controls, self.max_intents, self.max_requests = max_controls, max_intents, max_requests
    self._controls, self._intent_count, self._request_count = {}, 0, 0

  def _principal(self, principal):
    try:
      if principal.role != "manager" or not principal.lease_id: raise Conflict("REVIEW_SCOPE_CONTROL_MANAGER_REQUIRED")
      lease = self.host.store.read(principal.lease_id)
      if (self.host.store.owner != self._owner or lease["kind"] != "host"
          or any(lease[key] != self._owner[key] for key in OWNER_KEYS)):
        raise Conflict("REVIEW_SCOPE_CONTROL_OWNER")
      if (lease["state"] != "running" or lease["grant_generation"] != principal.grant_generation
          or self.host.store.processes.observe(lease["process_identity"]) != "alive"):
        raise Conflict("REVIEW_SCOPE_CONTROL_STALE")
      return (principal.lease_id, principal.grant_generation)
    except Conflict: raise
    except Exception: raise Conflict("REVIEW_SCOPE_CONTROL_STALE") from None

  def _after(self, principal):
    self._principal(principal)
    if self.host.service.closing: raise Conflict("REVIEW_SCOPE_CONTROL_CLOSING")

  def _control(self, principal, args, *, create=False):
    owner = self._principal(principal); identifier = args["control_id"]
    value = self._controls.get(identifier)
    if value is None:
      if not create: raise Conflict("REVIEW_SCOPE_CONTROL_UNKNOWN")
      if len(self._controls) >= self.max_controls: raise Conflict("REVIEW_SCOPE_CONTROL_CAPACITY")
      activation = digest({"domain": "reviewer-scope-session-v1", "manager_activation_id": self._owner["manager_activation_id"],
        "lease_id": owner[0], "grant_generation": owner[1], "control_id": identifier})[:32]
      value = {"owner": owner, "session_id": args["session_id"], "activation": activation,
        "session_scope": None, "state": "reserved", "intents": {}}
      self._controls[identifier] = value
    if value["owner"] != owner or "session_id" in args and value["session_id"] != args["session_id"]:
      raise Conflict("REVIEW_SCOPE_CONTROL_BINDING")
    return value

  def _intent(self, control, confirmation, *, create=False):
    row = control["intents"].get(confirmation)
    if row is None:
      if not create: raise Conflict("REVIEW_SCOPE_CONTROL_UNKNOWN")
      if self._intent_count >= self.max_intents: raise Conflict("REVIEW_SCOPE_CONTROL_CAPACITY")
      row = {"nonce": digest({"domain": "reviewer-scope-intent-v1", "activation_ref": control["activation"],
        "confirmation_ref": confirmation})[:32], "intent_ref": None, "state": "reserved", "requests": {}}
      control["intents"][confirmation] = row; self._intent_count += 1
    return row

  def _open(self, control):
    if control["state"] != "open": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED" if control["state"] == "retired" else "REVIEW_SCOPE_CONTROL_UNKNOWN")

  def open(self, principal, args):
    control = self._control(principal, args, create=True)
    if control["state"] == "retired": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED")
    ref = self._store.allocate_session(control["activation"])
    self._after(principal)
    if control["state"] == "retired": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED")
    _ref(ref)
    if control["session_scope"] is not None and control["session_scope"] != ref: _invalid()
    control.update(session_scope=ref, state="open")
    return {"control_id": args["control_id"], "session_id": control["session_id"], "session_scope": ref, "state": "open"}

  def allocate_intent(self, principal, args):
    control = self._control(principal, args); self._open(control)
    row = self._intent(control, args["confirmation_ref"], create=True)
    if row["state"] == "retired": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED")
    refs = self._store.allocate_intent(control["session_scope"], row["nonce"])
    if type(refs) is not dict or set(refs) != {"session_scope", "intent_ref"} or refs["session_scope"] != control["session_scope"]: _invalid()
    for value in refs.values(): _ref(value)
    self._after(principal); self._open(control)
    if row["state"] == "retired": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED")
    if row["intent_ref"] is not None and row["intent_ref"] != refs["intent_ref"]: _invalid()
    row.update(intent_ref=refs["intent_ref"], state="open")
    return deepcopy(refs)

  def allocate_request(self, principal, args):
    control = self._control(principal, args); self._open(control)
    row = self._intent(control, args["confirmation_ref"])
    if row["state"] != "open": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED")
    tool = args["tool_call_id"]
    if tool not in row["requests"]:
      if self._request_count >= self.max_requests: raise Conflict("REVIEW_SCOPE_CONTROL_CAPACITY")
      row["requests"][tool] = None; self._request_count += 1
    binding = {"session_scope": control["session_scope"], "intent_ref": row["intent_ref"]}
    ref = self._store.allocate_request({**binding, "tool_call_id": tool})
    _ref(ref); self._after(principal); self._open(control)
    if row["state"] != "open": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED")
    if row["requests"][tool] is not None and row["requests"][tool] != ref: _invalid()
    row["requests"][tool] = ref
    return {**binding, "request_ref": ref}

  def verify(self, principal, args):
    control = self._control(principal, args); self._open(control)
    row = self._intent(control, args["confirmation_ref"])
    if row["state"] != "open": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED")
    if row["requests"].get(args["tool_call_id"]) != args["request_ref"]: raise Conflict("REVIEW_SCOPE_CONTROL_BINDING")
    binding = {"session_scope": control["session_scope"], "intent_ref": row["intent_ref"], "request_ref": args["request_ref"]}
    if self._store.verify_current(binding) is not True: _invalid()
    self._after(principal); self._open(control)
    if row["state"] != "open": raise Conflict("REVIEW_SCOPE_CONTROL_RETIRED")
    return {"current": True, **binding}

  def operation_binding(self, principal, metadata, *, session_id):
    """受信本地绑定接缝，不注册RPC；锁顺序service→account。"""
    with self.mutex:
      return self._operation_binding_borrowed(principal, metadata, session_id=session_id)

  def _operation_binding_borrowed(self, principal, metadata, *, session_id):
    """调用者必须已持service mutex；不获取service锁、不分配引用。"""
    try:
      fields = {"control_id", "confirmation_ref", "tool_call_id", "request_ref"}
      if type(metadata) is not dict or any(type(key) is not str for key in metadata) or set(metadata) != fields: _invalid()
      for key in fields: (_text if key == "tool_call_id" else _ref)(metadata[key])
      _text(session_id)
      self._principal(principal)
      if self.host.service.closing: raise Conflict("REVIEW_SCOPE_CONTROL_CLOSING")
      result = self.verify(principal, {**metadata, "session_id": session_id})
      return {key: result[key] for key in ("session_scope", "intent_ref", "request_ref")}
    except ConfigError as error:
      if error.code in ("PI_RISK_REVIEW_SCOPE_CONTROL_INVALID", "PI_RISK_REVIEW_SCOPE_INVALID", "PI_RISK_REVIEW_AUTHORITY_INVALID"): raise error from None
      raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None
    except Conflict as error:
      if re.fullmatch("REVIEW_(?:SCOPE|AUTHORITY|ACCOUNT)_[A-Z_]+", str(error)): raise error from None
      raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None
    except Exception: raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None

  def retire_operation_intent(self, principal, metadata, *, session_id, intent_ref, request_ref):
    """只清理已属原行的意图，不要求authority当前；不是RPC或current资格。"""
    with self.mutex:
      return self._retire_operation_intent_borrowed(principal, metadata, session_id=session_id,
        intent_ref=intent_ref, request_ref=request_ref)

  def _retire_operation_intent_borrowed(self, principal, metadata, *, session_id, intent_ref, request_ref):
    """可信调用者已持service锁；只核原owned映射，不分配或授予current资格。"""
    try:
      fields = {"control_id", "confirmation_ref", "tool_call_id", "request_ref"}
      if type(metadata) is not dict or any(type(key) is not str for key in metadata) or set(metadata) != fields: _invalid()
      for key in fields: (_text if key == "tool_call_id" else _ref)(metadata[key])
      _text(session_id); _ref(intent_ref); _ref(request_ref)
      control = self._control(principal, {**metadata, "session_id": session_id})
      if control["state"] not in ("open", "retired"): raise Conflict("REVIEW_SCOPE_CONTROL_UNKNOWN")
      row = self._intent(control, metadata["confirmation_ref"])
      if (row["intent_ref"] != intent_ref or metadata["request_ref"] != request_ref or
          row["requests"].get(metadata["tool_call_id"]) != request_ref):
        raise Conflict("REVIEW_SCOPE_CONTROL_BINDING")
      return self.retire_intent(principal, {"control_id": metadata["control_id"],
        "confirmation_ref": metadata["confirmation_ref"]})
    except ConfigError as error:
      if error.code in ("PI_RISK_REVIEW_SCOPE_CONTROL_INVALID", "PI_RISK_REVIEW_SCOPE_INVALID", "PI_RISK_REVIEW_AUTHORITY_INVALID"): raise error from None
      raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None
    except Conflict as error:
      if re.fullmatch("REVIEW_(?:SCOPE|AUTHORITY|ACCOUNT)_[A-Z_]+", str(error)): raise error from None
      raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None
    except Exception: raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None

  def retire_session(self, principal, args):
    control = self._control(principal, args, create=True)
    control["state"] = "retired"
    for row in control["intents"].values(): row["state"] = "retired"
    self._store.retire_session_activation(control["activation"])
    return {"control_id": args["control_id"], "state": "retired"}

  def retire_intent(self, principal, args):
    control = self._control(principal, args)
    if control["state"] == "retired": row = self._intent(control, args["confirmation_ref"])
    else:
      self._open(control); row = self._intent(control, args["confirmation_ref"], create=True)
    row["state"] = "retired"
    self._store.retire_intent_confirmation(control["session_scope"], row["nonce"])
    return {"control_id": args["control_id"], "confirmation_ref": args["confirmation_ref"], "state": "retired"}

  def handle(self, principal, method, args):
    try:
      with self.mutex:
        if method not in METHODS: _invalid()
        name = method.removeprefix("ordinary_reviewer_scope_")
        fields = {"control_id", "session_id"} if name in ("open", "retire_session") else {"control_id", "confirmation_ref"}
        if name in ("allocate_request", "verify"): fields.add("tool_call_id")
        if name == "verify": fields.add("request_ref")
        if type(args) is not dict or set(args) != fields: _invalid()
        for key in fields:
          (_text if key in ("session_id", "tool_call_id") else _ref)(args[key])
        self._principal(principal)
        if self.host.service.closing and name not in ("retire_intent", "retire_session"):
          raise Conflict("REVIEW_SCOPE_CONTROL_CLOSING")
        return getattr(self, name)(principal, args)
    except ConfigError as error:
      if error.code in ("PI_RISK_REVIEW_SCOPE_CONTROL_INVALID", "PI_RISK_REVIEW_SCOPE_INVALID", "PI_RISK_REVIEW_AUTHORITY_INVALID"): raise error from None
      raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None
    except Conflict as error:
      if re.fullmatch("REVIEW_(?:SCOPE|AUTHORITY|ACCOUNT)_[A-Z_]+", str(error)): raise error from None
      raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None
    except Exception: raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE") from None
