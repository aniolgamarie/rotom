"""私有确认范围引用表；不确认用户来源、不发送模型、不签执行许可。

宿主为一次活动实例和真实确认生成私有幂等nonce。公开session ID、模型文本
和工具参数不能作为这些nonce的授权来源。目录建立先持久化；所有映射/退役
在账户短锁内原子保存，不删除墓碑、不跨重启猜测活动实例仍有权限。
"""
from copy import deepcopy
import json
import os
import re
import time
import uuid

from .pi_registered_roots import RegisteredRoots, physical, identity
from .pi_reviewer_authority import _snapshot, _expected
from .pi_reviewer_authority_protocol import check_effective
from .schema import ConfigError
from .storage import Conflict, Tree


DIRECTORY = "reviewer-scopes"
FILE = "scopes.json"
MAX_BYTES = 4 * 1024 * 1024


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_SCOPE_INVALID")


def _closed(value, fields):
  if type(value) is not dict or set(value) != set(fields): _invalid()


def _ref(value):
  if type(value) is not str or not re.fullmatch("[0-9a-f]{32}", value): _invalid()


def _tool(value):
  if type(value) is not str or not re.fullmatch("[!-~]{1,512}", value): _invalid()


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result: _invalid()
    result[key] = value
  return result


def _encode(value):
  return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("ascii")


def _decode(raw):
  try: return json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda _: _invalid())
  except (ValueError, UnicodeError, RecursionError): _invalid()


def _validate(value):
  _closed(value, ("schema_version", "account_identity", "registry_identity", "scopes_identity", "sessions", "intents", "requests"))
  if type(value["schema_version"]) is not int or value["schema_version"] != 1: _invalid()
  for field in ("account_identity", "registry_identity", "scopes_identity"):
    if type(value[field]) is not dict: _invalid()
    identity(value[field])
  for field in ("sessions", "intents", "requests"):
    if type(value[field]) is not dict: _invalid()
  if sum(len(value[field]) for field in ("sessions", "intents", "requests")) > 4096: _invalid()
  sessions, intents, used, tools = {}, {}, set(), set()
  def unique(ref):
    _ref(ref)
    if ref in used: _invalid()
    used.add(ref)
  for nonce, row in value["sessions"].items():
    _ref(nonce); _closed(row, ("session_scope", "retired")); unique(row["session_scope"])
    if type(row["retired"]) is not bool: _invalid()
    sessions[row["session_scope"]] = row
  for nonce, row in value["intents"].items():
    _ref(nonce); _closed(row, ("session_scope", "intent_ref", "retired"))
    _ref(row["session_scope"]); unique(row["intent_ref"])
    if row["session_scope"] not in sessions or type(row["retired"]) is not bool: _invalid()
    intents[row["intent_ref"]] = row
  for ref, row in value["requests"].items():
    unique(ref); _closed(row, ("session_scope", "intent_ref", "tool_call_id"))
    _ref(row["session_scope"]); _ref(row["intent_ref"]); _tool(row["tool_call_id"])
    if row["intent_ref"] not in intents or intents[row["intent_ref"]]["session_scope"] != row["session_scope"]: _invalid()
    key = (row["session_scope"], row["intent_ref"], row["tool_call_id"])
    if key in tools: _invalid()
    tools.add(key)
  return sessions, intents


def _snapshot_scopes(tree, account_identity):
  """仅已持有账户短锁的自有控制器复用，不新建Root或再取flock。"""
  if tree is None or not os.path.lexists(tree.root / DIRECTORY): raise Conflict("REVIEW_SCOPE_RECOVERY_REQUIRED")
  with Tree(tree.root / DIRECTORY) as scope:
    if set(os.listdir(scope.fd)) != {FILE}: raise Conflict("REVIEW_SCOPE_RECOVERY_REQUIRED")
    saved = scope.read(FILE, max_bytes=MAX_BYTES)
    if saved is None or saved[1] != 0o600: raise Conflict("REVIEW_SCOPE_INVALID")
    value = _decode(saved[0]); _validate(value)
    if (value["account_identity"] != account_identity
        or value["registry_identity"] != physical(os.fstat(tree.fd))
        or value["scopes_identity"] != physical(os.fstat(scope.fd))):
      raise Conflict("REVIEW_SCOPE_RECOVERY_REQUIRED")
    return value, saved


