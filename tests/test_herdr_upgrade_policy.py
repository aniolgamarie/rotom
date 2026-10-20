"""首基线、噪声、必需缺证及正确性失败优先级。"""
from copy import deepcopy

import pytest

from test_herdr_benchmark import bench, fixture


def test_no_calibration_or_budget_never_passes():
  manifest, policy = fixture("manifest"), fixture("policy")
  report = bench.empty_report(manifest, policy, "candidate", "first-baseline")
  assert bench.compare(manifest, policy, report)["decision"] == "unverified"


def test_correctness_failure_cannot_be_hidden_by_invalid_performance():
  manifest, policy = fixture("manifest"), fixture("policy")
  report = bench.empty_report(manifest, policy, "candidate", "first-baseline")
  report["validity"] = "invalid"
  report["invalid_reasons"] = ["producer_shortfall"]
  report["correctness"] = [{"id": "wrong_target", "status": "failure", "evidence_ref": "synthetic-case", "reason": "wrong synthetic workspace"}]
  result = bench.compare(manifest, policy, report)
  assert result["decision"] == "failure"
  assert result["task_status"] == "失败待决策"


def test_relative_and_absolute_threshold_both_required_near_zero():
  threshold = {"relative": 0.1, "absolute": 2, "near_zero": 0.1}
  assert not bench.regression(100, 101, threshold)
  assert not bench.regression(100, 105, threshold)
  assert bench.regression(100, 115, threshold)
  assert bench.regression(0, 3, threshold)


def test_producer_shortfall_invalidates_without_inventing_zero():
  report = {"producer": [{"workload": "output-1", "batch": 1, "pane_label": "pane-1", "mode": "output", "phase": "measure", "start_ns": 1, "end_ns": 300000000001, "lines": 0, "bytes": 0, "cpu_seconds": 0.1, "backpressure_seconds": 1.0}], "validity": "valid", "invalid_reasons": []}
  bench.check_producers(report)
  assert report["validity"] == "invalid"
  assert "producer_shortfall" in report["invalid_reasons"]


def measured(*, scope="first-baseline", values=(10, 10, 10), optional=False):
  manifest, policy = fixture("manifest"), fixture("policy")
  manifest["scope"] = policy["scope"] = scope
  manifest["authorization_ref"] = "synthetic-approval"
  manifest["correctness_cases"] = ["synthetic-target"]
  manifest["measure_specs"] = [{"metric": "cpu.cores", "group": "server_group", "unit": "cores", "required": True}]
  if optional:
    manifest["measure_specs"].append({"metric": "pss", "group": "server_group", "unit": "bytes", "required": False})
  identity = bench.public_subject(manifest["subjects"]["candidate"])
  if scope != "first-baseline":
    manifest["subjects"].update(baseline=deepcopy(manifest["subjects"]["candidate"]), baseline_reason=None)
  bench.sealed(manifest)
  policy.update(frozen_at="2026-01-01T00:00:00Z", approval_ref="synthetic-test-approval", metrics=[{"metric": "cpu.cores", "group": "server_group", "unit": "cores", "absolute_budget": 20, "budget_reason": None, "regression": {"relative": 0.1, "absolute": 2, "near_zero": 0.1}, "noise_absolute": 1, "noise_reason": None}], calibration_refs=[{"report_digest": "a" * 64, "subject_digest": bench.digest(identity), "evidence_ref": "synthetic-aa.json", "policy_digest": "b" * 64, "policy_ref": "absolute-policy.json"}])
  bench.sealed(policy)
  report = bench.empty_report(manifest, policy, "candidate", scope)
  report.update(validity="valid", reason=None, invalid_reasons=[], correctness=[{"id": "synthetic-target", "status": "pass", "evidence_ref": "test-case", "reason": None}], evidence=[{"id": "synthetic-required", "required": True, "status": "pass", "evidence_ref": "test-case", "reason": None}])
  # 比较器单测显式信任 originals_verified；这里只提供逻辑引用，不伪造原生帧或文件。
  for kind in ("ready", "geometry"):
    for batch in (1, 2, 3):
      proof_digest = bench.digest({"synthetic_unit_proof": True, "kind": kind, "batch": batch})
      report["evidence"].append({"id": "client-" + kind + "-batch-" + str(batch), "required": True,
        "status": "pass", "evidence_ref": "client-proof-" + proof_digest + ".json", "reason": None})
  report["isolation"].update(verified=True, sentinels_unchanged=True, private_originals_verified=True, evidence_ref="synthetic-test-only")
  report["coverage"].update(cpu_complete=True, client_ready_proven=True, dimensions_proven=True, client_version_verified=True, effective_inputs_verified=True, reason=None)
  report["batches"] = [{"batch": b, "order": ["candidate"], "warmup_seconds": 60, "measure_seconds": 300, "start_ns": 1, "end_ns": 300000000001, "identity_digest": bench.digest(identity)} for b in (1, 2, 3)]
  report["measurements"] = [{"workload": w["id"], "mode": mode, "batch": batch, "metric": "cpu.cores", "group": "server_group", "unit": "cores", "value": value, "n": 300, "reason": None, "samples": []} for w in manifest["workloads"] for mode in w["modes"] for batch, value in enumerate(values, 1)]
  report["cpu_windows"] = [{"workload": item["workload"], "mode": item["mode"], "batch": item["batch"],
    "method": "cpuacct-v1", "completeness_scope": "server-group-descendants", "complete": True, "reason": None,
    "source_digest": "c" * 64, "execution_digest": "d" * 64, "evidence_ref": f"{number:032x}.json"}
    for number, item in enumerate(report["measurements"])]
  report["producer"] = [{"workload": w["id"], "batch": batch, "pane_label": "pane-" + str(pane), "mode": mode, "phase": phase, "start_ns": 1 if phase == "warmup" else 60000000002, "end_ns": 60000000001 if phase == "warmup" else 360000000002, "lines": seconds * 512 if mode == "output" else 0, "bytes": seconds * 512 * 128 if mode == "output" else 0, "cpu_seconds": 0.1, "backpressure_seconds": 0.0} for w in manifest["workloads"] for mode in w["modes"] for batch in (1, 2, 3) for phase, seconds in (("warmup", 60), ("measure", 300)) for pane in range(w["terminals"])]
  for batch in report["batches"]:
    batch["end_ns"] = 400000000001
  return manifest, policy, bench.sealed(report)


