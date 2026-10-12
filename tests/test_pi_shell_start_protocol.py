"""独立外层argv/就绪/FD协议；进程全替身，不启动helper或namespace。"""

from copy import deepcopy
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import pi_shell_start as module
from agentcfg.storage import Conflict


def outer_case():
  launch = module.ShellStart.__new__(module.ShellStart)
  launch.execution = SimpleNamespace(argv=("/runtime/bin/pi-bwrap",
    "--clearenv", "--bind-fd", "21", "/work/project",
    "--ro-bind-fd", "22", "/usr", "--symlink", "/usr/bin", "/bin",
    "--ro-bind-fd", "23", "/usr/bin/bash",
    "--perms", "0000", "--tmpfs", "/work/project/private", "--remount-ro", "/work/project/private",
    "--ro-bind-data", "24", "/.rotom-shell/script", "--seccomp", "25",
    "--chdir", "/work/project", "--", "/usr/bin/bash", "--noprofile", "--norc", "/.rotom-shell/script"))
  launch.runtime_fd, launch.dependencies_fd = 26, 27
  launch.outer_sources = {21: 31, 22: 32, 23: 33}
  launch.command = SimpleNamespace(cwd=Path("/work/project"), argv=("/usr/bin/python3.11", "-I", "-B", "-S",
    module.BOOTSTRAP + "/runtime/supervisor/scripts/pi-shell.py", "--handoff-fd", "28"))
  return launch


def triples(argv, flag):
  return [tuple(argv[index:index + 3]) for index, value in enumerate(argv) if value == flag]


def test_outer_argv_mounts_only_fd_sources_and_fixed_bootstrap_without_rpc_environment(monkeypatch):
  launch = outer_case()
  monkeypatch.setenv("AGENTCFG_SUPERVISOR_CAPABILITY", "private-capability-sentinel")
  monkeypatch.setenv("PYTHONPATH", "/untrusted-python")
  result = launch._outer_argv(29)
  assert result[:8] == ["/runtime/bin/pi-bwrap", "--unshare-all", "--as-pid-1", "--new-session",
    "--die-with-parent", "--cap-drop", "ALL", "--clearenv"]
  assert triples(result, "--bind-fd") == [("--bind-fd", "31", "/work/project")]
  assert triples(result, "--bind") == [] and triples(result, "--ro-bind") == []
  assert triples(result, "--ro-bind-fd") == [
    ("--ro-bind-fd", "32", "/usr"), ("--ro-bind-fd", "33", "/usr/bin/bash"),
    ("--ro-bind-fd", "26", module.BOOTSTRAP + "/runtime"),
    ("--ro-bind-fd", "27", module.BOOTSTRAP + "/python-deps")]
  assert triples(result, "--symlink") == [("--symlink", "/usr/bin", "/bin")]
  assert triples(result, "--setenv") == [("--setenv", key, value) for key, value in module.ENVIRONMENT.items()]
  assert module.ENVIRONMENT["HOME"] == module.BOOTSTRAP + "/home"
  assert result[-(len(launch.command.argv) + 5):] == ["--info-fd", "29", "--chdir", "/work/project", "--", *launch.command.argv]
  assert "--ro-bind-data" not in result and "--seccomp" not in result
  assert not any(value.startswith("/proc/self/fd/") for value in result)
  assert not {"21", "22", "23", "24", "25"} & set(result)
  assert "/work/project/private" not in result and "/.rotom-shell/script" not in result
  assert "private-capability-sentinel" not in repr(result) and "/untrusted-python" not in result
  assert "AGENTCFG_SUPERVISOR_ENDPOINT" not in result and "AGENTCFG_SUPERVISOR_CAPABILITY" not in result


@pytest.mark.parametrize("destination", ["/", module.BOOTSTRAP, module.BOOTSTRAP + "/child"])
def test_outer_argv_cannot_bind_over_bootstrap_parent_or_child(destination):
  launch = outer_case()
  launch.execution.argv = ("helper", "--ro-bind-fd", "21", destination)
  with pytest.raises(Conflict, match="^SHELL_START_STALE$"): launch._outer_argv(29)


@pytest.mark.parametrize("body", [b"R", b"", b"X"])
def test_ready_checks_real_pipe_eof_or_fixed_byte(body):
  read, write = os.pipe()
  try:
    if body: os.write(write, body)
    os.close(write); write = None
    with os.fdopen(os.dup(read), "rb") as stream:
      if body == b"R": module._ready(stream)
      else:
        with pytest.raises(Conflict, match="^SHELL_START_STALE$"): module._ready(stream)
    # 调用者FD不被关闭。
    os.fstat(read)
  finally:
    os.close(read)
    if write is not None: os.close(write)


def test_ready_timeout_is_bounded_and_never_reads_when_unready(monkeypatch):
  calls = []
  class Selector:
    def __enter__(self): return self
    def __exit__(self, *args): calls.append("close")
    def register(self, fd, event): calls.append((fd, event))
    def select(self, timeout): assert timeout == 10; calls.append("wait"); return []
  monkeypatch.setattr(module.selectors, "DefaultSelector", Selector)
  proxy = SimpleNamespace(**vars(os))
  proxy.read = lambda *args: pytest.fail("timeout must not read")
  monkeypatch.setattr(module, "os", proxy)
  with pytest.raises(Conflict): module._ready(SimpleNamespace(fileno=lambda: 41))
  assert calls == [(41, module.selectors.EVENT_READ), "wait", "close"]


