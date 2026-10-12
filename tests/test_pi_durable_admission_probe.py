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
SPEC = importlib.util.spec_from_file_location("durable_admission_probe", ROOT / "scripts/pi-probe-durable-admission.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def dump(path, value):
  path.write_text(json.dumps(value) + "\n"); path.chmod(0o600)


def observed(case):
  value = deepcopy(probe.decode((probe.FIXTURE / "oracle.json").read_bytes())["cases"][case])
  value.pop("batchCount"); has = value["taskWrites"] == 1
  value.update(seedConversationId=1, lookupNativeTaskId=3 if has else None, recordNativeTaskId=3 if has else None,
    nativeTaskIds=[3] if has else [], batchTypes=[["document.create"], ["task", "document.change"]] if has else [] if case == "active-missing" else [["document.create"]])
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
      if fault == "duplicate": raw = b'{"schema":1,"schema":1}\n'
      if fault == "stdout-limit": raw = b"x" * (probe.MAX_LINE + 1)
      self.stdout = self.stream(raw); self.stderr = self.stream(stderr); self.returncode = 0; self.pid = 123456789
    def stream(self, data):
      reader, writer = os.pipe(); os.write(writer, data); os.close(writer); return os.fdopen(reader, "rb")
    def poll(self): return self.returncode
    def wait(self, timeout=None): return self.returncode
  monkeypatch.setattr(probe.subprocess, "Popen", Process)
  return calls


@pytest.mark.parametrize("case", probe.CASES)
def test_closed_seven_case_oracle_without_sdk(case):
  assert probe.oracle(case, observed(case), 0)["bodyCalls"] == 0


@pytest.mark.parametrize("fault", ["unknown", "wrong-id", "seed-id", "bool-id", "task-count", "commit-count", "body", "proxy", "persistent", "same-batch", "exit", "batch-extra", "counter-bool"])
def test_oracle_rejects_false_native_success(fault):
  value = observed("normal"); code = 0
  if fault == "unknown": value["extra"] = True
  if fault == "wrong-id": value["recordNativeTaskId"] = 4
  if fault == "seed-id": value.update(nativeTaskIds=[1], recordNativeTaskId=1, lookupNativeTaskId=1)
  if fault == "bool-id": value.update(nativeTaskIds=[True], recordNativeTaskId=True, lookupNativeTaskId=True)
  if fault == "task-count": value["taskWrites"] = 2
  if fault == "commit-count": value["componentCommits"] = 3
  if fault == "body": value["bodyCalls"] = 1
  if fault == "proxy": value["nativeProxyObserved"] = False
  if fault == "persistent": value["persistentDocMatched"] = False
  if fault == "same-batch": value["batchTypes"] = [["task"], ["document.change"]]
  if fault == "exit": code = 1
  if fault == "batch-extra": value["batchTypes"][1].append("entry")
  if fault == "counter-bool": value["seedBatches"] = True
  with pytest.raises(probe.ProbeError): probe.oracle("normal", value, code)


def test_prepare_is_read_only_with_no_process_and_explicit_ungranted_plan(small, monkeypatch):
  _, output = small
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("default prepare started process"))
  assert probe.main(["prepare", "--directory", str(output)]) == 0
  value = probe.decode(probe.read_private(output / "plan.json")); assert value["nativeStarted"] is False; assert value["nativeAuthorized"] is False
  assert probe.validate_plan(value, output) is value
  assert set(p.name for p in output.iterdir()) == {"plan.json"}


@pytest.mark.parametrize("field", ["extra", "cases", "nativeAuthorized", "limits", "invocations", "sources", "schema"])
def test_prepared_plan_rejects_drift_or_unknown_fields(small, field):
  _, output = small; value = probe.prepare(output)
  if field == "extra": value["extra"] = 1
  if field == "cases": value["cases"].reverse()
  if field == "nativeAuthorized": value["nativeAuthorized"] = True
  if field == "limits": value["limits"]["case_seconds"] = 100
  if field == "invocations": value["invocations"]["normal"]["env"] = {"SECRET": "synthetic"}
  if field == "sources": value["material"]["sources"]["source.py"]["sha256"] = "f" * 64
  if field == "schema": value["schema"] = True
  with pytest.raises(probe.ProbeError): probe.validate_plan(value, output)


