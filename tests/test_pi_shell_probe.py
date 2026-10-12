"""探针准备和父流程故障注入；不启动任何进程或真实隔离后端。"""

from contextlib import contextmanager
import io
import os
from types import SimpleNamespace

import pytest

from agentcfg import pi_shell_probe as probe
from agentcfg.pi_runtime_files import lock_files
from agentcfg.schema import ConfigError


NONCE = "a" * 32
HELPER = "b" * 64
PLAN_DIGEST = "c" * 64


@pytest.fixture
def prepared(tmp_path, monkeypatch):
  repository = tmp_path / "repository"; repository.mkdir(mode=0o700)
  (repository / "src/agentcfg").mkdir(parents=True)
  source = repository / "src/agentcfg/example.py"; source.write_text("VALUE = 1\n")
  monkeypatch.setattr(probe, "ROOT", repository)
  monkeypatch.setattr(probe, "CONTROLLERS", ("src/agentcfg/example.py",))
  rows = lock_files(repository, [{"source": "src/agentcfg/example.py", "path": "supervisor/src/agentcfg/example.py", "transform": "copy"}])
  monkeypatch.setattr(probe, "sources", lambda: (b"synthetic-helper-never-executed", rows))
  monkeypatch.setattr(probe, "file_identity", lambda path: {"path": str(path), "sha256": "c" * 64, "device": 1, "inode": 2})
  monkeypatch.setattr(probe, "dependencies", lambda: {"path": "/synthetic-python-deps", "device": 1, "inode": 3})
  directory = tmp_path / "bundle"
  plan = probe.prepare(directory)
  return directory, plan


def test_prepare_only_creates_fixed_private_bundle_and_preflight_accepts(prepared):
  directory, plan = prepared
  assert probe.preflight(directory) == plan
  assert not (directory / "execution-started.json").exists()
  assert (directory / "inputs/helper").stat().st_mode & 0o777 == 0o700
  assert set(plan["nonces"]) == set(probe.CASES)
  for case in probe.CASES:
    work = directory / "cases" / case / "work"
    assert (work / "home").is_dir()
    assert not (work / "project/positive").exists()
    for name, value in probe.CANARIES.items(): assert (work / name).read_bytes() == value


@pytest.mark.parametrize("fault", ["extra-file", "extra-dir", "forged-file", "forged-dir", "symlink", "mode", "helper", "source", "passwd", "group", "canary", "payload", "nonce", "unknown", "bool-version", "replay"])
def test_preflight_rejects_tampering_before_any_launch(prepared, fault):
  directory, plan = prepared
  if fault == "extra-file": (directory / "extra").write_text("x")
  if fault == "extra-dir": (directory / "extra").mkdir(mode=0o700)
  if fault == "forged-file":
    (directory / "inputs/extra").write_text("x"); (directory / "inputs/extra").chmod(0o600)
  if fault == "forged-dir": (directory / "inputs/extra").mkdir(mode=0o700)
  if fault == "symlink": (directory / "link").symlink_to(directory / "inputs/helper")
  if fault == "mode": (directory / "inputs/worker.py").chmod(0o644)
  if fault == "helper": (directory / "inputs/helper").write_bytes(b"changed")
  if fault == "source": (directory / "inputs/supervisor/src/agentcfg/example.py").write_text("VALUE = 2\n")
  if fault == "passwd": (directory / "inputs/passwd").write_text("real-account\n")
  if fault == "group": (directory / "inputs/group").write_text("real-group\n")
  if fault == "canary": (directory / "cases/boundary/work/outside/canary").write_text("changed")
  if fault == "payload": (directory / "cases/boundary/work/readonly/payload.py").write_text("changed")
  if fault == "nonce": plan["nonces"]["boundary"] = "$(never)"
  if fault == "unknown": plan["allow"] = True
  if fault == "bool-version": plan["schema_version"] = True
  if fault == "replay": (directory / "execution-started.json").write_text("{}")
  # 即使重写包内清单，固定源和canary的独立校验也必须拒绝。
  if fault in ("source", "helper", "passwd", "group", "canary", "payload", "forged-file", "forged-dir"):
    plan["files"], plan["directories"] = probe.inventory(directory)
  (directory / "plan.json").write_bytes(probe.json_bytes(plan))
  with pytest.raises(Exception): probe.preflight(directory)


def test_prepare_refuses_existing_directory(prepared):
  directory, plan = prepared
  with pytest.raises(ConfigError): probe.prepare(directory)
  assert probe.preflight(directory) == plan


