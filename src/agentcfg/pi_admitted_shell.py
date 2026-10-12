"""Shell的一次许可到执行租约桥；没有默认后端，也不直接启动进程。

backend_preflight只能由受信宿主组装提供，必须完成实际helper/完整挂载可用性检查；
其结果用于绑定和重验，不是可接受模型提供的证明。内部启动/RPC已接线，生产后端及工具尚未启用。
准备/决定无Writer，消费先烧许可再分配；unknown只读定位，绝不重试或自动回收。
"""

from copy import deepcopy
import re
import hashlib
import json
from pathlib import Path

from .activity import OWNER_KEYS, digest, protected
from .deployment import json_bytes
from .pi_catalog import validate
from .pi_operation_admission import OperationAdmissions, context, encode_private_input
from .pi_shell_approval import classify_shell_approval
from .pi_shell_mounts import compile_mount_plan
from .pi_shell_preparation import BINDING_FIELDS, prepare_shell
from .pi_supervisor import Principal, SpawnCommand, closed
from .schema import ConfigError
from .storage import Conflict, Tree


def _unique_document(raw):
  """命令与收据不接受JSON重复键，避免解析器覆盖授权声明。"""
  def pairs(items):
    value = {}
    for key, item in items:
      if key in value: raise ValueError()
      value[key] = item
    return value
  return json.loads(raw, object_pairs_hook=pairs)


