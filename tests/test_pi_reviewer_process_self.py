"""默认仅fake Popen/selector/signal；不运行自有或第三方真实进程。"""
import importlib.util
import json
import os
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location("reviewer_self_runner", Path(__file__).resolve().parents[1] / "scripts/test-pi-reviewer-process-self.py")
probe = importlib.util.module_from_spec(spec); spec.loader.exec_module(probe)


def observed():
  observations = {}
  for identifier in probe.ALLOW_IDS:
    shared = identifier != "self-model"
    observations[identifier] = {"schema_version": 1, "is_worker": True, "ambient_key_absent": True, "environment_data_absent": True,
      "environment_keys": ["OPENAI_LOG"], "log_off": True, "key_not_in_argv": True, "injected_node_options_absent": True,
      "model": probe.expected_model(identifier), "options": {"maxRetries": 0, "maxTokens": 4096 if shared else 1024, "temperature": 0, "reasoning": "off" if shared else None},
      "wire": {"model": identifier, "max_tokens": 4096 if shared else 1024, "thinking": {"type": "disabled"} if identifier == "shared-deepseek" else None}}
  rows = []
  for name, outcome in probe.CASES:
    called = outcome == "valid"
    rows.append({"case": name, "outcome": outcome, "requests": int(called), "processes": int(called), "raw_events": 2 if called else 0,
      "usage": {"status": "reported" if called else "not-sent", "input_tokens": 5 if called else 0, "output_tokens": 3 if called else 0, "total_tokens": 8 if called else 0},
      "model_identity": probe.expected_identity("shared-text" if name == "shared-text-allow" else "shared-deepseek") if name.startswith("shared-") else None,
      "scope_termination": "not-independently-observed"})
  return {"schema_version": 1, "status": "observed", "sdk": "self-owned-fake-only", "cases": rows, "observations": observations,
    "child_close_observed": True, "child_stdout_bytes": 0, "child_stderr_bytes": 0, "real_model_requests": 0, "product_gate": False}


def fake_outputs(directory, result):
  for name, body in {"result.json": result, **{"sdk-observation-" + identifier + ".json": body for identifier, body in result["observations"].items()}}.items():
    path = directory / "work" / name; path.write_text(json.dumps(body)); path.chmod(0o600)


@pytest.fixture
def materials(tmp_path, monkeypatch):
  root = tmp_path / "repo"; root.mkdir()
  for name in probe.SOURCES:
    path = root / "agents/pi/packages/risk-review/src" / (name + ".ts"); path.parent.mkdir(parents=True, exist_ok=True); path.write_text("// own synthetic source " + name)
  for name in probe.FIXTURES:
    path = root / "tests/fixtures/pi/reviewer-process-self-probe" / (name + ".mjs"); path.parent.mkdir(parents=True, exist_ok=True); path.write_text("// own fixture " + name)
  for name in ("node", "bwrap"):
    path = tmp_path / name; path.write_bytes(b"\x7fELF" + b"self-owned-fake"); path.chmod(0o700); monkeypatch.setattr(probe, name.upper(), path)
  return root, tmp_path


def test_prepare_exact_owned_closure_and_private_work_without_process(materials, monkeypatch):
  root, tmp = materials
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: pytest.fail("prepare spawned"))
  prepared = probe.prepare(root, tmp_parent=tmp)
  directory = Path(prepared["directory"])
  assert directory.name.startswith("agentcfg-reviewer-self-process-")
  assert len(list((directory / "bundle/src").glob("*.ts"))) == 13
  package = json.loads((directory / "bundle/sdk/node_modules/@earendil-works/pi-ai/package.json").read_text())
  assert package["exports"] == {"./api/openai-completions": {"import": "./provider.mjs"}, "./utils/transcript": {"import": "./transcript.mjs"}}
  assert set(p.name for p in (directory / "work").iterdir()) == {"home", "tmp"}
  assert all((path.stat().st_mode & 0o777) == (0o700 if path.is_dir() else 0o600) for path in directory.rglob("*"))
  assert "candidate" not in json.dumps(prepared["manifest"])


