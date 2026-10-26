"""可选维护对象沿原 setup 接缝传递；只验证 plumbing，不实现或消费执行许可。"""
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
import fcntl
import os
import sys

import pytest

from agentcfg import commands, deployment, omp_admission, omp_setup
from agentcfg.omp import OmpAdapter
from agentcfg.storage import Conflict, Tree, instance_lock
from test_rotom_setup_operation import operation
from test_deployment import BINDING, LAUNCH, candidate


def test_setup_passes_same_object_after_approval_and_keeps_sync(operation, monkeypatch):
  token, calls = object(), []
  def preflight(w, *, maintenance):
    assert w is operation.first and maintenance is token
    calls.append("preflight")
  def resources(w, lock, *, maintenance):
    assert w is operation.first and lock is operation.lock and maintenance is token
    calls.append("resources")
  def sync(w, lock, progress, *, maintenance):
    assert w is operation.first and lock is operation.lock and maintenance is token
    assert progress is operation.progress.sync_stage
    calls.append("sync")
  def apply(w, lock, proposed, *, expected_plan, maintenance):
    assert w is operation.second and lock is operation.lock and proposed is operation.candidate
    assert expected_plan is operation.updated and maintenance is token
    calls.append("apply")
    return operation.result
  def approve(*args):
    assert not calls
    calls.append("approve")
  operation.first.adapter.pre_sync_preflight = preflight
  operation.first.adapter.prepare_setup_resources = resources
  monkeypatch.setattr(commands, "sync_backend", sync)
  monkeypatch.setattr(commands, "apply_candidate", apply)
  result = commands._setup_operation(operation.args, progress=operation.progress, preview=operation.preview,
    approve=approve, maintenance=token)
  assert result.code == 0 and result.result is operation.result
  assert calls == ["approve", "preflight", "resources", "sync", "apply"]


@pytest.mark.parametrize("progress_supported", [False, True])
def test_sync_backend_forwards_explicit_maintenance_and_progress(progress_supported):
  token, events, lock = object(), [], object()
  def with_progress(ws, actual_lock, *, progress, maintenance):
    assert actual_lock is lock and maintenance is token
    progress("synthetic")
    return "result"
  def without_progress(ws, actual_lock, *, maintenance):
    assert actual_lock is lock and maintenance is token
    return "result"
  ws = SimpleNamespace(backend=SimpleNamespace(sync=with_progress if progress_supported else without_progress))
  assert commands.sync_backend(ws, lock, events.append, maintenance=token) == "result"
  assert events == (["synthetic"] if progress_supported else ["检查运行包"])


@pytest.mark.parametrize("kind", ["legacy", "kwargs", "positional-only"])
def test_maintenance_sync_requires_explicit_keyword_parameter(kind):
  calls = []
  def legacy(w, lock): calls.append(True)
  def kwargs(w, lock, **options): calls.append(True)
  def positional(w, lock, maintenance, /): calls.append(True)
  ws = SimpleNamespace(backend=SimpleNamespace(sync={"legacy": legacy, "kwargs": kwargs, "positional-only": positional}[kind]))
  with pytest.raises(Conflict):
    commands.sync_backend(ws, object(), lambda value: calls.append(value), maintenance=object())
  assert calls == []


def test_ordinary_sync_retains_two_argument_backend():
  ws, lock, events = SimpleNamespace(), object(), []
  def sync(actual, actual_lock):
    assert actual is ws and actual_lock is lock
    return "result"
  ws.backend = SimpleNamespace(sync=sync)
  assert commands.sync_backend(ws, lock, events.append) == "result"
  assert events == ["检查运行包"]


@pytest.mark.parametrize("maintenance_mode", [False, True])
def test_apply_candidate_uses_original_instance_fd_and_forwards_state_guard(monkeypatch, maintenance_mode):
  events, instance_fd, state_fd = [], object(), object()
  ws = SimpleNamespace(instance=Path("/synthetic/instance"), state_root=Path("/synthetic/state"), binding={})
  lock, proposed, expected = object(), object(), object()
  @contextmanager
  def apply_guard(actual, actual_lock, actual_candidate, plan, **fds):
    assert (actual, actual_lock, actual_candidate, plan) == (ws, lock, proposed, expected)
    assert fds == {"instance_fd": instance_fd, "state_fd": state_fd}
    assert events == ["instance-enter", "apply"]
    events.append("maintenance-enter")
    yield
    events.append("maintenance-exit")
  token = SimpleNamespace(apply_guard=apply_guard) if maintenance_mode else None
  @contextmanager
  def guard_for(actual, actual_lock, **options):
    assert actual is ws and actual_lock is lock
    assert options == ({"maintenance": token} if maintenance_mode else {})
    events.append("instance-enter")
    yield instance_fd
    events.append("instance-exit")
  ws.adapter = SimpleNamespace(apply_lifecycle_guard_for=guard_for)
  monkeypatch.setattr(commands.runtime, "record", lambda *args: {})
  def apply(*args, **options):
    events.append("apply")
    assert options["expected_plan"] is expected
    if maintenance_mode:
      with options["maintenance_guard"](state_fd):
        events.append("body")
    else:
      assert "maintenance_guard" not in options
    return "result"
  monkeypatch.setattr(deployment, "apply", apply)
  assert commands.apply_candidate(ws, lock, proposed, expected_plan=expected, maintenance=token) == "result"
  assert events == (["instance-enter", "apply", "maintenance-enter", "body", "maintenance-exit", "instance-exit"]
    if maintenance_mode else ["instance-enter", "apply", "instance-exit"])


