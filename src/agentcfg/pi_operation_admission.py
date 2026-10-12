"""受信准备器的内存准入账本；不解析模型身份、不取得租约或执行任何 IO。

正式入口须先由受信适配器解析身份、最终参数、硬策略和后端，再调用本模块。
consume 返回后才可进入 ExecutionStore；失败不能恢复许可。此模块尚未接入旧入口。
"""

from copy import deepcopy
import json
import math
from pathlib import PurePosixPath
import re
from threading import Lock
import time
import uuid

from .activity import digest
from .schema import ConfigError
from .storage import Conflict


HEX = re.compile(r"[0-9a-f]{64}")
FILES = frozenset({"read", "write", "edit", "rename", "ls", "find", "grep"})
CONTEXT = ("activation_id", "profile", "session_id", "role_id", "cwd", "user_intent_ref",
  "restrictions_digest", "policy_generation", "cancel_epoch", "runtime_identity", "config_identity",
  "reviewer_identity", "deadline_ms")


def _invalid():
  # 校验失败不把参数、秘密正文或源异常加入错误。
  raise ConfigError("pi-operation-admission")


def _closed(value, fields):
  if type(value) is not dict or set(value) != set(fields): _invalid()


def _text(value, limit=512):
  if type(value) is not str or not value or len(value) > limit or any(ord(char) < 32 for char in value): _invalid()


def _sha(value):
  if type(value) is not str or not HEX.fullmatch(value): _invalid()


def _integer(value, minimum=0):
  if type(value) is not int or not minimum <= value <= 2**53 - 1: _invalid()


def _path(value):
  _text(value, 4096)
  path = PurePosixPath(value)
  if not path.is_absolute() or str(path) != value or ".." in path.parts or value.startswith("//"): _invalid()


def _json(value, *, limit=1024 * 1024, allow_finite_numbers=False):
  # JSON 不接受隐式类型转换、非有限数或自定义对象；正文只用于私有内存相等比较。
  # 先计算精确UTF-8序列化大小，避免巨型字符串先生成副本才命中容量限制。
  size = 0
  def add(count):
    nonlocal size
    size += count
    if size > limit: raise Conflict("OPERATION_CAPACITY")
  def string(item):
    if len(item) > limit - size: raise Conflict("OPERATION_CAPACITY")
    add(2)
    for char in item:
      code = ord(char)
      if 0xD800 <= code <= 0xDFFF: _invalid()
      add(2 if char in '\\"\b\f\n\r\t' else 6 if code < 32 else 1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4)
  def check(item, depth=0):
    if depth > 32: _invalid()
    if item is None: add(4); return
    if type(item) is bool: add(4 if item else 5); return
    if type(item) is str: string(item); return
    if type(item) is int:
      if abs(item) > (1.7976931348623157e308 if allow_finite_numbers else 2**53 - 1): _invalid()
      add(len(str(item)))
      return
    if type(item) is float and allow_finite_numbers:
      if not math.isfinite(item): _invalid()
      add(len(json.dumps(item, allow_nan=False)))
      return
    if type(item) is list:
      add(2 + max(0, len(item) - 1))
      for child in item: check(child, depth + 1)
      return
    if type(item) is dict and all(type(key) is str for key in item):
      add(2 + max(0, len(item) - 1) + len(item))
      for key, child in item.items(): string(key); check(child, depth + 1)
      return
    _invalid()
  check(value)
  try: return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf8")
  except (UnicodeError, ValueError): _invalid()


def encode_private_input(value, *, limit=1024 * 1024, allow_finite_numbers=False):
  """给实际工具入口复用同一有界私有表示，不生成正文摘要或权限。"""
  if type(limit) is not int or limit < 1 or type(allow_finite_numbers) is not bool: _invalid()
  return _json(value, limit=limit, allow_finite_numbers=allow_finite_numbers)


def context(value):
  _closed(value, CONTEXT)
  for key in ("activation_id", "session_id", "role_id", "user_intent_ref"): _text(value[key])
  if value["profile"] not in ("pi-base", "pi-full"): _invalid()
  _path(value["cwd"])
  for key in ("restrictions_digest", "runtime_identity", "config_identity"): _sha(value[key])
  if value["reviewer_identity"] is not None: _sha(value["reviewer_identity"])
  if value["profile"] == "pi-base" and value["reviewer_identity"] is not None: _invalid()
  _integer(value["policy_generation"], 1); _integer(value["cancel_epoch"]); _integer(value["deadline_ms"], 1)
  _json(value)
  return deepcopy(value)


