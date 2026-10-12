"""公开scope探针父边界：全为临时合成材料/假capture，零SDK与进程。"""
from copy import deepcopy
import hashlib
import json
import os
import stat

import pytest

from agentcfg import pi_intent_scope_probe as probe
from agentcfg import pi_reviewer_sdk_probe as shared
from agentcfg.schema import ConfigError
from agentcfg.paths import PathError


@pytest.fixture
def materials(tmp_path, monkeypatch):
  root = tmp_path / "repo"
  root.mkdir(mode=0o700)
  for name in (*probe.SOURCES, *probe.CONTROLLERS):
    path = root / name
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(b"self-owned inert synthetic source\n")
  candidate = root / "candidate"
  candidate.mkdir(mode=0o700)
  lock = candidate / "package-lock.json"
  lock.write_bytes(b'{"name":"synthetic-only"}\n')
  for name, version in (("@earendil-works/pi-coding-agent", "1.0.1"), ("@earendil-works/pi-ai", "1.0.2"), ("openai", "7.19.0")):
    directory = candidate / "node_modules" / name
    directory.mkdir(mode=0o700, parents=True)
    (directory / "package.json").write_text(json.dumps({"name": name, "version": version}))
  node = root / "node"
  (node / "bin").mkdir(mode=0o700, parents=True)
  for path in (node / "bin/node", root / "bwrap", root / "timeout"):
    path.write_bytes(b"not-a-real-program\n")
    path.chmod(0o700)
  patches = {"ROOT": root, "CANDIDATE": candidate, "NODE": node, "BWRAP": root / "bwrap", "TIMEOUT": root / "timeout"}
  for module in (probe, shared):
    for name, value in patches.items():
      monkeypatch.setattr(module, name, value)
  monkeypatch.setattr(shared, "LOCK_SHA", hashlib.sha256(lock.read_bytes()).hexdigest())
  def forbidden(*args, **kwargs):
    pytest.fail("prepare/preflight must not capture or launch")
  monkeypatch.setattr(probe, "capture", forbidden)
  return {"root": root, "candidate": candidate, "node": node, "path": tmp_path / "prepared"}


def observations():
  # 独立固定oracle；不从生产EXPECTED反向生成正控。
  rows = [
    ("confirmed-idle", 1, 1, 1, 2, 1, 0, "settled"),
    ("declined", 1, 0, 0, 0, 0, 0, "declined"),
    ("no-ui", 0, 0, 0, 0, 0, 0, "unavailable"),
    ("base", 0, 0, 0, 0, 0, 0, "not-called"),
    ("off", 0, 0, 0, 0, 0, 0, "not-called"),
    ("unrelated-input", 0, 0, 0, 2, 0, 1, None),
    ("nested-follow-up", 1, 1, 1, 4, 1, 1, "retired"),
    ("handled-input", 1, 1, 0, 0, 0, 0, "not-started"),
    ("canceled", 1, 1, 1, 1, 1, 0, "retired"),
    ("settling-deferred", 1, 1, 0, 3, 0, 1, "not-started"),
    ("async-confirmed", 1, 1, 1, 2, 1, 0, "settled"),
    ("async-late-resolve", 1, 1, 1, 2, 0, 1, "retired"),
    ("async-late-reject", 1, 1, 1, 2, 0, 1, "retired"),
  ]
  names = ("case_id", "confirm_calls", "intent_allocations", "request_allocations", "model_requests", "scoped_tool_calls", "unscoped_tool_calls", "command_status")
  return {"schema_version": 1, "probe_id": "confirmed-intent-public-sdk-async-v2", "status": "observed", "product_gate": False,
    "cases": [dict(zip(names, row), outcome="observed", extension_errors=0, async_binding_waits=2 if row[0] == "async-confirmed" else 1 if row[0].startswith("async-") else 0, async_late_results=1 if row[0] in ("async-late-resolve", "async-late-reject") else 0) for row in rows]}


def test_static_prepare_exact_copy_and_fixed_invocation_no_capture(materials):
  path = materials["path"]
  expected = {"schema_version": 1, "status": "prepared", "probe_id": probe.PROBE_ID, "native_started": False, "cases": 13, "product_gate": False}
  assert probe.prepare(path) == expected
  assert probe.preflight(path) == expected
  assert {p.relative_to(path / "bundle").as_posix() for p in (path / "bundle").rglob("*") if p.is_file()} == set(probe.SOURCES)
  assert stat.S_IMODE(path.stat().st_mode) == 0o700
  assert stat.S_IMODE((path / "plan.json").stat().st_mode) == 0o600
  argv = probe.build_invocation(path)
  assert {argv[i + 1]: argv[i + 2] for i, item in enumerate(argv) if item == "--setenv"} == probe.ENV
  assert argv[-2:] == ["/probe/scripts/pi-probe-intent-scope.mjs", "--native-intent-scope-probe"]
  binds = [(arg, argv[i + 1], argv[i + 2]) for i, arg in enumerate(argv) if arg in ("--bind", "--ro-bind")]
  assert [b for b in binds if b[0] == "--bind"] == [("--bind", str(path / "work"), "/work")]
  assert all(not b[2].startswith("/home/") for b in binds)
  with pytest.raises(FileExistsError):
    probe.prepare(path)


