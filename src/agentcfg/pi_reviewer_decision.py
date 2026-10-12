"""可信reviewer决定控制面；能力对象仅留在私有控制通道，不注册模型RPC。

复用原OperationAdmissions的一次许可。模型只提供封闭wire结论，不提供source、
当前身份或许可字段。这里没有SDK、网络、进程和执行回调。真实宿主接线仍独立。
"""

from copy import deepcopy
import json
import inspect
import secrets
from threading import RLock
from types import CoroutineType

from .activity import digest
from .pi_operation_admission import context, resolution
from .pi_reviewer_ledger import _closed, _hex, REASONS, OUTCOMES
from .pi_reviewer_prompt import facts_from_projection, prompt_payload
from .schema import ConfigError
from .storage import Conflict


WIRE = ("schema_version", "request_id", "operation_digest", "context_digest", "reviewer_identity", "decision", "reason_code")


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_DECISION_INVALID")


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result: _invalid()
    result[key] = value
  return result


def _candidate(raw, binding):
  try:
    if type(raw) is not str or not raw or len(raw) > 8192 or len(raw.encode("utf8")) > 8192: _invalid()
    value = json.loads(raw, object_pairs_hook=_pairs)
    _closed(value, WIRE)
    if type(value["schema_version"]) is not int or value["schema_version"] != 1: _invalid()
    for key in WIRE[1:5]:
      _hex(value[key], 32 if key == "request_id" else 64)
      if value[key] != binding[key]: _invalid()
    decision = value["decision"]
    if (type(decision) is not str or decision not in REASONS or type(value["reason_code"]) is not str or
        value["reason_code"] not in REASONS[decision]): _invalid()
    return value
  except (ConfigError, ValueError, UnicodeError, RecursionError): _invalid()