def resolution(value):
  """只接受受信准备器完成硬策略检查的结果；不是向模型开放的请求接口。"""
  _closed(value, ("kind", "tool_name", "target", "read_roots", "write_roots", "workspace_keys",
    "network", "services", "backend", "policy"))
  for key in ("kind", "tool_name", "network", "backend"): _text(value[key])
  policy = value["policy"]
  fields = {"generation", "policy_digest", "ceiling_digest", "hard_policy", "requires_human"}
  # 旧可信组件的五字段投影保留原语义；新匹配器必须显式提供审批等级。
  if type(policy) is not dict or set(policy) not in (fields, fields | {"approval"}): _invalid()
  _integer(policy["generation"], 1); _sha(policy["policy_digest"]); _sha(policy["ceiling_digest"])
  if policy["hard_policy"] != "allow": raise Conflict("OPERATION_HARD_DENIED")
  if type(policy["requires_human"]) is not bool: _invalid()
  if "approval" in policy:
    approval = policy["approval"]
    if (type(approval) is not str or approval not in ("human", "reviewer", "deterministic-policy")
        or policy["requires_human"] != (approval == "human")): _invalid()
  for key in ("read_roots", "write_roots"):
    if type(value[key]) is not list: _invalid()
    paths = set()
    for root in value[key]:
      _closed(root, ("path", "identity")); _path(root["path"]); _sha(root["identity"])
      if root["path"] in paths: _invalid()
      paths.add(root["path"])
  if type(value["workspace_keys"]) is not list: _invalid()
  for key in value["workspace_keys"]: _sha(key)
  if len(set(value["workspace_keys"])) != len(value["workspace_keys"]): _invalid()
  # 服务投影来自受信准备器；名称不能自证隔离、网络或执行许可。
  mcp = value["kind"] == "mcp"
  if not mcp and (value["network"] != "deny" or value["services"] != []): _invalid()
  target = value["target"]
  if mcp:
    if (value["tool_name"] != "mcp" or value["backend"] != "native-mcp-v1"
        or value["network"] not in ("deny", "managed-route")
        or value["read_roots"] or value["write_roots"] or value["workspace_keys"]): _invalid()
    _closed(target, ("server_names", "action", "name", "binding_digest"))
    names = target["server_names"]
    if (type(names) is not list or not 0 < len(names) <= 64
        or any(type(name) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) for name in names)
        or len(set(names)) != len(names) or value["services"] != ["mcp:" + name for name in names]): _invalid()
    if target["action"] not in ("tool", "list_resources", "list_templates", "read_resource", "tool_search"): _invalid()
    _text(target["name"], 64)
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", target["name"]): _invalid()
    if target["action"] == "tool" and len(names) != 1: _invalid()
    _sha(target["binding_digest"])
  elif value["kind"] == "file":
    if value["tool_name"] not in FILES or value["backend"] != "guarded-files-v1": _invalid()
    _closed(target, ("path", "destination")); _path(target["path"])
    if value["tool_name"] == "rename": _path(target["destination"])
    elif target["destination"] is not None: _invalid()
    write = value["tool_name"] in ("write", "edit", "rename")
    if write != bool(value["write_roots"]) or write != bool(value["workspace_keys"]): _invalid()
    if not write and not value["read_roots"]: _invalid()
    def covered(path, roots):
      return any(PurePosixPath(path).is_relative_to(PurePosixPath(root["path"])) for root in roots)
    targets = [target["path"]] + ([target["destination"]] if value["tool_name"] == "rename" else [])
    if any(not covered(path, value["write_roots"] if write else value["read_roots"]) for path in targets): _invalid()
    if value["tool_name"] == "edit" and not covered(target["path"], value["read_roots"]): _invalid()
  elif value["kind"] in ("fixed-command", "shell-command"):
    if value["tool_name"] not in ("bash", "editor") or value["backend"] != "linux-bwrap-v1": _invalid()
    shell = value["kind"] == "shell-command"
    _closed(target, ("command_ref", "executable", "timeout_ms") if shell else ("command_ref", "argv", "executable", "timeout_ms"))
    _text(target["command_ref"]); _integer(target["timeout_ms"], 1)
    if shell:
      if value["tool_name"] != "bash" or not re.fullmatch(r"tool:[a-z][a-z0-9_-]{0,63}", target["command_ref"]): _invalid()
      if not value["read_roots"]: _invalid()
    else:
      if type(target["argv"]) is not list or not target["argv"]: _invalid()
      for arg in target["argv"]:
        if type(arg) is not str or "\0" in arg or len(arg) > 65536: _invalid()
    _closed(target["executable"], ("path", "device", "inode", "uid", "sha256"))
    executable = target["executable"]
    _path(executable["path"]); _sha(executable["sha256"])
    for key in ("device", "inode", "uid"): _integer(executable[key])
    if not shell and target["argv"][0] != executable["path"]: _invalid()
    if bool(value["write_roots"]) != bool(value["workspace_keys"]): _invalid()
  else: _invalid()
  _json(value)
  return deepcopy(value)