@pytest.mark.parametrize("fault", ["source", "controller", "candidate", "system", "extra-bundle", "extra-directory", "bundle-mode", "bundle-link", "root-mode", "work-mode", "child-mode", "work-link", "child-link", "already-output", "extra-root"])
def test_preflight_drift_and_private_work_refused_before_capture(materials, fault):
  path = materials["path"]
  probe.prepare(path)
  if fault == "source": (materials["root"] / probe.SOURCES[0]).write_bytes(b"changed")
  if fault == "controller": (materials["root"] / probe.CONTROLLERS[0]).write_bytes(b"changed")
  if fault == "candidate": (materials["candidate"] / "extra.js").write_bytes(b"changed")
  if fault == "system": (materials["node"] / "bin/node").write_bytes(b"changed")
  if fault == "extra-bundle": (path / "bundle/extra.ts").write_bytes(b"changed")
  if fault == "extra-directory": (path / "bundle/empty-extra").mkdir(mode=0o700)
  if fault == "bundle-mode": (path / "bundle" / probe.SOURCES[0]).chmod(0o644)
  if fault == "bundle-link":
    file = path / "bundle" / probe.SOURCES[0]
    file.unlink()
    file.symlink_to(materials["root"] / probe.SOURCES[0])
  if fault == "root-mode": path.chmod(0o755)
  if fault == "work-mode": (path / "work").chmod(0o755)
  if fault == "child-mode": (path / "work/home").chmod(0o755)
  if fault == "work-link":
    (path / "work").rename(path / "detached-work")
    (path / "work").symlink_to(path / "detached-work", target_is_directory=True)
  if fault == "child-link":
    (path / "work/home").rmdir()
    (path / "work/home").symlink_to(path / "work/tmp", target_is_directory=True)
  if fault == "already-output": (path / "work/intent-scope-result.json").write_bytes(b"{}")
  if fault == "extra-root": (path / "extra-empty-directory").mkdir(mode=0o700)
  with pytest.raises((ConfigError, OSError, PathError)):
    probe.run_native(path)
  assert not (path / "started.json").exists()


@pytest.mark.parametrize("fault", ["unknown", "version-bool", "cases", "environment", "invocation", "duplicate"])
def test_closed_plan_rejects_forged_control_and_duplicate_json(materials, fault):
  path = materials["path"]
  probe.prepare(path)
  plan_path = path / "plan.json"
  plan = probe.decode(plan_path.read_bytes())
  if fault == "unknown": plan["credential"] = "SYNTHETIC_PRIVATE"
  if fault == "version-bool": plan["schema_version"] = True
  if fault == "cases": plan["cases"].reverse()
  if fault == "environment": plan["environment"]["OPENAI_API_KEY"] = "SYNTHETIC_PRIVATE"
  if fault == "invocation": plan["invocation"].append("--allow-network")
  raw = probe.encode(plan)
  if fault == "duplicate": raw = raw.replace(b'"probe_id":', b'"probe_id":"wrong","probe_id":', 1)
  plan_path.write_bytes(raw)
  with pytest.raises(ConfigError):
    probe.preflight(path)


def test_independent_ten_case_observations_are_not_product_gate():
  value = observations()
  assert probe.verify_result(value) == value
  assert value["product_gate"] is False


@pytest.mark.parametrize("fault", ["order", "duplicate-case", "missing", "extra-case", "unknown", "row-secret", "version-bool", "gate", "state", "status", "extension-error", "count", "state-forgery"])
def test_closed_oracle_rejects_false_evidence(fault):
  value = deepcopy(observations())
  if fault == "order": value["cases"].reverse()
  if fault == "duplicate-case": value["cases"][-1] = value["cases"][0]
  if fault == "missing": value["cases"].pop()
  if fault == "extra-case": value["cases"].append(deepcopy(value["cases"][0]))
  if fault == "unknown": value["raw_sdk_error"] = "SYNTHETIC_PRIVATE"
  if fault == "row-secret": value["cases"][0]["objective"] = "SYNTHETIC_PRIVATE"
  if fault == "version-bool": value["schema_version"] = True
  if fault == "gate": value["product_gate"] = True
  if fault == "state": value["cases"][0]["outcome"] = "passed"
  if fault == "status": value["status"] = "failed"
  if fault == "extension-error": value["cases"][0]["extension_errors"] = 1
  if fault == "count": value["cases"][0]["model_requests"] = 0
  if fault == "state-forgery": value["cases"][-1]["command_status"] = "settled"
  with pytest.raises(ConfigError):
    probe.verify_result(value)


