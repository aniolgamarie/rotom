"""监督主循环与执行闸门使用Popen/身份/端点替身，不启动宿主。"""

from pathlib import Path
from types import SimpleNamespace
import os

import pytest

from agentcfg import pi_host
from agentcfg.pi_supervisor import SpawnCommand
from agentcfg.storage import Conflict
from test_pi_activity import FakeProcesses, identity
from test_pi_supervisor import request


def test_supervisor_registers_before_exec_and_outlives_parent_host(tmp_path, monkeypatch):
  processes = FakeProcesses()
  processes.current[os.getpid()] = identity(os.getpid())
  processes.identity = lambda pid: processes.current[pid]
  registered = []
  processes.register = lambda value: registered.append(value["pid"])
  # 停止请求不等于物理退出；第二次观察前仍保留活动与实例保护。
  processes.stop = lambda value, **kwargs: processes.signals.append(value)
  monkeypatch.setattr(pi_host, "LinuxProcesses", lambda *args: processes)
  monkeypatch.setattr(pi_host.sys, "platform", "linux")
  children = []
  class Child:
    def __init__(self, argv, *, cwd, env, pass_fds, start_new_session):
      assert start_new_session is True
      self.pid = 201 + len(children)
      self.returncode = None
      self.gate = os.dup(pass_fds[0])
      self.environment = env
      self.argv = argv
      processes.current[self.pid] = identity(self.pid)
      children.append(self)
    def poll(self):
      return self.returncode
  monkeypatch.setattr(pi_host.subprocess, "Popen", Child)
  def namespace_spawn(host, command, environment, streams):
    assert not streams
    read_fd, write_fd = os.pipe()
    try:
      child = Child(command.argv, cwd=command.cwd, env=environment, pass_fds=(read_fd,), start_new_session=True)
    finally:
      os.close(read_fd)
    value = processes.identity(child.pid)
    processes.register(value)
    return child, value, write_fd
  monkeypatch.setattr("agentcfg.pi_pid_namespace.spawn_host_namespace", namespace_spawn)
  config = {"state_root": str(tmp_path / "state"), "instance_root": str(tmp_path / "instance"),
    "repository": str(Path(__file__).resolve().parents[1]), "runtime_root": str(tmp_path / "runtime"), "instance_id": "fixture",
    "lock_identity": "a" * 64, "slice_identity": "b" * 64, "policy_digest": "c" * 64, "cwd": str(tmp_path), "engine": "node", "argv": ["synthetic-host"]}
  host = pi_host.HostSupervisor(config, lease_fd=None)
  class Endpoint:
    endpoint = tmp_path / "control.json"
    polls = 0
    closed = False
    def open(self):
      return self.endpoint
    def poll(self):
      self.polls += 1
      if self.polls == 1:
        assert host.store.read(host.host_lease_id)["state"] == "running"
        assert os.read(children[0].gate, 1) == b"G"
        os.close(children[0].gate)
        token = children[0].environment["AGENTCFG_SUPERVISOR_CAPABILITY"]
        args = {"kind": "worker", "execution_id": "worker", "task_id": "task", "attempt_id": "attempt", "lock_identity": "a" * 64,
          "slice_identity": "b" * 64, "policy_digest": "c" * 64, "candidate_digest": "d" * 64, "planned_workspaces": []}
        allocated = host.service.reply(token, os.geteuid(), request("allocate", args))["result"]
        host.service.command_resolver = lambda *args: SpawnCommand(("synthetic-worker",), tmp_path, {})
        started = host.service.reply(token, os.geteuid(), request("start", {"lease_id": allocated["lease_id"], "program": "worker", "payload": {}}))
        assert started["result"]["state"] == "running"
        assert os.read(children[1].gate, 1) == b"G"
        os.close(children[1].gate)
        children[0].returncode = 0
        processes.current.pop(201)
      else:
        assert host.host_exit == 0
        with pytest.raises(Conflict):
          host.store.assert_mutable()
        old_token = children[0].environment["AGENTCFG_SUPERVISOR_CAPABILITY"]
        assert host.service.reply(old_token, os.geteuid(), request("handshake", {}))["exit_code"] == 4
        children[1].returncode = 0
        processes.current.pop(202)
    def close(self):
      self.closed = True
  endpoint = Endpoint()
  host.server = endpoint
  assert host.run() == 0
  assert endpoint.polls == 2 and endpoint.closed is True
  assert registered == [201, 202]
  assert processes.signals and all(value["pid"] == 202 for value in processes.signals)
  host.store.assert_mutable()


