"""监督者拥有宿主及已登记子执行；普通退出不会遗忘仍活动的工作。"""

from copy import deepcopy
import json
import os
import re
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
import uuid

from .activity import ExecutionStore, OWNER_KEYS, digest, protected
from .activity_linux import LinuxProcesses
from .activity_macos import MacProcesses
from .deployment import json_bytes
from .paths import relative_path
from .pi_control import read_frame
from .pi_supervisor import SpawnCommand, SupervisorServer, SupervisorService, closed
from .process import DependencyError, environment
from .pi_worker_files import WorkerFiles, source_scope
from .pi_worker_protocol import scoped_models, validate_context, validate_descriptor
from .pi_output import OutputCapture
from .secrets import CredentialError
from .storage import Conflict, Tree, ensure_private
from .workspace_leases import WorkspaceLeases


class HostSupervisor:
  def __init__(self, config, *, lease_fd):
    closed(config, ("state_root", "instance_root", "repository", "runtime_root", "instance_id", "lock_identity", "slice_identity", "policy_digest", "cwd", "engine", "argv"), ("manifest_digest", "protected_roots", "delegate_request"))
    self.config = config
    self.root = Path(config["state_root"])
    self.runtime_root = Path(config["runtime_root"])
    selected_engine = shutil.which(config["engine"])
    self.engine_executable = str(Path(selected_engine).resolve(strict=True)) if selected_engine else None
    self.repository = Path(config["repository"])
    self.children = {}
    self.host_lease_id = None
    self.host_exit = None
    records = self.root / "activity/processes"
    if sys.platform == "linux":
      self.processes = LinuxProcesses(records)
    elif sys.platform == "darwin":
      with Tree(self.runtime_root) as tree:
        raw = tree.read(".agentcfg-receipt.json")
      try:
        helper_hash = json.loads(raw[0])["files"]["bin/pi-supervisor-macos"]["sha256"]
      except (KeyError, TypeError, ValueError):
        raise DependencyError("macOS监督helper尚未进入已验证运行包") from None
      self.processes = MacProcesses(self.runtime_root / "bin/pi-supervisor-macos", records, helper_digest=helper_hash)
    else:
      raise DependencyError("此平台没有实现Pi监督后端")
    identity = self.processes.identity(os.getpid())
    activation = uuid.uuid4().hex
    owner = {"instance_id": config["instance_id"], "supervisor_activation_id": activation,
      "manager_activation_id": uuid.uuid4().hex, "owner_nonce": secrets.token_hex(32), "supervisor_process_identity": identity}
    self.store = ExecutionStore(self.root, owner, self.processes, workspaces=WorkspaceLeases(identity["boot_id"]), lease_fd=lease_fd)
    self.store.assert_mutable()
    self.service = SupervisorService(self.store, self.resolve_command, self.spawn, activate=self.activate,
      runtime_identity=self.runtime_root.name, slice_identity=config["slice_identity"],
      worker_operation=WorkerFiles(self.store, self.manifest, config["instance_root"], protected_roots=config.get("protected_roots", [])),
      worker_validate=lambda lease: self.manifest(), protected_roots=config.get("protected_roots", []),
      snapshot_scope=lambda cwd: source_scope(config["instance_root"], cwd))
    self.server = SupervisorServer(self.service)
    from .pi_delegate import DelegateController
    self.delegates = DelegateController(self)
    self.service.delegate_handler = self.delegates.handle
    from .pi_operations import OrdinaryOperations
    self.operations = OrdinaryOperations(self)
    self.service.ordinary_handler = self.operations.handle

  def manifest(self):
    with Tree(Path(self.config["instance_root"])) as tree:
      raw = tree.read("pi-home/agentcfg-manifest.json")
    if raw is None:
      raise Conflict("PI_MANIFEST_MISSING")
    value = json.loads(raw[0])
    if digest(value["permission_policy"]) != self.config["policy_digest"] or digest(value) != self.config.get("manifest_digest"):
      raise Conflict("ADMISSION_STALE")
    return value

  def resolve_command(self, lease, program, payload):
    """固定运行包声明入口；不接受任意 argv、cwd 或环境覆盖。"""
    if program == "file-operation":
      return self.operations.command(lease, payload)
    if program == "checkpoint":
      return self.operations.checkpoints.command(lease, payload)
    if program == "ordinary-command":
      return self.operations.commands.command(lease, payload)
    if program == "codex-login":
      from .pi_login import resolve_login
      return resolve_login(self, lease, payload)
    if program in ("delegate-pi", "delegate-codex"):
      from .pi_delegate_spawn import resolve_delegate
      return resolve_delegate(self, lease, program, payload)
    if program in ("workspace", "check"):
      from .pi_auxiliary import resolve_auxiliary
      return resolve_auxiliary(self, lease, program, payload)
    with Tree(self.runtime_root) as tree:
      raw = tree.read("runtime/commands.json")
    if raw is None:
      raise DependencyError("所需受管执行入口尚未进入运行包")
    try:
      registry = json.loads(raw[0])
      closed(registry, ("schema_version", "programs"))
      definition = registry["programs"][program]
      closed(definition, ("entrypoint", "kind", "engine"))
      if registry["schema_version"] != 1 or definition["kind"] != lease["kind"] or definition["engine"] != self.config["engine"]:
        raise ValueError()
      entrypoint = self.runtime_root / relative_path(definition["entrypoint"])
      with Tree(self.runtime_root) as tree:
        if tree.read(definition["entrypoint"]) is None:
          raise ValueError()
    except (ValueError, KeyError, TypeError):
      raise DependencyError("未声明或不匹配的执行入口") from None
    closed(payload, ("descriptor", "context"))
    descriptor = payload["descriptor"]
    validate_descriptor(descriptor, lease, self.store.owner, self.runtime_root.name)
    manifest = self.manifest()
    def read_role(identity):
      # 角色文件由 launcher 生成，路径不是调用者的自由输入。
      if not isinstance(identity, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", identity):
        raise Conflict("WORKER_ROLE_MISMATCH")
      with Tree(Path(self.config["instance_root"])) as tree:
        raw = tree.read("pi-home/generated-roles/" + identity + ".md")
      if raw is None:
        raise Conflict("WORKER_ROLE_MISMATCH")
      return raw[0]
    route = validate_context(payload["context"], descriptor, manifest, self.config["instance_root"], read_role)
    with Tree(Path(self.config["instance_root"])) as tree:
      model_bytes = tree.read("pi-home/models.json")
    if model_bytes is None:
      raise Conflict("WORKER_MODEL_MISSING")
    models, selected_env = scoped_models(json.loads(model_bytes[0]), descriptor, manifest, os.environ)
    selected_provider = models["providers"][descriptor["provider_id"]]
    if selected_provider["baseUrl"] != payload["context"]["route"]["base_url"]:
      raise Conflict("WORKER_ROUTE_MISMATCH")
    if route.get("credential_ref"):
      from .pi import route_key_variable
      value = os.environ.get(route_key_variable(descriptor["route_id"]))
      if not value or "\n" in value or "\r" in value:
        raise CredentialError()
      selected_env["AGENTCFG_PI_PROXY_AUTHORIZATION"] = value
    # 完整角色/路线/权限由入口再次核验；工作区位置必须来自本次既有预留或明确读根。
    if descriptor.get("write_roots") and not lease["planned_workspaces"]:
      raise Conflict("writer缺少实际工作区预留")
    root = self.root / "activity/worker-homes" / lease["lease_id"]
    ensure_private(root)
    with Tree(self.root) as tree:
      input_name = "activity/inputs/" + lease["lease_id"] + ".json"
      tree.write_immutable(input_name, json_bytes(payload))
    ensure_private(root / "pi-home")
    with Tree(root) as tree:
      tree.write_immutable("pi-home/models.json", json_bytes(models))
    env = environment(home=root)
    for name in ("SSH_AUTH_SOCK", "EDITOR", "VISUAL", "TMUX", "TMUX_PANE", "SSH_TTY"):
      env.pop(name, None)
    env.update(selected_env)
    env["AGENTCFG_TASK_KEEPER_DATABASE"] = str(Path(self.config["instance_root"]) / "pi-home/task-keeper/runtime.db")
    env.update(PI_CODING_AGENT_DIR=str(root / "pi-home"), PI_CODING_AGENT_SESSION_DIR=str(root / "sessions"),
      AGENTCFG_SUPERVISOR_ENDPOINT=str(self.server.endpoint), AGENTCFG_SUPERVISOR_CAPABILITY=self.service.issue_capability("worker", lease["lease_id"]),
      AGENTCFG_SUPERVISOR_CLIENT=str(self.repository / "scripts/pi-control.py"), AGENTCFG_PYTHON=sys.executable,
      AGENTCFG_INSTANCE_ID=self.store.owner["instance_id"], AGENTCFG_EXECUTION_LEASE_ID=lease["lease_id"])
    return SpawnCommand((definition["engine"], str(entrypoint), "--input", str(self.root / input_name), "--runtime-root", str(self.runtime_root)), Path(descriptor["cwd"]), env)

  def spawn(self, command, lease):
    capture = OutputCapture(command.capture_root) if command.capture_root else None
    streams = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "stdin": subprocess.DEVNULL} if capture else {}
    if command.stdin_pipe: streams["stdin"] = subprocess.PIPE
    terminal = None
    environment = dict(command.environment)
    environment.pop("AGENTCFG_EXECUTION_TTY", None)
    if command.terminal_size is not None:
      from .pi_terminal import TerminalChannels
      terminal = TerminalChannels(*command.terminal_size)
      streams = terminal.streams()
      environment["AGENTCFG_EXECUTION_TTY"] = "1"
    if sys.platform == "linux" and lease.get("kind") == "codex":
      from .pi_pid_namespace import spawn_namespace
      child, identity, gate_write = spawn_namespace(self, command, environment, streams)
    elif sys.platform == "linux" and lease.get("kind") == "host":
      from .pi_pid_namespace import spawn_host_namespace
      try:
        child, identity, gate_write = spawn_host_namespace(self, command, environment, streams)
      except BaseException:
        if terminal: terminal.close()
        raise
    elif sys.platform == "linux":
      gate_read, gate_write = os.pipe()
      try:
        child = subprocess.Popen([sys.executable, "-I", str(self.repository / "scripts/pi-exec.py"), "--gate-fd", str(gate_read), "--", *command.argv],
          cwd=command.cwd, env=environment, pass_fds=(gate_read,), start_new_session=True, **streams)
      except BaseException:
        if terminal: terminal.close()
        os.close(gate_write)
        raise
      finally:
        os.close(gate_read)
      try:
        identity = self.processes.identity(child.pid)
        self.processes.register(identity)
      except BaseException:
        # 身份失败时关闭闸门，包装进程收到 EOF；持久 starting 仍由上层保留 unknown。
        os.close(gate_write)
        if terminal: terminal.close()
        raise
    else:
      gate_read, gate_write = os.pipe()
      nonce_read, nonce_write = os.pipe()
      status_read, status_write = os.pipe()
      nonce = secrets.token_hex(32)
      control = self.processes.record_root / (lease["lease_id"] + ".sock")
      ensure_private(self.processes.record_root)
      os.write(nonce_write, (nonce + "\n").encode())
      os.close(nonce_write)
      try:
        child = subprocess.Popen([str(self.processes.helper), "supervise", str(control), str(nonce_read), str(status_write), str(gate_read), "--", *command.argv],
          cwd=command.cwd, env=environment, pass_fds=(nonce_read, status_write, gate_read), start_new_session=True, **streams)
      except BaseException:
        if terminal: terminal.close()
        os.close(gate_write)
        os.close(status_read)
        raise
      finally:
        os.close(nonce_read)
        os.close(status_write)
        os.close(gate_read)
      try:
        with os.fdopen(status_read, "rb") as status:
          ready = read_frame(status)
        closed(ready, ("schema_version", "state", "helper", "worker", "control_path"))
        if ready["schema_version"] != 1 or ready["state"] != "ready" or ready["control_path"] != str(control):
          raise Conflict("macOS执行握手不匹配")
        identity = ready["worker"]
        self.processes.register(identity)
        self.processes.bind_control(identity, helper_identity=ready["helper"], control_path=control, nonce=nonce)
      except BaseException:
        os.close(gate_write)
        if terminal: terminal.close()
        raise
    try:
      if terminal:
        terminal.attach(child)
      if capture:
        capture.attach(child)
    except BaseException:
      os.close(gate_write)
      if terminal: terminal.close()
      for name in ("stdin", "stdout", "stderr"):
        stream = getattr(child, name, None)
        if stream is not None: stream.close()
      raise
    self.children[lease["lease_id"]] = {"process": child, "gate": gate_write, "identity": identity, "capture": capture, "terminal": terminal}
    return identity

  def activate(self, lease):
    child = self.children.get(lease["lease_id"])
    if child is None or child["gate"] is None:
      return
    gate = child["gate"]
    child["gate"] = None
    try:
      os.write(gate, b"G")
    finally:
      os.close(gate)

  def poll(self):
    # tick与RPC共用锁，避免派生操作登记过程中被取消/回收。
    if self.service.mutex.acquire(blocking=False):
      try:
        if getattr(self, "delegates", None) is not None:
          self.delegates.tick()
        if getattr(self, "operations", None) is not None:
          self.operations.tick()
      finally:
        self.service.mutex.release()
    # 退出码先持久化；macOS helper 可能先写终止收据再退出，已 reclaimed 也要回收子句柄。
    for lease_id, child in list(self.children.items()):
      status = child["process"].poll()
      if status is None:
        continue
      stream = getattr(child["process"], "stdin", None)
      if stream is not None and not stream.closed:
        stream.close()
      with Tree(self.root) as tree:
        tree.write_immutable("activity/exits/" + lease_id + ".json", json_bytes({"schema_version": 1,
          "lease_id": lease_id, "process_identity": child["identity"], "exit_code": status}))
      if lease_id == self.host_lease_id:
        self.host_exit = status
    for lease in self.store.records():
      if lease["supervisor_activation_id"] != self.store.owner["supervisor_activation_id"] or not protected(lease):
        continue
      if self.host_exit is not None and lease["kind"] != "host" and lease["state"] == "allocating" and not lease["spawn_committed"]:
        # 父控制者已退出，管理者通道不能再 start；只撤销完整且证明从未启动的预留。
        try:
          self.store.abort_allocation(lease["lease_id"], self.store.owner)
        except Conflict:
          pass
        continue
      if lease["process_identity"] is None:
        continue
      if self.host_exit is not None and lease["kind"] != "host" and lease["state"] == "running":
        lease = self.store.request_cancel(lease["lease_id"], self.store.owner)
      if lease["state"] == "cancel_requested":
        try:
          forced = lease["lease_id"] in getattr(self.service, "force_stop_ids", set())
          self.processes.stop(lease["process_identity"], grant_generation=lease["grant_generation"], **({"force": True} if forced else {}))
        except (Conflict, DependencyError):
          continue
      if self.processes.termination_status(lease["process_identity"]) == "terminated":
        child = self.children.get(lease["lease_id"])
        if child is not None and (child["process"].poll() is None or child.get("capture") and not child["capture"].complete()):
          continue
        # worker退出时，父监督线程可能仍在完成它已获准的文件IO。
        # 不能在该动作结束前释放写租约；非阻塞探测保证停止/截止检查继续运行。
        if not self.service.mutex.acquire(blocking=False):
          continue
        try:
          try:
            self.store.finish(lease["lease_id"], self.store.owner)
            getattr(self.service, "force_stop_ids", set()).discard(lease["lease_id"])
          except Conflict:
            pass
        finally:
          self.service.mutex.release()

  def run(self):
    self.server.open()
    host = self.store.allocate(kind="host", execution_id=uuid.uuid4().hex, task_id=None, attempt_id=uuid.uuid4().hex,
      lock_identity=self.config["lock_identity"], slice_identity=self.config["slice_identity"], policy_digest=self.config["policy_digest"],
      candidate_digest=None, planned_workspaces=[])
    self.host_lease_id = host["lease_id"]
    host_env = dict(os.environ)
    host_env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(self.server.endpoint), AGENTCFG_SUPERVISOR_CAPABILITY=self.service.issue_capability("manager", host["lease_id"]),
      AGENTCFG_SUPERVISOR_CLIENT=str(self.repository / "scripts/pi-control.py"), AGENTCFG_PYTHON=sys.executable,
      AGENTCFG_INSTANCE_ID=self.store.owner["instance_id"], AGENTCFG_EXECUTION_LEASE_ID=host["lease_id"])
    command = SpawnCommand(tuple(self.config["argv"]), Path(self.config["cwd"]), host_env)
    try:
      host = self.store.start(host["lease_id"], self.store.owner, spawn=lambda current: self.spawn(command, current))
      self.activate(host)
      while True:
        self.server.poll()
        self.poll()
        with self.service.mutex:
          if self.host_exit is not None and not any(protected(item) for item in self.store.records()):
            self.service.closing = True
            break
      return self.host_exit if self.host_exit >= 0 else 128 - self.host_exit
    finally:
      # 停止只针对本监督者已登记的执行；未确认回收的记录始终保留。
      for child in self.children.values():
        if child["gate"] is not None:
          os.close(child["gate"])
      self.server.close()

  def run_delegate(self, ready_fd):
    """独立单 run：仅监督目标执行；不启动交互 Pi，也不创建第二管理者队列。"""
    from .pi_supervisor import Principal
    self.server.open()
    run_id = None
    try:
      try:
        request = self.delegates.prepare(Principal("delegate"), self.config["delegate_request"])
        run_id = request["run_id"]
        result = self.delegates.start(Principal("delegate"), run_id)
        reply = {"ok": True, "result": result}
      except Exception as error:
        from .pi_codex_admission import public_rejection
        reply = {"ok": False, "error_code": public_rejection(error) or "DELEGATE_START_FAILED", "exit_code": getattr(error, "exit_code", 6)}
      os.write(ready_fd, json_bytes(reply))
      os.close(ready_fd)
      ready_fd = None
      if run_id is None:
        return reply.get("exit_code", 5)
      while True:
        self.server.poll()
        self.poll()
        with self.service.mutex:
          if not any(protected(item) for item in self.store.records()):
            self.delegates.refresh(run_id)
            self.service.closing = True
            break
      return 0 if self.delegates.runs.status(run_id)["state"] == "completed" else 5
    finally:
      if ready_fd is not None:
        os.close(ready_fd)
      self.server.close()


