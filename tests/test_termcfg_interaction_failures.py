"""真实临时机器的失败链：下一步与副作用必须符合已经发生的事实。"""

import json
import shlex

import pytest

from termcfg import cli, transaction
from termcfg.config import encode_machine, machine_path, read_machine
from termcfg.preview import build_preview
from termcfg.state import journal_file, read_journal, read_state, state_file, write_json


MACHINE = "workstation"


def initialize(capsys):
  assert cli.main(["--machine", MACHINE, "init-local", "--component", "zsh", "--json"]) == 0
  capsys.readouterr()
  return read_machine(MACHINE)


def parse_hint(value):
  words = shlex.split(value)
  assert words.pop(0) == "./termcfg"
  return cli.build_parser().parse_args(words)


def legacy_with_pending(capsys, *, proxy):
  machine = initialize(capsys)
  if proxy:
    path = machine_path(MACHINE)
    path.write_bytes(encode_machine(machine).replace(b'["zsh"]', b'["zsh", "mihomo"]'))
  old = {"version": 1, "machine_id": MACHINE, "selected_core": "a" * 64,
    "public_config_identity": None, "pending_core_effect": True, "pending_config_effect": True,
    "targets": {"mihomo-base": {"component": "mihomo", "after": {"kind": "absent"}, "source_digest": "b" * 64}},
    "previous": {"mihomo": {"mihomo-base": {"before": {"kind": "absent"}, "path": None}}}}
  write_json(state_file(machine), old)
  journal = {"version": 1, "kind": "apply", "transaction_id": "a" * 32,
    "phase": "prepared", "plan_id": "b" * 64, "state_before": old,
    "items": [{"target_id": "mihomo-base", "component": "mihomo",
      "relative": ".config/termcfg/mihomo/base.yaml", "before": {"kind": "absent"},
      "desired": None, "mode": None, "backup": None, "after": None, "stage": "pending"}]}
  write_json(journal_file(machine), journal)
  return machine


