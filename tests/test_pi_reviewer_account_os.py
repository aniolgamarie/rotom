"""只准备自有材料/验证数据，默认不启动worker、namespace或第三方。"""
import importlib.util
from pathlib import Path
from copy import deepcopy
import json
import hashlib
import pytest

ROOT = Path(__file__).resolve().parents[1]

@pytest.fixture
def probe():
  spec = importlib.util.spec_from_file_location("account_os_probe", ROOT / "scripts/test-pi-reviewer-account-os.py")
  value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
  return value


def result(probe):
  return {"schema_version": 1, "status": "observed", "cases": [
    {"case": name, "status": "observed", "claim_returns": 1 if i == 0 else 0,
      "fake_dispatches": 1 if i == 0 else 0, "attempt_claimed": i != 1,
      "sentinel_state": "updating" if i in (1, 2, 3) else "ready",
      "reopen": "conflict" if i in (0, 4) else "recovery-required" if i in (1, 2, 3) else "deny-locked",
      "synthetic_requests": 1 if i == 5 else 0, "actual_http_requests": 0, "actual_model_requests": 0}
    for i, name in enumerate(probe.CASES)], "scope_termination": "not-independently-observed", "product_gate": False}


def test_closed_oracle_accepts_six_independent_cases(probe):
  value = result(probe)
  assert probe.verify_result(value) == value

@pytest.mark.parametrize("kind", ["extra", "bool", "missing", "order", "duplicate", "fake-dispatch", "model", "recovery", "product", "scope"])
def test_oracle_rejects_wrong_facts(probe, kind):
  value = result(probe)
  if kind == "extra": value["secret"] = "synthetic"
  if kind == "bool": value["cases"][0]["claim_returns"] = True
  if kind == "missing": value["cases"].pop()
  if kind == "order": value["cases"].reverse()
  if kind == "duplicate": value["cases"][1] = deepcopy(value["cases"][0])
  if kind == "fake-dispatch": value["cases"][3]["fake_dispatches"] = 1
  if kind == "model": value["cases"][5]["actual_model_requests"] = 1
  if kind == "recovery": value["cases"][2]["reopen"] = "conflict"
  if kind == "product": value["product_gate"] = True
  if kind == "scope": value["scope_termination"] = "terminated"
  with pytest.raises(probe.ProbeError): probe.verify_result(value)


def test_duplicate_json_never_accepted(probe):
  with pytest.raises(probe.ProbeError): probe.decode(b'{"schema_version":1,"schema_version":1}')


def test_prepare_is_static_minimal_and_fixed_invocation(probe, tmp_path, monkeypatch):
  def forbidden(*args, **kwargs): raise AssertionError("process forbidden")
  monkeypatch.setattr(probe.subprocess, "Popen", forbidden)
  prepared = probe.prepare(ROOT, tmp_parent=tmp_path)
  directory = probe.preflight(prepared)
  assert prepared["manifest"]["self_worker_started"] is False
  assert "pi_reviewer_account" in prepared["manifest"]["sources"]
  assert len(prepared["manifest"]["sources"]) < 30
  assert not (directory / "started.json").exists()
  argv = probe.invocation(directory)
  assert "--unshare-all" in argv and "--clearenv" not in argv
  index = argv.index("PWD")
  assert argv[index - 1:index + 2] == ["--setenv", "PWD", "/work"]
  assert argv[-5:] == ["/usr/bin/python3.11", "-I", "-B", "-S", "/probe/worker.py"]
  assert not any("account_home" in arg for arg in argv)
  assert set((directory / "work").iterdir()) == {directory / "work/home", directory / "work/tmp"}

@pytest.mark.parametrize("kind", ["extra", "mode", "link", "started", "source"])
def test_preflight_rejects_material_drift(probe, tmp_path, monkeypatch, kind):
  prepared = probe.prepare(ROOT, tmp_parent=tmp_path); directory = Path(prepared["directory"])
  if kind == "extra": (directory / "bundle/extra").write_text("x")
  if kind == "mode": (directory / "bundle/worker.py").chmod(0o644)
  if kind == "link": (directory / "work/link").symlink_to(tmp_path)
  if kind == "started": probe.write_new(directory / "started.json", b"{}")
  if kind == "source": monkeypatch.setattr(probe, "sources", lambda _: {})
  with pytest.raises(probe.ProbeError): probe.preflight(prepared)


