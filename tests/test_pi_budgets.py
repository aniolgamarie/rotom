"""虚构纯 Pi 样本冻结数值工件；不采集基线、不发布产品预算。"""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from agentcfg.activity import digest
from agentcfg.pi_budgets import freeze_budget
from agentcfg.schema import ConfigError


def observed(*values):
  return [{"status": "observed", "value": str(value)} for value in values]


def inputs(values=("10", "14"), **limits):
  baseline = {"schema_version": 1, "profile": "pure-pi", "platform": "linux-x86_64", "platform_identity": "a" * 64,
    "runtime_identity": "b" * 64, "method_identity": "c" * 64, "checker_identity": "d" * 64, "input_identity": "e" * 64,
    "metrics": {"latency": {"unit": "ms", "samples": observed(*values), "warmup_samples": observed("99999")}}}
  metric = {"unit": "ms", "direction": "upper", "statistic": "median", "min_valid_samples": 2, "max_failed_samples": 0,
    "absolute_delta": "5", "relative_delta": "0.25", "authorized_limit": "100"}
  metric.update(limits)
  tolerances = {"schema_version": 1, "revision": 3, "method_identity": baseline["method_identity"],
    "authorized_limits": {"max_model_calls": 0, "max_cost": "0.00", "currency": "USD"}, "metrics": {"latency": metric}}
  return baseline, tolerances


def test_even_median_selects_hand_computed_strictest_bound_and_excludes_warmup():
  baseline, tolerances = inputs()
  before = deepcopy((baseline, tolerances))
  result = freeze_budget(baseline, tolerances, revision=7)
  assert result["revision"] == 7 and result["tolerances_revision"] == 3
  assert result["metrics"]["latency"]["baseline_stat"] == "12"
  assert result["metrics"]["latency"]["threshold"] == "15"  # min(17,15,100)
  assert result["metrics"]["latency"]["formal"] == {"total": 2, "valid": 2, "failed": 0, "timeout": 0, "missing": 0}
  assert result["metrics"]["latency"]["warmup"] == {"total": 1, "valid": 1, "failed": 0, "timeout": 0, "missing": 0}
  assert result["baseline_digest"] == digest(baseline) and result["tolerances_digest"] == digest(tolerances)
  assert result["authorized_limits"]["max_cost"] == "0"
  assert (baseline, tolerances) == before
  assert not ({"passed", "accepted", "authorization"} & result.keys())


@pytest.mark.parametrize("limits,expected", [({"absolute_delta": "1", "relative_delta": "2"}, "13"), ({"authorized_limit": "13"}, "13")])
def test_each_explicit_upper_bound_can_be_strictest(limits, expected):
  assert freeze_budget(*inputs(**limits), revision=1)["metrics"]["latency"]["threshold"] == expected


def test_zero_baseline_omits_relative_term_and_uses_only_explicit_bounds():
  result = freeze_budget(*inputs(("0", "0"), absolute_delta="2.500", relative_delta="0", authorized_limit="3"), revision=1)
  assert result["metrics"]["latency"]["threshold"] == "2.5"


@pytest.mark.parametrize("limits,expected", [({"absolute_delta": "5", "relative_delta": "0.1", "authorized_limit": "0"}, "10.8"),
  ({"absolute_delta": "1", "relative_delta": "0.5", "authorized_limit": "0"}, "11"),
  ({"absolute_delta": "20", "relative_delta": "1", "authorized_limit": "13"}, "13")])
def test_lower_bounds_are_hand_computed_without_reversing_strictness(limits, expected):
  result = freeze_budget(*inputs(direction="lower", **limits), revision=1)
  assert result["metrics"]["latency"]["threshold"] == expected


def test_p95_uses_nearest_rank_at_twenty_and_max_is_distinct():
  baseline, tolerances = inputs(tuple(str(value) for value in range(20, 0, -1)), statistic="p95")
  assert freeze_budget(baseline, tolerances, revision=1)["metrics"]["latency"]["baseline_stat"] == "19"
  tolerances["metrics"]["latency"]["statistic"] = "max"
  assert freeze_budget(baseline, tolerances, revision=1)["metrics"]["latency"]["baseline_stat"] == "20"


def test_decimal_math_is_exact_beyond_default_decimal_precision():
  values = ("1000000000000000000000000000000.1", "1000000000000000000000000000000.3")
  result = freeze_budget(*inputs(values, absolute_delta="0.01", relative_delta="1", authorized_limit="9999999999999999999999999999999"), revision=1)
  assert result["metrics"]["latency"]["baseline_stat"] == "1000000000000000000000000000000.2"
  assert result["metrics"]["latency"]["threshold"] == "1000000000000000000000000000000.21"


