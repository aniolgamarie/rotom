"""默认仅自有假 Popen/小文件清单；绝不加载或启动 SDK/Node worker。"""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import time

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("durable_summary_recovery_probe", ROOT / "scripts/pi-probe-durable-summary-recovery.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def dump(path, value):
  path.write_text(json.dumps(value) + "\n"); path.chmod(0o600)


def observed(case):
  value = deepcopy(probe.decode((probe.FIXTURE / "oracle.json").read_bytes())["cases"][case])
  success = case == probe.CASES[0]
  value.update(nativeTaskId=3, nativeConversationId=1, firstKeptEntryId=6, historyEntryIds=[5, 6],
    summarySubmissionId=7 if success else None, summaryEntryId=8 if success else None,
    summaryHeadEntryId=6 if success else None, metadataGetModel={"old": 2, "fresh": 1})
  return value


@pytest.fixture
def small(monkeypatch, tmp_path):
  base = tmp_path / "bundle"; base.mkdir()
  for name in ("durable", "candidate", "system", "fixtures"):
    (base / name).mkdir()
  for name in ("durable/a.js", "candidate/b.js", "system/node", "system/bwrap", "source.py"):
    (base / name).write_text("own static fixture\n")
  for name in ("system/node", "system/bwrap"): (base / name).chmod(0o700)
  fixture = base / "fixtures"
  (fixture / "oracle.json").write_bytes((probe.FIXTURE / "oracle.json").read_bytes())
  fixed = {"schema": 1, "versions": probe.VERSIONS, "source_chain": {}, "durable": probe.inventory(base / "durable"), "candidate": probe.inventory(base / "candidate")}
  (fixture / "manifest.json").write_text(json.dumps(fixed))
  monkeypatch.setattr(probe, "SOURCE_CHAIN", ())
  monkeypatch.setattr(probe, "system", lambda: {"node": probe.record(base / "system/node"), "bwrap": probe.record(base / "system/bwrap")})
  monkeypatch.setattr(probe, "ROOT", base); monkeypatch.setattr(probe, "DURABLE", base / "durable"); monkeypatch.setattr(probe, "CANDIDATE", base / "candidate")
  monkeypatch.setattr(probe, "FIXTURE", fixture); monkeypatch.setattr(probe, "SOURCES", ("source.py",)); monkeypatch.setattr(probe, "NODE", base / "system/node"); monkeypatch.setattr(probe, "BWRAP", base / "system/bwrap")
  output = tmp_path / "output"; output.mkdir(mode=0o700)
  return base, output


def fake_launcher(monkeypatch, case, value=None, stderr=b"", fault=None):
  calls = []
  if fault == "stdout-limit": monkeypatch.setattr(probe, "MAX_LINE", 64)
  class Process:
    def __init__(self, argv, **kwargs):
      calls.append((argv, kwargs)); assert kwargs["shell"] is False; assert kwargs["start_new_session"] is True; assert kwargs["env"] == {}; assert kwargs["stdin"] == subprocess.DEVNULL
      work = Path(argv[argv.index("--bind") + 1]); state = observed(argv[-1] if case is None else case) if value is None else value
      dump(work / "state.json", state); (work / "database.sqlite").write_bytes(b"OWN FAKE SQLITE FILE"); (work / "database.sqlite").chmod(0o600)
      if fault == "extra": (work / "unexpected").write_text("sentinel")
      if fault == "symlink": (work / "database.sqlite-wal").symlink_to(work / "database.sqlite")
      if fault == "hardlink": os.link(work / "database.sqlite", work / "database.sqlite-wal")
      if fault == "child-directory": (work / "home/extra").mkdir()
      raw = json.dumps(state).encode() + b"\n"
      if fault == "utf16be": raw = b"\xfe\xff" + (json.dumps(state, ensure_ascii=True) + "\n").encode("utf-16-be")
      if fault == "two-lines": raw += raw
      if fault == "state-drift":
        changed = deepcopy(state); changed["counters"]["prepare"] = True; dump(work / "state.json", changed)
      if fault == "truncated": raw = raw[:-1]
      if fault == "duplicate": raw = b'{"schema":1,"schema":1}\n'
      if fault == "stdout-limit": raw = b"x" * (probe.MAX_LINE + 1)
      self.stdout = self.stream(raw); self.stderr = self.stream(stderr); self.returncode = 1 if fault == "nonzero" else 0; self.pid = 123456789
    def stream(self, data):
      reader, writer = os.pipe(); os.write(writer, data); os.close(writer); return os.fdopen(reader, "rb")
    def poll(self): return self.returncode
    def wait(self, timeout=None): return self.returncode
  monkeypatch.setattr(probe.subprocess, "Popen", Process)
  return calls




@pytest.mark.parametrize("case", probe.CASES)
def test_three_closed_recovery_oracles(case):
  assert probe.oracle(case, observed(case), 0)["oldClosed"] is True

@pytest.mark.parametrize("fault", ["unknown", "bool-id", "bool-counter", "different-task", "different-cp", "not-closed", "not-settled", "old-live", "same-signal", "same-envelope", "input-drift", "passive-send", "no-authorize", "new-budget", "refund", "summary-noop", "wrong-head", "not-active", "trace", "exit"])
def test_oracle_rejects_false_recovery(fault):
  case = probe.CASES[2] if fault in {"new-budget", "refund"} else probe.CASES[0]
  value = observed(case); status = 0
  if fault == "unknown": value["extra"] = True
  if fault == "bool-id": value["nativeTaskId"] = True
  if fault == "bool-counter": value["counters"]["old"]["authorize"] = True
  if fault == "different-task": value["nativeTaskId"] = value["nativeConversationId"]
  if fault == "different-cp": value["freshOpenTask"]["attempt"] = 2
  if fault == "not-closed": value["oldClosed"] = False
  if fault == "not-settled": value["heldSettled"] = False
  if fault == "old-live": value["oldSignalAborted"] = False
  if fault == "same-signal": value["newSignalDifferent"] = False
  if fault == "same-envelope": value["newEnvelopeDifferent"] = False
  if fault == "input-drift": value["crossEnvelopeMatched"] = False
  if fault == "passive-send": value["beforeResumeZero"] = False
  if fault == "no-authorize": value["counters"]["fresh"]["authorize"] = 0
  if fault == "new-budget": value["ledgerFinal"]["a2"] = {"state": "prepared"}
  if fault == "refund": value["ledgerFinal"]["budget"]["reservedCostUnits"] = "0"
  if fault == "summary-noop": value["summarySubmissionId"] = None
  if fault == "wrong-head": value["summaryHeadEntryId"] = 5
  if fault == "not-active": value["freshOpenTask"]["status"] = "running"
  if fault == "trace": value["trace"].reverse()
  if fault == "exit": status = 1
  with pytest.raises(probe.ProbeError): probe.oracle(case, value, status)

@pytest.mark.parametrize("case", probe.CASES)
def test_parent_fake_capture_preserves_own_original_receipts(small, monkeypatch, case):
  _, directory = small; calls = fake_launcher(monkeypatch, case)
  result = probe.run_case(case, directory, time.monotonic() + 10)
  assert result["started"] is True and result["outcome"] == "observed" and len(calls) == 1
  assert probe.decode(probe.read_private(directory / "case-result.json")) == result

@pytest.mark.parametrize("fault", ["utf16be", "two-lines", "truncated", "duplicate", "state-drift", "nonzero", "extra", "symlink", "hardlink", "child-directory", "stdout-limit"])
def test_bad_capture_cannot_be_observed(small, monkeypatch, fault):
  _, directory = small; fake_launcher(monkeypatch, probe.CASES[0], fault=fault)
  result = probe.run_case(probe.CASES[0], directory, time.monotonic() + 10)
  assert result["started"] is True and result["outcome"] == "failed"
  assert result["namespaceTermination"] == "unknown"

@pytest.mark.parametrize("binary", [bytes, bytearray])
def test_strict_utf8_for_capture_and_state(binary):
  with pytest.raises(probe.ProbeError): probe.decode(binary(b"\xfe\xff" + '{"own":1}'.encode("utf-16-be")))

def test_fake_complete_three_cases_and_replay_is_blocked(small, monkeypatch):
  _, directory = small; probe.prepare(directory); calls = fake_launcher(monkeypatch, None)
  args = ["run-native", "--directory", str(directory), "--native-durable-summary-recovery-probe"]
  assert probe.main(args) == 0; assert len(calls) == 3
  execution = probe.decode(probe.read_private(directory / "execution.json")); assert execution["materialIntact"] is True
  assert all(row["started"] and row["outcome"] == "observed" for row in execution["cases"])
  assert probe.main(args) == 2; assert len(calls) == 3

@pytest.mark.parametrize("fault", ["source", "durable", "candidate", "system", "argv", "env", "limits", "native", "unknown"])
def test_plan_exact_material_before_launch(small, fault):
  base, directory = small; value = probe.prepare(directory)
  if fault == "source": (base / "source.py").write_text("own changed")
  if fault == "durable": (base / "durable/a.js").write_text("own changed")
  if fault == "candidate": (base / "candidate/b.js").write_text("own changed")
  if fault == "system": (base / "system/node").write_text("own changed")
  if fault == "argv": value["invocations"][probe.CASES[0]]["argv"].append("extra")
  if fault == "env": value["invocations"][probe.CASES[0]]["env"]["HOME"] = "own invalid"
  if fault == "limits": value["limits"]["total_seconds"] = 240
  if fault == "native": value["nativeStarted"] = True
  if fault == "unknown": value["extra"] = True
  with pytest.raises(probe.ProbeError): probe.validate_plan(value, directory)
  assert not (directory / "started.json").exists()

@pytest.mark.parametrize("cut", ["fsync", "result-write", "post-read"])
def test_started_persistence_failure_not_overwritten(small, monkeypatch, cut):
  _, directory = small; fake_launcher(monkeypatch, probe.CASES[0]); row = probe.case_result(probe.CASES[0]); original_write = probe.write_new
  if cut == "fsync":
    original_sync = probe.os.fsync
    def sync(fd):
      if (directory / "stdout.raw").exists(): raise OSError("own IO fault")
      return original_sync(fd)
    monkeypatch.setattr(probe.os, "fsync", sync)
  if cut == "result-write":
    def write(path, value):
      if path.name == "case-result.json": raise OSError("own IO fault")
      return original_write(path, value)
    monkeypatch.setattr(probe, "write_new", write)
  if cut == "post-read": monkeypatch.setattr(probe, "post_case", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("own IO fault")))
  with pytest.raises(probe.ProbeError): probe.run_case(probe.CASES[0], directory, time.monotonic() + 10, result=row)
  assert row["started"] is True and row["outcome"] == "failed" and row["phase"] == "persistence"

