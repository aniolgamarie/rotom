"""受信 cooperative lease 接缝；合成 OMP workspace，不启用生产适配器。"""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import os
import subprocess

import pytest

from agentcfg import lifecycle, runtime
from agentcfg.process import DependencyError
from agentcfg.storage import Conflict
from test_omp_runtime_foundation import runtime_workspace, clear_omp_identity_environment, isolate_runtime_discovery


@pytest.fixture
def cooperative(tmp_path, monkeypatch):
  clear_omp_identity_environment(monkeypatch)
  isolate_runtime_discovery(monkeypatch)
  ws, lock = runtime_workspace(tmp_path)
  ws.agent = "omp"
  cwd = tmp_path / "work"
  cwd.mkdir()
  trace, state, control = [], {}, {}
  original_admission = ws.adapter.run_lifecycle_guard
  original_package = ws.backend.runtime_guard
  def alive():
    for name in ("physical_fd", "state_fd", "package_fd"):
      if name in state:
        os.fstat(state[name])
  @contextmanager
  def package(selected, identity):
    assert selected is ws and identity == lock.identity
    with original_package(selected, identity) as fd:
      state["package_fd"] = fd
      trace.append("package-enter")
      try:
        if control.get("package_error"):
          raise Conflict("synthetic-package-refusal")
        selected_fd = control.get("package_fd", fd)
        if control.get("closed_package"):
          selected_fd = os.dup(fd)
          os.close(selected_fd)
        yield selected_fd
      finally:
        alive()
        trace.append("package-exit")
  @contextmanager
  def owner(selected, *, metadata, lifecycle_fd, state_fd, package_fd):
    assert selected is ws
    assert lifecycle_fd == state["physical_fd"] and package_fd == state["package_fd"]
    assert metadata["agent"] == "omp" and metadata["coordination_domain"] is None
    assert metadata["start_cwd"]["path"] == str(cwd)
    state["state_fd"] = state_fd
    trace.append("owner-enter")
    try:
      alive()
      if control.get("owner_error"):
        raise Conflict("synthetic-owner-refusal")
      yield control.get("run_id", "a" * 32)
    finally:
      alive()
      trace.append("owner-exit")
  @contextmanager
  def admission(selected):
    with original_admission(selected) as fd:
      state["physical_fd"] = fd
      trace.append("physical-enter")
      try:
        yield lifecycle.CooperativeRunLease(control.get("physical_fd", fd), package, owner)
      finally:
        os.fstat(fd)
        trace.append("physical-exit")
  monkeypatch.setattr(ws.adapter, "run_lifecycle_guard", admission)
  monkeypatch.setattr(ws.backend, "runtime_guard", lambda *a: pytest.fail("不可回退默认包guard"))
  monkeypatch.setattr(ws.adapter, "run_owner_guard", lambda *a, **k: pytest.fail("不可回退旧owner guard"), raising=False)
  return ws, cwd, trace, state, control, alive


@pytest.mark.parametrize("code,expected", [(0, 0), (37, 37), (-9, 137)])
def test_child_inherits_only_three_int_fds_and_cleanup_preserves_exit(cooperative, fake_subprocess, monkeypatch, code, expected):
  ws, cwd, trace, state, _, alive = cooperative
  fake_subprocess.queue(returncode=code)
  original = subprocess.run
  def child(*args, **kwargs):
    alive()
    assert kwargs["pass_fds"] == (state["physical_fd"], state["state_fd"], state["package_fd"])
    assert all(type(fd) is int for fd in kwargs["pass_fds"])
    trace.append("child")
    return original(*args, **kwargs)
  monkeypatch.setattr(subprocess, "run", child)
  assert runtime.run(ws, cwd=cwd) == expected
  assert trace == ["physical-enter", "package-enter", "owner-enter", "child", "owner-exit", "package-exit", "physical-exit"]
  for fd in state.values():
    with pytest.raises(OSError):
      os.fstat(fd)


@pytest.mark.parametrize("mode", ["launch", "resume", "executor"])
def test_operations_receive_original_int_lifecycle_not_context_object(cooperative, monkeypatch, mode):
  ws, cwd, trace, state, _, alive = cooperative
  marker = object()
  def execute(selected, spec, env, lease, contract, *, lifecycle_fd, **kwargs):
    assert selected is ws and type(lifecycle_fd) is int and lifecycle_fd == state["physical_fd"]
    assert lease == state["state_fd"]
    if mode == "resume":
      assert kwargs == {"run_id": "a" * 32, "package_fd": state["package_fd"]}
    else:
      assert kwargs == {}
    alive()
    trace.append("operation")
    return marker
  options = {mode + "_operation": execute} if mode != "executor" else {}
  if mode == "executor":
    monkeypatch.setattr(ws.adapter, "launch_executor", lambda: execute, raising=False)
  assert runtime.run(ws, cwd=cwd, **options) is marker
  assert trace[-4:] == ["operation", "owner-exit", "package-exit", "physical-exit"]


