"""迁移探测的进程为替身；空 SDK 账号存储不冒充导入，也不能藏入账号。"""
from types import SimpleNamespace
from pathlib import Path
from contextlib import nullcontext
import pytest

import agentcfg.pi_validation_migration as migration
from agentcfg.storage import Tree, Conflict
from agentcfg.pi_host import HostSupervisor


def test_active_mutation_probe_waits_for_a_real_request_and_uses_only_fixture_cli(tmp_path, monkeypatch):
  host = object.__new__(migration.MigrationConflictSupervisor)
  workspace = SimpleNamespace(repository=tmp_path / "source", local_path=tmp_path / "local.toml", resolved=SimpleNamespace(data={"profile": {"id": "pi-default"}}))
  host.fixture = {"workspace": workspace, "project": tmp_path / "project", "environment": {"HOME": str(tmp_path / "home")}}
  host.conflict_results, host.host_exit = [], None
  host.model_started = lambda: False
  monkeypatch.setattr(HostSupervisor, "poll", lambda _: None)
  calls = []
  def run(argv, **kwargs):
    assert kwargs["env"] == host.fixture["environment"] and kwargs["timeout"] == 15
    assert str(workspace.local_path) in argv and str(workspace.repository / "src") in argv
    calls.append(argv[-1])
    return SimpleNamespace(returncode=4, stdout=b"synthetic private text", stderr=b"synthetic private text")
  monkeypatch.setattr(migration.subprocess, "run", run)
  host.poll(); assert calls == []
  host.model_started = lambda: True
  host.poll(); host.poll()
  assert calls == ["apply", "sync", "rollback"]
  assert host.conflict_results == [{"action": action, "exit_code": 4} for action in calls]


@pytest.mark.parametrize("auth", [None, b"{}", b'{"synthetic":"unexpected-account"}'])
def test_migration_accepts_only_absent_or_empty_new_auth_storage(tmp_path, monkeypatch, auth):
  workspace = SimpleNamespace(state_root=tmp_path / "state", instance=tmp_path / "instance", binding={})
  old = tmp_path / "old"
  with Tree(old, create=True) as tree: tree.write_new("auth.json", b"old synthetic account")
  with Tree(workspace.state_root, create=True) as tree: tree.write_new("deployment.json", b"synthetic deployment")
  with Tree(workspace.instance, create=True) as tree:
    if auth is not None: tree.write_new("pi-home/auth.json", auth)
  monkeypatch.setattr(migration, "guard", lambda _: nullcontext())
  monkeypatch.setattr(migration, "apply", lambda *_: {"changes": 0})
  probe = {"old": old, "originals": {"auth.json": b"old synthetic account"}, "candidate": None, "launch": None}
  supervisor = SimpleNamespace(conflict_results=[{"action": action, "exit_code": 4} for action in ("apply", "sync", "rollback")])
  if auth not in (None, b"{}"):
    with pytest.raises(Conflict, match="IDEMPOTENCE"): migration.finish_migration_probe({"workspace": workspace}, probe, supervisor)
  else: assert migration.finish_migration_probe({"workspace": workspace}, probe, supervisor)["credentials_not_imported"] is True
