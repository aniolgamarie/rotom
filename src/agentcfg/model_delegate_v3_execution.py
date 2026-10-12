"""原 DelegationRuns 锁内的逻辑动作/物理 attempt 关联；本对象不授予来源权限。"""

from copy import deepcopy
import time

from .deployment import json_bytes
from .model_delegate_actions import capture_delegate_action, capture_delegate_origin
from .model_delegate_v3_intents import _binding, _document, _read_run, _hex
from .schema import ConfigError
from .storage import Conflict
from .paths import safe_id


_CONFIG = {"scope_id", "currency", "max_calls", "max_turns", "max_input_tokens", "max_output_tokens",
  "max_cost_microunits", "per_call_input_tokens", "per_call_output_tokens", "per_call_cost_microunits", "wall_seconds"}
_LIMITS = _CONFIG - {"scope_id", "currency", "wall_seconds"}
_METRICS = {"calls", "turns", "input_tokens", "output_tokens", "cost_microunits"}
_TOTALS = _METRICS - {"cost_microunits"} | {"known_cost_microunits", "estimated_cost_microunits"}
_TOP = {"schema_version", "kind", "run_id", "origin", "binding", "budget", "cancel_requested", "actions", "active_attempt_id", "next_sequence"}
_ACTION = {"action_key", "request_digest", "kind", "sequence", "state", "reservation", "physical_run_id", "attempt_id", "lease_id", "native_action_id", "receipt_ref", "failure_code"}
_STATES = {"prepared", "sending", "acknowledged", "completed", "unknown", "rejected"}


def _invalid():
  raise Conflict("DELEGATE_EXECUTION_STATE_INVALID") from None


def capture_budget(value):
  if type(value) is not dict or any(type(key) is not str for key in value) or value.keys() != _CONFIG:
    raise ConfigError("delegate-budget-invalid") from None
  result = dict.copy(value)
  if (type(result["scope_id"]) is not str or type(result["currency"]) is not str or result["currency"] not in ("CNY", "USD")
      or any(type(result[key]) is not int or not 1 <= result[key] <= 2**53 - 1 for key in _CONFIG - {"scope_id", "currency"})):
    raise ConfigError("delegate-budget-invalid") from None
  safe_id(result["scope_id"])
  for per, maximum in (("per_call_input_tokens", "max_input_tokens"), ("per_call_output_tokens", "max_output_tokens"), ("per_call_cost_microunits", "max_cost_microunits")):
    if result[per] > result[maximum]: raise ConfigError("delegate-budget-invalid")
  return result


def _amounts(value, keys):
  if type(value) is not dict or value.keys() != keys or any(type(item) is not int or not 0 <= item <= 2**53 - 1 for item in value.values()):
    _invalid()


def _budget(value, binding):
  if (type(value) is not dict or value.keys() != {"scope_id", "account_scope_id", "currency", "limits", "totals", "reservations", "deadline_ms", "cost_state"}
      or value["scope_id"] != binding["budget_scope_id"] or value["account_scope_id"] != binding["account_scope_id"]
      or value["currency"] not in ("CNY", "USD") or value["cost_state"] not in {"known", "estimated", "unknown", "reserved"}
      or type(value["deadline_ms"]) is not int or not 0 < value["deadline_ms"] <= 2**53 - 1):
    _invalid()
  _amounts(value["limits"], _LIMITS)
  _amounts(value["totals"], _TOTALS)
  _amounts(value["reservations"], _METRICS)
  if any(item < 1 for item in value["limits"].values()): _invalid()
  for per, maximum in (("per_call_input_tokens", "max_input_tokens"), ("per_call_output_tokens", "max_output_tokens"), ("per_call_cost_microunits", "max_cost_microunits")):
    if value["limits"][per] > value["limits"][maximum]: _invalid()
  for metric in ("calls", "turns", "input_tokens", "output_tokens"):
    if value["totals"][metric] + value["reservations"][metric] > value["limits"]["max_" + metric]: _invalid()
  if (value["totals"]["known_cost_microunits"] + value["totals"]["estimated_cost_microunits"]
      + value["reservations"]["cost_microunits"] > value["limits"]["max_cost_microunits"]): _invalid()
  return value


