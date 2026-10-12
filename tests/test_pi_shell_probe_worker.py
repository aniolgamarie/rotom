"""可信探针worker/heartbeat的默认替身测试；不启动原生payload或进程。"""

from contextlib import contextmanager
from copy import deepcopy
import errno
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from agentcfg.schema import ConfigError
from test_pi_shell_execution import execution_case
from test_pi_shell_preparation import shell_case


DIRECTORY = Path(__file__).parent / "fixtures/pi/shell-helper-probe"
NONCE = "a" * 32
HELPER = "b" * 64
PLAN = "c" * 64
NS = ("pid", "net", "user", "mnt", "ipc", "uts")


def load(name):
  paths, flag = sys.path[:], sys.dont_write_bytecode
  try:
    spec = importlib.util.spec_from_file_location("synthetic_probe_" + name, DIRECTORY / (name + ".py"))
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value
  finally:
    sys.path[:] = paths
    sys.dont_write_bytecode = flag


@pytest.fixture
def worker(tmp_path, monkeypatch):
  value = load("worker"); calls = []; descriptors = []; null_fds = []
  value.os = SimpleNamespace(**vars(os))
  value._test_work_root = tmp_path
  canary = tmp_path / "canary"; canary.write_bytes(b"probe-outside\n")
  null = tmp_path / "null"; null.write_bytes(b"")
  original_open = os.open
  def opened(path, flags, mode=0o777):
    if str(path) == "/dev/null":
      calls.append(("null", flags))
      fd = original_open(null, flags, mode); null_fds.append(fd); return fd
    assert path == tmp_path / "outside/canary"
    assert flags & os.O_CLOEXEC and flags & os.O_NOFOLLOW
    fd = original_open(canary, flags, mode); descriptors.append(fd); return fd
  monkeypatch.setattr(value.os, "open", opened)
  def read(fd, size):
    assert (fd, size) == (0, 2); calls.append("gate-read"); return b"G"
  monkeypatch.setattr(value.os, "read", read)
  monkeypatch.setattr(value.os, "dup2", lambda source, dest, **kwargs: calls.append(("dup2", dest)))
  monkeypatch.setattr(value.os, "getpid", lambda: 1)
  monkeypatch.setattr(value, "bootstrap", lambda case, nonce: {"schema_version": 1, "phase": "bootstrap", "case_id": case,
    "nonce": nonce, "uid": 1002, "owners": {"root": 0, "usr": 0, "bash": 0}, "user_namespace": "user:[123]", "uid_map": "1002 1002 1\n"})
  monkeypatch.setattr(value, "namespaces", lambda: {name: name + ":[123]" for name in NS})
  @contextmanager
  def adoption(fd, **kwargs):
    assert len(null_fds) == 1
    with pytest.raises(OSError) as caught: os.fstat(null_fds[0])
    assert caught.value.errno == errno.EBADF
    calls.append(("adopt", fd, kwargs))
    try: yield SimpleNamespace(synthetic=True)
    finally: calls.append("cleanup")
  monkeypatch.setattr(value, "adopt_handoff", adoption)
  class Executed(BaseException): pass
  def execute(execution):
    assert execution.synthetic and os.get_inheritable(descriptors[-1])
    calls.append("exec"); raise Executed()
  monkeypatch.setattr(value, "exec_prepared", execute)
  return value, calls, descriptors, Executed


