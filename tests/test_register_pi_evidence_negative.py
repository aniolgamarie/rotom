"""登记器回归：生产格式正例 + 全部缺陷类负向样本 + 主入口可核验状态。

负向样本以 pi-register-review-20260922.md 的 8 类错误接受为基线，
并补齐 scenario 缺失、命令/时间缺失、无装饰冷报告等新增契约要求。
"""
import importlib.util
import json
from types import SimpleNamespace
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

_spec = importlib.util.spec_from_file_location("register_pi_evidence", Path(__file__).resolve().parents[1] / "scripts" / "register-pi-evidence.py")
register = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(register)

verify_mock_report = register.verify_mock_report
verify_native_report = register.verify_native_report
verify_cold_rebuild_report = register.verify_cold_rebuild_report
write_record = register.write_record
main = register.main

from agentcfg.pi_cold_rebuild import native_cases, collect_source, snapshot_digest
from agentcfg.pi_validation_native import scenarios

LOCK = "a" * 64
SOURCE = "d" * 64
PLATFORM = "linux-x86_64"
COLD_TARGETS = ("first", "第二组 空格路径")
TARGET_RUNTIMES = {"first": "b" * 64, "第二组 空格路径": "e" * 64}


def _time(offset_minutes):
  return "2026-09-23T00:%02d:00.000000Z" % min(59, offset_minutes)


def native_document(profile, case, runtime="b" * 64, index=0):
  rows = [{"scenario_id": name, "status": "passed",
    "execution": {"exit_code": 0, "termination_confirmed": True},
    "facts": {"real_account_used": False, "sdk_session": True}} for name in scenarios(case, profile)]
  return {"schema_version": 1, "tier": "native", "case": case, "status": "passed",
    "started_at": _time(10 * index), "finished_at": _time(10 * index + 1),
    "source_digest": SOURCE, "work_root": "/fixture/work",
    "command": ["/fixture/.venv/bin/python", "-B", "/fixture/checkout/scripts/verify-pi.py", "--tier", "native", "--allow-host",
      "--case", case, "--runtime", "/fixture/runtime", "--output", "/fixture/out/" + case + ".json"],
    "runtime": {"engine": "bun" if profile == "pi-cursor" else "node", "lock_identity": LOCK, "runtime_identity": runtime,
      "platform": PLATFORM, "profile": profile, "slice_identity": "c" * 64, "toolchains": {"node": "v24.14.0", "bun": "1.4.0"}},
    "results": rows, "limitations": ["synthetic-loopback-models; no real accounts"]}


def write_native(run_root, profile, case, runtime, index=0, document=None):
  directory = run_root / "native"
  directory.mkdir(parents=True, exist_ok=True)
  path = directory / (case + ".json")
  path.write_text(json.dumps(document or native_document(profile, case, runtime=runtime, index=index)))
  return path


def cold_document(profile):
  targets = [{"target": name, "installation": "verified", "native_execution": "passed", "lock_identity": LOCK,
    "runtime_identity": TARGET_RUNTIMES[name], "source_digest": SOURCE,
    "steps": [{"step": step, "exit_code": 0} for step in register.EXPECTED_COLD_STEPS],
    "native_cases": [{"case": case, "status": "passed", "exit_code": 0, "report": "native/" + case + ".json"} for case in native_cases(profile)]}
    for name in COLD_TARGETS]
  return {"schema_version": 1, "case": "cold-rebuild", "profile": profile, "platform": PLATFORM, "lock_identity": LOCK,
    "status": "passed", "reason": "two-fresh-targets-verified", "targets": targets,
    "started_at": _time(0), "finished_at": _time(9),
    "command": ["/fixture/.venv/bin/python", "-B", "-I", "scripts/cold-driver.py", "--profile", profile]}


def make_valid_cold(tmp_path, profile="pi-default"):
  """生产布局：run_root/<profile>-cold.json + run_root/<profile>/<target>/native/<case>.json。"""
  run_root = tmp_path / "run"; run_root.mkdir()
  report = cold_document(profile)
  for target in report["targets"]:
    directory = run_root / profile / target["target"]
    for index, row in enumerate(target["native_cases"]):
      write_native(directory, profile, row["case"], target["runtime_identity"], index=index)
  report_path = run_root / (profile + "-cold.json")
  report_path.write_text(json.dumps(report))
  return run_root, report_path


def make_valid_mock(tmp_path):
  mock_path = tmp_path / "mock.json"
  artifacts = tmp_path / "mock.json.artifacts"; artifacts.mkdir()
  for name in ("pytest.stdout", "pytest.stderr", "node.stdout", "node.stderr"):
    (artifacts / name).write_text("fixture " + name)
  mock_path.write_text(json.dumps({"schema_version": 1, "tier": "mock", "case": "all", "status": "passed",
    "started_at": _time(0), "finished_at": _time(2),
    "results": [
      {"runner": "pytest", "exit_code": 0, "command": [".venv/bin/python", "-m", "pytest", "-q", "tests"],
        "artifact_refs": ["mock.json.artifacts/pytest.stdout", "mock.json.artifacts/pytest.stderr"]},
      {"runner": "node", "exit_code": 0, "command": ["node", "scripts/test-pi-mock.mjs", "agents/pi/runtime/tests/a.test.ts"],
        "artifact_refs": ["mock.json.artifacts/node.stdout", "mock.json.artifacts/node.stderr"]}],
    "limitations": ["mock-only; no native hosts or accounts"]}))
  return mock_path


def mutate(path, transform):
  value = json.loads(path.read_text())
  transform(value)
  path.write_text(json.dumps(value))
  return value


