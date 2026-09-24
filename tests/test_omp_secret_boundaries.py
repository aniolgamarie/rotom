"""命令边界的秘密/归属断言，均为合成哨兵。"""

from types import SimpleNamespace
import json
import yaml

import pytest

from agentcfg import commands, deployment
from agentcfg.omp_identity import lifecycle_guard
from agentcfg.storage import Conflict
from test_omp_runtime_foundation import runtime_workspace
from test_omp_pipeline import full_workspace
from agentcfg.omp_identity import native_identity
from agentcfg.secrets import SecretStore
from agentcfg import runtime


@pytest.mark.parametrize("condition", ["pending", "active", "no-deployment", "binding"])
def test_capture_requires_deployed_identity_and_same_activity_gate(tmp_path, monkeypatch, condition):
  workspace, _ = runtime_workspace(tmp_path)
  monkeypatch.setattr(commands, "workspace", lambda _: workspace)
  state_path = workspace.state_root / "deployment.json"
  if condition == "pending":
    pending = workspace.state_root / "pending.json"
    pending.write_bytes(b"{}")
    pending.chmod(0o600)
  elif condition == "no-deployment":
    state_path.unlink()
  elif condition == "binding":
    saved = json.loads(state_path.read_bytes())
    saved["current"]["binding"]["machine"] = "foreign"
    state_path.write_bytes(deployment.json_bytes(saved))
  if condition == "active":
    with lifecycle_guard(workspace):
      with pytest.raises(Conflict):
        commands.cmd_capture(SimpleNamespace())
  else:
    with pytest.raises(Conflict):
      commands.cmd_capture(SimpleNamespace())
  assert not (workspace.cache / "proposals").exists()


def prepare_full(workspace):
  lock = workspace.backend.read_lock(workspace.repository)
  with workspace.adapter.apply_lifecycle_guard(workspace):
    deployment.apply(workspace.instance, workspace.state_root, workspace.candidate(lock.identity), workspace.binding, runtime.record(workspace, lock))
  return lock


@pytest.mark.parametrize("command", ["plan", "capture", "rollback", "doctor"])
def test_literal_native_secret_never_enters_reports_or_backups(tmp_path, monkeypatch, capsys, command):
  workspace = full_workspace(tmp_path)
  sentinel = "SYNTHETIC_SECRET_BOUNDARY_98432"
  workspace.secret_store = SecretStore({"omp_smoke_placeholder": sentinel})
  prepare_full(workspace)
  workspace.resolved.data["profile"]["agent_options"]["ui"]["keybindings"]["app.model.cycleForward"] = "Ctrl+O"
  prepare_full(workspace)
  identity = native_identity(workspace.profile, workspace.instance)
  models = identity.agent_dir / "models.yml"
  document = yaml.safe_load(models.read_bytes())
  document["providers"]["omp-smoke"]["apiKey"] = sentinel
  models.write_text(yaml.safe_dump(document))
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  args = SimpleNamespace(live=False)
  with pytest.raises(Conflict) as error:
    getattr(commands, "cmd_" + command)(args)
  captured = capsys.readouterr()
  assert sentinel not in captured.out + captured.err + str(error.value)
  for root in (workspace.state_root, workspace.cache):
    for path in root.rglob("*"):
      if path.is_file():
        assert sentinel.encode() not in path.read_bytes()


@pytest.mark.parametrize("location", ["current", "previous", "pending"])
def test_deleted_historical_guard_cannot_export_literal_secret(tmp_path, monkeypatch, location):
  workspace = full_workspace(tmp_path)
  prepare_full(workspace)
  workspace.resolved.data["profile"]["agent_options"]["ui"]["keybindings"]["app.model.cycleForward"] = "Ctrl+O"
  prepare_full(workspace)
  state_path = workspace.state_root / "deployment.json"
  saved = json.loads(state_path.read_bytes())
  current = saved["current"] if location != "previous" else saved["previous"]["current"]
  item = next(item for item in current["items"].values() if (item.get("selector") or "").endswith("/apiKey"))
  item.pop("guard")
  item["baseline"]["value"] = "SYNTHETIC_HISTORICAL_SECRET_947"
  if location == "pending":
    pending = workspace.state_root / "pending.json"
    pending.write_bytes(deployment.json_bytes({"after_state": saved, "changes": []}))
    pending.chmod(0o600)
  else:
    state_path.write_bytes(deployment.json_bytes(saved))
  monkeypatch.setattr(commands, "workspace", lambda args: workspace)
  with pytest.raises(Conflict) as error:
    commands.cmd_rollback(SimpleNamespace()) if location == "previous" else commands.cmd_capture(SimpleNamespace())
  assert "SYNTHETIC_HISTORICAL_SECRET_947" not in str(error.value)
  assert not (workspace.cache / "proposals").exists()
