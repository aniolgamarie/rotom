import copy
import io
import json
from pathlib import Path
from types import SimpleNamespace

from agentcfg.presentation import _display_width, command_line, emit_result, table


class Output(io.StringIO):
  def __init__(self, tty):
    super().__init__()
    self.tty = tty

  def isatty(self):
    return self.tty


def emit(monkeypatch, payload, *, mode="auto", tty=False, args=None):
  output = Output(tty)
  monkeypatch.setattr("sys.stdout", output)
  options = args or SimpleNamespace(format=mode, machine="测试 machine", local=None, profile="omp-default")
  options.format = mode
  emit_result(payload, args=options)
  return output.getvalue()


def test_command_line_preserves_selectors_and_shell_quotes_dynamic_words():
  machine = SimpleNamespace(machine="work station", local=Path("/ignored"), profile="pi-base")
  assert command_line(machine, "run", "--cwd", "/tmp/中文 project") == (
    "./agentcfg --machine 'work station' --profile pi-base run --cwd '/tmp/中文 project'")
  local = SimpleNamespace(machine=None, local=Path("/tmp/private config.toml"), profile=None)
  assert command_line(local, "doctor", "--input", profile="omp-default") == (
    "./agentcfg --local '/tmp/private config.toml' --profile omp-default doctor --input")


def test_json_modes_are_exact_compatible_and_do_not_mutate(monkeypatch):
  payload = {"profile": "中文", "command": "validate", "valid": True,
    "nested": {"z": 1}, "agent": "dsh"}
  original = copy.deepcopy(payload)
  expected = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
  assert emit(monkeypatch, payload, mode="json", tty=True) == expected
  assert emit(monkeypatch, payload, mode="auto", tty=False) == expected
  assert payload == original


def test_missing_format_defaults_to_auto(monkeypatch):
  output = Output(False)
  monkeypatch.setattr("sys.stdout", output)
  payload = {"command": "lock", "agent": "omp", "locked": True}
  emit_result(payload, args=SimpleNamespace(machine=None, local=None, profile=None))
  assert output.getvalue() == json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"


def test_explicit_human_and_auto_tty_are_readable(monkeypatch):
  payload = {"command": "validate", "agent": "dsh", "profile": "中文配置", "instance": "/private",
    "valid": True, "artifacts": 3, "profiles_checked": 2, "credentials": "not-checked-offline"}
  for mode, tty in (("human", False), ("auto", True)):
    output = emit(monkeypatch, payload, mode=mode, tty=tty)
    assert "validate：配置有效" in output
    assert "中文配置" in output and "产物" in output and "3" in output
    assert "未检查（离线）" in output
    assert not output.lstrip().startswith("{")


def test_table_aligns_chinese_and_switches_to_vertical_without_truncation():
  wide = io.StringIO()
  table(("名称", "状态"), (("中文", "ok"), ("a", "ready")), stream=wide, width=80)
  lines = wide.getvalue().splitlines()
  assert len({_display_width(line.split("|")[0]) for line in (lines[0], lines[2], lines[3])}) == 1
  narrow = io.StringIO()
  identifier = "location-" + "a" * 64
  table(("类型", "位置 ID", "目标"), (("冲突", identifier, "<managed-resource>"),), stream=narrow, width=20)
  assert "条目 1" in narrow.getvalue()
  assert identifier in narrow.getvalue()
  assert "…" not in narrow.getvalue()


def test_common_fields_use_compact_aligned_definition_lines(monkeypatch):
  output = emit(monkeypatch, {"command": "render", "agent": "dsh", "profile": "中文配置",
    "artifacts": 2, "cache": "/tmp/" + "long-path-" * 20}, mode="human")
  lines = output.splitlines()
  target = next(line for line in lines if line.startswith("目标"))
  artifacts = next(line for line in lines if line.startswith("产物"))
  assert _display_width(target.split("dsh")[0]) == _display_width(artifacts.split("2")[0])
  assert "字段 | 值" not in output and "条目 1" not in output