def test_file_identity_reads_regular_file_and_rejects_links_permissions_and_fifo(tmp_path):
  path = tmp_path / "source"; path.write_bytes(b"fixed")
  assert probe.file_identity(path)["sha256"] == probe.sha(b"fixed")
  path.chmod(0o666)
  with pytest.raises(ConfigError): probe.file_identity(path)
  path.chmod(0o600)
  link = tmp_path / "link"; link.symlink_to(path)
  with pytest.raises(OSError): probe.file_identity(link)
  hard = tmp_path / "hard"; os.link(path, hard)
  with pytest.raises(ConfigError): probe.file_identity(path)
  fifo = tmp_path / "fifo"; os.mkfifo(fifo, 0o600)
  with pytest.raises(ConfigError): probe.file_identity(fifo)


@pytest.mark.parametrize("case", probe.CASES)
def test_invocation_has_only_synthetic_work_writable_and_no_inherited_environment(prepared, case):
  directory, plan = prepared
  argv, env = probe.invocation(directory, plan, case, 123, 124, PLAN_DIGEST)
  assert env == {}
  assert argv[0] == "/usr/bin/bwrap" and "--as-pid-1" in argv and "--unshare-all" in argv
  assert argv[argv.index("--info-fd") + 1] == "123"
  assert "--gate-fd" not in argv
  assert [argv[i + 1:i + 3] for i, word in enumerate(argv) if word == "--bind"] == [[str(directory / "cases" / case / "work")] * 2]
  assert "--cap-drop" in argv and "--die-with-parent" in argv and "--new-session" in argv
  assert argv[-12:-6] == ["--probe-worker", case, "--nonce", plan["nonces"][case], "--helper-identity", plan["helper_identity"]]
  assert argv[-6:] == ["--handoff-fd", "124", "--plan-digest", PLAN_DIGEST, "--work-root", str(directory / "cases" / case / "work")]


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'NaN', b'Infinity', b'\xff', b'{broken'])
def test_decode_rejects_ambiguous_input(raw):
  with pytest.raises(ConfigError): probe.decode(raw)


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
  directory = tmp_path / "run"; directory.mkdir(mode=0o700)
  case = "boundary"; root = directory / "cases" / case / "work"
  with probe.Tree(directory) as tree:
    for name, value in probe.CANARIES.items(): tree.write_new("cases/" + case + "/work/" + name, value)
    tree.write_new("cases/" + case + "/work/project/positive", (NONCE + "\n").encode())
  state = SimpleNamespace(directory=directory, root=root, calls=[], fault=None, gate=None, status="terminated", process=None)
  class Process:
    pid = 123
    def __init__(self):
      self.stdout, self.stderr = io.BytesIO(), io.BytesIO(); self.returncode = 0
    def poll(self): return self.returncode
    def wait(self, timeout):
      state.calls.append("wait")
      if state.fault in ("wait-timeout", "kill-fail") and self.returncode is None:
        raise probe.subprocess.TimeoutExpired("synthetic", timeout)
      return self.returncode
    def kill(self):
      state.calls.append("kill")
      if state.fault == "kill-fail": raise OSError()
      self.returncode = -9
  def popen(argv, **kwargs):
    state.calls.append("popen")
    assert kwargs["env"] == {} and kwargs["shell"] is False and kwargs["close_fds"] and kwargs["start_new_session"]
    assert kwargs["stdin"] not in kwargs["pass_fds"] and len(kwargs["pass_fds"]) == 4
    if state.fault == "launch": raise OSError()
    state.gate = os.dup(kwargs["stdin"])
    state.process = Process()
    return state.process
  class Processes:
    def __init__(self, record_root): state.record = record_root
    def identity(self, pid):
      state.calls.append("identity")
      assert "bootstrap" in state.calls
      if state.fault == "identity": raise OSError()
      return {"pid": pid, "namespace": "pid:[42]"}
    def register_namespace(self, leader, wrapper):
      state.calls.append("register")
      state.record.mkdir(parents=True, mode=0o700)
      (state.record / "retained").write_text("identity record")
      if state.fault == "register": raise OSError()
    def termination_status(self, leader):
      state.calls.append("status")
      if state.fault == "status-error": raise OSError()
      return state.status
    def stop(self, leader, **kwargs):
      state.calls.append("stop")
      if state.fault == "stop-error": raise OSError()
      state.status = "terminated"
  def info(fd):
    if state.fault == "info": raise OSError()
    return {"child-pid": 456, "pid-namespace": 42}
  def collect(*args):
    state.calls.append("collect")
    assert "seal" in state.calls and "register" in state.calls and os.read(state.gate, 2) == b"G"
    if state.fault == "interrupt": raise KeyboardInterrupt()
    if state.fault in ("observe", "stop-error", "wait-timeout", "kill-fail"):
      if state.fault in ("wait-timeout", "kill-fail"): state.process.returncode = None
      raise ConfigError("synthetic")
    return [{"synthetic": True}], 0, 0
  def verify(case, nonce, events, facts):
    state.calls.append("verify")
    if state.fault == "verify": raise ConfigError("synthetic")
    assert facts["positive"] and facts["canaries_unchanged"] and facts["blocked_files_absent"] and facts["terminated"]
    assert facts["heartbeat_before"] == facts["heartbeat_after"] == 0
    return {"case_id": case, "outcome": "observed"}
  monkeypatch.setattr(probe.subprocess, "Popen", popen)
  monkeypatch.setattr(probe, "LinuxProcesses", Processes)
  monkeypatch.setattr(probe, "read_namespace_info", info)
  def bootstrap(*args):
    state.calls.append("bootstrap")
    if state.fault == "bootstrap": raise ConfigError("synthetic")
    return {"synthetic": True}
  monkeypatch.setattr(probe, "read_bootstrap", bootstrap)
  @contextmanager
  def preparation(*args):
    state.calls.append("prepare")
    if state.fault == "prepare": raise ConfigError("synthetic")
    try: yield SimpleNamespace(helper_fd=234, pass_fds=(235,)), PLAN_DIGEST
    finally: state.calls.append("release-fds")
  def binding(*args, **kwargs):
    state.calls.append("binding")
    if state.fault == "identity-map": raise ConfigError("synthetic")
    return {"synthetic": True}, {"synthetic": True}
  def seal(*args):
    state.calls.append("seal")
    if state.fault == "handoff": raise ConfigError("synthetic")
  monkeypatch.setattr(probe, "prepare_execution", preparation)
  monkeypatch.setattr(probe, "bind_worker", binding)
  monkeypatch.setattr(probe, "seal_handoff", seal)
  monkeypatch.setattr(probe, "collect", collect)
  monkeypatch.setattr(probe, "verify_case", verify)
  state.plan = {"nonces": {case: NONCE}, "helper_identity": HELPER, "system": {"dependencies": {"path": "/synthetic"}}}
  yield state
  if state.gate is not None: os.close(state.gate)


