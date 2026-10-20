"""基准默认只测结构与 fake 数据，不启动宿主。"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("herdr_upgrade", ROOT / "tools/bench/herdr_upgrade.py")
bench = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bench)
FIXTURES = ROOT / "tests/fixtures/herdr-bench/v1"


def fixture(name):
  return json.loads((FIXTURES / (name + ".json")).read_text())


def test_checked_in_inputs_validate_without_host():
  assert bench.main(["validate", "--manifest", str(FIXTURES / "manifest.json"), "--policy", str(FIXTURES / "policy.json")]) == 0


def test_canonical_hash_rejects_nonfinite_and_excludes_digest():
  value = {"字": "值", "digest": "ignored"}
  assert bench.digest(value) == bench.digest({"字": "值"})
  with pytest.raises(ValueError):
    bench.digest({"value": float("nan")})


def test_atomic_new_file_never_overwrites(tmp_path):
  path = tmp_path / "evidence.json"
  bench.write_new(path, {"example": 1})
  original = path.read_bytes()
  with pytest.raises(bench.BenchError) as error:
    bench.write_new(path, {"example": 2})
  assert error.value.code == 4
  assert path.read_bytes() == original


@pytest.mark.parametrize("command", ["run", "calibrate"])
def test_native_requires_opt_in_before_any_subprocess(command, monkeypatch, tmp_path):
  monkeypatch.setattr(bench.subprocess, "Popen", lambda *a, **k: pytest.fail("native process must not start"))
  args = [command, "--manifest", str(FIXTURES / "manifest.json"), "--policy", str(FIXTURES / "policy.json"), "--subject", "candidate", "--output", str(tmp_path / "report.json")]
  args += ["--scope", "first-baseline"] if command == "run" else ["--policy-output", str(tmp_path / "policy.json")]
  assert bench.main(args) == 2


def test_unknown_nested_fields_and_bad_digest_rejected():
  value = fixture("manifest")
  value["environment"]["unknown"] = True
  value["digest"] = bench.digest(value)
  with pytest.raises(bench.BenchError):
    bench.validate_document(value, "manifest")
  value = fixture("manifest")
  value["seed"] += 1
  with pytest.raises(bench.BenchError):
    bench.validate_document(value, "manifest")


def test_latency_nearest_rank_and_sample_minimum():
  assert bench.statistics(list(range(1, 201)), p95=True) == {"n": 200, "median": 100.5, "p95": 190, "min": 1, "max": 200}
  with pytest.raises(bench.BenchError):
    bench.statistics([1, 2, 3], p95=True)
  assert bench.statistics([1, 2, 3], p95=False)["p95"] is None


def test_report_roundtrip_and_cli_compare_requires_private_proof(tmp_path):
  from test_herdr_upgrade_policy import measured
  manifest, policy, report = measured()
  for name, value in [("manifest", manifest), ("policy", policy), ("candidate", report)]:
    (tmp_path / (name + ".json")).write_text(json.dumps(value))
  output = tmp_path / "decision.json"
  argv = ["compare", "--manifest", str(tmp_path / "manifest.json"), "--policy", str(tmp_path / "policy.json"), "--candidate", str(tmp_path / "candidate.json"), "--output", str(output)]
  assert bench.main(argv) == 5
  result = json.loads(output.read_text())
  assert result["decision"] == "unverified"
  bench.validate_document(result, "report")
  before = output.read_bytes()
  assert bench.main(argv) == 4
  assert output.read_bytes() == before


def test_private_originals_digest_argv_and_repository_boundary(tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, r = measured()
  directory = tmp_path / "private"
  directory.mkdir(mode=0o700)
  m["isolation"]["private_record_root"] = str(directory)
  original = {"expected_argv": m["steps"][0]["argv"], "actual_argv": m["steps"][0]["argv"], "subject_digest": bench.digest(r["subject_identity"]), "exit_code": 0, "start_ns": 1, "end_ns": 2}
  path = directory / "step.json"
  bench.write_new(path, original)
  r["steps"] = [{"id": m["steps"][0]["id"], "normalized_argv": original["actual_argv"], "cwd_label": "synthetic-checkout", "exit_code": 0, "start_ns": 1, "end_ns": 2, "ready_evidence_ref": "synthetic-ready", "execution_digest": bench.bytes_digest(path), "evidence_ref": path.name, "original_verified": True}]
  assert not bench.verify_originals(m, r, tmp_path)  # 有效来源布尔值不能替代私有原件。
  r["coverage"]["effective_inputs_verified"] = False
  r["coverage"]["cpu_complete"] = False
  r["cpu_windows"] = []
  r["coverage"].update(client_ready_proven=False, dimensions_proven=False)
  r["evidence"] = [row for row in r["evidence"] if not row["id"].startswith(("client-ready-batch-", "client-geometry-batch-"))]
  assert bench.verify_originals(m, r, tmp_path)
  original["actual_argv"] = ["different-command"]
  path.write_text(json.dumps(original))
  assert not bench.verify_originals(m, r, tmp_path)
  with pytest.raises(bench.BenchError):
    bench.private_directory(ROOT / "private-records", create=True)


def test_procfs_sampling_pins_pid_starttime(tmp_path, monkeypatch):
  sampler = bench.ProcSampler(100, producer_pids=[200], proc=tmp_path)
  snapshots = iter([{100: {"ppid": 1, "cpu": 10, "start": 1, "rss": 4096}, 200: {"ppid": 100, "cpu": 2, "start": 2, "rss": 100}}, {100: {"ppid": 1, "cpu": 11, "start": 1, "rss": 5000}, 200: {"ppid": 100, "cpu": 99, "start": 3, "rss": 500}}])
  monkeypatch.setattr(sampler, "snapshot", lambda: next(snapshots))
  sampler.sample()
  sampler.sample()
  assert sampler.cpu["server"] == 1
  assert sampler.cpu["producer"] == 0
  assert sampler.lost is True


def producer_module():
  spec = importlib.util.spec_from_file_location("fixture_producer", FIXTURES / "producer.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_producer_fixed_output_window_without_real_sleep_or_stdout():
  producer = producer_module()
  now = [1]
  total = [0, 0]
  def sleep(seconds):
    now[0] += max(1, round(seconds * 1000000000))
  def write(fd, data):
    assert fd == 1
    assert len(data) == 128 and data[-1:] == b"\n" and data.isascii()
    total[0] += 1
    total[1] += len(data)
    return len(data)
  result = producer.window("output", 73421, "measure", 1, clock=lambda: now[0], sleep=sleep, write=write)
  assert total == [153600, 19660800]
  assert result["lines"] == 153600
  assert result["end_ns"] >= 300000000001


def test_producer_rejects_unknown_anchor_and_unsafe_control(tmp_path):
  producer = producer_module()
  control = tmp_path / "control"
  control.mkdir(mode=0o700)
  anchor = {"version": 1, "run_id": "a" * 32, "mode": "idle", "seed": 1, "control_dir": str(control)}
  import hashlib
  anchor["config_digest"] = hashlib.sha256(producer.canonical(anchor)).hexdigest()
  path = tmp_path / ".rotom-bench-v1.json"
  bench.write_new(path, anchor)
  assert producer.config(tmp_path, "pane-1")[0] == anchor
  assert producer.config(tmp_path, "w1:pA")[0] == anchor
  for invalid in ("../w1:pA", "w1/pA", "w1:pA\n", ""):
    with pytest.raises(ValueError):
      producer.config(tmp_path, invalid)
  control.chmod(0o755)
  with pytest.raises(ValueError):
    producer.config(tmp_path, "pane-1")
  control.chmod(0o700)
  anchor["command"] = "forbidden"
  path.write_text(json.dumps(anchor))
  with pytest.raises(ValueError):
    producer.config(tmp_path, "pane-1")


def test_native_preflight_refuses_existing_root_before_host(tmp_path, monkeypatch):
  manifest = fixture("manifest")
  manifest["isolation"]["root"] = str(tmp_path)
  with pytest.raises(bench.BenchError) as error:
    bench.preflight(manifest, "candidate", tmp_path)
  assert error.value.code == 4


def test_falsified_sample_summary_is_rejected():
  from test_herdr_upgrade_policy import measured
  m, p, r = measured()
  r["measurements"][0].update(metric="latency.warm_enter.p95", unit="ms", value=1, n=200, samples=list(range(1, 201)))
  bench.sealed(r)
  with pytest.raises(bench.BenchError) as error:
    bench.validate_document(r, "report")
  assert error.value.reason == "sample_summary_mismatch"


def test_paired_native_schedule_is_seeded_alternating_and_fake_only(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, r = measured(scope="runtime")
  calls = []
  def prepare(manifest, name, directory):
    return {"root": tmp_path / "isolated", "private": tmp_path, "binary": tmp_path / name, "sentinels": []}
  def fake_measure(manifest, policy, name, scope, directory, authorization, prepared, *, batch_numbers, case_filter):
    calls.append((batch_numbers[0], case_filter, name))
    return bench.empty_report(manifest, policy, name, scope)
  monkeypatch.setattr(bench, "preflight", prepare)
  monkeypatch.setattr(bench, "check_socket_capacity", lambda path: None)  # 此例仅验证fake调度；真实长度另测。
  monkeypatch.setattr(bench, "network_isolated", lambda: True)
  monkeypatch.setattr(bench, "_native_measure", fake_measure)
  primary, paired = bench.native_run(m, p, "candidate", "runtime", tmp_path, "synthetic-approval", allow_incomplete_cpu=True)
  frozen = bench.paired_schedule(m)
  assert calls == [(row["batch"], (row["workload"], row["mode"]), name) for row in frozen for name in row["planned_order"]]
  assert all(frozen[index]["planned_order"] != frozen[index + 1]["planned_order"] for index in range(len(frozen) - 1))
  assert primary["subject"] == "candidate" and paired["subject"] == "baseline"
  assert primary["paired_run_id"] == paired["paired_run_id"]
  assert primary["paired_schedule"] == paired["paired_schedule"]
  assert primary["validity"] == "invalid"


def test_paired_output_rules_and_new_file_protection(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured, install_pair
  m, p, candidate = measured(scope="runtime")
  baseline = json.loads(json.dumps(candidate))
  baseline["subject"] = "baseline"
  install_pair(m, candidate, baseline)
  for name, value in [("manifest", m), ("policy", p)]:
    (tmp_path / (name + ".json")).write_text(json.dumps(value))
  monkeypatch.setattr(bench, "native_run", lambda *a, **k: (bench.sealed(candidate), bench.sealed(baseline)))
  prefix = ["run", "--manifest", str(tmp_path / "manifest.json"), "--policy", str(tmp_path / "policy.json"), "--subject", "candidate", "--scope", "runtime", "--allow-native", "--allow-incomplete-cpu", "--authorization", "synthetic-approval", "--output", str(tmp_path / "candidate.json")]
  assert bench.main(prefix) == 2
  assert bench.main(prefix + ["--paired-output", str(tmp_path / "candidate.json")]) == 4
  assert bench.main(prefix + ["--paired-output", str(tmp_path / "baseline.json")]) == 0
  assert (tmp_path / "candidate.json").exists() and (tmp_path / "baseline.json").exists()
  assert bench.main(prefix + ["--paired-output", str(tmp_path / "baseline.json")]) == 4


def test_partial_pair_publication_retains_written_evidence(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured, install_pair
  m, p, candidate = measured(scope="runtime")
  baseline = json.loads(json.dumps(candidate))
  baseline["subject"] = "baseline"
  install_pair(m, candidate, baseline)
  for name, value in [("manifest", m), ("policy", p)]:
    (tmp_path / (name + ".json")).write_text(json.dumps(value))
  monkeypatch.setattr(bench, "native_run", lambda *a, **k: (bench.sealed(candidate), bench.sealed(baseline)))
  original = bench.write_new
  def fail_second(path, value, **kwargs):
    if Path(path).name == "candidate.json":
      raise OSError("synthetic publication failure")
    return original(path, value, **kwargs)
  monkeypatch.setattr(bench, "write_new", fail_second)
  assert bench.main(["run", "--manifest", str(tmp_path / "manifest.json"), "--policy", str(tmp_path / "policy.json"), "--subject", "candidate", "--scope", "runtime", "--allow-native", "--allow-incomplete-cpu", "--authorization", "synthetic-approval", "--output", str(tmp_path / "candidate.json"), "--paired-output", str(tmp_path / "baseline.json")]) == 6
  assert (tmp_path / "baseline.json").exists()
  assert not (tmp_path / "candidate.json").exists()


def test_backpressure_cannot_count_late_bytes_as_measurement():
  producer = producer_module()
  now = [1]
  def sleep(seconds):
    now[0] += max(1, round(seconds * 1000000000))
  def blocked_write(fd, data):
    now[0] += 301000000000
    return len(data)
  result = producer.window("output", 1, "measure", 1, clock=lambda: now[0], sleep=sleep, write=blocked_write)
  assert result["lines"] == 0 and result["bytes"] == 0
  report = {"producer": [{"mode": "output", **result}], "validity": "valid", "invalid_reasons": []}
  bench.check_producers(report)
  assert report["validity"] == "invalid"


def test_recipe_normalization_does_not_publish_runtime_paths(tmp_path):
  m = fixture("manifest")
  m["isolation"]["root"] = str(tmp_path / "private-run")
  argv = [str(ROOT / "work"), "--local", str(tmp_path / "private-run/case/local.toml"), "open", "edit"]
  normalized = bench.normalize_argv(argv, m, tmp_path)
  assert normalized == ["<ROTOM>/work", "--local", "<ISOLATION>/case/local.toml", "open", "edit"]
  assert bench.matches_recipe(["<ROTOM>/work", "--local", "<LOCAL>", "open", "edit"], normalized)
  assert not bench.matches_recipe(["<HERDR>", "pane", "close", "<PANE>"], ["<HERDR>", "pane", "close", "../private"])


def test_authorization_receipt_binding_rejects_before_any_native_preflight(monkeypatch, tmp_path):
  manifest = fixture("manifest")
  monkeypatch.setattr(bench, "preflight", lambda *a, **k: pytest.fail("native preflight must not run"))
  for label in ("synthetic-approval", "bad\nlabel", "https://example.invalid/auth"):
    with pytest.raises(bench.BenchError) as error:
      bench.native_run(manifest, fixture("policy"), "candidate", "first-baseline", tmp_path, label)
    assert error.value.code == 2
  manifest["authorization_ref"] = "synthetic-approval"
  with pytest.raises(bench.BenchError):
    bench.native_run(manifest, fixture("policy"), "candidate", "first-baseline", tmp_path, "different-label")


def test_effective_identity_false_stays_unverified_with_all_metrics():
  from test_herdr_upgrade_policy import measured, decide
  for field in ("client_version_verified", "effective_inputs_verified"):
    m, p, report = measured()
    report["coverage"][field] = False
    assert decide(m, p, report)["decision"] == "unverified"


def test_report_authorization_reference_must_match_manifest():
  from test_herdr_upgrade_policy import measured
  m, p, report = measured()
  report["authorization_ref"] = "different-approval"
  with pytest.raises(bench.BenchError):
    bench.validate_references(m, p, [report])


def test_namespace_network_view_uses_proc_not_stale_sysfs(tmp_path):
  path = tmp_path / "net-dev"
  path.write_text("Inter-| Receive | Transmit\n face |bytes |bytes\n lo: 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n")
  assert bench.network_isolated(dev_path=path)
  path.write_text(path.read_text() + "eth0: 0 0 0\n")
  assert not bench.network_isolated(dev_path=path)


def test_effective_origin_fingerprint_rejects_partial_override_or_installed():
  rows = [{"agent": agent, "source": "bundled", "source_kind": "bundled", "active_version": "1", "local_override_shadowing_remote": False} for agent in bench.BUNDLED_AGENTS]
  reply = {"id": "synthetic", "result": {"type": "agent_manifest_status", "manifests": rows}}
  status = "\n".join(target + (" (experimental)" if target == "letta" else "") + ": not installed (/tmp/synthetic-home/" + target + ")" for target in bench.INTEGRATION_TARGETS)
  rules, integrations = bench.origin_fingerprints(reply, status, "a" * 64, "b" * 64)
  assert rules["kind"] == "builtin-origin-fingerprint"
  assert integrations["kind"] == "disabled-origin-fingerprint"
  assert "/tmp" not in json.dumps([rules, integrations])
  rows[0]["source_kind"] = "local override"
  with pytest.raises(bench.BenchError):
    bench.origin_fingerprints(reply, status, "a" * 64, "b" * 64)
  rows[0]["source_kind"] = "bundled"
  rows.pop()
  with pytest.raises(bench.BenchError):
    bench.origin_fingerprints(reply, status, "a" * 64, "b" * 64)
  with pytest.raises(bench.BenchError):
    bench.origin_fingerprints({"result": {"type": "agent_manifest_status", "manifests": rows}}, status.replace("not installed", "current (v1)", 1), "a" * 64, "b" * 64)


def test_perf_task_clock_unit_cannot_masquerade_as_user_system():
  result = bench.parse_task_clock("341.85;msec;task-clock:u;300000000;100.00;\n")
  assert result["value"] == 0.34185
  assert result["unit"] == "task-clock-seconds"
  assert result["equivalent_user_system"] is False
  for invalid in ("1;seconds;task-clock:u;1;100.00;\n", "<not counted>;;task-clock:u;0;0;\n", "1;msec;cycles;1;100.00;\n", "1;msec;task-clock:u;1;50.00;\n"):
    with pytest.raises(bench.BenchError):
      bench.parse_task_clock(invalid)


def test_perf_control_ack_is_bounded_and_accepts_documented_nul_suffix():
  assert bench.perf_ack(b"ack\n\x00")
  assert bench.perf_ack(b"ack\n")
  assert not bench.perf_ack(b"unknown")


def test_fixed_duration_estimate_does_not_hide_churn_or_operation_costs():
  estimate = bench.duration_estimate(fixture("manifest"))
  assert estimate["fixed_seconds_per_subject"] == 18360
  assert estimate["warm_samples_per_subject"] == 2400
  assert estimate["cold_samples_per_subject"] == 90
  assert estimate["operation_seconds_included"] is False


def test_namespace_helper_is_fixed_and_native_opt_in_only(monkeypatch):
  import importlib.util
  path = bench.FIXTURE / "namespace_exec.py"
  spec = importlib.util.spec_from_file_location("bench_namespace", path)
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  calls = []
  monkeypatch.setattr(module, "enter_namespace", lambda: calls.append("namespace"))
  monkeypatch.setattr(module, "protected_root_visible", lambda: True)
  monkeypatch.setattr(module.os, "execv", lambda executable, argv: calls.append((executable, argv)))
  assert module.main(["validate", "--allow-native"]) == 2
  assert module.main(["run"]) == 2
  assert calls == []
  assert module.main(["run", "--allow-native", "--manifest", "fake.json"]) == 0
  assert calls[0] == "namespace"
  assert calls[1][1][1] == str(bench.ROOT / "tools/bench/herdr_upgrade.py")


def test_measurement_scope_does_not_time_undeclared_warm_paths():
  manifest = fixture("manifest")
  assert bench.measure_applies(manifest, "latency.warm_enter.p95", "projects-27")
  assert not bench.measure_applies(manifest, "latency.warm_enter.p95", "output-30")


def test_native_cpu_preflight_refuses_hours_without_explicit_incomplete_opt_in(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, _ = measured()
  monkeypatch.setattr(bench, "preflight", lambda *a, **k: pytest.fail("no native preflight or process"))
  with pytest.raises(bench.BenchError) as error:
    bench.native_run(m, p, "candidate", "first-baseline", tmp_path, "synthetic-approval")
  assert error.value.code == 5
  assert error.value.reason == "required_cpu_coverage_unavailable_explicit_incomplete_opt_in_required"


def test_explicit_partial_case_keeps_full_measure_window_and_cannot_pass(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, _ = measured()
  calls = []
  monkeypatch.setattr(bench, "preflight", lambda *a: {"root": tmp_path / "new"})
  monkeypatch.setattr(bench, "network_isolated", lambda: True)
  def measure(*args, **kwargs):
    calls.append(kwargs)
    return bench.empty_report(m, p, "candidate", "first-baseline")
  monkeypatch.setattr(bench, "_native_measure", measure)
  report = bench.native_run(m, p, "candidate", "first-baseline", tmp_path, "synthetic-approval", allow_incomplete_cpu=True, selected_case="output-1:output", selected_batch=2)
  assert calls == [{"batch_numbers": (2,), "case_filter": ("output-1", "output")}]
  assert report["validity"] == "invalid" and report["decision"] != "pass"
  assert "explicit_partial_measurement" in report["invalid_reasons"]
  assert m["sampling"]["measure_seconds"] == 300


def test_estimate_is_offline_and_does_not_start_hosts(monkeypatch, capsys):
  monkeypatch.setattr(bench.subprocess, "run", lambda *a, **k: pytest.fail("offline estimate"))
  assert bench.main(["estimate", "--manifest", str(bench.FIXTURE / "manifest.json")]) == 0
  value = json.loads(capsys.readouterr().out)
  assert value["fixed_seconds_per_subject"] == 18360
  assert value["can_establish_baseline"] is False


def test_namespace_cli_dispatch_is_fixed_and_cannot_recurse(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, _ = measured()
  for name, value in (("manifest", m), ("policy", p)):
    (tmp_path / (name + ".json")).write_text(json.dumps(value))
  calls = []
  def run(argv, **kwargs):
    calls.append(argv)
    return type("Result", (), {"returncode": 5})()
  monkeypatch.setattr(bench.subprocess, "run", run)
  assert bench.main(["run", "--manifest", str(tmp_path / "manifest.json"), "--policy", str(tmp_path / "policy.json"), "--subject", "candidate", "--scope", "first-baseline", "--allow-native", "--authorization", "synthetic-approval", "--output", str(tmp_path / "out.json"), "--isolated-netns", "--allow-incomplete-cpu", "--case", "idle-1:idle"]) == 5
  assert len(calls) == 1
  assert calls[0][1] == str(bench.FIXTURE / "namespace_exec.py")
  assert "--isolated-netns" not in calls[0]


def test_private_origins_bind_kind_asset_config_and_complete_public_source(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, r = measured()
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  m["isolation"]["private_record_root"] = str(private)
  reply = {"result": {"type": "agent_manifest_status", "manifests": [{"agent": agent, "source": "bundled", "source_kind": "bundled", "local_override_shadowing_remote": False} for agent in bench.BUNDLED_AGENTS]}}
  status = "\n".join(target + (" (experimental)" if target == "letta" else "") + ": not installed (/tmp/synthetic/" + target + ")" for target in bench.INTEGRATION_TARGETS)
  rules, integrations = bench.origin_fingerprints(reply, status, r["subject_identity"]["asset_digest"], r["inputs"]["config_digest"])
  r["inputs"].update(rules_identity_kind=rules["kind"], integration_identity_kind=integrations["kind"], rules_digest=bench.hashlib.sha256(bench.canonical(rules)).hexdigest(), integration_digest=bench.hashlib.sha256(bench.canonical(integrations)).hexdigest())
  r["subject_identity"]["inputs"] = dict(r["inputs"])
  raw = {"manifests_reply": reply, "integration_status": status, "rules": rules, "integrations": integrations, "subject_digest": bench.digest(r["subject_identity"])}
  receipt = private / ("a" * 32 + ".json")
  bench.write_new(receipt, raw, private=True)
  r["origin_receipts"] = [{"evidence_ref": receipt.name, "execution_digest": bench.bytes_digest(receipt), **{k: r["inputs"][k] for k in ("rules_digest", "integration_digest", "rules_identity_kind", "integration_identity_kind")}}]
  argv = m["steps"][0]["argv"]
  original = {"expected_argv": argv, "actual_argv": argv, "subject_digest": bench.digest(r["subject_identity"]), "exit_code": 0, "start_ns": 1, "end_ns": 2}
  bench.write_new(private / "step.json", original)
  r["steps"] = [{"id": m["steps"][0]["id"], "normalized_argv": argv, "cwd_label": "synthetic-checkout", "exit_code": 0, "start_ns": 1, "end_ns": 2, "ready_evidence_ref": "synthetic-ready", "execution_digest": bench.bytes_digest(private / "step.json"), "evidence_ref": "step.json", "original_verified": True}]
  r["coverage"]["cpu_complete"] = False
  r["cpu_windows"] = []
  r["coverage"].update(client_ready_proven=False, dimensions_proven=False)
  r["evidence"] = [row for row in r["evidence"] if not row["id"].startswith(("client-ready-batch-", "client-geometry-batch-"))]
  assert bench.verify_originals(m, r, tmp_path)
  r["inputs"]["rules_identity_kind"] = "byte-digest"
  assert not bench.verify_originals(m, r, tmp_path)
  r["inputs"]["rules_identity_kind"] = rules["kind"]
  r["origin_receipts"][0]["execution_digest"] = "f" * 64
  assert not bench.verify_originals(m, r, tmp_path)


def test_pending_policy_only_allows_explicit_invalid_partial_diagnostic(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, _ = measured()
  p.update(frozen_at=None, approval_ref=None, pending_reason="Synthetic unapproved diagnostic policy")
  bench.sealed(p)
  calls = []
  monkeypatch.setattr(bench, "preflight", lambda *args: calls.append("preflight") or {"root": tmp_path / "new"})
  monkeypatch.setattr(bench, "network_isolated", lambda: True)
  monkeypatch.setattr(bench, "_native_measure", lambda *a, **k: bench.empty_report(m, p, "candidate", "first-baseline"))
  with pytest.raises(bench.BenchError):
    bench.native_run(m, p, "candidate", "first-baseline", tmp_path, "synthetic-approval", allow_incomplete_cpu=True)
  assert calls == []
  report = bench.native_run(m, p, "candidate", "first-baseline", tmp_path, "synthetic-approval", allow_incomplete_cpu=True, selected_case="output-1:output")
  assert report["policy_digest"] == p["digest"]
  assert report["validity"] == "invalid"
  assert any(e["id"] == "pending-policy-diagnostic" and e["status"] == "unverified" for e in report["evidence"])
  assert bench.compare(m, p, report)["decision"] == "unverified"
  assert p["frozen_at"] is None and p["approval_ref"] is None


def test_native_socket_paths_are_bounded_before_server_or_config_processes(tmp_path):
  manifest = fixture("manifest")
  root = Path("/tmp/bn-synthetic")
  session = bench.benchmark_session("bench-partial")
  case = bench.benchmark_case(root, 3, "detached-30", "output", manifest)
  assert len(session) <= 21 and session.startswith("bench-")
  assert len(str(case / "home/.config/herdr/sessions" / session / "herdr-client.sock").encode()) <= 107
  bench.check_socket_capacity(root)
  with pytest.raises(bench.BenchError) as error:
    bench.check_socket_capacity(tmp_path / ("x" * 108))
  assert error.value.code == 2


def test_namespace_helper_refuses_unmapped_root_before_runner(monkeypatch, capsys):
  import importlib.util
  spec = importlib.util.spec_from_file_location("bench_namespace_unmapped", bench.FIXTURE / "namespace_exec.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  monkeypatch.setattr(module, "enter_namespace", lambda: None)
  monkeypatch.setattr(module, "protected_root_visible", lambda: False)
  monkeypatch.setattr(module.os, "execv", lambda *a: pytest.fail("unmapped trusted root must not start runner"))
  assert module.main(["run", "--allow-native"]) == 5
  assert "namespace_trusted_root_ancestor_unmapped" in capsys.readouterr().err


def filter_helper():
  spec = importlib.util.spec_from_file_location("bench_socket_filter", FIXTURES / "socket_filter_exec.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  return module


def test_socket_filter_installs_exact_family_rules_with_fake_libraries():
  from types import SimpleNamespace
  module = filter_helper()
  calls = []
  class Function:
    def __init__(self, fn): self.fn = fn
    def __call__(self, *args): return self.fn(*args)
  def rule(ctx, action, number, count, comparisons):
    calls.append((number, count, comparisons.contents.arg if count else None,
      comparisons.contents.op if count else None, comparisons.contents.datum_a if count else None, action))
    return 0
  lib = SimpleNamespace(seccomp_init=Function(lambda action: 123),
    seccomp_syscall_resolve_name=Function(lambda name: {b"socket": 10, b"socketpair": 11, b"io_uring_setup": 12}[name]),
    seccomp_rule_add_array=Function(rule), seccomp_load=Function(lambda ctx: 0),
    seccomp_release=Function(lambda ctx: calls.append("released")))
  libc = SimpleNamespace(prctl=Function(lambda *args: calls.append(("nnp", args)) or 0))
  module.install_filter(lib=lib, libc=libc)
  assert calls[0][0] == "nnp" and calls[0][1][0:2] == (38, 1)
  assert calls[1:4] == [(10, 1, 0, 1, 1, 0x50001), (11, 1, 0, 1, 1, 0x50001), (12, 0, None, None, None, 0x50001)]
  assert calls[-1] == "released"
  lib.seccomp_load = Function(lambda ctx: -1)
  with pytest.raises(OSError): module.install_filter(lib=lib, libc=libc)


def test_socket_filter_closes_extra_fds_and_rejects_network_stdio():
  from types import SimpleNamespace
  import stat
  module = filter_helper()
  closed = []
  module.close_inherited_fds(fd_numbers=lambda: [0, 1, 2, 4, 8], close=closed.append)
  assert closed == [4, 8]
  with pytest.raises(OSError):
    module.check_stdio(stat_fd=lambda fd: SimpleNamespace(st_mode=stat.S_IFSOCK), family_for_fd=lambda fd: 2)
  module.check_stdio(stat_fd=lambda fd: SimpleNamespace(st_mode=stat.S_IFIFO), family_for_fd=lambda fd: pytest.fail("pipe is not socket"))
  module.check_stdio(stat_fd=lambda fd: SimpleNamespace(st_mode=stat.S_IFSOCK), family_for_fd=lambda fd: 1)


def test_socket_filter_fixed_exec_requires_native_opt_in_and_no_recursion(monkeypatch):
  module = filter_helper()
  calls = []
  monkeypatch.setattr(module, "check_stdio", lambda: calls.append("stdio"))
  monkeypatch.setattr(module, "close_inherited_fds", lambda: calls.append("fds"))
  monkeypatch.setattr(module, "install_filter", lambda: calls.append("filter"))
  monkeypatch.setattr(module, "prove_policy", lambda: calls.append("proof"))
  monkeypatch.setattr(module.os, "execv", lambda executable, argv: calls.append(argv))
  assert module.main(["validate", "--allow-native", "--offline-sockets"]) == 2
  assert module.main(["run", "--offline-sockets"]) == 2
  assert module.main(["run", "--allow-native", "--offline-sockets", "--socket-filter-active"]) == 2
  assert calls == []
  assert module.main(["run", "--allow-native", "--offline-sockets"]) == 0
  assert calls[:4] == ["stdio", "fds", "filter", "proof"]
  assert calls[-1][1] == str(ROOT / "tools/bench/herdr_upgrade.py")
  assert calls[-1][-1] == "--socket-filter-active"


def test_socket_filter_proof_uses_fake_kernel_and_rejects_missing_capabilities():
  import errno
  module = filter_helper()
  def denied(*args): raise OSError(errno.EPERM, "synthetic denied")
  args = dict(status_text="NoNewPrivs:\t1\nSeccomp:\t2\n", create_socket=denied,
    create_pair=denied, unix_check=lambda: True, ring_errno=lambda: errno.EPERM,
    stdio_check=lambda: None, extra_fds_check=lambda: None, root_visible=True)
  proof = module.prove_policy(**args)
  assert proof["mode"] == "offline-sockets-seccomp" and proof["unix_ipc"] is True
  assert proof["inet_errno"] == errno.EPERM and proof["inet6_errno"] == errno.EPERM
  for changed in ({"status_text": "NoNewPrivs:\t0\nSeccomp:\t2\n"},
      {"unix_check": lambda: False}, {"ring_errno": lambda: 0}, {"root_visible": False}):
    with pytest.raises(OSError): module.prove_policy(**{**args, **changed})


def test_offline_sockets_mutually_exclusive_and_fixed_helper_dispatch(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, _ = measured()
  for name, value in (("manifest", m), ("policy", p)):
    (tmp_path / (name + ".json")).write_text(json.dumps(value))
  prefix = ["run", "--manifest", str(tmp_path / "manifest.json"), "--policy", str(tmp_path / "policy.json"),
    "--subject", "candidate", "--scope", "first-baseline", "--allow-native", "--allow-incomplete-cpu",
    "--authorization", "synthetic-approval", "--output", str(tmp_path / "report.json")]
  calls = []
  monkeypatch.setattr(bench.subprocess, "run", lambda argv, **kwargs: calls.append(argv) or type("R", (), {"returncode": 5})())
  assert bench.main(prefix + ["--offline-sockets", "--isolated-netns"]) == 2
  assert not calls
  assert bench.main(prefix + ["--offline-sockets"]) == 5
  assert calls[0][1] == str(FIXTURES / "socket_filter_exec.py")
  assert "--socket-filter-active" not in calls[0]


def test_offline_socket_proof_fails_before_native_preflight(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, _ = measured()
  monkeypatch.setattr(bench, "preflight", lambda *a: pytest.fail("unverified filter cannot preflight"))
  def fail(): raise bench.BenchError(5, "offline_socket_capabilities_unverified")
  monkeypatch.setattr(bench, "socket_filter_proof", fail)
  with pytest.raises(bench.BenchError) as error:
    bench.native_run(m, p, "candidate", "first-baseline", tmp_path, "synthetic-approval", allow_incomplete_cpu=True,
      selected_case="output-1:output", offline_sockets=True)
  assert error.value.code == 5


def test_socket_proof_private_receipt_is_bound_and_does_not_claim_namespace(monkeypatch, tmp_path):
  from test_herdr_upgrade_policy import measured
  m, p, report = measured()
  report["producer"] = [row for row in report["producer"] if (row["workload"], row["mode"], row["batch"]) == ("output-1", "output", 1)]
  m["isolation"]["private_record_root"] = str(tmp_path)
  proof = {"mode": "offline-sockets-seccomp", "no_new_privs": 1, "seccomp": 2,
    "inet_errno": 1, "inet6_errno": 1, "inet_pair_errno": 1, "inet6_pair_errno": 1,
    "unix_ipc": True, "io_uring_errno": 1, "root_owner_visible": True,
    "network_stdio_absent": True, "extra_fds_absent": True, "uid": 1234, "gid": 1234}
  monkeypatch.setattr(bench, "socket_filter_proof", lambda: proof)
  bench.record_socket_filter_proof(report, {"private": tmp_path}, "output-1", "output", 1)
  assert report["isolation"]["evidence_ref"] == "offline-sockets-seccomp"
  assert bench.verify_socket_filter_originals(m, report, tmp_path)
  report["isolation"]["evidence_ref"] = "dedicated-root-and-loopback-namespace"
  assert not bench.verify_socket_filter_originals(m, report, tmp_path)
  report["isolation"]["evidence_ref"] = "offline-sockets-seccomp"
  evidence = report["evidence"][-1]
  path = tmp_path / evidence["evidence_ref"].split(":")[1]
  data = json.loads(path.read_text());data["proof"]["inet_errno"] = 0
  path.write_text(json.dumps(data))
  assert not bench.verify_socket_filter_originals(m, report, tmp_path)


def test_producer_clock_crossing_deadline_never_sleeps_negative():
  producer = producer_module()
  ticks = iter([0, 2, 300_000_000_002, 300_000_000_003, 300_000_000_004, 300_000_000_005])
  sleeps = []
  def sleep(seconds):
    assert seconds >= 0
    sleeps.append(seconds)
  producer.window("idle", 1, "measure", 1, clock=lambda: next(ticks), sleep=sleep)
  assert all(seconds >= 0 for seconds in sleeps)


def test_interactive_client_routes_session_and_fences_fixed_api(tmp_path):
  socket = tmp_path / "herdr.sock"
  socket.touch()
  class Client:
    socket_path = str(socket)
    identity = (socket.stat().st_dev, socket.stat().st_ino)
    def request(self, method, params):
      assert (method, params) == ("ping", {})
      return {}
  calls = []
  def discover(binary, session, deadline):
    calls.append((binary, session))
    return {"name": session, "socket_path": str(socket), "session_dir": str(tmp_path)}
  argv, env = bench.interactive_client_route("herdr", "bench-test", {"HOME": str(tmp_path), "HERDR_SOCKET_PATH": "wrong", "HERDR_PANE_ID": "wrong"}, Client(), discover)
  assert argv == ["herdr", "--session", "bench-test"]
  assert "HERDR_SOCKET_PATH" not in env and "HERDR_PANE_ID" not in env
  assert calls == [("herdr", "bench-test")]
  socket.rename(tmp_path / "old-endpoint")
  socket.touch()
  with pytest.raises(bench.BenchError):
    bench.interactive_client_route("herdr", "bench-test", {}, Client(), discover)


@pytest.mark.parametrize("error,code", [(ValueError("sleep length must be non-negative"), "negative_sleep"), (ValueError("private arbitrary text"), "fixture_validation")])
def test_producer_failure_receipt_contains_only_static_code(tmp_path, monkeypatch, error, code):
  producer = producer_module()
  value = {"run_id": "a" * 32, "mode": "output", "seed": 1, "config_digest": "b" * 64}
  monkeypatch.setenv("HERDR_PANE_ID", "w1:p2")
  monkeypatch.setattr(producer, "config", lambda *args: (value, tmp_path))
  monkeypatch.setattr(producer, "wait_file", lambda *args: {"run_id": value["run_id"], "panes": ["w1:p2"]})
  monkeypatch.setattr(producer, "barrier", lambda *args: 1)
  def fail(*args):
    raise error
  monkeypatch.setattr(producer, "window", fail)
  monkeypatch.setattr(producer.os, "write", lambda *args: 0)
  assert producer.main() == 5
  path = tmp_path / "w1:p2.failure.json"
  assert json.loads(path.read_text()) == {"run_id": "a" * 32, "pane_id": "w1:p2", "phase": "warmup", "error_code": code}
  assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("failure", ["preflight", "spawn", "postflight"])
def test_interactive_attach_tracks_process_and_closes_unowned_fds(tmp_path, monkeypatch, failure):
  import os
  import pty
  import fcntl
  master = os.open(tmp_path / "master", os.O_RDWR | os.O_CREAT, 0o600)
  slave = os.open(tmp_path / "slave", os.O_RDWR | os.O_CREAT, 0o600)
  monkeypatch.setattr(pty, "openpty", lambda: (master, slave))
  monkeypatch.setattr(fcntl, "ioctl", lambda *args: None)
  calls = []
  def route(*args):
    calls.append(1)
    if failure == "preflight" or (failure == "postflight" and len(calls) == 2):
      raise bench.BenchError(4, "interactive_session_changed")
    return ["herdr", "--session", "test"], {"HOME": str(tmp_path)}
  monkeypatch.setattr(bench, "interactive_client_route", route)
  process = object()
  def spawn(*args, **kwargs):
    if failure == "spawn":
      raise OSError("synthetic spawn failed")
    return process
  monkeypatch.setattr(bench.subprocess, "Popen", spawn)
  clients, spawns = [], []
  with pytest.raises((bench.BenchError, OSError)):
    bench.attach_interactive("herdr", "test", {}, None, None, clients, spawns, 120, 40)
  with pytest.raises(OSError):
    os.fstat(slave)
  if failure == "postflight":
    assert clients == [(process, master)]
    assert spawns[0][0] is process
    os.close(master)
  else:
    assert clients == spawns == []
    with pytest.raises(OSError):
      os.fstat(master)


@pytest.mark.parametrize("unknown", [False, True])
def test_cleanup_stops_complete_owned_set_without_closing_panes(monkeypatch, unknown):
  owned = [{"pane_id": "w1:p1", "terminal_id": "t1", "workspace_id": "w1"}, {"pane_id": "w2:p2", "terminal_id": "t2", "workspace_id": "w2"}]
  events = []
  class Client:
    pinned_fd = 9
    pinned_address = "/proc/self/fd/9"
    def request(self, method, params):
      assert method == "pane.list"
      events.append("list")
      return {"panes": list(reversed(owned)) + ([{"pane_id": "unknown"}] if unknown else [])}
  monkeypatch.setattr(bench, "interactive_client_route", lambda *args: events.append("fence"))
  def record(argv, label, env, **kwargs):
    assert argv == ["herdr", "server", "stop"]
    assert env["HERDR_SOCKET_PATH"] == "/proc/self/fd/9"
    assert kwargs["pass_fds"] == (9,)
    events.append("stop")
  if unknown:
    with pytest.raises(bench.BenchError):
      bench.stop_owned_server("herdr", "test", {}, Client(), None, owned, record)
    assert "stop" not in events
  else:
    bench.stop_owned_server("herdr", "test", {}, Client(), None, owned, record)
    assert events == ["fence", "list", "fence", "stop"]


def test_owned_pty_pump_drains_only_registered_fd_without_threads():
  import os
  read_fd, write_fd = os.pipe()
  other_fd, other_write = os.pipe()
  try:
    os.set_blocking(read_fd, False)
    os.write(write_fd, b"synthetic terminal bytes")
    os.write(other_write, b"untouched")
    assert bench.pump_owned_ptys([(None, read_fd)]) == len(b"synthetic terminal bytes")
    assert os.read(other_fd, 32) == b"untouched"
    assert bench.pump_owned_ptys([(None, read_fd)]) == 0
  finally:
    for fd in (read_fd, write_fd, other_fd, other_write):
      os.close(fd)


def test_cpu_window_requires_source_members_and_fixed_window():
  snapshot = {role: {"user_ns": 100, "system_ns": 200} for role in ("server", "client", "producer", "driver")}
  after = {role: {"user_ns": 1100, "system_ns": 1200} for role in snapshot}
  before = {"read_begin_ns": 100, "read_end_ns": 110, "counters": snapshot}
  end = {"read_begin_ns": 300000000100, "read_end_ns": 300000000110, "counters": after}
  values, reason = bench.cpu_window_values(before, end, 100, members_verified=True)
  assert reason is None
  assert values["server_group"] == 0.000002
  _, reason = bench.cpu_window_values(before, end, 100, members_verified=False)
  assert reason == "cpuacct_membership_unproven"
  end["read_end_ns"] += 50000001
  _, reason = bench.cpu_window_values(before, end, 100, members_verified=True)
  assert reason == "cpuacct_window_unproven"


def synthetic_cpu_original():
  import hashlib
  from copy import deepcopy
  manifest = fixture("manifest")
  manifest["measure_specs"] = [{"metric": metric, "group": "server_group", "unit": unit, "required": True}
    for metric, unit in (("cpu.core_seconds", "core-seconds"), ("cpu.cores", "cores"))]
  report = bench.empty_report(manifest, fixture("policy"), "candidate", "first-baseline")
  import os
  delegation = {"schema_version": 1, "method": "cpuacct-v1", "uid": os.getuid(),
    "boot_id": "12345678-1234-1234-1234-123456789abc", "source_cgroup": "/synthetic-source",
    "scope_path": "/synthetic-mount/rotom-bench-" + "a" * 32, "scope_dev": 1, "scope_ino": 2,
    "roles": {role: {"dev": 1, "ino": i + 3} for i, role in enumerate(("server", "client", "producer", "driver"))}, "admin_token": "a" * 32}
  source_digest = hashlib.sha256(bench.canonical(delegation)).hexdigest()
  target = 100
  snapshots = [{"read_begin_ns": target + i * 1_000_000_000, "read_end_ns": target + i * 1_000_000_000 + 10,
    "counters": {role: {"user_ns": i * 1_000_000_000, "system_ns": 0} for role in ("server", "client", "producer", "driver")},
    "server_main": {"pid": 100, "starttime": 10, "ticks": 0, "ticks_per_second": 100} if i in (0, 300) else None} for i in range(301)]
  members = {role: [{"pid": pid, "starttime": pid // 10}] for role, pid in (("server", 100), ("producer", 200), ("driver", 300), ("client", 400))}
  ready = [{"pid": 200, "cpuacct": {"method": "cpuacct-v1", "role": "producer", "delegation_digest": source_digest}}]
  raw = {"method": "cpuacct-v1", "completeness_scope": "server-group-descendants", "workload": "output-1", "mode": "output", "batch": 1,
    "subject_digest": bench.digest(report["subject_identity"]), "delegation": delegation, "delegation_digest": source_digest,
    "module_digest": bench.bytes_digest(ROOT / "tools/bench/cpuacct.py"), "target_start_ns": target, "target_end_ns": target + 300_000_000_000,
    "tolerance_ns": bench.CPU_WINDOW_TOLERANCE_NS, "snapshots": snapshots, "members_before": members, "members_after": deepcopy(members),
    "server_pid": 100, "driver_pid": 300, "client_pids": [400], "ready": ready}
  row = {"workload": "output-1", "mode": "output", "batch": 1, "method": "cpuacct-v1", "completeness_scope": "server-group-descendants",
    "complete": True, "reason": None, "source_digest": source_digest, "evidence_ref": "a" * 32 + ".json", "execution_digest": "b" * 64}
  report["measurements"] = [{"workload": "output-1", "mode": "output", "batch": 1, "metric": metric, "group": "server_group", "unit": unit,
    "value": value, "n": 300, "samples": [1.0] * 300, "reason": None} for metric, unit, value in
    (("cpu.core_seconds", "core-seconds", 300), ("cpu.cores", "cores", 1))]
  report["cpu_windows"] = [row]
  return manifest, report, row, raw


def test_cpu_original_uses_kernel_total_for_short_lived_helpers():
  manifest, report, row, raw = synthetic_cpu_original()
  # TGID 没有增加，而内核聚合计入未在任意 proc 快照留下的短命后代。
  assert raw["snapshots"][0]["server_main"] == raw["snapshots"][-1]["server_main"]
  assert bench.verify_cpu_original(manifest, report, row, raw)
  report["measurements"][0]["value"] = 0
  assert not bench.verify_cpu_original(manifest, report, row, raw)


@pytest.mark.parametrize("mutation", ["membership", "source", "counter", "window", "scope", "samples", "tolerance", "pid_reuse", "main_identity"])
def test_cpu_original_missing_proof_never_complete(mutation):
  manifest, report, row, raw = synthetic_cpu_original()
  if mutation == "membership":
    raw["members_after"]["producer"] = []
  elif mutation == "source":
    raw["delegation"]["method"] = "procfs"
  elif mutation == "counter":
    raw["snapshots"][120]["counters"]["server"]["user_ns"] = -1
  elif mutation == "window":
    raw["snapshots"][-1]["read_end_ns"] += 50_000_001
  elif mutation == "scope":
    row["completeness_scope"] = "procfs-visible"
  elif mutation == "samples":
    raw["snapshots"].pop(120)
  elif mutation == "tolerance":
    raw["tolerance_ns"] += 1
  elif mutation == "pid_reuse":
    raw["members_after"]["server"][0]["starttime"] += 1
  else:
    raw["snapshots"][-1]["server_main"]["starttime"] += 1
  try:
    proven = bench.verify_cpu_original(manifest, report, row, raw)
  except bench.BenchError:
    proven = False
  assert not proven


def test_cpu_average_uses_actual_endpoint_interval():
  manifest, report, row, raw = synthetic_cpu_original()
  raw["snapshots"][-1]["read_begin_ns"] += 10_000_000
  raw["snapshots"][-1]["read_end_ns"] += 10_000_000
  average = next(item for item in report["measurements"] if item["metric"] == "cpu.cores")
  average["value"] = 300 / 300.01
  assert bench.verify_cpu_original(manifest, report, row, raw)
  average["value"] = 1.0
  assert not bench.verify_cpu_original(manifest, report, row, raw)


def test_server_tgid_identity_and_negative_helpers_are_not_clamped():
  before = {"pid": 100, "starttime": 1, "ticks": 10, "ticks_per_second": 100}
  after = {**before, "ticks": 13}
  assert bench.server_cpu_delta(before, after) == (0.03, None)
  values, reason = bench.server_cpu_breakdown(0.02, before, after)
  assert values == {"server": 0.03, "helpers": None}
  assert reason == "server_tgid_tick_precision_unproven"
  after["starttime"] = 2
  assert bench.server_cpu_delta(before, after)[0] is None


def test_cpu_receipt_reused_for_all_cases_and_closed_on_failure(monkeypatch, tmp_path):
  manifest, policy = fixture("manifest"), fixture("policy")
  manifest["authorization_ref"] = "synthetic-approval"
  receipt = tmp_path / "delegation.json"
  receipt.write_text('{"synthetic":true}')
  events = []
  class Groups:
    receipt_digest = bench.hashlib.sha256(bench.canonical({"synthetic": True})).hexdigest()
    def __init__(self, path):
      assert path == receipt
      events.append("open")
    def __enter__(self):
      return self
    def join_self(self, role):
      events.append(role)
    def __exit__(self, *args):
      events.append("close")
  def run(*args, **kwargs):
    assert isinstance(kwargs["cpuacct_groups"], Groups)
    assert kwargs["cpuacct_original"] == {"synthetic": True}
    raise RuntimeError("synthetic-run-failure")
  monkeypatch.setattr(bench, "CpuacctGroups", Groups)
  monkeypatch.setattr(bench, "_native_run", run)
  with pytest.raises(RuntimeError, match="synthetic-run-failure"):
    bench.native_run(manifest, policy, "candidate", "first-baseline", tmp_path, "synthetic-approval", cpuacct_delegation=receipt)
  assert events == ["open", "driver", "close"]


def test_attach_restoration_failure_keeps_child_and_fd_tracked(monkeypatch):
  import os
  from contextlib import contextmanager
  class Groups:
    @contextmanager
    def spawn(self, role):
      assert role == "client"
      yield
      raise bench.CpuacctError("cpuacct_join")
  process = object()
  monkeypatch.setattr(bench, "interactive_client_route", lambda *args: (["herdr", "--session", "synthetic"], {}))
  monkeypatch.setattr(bench.subprocess, "Popen", lambda *args, **kwargs: process)
  clients, spawns = [], []
  try:
    with pytest.raises(bench.CpuacctError, match="cpuacct_join"):
      bench.attach_interactive("herdr", "synthetic", {}, None, None, clients, spawns, 120, 40, Groups())
    assert clients[0][0] is process
    assert spawns[0][0] is process
    assert not os.get_blocking(clients[0][1])
  finally:
    for process, fd in clients:
      os.close(fd)


def test_pty_pump_eof_does_not_spin(monkeypatch):
  import os
  read_fd, write_fd = os.pipe()
  os.set_blocking(read_fd, False)
  os.close(write_fd)
  sleeps = []
  monkeypatch.setattr(bench.time, "sleep", lambda seconds: sleeps.append(seconds))
  try:
    assert bench.pump_owned_ptys([(None, read_fd)], 0.01) == 0
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 0.01
  finally:
    os.close(read_fd)


def test_cpu_producer_optional_field_strict_and_fixed_join(tmp_path, monkeypatch):
  import hashlib
  producer = producer_module()
  control = tmp_path / "control"
  control.mkdir(mode=0o700)
  anchor = {"version": 1, "run_id": "a" * 32, "mode": "idle", "seed": 1, "control_dir": str(control), "cpuacct_receipt": "/synthetic/delegation.json"}
  anchor["config_digest"] = hashlib.sha256(producer.canonical(anchor)).hexdigest()
  config_path = tmp_path / ".rotom-bench-v1.json"
  producer.write_new(config_path, anchor)
  assert producer.config(tmp_path, "w1:p1")[0] == anchor
  anchor["cpuacct_receipt"] = ["invalid-command"]
  anchor["config_digest"] = hashlib.sha256(producer.canonical({key: value for key, value in anchor.items() if key != "config_digest"})).hexdigest()
  config_path.write_bytes(producer.canonical(anchor))
  with pytest.raises(ValueError, match="invalid fixture configuration"):
    producer.config(tmp_path, "w1:p1")


def test_sleep_pumps_ptys_without_turning_rss_into_100hz(monkeypatch):
  clock = [0]
  samples, pumps = [], []
  class Sampler:
    def sample(self):
      samples.append(clock[0])
  monkeypatch.setattr(bench.time, "monotonic_ns", lambda: clock[0])
  def pump(clients, timeout):
    pumps.append(timeout)
    clock[0] += int(timeout * 1_000_000_000)
  monkeypatch.setattr(bench, "pump_owned_ptys", pump)
  bench._sleep_until(3_000_000_000, Sampler(), [])
  assert len(samples) == 3
  assert len(pumps) == 300


@pytest.mark.parametrize("fail_cpu", [False, True])
@pytest.mark.parametrize("batch_numbers", [(1,), (1, 2)])
def test_native_case_collects_kernel_cpu_and_closes_owned_fds(monkeypatch, tmp_path, fail_cpu, batch_numbers):
  import os
  from contextlib import contextmanager, nullcontext
  import termcfg.herdr as herdr
  import termcfg.work as work
  import termcfg.work_config as work_config
  manifest, _, _, template = synthetic_cpu_original()
  manifest["workloads"] = [{"id": "idle-1", "modes": ["idle"], "terminals": 1}]
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  clock, state = [1_000_000_000], {"role": "driver", "started": False, "ready": False, "client": False, "closed": False}
  events, descriptors = [], []
  monkeypatch.setattr(bench.time, "monotonic_ns", lambda: clock[0])
  monkeypatch.setattr(bench.time, "monotonic", lambda: clock[0] / 1_000_000_000)
  monkeypatch.setattr(bench, "_sleep_until", lambda target, *args, **kwargs: clock.__setitem__(0, target))
  class Groups:
    receipt_digest = template["delegation_digest"]
    @contextmanager
    def spawn(self, role):
      assert state["role"] == "driver"
      state["role"] = role
      events.append(role)
      try:
        yield
      finally:
        state["role"] = "driver"
    def wait_case_empty(self):
      assert server.returncode == 0
      events.append("case-empty")
      state.update(started=False, ready=False, client=False)
    def members(self):
      if not state["started"]:
        events.append("entry-members")
      return {"server": [{"pid": 100, "starttime": 10}] if state["started"] else [],
        "producer": [{"pid": 200, "starttime": 20}] if state["ready"] else [],
        "client": [{"pid": 400, "starttime": 40}] if state["client"] else [],
        "driver": [{"pid": os.getpid(), "starttime": 30}]}
    def read(self):
      assert state["role"] == "driver"
      if fail_cpu:
        raise bench.CpuacctError("cpuacct_counter_regressed")
      return {role: {"user_ns": clock[0], "system_ns": 0} for role in ("server", "client", "producer", "driver")}
  groups = Groups()
  class Process:
    def __init__(self, args, **kwargs):
      assert state["role"] == "client"
      self.args, self.returncode, self.pid = args, None, 500
    def communicate(self, **kwargs):
      assert state["role"] == "driver"
      self.returncode = 0
      if self.args[1:3] == ["pane", "process-info"]:
        return json.dumps({"result": {"process_info": {"shell_pid": 200}}}).encode(), None
      return (("herdr " + manifest["subjects"]["candidate"]["client_version"]).encode() if self.args[-1] == "--version" else b"{}"), None
    def poll(self):
      return self.returncode
    def wait(self, **kwargs):
      self.returncode = 0
      return 0
  class Server:
    args = [str(tmp_path / "herdr"), "--session", "bench-fake", "server"]
    pid, returncode = 100, None
    def poll(self):
      return self.returncode
    def wait(self, **kwargs):
      if self.pid == 100:
        events.append("server-wait")
      self.returncode = 0
      return 0
  server = Server()
  def start(*args):
    assert state["role"] == "server"
    state["started"] = True
    server.returncode = None
    return server
  monkeypatch.setattr(herdr, "start_headless", start)
  monkeypatch.setattr(herdr, "discover", lambda binary, session, deadline: {"socket_path": "/synthetic.sock"} if state["started"] else None)
  monkeypatch.setattr(herdr, "verify_schema", lambda *args: None)
  pane = {"pane_id": "w1:p2", "workspace_id": "w1", "terminal_id": "t2"}
  caller = {"pane_id": "w1:p1", "workspace_id": "w1", "terminal_id": "t1"}
  class Client:
    socket_path, pinned_address, pinned_fd = "/synthetic.sock", "/proc/self/fd/9", 9
    def __init__(self, *args):
      pass
    def request(self, method, params):
      if method == "ping":
        return {"version": manifest["subjects"]["candidate"]["server_version"]}
      if method == "pane.list":
        return {"panes": [caller] if params else []}
      if method == "pane.get":
        return {"pane": caller}
      pytest.fail("unexpected fake API")
    def close(self):
      state["closed"] = True
  monkeypatch.setattr(herdr, "HerdrClient", Client)
  monkeypatch.setattr(work, "enter_project", lambda *args: {"workspace_id": "w1"})
  monkeypatch.setattr(work, "open_role", lambda *args, **kwargs: pane)
  monkeypatch.setattr(work, "operation_lock", lambda *args: nullcontext())
  monkeypatch.setattr(work_config, "read_settings", lambda **kwargs: object())
  monkeypatch.setattr(bench.subprocess, "Popen", Process)
  monkeypatch.setattr(bench, "matches_recipe", lambda *args: True)
  monkeypatch.setattr(bench, "benchmark_session", lambda *args: "bench-fake")
  monkeypatch.setattr(bench, "server_cpu_identity", lambda pid: {"pid": pid, "starttime": 10, "ticks": 0, "ticks_per_second": 100})
  monkeypatch.setattr(bench, "stop_owned_server", lambda *args: None)
  monkeypatch.setattr(bench, "_known_producer_identity", lambda pid: (20, state["producer_cwd"]))
  def attach(binary, session, env, client, discover, clients, spawns, cols, rows, delegated, ready_run_id=None):
    assert delegated is groups
    assert ready_run_id is None
    with groups.spawn("client"):
      read_fd, write_fd = os.pipe()
      os.set_blocking(read_fd, False)
      descriptors.extend((read_fd, write_fd))
      process = Server()
      process.pid = 400
      clients.append((process, read_fd))
      state["client"] = True
  monkeypatch.setattr(bench, "attach_interactive", attach)
  monkeypatch.setattr(bench, "detach_owned_client", lambda process, master, **kwargs: process.wait(timeout=5))
  original_private = bench._private_value
  def private_value(path, value):
    original_private(path, value)
    if path.name == ".rotom-bench-v1.json":
      state["producer_cwd"] = str(path.parent.resolve())
      state["producer_config_digest"] = value["config_digest"]
    if path.name == "expected.json":
      state["ready"] = True
      original_private(path.parent / (pane["pane_id"] + ".ready.json"), {"run_id": value["run_id"], "pane_id": pane["pane_id"], "pid": 200, "config_digest": state["producer_config_digest"],
        "cpuacct": {"method": "cpuacct-v1", "role": "producer", "delegation_digest": groups.receipt_digest}})
    if path.name in {"warmup.json", "measure.json"}:
      phase = value["phase"]
      original_private(path.parent / (pane["pane_id"] + "." + phase + ".json"), {"run_id": value["run_id"], "pane_id": pane["pane_id"],
        "mode": "idle", "phase": phase, "start_ns": value["start_ns"], "end_ns": value["start_ns"] + (60 if phase == "warmup" else 300) * 1_000_000_000,
        "lines": 0, "bytes": 0, "cpu_seconds": 0.0, "backpressure_seconds": 0.0})
  monkeypatch.setattr(bench, "_private_value", private_value)
  try:
    report = bench._native_measure(manifest, fixture("policy"), "candidate", "first-baseline", tmp_path, "synthetic-approval",
      {"root": tmp_path / "case", "binary": tmp_path / "herdr", "private": private, "sentinels": [], "cpuacct_groups": groups,
       "cpuacct_receipt": tmp_path / "delegation.json", "cpuacct_original": template["delegation"]}, batch_numbers=batch_numbers, case_filter=("idle-1", "idle"))
    assert state["closed"] and state["role"] == "driver"
    assert "server" in events
    transitions = [event for event in events if event in {"entry-members", "server-wait", "case-empty"}]
    assert transitions == (["entry-members"] if fail_cpu else ["entry-members", "server-wait", "case-empty"] * len(batch_numbers))
    for fd in descriptors[::2]:
      with pytest.raises(OSError):
        os.fstat(fd)
    if fail_cpu:
      assert report["operation_exit_code"] == 5
      assert not report["coverage"]["cpu_complete"]
      failure = next(row for row in report["evidence"] if row["reason"] == "native_operation_failed_or_unknown_no_replay")
      prefix, name, checksum = failure["evidence_ref"].split(":")
      assert prefix == "native-failure" and bench.bytes_digest(private / name) == checksum
      original = bench.read_json(private / name)
      assert original["phase"] == "case-runtime" and original["exception_category"] == "cpuacct"
      assert original["reason_code"] == "cpuacct_counter_regressed" and original["exit_code"] == 5
    else:
      assert report["operation_exit_code"] == 0
      assert report["cpu_windows"][0]["complete"]
      raw = bench.read_json(private / report["cpu_windows"][0]["evidence_ref"])
      assert len(raw["snapshots"]) == 301
      assert bench.verify_cpu_original(manifest, report, report["cpu_windows"][0], raw)
      assert report["measurements"][0]["value"] == 300
      assert not report["coverage"]["cpu_complete"]  # 单 case / batch 不晋升完整覆盖。
  finally:
    for fd in descriptors:
      try:
        os.close(fd)
      except OSError:
        pass


def test_producer_joins_fixed_module_before_ready_and_barrier(monkeypatch, tmp_path):
  producer = producer_module()
  value = {"run_id": "a" * 32, "mode": "idle", "seed": 1, "config_digest": "b" * 64,
    "cpuacct_receipt": "/synthetic/delegation.json"}
  proof = {"method": "cpuacct-v1", "role": "producer", "delegation_digest": "c" * 64}
  events, writes = [], []
  monkeypatch.setattr(producer, "config", lambda *args: (value, tmp_path))
  monkeypatch.setenv("HERDR_PANE_ID", "w1:p1")
  def wait_file(*args):
    events.append("expected")
    return {"run_id": value["run_id"], "panes": ["w1:p1"]}
  monkeypatch.setattr(producer, "wait_file", wait_file)
  monkeypatch.setattr(producer, "write_new", lambda path, payload: writes.append((path.name, payload)))
  def barrier(*args):
    events.append("barrier")
    raise ValueError("stop synthetic fixture")
  monkeypatch.setattr(producer, "barrier", barrier)
  monkeypatch.setattr(producer.os, "write", lambda *args: 0)
  class Module:
    CpuacctError = bench.CpuacctError
    @staticmethod
    def join_producer(path):
      events.append("join")
      assert path == value["cpuacct_receipt"]
      return proof
  import importlib.util
  class Loader:
    def exec_module(self, module):
      assert module is Module
  def module_spec(name, path):
    assert path == ROOT / "tools/bench/cpuacct.py"
    return type("Spec", (), {"loader": Loader()})()
  with monkeypatch.context() as patch:
    patch.setattr(importlib.util, "spec_from_file_location", module_spec)
    patch.setattr(importlib.util, "module_from_spec", lambda spec: Module)
    assert producer.main() == 5
  assert events == ["join", "expected", "barrier"]
  assert writes[0][0] == "w1:p1.ready.json"
  assert writes[0][1]["cpuacct"] == proof


@pytest.mark.parametrize("category", ["bench", "cpuacct", "termcfg", "subprocess", "os", "key", "value"])
def test_native_failure_original_excludes_unknown_reason_and_exception_text(tmp_path, category):
  import subprocess
  from termcfg.errors import TermcfgError
  secret = "synthetic_secret_never_recorded"
  errors = {"bench": bench.BenchError(5, secret), "cpuacct": bench.CpuacctError(secret),
    "termcfg": TermcfgError(5, secret), "subprocess": subprocess.SubprocessError(secret),
    "os": OSError(secret), "key": KeyError(secret), "value": ValueError(secret)}
  reference = bench._record_native_failure(tmp_path, "idle-10", "idle", 1, "cpuacct-members", errors[category], 5)
  prefix, name, checksum = reference.split(":")
  assert prefix == "native-failure"
  path = tmp_path / name
  assert path.stat().st_mode & 0o777 == 0o600
  assert bench.bytes_digest(path) == checksum
  raw = bench.read_json(path)
  assert set(raw) == {"schema_version", "kind", "workload", "mode", "batch", "at_ns", "phase", "exception_category", "exit_code", "reason_code"}
  assert raw["schema_version"] == 1 and raw["kind"] == "native-case-failure-v1"
  assert raw["phase"] == "cpuacct-members" and raw["exception_category"] == category
  assert raw["reason_code"] is None and raw["exit_code"] == 5
  assert type(raw["at_ns"]) is int and raw["at_ns"] > 0
  assert secret.encode() not in path.read_bytes()
  second = bench._record_native_failure(tmp_path, "idle-10", "idle", 1, "cpuacct-members", errors[category], 5)
  assert second != reference and path.exists()


@pytest.mark.parametrize("phase", ["socket-proof", "cpuacct-members", "discover", "version"])
@pytest.mark.parametrize("metadata_write_fails", [False, True])
def test_native_failure_records_phase_before_first_case_operation(tmp_path, monkeypatch, phase, metadata_write_fails):
  from contextlib import nullcontext
  import termcfg.herdr as herdr
  from termcfg.errors import TermcfgError
  manifest = fixture("manifest")
  manifest["workloads"] = [{"id": "idle-10", "modes": ["idle"], "terminals": 10}]
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  events = []
  def fault():
    events.append(phase)
    if phase == "cpuacct-members":
      raise bench.CpuacctError("cpuacct_member_identity")
    if phase == "discover":
      raise TermcfgError(5, "Herdr public CLI unavailable or incompatible")
    if phase == "socket-proof":
      raise bench.BenchError(5, "offline_socket_capabilities_unverified")
    raise ValueError("synthetic_secret_never_recorded")
  class Groups:
    def spawn(self, role):
      return nullcontext()
    def members(self):
      if phase == "cpuacct-members":
        fault()
      return {role: [] for role in ("server", "client", "producer", "driver")}
  def discover(*args):
    if phase == "discover":
      fault()
    return None
  monkeypatch.setattr(herdr, "discover", discover)
  monkeypatch.setattr(bench, "record_socket_filter_proof", lambda *args: fault())
  monkeypatch.setattr(bench, "matches_recipe", lambda *args: True)
  if metadata_write_fails:
    def unavailable(*args):
      raise OSError("synthetic_secret_never_recorded")
    monkeypatch.setattr(bench, "_record_native_failure", unavailable)
  monkeypatch.setattr(bench.subprocess, "Popen", lambda *args, **kwargs: fault() if phase == "version" else pytest.fail("native spawn"))
  original_environment = dict(bench.os.environ)
  prepared = {"root": tmp_path / "case", "binary": tmp_path / "herdr", "private": private,
    "sentinels": [], "cpuacct_groups": Groups()}
  if phase == "socket-proof":
    prepared["isolation_mode"] = "offline-sockets"
  report = bench._native_measure(manifest, fixture("policy"), "candidate", "first-baseline", tmp_path,
    "synthetic-approval", prepared, batch_numbers=(1,), case_filter=("idle-10", "idle"))
  assert events == [phase] and report["operation_exit_code"] == 5
  assert report["invalid_reasons"] == ["native_operation_incomplete_objects_preserved"]
  assert report["decision"] == "measured" and report["validity"] == "invalid"
  assert not report["steps"] and not report["cpu_windows"]
  assert dict(bench.os.environ) == original_environment
  evidence = report["evidence"][-1]
  assert evidence["status"] == "unverified" and evidence["reason"] == "native_operation_failed_or_unknown_no_replay"
  if metadata_write_fails:
    assert evidence["evidence_ref"] is None and not list(private.iterdir())
    return
  _, name, checksum = evidence["evidence_ref"].split(":")
  raw = bench.read_json(private / name)
  assert bench.bytes_digest(private / name) == checksum
  assert raw["phase"] == phase and raw["workload"] == "idle-10"
  assert raw["mode"] == "idle" and raw["batch"] == 1
  expected = {"socket-proof": "offline_socket_capabilities_unverified", "cpuacct-members": "cpuacct_member_identity",
    "discover": "herdr_public_cli_unavailable", "version": None}
  assert raw["reason_code"] == expected[phase]
  assert b"synthetic_secret_never_recorded" not in (private / name).read_bytes()


def test_native_failure_does_not_stringify_exception_or_accept_format_only_reason(tmp_path):
  tmp_path = tmp_path / "metadata"
  tmp_path.mkdir(mode=0o700)
  class Opaque(ValueError):
    def __str__(self):
      pytest.fail("exception text must not be read")
    def __repr__(self):
      pytest.fail("exception representation must not be read")
  secret = "synthetic_secret_never_recorded"
  errors = [Opaque(secret), bench.CpuacctError("cpuacct_" + secret), bench.BenchError(5, [secret])]
  for error in errors:
    _, name, _ = bench._record_native_failure(tmp_path, "idle-10", "idle", 1, "discover", error, 5).split(":")
    assert bench.read_json(tmp_path / name)["reason_code"] is None
    assert secret.encode() not in (tmp_path / name).read_bytes()
  assert len(list(tmp_path.iterdir())) == 3


def test_native_failure_rejects_unknown_phase_and_category_without_writing(tmp_path):
  tmp_path = tmp_path / "metadata"
  tmp_path.mkdir(mode=0o700)
  with pytest.raises(bench.BenchError, match="invalid_native_failure_phase"):
    bench._record_native_failure(tmp_path, "idle-10", "idle", 1, "private-context", ValueError(), 5)
  with pytest.raises(bench.BenchError, match="invalid_native_failure_category"):
    bench._record_native_failure(tmp_path, "idle-10", "idle", 1, "discover", RuntimeError(), 5)
  assert not list(tmp_path.iterdir())


def test_native_first_case_existing_members_are_not_waited_or_retried(tmp_path, monkeypatch):
  manifest = fixture("manifest")
  manifest["workloads"] = [{"id": "idle-10", "modes": ["idle"], "terminals": 10}]
  private = tmp_path / "private"
  private.mkdir(mode=0o700)
  events = []
  class Groups:
    def members(self):
      events.append("members")
      return {"server": [{"pid": 123, "starttime": 456}], "client": [], "producer": [], "driver": []}
    def wait_case_empty(self, *args, **kwargs):
      pytest.fail("preexisting first-case members cannot be waited away")
    def spawn(self, role):
      pytest.fail("preexisting members must fail before spawn")
  report = bench._native_measure(manifest, fixture("policy"), "candidate", "first-baseline", tmp_path,
    "synthetic-approval", {"root": tmp_path / "case", "binary": tmp_path / "herdr", "private": private,
      "sentinels": [], "cpuacct_groups": Groups()}, batch_numbers=(1,), case_filter=("idle-10", "idle"))
  assert events == ["members"] and report["operation_exit_code"] == 4
  assert report["validity"] == "invalid" and not report["steps"]
  reference = report["evidence"][-1]["evidence_ref"]
  _, name, _ = reference.split(":")
  raw = bench.read_json(private / name)
  assert raw["phase"] == "cpuacct-members" and raw["reason_code"] == "cpuacct_previous_case_members_remain"


def test_native_cleanup_timeout_reason_is_preserved_as_fixed_diagnostic(tmp_path):
  reference = bench._record_native_failure(tmp_path, "idle-10", "idle", 1, "case-runtime",
    bench.CpuacctError("cpuacct_case_cleanup_timeout"), 5)
  _, name, _ = reference.split(":")
  raw = bench.read_json(tmp_path / name)
  assert raw["reason_code"] == "cpuacct_case_cleanup_timeout" and raw["exit_code"] == 5


@pytest.mark.parametrize("side", ["owned", "live"])
@pytest.mark.parametrize("corruption", ["empty", "duplicate", "conflicting-pane", "missing-row",
  "missing-pane_id", "missing-terminal_id", "missing-workspace_id", "replaced-pane_id",
  "replaced-terminal_id", "replaced-workspace_id", "invalid-value", "not-list"])
def test_whole_server_cleanup_preserves_any_unproven_set(monkeypatch, side, corruption):
  from copy import deepcopy
  owned = [{"pane_id": "w" + str(i) + ":p1", "terminal_id": "t" + str(i), "workspace_id": "w" + str(i)} for i in range(3)]
  live = deepcopy(owned)
  target = owned if side == "owned" else live
  if corruption == "empty":
    target.clear()
  elif corruption == "duplicate":
    target.append(deepcopy(target[0]))
  elif corruption == "conflicting-pane":
    target.append({**target[0], "terminal_id": "conflicting"})
  elif corruption == "missing-row":
    target.pop()
  elif corruption.startswith("missing-"):
    target[0].pop(corruption.removeprefix("missing-"))
  elif corruption.startswith("replaced-"):
    target[0][corruption.removeprefix("replaced-")] = "replacement"
  elif corruption == "invalid-value":
    target[0]["terminal_id"] = []
  elif side == "owned":
    owned = {"unexpected": "mapping"}
  else:
    live = {"unexpected": "mapping"}
  events = []
  class Client:
    def request(self, method, params):
      assert method == "pane.list" and params == {}
      events.append("list")
      return {"panes": live}
  monkeypatch.setattr(bench, "interactive_client_route", lambda *args: events.append("fence"))
  def record(*args, **kwargs):
    pytest.fail("unproven owned membership cannot stop a server")
  with pytest.raises(bench.BenchError) as error:
    bench.stop_owned_server("herdr", "test", {}, Client(), None, owned, record)
  assert error.value.code == 4
  assert events in ([], ["fence", "list"])


@pytest.mark.parametrize("response", [{}, {"panes": None}, {"panes": [None]}, None])
def test_whole_server_cleanup_rejects_malformed_listing(monkeypatch, response):
  owned = [{"pane_id": "w1:p1", "terminal_id": "t1", "workspace_id": "w1"}]
  class Client:
    def request(self, *args):
      return response
  monkeypatch.setattr(bench, "interactive_client_route", lambda *args: None)
  with pytest.raises(bench.BenchError) as error:
    bench.stop_owned_server("herdr", "test", {}, Client(), None, owned,
      lambda *args, **kwargs: pytest.fail("malformed listing cannot stop"))
  assert error.value.code == 4


@pytest.mark.parametrize("failed_fence", [1, 2])
def test_whole_server_cleanup_does_not_stop_after_route_change(monkeypatch, failed_fence):
  owned = [{"pane_id": "w1:p1", "terminal_id": "t1", "workspace_id": "w1"}]
  fences = []
  class Client:
    def request(self, *args):
      return {"panes": owned}
  def fence(*args):
    fences.append(True)
    if len(fences) == failed_fence:
      raise bench.BenchError(4, "interactive_endpoint_changed")
  monkeypatch.setattr(bench, "interactive_client_route", fence)
  with pytest.raises(bench.BenchError, match="interactive_endpoint_changed"):
    bench.stop_owned_server("herdr", "test", {}, Client(), None, owned,
      lambda *args, **kwargs: pytest.fail("route changed"))
  assert len(fences) == failed_fence
