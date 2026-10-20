"""CPU/MiB 仅从已核对 CPU 分子和本 case 实际 producer 字节派生。"""
import pytest

from test_herdr_benchmark import bench, synthetic_cpu_original


MIB = 1 << 20
GROUPS = ("server", "helpers", "server_group", "client", "producer")


def producers():
  return [{"workload": "output-1", "mode": "output", "batch": 1, "phase": "measure", "bytes": MIB, "pane_label": "producer-0"},
    {"workload": "output-1", "mode": "output", "batch": 1, "phase": "measure", "bytes": 3 * MIB, "pane_label": "producer-1"}]


def cost(cpu=8, rows=None, mode="output", intervals=300, reason=None):
  return bench.output_cpu_cost(cpu, producers() if rows is None else rows, "output-1", mode, 1,
    interval_count=intervals, source_reason=reason)


def test_output_cost_sums_actual_bytes_and_ignores_other_windows():
  rows = producers()
  for field, value in (("phase", "warmup"), ("workload", "output-10"), ("batch", 2), ("mode", "idle")):
    rows.append({**producers()[0], field: value, "bytes": 1000 * MIB})
  assert cost(rows=rows) == {"value": 2, "n": 300, "samples": [], "reason": None}
  rows[0]["bytes"] = MIB // 2
  rows[1]["bytes"] = MIB // 2
  assert cost(rows=rows)["value"] == 8


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "123", None])
def test_output_cost_bad_or_zero_bytes_are_null(value):
  rows = producers()
  rows[0]["bytes"] = value
  actual = cost(rows=rows)
  assert actual == {"value": None, "n": 0, "samples": [], "reason": "producer_output_bytes_missing_or_invalid"}


@pytest.mark.parametrize("mode", ["idle", "record"])
def test_non_output_cost_is_null(mode):
  assert cost(mode=mode) == {"value": None, "n": 0, "samples": [], "reason": "cpu_output_cost_requires_output_mode"}


def test_missing_denominator_or_incomplete_window_is_null():
  assert cost(rows=[])["reason"] == "producer_output_bytes_missing_or_invalid"
  assert cost(intervals=299) == {"value": None, "n": 0, "samples": [], "reason": "cpu_output_cost_window_incomplete"}


def test_null_tgid_cost_preserves_source_reason_and_valid_zero_cpu_is_zero():
  assert cost(cpu=None, reason="server_tgid_tick_precision_or_identity_unproven") == {
    "value": None, "n": 0, "samples": [], "reason": "server_tgid_tick_precision_or_identity_unproven"}
  assert cost(cpu=0) == {"value": 0, "n": 300, "samples": [], "reason": None}


def original_with_costs():
  manifest, report, row, raw = synthetic_cpu_original()
  report["producer"] = producers()
  for group in GROUPS:
    manifest["measure_specs"].append({"metric": "cpu.per_mib", "group": group, "unit": "core-seconds/MiB", "required": False, "workloads": ["output-1"]})
    report["measurements"].append({"workload": "output-1", "mode": "output", "batch": 1, "metric": "cpu.per_mib", "group": group,
      "unit": "core-seconds/MiB", "value": 0 if group == "server" else 75, "n": 300, "samples": [], "reason": None})
  return manifest, report, row, raw


def test_private_cpu_original_checks_output_cost_for_each_group():
  manifest, report, row, raw = original_with_costs()
  assert bench.verify_cpu_original(manifest, report, row, raw)


@pytest.mark.parametrize("mutation", ["ratio", "count", "samples", "unit", "denominator", "mode", "phase", "zero", "negative", "noninteger", "boolean_ratio", "noninteger_count"])
def test_private_cpu_original_rejects_tampered_output_cost(mutation):
  manifest, report, row, raw = original_with_costs()
  item = next(item for item in report["measurements"] if item["metric"] == "cpu.per_mib" and item["group"] == "server_group")
  if mutation == "ratio":
    item["value"] = 0
  elif mutation == "boolean_ratio":
    next(item for item in report["measurements"] if item["metric"] == "cpu.per_mib" and item["group"] == "server")["value"] = False
  elif mutation == "noninteger_count":
    item["n"] = 300.0
  elif mutation == "count":
    item["n"] = 2
  elif mutation == "samples":
    item["samples"] = [item["value"]] * 300
  elif mutation == "unit":
    item["unit"] = "core-seconds"
  elif mutation == "denominator":
    report["producer"][0]["bytes"] *= 2
  elif mutation == "mode":
    for producer in report["producer"]:
      producer["mode"] = "idle"
  elif mutation == "phase":
    for producer in report["producer"]:
      producer["phase"] = "warmup"
  else:
    report["producer"][0]["bytes"] = {"zero": 0, "negative": -1, "noninteger": True}[mutation]
  assert not bench.verify_cpu_original(manifest, report, row, raw)


def test_private_output_cost_null_precision_and_denominator_reasons_checked():
  manifest, report, row, raw = original_with_costs()
  raw["snapshots"][-1]["server_main"]["ticks"] = 30001
  for item in report["measurements"]:
    if item["metric"] == "cpu.per_mib" and item["group"] == "helpers":
      item.update(value=None, n=0, reason="server_tgid_tick_precision_or_identity_unproven")
    elif item["metric"] == "cpu.per_mib" and item["group"] == "server":
      item["value"] = 300.01 / 4
  assert bench.verify_cpu_original(manifest, report, row, raw)
  for producer in report["producer"]:
    producer["bytes"] = 0
  for item in report["measurements"]:
    if item["metric"] == "cpu.per_mib" and item["group"] != "helpers":
      item.update(value=None, n=0, reason="producer_output_bytes_missing_or_invalid")
  assert bench.verify_cpu_original(manifest, report, row, raw)
  next(item for item in report["measurements"] if item["metric"] == "cpu.per_mib")["reason"] = "unrelated_reason"
  assert not bench.verify_cpu_original(manifest, report, row, raw)
