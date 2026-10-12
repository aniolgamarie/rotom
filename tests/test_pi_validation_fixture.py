"""原生验收夹具只生成私有文件；Git 等程序在本测试中全部使用替身。"""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from agentcfg.pi_validation_fixture import prepare_fixture
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("service", ["mcp", "web", "terminal"])
def test_native_service_fixture_selects_only_synthetic_service_bindings(tmp_path, service):
  program = tmp_path / "program"; program.write_text("never execute"); program.chmod(0o700)
  packages = tmp_path / "packages"; packages.mkdir()
  programs = {"engine": str(program), "git": str(program), "python": str(program), "python_runtime": str(packages), "python_packages": str(packages)}
  runtime = SimpleNamespace(profile="pi-default", engine="node", root=tmp_path / "runtime", lock_identity="a" * 64)
  result = prepare_fixture(tmp_path / "fixture", ROOT, runtime, "http://127.0.0.1:43123/v1", programs, run=lambda *_a, **_k: "", service=service)
  manifest = json.loads((result["workspace"].instance / "pi-home/agentcfg-manifest.json").read_text())
  if service == "mcp":
    assert "pi-mcp" in manifest["plugins"] and "pi-web" not in manifest["plugins"]
    assert manifest["options"]["mcp"]["servers"]["native-mcp"]["authentication"] == "bearer"
  elif service == "web":
    assert "pi-web" in manifest["plugins"] and manifest["options"]["web"]["providers"] == ["searxng"]
  else:
    assert manifest["options"]["agent_state"]["mode"] == "service"
    assert manifest["options"]["agent_state"]["pane"] == "native-pane"
  assert "synthetic-web-key" not in json.dumps(manifest) and "synthetic-mcp-key" not in json.dumps(manifest)


@pytest.mark.parametrize("profile,engine", [("pi-default", "node"), ("pi-managed", "node"), ("pi-codex", "node"), ("pi-cursor", "bun")])
@pytest.mark.parametrize("fixing", [False, True])
def test_native_fixture_renders_new_instance_with_synthetic_models_and_no_parent_credentials(tmp_path, monkeypatch, profile, engine, fixing):
  monkeypatch.setenv("OPENAI_API_KEY", "never-forward-parent-value")
  program = tmp_path / "synthetic-program"; program.write_text("fixture program, never execute"); program.chmod(0o700)
  packages = tmp_path / "packages"; packages.mkdir()
  programs = {"engine": str(program), "git": str(program), "python": str(program), "python_runtime": str(packages), "python_packages": str(packages)}
  runtime = SimpleNamespace(profile=profile, engine=engine, root=tmp_path / "runtime", lock_identity="a" * 64)
  calls = []
  def run(argv, **kwargs): calls.append((argv, kwargs)); return ""
  result = prepare_fixture(tmp_path / "fixture", ROOT, runtime, "http://127.0.0.1:43123/v1", programs, run=run, fixing=fixing)
  assert len(calls) == 4 and all(row[1]["cwd"] == result["project"] for row in calls)
  assert "OPENAI_API_KEY" not in result["environment"] and "never-forward-parent-value" not in json.dumps(result["environment"])
  manifest = json.loads((result["workspace"].instance / "pi-home/agentcfg-manifest.json").read_text())
  assert manifest["engine"] == engine and not manifest["bootstrap"]
  assert "python-runtime" not in manifest["options"]["paths"]["roots"]
  if profile != "pi-managed":
    from agentcfg.model_delegate import selected_route
    assert manifest["options"]["model_delegate"]["pi"]["model_roles"] == ["scout", "reviewer"]
    assert selected_route(manifest, "pi", {"provider_id": "agentcfg-native-fixture", "model_id": "agentcfg-native-reader"})[0] == "native-direct"
  assert manifest["model_bindings"]["main"]["model"] == "agentcfg-native-main"
  assert "synthetic-native-key" not in json.dumps(manifest)
  allowed = {value["model"] for value in manifest["allowed_models"]}
  assert {"agentcfg-native-main", "agentcfg-native-reader", "agentcfg-native-reviewer"} <= allowed
  assert {"deepseek-flash", "kimi-for-coding", "glm-5.3"} <= allowed
  assert not (result["workspace"].instance / "pi-home/auth.json").exists()
  assert (result["project"] / "code.txt").read_text() == "original\n"
  assert json.dumps("changed\n" if fixing else "original\n") in (result["project"] / "test_native_fixture.py").read_text()
  with pytest.raises(Conflict): prepare_fixture(tmp_path / "fixture", ROOT, runtime, "http://127.0.0.1:43123/v1", programs, run=run)