@pytest.mark.parametrize("words", [
  ["doctor"], ["plan"], ["sync", "--component", "zsh"],
  ["apply", "--plan-id", "b" * 64], ["rollback", "--component", "zsh", "--plan-id", "b" * 64],
  ["init-local", "--edit", "--component", "zsh"],
])
@pytest.mark.parametrize("proxy", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
def test_legacy_entry_does_not_schedule_migration_before_recovery(words, proxy, json_mode, capsys):
  machine = legacy_with_pending(capsys, proxy=proxy)
  before = state_file(machine).read_bytes()
  assert cli.main(["--machine", MACHINE, *words, *(["--json"] if json_mode else [])]) == 4
  text = capsys.readouterr().out
  if json_mode:
    result = json.loads(text)
    assert result["reason"] == "legacy_migration_required"
    suggestion = parse_hint(result["next_command"])
    assert suggestion.machine == MACHINE
    assert suggestion.command in {"status", "recover"}
  else:
    assert "旧所有权元数据" in text
    assert "./termcfg --machine workstation migrate" not in text
    assert any(f"./termcfg --machine workstation {name}" in text for name in ("status", "recover"))
  assert state_file(machine).read_bytes() == before
  assert read_journal(machine) is not None
  # 未确认恢复事实的入口先观察；观察后必须把恢复置于迁移之前。
  assert cli.main(["--machine", MACHINE, "status", "--json"]) == 0
  status = json.loads(capsys.readouterr().out)
  assert status["recovery_pending"] is True
  assert parse_hint(status["next_command"]).command == "recover"


@pytest.mark.parametrize("json_mode", [False, True])
def test_failed_recovery_keeps_drift_inspection_instead_of_retry(monkeypatch, fake_terminal_commands, capsys, json_mode):
  machine = initialize(capsys)
  plan = build_preview(machine, ("zsh",))
  original = transaction.atomic_target_bytes
  def crash(*args, **kwargs):
    original(*args, **kwargs)
    raise OSError("synthetic write interruption")
  monkeypatch.setattr(transaction, "atomic_target_bytes", crash)
  assert cli.main(["--machine", MACHINE, "apply", "--plan-id", plan.plan_id, "--json"]) == 6
  capsys.readouterr()
  monkeypatch.setattr(transaction, "atomic_target_bytes", original)
  journal = read_journal(machine)
  target = machine.target_home / journal["items"][0]["relative"]
  target.write_text("synthetic external edit\n")
  assert cli.main(["--machine", MACHINE, "recover", *(["--json"] if json_mode else [])]) == 4
  text = capsys.readouterr().out
  if json_mode:
    result = json.loads(text)
    assert result["reason"] == "recovery_target_drift"
    assert result["side_effect"] == "recovery_pending"
    assert result["transaction_id"] == journal["transaction_id"]
    next_args = parse_hint(result["next_command"])
    assert next_args.command == "status" and next_args.machine == MACHINE
  else:
    assert "保留现场" in text and "不强行恢复" in text
    assert text.index("保留现场") < text.index("下一步")
    assert "./termcfg --machine workstation status" in text
    assert "./termcfg --machine workstation recover" not in text
  assert target.read_text() == "synthetic external edit\n"
  assert read_journal(machine) is not None


@pytest.mark.parametrize("command", ["apply", "rollback"])
@pytest.mark.parametrize("json_mode", [False, True])
def test_post_commit_interrupt_does_not_claim_unchanged_home(command, json_mode, monkeypatch, fake_terminal_commands, capsys):
  machine = initialize(capsys)
  plan_id = build_preview(machine, ("zsh",)).plan_id
  if command == "rollback":
    assert cli.main(["--machine", MACHINE, "apply", "--plan-id", plan_id, "--json"]) == 0
    capsys.readouterr()
    plan_id = transaction.rollback_preview(machine, "zsh")["plan_id"]
  before = read_state(machine)
  def interrupt(*args, **kwargs):
    raise KeyboardInterrupt()
  monkeypatch.setattr(transaction, "_clean_old_backups", interrupt)
  args = ["--machine", MACHINE, command, "--component", "zsh", "--plan-id", plan_id]
  assert cli.main([*args, *(["--json"] if json_mode else [])]) == 6
  text = capsys.readouterr().out
  assert read_journal(machine) is None
  assert read_state(machine) != before
  assert (machine.target_home / ".zshrc").exists() is (command == "apply")
  if json_mode:
    result = json.loads(text)
    assert result["reason"] == "interrupted" and result["stage"] == "commit"
    assert result["side_effect"] == "check_home_and_transaction_state"
    next_args = parse_hint(result["next_command"])
    assert next_args.command == "status" and next_args.machine == MACHINE
  else:
    assert "未报告 HOME 写入" not in text
    assert "可能已有" in text
    assert "清理" in text and "未验证" in text
    assert text.index("影响：") < text.index("下一步")


@pytest.mark.parametrize("editing", [False, True])
@pytest.mark.parametrize("json_mode", [False, True])
def test_cancelled_initialization_retries_correct_creation_mode(editing, json_mode, monkeypatch, capsys):
  if editing:
    initialize(capsys)
  path = machine_path(MACHINE)
  before = path.read_bytes() if editing else None
  monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
  monkeypatch.setattr(cli, "_confirm", lambda message: False)
  words = ["--machine", MACHINE, "init-local", "--component", "tmux", *(["--edit"] if editing else [])]
  assert cli.main([*words, *(["--json"] if json_mode else [])]) == 4
  text = capsys.readouterr().out
  assert path.exists() is editing
  if editing:
    assert path.read_bytes() == before
  if json_mode:
    result = json.loads(text)
    assert result["reason"] == "confirmation_declined"
    next_args = parse_hint(result["next_command"])
    assert next_args.machine == MACHINE and next_args.command == "init-local"
    assert next_args.edit is editing and next_args.component == ["tmux"]
  else:
    assert "已取消确认" in text
    assert "./termcfg --machine workstation init-local" in text
    assert ("--edit" in text) is editing
