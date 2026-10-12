"""准备/来源漂移/闭合oracle；默认仅临时假文件，不执行官方SDK或子进程。"""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import stat

import pytest

from agentcfg import pi_reviewer_sdk_probe as probe
from agentcfg.schema import ConfigError


@pytest.fixture
def materials(tmp_path, monkeypatch):
  root = tmp_path / "repo"; root.mkdir(mode=0o700)
  candidate = root / "candidate"; candidate.mkdir(mode=0o700)
  for name in (*probe.SOURCES, *probe.CONTROLLERS):
    path = root / name; path.parent.mkdir(parents=True, exist_ok=True, mode=0o700); path.write_bytes(b"self-owned source\n")
  (candidate / "package-lock.json").write_bytes(b'{"name":"own-synthetic-lock"}\n')
  for name, version in (("@earendil-works/pi-coding-agent", "1.0.1"), ("@earendil-works/pi-ai", "1.0.2"), ("openai", "7.19.0")):
    directory = candidate / "node_modules" / name; directory.mkdir(parents=True, mode=0o700)
    (directory / "package.json").write_text(json.dumps({"name": name, "version": version}))
  node = root / "node"; (node / "bin").mkdir(parents=True, mode=0o700)
  for path in (node / "bin/node", root / "bwrap", root / "timeout"):
    path.write_bytes(b"own-not-executable-fixture\n"); path.chmod(0o700)
  for key, value in {"ROOT": root, "CANDIDATE": candidate, "NODE": node, "BWRAP": root / "bwrap", "TIMEOUT": root / "timeout",
    "LOCK_SHA": hashlib.sha256((candidate / "package-lock.json").read_bytes()).hexdigest()}.items(): monkeypatch.setattr(probe, key, value)
  return {"root": root, "candidate": candidate, "work": tmp_path / "prepared", "node": node}


def test_prepare_and_preflight_copy_exact_sources_without_process(materials, monkeypatch):
  calls = []; monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
  result = probe.prepare(materials["work"])
  assert result["native_started"] is False and result["product_gate"] is False and result["source_files"] == 9
  assert probe.preflight(materials["work"])["native_started"] is False and calls == []
  assert {p.relative_to(materials["work"] / "bundle").as_posix() for p in (materials["work"] / "bundle").rglob("*") if p.is_file()} == set(probe.SOURCES)
  assert stat.S_IMODE(materials["work"].stat().st_mode) == 0o700
  assert stat.S_IMODE((materials["work"] / "plan.json").stat().st_mode) == 0o600
  assert not (materials["work"] / "started.json").exists()
  with pytest.raises(FileExistsError): probe.prepare(materials["work"])


@pytest.mark.parametrize("fault", ["source", "controller", "candidate", "node", "lock", "version", "extra-bundle-file", "extra-bundle-directory", "bundle-symlink", "bundle-mode", "work-secret", "work-dir-mode", "started"])
def test_preflight_rejects_drift_before_native(materials, fault, monkeypatch):
  work = materials["work"]; probe.prepare(work)
  if fault == "source": (materials["root"] / probe.SOURCES[0]).write_bytes(b"changed\n")
  if fault == "controller": (materials["root"] / probe.CONTROLLERS[0]).write_bytes(b"changed\n")
  if fault == "candidate": (materials["candidate"] / "new-source.js").write_bytes(b"changed\n")
  if fault == "node": (materials["node"] / "bin/node").write_bytes(b"changed\n")
  if fault == "lock": (materials["candidate"] / "package-lock.json").write_bytes(b"changed\n")
  if fault == "version": (materials["candidate"] / "node_modules/openai/package.json").write_text('{"name":"openai","version":"7.20.0"}')
  if fault == "extra-bundle-file": (work / "bundle/new.js").write_bytes(b"changed\n")
  if fault == "extra-bundle-directory": (work / "bundle/new-empty").mkdir(mode=0o700)
  if fault == "bundle-symlink":
    path = work / "bundle" / probe.SOURCES[0]; path.unlink(); path.symlink_to(materials["root"] / probe.SOURCES[0])
  if fault == "bundle-mode": (work / "bundle" / probe.SOURCES[0]).chmod(0o644)
  if fault == "work-secret": (work / "work/home/auth.json").write_bytes(b"OWN_SECRET_SENTINEL")
  if fault == "work-dir-mode": (work / "work/home").chmod(0o755)
  if fault == "started": (work / "started.json").write_bytes(b"{}")
  calls = []; monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
  with pytest.raises((ConfigError, OSError)): probe.run_native(work)
  assert calls == []