def test_unchanged_source_mounts_complete_import_inventory(tmp_path):
  value = probe.invocation(probe.CASES[0], tmp_path); assert value["env"] == {}
  assert len(probe.SOURCES) == 12
  for name in probe.MODULES:
    index = value["argv"].index(str(ROOT / name)); assert value["argv"][index - 1] == "--ro-bind"
    assert value["argv"][index + 1] == "/probe/" + Path(name).name
  assert value["argv"][-2:] == ["--native-durable-summary-recovery-worker", probe.CASES[0]]

@pytest.mark.parametrize("raw", [b'{"own":1,"own":2}', b'{"own":NaN}', b'{"own":Infinity}', b'\xff', b'[]'])
def test_binary_json_frame_is_closed(raw):
  with pytest.raises(probe.ProbeError): probe.decode(raw)

def test_default_prepare_never_launches(small, monkeypatch):
  _, directory = small
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("prepare launched"))
  assert probe.main(["prepare", "--directory", str(directory)]) == 0
  value = probe.decode(probe.read_private(directory / "plan.json"))
  assert value["nativeStarted"] is False and value["nativeAuthorized"] is False
  assert value["limits"]["case_seconds"] == 30 and value["limits"]["total_seconds"] == 90


def test_first_failed_capture_stops_later_and_keeps_execution(small, monkeypatch):
  _, directory = small; probe.prepare(directory); calls = fake_launcher(monkeypatch, None, stderr=b"fixed own failure")
  assert probe.main(["run-native", "--directory", str(directory), "--native-durable-summary-recovery-probe"]) == 1
  result = probe.decode(probe.read_private(directory / "execution.json")); assert len(calls) == 1
  assert result["cases"][0]["started"] is True and result["cases"][0]["outcome"] == "failed"
  assert all(not row["started"] and row["outcome"] == "not-run" for row in result["cases"][1:])


