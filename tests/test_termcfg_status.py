"""状态、严格环境检查和诊断结果的隔离契约。"""

import json

from termcfg.cli import main
from termcfg.config import read_machine
from termcfg.preview import build_preview
from termcfg.state import read_state, state_file, write_json


def test_doctor_strict_reports_missing_required_program(isolated_environment, capsys):
  assert main(["init-local", "--component", "zsh"]) == 0
  capsys.readouterr()
  assert main(["doctor", "--component", "zsh", "--strict", "--json"]) == 5
  result = json.loads(capsys.readouterr().out)
  assert result["overall_ready"] is False
  assert result["components"]["zsh"]["status"] == "blocked"
  assert "required_program_missing" in result["components"]["zsh"]["required_blockers"]
  assert result["next_command"]


def test_offline_plan_apply_status_and_drift(isolated_environment, fake_terminal_commands, capsys):
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  capsys.readouterr()
  assert main(["doctor", "--component", "zsh", "--json"]) == 0
  assert json.loads(capsys.readouterr().out)["components"]["zsh"]["ready"] is True
  assert main(["plan", "--component", "zsh", "--json"]) == 0
  assert json.loads(capsys.readouterr().out)["plan_id"] == plan.plan_id
  assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id]) == 0
  capsys.readouterr()
  assert main(["status", "--component", "zsh", "--json"]) == 0
  result = json.loads(capsys.readouterr().out)
  assert set(result["components"]["zsh"]["files"].values()) == {"synced"}
  (isolated_environment.home / ".zshrc").write_text("synthetic local change\n")
  assert main(["status", "--component", "zsh", "--json"]) == 0
  result = json.loads(capsys.readouterr().out)
  assert result["components"]["zsh"]["files"]["zshrc"] == "conflict"
  assert result["overall_ready"] is False
  assert "target_drift" in result["components"]["zsh"]["required_blockers"]


def test_pending_effect_causes_are_separate(isolated_environment, capsys):
  assert main(["init-local", "--component", "mihomo"]) == 0
  machine = read_machine("default")
  state = read_state(machine)
  state["pending_core_effect"] = True
  state["pending_config_effect"] = False
  write_json(state_file(machine), state)
  capsys.readouterr()
  assert main(["status", "--component", "mihomo", "--json"]) == 0
  result = json.loads(capsys.readouterr().out)
  info = result["components"]["mihomo"]
  assert info["pending_core_effect"] is True
  assert info["pending_config_effect"] is False


def test_plan_ready_reflects_required_environment(isolated_environment, capsys):
  assert main(["init-local", "--component", "mihomo"]) == 0
  capsys.readouterr()
  assert main(["plan", "--component", "mihomo", "--json"]) == 0
  result = json.loads(capsys.readouterr().out)
  assert result["overall_ready"] is False
  assert result["environment"]["mihomo"]["ready"] is False


def test_failure_reports_component_and_next_command(isolated_environment, capsys):
  assert main(["init-local", "--component", "mihomo"]) == 0
  capsys.readouterr()
  assert main(["sync", "--component", "mihomo", "--timeout", "1", "--json"]) == 2
  result = json.loads(capsys.readouterr().out)
  assert result["command"] == "sync"
  assert result["component"] == "mihomo"
  assert result["reason"] == "invalid_timeout"
  assert result["next_command"]


def test_interrupted_apply_reports_recovery_transaction(isolated_environment, fake_terminal_commands,
                                                        monkeypatch, capsys):
  from termcfg import transaction
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  original = transaction.atomic_target_bytes
  def crash_after_replace(*args, **kwargs):
    original(*args, **kwargs)
    raise OSError("synthetic crash")
  monkeypatch.setattr(transaction, "atomic_target_bytes", crash_after_replace)
  capsys.readouterr()
  assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id, "--json"]) == 6
  failed = json.loads(capsys.readouterr().out)
  assert failed["transaction_id"]
  assert failed["transaction_phase"] == "recovery_pending"
  assert failed["next_command"] == "./termcfg recover"
  from termcfg.state import state_file
  state_before = state_file(machine).read_bytes() if state_file(machine).exists() else None
  assert main(["sync", "--component", "zsh", "--json"]) == 4
  assert json.loads(capsys.readouterr().out)["reason"] == "recovery_pending"
  assert main(["service", "stop", "--json"]) == 4
  assert json.loads(capsys.readouterr().out)["reason"] == "recovery_pending"
  assert main(["init-local", "--edit", "--none", "--json"]) == 4
  assert json.loads(capsys.readouterr().out)["reason"] == "recovery_pending"
  assert (state_file(machine).read_bytes() if state_file(machine).exists() else None) == state_before
  assert main(["status", "--component", "zsh", "--json"]) == 0
  status = json.loads(capsys.readouterr().out)
  assert status["recovery_pending"] is True
  assert status["transaction"]["items"]


def test_failed_sync_json_reports_stage_and_side_effect(isolated_environment, monkeypatch, capsys):
  import gzip
  import hashlib
  from termcfg import packages
  assert main(["init-local", "--component", "mihomo"]) == 0
  archive = gzip.compress(b"synthetic core")
  asset = {"version": "v1.0.0", "platform": "linux-x86_64",
           "name": "mihomo-linux-amd64-compatible-v1.0.0.gz",
           "url": "https://github.com/MetaCubeX/mihomo/releases/download/v1.0.0/mihomo-linux-amd64-compatible-v1.0.0.gz",
           "size": len(archive), "sha256": hashlib.sha256(archive).hexdigest(),
           "archive": "gzip-single", "entry": "mihomo", "resources": []}
  monkeypatch.setattr(packages, "_read_lock_raw", lambda component: ({"assets": {"linux-x86_64": asset}}, "synthetic-snapshot"))
  monkeypatch.setattr(packages, "_download", lambda *a, **k: b"tampered")
  capsys.readouterr()
  assert main(["sync", "--component", "mihomo", "--json"]) == 5
  result = json.loads(capsys.readouterr().out)
  assert result["stage"] == "verify"
  assert result["component"] == "mihomo"
  assert result["side_effect"] == "package_selection_unchanged"


def test_apply_source_failure_identifies_component_and_target(isolated_environment,
                                                               fake_terminal_commands, monkeypatch, capsys):
  from termcfg import environment
  from termcfg.catalog import load_catalog
  from termcfg.errors import TermcfgError
  assert main(["init-local", "--component", "zsh"]) == 0
  machine = read_machine("default")
  plan = build_preview(machine, ("zsh",))
  original = load_catalog()
  class CorruptSource:
    id = "zshrc"
    component = "zsh"
    destination = original[0].destination
    def bytes(self):
      raise TermcfgError(5, "source_digest_mismatch")
  monkeypatch.setattr(environment, "load_catalog", lambda: (CorruptSource(),))
  capsys.readouterr()
  assert main(["apply", "--component", "zsh", "--plan-id", plan.plan_id, "--json"]) == 5
  result = json.loads(capsys.readouterr().out)
  assert (result["component"], result["target_id"], result["stage"]) == ("zsh", "zshrc", "validate")