# ========== 生产格式正例 ==========

def test_mock_positive(tmp_path):
  assert verify_mock_report(make_valid_mock(tmp_path))["status"] == "passed"


def test_native_positive_roundtrip(tmp_path):
  for profile in ("pi-default", "pi-cursor", "pi-codex", "pi-managed"):
    for index, case in enumerate(native_cases(profile)):
      path = write_native(tmp_path / profile, profile, case, TARGET_RUNTIMES["first"], index=index)
      assert verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, profile, PLATFORM, case=case)["case"] == case


@pytest.mark.parametrize("profile", ("pi-default", "pi-cursor", "pi-codex", "pi-managed"))
def test_cold_positive(tmp_path, profile):
  run_root, report_path = make_valid_cold(tmp_path, profile)
  assert verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, profile, PLATFORM)["status"] == "passed"


def test_cursor_cold_expectation_includes_readseek(tmp_path):
  # 曾经的缺口：cold 预期集不含 Cursor 的 readseek-tools；现在生产与登记必须一致
  assert "readseek-tools" in native_cases("pi-cursor")
  run_root, report_path = make_valid_cold(tmp_path, "pi-cursor")
  mutate(report_path, lambda value: value["targets"][0].__setitem__("native_cases",
    [row for row in value["targets"][0]["native_cases"] if row["case"] != "readseek-tools"]))
  with pytest.raises(ValueError, match="native_cases 与生产预期"):
    verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, "pi-cursor", PLATFORM)


# ========== register-review 的 8 类负向样本 ==========

def test_negative_1_mock_missing_node_runner(tmp_path):
  path = make_valid_mock(tmp_path)
  mutate(path, lambda value: value.__setitem__("results", [row for row in value["results"] if row["runner"] != "node"]))
  with pytest.raises(ValueError, match="runner 集合"):
    verify_mock_report(path)


def test_negative_2_mock_empty_artifact_refs(tmp_path):
  path = make_valid_mock(tmp_path)
  mutate(path, lambda value: [row.__setitem__("artifact_refs", []) for row in value["results"]])
  with pytest.raises(ValueError, match="(artifact_refs 为空|未通过生产校验)"):
    verify_mock_report(path)


def test_negative_3_native_invented_scenario(tmp_path):
  path = write_native(tmp_path, "pi-default", "host-resources", TARGET_RUNTIMES["first"])
  mutate(path, lambda value: value["results"][0].__setitem__("scenario_id", "invented-scenario"))
  with pytest.raises(ValueError, match="未通过生产校验"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="host-resources")


def test_negative_4_native_cross_identity(tmp_path):
  path = write_native(tmp_path, "pi-cursor", "host-resources", TARGET_RUNTIMES["first"])
  with pytest.raises(ValueError, match="profile 不匹配"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="host-resources")
  path2 = write_native(tmp_path / "x", "pi-default", "host-resources", TARGET_RUNTIMES["first"])
  with pytest.raises(ValueError, match="platform 不匹配"):
    verify_native_report(path2, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", "darwin-arm64", case="host-resources")


def test_negative_5_native_timed_out(tmp_path):
  path = write_native(tmp_path, "pi-default", "host-resources", TARGET_RUNTIMES["first"])
  mutate(path, lambda value: value["results"][0]["execution"].__setitem__("timed_out", True))
  with pytest.raises(ValueError, match="未通过生产校验"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="host-resources")


def test_negative_6_native_empty_facts(tmp_path):
  path = write_native(tmp_path, "pi-default", "host-resources", TARGET_RUNTIMES["first"])
  mutate(path, lambda value: value["results"][0].__setitem__("facts", {}))
  with pytest.raises(ValueError, match="未通过生产校验"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="host-resources")


def test_negative_7_cold_duplicate_targets(tmp_path):
  run_root, report_path = make_valid_cold(tmp_path)
  mutate(report_path, lambda value: value["targets"][1].__setitem__("target", "first"))
  with pytest.raises(ValueError, match="按序"):
    verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, "pi-default", PLATFORM)


def test_negative_8_cold_referenced_native_failed(tmp_path):
  run_root, report_path = make_valid_cold(tmp_path)
  native_path = run_root / "pi-default" / "first" / "native" / "host-resources.json"
  mutate(native_path, lambda value: value["results"][0].__setitem__("status", "failed"))
  with pytest.raises(ValueError, match="引用的 native 报告核验失败"):
    verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, "pi-default", PLATFORM)
  # termination_confirmed=false 同样被递归核验拒绝
  native_path2 = run_root / "pi-default" / "first" / "native" / "budget-permissions.json"
  mutate(native_path2, lambda value: value["results"][0]["execution"].__setitem__("termination_confirmed", False))
  with pytest.raises(ValueError, match="引用的 native 报告核验失败"):
    verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, "pi-default", PLATFORM)


# ========== 其他关键负向 ==========

def test_negative_mock_duplicate_runner(tmp_path):
  path = make_valid_mock(tmp_path)
  mutate(path, lambda value: value["results"][1].__setitem__("runner", "pytest"))
  with pytest.raises(ValueError, match="(runner 集合|生产校验)"):
    verify_mock_report(path)


def test_negative_mock_missing_artifact(tmp_path):
  path = make_valid_mock(tmp_path)
  mutate(path, lambda value: value["results"][0]["artifact_refs"].append("mock.json.artifacts/ghost"))
  with pytest.raises(ValueError, match="产物引用不存在"):
    verify_mock_report(path)


