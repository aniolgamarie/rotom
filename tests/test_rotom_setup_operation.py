"""setup等价操作接缝：假计划和后端，不使用宿主或真实配置。"""
from contextlib import contextmanager
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest

from agentcfg import commands


@pytest.fixture
def operation(monkeypatch):
  events = []
  first = SimpleNamespace(agent="omp", profile="synthetic", adapter=SimpleNamespace())
  second = SimpleNamespace(agent="omp", profile="synthetic", adapter=SimpleNamespace())
  lock, candidate = SimpleNamespace(identity="lock"), SimpleNamespace(generation="generation")
  summary = {"changes": 1, "drift": 0, "conflicts": 0}
  def plan(label):
    value = SimpleNamespace(conflicts=[], drift=[])
    def public(): events.append(label + "-public"); return dict(summary)
    value.public = public
    return value
  initial, updated = plan("initial"), plan("updated")
  args = SimpleNamespace(command="setup")
  state = SimpleNamespace(events=events, first=first, second=second, lock=lock, candidate=candidate,
    initial=initial, updated=updated, args=args, result={"changes": 1}, summary=summary, preparations=0)
  def prepared(args):
    state.preparations += 1
    events.append("prepare" + str(state.preparations))
    return (first if state.preparations == 1 else second), state.lock, state.candidate
  def current(w, actual_lock, actual_candidate):
    assert actual_lock is state.lock and actual_candidate is state.candidate
    events.append("plan")
    return initial if w is first else updated
  def preflight(w): assert w is first; events.append("preflight")
  def resources(w, actual_lock): assert w is first and actual_lock is lock; events.append("resources")
  first.adapter.pre_sync_preflight = preflight
  first.adapter.prepare_setup_resources = resources
  def sync(w, actual_lock, progress):
    assert w is first and actual_lock is lock and progress is state.progress.sync_stage
    events.append("sync")
  def apply(w, actual_lock, actual_candidate, *, expected_plan):
    assert w is second and actual_lock is state.lock and actual_candidate is state.candidate
    assert expected_plan is updated
    events.append("apply")
    return state.result
  def preview(w, value): assert w is first and value == summary; events.append("preview")
  def approve(w, actual_lock, actual_candidate, actual_plan):
    assert (w, actual_lock, actual_candidate, actual_plan) == (first, lock, candidate, initial)
    events.append("approve")
  class Progress:
    sync_stage = object()
    def stage(self, label, *, hint): events.append("stage:" + hint)
    @contextmanager
    def heartbeat(self):
      events.append("heartbeat-enter")
      try: yield
      finally: events.append("heartbeat-exit")
  state.progress, state.preview, state.approve = Progress(), preview, approve
  for name, value in (("prepared", prepared), ("current_plan", current), ("sync_backend", sync), ("apply_candidate", apply)):
    monkeypatch.setattr(commands, name, value)
  monkeypatch.setattr(commands, "failure_context", lambda *a, **kw: pytest.fail("core diagnostic output"))
  monkeypatch.setattr(commands, "emit_result", lambda *a, **kw: pytest.fail("core JSON output"))
  return state


def invoke(state):
  return commands._setup_operation(state.args, progress=state.progress, preview=state.preview, approve=state.approve)


def test_operation_exact_order_original_result_and_no_output_or_outer_guard(operation, capsys):
  def forbidden(*args, **kw): pytest.fail("outer physical guard changes lock sequence")
  operation.first.adapter.apply_lifecycle_guard_for = forbidden
  operation.first.adapter.lifecycle_guard = forbidden
  result = invoke(operation)
  assert result.workspace is operation.second and result.code == 0 and result.result is operation.result
  assert result.reason is None and result.hint is None
  assert operation.events == ["stage:validate", "prepare1", "stage:plan", "plan", "initial-public", "preview",
    "approve", "preflight", "resources", "stage:doctor", "heartbeat-enter", "sync", "heartbeat-exit",
    "stage:plan", "prepare2", "plan", "updated-public", "stage:plan", "apply"]
  assert capsys.readouterr() == ("", "")
  with pytest.raises(FrozenInstanceError): result.code = 4


