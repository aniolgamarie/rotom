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
SPEC = importlib.util.spec_from_file_location("durable_phase_model_probe", ROOT / "scripts/pi-probe-durable-phase-model.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def dump(path, value):
  path.write_text(json.dumps(value) + "\n"); path.chmod(0o600)


def observed(case):
  value = deepcopy(probe.decode((probe.FIXTURE / "oracle.json").read_bytes())["cases"][case])
  kind = "compaction" if case.startswith("compaction") else "generation"
  value.update(nativeTaskId=3, nativeConversationId=1, metadataGetModel=2,
    nativeIdentity={"schema": 1, "nativeTaskId": 3, "nativeConversationId": 1, "call_kind": kind},
    observedCheckpoint={"phase": "summarize" if kind == "compaction" else "request", "attempt": 1},
    nativeResultEntryId=7 if case == "generation-success" else None, answerEntryId=7 if case == "generation-success" else None,
    nativeResultSubmissionId=7 if case == "compaction-success" else None, summaryEntryId=8 if case == "compaction-success" else None, historyEntryIds=[5, 6] if kind == "compaction" else [],
    selectedFirstKeptEntryId=6 if kind == "compaction" else None, summaryHeadEntryId=6 if case == "compaction-success" else None)
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
def test_eight_closed_typed_oracles(case):
  assert probe.oracle(case, observed(case), 0)["rootBodyCalls"] == 0

@pytest.mark.parametrize("fault", ["unknown", "bool-id", "bool-counter", "wrong-identity", "same-id", "extra-entry", "wrong-ack", "wrong-unknown", "body", "versions", "options", "envelope", "signal", "checkpoint", "exit", "summary", "trace"])
def test_oracle_rejects_unproven_result(fault):
  value = observed("generation-lost-sending-ack"); code = 0
  if fault == "unknown": value["extra"] = 1
  if fault == "bool-id": value["nativeTaskId"] = True
  if fault == "bool-counter": value["counters"]["prepare"] = True
  if fault == "wrong-identity": value["nativeIdentity"]["nativeTaskId"] = 4
  if fault == "same-id": value["nativeTaskId"] = value["nativeConversationId"]
  if fault == "extra-entry": value["counters"]["stream"] = 1
  if fault == "wrong-ack": value["sendingReceipts"] = [False]
  if fault == "wrong-unknown": value["ledger"]["state"] = "not-sent"
  if fault == "body": value["rootBodyCalls"] = 1
  if fault == "versions": value["versions"]["durable"] = "other"
  if fault == "options": value["normalizedOptions"]["maxTokens"] = 200
  if fault == "envelope": value["envelopeMatched"] = False
  if fault == "signal": value["sameSignal"] = False
  if fault == "checkpoint": value["observedCheckpoint"]["attempt"] = True
  if fault == "exit": code = 1
  if fault == "summary": value["summaryObserved"] = True
  if fault == "trace": value["trace"].reverse()
  with pytest.raises(probe.ProbeError): probe.oracle("generation-lost-sending-ack", value, code)

@pytest.mark.parametrize("case", probe.CASES)
def test_actual_parent_capture_fake_process_each_case(small, monkeypatch, case):
  _, directory = small; calls = fake_launcher(monkeypatch, case)
  result = probe.run_case(case, directory, time.monotonic() + 10)
  assert result["started"] is True and result["outcome"] == "observed"
  assert len(calls) == 1
  assert probe.decode(probe.read_private(directory / "case-result.json")) == result

@pytest.mark.parametrize("fault", ["stderr", "duplicate", "two-lines", "truncated", "stdout-limit", "extra", "symlink", "hardlink", "child-directory", "nonzero", "state-drift"])
def test_started_bad_capture_keeps_failure(small, monkeypatch, fault):
  _, directory = small; fake_launcher(monkeypatch, "generation-success", stderr=b"fixed fake error" if fault == "stderr" else b"", fault=fault)
  result = probe.run_case("generation-success", directory, time.monotonic() + 10)
  assert result["started"] is True and result["outcome"] == "failed"
  assert result["namespaceTermination"] == "unknown"

@pytest.mark.parametrize("fault", ["source", "candidate", "durable", "system", "argv", "env", "unknown", "flag", "limits"])
def test_plan_drift_before_launch(small, monkeypatch, fault):
  base, directory = small; value = probe.prepare(directory)
  if fault == "source": (base / "source.py").write_text("changed")
  if fault == "candidate": (base / "candidate/b.js").write_text("changed")
  if fault == "durable": (base / "durable/a.js").write_text("changed")
  if fault == "system": (base / "system/node").write_text("changed")
  if fault == "argv": value["invocations"][probe.CASES[0]]["argv"].append("extra")
  if fault == "env": value["invocations"][probe.CASES[0]]["env"]["SECRET"] = "fixed"
  if fault == "unknown": value["extra"] = True
  if fault == "flag": value["nativeAuthorized"] = True
  if fault == "limits": value["limits"]["case_seconds"] = True
  with pytest.raises(probe.ProbeError): probe.validate_plan(value, directory)
  assert not (directory / "started.json").exists()

@pytest.mark.parametrize("flags", [[], ["--native-durable-phase-model-probe"], ["--native-durable-phase-model-probe", "--extra"]])
def test_run_requires_prepared_plan_and_exact_flag(small, flags):
  _, directory = small
  assert probe.main(["run-native", "--directory", str(directory), *flags]) == 2
  assert not (directory / "started.json").exists()

def test_fake_whole_execution_and_no_replay(small, monkeypatch):
  _, directory = small; probe.prepare(directory); calls = fake_launcher(monkeypatch, None)
  args = ["run-native", "--directory", str(directory), "--native-durable-phase-model-probe"]
  assert probe.main(args) == 0
  value = probe.decode(probe.read_private(directory / "execution.json")); assert len(calls) == 8
  assert all(row["started"] and row["outcome"] == "observed" for row in value["cases"])
  assert value["materialIntact"] is True
  assert probe.main(args) == 2; assert len(calls) == 8

@pytest.mark.parametrize("cut", ["fsync", "case-result", "post-read"])
def test_started_finally_failure_cannot_become_not_run(small, monkeypatch, cut):
  _, directory = small; probe.prepare(directory); fake_launcher(monkeypatch, None)
  original_write, original_post, original_fsync = probe.write_new, probe.post_case, probe.os.fsync
  if cut == "case-result":
    def write(path, value):
      if path.name == "case-result.json": raise OSError("own fixed persistence failure")
      return original_write(path, value)
    monkeypatch.setattr(probe, "write_new", write)
  if cut == "post-read": monkeypatch.setattr(probe, "post_case", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("own fixed persistence failure")))
  if cut == "fsync":
    def sync(fd):
      if (directory / probe.CASES[0] / "stdout.raw").exists(): raise OSError("own fixed persistence failure")
      return original_fsync(fd)
    # Only capture fsync fails; aggregate cannot persist under global fsync failure, retain mutable row directly.
    monkeypatch.setattr(probe.os, "fsync", sync)
    child = directory / probe.CASES[0]; child.mkdir(mode=0o700); row = probe.case_result(probe.CASES[0])
    with pytest.raises(probe.ProbeError): probe.run_case(probe.CASES[0], child, time.monotonic() + 10, result=row)
    assert row["started"] is True and row["outcome"] == "failed" and row["phase"] == "persistence"; return
  assert probe.main(["run-native", "--directory", str(directory), "--native-durable-phase-model-probe"]) in (1, 2)
  execution = probe.decode(probe.read_private(directory / "execution.json"))
  assert execution["parentFailed"] is True
  assert execution["cases"][0]["started"] is True and execution["cases"][0]["outcome"] == "failed"
  assert all(row["started"] is False for row in execution["cases"][1:])

