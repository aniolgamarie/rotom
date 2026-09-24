"""父宿主丢失探测只用已知身份替身；不发信号，不启动宿主。"""
from pathlib import Path
import signal
from types import SimpleNamespace

import pytest

from agentcfg.deployment import json_bytes
from agentcfg.pi_host import HostSupervisor
from agentcfg.pi_validation_parent_loss import ParentLossSupervisor
from agentcfg.storage import Conflict, Tree


@pytest.mark.parametrize("kind", ["worker", "external"])
@pytest.mark.parametrize("fault", [None, "nonce", "identity", "no-worker", "no-request"])
def test_parent_loss_probe_signals_only_its_verified_host_after_worker_start(tmp_path, monkeypatch, fault, kind):
  host = object.__new__(ParentLossSupervisor)
  host.host_exit, host.host_lease_id = None, "host"
  host.runtime_root = tmp_path / ("a" * 64)
  host.readiness, host.native_nonce = tmp_path / "ready.json", "current"
  host.parent_loss_workers, host.parent_loss_facts = [], None
  host.model_started = lambda: fault != "no-request"
  host.kill_platform = "linux"
  parent = {"pid": 201}; worker = {"pid": 202}
  host.children = {"host": {"identity": {"pid": 301} if fault == "identity" else parent}}
  host.store = SimpleNamespace(records=lambda: [] if fault == "no-worker" else [{"kind": kind, "state": "running", "process_identity": worker, "lease_id": "worker"}],
    read=lambda _: {"state": "running", "process_identity": parent})
  calls = []
  host.processes = SimpleNamespace(observe=lambda _: "alive", send_signal=lambda identity, number: calls.append((identity, number)))
  monkeypatch.setattr(HostSupervisor, "poll", lambda _: None)
  with Tree(tmp_path) as tree: tree.write_new("ready.json", json_bytes({"nonce": "other" if fault == "nonce" else "current",
    "runtime_identity": host.runtime_root.name, "facts": {"sdk_session": True, "child_execution_kind": kind}}))
  if fault == "nonce":
    with pytest.raises(Conflict): host.poll()
  else:
    host.poll(); host.poll()
  assert calls == ([(parent, signal.SIGKILL)] if fault is None else [])
  assert host.parent_loss_workers == (["worker"] if fault is None else [])


def test_cancel_readiness_is_written_only_after_an_actual_model_request(tmp_path, monkeypatch):
  from agentcfg.pi_validation_parent_loss import OrdinaryCancelSupervisor
  import json
  host = object.__new__(OrdinaryCancelSupervisor)
  host.runtime_root = tmp_path / ("a" * 64)
  host.readiness, host.native_nonce = tmp_path / "ready.json", "current"
  host.notified = False
  host.model_started = lambda: False
  monkeypatch.setattr(HostSupervisor, "poll", lambda _: None)
  host.poll()
  assert not host.readiness.exists()
  host.model_started = lambda: True
  host.poll(); host.poll()
  assert json.loads(host.readiness.read_text()) == {"nonce": "current", "runtime_identity": host.runtime_root.name}