@pytest.mark.parametrize("condition", ["conflicts", "drift"])
def test_unsafe_preview_returns_fixed_failure_before_approval_or_sync(operation, condition, capsys):
  setattr(operation.initial, condition, ["synthetic-private-canary"])
  result = invoke(operation)
  assert result.workspace is operation.first and result.code == 4 and result.result is None
  assert result.reason == "存在冲突或漂移，部署已停止。" and result.hint == "plan"
  assert not {"approve", "preflight", "resources", "sync", "apply"}.intersection(operation.events)
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("change", ["generation", "lock", "summary"])
def test_post_sync_changes_reject_without_apply(operation, monkeypatch, change):
  original = commands.sync_backend
  def changed(*args):
    original(*args)
    if change == "generation": operation.candidate = SimpleNamespace(generation="other")
    elif change == "lock": operation.lock = SimpleNamespace(identity="other")
    else: operation.summary["changes"] = 2
  monkeypatch.setattr(commands, "sync_backend", changed)
  result = invoke(operation)
  assert result.workspace is operation.second and result.code == 4 and result.result is None
  assert result.reason == "同步期间配置或目标发生变化；请重新运行 setup。" and result.hint == "setup"
  assert "apply" not in operation.events


@pytest.mark.parametrize("site", ["preview", "approve", "preflight", "resources", "sync", "apply"])
@pytest.mark.parametrize("error_type", [ValueError, KeyboardInterrupt, SystemExit])
def test_original_errors_and_control_interrupt_propagate(operation, monkeypatch, site, error_type):
  error = error_type("synthetic-private-canary")
  def failed(*args, **kwargs): raise error
  if site in ("preview", "approve"): setattr(operation, site, failed)
  elif site in ("preflight", "resources"):
    setattr(operation.first.adapter, "pre_sync_preflight" if site == "preflight" else "prepare_setup_resources", failed)
  else: monkeypatch.setattr(commands, "sync_backend" if site == "sync" else "apply_candidate", failed)
  with pytest.raises(error_type) as caught: invoke(operation)
  assert caught.value is error
  if site != "apply": assert "apply" not in operation.events


def test_approval_is_required_explicit_callback(operation):
  with pytest.raises(TypeError):
    commands._setup_operation(operation.args, progress=operation.progress, preview=operation.preview)


@pytest.mark.parametrize("code", [0, 4])
def test_cli_delegates_same_core_preserving_preview_confirmation_and_result(operation, monkeypatch, capsys, code):
  confirmations, failures = [], []
  operation.args.invocation_context = SimpleNamespace(explicit_fields=set(),
    input_policy="synthetic-policy", input_gateway=SimpleNamespace(confirm=lambda *a, **kw: confirmations.append((a, kw))))
  def core(args, *, progress, preview, approve):
    assert args is operation.args
    preview(operation.first, operation.summary)
    approve(operation.first, operation.lock, operation.candidate, operation.initial)
    return commands.SetupResult(operation.second, code, operation.result if code == 0 else None,
      "synthetic-fixed-reason" if code else None, "plan" if code else None)
  monkeypatch.setattr(commands, "_setup_operation", core)
  monkeypatch.setattr(commands, "failure_context", lambda *a, **kw: failures.append((a, kw)))
  monkeypatch.setattr(commands, "command_line", lambda *a: "rotom run")
  assert commands.cmd_setup(operation.args) == code
  captured = capsys.readouterr()
  assert "部署预览" in captured.err and "部署预览" not in captured.out
  assert len(confirmations) == 1
  assert ("部署完成" in captured.out) == (code == 0)
  assert len(failures) == (code == 4)
