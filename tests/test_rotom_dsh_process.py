"""共享启动生命周期：全部假 Popen/host，不启动原生宿主。"""
from types import SimpleNamespace

import pytest

from agentcfg import dsh_process as process, dsh_sessions, spawned_host


@pytest.fixture
def launch(monkeypatch, tmp_path):
  state = SimpleNamespace(trace=[], code=19, wait_error=None, spawn_error=None,
    close_error=None, capture_error=None, unavailable=False, calls=[], closed=0)
  handle = object.__new__(spawned_host.SpawnedHost)
  def close(self):
    state.trace.append("close"); state.closed += 1
    if state.close_error: raise state.close_error
  monkeypatch.setattr(spawned_host.SpawnedHost, "close", close)
  class Child:
    returncode = None
    waits = 0
    def wait(self):
      assert state.closed == 0
      state.trace.append("wait"); self.waits += 1
      if state.wait_error: raise state.wait_error
      self.returncode = state.code
      return state.code
    def forbidden(self, *args, **kw): pytest.fail("no control, polling, input or Popen context")
    kill = terminate = send_signal = communicate = poll = __enter__ = forbidden
  state.child = Child()
  def popen(*args, **kwargs):
    state.trace.append("popen"); state.calls.append((args, kwargs))
    if state.spawn_error: raise state.spawn_error
    return state.child
  def capture(child, manager):
    assert child is state.child and manager is state.manager and child.waits == 0
    state.trace.append("capture")
    if state.capture_error: raise state.capture_error
    return None if state.unavailable else handle
  def bind(run, actual):
    assert run == "a" * 32 and actual is handle and state.closed == 0
    state.trace.append("bind")
  def before(run): assert run == "a" * 32; state.trace.append("before")
  def after(run): assert run == "a" * 32; state.trace.append("after")
  class Attempt:
    def launched(self): state.trace.append("launched")
    def exited(self, code):
      assert code == (state.code if state.code >= 0 else 128 - state.code)
      assert state.closed == 0
      state.trace.append("exited")
  state.spec = SimpleNamespace(argv=("synthetic-node", "synthetic-entry"), cwd=tmp_path)
  state.env = {"SYNTHETIC": "non-secret"}; state.fds = (11, 12, 13)
  state.manager = {"pid": 101, "birth_id": "synthetic-birth"}
  state.options = dict(run_id="a" * 32, owner_registry=SimpleNamespace(bind_current_host=bind),
    manager_identity=state.manager, before_dispatch=before, after_dispatch=after, attempt=Attempt())
  monkeypatch.setattr(process.subprocess, "Popen", popen)
  monkeypatch.setattr(spawned_host, "capture_spawned_host", capture)
  return state


def invoke(state, **kwargs):
  return process.launch(state.spec, state.env, state.fds, **state.options, **kwargs)


@pytest.mark.parametrize("code", [0, 19, -15])
@pytest.mark.parametrize("resume", [False, True])
def test_exact_lifecycle_arguments_stdio_native_exit_and_owned_handle(launch, code, resume):
  launch.code = code
  assert invoke(launch, resume=resume) == (code if code >= 0 else 128 - code)
  assert launch.trace == ["before", "popen", "capture", "bind", "launched", "after", "wait", "exited", "close"]
  assert launch.calls == [((["synthetic-node", "synthetic-entry"],),
    {"cwd": launch.spec.cwd, "env": launch.env, "pass_fds": launch.fds})]
  assert launch.child.waits == 1 and launch.closed == 1


def test_default_optional_callbacks_do_not_capture_or_make_owner(launch):
  assert process.launch(launch.spec, launch.env, launch.fds, run_id="a" * 32) == 19
  assert launch.trace == ["popen", "wait"] and launch.closed == 0