@pytest.mark.parametrize("stage", ["package", "owner"])
def test_guard_failure_prevents_child_and_preserves_cleanup(cooperative, fake_subprocess, stage):
  ws, cwd, trace, _, control, _ = cooperative
  control[stage + "_error"] = True
  with pytest.raises(Conflict):
    runtime.run(ws, cwd=cwd)
  assert fake_subprocess.calls == []
  assert trace[-1] == "physical-exit" and "package-exit" in trace


@pytest.mark.parametrize("exception", [OSError, ValueError])
def test_child_exception_runs_owner_finally_while_three_leases_alive(cooperative, monkeypatch, exception):
  ws, cwd, trace, _, _, alive = cooperative
  def child(*args, **kwargs):
    alive()
    raise exception("synthetic-child-failure")
  monkeypatch.setattr(subprocess, "run", child)
  with pytest.raises(DependencyError if exception is OSError else ValueError):
    runtime.run(ws, cwd=cwd)
  assert trace[-3:] == ["owner-exit", "package-exit", "physical-exit"]


@pytest.mark.parametrize("bad", [None, True, -1, "1"])
def test_context_rejects_inexact_physical_fd_before_entry(bad):
  with pytest.raises(DependencyError):
    lifecycle.CooperativeRunLease(bad, lambda *a: None, lambda *a: None)


@pytest.mark.parametrize("field", ["package_guard", "owner_guard"])
def test_context_is_frozen_and_requires_callbacks(field):
  values = {"physical_fd": 0, "package_guard": lambda *a: None, "owner_guard": lambda *a: None}
  context = lifecycle.CooperativeRunLease(**values)
  with pytest.raises(FrozenInstanceError):
    context.physical_fd = 1
  values[field] = None
  with pytest.raises(DependencyError):
    lifecycle.CooperativeRunLease(**values)


@pytest.mark.parametrize("field", ["physical_fd", "package_fd", "state_fd"])
@pytest.mark.parametrize("bad", [None, True, -1])
def test_bad_cooperative_fd_prevents_any_owner_or_child(cooperative, fake_subprocess, monkeypatch, field, bad):
  ws, cwd, trace, _, control, _ = cooperative
  if field == "state_fd":
    original = runtime.instance_lock
    @contextmanager
    def state_guard(*args, **kwargs):
      with original(*args, **kwargs):
        yield bad
    monkeypatch.setattr(runtime, "instance_lock", state_guard)
  else:
    control[field] = bad
  with pytest.raises(DependencyError):
    runtime.run(ws, cwd=cwd)
  assert fake_subprocess.calls == [] and "owner-enter" not in trace


@pytest.mark.parametrize("mode", ["ordinary", "launch", "resume", "executor"])
@pytest.mark.parametrize("bad", [None, True, "invalid"])
def test_cooperative_owner_id_is_required_for_every_execution_mode(cooperative, fake_subprocess, monkeypatch, mode, bad):
  ws, cwd, _, _, control, _ = cooperative
  control["run_id"] = bad
  def forbidden(*args, **kwargs):
    pytest.fail("坏run身份不得派发任何执行路径")
  options = {} if mode in ("ordinary", "executor") else {mode + "_operation": forbidden}
  if mode == "executor":
    monkeypatch.setattr(ws.adapter, "launch_executor", lambda: forbidden, raising=False)
  with pytest.raises(DependencyError):
    runtime.run(ws, cwd=cwd, **options)
  assert fake_subprocess.calls == []


def test_closed_package_fd_refuses_before_owner_or_child(cooperative, fake_subprocess):
  ws, cwd, trace, _, control, _ = cooperative
  control["closed_package"] = True
  with pytest.raises(DependencyError):
    runtime.run(ws, cwd=cwd)
  assert "owner-enter" not in trace and fake_subprocess.calls == []


def test_only_exact_cooperative_type_is_accepted(cooperative, fake_subprocess, monkeypatch):
  ws, cwd, trace, _, _, _ = cooperative
  class DerivedLease(lifecycle.CooperativeRunLease):
    pass
  monkeypatch.setattr(lifecycle, "CooperativeRunLease", DerivedLease)
  with pytest.raises(DependencyError):
    runtime.run(ws, cwd=cwd)
  assert "owner-enter" not in trace and fake_subprocess.calls == []


def test_existing_pending_deployment_still_blocks_before_package_and_owner(cooperative, fake_subprocess):
  ws, cwd, trace, _, _, _ = cooperative
  (ws.state_root / "pending.json").write_bytes(b"{}")
  with pytest.raises(Conflict):
    runtime.run(ws, cwd=cwd)
  assert trace == ["physical-enter", "physical-exit"] and fake_subprocess.calls == []


def test_out_of_range_package_fd_has_fixed_dependency_failure(cooperative, fake_subprocess):
  ws, cwd, trace, _, control, _ = cooperative
  control["package_fd"] = 1 << 100
  with pytest.raises(DependencyError) as error:
    runtime.run(ws, cwd=cwd)
  assert error.value.exit_code == 5 and fake_subprocess.calls == [] and "owner-enter" not in trace