def test_identity_failure_closes_exec_gate_without_releasing_unknown_lease(tmp_path, monkeypatch):
  host = object.__new__(pi_host.HostSupervisor)
  host.repository = tmp_path
  host.children = {}
  gates = []
  class Child:
    pid = 201
    def __init__(self, argv, **kwargs):
      gates.append(os.dup(kwargs["pass_fds"][0]))
  def unknown(pid):
    raise Conflict("synthetic identity unavailable")
  host.processes = SimpleNamespace(identity=unknown)
  monkeypatch.setattr(pi_host.sys, "platform", "linux")
  monkeypatch.setattr(pi_host.subprocess, "Popen", Child)
  with pytest.raises(Conflict):
    host.spawn(SpawnCommand(("synthetic-worker",), tmp_path, {}), {"lease_id": "lease"})
  try:
    os.set_blocking(gates[0], False)
    assert os.read(gates[0], 1) == b""
  finally:
    os.close(gates[0])
  assert host.children == {}


def test_parent_exit_aborts_only_complete_unspawned_allocations(tmp_path):
  from test_pi_activity import make_store
  store, processes = make_store(tmp_path)
  host = object.__new__(pi_host.HostSupervisor)
  host.store, host.processes, host.children, host.root = store, processes, {}, store.root
  import threading
  host.service = SimpleNamespace(mutex=threading.RLock())
  host.host_exit, host.host_lease_id = 0, "host"
  args = {"kind": "worker", "task_id": "task", "lock_identity": "a" * 64, "slice_identity": "b" * 64,
    "policy_digest": "c" * 64, "candidate_digest": "d" * 64, "planned_workspaces": []}
  waiting = store.allocate(**args, execution_id="waiting", attempt_id="waiting")
  unknown = store.allocate(**args, execution_id="unknown", attempt_id="unknown")
  def lost_ack(lease):
    raise OSError("synthetic spawn acknowledgment loss")
  with pytest.raises(Conflict):
    store.start(unknown["lease_id"], store.owner, spawn=lost_ack)
  host.poll()
  assert store.reconcile(waiting["lease_id"])["protected"] is False
  assert store.reconcile(unknown["lease_id"])["protected"] is True
  assert processes.signals == []


def test_standalone_delegate_supervisor_never_starts_an_interactive_host(tmp_path):
  import json
  import threading
  from test_pi_delegate import fixture
  controller, base, args, starts = fixture(tmp_path)
  host = object.__new__(pi_host.HostSupervisor)
  host.__dict__.update(base.__dict__)
  host.config["delegate_request"] = args
  host.children = {}; host.host_exit = None; host.host_lease_id = None
  host.delegates = controller; controller.host = host
  host.processes = host.store.processes
  host.service.mutex = threading.RLock(); host.service.closing = False
  class Server:
    closed = False
    def open(self): pass
    def poll(self): host.store.processes.current.pop(201, None)
    def close(self): self.closed = True
  host.server = Server()
  read, write = os.pipe()
  try:
    # 假执行没有模型结果，监督者只能报告 failed，不能从退出0推导成功。
    assert host.run_delegate(write) == 5
    result = json.loads(os.read(read, 4096))
    assert result["ok"] is True and result["result"]["state"] == "start_unknown"
    assert len(starts) == 1 and all(row["kind"] != "host" for row in host.store.records())
    assert host.server.closed and host.service.closing
    host.store.assert_mutable()
  finally:
    os.close(read)


def test_worker_exit_does_not_release_lease_while_supervisor_file_action_is_in_flight(tmp_path):
  import threading
  from test_pi_supervisor import fixture
  service, token, args, calls = fixture(tmp_path)
  allocated = service.reply(token, os.geteuid(), request("allocate", args))["result"]
  started = service.reply(token, os.geteuid(), request("start", {"lease_id": allocated["lease_id"], "program": "worker", "payload": {}}))["result"]
  worker = service.issue_capability("worker", allocated["lease_id"])
  entered, release = threading.Event(), threading.Event()
  sentinel = tmp_path / "supervisor-file-action"
  def operation(*_args):
    entered.set(); assert release.wait(5)
    sentinel.write_text("settled")
    return {"finished": True}
  service.ordinary_handler = operation
  thread = threading.Thread(target=lambda: service.reply(worker, os.geteuid(), request("ordinary_perform", {})))
  host = object.__new__(pi_host.HostSupervisor)
  host.store, host.processes, host.children, host.root = service.store, service.store.processes, {}, service.store.root
  host.service, host.host_exit, host.host_lease_id = service, None, None
  thread.start()
  try:
    assert entered.wait(2)
    service.store.processes.current.pop(service.store.read(allocated["lease_id"])["process_identity"]["pid"])
    host.poll()
    assert service.store.reconcile(allocated["lease_id"])["protected"] is True
    assert not sentinel.exists()
  finally:
    release.set(); thread.join(5)
  host.poll()
  assert sentinel.read_text() == "settled"
  assert service.store.reconcile(allocated["lease_id"])["protected"] is False