def test_capture_failure_is_unknown_and_never_replayed(probe, tmp_path, monkeypatch):
  prepared = probe.prepare(ROOT, tmp_parent=tmp_path); directory = Path(prepared["directory"])
  calls = []
  def failed(argv): calls.append(argv); raise RuntimeError("synthetic-private")
  monkeypatch.setattr(probe, "capture", failed)
  with pytest.raises(probe.ProbeError): probe.run(prepared)
  execution = json.loads((directory / "execution.json").read_bytes())
  assert execution["status"] == "failed" and execution["self_worker_started"] is None
  assert execution["scope_termination"] == "not-independently-observed"
  assert "synthetic-private" not in (directory / "execution.json").read_text()
  with pytest.raises(probe.ProbeError): probe.run(prepared)
  assert len(calls) == 1

@pytest.fixture
def fake_capture(probe, monkeypatch):
  from types import SimpleNamespace
  events, pending, waits = [], [], []; clock = [0]; alive = [True]
  class Pipe:
    def __init__(self, fd): self.fd = fd; self.closed = False
    def fileno(self): return self.fd
    def close(self): self.closed = True
  child = SimpleNamespace(pid=99118822, stdout=Pipe(910), stderr=Pipe(911))
  def wait(timeout):
    events.append(("wait", timeout)); value = waits.pop(0) if waits else 0
    if isinstance(value, BaseException): raise value
    alive[0] = False; return value
  child.wait = wait; child.poll = lambda: None if alive[0] else 0
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
  monkeypatch.setattr(probe.subprocess, "Popen", lambda *a, **k: (events.append(("popen", a, k)) or child))
  monkeypatch.setattr(probe.selectors, "DefaultSelector", Selector)
  def read(fd, size):
    expected, value = pending.pop(0); assert fd == expected and size == 8192
    if isinstance(value, Exception): raise value
    return value
  monkeypatch.setattr(probe.os, "read", read)
  monkeypatch.setattr(probe.os, "set_blocking", lambda *_: None)
  monkeypatch.setattr(probe.os, "killpg", lambda pid, sig: (events.append(("signal", sig)) if pid == child.pid else pytest.fail("foreign PG")))
  monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
  return SimpleNamespace(events=events, pending=pending, waits=waits, child=child)


def test_capture_empty_env_closed_fds_stdin_and_stderr_drop(probe, fake_capture):
  fake_capture.pending[:] = [(910, b"{}"), (911, b"synthetic-private"), (910, b""), (911, b"")]
  facts, stdout = probe.capture(["fixed"])
  assert stdout == b"{}" and facts["stderr_bytes"] == len(b"synthetic-private")
  kwargs = fake_capture.events[0][2]
  assert kwargs["env"] == {} and kwargs["stdin"] == probe.subprocess.DEVNULL and kwargs["close_fds"] is True and kwargs["start_new_session"] is True
  assert fake_capture.child.stdout.closed and fake_capture.child.stderr.closed

@pytest.mark.parametrize("kind", ["stdout", "stderr", "timeout", "read", "initialize", "kill-wait"])
def test_capture_failure_bounded_stop_own_group_and_close(probe, fake_capture, monkeypatch, kind):
  f = fake_capture
  if kind in ("stdout", "stderr"):
    f.pending[:] = [(910 if kind == "stdout" else 911, b"x" * 8192)] * 9
  if kind == "read": f.pending[:] = [(910, OSError("synthetic-private"))]
  if kind == "initialize": monkeypatch.setattr(probe.os, "set_blocking", lambda *_: (_ for _ in ()).throw(OSError("synthetic-private")))
  f.waits[:] = [probe.subprocess.TimeoutExpired("fixed", 5)]
  if kind == "kill-wait": f.waits.append(probe.subprocess.TimeoutExpired("fixed", 5))
  try: facts, output = probe.capture(["fixed"])
  except Exception: pass
  assert f.child.stdout.closed and f.child.stderr.closed
  signals = [entry[1] for entry in f.events if entry[0] == "signal"]
  assert signals == [probe.signal.SIGTERM, probe.signal.SIGKILL]
  assert len([entry for entry in f.events if entry[0] == "wait"]) == 2


