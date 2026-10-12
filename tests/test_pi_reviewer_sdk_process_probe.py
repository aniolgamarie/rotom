"""纯fake组合探针父oracle；不启动SDK、Node、bwrap或真实账户。"""
from copy import deepcopy
import pytest
from agentcfg import pi_reviewer_sdk_process_probe as probe
from agentcfg.schema import ConfigError
from agentcfg.paths import PathError


def observed():
  rows = []
  for case in probe.CASES:
    started = case not in ("hard-deny", "human-required", "input-unqualified"); reported = case in ("allow", "ask", "deny", "text-allow")
    rows.append({"case_id": case, "outcome": "observed", "transport_outcome": {"wrong-model": "transport-failure", "canceled": "canceled", "response-limit": "transport-failure", "hard-deny": "policy-blocked", "human-required": "human-required", "input-unqualified": "transport-failure"}.get(case, "valid"),
      "decision": case if case in ("allow", "ask", "deny") else "allow" if case in ("missing-usage", "text-allow") else None,
      "requests": int(started), "usage": {"status": "reported" if reported else "unknown" if started else "not-sent", "input_tokens": 5 if reported else None if started else 0,
        "output_tokens": 3 if reported else None if started else 0, "total_tokens": 8 if reported else None if started else 0},
      "child_started": started, "child_close_observed": started, "child_stdout_bytes": 0, "child_stderr_bytes": 0,
      "model_identity": probe.shared_identity(case), "wire": {"shape": "openai-chat-text" if case == "text-allow" else "deepseek-chat-text-disabled", "model": "synthetic-text" if case == "text-allow" else "synthetic-reviewer", "max_tokens": 4096, "thinking": None if case == "text-allow" else {"type": "disabled"}} if started else None,
      "scope_termination": "not-independently-observed"})
  return {"schema_version": 1, "probe_id": probe.PROBE_ID, "status": "observed", "cases": rows, "product_gate": False}


def test_valid_closed_eleven_case_result_preserves_unknown_scope():
  value = observed()
  assert probe.verify_result(value) == value


@pytest.mark.parametrize("fault", ["scope", "boolean", "extra", "worker", "usage", "order", "requests"])
def test_oracle_rejects_changed_evidence(fault):
  value = observed(); row = value["cases"][0]
  if fault == "scope": row["scope_termination"] = "observed"
  if fault == "boolean": row["requests"] = True
  if fault == "extra": row["secret"] = "SYNTHETIC_PRIVATE"
  if fault == "worker": row["worker_started"] = True
  if fault == "usage": row["usage"]["input_tokens"] = True
  if fault == "order": value["cases"].reverse()
  if fault == "requests": row["requests"] = 0
  with pytest.raises(ConfigError): probe.verify_result(value)


import hashlib
import os
from pathlib import Path
import stat
from agentcfg import pi_reviewer_sdk_probe as helpers


@pytest.fixture
def materials(tmp_path, monkeypatch):
  root = tmp_path / "repo"; root.mkdir(mode=0o700)
  candidate = root / "candidate"; candidate.mkdir(mode=0o700)
  for name in (*probe.SOURCES, *probe.CONTROLLERS):
    path = root / name; path.parent.mkdir(parents=True, exist_ok=True, mode=0o700); path.write_bytes(b"self-owned source\n")
  (candidate / "package-lock.json").write_bytes(b'{"name":"own-synthetic-lock"}\n')
  for name, version in (("@earendil-works/pi-coding-agent", "1.0.1"), ("@earendil-works/pi-ai", "1.0.2"), ("openai", "7.19.0")):
    directory = candidate / "node_modules" / name; directory.mkdir(parents=True, mode=0o700)
    (directory / "package.json").write_text(helpers.encode({"name": name, "version": version}).decode())
  node = root / "node"; (node / "bin").mkdir(parents=True, mode=0o700)
  for path in (node / "bin/node", root / "bwrap", root / "timeout"):
    path.write_bytes(b"own-not-executed-fixture\n"); path.chmod(0o700)
  values = {"ROOT": root, "CANDIDATE": candidate, "NODE": node, "BWRAP": root / "bwrap", "TIMEOUT": root / "timeout"}
  for module in (probe, helpers):
    for key, value in values.items(): monkeypatch.setattr(module, key, value)
  monkeypatch.setattr(helpers, "LOCK_SHA", hashlib.sha256((candidate / "package-lock.json").read_bytes()).hexdigest())
  return {"root": root, "candidate": candidate, "work": tmp_path / "prepared", "node": node}


