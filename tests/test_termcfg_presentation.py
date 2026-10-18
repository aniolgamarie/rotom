"""终端摘要不重新采集事实，也不展开未知或私人结构。"""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from termcfg.diagnostics import emit
from termcfg.presentation import render_result


CONTEXT = {"machine": "workstation", "components": ("zsh", "tmux"), "diagnostic_home": False}


def environment(**changes):
  value = {"status": "ready", "ready": True, "required_blockers": [],
    "optional_degradations": [], "unverified": [], "target_issues": {},
    "next_command": "./termcfg --machine workstation plan --component zsh"}
  value.update(changes)
  return value


def test_json_payload_is_unchanged_and_single_object(capsys):
  result = {"command": "status", "ready": False, "overall_ready": False,
    "components": {"zsh": environment(status="blocked", required_blockers=["required_program_missing"])},
    "unknown": {"private": "PRIVATE-CANARY"}, "next_command": "./termcfg --machine workstation doctor"}
  before = deepcopy(result)
  emit(result, json_mode=True, context=CONTEXT)
  output = capsys.readouterr()
  assert json.loads(output.out) == result == before
  assert len(output.out.splitlines()) == 1
  assert not output.err


def test_human_result_is_an_allowlist_not_repr_or_recursive_dump():
  class Dangerous:
    def __str__(self):
      raise AssertionError("must not stringify unknown objects")
    __repr__ = __str__
  result = {"command": "status", "ready": True, "overall_ready": True,
    "components": {"zsh": environment(private="PRIVATE-CANARY", opaque=Dangerous()),
                   "PRIVATE-CANARY": {"body": Dangerous()}},
    "package": "/PRIVATE-CANARY", "private_file": "/PRIVATE-CANARY", "unknown": Dangerous()}
  text = render_result(result, context=CONTEXT)
  assert "PRIVATE-CANARY" not in text
  assert "workstation" in text
  assert "zsh" in text
  assert "{'" not in text


@pytest.mark.parametrize("state, facts, expected", [
  ("blocked", {"required_blockers": ["required_program_missing"]}, "必需"),
  ("degraded", {"optional_degradations": ["optional_plugins_not_synced"]}, "可选"),
  ("unverified", {"unverified": ["private_hook_metadata_unverified"]}, "未验证"),
  ("ready", {}, "未发现必需阻塞"),
])
def test_environment_states_remain_distinct(state, facts, expected):
  result = {"command": "doctor", "ready": state != "blocked", "overall_ready": state != "blocked",
    "components": {"zsh": environment(status=state, **facts)}, "next_command": "./termcfg doctor"}
  text = render_result(result, context=CONTEXT)
  assert expected in text
  if state == "blocked":
    assert "自行准备" in text and "自动安装" in text
  if state == "degraded":
    assert "降级" in text and "未发现必需阻塞" in text


def test_plan_keeps_consent_ids_backup_and_unknown_readiness_separate():
  plan_id = "a" * 64
  result = {"command": "plan", "ready": True, "overall_ready": True, "plan_id": plan_id,
    "targets": [{"target_id": "zshenv", "component": "zsh", "path": "PRIVATE-CANARY",
                 "action": "adopt-required", "reason": "unmanaged_target", "backup": True}],
    "next_command": "./termcfg --machine workstation apply --component zsh"}
  text = render_result(result, context=CONTEXT)
  assert plan_id in text and "zshenv" in text
  assert "接管" in text and "备份" in text and "确认" in text
  assert "--confirm-zshenv" in text
  assert "PRIVATE-CANARY" not in text
  assert "已授权" not in text


def test_partial_failure_recovery_and_phase_precede_next_command():
  result = {"command": "apply", "ready": False, "overall_ready": False,
    "reason": "filesystem_failure", "side_effect": "recovery_pending",
    "transaction_id": "b" * 32, "transaction_phase": "recovery_pending",
    "component": "zsh", "target_id": "zshrc", "stage": "write",
    "next_command": "./termcfg --machine workstation recover"}
  text = render_result(result, context=CONTEXT)
  assert "部分" in text and "待恢复" in text
  assert "b" * 32 in text and "zshrc" in text
  assert text.index("待恢复") < text.index("./termcfg")


def test_status_keeps_all_target_and_transaction_facts():
  result = {"command": "status", "ready": False, "overall_ready": False, "recovery_pending": True,
    "components": {"zsh": environment(status="blocked", files={"zshrc": "drift", "zshenv": "conflict"},
                                      previous_backup=True, required_blockers=["recovery_pending"])},
    "transaction": {"transaction_id": "c" * 32, "phase": "writing", "items": [
      {"target_id": "zshrc", "component": "zsh", "stage": "pending"}]},
    "next_command": "./termcfg --machine workstation recover"}
  text = render_result(result, context=CONTEXT)
  for value in ("zshrc", "zshenv", "drift", "conflict", "writing", "pending", "c" * 32):
    assert value in text
  assert "上一版备份" in text