@pytest.mark.parametrize("field", ["confirm_calls", "intent_allocations", "request_allocations", "model_requests", "scoped_tool_calls", "unscoped_tool_calls", "extension_errors"])
def test_every_counter_requires_int_not_boolean(field):
  value = observations()
  value["cases"][0][field] = bool(value["cases"][0][field])
  with pytest.raises(ConfigError):
    probe.verify_result(value)


@pytest.mark.parametrize("fault", [None, "stdout-private", "stdout-discord", "stdout-bool", "result-mode", "result-secret", "result-duplicate", "result-oversize", "exit", "capture-limit", "post-source", "post-bundle", "post-bundle-directory", "post-bundle-mode", "post-controller-helper", "post-extra-root", "post-extra-work", "post-extra-child-file", "post-extra-child-directory", "post-child-mode", "post-child-link", "post-child-missing", "post-case-file", "post-agent-directory", "post-agent-mode"])
def test_fake_capture_requires_result_summary_and_post_integrity(materials, monkeypatch, fault):
  path = materials["path"]
  helper = materials["root"] / "src/agentcfg/storage.py"
  if fault == "post-controller-helper" and not helper.exists(): helper.write_bytes(b"inert helper before prepare")
  probe.prepare(path)
  calls = []
  def fake_capture(argv):
    calls.append(argv)
    # 与固定探针一致：每个场景只有空的 cwd/agent 私有目录。
    for case in probe.CASES:
      (path / "work" / ("case-" + case) / "agent").mkdir(mode=0o700, parents=True)
      (path / "work" / ("case-" + case)).chmod(0o700)
    value = observations()
    if fault == "result-secret": value["key"] = "SYNTHETIC_PRIVATE"
    raw = probe.encode(value)
    if fault == "result-duplicate": raw = raw.replace(b'"probe_id":', b'"probe_id":"wrong","probe_id":', 1)
    result = path / "work/intent-scope-result.json"
    result.write_bytes(raw if fault != "result-oversize" else b" " * (probe.MAX_OUTPUT + 1))
    result.chmod(0o644 if fault == "result-mode" else 0o600)
    summary = {"schema_version": 1, "status": "observed", "cases": 13, "product_gate": False}
    if fault == "stdout-discord": summary["cases"] = 9
    if fault == "stdout-bool": summary["schema_version"] = True
    stdout = b"SYNTHETIC_PRIVATE" if fault == "stdout-private" else probe.encode(summary)
    if fault == "post-source": (materials["root"] / probe.SOURCES[0]).write_bytes(b"changed")
    if fault == "post-bundle": (path / "bundle" / probe.SOURCES[0]).write_bytes(b"changed")
    if fault == "post-bundle-directory": (path / "bundle/extra-empty").mkdir(mode=0o700)
    if fault == "post-bundle-mode": (path / "bundle" / probe.SOURCES[0]).chmod(0o644)
    if fault == "post-controller-helper": helper.write_bytes(b"changed helper after capture")
    if fault == "post-extra-root": (path / "extra-empty-directory").mkdir(mode=0o700)
    if fault == "post-extra-work": (path / "work/extra.txt").write_bytes(b"inert synthetic extra output")
    if fault == "post-extra-child-file": (path / "work/home/extra.txt").write_bytes(b"inert synthetic extra output")
    if fault == "post-extra-child-directory": (path / "work/cache/extra-empty").mkdir(mode=0o700)
    if fault == "post-child-mode": (path / "work/state").chmod(0o755)
    if fault == "post-child-link":
      (path / "work/config").rmdir()
      (path / "work/config").symlink_to(path / "work/tmp", target_is_directory=True)
    if fault == "post-child-missing": (path / "work/data").rmdir()
    if fault == "post-case-file": (path / "work/case-confirmed-idle/extra.txt").write_bytes(b"inert synthetic extra output")
    if fault == "post-agent-directory": (path / "work/case-off/agent/extra-empty").mkdir(mode=0o700)
    if fault == "post-agent-mode": (path / "work/case-base/agent").chmod(0o755)
    return {"exit_code": 1 if fault == "exit" else 0, "capture_failed": fault == "capture-limit", "stdout_bytes": len(stdout), "stderr_bytes": 7}, stdout
  monkeypatch.setattr(probe, "capture", fake_capture)
  if fault is None:
    assert probe.run_native(path) == {"schema_version": 1, "status": "observed", "cases": 13, "product_gate": False}
  else:
    with pytest.raises(ConfigError): probe.run_native(path)
  saved = probe.decode((path / "execution.json").read_bytes())
  assert saved["verification"] == ("observed" if fault is None else "failed")
  assert saved["product_gate"] is False and saved["namespace_termination"] == "not-independently-observed"
  assert "SYNTHETIC_PRIVATE" not in json.dumps(saved)
  assert stat.S_IMODE((path / "started.json").stat().st_mode) == 0o600
  with pytest.raises(ConfigError): probe.run_native(path)
  assert len(calls) == 1