def test_parent_registers_before_gate_and_records_only_checked_facts(lifecycle):
  state = lifecycle
  result = probe.run_case(state.directory, state.plan, "boundary")
  assert result["outcome"] == "observed" and result["registered"]
  assert state.calls.index("bootstrap") < state.calls.index("identity") < state.calls.index("register") < state.calls.index("binding") < state.calls.index("seal") < state.calls.index("collect") < state.calls.index("verify")
  assert state.calls[-1] == "release-fds"
  assert state.process.stdout.closed and state.process.stderr.closed
  assert os.read(state.gate, 1) == b""


@pytest.mark.parametrize("fault,expected", [("prepare", "unavailable"), ("handoff", "unavailable"), ("launch", "unavailable"), ("info", "unavailable"), ("identity", "unavailable"),
  ("bootstrap", "unavailable"), ("identity-map", "unavailable"),
  ("register", "termination-unknown"), ("observe", "unavailable"), ("verify", "failed"), ("interrupt", "interrupted"),
  ("stop-error", "termination-unknown"), ("status-error", "termination-unknown"), ("wait-timeout", "unavailable"), ("kill-fail", "termination-unknown")])
def test_faults_close_gate_keep_records_and_never_claim_observed(lifecycle, fault, expected):
  state = lifecycle; state.fault = fault
  if fault == "stop-error": state.status = "unknown"
  result = probe.run_case(state.directory, state.plan, "boundary")
  assert result["outcome"] == expected and result["summary"] is None
  if state.gate is not None:
    # register之前失败只给EOF；collect已经消耗成功路径的G。
    assert os.read(state.gate, 2) == b""
    assert state.process.stdout.closed and state.process.stderr.closed
  if fault in ("info", "identity", "register"): assert "collect" not in state.calls and "stop" not in state.calls
  if fault in ("bootstrap", "identity-map"): assert "collect" not in state.calls and result["stage"] == fault
  if fault == "register": assert (state.record / "retained").exists()
  if fault in ("wait-timeout", "kill-fail"): assert "kill" in state.calls