@pytest.mark.parametrize("fault", ["unknown", "version-bool", "environment", "invocation", "case", "duplicate"])
def test_plan_tamper_or_ambiguous_json_rejects(materials, fault):
  work = materials["work"]; probe.prepare(work); path = work / "plan.json"; value = probe.decode(path.read_bytes())
  if fault == "unknown": value["approval"] = True
  if fault == "version-bool": value["schema_version"] = True
  if fault == "environment": value["environment"]["REAL_AUTH"] = "OWN_SENTINEL"
  if fault == "invocation": value["invocation"].append("--allow-network")
  if fault == "case": value["cases"].append("real-model")
  raw = probe.encode(value)
  if fault == "duplicate": raw = raw.replace(b'"probe_id":', b'"probe_id":"other","probe_id":', 1)
  path.write_bytes(raw)
  with pytest.raises(ConfigError): probe.preflight(work)


def test_candidate_internal_link_allowed_but_escape_and_fifo_refused(materials):
  candidate = materials["candidate"]; target = candidate / "own.js"; target.write_bytes(b"self-owned\n")
  link = candidate / "own-link"; link.symlink_to("own.js")
  assert probe.candidate_records()["own-link"]["kind"] == "symlink"
  link.unlink(); link.symlink_to(materials["root"] / probe.SOURCES[0])
  with pytest.raises(ConfigError): probe.candidate_records()
  link.unlink(); os.mkfifo(candidate / "own-fifo", 0o600)
  with pytest.raises(ConfigError): probe.candidate_records()


def test_fixed_invocation_uses_empty_parent_environment_and_only_private_work(materials):
  argv, environment = probe.build_invocation(materials["work"])
  assert environment == {} and argv[0] == str(probe.TIMEOUT)
  assert {"--unshare-all", "--die-with-parent", "--new-session"} <= set(argv)
  assert argv[argv.index("--cap-drop") + 1] == "ALL"
  binds = [(arg, argv[i + 1], argv[i + 2]) for i, arg in enumerate(argv) if arg in ("--bind", "--ro-bind")]
  assert [row for row in binds if row[0] == "--bind"] == [("--bind", str(materials["work"] / "work"), "/work")]
  assert ("--ro-bind", str(probe.CANDIDATE), "/candidate") in binds
  assert ("--ro-bind", str(materials["work"] / "bundle"), "/probe") in binds
  assert not any(target.startswith("/home") for _, _, target in binds)
  assert argv[-2:] == ["/probe/scripts/pi-probe-reviewer-sdk.mjs", "--native-reviewer-sdk-probe"]
  assert "--experimental-import-meta-resolve" in argv
  assert {argv[i + 1]: argv[i + 2] for i, arg in enumerate(argv) if arg == "--setenv"} == probe.ENV


def observed():
  rows = []
  for case in probe.CASES:
    started = case not in ("hard-deny", "human-required"); reported = case in ("allow", "ask", "deny")
    rows.append({"case_id": case, "outcome": "observed", "transport_outcome": {"wrong-model": "transport-failure", "canceled": "canceled", "response-limit": "transport-failure", "hard-deny": "policy-blocked", "human-required": "human-required"}.get(case, "valid"),
      "decision": case if case in ("allow", "ask", "deny") else "allow" if case == "missing-usage" else None,
      "requests": int(started), "usage": {"status": "reported" if reported else "unknown" if started else "not-sent", "input_tokens": 5 if reported else None if started else 0,
        "output_tokens": 3 if reported else None if started else 0, "total_tokens": 8 if reported else None if started else 0}, "worker_started": started, "worker_terminated": started})
  return {"schema_version": 1, "probe_id": probe.PROBE_ID, "status": "observed", "cases": rows, "product_gate": False}


def test_exact_observations_are_accepted_without_product_pass():
  value = observed(); assert probe.verify_result(value) == value