@pytest.mark.parametrize("where", ["candidate", "durable", "source", "system", "extra-file", "symlink"])
def test_material_revalidation_uses_full_closed_lists(small, where):
  base, output = small; value = probe.prepare(output)
  path = base / {"candidate": "candidate/b.js", "durable": "durable/a.js", "source": "source.py", "system": "system/node", "extra-file": "candidate/extra", "symlink": "candidate/b.js"}[where]
  if where == "symlink": path.unlink(); path.symlink_to(base / "source.py")
  else: path.write_text("drift")
  with pytest.raises(probe.ProbeError): probe.validate_plan(value, output)


@pytest.mark.parametrize("args", [[], ["prepare"], ["run-native", "--directory", "relative"], ["prepare", "--directory", "/tmp", "--native-durable-admission-probe"], ["run-native", "--directory", "/tmp"], ["prepare", "--directory", "/tmp", "--unknown"], ["prepare", "--dir", "/tmp"]])
def test_closed_parameters_never_start_process(args, monkeypatch):
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("invalid parameters started process"))
  assert probe.main(args) == 2


@pytest.mark.parametrize("case", probe.CASES)
def test_fake_native_capture_and_post_inventory_only(case, small, monkeypatch):
  _, output = small; calls = fake_launcher(monkeypatch, case)
  result = probe.run_case(case, output, time.monotonic() + 5)
  assert result["outcome"] == "observed"; assert result["started"] is True; assert result["namespaceTermination"] == "unknown"; assert len(calls) == 1
  assert calls[0][0] == probe.invocation(case, output / "work")["argv"]; probe.post_case(output)


@pytest.mark.parametrize("fault", ["extra", "symlink", "hardlink", "child-directory", "duplicate", "stdout-limit", "stderr", "wrong-id"])
def test_fake_native_bad_output_preserves_executed_evidence(small, monkeypatch, fault):
  _, output = small; value = observed("normal")
  if fault == "wrong-id": value["lookupNativeTaskId"] = 5
  fake_launcher(monkeypatch, "normal", value, b"fixed stderr\n" if fault == "stderr" else b"", fault)
  result = probe.run_case("normal", output, time.monotonic() + 5)
  assert result["started"] is True and result["outcome"] == "failed"
  stored = probe.decode(probe.read_private(output / "case-result.json")); assert stored["started"] is True
  assert (output / "stdout.raw").is_file() and (output / "invocation.json").is_file()


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'[]', b'{bad', b'\xff'])
def test_duplicate_nonfinite_and_malformed_json(raw):
  with pytest.raises(probe.ProbeError): probe.decode(raw)


def test_private_plan_hardlink_symlink_and_mode_rejected(tmp_path):
  target = tmp_path / "file"; dump(target, {})
  target.chmod(0o644)
  with pytest.raises(probe.ProbeError): probe.read_private(target)
  target.chmod(0o600); link = tmp_path / "link"; link.symlink_to(target)
  with pytest.raises(probe.ProbeError): probe.read_private(link)
  link.unlink(); os.link(target, link)
  with pytest.raises(probe.ProbeError): probe.read_private(target)


def test_fixed_invocation_has_no_sdk_patch_or_account_mount(tmp_path):
  selected = probe.invocation("normal", tmp_path / "work"); argv = selected["argv"]
  assert selected["env"] == {}; assert "--unshare-all" in argv and "--cap-drop" in argv and "--clearenv" not in argv
  assert argv.count("--bind") == 1; assert "--new-session" in argv and "--die-with-parent" in argv
  assert argv[-2:] == ["--native-durable-admission-worker", "normal"]
  for key, value in probe.ENV.items(): assert ["--setenv", key, value] == argv[argv.index(key)-1:argv.index(key)+2]
  assert "npm" not in argv and str(Path.home()) not in argv

@pytest.mark.parametrize("nested", ["limits", "settings", "source-bytes"])
def test_float_or_bool_cannot_impersonate_fixed_nested_integer(small, nested):
  _, output = small
  if nested == "settings":
    value = observed("normal"); value["settings"]["synchronous"] = 2.0
    with pytest.raises(probe.ProbeError): probe.oracle("normal", value, 0)
  else:
    value = probe.prepare(output)
    if nested == "limits": value["limits"]["case_seconds"] = 15.0
    else: value["material"]["sources"]["source.py"]["bytes"] = float(value["material"]["sources"]["source.py"]["bytes"])
    with pytest.raises(probe.ProbeError): probe.validate_plan(value, output)