def test_second_pipe_failure_closes_first_pair(lifecycle, monkeypatch):
  original = os.pipe; descriptors = []
  def pipe():
    if descriptors: raise OSError()
    descriptors.extend(original()); return tuple(descriptors)
  monkeypatch.setattr(probe.os, "pipe", pipe)
  assert probe.run_case(lifecycle.directory, lifecycle.plan, "boundary")["outcome"] == "unavailable"
  for fd in descriptors:
    with pytest.raises(OSError): os.fstat(fd)
  assert "popen" not in lifecycle.calls


@pytest.mark.parametrize("outcomes", [("observed", "observed", "observed"), ("failed",), ("observed", "unavailable")])
def test_native_run_requires_preflight_and_stops_at_first_failure(prepared, monkeypatch, outcomes):
  directory, plan = prepared; calls = []
  def run(root, checked, case):
    assert (root / "execution-started.json").exists() and checked == plan
    calls.append(case)
    return {"case_id": case, "outcome": outcomes[len(calls) - 1]}
  monkeypatch.setattr(probe, "run_case", run)
  result = probe.run_native(directory)
  assert calls == list(probe.CASES[:len(outcomes)])
  assert result["status"] == ("observed" if len(outcomes) == 3 else "failed") and result["product_gate"] is False
  with pytest.raises(ConfigError): probe.run_native(directory)


@pytest.mark.parametrize("args", [[], ["--directory", "/synthetic"], ["--run", "--directory", "/synthetic"],
  ["--prepare", "--run-native-shell-probe", "--directory", "/synthetic"]])
def test_cli_cannot_implicitly_select_native_mode(args, monkeypatch):
  monkeypatch.setattr(probe, "run_native", lambda *_: pytest.fail("native called"))
  monkeypatch.setattr(probe, "prepare", lambda *_: pytest.fail("prepare called"))
  assert probe.main(args) == 5


@pytest.fixture
def output_process():
  streams = []
  def make(stdout, stderr=b""):
    pairs = []
    for body in (stdout, stderr):
      read, write = os.pipe()
      try: os.write(write, body)
      finally: os.close(write)
      stream = os.fdopen(read, "rb", buffering=0); streams.append(stream); pairs.append(stream)
    return SimpleNamespace(stdout=pairs[0], stderr=pairs[1], wait=lambda **_: 0)
  yield make
  for stream in streams: stream.close()


def test_collect_reads_bounded_json_lines(output_process, tmp_path):
  process = output_process(b'{"phase":"prepared"}\n{"phase":"payload"}\n')
  events, before, elapsed = probe.collect(process, None, None, tmp_path, "boundary", NONCE, probe.time.monotonic())
  assert events == [{"phase": "prepared"}, {"phase": "payload"}] and before == elapsed == 0


def test_stderr_failure_is_not_hidden_by_success_events(output_process, tmp_path):
  with pytest.raises(ConfigError):
    probe.collect(output_process(b'{}\n', b'fixed failure'), None, None, tmp_path, "boundary", NONCE, probe.time.monotonic())


@pytest.mark.parametrize("body", [b'{}', b'\n', b'[]\n', b'{"x":1,"x":2}\n', b'{}\n' * 5, b'\xff\n'])
def test_collect_rejects_bad_output(output_process, tmp_path, body):
  with pytest.raises(ConfigError): probe.collect(output_process(body), None, None, tmp_path, "boundary", NONCE, probe.time.monotonic())


def test_collect_limits_combined_stdout_stderr(output_process, tmp_path, monkeypatch):
  monkeypatch.setattr(probe, "MAX_BYTES", 16)
  with pytest.raises(ConfigError): probe.collect(output_process(b'{}\n', b'x' * 17), None, None, tmp_path, "boundary", NONCE, probe.time.monotonic())


def test_collect_times_out_without_treating_eof_as_proof(output_process, tmp_path, monkeypatch):
  ticks = iter((probe.CASE_SECONDS + 1,))
  monkeypatch.setattr(probe.time, "monotonic", lambda: next(ticks))
  with pytest.raises(ConfigError): probe.collect(output_process(b''), None, None, tmp_path, "boundary", NONCE, 0)


