"""CLI来源固定冲突应在原Host spawn/G前拒绝，不停止未知旧进程。"""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading

import pytest

from agentcfg.activity import protected, valid_evidence
from agentcfg.pi_host import HostSupervisor
from agentcfg.storage import Conflict
from test_pi_activity import make_store, identity


@pytest.mark.parametrize("fail", [False, True])
def test_cli_source_registered_on_original_allocating_lease_before_spawn(tmp_path, fail):
  host = object.__new__(HostSupervisor)
  host.store, processes = make_store(tmp_path)
  host.config = {"lock_identity": "a" * 64, "slice_identity": "b" * 64, "policy_digest": "c" * 64,
    "argv": ["synthetic-manager-never-executed"], "cwd": str(tmp_path)}
  host.repository = tmp_path; host.children = {}; host.host_exit = None; host.host_lease_id = None
  host._spawn_executor = ThreadPoolExecutor(max_workers=1)
  host.service = SimpleNamespace(mutex=threading.RLock(), closing=False, issue_capability=lambda *args: "synthetic")
  host.server = SimpleNamespace(endpoint=tmp_path / "control.json", open=lambda: None, close=lambda: None, poll=lambda: None)
  host.manifest = lambda: {"profile_id": "pi-full", "plugins": ["model-delegate"], "options": {},
    "plugin_capabilities": {"model-delegate": {"capability_id": "unified-delegate"}}}
  events = []
  def register():
    current = host.store.read(host.host_lease_id)
    events.append(("register", current["state"], current["spawn_committed"]))
    if fail: raise Conflict("DELEGATE_SOURCE_SCOPE_STALE")
  host.delegates = SimpleNamespace(register_cli_source=register)
  def spawn(command, lease):
    events.append(("spawn", lease["state"], lease["spawn_committed"]))
    born = identity(201); processes.current[201] = born; return born
  host.spawn = spawn
  host.activate = lambda lease: events.append(("activate", lease["state"], lease["spawn_committed"]))
  def poll():
    processes.current.pop(201, None)
    host.store.finish(host.host_lease_id, host.store.owner)
    host.host_exit = 0
  host.poll = poll
  if fail:
    with pytest.raises(Conflict, match="DELEGATE_SOURCE_SCOPE_STALE"): host.run()
    current = host.store.read(host.host_lease_id)
    assert events == [("register", "allocating", False)]
    assert current["state"] == "failed" and current["process_identity"] is None
    assert not current["spawn_committed"] and not protected(current)
    assert valid_evidence(current)
    assert current["termination_evidence"]["kind"] == "never-started"
  else:
    assert host.run() == 0
    assert events == [("register", "allocating", False), ("spawn", "starting", True), ("activate", "running", True)]
