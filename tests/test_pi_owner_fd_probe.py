"""小自有 bundle、假 Popen/proc/pidfd/flock；绝不执行 guest/native。"""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT = Path(__file__).resolve().parents[1]


@pytest.fixture
def probe(tmp_path, monkeypatch):
  spec = importlib.util.spec_from_file_location("own_fd_probe", PROJECT / "scripts/pi-probe-owner-fd.py")
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  bundle = tmp_path / "bundle"
  for name in module.SOURCES:
    target = bundle / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes((PROJECT / name).read_bytes())
  monkeypatch.setattr(module, "ROOT", bundle); monkeypatch.setattr(module, "FIXTURE", bundle / "tests/fixtures/pi/owner-fd-probe")
  monkeypatch.setattr(module, "system", lambda: {"synthetic": "small-static-system"})
  module._test_original_guest_driver = module.guest_driver
  monkeypatch.setattr(module, "guest_driver", lambda *a: pytest.fail("guest driver forbidden"))
  monkeypatch.setattr(module, "guest_controller", lambda *a: pytest.fail("guest controller forbidden"))
  return module


@pytest.fixture
def directory(tmp_path):
  value = tmp_path / "plan"; value.mkdir(mode=0o700); return value


def fixture_frame(probe, case):
  expected = json.loads((probe.FIXTURE / "oracle.json").read_text())["cases"][case]
  def identity(pid, exe): return {"pid": pid, "start": "91", "uid": os.geteuid(), "namespace": "pid:[100]", "exe": exe}
  entry = {"schema": 1, "kind": "entry", "flags": "2000002" if expected["entry"]["accepted"] else None, **expected["entry"]}
  return {"schema": 1, "case": case, "driver": identity(2, str(probe.PYTHON)), "controller": identity(3, str(probe.PYTHON)),
    "node": identity(4, "/node"), "lock": {"device": "0", "inode": "1", "uid": os.geteuid(), "mode": 0o600, "nlink": 1}, "entry": entry,
    **{key: copy.deepcopy(expected[key]) for key in ("nodeLaunches", "cuts", "controllerExitCode", "nodeExitCode")}}


def fake_work(probe, work, case, value):
  lock = work / "lock-state/instance.lock"; lock.write_bytes(b""); lock.chmod(0o600)
  value["lock"] = probe.binding(lock.stat())
  for name, item in {"state.json": value, "node-entry.json": value["entry"],
    "controller-info.json": {"schema": 1, "nodePid": value["node"]["pid"], "nodeLaunches": value["nodeLaunches"], "lock": value["lock"]}}.items(): probe.write(work / name, item)
  probe.write_bytes(work / "node.stdout", probe.raw_json(value["entry"])); probe.write_bytes(work / "node.stderr", b"")
  if case not in ("controller-exit", "controller-kill"):
    probe.write(work / "controller-result.json", {"schema": 1, "nodeExitCode": value["nodeExitCode"]})
  if case != "node-kill": probe.write_bytes(work / "node-command", b"exit\n")
  if case != "controller-kill": probe.write_bytes(work / "controller-command", b"exit\n")


@pytest.fixture
def fake_launch(probe, monkeypatch):
  calls, virtual = [], {}; original_read = os.read
  options = {"mutate": None, "output": None, "errors": b"", "returncode": 0, "never_exit": False, "after": None}
  class Stream(io.BytesIO):
    def __init__(self, raw): super().__init__(raw); self.number = 50000 + len(virtual); virtual[self.number] = self
    def fileno(self): return self.number
  class Process:
    def __init__(self, argv, **kwargs):
      calls.append((argv, kwargs)); self.pid = 200 + len(calls); self.returncode = None
      case = argv[-1]; work = Path(kwargs["cwd"]) / "work"; value = fixture_frame(probe, case)
      fake_work(probe, work, case, value)
      if options["mutate"]: options["mutate"](value, work)
      raw = options["output"] if options["output"] is not None else probe.raw_json(value)
      self.stdout, self.stderr = Stream(raw), Stream(options["errors"])
      if options["after"]: options["after"]()
    def wait(self, timeout=None):
      if options["never_exit"]: raise probe.subprocess.TimeoutExpired("synthetic", timeout)
      self.returncode = options["returncode"]; return self.returncode
    def poll(self): return self.returncode
  class Selector:
    def __init__(self): self.items = {}
    def __enter__(self): return self
    def __exit__(self, *exc): pass
    def register(self, stream, event, name): self.items[stream.fileno()] = SimpleNamespace(fileobj=stream, data=name)
    def unregister(self, stream): del self.items[stream.fileno()]
    def get_map(self): return self.items
    def select(self, timeout): return [(item, 1) for item in tuple(self.items.values())]
  monkeypatch.setattr(probe.subprocess, "Popen", Process)
  monkeypatch.setattr(probe.selectors, "DefaultSelector", Selector)
  monkeypatch.setattr(os, "read", lambda fd, maximum: virtual[fd].read(maximum) if fd in virtual else original_read(fd, maximum))
  monkeypatch.setattr(os, "killpg", lambda *args: None)
  return calls, options