def _check_scope_binding(tree, account_identity, binding):
  """原账户锁内精确核验请求引用；文件存在不代表运行中确认能力仍活动。"""
  _closed(binding, ("session_scope", "intent_ref", "request_ref"))
  for ref in binding.values(): _ref(ref)
  value, _ = _snapshot_scopes(tree, account_identity)
  sessions, intents = _validate(value)
  session, intent = sessions.get(binding["session_scope"]), intents.get(binding["intent_ref"])
  if session is None or intent is None or intent["session_scope"] != binding["session_scope"]:
    raise Conflict("REVIEW_SCOPE_UNKNOWN")
  if session["retired"] or intent["retired"]: raise Conflict("REVIEW_SCOPE_RETIRED")
  row = value["requests"].get(binding["request_ref"])
  if row is None or any(row[key] != binding[key] for key in ("session_scope", "intent_ref")):
    raise Conflict("REVIEW_SCOPE_UNKNOWN")
  return True


def _error(error):
  if isinstance(error, ConfigError) and error.code in ("PI_RISK_REVIEW_SCOPE_INVALID", "PI_RISK_REVIEW_AUTHORITY_INVALID"):
    raise error from None
  if isinstance(error, Conflict):
    code = str(error)
    if code == "WORKSPACE_BUSY：账户协调锁繁忙": raise Conflict("REVIEW_ACCOUNT_BUSY") from None
    if re.fullmatch("REVIEW_(?:SCOPE|AUTHORITY)_[A-Z_]+", code): raise error from None
  raise Conflict("REVIEW_SCOPE_INVALID") from None