def test_plan_uses_public_location_ids_and_never_prints_values(monkeypatch):
  payload = {"command": "plan", "agent": "pi", "profile": "pi-base", "instance": "/instance",
    "changes": 1, "drift": 1, "conflicts": 0, "dependencies": "sync-required",
    "diagnostics": "/cache/locations.json",
    "diff": [{"id": "public-change-id", "target": "<managed-resource>", "field": "<managed-field>",
      "action": "update", "value": "SECRET_CANARY"}],
    "drift_targets": [{"id": "public-drift-id", "target": "<managed-resource>", "field": None}],
    "conflict_targets": []}
  output = emit(monkeypatch, payload, mode="human")
  assert "待变更" in output and "漂移" in output and "依赖" in output
  assert "public-change-id" in output and "public-drift-id" in output
  assert "SECRET_CANARY" not in output and "<redacted>" not in output
  assert "/cache/locations.json" in output


def test_doctor_prioritizes_readiness_without_treating_auth_as_failure(monkeypatch):
  ready = {"command": "doctor", "agent": "omp", "profile": "omp-default", "deployed": True,
    "dependencies": "installed", "deployed_dependencies": "installed", "recovery_pending": False,
    "drift": False, "conflicts": False, "changes_pending": 0,
    "authentication": "not-inspected; use native auth status",
    "readiness": {"status": "offline-ready", "blockers": [], "next_commands": [],
      "authentication": "not-inspected"}}
  output = emit(monkeypatch, ready, mode="human")
  assert "doctor：离线就绪" in output
  assert "账号登录与模型服务" in output and "未验证" in output
  assert "认证失败" not in output and "not-inspected" not in output

  blocked = copy.deepcopy(ready)
  blocked.update(recovery_pending=True, dependencies="sync-required")
  blocked["readiness"] = {"status": "action-required",
    "blockers": ["recovery-pending", "dependencies-sync-required"],
    "next_commands": ["apply-or-rollback", "sync"], "authentication": "not-inspected"}
  output = emit(monkeypatch, blocked, mode="human")
  assert "doctor：需要处理" in output and "存在待恢复的部署操作" in output
  assert "当前依赖需要同步" in output and "recovery-pending" not in output
  assert "./agentcfg --machine '测试 machine' --profile omp-default apply" in output
  assert " rollback" in output and " sync" in output


def test_doctor_input_extracts_real_omp_event_shape_and_advice(monkeypatch):
  payload = {"command": "doctor", "agent": "omp", "profile": "omp-default", "deployed": False,
    "dependencies": "unknown", "recovery_pending": False,
    "input_diagnostics": {"diagnostic_terminal": {"stdin_tty": True, "canonical": False, "echo": False, "signals": True},
      "readiness": {"status": "action-required", "blockers": ["not-deployed"], "next_commands": ["setup"]},
      "note": "SECRET_CANARY",
      "host_events": {"logs_present": True, "logs_checked": 2, "logs_status": "some-logs-unavailable",
        "loop_blocks": [{"timestamp": "2026-09-27T12:00:00.000+08:00", "pid": 123,
          "blocked_ms": 429, "cpu_ms": 288, "phase": "render", "private": "SECRET_CANARY"}],
        "note": "SECRET_CANARY"}}}
  output = emit(monkeypatch, payload, mode="human")
  assert "doctor：需要处理" in output and "尚未部署配置" in output
  assert "./agentcfg --machine '测试 machine' --profile omp-default setup" in output
  assert "诊断 stdin 为终端" in output and "OMP 日志存在" in output and "循环阻塞事件" in output
  assert "2026-09-27T12:00:00.000+08:00" in output and "渲染" in output and "429" in output
  assert "部分日志不可用" in output and "OMP 建议" in output and "诊断说明" in output
  assert "SECRET_CANARY" not in output


def test_validate_profile_list_uses_readable_join_without_repr(monkeypatch):
  payload = {"command": "validate", "agent": "dsh", "profile": "dsh-default", "valid": True,
    "artifacts": 2, "profiles_checked": ["dsh-default", "pi-base"],
    "credentials": "not-checked-offline"}
  output = emit(monkeypatch, payload, mode="human")
  assert "dsh-default、pi-base" in output
  assert "['dsh-default'" not in output


