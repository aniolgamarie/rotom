"""Shell一次启动的可信父侧作用域；FD清理不构成进程终止或Writer释放证据。"""

from contextlib import contextmanager, ExitStack
from dataclasses import replace
from copy import deepcopy
import os
from pathlib import Path
import secrets
import selectors
import subprocess
import sys
import sysconfig

from .activity import digest
from .deployment import json_bytes
from .paths import trusted_source_directory
from .pi_pid_namespace import host_namespace_binary
from .pi_shell_execution import prepare_shell_execution, _snapshot
from .pi_shell_handoff import authorization_digest, handoff_channel, seal_handoff
from .pi_shell_identity import identity_projection
from .pi_shell_probe_info import read_namespace_info
from .pi_shell_script import _close_owned
from .storage import Conflict, Tree


BOOTSTRAP = "/.rotom-shell-bootstrap"
ENVIRONMENT = {"HOME": BOOTSTRAP + "/home", "TMPDIR": "/tmp", "PATH": "/usr/bin:/bin",
  "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def _require(value):
  if not value: raise Conflict("SHELL_START_STALE")


def _ready(stream):
  with selectors.DefaultSelector() as poll:
    poll.register(stream.fileno(), selectors.EVENT_READ)
    _require(poll.select(10) and os.read(stream.fileno(), 1) == b"R")


class ShellStart:
  """只由已消费准入构造；不接受RPC传来的FD、命令或授权摘要。"""
  def __init__(self, bridge, entry, lease, entrypoint):
    self.bridge, self.host, self.entry = bridge, bridge.host, entry
    self.lease_id, self.entrypoint = lease["lease_id"], entrypoint
    self.attempted = self.active = self.spawned = self.released = False
    self.process = self.identity = self.child = self.gate = self.gate_identity = None
    self.registered = False
    self.private = self.execution = self.handoff_fd = None
    self.private_snapshot = deepcopy(entry["private"])

  def _authority(self, lease, state, *, taken, full=False):
    from .pi_supervisor import Principal
    entry, bridge = self.entry, self.bridge
    _require(not self.host.service.closing and entry["state"] == "consumed"
      and not entry["input_revoked"] and entry["input_taken"] is taken
      and entry["lease_id"] == self.lease_id == lease["lease_id"]
      and lease == self.host.store.read(self.lease_id) and lease["state"] == state
      and lease["spawn_committed"] is (state != "allocating")
      and lease["grant_generation"] == entry["grant_generation"]
      and all(lease[key] == value for key, value in entry["allocation"].items())
      and all(lease[key] == self.host.config[key] for key in ("lock_identity", "slice_identity"))
      and self.host.runtime_root.name == entry["prepared"]["context"]["runtime_identity"]
      and self.host.manifest().get("profile_id") == entry["prepared"]["context"]["profile"]
      and bridge._now_ms() < entry["run_deadline_ms"])
    bridge._principal(Principal("manager", *entry["principal"]))
    shadow = {**entry, "private": self.private} if taken else entry
    _require(shadow["private"] == self.private_snapshot)
    bridge._fresh(shadow, entry["prepared"]["context"], full=full)
    _require(bridge._worker_entrypoint() == self.entrypoint)
    helper = host_namespace_binary(self.host)
    if self.execution is not None:
      _require(str(helper) == self.execution.argv[0])
      for fd, snapshot in self.execution.snapshots:
        _require(_snapshot(os.fstat(fd)) == snapshot)
    # 完整扫描可能消耗剩余时限；密封与G均不能沿用扫描前的时间判断。
    now = bridge._now_ms()
    _require(now < entry["run_deadline_ms"] and now < entry["prepared"]["context"]["deadline_ms"])

  def _authorization(self):
    entry = self.entry; prepared = entry["prepared"]; context = prepared["context"]
    return {"operation_id": prepared["operation_id"], "lease_id": self.lease_id,
      "operation_digest": prepared["operation_digest"], "allocation_digest": digest(entry["allocation"]),
      "runtime_identity": context["runtime_identity"], "lock_identity": entry["allocation"]["lock_identity"],
      "slice_identity": entry["allocation"]["slice_identity"], "context_digest": digest(context),
      "grant_generation": entry["grant_generation"], "profile_id": context["profile"]}

  @contextmanager
  def prepare(self, command, lease):
    _require(not self.attempted and command.launch is self)
    self.attempted = True
    with ExitStack() as resources:
      try:
        self._authority(lease, "allocating", taken=False)
        # 第一次尝试取走正文；即使后续准备失败也不恢复或再发许可。
        self.private = self.entry["private"]
        self.entry.update(private=None, input_taken=True)
        self.authorization = self._authorization()
        self.authorization_hash = authorization_digest(self.authorization)
        self.backend = deepcopy(self.entry["backend"])
        helper = host_namespace_binary(self.host)
        public = {"resolution": self.entry["prepared"]["resolution"], "physical": self.entry["physical"]}
        self.execution = resources.enter_context(prepare_shell_execution(public, self.private["command"],
          helper_path=str(helper), helper_identity=self.backend["helper_identity"], plan_digest=self.backend["plan_digest"]))
        self.outer_sources = {}
        for index, value in enumerate(self.execution.argv):
          if value not in ("--bind-fd", "--ro-bind-fd"): continue
          source = int(self.execution.argv[index + 1])
          _require(source in self.execution.pass_fds and source not in self.outer_sources)
          duplicate = os.dup(source)
          info = os.fstat(duplicate)
          resources.callback(_close_owned, duplicate, (info.st_dev, info.st_ino))
          self.outer_sources[source] = duplicate
        self.handoff_fd = resources.enter_context(handoff_channel())
        python = Path(sys.executable).resolve(strict=True)
        _require(python.is_relative_to("/usr") and python.is_file())
        # -S禁用site/.pth；仅显式加入已选父解释器依赖和收据运行包。
        deps = Path(sysconfig.get_paths()["purelib"]).resolve(strict=True)
        self.dependencies_fd = resources.enter_context(trusted_source_directory(deps))
        self.runtime_fd = resources.enter_context(trusted_source_directory(self.host.runtime_root))
        self.nonce = secrets.token_hex(16)
        argv = (str(python), "-I", "-B", "-S", BOOTSTRAP + "/runtime/supervisor/scripts/pi-shell.py",
          "--handoff-fd", str(self.handoff_fd), "--nonce", self.nonce,
          "--helper-identity", self.backend["helper_identity"], "--plan-digest", self.backend["plan_digest"],
          "--authorization-digest", self.authorization_hash)
        prepared = replace(command, argv=argv, environment=dict(ENVIRONMENT))
        self.command = prepared
        self.active = True
        yield prepared
      finally:
        # gate先关闭，子namespace清理后再归还父FD。失败不改租约/Writer状态。
        self.close_gate()
        if not self.released: self._stop_failed()
        self.active = False
        self.private = self.execution = self.handoff_fd = None
        self.private_snapshot = None

  def _outer_argv(self, info_fd):
    argv = [self.execution.argv[0], "--unshare-all", "--as-pid-1", "--new-session",
      "--die-with-parent", "--cap-drop", "ALL", "--clearenv", "--proc", "/proc", "--dev", "/dev",
      "--perms", "1777", "--tmpfs", "/tmp"]
    # 普通bind的proc路径仍会realpath重开；用专用dup做bind-fd挂载后身份核验。
    # 外层bwrap消费dup，原始来源FD留给内层；不以proc路径字符串冒充FD锚定。
    inner = self.execution.argv
    for index, value in enumerate(inner):
      if value in ("--bind-fd", "--ro-bind-fd"):
        fd, destination = inner[index + 1:index + 3]
        path = Path(destination)
        _require(not path.is_relative_to(BOOTSTRAP) and not Path(BOOTSTRAP).is_relative_to(path))
        argv.extend((value, str(self.outer_sources[int(fd)]), destination))
      elif value == "--symlink":
        argv.extend(inner[index:index + 3])
    argv.extend(("--perms", "0700", "--dir", BOOTSTRAP, "--dir", BOOTSTRAP + "/home",
      "--ro-bind-fd", str(self.runtime_fd), BOOTSTRAP + "/runtime",
      "--ro-bind-fd", str(self.dependencies_fd), BOOTSTRAP + "/python-deps"))
    for name, value in ENVIRONMENT.items(): argv.extend(("--setenv", name, value))
    argv.extend(("--info-fd", str(info_fd), "--chdir", str(self.command.cwd), "--", *self.command.argv))
    return argv

  def spawn(self, command, lease, environment, streams):
    _require(self.active and not self.spawned and command is self.command and environment == ENVIRONMENT
      and streams == {"stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE})
    self.spawned = True
    self._authority(lease, "starting", taken=True)
    info_read = info_write = gate_read = None
    try:
      info_read, info_write = os.pipe()
      gate_read, self.gate = os.pipe()
      info = os.fstat(self.gate); self.gate_identity = (info.st_dev, info.st_ino)
      self.process = subprocess.Popen(self._outer_argv(info_write),
        executable="/proc/self/fd/" + str(self.execution.helper_fd), cwd=command.cwd, env={},
        stdin=gate_read, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, close_fds=True,
        pass_fds=(info_write, self.handoff_fd, self.execution.helper_fd, *self.execution.pass_fds,
          *self.outer_sources.values(), self.runtime_fd, self.dependencies_fd), start_new_session=True)
      os.close(info_write); info_write = None
      os.close(gate_read); gate_read = None
      info = read_namespace_info(info_read)
      _ready(self.process.stdout)
      # R在PID1/setsid之后；不能用info刚发布时可能改变的PGID登记。
      self.identity = self.host.processes.identity(info["child-pid"])
      wrapper = self.host.processes.identity(self.process.pid)
      _require(self.identity["namespace"] == "pid:[" + str(info["pid-namespace"]) + "]")
      self.host.processes.register_namespace(self.identity, wrapper)
      self.registered = True
      return self.process, self.identity, self.gate
    finally:
      for fd in (info_read, info_write, gate_read):
        if fd is not None: os.close(fd)

  def bind_child(self, child):
    _require(self.active and self.child is None and child["process"] is self.process
      and child["identity"] == self.identity and child["gate"] == self.gate)
    self.child = child

  def activate(self, lease):
    _require(self.active and self.registered and not self.released and self.child is not None
      and self.child["gate"] == self.gate and self.gate is not None and lease["process_identity"] == self.identity)
    self._authority(lease, "running", taken=True)
    _require(self.authorization == self._authorization() and self.backend == self.entry["backend"])
    mapping = identity_projection(self.execution, processes=self.host.processes, leader=self.identity)
    binding = {"purpose": "shell-execution", "nonce": self.nonce,
      "helper_identity": self.backend["helper_identity"], "plan_digest": self.backend["plan_digest"],
      "worker_identity": self.identity, "worker_user_namespace": mapping["worker_user_namespace"],
      "uid_projection": mapping["uid_projection"], "authorization": self.authorization}
    seal_handoff(self.handoff_fd, self.execution, binding)
    with Tree(self.host.root) as tree:
      tree.write_immutable("activity/ordinary-shell-handoffs/" + self.lease_id + ".json",
        json_bytes({"schema_version": 1, "binding": binding, "identity_projection": mapping}))
    # 密封和持久交接记录之后、G之前仍完整扫描；交接记录本身不授予执行。
    self._authority(lease, "running", taken=True, full=True)
    gate = self.gate
    info = os.fstat(gate)
    _require((info.st_dev, info.st_ino) == self.gate_identity)
    # 表中先撤销FD所有权，避免Host退出路径关闭已复用的整数。
    self.child["gate"] = None
    try:
      _require(os.write(gate, b"G") == 1)
      self.released = True
    finally: self.close_gate()

  def close_gate(self):
    gate, self.gate = self.gate, None
    if self.child is not None: self.child["gate"] = None
    if gate is not None: _close_owned(gate, self.gate_identity)

  def _stop_failed(self):
    if self.process is None: return
    if self.registered:
      try: self.host.processes.stop(self.identity, grace_seconds=2)
      except Exception: pass  # 未确认的终止保留租约保护，由既有恢复路径处理。
    try:
      if self.process.poll() is None:
        try: self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
          self.process.kill(); self.process.wait(timeout=2)
    except Exception: pass
    if self.child is None:
      for name in ("stdin", "stdout", "stderr"):
        stream = getattr(self.process, name, None)
        if stream is not None: stream.close()
