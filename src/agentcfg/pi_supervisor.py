"""私有监督 RPC 的权限与准入层；连接身份由外部通道认证，不接受正文自报角色。"""

from dataclasses import dataclass, field
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import re

from jsonschema import Draft202012Validator

from .activity import OWNER_KEYS, digest, protected
from .deployment import json_bytes
from .schema import ConfigError
from .pi_catalog import read_schema
from .paths import PathError
from .storage import Conflict, Tree


@dataclass(frozen=True)
class Principal:
  role: str
  lease_id: str | None = None
  grant_generation: int | None = None


@dataclass(frozen=True)
class SpawnCommand:
  argv: tuple[str, ...] = field(repr=False)
  cwd: Path = field(repr=False)
  environment: dict = field(repr=False)
  capture_root: Path | None = field(default=None, repr=False)
  stdin_pipe: bool = field(default=False, repr=False)
  terminal_size: tuple[int, int] | None = field(default=None, repr=False)

  def __post_init__(self):
    if type(self.stdin_pipe) is not bool:
      raise ConfigError("pi-spawn-stdin")
    if self.terminal_size is not None:
      from .pi_terminal import dimensions
      if not isinstance(self.terminal_size, tuple) or len(self.terminal_size) != 2 or not self.stdin_pipe or self.capture_root is None:
        raise ConfigError("pi-spawn-terminal")
      dimensions(*self.terminal_size)
    if self.capture_root is not None and (not isinstance(self.capture_root, Path) or not self.capture_root.is_absolute()):
      raise ConfigError("pi-spawn-capture")
    if (not isinstance(self.argv, tuple) or not self.argv or not self.argv[0] or not all(isinstance(arg, str) and "\0" not in arg for arg in self.argv)
        or not isinstance(self.cwd, Path) or not self.cwd.is_absolute() or not isinstance(self.environment, dict)
        or any(not isinstance(key, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key)
          or not isinstance(value, str) or "\0" in value for key, value in self.environment.items())):
      raise ConfigError("pi-spawn-command")


def closed(value, keys, optional=()):
  if not isinstance(value, dict) or set(value) - set(keys) - set(optional) or set(keys) - value.keys():
    raise ConfigError("pi-control-protocol")