def decide(manifest, policy, candidate, baseline=None):
  return bench.compare(manifest, policy, candidate, baseline, originals_verified=True, calibration_verified=True, baseline_accepted=True)


def test_complete_synthetic_first_baseline_is_scoped_not_upgrade():
  m, p, r = measured(optional=True)
  result = decide(m, p, r)
  assert result["decision"] == "pass"
  assert result["comparison_kind"] == "first-baseline"
  assert any(item["decision"] == "unverified" and "pss" in item["id"] for item in result["item_decisions"])


def test_reproducible_absolute_budget_failure_and_split_batches():
  for values, expected in [((25, 25, 25), "failure"), ((25, 10, 10), "unverified")]:
    m, p, r = measured(values=values)
    assert decide(m, p, r)["decision"] == expected


def test_missing_required_null_never_zero_or_pass():
  m, p, r = measured()
  r["measurements"][0].update(value=None, reason="not observable", n=0)
  assert decide(m, p, r)["decision"] == "unverified"


def test_invalid_performance_no_pass_even_with_all_numbers():
  m, p, r = measured()
  r.update(validity="invalid", invalid_reasons=["interference"])
  assert decide(m, p, r)["decision"] == "unverified"
  r["correctness"][0]["status"] = "failure"
  assert decide(m, p, r)["decision"] == "failure"


def test_runtime_ab_inputs_and_noise_are_not_silent_passes():
  m, p, r = measured(scope="runtime", values=(15, 15, 15))
  baseline = deepcopy(r)
  baseline.update(subject="baseline", decision="measured")
  install_pair(m, r, baseline)
  for item in baseline["measurements"]:
    item["value"] = 10
  assert decide(m, p, r, baseline)["decision"] == "failure"
  p["metrics"][0]["noise_absolute"] = 10
  assert decide(m, p, r, baseline)["decision"] == "unverified"
  r["inputs"]["rules_digest"] = "d" * 64
  import pytest
  with pytest.raises(bench.BenchError) as error:
    decide(m, p, r, baseline)
  assert error.value.code == 2


