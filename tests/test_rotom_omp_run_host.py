"""OMP 原 child 捕获在原三层租约内通过 Domain 同步；不准入控制。"""
from copy import deepcopy
import os

import pytest

from agentcfg import lifecycle, omp_run_observation, run_owners, runtime, spawned_host
from agentcfg.process import DependencyError
from agentcfg.storage import Conflict
from test_rotom_omp_cooperative_launch import case, install, manual_owner, package_path, busy
from test_rotom_resource_owners import MANAGER
from test_rotom_resume_dispatch import fake_popen


HOST = {"identity": {"pid": 31338, "birth_id": "synthetic-child-birth"},
  "manager_identity": MANAGER, "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}
_REAL_CHILD = runtime._run_dsh_child


@pytest.fixture
def managed(case, fake_subprocess, fake_popen, monkeypatch):
  install(case, monkeypatch)
  monkeypatch.setattr(runtime, "_run_dsh_child", _REAL_CHILD)
  # 本模块隔离原 host 捕获；实际 sidecar 工厂由 tool_stop 集成测试覆盖。
  def forbidden(*args, **kwargs): pytest.fail("OMP 不得直接 Registry 写入")
  monkeypatch.setattr("agentcfg.dsh_stop_control.default_factory", lambda *args, **kwargs: None)
  monkeypatch.setattr(run_owners.Registry, "bind_current_host", forbidden)
  handle = object.__new__(spawned_host.SpawnedHost)
  capture = {"closed": 0, "count": 0}
  def take(child, manager):
    assert manager == MANAGER and child.wait_calls == 0 and child.returncode is None
    capture["count"] += 1
    return handle
  def snapshot(self):
    assert capture["closed"] == 0
    return deepcopy(HOST)
  monkeypatch.setattr(spawned_host, "capture_spawned_host", take)
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", snapshot)
  monkeypatch.setattr(spawned_host.SpawnedHost, "close", lambda self: capture.update(closed=capture["closed"]+1))
  return capture


def record(case):
  row, = run_owners.Registry(case.ws.state_root / "run-owners", case.ws.binding).snapshot().values()
  return row


@pytest.mark.parametrize("code,complete", [(0, True), (23, False), (-15, False)])
def test_original_host_is_bound_before_wait_in_original_leases(case, managed, fake_popen, code, complete):
  case.control["complete"] = complete
  def wait():
    saved = record(case)
    assert saved["host_identity"] == HOST and saved["protocol"]["control"] is None
    assert saved["session_observation"] is None
    entry, = case.domain.snapshot()["reservations"].values()
    assert entry["phase"] == "dispatched"
    assert managed["closed"] == 0
    for path in (case.ws.instance / ".agentcfg-omp.lock", case.ws.state_root / "instance.lock", package_path(case)):
      busy(path)
    assert len(fake_popen.calls[0]["pass_fds"]) == 3
    for fd in fake_popen.calls[0]["pass_fds"]: os.fstat(fd)
  fake_popen.queue(returncode=code, on_wait=wait)
  assert runtime.run(case.ws, cwd=case.cwd) == (code if code >= 0 else 128-code)
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1
  assert managed == {"closed": 1, "count": 1}
  assert record(case)["host_identity"] == HOST
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == ("released" if complete else "unknown")


@pytest.mark.parametrize("fault", ["capture", "bind"])
def test_observation_failure_waits_once_without_retry(case, managed, fake_popen, monkeypatch, fault):
  case.control["complete"] = False
  if fault == "capture":
    monkeypatch.setattr(spawned_host, "capture_spawned_host", lambda *args: None)
  else:
    def fail(*args, **kwargs): raise Conflict("synthetic-private-error")
    monkeypatch.setattr(omp_run_observation, "bind_current_host", fail)
  fake_popen.queue(returncode=29)
  assert runtime.run(case.ws, cwd=case.cwd) == 29
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1
  assert record(case)["host_identity"] is None
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "unknown"


@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt])
def test_wait_failure_preserves_unknown_and_original_exception(case, managed, fake_popen, kind):
  case.control["complete"] = False
  error = kind("synthetic-private-error")
  fake_popen.queue(returncode=0, wait_error=error)
  with pytest.raises(Conflict if kind is OSError else kind) as caught:
    runtime.run(case.ws, cwd=case.cwd)
  if kind is KeyboardInterrupt: assert caught.value is error
  assert managed["closed"] == 1 and fake_popen.children[0].wait_calls == 1
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "unknown"


def test_factory_and_observer_are_limited_to_original_live_owner(case):
  with case.module.cooperative_run(case.ws, case.lock.identity) as lease:
    with pytest.raises(Conflict): lease.observer_factory("a" * 32)
    with manual_owner(case, lease) as run_id:
      observer = lease.observer_factory(run_id)
      assert run_id in observer.snapshot()
      with pytest.raises(Conflict): lease.observer_factory("b" * 32)
    with pytest.raises(Conflict): observer.snapshot()
    with pytest.raises(Conflict): observer.bind_current_host(run_id, None)
  with pytest.raises(Conflict): lease.observer_factory(run_id)


def test_optional_factory_must_be_callable():
  with pytest.raises(DependencyError): lifecycle.CooperativeRunLease(1, lambda: None, lambda: None, object())


def test_committed_pending_response_loss_retains_protection_without_retry(case, managed, fake_popen, monkeypatch):
  import json
  from agentcfg.storage import Tree
  original = Tree.replace
  writes = []
  def lost(tree, name, data, *args, **kwargs):
    result = original(tree, name, data, *args, **kwargs)
    if managed["count"] == 1 and name == "coordination.json" and any(row["phase"] == "owner_pending"
        for row in json.loads(data)["reservations"].values()):
      writes.append(True)
      raise OSError("synthetic-private-response-loss")
    return result
  monkeypatch.setattr(Tree, "replace", lost)
  fake_popen.queue(returncode=31)
  assert runtime.run(case.ws, cwd=case.cwd) == 31
  assert len(writes) == 1 and fake_popen.children[0].wait_calls == 1
  assert len(fake_popen.calls) == 1 and managed == {"closed": 1, "count": 1}
  assert record(case)["host_identity"] is None
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "owner_pending"


def test_spawn_failure_does_not_capture_or_restart(case, managed, fake_popen):
  case.control["complete"] = False
  fake_popen.queue(spawn_error=OSError("synthetic-private-spawn"))
  with pytest.raises(DependencyError): runtime.run(case.ws, cwd=case.cwd)
  assert len(fake_popen.calls) == 1 and fake_popen.children == []
  assert managed == {"closed": 0, "count": 0}
  assert next(iter(case.domain.snapshot()["reservations"].values()))["phase"] == "unknown"