def test_native_fixture_rejects_an_external_model_endpoint_before_any_process_or_file(tmp_path):
  calls = []
  with pytest.raises(ConfigError, match="loopback"):
    prepare_fixture(tmp_path / "fixture", ROOT, None, "https://real-account.invalid/v1", {}, run=lambda *args, **kwargs: calls.append(args))
  assert not calls and not (tmp_path / "fixture").exists()


def test_configuration_can_bind_a_new_python_environment_before_runtime_installation(tmp_path):
  from agentcfg.pi_validation_fixture import prepare_configuration
  programs = {"engine": "/fixture/node", "git": "/fixture/git", "python": "/fixture/python",
    "python_runtime": "/fixture/python-runtime", "python_packages": str(tmp_path / "checkout/.venv/lib/python3.11/site-packages")}
  calls = []
  result = prepare_configuration(tmp_path / "new-home/native", ROOT, "pi-managed", "http://127.0.0.1:43217/v1", programs,
    run=lambda argv, **kwargs: calls.append(argv) or "")
  assert len(calls) == 4
  assert not result["workspace"].instance.exists()
  options = result["workspace"].resolved.data["profile"]["agent_options"]
  assert options["task_keeper"]["enabled"] and set(options["task_keeper"]["check_ids"]) == {"native-build", "native-tests"}
  assert options["paths"]["roots"]["python-packages"]["path"] == programs["python_packages"]
  assert not Path(programs["python_packages"]).exists()


def test_base_cold_configuration_keeps_main_only_without_full_roles_or_services(tmp_path, monkeypatch):
  from agentcfg.pi_validation_fixture import prepare_configuration
  monkeypatch.setenv("OPENAI_API_KEY", "synthetic-parent-not-selected")
  programs = {"engine": "/fixture/node", "git": "/fixture/git", "python": "/fixture/python",
    "python_runtime": "/fixture/python-runtime", "python_packages": str(tmp_path / "checkout/.venv/site-packages")}
  calls = []
  fixture = prepare_configuration(tmp_path / "base", ROOT, "pi-base", "http://127.0.0.1:43217/v1", programs,
    run=lambda argv, **kwargs: calls.append((argv, kwargs)) or "")
  data = fixture["workspace"].resolved.data
  assert len(calls) == 4 and not fixture["workspace"].instance.exists()
  assert data["profile"]["roles"] == {"main": "native-main"}
  assert data["profile"]["agent_options"]["permissions"]["policy_ref"] == "project-default"
  assert fixture["model_ids"] == ("agentcfg-native-main",)
  assert set(data["profile"]["agent_options"]["model_settings"]) == {"native-main"}
  assert not set(data["profile"]["agent_options"]) & {"model_delegate", "task_keeper", "durable", "readseek"}
  assert set(data["plugins"]) == {"pi-todo", "loop-guard", "colorful-footer"}
  assert "OPENAI_API_KEY" not in fixture["environment"]
  assert not (fixture["workspace"].instance / "pi-home/auth.json").exists()


@pytest.mark.parametrize("option", ["second_view", "proxy", "readseek"])
def test_base_cold_configuration_rejects_legacy_capabilities_before_side_effects(tmp_path, option):
  from agentcfg.pi_validation_fixture import prepare_configuration
  with pytest.raises(ConfigError):
    prepare_configuration(tmp_path / "base", ROOT, "pi-base", "http://127.0.0.1:43217/v1", {},
      run=lambda *_a, **_k: pytest.fail("unsupported Base capability must not start Git"), **{option: True})
  assert not (tmp_path / "base").exists()


def test_preinstalled_fixture_cannot_adopt_an_ordinary_existing_directory(tmp_path):
  from agentcfg.pi_validation_fixture import prepare_configuration
  root = tmp_path / "fixture"; slot = root / "instances_root/pi/pi-default/runtimes" / ("a" * 64)
  slot.mkdir(parents=True)
  sentinel = root / "original"; sentinel.write_text("synthetic existing data")
  with pytest.raises(Conflict, match="FIXTURE_EXISTS"):
    prepare_configuration(root, ROOT, "pi-default", "http://127.0.0.1:43217/v1", {}, run=lambda *_: pytest.fail("must not run"), preinstalled_runtime=slot)
  assert sentinel.read_text() == "synthetic existing data" and not (root / "local.toml").exists()