def test_private_original_and_calibration_boolean_cannot_default_to_pass():
  m, p, r = measured()
  assert bench.compare(m, p, r)["decision"] == "unverified"
  assert bench.compare(m, p, r, originals_verified=True)["decision"] == "unverified"


def test_calibrate_preserves_absolute_budget_and_does_not_approve():
  m, p, r = measured(values=(10, 11, 12))
  proposed = bench.calibrated_policy(p, r)
  assert proposed["metrics"][0]["absolute_budget"] == p["metrics"][0]["absolute_budget"]
  assert proposed["metrics"][0]["noise_absolute"] == 2
  assert proposed["approval_ref"] is None
  assert proposed["frozen_at"] is None


def install_pair(manifest, candidate, baseline):
  schedule = []
  clock = 1
  for planned in bench.paired_schedule(manifest):
    row = {**planned, "actual_order": planned["planned_order"], "windows": []}
    for name in planned["planned_order"]:
      start = clock
      end = start + 400000000000
      row["windows"].append({"subject": name, "start_ns": start, "end_ns": end})
      target = candidate if name == "candidate" else baseline
      for producer in target["producer"]:
        if (producer["batch"], producer["workload"], producer["mode"]) == (planned["batch"], planned["workload"], planned["mode"]):
          producer["start_ns"] = start + 1 if producer["phase"] == "warmup" else start + 60000000002
          producer["end_ns"] = start + 60000000001 if producer["phase"] == "warmup" else start + 360000000002
      clock = end + 1
    schedule.append(row)
  for report in (candidate, baseline):
    report.update(paired_run_id="a" * 32, paired_schedule=deepcopy(schedule))


def test_missing_producer_instance_or_phase_prevents_pass():
  def duplicate(report):
    rows = [row for row in report["producer"] if row["workload"] == "output-10" and row["batch"] == 1 and row["phase"] == "measure"]
    rows[0]["pane_label"] = rows[1]["pane_label"]
  for change in (lambda r: r.update(producer=[]), lambda r: r["producer"].pop(), duplicate):
    m, p, r = measured()
    change(r)
    assert decide(m, p, r)["decision"] == "unverified"


def test_partial_matrix_never_full_acceptance():
  m, p, r = measured()
  m["workloads"] = [m["workloads"][0]]
  bench.sealed(m)
  r["manifest_digest"] = m["digest"]
  assert decide(m, p, r)["decision"] == "unverified"


def test_explicit_false_client_or_dimensions_coverage_cannot_be_omitted_evidence():
  for key in ("client_ready_proven", "dimensions_proven"):
    m, p, r = measured()
    r["coverage"][key] = False
    assert decide(m, p, r)["decision"] == "unverified"


def test_pair_identity_order_or_overlapping_window_cannot_pass():
  m, p, r = measured(scope="runtime")
  baseline = deepcopy(r)
  baseline["subject"] = "baseline"
  install_pair(m, r, baseline)
  for item in baseline["measurements"]:
    item["value"] = 10
  assert decide(m, p, r, baseline)["decision"] == "pass"
  baseline["paired_run_id"] = "b" * 32
  assert decide(m, p, r, baseline)["decision"] == "unverified"
  install_pair(m, r, baseline)
  for report in (r, baseline):
    report["paired_schedule"][0]["windows"][1]["start_ns"] = report["paired_schedule"][0]["windows"][0]["start_ns"]
  assert decide(m, p, r, baseline)["decision"] == "unverified"


def test_cpu_complete_boolean_without_source_windows_cannot_pass():
  m, p, r = measured()
  r["cpu_windows"] = []
  assert decide(m, p, r)["decision"] == "unverified"


def test_incomplete_or_duplicate_cpu_source_prevents_pass():
  for change in (lambda r: r["cpu_windows"][0].update(complete=False, reason="cpuacct_window_unproven"),
      lambda r: r["cpu_windows"].append(deepcopy(r["cpu_windows"][0]))):
    m, p, r = measured()
    change(r)
    assert decide(m, p, r)["decision"] == "unverified"