def test_failed_timeout_missing_all_consume_formal_tolerance_and_warmup_is_separate():
  baseline, tolerances = inputs(max_failed_samples=3)
  baseline["metrics"]["latency"]["samples"] += [{"status": name} for name in ("failed", "timeout", "missing")]
  baseline["metrics"]["latency"]["warmup_samples"] = [{"status": "failed"}, {"status": "missing"}]
  result = freeze_budget(baseline, tolerances, revision=1)["metrics"]["latency"]
  assert result["formal"] == {"total": 5, "valid": 2, "failed": 1, "timeout": 1, "missing": 1}
  assert result["warmup"] == {"total": 2, "valid": 0, "failed": 1, "timeout": 0, "missing": 1}
  tolerances["metrics"]["latency"]["max_failed_samples"] = 2
  with pytest.raises(ConfigError): freeze_budget(baseline, tolerances, revision=1)


@pytest.mark.parametrize("fault", ["baseline-unknown", "tolerance-unknown", "metric-unknown", "candidate", "version-bool", "version-float", "revision-bool", "tolerance-revision", "method", "identity", "platform", "missing-platform-identity", "unit", "unit-mismatch", "authorized", "authorized-metric", "metric-keys", "empty", "insufficient", "p95-small", "relative-lower", "statistic", "direction", "min-bool", "failed-bool", "failed-over", "sample-unknown", "sample-failed-value", "warmup-unknown", "calls-bool", "cost", "currency"])
def test_missing_or_inconsistent_inputs_fail_without_defaults(fault):
  baseline, tolerances = inputs(); metric = tolerances["metrics"]["latency"]; revision = 1
  if fault == "baseline-unknown": baseline["secret"] = "synthetic-secret"
  if fault == "tolerance-unknown": tolerances["candidate_results"] = []
  if fault == "metric-unknown": metric["auto_adjust"] = True
  if fault == "candidate": baseline["profile"] = "pi-base"
  if fault == "version-bool": baseline["schema_version"] = True
  if fault == "version-float": tolerances["schema_version"] = 1.0
  if fault == "revision-bool": revision = True
  if fault == "tolerance-revision": tolerances["revision"] = 0
  if fault == "method": tolerances["method_identity"] = "f" * 64
  if fault == "identity": baseline["runtime_identity"] = "not-a-digest"
  if fault == "platform": baseline["platform"] = "unknown"
  if fault == "missing-platform-identity": del baseline["platform_identity"]
  if fault == "unit": del metric["unit"]
  if fault == "unit-mismatch": metric["unit"] = "seconds"
  if fault == "authorized": del tolerances["authorized_limits"]
  if fault == "authorized-metric": del metric["authorized_limit"]
  if fault == "metric-keys": tolerances["metrics"]["extra"] = deepcopy(metric)
  if fault == "empty": baseline["metrics"]["latency"]["samples"] = []
  if fault == "insufficient": metric["min_valid_samples"] = 3
  if fault == "p95-small": metric["statistic"] = "p95"
  if fault == "relative-lower": metric.update(direction="lower", relative_delta="1.01")
  if fault == "statistic": metric["statistic"] = "mean"
  if fault == "direction": metric["direction"] = "auto"
  if fault == "min-bool": metric["min_valid_samples"] = True
  if fault == "failed-bool": metric["max_failed_samples"] = False
  if fault == "failed-over": baseline["metrics"]["latency"]["samples"].append({"status": "timeout"})
  if fault == "sample-unknown": baseline["metrics"]["latency"]["samples"][0]["secret"] = "synthetic-secret"
  if fault == "sample-failed-value": baseline["metrics"]["latency"]["samples"][0] = {"status": "failed", "value": "0"}
  if fault == "warmup-unknown": baseline["metrics"]["latency"]["warmup_samples"] = [{"status": "auto-retry"}]
  if fault == "calls-bool": tolerances["authorized_limits"]["max_model_calls"] = True
  if fault == "cost": tolerances["authorized_limits"]["max_cost"] = "-1"
  if fault == "currency": tolerances["authorized_limits"]["currency"] = ""
  with pytest.raises(ConfigError) as error: freeze_budget(baseline, tolerances, revision=revision)
  assert error.value.exit_code == 2 and "synthetic-secret" not in str(error.value)


@pytest.mark.parametrize("value", [True, 1, 0.1, "NaN", "Infinity", "-0", "-1", "1e3", "", " 1", ".5"])
def test_observation_numbers_are_nonnegative_decimal_strings_only(value):
  baseline, tolerances = inputs(); baseline["metrics"]["latency"]["samples"][0]["value"] = value
  with pytest.raises(ConfigError): freeze_budget(baseline, tolerances, revision=1)


def test_identity_changes_are_bound_instead_of_reusing_old_output():
  baseline, tolerances = inputs(); original = freeze_budget(baseline, tolerances, revision=1)
  baseline["checker_identity"] = "f" * 64
  changed = freeze_budget(baseline, tolerances, revision=2)
  assert original["baseline_digest"] != changed["baseline_digest"]
  assert changed["checker_identity"] == "f" * 64 and changed["revision"] == 2


