"""显式Shell路由接真实准入/存储，进程与门控均用替身。"""

from types import SimpleNamespace
from contextlib import contextmanager
import os

import pytest

from agentcfg.activity import protected
from agentcfg.pi_host import HostSupervisor
from agentcfg.pi_shell_start import ShellStart
from agentcfg.pi_supervisor import OrdinaryCapabilityUnavailable
from test_pi_activity import identity
from test_pi_admitted_shell import prepare, consume
from test_pi_shell_launch import configured
from test_pi_supervisor import request


@pytest.mark.parametrize("control", [None, SimpleNamespace(shell_bridge=None)])
def test_missing_shell_bridge_is_unavailable_without_registry_fallback(tmp_path, control):
  f = configured(tmp_path)
  host = f[2]; host.operations = f[1]
  host.operations.admission_control = control
  with pytest.raises(OrdinaryCapabilityUnavailable):
    HostSupervisor.resolve_command(host, {}, "ordinary-shell", {"operation_id": "reference"})


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_shell_start_and_timeout_use_explicit_bridge_without_task_keeper(tmp_path, monkeypatch, profile):
  f = configured(tmp_path)
  bridge, operations, host, principal = f[:4]
  host.manifest()["profile_id"] = profile
  f[4]["profile"] = profile
  host.operations = operations
  operations.admission_control = SimpleNamespace(shell_bridge=bridge)
  host.service.command_resolver = lambda *args: HostSupervisor.resolve_command(host, *args)
  now = [bridge._now_ms()]
  monkeypatch.setattr(bridge, "_now_ms", lambda: now[0])
  calls = []
  @contextmanager
  def preparation(launch, command, lease):
    # 此用例只验选路和tick；真实父FD作用域由test_pi_shell_start独立故障矩阵覆盖。
    assert command.launch is launch and lease["state"] == "allocating"
    yield command
  monkeypatch.setattr(ShellStart, "prepare", preparation)
  def spawn(command, lease):
    assert command.process_scope == "linux-shell"
    assert host.store.read(lease["lease_id"])["state"] == "starting"
    calls.append(command)
    host.store.processes.current[203] = identity(203)
    return identity(203)
  activated = []
  def activate(lease):
    assert host.store.read(lease["lease_id"])["state"] == "running"
    activated.append(lease["process_identity"])
  host.service.spawn, host.service.activate = spawn, activate
  prepared = prepare(f); ticket = consume(f, prepared)
  token = host.service.issue_capability("manager", principal.lease_id)
  message = request("start", {"lease_id": ticket["lease_id"], "program": "ordinary-shell",
    "payload": {"operation_id": prepared["operation_id"]}})
  result = host.service.reply(token, os.geteuid(), message)
  assert result["ok"] and result["result"]["state"] == "running"
  assert len(calls) == 1 and activated == [identity(203)]
  now[0] = bridge.records[prepared["operation_id"]]["run_deadline_ms"]
  operations.tick()
  lease = host.store.read(ticket["lease_id"])
  assert lease["state"] == "cancel_requested" and protected(lease)
  assert host.store.workspaces.read(lease["planned_workspaces"][0])["state"] != "released"
  operations.tick()
  assert host.store.read(ticket["lease_id"]) == lease and len(calls) == 1