@pytest.mark.parametrize("helper", ["__init__", "adapter", "omp_env", "paths", "schema", "secrets", "storage"])
def test_own_parent_dependency_drift_cannot_use_old_preparation(materials, helper):
  source = materials["root"] / ("src/agentcfg/" + helper + ".py")
  if not source.exists(): source.write_bytes(b"inert dependency before prepare")
  probe.prepare(materials["path"])
  source.write_bytes(b"changed dependency after prepare")
  with pytest.raises(ConfigError): probe.preflight(materials["path"])


def test_capture_exception_is_unknown_and_never_replay(materials, monkeypatch):
  path = materials["path"]
  probe.prepare(path)
  calls = []
  def broken(argv):
    calls.append(argv)
    raise RuntimeError("SYNTHETIC_PRIVATE path key exception")
  monkeypatch.setattr(probe, "capture", broken)
  with pytest.raises(ConfigError) as caught:
    probe.run_native(path)
  assert "SYNTHETIC_PRIVATE" not in str(caught.value)
  saved = probe.decode((path / "execution.json").read_bytes())
  assert saved["native_started"] is None and saved["exit_code"] is None
  assert saved["verification"] == "failed" and saved["capture_failed"] is True
  assert saved["namespace_termination"] == "not-independently-observed" and saved["product_gate"] is False
  assert "SYNTHETIC_PRIVATE" not in json.dumps(saved)
  with pytest.raises(ConfigError): probe.run_native(path)
  assert len(calls) == 1


@pytest.mark.parametrize("mode,flag", [("run", False), ("prepare", True), ("preflight", True)])
def test_cli_native_flag_is_exact_mode_gate(materials, capsys, mode, flag):
  argv = [mode, "--directory", str(materials["path"])]
  if flag: argv.append("--native-intent-scope-probe")
  assert probe.main(argv) == 5
  output = probe.decode(capsys.readouterr().out.encode())
  assert output == {"status": "failed", "error_code": "PI_INTENT_SCOPE_PROBE_FAILED", "product_gate": False}
  assert not materials["path"].exists()


def test_nonprivate_owner_is_refused_without_chown_or_process(materials, monkeypatch):
  path = materials["path"]
  probe.prepare(path)
  target = (path / "work/home").stat()
  original = os.fstat
  def different_owner(fd):
    value = original(fd)
    if (value.st_dev, value.st_ino) == (target.st_dev, target.st_ino):
      fields = list(value)
      fields[4] = os.geteuid() + 1
      return os.stat_result(fields)
    return value
  monkeypatch.setattr(os, "fstat", different_owner)
  with pytest.raises(PathError):
    probe.preflight(path)
  assert not (path / "started.json").exists()


def test_cli_capture_exception_is_fixed_and_marker_remains(materials, monkeypatch, capsys):
  path = materials["path"]
  probe.prepare(path)
  def failure(argv):
    raise RuntimeError("SYNTHETIC_PRIVATE underlying SDK exception")
  monkeypatch.setattr(probe, "capture", failure)
  args = ["run", "--directory", str(path), "--native-intent-scope-probe"]
  assert probe.main(args) == 5
  assert probe.decode(capsys.readouterr().out.encode()) == {"status": "failed", "error_code": "PI_INTENT_SCOPE_PROBE_FAILED", "product_gate": False}
  assert probe.main(args) == 5
  assert "SYNTHETIC_PRIVATE" not in capsys.readouterr().out
  assert (path / "started.json").is_file()


def test_new_async_sdk_evidence_has_a_closed_parent_oracle():
  value = observations()
  assert len(value["cases"]) == 13
  assert probe.verify_result(value) == value


@pytest.mark.parametrize("case", [10, 11, 12])
@pytest.mark.parametrize("field", ["async_binding_waits", "async_late_results", "request_allocations", "scoped_tool_calls", "unscoped_tool_calls"])
def test_async_counts_reject_overstated_or_boolean_evidence(case, field):
  for change in (True, 999):
    value = observations(); value["cases"][case][field] = change
    with pytest.raises(ConfigError): probe.verify_result(value)