def test_linux_gate_sets_private_umask_only_after_admission(tmp_path, monkeypatch):
  import importlib.util
  import sys
  source = Path(__file__).resolve().parents[1] / "scripts/pi-exec.py"
  spec = importlib.util.spec_from_file_location("pi_exec_gate_fixture", source)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  read_fd, write_fd = os.pipe(); os.write(write_fd, b"G"); os.close(write_fd)
  monkeypatch.setattr(sys, "argv", ["pi-exec.py", "--gate-fd", str(read_fd), "--", "fixture-never-executed"])
  observed = []
  def exec_stub(*_):
    current = os.umask(0o077); observed.append(current)
  monkeypatch.setattr(os, "execvpe", exec_stub)
  before = os.umask(0o022)
  try:
    assert module.main() == 126
    assert observed == [0o077]
  finally: os.umask(before)


@pytest.mark.parametrize("admitted", [False, True])
def test_terminal_gate_claims_only_after_admission(tmp_path, monkeypatch, admitted):
  import importlib.util
  import fcntl
  import termios
  source = Path(__file__).resolve().parents[1] / "scripts/pi-exec.py"
  spec = importlib.util.spec_from_file_location("pi_terminal_gate_fixture", source)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  read_fd, write_fd = os.pipe()
  if admitted: os.write(write_fd, b"G")
  os.close(write_fd)
  monkeypatch.setattr(pi_host.sys, "argv", ["pi-exec.py", "--gate-fd", str(read_fd), "--", "fixture-never-executed"])
  monkeypatch.setenv("AGENTCFG_EXECUTION_TTY", "1")
  calls = []
  monkeypatch.setattr(os, "isatty", lambda fd: fd == 0)
  monkeypatch.setattr(fcntl, "ioctl", lambda *args: calls.append(args))
  monkeypatch.setattr(os, "execvpe", lambda *args: calls.append(("exec", "AGENTCFG_EXECUTION_TTY" in args[2])))
  before = os.umask(0o022)
  try:
    assert module.main() == (126 if admitted else 125)
    assert calls == ([(0, termios.TIOCSCTTY, 0), ("exec", False)] if admitted else [])
  finally: os.umask(before)


def test_terminal_spawn_binds_private_streams_before_opening_gate(tmp_path, monkeypatch):
  from agentcfg import pi_terminal
  host = object.__new__(pi_host.HostSupervisor)
  host.repository, host.children = tmp_path, {}
  events, gates = [], []
  class Terminal:
    def __init__(self, *size): events.append(("terminal", size))
    def streams(self): return {"stdin": 901, "stdout": 901, "stderr": 901}
    def attach(self, child): events.append("attach-terminal")
    def close(self): events.append("close-terminal")
  class Capture:
    def __init__(self, root): pass
    def attach(self, child): events.append("attach-capture")
  class Child:
    pid = 201
    def __init__(self, argv, **kwargs):
      assert kwargs["start_new_session"]
      assert all(kwargs[name] == 901 for name in ("stdin", "stdout", "stderr"))
      assert kwargs["env"]["AGENTCFG_EXECUTION_TTY"] == "1"
      gate = os.dup(kwargs["pass_fds"][0]); os.set_blocking(gate, False); gates.append(gate)
      events.append("spawn")
  host.processes = SimpleNamespace(identity=lambda pid: identity(pid), register=lambda row: events.append("register"))
  monkeypatch.setattr(pi_host.sys, "platform", "linux")
  monkeypatch.setattr(pi_terminal, "TerminalChannels", Terminal)
  monkeypatch.setattr(pi_host, "OutputCapture", Capture)
  monkeypatch.setattr(pi_host.subprocess, "Popen", Child)
  command = SpawnCommand(("synthetic-editor",), tmp_path, {}, capture_root=tmp_path / "capture", stdin_pipe=True, terminal_size=(24, 80))
  try:
    host.spawn(command, {"lease_id": "editor", "kind": "external"})
    assert events == [("terminal", (24, 80)), "spawn", "register", "attach-terminal", "attach-capture"]
    with pytest.raises(BlockingIOError): os.read(gates[0], 1)
    host.activate({"lease_id": "editor"})
    assert os.read(gates[0], 1) == b"G"
  finally:
    for fd in gates: os.close(fd)
