"""普通文件的准入账本与实际租约桥。只有受信控制面可安装 context_provider。

本模块不把模型参数当上下文，不开放新的 RPC；正式宿主的会话/用户意图来源仍须接线。
所有调用与普通监督操作共用 SupervisorService.mutex，保持消费、tick 和状态观察的顺序。
"""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .activity import digest
from .pi_operation_admission import FILES, OperationAdmissions, context, encode_private_input
from .schema import ConfigError
from .storage import Conflict


class FileOperationAdmissions:
  def __init__(self, operations, *, context_provider, admissions=None):
    # 仅可信宿主构造注入；不从RPC或工具正文读取，不复制或重建共享账本。
    if admissions is not None and (type(admissions) is not OperationAdmissions or
        admissions.activation_id != operations.host.store.owner["manager_activation_id"]):
      raise ConfigError("pi-operation-shared-admissions")
    if not callable(context_provider): raise ConfigError("pi-operation-context-provider")
    if operations.admission is not None: raise Conflict("OPERATION_CONTROL_ALREADY_BOUND")
    if operations.host.manifest().get("profile_id") not in ("pi-base", "pi-full"):
      raise ConfigError("pi-operation-profile")
    self.operations, self.context_provider = operations, context_provider
    self.host, self.mutex = operations.host, operations.host.service.mutex
    self.activation = self.host.store.owner["manager_activation_id"]
    self.ledger = admissions if admissions is not None else OperationAdmissions(self.activation, now_ms=lambda: int(operations.now().timestamp() * 1000))
    self.requests, self.records, self.permits = {}, {}, {}
    operations.admission = self

  def _principal(self, principal):
    if principal.role != "manager" or not principal.lease_id: raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    lease = self.host.store.read(principal.lease_id)
    if lease["state"] != "running" or lease["grant_generation"] != principal.grant_generation:
      raise Conflict("GRANT_STALE")

  def _current(self, request_id):
    if type(request_id) is not str or not request_id or len(request_id) > 512 or any(ord(c) < 32 for c in request_id):
      raise ConfigError("pi-operation-request-id")
    encode_private_input(request_id)
    # 上游SDK/控制面错误可能携带正文；这个边界只返回固定错误。
    try: current = context(self.context_provider(request_id))
    except Exception: raise Conflict("OPERATION_CONTEXT_UNAVAILABLE") from None
    manifest = self.host.manifest()
    if (current["activation_id"] != self.activation or current["profile"] != manifest.get("profile_id")
        or current["runtime_identity"] != self.host.runtime_root.name or current["role_id"] != "main"):
      raise Conflict("OPERATION_CONTEXT_STALE")
    return current

  def _entry(self, principal, operation_id):
    self._principal(principal)
    if type(operation_id) is not str: raise ConfigError("pi-operation-id")
    entry = self.records.get(operation_id)
    if entry is None: raise Conflict("OPERATION_UNKNOWN")
    if entry["principal"] != (principal.lease_id, principal.grant_generation):
      raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    return entry

  def _value(self, entry):
    value = self.operations.inputs.get(entry["ordinary_id"])
    if value is None or value.get("_admission_owner") is not self: raise Conflict("OPERATION_BINDING_STALE")
    return value

  def _resolution(self, value, current):
    if value["state"] != "prepared": raise Conflict("OPERATION_NOT_PENDING")
    approval = self.operations.preview(value)
    if value["cwd"] != current["cwd"]: raise Conflict("OPERATION_CONTEXT_STALE")
    roots = value["grant"]["root_bindings"]
    ceiling = value.get("ceiling", {"allowed_tools": ["read"], "read_roots": ["resource"], "write_roots": []})
    targets = [value["path"]] + ([value["destination"]] if value["tool_name"] == "rename" else [])
    def selected(ids, paths):
      result = {}
      for path in paths:
        matches = [roots[key] for key in ids if key in roots and Path(path).is_relative_to(Path(roots[key]["path"]))]
        if not matches: raise Conflict("PERMISSION_DENIED")
        root = max(matches, key=lambda row: len(row["path"]))
        result[root["path"]] = deepcopy(root)
      return [result[key] for key in sorted(result)]
    reads = selected(ceiling["read_roots"], [value["path"]]) if not value["write"] or value["tool_name"] == "edit" else []
    writes = selected(ceiling["write_roots"], targets) if value["write"] else []
    return {"kind": "file", "tool_name": value["tool_name"],
      "target": {"path": value["path"], "destination": value.get("destination")},
      "read_roots": reads, "write_roots": writes,
      "workspace_keys": sorted(row["workspace_key"] for row in value["planned_workspaces"]),
      "network": "deny", "services": [], "backend": "guarded-files-v1",
      "policy": {"generation": current["policy_generation"], "policy_digest": value["policy_digest"],
        "ceiling_digest": digest(ceiling), "hard_policy": "allow", "approval": approval,
        "requires_human": approval == "human"}}

  def prepare(self, principal, request_id, tool_name, private_input):
    with self.mutex:
      self._principal(principal)
      current = self._current(request_id)
      if type(tool_name) is not str or tool_name not in FILES: raise ConfigError("pi-operation-tool-not-supported")
      # 先有限编码，避免复制一个不受限的模型参数对象。
      private = {"tool_name": tool_name, "input": private_input}
      encode_private_input(private)
      key = (current["profile"], current["session_id"], request_id)
      existing = self.requests.get(key)
      if existing is not None:
        self._entry(principal, existing["prepared"]["operation_id"])
        # 幂等观察返回原准备对象；issue/consume仍分别重新核验当前物理根/硬策略。
        return self.ledger.prepare(request_id, current=current, resolved=existing["prepared"]["resolution"], private_input=private)
      args = {"operation_id": uuid4().hex, "role_id": current["role_id"], "cwd": current["cwd"],
        "tool_name": tool_name, "input": deepcopy(private_input)}
      ticket = self.operations.prepare(principal, args, deferred=True, admission=self)
      value = self.operations.inputs[ticket["operation_id"]]
      try:
        resolved = self._resolution(value, current)
        prepared = self.ledger.prepare(request_id, current=current, resolved=resolved, private_input=private)
      except Exception:
        self.operations.retire(value, "revoked")
        raise
      entry = {"prepared": deepcopy(prepared), "ordinary_id": ticket["operation_id"],
        "principal": (principal.lease_id, principal.grant_generation)}
      self.requests[key] = self.records[prepared["operation_id"]] = entry
      return prepared

  def issue(self, principal, operation_id, *, operation_digest, source, reviewer_identity=None):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      current = self._current(entry["prepared"]["request_id"])
      if self._resolution(self._value(entry), current) != entry["prepared"]["resolution"]:
        raise Conflict("OPERATION_RESOLUTION_STALE")
      permit = self.ledger.issue(operation_id, operation_digest=operation_digest, current=current,
        source=source, reviewer_identity=reviewer_identity)
      self.permits[permit["permit_id"]] = operation_id
      return permit

  def consume(self, principal, permit):
    with self.mutex:
      if type(permit) is not dict or type(permit.get("permit_id")) is not str:
        raise Conflict("OPERATION_PERMIT_UNKNOWN")
      operation_id = self.permits.get(permit["permit_id"])
      if operation_id is None: raise Conflict("OPERATION_PERMIT_UNKNOWN")
      entry = self._entry(principal, operation_id)
      value = self._value(entry)
      try:
        current = self._current(entry["prepared"]["request_id"])
        resolved = self._resolution(value, current)
        self.ledger.consume(permit, current=current, resolved=resolved)
      except Exception:
        self.ledger.revoke(operation_id)
        if value["state"] == "prepared": self.operations.retire(value, "revoked")
        raise
      # 此后许可永不恢复。分配失败或丢回执时保留ordinary原状态及Writer保护。
      return self.operations.consume(principal, {"operation_id": entry["ordinary_id"]}, admission=self,
        approval_source=permit["source"])

  def status(self, principal, operation_id):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      return {"admission": self.ledger.status(operation_id),
        "execution": self.operations.status(principal, {"operation_id": entry["ordinary_id"]})}

  def revoke(self, principal, operation_id):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      self.ledger.revoke(operation_id)
      value = self._value(entry)
      if value["state"] == "prepared": self.operations.retire(value, "revoked")
      # consumed只表示已消费；停止进程必须继续走ExecutionStore取消/终止证明。
      return self.status(principal, operation_id)