def execute(workspace, spec, env, lease_fd, saved, *, lifecycle_fd):
  runtime_root = workspace.backend.root(workspace, saved.get("runtime_identity", saved["lock_identity"]))
  with Tree(runtime_root) as tree:
    raw = tree.read(".agentcfg-receipt.json")
  receipt = json.loads(raw[0])
  with Tree(workspace.instance) as tree:
    manifest = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])
  frozen_root = runtime_root / "supervisor"
  config = {"state_root": str(workspace.state_root), "instance_root": str(workspace.instance), "repository": str(frozen_root),
    "runtime_root": str(runtime_root), "instance_id": digest({"instance": str(workspace.instance), "binding": workspace.binding}),
    "lock_identity": saved["lock_identity"], "slice_identity": receipt["slice_identity"], "policy_digest": digest(manifest["permission_policy"]), "manifest_digest": digest(manifest),
    "cwd": str(spec.cwd), "engine": manifest["engine"], "argv": list(spec.argv),
    "protected_roots": [str(workspace.local_path), str(workspace.instance), str(workspace.state_root)]}
  # 只传非秘密启动意图；所需秘密已经由 runtime 选定并通过环境交付。
  with tempfile.TemporaryFile(dir=workspace.state_root) as bootstrap:
    bootstrap.write(json_bytes(config))
    bootstrap.flush()
    bootstrap.seek(0)
    child = subprocess.run([sys.executable, "-I", str(frozen_root / "scripts/pi-supervisor.py"),
      "--bootstrap-fd", str(bootstrap.fileno()), "--lease-fd", str(lease_fd), "--instance-fd", str(lifecycle_fd), "--", *spec.argv],
      cwd=spec.cwd, env=env, pass_fds=(bootstrap.fileno(), lease_fd, lifecycle_fd))
  return child.returncode if child.returncode >= 0 else 128 - child.returncode
