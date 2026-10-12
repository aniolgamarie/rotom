"""可信控制面专用的累计 reviewer 账本；不接受模型调用，不签发许可。

一个获准账号/预算周期固定一个私有根，profile、重启和重连不能另建根清零。
同一文件事务保存请求墓碑、拒绝锁和预算；发送提交先落盘，才允许平台调用。
提交后中断视为可能已发送。只有可信观察者确认最终用量和整个进程域终止，
才能将预留换成 Provider 自报用量的费用估计；它不等于真实账单。
"""

from copy import deepcopy
import json
from pathlib import Path
import re
from threading import RLock

from .schema import ConfigError
from .storage import Conflict, Tree, instance_lock


FILE = "reviewer-ledger.json"
MAX_BYTES = 8 * 1024 * 1024
BINDING = ("operation_id", "request_id", "operation_digest", "context_digest", "reviewer_identity")
PRICING = ("identity", "currency", "input_units_per_million", "output_units_per_million",
  "cache_read_units_per_million", "cache_write_units_per_million")
OUTCOMES = ("valid", "not-called", "policy-blocked", "human-required", "canceled", "timeout",
  "discarded", "transport-failure", "protocol-failure")
REASONS = {"allow": ("authorized-in-scope",), "ask": ("ambiguous-intent", "unverifiable-input", "needs-human"),
  "deny": ("outside-user-scope", "destructive-change", "untrusted-authorization")}
ROW = ("binding", "scope", "pricing", "token_limits", "reservation_units", "attempt_claimed", "send_state", "requests",
  "outcome", "decision", "reason_code", "usage", "final_usage", "process_terminated", "settled_units")


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_LEDGER_INVALID")


def _closed(value, keys):
  if type(value) is not dict or set(value) != set(keys): _invalid()


def _integer(value, low=0, high=10**18):
  if type(value) is not int or not low <= value <= high: _invalid()


def _hex(value, length):
  if type(value) is not str or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value): _invalid()


def _limits(value):
  _closed(value, ("currency", "max_calls", "max_cost_units"))
  if type(value["currency"]) is not str or not re.fullmatch("[A-Z]{3}", value["currency"]): _invalid()
  _integer(value["max_calls"], high=1000000); _integer(value["max_cost_units"])
  return deepcopy(value)


def _request(binding, scope, pricing, token_limits):
  _closed(binding, BINDING)
  for key in BINDING: _hex(binding[key], 32 if key in ("operation_id", "request_id") else 64)
  _closed(scope, ("session_scope", "intent_ref"))
  for key in scope: _hex(scope[key], 32)
  _closed(pricing, PRICING); _hex(pricing["identity"], 64)
  if type(pricing["currency"]) is not str or not re.fullmatch("[A-Z]{3}", pricing["currency"]): _invalid()
  for key in PRICING[2:]: _integer(pricing[key], high=10**15)
  _closed(token_limits, ("input_tokens", "output_tokens"))
  _integer(token_limits["input_tokens"], 1, 10000000); _integer(token_limits["output_tokens"], 1, 4096)
  return deepcopy({"binding": binding, "scope": scope, "pricing": pricing, "token_limits": token_limits})


def _cost(pricing, tokens):
  # units为货币的十亿分之一。缓存费取输入各档最高价，避免把未知缓存当优惠。
  input_rate = max(pricing[key] for key in ("input_units_per_million", "cache_read_units_per_million", "cache_write_units_per_million"))
  return (tokens["input_tokens"] * input_rate + tokens["output_tokens"] * pricing["output_units_per_million"] + 999999) // 1000000


def _usage(value, token_limits):
  _closed(value, ("input_tokens", "output_tokens", "total_tokens"))
  for key in ("input_tokens", "output_tokens"): _integer(value[key], high=token_limits[key])
  _integer(value["total_tokens"], high=token_limits["input_tokens"] + token_limits["output_tokens"])
  if value["total_tokens"] != value["input_tokens"] + value["output_tokens"]: _invalid()