def test_doctor_generic_host_status_uses_fixed_safe_advice(monkeypatch):
  payload = {"command": "doctor", "agent": "pi", "profile": "pi-base", "deployed": False,
    "dependencies": "unknown", "recovery_pending": False,
    "readiness": {"status": "action-required", "blockers": ["lock-missing-or-invalid"],
      "next_commands": ["lock --agent pi"]},
    "input_diagnostics": {"diagnostic_terminal": {"stdin_tty": False, "canonical": None,
      "echo": None, "signals": None}, "host_events": {"status": "not-checked", "reason": "SECRET_CANARY"}}}
  output = emit(monkeypatch, payload, mode="human")
  assert "依赖锁缺失或无效" in output and "尚未检查宿主输入事件" in output
  assert "./agentcfg --machine '测试 machine' --profile pi-base lock --agent pi" in output
  assert "SECRET_CANARY" not in output


def test_doctor_feature_declarations_use_fixed_labels_without_claiming_loaded(monkeypatch):
  payload = {"command": "doctor", "agent": "pi", "profile": "pi-base", "deployed": True,
    "dependencies": "installed", "recovery_pending": False,
    "readiness": {"status": "offline-ready", "blockers": [], "next_commands": []},
    "feature_readiness": {
      "status_bar": {"status": "not_ready", "decision": "held", "candidate": "SECRET_CANARY"},
      "collaboration": {"status": "not_ready", "decision": "held", "requested": "SECRET_CANARY"},
      "optional_modules": {"status": "not_selected", "decision": "candidate", "selected": ["SECRET_CANARY"]}}}
  output = emit(monkeypatch, payload, mode="human")
  assert "功能声明（不代表已加载）" in output
  assert "状态栏信息对齐" in output and "Pro调查协作" in output and "按需模块" in output
  assert "未就绪；暂停准入" in output and "未选择；候选" in output
  assert "SECRET_CANARY" not in output


def test_doctor_approval_preview_preserves_unknown_runtime_and_audit_limits(monkeypatch):
  payload = {"command": "doctor", "agent": "dsh", "profile": "dsh-default", "deployed": True,
    "dependencies": "installed", "recovery_pending": False,
    "readiness": {"status": "offline-ready", "blockers": [], "next_commands": []},
    "approval_review": {"scope": "configuration-preview", "enabled": True,
      "sandbox_escalation": True, "reviewer_timeout_ms": 90000, "max_reviews_per_turn": 3,
      "max_failures_per_turn": 1, "fallback_policy": "delegate",
      "persistent_verdict_audit": "unsupported", "runtime_checked": False,
      "reason": "SECRET_CANARY"}}
  output = emit(monkeypatch, payload, mode="human")
  assert "审批配置预览（不代表当前会话状态）" in output
  assert "待批沙箱提权" in output and "AI 审查" in output
  assert "90000" in output and "每回合失败预算" in output and "转人工" in output
  assert "完整 AI 判决持久审计" in output and "不支持" in output
  assert "当前会话的实际分流与回退原因" in output and "未检查" in output
  assert "SECRET_CANARY" not in output
  payload["approval_review"]["reviewer_timeout_ms"] = "SECRET_CANARY"
  payload["approval_review"]["enabled"] = False
  output = emit(monkeypatch, payload, mode="human")
  assert "人工处理" in output and "SECRET_CANARY" not in output


def test_doctor_live_summarizes_real_service_checks_without_offline_claim(monkeypatch):
  payload = {"command": "doctor", "agent": "pi", "profile": "pi-base", "deployed": True,
    "dependencies": "installed", "deployed_dependencies": "installed", "recovery_pending": False,
    "drift": False, "conflicts": False, "changes_pending": 0, "live": True,
    "readiness": {"status": "offline-ready", "blockers": [], "next_commands": []},
    "service_checks": [
      {"location_id": "route:" + "c" * 20, "status": "reachable", "http_status": 401,
        "private": "SECRET_CANARY"},
      {"location_id": "provider:" + "d" * 20, "status": "unverified",
        "reason": "explicit-route-required", "private": "SECRET_CANARY"}]}
  output = emit(monkeypatch, payload, mode="human")
  assert "doctor：在线检查完成，部分未验证" in output and "离线就绪" not in output
  assert "基础部署检查通过" in output
  assert "HTTP 可达" in output and "401" in output and "需要显式网络路线" in output
  assert "账号登录与模型调用" in output and "只验证显式路线" in output
  assert "route:" + "c" * 20 in output and "provider:" + "d" * 20 in output
  assert "SECRET_CANARY" not in output