class OperationAdmissions:
  """一个受信控制面 activation 的一次许可，不提供可恢复的执行队列。

  受信调用者提供 current context 和重新核验过的 resolution；不接受模型自报身份。
  私有请求比较保留在有限内存内，不将正文或其 hash 放进可序列化的投影。
  容量耗尽明确拒绝，不删除仍需防重放的条目。生命周期整合由宿主适配器负责。
  """
  def __init__(self, activation_id, *, now_ms=lambda: time.time_ns() // 1_000_000,
      max_operations=4096, max_private_bytes=32 * 1024 * 1024, reviewer_current=None):
    _text(activation_id); _integer(max_operations, 1); _integer(max_private_bytes, 1)
    if reviewer_current is not None and not callable(reviewer_current): _invalid()
    self._reviewer_current = reviewer_current
    self.activation_id, self.now_ms = activation_id, now_ms
    self.max_operations, self.max_private_bytes = max_operations, max_private_bytes
    self._lock, self._requests, self._operations, self._permits = Lock(), {}, {}, {}
    self._private_bytes = 0
    self._reviewer_scope_owner, self._reviewer_scope_binder = None, None

  def _claim_reviewer_scope_owner(self, owner, *, binder=None):
    """私有原生对象能力永久占槽；不授许可，也不获取service或账户锁。"""
    if type(owner) is not object or binder is not None and type(binder) is not object: _invalid()
    with self._lock:
      if (self._reviewer_scope_owner is not None and self._reviewer_scope_owner is not owner or
          binder is not None and self._reviewer_scope_binder is not None and self._reviewer_scope_binder is not binder):
        raise Conflict("REVIEW_SCOPE_OWNER_ALREADY_BOUND")
      self._reviewer_scope_owner = owner
      if binder is not None: self._reviewer_scope_binder = binder

  def _context(self, current):
    current = context(current)
    if current["activation_id"] != self.activation_id: raise Conflict("OPERATION_CONTEXT_STALE")
    return current

  def prepare(self, request_id, *, current, resolved, private_input):
    _text(request_id)
    current, resolved = self._context(current), resolution(resolved)
    request = _json(private_input, limit=self.max_private_bytes, allow_finite_numbers=resolved["kind"] == "mcp")
    if resolved["policy"]["generation"] != current["policy_generation"]: raise Conflict("OPERATION_CONTEXT_STALE")
    key = (current["profile"], current["session_id"], request_id)
    with self._lock:
      if key in self._requests:
        record = self._requests[key]
        if (record["prepared"]["context"] != current or record["prepared"]["resolution"] != resolved
            or record["private_input"] != request): raise Conflict("OPERATION_IDEMPOTENCY_CONFLICT")
        return deepcopy(record["prepared"])
      if self.now_ms() >= current["deadline_ms"]: raise Conflict("OPERATION_EXPIRED")
      if len(self._operations) >= self.max_operations or self._private_bytes + len(request) > self.max_private_bytes:
        raise Conflict("OPERATION_CAPACITY")
      prepared = {"schema_version": 1, "operation_id": uuid.uuid4().hex, "request_id": request_id,
        "context": current, "resolution": resolved, "private_input_ref": uuid.uuid4().hex}
      prepared["operation_digest"] = digest(prepared)
      record = {"prepared": prepared, "private_input": request, "state": "prepared", "permit_id": None}
      self._requests[key] = self._operations[prepared["operation_id"]] = record
      self._private_bytes += len(request)
      return deepcopy(prepared)

  def _current(self, record, current):
    if record["prepared"]["context"] != current: raise Conflict("OPERATION_CONTEXT_STALE")
    if self.now_ms() >= current["deadline_ms"]:
      record["state"] = "expired"
      raise Conflict("OPERATION_EXPIRED")

  def _reviewer_qualified(self, record, current):
    # 受信同步hook在原非重入Lock内，仅读外部私有scope/authority/model/质量。
    # 可复用账户短锁，顺序Admission→account→ledger；账户临界区不得反调Admission。
    # hook不得重入同一Admissions，也不得等待网络、SDK进程或引入反向锁顺序。
    try:
      allowed = self._reviewer_current is not None and self._reviewer_current(
        deepcopy(record["prepared"]), deepcopy(current)) is True
    except Exception:
      allowed = False
    if not allowed: raise Conflict("OPERATION_REVIEWER_UNQUALIFIED") from None

  def issue(self, operation_id, *, operation_digest, current, source, reviewer_identity=None):
    """只接收受信决定者已作出的 allow；ask/deny 不调用 issue。"""
    _text(operation_id); _sha(operation_digest)
    current = self._context(current)
    if source not in ("deterministic-policy", "human", "reviewer"): _invalid()
    if reviewer_identity is not None: _sha(reviewer_identity)
    with self._lock:
      record = self._operations.get(operation_id)
      if record is None: raise Conflict("OPERATION_UNKNOWN")
      if record["state"] != "prepared": raise Conflict("OPERATION_NOT_PENDING")
      self._current(record, current)
      if operation_digest != record["prepared"]["operation_digest"]: raise Conflict("OPERATION_DECISION_MISMATCH")
      policy = record["prepared"]["resolution"]["policy"]
      if policy["requires_human"] and source != "human": raise Conflict("OPERATION_HUMAN_REQUIRED")
      # 原prepared限制实际签发来源；工具参数不能把reviewer级改作确定性允许。
      approval = policy.get("approval")
      if approval is not None and source != "human" and source != approval:
        raise Conflict("OPERATION_APPROVAL_SOURCE_MISMATCH")
      if ((source == "reviewer" and (reviewer_identity is None or reviewer_identity != current["reviewer_identity"]))
          or source != "reviewer" and reviewer_identity is not None): raise Conflict("OPERATION_REVIEWER_MISMATCH")
      if source == "reviewer": self._reviewer_qualified(record, current)
      permit = {"schema_version": 1, "permit_id": uuid.uuid4().hex, "operation_id": operation_id,
        "operation_digest": record["prepared"]["operation_digest"], "source": source,
        "reviewer_identity": reviewer_identity, "context": deepcopy(current)}
      record.update(state="permitted", permit_id=permit["permit_id"])
      self._permits[permit["permit_id"]] = (record, deepcopy(permit))
      return permit

  def consume(self, permit, *, current, resolved):
    # 先不可逆消费，再做所有复核；复核/后续allocate失败均不能重新签发或消费。
    if type(permit) is not dict or type(permit.get("permit_id")) is not str: raise Conflict("OPERATION_PERMIT_UNKNOWN")
    with self._lock:
      found = self._permits.get(permit["permit_id"])
      if found is None: raise Conflict("OPERATION_PERMIT_UNKNOWN")
      record, expected = found
      if record["state"] != "permitted": raise Conflict("OPERATION_PERMIT_USED")
      record["state"] = "consumed"
      try:
        current, resolved = self._context(current), resolution(resolved)
        if _json(permit) != _json(expected): raise Conflict("OPERATION_PERMIT_MISMATCH")
        self._current(record, current)
        if resolved != record["prepared"]["resolution"]: raise Conflict("OPERATION_RESOLUTION_STALE")
        if expected["source"] == "reviewer": self._reviewer_qualified(record, current)
      except Exception:
        if record["state"] != "expired": record["state"] = "revoked"
        raise
      return {"prepared": deepcopy(record["prepared"]), "private_input": json.loads(record["private_input"])}

  def revoke(self, operation_id):
    _text(operation_id)
    with self._lock:
      record = self._operations.get(operation_id)
      if record is None: raise Conflict("OPERATION_UNKNOWN")
      if record["state"] in ("prepared", "permitted"): record["state"] = "revoked"
      # 已进入物理执行的取消仍须ExecutionStore；不把consumed描述为已终止。
      return record["state"]

  def status(self, operation_id):
    _text(operation_id)
    with self._lock:
      record = self._operations.get(operation_id)
      if record is None: raise Conflict("OPERATION_UNKNOWN")
      return {"operation_id": operation_id, "state": record["state"]}

  def prepared(self, operation_id):
    """仅供可信决定控制面读取原准备投影；不暴露正文，也不重建终态请求。"""
    _text(operation_id)
    with self._lock:
      record = self._operations.get(operation_id)
      if record is None: raise Conflict("OPERATION_UNKNOWN")
      if record["state"] != "prepared": raise Conflict("OPERATION_NOT_PENDING")
      self._current(record, record["prepared"]["context"])
      return deepcopy(record["prepared"])