def test_prepare_is_small_closed_material_with_zero_launch(probe, directory):
  value = probe.prepare(directory)
  assert value["nativeAuthorized"] is False and value["nativeStarted"] is False
  assert set(value["material"]["sources"]) == set(probe.SOURCES)
  assert {p.name for p in directory.iterdir()} == {"plan.json"}
  for item in value["invocations"].values():
    assert item["env"] == {} and "--clearenv" not in item["argv"]
    assert "--unshare-all" in item["argv"] and "--remount-ro" in item["argv"]
    assert item["argv"][-7:-4] == ["-I", "-S", "-B"]
    assert not any(name in item["argv"] for name in ("/durable", "/candidate", "/node_modules"))
  with pytest.raises(probe.ProbeError): probe.prepare(directory)


@pytest.mark.parametrize("change", ["source", "manifest", "plan-unknown", "environment", "argument", "symlink-source"])
def test_drift_before_started_never_launches(probe, directory, fake_launch, change):
  probe.prepare(directory)
  if change == "source": (probe.ROOT / probe.SOURCES[0]).write_bytes(b"changed")
  elif change == "manifest": (probe.FIXTURE / "manifest.json").write_bytes(b"{}")
  elif change == "symlink-source":
    path = probe.ROOT / probe.SOURCES[0]; path.unlink(); path.symlink_to(probe.ROOT / probe.SOURCES[1])
  else:
    value = probe.decode(probe.read(directory / "plan.json", probe.MAX_PLAN))
    if change == "plan-unknown": value["unknown"] = True
    elif change == "environment": value["invocations"][probe.CASES[0]]["env"] = {"NODE_OPTIONS": "secret"}
    else: value["invocations"][probe.CASES[0]]["argv"].append("unknown")
    (directory / "plan.json").write_bytes(probe.raw_json(value))
  with pytest.raises((probe.ProbeError, OSError)): probe.run(directory)
  assert not fake_launch[0] and not (directory / "started.json").exists()


@pytest.mark.parametrize("case", ["entry-and-node-exit", "controller-exit", "controller-kill", "node-kill", "wrong-fd", "high-fd-rejected"])
def test_six_fixture_frames_have_independent_strict_oracle(probe, case):
  value = fixture_frame(probe, case); assert probe.oracle(case, value, 0) is value
  bad = copy.deepcopy(value); bad["cuts"][-1]["lock"] = "busy"
  with pytest.raises(probe.ProbeError): probe.oracle(case, bad, 0)


@pytest.mark.parametrize("change", ["bool-schema", "launches", "missing-cut", "wrong-physical", "uid", "birth", "namespace", "controller-pid1", "descendant", "flag", "negative-accepted", "exit", "entry-extra"])
def test_bad_fact_never_matches_oracle(probe, change):
  case = "wrong-fd" if change == "negative-accepted" else "entry-and-node-exit"; value = fixture_frame(probe, case)
  if change == "bool-schema": value["schema"] = True
  elif change == "launches": value["nodeLaunches"] = 2
  elif change == "missing-cut": value["cuts"].pop()
  elif change == "wrong-physical": value["lock"]["inode"] = "0"
  elif change == "uid": value["lock"]["uid"] += 1
  elif change == "birth": value["node"]["start"] = "secret"
  elif change == "namespace": value["node"]["namespace"] = "pid:[200]"
  elif change == "controller-pid1": value["controller"]["pid"] = 1
  elif change == "descendant": value["entry"]["descendantMatches"] = 1
  elif change == "flag": value["entry"]["flags"] = "2"
  elif change == "negative-accepted": value["entry"]["accepted"] = True
  elif change == "exit": value["nodeExitCode"] = -9
  else: value["entry"]["secret"] = "SYNTHETIC_SECRET"
  with pytest.raises(probe.ProbeError): probe.oracle(case, value, 0)


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":1}', b'{"a":NaN}', b'\xff', b'[]', b'{'])
def test_duplicate_nonfinite_invalid_frames(probe, raw):
  with pytest.raises(probe.ProbeError): probe.decode(raw)


