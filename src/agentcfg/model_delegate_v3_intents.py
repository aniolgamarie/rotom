"""原 DelegationRuns 控制区的 schema3 意图登记；不启动或授权外部工作。"""

import hashlib
import json
import os
import re

from .deployment import json_bytes
from .model_delegate_actions import capture_delegate_action, capture_delegate_origin, delegate_action_identity
from .schema import ConfigError
from .storage import Conflict


_PENDING = "prepare-v3.pending.json"
_MAX_BYTES = 8 * 1024 * 1024
_DIGESTS = {"runtime_identity_digest", "capability_binding_digest", "config_identity_digest", "policy_digest", "workspace_identity_digest"}
_SCOPES = {"account_scope_id", "budget_scope_id"}


def _checkpoint(phase):
  # 仅供自有故障测试建立持久切点；生产路径没有外来回调或 IPC。
  pass


def _invalid():
  raise Conflict("DELEGATE_INTENT_STATE_INVALID") from None


def _hex(value):
  return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _digest(value):
  return hashlib.sha256(json_bytes(value)).hexdigest()


def _binding(value):
  if type(value) is not dict:
    raise ConfigError("delegate-intent-binding-invalid") from None
  value = dict.copy(value)
  if (any(type(key) is not str for key in value) or value.keys() != _DIGESTS | _SCOPES
      or any(not _hex(value[key]) for key in _DIGESTS)
      or any(type(value[key]) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", value[key]) for key in _SCOPES)):
    raise ConfigError("delegate-intent-binding-invalid") from None
  return value


def _shape(value, kind, fields):
  if (type(value) is not dict or value.keys() != fields
      or type(value["schema_version"]) is not int or value["schema_version"] != 3 or value["kind"] != kind):
    _invalid()


def _pairs(pairs):
  result = {}
  for key, value in pairs:
    if key in result: raise ValueError()
    result[key] = value
  return result


def _document(tree, name):
  raw = tree.read(name, max_bytes=_MAX_BYTES)
  if raw is None: return None
  if raw[1] != 0o600: _invalid()
  try:
    value = json.loads(raw[0], object_pairs_hook=_pairs)
  except (ValueError, UnicodeError, RecursionError):
    _invalid()
  return value, raw[2]


def _run(value):
  _shape(value, "logical-run-intents", {"schema_version", "kind", "run_id", "origin", "binding", "submit_key", "submit_request_digest", "action_keys"})
  try:
    origin, binding = capture_delegate_origin(value["origin"]), _binding(value["binding"])
  except ConfigError:
    _invalid()
  keys = value["action_keys"]
  if (not _hex(value["submit_key"]) or not _hex(value["submit_request_digest"])
      or value["run_id"] != "run-" + value["submit_key"]
      or type(keys) is not list or not keys or any(not _hex(key) for key in keys)
      or len(keys) != len(set(keys)) or keys[0] != value["submit_key"]
      or origin != value["origin"] or binding != value["binding"]):
    _invalid()
  return value


def _intent(value):
  _shape(value, "action-intent", {"schema_version", "kind", "key", "request_digest", "run_id", "origin", "binding_digest", "action"})
  try:
    origin, action = capture_delegate_origin(value["origin"]), capture_delegate_action(value["action"])
    identity = delegate_action_identity(origin, action)
  except ConfigError:
    _invalid()
  target = "run-" + identity["key"] if action["action"] == "submit" else action["run_id"]
  if (value["key"] != identity["key"] or value["request_digest"] != identity["request_digest"]
      or value["run_id"] != target or not re.fullmatch(r"run-[0-9a-f]{64}", target)
      or not _hex(value["binding_digest"]) or action != value["action"] or origin != value["origin"]):
    _invalid()
  return value


def _links(tree, row, *, pending_key=None):
  for index, key in enumerate(row["action_keys"]):
    # 只有已完整核验的 pending 新叶可由 postimage 恢复；历史引用一律核原文件。
    if key == pending_key and index == len(row["action_keys"]) - 1: continue
    document = _document(tree, "intents-v3/" + key + ".json")
    if document is None: _invalid()
    intent = _intent(document[0])
    if (intent["key"] != key or intent["run_id"] != row["run_id"]
        or intent["origin"] != row["origin"] or intent["binding_digest"] != _digest(row["binding"])):
      _invalid()
    if index == 0:
      if intent["action"]["action"] != "submit" or intent["request_digest"] != row["submit_request_digest"]: _invalid()
    elif intent["action"]["action"] == "submit":
      _invalid()


def _read_run(tree, runs, run_id):
  document = _document(tree, runs._key(run_id))
  if document is None: raise Conflict("DELEGATE_INTENT_RUN_NOT_FOUND")
  value = document[0]
  if type(value) is dict and value.get("schema_version") != 3:
    raise Conflict("DELEGATE_INTENT_FORMAT_UNSUPPORTED")
  _run(value)
  if value["run_id"] != run_id: _invalid()
  _links(tree, value)
  return value


def _match_run(row, origin, binding):
  if row["origin"] != origin: raise Conflict("DELEGATE_INTENT_ORIGIN_CONFLICT")
  if row["binding"] != binding: raise Conflict("DELEGATE_INTENT_BINDING_CONFLICT")


def _pending(value):
  _shape(value, "prepare-action", {"schema_version", "kind", "before_run_digest", "run_record", "intent"})
  row, intent = _run(value["run_record"]), _intent(value["intent"])
  if (intent["run_id"] != row["run_id"] or intent["origin"] != row["origin"]
      or intent["binding_digest"] != _digest(row["binding"]) or row["action_keys"][-1] != intent["key"]):
    _invalid()
  before = value["before_run_digest"]
  if intent["action"]["action"] == "submit":
    if (before is not None or row["action_keys"] != [intent["key"]]
        or row["submit_key"] != intent["key"] or row["submit_request_digest"] != intent["request_digest"]):
      _invalid()
  elif (not _hex(before) or len(row["action_keys"]) < 2
      or _digest({**row, "action_keys": row["action_keys"][:-1]}) != before):
    _invalid()
  return value


def _apply_pending(tree, runs, document):
  pending, pending_identity = _pending(document[0]), document[1]
  intent, after = pending["intent"], pending["run_record"]
  intent_path, run_path = "intents-v3/" + intent["key"] + ".json", runs._key(after["run_id"])
  current_intent, current_run = _document(tree, intent_path), _document(tree, run_path)
  # 完整检查两个目标之后才写任何目标，冲突时 pending 与原文件均保留。
  if current_intent is not None and (_intent(current_intent[0]) != intent):
    raise Conflict("DELEGATE_INTENT_RECOVERY_CONFLICT")
  actual_digest = None if current_run is None else _digest(_run(current_run[0]))
  if actual_digest not in {pending["before_run_digest"], _digest(after)}:
    raise Conflict("DELEGATE_INTENT_RECOVERY_CONFLICT")
  if intent["action"]["action"] != "submit":
    _links(tree, current_run[0], pending_key=intent["key"])
  if current_intent is None: tree.write_immutable(intent_path, json_bytes(intent))
  _checkpoint("intent")
  if actual_digest != _digest(after): tree.write_state(run_path, json_bytes(after))
  _checkpoint("run")
  tree.replace(_PENDING, None, expected=pending_identity)
  _checkpoint("clear")


def _recover_pending(tree, runs):
  document = _document(tree, _PENDING)
  if document is not None: _apply_pending(tree, runs, document)


def _registration(intent):
  return {"schema_version": 3, "run_id": intent["run_id"], "action_key": intent["key"],
    "request_digest": intent["request_digest"], "registration": "prepared"}


def _assert_unreferenced(tree, runs, key):
  # 缺失 intent 也不能复用已登记的 key，包括改指另一个 run 的请求。
  for name in os.listdir(tree.fd):
    if re.fullmatch(r"run-[0-9a-f]{64}\.json", name):
      row = _read_run(tree, runs, name[:-5])
      if key in row["action_keys"]: _invalid()


def prepare_modern_intent(runs, origin, action, binding):
  # 坏输入与外来 hook 在控制目录创建及任何持久副作用之前拒绝。
  origin, action, binding = capture_delegate_origin(origin), capture_delegate_action(action), _binding(binding)
  identity = delegate_action_identity(origin, action)
  key, request_digest = identity["key"], identity["request_digest"]
  target = "run-" + key if action["action"] == "submit" else action["run_id"]
  def prepare(tree):
    _recover_pending(tree, runs)
    old = _document(tree, "intents-v3/" + key + ".json")
    if old is not None:
      intent = _intent(old[0])
      if intent["origin"] != origin or intent["request_digest"] != request_digest or intent["action"] != action:
        raise Conflict("DELEGATE_INTENT_CONFLICT")
      if intent["binding_digest"] != _digest(binding): raise Conflict("DELEGATE_INTENT_BINDING_CONFLICT")
      row = _read_run(tree, runs, intent["run_id"])
      _match_run(row, origin, binding)
      if key not in row["action_keys"]: _invalid()
      return _registration(intent)
    _assert_unreferenced(tree, runs, key)
    if action["action"] == "submit":
      if _document(tree, runs._key(target)) is not None: raise Conflict("DELEGATE_INTENT_CONFLICT")
      before = None
      row = {"schema_version": 3, "kind": "logical-run-intents", "run_id": target,
        "origin": origin, "binding": binding, "submit_key": key, "submit_request_digest": request_digest, "action_keys": [key]}
    else:
      row = _read_run(tree, runs, target)
      _match_run(row, origin, binding)
      if key in row["action_keys"]: _invalid()
      before = _digest(row)
      row = {**row, "action_keys": [*row["action_keys"], key]}
    intent = {"schema_version": 3, "kind": "action-intent", "key": key, "request_digest": request_digest,
      "run_id": target, "origin": origin, "binding_digest": _digest(binding), "action": action}
    pending = _pending({"schema_version": 3, "kind": "prepare-action", "before_run_digest": before, "run_record": row, "intent": intent})
    for value in (pending, row, intent):
      if len(json_bytes(value)) > _MAX_BYTES: raise Conflict("DELEGATE_INTENT_CAPACITY")
    tree.write_immutable(_PENDING, json_bytes(pending))
    _checkpoint("pending")
    _apply_pending(tree, runs, _document(tree, _PENDING))
    return _registration(intent)
  return runs._transaction(prepare)


def read_modern_intent(runs, origin, request_id):
  origin = capture_delegate_origin(origin)
  # 复用纯请求 ID 边界；lookup 标签不写入状态、不决定实际动作。
  identity = delegate_action_identity(origin, {"schema_version": 3, "action": "cancel", "request_id": request_id, "run_id": "lookup"})
  def read(tree):
    if _document(tree, _PENDING) is not None: raise Conflict("DELEGATE_INTENT_RECOVERY_PENDING")
    document = _document(tree, "intents-v3/" + identity["key"] + ".json")
    if document is None: raise Conflict("DELEGATE_INTENT_NOT_FOUND")
    intent = _intent(document[0])
    if intent["key"] != identity["key"] or intent["origin"] != origin: _invalid()
    row = _read_run(tree, runs, intent["run_id"])
    if (row["origin"] != origin or intent["binding_digest"] != _digest(row["binding"]) or intent["key"] not in row["action_keys"]):
      _invalid()
    return _registration(intent)
  return runs._transaction(read)