def test_deadline_cleans_only_owned_processgroup_and_preserves_started(small, monkeypatch):
  _, output = small; calls = []; writers = []
  class Pending:
    pid = 123456789
    returncode = None
    def __init__(self, *args, **kwargs):
      self.stdout = self.stream(); self.stderr = self.stream()
    def stream(self):
      reader, writer = os.pipe(); writers.append(writer); return os.fdopen(reader, "rb")
    def poll(self): return self.returncode
    def wait(self, timeout=None):
      if self.returncode is None: raise subprocess.TimeoutExpired("OWN FAKE", timeout)
      return self.returncode
  instance = Pending.__new__(Pending)
  def factory(*args, **kwargs): Pending.__init__(instance, *args, **kwargs); return instance
  def kill(pid, selected): calls.append((pid, selected)); instance.returncode = -selected
  monkeypatch.setattr(probe.subprocess, "Popen", factory); monkeypatch.setattr(probe.os, "killpg", kill)
  try:
    result = probe.run_case("normal", output, time.monotonic() + 0.02)
    assert result["outcome"] == "failed" and result["started"] is True
    assert calls == [(instance.pid, probe.signal.SIGTERM)]; assert result["namespaceTermination"] == "unknown"
  finally:
    for writer in writers: os.close(writer)


def test_launch_failure_does_not_claim_execution(small, monkeypatch):
  _, output = small
  def fail(*args, **kwargs): raise OSError("synthetic private launch failure")
  monkeypatch.setattr(probe.subprocess, "Popen", fail)
  result = probe.run_case("normal", output, time.monotonic() + 1)
  assert result["started"] is False and result["outcome"] == "not-run"
  assert probe.decode(probe.read_private(output / "case-result.json"))["started"] is False


def test_missing_private_environment_directory_fails_post_inventory(small, monkeypatch):
  _, output = small; fake_launcher(monkeypatch, "normal")
  result = probe.run_case("normal", output, time.monotonic() + 1); assert result["outcome"] == "observed"
  (output / "work/home").rmdir()
  with pytest.raises(probe.ProbeError): probe.post_case(output)

def test_fake_native_full_parent_requires_prepared_plan_explicit_flag_and_is_one_shot(small, monkeypatch):
  _, output = small; probe.prepare(output); calls = fake_launcher(monkeypatch, None)
  assert probe.main(["run-native", "--directory", str(output)]) == 2; assert calls == []
  assert probe.main(["run-native", "--directory", str(output), "--native-durable-admission-probe"]) == 0; assert len(calls) == 7
  result = probe.decode(probe.read_private(output / "execution.json")); assert result["materialIntact"] is True
  assert all(case["outcome"] == "observed" for case in result["cases"])
  assert probe.main(["run-native", "--directory", str(output), "--native-durable-admission-probe"]) == 2; assert len(calls) == 7


def test_parent_failure_keeps_started_execution_and_skips_remaining_cases(small, monkeypatch):
  _, output = small; probe.prepare(output); value = observed("normal"); value["recordNativeTaskId"] = 999
  calls = fake_launcher(monkeypatch, "normal", value)
  assert probe.main(["run-native", "--directory", str(output), "--native-durable-admission-probe"]) == 1; assert len(calls) == 1
  result = probe.decode(probe.read_private(output / "execution.json")); assert result["cases"][0]["started"] is True; assert result["cases"][0]["outcome"] == "failed"
  assert all(case["outcome"] == "not-run" for case in result["cases"][1:]); assert (output / "normal/stdout.raw").is_file()


def test_fixture_namespace_is_closed_even_before_prepare(small):
  base, output = small; (base / "fixtures/unexpected.mjs").write_text("own extra")
  with pytest.raises(probe.ProbeError): probe.prepare(output)
  assert list(output.iterdir()) == []


def test_source_chain_cannot_be_omitted_from_real_manifest():
  assert set(probe.manifest()["source_chain"]) == set(probe.SOURCE_CHAIN)


def test_deep_malformed_json_is_fixed_not_raw_recursion():
  with pytest.raises(probe.ProbeError): probe.decode(b'{"a":' + b"[" * 5000 + b"0" + b"]" * 5000 + b"}")


def test_correlated_ids_still_must_be_native_safe_integers():
  value = observed("normal"); value.update(nativeTaskIds=[2**60], lookupNativeTaskId=2**60, recordNativeTaskId=2**60)
  with pytest.raises(probe.ProbeError): probe.oracle("normal", value, 0)


def test_later_parent_setup_failure_preserves_aggregate_executed_case(small, monkeypatch):
  _, output = small; probe.prepare(output); calls = fake_launcher(monkeypatch, None)
  original = probe.run_case
  def run(case, directory, deadline, result=None):
    result = original(case, directory, deadline, result=result)
    if case == "normal": (output / "concurrent-conflicts").mkdir(mode=0o700)
    return result
  monkeypatch.setattr(probe, "run_case", run)
  assert probe.main(["run-native", "--directory", str(output), "--native-durable-admission-probe"]) != 0
  assert len(calls) == 1
  result = probe.decode(probe.read_private(output / "execution.json"))
  assert result["cases"][0]["started"] is True and result["cases"][0]["outcome"] == "observed"
  assert (output / "normal/stdout.raw").is_file()