@pytest.mark.parametrize("fault", ["source", "fixture", "extra", "link", "mode"])
def test_preflight_bundle_drift_prevents_process(materials, monkeypatch, fault):
  root, tmp = materials; prepared = probe.prepare(root, tmp_parent=tmp); directory = Path(prepared["directory"])
  if fault == "source": (root / "agents/pi/packages/risk-review/src/protocol.ts").write_text("drift")
  if fault == "fixture": (root / "tests/fixtures/pi/reviewer-process-self-probe/probe.mjs").write_text("drift")
  if fault == "extra": (directory / "bundle/extra").write_text("extra")
  if fault == "link": (directory / "bundle/probe.mjs").unlink(); (directory / "bundle/probe.mjs").symlink_to("src/protocol.ts")
  if fault == "mode": (directory / "bundle/probe.mjs").chmod(0o644)
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: pytest.fail("drift spawned"))
  with pytest.raises(probe.ProbeError): probe.run(prepared)


def test_closed_result_preserves_unknown_whole_scope():
  result = probe.verify_result(observed())
  assert result == observed() and result["product_gate"] is False
  assert all(row["scope_termination"] == "not-independently-observed" for row in result["cases"])


@pytest.mark.parametrize("fault", ["extra", "version", "scope", "zero-usage", "raw", "send", "observation", "child", "log", "model", "product", "missing"])
def test_result_oracle_rejects_false_or_private_claims(fault):
  value = observed()
  if fault == "extra": value["raw_error"] = "PRIVATE"
  if fault == "version": value["schema_version"] = True
  if fault == "scope": value["cases"][0]["scope_termination"] = "observed"
  if fault == "zero-usage": value["cases"][1]["usage"]["status"] = "unknown"
  if fault == "raw": value["cases"][0]["raw_events"] = 1
  if fault == "send": value["cases"][1]["requests"] = 1
  if fault == "observation": value["observations"]["self-model"]["ambient_key_absent"] = False
  if fault == "child": value["child_close_observed"] = False
  if fault == "log": value["child_stderr_bytes"] = 1
  if fault == "model": value["real_model_requests"] = 1
  if fault == "product": value["product_gate"] = True
  if fault == "missing": value["cases"].pop()
  with pytest.raises(probe.ProbeError): probe.verify_result(value)


@pytest.fixture
def fake_capture(monkeypatch):
  events = []; pending = []; waits = []; clock = [0]; running = [True]; native_read = probe.os.read
  class Pipe:
    def __init__(self, fd): self.fd = fd; self.closed = False
    def fileno(self): return self.fd
    def close(self): self.closed = True
  child = SimpleNamespace(pid=99887766, stdout=Pipe(901), stderr=Pipe(902))
  def wait(timeout):
    events.append(("wait", timeout)); value = waits.pop(0) if waits else 0
    if isinstance(value, BaseException): raise value
    running[0] = False; return value
  child.wait = wait; child.poll = lambda: None if running[0] else 0
  class Selector:
    def __init__(self): self.mapping = {}
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def register(self, stream, event, name): self.mapping[stream.fd] = SimpleNamespace(fileobj=stream, data=name)
    def unregister(self, stream): del self.mapping[stream.fd]
    def get_map(self): return self.mapping
    def select(self, timeout):
      if not pending: clock[0] += 30; return []
      return [(self.mapping[pending[0][0]], probe.selectors.EVENT_READ)]
  def read(fd, size):
    if fd not in (901, 902): return native_read(fd, size)  # 仅静态临时材料的真实文件FD。
    assert size == 8192
    expected, value = pending.pop(0); assert fd == expected
    if isinstance(value, BaseException): raise value
    return value
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: (events.append(("popen", a, k)) or child))
  monkeypatch.setattr(probe.selectors, "DefaultSelector", Selector)
  monkeypatch.setattr(probe.os, "read", read)
  monkeypatch.setattr(probe.os, "set_blocking", lambda fd, value: events.append(("blocking", fd, value)))
  monkeypatch.setattr(probe.os, "killpg", lambda pid, sig: (events.append(("signal", pid, sig)) if pid == child.pid else pytest.fail("foreign PG")))
  monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
  return SimpleNamespace(events=events, pending=pending, waits=waits, clock=clock, child=child)