def test_finally_write_failure_preserves_same_started_aggregate_row(small, monkeypatch):
  _, directory = small; probe.prepare(directory); fake_launcher(monkeypatch, None); original = probe.write_new
  def write(path, value):
    if path.name == "case-result.json": raise OSError("own fixed failure")
    return original(path, value)
  monkeypatch.setattr(probe, "write_new", write)
  assert probe.main(["run-native", "--directory", str(directory), "--native-durable-summary-recovery-probe"]) == 2
  value = probe.decode(probe.read_private(directory / "execution.json"))
  assert value["parentFailed"] is True and value["cases"][0]["started"] is True
  assert value["cases"][0]["outcome"] == "failed" and value["cases"][0]["phase"] == "persistence"


def test_late_material_drift_is_not_hidden_by_observed_fake_cases(small, monkeypatch):
  base, directory = small; probe.prepare(directory); fake_launcher(monkeypatch, None); original = probe.subprocess.Popen
  def launch(*args, **kwargs):
    process = original(*args, **kwargs); (base / "source.py").write_text("own late drift"); return process
  monkeypatch.setattr(probe.subprocess, "Popen", launch)
  assert probe.main(["run-native", "--directory", str(directory), "--native-durable-summary-recovery-probe"]) == 1
  assert probe.decode(probe.read_private(directory / "execution.json"))["materialIntact"] is False


def test_capture_deadline_failure_keeps_started(small, monkeypatch):
  _, directory = small; fake_launcher(monkeypatch, probe.CASES[0]); ticks = iter([0, 100])
  monkeypatch.setattr(probe.time, "monotonic", lambda: next(ticks, 100))
  row = probe.run_case(probe.CASES[0], directory, 30)
  assert row["started"] is True and row["outcome"] == "failed" and row["namespaceTermination"] == "unknown"


def test_cleanup_timeout_only_targets_saved_fake_group(small, monkeypatch):
  _, directory = small; fake_launcher(monkeypatch, probe.CASES[0]); original = probe.subprocess.Popen; signals = []
  class Process(original):
    def poll(self): return None
    def wait(self, timeout=None): raise subprocess.TimeoutExpired("own fake", timeout)
  monkeypatch.setattr(probe.subprocess, "Popen", Process)
  monkeypatch.setattr(probe.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
  row = probe.run_case(probe.CASES[0], directory, time.monotonic() + 10)
  assert signals == [(123456789, probe.signal.SIGTERM), (123456789, probe.signal.SIGKILL)]
  assert row["started"] is True and row["outcome"] == "failed" and row["exitCode"] is None and row["namespaceTermination"] == "unknown"
