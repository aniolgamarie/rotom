"""内核后代观察的合成边界；不创建子进程或给宿主发信号。"""

import errno
import os
from types import SimpleNamespace

import pytest

from agentcfg.storage import Conflict


@pytest.fixture
def kernel(monkeypatch):
  from agentcfg import descendants, run_owners
  state = {"subreaper": 0, "empty_before": True, "wait": [], "calls": []}
  manager = {"pid": os.getpid(), "birth_id": "synthetic-complete-birth"}
  monkeypatch.setattr(descendants.sys, "platform", "linux")
  monkeypatch.setattr(descendants.threading, "active_count", lambda: 1)
  monkeypatch.setattr(descendants.signal, "getsignal", lambda *a: descendants.signal.SIG_DFL)
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: dict(manager))
  monkeypatch.setattr(descendants, "_get_subreaper", lambda: state["subreaper"])
  monkeypatch.setattr(descendants, "_initially_empty", lambda: state["empty_before"])
  def set_value(value):
    state["calls"].append(value)
    state["subreaper"] = value
  monkeypatch.setattr(descendants, "_set_subreaper", set_value)
  def wait(pid, flags):
    assert pid == -1 and flags & os.WNOHANG and flags & descendants.WALL
    if not state["wait"]:
      raise ChildProcessError(errno.ECHILD, "synthetic no children")
    value = state["wait"].pop(0)
    if isinstance(value, Exception): raise value
    return value
  monkeypatch.setattr(descendants.os, "waitpid", wait)
  return descendants, manager, state


def test_clean_kernel_coverage_reaps_exited_children_then_confirms_release(kernel):
  module, manager, state = kernel
  state["wait"] = [(23456, 0), (23457, 3 << 8)]
  with module.DescendantScope(manager) as scope:
    assert state["subreaper"] == 1
    result = scope.observe("a" * 32)
  assert result.complete and result.all_related_exited
  assert result.manager_identity == manager and state["calls"] == [1, 0]


@pytest.mark.parametrize("condition", ["live-child", "wait-error", "identity-drift", "tracking-lost"])
def test_unknown_or_live_descendants_never_produce_complete_release(kernel, condition, monkeypatch):
  module, manager, state = kernel
  with module.DescendantScope(manager) as scope:
    if condition == "live-child": state["wait"] = [(0, 0)]
    elif condition == "wait-error": state["wait"] = [OSError(errno.EPERM, "synthetic unavailable")]
    elif condition == "identity-drift": manager["birth_id"] = "different-start"
    else: state["subreaper"] = 0
    assert scope.observe("a" * 32) is None


@pytest.mark.parametrize("condition", ["preexisting-child", "foreign-pid", "threads", "signal-handler", "unsupported"])
def test_incomplete_start_does_not_claim_kernel_coverage(kernel, condition, monkeypatch):
  module, manager, state = kernel
  if condition == "preexisting-child": state["empty_before"] = False
  elif condition == "foreign-pid": manager["pid"] += 1
  elif condition == "threads": monkeypatch.setattr(module.threading, "active_count", lambda: 2)
  elif condition == "signal-handler": monkeypatch.setattr(module.signal, "getsignal", lambda *a: lambda *a: None)
  else: monkeypatch.setattr(module.sys, "platform", "darwin")
  with module.DescendantScope(manager) as scope:
    assert scope.observe("a" * 32) is None
  assert state["calls"] == []


def test_complete_current_run_does_not_release_another_run(kernel, tmp_path):
  from agentcfg.lifecycle import guard
  from agentcfg.run_owners import Registry
  module, manager, state = kernel
  workspace = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    binding={"profile": "synthetic"}, profile="synthetic")
  with guard(workspace): pass
  registry = Registry(workspace.state_root / "run-owners", workspace.binding)
  with guard(workspace, shared=True, create=False):
    first = registry.register(manager)
    second = registry.register(manager)
    with module.DescendantScope(manager) as scope:
      proof = scope.observe(first)
      registry.finish_current(first, manager, proof)
    assert registry.snapshot()[first]["state"] == "idle_confirmed"
    assert registry.snapshot()[second]["state"] == "active"
  with guard(workspace, create=False), pytest.raises(Conflict):
    registry.assert_inactive()


@pytest.mark.parametrize("damage", ["incomplete", "live", "wrong-run", "wrong-manager", "old-unknown"])
def test_current_finish_rejects_partial_or_unrelated_proof(kernel, tmp_path, damage):
  from agentcfg.lifecycle import guard
  from agentcfg.run_owners import Registry, ReleaseObservation
  _, manager, _ = kernel
  workspace = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    binding={"profile": "synthetic"}, profile="synthetic")
  with guard(workspace): pass
  registry = Registry(workspace.state_root / "run-owners", workspace.binding)
  with guard(workspace, shared=True, create=False):
    run_id = registry.register(manager)
    if damage == "old-unknown": registry.mark_unknown(run_id, manager)
    proof = ReleaseObservation("b" * 32 if damage == "wrong-run" else run_id,
      {**manager, "birth_id": "wrong"} if damage == "wrong-manager" else manager,
      damage != "live", damage != "incomplete")
    with pytest.raises(Conflict): registry.finish_current(run_id, manager, proof)
    assert registry.snapshot()[run_id]["state"] == ("unknown" if damage == "old-unknown" else "active")


def test_registered_run_clean_kernel_release_is_usable_by_maintenance(kernel, tmp_path):
  from agentcfg.lifecycle import guard, registered_run
  from agentcfg.run_owners import Registry
  _, _, _ = kernel
  workspace = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    binding={"profile": "synthetic"}, profile="synthetic")
  with guard(workspace): pass
  registry = Registry(workspace.state_root / "run-owners", workspace.binding)
  with guard(workspace, shared=True, create=False):
    with registered_run(workspace) as run_id:
      assert registry.snapshot()[run_id]["state"] == "active"
  with guard(workspace, create=False): registry.assert_inactive()