class SupervisorService:
  def __init__(self, store, command_resolver, spawn, *, active_children=2, activate=None, runtime_identity=None, slice_identity=None, worker_operation=None, worker_validate=None, protected_roots=(), snapshot_scope=None, delegate_handler=None, ordinary_handler=None):
    self.store, self.command_resolver, self.spawn = store, command_resolver, spawn
    self.ordinary_handler = ordinary_handler
    self.delegate_handler = delegate_handler
    self.worker_operation = worker_operation
    self.worker_validate = worker_validate
    self.protected_roots = tuple(protected_roots)
    self.snapshot_scope = snapshot_scope or (lambda cwd: None)
    self.active_children = active_children
    self.service_leases = set()
    self.active_services = 16
    self.activate = activate or (lambda lease: None)
    self.capabilities = {}
    self.mutex = threading.RLock()
    self.closing = False
    self.force_stop_ids = set()
    self.runtime_identity, self.slice_identity = runtime_identity, slice_identity

  def register_service_lease(self, lease_id):
    lease = self.store.read(lease_id)
    if lease["kind"] != "external" or not all(lease[key] == self.store.owner[key] for key in OWNER_KEYS): raise Conflict("SERVICE_LEASE_OWNER")
    if lease_id in self.service_leases: return
    if lease["state"] != "allocating" or lease["spawn_committed"]: raise Conflict("SERVICE_LEASE_STATE")
    active = [row for row in self.store.records() if row["lease_id"] in self.service_leases and protected(row)]
    if len(active) >= self.active_services: raise Conflict("SERVICE_CAPACITY_BUSY")
    self.service_leases.add(lease_id)

  def execution_children(self):
    return [row for row in self.store.records() if protected(row) and row["kind"] != "host"
      and row["spawn_committed"] and row["lease_id"] not in self.service_leases]

  def issue_capability(self, role, lease_id=None):
    if role not in ("manager", "delegate", "worker", "user") or (role in ("manager", "worker") and lease_id is None):
      raise ConfigError("pi-control-principal")
    generation = self.store.read(lease_id)["grant_generation"] if lease_id else None
    token = secrets.token_hex(32)
    self.capabilities[digest(token)] = Principal(role, lease_id, generation)
    return token

  def authenticate(self, token, peer_uid):
    if peer_uid != os.geteuid() or not isinstance(token, str):
      raise Conflict("监督通道身份不匹配")
    key = digest(token)
    for expected, principal in self.capabilities.items():
      if hmac.compare_digest(key, expected):
        if principal.role == "manager":
          lease = self.store.read(principal.lease_id)
          if (lease["state"] != "running" or lease["grant_generation"] != principal.grant_generation
              or self.store.processes.observe(lease["process_identity"]) != "alive"):
            raise Conflict("父宿主已经结束，不能继续使用旧管理者通道")
        return principal
    raise Conflict("监督通道未认证或激活已改变")

  def _scope(self, principal, lease_id, *, mutate=False):
    lease = self.store.read(lease_id)
    if principal.role == "worker":
      if principal.lease_id != lease_id:
        raise Conflict("worker不能访问其他执行")
      if mutate and (lease["grant_generation"] != principal.grant_generation or lease["state"] != "running"):
        raise Conflict("worker授权已撤销或执行已结束")
    return lease

  def handle(self, principal, message):
    with self.mutex:
      return self._handle(principal, message)

  def _handle(self, principal, message):
    closed(message, ("schema_version", "request_id", "method", "args"))
    if type(message["schema_version"]) is not int or message["schema_version"] != 1 or not isinstance(message["request_id"], str) or not message["request_id"]:
      raise ConfigError("pi-control-protocol")
    method, args = message["method"], message["args"]
    if self.closing and method in ("allocate", "start"):
      raise Conflict("监督者正在关闭，不再接受新执行")
    if not isinstance(args, dict):
      raise ConfigError("pi-control-protocol")
    if isinstance(method, str) and method.startswith("ordinary_"):
      if self.ordinary_handler is None:
        raise Conflict("ORDINARY_IO_CAPABILITY_MISSING")
      if self.closing and method in {"ordinary_prepare", "ordinary_command_prepare", "ordinary_checkpoint_prepare", "ordinary_git_status_prepare", "ordinary_git_review_prepare", "ordinary_editor_prepare", "ordinary_service_prepare", "ordinary_mcp_script_prepare", "ordinary_readseek_prepare", "ordinary_readseek_stage"}:
        raise Conflict("监督者正在关闭，不再接受新操作")
      return self.ordinary_handler(principal, method, args)
    if isinstance(method, str) and method.startswith("delegate_"):
      if self.delegate_handler is None:
        from .process import DependencyError
        raise DependencyError("委托能力未进入实例监督者")
      if self.closing and method in {"delegate_prepare", "delegate_start", "delegate_command_start"}:
        raise Conflict("监督者正在关闭，不再接受新委托")
      return self.delegate_handler(principal, method, args)
    if method == "handshake":
      closed(args, ())
      result = {"schema_version": 1, "instance_id": self.store.owner["instance_id"], "supervisor_activation_id": self.store.owner["supervisor_activation_id"], "role": principal.role,
        "runtime_identity": self.runtime_identity, "slice_identity": self.slice_identity}
      if principal.role in ("manager", "worker"):
        owned = self.store.read(principal.lease_id)
        result.update(lease_id=owned["lease_id"], process_identity=owned["process_identity"], protected_roots=list(self.protected_roots))
      if principal.role == "manager":
        result.update(manager_activation_id=self.store.owner["manager_activation_id"], owner_nonce=self.store.owner["owner_nonce"])
      return result
    if method in ("inspect", "reconcile"):
      closed(args, ("lease_id",))
      self._scope(principal, args["lease_id"])
      return self.store.reconcile(args["lease_id"])
    if method == "activity_summary":
      closed(args, ())
      if principal.role not in ("manager", "delegate", "user"):
        raise Conflict("此通道不能读取父会话活动")
      active = [row for row in self.store.records() if row["kind"] != "host" and protected(row)]
      return {"active_count": len(active), "unknown_count": sum(row["state"] in ("starting", "unknown") for row in active)}
    if method in ("workspace_identity", "workspace_snapshot"):
      closed(args, ("path",))
      if principal.role not in ("manager", "delegate", "user") or self.store.workspaces is None:
        raise Conflict("此通道没有工作区准入权限")
      planned = self.store.workspaces.identify(args["path"])
      if method == "workspace_snapshot":
        from .pi_worker_files import snapshot
        return {"snapshot_digest": snapshot(args["path"], protected_roots=self.protected_roots, source_paths=self.snapshot_scope(args["path"]))}
      return planned
    if method == "worker_admission":
      closed(args, ("descriptor", "purpose"))
      if principal.role != "manager" or args["purpose"] not in ("admission", "result"):
        raise Conflict("此通道没有受管预检权限")
      from .pi_worker_protocol import validate_descriptor
      from .pi_worker_files import snapshot, mutation_chain
      descriptor = args["descriptor"]
      if not isinstance(descriptor, dict) or not isinstance(descriptor.get("allocation_id"), str):
        raise ConfigError("pi-managed-descriptor")
      lease = self.store.read(descriptor["allocation_id"])
      validate_descriptor(descriptor, lease, self.store.owner, self.runtime_identity, allow_revoked=args["purpose"] == "result")
      if self.worker_validate:
        self.worker_validate(lease)
      if self.store.workspaces is None:
        raise Conflict("WORKSPACE_IDENTITY_UNAVAILABLE")
      workspace = self.store.workspaces.identify(descriptor["cwd"])
      if workspace["workspace_key"] != descriptor["workspace_identity_digest"]:
        raise Conflict("WORKSPACE_IDENTITY_CHANGED")
      current = snapshot(descriptor["cwd"], protected_roots=self.protected_roots, source_paths=self.snapshot_scope(descriptor["cwd"]))
      if args["purpose"] == "admission":
        if lease["state"] not in ("allocating", "running") or current != descriptor["snapshot_digest"]:
          raise Conflict("ADMISSION_STALE")
        if lease["state"] == "allocating":
          for planned in lease["planned_workspaces"]:
            self.store.workspaces.assert_reserved(planned, lease)
      proof = mutation_chain(self.store, lease, descriptor["cwd"], protected_roots=self.protected_roots, source_paths=self.snapshot_scope(descriptor["cwd"])) if args["purpose"] == "result" and descriptor["write_roots"] else {}
      with Tree(self.store.root) as tree:
        exit_raw = tree.read("activity/exits/" + lease["lease_id"] + ".json")
      exit_record = json.loads(exit_raw[0]) if exit_raw else None
      if exit_record and (exit_record.get("schema_version") != 1 or exit_record.get("process_identity") != lease["process_identity"]):
        raise Conflict("EXIT_EVIDENCE_MISMATCH")
      return {"lease_id": lease["lease_id"], "state": lease["state"], "grant_generation": lease["grant_generation"],
        "exit_code": exit_record["exit_code"] if exit_record else None, "stop_requested": lease["stop_requested_at"] is not None,
        "snapshot_digest": current, "workspace_identity_digest": workspace["workspace_key"], "termination_evidence": lease["termination_evidence"],
        "resources_reclaimed": not protected(lease), "process_identity": lease["process_identity"], **proof}
    if method in ("allocate", "start", "abort_allocation", "cancel"):
      allowed = ("manager", "delegate") if method in ("allocate", "start") else ("manager", "delegate", "user")
      if principal.role not in allowed:
        raise Conflict("worker没有派发或停止控制权限")
    if method == "allocate":
      keys = ("kind", "execution_id", "task_id", "attempt_id", "lock_identity", "slice_identity", "policy_digest", "candidate_digest", "planned_workspaces")
      closed(args, keys, ("parent_execution_id",))
      properties = read_schema("execution-lease")["properties"]
      schema = {"type": "object", "properties": {key: properties[key] for key in (*keys, "parent_execution_id")}, "required": list(keys), "additionalProperties": False}
      if not Draft202012Validator(schema).is_valid(args):
        raise ConfigError("pi-control-allocation")
      if args["kind"] not in ("worker", "check", "codex", "external"):
        raise ConfigError("pi-control-kind")
      # 预留意图可以排队；物理并发在 start 的同一服务锁内计数。
      lease = self.store.allocate(**args)
      return {"lease_id": lease["lease_id"], "allocation_id": lease["allocation_id"], "state": lease["state"],
        "grant_generation": lease["grant_generation"], "workspace_write_lease_ids": lease["workspace_write_lease_ids"]}
    if method == "start":
      closed(args, ("lease_id", "program", "payload"))
      lease = self._scope(principal, args["lease_id"])
      if any(lease[key] != self.store.owner[key] for key in OWNER_KEYS):
        raise Conflict("不能启动旧控制者的分配")
      active = self.execution_children()
      if lease["lease_id"] not in self.service_leases and not lease["spawn_committed"] and len(active) >= self.active_children:
        raise Conflict("实例执行容量已占用")
      command = self.command_resolver(lease, args["program"], args["payload"])
      if not isinstance(command, SpawnCommand):
        raise ConfigError("pi-spawn-contract")
      binding = {"program": args["program"], "payload_digest": digest(args["payload"]), "argv_digest": digest(list(command.argv)), "cwd": str(command.cwd)}
      # 环境可能含所选秘密，绝不进入启动绑定、摘要或异常。
      with Tree(self.store.root) as tree:
        tree.write_immutable("activity/commands/" + lease["lease_id"] + ".json", json_bytes(binding))
      started = self.store.start(lease["lease_id"], self.store.owner, spawn=lambda current: self.spawn(command, current))
      if started["state"] == "running":
        self.activate(started)
      return {"lease_id": started["lease_id"], "attempt_id": started["attempt_id"], "state": started["state"]}
    if method == "abort_allocation":
      closed(args, ("lease_id",))
      lease = self.store.abort_allocation(args["lease_id"], self.store.owner)
      return {"lease_id": lease["lease_id"], "state": lease["state"]}
    if method == "cancel":
      closed(args, ("lease_id",), ("force",))
      if type(args.get("force", False)) is not bool:
        raise ConfigError("pi-control-stop-mode")
      lease = self.store.request_cancel(args["lease_id"], self.store.owner)
      if args.get("force") and protected(lease): self.force_stop_ids.add(lease["lease_id"])
      return {"accepted": True, "grant_generation": lease["grant_generation"], "termination_confirmed": not protected(lease)}
    if method == "authorize":
      closed(args, ("lease_id", "grant_generation"))
      lease = self._scope(principal, args["lease_id"], mutate=True)
      if principal.role != "worker" or lease["grant_generation"] != args["grant_generation"]:
        raise Conflict("此通道没有worker操作授权")
      if lease["execution_id"].startswith("delegate-command-"):
        parents = [row for row in self.store.records() if row["execution_id"] == lease["parent_execution_id"]]
        if len(parents) != 1 or parents[0]["state"] != "running" or self.store.processes.observe(parents[0]["process_identity"]) != "alive":
          raise Conflict("DELEGATE_GRANT_REVOKED")
      if self.worker_validate:
        self.worker_validate(lease)
      return {"valid": True, "grant_generation": lease["grant_generation"]}
    if method == "file_action":
      closed(args, ("lease_id", "grant_generation", "operation_id", "action"))
      lease = self._scope(principal, args["lease_id"], mutate=True)
      if principal.role != "worker" or lease["grant_generation"] != args["grant_generation"] or self.worker_operation is None:
        raise Conflict("此通道没有受管文件操作授权")
      if args["operation_id"] == "head" or not isinstance(args["operation_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", args["operation_id"]):
        raise ConfigError("pi-operation-identity")
      return self.worker_operation(lease, args["operation_id"], args["action"])
    if method in ("plan_stop", "recover_stop"):
      if principal.role != "user":
        raise Conflict("停止恢复只允许用户控制入口")
      if method == "plan_stop":
        closed(args, ("lease_id",))
        return self.store.plan_stop(args["lease_id"])
      closed(args, ("lease_id", "plan_digest"))
      lease = self.store.recover_stop(args["lease_id"], args["plan_digest"], request_id=message["request_id"])
      return {"lease_id": lease["lease_id"], "state": lease["state"]}
    raise ConfigError("pi-control-method")

  def reply(self, token, peer_uid, message):
    try:
      result = self.handle(self.authenticate(token, peer_uid), message)
      return {"schema_version": 1, "ok": True, "result": result}
    except Exception as error:
      # 不回显原始请求、参数、秘密或宿主错误。
      from .pi_codex_admission import public_rejection
      reason = public_rejection(error)
      if isinstance(error, Conflict) and str(error) == "ORDINARY_STDIN_BACKPRESSURE": reason = "ORDINARY_STDIN_BACKPRESSURE"
      return {"schema_version": 1, "ok": False, "exit_code": 2 if isinstance(error, PathError) else getattr(error, "exit_code", 6), "error": reason or "PI_CONTROL_REJECTED"}


class SupervisorServer:
  """端点仅位于实例私人状态目录；异步连接不能绕过服务层的串行准入。"""

  def __init__(self, service):
    self.service = service
    self.directory = service.store.root / "activity/control"
    self.endpoint = self.directory / "control.json"
    self.socket = None
    self.socket_identity = None
    self.stopping = threading.Event()
    self.threads = []

  def open(self):
    import socket
    import stat
    from .storage import ensure_private
    ensure_private(self.directory)
    with Tree(self.directory) as tree:
      before = tree.read("control.json")
      try:
        previous = os.stat("control.sock", dir_fd=tree.fd, follow_symlinks=False)
      except FileNotFoundError:
        previous = None
      if previous is not None:
        try:
          record = json.loads(before[0]) if before else {}
          identity = record["socket_identity"]
          valid = (stat.S_ISSOCK(previous.st_mode) and previous.st_uid == os.geteuid()
            and (previous.st_dev, previous.st_ino) == (identity["device"], identity["inode"])
            and record["owner"]["instance_id"] == self.service.store.owner["instance_id"]
            and self.service.store.processes.observe(record["owner"]["supervisor_process_identity"]) == "dead")
        except (KeyError, ValueError, TypeError):
          valid = False
        if not valid:
          raise Conflict("旧监督端点仍活动、身份未知或未归属；不能覆盖")
        os.unlink("control.sock", dir_fd=tree.fd)
        os.fsync(tree.fd)
      self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
      # 相对 Unix 路径避免 pathname 长度限制；绑定结束恢复调用者 cwd。
      previous_cwd = os.open(".", os.O_RDONLY | os.O_DIRECTORY)
      try:
        os.fchdir(tree.fd)
        self.socket.bind("control.sock")
      finally:
        os.fchdir(previous_cwd)
        os.close(previous_cwd)
      os.chmod("control.sock", 0o600, dir_fd=tree.fd, follow_symlinks=False)
      self.socket.listen(8)
      self.socket.settimeout(0.1)
      info = os.stat("control.sock", dir_fd=tree.fd, follow_symlinks=False)
      self.socket_identity = {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}
      tree.write_state("control.json", json_bytes({"schema_version": 1, "owner": self.service.store.owner,
        "socket_name": "control.sock", "socket_identity": self.socket_identity, "user_capability": self.service.issue_capability("user")}))
    return self.endpoint

  def _connection(self, connection):
    from .pi_control import MAX_FRAME, peer_uid, read_frame
    try:
      connection.settimeout(30)
      uid = peer_uid(connection)
      if uid != os.geteuid():
        raise Conflict("监督通道用户不匹配")
      with connection, connection.makefile("rwb") as stream:
        value = read_frame(stream)
        closed(value, ("capability", "message"))
        result = self.service.reply(value["capability"], uid, value["message"])
        data = json_bytes(result)
        if len(data) > MAX_FRAME:
          data = json_bytes({"schema_version": 1, "ok": False, "exit_code": 4, "error": "PI_CONTROL_RESPONSE_TOO_LARGE"})
        stream.write(data)
        stream.flush()
    except Exception:
      connection.close()

  def poll(self):
    import socket
    self.threads = [thread for thread in self.threads if thread.is_alive()]
    try:
      connection, _ = self.socket.accept()
    except socket.timeout:
      return
    if len(self.threads) >= 8:
      connection.close()
      return
    thread = threading.Thread(target=self._connection, args=(connection,), daemon=True)
    self.threads.append(thread)
    thread.start()

  def close(self):
    self.stopping.set()
    if self.socket is not None:
      self.socket.close()
    with Tree(self.directory) as tree:
      try:
        info = os.stat("control.sock", dir_fd=tree.fd, follow_symlinks=False)
      except FileNotFoundError:
        return
      if self.socket_identity and (info.st_dev, info.st_ino) == (self.socket_identity["device"], self.socket_identity["inode"]):
        os.unlink("control.sock", dir_fd=tree.fd)
        os.fsync(tree.fd)