def slope_measurement(*, scope="first-baseline"):
  m, p, r = measured(scope=scope)
  m["measure_specs"].append({"metric": "rss.slope", "group": "server_group", "unit": "bytes/second", "required": True, "workloads": ["churn-leak"]})
  p["metrics"].append({"metric": "rss.slope", "group": "server_group", "unit": "bytes/second", "absolute_budget": 20,
    "budget_reason": None, "regression": {"relative": 0.1, "absolute": 2, "near_zero": 0.1}, "noise_absolute": 1, "noise_reason": None})
  for batch in (1, 2, 3):
    r["measurements"].append({"workload": "churn-leak", "mode": "record", "batch": batch, "metric": "rss.slope", "group": "server_group",
      "unit": "bytes/second", "value": 1, "n": 7, "samples": [100, 101, 102, 103, 104, 105, 106], "reason": None})
  bench.sealed(m)
  bench.sealed(p)
  r.update(manifest_digest=m["digest"], policy_digest=p["digest"])
  return m, p, bench.sealed(r)


def test_rss_slope_seven_settled_checkpoints_can_pass():
  m, p, r = slope_measurement()
  assert decide(m, p, r)["decision"] == "pass"


def test_rss_slope_requires_exactly_seven_samples_and_count():
  for count, samples in ((6, [100] * 6), (8, [100] * 8), (7, [100] * 6), (7, [100] * 8), (300, [100] * 300)):
    m, p, r = slope_measurement()
    next(item for item in r["measurements"] if item["metric"] == "rss.slope").update(n=count, samples=samples)
    assert decide(m, p, r)["decision"] == "unverified"


def test_baseline_slope_and_ordinary_cpu_sample_counts_are_required():
  m, p, r = slope_measurement(scope="runtime")
  baseline = deepcopy(r)
  baseline["subject"] = "baseline"
  install_pair(m, r, baseline)
  assert decide(m, p, r, baseline)["decision"] == "pass"
  slope = next(item for item in baseline["measurements"] if item["metric"] == "rss.slope")
  slope.update(n=5, samples=[100] * 5)
  assert decide(m, p, r, baseline)["decision"] == "unverified"
  slope.update(n=7, samples=[100] * 7)
  baseline["measurements"][0]["n"] = 299
  assert decide(m, p, r, baseline)["decision"] == "unverified"


def test_synthetic_positive_has_all_three_client_proof_batches():
  m, p, r = measured()
  for kind in ("ready", "geometry"):
    assert bench.client_coverage_proven(m, r, kind)
  assert len({item["evidence_ref"] for item in r["evidence"] if item["id"].startswith("client-")}) == 6
  expected_cpu = {(workload["id"], mode, batch) for workload in m["workloads"] for mode in workload["modes"] for batch in (1, 2, 3)}
  assert {(item["workload"], item["mode"], item["batch"]) for item in r["cpu_windows"]} == expected_cpu
  assert len(r["cpu_windows"]) == len(expected_cpu)
  assert decide(m, p, r)["decision"] == "pass"


@pytest.mark.parametrize("kind", ["ready", "geometry"])
@pytest.mark.parametrize("change", ["boolean_only", "missing_batch", "duplicate_ref", "cross_kind_ref", "wrong_kind"])
def test_client_coverage_requires_distinct_correct_batch_references(kind, change):
  m, p, r = measured()
  assert decide(m, p, r)["decision"] == "pass"
  prefix = "client-" + kind + "-batch-"
  rows = [item for item in r["evidence"] if item["id"].startswith(prefix)]
  if change == "boolean_only":
    r["evidence"] = [item for item in r["evidence"] if not item["id"].startswith(prefix)]
  elif change == "missing_batch":
    r["evidence"].remove(rows[1])
  elif change == "duplicate_ref":
    rows[1]["evidence_ref"] = rows[0]["evidence_ref"]
  elif change == "cross_kind_ref":
    other_kind = "ready" if kind == "geometry" else "geometry"
    rows[1]["evidence_ref"] = next(item["evidence_ref"] for item in r["evidence"] if item["id"] == "client-" + other_kind + "-batch-2")
  else:
    wrong_kind = "ready" if kind == "geometry" else "geometry"
    rows[1]["id"] = "client-" + wrong_kind + "-batch-2"
  assert r["coverage"]["client_ready_proven"] is True
  assert r["coverage"]["dimensions_proven"] is True
  assert decide(m, p, r)["decision"] == "unverified"