@pytest.mark.parametrize("fault", [None, "stdout-flood", "stderr-flood", "timeout", "read", "post-source", "summary", "result"])
def test_fake_run_capture_lifecycle_closed_failure_and_replay(materials, fake_capture, fault):
  root, tmp = materials; f = fake_capture; prepared = probe.prepare(root, tmp_parent=tmp); directory = Path(prepared["directory"])
  result = observed(); summary = {"schema_version": 1, "status": "observed", "cases": 8, "product_gate": False}
  if fault == "result": result["product_gate"] = True
  if fault == "summary": summary["cases"] = 0
  fake_outputs(directory, result)
  for path in (directory / "work").glob("*.json"): path.chmod(0o600)
  if fault in ("stdout-flood", "stderr-flood"):
    f.pending.extend([(901 if fault == "stdout-flood" else 902, b"x" * 8192)] * 9)
    f.waits.extend([probe.subprocess.TimeoutExpired("own", 5), 137])
  elif fault == "read": f.pending.append((901, OSError("PRIVATE_READ")))
  elif fault != "timeout": f.pending.extend([(901, json.dumps(summary).encode()), (902, b"PRIVATE_STDERR_DROP"), (901, b""), (902, b"")])
  # 初始work必须空。只由fake Popen写结果，不绕开preflight。
  def popen(argv, **kwargs):
    f.events.append(("popen", argv, kwargs))
    fake_outputs(directory, result)
    if fault == "post-source": (root / "agents/pi/packages/risk-review/src/protocol.ts").write_text("post-drift")
    return f.child
  probe.subprocess.Popen = popen
  for path in (directory / "work").glob("*.json"): path.unlink()
  if fault is None: assert probe.run(prepared)["status"] == "observed"
  else:
    with pytest.raises(probe.ProbeError): probe.run(prepared)
  execution = json.loads((directory / "execution.json").read_text())
  assert execution["product_gate"] is False and execution["scope_termination"] == "not-independently-observed"
  assert "PRIVATE" not in json.dumps(execution)
  assert execution["status"] == ("observed" if fault is None else "failed")
  assert f.child.stdout.closed and f.child.stderr.closed
  call = next(event for event in f.events if event[0] == "popen")
  assert call[2] == {"env": {}, "cwd": "/tmp", "stdin": probe.subprocess.DEVNULL, "stdout": probe.subprocess.PIPE, "stderr": probe.subprocess.PIPE, "close_fds": True, "start_new_session": True}
  argv = call[1]; assert str(probe.BWRAP) == argv[0]; assert argv[-3:] == ["/node/bin/node", "--experimental-import-meta-resolve", "/probe/probe.mjs"]
  assert "--unshare-all" in argv and "--clearenv" not in argv and "--chdir" in argv
  if fault in ("stdout-flood", "stderr-flood", "timeout"):
    assert ("signal", f.child.pid, probe.signal.SIGTERM) in f.events
  if fault in ("stdout-flood", "stderr-flood"):
    assert [event[2] for event in f.events if event[0] == "signal"] == [probe.signal.SIGTERM, probe.signal.SIGKILL]
  with pytest.raises(probe.ProbeError): probe.run(prepared)
  assert len([event for event in f.events if event[0] == "popen"]) == 1


def test_initial_extra_work_file_and_top_level_directory_rejected(materials, monkeypatch):
  root, tmp = materials
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: pytest.fail("unclosed material spawned"))
  for target in ("work/home/secret", "unknown"):
    prepared = probe.prepare(root, tmp_parent=tmp); path = Path(prepared["directory"]) / target
    path.write_text("OWN_SYNTHETIC_PRIVATE"); path.chmod(0o600)
    with pytest.raises(probe.ProbeError): probe.run(prepared)


def test_source_replacement_after_pin_is_rejected_before_copy(materials, monkeypatch):
  root, tmp = materials; original = probe.source_bytes
  def replace_source(path, expected):
    path.rename(path.with_suffix(".old")); path.write_text("replaced-own-source")
    return original(path, expected)
  monkeypatch.setattr(probe, "source_bytes", replace_source)
  with pytest.raises(probe.ProbeError): probe.prepare(root, tmp_parent=tmp)


def test_capture_cleanup_timeout_closes_pipes_even_if_scope_stays_unknown(fake_capture):
  f = fake_capture; f.pending.append((901, OSError("PRIVATE_READ"))); f.waits.append(probe.subprocess.TimeoutExpired("own", 5))
  with pytest.raises(probe.subprocess.TimeoutExpired): probe.capture(["own-fake"])
  assert f.child.stdout.closed and f.child.stderr.closed
  assert f.events[-2:] == [("signal", f.child.pid, probe.signal.SIGKILL), ("wait", 5)]