class ReviewerScopeStore:
  def __init__(self, *, account_home=None, authority_identity=None, now=None, max_records=4096):
    if type(max_records) is not int or not 1 <= max_records <= 4096: _invalid()
    if authority_identity is not None:
      _expected(authority_identity)
      if now is not None and not callable(now): _invalid()
    elif now is not None: _invalid()
    self.__authority_identity, self.__max_records = authority_identity, max_records
    # now只供受信本地同步时钟/临时测试；在账户锁内取值，禁止等待IO或重入控制面。
    # 产品默认使用下面的time.time_ns；此构造参数不能注册为模型/RPC输入。
    self.__now = now if now is not None else lambda: time.time_ns() // 1_000_000_000
    try: self.__roots = RegisteredRoots(account_home=account_home)
    except Exception as error: _error(error)

  def __authority(self, tree):
    if self.__authority_identity is None: raise Conflict("REVIEW_SCOPE_AUTHORITY_REQUIRED")
    snapshot, _ = _snapshot(tree, self.__roots.account_identity)
    if snapshot["identity"] != self.__authority_identity: raise Conflict("REVIEW_AUTHORITY_STALE")
    check_effective(snapshot["document"], self.__now())

  def __read(self, tree):
    return _snapshot_scopes(tree, self.__roots.account_identity)

  def __durable(self, tree, saved):
    # 丢失原写入回执后，幂等重读仍先核验并fsync原文件/目录再返回引用。
    with Tree(tree.root / DIRECTORY) as scope:
      with scope.open_read(FILE, max_bytes=MAX_BYTES) as (stream, info):
        if scope.read(FILE, max_bytes=MAX_BYTES) != saved: raise Conflict("REVIEW_SCOPE_WRITE_UNCONFIRMED")
        os.fsync(stream.fileno())
      os.fsync(scope.fd)
      if scope.read(FILE, max_bytes=MAX_BYTES) != saved: raise Conflict("REVIEW_SCOPE_WRITE_UNCONFIRMED")

  def __write(self, tree, value, *, expected):
    _validate(value)
    raw = _encode(value)
    if len(raw) > MAX_BYTES: _invalid()
    try:
      with Tree(tree.root / DIRECTORY) as scope: scope.replace(FILE, raw, expected=expected)
      actual, _ = self.__read(tree)
      if actual != value: raise Conflict("REVIEW_SCOPE_WRITE_UNCONFIRMED")
    except Exception: raise Conflict("REVIEW_SCOPE_WRITE_UNCONFIRMED") from None

  def initialize(self):
    """仅私有首次bootstrap显式调用；常规打开、查询和缺失恢复不初始化。"""
    try:
      with self.__roots._locked(write=True) as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          self.__authority(tree)
          if os.path.lexists(tree.root / DIRECTORY):
            self.__read(tree)
            raise Conflict("REVIEW_SCOPE_EXISTS")
          if {"reviewer-budget", "reviewer-budget.json"} & set(os.listdir(tree.fd)):
            raise Conflict("REVIEW_SCOPE_RECOVERY_REQUIRED")
          # 先留下持久目录，再写表；空目录是恢复标记，不能自动删除或重建。
          os.mkdir(DIRECTORY, mode=0o700, dir_fd=tree.fd); os.fsync(tree.fd)
          with Tree(tree.root / DIRECTORY) as scope:
            value = {"schema_version": 1, "account_identity": deepcopy(self.__roots.account_identity),
              "registry_identity": physical(os.fstat(tree.fd)), "scopes_identity": physical(os.fstat(scope.fd)),
              "sessions": {}, "intents": {}, "requests": {}}
          self.__write(tree, value, expected=None)
          return self.__counts(value)
    except Exception as error: _error(error)

  def __counts(self, value):
    return {"sessions": len(value["sessions"]), "intents": len(value["intents"]), "requests": len(value["requests"]),
      "retired_sessions": sum(row["retired"] for row in value["sessions"].values()),
      "retired_intents": sum(row["retired"] for row in value["intents"].values())}

  def snapshot(self):
    try:
      with self.__roots._locked() as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          value, _ = self.__read(tree)
          return self.__counts(value)
    except Exception as error: _error(error)

  def __new_ref(self, value):
    # 降低新增容量不删除旧映射，重开/对账和满容量的幂等重读仍可保留旧ref。
    if sum(len(value[field]) for field in ("sessions", "intents", "requests")) >= self.__max_records:
      raise Conflict("REVIEW_SCOPE_CAPACITY")
    ref = uuid.uuid4().hex; _ref(ref)
    used = {row["session_scope"] for row in value["sessions"].values()}
    used.update(row["intent_ref"] for row in value["intents"].values()); used.update(value["requests"])
    if ref in used: raise Conflict("REVIEW_SCOPE_COLLISION")
    return ref

  def __live(self, value, session_scope, intent_ref=None):
    sessions, intents = _validate(value)
    session = sessions.get(session_scope)
    if session is None: raise Conflict("REVIEW_SCOPE_UNKNOWN")
    if session["retired"]: raise Conflict("REVIEW_SCOPE_RETIRED")
    if intent_ref is not None:
      intent = intents.get(intent_ref)
      if intent is None or intent["session_scope"] != session_scope: raise Conflict("REVIEW_SCOPE_UNKNOWN")
      if intent["retired"]: raise Conflict("REVIEW_SCOPE_RETIRED")

  def __call(self, action):
    try:
      with self.__roots._locked(write=True) as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          self.__authority(tree)
          value, saved = self.__read(tree)
          result, changed = action(value)
          if changed: self.__write(tree, value, expected=saved[2])
          else: self.__durable(tree, saved)
          return deepcopy(result)
    except Exception as error: _error(error)

  def allocate_session(self, activation_ref):
    _ref(activation_ref)
    def action(value):
      row = value["sessions"].get(activation_ref)
      if row is not None:
        self.__live(value, row["session_scope"])
        return row["session_scope"], False
      ref = self.__new_ref(value)
      value["sessions"][activation_ref] = {"session_scope": ref, "retired": False}
      return ref, True
    return self.__call(action)

  def allocate_intent(self, session_scope, confirmation_ref):
    _ref(session_scope); _ref(confirmation_ref)
    def action(value):
      self.__live(value, session_scope)
      row = value["intents"].get(confirmation_ref)
      if row is not None:
        if row["session_scope"] != session_scope: raise Conflict("REVIEW_SCOPE_NONCE_CONFLICT")
        self.__live(value, session_scope, row["intent_ref"])
        return {key: row[key] for key in ("session_scope", "intent_ref")}, False
      ref = self.__new_ref(value)
      value["intents"][confirmation_ref] = {"session_scope": session_scope, "intent_ref": ref, "retired": False}
      return {"session_scope": session_scope, "intent_ref": ref}, True
    return self.__call(action)

  def allocate_request(self, binding):
    _closed(binding, ("session_scope", "intent_ref", "tool_call_id"))
    _ref(binding["session_scope"]); _ref(binding["intent_ref"]); _tool(binding["tool_call_id"])
    binding = deepcopy(binding)
    def action(value):
      self.__live(value, binding["session_scope"], binding["intent_ref"])
      for ref, row in value["requests"].items():
        if row == binding: return ref, False
      ref = self.__new_ref(value); value["requests"][ref] = binding
      return ref, True
    return self.__call(action)

  def verify_current(self, binding):
    _closed(binding, ("session_scope", "intent_ref", "request_ref"))
    for ref in binding.values(): _ref(ref)
    try:
      with self.__roots._locked() as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          self.__authority(tree)
          return _check_scope_binding(tree, self.__roots.account_identity, binding)
    except Exception as error: _error(error)

  def __retire(self, session_scope, intent_ref):
    _ref(session_scope)
    if intent_ref is not None: _ref(intent_ref)
    try:
      with self.__roots._locked(write=True) as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          value, saved = self.__read(tree)
          sessions, intents = _validate(value)
          session = sessions.get(session_scope)
          row = session if intent_ref is None else intents.get(intent_ref)
          if session is None or row is None or row.get("session_scope") != session_scope: raise Conflict("REVIEW_SCOPE_UNKNOWN")
          if row["retired"]: self.__durable(tree, saved)
          else:
            row["retired"] = True
            self.__write(tree, value, expected=saved[2])
          return self.__counts(value)
    except Exception as error: _error(error)

  def retire_session(self, session_scope):
    return self.__retire(session_scope, None)

  def retire_intent(self, session_scope, intent_ref):
    return self.__retire(session_scope, intent_ref)

  def __retire_nonce(self, nonce, session_scope=None):
    """私有分配回执丢失时仍按原nonce留墓碑；只创建retired行，不建立权限。"""
    _ref(nonce)
    if session_scope is not None: _ref(session_scope)
    try:
      with self.__roots._locked(write=True) as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          # 退役不依赖尚有效的authority；仍要求原账户根及完整已初始化scope表。
          value, saved = self.__read(tree)
          sessions, _ = _validate(value)
          if session_scope is None:
            rows, field = value["sessions"], "session_scope"
          else:
            if session_scope not in sessions: raise Conflict("REVIEW_SCOPE_UNKNOWN")
            rows, field = value["intents"], "intent_ref"
          row = rows.get(nonce)
          if row is not None and session_scope is not None and row["session_scope"] != session_scope:
            raise Conflict("REVIEW_SCOPE_NONCE_CONFLICT")
          if row is None:
            row = {field: self.__new_ref(value), "retired": True}
            if session_scope is not None: row["session_scope"] = session_scope
            rows[nonce] = row
            self.__write(tree, value, expected=saved[2])
          elif row["retired"]:
            self.__durable(tree, saved)
          else:
            row["retired"] = True
            self.__write(tree, value, expected=saved[2])
          return self.__counts(value)
    except Exception as error: _error(error)

  def retire_session_activation(self, activation_ref):
    """仅可信控制器持有的原activation nonce；不接受公开SDK session ID替代。"""
    return self.__retire_nonce(activation_ref)

  def retire_intent_confirmation(self, session_scope, confirmation_ref):
    """原session与私有确认nonce；未知分配回执不能让迟到分配重新开放。"""
    _ref(session_scope)
    return self.__retire_nonce(confirmation_ref, session_scope)