def test_one_round_records_all_synthetic_started_then_blocks_replay(probe, directory, fake_launch):
  probe.prepare(directory); assert probe.run(directory) == 0
  execution = probe.decode(probe.read(directory / "execution.json", probe.MAX_PLAN))
  assert len(fake_launch[0]) == 6 and execution["materialIntact"] is True and execution["parentFailed"] is False
  assert all(row["started"] and row["outcome"] == "observed" and row["namespaceTermination"] == "unknown" for row in execution["cases"])
  with pytest.raises(probe.ProbeError): probe.run(directory)
  assert len(fake_launch[0]) == 6


@pytest.mark.parametrize("mode", ["multi-frame", "stdout-limit", "stderr", "state-mismatch", "extra-work", "late-material", "timeout", "persist-result"])
def test_started_failure_never_becomes_not_run_or_retried(probe, directory, fake_launch, monkeypatch, mode):
  calls, options = fake_launch; probe.prepare(directory)
  if mode == "multi-frame": options["output"] = b'{}\n{}\n'
  elif mode == "stdout-limit": options["output"] = b'x' * (probe.MAX_LINE + 1)
  elif mode == "stderr": options["errors"] = b"SYNTHETIC_SECRET"
  elif mode == "state-mismatch": options["mutate"] = lambda value, work: value.update(nodeLaunches=2)
  elif mode == "extra-work": options["mutate"] = lambda value, work: (work / "extra").write_bytes(b"x")
  elif mode == "late-material": options["after"] = lambda: (probe.ROOT / probe.SOURCES[0]).write_bytes(b"changed")
  elif mode == "timeout": options["never_exit"] = True
  else:
    original = probe.write
    def write(path, value):
      if path.name == "case-result.json": raise OSError("SYNTHETIC_SECRET")
      return original(path, value)
    monkeypatch.setattr(probe, "write", write)
  try: result = probe.run(directory)
  except (probe.ProbeError, OSError): result = 2
  assert result != 0
  execution = probe.decode(probe.read(directory / "execution.json", probe.MAX_PLAN)); first = execution["cases"][0]
  assert first["started"] is True and first["pid"] == 201 and first["outcome"] == "failed"
  if mode == "late-material":
    assert execution["materialIntact"] is False
  else:
    assert len(calls) == 1 and all(not row["started"] for row in execution["cases"][1:])
  assert (directory / "started.json").exists()


@pytest.mark.parametrize("fd,wanted", [(3, True), (4, False), (64, False), (True, False), (None, False)])
def test_reservation_only_exact_new_owned_slot_three(probe, fd, wanted):
  assert probe.reserve_decision(fd) is wanted


@pytest.mark.parametrize("is_ready,state,start,uid,missing,wanted", [(False, "Z", "91", 2, False, False), (True, "Z", "91", 2, False, True),
  (True, "Z", "92", 2, False, False), (True, "Z", "91", 3, False, False), (True, "S", "91", 2, False, False), (True, "Z", "91", 2, True, True)])
def test_exit_ready_birth_bound_z_or_disappearance_only(probe, monkeypatch, is_ready, state, start, uid, missing, wanted):
  expected = {"pid": 40, "start": "91", "uid": 2, "namespace": "pid:[1]", "exe": "/node"}
  monkeypatch.setattr(probe, "ready", lambda fd: is_ready)
  original_stat, original_exists = Path.stat, Path.exists
  raw = "40 (synthetic) " + " ".join([state] + ["0"] * 18 + [start])
  def text(path):
    assert str(path) == "/proc/40"
    if missing: raise FileNotFoundError()
    return raw
  monkeypatch.setattr(probe, "proc_stat", text)
  monkeypatch.setattr(Path, "stat", lambda path, *a, **k: SimpleNamespace(st_uid=uid) if str(path) == "/proc/40" else original_stat(path, *a, **k))
  monkeypatch.setattr(Path, "exists", lambda path: not missing if str(path) == "/proc/40" else original_exists(path))
  assert probe.exit_seen(expected, 700) is wanted


def test_alive_requires_full_original_identity_and_not_ready(probe, monkeypatch):
  original = {"pid": 40, "start": "91", "uid": 2, "namespace": "pid:[1]", "exe": "/node"}
  monkeypatch.setattr(probe, "ready", lambda fd: False); monkeypatch.setattr(probe, "birth", lambda pid: dict(original))
  assert probe.alive(original, 700)
  monkeypatch.setattr(probe, "birth", lambda pid: {**original, "exe": "/different"}); assert not probe.alive(original, 700)
  monkeypatch.setattr(probe, "ready", lambda fd: True); monkeypatch.setattr(probe, "birth", lambda pid: pytest.fail("ready pidfd must not be alive"))
  assert not probe.alive(original, 700)