@pytest.mark.parametrize("command, fields, expected", [
  ("init-local", {"components": ["zsh"]}, "选择已保存"),
  ("sync", {"component": "zsh", "prepared": ["zinit"]}, "插件已准备"),
  ("lock", {"component": "zsh", "plugin": "zinit", "commit": "d" * 40}, "仓库插件锁已保存"),
  ("apply", {"changed": ["zshrc"], "unchanged": ["zshenv"]}, "配置已写入"),
  ("apply", {"changed": [], "unchanged": ["zshrc", "zshenv"]}, "无需写入"),
  ("rollback", {"component": "zsh", "restored": ["zshrc"]}, "上一版配置已恢复"),
  ("recover", {"recovered": False, "reason": "no_recovery_pending"}, "没有待恢复事务"),
  ("migrate", {"migrated": True}, "元数据已迁移"),
])
def test_completion_feedback_is_specific_not_environment_health(command, fields, expected):
  text = render_result({"command": command, "ready": True, "overall_ready": True, **fields}, context=CONTEXT)
  assert expected in text
  assert "环境已就绪" not in text
  if command in ("apply", "rollback"):
    assert "未重启" in text


def test_cleanup_pending_and_private_content_prerequisites_are_visible():
  text = render_result({"command": "apply", "ready": True, "cleanup_pending": True, "changed": ["zshrc"]})
  assert "清理" in text
  text = render_result({"command": "plan", "ready": False, "reason": "possible_private_content",
                        "next_command": "./termcfg plan"})
  assert "0600" in text and "私人值" in text
  assert text.index("私人值") < text.index("./termcfg")


def test_diagnostic_home_is_labeled_without_echoing_path():
  text = render_result({"command": "plan", "plan_id": "e" * 64, "targets": [], "ready": True,
                        "next_command": "./termcfg --machine workstation plan"},
                       context={**CONTEXT, "diagnostic_home": True})
  assert "--home" in text and "保存" in text and "不授权" in text


def test_unknown_reason_codes_and_missing_state_are_not_healthy():
  text = render_result({"command": "doctor", "reason": "future_reason"})
  assert "future_reason" in text
  assert "未发现必需阻塞" not in text
  assert "PRIVATE-CANARY" not in render_result({"reason": "PRIVATE-CANARY/path", "ready": None})


@pytest.mark.parametrize("control", ["\t", "\n", "\r", "\x1b", "\x7f", "\u202e"])
@pytest.mark.parametrize("slot", ["top", "component"])
def test_unrepresentable_commands_use_help_without_changing_json(control, slot, capsys):
  suggestion = "./termcfg plan --home '/synthetic/A" + control + "B'"
  payload = {"command": "plan", "plan_id": "a" * 64, "targets": []}
  if slot == "top":
    payload["next_command"] = suggestion
  else:
    payload["environment"] = {"zsh": environment(next_command=suggestion)}
  before = deepcopy(payload)
  text = render_result(payload)
  assert "不能原样复制" in text
  assert [line.strip() for line in text.splitlines() if line.startswith("  ./termcfg")] == ["./termcfg plan --help"]
  assert all(value not in text for value in ("\x1b", "\r", "\t", "\x7f", "\u202e"))
  assert "/synthetic/" not in text and "a" * 64 in text
  assert payload == before
  emit(payload, json_mode=True)
  assert json.loads(capsys.readouterr().out) == before


def test_literal_backslash_in_command_is_not_reinterpreted():
  suggestion = "./termcfg doctor --home '/synthetic/A\\tB'"
  text = render_result({"command": "doctor", "next_command": suggestion})
  assert "不能原样复制" not in text
  assert "  " + suggestion in text.splitlines()


@pytest.mark.parametrize("command, expected", [
  ("future-command", "./termcfg --help"), ("rollback-plan", "./termcfg rollback --help"),
])
def test_unrepresentable_command_fallback_uses_registered_help(command, expected):
  text = render_result({"command": command, "next_command": "unknown\tcommand"})
  assert "不能原样复制" in text
  assert "  " + expected in text.splitlines()
  assert "unknown" not in text and "future-command" not in text


def test_rendering_does_not_probe_files_or_terminal(monkeypatch):
  import os
  import shutil
  def forbidden(*args, **kwargs):
    pytest.fail("renderer must use collected facts only")
  # 仅覆盖展示调用；结束后恢复，保证全局文件哨兵仍能正常检查未改变。
  with monkeypatch.context() as guarded:
    guarded.setattr(Path, "stat", forbidden)
    guarded.setattr(Path, "open", forbidden)
    guarded.setattr(shutil, "get_terminal_size", forbidden)
    guarded.setattr(shutil, "which", forbidden)
    guarded.setattr(os, "get_terminal_size", forbidden)
    text = render_result({"command": "doctor", "ready": True, "components": {"zsh": environment()}}, context=CONTEXT)
    assert "zsh" in text