def test_negative_native_missing_scenario(tmp_path):
  path = write_native(tmp_path, "pi-default", "termination-recovery", TARGET_RUNTIMES["first"])
  mutate(path, lambda value: value["results"].pop())
  with pytest.raises(ValueError, match="未通过生产校验"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="termination-recovery")


def test_negative_native_duplicate_scenario(tmp_path):
  path = write_native(tmp_path, "pi-default", "termination-recovery", TARGET_RUNTIMES["first"])
  mutate(path, lambda value: value["results"].append(dict(value["results"][0])))
  with pytest.raises(ValueError, match="未通过生产校验"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="termination-recovery")


def test_negative_native_wrong_case_context(tmp_path):
  path = write_native(tmp_path, "pi-default", "host-resources", TARGET_RUNTIMES["first"])
  with pytest.raises(ValueError, match="case 不匹配"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="budget-permissions")


def test_negative_native_missing_command(tmp_path):
  path = write_native(tmp_path, "pi-default", "host-resources", TARGET_RUNTIMES["first"])
  mutate(path, lambda value: value.pop("command"))
  with pytest.raises(ValueError, match="native command"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="host-resources")


def test_negative_native_missing_times(tmp_path):
  path = write_native(tmp_path, "pi-default", "host-resources", TARGET_RUNTIMES["first"])
  mutate(path, lambda value: (value.pop("started_at"), value.pop("finished_at")))
  with pytest.raises(ValueError, match="(生产校验|起止时间)"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="host-resources")


def test_negative_native_live_account(tmp_path):
  path = write_native(tmp_path, "pi-default", "host-resources", TARGET_RUNTIMES["first"])
  mutate(path, lambda value: value["results"][0]["facts"].__setitem__("real_account_used", True))
  with pytest.raises(ValueError, match="real_account_used"):
    verify_native_report(path, LOCK, TARGET_RUNTIMES["first"], SOURCE, "pi-default", PLATFORM, case="host-resources")


def test_negative_cold_legacy_undecorated(tmp_path):
  run_root, report_path = make_valid_cold(tmp_path)
  mutate(report_path, lambda value: [value.pop(key) for key in ("started_at", "finished_at", "command")])
  with pytest.raises(ValueError, match="(起止时间|command)"):
    verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, "pi-default", PLATFORM)


def test_negative_cold_empty_steps(tmp_path):
  run_root, report_path = make_valid_cold(tmp_path)
  mutate(report_path, lambda value: value["targets"][0].__setitem__("steps", []))
  with pytest.raises(ValueError, match="steps"):
    verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, "pi-default", PLATFORM)


def test_negative_cold_empty_cases(tmp_path):
  run_root, report_path = make_valid_cold(tmp_path)
  mutate(report_path, lambda value: value["targets"][0].__setitem__("native_cases", []))
  with pytest.raises(ValueError, match="native_cases 与生产预期"):
    verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, "pi-default", PLATFORM)


def test_negative_cold_step_failure(tmp_path):
  run_root, report_path = make_valid_cold(tmp_path)
  mutate(report_path, lambda value: value["targets"][0]["steps"][1].__setitem__("exit_code", 5))
  with pytest.raises(ValueError, match="steps"):
    verify_cold_rebuild_report(report_path, LOCK, SOURCE, run_root, "pi-default", PLATFORM)


def test_negative_cold_foreign_lock(tmp_path):
  run_root, report_path = make_valid_cold(tmp_path)
  with pytest.raises(ValueError, match="lock_identity"):
    verify_cold_rebuild_report(report_path, "f" * 64, SOURCE, run_root, "pi-default", PLATFORM)


# ========== write_record 语义 ==========

def test_write_record_idempotent(tmp_path):
  content = {"status": "passed", "value": 1}
  assert write_record(tmp_path, "evidence.json", content) == write_record(tmp_path, "evidence.json", content) == "evidence.json"


def test_write_record_conflict(tmp_path):
  write_record(tmp_path, "evidence.json", {"status": "passed", "value": 1})
  with pytest.raises(ValueError, match="内容不同"):
    write_record(tmp_path, "evidence.json", {"status": "passed", "value": 2})


def test_write_record_rejects_symlink(tmp_path):
  target = tmp_path / "target.json"; target.write_text("{}")
  link = tmp_path / "link.json"; link.symlink_to(target)
  with pytest.raises(ValueError, match="符号链接"):
    write_record(tmp_path, "link.json", {"status": "passed"})


# ========== 主入口（临时输出根）验证 ==========

PROFILES = ("pi-default", "pi-cursor", "pi-codex", "pi-managed")
IDENTITY = {"lock_digest": LOCK, "runtime_digest": "f" * 64, "policy_digest": "0" * 64, "resource_digest": "1" * 64, "machine_contract_digest": "2" * 64}


