"""账户短锁下的累计reviewer账本；不启用SDK、产品factory或恢复/清零。

锁顺序固定账户→原ledger实例锁。写入与旧get/snapshot先持久updating，再调用原ledger；
新ready持久后才返回。未知部分状态只拒绝，不回滚账本或猜测是否已发送。
observe仅在账户共享短锁内核对ready并读取原行，不写入或取得发送资格。
账户自身可抹除所有控制文件属于既有受信OS账户边界，不提供外部签名。
"""
from copy import deepcopy
import hashlib
import json
import os
import re
import time

from .pi_registered_roots import RegisteredRoots, physical, identity
from .pi_reviewer_ledger import ReviewerLedger, FILE, MAX_BYTES, _limits, _integer, _document, _request, _hex
from .pi_reviewer_authority import _snapshot as _authority_snapshot, _expected
from .pi_reviewer_authority_protocol import check_effective, price_identity, RATES
from .pi_reviewer_scopes import _snapshot_scopes, _check_scope_binding
from .schema import ConfigError
from .storage import Conflict, Tree

SENTINEL = "reviewer-budget.json"
DIRECTORY = "reviewer-budget"
MAX_SENTINEL = 8192
KEYS = {"schema_version", "state", "account_identity", "registry_identity", "budget_identity", "ledger_identity", "ledger_sha256"}


def _invalid():
  raise Conflict("REVIEW_ACCOUNT_INVALID")


def _recovery():
  raise Conflict("REVIEW_ACCOUNT_RECOVERY_REQUIRED")


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result: _invalid()
    result[key] = value
  return result


def _decode(raw):
  try:
    return json.loads(raw, object_pairs_hook=_pairs, parse_constant=lambda value: _invalid())
  except (ValueError, UnicodeError, RecursionError):
    _invalid()


def _encode(value):
  return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _safe_error(error):
  if isinstance(error, Conflict) and str(error) == "WORKSPACE_BUSY：账户协调锁繁忙":
    raise Conflict("REVIEW_ACCOUNT_BUSY") from None
  if isinstance(error, ConfigError) and error.code in ("PI_RISK_REVIEW_LEDGER_INVALID", "PI_RISK_REVIEW_AUTHORITY_INVALID", "PI_RISK_REVIEW_SCOPE_INVALID"):
    raise error from None
  if isinstance(error, Conflict) and re.fullmatch("REVIEW_[A-Z_]+", str(error)):
    raise error from None
  # 未知底层错误不进入对外默认traceback；固定消息也须关闭隐式异常链渲染。
  raise Conflict("REVIEW_ACCOUNT_INVALID") from None