def protocol_popen(state, monkeypatch):
  # 独立spawn协议不调用Store.start；保留原allocating租约作为不变哨兵。
  class Process:
    pid = 204
    stdin = None
    def __init__(self):
      self.stdout = open(os.devnull, "rb"); self.stderr = open(os.devnull, "rb")
      self.returncode = None
    def poll(self): return self.returncode
    def wait(self, **kwargs): self.returncode = 0; return 0
    def kill(self): self.returncode = -9
  def popen(argv, **kwargs):
    state.events.append("spawn")
    state.argv, state.kwargs = argv, kwargs
    state.parent_fds.extend(fd for fd in kwargs["pass_fds"] if fd not in state.parent_fds)
    state.gate_read = os.dup(kwargs["stdin"])
    state.process = Process()
    return state.process
  monkeypatch.setattr(module.subprocess, "Popen", popen)


def test_spawn_ready_precedes_identity_registration_and_inherits_only_owned_fds(tmp_path, monkeypatch):
  from test_pi_shell_start import fixture, cleanup
  state = fixture(tmp_path, monkeypatch)
  protocol_popen(state, monkeypatch)
  launch = state.launch; events = state.events
  original_identity = state.f[2].processes.identity
  def identity(pid):
    events.append("identity-" + str(pid)); return original_identity(pid)
  monkeypatch.setattr(state.f[2].processes, "identity", identity)
  try:
    with launch.prepare(state.command, state.lease) as command:
      monkeypatch.setattr(launch, "_authority", lambda *args, **kwargs: None)
      child, leader, gate = launch.spawn(command, state.lease, deepcopy(module.ENVIRONMENT),
        {"stdin": module.subprocess.DEVNULL, "stdout": module.subprocess.PIPE, "stderr": module.subprocess.PIPE})
      assert events.index("ready") < events.index("identity-203") < events.index("register")
      expected = {launch.handoff_fd, launch.execution.helper_fd, *launch.execution.pass_fds,
        *launch.outer_sources.values(), launch.runtime_fd, launch.dependencies_fd}
      inherited = state.kwargs["pass_fds"]
      assert len(inherited) == len(set(inherited)) and set(inherited[1:]) == expected
      assert state.kwargs["env"] == {} and state.kwargs["shell"] is False and state.kwargs["close_fds"] is True
      assert state.kwargs["stdin"] not in inherited and launch.gate not in inherited
      for fd in inherited[1:]: os.fstat(fd)
      os.set_blocking(state.gate_read, False)
      with pytest.raises(BlockingIOError): os.read(state.gate_read, 1)
      descriptors = list(inherited[1:])
    assert os.read(state.gate_read, 1) == b""
    for fd in descriptors:
      with pytest.raises(OSError): os.fstat(fd)
    assert state.f[2].store.read(state.lease["lease_id"]) == state.lease
  finally: cleanup(state)


def test_failed_readiness_closes_gate_and_wrapper_resources_without_registration_or_lease_change(tmp_path, monkeypatch):
  from test_pi_shell_start import fixture, cleanup
  state = fixture(tmp_path, monkeypatch); state.fault = "ready"
  protocol_popen(state, monkeypatch)
  launch = state.launch
  monkeypatch.setattr(state.f[2].processes, "identity", lambda pid: pytest.fail("identity must follow R"))
  try:
    with pytest.raises(Conflict, match="fixture-ready"):
      with launch.prepare(state.command, state.lease) as command:
        monkeypatch.setattr(launch, "_authority", lambda *args, **kwargs: None)
        launch.spawn(command, state.lease, deepcopy(module.ENVIRONMENT),
          {"stdin": module.subprocess.DEVNULL, "stdout": module.subprocess.PIPE, "stderr": module.subprocess.PIPE})
    assert state.events == ["prepare", "spawn", "ready", "close-preparation"]
    assert not launch.registered and launch.gate is None and not launch.active
    assert state.process.poll() == 0 and state.process.stdout.closed and state.process.stderr.closed
    assert os.read(state.gate_read, 2) == b""
    assert state.f[2].store.read(state.lease["lease_id"]) == state.lease
    for fd in state.parent_fds:
      with pytest.raises(OSError): os.fstat(fd)
  finally: cleanup(state)


def test_consuming_outer_duplicate_fds_preserves_original_inner_sources(tmp_path, monkeypatch):
  from test_pi_shell_start import fixture, cleanup
  state = fixture(tmp_path, monkeypatch); launch = state.launch
  try:
    with launch.prepare(state.command, state.lease):
      originals = set(launch.outer_sources)
      duplicates = set(launch.outer_sources.values())
      assert originals and len(originals) == len(duplicates)
      assert not originals & duplicates and not duplicates & {launch.execution.helper_fd, *launch.execution.pass_fds}
      for original, duplicate in launch.outer_sources.items():
        assert os.fstat(original) == os.fstat(duplicate)
        assert not os.get_inheritable(original) and not os.get_inheritable(duplicate)
      # 模拟bwrap消费专用挂载FD；内层FD不被消费，无需真实fork/helper。
      for duplicate in duplicates: os.close(duplicate)
      for original in originals: os.fstat(original)
    for fd in originals | duplicates:
      with pytest.raises(OSError): os.fstat(fd)
    assert state.f[2].store.read(state.lease["lease_id"]) == state.lease
  finally: cleanup(state)