def _seal_two_profiles(value):
  from agentcfg.activity import digest
  value["scope_digest"] = digest({key: row for key, row in value.items() if key != "scope_digest"})
  return value


def test_two_profiles_scope_preserves_checks_traceability_and_profile_subitems(tmp_path):
  from agentcfg.pi_scope import two_profiles_scope, CHECK_REQUIREMENTS, INVARIANTS
  from agentcfg.pi_acceptance import report
  value = two_profiles_scope(created_at="2026-10-04T00:00:00Z")
  assert len(CHECK_REQUIREMENTS) == 63 and len(INVARIANTS) == 8
  assert {row["check_id"] for row in value["items"]} == set(CHECK_REQUIREMENTS) | set(INVARIANTS)
  assert {requirement for row in CHECK_REQUIREMENTS.values() for requirement in row} == {f"R{number:02}" for number in range(1, 38)}
  assert sum(key.startswith(("S", "B", "F", "W")) for key in CHECK_REQUIREMENTS) == 46
  base = [row for row in value["items"] if row["profile"] == "pi-base"]
  assert not any(row["check_id"].startswith("F") for row in base)
  assert next(row for row in base if row["check_id"] == "M03")["subitem_id"] == "pure-pi-base"
  assert next(row for row in value["items"] if row["check_id"] == "M03" and row["profile"] == "pi-full")["subitem_id"] == "four-states"
  result = report(value, tmp_path)
  assert result["report_generated"] and not result["release_approved"]
  assert not any(result["gates"].values())
  assert all(row["result"] == "not-run" and row["execution_state"] == "pending" for row in result["items"])


@pytest.mark.parametrize("fault", ["unknown", "missing-check", "levels", "profile", "maintenance", "old-scope"])
def test_two_profiles_scope_rejects_unknown_fields_and_scope_reduction(fault):
  from agentcfg.pi_scope import two_profiles_scope, initial_scope, OPTIONAL
  from agentcfg.pi_acceptance import validate_scope
  value = two_profiles_scope(created_at="2026-10-04T00:00:00Z")
  if fault == "unknown": value["items"][0]["task_checked"] = True
  if fault == "missing-check": value["items"].pop()
  if fault == "levels": value["items"][0]["levels"] = ["U"]
  if fault == "profile": value["items"][0]["profile"] = "pi-default"
  if fault == "maintenance": next(row for row in value["items"] if row["check_id"] == "M03")["subitem_id"] = "four-states"
  if fault == "old-scope":
    value = initial_scope(optional_selected=dict.fromkeys(OPTIONAL, True))
    value["scope_id"] = "005-pi-two-profiles"
  with pytest.raises(ConfigError): validate_scope(_seal_two_profiles(value))


def _bind_two_profiles_item(item, identity=None):
  item["identity"] = dict(identity) if identity else dict.fromkeys(("runtime_digest", "config_digest", "input_snapshot_digest"), "a" * 64)
  item["checker"] = {"checker_id": "synthetic-independent-checker", "implementation_digest": "c" * 64}


def _write_two_profiles_oracle(root, record):
  import hashlib
  keys = ("schema_version", "check_id", "profile", "subitem_id", "identity", "checker", "platform", "level", "result", "execution_state", "exit_code", "termination_confirmed", "tests")
  oracle = {key: record[key] for key in keys}
  oracle["assertions"] = {"semantics_verified": True, "stopped": True}
  path = root / ("oracle-" + str(len(list(root.iterdir()))) + ".json")
  path.write_text(json.dumps(oracle)); path.chmod(0o600)
  record["oracle"] = path.name
  record["artifacts"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}
  return path


def _two_profiles_evidence(item, level):
  return {"schema_version": 2, "check_id": item["check_id"], "profile": item["profile"], "subitem_id": item["subitem_id"],
    "identity": dict(item["identity"]), "checker": dict(item["checker"]), "platform": dict(item["platform"]), "level": level,
    "result": "passed", "execution_state": "finished", "validity": "current",
    "started_at": "2026-10-04T00:00:00Z", "finished_at": "2026-10-04T00:00:01Z", "command": ["synthetic-check"],
    "cwd": "/synthetic-project", "exit_code": 0, "termination_confirmed": True,
    "tests": {"discovered": 1, "passed": 1, "failed": 0, "skipped": 0}, "oracle": "oracle.json", "artifacts": {}, "reason": "synthetic evidence"}