def build_world(tmp_path, *, tamper=None):
  """生产布局的 run-root + evidence-root + mock + scope；可选破坏某 profile 的源码快照。"""
  repository = Path(__file__).resolve().parents[1]
  run_root = tmp_path / "run"; run_root.mkdir()
  for profile in PROFILES:
    for name in COLD_TARGETS:
      directory = run_root / profile / name
      for index, case in enumerate(native_cases(profile)):
        write_native(directory, profile, case, TARGET_RUNTIMES[name], index=index,
          document=native_document(profile, case, runtime=TARGET_RUNTIMES[name], index=index))
    checkout = run_root / profile / "first" / "checkout"; checkout.mkdir(parents=True)
    for file_name in ("agentcfg", "pyproject.toml", "uv.lock"):
      (checkout / file_name).write_bytes(b"synthetic frozen source " + file_name.encode())
    if tamper == profile:
      (checkout / "agentcfg").write_bytes(b"tampered candidate")
    report_path = run_root / (profile + "-cold.json")
    report_path.write_text(json.dumps(cold_document(profile)))
    source = snapshot_digest(collect_source(checkout))
    value = json.loads(report_path.read_text())
    for target in value["targets"]:
      target["source_digest"] = source
      for row in target["native_cases"]:
        native = run_root / profile / target["target"] / "native" / (row["case"] + ".json")
        document = json.loads(native.read_text())
        document["source_digest"] = source
        native.write_text(json.dumps(document))
    report_path.write_text(json.dumps(value))
  evidence_root = tmp_path / "evidence"; evidence_root.mkdir()
  make_valid_mock(evidence_root)
  from agentcfg.pi_scope import initial_scope, OPTIONAL
  scope_value = initial_scope(optional_selected={name: True for name in OPTIONAL}, created_at="2026-09-23T00:00:00.000000Z")
  scope_path = evidence_root / "scope.json"
  scope_path.write_text(json.dumps(scope_value))
  scope_path.chmod(0o600)
  return run_root, evidence_root, scope_path


def invoke(tmp_path, run_root, evidence_root, scope_path):
  return main(["--scope", str(scope_path), "--evidence-root", str(evidence_root), "--run-root", str(run_root),
    "--mock-report", str(evidence_root / "mock.json"), "--lock", LOCK], lock_anchor=LOCK,
    identity_override={profile: IDENTITY for profile in PROFILES})


def test_main_registers_valid_inputs(tmp_path, capsys):
  from agentcfg.pi_acceptance import read_scope, report
  run_root, evidence_root, scope_path = build_world(tmp_path)
  assert invoke(tmp_path, run_root, evidence_root, scope_path) == 0
  output = capsys.readouterr().out
  assert "有效 profiles: " in output and "skipped" not in output
  registered = read_scope(scope_path.with_name("scope-r2.json"))
  value = report(registered, evidence_root)
  rows = {(row["capability_id"], row["scenario_id"]): row for row in value["items"] if row["platform"]["os"] == "linux" and row["platform"]["architecture"] == "x86_64"}
  assert rows[("pi-host", "pi-default.V01-inventory")]["status"] == "passed"
  assert rows[("pi-host", "pi-default.V20-cold-rebuild")]["levels"]["native"]["status"] == "passed"
  assert rows[("pi-host", "pi-cursor.V05-resources")]["levels"]["native"]["status"] == "passed"
  # Cursor 的 readseek 是冷重建预期集的一部分（回归护栏）：证据记录的 artifact_refs 必须含两份目标的 readseek 子报告
  cursor_v20 = next(row for row in registered["items"] if row["scenario_id"] == "pi-cursor.V20-cold-rebuild")
  cold_record = next(p for p in cursor_v20["evidence_paths"] if ".native.cold." in p)
  record_value = json.loads((evidence_root / cold_record).read_text())
  assert sum(1 for ref in record_value["artifact_refs"] if "readseek-tools.json" in ref) == 2
  # managed 的 V05/V13 映射中 readseek 不适用：按配方适用 case 过滤登记，并在 limitations 说明
  managed_v05 = rows[("pi-host", "pi-managed.V05-resources")]
  assert managed_v05["levels"]["native"]["status"] == "passed"
  managed_record = next(p for p in next(i for i in registered["items"] if i["scenario_id"] == "pi-managed.V05-resources")["evidence_paths"] if ".native.cases." in p)
  assert "readseek-tools" in json.dumps(json.loads((evidence_root / managed_record).read_text())["limitations"])
  # live 项不借用本次证据：即使身份可提取也保持 not-run
  assert rows[("task-keeper", "pi-managed.live-direct.inspect-fix-review")]["status"] == "not-run"
  assert rows[("cursor", "pi-cursor.live-cursor")]["status"] == "not-run"
  assert value["release_approved"] is False


def test_main_rejects_wrong_candidate(tmp_path, capsys):
  run_root, evidence_root, scope_path = build_world(tmp_path)
  assert main(["--scope", str(scope_path), "--evidence-root", str(evidence_root), "--run-root", str(run_root),
    "--mock-report", str(evidence_root / "mock.json"), "--lock", "9" * 64], lock_anchor=LOCK) == 2


def test_main_skips_mixed_candidate_profile(tmp_path, capsys):
  from agentcfg.pi_acceptance import read_scope, report
  run_root, evidence_root, scope_path = build_world(tmp_path, tamper="pi-codex")
  assert invoke(tmp_path, run_root, evidence_root, scope_path) == 0
  output = capsys.readouterr().out
  assert "不允许混候选登记" in output
  registered = read_scope(scope_path.with_name("scope-r2.json"))
  rows = {(row["capability_id"], row["scenario_id"]): row for row in report(registered, evidence_root)["items"]
    if row["platform"]["os"] == "linux" and row["platform"]["architecture"] == "x86_64"}
  assert rows[("pi-host", "pi-codex.V01-inventory")]["status"] == "not-run"
  assert rows[("pi-host", "pi-default.V01-inventory")]["status"] == "passed"