def test_maintenance_apply_rejects_missing_parameterized_guard_before_legacy(monkeypatch):
  def forbidden(*args, **kwargs): pytest.fail("legacy admission must not run")
  ws = SimpleNamespace(adapter=SimpleNamespace(lifecycle_guard=forbidden))
  monkeypatch.setattr(deployment, "apply", forbidden)
  with pytest.raises(Conflict):
    commands.apply_candidate(ws, object(), object(), maintenance=object())


@pytest.mark.parametrize("method,delegate,needs_lock", [
  ("pre_sync_preflight", "preflight", False), ("prepare_setup_resources", "prepare", True),
  ("apply_lifecycle_guard_for", "apply_for", True)])
@pytest.mark.parametrize("maintenance_mode", [False, True])
def test_adapter_forwards_only_present_optional_object(monkeypatch, method, delegate, needs_lock, maintenance_mode):
  ws, lock, token = object(), object(), object()
  calls = []
  def action(*args, **options):
    assert args == ((ws, lock) if needs_lock else (ws,))
    assert options == ({"maintenance": token} if maintenance_mode else {})
    calls.append(True)
    return "result"
  monkeypatch.setattr(omp_admission, delegate, action)
  args = (ws, lock) if needs_lock else (ws,)
  result = getattr(OmpAdapter, method)(object(), *args, maintenance=token if maintenance_mode else None)
  assert calls == [True]
  assert result == (None if method == "pre_sync_preflight" else "result")


@pytest.mark.parametrize("claimed", [False, True])
def test_admission_preflight_uses_maintenance_scope_guard_only(monkeypatch, claimed):
  ws, token, events = SimpleNamespace(instance=Path("/synthetic/instance")), object(), []
  monkeypatch.setattr(omp_admission.scopes, "scope_claim_exists", lambda path: claimed)
  monkeypatch.setattr(omp_admission.omp_identity, "preflight_setup", lambda *args: pytest.fail("legacy preflight"))
  @contextmanager
  def guard(actual, *, maintenance, stage):
    assert actual is ws and maintenance is token and stage == "preflight"
    events.append("guard")
    yield
  monkeypatch.setattr(omp_admission, "omp_scope_write_guard", guard)
  if claimed:
    omp_admission.preflight(ws, maintenance=token)
    assert events == ["guard"]
  else:
    with pytest.raises(Conflict): omp_admission.preflight(ws, maintenance=token)
    assert events == []


@pytest.mark.parametrize("stage", ["prepare", "apply"])
@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_admission_routes_linux_maintenance_without_legacy(monkeypatch, stage, platform):
  ws, lock, token, events = object(), object(), object(), []
  monkeypatch.setattr(omp_admission.sys, "platform", platform)
  monkeypatch.setattr(omp_admission.runtime, "runtime_identity", lambda actual, actual_lock: "runtime")
  def prepare(actual, identity, *, maintenance):
    assert actual is ws and identity == "runtime" and maintenance is token
    events.append("prepare")
  @contextmanager
  def apply(actual, identity, *, maintenance):
    assert actual is ws and identity == "runtime" and maintenance is token
    events.append("apply")
    yield 42
  monkeypatch.setattr(omp_setup, "prepare_setup", prepare)
  monkeypatch.setattr(omp_setup, "apply_guard", apply)
  monkeypatch.setattr(omp_admission, "_require_legacy", lambda *args: pytest.fail("legacy selection"))
  def invoke():
    if stage == "prepare": omp_admission.prepare(ws, lock, maintenance=token)
    else:
      with omp_admission.apply_for(ws, lock, maintenance=token) as fd: assert fd == 42
  if platform == "linux":
    invoke()
    assert events == [stage]
  else:
    with pytest.raises(Conflict): invoke()
    assert events == []