@pytest.fixture
def budget_cli(monkeypatch):
  monkeypatch.setattr(sys, "path", list(sys.path)); monkeypatch.setattr(sys, "dont_write_bytecode", True)
  script = Path(__file__).resolve().parents[1] / "scripts/pi-freeze-budgets.py"
  spec = importlib.util.spec_from_file_location("pi_budget_cli_fixture", script)
  module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
  return module.main


def cli_files(tmp_path):
  baseline, tolerances = inputs()
  files = [tmp_path / name for name in ("baseline.json", "tolerances.json", "budget.json")]
  for path, value in zip(files, (baseline, tolerances)): path.write_text(json.dumps(value))
  return files, ["--baseline", str(files[0]), "--tolerances", str(files[1]), "--output", str(files[2]), "--revision", "1"]


def test_cli_atomically_creates_private_output_and_never_overwrites(tmp_path, budget_cli, capsys):
  files, argv = cli_files(tmp_path)
  assert budget_cli(argv) == 0
  saved = files[2].read_bytes()
  assert json.loads(saved)["metrics"]["latency"]["threshold"] == "15"
  assert files[2].stat().st_mode & 0o777 == 0o600
  assert budget_cli(argv) == 4 and files[2].read_bytes() == saved
  assert not list(tmp_path.glob(".agentcfg-*"))
  assert str(files[2]) not in capsys.readouterr().err


@pytest.mark.parametrize("fault", ["json", "duplicate", "missing", "arguments", "revision", "symlink", "io"])
def test_cli_errors_keep_input_content_and_paths_out_of_messages(tmp_path, budget_cli, capsys, monkeypatch, fault):
  files, argv = cli_files(tmp_path)
  if fault == "json": files[0].write_text('{"synthetic-secret": invalid}')
  if fault == "duplicate": files[0].write_text('{"schema_version":1,"schema_version":1}')
  if fault == "missing": files[0].unlink()
  if fault == "arguments": argv.append("synthetic-secret-option")
  if fault == "revision": argv[-1] = "synthetic-secret-revision"
  if fault == "symlink": files[2].symlink_to(files[0])
  if fault == "io":
    from agentcfg.storage import Tree
    monkeypatch.setattr(Tree, "write_new", lambda *_: (_ for _ in ()).throw(OSError("synthetic-secret-io")))
  expected = 4 if fault == "symlink" else 6 if fault in ("missing", "io") else 2
  assert budget_cli(argv) == expected
  if fault != "symlink": assert not files[2].is_file()
  captured = capsys.readouterr()
  assert "synthetic-secret" not in captured.err and str(tmp_path) not in captured.err



def test_exact_small_decimal_delta_does_not_round_lower_bound_up():
  tiny = "0." + "0" * 100 + "1"
  result = freeze_budget(*inputs(("1", "1"), direction="lower", absolute_delta=tiny, relative_delta="0.5", authorized_limit="0"), revision=1)
  assert result["metrics"]["latency"]["threshold"] == "0." + "9" * 101



@pytest.mark.parametrize("field", ["absolute_delta", "relative_delta", "authorized_limit"])
@pytest.mark.parametrize("value", [True, 1, "NaN", "Infinity", "-1"])
def test_every_numeric_tolerance_is_explicit_nonnegative_decimal(field, value):
  baseline, tolerances = inputs(); tolerances["metrics"]["latency"][field] = value
  with pytest.raises(ConfigError): freeze_budget(baseline, tolerances, revision=1)


def test_zero_lower_baseline_and_authorized_floor_remain_explicit():
  result = freeze_budget(*inputs(("0", "0"), direction="lower", absolute_delta="2", relative_delta="1", authorized_limit="1"), revision=1)
  assert result["metrics"]["latency"]["baseline_stat"] == "0"
  assert result["metrics"]["latency"]["threshold"] == result["metrics"]["latency"]["authorized_limit"] == "1"


def test_atomic_cli_publication_rejects_concurrent_same_name(tmp_path, budget_cli, monkeypatch):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  from agentcfg.storage import Tree
  files, argv = cli_files(tmp_path); barrier = Barrier(2); original = Tree.write_new
  def publish(tree, name, data):
    barrier.wait(timeout=5)
    original(tree, name, data)
  monkeypatch.setattr(Tree, "write_new", publish)
  with ThreadPoolExecutor(max_workers=2) as pool:
    assert sorted(pool.map(lambda _: budget_cli(argv), range(2))) == [0, 4]
  assert json.loads(files[2].read_bytes())["metrics"]["latency"]["threshold"] == "15"
  assert not list(tmp_path.glob(".agentcfg-*"))