def _row(value, operation_id):
  _closed(value, ROW)
  _request(value["binding"], value["scope"], value["pricing"], value["token_limits"])
  if value["binding"]["operation_id"] != operation_id: _invalid()
  if value["reservation_units"] != _cost(value["pricing"], value["token_limits"]): _invalid()
  _integer(value["reservation_units"])
  if value["send_state"] not in ("reserved", "committed", "not-sent"): _invalid()
  if value["requests"] is not None: _integer(value["requests"], high=1)
  if value["outcome"] is not None and value["outcome"] not in OUTCOMES: _invalid()
  if value["outcome"] == "valid":
    if (type(value["decision"]) is not str or value["decision"] not in REASONS
        or value["reason_code"] not in REASONS[value["decision"]] or value["requests"] != 1): _invalid()
  elif value["decision"] is not None or value["reason_code"] is not None: _invalid()
  for key in ("attempt_claimed", "final_usage", "process_terminated"):
    if type(value[key]) is not bool: _invalid()
  if value["settled_units"] is not None: _integer(value["settled_units"])
  if value["usage"] is not None: _usage(value["usage"], value["token_limits"])
  if value["send_state"] == "reserved":
    if (value["requests"] != 0 or value["outcome"] is not None or value["usage"] is not None
        or value["final_usage"] or value["settled_units"] is not None): _invalid()
  elif value["send_state"] == "not-sent":
    if (value["requests"] != 0 or value["outcome"] is None or value["outcome"] == "valid"
        or value["usage"] is not None or value["final_usage"] or value["settled_units"] != 0): _invalid()
  elif value["requests"] == 0: _invalid()
  if value["send_state"] == "committed" and not value["attempt_claimed"]: _invalid()
  if value["final_usage"]:
    if (value["send_state"] != "committed" or value["requests"] != 1 or not value["process_terminated"]
        or value["outcome"] is None or value["usage"] is None
        or value["settled_units"] != _cost(value["pricing"], value["usage"])): _invalid()
  elif value["send_state"] != "not-sent" and value["settled_units"] is not None: _invalid()


def _document(value):
  _closed(value, ("schema_version", "limits", "rows"))
  if type(value["schema_version"]) is not int or value["schema_version"] != 1: _invalid()
  _limits(value["limits"])
  if type(value["rows"]) is not dict or len(value["rows"]) > 4096: _invalid()
  for key, row in value["rows"].items():
    _hex(key, 32); _row(row, key)
    if row["pricing"]["currency"] != value["limits"]["currency"]: _invalid()


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result: _invalid()
    result[key] = value
  return result


def _totals(document):
  rows = tuple(document["rows"].values())
  committed = sum(row["send_state"] == "committed" for row in rows)
  reserved = sum(row["send_state"] == "reserved" for row in rows)
  held = sum(row["reservation_units"] for row in rows if row["settled_units"] is None)
  estimated = sum(row["settled_units"] for row in rows if row["settled_units"] is not None)
  charged = held + estimated
  return {"committed_calls": committed, "reserved_calls": reserved,
    "observed_requests": sum(row["requests"] == 1 for row in rows),
    "unknown_requests": sum(row["requests"] is None for row in rows),
    "reserved_cost_units": held, "reported_estimated_cost_units": estimated,
    "charged_cost_units": charged,
    "over_budget": committed + reserved > document["limits"]["max_calls"] or charged > document["limits"]["max_cost_units"]}


def _intent_block(document, scope, *, except_operation=None):
  for key, row in document["rows"].items():
    if key == except_operation or row["scope"] != scope: continue
    if row["decision"] == "deny": raise Conflict("REVIEW_INTENT_DENIED")
    if row["decision"] == "ask" or row["send_state"] == "committed" and row["outcome"] != "valid":
      raise Conflict("REVIEW_INTENT_BLOCKED")
    if row["send_state"] == "reserved": raise Conflict("REVIEW_INTENT_BUSY")