def test_proposals_recovery_and_main_results_keep_semantics(monkeypatch):
  cases = [
    ({"command": "inventory", "agent": "omp", "profile": "omp-default", "items": 8,
      "ready_to_deploy": False, "proposal": "/tmp/review"}, ("尚未部署", "盘点条目", "/tmp/review")),
    ({"command": "plan", "agent": "pi", "profile": "pi-base", "mode": "migration-preview",
      "items": 4, "blockers": 2, "ready_to_deploy": False, "proposal": "/tmp/inventory.json"},
      ("迁移提案", "阻塞项", "/tmp/inventory.json")),
    ({"command": "rollback", "agent": "dsh", "profile": "dsh-default", "restored": 3},
      ("上一版已恢复", "已恢复项", "3")),
  ]
  for payload, expected in cases:
    output = emit(monkeypatch, payload, mode="human")
    assert all(value in output for value in expected)


def test_failure_shaped_results_are_not_reported_as_success(monkeypatch):
  for payload, absent in (
    ({"command": "lock", "agent": "omp", "locked": False}, "依赖锁已生成"),
    ({"command": "validate", "agent": "dsh", "profile": "dsh-default", "valid": False}, "配置有效"),
  ):
    assert absent not in emit(monkeypatch, payload, mode="human")


def test_sync_false_means_no_new_install(monkeypatch):
  sync = emit(monkeypatch, {"command": "sync", "agent": "pi", "profile": "pi-base",
    "installed": False, "identity": "public-runtime-id"}, mode="human")
  assert "依赖同步完成" in sync and "本次安装" in sync and "否" in sync


def test_plan_prioritizes_conflict_and_drift_locations_before_changes(monkeypatch):
  payload = {"command": "plan", "agent": "dsh", "profile": "dsh-default", "changes": 9,
    "drift": 1, "conflicts": 1, "dependencies": "installed", "diagnostics": "/tmp/locations.json",
    "diff": [{"id": f"change-{index}", "target": "<managed-resource>", "field": None,
      "action": "update", "value": "<redacted>"} for index in range(9)],
    "drift_targets": [{"id": "drift-priority", "target": "<managed-resource>", "field": None}],
    "conflict_targets": [{"id": "conflict-priority", "target": "<managed-resource>", "field": None}]}
  output = emit(monkeypatch, payload, mode="human")
  assert "conflict-priority" in output and "drift-priority" in output
  assert "change-0" in output and "change-5" in output and "change-6" not in output


def test_simple_results_do_not_repeat_json_hint(monkeypatch):
  output = emit(monkeypatch, {"command": "render", "agent": "dsh", "profile": "dsh-default",
    "artifacts": 2, "cache": "/tmp/rendered"}, mode="human")
  assert "原生产物已生成" in output
  assert "--format json" not in output


def test_doctor_environment_is_visible_in_terminal_and_never_dumps_values(monkeypatch):
  payload = {"command": "doctor", "agent": "dsh", "profile": "dsh-default",
    "environment": {"status": "host-preview", "policy": "isolated", "declarations_pending": True,
      "sensitive_excluded": 2, "value": "PRIVATE_ENVIRONMENT_CANARY", "variables": [
        {"name": "HOME", "status": "overridden", "source": "adapter-policy", "value": "PRIVATE_HOME_CANARY"},
        {"name": "CUSTOM_BUILD_ROOT", "status": "removed", "source": "not-inherited"},
        {"name": "PRIVATE_API_KEY", "status": "removed", "source": "not-inherited"}]}}
  for mode, tty in (("human", False), ("auto", True)):
    output = emit(monkeypatch, payload, mode=mode, tty=tty)
    assert "环境诊断" in output and "独立宿主" in output and "环境声明待部署" in output
    assert "HOME" in output and "CUSTOM_BUILD_ROOT" in output and "适配器策略" in output
    assert "PRIVATE_" not in output