def test_main_missing_referenced_case_blocks_cold(tmp_path, capsys):
  from agentcfg.pi_acceptance import read_scope, report
  run_root, evidence_root, scope_path = build_world(tmp_path)
  (run_root / "pi-default" / "first" / "native" / "readseek-tools.json").unlink()
  assert invoke(tmp_path, run_root, evidence_root, scope_path) == 0
  output = capsys.readouterr().out
  # 引用的 native 子报告缺失 → 整个 profile 身份提取失败，任何 V 项都不登记（不部分放行）
  assert "引用的 native 报告核验失败" in output
  registered = read_scope(scope_path.with_name("scope-r2.json"))
  rows = {(row["capability_id"], row["scenario_id"]): row for row in report(registered, evidence_root)["items"]
    if row["platform"]["os"] == "linux" and row["platform"]["architecture"] == "x86_64"}
  assert rows[("pi-host", "pi-default.V20-cold-rebuild")]["status"] == "not-run"
  assert rows[("pi-host", "pi-default.V01-inventory")]["status"] == "not-run"
  assert rows[("pi-host", "pi-cursor.V01-inventory")]["status"] == "passed"


def test_main_rejects_conflicting_rerun_and_allows_identical_rerun(tmp_path, capsys):
  run_root, evidence_root, scope_path = build_world(tmp_path)
  assert invoke(tmp_path, run_root, evidence_root, scope_path) == 0
  capsys.readouterr()
  # 完全相同的重跑：幂等复用，不产生不同内容的第二个快照
  assert invoke(tmp_path, run_root, evidence_root, scope_path) == 0
  assert "skip identical" in capsys.readouterr().out
  # 输入变化后的重跑：拒绝以不同内容覆盖既有证据
  mock_path = evidence_root / "mock.json"
  mutate(mock_path, lambda value: value.__setitem__("finished_at", "2026-09-23T03:00:00.000000Z"))
  assert invoke(tmp_path, run_root, evidence_root, scope_path) == 1


# ========== --freeze-live：真实函数路径与按项粒度 ==========

MANAGED_LIVE_ITEMS = ["pi-managed.live-direct.inspect-fix-review", "pi-managed.live-direct.second-view",
  "pi-managed.live-proxy.inspect-fix-review", "pi-managed.live-proxy.second-view"]


def make_scope(tmp_path, name="scope.json"):
  from agentcfg.pi_scope import initial_scope, OPTIONAL
  scope_value = initial_scope(optional_selected={name_: True for name_ in OPTIONAL}, created_at="2026-09-23T12:00:00.000000Z")
  path = tmp_path / name
  path.write_text(json.dumps(scope_value)); path.chmod(0o600)
  return path


def freeze_argv(scope_path, items, profile="pi-managed"):
  argv = ["--scope", str(scope_path), "--lock", LOCK, "--freeze-live", "--local", str(scope_path.parent / "local.toml"), "--profile", profile]
  for item in items: argv += ["--live-item", item]
  return argv


def test_freeze_live_requires_explicit_items(tmp_path):
  scope_path = make_scope(tmp_path)
  argv = ["--scope", str(scope_path), "--lock", LOCK, "--freeze-live", "--local", str(tmp_path / "l.toml"), "--profile", "pi-managed"]
  assert main(argv, lock_anchor=LOCK, live_identity_fn=lambda _l, _p: (IDENTITY, LOCK)) == 2
  # 传入不属于该 profile 的项 → 拒绝且不改 scope
  assert main(freeze_argv(scope_path, ["pi-default.live-mcp"]), lock_anchor=LOCK, live_identity_fn=lambda _l, _p: (IDENTITY, LOCK)) == 2
  assert not (tmp_path / "scope-r2.json").exists()


def test_freeze_live_per_route_granularity(tmp_path):
  scope_path = make_scope(tmp_path)
  assert main(freeze_argv(scope_path, MANAGED_LIVE_ITEMS[:2]), lock_anchor=LOCK,
    live_identity_fn=lambda _l, _p: (IDENTITY, LOCK)) == 0
  mid = json.loads((tmp_path / "scope-r2.json").read_text())
  rows = {row["scenario_id"]: row for row in mid["items"] if row["platform"]["os"] == "linux" and row["platform"]["architecture"] == "x86_64" and row["levels"] == ["live"]}
  assert rows["pi-managed.live-direct.inspect-fix-review"]["identity"] == IDENTITY
  assert rows["pi-managed.live-proxy.inspect-fix-review"]["identity"] is None
  assert rows["pi-default.live-mcp"]["identity"] is None
  # proxy 路线用另一身份冻结：direct 身份保留，互不波及
  other = dict(IDENTITY, runtime_digest="7" * 64)
  assert main(freeze_argv(scope_path.with_name("scope-r2.json"), MANAGED_LIVE_ITEMS[2:]), lock_anchor=LOCK,
    live_identity_fn=lambda _l, _p: (other, LOCK)) == 0
  final = json.loads((tmp_path / "scope-r2-r3.json").read_text())
  rows = {row["scenario_id"]: row for row in final["items"] if row["platform"]["os"] == "linux" and row["platform"]["architecture"] == "x86_64" and row["levels"] == ["live"]}
  assert rows["pi-managed.live-direct.inspect-fix-review"]["identity"] == IDENTITY
  assert rows["pi-managed.live-proxy.second-view"]["identity"] == other