def test_prepare_exact_thirteen_ts_and_fixed_boundary_without_capture(materials, monkeypatch):
  monkeypatch.setattr(probe, "capture", lambda _: pytest.fail("capture during preparation"))
  result = probe.prepare(materials["work"])
  assert result["native_started"] is False and result["product_gate"] is False
  assert probe.preflight(materials["work"])["status"] == "prepared"
  assert len(probe.SOURCES) == 15 and len([x for x in probe.SOURCES if x.endswith(".ts")]) == 13
  assert {p.relative_to(materials["work"] / "bundle").as_posix() for p in (materials["work"] / "bundle").rglob("*") if p.is_file()} == set(probe.SOURCES)
  assert not (materials["work"] / "started.json").exists()
  argv = probe.build_invocation(materials["work"])
  assert argv[-2:] == ["/probe/scripts/pi-probe-reviewer-sdk-process.mjs", "--native-reviewer-sdk-process-probe"]
  assert "--unshare-all" in argv and "--cap-drop" in argv
  assert [(argv[i + 1], argv[i + 2]) for i, x in enumerate(argv) if x == "--bind"] == [(str(materials["work"] / "work"), "/work")]
  assert {argv[i + 1]: argv[i + 2] for i, x in enumerate(argv) if x == "--setenv"} == probe.ENV
  with pytest.raises(FileExistsError): probe.prepare(materials["work"])


@pytest.mark.parametrize("fault", ["source", "controller", "candidate", "node", "extra-bundle", "extra-directory", "bundle-link", "bundle-hardlink", "bundle-file-mode", "bundle-dir-mode", "work-link", "work-child-link", "work-mode", "work-output", "extra-root", "started"])
def test_preflight_drift_is_zero_capture(materials, monkeypatch, fault):
  work = materials["work"]; probe.prepare(work); source = work / "bundle" / probe.SOURCES[0]
  if fault == "source": (materials["root"] / probe.SOURCES[0]).write_bytes(b"changed")
  if fault == "controller": (materials["root"] / probe.CONTROLLERS[-1]).write_bytes(b"changed")
  if fault == "candidate": (materials["candidate"] / "new.mjs").write_bytes(b"changed")
  if fault == "node": (materials["node"] / "bin/node").write_bytes(b"changed")
  if fault == "extra-bundle": (work / "bundle/new.js").write_bytes(b"changed")
  if fault == "extra-directory": (work / "bundle/extra").mkdir(mode=0o700)
  if fault == "bundle-link": source.unlink(); source.symlink_to(materials["root"] / probe.SOURCES[0])
  if fault == "bundle-hardlink": os.link(source, work / "elsewhere")
  if fault == "bundle-file-mode": source.chmod(0o644)
  if fault == "bundle-dir-mode": source.parent.chmod(0o755)
  if fault == "work-link": (work / "work").rename(work / "saved"); (work / "work").symlink_to(work / "saved")
  if fault == "work-child-link": (work / "work/home").rmdir(); (work / "work/home").symlink_to(materials["root"])
  if fault == "work-mode": (work / "work/home").chmod(0o755)
  if fault == "work-output": (work / "work/home/auth.json").write_bytes(b"SYNTHETIC_PRIVATE")
  if fault == "extra-root": (work / "extra").mkdir(mode=0o700)
  if fault == "started": (work / "started.json").write_bytes(b"{}")
  monkeypatch.setattr(probe, "capture", lambda _: pytest.fail("invalid preflight started capture"))
  with pytest.raises((ConfigError, PathError, OSError)): probe.run_native(work)


@pytest.mark.parametrize("fault", ["unknown", "boolean-version", "environment", "argv", "case", "duplicate"])
def test_closed_plan_and_duplicate_json(materials, fault):
  work = materials["work"]; probe.prepare(work); path = work / "plan.json"; value = probe.decode(path.read_bytes())
  if fault == "unknown": value["SDK_KEY"] = "SYNTHETIC_PRIVATE"
  if fault == "boolean-version": value["schema_version"] = True
  if fault == "environment": value["environment"]["OTHER"] = "SYNTHETIC_PRIVATE"
  if fault == "argv": value["invocation"].append("--inherit-env")
  if fault == "case": value["cases"].reverse()
  raw = probe.encode(value)
  if fault == "duplicate": raw = raw.replace(b'"probe_id":', b'"probe_id":"other","probe_id":', 1)
  path.write_bytes(raw)
  with pytest.raises(ConfigError): probe.preflight(work)


@pytest.mark.parametrize("case", range(11))
@pytest.mark.parametrize("field", ["child_started", "child_close_observed", "child_stdout_bytes", "child_stderr_bytes", "requests"])
def test_each_case_has_exact_process_and_send_observation(case, field):
  value = observed(); row = value["cases"][case]
  row[field] = not row[field] if type(row[field]) is bool else True
  with pytest.raises(ConfigError): probe.verify_result(value)