def test_saved_official_review01_node_observations_match_parent_oracle():
  # 仅读取已授权review01的闭合Node输出；不导入SDK，首次父验证失败仍保留。
  fixture = Path(__file__).parent / "fixtures/pi/reviewer-sdk-probe/observed-review01.json"
  value = probe.decode(fixture.read_bytes())
  assert probe.verify_result(value) == value


@pytest.mark.parametrize("fault", ["passed", "product", "unknown", "bool-version", "missing-case", "duplicate-case", "private-error", "ask-allow", "deny-allow", "cancel-refund", "hard-send", "human-worker", "no-termination", "unknown-zero", "usage-bool", "usage-cost", "wrong-model-allow", "blocked-unknown"])
def test_oracle_rejects_false_evidence_and_private_extra_fields(fault):
  value = deepcopy(observed()); rows = {row["case_id"]: row for row in value["cases"]}
  if fault == "passed": value["status"] = "passed"
  if fault == "product": value["product_gate"] = True
  if fault == "unknown": value["credential"] = "OWN_SECRET_SENTINEL"
  if fault == "bool-version": value["schema_version"] = True
  if fault == "missing-case": value["cases"].pop()
  if fault == "duplicate-case": value["cases"][-1] = value["cases"][0]
  if fault == "private-error": rows["allow"]["error"] = "OWN_SECRET_SENTINEL"
  if fault == "ask-allow": rows["ask"]["decision"] = "allow"
  if fault == "deny-allow": rows["deny"]["decision"] = "allow"
  if fault == "cancel-refund": rows["canceled"]["requests"] = 0
  if fault == "hard-send": rows["hard-deny"]["requests"] = 1
  if fault == "human-worker": rows["human-required"]["worker_started"] = True
  if fault == "no-termination": rows["allow"]["worker_terminated"] = False
  if fault == "unknown-zero": rows["missing-usage"]["usage"]["total_tokens"] = 0
  if fault == "usage-bool": rows["allow"]["usage"]["input_tokens"] = True
  if fault == "usage-cost": rows["allow"]["usage"]["cost"] = 0
  if fault == "wrong-model-allow": rows["wrong-model"]["decision"] = "allow"
  if fault == "blocked-unknown": rows["hard-deny"]["usage"] = {"status": "unknown", "input_tokens": None, "output_tokens": None, "total_tokens": None}
  with pytest.raises(ConfigError): probe.verify_result(value)


def test_cli_run_requires_explicit_native_flag(materials, monkeypatch, capsys):
  calls = []; monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
  assert probe.main(["run", "--directory", str(materials["work"])]) == 5
  assert calls == [] and "PI_REVIEWER_SDK_PROBE_FAILED" in capsys.readouterr().out


@pytest.mark.parametrize("fault", [None, "stdout-private", "stdout-bool", "result-unknown", "result-mode", "exit", "capture-limit", "post-source-drift"])
def test_fake_launcher_requires_independent_result_summary_and_post_source_identity(materials, monkeypatch, fault):
  work = materials["work"]; probe.prepare(work); calls = []
  def fake_capture(argv):
    calls.append(argv)
    value = observed()
    if fault == "result-unknown": value["private_error"] = "OWN_SECRET_SENTINEL"
    result = work / "work/reviewer-result.json"; result.write_bytes(probe.encode(value))
    if fault == "result-mode": result.chmod(0o644)
    summary = {"schema_version": 1, "status": "observed", "cases": 9, "product_gate": False}
    if fault == "stdout-bool": summary["schema_version"] = True
    if fault == "post-source-drift": (materials["root"] / probe.SOURCES[0]).write_bytes(b"changed\n")
    output = b"OWN_SECRET_SENTINEL\n" if fault == "stdout-private" else probe.encode(summary)
    return {"exit_code": 5 if fault == "exit" else 0, "stdout_bytes": len(output), "stderr_bytes": 0, "capture_failed": fault == "capture-limit"}, output
  monkeypatch.setattr(probe, "capture", fake_capture)
  if fault is None: assert probe.run_native(work) == observed()
  else:
    with pytest.raises(ConfigError): probe.run_native(work)
  execution = probe.decode((work / "execution.json").read_bytes())
  assert execution["verification"] == ("observed" if fault is None else "failed")
  assert execution["product_gate"] is False and execution["namespace_termination"] == "not-independently-observed"
  assert "OWN_SECRET_SENTINEL" not in json.dumps(execution)
  with pytest.raises(ConfigError): probe.run_native(work)
  assert len(calls) == 1