@pytest.mark.parametrize("fault", ["write", "write-assertion", "fsync", "close", "post-case"])
def test_finally_io_fault_keeps_real_started_current_row(small, monkeypatch, fault):
  _, output = small; probe.prepare(output); calls = fake_launcher(monkeypatch, None)
  original_write, original_fsync, original_close, original_post = probe.write_new, probe.os.fsync, probe.os.close, probe.post_case
  triggered = []
  def write(path, value):
    if path.name == "case-result.json":
      triggered.append("write")
      if fault == "write-assertion": raise probe.ProbeError("own partial-write assertion failure")
      raise OSError("own case receipt persistence failure")
    return original_write(path, value)
  def sync(fd):
    if not triggered and os.readlink(f"/proc/self/fd/{fd}").endswith("stdout.raw"):
      triggered.append("fsync"); raise OSError("own raw sync failure")
    return original_fsync(fd)
  def close(fd):
    if not triggered and os.readlink(f"/proc/self/fd/{fd}").endswith("stdout.raw"):
      triggered.append("close"); original_close(fd); raise OSError("own close acknowledgment failure")
    return original_close(fd)
  def post(directory, *args, **kwargs):
    if directory.name == "normal": triggered.append("post"); raise OSError("own post inventory failure")
    return original_post(directory, *args, **kwargs)
  monkeypatch.setattr(probe, {"write": "write_new", "post-case": "post_case"}.get(fault, "write_new"), write if fault in ("write", "write-assertion") else post if fault == "post-case" else original_write)
  if fault == "fsync": monkeypatch.setattr(probe.os, "fsync", sync)
  if fault == "close": monkeypatch.setattr(probe.os, "close", close)
  assert probe.main(["run-native", "--directory", str(output), "--native-durable-admission-probe"]) != 0
  assert len(calls) == 1 and triggered
  execution = probe.decode(probe.read_private(output / "execution.json")); current = execution["cases"][0]
  assert current["started"] is True and current["exitCode"] == 0
  assert current["outcome"] == "failed" and current["phase"] == "persistence"
  assert execution["parentFailed"] is True
  assert (output / "normal/stdout.raw").is_file()


def test_state_bool_cannot_impersonate_stdout_integer(small, monkeypatch):
  _, output = small; fake_launcher(monkeypatch, "normal"); original = probe.read_private
  def read(path, *args, **kwargs):
    raw = original(path, *args, **kwargs)
    if path.name == "state.json":
      state = probe.decode(raw); state["taskWrites"] = True; return json.dumps(state).encode() + b"\n"
    return raw
  monkeypatch.setattr(probe, "read_private", read)
  result = probe.run_case("normal", output, time.monotonic() + 1)
  assert result["started"] is True and result["outcome"] == "failed"


def test_fixed_bwrap_uses_empty_popen_environment_without_unsupported_clearenv(tmp_path):
  selected = probe.invocation("normal", tmp_path / "work")
  assert selected["env"] == {} and "--clearenv" not in selected["argv"]
  for key, value in probe.ENV.items(): assert ["--setenv", key, value] == selected["argv"][selected["argv"].index(key)-1:selected["argv"].index(key)+2]


def test_json_helper_is_pinned_once_and_has_one_readonly_namespace_mount(tmp_path):
  name = "scripts/pi-probe-json.mjs"
  assert probe.SOURCES.count(name) == 1
  argv = probe.invocation("normal", tmp_path / "work")["argv"]
  assert argv.count("/probe/json.mjs") == 1
  index = argv.index("/probe/json.mjs")
  assert argv[index-2:index+1] == ["--ro-bind", str(probe.ROOT / name), "/probe/json.mjs"]


def test_prepared_small_bundle_rejects_json_helper_source_drift(small, monkeypatch):
  base, output = small; (base / "helper.mjs").write_text("own fixed helper fixture")
  monkeypatch.setattr(probe, "SOURCES", ("source.py", "helper.mjs"))
  value = probe.prepare(output); assert "helper.mjs" in value["material"]["sources"]
  (base / "helper.mjs").write_text("helper drift")
  with pytest.raises(probe.ProbeError): probe.validate_plan(value, output)