def test_readonly_mounts_every_actual_local_import_and_empty_host_env(tmp_path):
  spec = probe.invocation(probe.CASES[0], tmp_path)
  assert spec["env"] == {}
  argv = spec["argv"]; assert "--clearenv" not in argv
  for name in probe.MODULES:
    index = argv.index(str(ROOT / name)); assert argv[index - 1] == "--ro-bind"
    assert argv[index + 1] == "/probe/" + Path(name).name
  assert argv[-3:] == ["/probe/worker.mjs", "--native-durable-phase-model-worker", probe.CASES[0]]

@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xff', b'[]'])
def test_closed_json_decoder(raw):
  with pytest.raises(probe.ProbeError): probe.decode(raw)

def test_prepare_defaults_never_launch(small, monkeypatch):
  _, directory = small
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("prepare launched"))
  assert probe.main(["prepare", "--directory", str(directory)]) == 0
  plan = probe.decode(probe.read_private(directory / "plan.json"))
  assert plan["nativeStarted"] is False and plan["nativeAuthorized"] is False


def test_utf16_bytes_are_not_strict_utf8_json():
  with pytest.raises(probe.ProbeError): probe.decode('{"own":1}'.encode("utf-16"))


def test_timeout_started_keeps_capture_failure_without_real_signal(small, monkeypatch):
  _, directory = small; fake_launcher(monkeypatch, probe.CASES[0]); ticks = iter([0, 100])
  monkeypatch.setattr(probe.time, "monotonic", lambda: next(ticks, 100))
  result = probe.run_case(probe.CASES[0], directory, 30)
  assert result["started"] is True and result["outcome"] == "failed"
  assert result["namespaceTermination"] == "unknown"