class ReviewerAccountLedger:
  def __init__(self, *, limits=None, account_home=None, max_records=4096, authority_identity=None, now=None, scope_required=False):
    # 产品绑定态仅从同一账户授权取额度；旧组件接口仍用于独立离线账本。
    self.__authority_identity = authority_identity
    if type(scope_required) is not bool or scope_required and authority_identity is None:
      raise ConfigError("PI_RISK_REVIEW_LEDGER_INVALID")
    self.__scope_required = scope_required
    self.__settlement_only = False
    if authority_identity is None:
      if now is not None: raise ConfigError("PI_RISK_REVIEW_AUTHORITY_INVALID")
      self.__limits = _limits(limits)
      self.__now = None
    else:
      _expected(authority_identity)
      if limits is not None or now is not None and not callable(now):
        raise ConfigError("PI_RISK_REVIEW_AUTHORITY_INVALID")
      self.__limits = None
      self.__now = now if now is not None else lambda: time.time_ns() // 1_000_000_000
    _integer(max_records, 1, 4096)
    self.__max_records = max_records
    try:
      self.__roots = RegisteredRoots(account_home=account_home)
      with self.__roots._locked(write=True) as account_fd:
        with self.__roots._state(account_fd, create=authority_identity is None) as (tree, registry, raw):
          if authority_identity is not None:
            self.__limits = deepcopy(self.__authority(tree)["limits"])
          if self.__scope_required: _snapshot_scopes(tree, self.__roots.account_identity)
          if raw is None:
            tree.replace("registry.json", _encode(registry), expected=None)
          saved = tree.read(SENTINEL, max_bytes=MAX_SENTINEL)
          exists = os.path.lexists(tree.root / DIRECTORY)
          if saved is None and not exists:
            self.__initialize(tree)
          elif saved is None or not exists:
            _recovery()
          else:
            self.__operate(tree, "snapshot", (), {})
    except Exception as error:
      _safe_error(error)

  @classmethod
  def for_settlement(cls, *, account_home=None, max_records=4096):
    """重启后仅对账旧事实；不读取授权、不建新账本、不获得发送能力。"""
    _integer(max_records, 1, 4096)
    value = cls.__new__(cls)
    value.__authority_identity, value.__now, value.__settlement_only = None, None, True
    value.__scope_required = False
    value.__limits, value.__max_records = None, max_records
    try:
      value.__roots = RegisteredRoots(account_home=account_home)
      with value.__roots._locked() as account_fd:
        with value.__roots._state(account_fd) as (tree, _, __):
          if tree is None: _recovery()
          value.__limits = value.__fact_limits(tree)
    except Exception as error:
      _safe_error(error)
    return value

  def __authority(self, tree):
    snapshot, _ = _authority_snapshot(tree, self.__roots.account_identity)
    if snapshot["identity"] != self.__authority_identity:
      raise Conflict("REVIEW_AUTHORITY_STALE")
    check_effective(snapshot["document"], self.__now())
    return snapshot["document"]

  def __fact_limits(self, tree):
    # 迟到的发送/用量事实不能因授权撤回而丢失；只沿用已核验持久账本的额度。
    self.__ready(tree)
    with Tree(tree.root / DIRECTORY) as budget:
      saved = budget.read(FILE, max_bytes=MAX_BYTES)
      if saved is None: _recovery()
      document = _decode(saved[0]); _document(document)
      return _limits(document["limits"])

  def __base(self, tree):
    return {"schema_version": 1, "state": "preparing", "account_identity": deepcopy(self.__roots.account_identity),
      "registry_identity": physical(os.fstat(tree.fd)), "budget_identity": None,
      "ledger_identity": None, "ledger_sha256": None}

  def __initialize(self, tree):
    state = self.__base(tree)
    # Preparing必先落盘；任何随后异常都留下恢复待处理，不删除部分状态。
    tree.replace(SENTINEL, _encode(state), expected=None)
    os.mkdir(DIRECTORY, 0o700, dir_fd=tree.fd)
    os.fsync(tree.fd)
    ReviewerLedger(tree.root / DIRECTORY, limits=self.__limits, max_records=self.__max_records, create=True)
    with Tree(tree.root / DIRECTORY) as budget:
      self.__members(budget)
      state.update(state="ready", budget_identity=physical(os.fstat(budget.fd)), **self.__binding(budget))
    saved = tree.read(SENTINEL, max_bytes=MAX_SENTINEL)
    tree.replace(SENTINEL, _encode(state), expected=saved[2])

  def __members(self, budget):
    if budget.fd is None or set(os.listdir(budget.fd)) != {FILE, "instance.lock"}: _recovery()
    lock = budget.read("instance.lock", max_bytes=65536)
    if lock is None or lock[1] != 0o600: _invalid()

  def __binding(self, budget):
    saved = budget.read(FILE, max_bytes=MAX_BYTES)
    if saved is None: _recovery()
    if saved[1] != 0o600: _invalid()
    _document(_decode(saved[0]))
    return {"ledger_identity": list(saved[2]), "ledger_sha256": hashlib.sha256(saved[0]).hexdigest()}

  def __ready(self, tree):
    saved = tree.read(SENTINEL, max_bytes=MAX_SENTINEL)
    if saved is None: _recovery()
    if saved[1] != 0o600: _invalid()
    state = _decode(saved[0])
    if type(state) is not dict or set(state) != KEYS or type(state["schema_version"]) is not int or state["schema_version"] != 1: _invalid()
    if state["state"] in ("preparing", "updating"): _recovery()
    if state["state"] != "ready": _invalid()
    for key in ("account_identity", "registry_identity", "budget_identity"):
      if type(state[key]) is not dict: _invalid()
      identity(state[key])
    if (state["account_identity"] != self.__roots.account_identity
        or state["registry_identity"] != physical(os.fstat(tree.fd))): _recovery()
    if (type(state["ledger_identity"]) is not list or len(state["ledger_identity"]) != 6
        or any(type(v) is not int or v < 0 for v in state["ledger_identity"])
        or type(state["ledger_sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}", state["ledger_sha256"])): _invalid()
    with Tree(tree.root / DIRECTORY) as budget:
      self.__members(budget)
      if state["budget_identity"] != physical(os.fstat(budget.fd)): _recovery()
      if self.__binding(budget) != {key: state[key] for key in ("ledger_identity", "ledger_sha256")}: _recovery()
    return state, saved

  def __operate(self, tree, method, args, kwargs, *, limits=None):
    ready, saved = self.__ready(tree)
    updating = {**ready, "state": "updating"}
    tree.replace(SENTINEL, _encode(updating), expected=saved[2])
    try:
      ledger = ReviewerLedger(tree.root / DIRECTORY, limits=self.__limits if limits is None else limits,
        max_records=self.__max_records, create=False)
      result = getattr(ledger, method)(*args, **kwargs)
    except Exception as error:
      # 只有账本字节及身份完全未变才可恢复原ready；变化或未知必须保持updating。
      try:
        with Tree(tree.root / DIRECTORY) as budget:
          self.__members(budget)
          if physical(os.fstat(budget.fd)) != ready["budget_identity"]: _recovery()
          if self.__binding(budget) != {key: ready[key] for key in ("ledger_identity", "ledger_sha256")}: _recovery()
        current = tree.read(SENTINEL, max_bytes=MAX_SENTINEL)
        if current is None or current[0] != _encode(updating): _recovery()
        tree.replace(SENTINEL, _encode(ready), expected=current[2])
      except Exception:
        _recovery()
      _safe_error(error)
    with Tree(tree.root / DIRECTORY) as budget:
      self.__members(budget)
      if physical(os.fstat(budget.fd)) != ready["budget_identity"]: _recovery()
      fresh = {**ready, **self.__binding(budget)}
    current = tree.read(SENTINEL, max_bytes=MAX_SENTINEL)
    if current is None or current[0] != _encode(updating): _recovery()
    tree.replace(SENTINEL, _encode(fresh), expected=current[2])
    return result

  def __call(self, method, args, kwargs):
    if self.__settlement_only and method in ("reserve", "claim_attempt", "commit_send"):
      raise Conflict("REVIEW_SETTLEMENT_ONLY")
    try:
      with self.__roots._locked(write=True) as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          if tree is None: _recovery()
          limits = None
          if self.__authority_identity is not None or self.__settlement_only:
            if method in ("reserve", "claim_attempt", "commit_send"):
              document = self.__authority(tree)
              limits = document["limits"]
              if method == "reserve":
                pricing = {"identity": price_identity(document), "currency": document["pricing"]["currency"],
                  **{key: document["pricing"][key] for key in RATES}}
                if kwargs["pricing"] != pricing or kwargs["token_limits"] != document["token_limits"]:
                  raise Conflict("REVIEW_AUTHORITY_REQUEST_MISMATCH")
              if self.__scope_required:
                if method == "reserve":
                  binding = {**kwargs["scope"], "request_ref": kwargs["binding"]["request_id"]}
                else:
                  # 从已核验持久原请求取refs，不从后续参数另分配或改绑定。
                  _hex(args[0], 32); self.__ready(tree)
                  with Tree(tree.root / DIRECTORY) as budget:
                    saved = budget.read(FILE, max_bytes=MAX_BYTES)
                    if saved is None: _recovery()
                    state = _decode(saved[0]); _document(state)
                    row = state["rows"].get(args[0])
                    if row is None: raise Conflict("REVIEW_UNKNOWN")
                    binding = {**row["scope"], "request_ref": row["binding"]["request_id"]}
                # 同一账户锁串行化retire与持久commit；不经公开Store方法再取锁。
                _check_scope_binding(tree, self.__roots.account_identity, binding)
            else:
              limits = self.__fact_limits(tree)
          return self.__operate(tree, method, args, kwargs, limits=limits)
    except Exception as error:
      _safe_error(error)

  def reserve(self, *, binding, scope, pricing, token_limits):
    request = _request(binding, scope, pricing, token_limits)
    return self.__call("reserve", (), request)

  def claim_attempt(self, operation_id):
    return self.__call("claim_attempt", (operation_id,), {})

  def commit_send(self, operation_id):
    return self.__call("commit_send", (operation_id,), {})

  def mark_sent(self, operation_id):
    return self.__call("mark_sent", (operation_id,), {})

  def finish(self, operation_id, *, requests, outcome, decision=None, reason_code=None):
    return self.__call("finish", (operation_id,), {"requests": requests, "outcome": outcome, "decision": decision, "reason_code": reason_code})

  def record_usage(self, operation_id, usage, *, final=False, process_terminated=False):
    return self.__call("record_usage", (operation_id, usage), {"final": final, "process_terminated": process_terminated})

  def get(self, operation_id):
    return self.__call("get", (operation_id,), {})

  def observe(self, operation_id):
    """纯读取已持久原事实；不修复未知状态，也不证明authority/scope仍live。"""
    try:
      _hex(operation_id, 32)
      with self.__roots._locked() as account_fd:
        with self.__roots._state(account_fd) as (tree, _, __):
          if tree is None: _recovery()
          ready, _ = self.__ready(tree)
          with Tree(tree.root / DIRECTORY) as budget:
            self.__members(budget)
            if physical(os.fstat(budget.fd)) != ready["budget_identity"]: _recovery()
            saved = budget.read(FILE, max_bytes=MAX_BYTES)
            if saved is None: _recovery()
            if saved[1] != 0o600: _invalid()
            # 共享账户锁阻止合作写入；仍复核本次读取的原文件身份与字节绑定。
            if (list(saved[2]) != ready["ledger_identity"] or
                hashlib.sha256(saved[0]).hexdigest() != ready["ledger_sha256"]): _recovery()
            document = _decode(saved[0]); _document(document)
            row = document["rows"].get(operation_id)
            if row is None: raise Conflict("REVIEW_UNKNOWN")
            return deepcopy(row)
    except Exception as error:
      _safe_error(error)

  def snapshot(self):
    return self.__call("snapshot", (), {})