@pytest.fixture
def fake_capture(monkeypatch):
  """所有危险syscall显式替身，只允许固定假PG和假FD。"""
  from types import SimpleNamespace
  events = []; pending = []; waits = []; running = [True]
  class Pipe:
    def __init__(self, fd): self.fd = fd; self.closed = False
    def fileno(self): return self.fd
    def close(self): self.closed = True; events.append(("close", self.fd))
  process = SimpleNamespace(pid=987654321, stdout=Pipe(901), stderr=Pipe(902))
  def wait(timeout):
    events.append(("wait", timeout))
    value = waits.pop(0) if waits else 0
    if isinstance(value, BaseException): raise value
    running[0] = False
    return value
  process.wait = wait; process.poll = lambda: None if running[0] else 0
  def popen(argv, **kwargs): events.append(("popen", argv, kwargs)); return process
  class Selector:
    def __init__(self): self.mapping = {}
    def __enter__(self): return self
    def __exit__(self, *args): events.append(("selector-close",))
    def register(self, stream, event, name): self.mapping[stream.fd] = SimpleNamespace(fileobj=stream, data=name)
    def unregister(self, stream): del self.mapping[stream.fd]
    def get_map(self): return self.mapping
    def select(self, timeout):
      fd, _ = pending[0]
      return [(self.mapping[fd], probe.selectors.EVENT_READ)]
  def read(fd, size):
    assert size == 8192 and fd in (901, 902)
    selected, value = pending.pop(0); assert selected == fd
    if isinstance(value, BaseException): raise value
    return value
  def killpg(pid, sig):
    assert pid == process.pid
    events.append(("signal", pid, sig))
  monkeypatch.setattr(probe.subprocess, "Popen", popen)
  monkeypatch.setattr(probe.selectors, "DefaultSelector", Selector)
  monkeypatch.setattr(probe.os, "read", read)
  monkeypatch.setattr(probe.os, "set_blocking", lambda fd, value: events.append(("blocking", fd, value)))
  monkeypatch.setattr(probe.os, "killpg", killpg)
  monkeypatch.setattr(probe.time, "monotonic", lambda: 10.0)
  return SimpleNamespace(events=events, pending=pending, waits=waits, process=process)


def test_capture_fixed_launch_and_stderr_is_only_counted(fake_capture):
  f = fake_capture
  f.pending.extend([(901, b"closed-summary\n"), (902, b"PRIVATE_STDERR_SENTINEL"), (901, b""), (902, b"")])
  metadata, output = probe.capture(["own-fake-command"])
  assert f.events[0] == ("popen", ["own-fake-command"], {"env": {}, "cwd": "/tmp", "stdin": probe.subprocess.DEVNULL,
    "stdout": probe.subprocess.PIPE, "stderr": probe.subprocess.PIPE, "close_fds": True, "start_new_session": True})
  assert output == b"closed-summary\n" and metadata == {"exit_code": 0, "stdout_bytes": len(output), "stderr_bytes": 23, "capture_failed": False}
  assert "PRIVATE" not in repr(metadata) and b"PRIVATE" not in output
  assert [("blocking", 901, False), ("blocking", 902, False)] == f.events[1:3]
  assert f.process.stdout.closed and f.process.stderr.closed
  assert not any(event[0] == "signal" for event in f.events)


@pytest.mark.parametrize("fd", [901, 902])
@pytest.mark.parametrize("needs_kill", [False, True])
def test_capture_flood_term_bounded_wait_then_optional_kill(fake_capture, fd, needs_kill):
  f = fake_capture
  f.pending.extend((fd, b"x" * 8192) for _ in range(9))
  f.waits.extend([probe.subprocess.TimeoutExpired("own-fake", 5), 137] if needs_kill else [143, 143])
  metadata, output = probe.capture(["own-fake"])
  assert metadata["capture_failed"] is True and metadata["exit_code"] != 0
  assert metadata["stdout_bytes" if fd == 901 else "stderr_bytes"] == 73728
  assert len(output) == (65536 if fd == 901 else 0)
  controls = [event for event in f.events if event[0] in ("signal", "wait")]
  expected = [("signal", f.process.pid, probe.signal.SIGTERM), ("wait", 5)]
  if needs_kill: expected.append(("signal", f.process.pid, probe.signal.SIGKILL))
  assert controls == expected + [("wait", 5)]
  assert f.process.stdout.closed and f.process.stderr.closed