@pytest.mark.parametrize("fault", ["zero-tests", "skipped", "nonzero", "assertion", "no-proof", "unknown", "old-evidence"])
def test_two_profiles_evidence_never_accepts_empty_success_or_hides_failure(tmp_path, fault):
  from agentcfg.pi_acceptance import _validate_evidence_v2
  from agentcfg.pi_scope import two_profiles_scope
  item = two_profiles_scope()["items"][0]
  _bind_two_profiles_item(item)
  record = _two_profiles_evidence(item, "U")
  if fault == "zero-tests": record["tests"] = dict.fromkeys(record["tests"], 0)
  if fault == "skipped": record["tests"].update(passed=0, skipped=1)
  if fault == "nonzero": record["exit_code"] = 1
  if fault == "assertion": record["tests"].update(passed=0, failed=1)
  if fault == "unknown": record["task_checked"] = True
  if fault == "old-evidence": record["schema_version"] = 1
  if fault in ("unknown", "old-evidence"):
    with pytest.raises(ConfigError): _validate_evidence_v2(record, tmp_path, {})
  elif fault == "no-proof": assert _validate_evidence_v2(record, tmp_path, {}) == ("invalid", "proof-missing")
  else: assert _validate_evidence_v2(record, tmp_path, {}) == ("current", "failed")


def test_two_profiles_base_gate_is_independent_and_current_failure_wins(tmp_path):
  import hashlib
  from agentcfg.pi_scope import two_profiles_scope
  from agentcfg.pi_acceptance import report
  value = two_profiles_scope(created_at="2026-10-04T00:00:00Z", whole_process_isolation_decision="supported")
  identity = dict.fromkeys(("runtime_digest", "config_digest", "input_snapshot_digest"), "a" * 64)
  for index, item in enumerate(value["items"]):
    _bind_two_profiles_item(item, identity)
    if item["profile"] != "pi-base" or item["check_id"].startswith("W"): continue
    for level in item["levels"]:
      path = f"{index}-{level}.json"
      record = _two_profiles_evidence(item, level); _write_two_profiles_oracle(tmp_path, record)
      (tmp_path / path).write_text(json.dumps(record)); (tmp_path / path).chmod(0o600)
      item["evidence_paths"].append(path)
  result = report(_seal_two_profiles(value), tmp_path)
  assert result["gates"]["base"] and not result["gates"]["full"] and not result["release_approved"]
  item = value["items"][0]
  failure = _two_profiles_evidence(item, "U")
  failure.update(finished_at="2026-10-04T00:00:02Z", exit_code=1)
  _write_two_profiles_oracle(tmp_path, failure)
  (tmp_path / "failure.json").write_text(json.dumps(failure)); (tmp_path / "failure.json").chmod(0o600)
  item["evidence_paths"].append("failure.json")
  result = report(_seal_two_profiles(value), tmp_path)
  assert result["items"][0]["result"] == "failed" and result["items"][0]["validity"] == "current"
  assert not result["gates"]["base"]
  item["identity"]["config_digest"] = "b" * 64
  result = report(_seal_two_profiles(value), tmp_path)
  assert result["items"][0]["validity"] == "stale" and not result["gates"]["base"]