def _record(value, run_id):
  if (type(value) is not dict or value.keys() != _TOP or type(value["schema_version"]) is not int or value["schema_version"] != 3
      or value["kind"] != "logical-execution" or value["run_id"] != run_id or type(value["cancel_requested"]) is not bool
      or type(value["actions"]) is not list or len(value["actions"]) > 4096
      or type(value["next_sequence"]) is not int or value["next_sequence"] != len(value["actions"]) + 1):
    _invalid()
  try:
    if capture_delegate_origin(value["origin"]) != value["origin"] or _binding(value["binding"]) != value["binding"]: _invalid()
  except ConfigError: _invalid()
  _budget(value["budget"], value["binding"])
  seen = set()
  for index, action in enumerate(value["actions"], 1):
    if (type(action) is not dict or action.keys() != _ACTION or not _hex(action["action_key"]) or not _hex(action["request_digest"])
        or action["action_key"] in seen or action["sequence"] != index or type(action["sequence"]) is not int
        or action["kind"] not in {"submit", "message", "continue", "cancel"} or action["state"] not in _STATES):
      _invalid()
    seen.add(action["action_key"]); _amounts(action["reservation"], _METRICS)
    for field in ("physical_run_id", "attempt_id", "lease_id", "native_action_id", "receipt_ref", "failure_code"):
      if action[field] is not None and (type(action[field]) is not str or not 1 <= len(action[field]) <= 256): _invalid()
  if value["active_attempt_id"] is not None and not any(action["attempt_id"] == value["active_attempt_id"] for action in value["actions"]): _invalid()
  if any(sum(action["reservation"][field] for action in value["actions"]) != value["budget"]["reservations"][field] for field in _METRICS): _invalid()
  return value