@pytest.mark.parametrize("site", ["before", "spawn"])
def test_pre_spawn_failure_does_not_wait_capture_or_notify(launch, site):
  error = OSError("synthetic-private-canary")
  if site == "spawn": launch.spawn_error = error
  else:
    def failed(*args): raise error
    launch.options["before_dispatch"] = failed
  with pytest.raises(OSError) as caught: invoke(launch)
  assert caught.value is error
  assert launch.trace == (["before", "popen"] if site == "spawn" else [])
  assert launch.child.waits == 0 and launch.closed == 0


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("site", ["unavailable", "capture", "bind", "launched", "after", "exited"])
def test_optional_observation_fault_keeps_one_wait_and_fixed_mode_label(launch, site, resume, capsys):
  def failed(*args): raise ValueError("synthetic-private-canary")
  if site == "unavailable": launch.unavailable = True
  elif site == "capture": launch.capture_error = ValueError("synthetic-private-canary")
  elif site == "bind": launch.options["owner_registry"].bind_current_host = failed
  elif site == "launched": launch.options["attempt"].launched = failed
  elif site == "after": launch.options["after_dispatch"] = failed
  else: launch.options["attempt"].exited = failed
  assert invoke(launch, resume=resume) == 19
  text = capsys.readouterr().err
  assert "synthetic-private-canary" not in text
  assert ("恢复" in text) is resume
  assert "启动" in text or "派发" in text or "退出" in text or "进程身份" in text
  assert launch.child.waits == 1 and len(launch.calls) == 1
  assert launch.closed == (0 if site in ("unavailable", "capture") else 1)


@pytest.mark.parametrize("kind", [TimeoutError, ConnectionError, ValueError])
@pytest.mark.parametrize("resume", [False, True])
def test_wait_unknown_fixed_token_once_without_control_or_retry(launch, kind, resume):
  launch.wait_error = kind("synthetic-private-canary")
  with pytest.raises(process.WaitUnconfirmed) as caught: invoke(launch, resume=resume)
  assert str(caught.value) == ("dsh_resume_wait_unconfirmed" if resume else "dsh_run_wait_unconfirmed")
  assert launch.child.waits == 1 and len(launch.calls) == 1 and launch.closed == 1
  assert "exited" not in launch.trace


@pytest.mark.parametrize("site", ["capture", "bind", "launched", "after", "wait", "exited"])
@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_new_control_interrupt_propagates_without_retry(launch, site, kind):
  error = kind("synthetic-control")
  def failed(*args): raise error
  if site == "capture": launch.capture_error = error
  elif site == "bind": launch.options["owner_registry"].bind_current_host = failed
  elif site == "launched": launch.options["attempt"].launched = failed
  elif site == "after": launch.options["after_dispatch"] = failed
  elif site == "wait": launch.wait_error = error
  else: launch.options["attempt"].exited = failed
  with pytest.raises(kind) as caught: invoke(launch)
  assert caught.value is error and len(launch.calls) == 1
  assert launch.closed == (0 if site == "capture" else 1)
  assert launch.child.waits == (1 if site in ("wait", "exited") else 0)


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_close_control_does_not_override_existing_wait_control(launch, kind):
  error = kind("synthetic-primary")
  launch.wait_error = error; launch.close_error = KeyboardInterrupt("synthetic-secondary")
  with pytest.raises(kind) as caught: invoke(launch)
  assert caught.value is error and launch.closed == 1 and launch.child.waits == 1


def test_new_close_interrupt_after_exited_fact_is_not_hidden(launch):
  error = KeyboardInterrupt("synthetic-cleanup")
  launch.close_error = error
  with pytest.raises(KeyboardInterrupt) as caught: invoke(launch)
  assert caught.value is error and launch.trace[-2:] == ["exited", "close"]


def test_resume_wrapper_delegates_and_keeps_exception_alias(launch, monkeypatch):
  calls = []
  def shared(*args, **kwargs): calls.append((args, kwargs)); return 23
  monkeypatch.setattr(process, "launch", shared)
  receipt = dsh_sessions._launch(launch.spec, launch.env, launch.fds, **launch.options)
  assert receipt.run_id == "a" * 32 and receipt.exit_code == 23
  assert calls == [((launch.spec, launch.env, launch.fds), {**launch.options, "resume": True})]
  assert dsh_sessions._WaitUnconfirmed is process.WaitUnconfirmed
