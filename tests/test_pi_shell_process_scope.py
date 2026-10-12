"""Shell可信启动选择PID范围；真实Store、假spawn，不运行helper。"""

from dataclasses import replace
import json
import os
import socket
import array
from types import SimpleNamespace

import pytest

from agentcfg import pi_host
from agentcfg.pi_supervisor import SpawnCommand
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_activity import identity
from test_pi_supervisor import fixture, request


def command(tmp_path, scope="linux-pid-namespace"):
  return SpawnCommand(("synthetic-shell-worker",), tmp_path, {}, process_scope=scope)


@pytest.mark.parametrize("scope", [None, True, "host", "join-existing", []])
def test_scope_selector_is_closed(tmp_path, scope):
  with pytest.raises(ConfigError): command(tmp_path, scope)


def test_running_identity_is_committed_before_gate_and_scope_is_durably_bound(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  selected = command(tmp_path)
  service.command_resolver = lambda *args: selected
  started = []
  def activate(lease):
    assert service.store.read(lease["lease_id"])["state"] == "running"
    started.append(lease["process_identity"])
  service.activate = activate
  allocation = service.reply(token, os.geteuid(), request("allocate", {**args, "kind": "external"}))["result"]
  message = request("start", {"lease_id": allocation["lease_id"], "program": "ordinary-shell", "payload": {"operation_id": "reference"}})
  result = service.reply(token, os.geteuid(), message)
  assert result["ok"] and started == [identity(201)]
  binding = json.loads((service.store.root / "activity/commands" / (allocation["lease_id"] + ".json")).read_text())
  assert binding["process_scope"] == "linux-pid-namespace"
  assert len(calls) == 1 and calls[0][0].process_scope == "linux-pid-namespace"
  service.command_resolver = lambda *args: replace(selected, process_scope="default")
  assert service.reply(token, os.geteuid(), message)["exit_code"] == 4
  assert len(calls) == 1
  assert service.store.read(allocation["lease_id"])["process_identity"] == started[0]


def test_rpc_cannot_supply_a_process_scope(tmp_path):
  service, token, args, calls = fixture(tmp_path)
  allocation = service.reply(token, os.geteuid(), request("allocate", args))["result"]
  result = service.reply(token, os.geteuid(), request("start", {"lease_id": allocation["lease_id"],
    "program": "worker", "payload": {}, "process_scope": "linux-pid-namespace"}))
  assert result["exit_code"] == 2 and not calls


def test_linux_shell_never_inherits_control_directory_or_marker(tmp_path, monkeypatch):
  host = host_fixture(tmp_path, monkeypatch)
  host.server.duplicate_control_directory = lambda: pytest.fail("Bash received control directory")
  class Capture:
    def __init__(self, root): pass
    def attach(self, child): pass
  monkeypatch.setattr(pi_host, "OutputCapture", Capture)
  seen = []
  from agentcfg.pi_shell_start import ShellStart
  launch = object.__new__(ShellStart)
  launch.spawn = lambda command, lease, environment, streams: (seen.append(dict(environment)) or SimpleNamespace(pid=201), identity(201), 99)
  launch.bind_child = lambda record: None
  selected = SpawnCommand(("synthetic-bash",), tmp_path, {"AGENTCFG_SUPERVISOR_DIRECTORY_FD": "3"},
    process_scope="linux-shell", capture_root=tmp_path, launch=launch)
  assert host._spawn(selected, {"kind": "external", "lease_id": "bash"}) == identity(201)
  assert "AGENTCFG_SUPERVISOR_DIRECTORY_FD" not in seen[0]
  assert "control_directory" not in host.children["bash"]


def host_fixture(tmp_path, monkeypatch):
  host = object.__new__(pi_host.HostSupervisor)
  host.repository, host.children = tmp_path, {}
  host.manifest = lambda: {"profile_id": "pi-base"}
  directory = tmp_path / "control-private"; directory.mkdir(mode=0o700)
  host.server = SimpleNamespace(duplicate_control_directory=lambda: os.open(directory, os.O_RDONLY | os.O_DIRECTORY))
  monkeypatch.setattr(pi_host.sys, "platform", "linux")
  def forbidden(*args, **kwargs): raise AssertionError("generic spawn fallback")
  monkeypatch.setattr(pi_host.subprocess, "Popen", forbidden)
  return host


@pytest.mark.parametrize("kind", ["external", "check"])
def test_external_shell_uses_registered_namespace_gate_without_generic_spawn(tmp_path, monkeypatch, kind):
  host = host_fixture(tmp_path, monkeypatch)
  if kind == "check": host.manifest = lambda: {"profile_id": "pi-full"}
  read, write = os.pipe()
  sent = []
  class Channel:
    def __init__(self, *, fileno): self.fd = fileno
    def __enter__(self): return self
    def __exit__(self, *args): os.close(self.fd)
    def sendmsg(self, data, ancillary):
      assert data == [b"G"] and len(ancillary) == 1
      values = list(ancillary[0][2]); assert len(values) == 1
      sent.append(os.fstat(values[0]).st_ino)
      return os.write(self.fd, b"G")
  monkeypatch.setattr(pi_host.socket, "socket", Channel)
  calls = []
  born = identity(201)
  def spawn(current, selected, environment, streams, *, control_directory=False):
    assert control_directory is True
    assert current is host and selected.process_scope == "linux-pid-namespace" and not streams
    calls.append(selected)
    return SimpleNamespace(pid=202), born, write
  monkeypatch.setattr("agentcfg.pi_pid_namespace.spawn_host_namespace", spawn)
  try:
    result = host._spawn(command(tmp_path), {"kind": kind, "lease_id": "shell"})
    assert result == born and len(calls) == 1
    os.set_blocking(read, False)
    with pytest.raises(BlockingIOError): os.read(read, 1)
    host.activate({"lease_id": "shell"})
    assert os.read(read, 1) == b"G"
    assert sent == [(tmp_path / "control-private").stat().st_ino]
    assert host.children["shell"]["identity"] == born and host.children["shell"]["gate"] is None
  finally:
    os.close(read)
    if host.children.get("shell", {}).get("gate") is not None: os.close(write)


@pytest.mark.parametrize("fault", ["platform", "kind", "legacy", "helper", "base-check"])
def test_unavailable_scope_never_falls_back_or_publishes_child(tmp_path, monkeypatch, fault):
  host = host_fixture(tmp_path, monkeypatch)
  lease = {"kind": "external", "lease_id": "shell"}
  if fault == "platform": monkeypatch.setattr(pi_host.sys, "platform", "darwin")
  if fault == "kind": lease["kind"] = "worker"
  if fault == "base-check": lease["kind"] = "check"
  if fault == "legacy": host.manifest = lambda: {"profile_id": "default"}
  calls = []
  def unavailable(*args, **kwargs):
    calls.append(True)
    raise Conflict("synthetic helper unavailable")
  monkeypatch.setattr("agentcfg.pi_pid_namespace.spawn_host_namespace", unavailable)
  with pytest.raises(Conflict): host._spawn(command(tmp_path), lease)
  assert calls == ([True] if fault == "helper" else [])
  assert host.children == {}
