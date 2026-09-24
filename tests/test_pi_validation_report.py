"""拒绝空成功、身份错配和不完整执行报告；不运行宿主。"""
import pytest

from agentcfg.pi_validation_report import validate_run_report
from agentcfg.pi_validation_runtime import ValidationRuntime
from agentcfg.pi_verification import main
from agentcfg.schema import ConfigError


def mock_report():
  return {"schema_version": 1, "tier": "mock", "case": "all", "status": "passed",
    "started_at": "2026-09-19T01:00:00Z", "finished_at": "2026-09-19T01:00:01Z",
    "results": [{"runner": "pytest", "exit_code": 0, "command": ["fixture"], "artifact_refs": ["fixture.stdout"]}]}


@pytest.mark.parametrize("fault", ["empty", "identity", "exit", "time", "unknown-field", "duplicate", "boolean-exit"])
def test_invalid_run_report_never_gets_persisted_as_success(tmp_path, fault):
  value = mock_report()
  if fault == "empty": value["results"] = []
  if fault == "identity": value["case"] = "host-resources"
  if fault == "exit": value["results"][0]["exit_code"] = 1
  if fault == "time": value["finished_at"] = "2026-09-18T00:00:00Z"
  if fault == "unknown-field": value["credentials"] = "synthetic-private"
  if fault == "duplicate": value["results"] *= 2
  if fault == "boolean-exit": value["results"][0]["exit_code"] = False
  output = tmp_path / "report.json"
  assert main(["--tier", "mock", "--case", "all", "--output", str(output)], execute=lambda _: value) == 2
  assert not output.exists()


@pytest.mark.parametrize("fault", [None, "missing-case", "physical", "source", "aggregate", "facts"])
def test_native_run_requires_complete_selection_identity_and_physical_proof(tmp_path, fault):
  runtime = ValidationRuntime(tmp_path, "pi-default", "node", "linux-x86_64", "a" * 64, "b" * 64, "c" * 64, "fixture", {"node": "v24.14.0"})
  value = {**mock_report(), "tier": "native", "case": "host-resources", "runtime": runtime.public_identity(), "source_digest": "d" * 64,
    "results": [{"scenario_id": "host-resources", "status": "passed", "facts": {"sdk_session": True}, "execution": {"exit_code": 0, "termination_confirmed": True}}]}
  if fault == "missing-case": value["results"][0]["scenario_id"] = "permission-denials"
  if fault == "physical": value["results"][0]["execution"]["termination_confirmed"] = False
  if fault == "source": value.pop("source_digest")
  if fault == "aggregate": value["status"] = "not-run"
  if fault == "facts": value["results"][0]["facts"] = None
  if fault:
    with pytest.raises(ConfigError): validate_run_report(value, tier="native", case="host-resources")
  else: assert validate_run_report(value, tier="native", case="host-resources") == value


def test_explicit_not_run_remains_reportable_but_empty_passed_live_is_rejected():
  value = {"schema_version": 1, "tier": "live", "case": "host-resources", "status": "not-run", "reason": "prerequisite-missing", "results": []}
  assert validate_run_report(value, tier="live", case="host-resources") == value
  value["status"] = "passed"
  with pytest.raises(ConfigError): validate_run_report(value, tier="live", case="host-resources")