def test_capture_exact_stdout_limit_is_retained(fake_capture):
  f = fake_capture
  f.pending.extend((901, b"x" * 8192) for _ in range(8))
  f.pending.extend([(901, b""), (902, b"")])
  metadata, output = probe.capture(["own-fake"])
  assert len(output) == 65536 and metadata["capture_failed"] is False
  assert f.process.stdout.closed and f.process.stderr.closed


def test_capture_read_exception_cleans_only_own_fake_process_group(fake_capture):
  f = fake_capture; fault = OSError("OWN_PRIVATE_READ_FAILURE")
  f.pending.append((901, fault)); f.waits.append(137)
  with pytest.raises(OSError) as error: probe.capture(["own-fake"])
  assert error.value is fault
  assert [event for event in f.events if event[0] in ("signal", "wait")] == [("signal", f.process.pid, probe.signal.SIGKILL), ("wait", 5)]
  assert f.process.stdout.closed and f.process.stderr.closed


def test_capture_final_kill_wait_timeout_still_closes_both_pipes(fake_capture):
  f = fake_capture
  f.pending.append((901, OSError("OWN_READ_FAILURE")))
  f.waits.append(probe.subprocess.TimeoutExpired("own-fake", 5))
  with pytest.raises(probe.subprocess.TimeoutExpired): probe.capture(["own-fake"])
  assert [("signal", f.process.pid, probe.signal.SIGKILL), ("wait", 5)] == [event for event in f.events if event[0] in ("signal", "wait")]
  assert f.process.stdout.closed and f.process.stderr.closed


@pytest.mark.parametrize("fault", ["set-blocking", "register"])
def test_capture_initialization_exception_cleans_own_group_and_pipes(fake_capture, monkeypatch, fault):
  f = fake_capture; error = OSError("OWN_PRIVATE_SETUP_FAILURE")
  if fault == "set-blocking":
    def fail_blocking(fd, blocking):
      assert fd in (901, 902) and blocking is False
      raise error
    monkeypatch.setattr(probe.os, "set_blocking", fail_blocking)
  else:
    original = probe.selectors.DefaultSelector
    def broken_selector():
      selector = original()
      def fail_register(*args): raise error
      selector.register = fail_register
      return selector
    monkeypatch.setattr(probe.selectors, "DefaultSelector", broken_selector)
  with pytest.raises(OSError) as raised: probe.capture(["own-fake"])
  assert raised.value is error
  assert [("signal", f.process.pid, probe.signal.SIGKILL), ("wait", 5)] == [event for event in f.events if event[0] in ("signal", "wait")]
  assert f.process.stdout.closed and f.process.stderr.closed


def test_capture_exception_records_closed_unknown_execution_and_blocks_replay(materials, monkeypatch):
  work = materials["work"]; probe.prepare(work); calls = []
  def failed_capture(argv):
    calls.append(argv)
    raise OSError("PRIVATE_CAPTURE_EXCEPTION_SENTINEL")
  monkeypatch.setattr(probe, "capture", failed_capture)
  with pytest.raises(ConfigError): probe.run_native(work)
  execution = probe.decode((work / "execution.json").read_bytes())
  assert execution == {"probe_id": probe.PROBE_ID, "verification": "failed", "native_started": None, "exit_code": None,
    "stdout_bytes": None, "stderr_bytes": None, "capture_failed": True, "product_gate": False,
    "namespace_termination": "not-independently-observed", "failure_code": "PI_REVIEWER_SDK_PROBE_CAPTURE_FAILED"}
  assert "PRIVATE_CAPTURE_EXCEPTION_SENTINEL" not in json.dumps(execution)
  assert probe.decode((work / "started.json").read_bytes()) == {"schema_version": 1, "probe_id": probe.PROBE_ID, "native_launch_requested": True}
  with pytest.raises(ConfigError): probe.run_native(work)
  assert len(calls) == 1