def test_descendant_stop_requires_active_heartbeat_then_samples_after_stop(output_process, tmp_path):
  root = tmp_path / "work"; root.mkdir(mode=0o700)
  with probe.Tree(root) as tree: tree.write_new("project/heartbeat", (NONCE + "\n").encode())
  calls = []
  def stop(leader, **kwargs):
    calls.append(leader)
    # 模拟stop确认前的最后一次写入，稳定性基线应包含它。
    with (root / "project/heartbeat").open("ab") as stream: stream.write((NONCE + "\n").encode())
  process = output_process(b'{"phase":"prepared"}\n{"phase":"heartbeat"}\n{"phase":"payload"}\n')
  events, before, elapsed = probe.collect(process, SimpleNamespace(stop=stop), {"pid": 123}, root, "descendants", NONCE, probe.time.monotonic())
  assert before == 2 and calls == [{"pid": 123}] and len(events) == 3 and 0 <= elapsed < 10000


@pytest.mark.parametrize("late", ["before-stop", "after-stop"])
def test_natural_heartbeat_expiry_cannot_be_recorded_as_active_stop(output_process, tmp_path, monkeypatch, late):
  with probe.Tree(tmp_path) as tree: tree.write_new("project/heartbeat", (NONCE + "\n").encode())
  ticks = iter((0, 10) if late == "before-stop" else (0, 1, 10))
  monkeypatch.setattr(probe.time, "monotonic", lambda: next(ticks))
  calls = []
  process = output_process(b'{"phase":"heartbeat"}\n{"phase":"payload"}\n')
  with pytest.raises(ConfigError):
    probe.collect(process, SimpleNamespace(stop=lambda *args, **kwargs: calls.append("stop")), {}, tmp_path, "descendants", NONCE, 0)
  assert calls == ([] if late == "before-stop" else ["stop"])


@pytest.mark.parametrize("body", [b'', b'bad', ("d" * 32 + "\n").encode()])
def test_heartbeat_rejects_wrong_empty_or_partial_record(tmp_path, body):
  with probe.Tree(tmp_path) as tree: tree.write_new("project/heartbeat", body)
  with pytest.raises(ConfigError): probe.heartbeat(tmp_path, NONCE)


def bootstrap_value():
  return {"schema_version": 1, "phase": "bootstrap", "case_id": "boundary", "nonce": NONCE,
    "uid": os.geteuid(), "owners": {"root": os.geteuid(), "usr": 0, "bash": 0},
    "user_namespace": "user:[123]", "uid_map": "0 0 4294967295\n"}


def test_bootstrap_identity_mapping_has_independent_closed_handshake(output_process):
  expected = bootstrap_value()
  process = output_process(probe.json_bytes(expected))
  value = probe.read_bootstrap(process.stdout, "boundary", NONCE)
  assert value == expected


@pytest.mark.parametrize("fault", ["unknown", "nonce", "case", "uid", "owner", "owners", "userns", "version", "phase", "mapping-type", "mapping-size"])
def test_bad_bootstrap_never_gets_gate_permission(output_process, fault):
  value = bootstrap_value()
  if fault == "unknown": value["allow"] = True
  if fault == "nonce": value["nonce"] = "b" * 32
  if fault == "case": value["case_id"] = "descendants"
  if fault == "uid": value["uid"] = True
  if fault == "owner": value["owners"]["bash"] = -1
  if fault == "owners": value["owners"]["extra"] = 0
  if fault == "userns": value["user_namespace"] = "pid:[123]"
  if fault == "version": value["schema_version"] = True
  if fault == "phase": value["phase"] = "prepared"
  if fault == "mapping-type": value["uid_map"] = []
  if fault == "mapping-size": value["uid_map"] = ""
  with pytest.raises(ConfigError): probe.read_bootstrap(output_process(probe.json_bytes(value)).stdout, "boundary", NONCE)


@pytest.mark.parametrize("body", [b'', b'{}', b'{}\n{}\n', b'{"x":1,"x":2}\n', b'\xff\n'])
def test_bootstrap_requires_one_complete_frame(output_process, body):
  with pytest.raises(ConfigError): probe.read_bootstrap(output_process(body).stdout, "boundary", NONCE)


def test_bootstrap_timeout_is_bounded(output_process, monkeypatch):
  ticks = iter((0, 10))
  monkeypatch.setattr(probe.time, "monotonic", lambda: next(ticks))
  with pytest.raises(ConfigError): probe.read_bootstrap(output_process(b'').stdout, "boundary", NONCE)