def test_cli_closed_arguments_never_guest_or_native(probe, directory):
  assert probe.main(["run-native", "--directory", str(directory)]) == 2
  assert probe.main(["prepare", "--directory", str(directory), "--native-owner-fd-probe"]) == 2
  assert probe.main(["guest-driver", "--case", probe.CASES[0], "--directory", str(directory)]) == 2
  assert probe.main(["prepare", "--directory", str(directory), "--unknown"]) == 2


def test_pidfd_open_zero_flags_binds_alive_birth_on_both_sides(probe, monkeypatch):
  observed, closed = [], []
  expected = {"pid": 40, "start": "91", "uid": 2, "namespace": "pid:[1]", "exe": "/node"}
  values = [dict(expected), dict(expected)]
  monkeypatch.setattr(probe, "birth", lambda pid: values.pop(0))
  monkeypatch.setattr(os, "pidfd_open", lambda pid, flags: observed.append((pid, flags)) or 700)
  monkeypatch.setattr(probe, "ready", lambda fd: False)
  original_close = os.close
  monkeypatch.setattr(os, "close", lambda fd: closed.append(fd) if fd == 700 else original_close(fd))
  assert probe.target(40) == (expected, 700) and observed == [(40, 0)] and not closed
  values.extend([dict(expected), {**expected, "start": "92"}])
  with pytest.raises(probe.ProbeError): probe.target(40)
  assert closed == [700]


@pytest.mark.parametrize("second_state,second_uid", [("S", 2), ("Z", 3)])
def test_z_exit_requires_both_stat_reads_and_uid_samples(probe, monkeypatch, second_state, second_uid):
  expected = {"pid": 40, "start": "91", "uid": 2, "namespace": "pid:[1]", "exe": "/node"}
  rows = ["40 (synthetic) " + " ".join([state] + ["0"] * 18 + ["91"]) for state in ("Z", second_state)]
  uids = [2, second_uid]
  monkeypatch.setattr(probe, "ready", lambda fd: True)
  monkeypatch.setattr(probe, "proc_stat", lambda base: rows.pop(0))
  original_stat = Path.stat
  monkeypatch.setattr(Path, "stat", lambda path, *a, **k: SimpleNamespace(st_uid=uids.pop(0)) if str(path) == "/proc/40" else original_stat(path, *a, **k))
  assert probe.exit_seen(expected, 700) is False


def test_bounded_stat_uses_only_synthetic_file_and_closes_handle(probe, tmp_path):
  base = tmp_path / "fake-proc"; base.mkdir(); (base / "stat").write_bytes(b"synthetic")
  assert probe.proc_stat(base) == "synthetic"
  (base / "stat").write_bytes(b"x" * 4097)
  with pytest.raises(probe.ProbeError): probe.proc_stat(base)


@pytest.mark.parametrize("fd", [63, 65, True, None])
def test_high_duplicate_must_be_exact_new_owned_64(probe, fd):
  assert probe.high_decision(64) is True and probe.high_decision(fd) is False


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "permissions", "controller-info-mismatch"])
def test_post_inventory_rejects_links_modes_and_unbound_producer_info(probe, tmp_path, kind):
  work = tmp_path / "work"; work.mkdir(mode=0o700)
  for name in probe.DIRECTORIES: (work / name).mkdir(mode=0o700)
  value = fixture_frame(probe, probe.CASES[0]); fake_work(probe, work, probe.CASES[0], value)
  path = work / "node-entry.json"
  if kind == "symlink": path.unlink(); path.symlink_to(work / "state.json")
  elif kind == "hardlink": os.link(path, work / "extra-alias")
  elif kind == "permissions": path.chmod(0o644)
  else: (work / "controller-info.json").write_bytes(probe.raw_json({"schema": 1, "nodePid": 5, "nodeLaunches": 1, "lock": value["lock"]}))
  with pytest.raises(probe.ProbeError): probe.post_work(work, probe.CASES[0])