@pytest.mark.parametrize("fault", ["profile", "runtime", "config", "snapshot", "mock-only", "artifact"])
def test_two_profiles_evidence_must_match_profile_identity_and_required_levels(tmp_path, fault):
  import hashlib
  from agentcfg.pi_scope import two_profiles_scope
  from agentcfg.pi_acceptance import report
  value = two_profiles_scope(created_at="2026-10-04T00:00:00Z"); item = value["items"][0]
  _bind_two_profiles_item(item)
  record = _two_profiles_evidence(item, "U")
  oracle = _write_two_profiles_oracle(tmp_path, record)
  if fault == "profile": record["profile"] = "pi-full"
  if fault in ("runtime", "config"): record["identity"][fault + "_digest"] = "b" * 64
  if fault == "snapshot": record["identity"]["input_snapshot_digest"] = "b" * 64
  if fault == "artifact": oracle.write_text("changed oracle")
  path = tmp_path / "evidence.json"; path.write_text(json.dumps(record)); path.chmod(0o600)
  item["evidence_paths"] = ["evidence.json"]
  if fault == "profile":
    with pytest.raises(ConfigError, match="reference"): report(_seal_two_profiles(value), tmp_path)
  else:
    result = report(_seal_two_profiles(value), tmp_path)
    assert not result["gates"]["base"] and not result["release_approved"]
    level = result["items"][0]["level_results"]["U"]
    if fault in ("runtime", "config", "snapshot"): assert level["validity"] == "stale"
    if fault == "artifact": assert level["validity"] == "invalid"
    if fault == "mock-only": assert result["items"][0]["level_results"]["V"]["result"] == "not-run"


@pytest.mark.parametrize("check,missing_level", [("S02", "P"), ("S04", "L"), ("P03", "O")])
def test_two_profiles_mock_record_cannot_fill_os_native_or_live_level(tmp_path, check, missing_level):
  from agentcfg.pi_scope import two_profiles_scope
  from agentcfg.pi_acceptance import report
  value = two_profiles_scope(); item = next(row for row in value["items"] if row["check_id"] == check)
  _bind_two_profiles_item(item)
  record = _two_profiles_evidence(item, "U")
  path = tmp_path / "mock.json"; path.write_text(json.dumps(record)); path.chmod(0o600)
  item["evidence_paths"] = ["mock.json"]
  result = report(_seal_two_profiles(value), tmp_path)
  row = next(row for row in result["items"] if row["check_id"] == check)
  assert row["level_results"][missing_level]["result"] == "not-run"
  assert not result["gates"]["base"] and not result["release_approved"]


@pytest.mark.parametrize("decision,result,proof,closed", [("undecided", "passed", True, False), ("unsupported", "unsupported", True, True), ("unsupported", "not-run", False, False), ("unsupported", "unsupported", False, False), ("unsupported", "passed", True, False), ("supported", "unsupported", True, False), ("supported", "passed", True, True)])
def test_whole_process_feasibility_preserves_unsupported_and_requires_real_proof(tmp_path, decision, result, proof, closed):
  import hashlib
  from agentcfg.pi_scope import two_profiles_scope
  from agentcfg.pi_acceptance import report
  value = two_profiles_scope(whole_process_isolation_decision=decision)
  for index, item in enumerate(value["items"]):
    if item["check_id"] != "P05" or item["subitem_id"] != "feasibility": continue
    _bind_two_profiles_item(item)
    for level in item["levels"]:
      record = _two_profiles_evidence(item, level); record["result"] = result
      if proof: _write_two_profiles_oracle(tmp_path, record)
      if result == "not-run": record.update(started_at=None, finished_at=None, command=[], termination_confirmed=False, execution_state="pending")
      path = f"{index}-{level}.json"; (tmp_path / path).write_text(json.dumps(record)); (tmp_path / path).chmod(0o600)
      item["evidence_paths"].append(path)
  observed = report(_seal_two_profiles(value), tmp_path)
  assert observed["gates"]["whole-process-feasibility"] is closed
  assert not observed["release_approved"] and not observed["gates"]["isolation"]
  if decision == "unsupported" and result == "unsupported" and proof:
    assert all(row["result"] == "unsupported" for row in observed["items"] if row["subitem_id"] == "feasibility")
  assert any(row["subitem_id"] == "malicious-extension" for row in value["items"]) is (decision == "supported")


def test_scope_revision_cannot_remove_frozen_whole_process_negative_branch():
  from agentcfg.pi_scope import two_profiles_scope
  from agentcfg.pi_acceptance import validate_revision
  before = two_profiles_scope(whole_process_isolation_decision="supported")
  after = two_profiles_scope(whole_process_isolation_decision="unsupported"); after["revision"] = 2
  with pytest.raises(ConfigError, match="scope-reduction"): validate_revision(before, _seal_two_profiles(after))


