import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("client_benchmark", ROOT / "tools/bench/herdr_upgrade.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def frame(round=0, slot=0, phase="measure"):
  cols, rows = [(120, 40), (80, 24)][(round + slot) % 2]
  area = {"x": 0, "y": 0, "width": cols - 26, "height": rows - 1}
  nonce = f"{round * 2 + slot + 1:032x}"
  pane_id = "w1:p" + str(round % 27 + 1)
  return {"run_id": "a" * 32, "pane_id": pane_id, "nonce": nonce, "phase": phase,
    "client": {"pid": 100 + slot, "starttime": 900 + slot}, "outer": {"cols": cols, "rows": rows},
    "begin": 101 + round * 10 + slot, "end": 101.5 + round * 10 + slot,
    "input": {"run_id": "a" * 32, "pane_id": pane_id, "nonce": nonce, "phase": phase,
      "size": {"cols": cols - 27, "rows": rows - 1}},
    "layout": {"type": "pane_layout", "layout": {"workspace_id": "w1", "tab_id": "t1", "zoomed": False,
      "area": area, "focused_pane_id": pane_id, "panes": [{"pane_id": pane_id, "focused": True, "rect": dict(area)}], "splits": []}}}


def inputs():
  manifest = {"sampling": {"warm_samples_per_batch": 200}}
  report = {"subject_identity": {"version": "synthetic"}, "producer": [{"workload": "clients-size", "batch": 1,
    "phase": "measure", "start_ns": 100_000_000_000}], "evidence": [], "invalid_reasons": [], "measurements": []}
  raw = {"method": "fixed-record-geometry-v1", "subject_digest": bench.digest(report["subject_identity"]),
    "run_id": "a" * 32, "workload": "clients-size", "batch": 1,
    "target_start_ns": 100_000_000_000, "target_end_ns": 400_000_000_000,
    "frames": [{"round": r, "slot": s, "frame": frame(r, s)} for r in range(30) for s in range(2)]}
  return manifest, report, raw


def test_raw_geometry_strict_proof():
  manifest, report, raw = inputs()
  assert bench.validate_client_original(manifest, report, raw, "geometry", 1)


@pytest.mark.parametrize("change", ["missing", "duplicate", "source", "window", "phase", "outer", "unknown", "subject"])
def test_geometry_proof_cannot_be_forged(change):
  manifest, report, raw = inputs()
  if change == "missing": raw["frames"].pop()
  if change == "duplicate": raw["frames"][1] = raw["frames"][0]
  if change == "source": raw["frames"][-1]["frame"]["client"]["starttime"] += 1
  if change == "window": raw["target_start_ns"] += 1
  if change == "phase": raw["frames"][0]["frame"]["phase"] = "record"
  if change == "outer": raw["frames"][0]["frame"]["outer"]["cols"] = 80
  if change == "unknown": raw["extra"] = True
  if change == "subject": raw["subject_digest"] = "0" * 64
  assert not bench.validate_client_original(manifest, report, raw, "geometry", 1)


def attach_inputs():
  manifest, report, raw = inputs()
  raw = {k: v for k, v in raw.items() if k not in {"target_start_ns", "target_end_ns"}}
  raw["method"] = "fixed-record-attach-v1"
  raw["frames"] = []
  for n in range(200):
    item = frame(0, 0, "record"); item["client"] = {"pid": n + 100, "starttime": n + 500}
    item["nonce"] = item["input"]["nonce"] = f"{n + 1:032x}"
    item["begin"], item["end"] = 10 + n * 6, 11 + n * 6
    raw["frames"].append({"attach_start_ns": (10 + n * 6) * 1_000_000_000 - 100,
      "attach_end_ns": (11 + n * 6) * 1_000_000_000 + 100, "frame": item})
  samples = [(row["attach_end_ns"] - row["attach_start_ns"]) / 1e6 for row in raw["frames"]]
  report["measurements"] = [{"workload": "clients-size", "batch": 1, "metric": "latency.attach.p95", "mode": "record", "group": "all", "unit": "ms",
    "n": 200, "samples": samples, "value": bench.statistics(samples)["p95"], "reason": None}]
  return manifest, report, raw


def test_attach_requires_independent_sources_and_record_phase():
  manifest, report, raw = attach_inputs()
  assert bench.validate_client_original(manifest, report, raw, "ready", 1)
  raw["frames"][-1]["frame"]["client"] = raw["frames"][0]["frame"]["client"]
  assert not bench.validate_client_original(manifest, report, raw, "ready", 1)


def test_coverage_needs_three_bound_references():
  manifest, report, raw = inputs()
  report["coverage"] = {"dimensions_proven": True, "client_ready_proven": True}
  assert not bench.client_coverage_proven(manifest, report, "geometry")
  for n in (1, 2, 3):
    report["evidence"].append({"id": "client-geometry-batch-" + str(n), "status": "pass", "required": True,
      "evidence_ref": "client-proof-" + str(n) * 64 + ".json", "reason": None})
  assert bench.client_coverage_proven(manifest, report, "geometry")
  report["evidence"].append(report["evidence"][0])
  assert not bench.client_coverage_proven(manifest, report, "geometry")


def test_default_config_guard(tmp_path):
  tmp_path = tmp_path / "config"
  tmp_path.mkdir()
  path = tmp_path / "config.toml"
  path.write_text('[ui]\nsidebar_collapsed_mode = "hidden"\nprompt_new_tab_name = false\n')
  bench.assert_default_client_geometry(path)
  path.write_text('[ui]\npane_scrollbars = false\n')
  with pytest.raises(bench.BenchError): bench.assert_default_client_geometry(path)
  path.write_text('[ui]\n')
  (tmp_path / "preferences.json").write_text('{}')
  with pytest.raises(bench.BenchError): bench.assert_default_client_geometry(path)


def test_measurement_digest_binds_all_three_sources():
  expected = [{"name": name, "sha256": bench.bytes_digest(ROOT / "tools/bench" / name)}
    for name in ("herdr_upgrade.py", "cpuacct.py", "client_geometry.py")]
  import hashlib
  assert bench.measurement_tool_digest() == hashlib.sha256(bench.canonical(expected)).hexdigest()


def test_geometry_round_focus_resize_then_both_real_input_paths():
  events = []
  clients = [("process0", 10), ("process1", 11)]
  raw = {"frames": []}
  def probe(process, master, pane, cols, rows, phase):
    events.append(("probe", process, master, cols, rows, phase))
    return {"source": process}
  bench.collect_geometry_round(raw, 1, clients, "owned-pane", lambda pane: events.append(("focus", pane)),
    lambda process, master, cols, rows: events.append(("resize", master, cols, rows)), probe,
    lambda: events.append(("settle",)))
  assert events == [("focus", "owned-pane"), ("resize", 10, 80, 24), ("resize", 11, 120, 40),
    ("settle",),
    ("probe", "process0", 10, 80, 24, "measure"), ("probe", "process1", 11, 120, 40, "measure")]
  assert [(row["round"], row["slot"]) for row in raw["frames"]] == [(1, 0), (1, 1)]


def test_private_geometry_originals_tamper_and_modes(tmp_path):
  manifest, report, raw = inputs()
  report["coverage"] = {"dimensions_proven": False, "client_ready_proven": False}
  bench.save_client_proof(report, tmp_path, raw, "geometry", True)
  assert bench.verify_client_originals(manifest, report, tmp_path)
  path = tmp_path / report["evidence"][0]["evidence_ref"]
  path.chmod(0o644)
  assert not bench.verify_client_originals(manifest, report, tmp_path)
  path.chmod(0o600)
  path.write_text(path.read_text() + " ")
  assert not bench.verify_client_originals(manifest, report, tmp_path)


@pytest.mark.parametrize("change", ["digest", "nativepid", "cwd", "starttime"])
def test_ready_native_identity_checks(tmp_path, monkeypatch, change):
  ready = {"pane_id": "w1:p1", "pid": 100, "config_digest": "a" * 64}
  pane = {"pane_id": "w1:p1", "terminal_id": "term1", "workspace_id": "w1"}
  native = {"shell_pid": 100}
  current = (900, str(tmp_path))
  if change == "digest": ready["config_digest"] = "b" * 64
  if change == "nativepid": native["shell_pid"] = 101
  if change == "cwd": current = (900, str(tmp_path / "other"))
  if change == "starttime": current = (901, str(tmp_path))
  monkeypatch.setattr(bench, "_known_producer_identity", lambda pid: current)
  with pytest.raises(bench.BenchError):
    bench.verify_producer_ready(ready, pane, tmp_path, "a" * 64, native, (900, str(tmp_path)))


@pytest.mark.parametrize("change", ["start", "end", "phase", "samples", "p95", "n", "unknown"])
def test_attach_timing_and_statistics_bound_to_original(change):
  manifest, report, raw = attach_inputs()
  if change == "start": raw["frames"][0]["attach_start_ns"] += 1000
  if change == "end": raw["frames"][0]["attach_end_ns"] -= 1000
  if change == "phase": raw["frames"][0]["frame"]["phase"] = "measure"
  if change == "samples": report["measurements"][0]["samples"][0] += 1
  if change == "p95": report["measurements"][0]["value"] -= 1
  if change == "n": report["measurements"][0]["n"] -= 1
  if change == "unknown": raw["frames"][0]["extra"] = True
  assert not bench.validate_client_original(manifest, report, raw, "ready", 1)


def test_geometry_all_same_pane_is_not_rotation():
  manifest, report, raw = inputs()
  for row in raw["frames"]:
    f = row["frame"]
    f["pane_id"] = f["input"]["pane_id"] = f["layout"]["layout"]["focused_pane_id"] = "w1:p1"
    f["layout"]["layout"]["panes"][0]["pane_id"] = "w1:p1"
  assert not bench.validate_client_original(manifest, report, raw, "geometry", 1)


def test_slope_item_requires_exactly_seven_even_with_other_missing_proofs():
  from test_herdr_upgrade_policy import slope_measurement
  for count, expected in ((6, "unverified"), (7, "pass"), (8, "unverified"), (300, "unverified")):
    manifest, policy, report = slope_measurement()
    for row in report["measurements"]:
      if row["metric"] == "rss.slope": row.update(n=count, samples=[100] * count)
    result = bench.compare(manifest, policy, report, originals_verified=True, calibration_verified=True)
    items = [row for row in result["item_decisions"] if ":rss.slope:" in row["id"]]
    assert items and all(row["decision"] == expected for row in items)


def test_churn_original_includes_tail_and_recomputes_slope(tmp_path):
  import hashlib
  times = [60, 120, 180, 240, 300, 360, 2160]
  rss = [100, 100, 100, 100, 100, 100, 2000]
  panes = [["w1:p" + str(n), "term" + str(n), "w1"] for n in range(27)]
  raw = {"method": "fixed-churn-tail-v1", "subject_digest": bench.digest({"version": "synthetic"}), "run_id": "a" * 32,
    "batch": 1, "times": times, "rss": rss, "processes": [30] * 7, "fds": [80] * 7, "expected_panes": panes, "actual_panes": panes}
  name = "churn-proof-" + hashlib.sha256(bench.canonical(raw) + b"\n").hexdigest() + ".json"
  bench._private_value(tmp_path / name, raw)
  slope = bench.stats.linear_regression([t - times[0] for t in times], rss).slope
  report = {"subject_identity": {"version": "synthetic"}, "evidence": [{"id": "churn-tail-batch-1", "status": "pass", "evidence_ref": name}],
    "measurements": [{"workload": "churn-leak", "mode": "record", "batch": 1, "metric": "rss.slope", "group": "server_group", "n": 7, "samples": rss, "value": slope}]}
  assert bench.verify_churn_originals({}, report, tmp_path)
  report["measurements"][0]["value"] = 0
  assert not bench.verify_churn_originals({}, report, tmp_path)


def test_cgroup_rss_includes_orphan_helpers_and_excludes_driver(tmp_path, monkeypatch):
  members = {"server": [{"pid": 100, "starttime": 1}, {"pid": 300, "starttime": 3}],
    "client": [], "producer": [], "driver": [{"pid": 999, "starttime": 9}]}
  sampler = bench.ProcSampler(100, proc=tmp_path, group_members=lambda: members)
  for pid, count in ((100, 2), (300, 3), (999, 10)):
    directory = tmp_path / str(pid) / "fd"
    directory.mkdir(parents=True)
    for n in range(count): (directory / str(n)).touch()
  live = {100: {"ppid": 1, "cpu": 1, "start": 1, "rss": 100},
    300: {"ppid": 1, "cpu": 1, "start": 3, "rss": 300},
    999: {"ppid": 1, "cpu": 1, "start": 9, "rss": 999},
    400: {"ppid": 100, "cpu": 1, "start": 4, "rss": 400}}
  monkeypatch.setattr(sampler, "snapshot", lambda: live)
  assert sampler.sample() == {100: "server", 300: "helpers"}
  assert sampler.rss["server_group"] == [400]
  assert sampler.fds == [5] and sampler.processes == [2] and not sampler.lost
  live[300]["start"] = 30
  sampler.sample()
  assert sampler.lost
  assert sampler.rss["server_group"][-1] == 100