@pytest.mark.parametrize("stage", ["prepare", "apply"])
@pytest.mark.parametrize("scope_claim,runtime_claim", [(True, True), (False, True), (True, False), (False, False)])
def test_setup_requires_existing_claims_and_runtime_check_before_original_guard(monkeypatch, stage, scope_claim, runtime_claim):
  token, events = object(), []
  ws = SimpleNamespace(instance=Path("/synthetic/instance"), cache=Path("/synthetic/cache"))
  def check_runtime(actual, identity, *, stage):
    assert actual is ws and identity == "runtime"
    events.append("check:" + stage)
  module = ModuleType("agentcfg.maintenance_execution")
  def require(actual):
    assert actual is token
    return SimpleNamespace(check_runtime=check_runtime)
  module.require_execution = require
  monkeypatch.setitem(sys.modules, "agentcfg.maintenance_execution", module)
  def context(actual, identity):
    assert events == ["check:" + stage]
    events.append("context")
    return object()
  monkeypatch.setattr(omp_setup, "_context", context)
  monkeypatch.setattr(omp_setup.scopes, "scope_claim_exists", lambda path: scope_claim)
  monkeypatch.setattr(omp_setup.coordination, "runtime_claim_exists", lambda *args: runtime_claim)
  def forbidden(*args, **kwargs): pytest.fail("must not create, enroll, or select legacy resources")
  monkeypatch.setattr(omp_setup, "_exists", forbidden)
  monkeypatch.setattr(omp_setup.coordination, "enroll_runtime", forbidden)
  monkeypatch.setattr(omp_setup.scopes, "enroll_scope", forbidden)
  @contextmanager
  def guard(actual, *, maintenance, stage):
    assert actual is ws and maintenance is token
    events.append("guard:" + stage)
    yield 42
  monkeypatch.setattr(omp_setup, "omp_scope_write_guard", guard)
  monkeypatch.setattr(omp_setup, "_check_runtime", lambda *args: events.append("original-runtime-check"))
  def invoke():
    if stage == "prepare": omp_setup.prepare_setup(ws, "runtime", maintenance=token)
    else:
      with omp_setup.apply_guard(ws, "runtime", maintenance=token) as fd: assert fd == 42
  if scope_claim and runtime_claim:
    invoke()
    assert events == ["check:" + stage, "context", "guard:" + stage] + (["original-runtime-check"] if stage == "prepare" else [])
  else:
    with pytest.raises(Conflict): invoke()
    assert events == ["check:" + stage, "context"]


def test_deployment_enters_maintenance_only_under_original_state_ex_and_covers_body(tmp_path, monkeypatch):
  instance, state = tmp_path / "instance", tmp_path / "state"
  deployment.apply(instance, state, candidate("A"), BINDING, LAUNCH)
  events, locks = [], []
  original_lock = deployment.instance_lock
  @contextmanager
  def lock(tree, **options):
    assert options == {"create": False}
    with original_lock(tree, **options) as fd:
      locks.append(fd)
      yield fd
  monkeypatch.setattr(deployment, "instance_lock", lock)
  @contextmanager
  def admission(fd):
    assert locks == [fd]
    assert os.fstat(fd).st_ino == (state / "instance.lock").stat().st_ino
    probe = os.open(state / "instance.lock", os.O_RDONLY)
    try:
      with pytest.raises(BlockingIOError):
        fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
      os.close(probe)
    assert events == []
    events.append("admission")
    yield
    events.append("exit")
  for name in ("guard_saved_state", "recover", "transact"):
    original = getattr(deployment, name)
    def observed(*args, _name=name, _original=original, **options):
      assert events[0] == "admission" and "exit" not in events
      events.append(_name)
      return _original(*args, **options)
    monkeypatch.setattr(deployment, name, observed)
  result = deployment.apply(instance, state, candidate("B"), BINDING, LAUNCH, maintenance_guard=admission)
  assert result["changes"] > 0
  assert events == ["admission", "guard_saved_state", "recover", "transact", "recover", "exit"]
  assert len(locks) == 1


@pytest.mark.parametrize("missing", ["state", "lock", "instance"])
def test_maintenance_deployment_does_not_create_missing_roots_or_lock(tmp_path, missing):
  instance, state = tmp_path / "instance", tmp_path / "state"
  if missing != "state": state.mkdir(mode=0o700)
  if missing == "instance":
    with Tree(state) as tree, instance_lock(tree): pass
  if missing != "instance": instance.mkdir(mode=0o700)
  @contextmanager
  def admission(fd):
    assert missing == "instance"
    yield
  with pytest.raises((Conflict, FileNotFoundError)):
    deployment.apply(instance, state, candidate("A"), BINDING, LAUNCH, maintenance_guard=admission)
  if missing == "state": assert not state.exists()
  elif missing == "lock": assert not (state / "instance.lock").exists()
  else: assert not instance.exists()


@pytest.mark.parametrize("site", ["guard_saved_state", "recover", "transact"])
def test_deployment_body_exceptions_propagate_unchanged_and_release_admission(tmp_path, monkeypatch, site):
  instance, state = tmp_path / "instance", tmp_path / "state"
  deployment.apply(instance, state, candidate("A"), BINDING, LAUNCH)
  error, events = ValueError("synthetic-private-canary"), []
  def failed(*args, **kwargs): raise error
  monkeypatch.setattr(deployment, site, failed)
  @contextmanager
  def admission(fd):
    events.append("enter")
    try: yield
    finally: events.append("exit")
  with pytest.raises(ValueError) as caught:
    deployment.apply(instance, state, candidate("B"), BINDING, LAUNCH, maintenance_guard=admission)
  assert caught.value is error and events == ["enter", "exit"]
  with Tree(state) as tree, instance_lock(tree, create=False): pass