def test_started_fsync_failure_retains_original_row(probe, directory, fake_launch, monkeypatch):
  probe.prepare(directory); original_sync = os.fsync
  # fake Popen 回调之后才注入 capture fsync 故障；aggregate 持久化仍可观察。
  failed = []
  def after():
    def sync(fd):
      if not failed: failed.append(fd); raise OSError("SYNTHETIC_SECRET")
      return original_sync(fd)
    monkeypatch.setattr(os, "fsync", sync)
  fake_launch[1]["after"] = after
  with pytest.raises(probe.ProbeError): probe.run(directory)
  execution = probe.decode(probe.read(directory / "execution.json", probe.MAX_PLAN))
  first = execution["cases"][0]
  assert first["started"] and first["pid"] == 201 and first["phase"] == "persistence" and first["outcome"] == "failed"
  assert execution["parentFailed"] is True and len(fake_launch[0]) == 1


def test_private_output_does_not_depend_on_host_umask(probe, tmp_path):
  path = tmp_path / "own-output"; previous = os.umask(0)
  try:
    with probe.private_output(path) as output: output.write(b"synthetic")
  finally: os.umask(previous)
  assert path.stat().st_mode & 0o777 == 0o600 and probe.read(path) == b"synthetic"
  with pytest.raises(FileExistsError): probe.private_output(path)


def test_original_ready_accepts_hup_only_exit_without_os_poll(probe, monkeypatch):
  class Poll:
    def register(self, fd, mask): assert fd == 700 and mask == probe.select.POLLIN
    def poll(self, timeout): assert timeout == 0; return [(700, probe.select.POLLHUP)]
  monkeypatch.setattr(probe.select, "poll", Poll)
  assert probe.ready(700) is True


@pytest.mark.parametrize("mask", [8, 32])
def test_original_ready_error_or_invalid_remains_unknown(probe, monkeypatch, mask):
  class Poll:
    def register(self, *args): pass
    def poll(self, timeout): return [(700, mask)]
  monkeypatch.setattr(probe.select, "poll", Poll)
  with pytest.raises(probe.ProbeError): probe.ready(700)


@pytest.mark.parametrize("drift", ["controller-uid", "controller-namespace", "controller-exe", "node-uid", "node-namespace", "late-driver-namespace"])
def test_existing_guest_driver_wrong_chain_never_signals(probe, monkeypatch, drift):
  # 调用原完整 driver；所有环境、进程、身份、竞争与信号均在调用前固定成自有替身。
  signals, closed, acquired = [], [], []
  driver = {"pid": os.getpid(), "start": "90", "uid": 0, "namespace": "pid:[100]", "exe": str(probe.PYTHON)}
  controller = {**driver, "pid": 42, "start": "91"}
  node = {**driver, "pid": 43, "start": "92", "exe": "/node"}
  current_driver = dict(driver)
  if drift == "controller-uid": controller["uid"] = 1
  elif drift == "controller-namespace": controller["namespace"] = "pid:[101]"
  elif drift == "controller-exe": controller["exe"] = "/node"
  elif drift == "node-uid": node["uid"] = 1
  elif drift == "node-namespace": node["namespace"] = "pid:[101]"
  class StopTrace(Exception): pass
  class Process:
    pid = 42
    stderr = io.BytesIO()
    def wait(self, timeout): raise StopTrace("stop fake trace after old signal")
  monkeypatch.setattr(probe, "guest_environment", lambda: None)
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: Process())
  monkeypatch.setattr(probe, "birth", lambda pid: dict(current_driver) if pid == driver["pid"] else dict(controller if pid == 42 else node))
  def target(pid):
    assert pid in (42, 43)
    fd = 700 if pid == 42 else 701; acquired.append(fd)
    return dict(controller if pid == 42 else node), fd
  monkeypatch.setattr(probe, "target", target)
  monkeypatch.setattr(probe, "alive", lambda *args: True)
  monkeypatch.setattr(probe, "compete", lambda binding: "busy")
  def load(path, deadline):
    if path.name == "controller-info.json":
      return {"schema": 1, "nodePid": 43, "nodeLaunches": 1, "lock": {"device": "1", "inode": "2", "uid": 0, "mode": 0o600, "nlink": 1}}
    assert path.name == "node-entry.json"
    if drift == "late-driver-namespace": current_driver["namespace"] = "pid:[102]"
    return fixture_frame(probe, "controller-kill")["entry"]
  monkeypatch.setattr(probe, "load_when", load)
  monkeypatch.setattr(probe.signal, "pidfd_send_signal", lambda fd, sig: signals.append((fd, sig)))
  original_close = os.close
  monkeypatch.setattr(os, "close", lambda fd: closed.append(fd) if fd in (700, 701) else original_close(fd))
  with pytest.raises((probe.ProbeError, StopTrace)):
    probe._test_original_guest_driver("controller-kill")
  assert signals == []
  assert sorted(closed) == sorted(acquired) and len(closed) == len(set(closed))
