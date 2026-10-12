"""manager私有通道的会话准入控制，不接受模型参数自报审批来源或后端。

human来源意味着受信SDK/UI适配器已确认，不是服务端对真人身份的独立证明。
控制、请求及取消墓碑保留到activation结束；不淘汰条目重新开放旧许可。
"""

from copy import deepcopy
import json
import re

from .activity import OWNER_KEYS
from .pi_admitted_files import FileOperationAdmissions
from .pi_operation_admission import OperationAdmissions, context, encode_private_input
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict


def identifier(value):
  if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
    raise ConfigError("pi-admission-control-id")
  return value


class FileAdmissionControl:
  def __init__(self, operations, *, max_controls=128, max_requests=4096, max_private_bytes=32 * 1024 * 1024,
      shell_bridge_factory=None, mcp_bridge_factory=None, shared_admissions=None, reviewer_scope_control=None):
    if shared_admissions is not None and (type(shared_admissions) is not OperationAdmissions or
        shared_admissions.activation_id != operations.host.store.owner["manager_activation_id"]):
      raise ConfigError("pi-operation-shared-admissions")
    if reviewer_scope_control is not None:
      from .pi_reviewer_scope_control import ReviewerScopeControl
      if (type(reviewer_scope_control) is not ReviewerScopeControl or shared_admissions is None or
          reviewer_scope_control.host is not operations.host or reviewer_scope_control.mutex is not operations.host.service.mutex):
        raise ConfigError("pi-admission-reviewer-scope")
    for value in (max_controls, max_requests, max_private_bytes):
      if type(value) is not int or value < 1: raise ConfigError("pi-admission-control-limit")
    if shell_bridge_factory is not None and not callable(shell_bridge_factory):
      raise ConfigError("pi-admission-shell-factory")
    if mcp_bridge_factory is not None and (not callable(mcp_bridge_factory) or shared_admissions is None):
      raise ConfigError("pi-admission-mcp-factory")
    self.operations, self.host = operations, operations.host
    self.mutex = self.host.service.mutex
    self.max_controls, self.max_requests, self.max_private_bytes = max_controls, max_requests, max_private_bytes
    self.controls, self.requests, self.operation_requests = {}, {}, {}
    self.private_bytes = 0
    self._reviewer_scope_control, self._shared_admissions = reviewer_scope_control, shared_admissions
    self._reviewer_decision_owner = None
    self._scope_bindings, self._scope_principal = None, None
    self._scope_owner = object() if reviewer_scope_control is not None else None
    if self._scope_owner is not None:
      # 同仓库Host与canonical Admission永久占槽，失败装配也不得重开。
      with self.mutex:
        if getattr(self.host, "_scoped_admission_owner", None) is not None:
          raise Conflict("REVIEW_SCOPE_OWNER_ALREADY_BOUND")
        shared_admissions._claim_reviewer_scope_owner(self._scope_owner)
        self.host._scoped_admission_owner = self._scope_owner
    # None保持原fake/人工工厂契约；只有显式受信注入才传共享ledger关键字。
    bridge_options = {"context_provider": self._context}
    if shared_admissions is not None: bridge_options["admissions"] = shared_admissions
    self.bridge = FileOperationAdmissions(operations, **bridge_options)
    self.shell_bridge = None
    if shell_bridge_factory is not None:
      if shared_admissions is None:
        self.shell_bridge = shell_bridge_factory(operations, **bridge_options)
      else:
        try:
          self.shell_bridge = shell_bridge_factory(operations, **bridge_options)
          if self.shell_bridge.ledger is not shared_admissions: raise ValueError()
        except Exception: raise ConfigError("pi-admission-shared-admissions") from None
    self.mcp_bridge = None
    if mcp_bridge_factory is not None:
      self.mcp_bridge = mcp_bridge_factory(operations, **bridge_options)
      if self.mcp_bridge.ledger is not shared_admissions: raise ConfigError("pi-admission-shared-admissions")

  def _principal(self, principal):
    self.bridge._principal(principal)
    lease = self.host.store.read(principal.lease_id)
    if lease["kind"] != "host" or any(lease[key] != self.host.store.owner[key] for key in OWNER_KEYS):
      raise Conflict("OPERATION_CONTROL_OWNER")
    return (principal.lease_id, principal.grant_generation)

  def _control(self, principal, control_id, *, create=False):
    owner = self._principal(principal)
    control_id = identifier(control_id)
    value = self.controls.get(control_id)
    if value is None:
      if not create: raise Conflict("OPERATION_CONTROL_UNKNOWN")
      if len(self.controls) >= self.max_controls: raise Conflict("OPERATION_CAPACITY")
      value = {"principal": owner, "session_id": None, "state": "reserved"}
      self.controls[control_id] = value
    if value["principal"] != owner: raise Conflict("OPERATION_CONTROL_OWNER")
    return value

  def _request(self, principal, control_id, request_id, *, create=False):
    control = self._control(principal, control_id)
    request_id = identifier(request_id)
    value = self.requests.get(request_id)
    if value is None:
      if not create: raise Conflict("OPERATION_UNKNOWN")
      if len(self.requests) >= self.max_requests: raise Conflict("OPERATION_CAPACITY")
      value = {"control_id": control_id, "request_id": request_id, "state": "new", "context": None,
        "private": None, "prepared": None, "bridge": None, "scoped": False, "metadata": None,
        "scope_refs": None, "scoped_owned": False, "scoped_bound": False, "scope_principal": None,
        "scope_cleanup": "not-needed"}
      self.requests[request_id] = value
    if value["control_id"] != control_id: raise Conflict("OPERATION_IDEMPOTENCY_CONFLICT")
    return control, value

  def _context(self, request_id):
    row = self.requests[request_id]
    if row["state"] != "prepared" or self.controls[row["control_id"]]["state"] != "open":
      raise Conflict("OPERATION_NOT_PENDING")
    self._scope_fresh(row)
    return row["context"]

  def _scope_metadata(self, value):
    if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != {"control_id", "confirmation_ref", "tool_call_id", "request_ref"}:
      raise ConfigError("pi-admission-reviewer-scope")
    for key, item in value.items():
      pattern = r"[!-~]{1,512}" if key == "tool_call_id" else r"[0-9a-f]{32}"
      if type(item) is not str or not re.fullmatch(pattern, item): raise ConfigError("pi-admission-reviewer-scope")
    return deepcopy(value)

  def _scope_binder(self, principal):
    owner = (principal.lease_id, principal.grant_generation)
    if self._scope_bindings is None:
      from .pi_reviewer_operation_scopes import ReviewerOperationScopeBindings
      self._scope_bindings = ReviewerOperationScopeBindings(self._shared_admissions, self._reviewer_scope_control, principal, owner=self._scope_owner)
      self._scope_principal = owner
    elif self._scope_principal != owner: raise Conflict("OPERATION_SCOPE_MANAGER_STALE")
    return self._scope_bindings

  def _scope_fresh(self, row):
    if not row["scoped"]: return
    if self._reviewer_scope_control is None: raise Conflict("OPERATION_SCOPE_UNAVAILABLE")
    if row["scoped_bound"]:
      if self._scope_bindings.reviewer_current_borrowed(row["prepared"], row["context"]) is not True:
        raise Conflict("OPERATION_SCOPE_UNQUALIFIED")
    else:
      refs = self._reviewer_scope_control._operation_binding_borrowed(row["scope_principal"], row["metadata"],
        session_id=row["context"]["session_id"])
      if refs["request_ref"] != row["request_id"] or refs["intent_ref"] != row["context"]["user_intent_ref"]:
        raise Conflict("OPERATION_SCOPE_UNQUALIFIED")
      row["scope_refs"] = deepcopy(refs)
      row["scoped_owned"] = True

  def _cancel_local(self, principal, row):
    if not row["scoped"] or row["state"] != "consumed": row["state"] = "canceled"
    if row["private"] is not None:
      self.private_bytes -= len(row["private"])
      row["private"] = None
    if row["prepared"] is not None:
      row["bridge"].revoke(principal, row["prepared"]["operation_id"])

  def _cancel(self, principal, row):
    # 先记本地墓碑；清理未知不恢复分配/Writer，也不自动重复持久调用。
    if not row["scoped"]:
      self._cancel_local(principal, row)
      return
    failed = False
    siblings = [row]
    if row["scoped_owned"]:
      siblings += [other for other in self.requests.values() if other is not row and other["scoped_owned"] and
        other["scope_refs"]["intent_ref"] == row["scope_refs"]["intent_ref"] and
        other["scope_refs"]["session_scope"] == row["scope_refs"]["session_scope"]]
    for other in siblings:
      try: self._cancel_local(principal, other)
      except Exception: failed = True
    if row["scoped"]:
      if self._reviewer_scope_control is None or row["metadata"] is None or row["context"] is None:
        row["scope_cleanup"] = "unverified"
      else:
        row["scope_cleanup"] = "unknown"
        try:
          self._reviewer_scope_control._retire_operation_intent_borrowed(principal, row["metadata"],
            session_id=row["context"]["session_id"], intent_ref=row["context"]["user_intent_ref"], request_ref=row["request_id"])
          for other in siblings: other["scope_cleanup"] = "confirmed"
        except Exception: failed = True
      if failed: raise Conflict("OPERATION_SCOPE_CLEANUP_UNKNOWN") from None
    elif failed: raise Conflict("OPERATION_CANCEL_INCOMPLETE") from None

  def _pending(self, principal, row, fresh):
    control = self._control(principal, row["control_id"])
    if control["state"] != "open" or row["state"] != "prepared": raise Conflict("OPERATION_NOT_PENDING")
    try:
      current = context(fresh)
      if current != row["context"]: raise Conflict("OPERATION_CONTEXT_STALE")
      self._scope_fresh(row)
      return current
    except Exception:
      self._cancel(principal, row)
      raise

  def _operation(self, principal, operation_id):
    identifier(operation_id)
    row = self.operation_requests.get(operation_id)
    if row is None: raise Conflict("OPERATION_UNKNOWN")
    self._control(principal, row["control_id"])
    return row

  def open(self, principal, args):
    closed(args, ("control_id", "session_id"))
    session_id = args["session_id"]
    if (type(session_id) is not str or not session_id or len(session_id) > 512
        or any(ord(c) < 32 for c in session_id)): raise ConfigError("pi-admission-session-id")
    encode_private_input(session_id)
    value = self._control(principal, args["control_id"], create=True)
    if value["state"] == "retired": raise Conflict("OPERATION_CONTROL_RETIRED")
    if value["session_id"] is not None and value["session_id"] != session_id:
      raise Conflict("OPERATION_IDEMPOTENCY_CONFLICT")
    value.update(state="open", session_id=session_id)
    return {"control_id": args["control_id"], "session_id": session_id, "state": "open"}

  def prepare(self, principal, args):
    closed(args, ("control_id", "request_id", "context", "tool_name", "input"), ("reviewer_scope",))
    control, row = self._request(principal, args["control_id"], args["request_id"], create=True)
    if control["state"] != "open" or row["state"] not in ("new", "prepared"):
      raise Conflict("OPERATION_NOT_PENDING")
    try:
      scoped = "reviewer_scope" in args
      if row["state"] == "new":
        row["scoped"] = scoped
        row["scope_principal"] = deepcopy(principal) if scoped else None
        if scoped: row["metadata"] = self._scope_metadata(args["reviewer_scope"])
      metadata = self._scope_metadata(args["reviewer_scope"]) if scoped else None
      if row["scoped"] != scoped or row["metadata"] != metadata: raise Conflict("OPERATION_IDEMPOTENCY_CONFLICT")
      current = context(args["context"])
      if current["session_id"] != control["session_id"]: raise Conflict("OPERATION_CONTEXT_STALE")
      private = encode_private_input({"tool_name": args["tool_name"], "input": args["input"]},
        allow_finite_numbers=args["tool_name"] == "mcp")
      if row["state"] == "prepared":
        self._pending(principal, row, current)
        if private != row["private"]: raise Conflict("OPERATION_IDEMPOTENCY_CONFLICT")
        return deepcopy(row["prepared"])
      now = int(self.operations.now().timestamp() * 1000)
      if not now < current["deadline_ms"] <= now + 300000: raise Conflict("OPERATION_EXPIRED")
      if self.private_bytes + len(private) > self.max_private_bytes: raise Conflict("OPERATION_CAPACITY")
      bridge = self.mcp_bridge if args["tool_name"] == "mcp" else self.shell_bridge if args["tool_name"] == "bash" else self.bridge
      row["bridge"] = bridge
      if bridge is None: raise Conflict("MCP_CAPABILITY_UNAVAILABLE" if args["tool_name"] == "mcp" else "SHELL_BACKEND_UNAVAILABLE")
      row.update(context=current, private=private, state="prepared")
      self.private_bytes += len(private)
      if scoped:
        if self._reviewer_scope_control is None: raise Conflict("OPERATION_SCOPE_UNAVAILABLE")
        self._scope_binder(principal)
        self._scope_fresh(row)
      prepared = bridge.prepare(principal, row["request_id"], args["tool_name"], args["input"])
      if scoped:
        # 未返回可信原投影时不猜测桥内部operation ID，更不撤销别人的记录。
        encode_private_input(prepared)
        fields = {"schema_version", "operation_id", "request_id", "context", "resolution", "private_input_ref", "operation_digest"}
        if (type(prepared) is not dict or set(prepared) != fields or
            type(prepared["operation_id"]) is not str or not re.fullmatch(r"[0-9a-f]{32}", prepared["operation_id"]) or
            prepared["request_id"] != row["request_id"] or prepared["context"] != row["context"] or
            self._shared_admissions.prepared(prepared["operation_id"]) != prepared):
          raise Conflict("OPERATION_SCOPE_UNQUALIFIED")
      row["prepared"] = deepcopy(prepared)
      self.operation_requests[prepared["operation_id"]] = row
      if scoped:
        refs = self._scope_bindings.bind(prepared, row["metadata"])
        if refs != row["scope_refs"]: raise Conflict("OPERATION_SCOPE_UNQUALIFIED")
        row["scope_refs"], row["scoped_bound"] = deepcopy(refs), True
      return prepared
    except Exception as error:
      if row["state"] != "canceled": self._cancel(principal, row)
      if row["scoped"] and not isinstance(error, (ConfigError, Conflict)):
        raise Conflict("OPERATION_SCOPE_UNQUALIFIED") from None
      raise

  def issue(self, principal, args):
    closed(args, ("operation_id", "context"))
    row = self._operation(principal, args["operation_id"])
    self._pending(principal, row, args["context"])
    try:
      return row["bridge"].issue(principal, args["operation_id"],
        operation_digest=row["prepared"]["operation_digest"], source="human")
    except Exception as error:
      self._cancel(principal, row)
      if row["scoped"] and not isinstance(error, (ConfigError, Conflict)):
        raise Conflict("OPERATION_SCOPE_UNQUALIFIED") from None
      raise

  def _issue_reviewer_prepared(self, prepared, *, current):
    """非RPC受信接缝：仅原scoped行与原bridge签发，source不可由参数选择。"""
    supplied = json.loads(encode_private_input(prepared))
    fresh = context(current)
    if type(supplied) is not dict or type(supplied.get("operation_id")) is not str:
      raise ConfigError("PI_RISK_REVIEW_BRIDGE_INVALID")
    with self.mutex:
      row = self.operation_requests.get(supplied["operation_id"])
      if (self._reviewer_decision_owner is None or self._reviewer_scope_control is None or self._shared_admissions is None or row is None or
          not row["scoped_bound"] or row["scope_principal"] is None or supplied != row["prepared"]):
        # 未核对原行的输入不取得撤销/清理别人的能力。
        raise Conflict("REVIEW_BRIDGE_BINDING_MISMATCH")
      principal = row["scope_principal"]
      self._operation(principal, supplied["operation_id"])
      self._pending(principal, row, fresh)
      try:
        return row["bridge"].issue(principal, supplied["operation_id"],
          operation_digest=row["prepared"]["operation_digest"], source="reviewer",
          reviewer_identity=row["context"]["reviewer_identity"])
      except Exception as error:
        # 已知原行失败沿既有whole-intent清理；不重签或删除未知permit映射。
        try: self._cancel(principal, row)
        except Exception: pass
        if not isinstance(error, (ConfigError, Conflict)):
          raise Conflict("REVIEW_PERMIT_ISSUE_UNKNOWN") from None
        raise error from None

  def issue_deterministic(self, principal, args):
    """manager固定来源入口；只有原prepared明确为确定性等级才能签发。"""
    closed(args, ("operation_id", "context"))
    row = self._operation(principal, args["operation_id"])
    self._pending(principal, row, args["context"])
    if row["prepared"]["resolution"]["policy"].get("approval") != "deterministic-policy":
      raise Conflict("OPERATION_APPROVAL_SOURCE_MISMATCH")
    try:
      return row["bridge"].issue(principal, args["operation_id"],
        operation_digest=row["prepared"]["operation_digest"], source="deterministic-policy")
    except Exception as error:
      # 原行保留一次签发映射；丢回执不重签、不猜许可、不释放执行Writer。
      try: self._cancel(principal, row)
      except Exception: pass
      if not isinstance(error, (ConfigError, Conflict)):
        raise Conflict("OPERATION_DETERMINISTIC_ISSUE_UNKNOWN") from None
      raise error from None

  def consume(self, principal, args):
    closed(args, ("permit", "context"))
    permit = args["permit"]
    if type(permit) is not dict or type(permit.get("permit_id")) is not str:
      raise Conflict("OPERATION_PERMIT_UNKNOWN")
    # 从服务端签发映射取operation，不相信调用者permit中的operation_id。
    matches = [(bridge, bridge.permits[permit["permit_id"]]) for bridge in (self.bridge, self.shell_bridge, self.mcp_bridge)
      if bridge is not None and permit["permit_id"] in bridge.permits]
    if not matches: raise Conflict("OPERATION_PERMIT_UNKNOWN")
    if len(matches) != 1: raise Conflict("OPERATION_PERMIT_AMBIGUOUS")
    bridge, operation_id = matches[0]
    row = self._operation(principal, operation_id)
    if row["bridge"] is not bridge: raise Conflict("OPERATION_PERMIT_BRIDGE")
    self._pending(principal, row, args["context"])
    try: return bridge.consume(principal, permit)
    except Exception as error:
      if row["scoped"]:
        # 先保留已开始消费的事实；未知分配不变成canceled或释放Writer。
        row["state"] = "consumed"
        if row["private"] is not None:
          self.private_bytes -= len(row["private"])
          row["private"] = None
        try: self._cancel(principal, row)
        except Exception: pass  # cleanup未知另记，不能覆盖原执行未知事实。
        if not isinstance(error, (ConfigError, Conflict)):
          raise Conflict("OPERATION_EXECUTION_UNKNOWN") from None
        raise error from None
      raise
    finally:
      # 成功、参数篡改、allocate失败或丢回执均不能重新签发/消费。
      row["state"] = "consumed"
      if row["private"] is not None:
        self.private_bytes -= len(row["private"])
        row["private"] = None

  def status(self, principal, args):
    closed(args, ("operation_id",))
    row = self._operation(principal, args["operation_id"])
    return row["bridge"].status(principal, args["operation_id"])

  def mcp_dispatch(self, principal, args):
    closed(args, ("operation_id", "context", "input"))
    row = self._operation(principal, args["operation_id"])
    control = self._control(principal, row["control_id"])
    if self.mcp_bridge is None or row["bridge"] is not self.mcp_bridge or row["state"] != "consumed":
      raise Conflict("OPERATION_NOT_PENDING")
    # 重复派发只拒绝，不能撤销已经发送的原调用或覆盖它的完成事实。
    if self.mcp_bridge.records[args["operation_id"]]["state"] != "consumed":
      return self.mcp_bridge.dispatch(principal, args["operation_id"], args["context"], args["input"])
    try:
      if control["state"] != "open" or context(args["context"]) != row["context"]:
        raise Conflict("OPERATION_NOT_PENDING")
      return self.mcp_bridge.dispatch(principal, args["operation_id"], args["context"], args["input"])
    except Exception:
      self.mcp_bridge.revoke(principal, args["operation_id"])
      raise

  def mcp_complete(self, principal, args):
    closed(args, ("operation_id", "outcome"))
    row = self._operation(principal, args["operation_id"])
    if self.mcp_bridge is None or row["bridge"] is not self.mcp_bridge: raise Conflict("OPERATION_UNKNOWN")
    return self.mcp_bridge.complete(principal, args["operation_id"], args["outcome"])

  def cancel_request(self, principal, args):
    closed(args, ("control_id", "request_id"))
    identifier(args["request_id"])
    self._control(principal, args["control_id"], create=True)
    _, row = self._request(principal, args["control_id"], args["request_id"], create=True)
    self._cancel(principal, row)
    return {"request_id": args["request_id"], "state": "canceled"}

  def retire(self, principal, args):
    closed(args, ("control_id",))
    control = self._control(principal, args["control_id"], create=True)
    control["state"] = "retired"
    failed, cleaned = False, set()
    for row in self.requests.values():
      if row["control_id"] != args["control_id"]: continue
      key = (row["scope_refs"]["session_scope"], row["scope_refs"]["intent_ref"]) if row["scoped_owned"] else None
      if key is not None and key in cleaned: continue
      if key is not None: cleaned.add(key)
      try: self._cancel(principal, row)
      except Exception: failed = True
    if failed: raise Conflict("OPERATION_RETIRE_INCOMPLETE")
    return {"control_id": args["control_id"], "state": "retired"}

  def handle(self, principal, method, args):
    handlers = {"ordinary_admission_" + name: getattr(self, name) for name in
      ("open", "prepare", "issue", "issue_deterministic", "consume", "status", "mcp_dispatch", "mcp_complete", "cancel_request", "retire")}
    with self.mutex:
      self._principal(principal)
      if method not in handlers: raise ConfigError("pi-admission-control-method")
      return handlers[method](principal, args)