@pytest.mark.parametrize("case", ["boundary", "descendants"])
def test_gate_and_fixed_shell_policy_and_exec_seams(worker, case, capsys):
  value, calls, fds, executed = worker
  with pytest.raises(executed): value.run(case, NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert calls[0] == "gate-read" and ("dup2", 0) in calls
  invocation = next(item for item in calls if isinstance(item, tuple) and item[0] == "adopt")
  assert invocation == ("adopt", 17, {"nonce": NONCE, "helper_identity": HELPER, "plan_digest": PLAN})
  assert not hasattr(value, "preparation") and not hasattr(value, "prepare_shell") and not hasattr(value, "compile_mount_plan")
  messages = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
  assert len(messages) == 2 and messages[0]["phase"] == "bootstrap"
  prepared = messages[1]
  assert set(prepared) == {"schema_version", "phase", "case_id", "nonce", "helper_identity", "plan_digest", "namespaces"}
  assert prepared["phase"] == "prepared" and prepared["case_id"] == case and prepared["helper_identity"] == HELPER
  assert prepared["plan_digest"] == PLAN
  assert calls[-2:] == ["exec", "cleanup"] and len(fds) == 1
  with pytest.raises(OSError) as caught: os.fstat(fds[0])
  assert caught.value.errno == errno.EBADF


@pytest.mark.parametrize("gate", [b"", b"X", b"GG", b"G\n"])
def test_invalid_gate_never_prepares(worker, monkeypatch, gate):
  value, calls, _, _ = worker
  monkeypatch.setattr(value.os, "read", lambda fd, count: gate)
  with pytest.raises(ValueError): value.run("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert not any(isinstance(item, tuple) and item[0] == "adopt" for item in calls)


def test_non_pid1_refuses_before_reading_gate(worker, monkeypatch):
  value, calls, _, _ = worker
  monkeypatch.setattr(value.os, "getpid", lambda: 20)
  with pytest.raises(ValueError): value.run("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert calls == []


@pytest.mark.parametrize("fault", ["case", "nonce", "helper"])
def test_invalid_parameters_refuse_before_gate(worker, fault):
  value, calls, _, _ = worker
  args = ["boundary", NONCE, HELPER]; args[{"case": 0, "nonce": 1, "helper": 2}[fault]] = "private-invalid"
  with pytest.raises(ValueError): value.run(*args, 17, PLAN, value._test_work_root)
  assert calls == []


def test_wrong_helper_hash_emits_only_fixed_rejection(worker, monkeypatch, capsys):
  value, calls, fds, _ = worker
  @contextmanager
  def rejected(fd, **kwargs):
    assert kwargs["helper_identity"] == "0" * 64
    raise ConfigError("pi-shell-handoff")
    yield
  monkeypatch.setattr(value, "adopt_handoff", rejected)
  value.run("helper-mismatch", NONCE, HELPER, 17, PLAN, value._test_work_root)
  messages = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
  assert len(messages) == 2 and messages[0]["phase"] == "bootstrap"
  assert messages[1] == {"schema_version": 1, "phase": "helper-rejected", "case_id": "helper-mismatch",
    "nonce": NONCE, "code": "pi-shell-handoff"}
  assert fds == [] and "exec" not in calls


def test_other_preparation_error_is_not_helper_mismatch_success(worker, monkeypatch, capsys):
  value, _, _, _ = worker
  @contextmanager
  def rejected(*args, **kwargs):
    raise ConfigError("private-other-error")
    yield
  monkeypatch.setattr(value, "adopt_handoff", rejected)
  with pytest.raises(ConfigError): value.run("helper-mismatch", NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert [json.loads(line)["phase"] for line in capsys.readouterr().out.splitlines()] == ["bootstrap"]


def test_canary_fd_reuse_is_not_closed(worker, monkeypatch, tmp_path):
  value, _, fds, executed = worker
  # worker fixture替换了os.open/dup2；自有memfd不触及pytest或stdin描述符。
  foreign = os.memfd_create("synthetic-foreign", os.MFD_CLOEXEC)
  real_dup2 = os.dup2
  def execute(execution):
    fd = fds[0]; os.close(fd); real_dup2(foreign, fd, inheritable=False)
    raise executed()
  monkeypatch.setattr(value, "exec_prepared", execute)
  try:
    with pytest.raises(executed): value.run("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)
    assert os.fstat(fds[0]).st_ino == os.fstat(foreign).st_ino
  finally:
    if fds: os.close(fds[0])
    os.close(foreign)


def test_main_has_no_gate_fd_argument(worker, monkeypatch):
  value, _, _, _ = worker; calls = []
  monkeypatch.setattr(value, "run", lambda *args: calls.append(args))
  value.main(["--probe-worker", "boundary", "--nonce", NONCE, "--helper-identity", HELPER, "--handoff-fd", "17", "--plan-digest", PLAN, "--work-root", str(value._test_work_root)])
  assert calls == [("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)]
  with pytest.raises(ValueError): value.main(["--probe-worker", "boundary", "--nonce", NONCE, "--helper-identity", HELPER, "--gate-fd", "9"])


@pytest.fixture
def heartbeat(tmp_path, monkeypatch):
  value = load("heartbeat"); original_open = os.open; fds = []; sleeps = []
  value.os = SimpleNamespace(**vars(os))
  value.time = SimpleNamespace(**vars(value.time))
  path = tmp_path / "heartbeat"
  def opened(name, flags, mode):
    assert name == value.WORK_ROOT / "project/heartbeat" and mode == 0o600
    assert flags & os.O_EXCL and flags & os.O_NOFOLLOW
    fd = original_open(path, flags, mode); fds.append(fd); return fd
  monkeypatch.setattr(value.os, "open", opened)
  monkeypatch.setattr(value.os, "getpid", lambda: 23)
  monkeypatch.setattr(value.os, "readlink", lambda path: path.rsplit("/", 1)[1] + ":[234]")
  monkeypatch.setattr(value.time, "sleep", lambda seconds: sleeps.append(seconds))
  return value, path, fds, sleeps


def test_heartbeat_fixed_event_and_600_writes_then_closes(heartbeat, capsys):
  value, path, fds, sleeps = heartbeat
  value.main(NONCE)
  assert json.loads(capsys.readouterr().out) == {"schema_version": 1, "phase": "heartbeat", "nonce": NONCE,
    "pid": 23, "namespaces": {key: key + ":[234]" for key in NS}}
  assert path.read_bytes() == (NONCE + "\n").encode() * 600
  assert sleeps == [0.05] * 600
  with pytest.raises(OSError): os.fstat(fds[0])


@pytest.mark.parametrize("nonce", ["", "A" * 32, "a" * 31, None])
def test_heartbeat_bad_nonce_never_opens(heartbeat, nonce):
  value, _, fds, sleeps = heartbeat
  with pytest.raises(ValueError): value.main(nonce)
  assert fds == [] and sleeps == []


@pytest.mark.parametrize("fault", ["short-write", "write-error", "sleep-error"])
def test_heartbeat_failure_closes_owned_fd(heartbeat, monkeypatch, fault):
  value, _, fds, _ = heartbeat
  def failed(*args): raise OSError(errno.EIO, "private-failure")
  if fault == "short-write": monkeypatch.setattr(value.os, "write", lambda *args: 1)
  elif fault == "write-error": monkeypatch.setattr(value.os, "write", failed)
  else: monkeypatch.setattr(value.time, "sleep", failed)
  with pytest.raises(OSError): value.main(NONCE)
  with pytest.raises(OSError): os.fstat(fds[0])


def test_returning_executor_is_failure_no_retry_and_closes_canary(worker, monkeypatch):
  value, calls, fds, _ = worker; executions = []
  monkeypatch.setattr(value, "exec_prepared", lambda result: executions.append(result))
  with pytest.raises(RuntimeError): value.run("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert len(executions) == 1 and calls[-1] == "cleanup"
  with pytest.raises(OSError) as caught: os.fstat(fds[0])
  assert caught.value.errno == errno.EBADF


@pytest.mark.parametrize("data", [b"1002 1002 1\n", b"x" * 16384])
def test_bootstrap_collects_exact_facts_with_bounded_temporary_uid_map(tmp_path, monkeypatch, data):
  value = load("worker"); value.os = SimpleNamespace(**vars(os))
  uid_map = tmp_path / "uid-map"; uid_map.write_bytes(data)
  monkeypatch.setattr(value.os, "geteuid", lambda: 1002)
  owners = {"/": 1002, "/usr": 65534, "/usr/bin/bash": 65534}
  monkeypatch.setattr(value.os, "stat", lambda path: SimpleNamespace(st_uid=owners[path]))
  monkeypatch.setattr(value.os, "readlink", lambda path: "user:[123]")
  reads = []
  @contextmanager
  def opened(path, mode):
    assert (path, mode) == ("/proc/self/uid_map", "rb")
    with uid_map.open(mode) as stream:
      def read(size): reads.append(size); return stream.read(size)
      yield SimpleNamespace(read=read)
  monkeypatch.setattr(value, "open", opened, raising=False)
  assert value.bootstrap("boundary", NONCE) == {"schema_version": 1, "phase": "bootstrap", "case_id": "boundary", "nonce": NONCE,
    "uid": 1002, "owners": {"root": 1002, "usr": 65534, "bash": 65534}, "user_namespace": "user:[123]", "uid_map": data.decode("ascii")}
  assert reads == [16385]


@pytest.mark.parametrize("data", [b"", b"x" * 16385, b"invalid\xff"])
def test_invalid_bootstrap_uid_map_never_reads_gate(worker, monkeypatch, tmp_path, data):
  value, calls, _, _ = worker
  real = load("worker")
  uid_map = tmp_path / "bad-uid-map"; uid_map.write_bytes(data)
  monkeypatch.setattr(real, "open", lambda path, mode: uid_map.open(mode), raising=False)
  monkeypatch.setattr(value, "bootstrap", real.bootstrap)
  with pytest.raises((ValueError, UnicodeError)): value.run("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert calls == []


def test_bootstrap_precedes_gate_and_invalid_pid_has_no_bootstrap(worker, monkeypatch, capsys):
  value, calls, _, _ = worker
  def gate(fd, size):
    assert json.loads(capsys.readouterr().out)["phase"] == "bootstrap"
    return b""
  monkeypatch.setattr(value.os, "read", gate)
  with pytest.raises(ValueError): value.run("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert calls == []
  monkeypatch.setattr(value.os, "getpid", lambda: 20)
  with pytest.raises(ValueError): value.run("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert capsys.readouterr().out == ""


def test_bootstrap_read_error_has_no_event_or_gate(worker, monkeypatch, capsys):
  value, calls, _, _ = worker; real = load("worker")
  def failed(path, mode): raise OSError(errno.EIO, "synthetic uid-map error")
  monkeypatch.setattr(real, "open", failed, raising=False)
  monkeypatch.setattr(value, "bootstrap", real.bootstrap)
  with pytest.raises(OSError): value.run("boundary", NONCE, HELPER, 17, PLAN, value._test_work_root)
  assert calls == [] and capsys.readouterr().out == ""


@pytest.mark.parametrize("fault", ["fd-bool", "fd-stdio", "digest", "work-relative", "work-root"])
def test_handoff_cli_binding_inputs_refuse_before_bootstrap(worker, capsys, fault):
  value, calls, _, _ = worker
  fd, digest, root = 17, PLAN, value._test_work_root
  if fault == "fd-bool": fd = True
  elif fault == "fd-stdio": fd = 2
  elif fault == "digest": digest = "private-invalid"
  elif fault == "work-relative": root = Path("relative")
  else: root = Path("/")
  with pytest.raises(ValueError): value.run("boundary", NONCE, HELPER, fd, digest, root)
  assert calls == [] and capsys.readouterr().out == ""


def test_worker_adopts_real_parent_prepared_fds_without_child_recompilation(worker, execution_case, monkeypatch, capsys):
  from agentcfg import pi_shell_execution as execution, pi_shell_handoff as handoff
  from test_pi_shell_handoff import binding
  value, _, poison, _ = worker
  monkeypatch.setattr(handoff, "_ADOPT_ATTEMPTED", False)
  with execution.prepare_shell_execution(**execution_case) as original:
    with handoff.handoff_channel() as channel:
      selected = binding(original, execution_case)
      handoff.seal_handoff(channel, original, selected)
      proxy = SimpleNamespace(**vars(os)); original_readlink = os.readlink
      proxy.getpid = lambda: 1
      proxy.readlink = lambda path: "user:[333]" if path == "/proc/self/ns/user" else original_readlink(path)
      monkeypatch.setattr(execution, "os", proxy); monkeypatch.setattr(handoff, "os", proxy)
      monkeypatch.setattr(execution, "_task_ids", lambda: ("1",))
      monkeypatch.setattr(execution, "_FD_EXEC_SUPPORTED", True)
      monkeypatch.setattr(handoff, "local_namespace_identity", lambda: {"platform": "linux", "pid": 1,
        "boot_id": "synthetic-boot", "start_time": "123", "namespace": "pid:[222]", "uid": os.geteuid()})
      monkeypatch.setattr(value, "adopt_handoff", handoff.adopt_handoff)
      monkeypatch.setattr(value, "exec_prepared", execution.exec_prepared)
      def inventory():
        found = []
        for fd in (*[item for item, _ in original.snapshots], *poison):
          try: os.fstat(fd)
          except OSError: continue
          found.append(fd)
        return tuple(found)
      monkeypatch.setattr(execution, "_fd_inventory", inventory)
      monkeypatch.setattr(execution, "pin_mount_plan", lambda *args, **kwargs: pytest.fail("child must not recompile"))
      calls = []
      def fake_exec(fd, argv, env):
        calls.append(fd); assert fd == original.helper_fd and env == {}
        for item in poison:
          with pytest.raises(OSError): os.fstat(item)
        raise OSError("synthetic exec failure, never run")
      monkeypatch.setattr(execution, "_exec_fd", fake_exec)
      with pytest.raises(ConfigError, match="pi-shell-exec-unavailable"):
        value.run("boundary", NONCE, execution_case["helper_identity"], channel, execution_case["plan_digest"], value._test_work_root)
      assert calls == [original.helper_fd]
      messages = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
      assert [item["phase"] for item in messages] == ["bootstrap", "prepared"]
      assert messages[1]["plan_digest"] == execution_case["plan_digest"]


def test_invalid_cli_does_not_echo_argument_values(worker, capsys):
  value, _, _, _ = worker
  with pytest.raises(ValueError): value.main(["--probe-worker", "boundary", "--nonce", NONCE, "--helper-identity", HELPER,
    "--handoff-fd", "private-value", "--plan-digest", PLAN, "--work-root", str(value._test_work_root)])
  captured = capsys.readouterr()
  assert captured.out == "" and captured.err == ""