class ReviewerDecisionControl:
  def __init__(self, admissions, ledger, *, current_provider, resolution_provider, qualification_provider,
      scope_provider, route_identity, pricing, token_limits, mutex=None, scope_current=None, human_available=None,
      admission_control=None, projection_provider=None):
    # 这些函数由宿主控制面绑定；不得从工具参数、模型文本或项目代码取得。
    for callback in (current_provider, resolution_provider, qualification_provider, scope_provider):
      if not callable(callback): _invalid()
    if scope_current is not None and not callable(scope_current): _invalid()
    if projection_provider is not None and (not callable(projection_provider) or
        inspect.iscoroutinefunction(projection_provider) or inspect.isasyncgenfunction(projection_provider)): _invalid()
    if human_available is not None and (not callable(human_available) or
        inspect.iscoroutinefunction(human_available) or inspect.isasyncgenfunction(human_available)): _invalid()
    _hex(route_identity, 64)
    if admission_control is not None:
      from .pi_admission_control import FileAdmissionControl
      if (type(admission_control) is not FileAdmissionControl or
          admission_control._shared_admissions is not admissions or admission_control._reviewer_scope_control is None or
          mutex is not None and mutex is not admission_control.mutex): _invalid()
      # 绑定原Host mutex，不能形成Decision锁→service锁的反向顺序。
      mutex = admission_control.mutex
    self.admissions, self.ledger = admissions, ledger
    self.current_provider, self.resolution_provider = current_provider, resolution_provider
    self.qualification_provider, self.scope_provider = qualification_provider, scope_provider
    self.scope_current = scope_current
    self._human_available = human_available
    self._projection_provider = projection_provider
    self.route_identity, self.pricing, self.token_limits = route_identity, deepcopy(pricing), deepcopy(token_limits)
    self.mutex = mutex if mutex is not None else RLock()
    self.tickets = {}
    self._admission_control = admission_control
    if admission_control is not None:
      with self.mutex:
        if admission_control._reviewer_decision_owner is not None:
          raise Conflict("REVIEW_DECISION_OWNER_ALREADY_BOUND")
        # 原控制面永久绑定一份Decision，activation内不清槽或重新装配。
        admission_control._reviewer_decision_owner = self

  def _scope_qualified(self, prepared, scopes):
    # 仅受信本地控制器：核对活动确认能力及持久引用，不从模型JSON取得True。
    # 同步predicate可取账户短锁；禁止等待SDK/网络、重入本控制器或反向锁序。
    if self.scope_current is None: raise Conflict("REVIEW_SCOPE_UNQUALIFIED")
    try: qualified = self.scope_current(deepcopy(prepared), deepcopy(scopes))
    except Exception: raise Conflict("REVIEW_SCOPE_UNQUALIFIED") from None
    if qualified is not True: raise Conflict("REVIEW_SCOPE_UNQUALIFIED")

  def _fresh(self, prepared, *, scopes=None):
    operation_id = prepared["operation_id"]
    current = context(self.current_provider(deepcopy(prepared)))
    if current != prepared["context"]: raise Conflict("REVIEW_CONTEXT_STALE")
    original = self.admissions.prepared(operation_id)
    if original != prepared: raise Conflict("REVIEW_OPERATION_STALE")
    resolved = resolution(self.resolution_provider(deepcopy(prepared)))
    if resolved != prepared["resolution"]: raise Conflict("REVIEW_RESOLUTION_STALE")
    # 确定性等级根本不进入review资格、scope或预算流程；仍先复核原操作与硬策略。
    if resolved["policy"].get("approval") == "deterministic-policy": return current, "not-called"
    qualify = self.qualification_provider(deepcopy(prepared))
    _closed(qualify, ("enabled", "role_allows", "automatic_risk_allowed"))
    if any(type(value) is not bool for value in qualify.values()): _invalid()
    if current["profile"] == "pi-base" or not qualify["enabled"]: return current, "not-called"
    if not qualify["role_allows"]: return current, "policy-blocked"
    if resolved["policy"]["requires_human"] or not qualify["automatic_risk_allowed"]: return current, "human-required"
    if current["reviewer_identity"] != self.route_identity: raise Conflict("REVIEW_ROUTE_STALE")
    if scopes is not None: self._scope_qualified(prepared, scopes)
    return current, None

  def begin(self, operation_id):
    with self.mutex:
      prepared = self.admissions.prepared(operation_id)
      try: current, blocked = self._fresh(prepared)
      except Exception:
        self.admissions.revoke(operation_id)
        raise
      if blocked is not None:
        return {"status": blocked, "operation_id": operation_id, "ticket": None, "binding": None}
      try: scopes = deepcopy(self.scope_provider(deepcopy(prepared)))
      except Exception:
        self.admissions.revoke(operation_id)
        raise Conflict("REVIEW_SCOPE_UNQUALIFIED") from None
      try:
        _closed(scopes, ("session_scope", "intent_ref", "request_ref"))
        for value in scopes.values(): _hex(value, 32)
        # 分配期间可能改变会话/取消/策略；进入预算之前再次核对原操作。
        _, blocked = self._fresh(prepared, scopes=scopes)
        if blocked is not None: raise Conflict("REVIEW_NO_LONGER_ELIGIBLE")
      except Exception:
        self.admissions.revoke(operation_id)
        raise
      binding = {"operation_id": operation_id, "request_id": scopes["request_ref"],
        "operation_digest": prepared["operation_digest"], "context_digest": digest(current), "reviewer_identity": self.route_identity}
      self.ledger.reserve(binding=binding, scope={key: scopes[key] for key in ("session_scope", "intent_ref")},
        pricing=self.pricing, token_limits=self.token_limits)
      self.ledger.claim_attempt(operation_id)
      # 能力是对象身份，不是可让模型提交的JSON、摘要或字符串句柄。
      ticket = object()
      self.tickets[ticket] = {"prepared": prepared, "binding": binding, "scopes": deepcopy(scopes), "settled": False,
        "wire_required": self._projection_provider is not None}
      return {"status": "reviewing", "operation_id": operation_id, "ticket": ticket,
        "binding": {key: value for key, value in binding.items() if key != "operation_id"}}

  def _entry(self, ticket):
    if type(ticket) is not object: raise Conflict("REVIEW_CAPABILITY_UNKNOWN")
    entry = self.tickets.get(ticket)
    if entry is None: raise Conflict("REVIEW_CAPABILITY_UNKNOWN")
    if entry["settled"]: raise Conflict("REVIEW_DECISION_ALREADY_SETTLED")
    return entry

  def commit_send(self, ticket):
    with self.mutex:
      entry = self._entry(ticket)
      try:
        _, blocked = self._fresh(entry["prepared"], scopes=entry["scopes"])
        if blocked is not None: raise Conflict("REVIEW_NO_LONGER_ELIGIBLE")
        if entry["wire_required"] and "wire" not in entry: raise Conflict("REVIEW_WIRE_NOT_PREPARED")
        if "wire" in entry: self._wire_facts_current(entry)
      except Exception:
        # 不提交send，也不让恢复资格复活旧操作；ticket仍可一次记未发送/迟到事实。
        self.admissions.revoke(entry["prepared"]["operation_id"])
        raise
      return self.ledger.commit_send(entry["prepared"]["operation_id"])

  def _projection_facts(self, prepared):
    # 仅factory持有的同步编译器闭包；不等待IO、不取private input、不接收模型参数。
    if self._projection_provider is None: return None
    try:
      value = self._projection_provider(deepcopy(prepared))
      if type(value) is CoroutineType: value.close()
      return facts_from_projection(value, prepared)
    except Exception:
      raise ConfigError("PI_RISK_REVIEW_PROJECTION_INVALID") from None

  def _wire_facts_current(self, entry):
    if self._projection_facts(entry["prepared"]) != entry["wire"]["projection"]:
      raise Conflict("REVIEW_PROJECTION_STALE")

  def prepare_wire(self, ticket):
    """原ticket私有接缝；准备不发送、不结算，不合格交原not-called路径。"""
    with self.mutex:
      entry = self._entry(ticket)
      entry["wire_required"] = True
      try:
        _, blocked = self._fresh(entry["prepared"], scopes=entry["scopes"])
        if blocked is not None: raise Conflict("REVIEW_NO_LONGER_ELIGIBLE")
        projection = self._projection_facts(entry["prepared"])
        if "wire" in entry:
          if projection != entry["wire"]["projection"]: raise Conflict("REVIEW_PROJECTION_STALE")
        elif projection is None:
          return {"status": "privacy-ineligible", "payload": None}
        else:
          binding = {key: secrets.token_hex(16 if key == "request_id" else 32) for key in WIRE[1:5]}
          entry["wire"] = {"projection": projection, "binding": binding,
            "payload": prompt_payload(binding, projection["facts"])}
        return {"status": "prepared", "payload": deepcopy(entry["wire"]["payload"])}
      except Exception:
        self.admissions.revoke(entry["prepared"]["operation_id"])
        raise

  def conclude_wire(self, ticket, report):
    """四个opaque回显全部匹配后，只在局部恢复原binding交原issuer。"""
    with self.mutex:
      entry = self._entry(ticket)
      _closed(report, ("outcome", "requests", "response"))
      if type(report["outcome"]) is not str or report["outcome"] not in OUTCOMES: _invalid()
      if report["requests"] is not None and (type(report["requests"]) is not int or report["requests"] not in (0, 1)): _invalid()
      if report["outcome"] != "valid" and report["response"] is not None: _invalid()
      entry["settled"] = True
      if report["outcome"] == "valid" and "wire" not in entry:
        report = {"outcome": "protocol-failure", "requests": report["requests"], "response": None}
      return self._conclude_entry(entry, report,
        preserve_failure_outcome=True)

  def mark_sent(self, ticket):
    with self.mutex:
      entry = self._entry(ticket)
      return self.ledger.mark_sent(entry["prepared"]["operation_id"])

  def conclude(self, ticket, report):
    with self.mutex:
      entry = self._entry(ticket)
      _closed(report, ("outcome", "requests", "response"))
      if type(report["outcome"]) is not str or report["outcome"] not in OUTCOMES: _invalid()
      if report["requests"] is not None and (type(report["requests"]) is not int or report["requests"] not in (0, 1)): _invalid()
      if report["outcome"] != "valid" and report["response"] is not None: _invalid()
      # 在持久记账和签发前不可逆结束本控制attempt；IO失败只能对账，不能再签。
      entry["settled"] = True
      return self._conclude_entry(entry, report)

  def _conclude_entry(self, entry, report, *, preserve_failure_outcome=False):
    operation_id, candidate, outcome = entry["prepared"]["operation_id"], None, report["outcome"]
    if outcome == "valid" and entry["wire_required"] and "wire" not in entry:
      outcome = "protocol-failure"
    if outcome == "valid":
      try:
        # 所有接受入口共用映射；旧conclude不能绕过同ticket的wire绑定。
        binding = entry["wire"]["binding"] if "wire" in entry else entry["binding"]
        candidate = _candidate(report["response"], binding)
        if "wire" in entry:
          self._wire_facts_current(entry)
          candidate = {**candidate, **{key: entry["binding"][key] for key in WIRE[1:5]}}
      except ConfigError: candidate, outcome = None, "protocol-failure"
      except Conflict:
        candidate, outcome = None, "discarded"
        self.admissions.revoke(operation_id)
    try:
      _, blocked = self._fresh(entry["prepared"], scopes=entry["scopes"])
      if blocked is not None:
        candidate = None
        if not preserve_failure_outcome or outcome == "valid": outcome = "discarded"
    except (Conflict, ConfigError):
      candidate = None
      if not preserve_failure_outcome or outcome == "valid": outcome = "discarded"
    try:
      self.ledger.finish(operation_id, requests=report["requests"], outcome=outcome,
        decision=candidate["decision"] if candidate else None, reason_code=candidate["reason_code"] if candidate else None)
    except Exception:
      self.admissions.revoke(operation_id)
      raise
    result = {"operation_id": operation_id, "status": "blocked", "source": "system-failure", "reason_code": outcome, "permit": None}
    if candidate is None:
      self.admissions.revoke(operation_id)
      return result
    result.update(source="reviewer", reason_code=candidate["reason_code"])
    if candidate["decision"] == "deny":
      self.admissions.revoke(operation_id)
      return result
    if candidate["decision"] == "ask":
      # 有效ask已持久化且保留意图锁；这里只投影可信同步UI资格。
      # 禁止重入控制器/账本或等待SDK/RPC，不传private input或凭据。
      available = False
      if self._human_available is not None:
        try:
          answer = self._human_available(deepcopy(entry["prepared"]))
          available = answer is True
          # 普通同步函数误返原生coroutine时关闭它，不读取外来awaitable。
          if inspect.iscoroutine(answer): answer.close()
        except Exception: available = False
      if available: result["status"] = "awaiting-human"
      return result
    try:
      current, blocked = self._fresh(entry["prepared"], scopes=entry["scopes"])
      if blocked is not None: raise Conflict("REVIEW_NO_LONGER_ELIGIBLE")
      if self._admission_control is None:
        permit = self.admissions.issue(operation_id, operation_digest=entry["binding"]["operation_digest"],
          current=current, source="reviewer", reviewer_identity=self.route_identity)
      else:
        permit = self._admission_control._issue_reviewer_prepared(entry["prepared"], current=current)
    except (Conflict, ConfigError) as error:
      if self._admission_control is not None and str(error) == "REVIEW_PERMIT_ISSUE_UNKNOWN":
        # 未知签发不能被投影为可确定的discarded；ticket已关闭且原事实保留。
        raise Conflict("REVIEW_PERMIT_ISSUE_UNKNOWN") from None
      self.admissions.revoke(operation_id)
      result.update(source="system-failure", reason_code="discarded")
      return result
    result.update(status="permitted", permit=permit)
    return result

  def conclude_transport(self, ticket, report):
    """可信私有平台/gate事实；先烧ticket再只读观察，不证明资格或物理终止。"""
    _closed(report, ("outcome", "platform_requests", "response", "gate_attempted", "gate_acknowledged"))
    report = dict.copy(report)  # 等待mutex期间不借用调用者可变事实容器。
    if type(report["outcome"]) is not str or report["outcome"] not in OUTCOMES: _invalid()
    if type(report["platform_requests"]) is not int or report["platform_requests"] not in (0, 1): _invalid()
    if type(report["gate_attempted"]) is not bool or type(report["gate_acknowledged"]) is not bool: _invalid()
    if report["outcome"] != "valid" and report["response"] is not None: _invalid()
    with self.mutex:
      entry = self._entry(ticket)
      entry["settled"] = True
      entry["transport_facts"] = {key: report[key] for key in
        ("platform_requests", "gate_attempted", "gate_acknowledged")}
      operation_id = entry["prepared"]["operation_id"]
      try: row = self.ledger.observe(operation_id)
      except Exception:
        self.admissions.revoke(operation_id)
        raise Conflict("REVIEW_SEND_RECONCILIATION_UNKNOWN") from None
      expected_scope = {key: entry["scopes"][key] for key in ("session_scope", "intent_ref")}
      count, acknowledged = report["platform_requests"], report["gate_acknowledged"]
      conflict = (type(row) is not dict or row.get("binding") != entry["binding"] or
        type(row.get("binding")) is not dict or row.get("scope") != expected_scope or
        type(row.get("scope")) is not dict or row.get("attempt_claimed") is not True or
        row.get("outcome") is not None or row.get("send_state") not in ("reserved", "committed") or
        acknowledged and not report["gate_attempted"])
      if not conflict:
        if row["send_state"] == "reserved":
          conflict = type(row.get("requests")) is not int or row["requests"] != 0 or count != 0 or acknowledged
          requests = 0
        else:
          conflict = (count == 0 and row.get("requests") is not None or
            count == 1 and row.get("requests") is not None and
            (type(row["requests"]) is not int or row["requests"] != 1))
          requests = None if count == 0 else 1
      if conflict:
        self.admissions.revoke(operation_id)
        raise Conflict("REVIEW_SEND_FACT_CONFLICT") from None
      outcome, response = report["outcome"], report["response"]
      if outcome == "valid" and (count == 0 or not report["gate_attempted"] or not acknowledged):
        outcome, response = "protocol-failure", None
      try:
        if count == 1: self.ledger.mark_sent(operation_id)
        return self._conclude_entry(entry, {"outcome": outcome, "requests": requests, "response": response},
          preserve_failure_outcome=True)
      except Exception:
        self.admissions.revoke(operation_id)
        raise Conflict("REVIEW_SEND_RECONCILIATION_UNKNOWN") from None