class LogicalExecutions:
  """单文件 postimage；sender、source 注册和工作区权威仍由原 controller 持有。"""

  def __init__(self, runs, *, now_ms=None):
    self.runs = runs
    self.now_ms = now_ms or (lambda: time.time_ns() // 1_000_000)

  def _path(self, run_id):
    return "execution-v3/" + self.runs._key(run_id)

  def _read(self, tree, run_id):
    document = _document(tree, self._path(run_id))
    return None if document is None else _record(document[0], run_id)

  def _save(self, tree, row):
    _record(row, row["run_id"])
    data = json_bytes(row)
    if len(data) > 8 * 1024 * 1024: raise Conflict("DELEGATE_EXECUTION_CAPACITY")
    try: tree.write_state(self._path(row["run_id"]), data)
    except (OSError, ValueError, TypeError): raise Conflict("DELEGATE_EXECUTION_WRITE_FAILED") from None

  def _match(self, row, origin, binding):
    if row["origin"] != origin: raise Conflict("DELEGATE_EXECUTION_ORIGIN_CONFLICT")
    if row["binding"] != binding: raise Conflict("DELEGATE_EXECUTION_STALE")

  def begin(self, origin, action, binding, config):
    action = capture_delegate_action(action)
    if action["action"] == "cancel": return self.cancel(origin, action)
    origin, action, binding, config = capture_delegate_origin(origin), capture_delegate_action(action), _binding(binding), capture_budget(config)
    if config["scope_id"] != binding["budget_scope_id"]: raise Conflict("DELEGATE_EXECUTION_BUDGET_SCOPE")
    registration = self.runs.prepare_modern_intent(origin, action, binding)
    run_id, key = registration["run_id"], registration["action_key"]
    def begin(tree):
      _read_run(tree, self.runs, run_id)
      row = self._read(tree, run_id)
      if row is None:
        row = {"schema_version": 3, "kind": "logical-execution", "run_id": run_id, "origin": origin, "binding": binding,
          "budget": {"scope_id": config["scope_id"], "account_scope_id": binding["account_scope_id"], "currency": config["currency"],
            "limits": {field: config[field] for field in _LIMITS}, "totals": {field: 0 for field in _TOTALS},
            "reservations": {field: 0 for field in _METRICS}, "deadline_ms": self.now_ms() + config["wall_seconds"] * 1000, "cost_state": "reserved"},
          "cancel_requested": False, "actions": [], "active_attempt_id": None, "next_sequence": 1}
      self._match(row, origin, binding)
      if row["budget"]["currency"] != config["currency"] or row["budget"]["limits"] != {field: config[field] for field in _LIMITS}:
        raise Conflict("DELEGATE_EXECUTION_BUDGET_STALE")
      prior = next((item for item in row["actions"] if item["action_key"] == key), None)
      if prior is not None:
        return {"send": False, "run_id": run_id, "action_key": key, "action": deepcopy(prior)}
      if row["cancel_requested"] and action["action"] != "cancel": raise Conflict("DELEGATE_EXECUTION_CANCELED")
      if action["action"] != "cancel" and self.now_ms() >= row["budget"]["deadline_ms"]: raise Conflict("DELEGATE_EXECUTION_DEADLINE")
      budget = row["budget"]; reservation = {field: 0 for field in _METRICS}
      if action["action"] != "cancel":
        reservation.update(calls=1, turns=1, input_tokens=config["per_call_input_tokens"], output_tokens=config["per_call_output_tokens"])
        remaining = config["max_cost_microunits"] - budget["totals"]["known_cost_microunits"] - budget["totals"]["estimated_cost_microunits"] - budget["reservations"]["cost_microunits"]
        if remaining < config["per_call_cost_microunits"]: raise Conflict("DELEGATE_EXECUTION_COST_UNQUALIFIED")
        # 未有已验证计价上界时，整个尚可用金额保守占用；不是实际账单估计。
        reservation["cost_microunits"] = remaining
        for metric in ("calls", "turns", "input_tokens", "output_tokens"):
          if budget["totals"][metric] + budget["reservations"][metric] + reservation[metric] > config["max_" + metric]:
            raise Conflict("DELEGATE_EXECUTION_BUDGET_EXCEEDED")
      item = {"action_key": key, "request_digest": registration["request_digest"], "kind": action["action"], "sequence": row["next_sequence"],
        "state": "sending", "reservation": reservation, "physical_run_id": None, "attempt_id": None, "lease_id": None,
        "native_action_id": None, "receipt_ref": None, "failure_code": None}
      for field in _METRICS: budget["reservations"][field] += reservation[field]
      if action["action"] == "cancel": row["cancel_requested"] = True
      else: budget["cost_state"] = "reserved"
      row["actions"].append(item); row["next_sequence"] += 1
      self._save(tree, row)
      return {"send": True, "run_id": run_id, "action_key": key, "action": deepcopy(item)}
    return self.runs._transaction(begin)

  def update(self, run_id, action_key, *, state, physical=None, native_action_id=None, receipt_ref=None, failure_code=None):
    if state not in _STATES: _invalid()
    def update(tree):
      row = self._read(tree, run_id)
      if row is None: _invalid()
      item = next((item for item in row["actions"] if item["action_key"] == action_key), None)
      if item is None: _invalid()
      allowed = {"prepared": {"prepared", "sending", "rejected"}, "sending": {"sending", "acknowledged", "unknown"},
        "acknowledged": {"acknowledged", "unknown"}, "unknown": {"unknown"}, "completed": {"completed"}, "rejected": {"rejected"}}
      if state not in allowed[item["state"]]: raise Conflict("DELEGATE_EXECUTION_TRANSITION")
      if physical is not None:
        for field, source in (("physical_run_id", "run_id"), ("attempt_id", "attempt_id"), ("lease_id", "lease_id")):
          value = physical[source]
          if item[field] is not None and item[field] != value: raise Conflict("DELEGATE_EXECUTION_ATTEMPT_CONFLICT")
          item[field] = value
        if item["kind"] in {"submit", "continue"}: row["active_attempt_id"] = item["attempt_id"]
      if item["state"] in {"completed", "rejected"} and state != item["state"]: raise Conflict("DELEGATE_EXECUTION_TERMINAL")
      item.update(state=state, native_action_id=native_action_id or item["native_action_id"], receipt_ref=receipt_ref or item["receipt_ref"], failure_code=failure_code)
      if state == "unknown": row["budget"]["cost_state"] = "unknown"
      self._save(tree, row)
      return deepcopy(item)
    return self.runs._transaction(update)

  def cancel(self, origin, action):
    origin, action = capture_delegate_origin(origin), capture_delegate_action(action)
    if action["action"] != "cancel": _invalid()
    run_id = action["run_id"]
    # 只由外层核原owner/source；撤销不依赖当前新预算，也不借此签发新的发送额度。
    binding = self.runs._transaction(lambda tree: deepcopy(_read_run(tree, self.runs, run_id)["binding"]))
    registration = self.runs.prepare_modern_intent(origin, action, binding)
    def cancel(tree):
      row = self._read(tree, run_id)
      if row is None: raise Conflict("DELEGATE_EXECUTION_NOT_STARTED")
      self._match(row, origin, binding)
      key = registration["action_key"]
      prior = next((item for item in row["actions"] if item["action_key"] == key), None)
      if prior is not None: return {"send": False, "run_id": run_id, "action_key": key, "action": deepcopy(prior)}
      item = {"action_key": key, "request_digest": registration["request_digest"], "kind": "cancel", "sequence": row["next_sequence"],
        "state": "sending", "reservation": {field: 0 for field in _METRICS}, "physical_run_id": None, "attempt_id": None,
        "lease_id": None, "native_action_id": None, "receipt_ref": None, "failure_code": None}
      row["cancel_requested"] = True; row["actions"].append(item); row["next_sequence"] += 1
      self._save(tree, row)
      return {"send": True, "run_id": run_id, "action_key": key, "action": deepcopy(item)}
    return self.runs._transaction(cancel)

  def finish_verified(self, run_id, action_key):
    # 原v2 store的finish/receipt校验已经完成，普通ACK无权调用completed转移。
    snapshot = self.private(run_id)
    if snapshot is None: _invalid()
    action = next((item for item in snapshot["actions"] if item["action_key"] == action_key), None)
    if action is None or action["physical_run_id"] is None: raise Conflict("DELEGATE_EXECUTION_PROOF_REQUIRED")
    physical = self.runs.read(action["physical_run_id"])
    receipt = physical["receipt"]
    if (physical["verification"] != "verified-execution" or receipt is None
        or receipt["run_id"] != action["physical_run_id"] or receipt["attempt_id"] != action["attempt_id"]
        or receipt["lease_id"] != action["lease_id"] or receipt["process_terminated"] is not True
        or receipt["resources_reclaimed"] is not True): raise Conflict("DELEGATE_EXECUTION_PROOF_REQUIRED")
    def finish(tree):
      row = self._read(tree, run_id)
      item = next((item for item in row["actions"] if item["action_key"] == action_key), None)
      if item is None or any(item[field] != action[field] for field in ("physical_run_id", "attempt_id", "lease_id")): _invalid()
      item.update(state="completed", receipt_ref=action["physical_run_id"], failure_code=None)
      # 物理终止/可读结果不是已付金额证据；未知计量预留保持。
      self._save(tree, row)
      return deepcopy(item)
    return self.runs._transaction(finish)

  def acknowledge_verified_live(self, run_id, action_key):
    # 仅控制器原私有worker/frame/epoch验证后调用；公开update仍不能提升unknown。
    def acknowledge(tree):
      row = self._read(tree, run_id)
      if row is None or row["cancel_requested"]: return False
      item = next((item for item in row["actions"] if item["action_key"] == action_key), None)
      if item is None or item["kind"] != "message" or item["state"] not in {"unknown", "acknowledged"}:
        raise Conflict("DELEGATE_EXECUTION_TRANSITION")
      if item["state"] == "acknowledged": return True
      item.update(state="acknowledged", failure_code=None)
      self._save(tree, row)
      return True
    return self.runs._transaction(acknowledge)

  def unknown(self, run_id, action_key, failure_code):
    return self.update(run_id, action_key, state="unknown", failure_code=failure_code)

  def revoke(self, run_id):
    def revoke(tree):
      row = self._read(tree, run_id)
      if row is None: _invalid()
      row["cancel_requested"] = True
      self._save(tree, row)
    self.runs._transaction(revoke)

  def meter_claim(self, run_id, action_key, metric, sequence, *, synthetic_cost=None):
    if metric not in ("calls", "turns") or type(sequence) is not int or sequence < 1:
      raise ConfigError("delegate-meter-invalid")
    def claim(tree):
      row = self._read(tree, run_id)
      if row is None: _invalid()
      if row["cancel_requested"] or self.now_ms() >= row["budget"]["deadline_ms"]: raise Conflict("DELEGATE_EXECUTION_CANCELED")
      action = next((item for item in row["actions"] if item["action_key"] == action_key), None)
      if action is None or action["state"] not in {"sending", "acknowledged"}: raise Conflict("DELEGATE_EXECUTION_ATTEMPT_UNKNOWN")
      budget = row["budget"]; limits = budget["limits"]
      if sequence != budget["totals"][metric] + 1: raise Conflict("DELEGATE_METER_SEQUENCE")
      if action["reservation"][metric] == 0:
        if budget["totals"][metric] + budget["reservations"][metric] >= limits["max_" + metric]:
          raise Conflict("DELEGATE_EXECUTION_BUDGET_EXCEEDED")
        action["reservation"][metric] += 1; budget["reservations"][metric] += 1
        if metric == "calls":
          remaining = limits["max_cost_microunits"] - budget["totals"]["known_cost_microunits"] - budget["totals"]["estimated_cost_microunits"] - budget["reservations"]["cost_microunits"]
          if remaining < limits["per_call_cost_microunits"]: raise Conflict("DELEGATE_EXECUTION_COST_UNQUALIFIED")
          for field, per in (("input_tokens", "per_call_input_tokens"), ("output_tokens", "per_call_output_tokens")):
            amount = limits[per]
            if budget["totals"][field] + budget["reservations"][field] + amount > limits["max_" + field]:
              raise Conflict("DELEGATE_EXECUTION_BUDGET_EXCEEDED")
            action["reservation"][field] += amount; budget["reservations"][field] += amount
          action["reservation"]["cost_microunits"] += remaining; budget["reservations"]["cost_microunits"] += remaining
      action["reservation"][metric] -= 1; budget["reservations"][metric] -= 1; budget["totals"][metric] += 1
      if metric == "calls":
        if synthetic_cost is not None:
          if type(synthetic_cost) is not int or synthetic_cost != 0: raise ConfigError("delegate-synthetic-meter-invalid")
          # 仅可信自有合成oracle可在发送前证明零费用；生产路径不提供此参数。
          budget["reservations"]["cost_microunits"] -= action["reservation"]["cost_microunits"]
          action["reservation"]["cost_microunits"] = 0; budget["cost_state"] = "known"
        else: budget["cost_state"] = "unknown"
      self._save(tree, row)
      return {"allowed": True, "sequence": sequence}
    return self.runs._transaction(claim)

  def private(self, run_id):
    return self.runs._transaction(lambda tree: deepcopy(self._read(tree, run_id)))

  def query(self, origin, run_id, binding):
    origin, binding = capture_delegate_origin(origin), _binding(binding)
    def read(tree):
      intent = _read_run(tree, self.runs, run_id)
      if intent["origin"] != origin or intent["binding"] != binding: raise Conflict("DELEGATE_EXECUTION_STALE")
      row = self._read(tree, run_id)
      if row is None: return {"schema_version": 3, "run_id": run_id, "status": "registered-not-started", "actions": []}
      self._match(row, origin, binding)
      states = [item["state"] for item in row["actions"]]
      status = "unknown" if any(state in {"sending", "unknown"} for state in states) else "cancel-requested" if row["cancel_requested"] else states[-1] if states else "registered-not-started"
      return {"schema_version": 3, "run_id": run_id, "status": status, "cancel_requested": row["cancel_requested"],
        "budget": deepcopy(row["budget"]), "active_attempt_id": row["active_attempt_id"], "actions": [{field: item[field] for field in ("kind", "sequence", "state", "physical_run_id", "attempt_id", "lease_id", "failure_code", "receipt_ref")} for item in row["actions"]]}
    return self.runs._transaction(read)