def fake_deployment(tmp_path, monkeypatch, *, status="installed", pending=False, current="ok", generation_match=True, record_match=True, inactive=True):
  """只替换 compute_live_identity 的底层依赖；不绕过其本体。"""
  import agentcfg.workspace as W, agentcfg.deployment as D, agentcfg.runtime as RT, agentcfg.pi_lifecycle as LC, agentcfg.pi_diagnostics as DG
  from agentcfg.storage import Conflict
  import tempfile as _tf
  state = Path(_tf.mkdtemp(prefix="state-", dir=tmp_path)); state.chmod(0o700)
  if pending: (state / "pending.json").write_text("{}")
  launch = {"runtime_identity": "r" * 64, "lock_identity": LOCK, "marker": "m"}
  current_value = ({"binding": "bnd", "generation": 7, "launch": launch} if current == "ok"
    else None if current == "none" else {"binding": "bnd", "generation": 7, "launch": {"runtime_identity": "x" * 64, "lock_identity": LOCK}} if current == "runtime"
    else {"binding": "other", "generation": 7, "launch": launch})
  backend = SimpleNamespace(
    read_lock=lambda _repo: SimpleNamespace(identity=LOCK),
    runtime_identity=lambda _w, _lock: "r" * 64,
    status=lambda _w, _identity: status)
  workspace = SimpleNamespace(agent="pi", backend=backend, binding="bnd", state_root=state, resolved=SimpleNamespace(data={"profile": {"agent_options": {}}}),
    repository=tmp_path, candidate=lambda _lock: SimpleNamespace(generation=7 if generation_match else 8))
  monkeypatch.setattr(W, "load_workspace", lambda *_a, **_k: workspace)
  monkeypatch.setattr(D, "read_state", lambda _tree: {"current": current_value})
  monkeypatch.setattr(RT, "record", lambda _w, _lock: launch if record_match else {"different": True})
  def assert_inactive(_root):
    if not inactive: raise Conflict("active")
  monkeypatch.setattr(LC, "assert_inactive", assert_inactive)
  monkeypatch.setattr(DG, "diagnostic_identity", lambda _projection: IDENTITY)
  return workspace


def test_compute_live_identity_real_path_gates(tmp_path, monkeypatch):
  import agentcfg.pi_cold_rebuild  # 确认真实模块可导入（曾误从 schema 导入 Conflict）
  from agentcfg.storage import Conflict
  compute = register.compute_live_identity
  fake_deployment(tmp_path, monkeypatch, status="not-installed")
  with pytest.raises(Conflict): compute(tmp_path / "l.toml", "pi-managed")
  fake_deployment(tmp_path, monkeypatch, pending=True)
  with pytest.raises(Conflict): compute(tmp_path / "l.toml", "pi-managed")
  fake_deployment(tmp_path, monkeypatch, current="none")
  with pytest.raises(Conflict): compute(tmp_path / "l.toml", "pi-managed")
  fake_deployment(tmp_path, monkeypatch, current="runtime")
  with pytest.raises(Conflict): compute(tmp_path / "l.toml", "pi-managed")
  fake_deployment(tmp_path, monkeypatch, current="binding")
  with pytest.raises(Conflict): compute(tmp_path / "l.toml", "pi-managed")
  fake_deployment(tmp_path, monkeypatch, generation_match=False)
  with pytest.raises(Conflict): compute(tmp_path / "l.toml", "pi-managed")
  fake_deployment(tmp_path, monkeypatch, record_match=False)
  with pytest.raises(Conflict): compute(tmp_path / "l.toml", "pi-managed")
  fake_deployment(tmp_path, monkeypatch, inactive=False)
  with pytest.raises(Conflict): compute(tmp_path / "l.toml", "pi-managed")
  fake_deployment(tmp_path, monkeypatch)
  identity, lock = compute(tmp_path / "l.toml", "pi-managed")
  assert identity == IDENTITY and lock == LOCK


def test_freeze_live_end_to_end_with_real_compute(tmp_path, monkeypatch):
  from agentcfg.storage import create_new_private_file
  workspace = fake_deployment(tmp_path, monkeypatch)
  monkeypatch.setattr(register, "ROOT", Path(__file__).resolve().parents[1])
  scope_path = make_scope(tmp_path)
  assert main(freeze_argv(scope_path, MANAGED_LIVE_ITEMS), lock_anchor=LOCK) == 0
  frozen = json.loads((tmp_path / "scope-r2.json").read_text())
  assert all(row["identity"] == IDENTITY for row in frozen["items"]
    if row["scenario_id"] in MANAGED_LIVE_ITEMS and row["platform"] == {"os": "linux", "architecture": "x86_64", "engine": "node"})


# ========== live 证据登记 ==========