class ShellOperationAdmissions:
  def __init__(self, operations, *, context_provider, binding_name, backend_preflight=None,
      max_operations=4096, max_private_bytes=32 * 1024 * 1024, admissions=None):
    if admissions is not None and (type(admissions) is not OperationAdmissions or
        admissions.activation_id != operations.host.store.owner["manager_activation_id"] or
        type(max_operations) is not int or type(max_private_bytes) is not int or
        max_operations != admissions.max_operations or max_private_bytes != admissions.max_private_bytes):
      raise ConfigError("pi-operation-shared-admissions")
    if (not callable(context_provider) or backend_preflight is not None and not callable(backend_preflight)
        or type(binding_name) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", binding_name)):
      raise ConfigError("pi-shell-control")
    self.operations, self.host = operations, operations.host
    if self.host.manifest().get("profile_id") not in ("pi-base", "pi-full"):
      raise ConfigError("pi-operation-profile")
    self.mutex = self.host.service.mutex
    self.context_provider, self.binding_name, self.backend_preflight = context_provider, binding_name, backend_preflight
    self.activation = self.host.store.owner["manager_activation_id"]
    self.ledger = admissions if admissions is not None else OperationAdmissions(self.activation, now_ms=self._now_ms,
      max_operations=max_operations, max_private_bytes=max_private_bytes)
    self.requests, self.records, self.permits = {}, {}, {}

  def _now_ms(self):
    return int(self.operations.now().timestamp() * 1000)

  def _principal(self, principal):
    if principal.role != "manager" or not principal.lease_id: raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    parent = self.host.store.read(principal.lease_id)
    if (parent["kind"] != "host" or parent["state"] != "running"
        or parent["grant_generation"] != principal.grant_generation
        or any(parent[key] != self.host.store.owner[key] for key in OWNER_KEYS)
        or self.host.store.processes.observe(parent["process_identity"]) != "alive"):
      raise Conflict("GRANT_STALE")
    return parent

  def _current(self, request_id):
    if type(request_id) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", request_id):
      raise ConfigError("pi-operation-request-id")
    try: current = context(self.context_provider(request_id))
    except Exception: raise Conflict("OPERATION_CONTEXT_UNAVAILABLE") from None
    if (current["activation_id"] != self.activation or current["profile"] != self.host.manifest().get("profile_id")
        or current["runtime_identity"] != self.host.runtime_root.name or current["role_id"] != "main"):
      raise Conflict("OPERATION_CONTEXT_STALE")
    return current

  def _compile(self, current, private, *, bound_backend=None):
    closed(private, ("command",), ("timeout",))
    manifest = self.host.manifest()
    raw = manifest["options"].get("external_tools", {}).get(self.binding_name)
    if raw is None: raise Conflict("SHELL_BINDING_UNAVAILABLE")
    validate("options", {"external_tools": {self.binding_name: raw}})
    if (not BINDING_FIELDS <= raw.keys() or raw.get("args", []) != [] or raw.get("interactive", False) is not False):
      raise ConfigError("pi-shell-binding")
    part = prepare_shell(command_ref="tool:" + self.binding_name,
      binding={key: raw[key] for key in BINDING_FIELDS}, command=private["command"],
      cwd=current["cwd"], policy_generation=current["policy_generation"], timeout_seconds=private.get("timeout"),
      declared_roots=manifest["options"].get("paths", {}).get("roots", {}),
      permission_policy=manifest["permission_policy"], permissions=manifest["options"].get("permissions", {}),
      protected_roots=[str(self.host.root), str(self.host.runtime_root), str(self.host.config["instance_root"]),
        *self.host.config.get("protected_roots", [])])
    if self.backend_preflight is None: raise Conflict("SHELL_BACKEND_UNAVAILABLE")
    # 后端检查拿不到脚本，只验证公开边界；不运行helper或把可用性布尔值当授权。
    try:
      backend = (json.loads(encode_private_input(self.backend_preflight(
        deepcopy({key: part[key] for key in ("resolution", "physical")}))))
        if bound_backend is None else deepcopy(bound_backend))
      fields = ("runtime_identity", "helper_identity", "plan_digest")
      closed(backend, fields, ("mount_plan",))
      if (backend["runtime_identity"] != current["runtime_identity"]
          or any(type(backend[key]) is not str or not re.fullmatch(r"[0-9a-f]{64}", backend[key]) for key in fields)):
        raise ValueError()
      if "mount_plan" in backend:
        # 完整计划来自受信后端，仍重新经过原物理planner；摘要和声明不是授权证明。
        plan = backend["mount_plan"]
        root_paths = {key: row["path"] for key, row in manifest["options"].get("paths", {}).get("roots", {}).items()}
        root_paths["project"] = root_paths[raw["project_root"]]
        approval = classify_shell_approval(permission_policy=manifest["permission_policy"], root_paths=root_paths,
          command_ref="tool:" + self.binding_name, mount_plan=plan)
        systems = [row["path"] for row in plan["mounts"] if row["role"] == "system"]
        systems.extend(row["path"] for row in plan["symlinks"])
        # 同一次start的轻量核仅复核声明/分类，不能证明目录内容未变。
        # 跨RPC与放G前仍完整扫描；真正挂载另由pin_mount_plan固定FD。
        actual = (compile_mount_plan({key: part[key] for key in ("resolution", "physical")}, system_roots=systems)
          if bound_backend is None else plan)
        if actual != plan or digest(actual) != backend["plan_digest"]:
          raise ValueError()
        part["resolution"]["policy"].update(approval=approval, requires_human=approval == "human")
    except Exception: raise Conflict("SHELL_BACKEND_UNAVAILABLE") from None
    planned = {}
    for root in part["resolution"]["write_roots"]:
      workspace = self.host.store.workspaces.identify(root["path"])
      old = planned.get(workspace["workspace_key"])
      if old is not None and old != workspace: raise Conflict("ROOT_IDENTITY")
      planned[workspace["workspace_key"]] = workspace
    part["resolution"]["workspace_keys"] = sorted(planned)
    part["resolution"]["policy"]["ceiling_digest"] = digest({"preparation": part["resolution"]["policy"]["ceiling_digest"],
      "binding": raw, "backend": backend})
    return part, [planned[key] for key in sorted(planned)], deepcopy(backend)

  def _entry(self, principal, operation_id):
    self._principal(principal)
    if type(operation_id) is not str: raise ConfigError("pi-operation-id")
    entry = self.records.get(operation_id)
    if entry is None: raise Conflict("OPERATION_UNKNOWN")
    if entry["principal"] != (principal.lease_id, principal.grant_generation):
      raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    return entry

  def _fresh(self, entry, current, *, full=True):
    if current != entry["prepared"]["context"]: raise Conflict("OPERATION_CONTEXT_STALE")
    if self._now_ms() >= current["deadline_ms"]: raise Conflict("OPERATION_EXPIRED")
    if entry["private"] is None: raise Conflict("SHELL_INPUT_UNAVAILABLE")
    part, planned, backend = self._compile(current, entry["private"],
      bound_backend=None if full else entry["backend"])
    if (part["resolution"] != entry["prepared"]["resolution"] or planned != entry["planned"]
        or part["physical"] != entry["physical"] or backend != entry["backend"]):
      raise Conflict("OPERATION_RESOLUTION_STALE")
    return part["resolution"]

  def prepare(self, principal, request_id, tool_name, private_input):
    with self.mutex:
      self._principal(principal)
      current = self._current(request_id)
      if tool_name != "bash": raise ConfigError("pi-shell-tool")
      encode_private_input(private_input)
      key = (current["profile"], current["session_id"], request_id)
      existing = self.requests.get(key)
      if existing is not None:
        self._entry(principal, existing["prepared"]["operation_id"])
        return self.ledger.prepare(request_id, current=current, resolved=existing["prepared"]["resolution"], private_input=private_input)
      part, planned, backend = self._compile(current, private_input)
      prepared = self.ledger.prepare(request_id, current=current, resolved=part["resolution"], private_input=private_input)
      entry = {"prepared": deepcopy(prepared), "private": deepcopy(private_input), "planned": planned,
        "physical": part["physical"], "backend": backend, "principal": (principal.lease_id, principal.grant_generation),
        "state": "prepared", "lease_id": None, "allocation": None, "input_taken": False, "input_revoked": False}
      self.requests[key] = self.records[prepared["operation_id"]] = entry
      return prepared

  def issue(self, principal, operation_id, *, operation_digest, source, reviewer_identity=None):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      if entry["state"] != "prepared": raise Conflict("OPERATION_NOT_PENDING")
      current = self._current(entry["prepared"]["request_id"])
      self._fresh(entry, current)
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
      if entry["state"] != "prepared": raise Conflict("OPERATION_NOT_PENDING")
      try:
        current = self._current(entry["prepared"]["request_id"])
        resolved = self._fresh(entry, current)
        consumed = self.ledger.consume(permit, current=current, resolved=resolved)
      except Exception:
        self.ledger.revoke(operation_id)
        entry.update(state="revoked", private=None, input_revoked=True)
        raise
      # 只使用账本保存的原始正文；此后任何失败都不能重发许可或自动释放Writer。
      entry.update(state="revoked", private=consumed["private_input"])
      parent = self.host.store.read(principal.lease_id)
      allocation = {"kind": "external", "execution_id": "shell-" + operation_id, "task_id": None,
        "attempt_id": operation_id, "parent_execution_id": parent["execution_id"],
        "lock_identity": self.host.config["lock_identity"], "slice_identity": self.host.config["slice_identity"],
        "policy_digest": resolved["policy"]["policy_digest"], "candidate_digest": None, "planned_workspaces": deepcopy(entry["planned"])}
      entry.update(state="unknown", allocation=deepcopy({**allocation, **self.host.store.owner}))
      lease = self.host.store.allocate(**allocation)
      if (any(lease[key] != value for key, value in entry["allocation"].items())
          or lease["state"] != "allocating" or lease["spawn_committed"]):
        raise Conflict("SHELL_ALLOCATION_IDENTITY")
      entry["lease_id"] = lease["lease_id"]
      entry["grant_generation"] = lease["grant_generation"]
      record = {"schema_version": 1, "operation_id": operation_id, "lease_id": lease["lease_id"],
        "grant_generation": lease["grant_generation"], "prepared": entry["prepared"], "backend": entry["backend"],
        "physical": entry["physical"], "parent_lease_id": principal.lease_id, "parent_generation": principal.grant_generation}
      with Tree(self.host.root) as tree:
        tree.write_immutable("activity/ordinary-shell-operations/" + operation_id + ".json", json_bytes(record))
      entry["state"] = "consumed"
      return self._summary(entry)

  def _summary(self, entry):
    prepared = entry["prepared"]
    return {"operation_id": prepared["operation_id"], "lease_id": entry["lease_id"], "kind": "command", "tool_name": "bash",
      "write": bool(prepared["resolution"]["write_roots"]), "state": entry["state"],
      "timeout_seconds": entry["physical"]["timeout_seconds"], "command_ref": prepared["resolution"]["target"]["command_ref"],
      "request_digest": prepared["operation_digest"]}

  def status(self, principal, operation_id):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      execution = self._summary(entry)
      if entry["state"] == "unknown" and entry["lease_id"] is None:
        expected = entry["allocation"]
        if expected is None: raise Conflict("SHELL_ALLOCATION_IDENTITY")
        matches = [row for row in self.host.store.records() if row["execution_id"] == expected["execution_id"]]
        if len(matches) > 1 or matches and any(matches[0][key] != value for key, value in expected.items()):
          raise Conflict("SHELL_ALLOCATION_IDENTITY")
        if matches: execution["lease_id"] = matches[0]["lease_id"]
      return {"admission": self.ledger.status(operation_id), "execution": execution}

  def revoke(self, principal, operation_id):
    with self.mutex:
      entry = self._entry(principal, operation_id)
      self.ledger.revoke(operation_id)
      entry.update(private=None, input_revoked=True)
      if entry["state"] == "prepared": entry["state"] = "revoked"
      # 已消费/unknown租约保持原状；拒发输入不是已终止进程的证明。
      return self.status(principal, operation_id)

  def output(self, principal, args):
    """只读观察原操作的输出；不重验过期脚本，不以capture完成释放Writer。"""
    closed(args, ("operation_id", "cursor"))
    cursor = args["cursor"]
    if type(cursor) is not int or not 0 <= cursor <= 2**53 - 1:
      raise ConfigError("pi-shell-output-cursor")
    with self.mutex:
      entry = self._entry(principal, args["operation_id"])
      if entry["state"] != "consumed" or entry["lease_id"] is None or entry["allocation"] is None:
        raise Conflict("SHELL_OUTPUT_UNAVAILABLE")
      lease = self.host.store.read(entry["lease_id"])
      if any(lease[key] != value for key, value in entry["allocation"].items()):
        raise Conflict("SHELL_ALLOCATION_IDENTITY")
      child = self.host.children.get(lease["lease_id"])
      if child is None:
        if lease["spawn_committed"]: raise Conflict("SHELL_OUTPUT_UNAVAILABLE")
        if cursor != 0: raise ConfigError("pi-shell-output-cursor")
        return {"events": [], "next_cursor": 0, "dropped": False, "has_more": False, "complete": False}
      capture = child.get("capture")
      if child["identity"] != lease["process_identity"] or capture is None:
        raise Conflict("SHELL_OUTPUT_UNAVAILABLE")
      if cursor > capture.sequence: raise ConfigError("pi-shell-output-cursor")
      return capture.since(cursor)

  def _worker_entrypoint(self):
    """仅接受已密封运行包明确声明的Shell入口，不回退旧命令驱动。"""
    entrypoint = "supervisor/scripts/pi-shell.py"
    try:
      with Tree(self.host.runtime_root) as tree:
        raw = tree.read("runtime/commands.json")
        receipt_raw = tree.read(".agentcfg-receipt.json")
        script = tree.read(entrypoint)
      if not raw or not receipt_raw or not script or raw[1] != 0o600 or receipt_raw[1] != 0o600:
        raise ValueError()
      definitions, receipt = _unique_document(raw[0]), _unique_document(receipt_raw[0])
      closed(definitions, ("schema_version", "programs"))
      if (type(definitions["schema_version"]) is not int or definitions["schema_version"] != 1
          or type(definitions["programs"]) is not dict):
        raise ValueError()
      if type(receipt) is not dict: raise ValueError()
      expected = {"entrypoint": entrypoint, "kind": "external", "engine": "python"}
      if (definitions.get("programs", {}).get("ordinary-shell") != expected
          or type(receipt.get("schema_version")) is not int or receipt["schema_version"] != 2
          or receipt.get("identity") != self.host.runtime_root.name):
        raise ValueError()
      for path, item in (("runtime/commands.json", raw), (entrypoint, script)):
        if item[1] != 0o600 or receipt.get("files", {}).get(path) != {
            "kind": "file", "mode": 0o600, "sha256": hashlib.sha256(item[0]).hexdigest()}:
          raise ValueError()
    except (OSError, ValueError, TypeError, AttributeError, Conflict, ConfigError):
      raise Conflict("SHELL_RUNTIME_UNAVAILABLE") from None
    return self.host.runtime_root / entrypoint

  def command(self, lease, payload):
    """生成受管worker描述；许可已经消费，不再分配或携带脚本正文。"""
    with self.mutex:
      closed(payload, ("operation_id",))
      if type(payload["operation_id"]) is not str: raise ConfigError("pi-operation-id")
      entry = self.records.get(payload["operation_id"])
      if (self.host.service.closing or entry is None or entry["state"] != "consumed"
          or entry["input_revoked"] or entry["input_taken"] or not isinstance(lease, dict)
          or lease.get("lease_id") != entry["lease_id"]
          or lease.get("grant_generation") != entry["grant_generation"]
          or any(lease.get(key) != value for key, value in entry["allocation"].items())):
        raise Conflict("SHELL_COMMAND_STALE")
      authoritative = self.host.store.read(entry["lease_id"])
      if authoritative != lease or lease["state"] not in ("allocating", "running"):
        raise Conflict("SHELL_COMMAND_STALE")
      self._principal(Principal("manager", *entry["principal"]))
      self._fresh(entry, entry["prepared"]["context"])
      now = self._now_ms()
      if now >= entry.get("run_deadline_ms", now + 1): raise Conflict("SHELL_COMMAND_STALE")
      entrypoint = self._worker_entrypoint()
      from .pi_shell_start import ShellStart, ENVIRONMENT
      if "run_deadline_ms" not in entry:
        entry["run_deadline_ms"] = now + entry["physical"]["timeout_seconds"] * 1000
      # 描述本身不能spawn；受信父作用域取走正文并固定FD后才生成可执行argv。
      return SpawnCommand((str(entrypoint),), Path(entry["physical"]["cwd"]), dict(ENVIRONMENT),
        capture_root=self.host.root / "activity/outputs" / lease["lease_id"],
        stdin_pipe=False, process_scope="linux-shell", launch=ShellStart(self, entry, lease, entrypoint))

  def tick(self):
    """只请求有权威进程身份的执行停止；未知启动和Writer保持保护。"""
    with self.mutex:
      now = self._now_ms()
      for entry in self.records.values():
        if entry["state"] != "consumed": continue
        if not entry["input_revoked"] and now < entry.get("run_deadline_ms", now + 1): continue
        entry.update(private=None, input_revoked=True)
        lease = self.host.store.read(entry["lease_id"])
        if (any(lease[key] != value for key, value in entry["allocation"].items())
            or lease["lease_id"] != entry["lease_id"]):
          raise Conflict("SHELL_ALLOCATION_IDENTITY")
        if lease["process_identity"] is not None and protected(lease):
          self.host.store.request_cancel(lease["lease_id"], self.host.store.owner)

  def take_input(self, principal, operation_id):
    """自有helper的私有通道；仅交给对应存活worker一次，不接受manager取正文。"""
    with self.mutex:
      if self.host.service.closing: raise Conflict("GRANT_STALE")
      if type(operation_id) is not str: raise ConfigError("pi-operation-id")
      entry = self.records.get(operation_id)
      now = self._now_ms()
      if (entry is None or entry["state"] != "consumed" or entry["input_revoked"] or entry["input_taken"]
          or now >= entry.get("run_deadline_ms", now + 1)
          or principal.role != "worker" or principal.lease_id != entry["lease_id"]):
        raise Conflict("SHELL_INPUT_UNAVAILABLE")
      lease = self.host.store.read(principal.lease_id)
      if (lease["state"] != "running" or lease["grant_generation"] != principal.grant_generation
          or any(lease[key] != value for key, value in entry["allocation"].items())
          or self.host.store.processes.observe(lease["process_identity"]) != "alive"):
        raise Conflict("GRANT_STALE")
      self._principal(Principal("manager", *entry["principal"]))
      self._fresh(entry, entry["prepared"]["context"])
      result = {"operation_id": operation_id, "lease_id": lease["lease_id"], "grant_generation": principal.grant_generation,
        "process_identity": deepcopy(lease["process_identity"]),
        "command": entry["private"]["command"], "resolution": deepcopy(entry["prepared"]["resolution"]),
        "physical": deepcopy(entry["physical"]), "backend": deepcopy(entry["backend"])}
      entry.update(input_taken=True, private=None)
      return result
