"""恢复CLI不读取模型、凭据或新运行包；系统进程全部为替身。"""

from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from agentcfg import cli
from agentcfg.pi_lifecycle import guard
from agentcfg import pi_recovery
from test_pi_activity import make_store, begin, identity


def fixture(tmp_path, monkeypatch):
  local = tmp_path / "local.toml"
  local.write_text('schema_version=1\n[machine]\nid="fixture"\ndefault_profile="pi-recovery"\n[machine.paths]\n'
    + '\n'.join(key+'='+json.dumps(str(tmp_path/key)) for key in ("state_root", "instances_root", "cache_root"))
    + '\n[overrides.models.unready]\nprovider="missing"\n[secrets]\ninvalid=["unused"]\n')
  args = SimpleNamespace(local=local, profile="pi-recovery", agent="pi")
  w = pi_recovery.recovery_workspace(args)
  with guard(w):
    pass
  store, processes = make_store(tmp_path / "old")
  store.root = w.state_root
  worker = identity(201)
  processes.current[201] = worker
  lease = begin(store, lambda _: worker)
  processes.current.pop(101)
  controller = identity(102)
  processes.current[102] = controller
  processes.identity = lambda pid: controller
  monkeypatch.setattr(pi_recovery, "make_processes", lambda *args: processes)
  return local, w, lease, processes


def test_preview_and_explicit_stop_work_without_current_config_readiness(tmp_path, monkeypatch, capsys):
  local, w, lease, processes = fixture(tmp_path, monkeypatch)
  args = ["--local", str(local), "recover", "pi", "--lease", lease["lease_id"]]
  assert cli.main(args) == 0
  plan = json.loads(capsys.readouterr().out)
  assert plan["plan_kind"] == "stop_execution" and plan["target_processes"] == 1
  assert processes.signals == []
  assert "owner_nonce" not in plan and "target_process_identities" not in plan
  assert cli.main([*args, "--stop", "--expect-plan", plan["plan_digest"]]) == 0
  result = json.loads(capsys.readouterr().out)
  assert result["state"] == "reclaimed" and result["protected"] is False
  assert len(processes.signals) == 1


def test_stop_requires_exact_plan_and_foreign_agent_profile_is_rejected(tmp_path, monkeypatch):
  local, w, lease, processes = fixture(tmp_path, monkeypatch)
  args = ["--local", str(local), "recover", "pi", "--lease", lease["lease_id"]]
  assert cli.main([*args, "--stop"]) == 2
  assert cli.main([*args, "--expect-plan", "a" * 64]) == 2
  assert cli.main(["--local", str(local), "--profile", "dsh-default", "recover", "pi", "--lease", lease["lease_id"]]) == 2
  assert processes.signals == []