class ReviewerLedger:
  def __init__(self, root, *, limits, max_records=4096, create=True):
    self.root = Path(root)
    self.limits = _limits(limits)
    _integer(max_records, 1, 4096)
    self.max_records, self.mutex = max_records, RLock()
    if type(create) is not bool: _invalid()
    if not create:
      with Tree(self.root) as tree:
        if tree.fd is None or tree.read(FILE, max_bytes=MAX_BYTES) is None:
          raise Conflict("REVIEW_LEDGER_MISSING")
    self._transaction(lambda document: None, create=create)

  def _transaction(self, action, *, create=False):
    with self.mutex, Tree(self.root, create=create) as tree, instance_lock(tree):
      saved = tree.read(FILE, max_bytes=MAX_BYTES)
      if saved is None:
        if not create: raise Conflict("REVIEW_LEDGER_MISSING")
        document = {"schema_version": 1, "limits": deepcopy(self.limits), "rows": {}}
      else:
        if saved[1] != 0o600: raise Conflict("REVIEW_LEDGER_MODE")
        try: document = json.loads(saved[0], object_pairs_hook=_pairs)
        except (ValueError, UnicodeError, RecursionError): _invalid()
        _document(document)
        previous = document["limits"]
        if (self.limits["currency"] != previous["currency"] or self.limits["max_calls"] > previous["max_calls"]
            or self.limits["max_cost_units"] > previous["max_cost_units"]): raise Conflict("REVIEW_BUDGET_INCREASE_REQUIRES_AUTHORITY")
        document["limits"] = deepcopy(self.limits)
      result = action(document)
      _document(document)
      body = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
      if len(body) > MAX_BYTES: raise Conflict("REVIEW_LEDGER_CAPACITY")
      if saved is None or saved[0] != body:
        tree.replace(FILE, body, expected=saved[2] if saved else None)
      # 只有替换及目录fsync完成后返回；提交失败不得执行send。
      return deepcopy(result)

  def reserve(self, *, binding, scope, pricing, token_limits):
    request = _request(binding, scope, pricing, token_limits)
    operation_id = request["binding"]["operation_id"]
    def action(document):
      rows = document["rows"]
      if pricing["currency"] != document["limits"]["currency"]: _invalid()
      if operation_id in rows:
        row = rows[operation_id]
        if any(row[key] != request[key] for key in request): raise Conflict("REVIEW_IDEMPOTENCY_CONFLICT")
        return row
      if any(row["scope"]["session_scope"] == request["scope"]["session_scope"]
          and row["binding"]["request_id"] == request["binding"]["request_id"] for row in rows.values()):
        raise Conflict("REVIEW_IDEMPOTENCY_CONFLICT")
      # 拒绝锁针对可信用户意图，保守覆盖其全部自动审批，不猜测字符串语义等价。
      _intent_block(document, request["scope"])
      if len(rows) >= self.max_records: raise Conflict("REVIEW_LEDGER_CAPACITY")
      row = {**request, "reservation_units": _cost(request["pricing"], request["token_limits"]), "attempt_claimed": False,
        "send_state": "reserved", "requests": 0,
        "outcome": None, "decision": None, "reason_code": None, "usage": None, "final_usage": False,
        "process_terminated": False, "settled_units": None}
      rows[operation_id] = row
      if _totals(document)["over_budget"]: raise Conflict("REVIEW_BUDGET_EXHAUSTED")
      return row
    return self._transaction(action)

  def _operation(self, document, operation_id):
    _hex(operation_id, 32)
    row = document["rows"].get(operation_id)
    if row is None: raise Conflict("REVIEW_UNKNOWN")
    return row

  def commit_send(self, operation_id):
    """不可重复提交。成功返回后仅原调用者可作一次实际平台调用；重启不能重发。"""
    def action(document):
      row = self._operation(document, operation_id)
      if row["send_state"] != "reserved" or row["outcome"] is not None: raise Conflict("REVIEW_SEND_ALREADY_CLAIMED")
      if not row["attempt_claimed"]: raise Conflict("REVIEW_ATTEMPT_NOT_CLAIMED")
      _intent_block(document, row["scope"], except_operation=operation_id)
      if _totals(document)["over_budget"]: raise Conflict("REVIEW_BUDGET_EXHAUSTED")
      row.update(send_state="committed", requests=None)
      return row
    return self._transaction(action)

  def claim_attempt(self, operation_id):
    """在建立SDK进程前不可逆登记一次attempt；启动未知或重启不再建第二个。"""
    def action(document):
      row = self._operation(document, operation_id)
      if row["attempt_claimed"] or row["send_state"] != "reserved" or row["outcome"] is not None:
        raise Conflict("REVIEW_ATTEMPT_ALREADY_CLAIMED")
      _intent_block(document, row["scope"], except_operation=operation_id)
      if _totals(document)["over_budget"]: raise Conflict("REVIEW_BUDGET_EXHAUSTED")
      row["attempt_claimed"] = True
      return row
    return self._transaction(action)

  def mark_sent(self, operation_id):
    def action(document):
      row = self._operation(document, operation_id)
      if row["send_state"] != "committed": raise Conflict("REVIEW_SEND_NOT_COMMITTED")
      row["requests"] = 1
      return row
    return self._transaction(action)

  def finish(self, operation_id, *, requests, outcome, decision=None, reason_code=None):
    if requests is not None: _integer(requests, high=1)
    if type(outcome) is not str or outcome not in OUTCOMES: _invalid()
    if outcome == "valid":
      if type(decision) is not str or decision not in REASONS or reason_code not in REASONS[decision] or requests != 1: _invalid()
    elif decision is not None or reason_code is not None: _invalid()
    def action(document):
      row = self._operation(document, operation_id)
      expected = {"requests": requests, "outcome": outcome, "decision": decision, "reason_code": reason_code}
      if row["outcome"] is not None:
        if any(row[key] != value for key, value in expected.items()): raise Conflict("REVIEW_TERMINAL_CONFLICT")
        return row
      if row["send_state"] == "reserved":
        if requests != 0 or outcome == "valid": raise Conflict("REVIEW_SEND_NOT_COMMITTED")
        row.update(send_state="not-sent", settled_units=0)
      elif requests == 0 or row["requests"] == 1 and requests is None: raise Conflict("REVIEW_REQUEST_FACT_CONFLICT")
      row.update(expected)
      return row
    return self._transaction(action)

  def record_usage(self, operation_id, usage, *, final=False, process_terminated=False):
    if type(final) is not bool or type(process_terminated) is not bool: _invalid()
    def action(document):
      row = self._operation(document, operation_id)
      if row["send_state"] != "committed" or row["requests"] != 1: raise Conflict("REVIEW_USAGE_WITHOUT_SEND")
      _usage(usage, row["token_limits"])
      if row["usage"] is not None and any(usage[key] < row["usage"][key] for key in ("input_tokens", "output_tokens")):
        raise Conflict("REVIEW_USAGE_REGRESSED")
      if row["final_usage"] and usage != row["usage"]: raise Conflict("REVIEW_FINAL_USAGE_CHANGED")
      row["usage"] = deepcopy(usage)
      row["process_terminated"] |= process_terminated
      if final:
        if row["outcome"] is None: raise Conflict("REVIEW_NOT_TERMINAL")
        if not row["process_terminated"]: raise Conflict("REVIEW_TERMINATION_UNKNOWN")
        row.update(final_usage=True, settled_units=_cost(row["pricing"], usage))
      return row
    return self._transaction(action)

  def get(self, operation_id):
    return self._transaction(lambda document: self._operation(document, operation_id))

  def snapshot(self):
    return self._transaction(lambda document: {"schema_version": 1, "limits": document["limits"],
      "record_count": len(document["rows"]), **_totals(document), "cost_scope": "reported-estimate-or-conservative-reservation",
      "product_gate": False})
