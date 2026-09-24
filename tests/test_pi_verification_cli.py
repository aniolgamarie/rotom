"""验证 CLI 的报告/执行授权边界；执行器全部替身。"""
import json
import pytest
from agentcfg.pi_verification import main
from test_pi_release_gate import scope, save


def test_report_success_is_not_release_approval_and_output_never_overwrites(tmp_path):
  save(tmp_path, "scope.json", scope())
  base = ["--scope", str(tmp_path / "scope.json"), "--evidence-root", str(tmp_path / "missing")]
  result = tmp_path / "report.json"
  assert main(["--report-only", *base, "--output", str(result)]) == 0
  assert not json.loads(result.read_text())["release_approved"]
  assert result.stat().st_mode & 0o777 == 0o600
  original = result.read_bytes()
  assert main(["--check-release", *base, "--output", str(result)]) == 2
  assert result.read_bytes() == original
  assert main(["--check-release", *base, "--output", str(tmp_path / "decision.json")]) == 1


@pytest.mark.parametrize("args", [
  ["--tier", "mock", "--case", "all", "--home", "/real/home"],
  ["--tier", "mock", "--case", "all", "--runtime", "/real/runtime"],
  ["--tier", "native", "--case", "all", "--runtime", "/runtime"],
  ["--tier", "native", "--case", "all", "--runtime", "/runtime", "--allow-host", "--local", "/credentials"],
  ["--tier", "live", "--case", "all", "--runtime", "/runtime", "--allow-host", "--allow-live", "--local", "/local", "--profile", "pi-default", "--project", "/project"],
  ["--tier", "live", "--case", "codex-receipts", "--runtime", "/runtime", "--allow-host"],
  ["--tier", "live", "--case", "codex-receipts", "--runtime", "/runtime", "--allow-host", "--allow-live", "--local", "/local", "--profile", "pi-codex", "--project", "/project"],
  ["--report-only", "--scope", "/scope", "--evidence-root", "/evidence", "--allow-host"],
])
def test_invalid_authorization_never_calls_executor(tmp_path, args):
  calls = []
  assert main([*args, "--output", str(tmp_path / "result.json")], execute=lambda _: calls.append(True)) == 2
  assert not calls and not (tmp_path / "result.json").exists()


def test_tier_required_and_modes_are_mutually_exclusive(tmp_path):
  for args in ([], ["--tier", "mock", "--report-only"]):
    with pytest.raises(SystemExit) as error: main([*args, "--output", str(tmp_path / "result.json")])
    assert error.value.code == 2


def test_execution_failed_or_not_run_returns_one_and_preserves_report(tmp_path):
  for status, expected in (("passed", 0), ("failed", 1), ("not-run", 1)):
    result = tmp_path / (status + ".json")
    value = {"schema_version": 1, "tier": "mock", "case": "all", "status": status,
      "started_at": "2026-09-19T01:00:00Z", "finished_at": "2026-09-19T01:00:01Z",
      "results": [{"runner": "pytest", "exit_code": 0 if status == "passed" else 1, "command": ["fixture"], "artifact_refs": ["fixture.stdout"]}]}
    if status == "not-run": value.update(results=[], reason="fixture-unavailable")
    assert main(["--tier", "mock", "--case", "all", "--output", str(result)], execute=lambda _: value) == expected
    assert json.loads(result.read_text())["status"] == status


def test_corrupt_scope_returns_input_error_not_a_missing_evidence_pass(tmp_path):
  (tmp_path / "scope.json").write_text('{"private-key":"synthetic secret"}')
  assert main(["--report-only", "--scope", str(tmp_path / "scope.json"), "--evidence-root", str(tmp_path), "--output", str(tmp_path / "out.json")]) == 2


def test_new_report_can_use_a_trusted_non_private_parent_and_never_replaces_a_racing_creator(tmp_path, monkeypatch):
  import os
  from agentcfg.pi_acceptance import write_report
  from agentcfg.storage import Conflict
  parent = tmp_path / "public"; parent.mkdir(mode=0o755); parent.chmod(0o755)
  write_report(parent / "first.json", {"status": "not-run"})
  assert (parent / "first.json").stat().st_mode & 0o777 == 0o600
  real_link = os.link
  def race(source, target, **kwargs):
    (parent / target).write_text("other writer")
    return real_link(source, target, **kwargs)
  monkeypatch.setattr(os, "link", race)
  with pytest.raises(Conflict): write_report(parent / "race.json", {"status": "passed"})
  assert (parent / "race.json").read_text() == "other writer"


def test_native_runtime_cannot_be_a_credential_file_and_bad_parent_never_executes(tmp_path):
  credential = tmp_path / "auth.json"; credential.write_text("synthetic credential")
  calls = []
  assert main(["--tier", "native", "--allow-host", "--case", "codex-receipts", "--runtime", str(credential), "--output", str(tmp_path / "report.json")], execute=lambda _: calls.append(True)) == 2
  assert not calls
  assert main(["--tier", "mock", "--case", "all", "--output", str(tmp_path / "absent/report.json")], execute=lambda _: calls.append(True)) == 2
  assert not calls


def test_mock_dispatch_runs_python_and_guarded_node_with_fresh_environment(tmp_path, monkeypatch):
  from types import SimpleNamespace
  import agentcfg.pi_validation as runner
  calls = []
  monkeypatch.setattr(runner.shutil, "which", lambda _: "/fixture/node")
  def run(argv, **kwargs):
    calls.append((argv, kwargs))
    assert kwargs["env"]["HOME"] != str(Path.home())
    assert "CODEX_HOME" in kwargs["env"] and "PRIVATE_CREDENTIAL" not in kwargs["env"]
    return SimpleNamespace(returncode=0, stdout=b"fixture pass", stderr=b"")
  from pathlib import Path
  monkeypatch.setenv("PRIVATE_CREDENTIAL", "synthetic must not forward")
  monkeypatch.setattr(runner.subprocess, "run", run)
  result = runner.execute(SimpleNamespace(tier="mock", case="all", output=tmp_path / "mock.json"))
  assert result["status"] == "passed" and [row["runner"] for row in result["results"]] == ["pytest", "node"]
  assert calls[1][0][1] == "scripts/test-pi-mock.mjs"


def test_prepare_live_project_is_separate_from_host_and_account_execution(tmp_path, monkeypatch):
  import agentcfg.pi_live_project as project
  calls = []
  monkeypatch.setattr(project, "prepare_project", lambda path: calls.append(path) or {"schema_version": 1, "status": "prepared", "kind": "live-project", "project": str(path), "model_calls": 0})
  output = tmp_path / "prepared.json"
  assert main(["--prepare-live-project", "--project", str(tmp_path / "project"), "--output", str(output)]) == 0
  assert len(calls) == 1 and json.loads(output.read_text())["model_calls"] == 0
  assert main(["--prepare-live-project", "--project", str(tmp_path / "project"), "--allow-live", "--output", str(tmp_path / "other.json")]) == 2
  assert len(calls) == 1