def test_no_send_usage_not_reported_or_unknown():
  value = observed()
  for row in [r for r in value["cases"] if r["requests"] == 0]:
    assert row["usage"] == {"status": "not-sent", "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    row["usage"] = {"status": "unknown", "input_tokens": None, "output_tokens": None, "total_tokens": None}
    with pytest.raises(ConfigError): probe.verify_result(value)


def fake_capture(work, result=None, summary=None):
  def capture(_):
    path = work / "work/reviewer-process-result.json"
    path.write_bytes(probe.encode(observed() if result is None else result)); path.chmod(0o600)
    raw = probe.encode({"schema_version": 1, "status": "observed", "cases": 11, "product_gate": False}) if summary is None else summary
    return {"exit_code": 0, "stdout_bytes": len(raw), "stderr_bytes": 0, "capture_failed": False}, raw
  return capture


def test_fake_run_closed_success_then_no_replay(materials, monkeypatch):
  work = materials["work"]; probe.prepare(work); monkeypatch.setattr(probe, "capture", fake_capture(work))
  assert probe.run_native(work) == {"schema_version": 1, "status": "observed", "cases": 11, "product_gate": False}
  execution = probe.decode((work / "execution.json").read_bytes())
  assert execution["namespace_termination"] == "not-independently-observed" and execution["product_gate"] is False
  with pytest.raises(ConfigError): probe.run_native(work)


@pytest.mark.parametrize("fault", ["result", "summary", "duplicate", "capture-limit", "capture-exception", "post-source", "post-controller", "post-bundle", "post-extra-directory", "result-mode"])
def test_fake_run_failure_retains_marker_unknown_scope_no_raw(materials, monkeypatch, fault):
  work = materials["work"]; probe.prepare(work); original = fake_capture(work)
  def capture(argv):
    if fault == "capture-exception": raise RuntimeError("SYNTHETIC_PRIVATE")
    execution, raw = original(argv)
    if fault == "result":
      value = observed(); value["cases"][0]["requests"] = 0; (work / "work/reviewer-process-result.json").write_bytes(probe.encode(value))
    if fault == "summary": raw = b'{"schema_version":1,"status":"observed","cases":true,"product_gate":false}'
    if fault == "duplicate": raw = b'{"schema_version":1,"status":"failed","status":"observed","cases":11,"product_gate":false}'
    if fault == "capture-limit": execution["capture_failed"] = True
    if fault == "post-source": (materials["root"] / probe.SOURCES[0]).write_bytes(b"changed")
    if fault == "post-controller": (materials["root"] / probe.CONTROLLERS[-1]).write_bytes(b"changed")
    if fault == "post-bundle": (work / "bundle" / probe.SOURCES[0]).write_bytes(b"changed")
    if fault == "post-extra-directory": (work / "bundle/extra").mkdir(mode=0o700)
    if fault == "result-mode": (work / "work/reviewer-process-result.json").chmod(0o644)
    return execution, raw
  monkeypatch.setattr(probe, "capture", capture)
  with pytest.raises(ConfigError): probe.run_native(work)
  execution = probe.decode((work / "execution.json").read_bytes())
  assert execution["verification"] == "failed" and execution["namespace_termination"] == "not-independently-observed"
  assert "SYNTHETIC_PRIVATE" not in (work / "execution.json").read_text()
  assert execution["outer_launcher_started"] is (None if fault == "capture-exception" else True)
  assert execution["sdk_execution_observed"] is False
  with pytest.raises(ConfigError): probe.run_native(work)


@pytest.mark.parametrize("mode,flag", [("prepare", True), ("preflight", True), ("run", False)])
def test_cli_requires_explicit_run_flag_before_dispatch(mode, flag, monkeypatch, capsys):
  for name in ("prepare", "preflight", "run_native"): monkeypatch.setattr(probe, name, lambda _: pytest.fail("invalid CLI dispatched"))
  argv = [mode, "--directory", "/tmp/synthetic"] + (["--native-reviewer-sdk-process-probe"] if flag else [])
  assert probe.main(argv) == 5
  assert "PI_REVIEWER_SDK_PROCESS_PROBE_FAILED" in capsys.readouterr().out


@pytest.mark.parametrize("name", probe.CONTROLLERS)
def test_every_pinned_controller_drift_blocks_dispatch(materials, monkeypatch, name):
  work = materials["work"]; probe.prepare(work)
  (materials["root"] / name).write_bytes(b"own changed controller")
  monkeypatch.setattr(probe, "capture", lambda _: pytest.fail("controller drift reached capture"))
  with pytest.raises(ConfigError): probe.run_native(work)


def test_fixed_controller_set_covers_current_local_ast_imports():
  # 只读静态源码闭包，含函数内相对import；不导入SDK/运行任何源码。
  import ast
  root = Path(__file__).resolve().parents[1]
  pending = ["src/agentcfg/pi_reviewer_sdk_process_probe.py"]
  seen = {"src/agentcfg/__init__.py", "scripts/pi-probe-reviewer-sdk-process.py"}
  while pending:
    name = pending.pop()
    if name in seen: continue
    seen.add(name)
    for node in ast.walk(ast.parse((root / name).read_text())):
      if isinstance(node, ast.ImportFrom) and node.level and node.module:
        target = "src/agentcfg/" + node.module.replace(".", "/") + ".py"
        assert (root / target).is_file(), "local source dependency missing"
        if target not in seen: pending.append(target)
  assert set(probe.CONTROLLERS) == seen


@pytest.mark.parametrize("fault", ["extra-file", "extra-directory", "home-auth", "cache", "child-mode"])
def test_post_work_artifacts_cannot_be_reported_as_observed(materials, monkeypatch, fault):
  work = materials["work"]; probe.prepare(work); original = fake_capture(work)
  def capture(argv):
    result = original(argv)
    if fault == "extra-file": (work / "work/unexpected.json").write_bytes(b"SYNTHETIC_PRIVATE")
    if fault == "extra-directory": (work / "work/unexpected").mkdir(mode=0o700)
    if fault == "home-auth": (work / "work/home/auth.json").write_bytes(b"SYNTHETIC_PRIVATE")
    if fault == "cache": (work / "work/cache/undeclared").mkdir(mode=0o700)
    if fault == "child-mode": (work / "work/home").chmod(0o755)
    return result
  monkeypatch.setattr(probe, "capture", capture)
  with pytest.raises(ConfigError): probe.run_native(work)
  execution = probe.decode((work / "execution.json").read_bytes())
  assert execution["verification"] == "failed"
  assert "SYNTHETIC_PRIVATE" not in (work / "execution.json").read_text()
  assert (work / "started.json").is_file()


def test_outer_launcher_exit_is_not_sdk_execution_observation(materials, monkeypatch):
  work = materials["work"]; probe.prepare(work)
  monkeypatch.setattr(probe, "capture", lambda _: ({"exit_code": 5, "stdout_bytes": 0,
    "stderr_bytes": 0, "capture_failed": False}, b""))
  with pytest.raises(ConfigError): probe.run_native(work)
  execution = probe.decode((work / "execution.json").read_bytes())
  assert execution["outer_launcher_started"] is True
  assert execution["sdk_execution_observed"] is False
  assert "native_started" not in execution


def test_shared_relative_dependencies_are_explicit_sources():
  assert {"agents/pi/packages/risk-review/src/" + n + ".ts" for n in ("shared-model", "shared-sdk-contract", "shared-request-wire")} <= set(probe.SOURCES)


@pytest.mark.parametrize("fault", ["identity", "missing-wire", "extra-wire", "cap", "bool-cap", "thinking", "shape", "model", "blocked-wire", "blocked-call", "text-thinking"])
def test_shared_variant_and_safe_final_wire_projection_are_exact(fault):
  value = observed(); row = value["cases"][0]
  if fault == "identity": row["model_identity"] = "a" * 64
  if fault == "missing-wire": del row["wire"]
  if fault == "extra-wire": row["wire"]["authorization"] = "SYNTHETIC_PRIVATE"
  if fault == "cap": row["wire"]["max_tokens"] = 384000
  if fault == "bool-cap": row["wire"]["max_tokens"] = True
  if fault == "thinking": row["wire"]["thinking"] = {"type": "enabled"}
  if fault == "shape": row["wire"]["shape"] = "openai-chat-text"
  if fault == "model": row["wire"]["model"] = "other"
  if fault == "blocked-wire": value["cases"][-1]["wire"] = row["wire"]
  if fault == "blocked-call": value["cases"][-1]["requests"] = 1
  if fault == "text-thinking": value["cases"][-2]["wire"]["thinking"] = {"type": "disabled"}
  with pytest.raises(ConfigError): probe.verify_result(value)


def test_current_own_ts_relative_imports_close_in_fifteen_sources():
  import re
  base = Path(__file__).resolve().parents[1]
  for source in probe.SOURCES:
    if not source.endswith(".ts"): continue
    for _, target in re.findall(r'(?:from\s*|import\s*\()(["\'])\./([^"\']+)\1', (base / source).read_text()):
      assert str(Path(source).parent / target) in probe.SOURCES