def test_capture_initialization_error_cleans_only_owned_group(fake_capture, monkeypatch):
  f = fake_capture
  def failed_blocking(fd, value): raise OSError("OWN_PRIVATE_SETUP")
  monkeypatch.setattr(probe.os, "set_blocking", failed_blocking)
  with pytest.raises(OSError): probe.capture(["own-fake"])
  assert f.child.stdout.closed and f.child.stderr.closed
  assert f.events[-2:] == [("signal", f.child.pid, probe.signal.SIGKILL), ("wait", 5)]


def test_legacy_bwrap_template_relies_on_empty_popen_environment(materials, fake_capture, monkeypatch):
  """本机已有公开bwrap模板不支持clearenv；父env={}仍拒绝ambient继承。"""
  root, tmp = materials; f = fake_capture; prepared = probe.prepare(root, tmp_parent=tmp)
  directory = Path(prepared["directory"])
  def supported_popen(argv, **kwargs):
    if "--clearenv" in argv: raise OSError("OWN_UNSUPPORTED_OPTION")
    assert kwargs["env"] == {}
    settings = {argv[index + 1]: argv[index + 2] for index, item in enumerate(argv) if item == "--setenv"}
    assert settings == {"HOME": "/work/home", "TMPDIR": "/work/tmp", "PATH": "/nonexistent", "OPENAI_LOG": "off"}
    f.events.append(("popen", argv, kwargs)); return f.child
  monkeypatch.setattr(probe.subprocess, "Popen", supported_popen)
  f.pending.extend([(901, b""), (902, b"")])
  facts, output = probe.capture(probe.invocation(directory))
  assert facts["exit_code"] == 0 and facts["capture_failed"] is False and output == b""


def test_shared_dependencies_are_in_the_prepared_explicit_closure():
  # 当前桥静态imports已需要这些来源；漏复制会在新进程import前失败。
  assert {"shared-model", "shared-sdk-contract", "shared-request-wire"} <= set(probe.SOURCES)


def test_explicit_sources_close_current_own_relative_imports():
  import re
  base = probe.ROOT / "agents/pi/packages/risk-review/src"
  edges = {}
  for name in probe.SOURCES:
    text = (base / (name + ".ts")).read_text()
    edges[name] = set(re.findall(r'(?:from\s*|import\s*\()(["\'])\./([^"\']+)\1', text))
    for _, target in edges[name]:
      assert target.endswith(".ts") and target[:-3] in probe.SOURCES, (name, target)
  assert any(target == "shared-sdk-contract.ts" for _, target in edges["sdk-process"])
  assert any(target == "shared-request-wire.ts" for _, target in edges["transport"])


@pytest.mark.parametrize("fault", ["missing-observations", "extra-observation", "native-cap", "request-cap", "name", "reasoning", "image", "thinking", "marker", "process-count", "worker", "unknown-scope", "bool-cost", "secret-option"])
def test_shared_result_oracle_requires_actual_safe_model_and_exact_variant(fault):
  value = observed(); record = value["observations"]["shared-deepseek"]
  if fault == "missing-observations": del value["observations"]["shared-text"]
  if fault == "extra-observation": value["observations"]["unknown"] = record
  if fault == "native-cap": record["model"]["maxTokens"] = 4096
  if fault == "request-cap": record["options"]["maxTokens"] = 384000
  if fault == "name": record["model"]["name"] = "shared-deepseek"
  if fault == "reasoning": record["model"]["reasoning"] = False
  if fault == "image": record["model"]["input"] = ["text"]
  if fault == "thinking": record["wire"]["thinking"] = None
  if fault == "marker": value["cases"][5]["model_identity"] = "a" * 64
  if fault == "process-count": value["cases"][7]["processes"] = 1
  if fault == "worker": record["is_worker"] = False
  if fault == "unknown-scope": value["cases"][5]["scope_termination"] = "observed"
  if fault == "bool-cost": record["model"]["cost"]["input"] = True
  if fault == "secret-option": record["options"]["apiKey"] = "SYNTHETIC_PRIVATE"
  with pytest.raises(probe.ProbeError) as error: probe.verify_result(value)
  assert "SYNTHETIC_PRIVATE" not in str(error.value)


def test_duplicate_nested_safe_model_keys_are_rejected():
  with pytest.raises(probe.ProbeError): probe.decode(b'{"model":{"maxTokens":384000,"maxTokens":4096}}')
