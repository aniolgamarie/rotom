#!/usr/bin/env python3
"""Herdr 合成升级证据：离线校验/判定；原生能力不充分时保留未验证。"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from decimal import Decimal
from copy import deepcopy
import ctypes
import errno
import hashlib
import json
import math
import os
import re
from pathlib import Path
import stat
import statistics as stats
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from cpuacct import CpuacctGroups, CpuacctError, _validate_receipt
from client_geometry import GeometryError, probe_record_client, verify_frame, resize_owned_client, detach_owned_client, wait_owned_client_marker
from jsonschema import Draft202012Validator

FIXTURE = ROOT / "tests/fixtures/herdr-bench/v1"
WORKLOADS = {"idle-1": 1, "idle-10": 10, "idle-30": 30, "output-1": 1,
             "output-10": 10, "output-30": 30, "projects-27": 27,
             "detached-30": 30, "clients-size": 27, "churn-leak": 27}
WARM = {"latency.warm_enter.p95", "latency.warm_reuse.p95", "latency.new_role.p95", "latency.attach.p95"}


class BenchError(Exception):
  def __init__(self, code, reason):
    self.code, self.reason = code, reason
    super().__init__(reason)


def canonical(value):
  return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
  return hashlib.sha256(canonical({k: v for k, v in value.items() if k != "digest"})).hexdigest()


def sealed(value):
  value["digest"] = digest(value)
  return value


def bytes_digest(path):
  return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def measurement_tool_digest():
  return hashlib.sha256(canonical([{"name": name, "sha256": bytes_digest(Path(__file__).parent / name)}
    for name in ("herdr_upgrade.py", "cpuacct.py", "client_geometry.py")])).hexdigest()


def assert_default_client_geometry(config_path):
  import tomllib
  ui = tomllib.loads(Path(config_path).read_text()).get("ui", {})
  geometry_keys = {"sidebar_width", "sidebar_min_width", "sidebar_max_width", "sidebar_start_collapsed",
    "mobile_width_threshold", "hide_tab_bar_when_single_tab", "tab_bar_position", "pane_borders",
    "pane_outer_borders", "pane_scrollbars", "pane_gaps"}
  if geometry_keys.intersection(ui) or ui.get("sidebar_collapsed_mode", "hidden") not in {"hidden", "compact"}:
    raise BenchError(2, "client_geometry_requires_reviewed_defaults")
  if any(path.name != "config.toml" for path in Path(config_path).parent.iterdir()):
    raise BenchError(4, "client_geometry_requires_clean_preferences")


def client_coverage_proven(manifest, report, kind, batches=(1, 2, 3)):
  if kind not in {"geometry", "ready"}:
    return False
  proof_rows = [row for row in report["evidence"] if row["id"].startswith(("client-geometry-batch-", "client-ready-batch-"))]
  references = [row["evidence_ref"] for row in proof_rows]
  if any(not isinstance(reference, str) for reference in references) or len(set(references)) != len(references):
    return False
  prefix = "client-geometry-batch-" if kind == "geometry" else "client-ready-batch-"
  rows = [row for row in report["evidence"] if row["id"].startswith(prefix)]
  return (len(rows) == len(batches) and {row["id"] for row in rows} == {prefix + str(n) for n in batches}
    and all(row["status"] == "pass" and row["required"] is True and row["reason"] is None and
      isinstance(row["evidence_ref"], str) and re.fullmatch(r"client-proof-[a-f0-9]{64}\.json", row["evidence_ref"]) for row in rows))


def validate_client_original(manifest, report, raw, kind, batch):
  try:
    expected = {"method", "subject_digest", "run_id", "workload", "batch", "frames"}
    if kind == "geometry": expected |= {"target_start_ns", "target_end_ns"}
    if (type(raw) is not dict or set(raw) != expected or raw["method"] != ("fixed-record-geometry-v1" if kind == "geometry" else "fixed-record-attach-v1") or
        raw["subject_digest"] != digest(report["subject_identity"]) or raw["workload"] != "clients-size" or
        type(raw["batch"]) is not int or raw["batch"] != batch or batch not in (1, 2, 3) or
        type(raw["run_id"]) is not str or not re.fullmatch(r"[a-f0-9]{32}", raw["run_id"]) or type(raw["frames"]) is not list):
      return False
    if kind == "geometry":
      if (type(raw["target_start_ns"]) is not int or type(raw["target_end_ns"]) is not int or
          raw["target_end_ns"] - raw["target_start_ns"] != 300_000_000_000 or len(raw["frames"]) != 60):
        return False
      anchors = [row for row in report["producer"] if row["workload"] == "clients-size" and row["batch"] == batch and row["phase"] == "measure"]
      if not anchors or any(row["start_ns"] != raw["target_start_ns"] for row in anchors): return False
    elif len(raw["frames"]) != manifest["sampling"]["warm_samples_per_batch"] or len(raw["frames"]) < 200:
      return False
    sources, nonces = {}, set()
    previous_end = -1
    attach_sources = set()
    attach_samples = []
    pane_sequence = []
    previous_attach_end = -1
    for index, row in enumerate(raw["frames"]):
      if kind == "geometry":
        if type(row) is not dict or set(row) != {"round", "slot", "frame"} or type(row["round"]) is not int or type(row["slot"]) is not int or (row["round"], row["slot"]) != divmod(index, 2): return False
        frame = row["frame"]
      else:
        if (type(row) is not dict or set(row) != {"attach_start_ns", "attach_end_ns", "frame"} or
            type(row["attach_start_ns"]) is not int or type(row["attach_end_ns"]) is not int or
            not 0 < row["attach_start_ns"] < row["attach_end_ns"] or row["attach_start_ns"] < previous_attach_end): return False
        frame = row["frame"]
        previous_attach_end = row["attach_end_ns"]
      verify_frame(frame)
      if frame["run_id"] != raw["run_id"] or frame["nonce"] in nonces or frame["begin"] < previous_end: return False
      nonces.add(frame["nonce"]); previous_end = frame["end"]
      source = (frame["client"]["pid"], frame["client"]["starttime"])
      if kind == "geometry":
        slot = row["slot"]
        if (frame["phase"] != "measure" or frame["begin"] * 1e9 < raw["target_start_ns"] or frame["end"] * 1e9 > raw["target_end_ns"] or
            frame["outer"] != dict(zip(("cols", "rows"), ((120, 40), (80, 24))[(row["round"] + slot) % 2]))): return False
        if slot in sources and sources[slot] != source: return False
        sources[slot] = source
        if slot == 0:
          pane_sequence.append(frame["pane_id"])
        elif frame["pane_id"] != pane_sequence[-1]: return False
      else:
        if row["attach_start_ns"] > frame["begin"] * 1e9 + 64 or frame["end"] * 1e9 > row["attach_end_ns"] + 64: return False
        attach_samples.append((row["attach_end_ns"] - row["attach_start_ns"]) / 1e6)
        if frame["phase"] != "record" or frame["outer"] != {"cols": 120, "rows": 40} or source in attach_sources: return False
        attach_sources.add(source)
    if kind == "geometry":
      count = WORKLOADS["clients-size"]
      return (len(set(sources.values())) == 2 and len({identity[0] for identity in sources.values()}) == 2 and
        len(set(pane_sequence[:count])) == count and all(pane_sequence[n] == pane_sequence[n % count] for n in range(count, 30)))
    metrics = [row for row in report["measurements"] if row["workload"] == "clients-size" and row["batch"] == batch and row["metric"] == "latency.attach.p95" and row["mode"] == "record" and row["group"] == "all"]
    return (len(metrics) == 1 and metrics[0]["n"] == len(attach_samples) and metrics[0]["samples"] == attach_samples and
      metrics[0]["reason"] is None and metrics[0]["unit"] == "ms" and metrics[0]["value"] == statistics(attach_samples)["p95"])
  except (GeometryError, KeyError, TypeError, ValueError, OverflowError):
    return False


def save_client_proof(report, private, raw, kind, passed):
  content = canonical(raw) + b"\n"
  name = "client-proof-" + hashlib.sha256(content).hexdigest() + ".json"
  _private_value(private / name, raw)
  report["evidence"].append({"id": ("client-geometry-batch-" if kind == "geometry" else "client-ready-batch-") + str(raw["batch"]),
    "required": True, "status": "pass" if passed else "unverified", "evidence_ref": name,
    "reason": None if passed else "fixed_record_client_proof_incomplete"})


def verify_client_originals(manifest, report, directory):
  for kind, prefix in (("geometry", "client-geometry-batch-"), ("ready", "client-ready-batch-")):
    rows = [row for row in report["evidence"] if row["id"].startswith(prefix)]
    if len({row["id"] for row in rows}) != len(rows): return False
    for row in rows:
      if row["status"] != "pass": continue
      suffix = row["id"][len(prefix):]
      if suffix not in {"1", "2", "3"} or not row["required"] or row["reason"] is not None: return False
      name = row["evidence_ref"]
      if not isinstance(name, str) or not re.fullmatch(r"client-proof-[a-f0-9]{64}\.json", name): return False
      path = directory / name
      before = path.lstat()
      if not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600 or before.st_uid != os.getuid() or before.st_nlink != 1: return False
      fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
      try:
        if _client_file_identity(os.fstat(fd)) != _client_file_identity(before): return False
        with os.fdopen(fd, "rb", closefd=False) as stream: content = stream.read(2_000_001)
        if len(content) > 2_000_000 or _client_file_identity(os.fstat(fd)) != _client_file_identity(before): return False
      finally: os.close(fd)
      if _client_file_identity(path.lstat()) != _client_file_identity(before) or hashlib.sha256(content).hexdigest() != name[13:-5]: return False
      def unique(pairs):
        value = {}
        for key, item in pairs:
          if key in value: raise ValueError("duplicate client proof field")
          value[key] = item
        return value
      raw = json.loads(content, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite client proof")))
      if canonical(raw) + b"\n" != content or not validate_client_original(manifest, report, raw, kind, int(suffix)): return False
    flag = "dimensions_proven" if kind == "geometry" else "client_ready_proven"
    if report["coverage"][flag] and not client_coverage_proven(manifest, report, kind): return False
  return True


def _client_file_identity(info):
  return (info.st_dev, info.st_ino, info.st_uid, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def verify_churn_originals(manifest, report, directory):
  rows = [row for row in report["evidence"] if row["id"].startswith("churn-tail-batch-")]
  if len({row["id"] for row in rows}) != len(rows): return False
  required_batches = {row["batch"] for row in report["measurements"] if row["workload"] == "churn-leak" and row["metric"] == "rss.slope"}
  if {row["id"] for row in rows} != {"churn-tail-batch-" + str(batch) for batch in required_batches}: return not rows and not required_batches
  for evidence in rows:
    if evidence["status"] != "pass": return False
    name = evidence["evidence_ref"]
    if not isinstance(name, str) or not re.fullmatch(r"churn-proof-[a-f0-9]{64}\.json", name): return False
    path = directory / name
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600: return False
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
      if _client_file_identity(os.fstat(fd)) != _client_file_identity(info): return False
      content = os.read(fd, 1_000_001)
      if len(content) > 1_000_000 or _client_file_identity(os.fstat(fd)) != _client_file_identity(info): return False
    finally: os.close(fd)
    if _client_file_identity(path.lstat()) != _client_file_identity(info) or hashlib.sha256(content).hexdigest() != name[12:-5]: return False
    raw = json.loads(content)
    if canonical(raw) + b"\n" != content or set(raw) != {"method", "subject_digest", "run_id", "batch", "times", "rss", "processes", "fds", "expected_panes", "actual_panes"}: return False
    if (raw["method"] != "fixed-churn-tail-v1" or raw["subject_digest"] != digest(report["subject_identity"]) or
        type(raw["batch"]) is not int or raw["batch"] not in required_batches or evidence["id"] != "churn-tail-batch-" + str(raw["batch"]) or
        type(raw["run_id"]) is not str or not re.fullmatch(r"[a-f0-9]{32}", raw["run_id"])): return False
    for field in ("times", "rss", "processes", "fds"):
      if type(raw[field]) is not list or len(raw[field]) != 7 or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0 for value in raw[field]): return False
    if any(b <= a for a, b in zip(raw["times"], raw["times"][1:])) or raw["times"][-1] - raw["times"][-2] < 1800 - 1e-6: return False
    expected_panes = raw["expected_panes"]
    if (type(expected_panes) is not list or len(expected_panes) != WORKLOADS["churn-leak"] or raw["actual_panes"] != expected_panes or
        any(type(row) is not list or len(row) != 3 or any(type(value) is not str or not value for value in row) for row in expected_panes) or
        len({tuple(row) for row in expected_panes}) != len(expected_panes)): return False
    metrics = [row for row in report["measurements"] if row["workload"] == "churn-leak" and row["mode"] == "record" and row["batch"] == raw["batch"]]
    slopes = [row for row in metrics if row["metric"] == "rss.slope" and row["group"] == "server_group"]
    slope = max(0, stats.linear_regression([t - raw["times"][0] for t in raw["times"]], raw["rss"]).slope)
    if len(slopes) != 1 or slopes[0]["n"] != 7 or slopes[0]["samples"] != raw["rss"] or slopes[0]["value"] != slope: return False
    for metric, field in (("processes.count", "processes"), ("fd.count", "fds")):
      counts = [row for row in metrics if row["metric"] == metric]
      if any(row["n"] != 7 or row["samples"] != raw[field] or row["value"] != max(raw[field]) for row in counts): return False
  return True



def update_client_coverage(manifest, report):
  report["coverage"]["dimensions_proven"] = client_coverage_proven(manifest, report, "geometry")
  report["coverage"]["client_ready_proven"] = client_coverage_proven(manifest, report, "ready")
  if any(w["id"] == "clients-size" for w in manifest["workloads"]):
    for flag, reason in (("dimensions_proven", "shared_dimensions_not_proven"), ("client_ready_proven", "client_ready_not_proven")):
      report["invalid_reasons"] = [r for r in report["invalid_reasons"] if r != reason]
      if not report["coverage"][flag]: report["invalid_reasons"].append(reason)
  reasons = list(report["invalid_reasons"])
  if not report["coverage"]["cpu_complete"]: reasons.append("complete_process_cpu_coverage_not_proven")
  if not report["coverage"]["client_version_verified"]: reasons.append("actual_client_version_not_verified")
  if not report["coverage"]["effective_inputs_verified"]: reasons.append("effective_rules_and_integrations_not_verified")
  if any(e["required"] and e["status"] != "pass" for e in report["evidence"]): reasons.append("required_evidence_missing")
  if any(check["status"] != "pass" for check in report["correctness"]): reasons.append("correctness_incomplete")
  if any(check["status"] == "failure" for check in report["correctness"]):
    report.update(decision="failure", task_status="失败待决策")
  report["coverage"]["reason"] = ";".join(sorted(set(reasons))) or None
  report["validity"] = "invalid" if reasons else "valid"



def fixture_digest():
  # 外部文件按原始 bytes 摘要，清单用 canonical JSON；不纳入自引用 manifest。
  return hashlib.sha256(canonical([{ "name": name, "sha256": bytes_digest(FIXTURE / name)}
    for name in ("producer.py", "checkouts.json", "namespace_exec.py", "origin-audit.json", "socket_filter_exec.py")])).hexdigest()


def schema_digest():
  return hashlib.sha256(canonical([{"name": name, "sha256": bytes_digest(ROOT / "schemas" / ("herdr-benchmark-" + name + ".schema.json"))} for name in ("manifest", "policy", "report")])).hexdigest()


def read_json(path):
  def unique(pairs):
    value = {}
    for key, item in pairs:
      if key in value:
        raise ValueError("duplicate key")
      value[key] = item
    return value
  try:
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite")))
  except (ValueError, UnicodeError, TypeError):
    raise BenchError(2, "invalid_json") from None


def validate_document(value, kind):
  schema = read_json(ROOT / "schemas" / ("herdr-benchmark-" + kind + ".schema.json"))
  if not Draft202012Validator(schema).is_valid(value):
    raise BenchError(2, "invalid_" + kind + "_schema")
  try:
    if value["digest"] != digest(value):
      raise BenchError(2, "document_digest_mismatch")
  except (ValueError, OverflowError, UnicodeError):
    raise BenchError(2, "noncanonical_document") from None
  if kind == "manifest":
    if value["fixture_digest"] != fixture_digest():
      raise BenchError(2, "fixture_digest_mismatch")
    if value["source"]["schema_digest"] != schema_digest():
      raise BenchError(2, "schema_identity_mismatch")
    if value["source"]["runner_digest"] != bytes_digest(Path(__file__)) or value["source"]["measurement_tool_digest"] != measurement_tool_digest():
      raise BenchError(2, "runner_or_measurement_identity_mismatch")
    if (value["subjects"]["baseline"] is None) != (value["subjects"]["baseline_reason"] is not None):
      raise BenchError(2, "baseline_reason_required")
    if len({w["id"] for w in value["workloads"]}) != len(value["workloads"]):
      raise BenchError(2, "duplicate_workload")
    for workload in value["workloads"]:
      if workload["terminals"] != WORKLOADS[workload["id"]]:
        raise BenchError(2, "workload_matrix_changed")
    if len({s["id"] for s in value["steps"]}) != len(value["steps"]):
      raise BenchError(2, "duplicate_step")
    for step in value["steps"]:
      forbidden = {"eval", "send-input", "send_input", "send-text", "send_text", "send-keys", "send_keys", "agent.start", "pane.run"}
      if any(token in forbidden for token in step["argv"]) or step["argv"][0] in {"sh", "bash", "zsh", "/bin/sh", "/bin/bash"}:
        raise BenchError(2, "unsupported_step_argv")
      if any(any(ord(c) < 32 or ord(c) == 127 for c in token) for token in step["argv"]):
        raise BenchError(2, "invalid_step_literal")
    _unique_keys(value["measure_specs"], ("metric", "group"))
  elif kind == "policy":
    _unique_keys(value["metrics"], ("metric", "group"))
    for metric in value["metrics"]:
      _null_reason(metric["absolute_budget"], metric["budget_reason"])
      _null_reason(metric["noise_absolute"], metric["noise_reason"])
  elif kind == "report":
    _unique_keys(value["measurements"], ("workload", "mode", "batch", "metric", "group"))
    _unique_keys(value["producer"], ("workload", "mode", "batch", "pane_label", "phase"))
    _unique_keys(value["batches"], ("batch",))
    _unique_keys(value.get("cpu_windows", []), ("workload", "mode", "batch"))
    for window in value.get("cpu_windows", []):
      _null_reason(1 if window["complete"] else None, window["reason"])
    for metric in value["measurements"]:
      _null_reason(metric["value"], metric["reason"])
      if metric["value"] is None and (metric["n"] != 0 or metric["samples"]):
        raise BenchError(2, "missing_metric_has_samples")
      if metric["value"] is not None and metric["n"] == 0:
        raise BenchError(2, "metric_sample_count_missing")
      if metric["samples"] and len(metric["samples"]) != metric["n"]:
        raise BenchError(2, "metric_sample_count_mismatch")
      samples = metric["samples"]
      if samples:
        expected = None
        if metric["metric"].endswith(".p95"):
          expected = statistics(samples)["p95"]
        elif metric["metric"].endswith(".median"):
          expected = stats.median(samples)
        elif metric["metric"].endswith(".peak") or metric["metric"] in {"fd.count", "processes.count", "objects.count"}:
          expected = max(samples)
        if expected is not None and not math.isclose(metric["value"], expected, rel_tol=1e-12, abs_tol=1e-12):
          raise BenchError(2, "sample_summary_mismatch")
    for entry in value["steps"] + value["batches"] + value["producer"]:
      if entry["end_ns"] < entry["start_ns"]:
        raise BenchError(2, "invalid_monotonic_window")
  return value


def _null_reason(value, reason):
  if (value is None) != (isinstance(reason, str) and bool(reason)):
    raise BenchError(2, "null_requires_reason")


def _unique_keys(items, fields):
  keys = [tuple(item[field] for field in fields) for item in items]
  if len(set(keys)) != len(keys):
    raise BenchError(2, "duplicate_record")


def validate_references(manifest, policy=None, reports=()):
  if policy is not None:
    if (policy["fixture_digest"] != manifest["fixture_digest"] or policy["scope"] != manifest["scope"] or
        policy["environment_class"] != manifest["environment"]["platform_class"]):
      raise BenchError(2, "policy_scope_or_identity_mismatch")
  for report in reports:
    if (report["manifest_digest"] != manifest["digest"] or report["fixture_digest"] != manifest["fixture_digest"] or
        report["source"] != manifest["source"] or report["scope"] != manifest["scope"] or report["comparison_kind"] != report["scope"] or report["authorization_ref"] != manifest["authorization_ref"] or
        report["subject_identity"] != public_subject(manifest["subjects"][report["subject"]])):
      raise BenchError(2, "report_identity_mismatch")
    if report["inputs"] != report["subject_identity"]["inputs"]:
      raise BenchError(2, "report_input_identity_mismatch")
    if policy is not None and report["policy_digest"] != policy["digest"]:
      raise BenchError(2, "report_policy_mismatch")
    if report["scope"] == "first-baseline" and report["subject"] != "candidate":
      raise BenchError(2, "first_baseline_candidate_only")
    if manifest["scope"] == "runtime" and report["inputs"] != manifest["inputs"]:
      raise BenchError(2, "runtime_inputs_changed")
    expected = {(s["metric"], s["group"]): s for s in manifest["measure_specs"]}
    for metric in report["measurements"]:
      spec = expected.get((metric["metric"], metric["group"]))
      if spec is None or metric["unit"] != spec["unit"]:
        raise BenchError(2, "metric_unit_or_scope_mismatch")


def _rename_noreplace(directory, temporary, destination):
  """只接受 Linux 原子不覆盖发布；缺能力时不尝试其他发布方式。"""
  if sys.platform != "linux":
    raise OSError(errno.ENOSYS, "atomic_publish_unavailable")
  try:
    rename = ctypes.CDLL(None, use_errno=True).renameat2
  except (AttributeError, OSError):
    raise OSError(errno.ENOSYS, "atomic_publish_unavailable") from None
  rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
  rename.restype = ctypes.c_int
  if rename(directory, os.fsencode(temporary), directory, os.fsencode(destination), 1) != 0:
    raise OSError(ctypes.get_errno(), "atomic_publish_failed")


def write_new(path, value, *, private=False):
  """完整写入/fsync 临时文件，再原子发布单链接新名，绝不覆盖。"""
  path = Path(path)
  if path.exists() or path.is_symlink():
    raise BenchError(4, "output_exists")
  directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
  temporary = ".herdr-bench-" + uuid.uuid4().hex
  staged = False
  try:
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
      0o600, dir_fd=directory)
    staged = True
    with os.fdopen(fd, "wb") as stream:
      os.fchmod(stream.fileno(), 0o600)
      stream.write(canonical(value) + b"\n")
      stream.flush()
      os.fsync(stream.fileno())
    try:
      _rename_noreplace(directory, temporary, path.name)
    except OSError as error:
      if error.errno == errno.EEXIST:
        raise BenchError(4, "output_exists") from None
      if error.errno in {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP}:
        raise BenchError(5, "atomic_publish_unavailable") from None
      raise
    staged = False
    os.fsync(directory)
  finally:
    try:
      if staged:
        try:
          os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
          pass
    finally:
      os.close(directory)


def statistics(samples, *, p95=True):
  if not samples or any(not isinstance(x, (int, float)) or isinstance(x, bool) or not math.isfinite(x) or x < 0 for x in samples):
    raise BenchError(2, "invalid_samples")
  if p95 and len(samples) < 200:
    raise BenchError(5, "p95_requires_200_samples_per_batch")
  values = sorted(samples)
  return {"n": len(values), "median": stats.median(values), "p95": values[math.ceil(0.95 * len(values)) - 1] if p95 else None, "min": values[0], "max": values[-1]}


def regression(before, after, threshold):
  delta = after - before
  if before <= threshold["near_zero"]:
    return delta > threshold["absolute"]
  return delta > threshold["absolute"] and delta / before > threshold["relative"]


def public_subject(identity):
  return {**deepcopy(identity), "binary": "<HERDR>", "acceptance_ref": "<ACCEPTANCE>"}


def empty_report(manifest, policy, subject, scope):
  identity = manifest["subjects"][subject]
  if identity is None:
    raise BenchError(2, "subject_missing")
  return sealed({"schema_version": 1, "report_id": "report-" + uuid.uuid4().hex, "kind": "measurement",
    "manifest_digest": manifest["digest"], "policy_digest": policy["digest"], "fixture_digest": manifest["fixture_digest"],
    "source": deepcopy(manifest["source"]), "inputs": deepcopy(identity["inputs"]), "subject": subject,
    "subject_identity": public_subject(identity), "scope": scope, "authorization_ref": manifest["authorization_ref"],
    "isolation": {"verified": False, "evidence_ref": None, "sentinels_unchanged": False, "private_originals_verified": False},
    "coverage": {"cpu_complete": False, "pid_identity": "pid-and-proc-stat-starttime", "rss_interval_seconds": 1, "client_ready_proven": False, "dimensions_proven": False, "client_version_verified": False, "effective_inputs_verified": False, "reason": "short_lived_process_cpu_coverage_not_proven"},
    "cpu_windows": [], "origin_receipts": [], "steps": [], "batches": [], "measurements": [], "correctness": [], "producer": [], "evidence": [],
    "invalid_reasons": [], "retest_refs": [], "validity": "invalid", "decision": "measured", "comparison_kind": scope,
    "item_decisions": [], "baseline_digest": None, "operation_exit_code": 0, "paired_run_id": None, "paired_schedule": [], "task_status": "环境不足未验证", "reason": "native_measurement_not_executed"})


def check_producers(report, manifest=None):
  reasons = set(report["invalid_reasons"])
  for producer in report["producer"]:
    duration = 60 if producer["phase"] == "warmup" else 300
    if producer["end_ns"] - producer["start_ns"] < duration * 1_000_000_000:
      reasons.add("producer_window_shortfall")
    if producer["mode"] == "output" and (producer["lines"] != duration * 512 or producer["bytes"] != duration * 512 * 128):
      reasons.add("producer_shortfall")
  if manifest is not None:
    expected_groups = {(w["id"], mode, batch, phase): w["terminals"] for w in manifest["workloads"] for mode in w["modes"] for batch in (1, 2, 3) for phase in ("warmup", "measure")}
    groups = {}
    for row in report["producer"]:
      key = (row["workload"], row["mode"], row["batch"], row["phase"])
      groups.setdefault(key, []).append(row)
    if set(groups) != set(expected_groups):
      reasons.add("producer_matrix_missing_or_extra")
    for key, count in expected_groups.items():
      rows = groups.get(key, [])
      if len(rows) != count or len({r["pane_label"] for r in rows}) != count:
        reasons.add("producer_instance_count_mismatch")
      if rows and len({r["start_ns"] for r in rows}) != 1:
        reasons.add("producer_barrier_mismatch")
      other = groups.get((*key[:3], "measure" if key[3] == "warmup" else "warmup"), [])
      if {r["pane_label"] for r in rows} != {r["pane_label"] for r in other}:
        reasons.add("producer_identity_changed_between_windows")
  report["invalid_reasons"] = sorted(reasons)
  if reasons:
    report["validity"] = "invalid"


def normalize_argv(argv, manifest, manifest_dir=None):
  directory = Path(manifest_dir or ".").absolute()
  paths = list(manifest["paths"]) + [{"label": "ROTOM", "path": str(ROOT)},
    {"label": "ISOLATION", "path": str(resolve_path(manifest["isolation"]["root"], directory).absolute())}]
  for identity in manifest["subjects"].values():
    if isinstance(identity, dict) and "binary" in identity:
      paths.append({"label": "HERDR", "path": str(resolve_path(identity["binary"], directory).absolute())})
  paths.sort(key=lambda x: len(x["path"]), reverse=True)
  return [next(("<" + item["label"] + ">" + arg[len(item["path"]):] for item in paths
               if arg == item["path"] or arg.startswith(item["path"] + os.sep)), arg) for arg in argv]


def matches_recipe(expected, actual):
  import re
  if len(expected) != len(actual):
    return False
  for planned, observed in zip(expected, actual):
    if planned == observed:
      continue
    if planned in {"<CHECKOUT>", "<LOCAL>"}:
      if not observed.startswith("<ISOLATION>/") or ".." in Path(observed).parts:
        return False
      if planned == "<LOCAL>" and not observed.endswith("/local.toml"):
        return False
    elif planned == "<SESSION>":
      if not re.fullmatch(r"bench-[A-Za-z0-9_-]{1,58}", observed):
        return False
    elif planned == "<PANE>":
      if not re.fullmatch(r"[A-Za-z0-9_:-]{1,128}", observed):
        return False
    else:
      return False
  return True


def resolve_path(value, directory):
  path = Path(value)
  return path if path.is_absolute() else Path(directory) / path


def private_directory(path, *, create=False):
  path = Path(path).absolute()
  if path.resolve().is_relative_to(ROOT.resolve()):
    raise BenchError(4, "private_records_must_be_outside_repository")
  if create and not path.exists():
    path.mkdir(mode=0o700)
  info = path.lstat()
  if not stat.S_ISDIR(info.st_mode) or path.is_symlink() or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
    raise BenchError(4, "unsafe_private_directory")
  return path


def output_cpu_cost(cpu, producers, workload, mode, batch, *, interval_count, source_reason=None):
  """每 MiB 成本只用本 case 的实际 measure 字节，不用标称输出量。"""
  def missing(reason):
    return {"value": None, "n": 0, "samples": [], "reason": reason}
  if cpu is None:
    return missing(source_reason or "cpu_output_cost_numerator_unavailable")
  if mode != "output":
    return missing("cpu_output_cost_requires_output_mode")
  if type(interval_count) is not int or interval_count != 300:
    return missing("cpu_output_cost_window_incomplete")
  try:
    if type(cpu) not in (int, float) or not math.isfinite(cpu) or cpu < 0:
      return missing("cpu_output_cost_numerator_unavailable")
  except OverflowError:
    return missing("cpu_output_cost_numerator_unavailable")
  rows = [item for item in producers if item.get("workload") == workload and item.get("mode") == mode and
    item.get("batch") == batch and item.get("phase") == "measure"]
  if not rows or any(type(item.get("bytes")) is not int or item["bytes"] <= 0 for item in rows):
    return missing("producer_output_bytes_missing_or_invalid")
  try:
    mib = sum(item["bytes"] for item in rows) / (1 << 20)
    value = cpu / mib
    if not math.isfinite(mib) or not math.isfinite(value):
      return missing("producer_output_bytes_missing_or_invalid")
  except (OverflowError, ZeroDivisionError):
    return missing("producer_output_bytes_missing_or_invalid")
  return {"value": value, "n": 300, "samples": [], "reason": None}


def verify_cpu_original(manifest, report, row, raw):
  fields = {"method", "completeness_scope", "workload", "mode", "batch", "subject_digest", "delegation", "delegation_digest", "module_digest",
    "target_start_ns", "target_end_ns", "tolerance_ns", "snapshots", "members_before", "members_after", "server_pid", "driver_pid", "client_pids", "ready"}
  if set(raw) != fields or any(raw[key] != row[key] for key in ("method", "completeness_scope", "workload", "mode", "batch")):
    return False
  try:
    _validate_receipt(raw["delegation"])
  except CpuacctError:
    return False
  if (raw["subject_digest"] != digest(report["subject_identity"]) or raw["method"] != "cpuacct-v1" or
      raw["completeness_scope"] != "server-group-descendants" or
      raw["module_digest"] != bytes_digest(Path(__file__).with_name("cpuacct.py")) or
      raw["delegation_digest"] != row["source_digest"] or hashlib.sha256(canonical(raw["delegation"])).hexdigest() != row["source_digest"] or
      raw["delegation"].get("method") != "cpuacct-v1" or raw["delegation"].get("schema_version") != 1 or
      raw["tolerance_ns"] != CPU_WINDOW_TOLERANCE_NS or
      raw["target_end_ns"] - raw["target_start_ns"] != CPU_WINDOW_SECONDS * 1_000_000_000):
    return False
  snapshots = raw["snapshots"]
  if len(snapshots) != 301:
    return False
  previous_end = 0
  for snapshot in snapshots:
    if (type(snapshot["read_begin_ns"]) is not int or type(snapshot["read_end_ns"]) is not int or
        not previous_end <= snapshot["read_begin_ns"] <= snapshot["read_end_ns"] or
        set(snapshot["counters"]) != {"server", "client", "producer", "driver"} or
        any(set(item) != {"user_ns", "system_ns"} for item in snapshot["counters"].values())):
      return False
    previous_end = snapshot["read_end_ns"]
  args = (raw["server_pid"], raw["ready"], raw["client_pids"], raw["delegation_digest"])
  verified = (_cpu_members_match(raw["members_before"], *args, driver_pid=raw["driver_pid"]) and
    _cpu_members_match(raw["members_after"], *args, previous=raw["members_before"], driver_pid=raw["driver_pid"]))
  verified = verified and _server_cpu_membership(snapshots, raw["members_before"], raw["members_after"], raw["server_pid"])
  values, reason = cpu_window_values(snapshots[0], snapshots[-1], raw["target_start_ns"], members_verified=verified)
  if row["complete"] != (reason is None) or row["reason"] != reason:
    return False
  breakdown, _ = server_cpu_breakdown(values["server_group"], snapshots[0]["server_main"], snapshots[-1]["server_main"])
  values.update(breakdown)
  samples = {}
  for before, after in zip(snapshots, snapshots[1:]):
    deltas, _ = cpu_window_values(before, after, before["read_begin_ns"], members_verified=True)
    for group, value in deltas.items():
      samples.setdefault(group, []).append(value)
  rows = [item for item in report["measurements"] if item["workload"] == row["workload"] and
    item["mode"] == row["mode"] and item["batch"] == row["batch"] and item["metric"].startswith("cpu.")]
  for item in rows:
    if item["metric"] not in {"cpu.core_seconds", "cpu.cores", "cpu.per_mib"} or item["group"] not in values:
      return False
    if item["metric"] == "cpu.per_mib":
      cost = output_cpu_cost(values[item["group"]], report["producer"], row["workload"], row["mode"], row["batch"],
        interval_count=len(snapshots) - 1, source_reason="server_tgid_tick_precision_or_identity_unproven")
      if item["unit"] != "core-seconds/MiB" or type(item["n"]) is not int or any(item[key] != cost[key] for key in ("n", "samples", "reason")):
        return False
      if cost["value"] is None:
        if item["value"] is not None:
          return False
      elif type(item["value"]) not in (int, float) or not math.isclose(item["value"], cost["value"], rel_tol=1e-12, abs_tol=1e-12):
        return False
      continue
    expected = values[item["group"]]
    if expected is None:
      if item["value"] is not None or item["n"] != 0 or item["samples"] or not item["reason"]:
        return False
      continue
    wall_seconds = ((snapshots[-1]["read_begin_ns"] + snapshots[-1]["read_end_ns"]) -
      (snapshots[0]["read_begin_ns"] + snapshots[0]["read_end_ns"])) / 2_000_000_000
    expected = expected if item["metric"] == "cpu.core_seconds" else expected / wall_seconds
    if item["value"] is None or not math.isclose(item["value"], expected, rel_tol=1e-12, abs_tol=1e-12) or item["reason"] is not None:
      return False
    expected_samples = samples.get(item["group"], [])
    if item["samples"] != expected_samples or item["n"] != (len(expected_samples) if expected_samples else 2):
      return False
  for spec in manifest["measure_specs"]:
    if spec["required"] and spec["metric"].startswith("cpu.") and row["workload"] in spec.get("workloads", WORKLOADS):
      if not any(item["metric"] == spec["metric"] and item["group"] == spec["group"] for item in rows):
        return False
  return True


def verify_originals(manifest, report, manifest_dir):
  try:
    if not verify_socket_filter_originals(manifest, report, manifest_dir):
      return False
    directory = private_directory(resolve_path(manifest["isolation"]["private_record_root"], manifest_dir))
    if not verify_churn_originals(manifest, report, directory):
      return False
    if not verify_client_originals(manifest, report, directory):
      return False
    steps = {step["id"]: step for step in manifest["steps"]}
    if not report["steps"] or not set(s["id"] for s in report["steps"]).issubset(steps):
      return False
    for step in report["steps"]:
      if not step["ready_evidence_ref"]:
        return False
      path = directory / step["evidence_ref"]
      info = path.lstat()
      if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600:
        return False
      if bytes_digest(path) != step["execution_digest"]:
        return False
      original = read_json(path)
      if set(original) != {"expected_argv", "actual_argv", "subject_digest", "exit_code", "start_ns", "end_ns"}:
        return False
      if (not matches_recipe(steps[step["id"]]["argv"], normalize_argv(original["expected_argv"], manifest, manifest_dir)) or original["actual_argv"] != original["expected_argv"] or
          original["subject_digest"] != digest(report["subject_identity"]) or original["exit_code"] != step["exit_code"] or original["exit_code"] != steps[step["id"]]["expected_exit"] or
          original["start_ns"] != step["start_ns"] or original["end_ns"] != step["end_ns"] or
          normalize_argv(original["actual_argv"], manifest, manifest_dir) != step["normalized_argv"] or not step["original_verified"]):
        return False
    if report["coverage"]["cpu_complete"] and not cpu_coverage_proven(manifest, report):
      return False
    for row in report.get("cpu_windows", []):
      path = directory / row["evidence_ref"]
      info = path.lstat()
      if (path.name != row["evidence_ref"] or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
          info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or bytes_digest(path) != row["execution_digest"] or
          not verify_cpu_original(manifest, report, row, read_json(path))):
        return False
    if report["coverage"]["effective_inputs_verified"]:
      if not report.get("origin_receipts"):
        return False
      for receipt in report["origin_receipts"]:
        path = directory / receipt["evidence_ref"]
        info = path.lstat()
        if path.name != receipt["evidence_ref"] or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or bytes_digest(path) != receipt["execution_digest"]:
          return False
        raw = read_json(path)
        rules, integrations = origin_fingerprints(raw["manifests_reply"], raw["integration_status"], report["subject_identity"]["asset_digest"], report["inputs"]["config_digest"])
        if raw["subject_digest"] != digest(report["subject_identity"]) or raw["rules"] != rules or raw["integrations"] != integrations:
          return False
        for field, value, kind in (("rules_digest", rules, "rules_identity_kind"), ("integration_digest", integrations, "integration_identity_kind")):
          if receipt[field] != hashlib.sha256(canonical(value)).hexdigest() or report["inputs"][field] != receipt[field] or report["inputs"].get(kind) != value["kind"] or receipt[kind] != value["kind"]:
            return False
    return True
  except (OSError, BenchError, KeyError, TypeError, ValueError, IndexError):
    return False


def compare(manifest, policy, candidate, baseline=None, *, originals_verified=False, calibration_verified=False, baseline_accepted=False):
  validate_references(manifest, policy, [candidate] + ([baseline] if baseline else []))
  if baseline is None and manifest["scope"] != "first-baseline":
    raise BenchError(2, "baseline_required_for_upgrade_scope")
  if baseline is not None:
    if manifest["scope"] == "first-baseline" or baseline["subject"] != "baseline" or candidate["subject"] != "candidate":
      raise BenchError(2, "comparison_subject_or_scope_mismatch")
    baseline = deepcopy(baseline)
    check_producers(baseline, manifest)
  result = deepcopy(candidate)
  result.update(kind="comparison", report_id="decision-" + uuid.uuid4().hex, item_decisions=[], baseline_digest=baseline["digest"] if baseline else None)
  result["isolation"]["private_originals_verified"] = originals_verified
  check_producers(result, manifest)
  failures = any(check["status"] == "failure" for check in candidate["correctness"])
  if baseline:
    failures |= any(check["status"] == "failure" for check in baseline["correctness"])
  reasons = []
  if baseline is not None and not baseline_accepted:
    reasons.append("prior_baseline_acceptance_not_verified")
  expected_matrix = {(name, tuple(["idle", "output"] if name == "detached-30" else ["output"] if name.startswith("output") else ["record"] if name in {"projects-27", "clients-size", "churn-leak"} else ["idle"])) for name in WORKLOADS}
  actual_matrix = {(w["id"], tuple(w["modes"])) for w in manifest["workloads"]}
  if actual_matrix != expected_matrix:
    reasons.append("partial_matrix_not_full_acceptance")
  if not paired_proof(manifest, candidate, baseline):
    reasons.append("frozen_paired_order_or_windows_not_proven")
  complete = bool(policy["frozen_at"] and policy["approval_ref"] and policy["calibration_refs"])
  if not complete or not calibration_verified:
    reasons.append("policy_not_calibrated_approved_and_frozen")
  if not originals_verified:
    reasons.append("private_execution_originals_not_verified")
  for report in [candidate] + ([baseline] if baseline else []):
    if not report["coverage"]["cpu_complete"] or not cpu_coverage_proven(manifest, report):
      reasons.append("complete_process_cpu_coverage_not_proven")
    if not report["coverage"]["client_version_verified"]:
      reasons.append("actual_client_version_not_verified")
    if not report["coverage"]["effective_inputs_verified"]:
      reasons.append("effective_rules_and_integrations_not_verified")
    if not report["coverage"]["client_ready_proven"] or not client_coverage_proven(manifest, report, "ready"):
      reasons.append("client_ready_not_proven")
    if any(w["id"] == "clients-size" for w in manifest["workloads"]) and (not report["coverage"]["dimensions_proven"] or not client_coverage_proven(manifest, report, "geometry")):
      reasons.append("shared_dimensions_not_proven")
    if not report["isolation"]["verified"] or not report["isolation"]["sentinels_unchanged"]:
      reasons.append("isolation_not_proven")
    if not set(manifest["correctness_cases"]).issubset(c["id"] for c in report["correctness"] if c["status"] == "pass" and c["evidence_ref"]):
      reasons.append("required_correctness_cases_missing")
    if not report["correctness"] or any(c["status"] != "pass" or not c["evidence_ref"] for c in report["correctness"]):
      reasons.append("correctness_incomplete")
    if any(e["required"] and (e["status"] != "pass" or not e["evidence_ref"]) for e in report["evidence"]):
      reasons.append("required_evidence_missing")
    if not report["evidence"]:
      reasons.append("required_evidence_missing")
    if len(report["batches"]) != 3 or {b["batch"] for b in report["batches"]} != {1, 2, 3}:
      reasons.append("three_batches_required")
    for batch in report["batches"]:
      if batch["identity_digest"] != digest(report["subject_identity"]) or batch["end_ns"] - batch["start_ns"] < 300_000_000_000:
        reasons.append("batch_identity_or_window_invalid")
  calibration_identity = digest((baseline or candidate)["subject_identity"])
  if complete and not any(c["subject_digest"] == calibration_identity for c in policy["calibration_refs"]):
    reasons.append("calibration_identity_mismatch")
  if result["validity"] != "valid" or (baseline and baseline["validity"] != "valid"):
    reasons.append("invalid_performance_run")
  def indexed(report):
    return {(m["workload"], m["mode"], m["batch"], m["metric"], m["group"]): m for m in report["measurements"]}
  candidate_metrics = indexed(candidate)
  baseline_metrics = indexed(baseline) if baseline else {}
  budgets = {(m["metric"], m["group"]): m for m in policy["metrics"]}
  for workload in [dict(w, mode=mode) for w in manifest["workloads"] for mode in w["modes"]]:
    for spec in manifest["measure_specs"]:
      if spec.get("workloads") and workload["id"] not in spec["workloads"]:
        continue
      key = (spec["metric"], spec["group"])
      budget = budgets.get(key)
      outcomes = []
      missing = False
      for batch in (1, 2, 3):
        metric = candidate_metrics.get((workload["id"], workload["mode"], batch, *key))
        before = baseline_metrics.get((workload["id"], workload["mode"], batch, *key)) if baseline else None
        if metric is None or metric["value"] is None or (baseline and (before is None or before["value"] is None)):
          missing = True
          continue
        if spec["metric"] in WARM and (metric["n"] < 200 or len(metric["samples"]) != metric["n"]):
          missing = True
        if spec["metric"].startswith(("cpu.", "rss.")):
          for observed in (metric, before) if before is not None else (metric,):
            if spec["metric"] == "rss.slope":
              if observed["n"] != 7 or len(observed["samples"]) != 7:
                missing = True
            elif observed["n"] < 300:
              missing = True
        if spec["metric"] == "latency.cold.median" and metric["n"] < 30:
          missing = True
        if budget is None or budget["absolute_budget"] is None or budget["noise_absolute"] is None or budget["unit"] != spec["unit"]:
          missing = True
          continue
        over = metric["value"] > budget["absolute_budget"]
        regressed = bool(before and regression(before["value"], metric["value"], budget["regression"]))
        noisy = bool(regressed and metric["value"] - before["value"] <= budget["noise_absolute"])
        outcomes.append("failure" if over or regressed and not noisy else "unverified" if noisy else "pass")
      item_id = workload["id"] + ":" + workload["mode"] + ":" + spec["metric"] + ":" + spec["group"]
      required = workload["required"] and spec["required"]
      if result["validity"] == "invalid" or missing or len(outcomes) != 3 or not complete:
        decision, reason = "unverified", "metric_or_calibration_missing_or_invalid"
      elif all(outcome == "failure" for outcome in outcomes):
        decision, reason = "failure", "reproducible_budget_or_regression_failure"
        failures |= required
      elif any(outcome != "pass" for outcome in outcomes):
        decision, reason = "unverified", "batch_disagreement_repeat_all_three_retain_first"
      else:
        decision, reason = "pass", None
      if required and decision == "unverified":
        reasons.append(item_id)
      result["item_decisions"].append({"id": item_id, "decision": decision, "reason": reason})
  result["decision"] = "failure" if failures else "unverified" if reasons else "pass"
  result["task_status"] = {"failure": "失败待决策", "unverified": "环境不足未验证", "pass": "已完成"}[result["decision"]]
  result["reason"] = "correctness_failure" if failures and any(c["status"] == "failure" for c in candidate["correctness"]) else ";".join(sorted(set(reasons))) or None
  return sealed(result)


def calibrated_policy(policy, report):
  proposed = deepcopy(policy)
  proposed.update(policy_id=policy["policy_id"] + "-pending-calibration", approval_ref=None, frozen_at=None,
    calibration_refs=[{"report_digest": report["digest"], "subject_digest": digest(report["subject_identity"]),
                       "evidence_ref": report["report_id"] + ".json", "policy_digest": policy["digest"], "policy_ref": policy["policy_id"] + ".json"}],
    pending_reason="Review native coverage and A/A evidence; approval is never automatic.")
  for budget in proposed["metrics"]:
    ranges = []
    keys = {(m["workload"], m["mode"]) for m in report["measurements"] if m["metric"] == budget["metric"] and m["group"] == budget["group"]}
    for workload, mode in keys:
      values = [m["value"] for m in report["measurements"] if m["metric"] == budget["metric"] and m["group"] == budget["group"] and m["workload"] == workload and m["mode"] == mode and m["value"] is not None]
      if len(values) == 3:
        ranges.append(max(values) - min(values))
    if ranges:
      budget["noise_absolute"] = max(ranges)
      budget["noise_reason"] = None
  return sealed(proposed)


def verify_calibrations(manifest, policy, policy_dir, manifest_dir):
  if not policy["calibration_refs"]:
    return False
  try:
    for reference in policy["calibration_refs"]:
      # 公开引用限同目录逻辑文件，不能借校准引用读取任意私人文件。
      if any(Path(reference[key]).name != reference[key] for key in ("evidence_ref", "policy_ref")):
        return False
      calibration = validate_document(read_json(Path(policy_dir) / reference["evidence_ref"]), "report")
      absolute_policy = validate_document(read_json(Path(policy_dir) / reference["policy_ref"]), "policy")
      if (calibration["digest"] != reference["report_digest"] or calibration["kind"] != "calibration" or
          calibration["policy_digest"] != reference["policy_digest"] or absolute_policy["digest"] != reference["policy_digest"] or
          digest(calibration["subject_identity"]) != reference["subject_digest"] or calibration["validity"] != "valid" or
          not calibration["coverage"]["cpu_complete"] or not cpu_coverage_proven(manifest, calibration) or not absolute_policy["frozen_at"] or not absolute_policy["approval_ref"]):
        return False
      if [(m["metric"], m["group"], m["unit"], m["absolute_budget"], m["regression"]) for m in policy["metrics"]] != [(m["metric"], m["group"], m["unit"], m["absolute_budget"], m["regression"]) for m in absolute_policy["metrics"]]:
        return False
      derived = calibrated_policy(absolute_policy, calibration)
      if [m["noise_absolute"] for m in derived["metrics"]] != [m["noise_absolute"] for m in policy["metrics"]]:
        return False
      if not verify_originals(manifest, calibration, manifest_dir):
        return False
    return True
  except (BenchError, OSError, KeyError, TypeError):
    return False


def preflight(manifest, subject, manifest_dir):
  """所有原生进程之前验证全新隔离根、私有证据、精确资产与哨兵。"""
  identity = manifest["subjects"][subject]
  if identity is None:
    raise BenchError(2, "subject_missing")
  root = resolve_path(manifest["isolation"]["root"], manifest_dir).absolute()
  if root.exists() or root.is_symlink() or root.resolve().is_relative_to(ROOT.resolve()):
    raise BenchError(4, "isolation_root_must_be_new_and_outside_repository")
  check_socket_capacity(root)
  private = private_directory(resolve_path(manifest["isolation"]["private_record_root"], manifest_dir), create=True)
  if root == private or private.is_relative_to(root) or root.is_relative_to(private):
    raise BenchError(4, "isolation_and_evidence_roots_overlap")
  binary = resolve_path(identity["binary"], manifest_dir)
  if not binary.is_file() or not os.access(binary, os.X_OK) or bytes_digest(binary) != identity["asset_digest"]:
    raise BenchError(5, "official_asset_identity_not_verified")
  from termcfg.work import source_digest as work_source_digest
  if manifest["source"]["source_digest"] != work_source_digest(ROOT) or manifest["source"]["lock_digest"] != bytes_digest(ROOT / "uv.lock"):
    raise BenchError(2, "actual_source_or_dependency_lock_identity_mismatch")
  git_env = {"PATH": "/usr/bin:/bin", "HOME": "/", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
  for reference, field in (("HEAD", "candidate_commit"), ("refs/heads/main", "target_main")):
    observed = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", str(ROOT), "rev-parse", reference],
      env=git_env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=5, check=False)
    if observed.returncode or observed.stdout.decode().strip() != manifest["source"][field]:
      raise BenchError(2, "actual_source_commit_or_target_main_mismatch")
  sentinels = []
  for item in manifest["isolation"]["sentinels"]:
    path = resolve_path(item["path"], manifest_dir)
    if not path.absolute().is_relative_to(private) or path.is_symlink() or not path.is_file() or bytes_digest(path) != item["digest"]:
      raise BenchError(4, "sentinel_identity_mismatch")
    sentinels.append((path, item["digest"]))
  if not sentinels or not manifest["isolation"]["network_evidence_ref"] or not manifest["isolation"]["ownership_ref"]:
    raise BenchError(4, "isolation_proof_missing")
  return {"root": root, "private": private, "binary": binary, "sentinels": sentinels}


class ProcSampler:
  """procfs 可见进程采样；pid+starttime 防重用，不声称覆盖短命进程。"""
  def __init__(self, server_pid, producer_pids=(), client_pids=(), *, proc=Path("/proc"), group_members=None):
    self.proc = Path(proc)
    self.group_members = group_members
    self.server_pid = server_pid
    self.seeds = {server_pid: "server", **{p: "producer" for p in producer_pids}, **{p: "client" for p in client_pids}}
    self.identities = {}
    self.last_cpu = {}
    self.cpu = {g: 0.0 for g in ("server", "helpers", "client", "producer")}
    self.rss = {g: [] for g in ("server", "helpers", "server_group", "client", "producer")}
    self.fds = []
    self.processes = []
    self.lost = False
    self.ticks = os.sysconf("SC_CLK_TCK")
    self.page_size = os.sysconf("SC_PAGE_SIZE")

  def snapshot(self):
    result = {}
    for entry in self.proc.iterdir():
      if not entry.name.isdigit():
        continue
      try:
        fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
        result[int(entry.name)] = {"ppid": int(fields[1]), "cpu": (int(fields[11]) + int(fields[12])) / self.ticks,
          "start": int(fields[19]), "rss": int(fields[21]) * self.page_size}
      except (OSError, ValueError, IndexError):
        continue
    return result

  def sample(self):
    live = self.snapshot()
    if self.group_members is None:
      groups = {pid: group for pid, group in self.seeds.items() if pid in live}
      for _ in range(len(live)):
        added = False
        for pid, item in live.items():
          if pid not in groups and item["ppid"] in groups:
            parent = groups[item["ppid"]]
            groups[pid] = "helpers" if parent in {"server", "helpers"} else parent
            added = True
        if not added:
          break
    else:
      groups = {}
      members = self.group_members()
      if type(members) is not dict or set(members) != {"server", "client", "producer", "driver"}:
        self.lost = True
        members = {}
      seen = set()
      for role, entries in members.items():
        if type(entries) is not list:
          self.lost = True
          continue
        for member in entries:
          if (type(member) is not dict or set(member) != {"pid", "starttime"} or
              any(type(member[key]) is not int or member[key] <= 0 for key in ("pid", "starttime"))):
            self.lost = True
            continue
          pid = member["pid"]
          if pid in seen:
            self.lost = True
            continue
          seen.add(pid)
          if role == "driver":
            continue
          if pid not in live or live[pid]["start"] != member["starttime"]:
            self.lost = True
            continue
          groups[pid] = ("server" if pid == self.server_pid else "helpers") if role == "server" else role
      if self.server_pid not in groups:
        self.lost = True
    rss = {g: 0 for g in self.rss}
    fds = 0
    for pid, group in groups.items():
      item = live[pid]
      identity = (pid, item["start"])
      if pid in self.identities and self.identities[pid] != identity:
        self.lost = True
        continue
      self.identities[pid] = identity
      previous = self.last_cpu.get(identity, item["cpu"])
      self.cpu[group] += max(0, item["cpu"] - previous)
      self.last_cpu[identity] = item["cpu"]
      rss[group] += item["rss"]
      try:
        fds += len(list((self.proc / str(pid) / "fd").iterdir()))
      except OSError:
        self.lost = True
    rss["server_group"] = rss["server"] + rss["helpers"]
    for group, value in rss.items():
      self.rss[group].append(value)
    self.fds.append(fds)
    self.processes.append(len(groups))
    return groups


BUNDLED_AGENTS = frozenset("pi claude codex gemini cursor devin agy cline opencode copilot kimi kiro droid amp grok hermes kilo qodercli qwen letta maki muse".split())
INTEGRATION_TARGETS = frozenset("pi omp claude codex copilot devin droid kimi opencode kilo hermes qodercli qwen cursor mastracode antigravity-cli grok letta".split())


def benchmark_session(prefix):
  return prefix[:8] + "-" + uuid.uuid4().hex[:12]


def benchmark_case(base, batch, workload, mode, manifest):
  index = next(i for i, item in enumerate(manifest["workloads"]) if item["id"] == workload)
  modes = next(item["modes"] for item in manifest["workloads"] if item["id"] == workload)
  return base / (str(batch) + "-" + str(index) + "-" + str(modes.index(mode)))


def check_socket_capacity(base):
  # 最长 client socket 也必须容纳；更早拒绝，避免生成未知失败的server。
  sample = Path(base) / "3-9-1/home/.config/herdr/sessions" / ("b" * 21) / "herdr-client.sock"
  if len(os.fsencode(sample)) > 107:
    raise BenchError(2, "isolation_root_too_long_for_native_unix_socket_choose_shorter_new_root")


def network_isolated(*, dev_path=Path("/proc/self/net/dev")):
  """sysfs 可继承旧挂载；以当前网络命名空间的 proc 视图为准。"""
  try:
    lines = Path(dev_path).read_text().splitlines()
    names = [line.split(":", 1)[0].strip() for line in lines[2:] if ":" in line]
    return len(lines) >= 3 and names == ["lo"]
  except (OSError, UnicodeError):
    return False


def socket_filter_proof(groups=None):
  import importlib.util
  spec = importlib.util.spec_from_file_location("rotom_bench_socket_filter", FIXTURE / "socket_filter_exec.py")
  module = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(module)
  try:
    if groups is None:
      return module.prove_policy()
    return module.prove_policy(extra_fds_check=groups.check_driver_descriptors)
  except (CpuacctError, OSError, AttributeError, ValueError):
    raise BenchError(5, "offline_socket_capabilities_unverified") from None


def valid_socket_filter_proof(proof):
  fixed = {"mode": "offline-sockets-seccomp", "no_new_privs": 1, "seccomp": 2,
    "inet_errno": 1, "inet6_errno": 1, "inet_pair_errno": 1, "inet6_pair_errno": 1,
    "unix_ipc": True, "io_uring_errno": 1, "root_owner_visible": True,
    "network_stdio_absent": True, "extra_fds_absent": True}
  return (isinstance(proof, dict) and set(proof) == set(fixed) | {"uid", "gid"}
    and all(proof[key] == value and type(proof[key]) is type(value) for key, value in fixed.items())
    and all(type(proof[key]) is int and proof[key] >= 0 for key in ("uid", "gid")))


def record_socket_filter_proof(report, prepared, workload, mode, batch):
  groups = prepared.get("cpuacct_groups")
  proof = socket_filter_proof(groups) if groups is not None else socket_filter_proof()
  if not valid_socket_filter_proof(proof):
    raise BenchError(5, "offline_socket_capabilities_unverified")
  original = {"proof": proof, "subject_digest": digest(report["subject_identity"]),
    "helper_digest": bytes_digest(FIXTURE / "socket_filter_exec.py"), "workload": workload,
    "mode": mode, "batch": batch, "checked_ns": time.monotonic_ns()}
  name = uuid.uuid4().hex + ".json"
  path = prepared["private"] / name
  _private_value(path, original)
  report["isolation"].update(verified=True, evidence_ref="offline-sockets-seccomp", sentinels_unchanged=True)
  report["evidence"].append({"id": "offline-sockets-proof-" + str(batch) + "-" + workload + "-" + mode,
    "required": True, "status": "pass", "evidence_ref": "socket-proof:" + name + ":" + bytes_digest(path), "reason": None})


def verify_socket_filter_originals(manifest, report, manifest_dir):
  rows = [row for row in report["evidence"] if row["id"].startswith("offline-sockets-proof-")]
  if report["isolation"]["evidence_ref"] != "offline-sockets-seccomp":
    return not rows
  try:
    directory = private_directory(resolve_path(manifest["isolation"]["private_record_root"], manifest_dir))
    if not rows:
      return False
    cases = set()
    for row in rows:
      prefix, name, expected = row["evidence_ref"].split(":")
      if prefix != "socket-proof" or Path(name).name != name or row["status"] != "pass" or not row["required"]:
        return False
      path = directory / name
      info = path.lstat()
      if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600 or bytes_digest(path) != expected:
        return False
      raw = read_json(path)
      if (set(raw) != {"proof", "subject_digest", "helper_digest", "workload", "mode", "batch", "checked_ns"}
          or not valid_socket_filter_proof(raw["proof"]) or raw["subject_digest"] != digest(report["subject_identity"])
          or raw["helper_digest"] != bytes_digest(FIXTURE / "socket_filter_exec.py") or type(raw["checked_ns"]) is not int or raw["checked_ns"] <= 0):
        return False
      case = (raw["workload"], raw["mode"], raw["batch"])
      if case in cases:
        return False
      cases.add(case)
    expected_cases = {(p["workload"], p["mode"], p["batch"]) for p in report["producer"]}
    return not expected_cases or expected_cases <= cases
  except (OSError, BenchError, ValueError, KeyError, TypeError, AttributeError):
    return False


def origin_fingerprints(reply, status, asset_sha256, config_sha256):
  """只证明公开来源，不冒充有效规则原字节的导出。"""
  result = reply.get("result", {}) if isinstance(reply, dict) else {}
  rows = result.get("manifests", [])
  if result.get("type") != "agent_manifest_status" or not isinstance(rows, list):
    raise BenchError(5, "agent_manifest_origin_unverified")
  agents = []
  for row in rows:
    if (not isinstance(row, dict) or row.get("source_kind") != "bundled" or row.get("source") != "bundled"
        or row.get("local_override_shadowing_remote") is not False
        or any(row.get(key) is not None for key in ("cached_remote_version", "remote_update_result", "remote_update_error", "remote_last_checked_unix", "warning"))):
      raise BenchError(5, "agent_manifest_origin_unverified")
    agents.append(row.get("agent"))
  if len(agents) != len(BUNDLED_AGENTS) or set(agents) != BUNDLED_AGENTS:
    raise BenchError(5, "agent_manifest_origin_incomplete")
  targets = []
  for line in status.splitlines():
    label, separator, state = line.partition(": ")
    target = label.removesuffix(" (experimental)")
    if not separator or not state.startswith("not installed (") or not state.endswith(")"):
      raise BenchError(5, "integration_origin_not_disabled")
    if label != target + (" (experimental)" if target == "letta" else ""):
      raise BenchError(5, "integration_origin_unknown")
    targets.append(target)
  if len(targets) != len(INTEGRATION_TARGETS) or set(targets) != INTEGRATION_TARGETS:
    raise BenchError(5, "integration_origin_incomplete")
  return ({"kind": "builtin-origin-fingerprint", "asset_sha256": asset_sha256,
    "sources": [{"agent": agent, "source_kind": "bundled"} for agent in sorted(agents)]},
    {"kind": "disabled-origin-fingerprint", "asset_sha256": asset_sha256, "config_sha256": config_sha256,
    "targets": [{"target": target, "status": "not installed"} for target in sorted(targets)]})


def parse_task_clock(text):
  rows = [line.split(";") for line in text.splitlines() if line.strip() and not line.startswith("#")]
  try:
    if len(rows) != 1 or len(rows[0]) < 5:
      raise ValueError()
    value, unit, event, runtime, percent = rows[0][:5]
    number = float(value)
    if unit != "msec" or event not in {"task-clock", "task-clock:u"} or float(percent) != 100 or not math.isfinite(number) or number < 0 or int(runtime) <= 0:
      raise ValueError()
  except (ValueError, OverflowError):
    raise BenchError(5, "perf_task_clock_incomplete_or_unsupported") from None
  return {"value": float(Decimal(value) / 1000), "unit": "task-clock-seconds", "equivalent_user_system": False,
    "event": event, "reason": "task_clock_including_supervisor_is_not_frozen_user_plus_system_cpu"}


def perf_ack(value):
  return value in (b"ack\n", b"ack\n\x00")


def measure_applies(manifest, metric, workload, group="all"):
  return any(spec["metric"] == metric and spec["group"] == group and workload in spec.get("workloads", WORKLOADS)
    for spec in manifest["measure_specs"])


def duration_estimate(manifest):
  sampling = manifest["sampling"]
  cases = sum(len(w["modes"]) for w in manifest["workloads"])
  batches = sampling["batches"]
  churn = sum(len(w["modes"]) for w in manifest["workloads"] if w["id"] == "churn-leak")
  return {"fixed_seconds_per_subject": batches * (cases * (sampling["warmup_seconds"] + sampling["measure_seconds"]) + churn * (6 * 60 + 1800)),
    "warm_samples_per_subject": batches * sampling["warm_samples_per_batch"] * sum(len(w["modes"]) for w in manifest["workloads"] for metric in WARM if measure_applies(manifest, metric, w["id"])),
    "cold_samples_per_subject": batches * sampling["cold_samples_per_batch"] * sum(len(w["modes"]) for w in manifest["workloads"] if measure_applies(manifest, "latency.cold.median", w["id"])),
    "barrier_seconds_per_subject": batches * cases * 4,
    "lower_bound_seconds_per_subject": batches * (cases * (sampling["warmup_seconds"] + sampling["measure_seconds"] + 4) + churn * (6 * 60 + 1800)),
    "operation_seconds_included": False}


CPU_WINDOW_TOLERANCE_NS = 50_000_000
CPU_WINDOW_SECONDS = 300


def pump_owned_ptys(clients, timeout=0, observer=None):
  """仅排空本轮登记的非阻塞 PTY；可选瞬时观察后立即丢弃，公平轮转。"""
  import errno
  import select
  fds = [fd for process, fd in clients]
  if not fds:
    if timeout:
      time.sleep(timeout)
    return 0
  deadline = time.monotonic() + timeout
  ready, _, _ = select.select(fds, (), (), timeout)
  count = 0
  for fd in ready:
    for _ in range(16):
      try:
        chunk = os.read(fd, 65536)
      except BlockingIOError:
        break
      except OSError as error:
        if error.errno == errno.EIO:
          break
        raise
      if not chunk:
        break
      count += len(chunk)
      if observer is not None:
        observer(fd, chunk)
  if count == 0 and timeout:
    time.sleep(max(0, deadline - time.monotonic()))
  return count


def cpu_window_values(before, after, target_start_ns, *, members_verified):
  """内核聚合是 CPU 唯一完整来源；固定 50ms 采集容差不随结果调整。"""
  result = {}
  for role in ("server", "client", "producer", "driver"):
    delta = 0
    for field in ("user_ns", "system_ns"):
      first, last = before["counters"][role][field], after["counters"][role][field]
      if type(first) is not int or type(last) is not int or first < 0 or last < first:
        raise BenchError(5, "cpuacct_counter_regressed_or_invalid")
      delta += last - first
    result["server_group" if role == "server" else role] = delta / 1_000_000_000
  target_end = target_start_ns + CPU_WINDOW_SECONDS * 1_000_000_000
  for snapshot, target in ((before, target_start_ns), (after, target_end)):
    begin, end = snapshot["read_begin_ns"], snapshot["read_end_ns"]
    if not target <= begin <= end <= target + CPU_WINDOW_TOLERANCE_NS:
      return result, "cpuacct_window_unproven"
  midpoint_delta_twice = after["read_begin_ns"] + after["read_end_ns"] - before["read_begin_ns"] - before["read_end_ns"]
  if abs(midpoint_delta_twice - 2 * CPU_WINDOW_SECONDS * 1_000_000_000) > 2 * CPU_WINDOW_TOLERANCE_NS:
    return result, "cpuacct_window_unproven"
  return result, None if members_verified else "cpuacct_membership_unproven"


def server_cpu_identity(pid, *, proc=Path("/proc")):
  try:
    fields = (proc / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
    return {"pid": pid, "starttime": int(fields[19]), "ticks": int(fields[11]) + int(fields[12]),
      "ticks_per_second": os.sysconf("SC_CLK_TCK")}
  except (OSError, ValueError, IndexError):
    raise BenchError(5, "server_tgid_cpu_identity_unavailable") from None


def server_cpu_delta(before, after):
  if (before is None or after is None or
      any(set(item) != {"pid", "starttime", "ticks", "ticks_per_second"} or
        any(type(item[key]) is not int or item[key] <= 0 for key in ("pid", "starttime", "ticks_per_second")) or
        type(item["ticks"]) is not int or item["ticks"] < 0 for item in (before, after)) or
      any(before[key] != after[key] for key in ("pid", "starttime", "ticks_per_second")) or after["ticks"] < before["ticks"]):
    return None, "server_tgid_identity_unproven"
  return (after["ticks"] - before["ticks"]) / before["ticks_per_second"], None


def server_cpu_breakdown(total, before, after):
  main, reason = server_cpu_delta(before, after)
  helper = None if main is None else total - main
  if helper is not None and helper < 0:
    helper = None
    reason = "server_tgid_tick_precision_unproven"
  return {"server": main, "helpers": helper}, reason


def _cpu_snapshot(groups, server_pid=None):
  begin = time.monotonic_ns()
  counters = groups.read()
  main = server_cpu_identity(server_pid) if server_pid is not None else None
  return {"read_begin_ns": begin, "read_end_ns": time.monotonic_ns(), "counters": counters, "server_main": main}


def _cpu_members_match(members, server_pid, ready, client_pids, delegation_digest, previous=None, driver_pid=None):
  if (not isinstance(members, dict) or set(members) != {"server", "producer", "client", "driver"} or
      any(not isinstance(items, list) or any(not isinstance(item, dict) or set(item) != {"pid", "starttime"} or
        any(type(item[key]) is not int or item[key] <= 0 for key in ("pid", "starttime")) for item in items) or
        len({item["pid"] for item in items}) != len(items) for items in members.values())):
    return False
  if (server_pid not in {item["pid"] for item in members["server"]} or
      {item["pid"] for item in members["producer"]} != {item["pid"] for item in ready} or
      {item["pid"] for item in members["client"]} != set(client_pids) or
      {item["pid"] for item in members["driver"]} != {os.getpid() if driver_pid is None else driver_pid}):
    return False
  if any(item.get("cpuacct") != {"method": "cpuacct-v1", "role": "producer", "delegation_digest": delegation_digest} for item in ready):
    return False
  if previous is not None:
    for role in ("producer", "client", "driver"):
      if sorted(members[role], key=lambda item: item["pid"]) != sorted(previous[role], key=lambda item: item["pid"]):
        return False
    before_server = next((item for item in previous["server"] if item["pid"] == server_pid), None)
    after_server = next((item for item in members["server"] if item["pid"] == server_pid), None)
    if before_server != after_server:
      return False
  return True


def _server_cpu_membership(snapshots, before, after, server_pid):
  for snapshot, members in ((snapshots[0], before), (snapshots[-1], after)):
    main = snapshot["server_main"]
    identity = next((item for item in members["server"] if item["pid"] == server_pid), None)
    if main is None or identity is None or main["pid"] != identity["pid"] or main["starttime"] != identity["starttime"]:
      return False
  return True


def cpu_coverage_proven(manifest, report):
  required = [spec for spec in manifest["measure_specs"] if spec["required"] and spec["metric"].startswith("cpu.")]
  if not required or any(spec["group"] != "server_group" for spec in required):
    return False
  expected = {(workload["id"], mode, batch) for workload in manifest["workloads"] for mode in workload["modes"]
    for batch in (1, 2, 3) if any(workload["id"] in spec.get("workloads", WORKLOADS) for spec in required)}
  windows = report.get("cpu_windows", [])
  seen = set()
  for row in windows:
    key = (row["workload"], row["mode"], row["batch"])
    if key in seen or row["method"] != "cpuacct-v1" or row["completeness_scope"] != "server-group-descendants" or not row["complete"] or not row["evidence_ref"]:
      return False
    seen.add(key)
  return expected.issubset(seen) and "explicit_partial_measurement" not in report["invalid_reasons"]


def _sleep_until(ns, sampler=None, clients=None):
  next_sample = time.monotonic_ns()
  while time.monotonic_ns() < ns:
    if sampler and time.monotonic_ns() >= next_sample:
      sampler.sample()
      next_sample += 1_000_000_000
    remaining = max(0, (ns - time.monotonic_ns()) / 1_000_000_000)
    if clients is not None:
      pump_owned_ptys(clients, min(0.01, remaining))
    else:
      time.sleep(min(1, remaining))


def _private_value(path, value):
  write_new(path, value, private=True)


def _renew(client):
  from termcfg.herdr import Deadline
  client.deadline = Deadline()


def interactive_client_route(binary, session, env, client, discover):
  """UI使用公开session路由；API仍固定在原有端点。"""
  from termcfg.herdr import Deadline
  _renew(client)
  client.request("ping", {})
  found = discover(binary, session, Deadline())
  if not found or found["name"] != session or found["socket_path"] != client.socket_path:
    raise BenchError(4, "interactive_session_changed")
  current = Path(client.socket_path).lstat()
  if (current.st_dev, current.st_ino) != client.identity:
    raise BenchError(4, "interactive_endpoint_changed")
  ui_env = {k: v for k, v in env.items() if k not in {"HERDR_SOCKET_PATH", "HERDR_PANE_ID"}}
  return [binary, "--session", session], ui_env


def attach_interactive(binary, session, env, client, discover, clients, spawns, cols, rows, groups=None, ready_run_id=None):
  import fcntl
  import pty
  import struct
  import termios
  master, slave = pty.openpty()
  process = None
  try:
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    argv, ui_env = interactive_client_route(binary, session, env, client, discover)
    spawn_begin = time.monotonic_ns()
    os.set_blocking(master, False)
    with groups.spawn("client") if groups is not None else nullcontext():
      process = subprocess.Popen(argv, env=ui_env, stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
      # 恢复 driver 失败也必须追踪已经创建的子进程和 PTY。
      clients.append((process, master))
      spawns.append([process, "native-client", argv, spawn_begin, False])
  finally:
    os.close(slave)
    if process is None:
      os.close(master)
  interactive_client_route(binary, session, env, client, discover)
  if ready_run_id is not None:
    try:
      wait_owned_client_marker(process, master, run_id=ready_run_id,
        pump=lambda observer: pump_owned_ptys(clients, 0.005, observer=observer))
    except GeometryError as error:
      raise BenchError(5, error.reason) from None


def stop_owned_server(binary, session, env, client, discover, owned, record):
  # 完整核对所有登记对象后一次停服，不逐pane关闭或猜测跨工作区编号。
  if not owned:
    raise BenchError(4, "dedicated_server_owned_fixture_required")
  interactive_client_route(binary, session, env, client, discover)
  _renew(client)
  response = client.request("pane.list", {})
  remaining = response.get("panes") if isinstance(response, dict) else None
  keys = ("pane_id", "terminal_id", "workspace_id")
  def identities(panes):
    if not isinstance(panes, list) or not panes:
      return None
    result = []
    for pane in panes:
      if not isinstance(pane, dict) or any(not isinstance(pane.get(key), str) or not pane[key] for key in keys):
        return None
      result.append(tuple(pane[key] for key in keys))
    if len(set(result)) != len(result) or len({row[0] for row in result}) != len(result):
      return None
    return set(result)
  expected, actual = identities(owned), identities(remaining)
  if expected is None or actual is None or actual != expected:
    raise BenchError(4, "dedicated_server_has_unclassified_objects_preserve")
  interactive_client_route(binary, session, env, client, discover)
  record([binary, "server", "stop"], "owned-known-server-stop", {**env, "HERDR_SOCKET_PATH": client.pinned_address}, pass_fds=(client.pinned_fd,))


def collect_geometry_round(raw, round_number, clients, pane, focus, resize, probe, settle=lambda: None):
  if len(clients) != 2:
    raise GeometryError("two_owned_clients_required")
  focus(pane)
  for slot, (process, master) in enumerate(clients):
    cols, rows = ((120, 40), (80, 24))[(round_number + slot) % 2]
    resize(process, master, cols, rows)
  settle()
  for slot, (process, master) in enumerate(clients):
    cols, rows = ((120, 40), (80, 24))[(round_number + slot) % 2]
    frame = probe(process, master, pane, cols, rows, "measure")
    raw["frames"].append({"round": round_number, "slot": slot, "frame": frame})


def _known_producer_identity(pid):
  raw = (Path("/proc") / str(pid) / "stat").read_text()
  start = int(raw.rsplit(")", 1)[1].split()[19])
  cwd = str((Path("/proc") / str(pid) / "cwd").resolve(strict=True))
  return start, cwd


def verify_producer_ready(ready, pane, checkout, config_digest, process_info, before=None):
  if (ready.get("pane_id") != pane["pane_id"] or ready.get("config_digest") != config_digest or
      type(ready.get("pid")) is not int or ready["pid"] <= 0 or process_info.get("shell_pid") != ready["pid"]):
    raise BenchError(4, "producer_native_identity_mismatch")
  before = _known_producer_identity(ready["pid"]) if before is None else before
  after = _known_producer_identity(ready["pid"])
  if before != after or before[1] != str(Path(checkout).resolve(strict=True)):
    raise BenchError(4, "producer_cwd_or_starttime_mismatch")
  return {"pane_id": pane["pane_id"], "terminal_id": pane["terminal_id"], "workspace_id": pane["workspace_id"],
    "pid": ready["pid"], "starttime": before[0], "cwd": before[1], "config_digest": config_digest}



def _record_native_failure(directory, workload, mode, batch, phase, error, exit_code):
  """失败原件只保存固定类别和白名单原因，不序列化异常文本或上下文。"""
  from termcfg.errors import TermcfgError
  phases = {"socket-proof", "cpuacct-members", "discover", "version", "case-runtime"}
  if phase not in phases:
    raise BenchError(2, "invalid_native_failure_phase")
  category = next((name for kind, name in ((TermcfgError, "termcfg"), (BenchError, "bench"),
    (CpuacctError, "cpuacct"), (subprocess.SubprocessError, "subprocess"), (OSError, "os"),
    (KeyError, "key"), (ValueError, "value")) if isinstance(error, kind)), None)
  if category is None:
    raise BenchError(2, "invalid_native_failure_category")
  reason = error.reason if isinstance(error, (TermcfgError, BenchError, CpuacctError)) else None
  allowed = {"atomic_publish_unavailable", "offline_socket_capabilities_unverified", "cpuacct_previous_case_members_remain",
    "existing_server_refused", "native_config_file_required", "actual_client_version_mismatch",
    "synthetic_command_failed", "cpuacct_closed", "cpuacct_filesystem", "cpuacct_replaced",
    "cpuacct_directory", "cpuacct_file_permissions", "cpuacct_unavailable", "cpuacct_members",
    "cpuacct_member_identity", "cpuacct_case_cleanup_timeout", "cpuacct_threads", "cpuacct_source", "cpuacct_join", "cpuacct_role",
    "cpuacct_controller", "cpuacct_counter", "cpuacct_counter_regressed",
    "cpuacct_descriptor_registry", "cpuacct_descriptor_inheritable", "cpuacct_unknown_descriptor",
    "cpuacct_descriptor_missing", "cpuacct_descriptor_audit"}
  public_cli_reasons = {"Herdr public CLI unavailable or incompatible": "herdr_public_cli_unavailable",
    "Herdr session discovery is malformed": "herdr_session_discovery_malformed",
    "Herdr session discovery is ambiguous": "herdr_session_discovery_ambiguous",
    "Herdr session connection failed": "herdr_session_connection_failed",
    "Herdr API rejected request": "herdr_api_rejected_request",
    "Herdr endpoint changed": "herdr_endpoint_changed",
    "Herdr mutation result is unknown": "herdr_mutation_result_unknown",
    "Herdr operation deadline expired": "herdr_operation_deadline_expired"}
  # 格式合法仍不可信；只有有限字面白名单可进入原件。
  code = reason if type(reason) is str and reason in allowed else None
  if category == "termcfg" and type(reason) is str:
    code = public_cli_reasons.get(reason)
  if code is not None and re.fullmatch(r"[a-z][a-z0-9_]{0,95}", code) is None:
    code = None
  original = {"schema_version": 1, "kind": "native-case-failure-v1", "workload": workload,
    "mode": mode, "batch": batch, "at_ns": time.monotonic_ns(), "phase": phase,
    "exception_category": category, "exit_code": exit_code, "reason_code": code}
  name = uuid.uuid4().hex + ".json"
  path = Path(directory) / name
  _private_value(path, original)
  return "native-failure:" + name + ":" + bytes_digest(path)


def _native_measure(manifest, policy, subject, scope, manifest_dir, authorization, prepared, *, batch_numbers=(1, 2, 3), case_filter=None):
  """执行隔离 synthetic producer；可见数据与未证明的覆盖分开记录。"""
  from contextlib import contextmanager
  import fcntl
  import pty
  import struct
  import termios
  from termcfg.herdr import Deadline, HerdrClient, discover as raw_discover, start_headless, verify_schema as raw_verify_schema
  from termcfg.work import enter_project, open_role, operation_lock
  from termcfg.work_config import WorkSettings, read_settings
  from termcfg.errors import TermcfgError

  groups = prepared.get("cpuacct_groups")
  def discover(*args):
    with groups.spawn("client") if groups is not None else nullcontext():
      return raw_discover(*args)

  def verify_schema(*args):
    with groups.spawn("client") if groups is not None else nullcontext():
      return raw_verify_schema(*args)

  report = empty_report(manifest, policy, subject, scope)
  report["authorization_ref"] = authorization
  report["isolation"].update(verified=prepared.get("isolation_mode") != "offline-sockets", evidence_ref=None if prepared.get("isolation_mode") == "offline-sockets" else "dedicated-root-and-loopback-namespace", sentinels_unchanged=True)
  report["invalid_reasons"] = (["short_lived_process_cpu_coverage_not_proven"] if groups is None else [])
  report["reason"] = "cpuacct_server_group_windows_pending" if groups is not None else "visible_procfs_samples_only_no_complete_cpu_claim"
  base = prepared["root"]
  base.mkdir(mode=0o700)
  binary = str(prepared["binary"].resolve())
  original_environment = dict(os.environ)
  run_id = uuid.uuid4().hex
  producer_source = FIXTURE / "producer.py"
  measurements = report["measurements"]
  spawns = []

  def save_spawns():
    for entry in spawns:
      process, label, expected, begin, saved = entry
      if saved or process.poll() is None:
        continue
      actual = list(process.args)
      end = time.monotonic_ns()
      name = uuid.uuid4().hex + ".json"
      original = {"expected_argv": expected, "actual_argv": actual, "subject_digest": digest(report["subject_identity"]),
                  "exit_code": process.returncode, "start_ns": begin, "end_ns": end}
      _private_value(prepared["private"] / name, original)
      report["steps"].append({"id": label, "normalized_argv": normalize_argv(actual, manifest, manifest_dir), "cwd_label": "isolated-home",
        "exit_code": process.returncode, "start_ns": begin, "end_ns": end, "ready_evidence_ref": "owned-process-exit-observed",
        "execution_digest": bytes_digest(prepared["private"] / name), "evidence_ref": name, "original_verified": actual == expected})
      entry[4] = True

  def record(argv, label, env, cwd=None, pass_fds=()):
    recipe = next((step for step in manifest["steps"] if step["id"] == label), None)
    if recipe is None or not matches_recipe(recipe["argv"], normalize_argv(argv, manifest, manifest_dir)):
      raise BenchError(2, "undeclared_native_step")
    begin = time.monotonic_ns()
    with groups.spawn("client") if groups is not None else nullcontext():
      process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, pass_fds=pass_fds)
      spawn_entry = [process, label, argv, begin, False]
      spawns.append(spawn_entry)
    try:
      stdout, _ = process.communicate(timeout=30)
    except BaseException:
      process.kill()
      process.communicate()
      raise
    result = subprocess.CompletedProcess(argv, process.returncode, stdout)
    end = time.monotonic_ns()
    name = uuid.uuid4().hex + ".json"
    original = {"expected_argv": argv, "actual_argv": argv, "subject_digest": digest(report["subject_identity"]),
                "exit_code": result.returncode, "start_ns": begin, "end_ns": end}
    _private_value(prepared["private"] / name, original)
    report["steps"].append({"id": label, "normalized_argv": normalize_argv(argv, manifest, manifest_dir), "cwd_label": "synthetic-checkout",
      "exit_code": result.returncode, "start_ns": begin, "end_ns": end, "ready_evidence_ref": "official-command-exit-observed",
      "execution_digest": bytes_digest(prepared["private"] / name), "evidence_ref": name, "original_verified": True})
    spawn_entry[4] = True
    if result.returncode:
      raise BenchError(5, "synthetic_command_failed")
    return result

  def emit(workload, batch, metric, group, unit, value, n, samples=(), reason=None):
    spec = next((s for s in manifest["measure_specs"] if s["metric"] == metric and s["group"] == group), None)
    if spec and workload in spec.get("workloads", WORKLOADS):
      measurements.append({"workload": workload, "mode": mode, "batch": batch, "metric": metric, "group": group,
        "unit": unit, "value": value, "n": n, "samples": list(samples), "reason": reason})

  for batch in batch_numbers:
    batch_start = time.monotonic_ns()
    for workload in manifest["workloads"]:
      # 客户端/churn 仍执行真实采样；其控制语义额外列未验证，不能假装已验收。
      for mode in workload["modes"]:
        if case_filter is not None and case_filter != (workload["id"], mode):
          continue
        case = benchmark_case(base, batch, workload["id"], mode, manifest)
        case.mkdir(mode=0o700)
        home = case / "home"
        home.mkdir(mode=0o700)
        env = {"HOME": str(home), "PATH": str(ROOT / ".venv/bin") + os.pathsep + str(ROOT) + ":/usr/bin:/bin",
          "SHELL": "/bin/sh", "TERM": "xterm-256color", "LANG": "C.UTF-8", "PYTHONUTF8": "1",
          "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_DATE": "2020-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z"}
        for name, relative in (("XDG_CONFIG_HOME", ".config"), ("XDG_DATA_HOME", ".local/share"),
                               ("XDG_STATE_HOME", ".local/state"), ("XDG_CACHE_HOME", ".cache"), ("TMPDIR", "tmp")):
          destination = home / relative
          destination.mkdir(parents=True, mode=0o700)
          env[name] = str(destination)
        config = home / ".config/herdr"
        config.mkdir(mode=0o700)
        config_path = config / "config.toml"
        config_path.write_bytes((ROOT / "terminals/herdr/config.toml").read_bytes())
        config_path.chmod(0o600)
        if workload["id"] == "clients-size":
          assert_default_client_geometry(config_path)
        if bytes_digest(config_path) != report["inputs"]["config_digest"]:
          raise BenchError(2, "actual_config_identity_mismatch")
        session = benchmark_session(manifest["isolation"]["session_prefix"])
        env["HERDR_SESSION"] = session
        os.environ.clear()
        os.environ.update(env)
        client = None
        clients = []
        owned = []
        failure_phase = "socket-proof"
        try:
          if prepared.get("isolation_mode") == "offline-sockets":
            record_socket_filter_proof(report, prepared, workload["id"], mode, batch)
          failure_phase = "cpuacct-members"
          if groups is not None:
            existing_members = groups.members()
            if any(existing_members[role] for role in ("server", "client", "producer")):
              raise BenchError(4, "cpuacct_previous_case_members_remain")
          failure_phase = "discover"
          if discover(binary, session, Deadline()) is not None:
            raise BenchError(4, "existing_server_refused")
          if not config_path.is_file():
            raise BenchError(2, "native_config_file_required")
          failure_phase = "version"
          version = record([binary, "--version"], "native-client-version", env).stdout.decode("utf-8").strip()
          if version != "herdr " + report["subject_identity"]["client_version"]:
            raise BenchError(2, "actual_client_version_mismatch")
          failure_phase = "case-runtime"
          report["coverage"]["client_version_verified"] = True
          record([binary, "config", "check"], "native-config-check", {**env, "HERDR_CONFIG_PATH": str(config_path)})
          verify_schema(binary, Deadline())
          server_begin = time.monotonic_ns()
          with groups.spawn("server") if groups is not None else nullcontext():
            server = start_headless(binary, session, Deadline(), ROOT)
            spawns.append([server, "native-server", [binary, "--session", session, "server"], server_begin, False])
          deadline = Deadline()
          info = None
          while info is None:
            pump_owned_ptys(clients, deadline.remaining(0.05))
            info = discover(binary, session, deadline)
          client = HerdrClient(info["socket_path"], Deadline())
          pong = client.request("ping", {})
          if pong["version"] != report["subject_identity"]["server_version"]:
            raise BenchError(2, "running_server_identity_mismatch")
          # 所有 public CLI API 只连固定 procfd；FD 显式传递给自有子进程。
          api_env = {**env, "HERDR_SOCKET_PATH": client.pinned_address}
          try:
            manifests_reply = json.loads(record([binary, "server", "agent-manifests", "--json"], "native-agent-manifests", api_env, pass_fds=(client.pinned_fd,)).stdout)
            status_text = record([binary, "integration", "status"], "native-integration-status", api_env, pass_fds=(client.pinned_fd,)).stdout.decode("utf-8")
            rules, integrations = origin_fingerprints(manifests_reply, status_text, report["subject_identity"]["asset_digest"], bytes_digest(config_path))
            inputs = report["inputs"]
            verified = (inputs.get("rules_identity_kind") == rules["kind"] and inputs.get("integration_identity_kind") == integrations["kind"]
              and inputs["rules_digest"] == hashlib.sha256(canonical(rules)).hexdigest()
              and inputs["integration_digest"] == hashlib.sha256(canonical(integrations)).hexdigest())
            receipt = {"manifests_reply": manifests_reply, "integration_status": status_text, "rules": rules, "integrations": integrations,
              "subject_digest": digest(report["subject_identity"])}
            name = uuid.uuid4().hex + ".json"
            _private_value(prepared["private"] / name, receipt)
            report["origin_receipts"].append({"evidence_ref": name, "execution_digest": bytes_digest(prepared["private"] / name),
              "rules_digest": hashlib.sha256(canonical(rules)).hexdigest(), "integration_digest": hashlib.sha256(canonical(integrations)).hexdigest(),
              "rules_identity_kind": rules["kind"], "integration_identity_kind": integrations["kind"]})
            report["coverage"]["effective_inputs_verified"] = verified
            report["evidence"].append({"id": "effective-origin-identity", "required": True, "status": "pass" if verified else "unverified",
              "evidence_ref": name, "reason": None if verified else "declared_inputs_are_not_matching_origin_fingerprints"})
          except (BenchError, ValueError, UnicodeError):
            report["evidence"].append({"id": "effective-origin-identity", "required": True, "status": "unverified", "evidence_ref": None,
              "reason": "effective_origin_not_fully_bundled_and_disabled"})
          original_panes = client.request("pane.list", {})["panes"]
          control = case / "control"
          control.mkdir(mode=0o700)
          checkouts = []
          checkout_digests = {}
          pane_checkouts = {}
          count = 9 if workload["id"] == "projects-27" else 1
          for index in range(count):
            checkout = case / ("project-" + str(index // 3)) / ("checkout-" + str(index))
            checkout.mkdir(parents=True, mode=0o700)
            if workload["id"] == "projects-27" and index % 3:
              primary = checkouts[index - index % 3]
              record(["git", "-C", str(primary), "worktree", "add", "--detach", str(checkout), "HEAD"], "git-worktree", env)
            else:
              record(["git", "init", str(checkout)], "git-init", env)
              (checkout / "fixture.txt").write_text("synthetic fixture v1\n")
              record(["git", "-C", str(checkout), "add", "fixture.txt"], "git-add", env)
              record(["git", "-C", str(checkout), "-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "Synthetic fixture"], "git-commit", env)
            anchor = {"version": 1, "run_id": run_id, "mode": mode, "seed": manifest["seed"], "control_dir": str(control)}
            if groups is not None:
              anchor["cpuacct_receipt"] = str(prepared["cpuacct_receipt"])
            anchor["config_digest"] = hashlib.sha256(canonical(anchor)).hexdigest()
            _private_value(checkout / ".rotom-bench-v1.json", anchor)
            checkouts.append(checkout)
            checkout_digests[str(checkout)] = anchor["config_digest"]
          local = case / "local.toml"
          local.write_text('schema_version = 1\n[machine]\nid = "synthetic-bench"\neditor = ' + json.dumps(str(producer_source)) + '\n[machine.work]\nherdr_binary = ' + json.dumps(binary) + '\nsession = ' + json.dumps(session) + '\n')
          local.chmod(0o600)
          settings = read_settings(local=local)
          workspaces = []
          for checkout in checkouts:
            _renew(client)
            with operation_lock(client.deadline):
              ws = enter_project(client, checkout)
            workspaces.append(ws)
            caller = next(p for p in client.request("pane.list", {"workspace_id": ws["workspace_id"]})["panes"])
            initial = caller
            copies = 3 if count == 9 else workload["terminals"]
            for _ in range(copies):
              _renew(client)
              with operation_lock(client.deadline):
                pane = open_role(client, settings, "edit", new=True, caller_id=caller["pane_id"])
              owned.append(pane)
              pane_checkouts[pane["pane_id"]] = checkout
              caller = pane
            original_panes.append(initial)
          expected = [p["pane_id"] for p in owned]
          _private_value(control / "expected.json", {"run_id": run_id, "panes": expected})
          ready = []
          end = time.monotonic() + 300
          while len(ready) != len(expected):
            found = list(control.glob("*.ready.json"))
            ready = [read_json(path) for path in found]
            if any(r.get("run_id") != run_id or r.get("pane_id") not in expected for r in ready) or len({r["pane_id"] for r in ready}) != len(ready):
              raise BenchError(4, "producer_identity_conflict")
            if time.monotonic() > end:
              raise BenchError(5, "producer_ready_timeout")
            pump_owned_ptys(clients, 0.02)
          if len({row["pid"] for row in ready}) != len(ready):
            raise BenchError(4, "producer_pid_identity_conflict")
          producer_identities = []
          for pane in owned:
            row = next(r for r in ready if r["pane_id"] == pane["pane_id"])
            process_before = _known_producer_identity(row["pid"])
            result = record([binary, "pane", "process-info", "--pane", pane["pane_id"]], "record-process-identity", api_env, pass_fds=(client.pinned_fd,))
            native = json.loads(result.stdout)["result"]["process_info"]
            checkout = pane_checkouts[pane["pane_id"]]
            producer_identities.append(verify_producer_ready(row, pane, checkout, checkout_digests[str(checkout)], native, process_before))
          identity_name = uuid.uuid4().hex + ".json"
          _private_value(prepared["private"] / identity_name, {"method": "fixed-producer-identity-v1",
            "run_id": run_id, "subject_digest": digest(report["subject_identity"]), "workload": workload["id"], "mode": mode,
            "batch": batch, "producers": producer_identities})
          report["evidence"].append({"id": workload["id"] + "-producer-identity-batch-" + str(batch) + "-" + mode,
            "required": True, "status": "pass", "evidence_ref": identity_name, "reason": None})
          def close_pane(pane):
            _renew(client)
            live = client.request("pane.get", {"pane_id": pane["pane_id"]})["pane"]
            if any(live[key] != pane[key] for key in ("pane_id", "terminal_id", "workspace_id")):
              raise BenchError(4, "cleanup_ownership_changed")
            record([binary, "pane", "close", pane["pane_id"]], "owned-pane-close", api_env, pass_fds=(client.pinned_fd,))
          for pane in original_panes:
            close_pane(pane)
          def attach(cols, rows):
            attach_interactive(binary, session, env, client, discover, clients, spawns, cols, rows, groups,
              ready_run_id=run_id if mode == "record" else None)
          def detach_client(process, master):
            try:
              detach_owned_client(process, master, pump=lambda: pump_owned_ptys(clients, 0.005))
            except GeometryError as error:
              raise BenchError(5, error.reason) from None
            os.close(master)
            clients.remove((process, master))
          def read_layout(pane_id):
            result = record([binary, "pane", "layout", "--pane", pane_id], "native-pane-layout", api_env, pass_fds=(client.pinned_fd,))
            return json.loads(result.stdout)["result"]
          def probe_client(process, master, pane, cols, rows, phase):
            _renew(client)
            live = client.request("pane.get", {"pane_id": pane["pane_id"]})["pane"]
            if mode != "record" or any(live[key] != pane[key] for key in ("pane_id", "terminal_id", "workspace_id")):
              raise GeometryError("record_target_identity_changed")
            return probe_record_client(process, master, run_id=run_id, pane_id=pane["pane_id"], control_dir=control,
              cols=cols, rows=rows, layout=lambda: read_layout(pane["pane_id"]),
              pump=lambda: pump_owned_ptys(clients, 0.005), phase=phase)
          attach(120, 40)
          if workload["id"] == "clients-size":
            attach(80, 24)
          pump_owned_ptys(clients)
          warmup = time.monotonic_ns() + 2_000_000_000
          _private_value(control / "warmup.json", {"run_id": run_id, "phase": "warmup", "start_ns": warmup})
          _sleep_until(warmup + 60_000_000_000, clients=clients)
          if workload["id"] == "detached-30":
            for process, master in list(clients):
              detach_client(process, master)
            clients.clear()
          sampler = ProcSampler(server.pid, [r["pid"] for r in ready], [p.pid for p, fd in clients],
            group_members=groups.members if groups is not None else None)
          measure = time.monotonic_ns() + 2_000_000_000
          _private_value(control / "measure.json", {"run_id": run_id, "phase": "measure", "start_ns": measure})
          cpu_members_before = None
          if groups is not None:
            _sleep_until(measure - 100_000_000, clients=clients)
            cpu_members_before = groups.members()
          _sleep_until(measure, clients=clients)
          cpu_snapshots = [_cpu_snapshot(groups, server.pid)] if groups is not None else []
          geometry = {"method": "fixed-record-geometry-v1", "subject_digest": digest(report["subject_identity"]),
            "run_id": run_id, "workload": workload["id"], "batch": batch, "target_start_ns": measure,
            "target_end_ns": measure + 300_000_000_000, "frames": []}
          geometry_failed = False
          for tick in range(300):
            sampler.sample()
            if workload["id"] == "clients-size" and tick % 10 == 0 and not geometry_failed:
              pane = owned[(tick // 10) % len(owned)]
              def focus_geometry(pane):
                _renew(client)
                client.request("workspace.focus", {"workspace_id": pane["workspace_id"]})
                client.request("tab.focus", {"tab_id": pane["tab_id"]})
                focused = client.request("pane.focus", {"pane_id": pane["pane_id"]})["pane"]
                if any(focused[key] != pane[key] for key in ("pane_id", "terminal_id", "workspace_id", "tab_id")):
                  raise GeometryError("focused_pane_changed")
              def resize_geometry(process, master, cols, rows):
                resize_owned_client(process, master, cols, rows)
              def settle_geometry():
                # 0.9.5 的尺寸轮询为100ms；等待事件处理仍包含在本轮固定窗口内。
                _sleep_until(time.monotonic_ns() + 250_000_000, clients=clients)
              try:
                collect_geometry_round(geometry, tick // 10, clients, pane, focus_geometry, resize_geometry, probe_client, settle_geometry)
              except GeometryError:
                geometry_failed = True
            _sleep_until(measure + (tick + 1) * 1_000_000_000, clients=clients)
            if groups is not None:
              cpu_snapshots.append(_cpu_snapshot(groups, server.pid if tick == 299 else None))
          cpu_members_after = groups.members() if groups is not None else None
          if sampler.lost:
            report["invalid_reasons"].append("rss_fd_process_membership_unproven")
          for pane, phase in [(pane, phase) for pane in owned for phase in ("warmup", "measure")]:
            path = control / (pane["pane_id"] + "." + phase + ".json")
            receipt_deadline = time.monotonic() + 5
            while not path.exists() and time.monotonic() < receipt_deadline:
              pump_owned_ptys(clients, 0.01)
            if not path.exists():
              report["invalid_reasons"].append("producer_count_missing")
              continue
            value = read_json(path)
            if value.get("run_id") != run_id or value.get("pane_id") != pane["pane_id"]:
              raise BenchError(4, "producer_count_identity_changed")
            report["producer"].append({"workload": workload["id"], "batch": batch, "pane_label": "producer-" + str(expected.index(pane["pane_id"])),
              **{key: value[key] for key in ("mode", "phase", "start_ns", "end_ns", "lines", "bytes", "cpu_seconds", "backpressure_seconds")}})
          if workload["id"] == "clients-size":
            geometry_passed = not geometry_failed and validate_client_original(manifest, report, geometry, "geometry", batch)
            save_client_proof(report, prepared["private"], geometry, "geometry", geometry_passed)
          cpu_values = {**sampler.cpu, "server_group": sampler.cpu["server"] + sampler.cpu["helpers"]}
          cpu_reason = "procfs_short_lived_cpu_unproven"
          cpu_samples = {}
          if groups is not None:
            member_args = (server.pid, ready, [process.pid for process, master in clients], groups.receipt_digest)
            members_verified = (_cpu_members_match(cpu_members_before, *member_args) and
              _cpu_members_match(cpu_members_after, *member_args, previous=cpu_members_before))
            members_verified = members_verified and _server_cpu_membership(cpu_snapshots, cpu_members_before, cpu_members_after, server.pid)
            cpu_values, cpu_reason = cpu_window_values(cpu_snapshots[0], cpu_snapshots[-1], measure, members_verified=members_verified)
            breakdown, _ = server_cpu_breakdown(cpu_values["server_group"], cpu_snapshots[0]["server_main"], cpu_snapshots[-1]["server_main"])
            cpu_values.update(breakdown)
            for previous, current in zip(cpu_snapshots, cpu_snapshots[1:]):
              deltas, _ = cpu_window_values(previous, current, previous["read_begin_ns"], members_verified=True)
              for group, value in deltas.items():
                cpu_samples.setdefault(group, []).append(value)
            raw = {"method": "cpuacct-v1", "completeness_scope": "server-group-descendants", "workload": workload["id"], "mode": mode,
              "batch": batch, "subject_digest": digest(report["subject_identity"]), "delegation": prepared["cpuacct_original"],
              "delegation_digest": groups.receipt_digest, "module_digest": bytes_digest(Path(__file__).with_name("cpuacct.py")),
              "target_start_ns": measure, "target_end_ns": measure + 300_000_000_000, "tolerance_ns": CPU_WINDOW_TOLERANCE_NS,
              "snapshots": cpu_snapshots, "members_before": cpu_members_before, "members_after": cpu_members_after,
              "server_pid": server.pid, "driver_pid": os.getpid(), "client_pids": [process.pid for process, master in clients], "ready": ready}
            name = uuid.uuid4().hex + ".json"
            _private_value(prepared["private"] / name, raw)
            report["cpu_windows"].append({"workload": workload["id"], "mode": mode, "batch": batch, "method": "cpuacct-v1",
              "completeness_scope": "server-group-descendants", "complete": cpu_reason is None, "reason": cpu_reason,
              "source_digest": groups.receipt_digest, "evidence_ref": name, "execution_digest": bytes_digest(prepared["private"] / name)})
            if cpu_reason:
              report["invalid_reasons"].append(cpu_reason)
          for group, cpu in cpu_values.items():
            if group == "driver":
              continue
            reason = None if cpu is not None else "server_tgid_tick_precision_or_identity_unproven"
            samples = cpu_samples.get(group, [])
            emit(workload["id"], batch, "cpu.core_seconds", group, "core-seconds", cpu, len(samples) if samples else (2 if groups is not None else 300) if cpu is not None else 0, samples, reason)
            cpu_wall_seconds = ((cpu_snapshots[-1]["read_begin_ns"] + cpu_snapshots[-1]["read_end_ns"]) -
                (cpu_snapshots[0]["read_begin_ns"] + cpu_snapshots[0]["read_end_ns"])) / 2_000_000_000 if groups is not None else 300
            emit(workload["id"], batch, "cpu.cores", group, "cores", None if cpu is None else cpu / cpu_wall_seconds,
              len(samples) if samples else (2 if groups is not None else 300) if cpu is not None else 0, samples, reason)
            cost = output_cpu_cost(cpu, report["producer"], workload["id"], mode, batch,
              interval_count=len(cpu_snapshots) - 1 if groups is not None else len(sampler.fds), source_reason=reason)
            emit(workload["id"], batch, "cpu.per_mib", group, "core-seconds/MiB", **cost)
          for group, values in sampler.rss.items():
            summary = statistics(values)
            for key in ("median", "p95"):
              emit(workload["id"], batch, "rss." + key, group, "bytes", summary[key], len(values), values)
            emit(workload["id"], batch, "rss.peak", group, "bytes", max(values), len(values), values)
          emit(workload["id"], batch, "fd.count", "all", "count", max(sampler.fds), len(sampler.fds), sampler.fds)
          emit(workload["id"], batch, "processes.count", "all", "count", max(sampler.processes), len(sampler.processes), sampler.processes)
          emit(workload["id"], batch, "objects.count", "all", "count", len(owned), 1)
          # 暖路径端到端包含 CLI/runner/公开确认成本；复用不发送计时输入。
          cli_env = {**env, "HERDR_PANE_ID": owned[0]["pane_id"], "HERDR_SOCKET_PATH": client.socket_path}
          for metric, argv in (("latency.warm_enter.p95", [str(ROOT / "work"), "--local", str(local), "enter", str(checkouts[0])]),
                               ("latency.warm_reuse.p95", [str(ROOT / "work"), "--local", str(local), "open", "edit"])):
            if not measure_applies(manifest, metric, workload["id"]):
              continue
            values = []
            for _ in range(manifest["sampling"]["warm_samples_per_batch"]):
              pump_owned_ptys(clients)
              _renew(client)
              begin = time.monotonic_ns()
              record(argv, metric, cli_env)
              focused = client.request("workspace.get", {"workspace_id": owned[0]["workspace_id"]})["workspace"]
              if not focused["focused"]:
                raise BenchError(4, "warm_operation_focus_not_confirmed")
              if metric == "latency.warm_reuse.p95" and not client.request("pane.get", {"pane_id": owned[0]["pane_id"]})["pane"]["focused"]:
                raise BenchError(4, "warm_reuse_pane_focus_not_confirmed")
              values.append((time.monotonic_ns() - begin) / 1_000_000)
            emit(workload["id"], batch, metric, "all", "ms", statistics(values)["p95"], len(values), values)
          if workload["id"] == "projects-27":
            from concurrent.futures import ThreadPoolExecutor
            baseline_ids = sorted(p["pane_id"] for p in owned)
            for _ in range(100):
              _renew(client)
              with operation_lock(client.deadline):
                enter_project(client, checkouts[0])
                open_role(client, settings, "edit", caller_id=owned[0]["pane_id"])
            for concurrency in (2, 10):
              _renew(client)
              def repeat_project(number):
                with operation_lock(client.deadline):
                  return enter_project(client, checkouts[number % len(checkouts)])["workspace_id"]
              with ThreadPoolExecutor(max_workers=concurrency) as pool:
                list(pool.map(repeat_project, range(concurrency)))
            _renew(client)
            actual_ids = sorted(p["pane_id"] for p in client.request("pane.list", {})["panes"])
            if actual_ids != baseline_ids or list(control.glob("*.input-*.json")):
              report["correctness"].append({"id": "project-repeat-concurrency-zero-extra-input", "status": "failure", "evidence_ref": "native-pane-set-and-record-fixture", "reason": "unexpected_native_pane_or_input"})
            else:
              report["correctness"].append({"id": "project-repeat-concurrency-zero-extra-input", "status": "pass", "evidence_ref": "native-pane-set-and-record-fixture", "reason": None})
          if workload["id"] == "clients-size":
            cold_values = []
            for cold_index in range(30):
              cold_session = benchmark_session("bench-cold")
              os.environ["HERDR_SESSION"] = cold_session
              begin = time.monotonic_ns()
              with groups.spawn("server") if groups is not None else nullcontext():
                cold_server = start_headless(binary, cold_session, Deadline(), ROOT)
                spawns.append([cold_server, "native-server", [binary, "--session", cold_session, "server"], begin, False])
              deadline = Deadline()
              cold_info = None
              while cold_info is None:
                pump_owned_ptys(clients, deadline.remaining(0.02))
                cold_info = discover(binary, cold_session, deadline)
              with HerdrClient(cold_info["socket_path"], deadline) as cold_client:
                cold_client.request("ping", {})
                cold_values.append((time.monotonic_ns() - begin) / 1_000_000)
                # 全新冷启动server没有业务任务；完整核对其初始对象后，仅停止本轮server。
                cold_panes = cold_client.request("pane.list", {})["panes"]
                again = cold_client.request("pane.list", {})["panes"]
                if [(p["pane_id"], p["terminal_id"]) for p in cold_panes] != [(p["pane_id"], p["terminal_id"]) for p in again]:
                  raise BenchError(4, "cold_server_ownership_changed")
                record([binary, "server", "stop"], "owned-cold-server-stop", {**env, "HERDR_SESSION": cold_session, "HERDR_SOCKET_PATH": cold_client.pinned_address}, pass_fds=(cold_client.pinned_fd,))
              cold_server.wait(timeout=10)
            os.environ["HERDR_SESSION"] = session
            emit(workload["id"], batch, "latency.cold.median", "all", "ms", statistics(cold_values, p95=False)["median"], len(cold_values), cold_values)

            # new role 使用独立不可变checkout/control，不向已有producer的注册表加实例。
            role_values = []
            for sample in range(manifest["sampling"]["warm_samples_per_batch"]):
              launch_root = case / ("role-sample-" + str(sample))
              launch_root.mkdir(mode=0o700)
              record(["git", "-C", str(checkouts[0]), "worktree", "add", "--detach", str(launch_root), "HEAD"], "role-worktree", env)
              launch_control = case / ("role-control-" + str(sample))
              launch_control.mkdir(mode=0o700)
              anchor = {"version": 1, "run_id": run_id, "mode": "record", "seed": manifest["seed"], "control_dir": str(launch_control)}
              if groups is not None:
                anchor["cpuacct_receipt"] = str(prepared["cpuacct_receipt"])
              anchor["config_digest"] = hashlib.sha256(canonical(anchor)).hexdigest()
              _private_value(launch_root / ".rotom-bench-v1.json", anchor)
              _renew(client)
              with operation_lock(client.deadline):
                ws = enter_project(client, launch_root)
              caller = client.request("pane.list", {"workspace_id": ws["workspace_id"]})["panes"][0]
              pump_owned_ptys(clients)
              _renew(client)
              begin = time.monotonic_ns()
              record([str(ROOT / "work"), "--local", str(local), "open", "edit", "--new"], "new-role", {**env, "HERDR_PANE_ID": caller["pane_id"], "HERDR_SOCKET_PATH": client.socket_path})
              after_launch = client.request("pane.list", {"workspace_id": ws["workspace_id"]})["panes"]
              created = [p for p in after_launch if p["pane_id"] != caller["pane_id"]]
              if len(created) != 1 or created[0].get("tokens", {}).get("rw_phase") != "accepted":
                raise BenchError(4, "new_role_membership_unconfirmed")
              launched = created[0]
              _private_value(launch_control / "expected.json", {"run_id": run_id, "panes": [launched["pane_id"]]})
              timeout = time.monotonic() + 30
              ready_path = launch_control / (launched["pane_id"] + ".ready.json")
              while not ready_path.exists():
                if time.monotonic() > timeout:
                  raise BenchError(5, "new_role_producer_ready_timeout")
                pump_owned_ptys(clients, 0.01)
              value = read_json(ready_path)
              if value["run_id"] != run_id or value["pane_id"] != launched["pane_id"]:
                raise BenchError(4, "new_role_producer_identity_changed")
              role_values.append((time.monotonic_ns() - begin) / 1_000_000)
              close_pane(launched)
              close_pane(caller)
            emit(workload["id"], batch, "latency.new_role.p95", "all", "ms", statistics(role_values)["p95"], len(role_values), role_values)

            attach_values = []
            attach_proof = {"method": "fixed-record-attach-v1", "subject_digest": digest(report["subject_identity"]),
              "run_id": run_id, "workload": workload["id"], "batch": batch, "frames": []}
            _renew(client)
            client.request("pane.focus", {"pane_id": owned[0]["pane_id"]})
            for process, master in list(clients):
              detach_client(process, master)
            clients.clear()
            for sample in range(manifest["sampling"]["warm_samples_per_batch"]):
              _renew(client)
              live = client.request("pane.get", {"pane_id": owned[0]["pane_id"]})["pane"]
              if live["terminal_id"] != owned[0]["terminal_id"] or mode != "record":
                raise BenchError(4, "attach_record_target_changed")
              process_result = record([binary, "pane", "process-info", "--pane", owned[0]["pane_id"]], "record-process-identity", api_env, pass_fds=(client.pinned_fd,))
              process_info = json.loads(process_result.stdout)["result"]["process_info"]
              expected_pid = next(r["pid"] for r in ready if r["pane_id"] == owned[0]["pane_id"])
              current_process = sampler.snapshot().get(expected_pid)
              if (process_info.get("shell_pid") != expected_pid or current_process is None or
                  sampler.identities.get(expected_pid) != (expected_pid, current_process["start"])):
                raise BenchError(4, "record_foreground_process_identity_unproven")
              begin = time.monotonic_ns()
              attach(120, 40)
              process, master = clients[-1]
              pump_owned_ptys(clients)
              probe_failed = False
              try:
                frame = probe_client(process, master, owned[0], 120, 40, "record")
                attach_end = time.monotonic_ns()
                attach_proof["frames"].append({"attach_start_ns": begin, "attach_end_ns": attach_end, "frame": frame})
                attach_values.append((attach_end - begin) / 1_000_000)
              except GeometryError:
                probe_failed = True
              if probe_failed:
                os.close(master)
                process.wait(timeout=10)
                clients.pop()
                break
              detach_client(process, master)
            if len(attach_values) >= 200:
              emit(workload["id"], batch, "latency.attach.p95", "all", "ms", statistics(attach_values)["p95"], len(attach_values), attach_values)
            attach_passed = validate_client_original(manifest, report, attach_proof, "ready", batch)
            save_client_proof(report, prepared["private"], attach_proof, "ready", attach_passed)
          if workload["id"] == "churn-leak":
            checkpoints = []
            checkpoint_times = []
            process_checkpoints = []
            fd_checkpoints = []
            for iteration in range(300):
              _renew(client)
              created = client.request("tab.create", {"workspace_id": owned[0]["workspace_id"], "cwd": str(checkouts[0]), "focus": False})["root_pane"]
              close_pane(created)
              attach(120, 40)
              process, master = clients[-1]
              pump_owned_ptys(clients)
              detach_client(process, master)
              if (iteration + 1) % 50 == 0:
                _sleep_until(time.monotonic_ns() + 60_000_000_000, sampler, clients)
                _renew(client)
                panes_now = client.request("pane.list", {})["panes"]
                if sorted(p["pane_id"] for p in panes_now) != sorted(p["pane_id"] for p in owned):
                  report["correctness"].append({"id": "churn-baseline-pane-set", "status": "failure", "evidence_ref": "native-current-pane-ids", "reason": "residual_or_missing_pane"})
                checkpoints.append(stats.median(sampler.rss["server_group"][-60:]))
                checkpoint_times.append(time.monotonic())
                process_checkpoints.append(sampler.processes[-1])
                fd_checkpoints.append(sampler.fds[-1])
            _sleep_until(time.monotonic_ns() + 1_800_000_000_000, sampler, clients)
            sampler.sample()
            _renew(client)
            tail_panes = client.request("pane.list", {})["panes"]
            def pane_identity(pane):
              return tuple(pane[key] for key in ("pane_id", "terminal_id", "workspace_id"))
            expected_panes = sorted(pane_identity(pane) for pane in owned)
            actual_panes = sorted(pane_identity(pane) for pane in tail_panes)
            report["correctness"].append({"id": "churn-tail-owned-membership-batch-" + str(batch),
              "status": "pass" if actual_panes == expected_panes else "failure", "evidence_ref": "native-tail-pane-identities",
              "reason": None if actual_panes == expected_panes else "native_tail_pane_membership_changed"})
            checkpoints.append(stats.median(sampler.rss["server_group"][-60:]))
            checkpoint_times.append(time.monotonic())
            process_checkpoints.append(sampler.processes[-1])
            fd_checkpoints.append(sampler.fds[-1])
            tail_original = {"method": "fixed-churn-tail-v1", "subject_digest": digest(report["subject_identity"]),
              "run_id": run_id, "batch": batch, "times": checkpoint_times, "rss": checkpoints, "processes": process_checkpoints,
              "fds": fd_checkpoints, "expected_panes": expected_panes, "actual_panes": actual_panes}
            tail_name = "churn-proof-" + hashlib.sha256(canonical(tail_original) + b"\n").hexdigest() + ".json"
            _private_value(prepared["private"] / tail_name, tail_original)
            report["evidence"].append({"id": "churn-tail-batch-" + str(batch), "required": True,
              "status": "pass" if actual_panes == expected_panes else "failure", "evidence_ref": tail_name,
              "reason": None if actual_panes == expected_panes else "native_tail_pane_membership_changed"})
            if len(checkpoints) == 7:
              slope = stats.linear_regression([t - checkpoint_times[0] for t in checkpoint_times], checkpoints).slope
              for item in measurements:
                if item["workload"] == workload["id"] and item["batch"] == batch and item["mode"] == mode:
                  if item["metric"] in {"processes.count", "fd.count"}:
                    points = process_checkpoints if item["metric"] == "processes.count" else fd_checkpoints
                    item.update(value=max(points), n=len(points), samples=points)
              emit(workload["id"], batch, "rss.slope", "server_group", "bytes/second", max(0, slope), len(checkpoints), checkpoints)
          if workload["id"] == "detached-30":
            attach(120, 40)
            process, master = clients[-1]
            pump_owned_ptys(clients)
            current = sampler.snapshot()
            stable = all(pid in current and sampler.identities.get(pid) == (pid, current[pid]["start"]) for pid in [r["pid"] for r in ready])
            report["correctness"].append({"id": "disconnect", "status": "pass" if stable else "failure", "evidence_ref": "producer-pid-starttime-after-300-seconds", "reason": None if stable else "producer_identity_lost"})
          if sampler.lost:
            report["invalid_reasons"].append("rss_fd_process_membership_unproven")
          for process, master in list(clients):
            detach_client(process, master)
          clients.clear()
          stop_owned_server(binary, session, env, client, discover, owned, record)
          report["correctness"].append({"id": workload["id"] + "-producer-membership-batch-" + str(batch), "status": "pass", "evidence_ref": "native-api-and-producer-barrier", "reason": None})
          server.wait(timeout=10)
          if groups is not None:
            groups.wait_case_empty()
          save_spawns()
        except (TermcfgError, subprocess.SubprocessError, BenchError, CpuacctError, OSError, KeyError, ValueError) as error:
          failure_exit = error.code if isinstance(error, (TermcfgError, BenchError)) else 6 if isinstance(error, OSError) else 5
          try:
            failure_ref = _record_native_failure(prepared["private"], workload["id"], mode, batch,
              failure_phase, error, failure_exit)
          except (OSError, BenchError):
            # 诊断落盘失败不覆盖原操作的退出码或触发原生清理/重试。
            failure_ref = None
          if isinstance(error, BenchError) and error.reason == "synthetic_command_failed":
            report["correctness"].append({"id": "native-command-exit", "status": "failure", "evidence_ref": "private-execution-record", "reason": "unexpected_exit_code"})
            report.update(decision="failure", task_status="失败待决策")
          save_spawns()
          report["operation_exit_code"] = failure_exit
          report["invalid_reasons"].append("native_operation_incomplete_objects_preserved")
          report["evidence"].append({"id": workload["id"] + "-incomplete-batch-" + str(batch), "required": True, "status": "unverified", "evidence_ref": failure_ref, "reason": "native_operation_failed_or_unknown_no_replay"})
          # 不确定结果不重试操作、关闭对象或停止server。
          report["isolation"]["sentinels_unchanged"] = all(bytes_digest(path) == expected for path, expected in prepared["sentinels"])
          report["invalid_reasons"] = sorted(set(report["invalid_reasons"]))
          return sealed(report)
        finally:
          if client:
            client.close()
          for process, master in clients:
            try:
              os.close(master)
            except OSError:
              pass
          os.environ.clear()
          os.environ.update(original_environment)
    report["batches"].append({"batch": batch, "order": [subject], "warmup_seconds": 60, "measure_seconds": 300,
      "start_ns": batch_start, "end_ns": time.monotonic_ns(), "identity_digest": digest(report["subject_identity"])})
  report["isolation"]["sentinels_unchanged"] = all(bytes_digest(path) == expected for path, expected in prepared["sentinels"])
  report["invalid_reasons"] = sorted(set(report["invalid_reasons"]))
  report["coverage"]["cpu_complete"] = cpu_coverage_proven(manifest, report)
  if report["coverage"]["cpu_complete"]:
    report["coverage"]["reason"] = None
  if len(batch_numbers) == 3 and case_filter is None:
    check_producers(report, manifest)
  else:
    check_producers(report)
  update_client_coverage(manifest, report)
  return sealed(report)


def paired_schedule(manifest):
  import random
  randomizer = random.Random(manifest["sampling"]["order_seed"])
  cases = [(w["id"], mode) for w in manifest["workloads"] for mode in w["modes"]]
  result = []
  direction = randomizer.randrange(2)
  for batch in (1, 2, 3):
    current = list(cases)
    randomizer.shuffle(current)
    for workload, mode in current:
      order = ["baseline", "candidate"] if direction == 0 else ["candidate", "baseline"]
      result.append({"batch": batch, "workload": workload, "mode": mode, "planned_order": order})
      direction = 1 - direction
  return result


def authorization_binding(manifest, authorization):
  import re
  if not isinstance(authorization, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", authorization) or authorization != manifest["authorization_ref"]:
    raise BenchError(2, "authorization_reference_mismatch_or_invalid_label")


def native_run(manifest, policy, subject, scope, manifest_dir, authorization, *, calibrating=False, allow_incomplete_cpu=False, selected_case=None, selected_batch=1, offline_sockets=False, cpuacct_delegation=None):
  authorization_binding(manifest, authorization)
  options = {"calibrating": calibrating, "allow_incomplete_cpu": allow_incomplete_cpu,
    "selected_case": selected_case, "selected_batch": selected_batch, "offline_sockets": offline_sockets}
  if cpuacct_delegation is None:
    return _native_run(manifest, policy, subject, scope, manifest_dir, authorization, **options)
  receipt_path = Path(cpuacct_delegation).absolute()
  with CpuacctGroups(receipt_path) as groups:
    original = read_json(receipt_path)
    if hashlib.sha256(canonical(original)).hexdigest() != groups.receipt_digest:
      raise BenchError(5, "cpuacct_receipt_replaced")
    groups.join_self("driver")
    return _native_run(manifest, policy, subject, scope, manifest_dir, authorization,
      cpuacct_groups=groups, cpuacct_receipt=receipt_path, cpuacct_original=original, **options)


def _native_run(manifest, policy, subject, scope, manifest_dir, authorization, *, calibrating=False, allow_incomplete_cpu=False, selected_case=None, selected_batch=1, offline_sockets=False, cpuacct_groups=None, cpuacct_receipt=None, cpuacct_original=None):
  authorization_binding(manifest, authorization)
  if cpuacct_groups is None and not allow_incomplete_cpu:
    raise BenchError(5, "required_cpu_coverage_unavailable_explicit_incomplete_opt_in_required")
  case_filter = None
  if selected_case is None and selected_batch != 1:
    raise BenchError(2, "batch_selector_requires_partial_case")
  if selected_case is not None:
    candidates = {w["id"] + ":" + mode: (w["id"], mode) for w in manifest["workloads"] for mode in w["modes"]}
    if calibrating or scope != "first-baseline" or selected_case not in candidates or selected_batch not in (1, 2, 3):
      raise BenchError(2, "partial_case_requires_first_baseline_run_and_frozen_case")
    case_filter = candidates[selected_case]
  if case_filter is None and (not policy["frozen_at"] or not policy["approval_ref"]):
    raise BenchError(2, "absolute_policy_must_be_frozen_before_native_measurement")
  subjects = ["baseline", "candidate"] if scope != "first-baseline" and not calibrating else [subject]
  if offline_sockets:
    if cpuacct_groups is None:
      socket_filter_proof()
    else:
      socket_filter_proof(cpuacct_groups)
  prepared = {name: preflight(manifest, name, manifest_dir) for name in subjects}
  if cpuacct_groups is not None:
    for value in prepared.values():
      value.update(cpuacct_groups=cpuacct_groups, cpuacct_receipt=cpuacct_receipt, cpuacct_original=cpuacct_original)
  if offline_sockets:
    for value in prepared.values():
      value["isolation_mode"] = "offline-sockets"
  elif not network_isolated():
    raise BenchError(4, "preexisting_loopback_only_network_namespace_required")
  if case_filter is not None:
    report = _native_measure(manifest, policy, subject, scope, manifest_dir, authorization, prepared[subject], batch_numbers=(selected_batch,), case_filter=case_filter)
    report["invalid_reasons"].append("explicit_partial_measurement")
    if not policy["frozen_at"] or not policy["approval_ref"]:
      report["evidence"].append({"id": "pending-policy-diagnostic", "required": True, "status": "unverified",
        "evidence_ref": None, "reason": "unapproved_policy_partial_diagnostic_cannot_be_promoted_to_baseline"})
    report.update(validity="invalid", reason="explicit_partial_measurement_not_a_baseline")
    return sealed(report)
  if len(subjects) == 1:
    return _native_measure(manifest, policy, subject, scope, manifest_dir, authorization, prepared[subject])
  base = prepared[subject]["root"]
  check_socket_capacity(base / "32-candidate")
  base.mkdir(mode=0o700)
  paired_id = uuid.uuid4().hex
  reports = {name: empty_report(manifest, policy, name, scope) for name in subjects}
  actual_schedule = []
  for number, planned in enumerate(paired_schedule(manifest)):
    actual = {**planned, "actual_order": [], "windows": []}
    for name in planned["planned_order"]:
      selected = {**prepared[name], "root": base / (str(number) + "-" + name)}
      begin = time.monotonic_ns()
      partial = _native_measure(manifest, policy, name, scope, manifest_dir, authorization, selected,
        batch_numbers=(planned["batch"],), case_filter=(planned["workload"], planned["mode"]))
      end = time.monotonic_ns()
      actual["actual_order"].append(name)
      actual["windows"].append({"subject": name, "start_ns": begin, "end_ns": end})
      target = reports[name]
      for key in ("steps", "measurements", "producer", "correctness", "evidence", "origin_receipts", "cpu_windows"):
        target[key].extend(partial[key])
      target["invalid_reasons"] = sorted(set(target["invalid_reasons"] + partial["invalid_reasons"]))
      target["isolation"] = partial["isolation"]
      target["authorization_ref"] = authorization
      target["operation_exit_code"] = partial["operation_exit_code"]
      target["coverage"]["client_ready_proven"] |= partial["coverage"]["client_ready_proven"]
      target["coverage"]["client_version_verified"] |= partial["coverage"]["client_version_verified"]
      target["coverage"]["effective_inputs_verified"] = bool(target["origin_receipts"]) and all(e["status"] == "pass" for e in target["evidence"] if e["id"] == "effective-origin-identity")
      if partial["decision"] == "failure":
        target.update(decision="failure", task_status="失败待决策")
      if partial["operation_exit_code"] or partial["decision"] == "failure":
        actual_schedule.append(actual)
        for value in reports.values():
          value.update(paired_run_id=paired_id, paired_schedule=deepcopy(actual_schedule), reason="paired_measurement_interrupted_evidence_preserved")
          sealed(value)
        return reports[subject], reports["baseline" if subject == "candidate" else "candidate"]
    actual_schedule.append(actual)
  for name, report in reports.items():
    report.update(paired_run_id=paired_id, paired_schedule=deepcopy(actual_schedule), reason="paired_procfs_measurement_has_explicit_coverage_limits")
    for batch in (1, 2, 3):
      windows = [window for row in actual_schedule if row["batch"] == batch for window in row["windows"] if window["subject"] == name]
      report["batches"].append({"batch": batch, "order": ["baseline", "candidate"], "warmup_seconds": 60, "measure_seconds": 300,
        "start_ns": min(w["start_ns"] for w in windows), "end_ns": max(w["end_ns"] for w in windows), "identity_digest": digest(report["subject_identity"])})
    report["coverage"]["cpu_complete"] = cpu_coverage_proven(manifest, report)
    if report["coverage"]["cpu_complete"]:
      report["coverage"]["reason"] = None
    check_producers(report, manifest)
    update_client_coverage(manifest, report)
    sealed(report)
  return reports[subject], reports["baseline" if subject == "candidate" else "candidate"]


def verify_prior_acceptance(manifest, manifest_dir):
  subject = manifest["subjects"]["baseline"]
  if subject is None or not subject.get("acceptance_digest"):
    return False
  reference = subject["acceptance_ref"]
  if Path(reference).name != reference:
    return False
  try:
    accepted = validate_document(read_json(Path(manifest_dir) / reference), "report")
    if accepted["digest"] != subject["acceptance_digest"] or accepted["decision"] != "pass" or accepted["validity"] != "valid":
      return False
    if not accepted["coverage"]["cpu_complete"] or not cpu_coverage_proven(manifest, accepted) or not accepted["isolation"]["private_originals_verified"]:
      return False
    fields = ("release", "tag", "commit", "asset_url", "asset_digest", "client_version", "server_version", "inputs")
    return all(accepted["subject_identity"][field] == subject[field] for field in fields)
  except (OSError, BenchError, KeyError, TypeError):
    return False


def paired_proof(manifest, candidate, baseline):
  if baseline is None:
    return manifest["scope"] == "first-baseline" and candidate["paired_run_id"] is None and not candidate["paired_schedule"]
  if (not candidate["paired_run_id"] or candidate["paired_run_id"] != baseline["paired_run_id"] or
      candidate["paired_schedule"] != baseline["paired_schedule"]):
    return False
  frozen = paired_schedule(manifest)
  actual = candidate["paired_schedule"]
  if len(actual) != len(frozen):
    return False
  previous_end = 0
  for expected, row in zip(frozen, actual):
    if any(row[key] != expected[key] for key in expected) or row["actual_order"] != expected["planned_order"]:
      return False
    if [w["subject"] for w in row["windows"]] != row["actual_order"]:
      return False
    for window in row["windows"]:
      if window["start_ns"] < previous_end or window["end_ns"] <= window["start_ns"]:
        return False
      previous_end = window["end_ns"]
      report = candidate if window["subject"] == "candidate" else baseline
      producers = [p for p in report["producer"] if p["workload"] == row["workload"] and p["mode"] == row["mode"] and p["batch"] == row["batch"]]
      if not producers or any(p["start_ns"] < window["start_ns"] or p["end_ns"] > window["end_ns"] for p in producers):
        return False
  return True


class Parser(argparse.ArgumentParser):
  def error(self, message):
    raise BenchError(2, "invalid_arguments")


def parser():
  root = Parser(description=__doc__)
  commands = root.add_subparsers(dest="command", required=True)
  for name in ("validate", "estimate", "compare", "run", "calibrate"):
    child = commands.add_parser(name)
    child.add_argument("--manifest", required=True)
    child.add_argument("--policy", required=name not in {"validate", "estimate"})
    if name in {"validate", "estimate"}:
      if name == "validate":
        child.add_argument("--report", action="append", default=[])
    elif name == "compare":
      child.add_argument("--candidate", required=True)
      child.add_argument("--baseline")
      child.add_argument("--output", required=True)
    else:
      child.add_argument("--subject", required=True, choices=["baseline", "candidate"])
      child.add_argument("--allow-native", action="store_true", required=True)
      isolation = child.add_mutually_exclusive_group()
      isolation.add_argument("--isolated-netns", action="store_true")
      isolation.add_argument("--offline-sockets", action="store_true")
      child.add_argument("--socket-filter-active", action="store_true", help=argparse.SUPPRESS)
      child.add_argument("--allow-incomplete-cpu", action="store_true")
      child.add_argument("--cpuacct-delegation")
      child.add_argument("--authorization", required=True)
      child.add_argument("--output", required=True)
      if name == "run":
        child.add_argument("--scope", required=True, choices=["first-baseline", "runtime", "full-stack"])
        child.add_argument("--paired-output")
        child.add_argument("--case")
        child.add_argument("--batch", type=int, choices=[1, 2, 3], default=1)
      else:
        child.add_argument("--policy-output", required=True)
  return root


def main(argv=None):
  try:
    args = parser().parse_args(argv)
    manifest_path = Path(args.manifest).absolute()
    manifest = validate_document(read_json(manifest_path), "manifest")
    policy = validate_document(read_json(args.policy), "policy") if args.policy else None
    validate_references(manifest, policy)
    if args.command == "estimate":
      print(json.dumps({**duration_estimate(manifest), "can_establish_baseline": False,
        "required_unavailable": ["complete_user_plus_system_cpu", "native_client_dimensions_evidence"],
        "partial_case_fixed_seconds": 360, "churn_case_fixed_seconds": 2520,
        "reason": "estimates_exclude_operations_setup_and_cleanup_no_native_execution"}))
      return 0
    if args.command == "validate":
      reports = [validate_document(read_json(path), "report") for path in args.report]
      validate_references(manifest, policy, reports)
      print(json.dumps({"valid": True, "decision": "unverified", "task_status": "已完成", "reason": "structure_validity_is_not_native_acceptance"}))
      return 0
    if args.command in {"run", "calibrate"}:
      authorization_binding(manifest, args.authorization)
      if args.socket_filter_active and not args.offline_sockets:
        raise BenchError(2, "socket_filter_marker_requires_explicit_offline_mode")
    if args.command == "run" and bool(args.paired_output) != (args.scope != "first-baseline"):
      raise BenchError(2, "paired_output_required_only_for_upgrade_run")
    outputs = [Path(args.output)] + ([Path(args.policy_output)] if args.command == "calibrate" else []) + ([Path(args.paired_output)] if args.command == "run" and args.paired_output else [])
    if len(set(p.absolute() for p in outputs)) != len(outputs) or any(p.exists() or p.is_symlink() for p in outputs):
      raise BenchError(4, "output_exists_or_aliases")
    if args.command in {"run", "calibrate"}:
      print(json.dumps({"native_preflight": "cpuacct_receipt_pending_validation" if args.cpuacct_delegation else "incomplete_required_cpu", **duration_estimate(manifest),
        "can_establish_baseline": False, "selected_case": getattr(args, "case", None),
        "selected_batch": getattr(args, "batch", None)}), file=sys.stderr)
      if not args.cpuacct_delegation and not args.allow_incomplete_cpu:
        raise BenchError(5, "required_cpu_coverage_unavailable_explicit_incomplete_opt_in_required")
    if args.command in {"run", "calibrate"} and args.offline_sockets:
      if args.socket_filter_active:
        socket_filter_proof()
      else:
        original = list(sys.argv[1:] if argv is None else argv)
        return subprocess.run([sys.executable, str(FIXTURE / "socket_filter_exec.py"), *original],
          stdin=subprocess.DEVNULL, check=False).returncode
    if args.command in {"run", "calibrate"} and args.isolated_netns:
      original = list(sys.argv[1:] if argv is None else argv)
      original.remove("--isolated-netns")
      return subprocess.run([sys.executable, str(FIXTURE / "namespace_exec.py"), *original],
        stdin=subprocess.DEVNULL, check=False).returncode
    if args.command == "compare":
      candidate = validate_document(read_json(args.candidate), "report")
      baseline = validate_document(read_json(args.baseline), "report") if args.baseline else None
      originals = all(verify_originals(manifest, report, manifest_path.parent) for report in [candidate] + ([baseline] if baseline else []))
      report = compare(manifest, policy, candidate, baseline, originals_verified=originals,
        calibration_verified=verify_calibrations(manifest, policy, Path(args.policy).absolute().parent, manifest_path.parent),
        baseline_accepted=verify_prior_acceptance(manifest, manifest_path.parent))
    else:
      scope = args.scope if args.command == "run" else manifest["scope"]
      if scope != manifest["scope"] or (scope == "first-baseline" and args.subject != "candidate"):
        raise BenchError(2, "run_scope_or_subject_mismatch")
      outcome = native_run(manifest, policy, args.subject, scope, manifest_path.parent, args.authorization, calibrating=args.command == "calibrate",
        allow_incomplete_cpu=args.allow_incomplete_cpu, selected_case=getattr(args, "case", None), selected_batch=getattr(args, "batch", 1), offline_sockets=args.offline_sockets, cpuacct_delegation=args.cpuacct_delegation)
      if isinstance(outcome, tuple):
        report, paired = outcome
        validate_document(report, "report")
        validate_document(paired, "report")
        write_new(args.paired_output, paired)
      else:
        report = outcome
      if args.command == "calibrate":
        report["kind"] = "calibration"
        sealed(report)
        proposed = calibrated_policy(policy, report)
        proposed["calibration_refs"][0].update(evidence_ref=Path(args.output).name, policy_ref=Path(args.policy).name)
        sealed(proposed)
        validate_document(report, "report")
        validate_document(proposed, "policy")
        write_new(args.policy_output, proposed)
    validate_document(report, "report")
    write_new(args.output, report)
    print(json.dumps({"report": report["report_id"], "validity": report["validity"], "decision": report["decision"], "task_status": report["task_status"]}, ensure_ascii=False))
    if report["decision"] == "failure":
      return 5
    if report["operation_exit_code"]:
      return report["operation_exit_code"]
    return 0 if report["decision"] == "pass" or report["decision"] == "measured" and report["validity"] == "valid" else 5
  except CpuacctError as error:
    print(json.dumps({"error": error.reason}, ensure_ascii=False), file=sys.stderr)
    return 5
  except BenchError as error:
    print(json.dumps({"error": error.reason}, ensure_ascii=False), file=sys.stderr)
    return error.code
  except OSError:
    print('{"error":"filesystem_failure"}', file=sys.stderr)
    return 6
  except (ValueError, TypeError, KeyError):
    print('{"error":"runner_internal_failure"}', file=sys.stderr)
    return 6


if __name__ == "__main__":
  raise SystemExit(main())