def live_fixture(tmp_path, *, item_identity=IDENTITY, runtime_id="f" * 64, native_mutate=None, sidecar=None, status="passed"):
  scope_path = make_scope(tmp_path, name="live-scope.json")
  scope = json.loads(scope_path.read_text())
  for row in scope["items"]:
    if row["scenario_id"] == "pi-codex.live-codex" and row["platform"] == {"os": "linux", "architecture": "x86_64", "engine": "node"}:
      row["identity"] = item_identity
  from agentcfg.activity import digest as _digest
  scope["scope_digest"] = _digest({k: v for k, v in scope.items() if k != "scope_digest"})
  scope_path.write_text(json.dumps(scope)); scope_path.chmod(0o600)
  evidence_root = tmp_path / "evidence-root"; (evidence_root / "evidence").mkdir(parents=True, exist_ok=True); evidence_root.chmod(0o700)
  runtime = {"profile": "pi-codex", "engine": "node", "platform": "linux-x86_64", "runtime_identity": runtime_id,
    "lock_identity": LOCK, "slice_identity": "c" * 64, "toolchains": {"node": "v24.14.0", "bun": "1.4.0"}}
  identity = dict(IDENTITY, runtime_digest=runtime_id, lock_digest=LOCK)
  native_doc = {"schema_version": 1, "tier": "native", "case": "codex-receipts", "status": "passed",
    "started_at": _time(0), "finished_at": _time(2), "source_digest": SOURCE,
    "runtime": runtime, "command": ["/fixture/python", "-B", "scripts/verify-pi.py", "--tier", "native", "--allow-host", "--case", "codex-receipts"],
    "results": [{"scenario_id": name, "status": "passed", "execution": {"exit_code": 0, "termination_confirmed": True},
      "facts": {"real_account_used": False}} for name in ("codex-native-readonly", "codex-native-write", "codex-native-control")]}
  native_doc = native_mutate(native_doc) if native_mutate else native_doc
  native_path = evidence_root / "native-codex.json"
  native_path.write_text(json.dumps(native_doc))
  facts = {"service_response_verified": True, "fresh_resume_verified": True,
    "cancellation_verified": True, "source_preserved": True, "termination_confirmed": True,
    "user_cli_operations": ["cancel", "poll", "probe", "result", "resume", "start", "status", "wait"], "write_verified": True}
  live_doc = {"schema_version": 1, "tier": "live", "case": "codex-receipts", "status": status,
    "started_at": _time(10), "finished_at": _time(14), "scope_digest": "e" * 64,
    "native_report_digest": register.digest(native_doc),
    "identity": identity, "runtime": runtime,
    "results": [{"scenario_id": "pi-codex.live-codex", "status": "passed" if status == "passed" else "failed", "facts": facts,
      "run_ids": ["run-" + "1" * 32, "run-" + "2" * 32, "run-" + "3" * 32, "run-" + "4" * 32]}]}
  live_path = evidence_root / "live-codex.json"; live_path.write_text(json.dumps(live_doc))
  sidecar_path = evidence_root / "sidecar.json"
  sidecar_path.write_text(json.dumps(sidecar or {"command": ["/fixture/python", "-B", "scripts/verify-pi.py", "--tier", "live",
    "--allow-host", "--allow-live", "--case", "codex-receipts", "--live-item", "pi-codex.live-codex"]}))
  argv = ["--scope", str(scope_path), "--lock", LOCK, "--live-register", "--live-item", "pi-codex.live-codex",
    "--live-report", str(live_path), "--native-report", str(native_path), "--command-sidecar", str(sidecar_path),
    "--evidence-root", str(evidence_root)]
  return argv, evidence_root, scope_path


def test_register_live_valid_input_writes_record_and_revision(tmp_path):
  argv, evidence_root, _scope = live_fixture(tmp_path)
  assert main(argv, lock_anchor=LOCK) == 0
  records = list((evidence_root / "evidence").glob("*.json"))
  assert len(records) == 1
  record = json.loads(records[0].read_text())
  assert record["level"] == "live" and record["status"] == "passed" and record["command"][0] == "/fixture/python"
  updated = json.loads((tmp_path / "live-scope-r2.json").read_text())
  row = next(r for r in updated["items"] if r["scenario_id"] == "pi-codex.live-codex" and r["platform"]["os"] == "linux" and r["platform"]["architecture"] == "x86_64")
  assert row["evidence_paths"] == ["evidence/" + records[0].name]


def taskkeeper_live_fixture(tmp_path, scenario="live-direct.inspect-fix-review", item=None, second_view=False):
  scope_path = make_scope(tmp_path, name="tk-scope.json")
  scope = json.loads(scope_path.read_text())
  target = item or ("pi-managed." + scenario)
  for row in scope["items"]:
    if row["scenario_id"] in {"pi-managed.live-direct.inspect-fix-review", "pi-managed.live-direct.second-view"} \
        and row["platform"] == {"os": "linux", "architecture": "x86_64", "engine": "node"}:
      row["identity"] = IDENTITY
  from agentcfg.activity import digest as _digest
  scope["scope_digest"] = _digest({k: v for k, v in scope.items() if k != "scope_digest"})
  scope_path.write_text(json.dumps(scope)); scope_path.chmod(0o600)
  evidence_root = tmp_path / "tk-evidence"; (evidence_root / "evidence").mkdir(parents=True, exist_ok=True); evidence_root.chmod(0o700)
  runtime = {"profile": "pi-managed", "engine": "node", "platform": "linux-x86_64", "runtime_identity": "f" * 64,
    "lock_identity": LOCK, "slice_identity": "c" * 64, "toolchains": {"node": "v24.14.0", "bun": "1.4.0"}}
  identity = dict(IDENTITY, runtime_digest="f" * 64, lock_digest=LOCK)
  native_doc = {"schema_version": 1, "tier": "native", "case": "taskkeeper-lifecycle", "status": "passed",
    "started_at": _time(0), "finished_at": _time(2), "source_digest": SOURCE, "runtime": runtime,
    "command": ["/fixture/python", "-B", "scripts/verify-pi.py", "--tier", "native", "--allow-host", "--case", "taskkeeper-lifecycle"],
    "results": [{"scenario_id": s, "status": "passed", "execution": {"exit_code": 0, "termination_confirmed": True},
      "facts": {"real_account_used": False}} for s in ("taskkeeper-inspect", "taskkeeper-fix", "taskkeeper-second-view",
        "taskkeeper-budget", "taskkeeper-quota", "taskkeeper-missing-result", "taskkeeper-pause-resume",
        "taskkeeper-stop", "taskkeeper-schedule", "taskkeeper-proxy-fix", "taskkeeper-proxy-second-view")]}
  native_path = evidence_root / "native-tk.json"; native_path.write_text(json.dumps(native_doc))
  facts = {"sdk_session": True, "capability": "task-keeper", "inspect_verified": True, "fix_verified": True,
    "checks_verified": True, "review_verified": True, "second_view_verified": second_view, "job_count": 2,
    "scope_restricted": True, "termination_confirmed": True}
  live_doc = {"schema_version": 1, "tier": "live", "case": "taskkeeper-lifecycle", "status": "passed",
    "started_at": _time(10), "finished_at": _time(12), "scope_digest": "e" * 64,
    "native_report_digest": register.digest(native_doc), "identity": identity, "runtime": runtime,
    "results": [{"scenario_id": "pi-managed." + scenario, "status": "passed", "facts": facts,
      "run_ids": ["run-" + "a" * 32, "run-" + "b" * 32]}]}
  live_path = evidence_root / "live-tk.json"; live_path.write_text(json.dumps(live_doc))
  sidecar_path = evidence_root / "sidecar.json"
  sidecar_path.write_text(json.dumps({"command": ["/fixture/python", "-B", "scripts/verify-pi.py", "--tier", "live"]}))
  argv = ["--scope", str(scope_path), "--lock", LOCK, "--live-register", "--live-item", target,
    "--live-report", str(live_path), "--native-report", str(native_path), "--command-sidecar", str(sidecar_path),
    "--evidence-root", str(evidence_root)]
  return argv, evidence_root


