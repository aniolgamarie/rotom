"""候选控制工厂的启动顺序；假 Popen/host/service，不发信号。"""

import subprocess
import sys
from types import SimpleNamespace

import pytest

from agentcfg import dsh_process as process
from agentcfg.storage import Conflict
from test_rotom_dsh_process import launch, invoke


@pytest.fixture
def controlled_launch(launch, monkeypatch):
  state = launch
  state.wait_results = [subprocess.TimeoutExpired("synthetic", 0.1), state.code]
  state.wait_arguments = []; state.factory_error = None; state.service_error = None
  state.service_close_error = None; state.service_closed = 0; state.service_calls = 0
  state.belongs = True; state.bound_host = None
  old_bind = state.options["owner_registry"].bind_current_host
  def bind(run, host):
    old_bind(run, host); state.bound_host = host
  state.options["owner_registry"].bind_current_host = bind
  class Child:
    returncode = None
    waits = 0
    def wait(self, **kwargs):
      assert state.closed == 0 and state.service_closed == 0
      self.waits += 1; state.trace.append("wait"); state.wait_arguments.append(kwargs)
      result = state.wait_results.pop(0)
      if isinstance(result, BaseException): raise result
      self.returncode = result
      return result
  state.child = Child()
  class Service:
    def __init__(self, run, host): self.run, self.host = run, host
    def belongs_to(self, run, host):
      return state.belongs and self.run == run and self.host is host
    def __call__(self):
      state.trace.append("service"); state.service_calls += 1
      if state.service_error: raise state.service_error
    def close(self):
      state.trace.append("service-close"); state.service_closed += 1
      if state.service_close_error: raise state.service_close_error
  monkeypatch.setitem(sys.modules, "agentcfg.stop_service", SimpleNamespace(StopService=Service))
  def factory(*, run_id, host):
    assert host is state.bound_host and state.child.waits == 0
    state.trace.append("factory")
    if state.factory_error: raise state.factory_error
    state.service = Service(run_id, host)
    return state.service
  state.factory = factory
  return state


@pytest.mark.parametrize("resume", [False, True])
def test_service_factory_runs_after_bound_host_and_start_notifications(controlled_launch, resume):
  state = controlled_launch
  assert invoke(state, control_factory=state.factory, resume=resume) == 19
  assert state.trace == ["before", "popen", "capture", "bind", "launched", "after", "factory",
    "wait", "service", "wait", "exited", "service-close", "close"]
  assert state.wait_arguments == [{"timeout": 0.1}, {"timeout": 0.1}]
  assert state.service_closed == state.closed == 1
  assert state.calls[0][1]["pass_fds"] == (11, 12, 13)


@pytest.mark.parametrize("site", ["unregistered", "no-host", "capture", "bind", "launched", "after"])
def test_incomplete_start_observation_never_creates_control_service(controlled_launch, site, capsys):
  state = controlled_launch; state.wait_results = [19]
  def failed(*args): raise OSError("synthetic-private-canary")
  if site == "unregistered": state.options["owner_registry"] = None
  elif site == "no-host": state.unavailable = True
  elif site == "capture": state.capture_error = OSError("synthetic-private-canary")
  elif site == "bind": state.options["owner_registry"].bind_current_host = failed
  elif site == "launched": state.options["attempt"].launched = failed
  else: state.options["after_dispatch"] = failed
  assert invoke(state, control_factory=state.factory) == 19
  assert "factory" not in state.trace and state.wait_arguments == [{}]
  assert state.service_closed == 0 and len(state.calls) == 1
  assert "synthetic-private-canary" not in capsys.readouterr().err


@pytest.mark.parametrize("result", [None, False, object()])
def test_wrong_factory_result_continues_original_child_wait(controlled_launch, capsys, result):
  state = controlled_launch; state.wait_results = [19]
  assert invoke(state, control_factory=lambda **kwargs: result) == 19
  assert state.wait_arguments == [{}] and state.service_closed == 0
  assert "停止" in capsys.readouterr().err


def test_foreign_service_is_not_used_or_closed(controlled_launch):
  state = controlled_launch; state.wait_results = [19]; state.belongs = False
  assert invoke(state, control_factory=state.factory) == 19
  assert state.service_calls == state.service_closed == 0 and state.wait_arguments == [{}]


@pytest.mark.parametrize("site", ["factory", "service"])
@pytest.mark.parametrize("kind", [OSError, ValueError])
def test_ordinary_service_failure_preserves_native_wait_and_fixed_diagnostic(controlled_launch, capsys, site, kind):
  state = controlled_launch; setattr(state, site + "_error", kind("synthetic-private-canary"))
  if site == "factory": state.wait_results = [19]
  assert invoke(state, control_factory=state.factory) == 19
  assert state.wait_arguments == ([{}] if site == "factory" else [{"timeout": 0.1}, {}])
  assert state.service_calls == (site == "service")
  assert state.service_closed == (site == "service") and state.closed == 1
  assert "synthetic-private-canary" not in capsys.readouterr().err


@pytest.mark.parametrize("site", ["factory", "service"])
@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_control_exception_is_original_without_retry(controlled_launch, site, kind):
  state = controlled_launch; error = kind("synthetic-control")
  setattr(state, site + "_error", error)
  with pytest.raises(kind) as caught: invoke(state, control_factory=state.factory)
  assert caught.value is error and "exited" not in state.trace
  assert state.child.waits == (site == "service") and state.closed == 1
  assert state.service_closed == (site == "service")


@pytest.mark.parametrize("first", [True, False])
def test_wait_error_does_not_rewait_restart_or_claim_exit(controlled_launch, first):
  state = controlled_launch
  state.wait_results = ([OSError("synthetic-private-canary")] if first else
    [subprocess.TimeoutExpired("synthetic", 0.1), OSError("synthetic-private-canary")])
  with pytest.raises(process.WaitUnconfirmed): invoke(state, control_factory=state.factory)
  assert state.child.waits == (1 if first else 2) and len(state.calls) == 1
  assert "exited" not in state.trace and state.service_closed == state.closed == 1


@pytest.mark.parametrize("primary", [None, ValueError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("cleanup", [OSError, KeyboardInterrupt, SystemExit])
def test_service_cleanup_does_not_override_existing_wait_error(controlled_launch, primary, cleanup):
  state = controlled_launch; state.service_close_error = cleanup("synthetic-cleanup")
  error = primary("synthetic-primary") if primary else None
  state.wait_results = [error if error else 19]
  expected = process.WaitUnconfirmed if primary is ValueError else primary
  if expected is None and cleanup in (KeyboardInterrupt, SystemExit): expected = cleanup
  if expected is None: assert invoke(state, control_factory=state.factory) == 19
  else:
    with pytest.raises(expected) as caught: invoke(state, control_factory=state.factory)
    if primary in (KeyboardInterrupt, SystemExit): assert caught.value is error
    elif primary is None: assert caught.value is state.service_close_error
  assert state.service_closed == state.closed == 1 and state.child.waits == 1


def test_invalid_factory_rejected_before_dispatch_callback_and_spawn(controlled_launch):
  state = controlled_launch
  with pytest.raises(Conflict): invoke(state, control_factory=True)
  assert state.trace == [] and state.calls == []