def test_material_changes_after_started_execution_remain_observed_but_intact_false(small, monkeypatch):
  base, directory = small; probe.prepare(directory); calls = fake_launcher(monkeypatch, None); original = probe.subprocess.Popen
  def launched(*args, **kwargs):
    process = original(*args, **kwargs); (base / "source.py").write_text("own changed after launch"); return process
  monkeypatch.setattr(probe.subprocess, "Popen", launched)
  assert probe.main(["run-native", "--directory", str(directory), "--native-durable-phase-model-probe"]) == 1
  execution = probe.decode(probe.read_private(directory / "execution.json"))
  assert execution["materialIntact"] is False and len(calls) == 8
  assert all(row["started"] for row in execution["cases"])


def test_first_failed_case_preserves_evidence_and_does_not_launch_later(small, monkeypatch):
  _, directory = small; probe.prepare(directory); calls = fake_launcher(monkeypatch, None, stderr=b"fixed own failure")
  assert probe.main(["run-native", "--directory", str(directory), "--native-durable-phase-model-probe"]) == 1
  execution = probe.decode(probe.read_private(directory / "execution.json"))
  assert len(calls) == 1 and execution["cases"][0]["started"] is True
  assert execution["cases"][0]["outcome"] == "failed"
  assert all(not row["started"] and row["outcome"] == "not-run" for row in execution["cases"][1:])


def test_own_import_source_symlink_cannot_qualify_manifest(small):
  base, _ = small; (base / "target.py").write_text("own unrelated target")
  (base / "source.py").unlink(); (base / "source.py").symlink_to(base / "target.py")
  with pytest.raises(probe.ProbeError): probe.material()


def test_timeout_cleanup_only_saved_fake_process_group_and_exit_unknown(small, monkeypatch):
  _, directory = small; fake_launcher(monkeypatch, probe.CASES[0]); base = probe.subprocess.Popen; killed = []
  class Stubborn(base):
    def poll(self): return None
    def wait(self, timeout=None): raise subprocess.TimeoutExpired("own fixed process", timeout)
  monkeypatch.setattr(probe.subprocess, "Popen", Stubborn)
  monkeypatch.setattr(probe.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
  result = probe.run_case(probe.CASES[0], directory, time.monotonic() + 10)
  assert result["started"] is True and result["outcome"] == "failed" and result["exitCode"] is None
  assert [pid for pid, sig in killed] == [123456789, 123456789]
  assert [sig for pid, sig in killed] == [probe.signal.SIGTERM, probe.signal.SIGKILL]
  assert result["namespaceTermination"] == "unknown"


@pytest.mark.parametrize("fault", ["generation-answer", "generation-bool-answer", "compaction-noop", "compaction-wrong-cut", "compaction-bool-head", "compaction-denial-enum"])
def test_public_receipt_and_genuine_cut_binding_cannot_be_replaced(fault):
  case = "generation-success" if fault.startswith("generation") else "compaction-denied" if fault == "compaction-denial-enum" else "compaction-success"
  value = observed(case)
  if fault == "generation-answer": value["answerEntryId"] = 9
  if fault == "generation-bool-answer": value["answerEntryId"] = True
  if fault == "compaction-noop": value["nativeResultSubmissionId"] = None; value["summaryEntryId"] = None
  if fault == "compaction-wrong-cut": value["selectedFirstKeptEntryId"] = 5
  if fault == "compaction-bool-head": value["summaryHeadEntryId"] = True
  if fault == "compaction-denial-enum": value["nativeTaskOutcome"] = "failed"
  with pytest.raises(probe.ProbeError): probe.oracle(case, value, 0)


def test_real_bytearray_stdout_capture_rejects_utf16be_with_same_utf8_state(small, monkeypatch):
  _, directory = small; fake_launcher(monkeypatch, "generation-success", fault="utf16be")
  original_decode = probe.decode; binary_types = []
  def decode(raw):
    if type(raw) is bytearray: binary_types.append(type(raw))
    return original_decode(raw)
  monkeypatch.setattr(probe, "decode", decode)
  result = probe.run_case("generation-success", directory, time.monotonic() + 10)
  assert binary_types == [bytearray]
  assert (result["started"], result["outcome"], result["phase"]) == (True, "failed", "oracle")
  stdout = probe.read_private(directory / "stdout.raw")
  assert stdout.startswith(b"\xfe\xff") and stdout.endswith(b"\n") and stdout.count(b"\n") == 1
  state = original_decode(probe.read_private(directory / "work/state.json"))
  assert state == observed("generation-success")
  assert probe.decode(probe.read_private(directory / "case-result.json")) == result


@pytest.mark.parametrize("binary_type", [bytes, bytearray])
@pytest.mark.parametrize("encoding", ["utf-16-be", "utf-16-le"])
def test_binary_decoder_never_autodetects_non_utf8(binary_type, encoding):
  bom = b"\xfe\xff" if encoding.endswith("be") else b"\xff\xfe"
  raw = binary_type(bom + '{"own":1}'.encode(encoding))
  with pytest.raises(probe.ProbeError): probe.decode(raw)