def test_register_live_rejects_cross_scenario_even_with_same_identity(tmp_path):
  # inspect-fix-review 的报告不得登记到 second-view 项
  argv, _ = taskkeeper_live_fixture(tmp_path, scenario="live-direct.inspect-fix-review", item="pi-managed.live-direct.second-view")
  assert main(argv, lock_anchor=LOCK) == 1
  # 反向亦然（second-view 报告指向普通项）
  argv, _ = taskkeeper_live_fixture(tmp_path, scenario="live-direct.second-view", item="pi-managed.live-direct.inspect-fix-review", second_view=True)
  assert main(argv, lock_anchor=LOCK) == 1
  assert not (tmp_path / "tk-evidence" / "live-reports").exists()
  assert not (tmp_path / "tk-scope-r2.json").exists()


def test_register_live_rejects_multiple_items(tmp_path):
  argv, _ = taskkeeper_live_fixture(tmp_path)
  assert main(argv + ["--live-item", "pi-managed.live-direct.second-view"], lock_anchor=LOCK) == 2


def test_register_live_failed_then_success_keeps_history(tmp_path):
  # 合法但执行失败 → 如实登记 failed
  argv, evidence_root = taskkeeper_live_fixture(tmp_path)
  doc = json.loads((evidence_root / "live-tk.json").read_text())
  doc["status"] = doc["results"][0]["status"] = "failed"
  from agentcfg.deployment import json_bytes as _jb
  doc["native_report_digest"] = register.digest(json.loads((evidence_root / "native-tk.json").read_text()))
  (evidence_root / "live-tk.json").write_text(json.dumps(doc))
  assert main(argv, lock_anchor=LOCK) == 0
  failed_records = list((evidence_root / "evidence").glob("*.json"))
  assert len(failed_records) == 1 and json.loads(failed_records[0].read_text())["status"] == "failed"
  after_fail = tmp_path / "tk-scope-r2.json"
  assert after_fail.exists()
  # 重复登记相同材料：幂等，不再产生新 revision
  assert main(argv, lock_anchor=LOCK) == 0
  assert not (tmp_path / "tk-scope-r3.json").exists()
  # 稍后合法成功：以当前 scope 头文件为基继续登记（链式修订）
  argv[argv.index("--scope") + 1] = str(tmp_path / "tk-scope-r2.json")
  success = json.loads((evidence_root / "live-tk.json").read_text())
  success["status"] = success["results"][0]["status"] = "passed"
  success["started_at"] = _time(20); success["finished_at"] = _time(26)
  (evidence_root / "live-tk.json").write_text(json.dumps(success))
  assert main(argv, lock_anchor=LOCK) == 0
  assert len(list((evidence_root / "evidence").glob("*.json"))) == 2
  assert json.loads(failed_records[0].read_text())["status"] == "failed"
  from agentcfg.pi_acceptance import read_scope as _rs, report as _rp
  summary = _rp(_rs(tmp_path / "tk-scope-r2-r3.json"), evidence_root)
  row = next(r for r in summary["items"] if r["scenario_id"] == "pi-managed.live-direct.inspect-fix-review"
    and r["platform"]["os"] == "linux" and r["platform"]["architecture"] == "x86_64")
  assert row["levels"]["live"]["status"] == "passed"
  # 无效材料不能覆盖有效结果
  argv[argv.index("--scope") + 1] = str(tmp_path / "tk-scope-r2-r3.json")
  bad = json.loads(json.dumps(success))
  bad["identity"] = dict(bad["identity"], policy_digest="4" * 64)
  (evidence_root / "live-tk.json").write_text(json.dumps(bad))
  assert main(argv, lock_anchor=LOCK) == 1
  assert not (tmp_path / "tk-scope-r2-r3-r4.json").exists()



  argv, _root, _scope = live_fixture(tmp_path, item_identity=dict(IDENTITY, policy_digest="3" * 64))
  assert main(argv, lock_anchor=LOCK) == 1
  argv, _root, _scope = live_fixture(tmp_path, runtime_id="8" * 64)
  assert main(argv, lock_anchor=LOCK) == 1
  argv, _root, _scope = live_fixture(tmp_path, native_mutate=lambda doc: (doc.__setitem__("status", "failed"), doc)[1])
  assert main(argv, lock_anchor=LOCK) == 1