@pytest.mark.parametrize("fault", ["text", "checker", "missing-checker", "oracle-failed", "oracle-counts", "oracle-stopped", "oracle-U-for-P", "oracle-U-for-L", "running", "blocked", "stalled", "scope-float", "record-float", "platform-number"])
def test_two_profiles_strict_oracle_and_finished_execution_are_required(tmp_path, fault):
  import hashlib
  from agentcfg.pi_scope import two_profiles_scope
  from agentcfg.pi_acceptance import report, validate_scope
  value = two_profiles_scope()
  selected_check = "S02" if fault == "oracle-U-for-P" else "S04" if fault == "oracle-U-for-L" else "S01"
  item = next(row for row in value["items"] if row["check_id"] == selected_check)
  _bind_two_profiles_item(item)
  item["checker"] = {"checker_id": "synthetic-independent-checker", "implementation_digest": "c" * 64}
  record = _two_profiles_evidence(item, "U")
  record.update(checker=dict(item["checker"]), execution_state="finished")
  oracle_keys = ("schema_version", "check_id", "profile", "subitem_id", "identity", "platform", "level", "checker", "result", "execution_state", "exit_code", "termination_confirmed", "tests")
  oracle = json.loads(json.dumps({key: record[key] for key in oracle_keys}))
  oracle["assertions"] = {"semantics_verified": True, "stopped": True}
  if fault == "checker": oracle["checker"]["implementation_digest"] = "d" * 64
  if fault == "missing-checker": item["checker"] = None
  if fault == "oracle-failed": oracle.update(result="failed", tests={"discovered": 1, "passed": 0, "failed": 1, "skipped": 0})
  if fault == "oracle-counts": oracle["tests"] = {"discovered": 2, "passed": 2, "failed": 0, "skipped": 0}
  if fault == "oracle-stopped": oracle["assertions"]["stopped"] = False
  if fault.startswith("oracle-U-for-"): record["level"] = fault[-1]
  if fault in ("running", "blocked", "stalled"): record["execution_state"] = fault; oracle["execution_state"] = fault
  if fault == "scope-float": value["schema_version"] = 2.0
  if fault == "record-float": record["schema_version"] = 2.0
  if fault == "platform-number": record["platform"]["os"] = 7
  path = tmp_path / "oracle.json"; path.write_text("arbitrary text" if fault == "text" else json.dumps(oracle)); path.chmod(0o600)
  record["artifacts"] = {"oracle.json": hashlib.sha256(path.read_bytes()).hexdigest()}
  path = tmp_path / "result.json"; path.write_text(json.dumps(record)); path.chmod(0o600)
  item["evidence_paths"] = ["result.json"]
  if fault in ("scope-float", "record-float", "platform-number"):
    with pytest.raises(ConfigError): report(_seal_two_profiles(value), tmp_path)
  else:
    observed = report(_seal_two_profiles(value), tmp_path)
    assert not observed["gates"]["base"]
    candidate = next(row for row in observed["items"] if (row["check_id"], row["profile"], row["subitem_id"]) == (item["check_id"], item["profile"], item["subitem_id"]))
    level = candidate["level_results"][record["level"]]
    assert level["result"] != "passed" or level["validity"] != "current"
    if fault == "oracle-failed": assert level["result"] == "failed"


def test_two_profiles_invariant_requirements_are_derived_from_related_checks():
  from agentcfg.pi_scope import two_profiles_scope, CHECK_REQUIREMENTS, INVARIANTS
  value = two_profiles_scope()
  for row in value["items"]:
    if row["check_id"] not in INVARIANTS: continue
    expected = {requirement for check in INVARIANTS[row["check_id"]] for requirement in CHECK_REQUIREMENTS[check]}
    assert expected and set(row["requirements"]) == expected


def test_report_only_consumes_v2_scope_without_creating_product_evidence(tmp_path):
  from agentcfg.pi_scope import two_profiles_scope
  from agentcfg.pi_verification import main
  scope = tmp_path / "scope.json"; scope.write_text(json.dumps(two_profiles_scope())); scope.chmod(0o600)
  output = tmp_path / "report.json"
  code = main(["--report-only", "--scope", str(scope), "--evidence-root", str(tmp_path), "--output", str(output)],
    execute=lambda *_: pytest.fail("report-only must not execute a host or checker"))
  assert code == 0
  value = json.loads(output.read_text())
  assert value["schema_version"] == 2 and value["scope_id"] == "005-pi-two-profiles"
  assert value["report_generated"] and not value["candidate_frozen"] and not value["release_approved"]
  assert not any(value["gates"].values())