def artifacts(probe, directory):
  """合成完整工件供父oracle测试；不是worker/OS故障执行证据。"""
  rows = result(probe)
  binding = {"operation_id": "0" * 31 + "1", "request_id": f"{101:032x}", "operation_digest": "a" * 64, "context_digest": "b" * 64, "reviewer_identity": "c" * 64}
  scope = {"session_scope": "d" * 32, "intent_ref": "e" * 32}
  pricing = {"identity": "f" * 64, "currency": "USD", "input_units_per_million": 1000000, "output_units_per_million": 2000000, "cache_read_units_per_million": 500000, "cache_write_units_per_million": 3000000}
  limits = {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000}
  for i, report in enumerate(rows["cases"]):
    base = directory / "work/cases" / report["case"]; anchor = base / "account/.agentcfg-workspaces"
    for target in (anchor / "reviewer-budget",): target.mkdir(parents=True, mode=0o700)
    row = {"binding": binding, "scope": scope, "pricing": pricing, "token_limits": {"input_tokens": 100, "output_tokens": 10}, "reservation_units": 320,
      "attempt_claimed": report["attempt_claimed"], "send_state": "committed" if i == 5 else "reserved", "requests": 1 if i == 5 else 0,
      "outcome": "valid" if i == 5 else None, "decision": "deny" if i == 5 else None, "reason_code": "outside-user-scope" if i == 5 else None,
      "usage": None, "final_usage": False, "process_terminated": False, "settled_units": None}
    def put(path, value): probe.write_new(path, probe.encode(value))
    def physical(path):
      info = path.stat(); return {"dev": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}
    account_identity, registry_identity, budget_identity = physical(base / "account"), physical(anchor), physical(anchor / "reviewer-budget")
    put(anchor / "registry.json", {"schema_version": 1, "coordinator": {"canonical_path": "/work/cases/" + report["case"] + "/account", "account_identity": account_identity, "registry_identity": registry_identity}, "roots": []})
    ledger = {"schema_version": 1, "limits": limits, "rows": {binding["operation_id"]: row}}
    ledger_path = anchor / "reviewer-budget/reviewer-ledger.json"
    probe.write_new(ledger_path, json.dumps(ledger, sort_keys=True, separators=(",", ":")).encode("ascii"))
    info = ledger_path.stat(); identity = [info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns]
    old = deepcopy(ledger)
    if i in (2, 3): old["rows"][binding["operation_id"]]["attempt_claimed"] = False
    sha = hashlib.sha256(json.dumps(old, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
    put(anchor / "reviewer-budget.json", {"schema_version": 1, "state": report["sentinel_state"], "account_identity": account_identity, "registry_identity": registry_identity, "budget_identity": budget_identity, "ledger_identity": identity, "ledger_sha256": sha})
    put(base / ("deny-check.json" if i == 5 else "reopen.json"), {"reopen": report["reopen"]})
    if i in (1, 2, 3, 4): put(base / "cut.json", {"case": report["case"], "exit_code": 70 + i})
    if i == 0:
      for name in ("ready-0", "ready-1", "go"):
        put(base / name, {"go" if name == "go" else "ready": True})
      for j, claimed in enumerate((True, False)):
        put(base / ("claim-" + str(j) + ".json"), {"claimed": claimed,
          "conflict": None if claimed else "REVIEW_ATTEMPT_ALREADY_CLAIMED"})
      put(base / "fake-dispatch", {"synthetic": True, "actual_http_requests": 0, "actual_model_requests": 0})
    if i == 5:
      snapshot = {"schema_version": 1, "limits": limits, "record_count": 1, "committed_calls": 1, "reserved_calls": 0, "observed_requests": 0, "unknown_requests": 1,
        "reserved_cost_units": 320, "reported_estimated_cost_units": 0, "charged_cost_units": 320, "over_budget": False, "cost_scope": "reported-estimate-or-conservative-reservation", "product_gate": False}
      put(base / "unknown.json", {"row": {**row, "requests": None, "outcome": None, "decision": None, "reason_code": None}, "snapshot": snapshot})
  return rows


def test_raw_artifacts_not_just_worker_summary(probe, tmp_path):
  value = artifacts(probe, tmp_path)
  probe.verify_artifacts(tmp_path, value)
  ledger = tmp_path / "work/cases/claimed-before-ready/account/.agentcfg-workspaces/reviewer-budget/reviewer-ledger.json"
  state = json.loads(ledger.read_bytes()); state["rows"]["0" * 31 + "1"]["attempt_claimed"] = False
  ledger.write_text(json.dumps(state))
  with pytest.raises(probe.ProbeError): probe.verify_artifacts(tmp_path, value)


def test_raw_fixture_reservation_matches_actual_owned_ledger_cache_upper_bound(probe, tmp_path):
  from agentcfg.pi_reviewer_account import ReviewerAccountLedger
  value = artifacts(probe, tmp_path)
  ledger_path = tmp_path / "work/cases/concurrent-claim/account/.agentcfg-workspaces/reviewer-budget/reviewer-ledger.json"
  fixture_row = json.loads(ledger_path.read_bytes())["rows"]["0" * 31 + "1"]
  home = tmp_path / "independent-account"; home.mkdir(mode=0o700)
  ledger = ReviewerAccountLedger(account_home=home,
    limits={"currency": "USD", "max_calls": 20, "max_cost_units": 1000000})
  actual = ledger.reserve(**{key: fixture_row[key] for key in ("binding", "scope", "pricing", "token_limits")})
  # 独立固定算例：100×最高输入价3+10×输出价2，不能把未知缓存当优惠。
  assert actual["reservation_units"] == 320
  assert fixture_row["reservation_units"] == actual["reservation_units"]


@pytest.mark.parametrize("conflict", ["REVIEW_ACCOUNT_BUSY", "REVIEW_ATTEMPT_ALREADY_CLAIMED"])
def test_concurrent_loser_records_only_trusted_preclaim_or_tombstone_conflict(probe, tmp_path, conflict):
  value = artifacts(probe, tmp_path)
  path = tmp_path / "work/cases/concurrent-claim/claim-1.json"
  path.write_text(json.dumps({"claimed": False, "conflict": conflict}))
  probe.verify_artifacts(tmp_path, value)


@pytest.mark.parametrize("claim", [{"claimed": False, "conflict": "REVIEW_ACCOUNT_INVALID"},
  {"claimed": True, "conflict": "REVIEW_ACCOUNT_BUSY"}, {"claimed": False, "conflict": None}])
def test_unknown_or_inconsistent_claim_conflict_never_accepted(probe, tmp_path, claim):
  value = artifacts(probe, tmp_path)
  path = tmp_path / "work/cases/concurrent-claim/claim-1.json"
  path.write_text(json.dumps(claim))
  with pytest.raises(probe.ProbeError): probe.verify_artifacts(tmp_path, value)

@pytest.mark.parametrize("kind", ["cut", "unknown-count", "unknown-requests", "unknown-extra", "binding", "second-claim"])
def test_raw_intermediate_and_binding_tampering_fails(probe, tmp_path, kind):
  value = artifacts(probe, tmp_path)
  if kind == "cut":
    path = tmp_path / "work/cases/ready-after-replace/cut.json"; state = json.loads(path.read_bytes()); state["exit_code"] = 73
  elif kind.startswith("unknown"):
    path = tmp_path / "work/cases/unknown-then-deny/unknown.json"; state = json.loads(path.read_bytes())
    if kind == "unknown-count": state["snapshot"]["unknown_requests"] = 0
    if kind == "unknown-requests": state["row"]["requests"] = 1
    if kind == "unknown-extra": state["secret"] = "synthetic"
  elif kind == "binding":
    path = tmp_path / "work/cases/concurrent-claim/account/.agentcfg-workspaces/reviewer-budget/reviewer-ledger.json"
    state = json.loads(path.read_bytes()); state["rows"]["0" * 31 + "1"]["binding"]["operation_digest"] = "f" * 64
  else:
    path = tmp_path / "work/cases/concurrent-claim/claim-1.json"; state = {"claimed": True}
  path.write_text(json.dumps(state))
  with pytest.raises(probe.ProbeError): probe.verify_artifacts(tmp_path, value)

@pytest.mark.parametrize("fault", [None, "summary", "result", "postbundle", "raw"])
def test_fake_success_requires_capture_result_original_rows_and_postflight(probe, tmp_path, monkeypatch, fault):
  prepared = probe.prepare(ROOT, tmp_parent=tmp_path); directory = Path(prepared["directory"])
  def captured(argv):
    value = artifacts(probe, directory)
    for i, case in enumerate(probe.CASES):
      base = directory / "work/cases" / case
      probe.write_new(base / "account/.agentcfg-workspaces/reviewer-budget/instance.lock", b"")
    for path in (directory / "work").rglob("*"):
      if path.is_dir(): path.chmod(0o700)
    if fault == "result": value["cases"][0]["fake_dispatches"] = 0
    if fault == "raw":
      ledger = directory / "work/cases/ready-after-replace/account/.agentcfg-workspaces/reviewer-budget/reviewer-ledger.json"
      ledger.write_text("{}")
    probe.write_new(directory / "work/result.json", probe.encode(value))
    if fault == "postbundle": probe.write_new(directory / "bundle/extra", b"drift")
    summary = probe.encode({"schema_version": 1, "status": "observed", "cases": 5 if fault == "summary" else 6, "product_gate": False})
    return {"stdout_bytes": len(summary), "stderr_bytes": 0, "exit_code": 0, "capture_failed": False}, summary
  monkeypatch.setattr(probe, "capture", captured)
  if fault is None:
    assert probe.run(prepared)["status"] == "observed"
  else:
    with pytest.raises(probe.ProbeError): probe.run(prepared)
  execution = json.loads((directory / "execution.json").read_bytes())
  assert execution["status"] == ("observed" if fault is None else "failed")
  assert execution["product_gate"] is False and execution["scope_termination"] == "not-independently-observed"
  with pytest.raises(probe.ProbeError): probe.run(prepared)

@pytest.mark.parametrize("field", ["dependencies", "dependency_directories", "worker", "binaries", "controller"])
def test_source_and_system_bindings_not_accepted_from_mutated_manifest(probe, tmp_path, field):
  prepared = probe.prepare(ROOT, tmp_parent=tmp_path); directory = Path(prepared["directory"])
  prepared["manifest"][field] = {}
  (directory / "manifest.json").write_bytes(probe.encode(prepared["manifest"]))
  with pytest.raises(probe.ProbeError): probe.preflight(prepared)

@pytest.fixture
def worker_module():
  spec = importlib.util.spec_from_file_location("account_os_worker", ROOT / "tests/fixtures/pi/reviewer-account-os/worker.py")
  value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
  return value


def test_failure_diagnostic_never_includes_environment_values_or_raw_argv(worker_module, monkeypatch):
  value = worker_module.diagnostic("environment", {"PWD": "/work", "OPENAI_API_KEY": "SYNTHETIC_PRIVATE"},
    ["/probe/worker.py", "SYNTHETIC_ARGV_PRIVATE"])
  raw = json.dumps(value)
  assert "SYNTHETIC_PRIVATE" not in raw and "SYNTHETIC_ARGV_PRIVATE" not in raw
  assert value["environment_keys"] == ["OPENAI_API_KEY", "PWD"]
  assert value["pwd_present"] is True and value["pwd_matches_chdir"] is True
  assert value["environment_matches"] is False and value["argv"]["role_shape"] is False


@pytest.mark.parametrize("fault", ["phase", "secret", "bool-count", "extra-env", "overlong", "product"])
def test_parent_diagnostic_is_closed_bounded_and_fixed(probe, worker_module, fault):
  value = worker_module.diagnostic("environment", worker_module.ENV, ["/probe/worker.py"])
  if fault == "phase": value["phase"] = "SYNTHETIC_PRIVATE_EXCEPTION"
  if fault == "secret": value["exception"] = "SYNTHETIC_PRIVATE"
  if fault == "bool-count": value["argv"]["count"] = True
  if fault == "extra-env": value["environment_values"] = {"secret": "SYNTHETIC_PRIVATE"}
  if fault == "overlong": value["environment_keys"] = ["x" * 1000]
  if fault == "product": value["product_gate"] = True
  with pytest.raises(probe.ProbeError): probe.verify_diagnostic(value)


def test_fake_run_retains_valid_failure_phase_not_success(probe, worker_module, tmp_path, monkeypatch):
  prepared = probe.prepare(ROOT, tmp_parent=tmp_path); directory = Path(prepared["directory"])
  value = worker_module.diagnostic("environment", {**worker_module.ENV, "PWD": "/work"}, ["/probe/worker.py"])
  def captured(argv):
    probe.write_new(directory / "work/failure.json", probe.encode(value))
    return {"exit_code": 5, "stdout_bytes": 0, "stderr_bytes": 0, "capture_failed": False}, b""
  monkeypatch.setattr(probe, "capture", captured)
  with pytest.raises(probe.ProbeError): probe.run(prepared)
  execution = json.loads((directory / "execution.json").read_bytes())
  assert execution["status"] == "failed" and execution["diagnostic"] == value
  assert execution["self_worker_started"] is None and execution["product_gate"] is False


@pytest.mark.parametrize("kind", ["fixed", "wrong-pwd", "missing-pwd", "extra"])
def test_fake_entry_requires_exact_fixed_environment_including_pwd(worker_module, tmp_path, monkeypatch, kind):
  monkeypatch.setattr(worker_module.sys, "argv", ["/probe/worker.py"])
  environment = dict(worker_module.ENV)
  if kind == "wrong-pwd": environment["PWD"] = "/SYNTHETIC_PRIVATE"
  if kind == "missing-pwd": environment.pop("PWD")
  if kind == "extra": environment["OPENAI_API_KEY"] = "SYNTHETIC_PRIVATE"
  monkeypatch.setattr(worker_module.os, "environ", environment)
  monkeypatch.setattr(worker_module.sys, "path", list(worker_module.sys.path))
  seen, coordinated = [], []
  monkeypatch.setattr(worker_module, "record_failure", lambda value: seen.append(value))
  monkeypatch.setattr(worker_module, "coordinate", lambda: coordinated.append(True))
  assert worker_module.entry() == (0 if kind == "fixed" else 5)
  assert coordinated == ([True] if kind == "fixed" else [])
  if kind == "fixed": assert seen == []
  else:
    assert seen[0]["phase"] == "environment"
    assert "SYNTHETIC_PRIVATE" not in json.dumps(seen)


def test_diagnostic_bounds_keys_and_argv_without_secret_values(worker_module, probe):
  environment = {"KEY_" + str(i): "SYNTHETIC_PRIVATE" for i in range(100)}
  environment["invalid key\n"] = "SYNTHETIC_PRIVATE"
  value = worker_module.diagnostic("argv", environment, ["SYNTHETIC_PRIVATE"] * 100)
  assert len(value["environment_keys"]) == 32 and value["environment_keys_truncated"] is True
  assert value["argv"]["count"] == 16 and value["argv"]["count_truncated"] is True
  assert len(probe.encode(value)) < 8192 and "SYNTHETIC_PRIVATE" not in json.dumps(value)
  assert probe.verify_diagnostic(value) == value


def test_claim_children_finish_constructor_before_common_go_without_constructor_contention(worker_module, tmp_path, monkeypatch):
  from types import SimpleNamespace
  children, started = [], []
  base = tmp_path / "case"; base.mkdir(mode=0o700)
  monkeypatch.setattr(worker_module, "paths", lambda case: (base, tmp_path / "account"))
  def start(case, role, index):
    assert case == "concurrent-claim" and role == "claim"
    # 如果第二构造提前进入，假账户LOCK_NB会明确冲突。
    if index == 1: assert (base / "ready-0").exists()
    started.append(index)
    return SimpleNamespace(poll=lambda: None)
  def complete_constructor(delay):
    (base / ("ready-" + str(started[-1]))).write_text("ready")
  monkeypatch.setattr(worker_module, "start", start)
  monkeypatch.setattr(worker_module.time, "sleep", complete_constructor)
  pair = worker_module.ready_claim_pair("concurrent-claim", children)
  assert pair == children and len(pair) == 2 and started == [0, 1]
  assert all((base / ("ready-" + str(index))).exists() for index in (0, 1))
  assert not (base / "go").exists()
