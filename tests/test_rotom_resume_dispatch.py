"""live 派发状态；独立 fake Popen 不执行宿主或回退真实子进程。"""

from collections import deque
from types import SimpleNamespace
from pathlib import Path
import subprocess

import pytest

from agentcfg import dsh_sessions, sessions
from test_rotom_resume import assert_pending, known


@pytest.fixture
def fake_popen(offline_guards, monkeypatch):
  class Child:
    def __init__(self, plan, trace):
      self.plan = plan
      self.trace = trace
      self.returncode = None
      self.wait_calls = 0

    def wait(self):
      self.wait_calls += 1
      self.trace.append("wait")
      if self.plan["on_wait"] is not None:
        self.plan["on_wait"]()
      if self.plan["wait_error"] is not None:
        raise self.plan["wait_error"]
      self.returncode = self.plan["returncode"]
      assert type(self.returncode) is int
      return self.returncode

    def kill(self):
      pytest.fail("未知/展示异常不得强杀已启动宿主")

    def terminate(self):
      pytest.fail("未知/展示异常不得终止已启动宿主")

    def communicate(self, *args, **kwargs):
      pytest.fail("普通恢复不得向宿主发送输入")

    def __enter__(self):
      pytest.fail("不得使用可能自动 kill 的 Popen context manager")

    def __exit__(self, *args):
      pytest.fail("不得使用 Popen context manager")

  class Factory:
    def __init__(self):
      self.plans = deque()
      self.calls = []
      self.children = []
      self.trace = []

    def queue(self, *, returncode=None, on_wait=None, spawn_error=None, wait_error=None):
      self.plans.append({"returncode": returncode, "on_wait": on_wait,
        "spawn_error": spawn_error, "wait_error": wait_error})

    def __call__(self, argv, *, cwd, env, pass_fds):
      assert self.plans, "fake Popen requires an explicit plan"
      assert cwd is not None and isinstance(pass_fds, tuple)
      self.trace.append("popen")
      self.calls.append({"argv": list(argv), "cwd": cwd, "env": dict(env), "pass_fds": pass_fds})
      plan = self.plans.popleft()
      if plan["spawn_error"] is not None:
        raise plan["spawn_error"]
      child = Child(plan, self.trace)
      self.children.append(child)
      return child

  fake = Factory()
  monkeypatch.setattr(subprocess, "Popen", fake)
  return fake


def backend_for(target):
  class Backend(sessions.HostResumeBackend):
    calls = 0

    def resume_session(self, selected, *, location, before_dispatch, after_dispatch):
      assert selected == target and location == "here"
      self.calls += 1
      spec = SimpleNamespace(argv=("synthetic-native", "--resume", target.ref.native_ref),
        cwd=Path(target.cwd))
      return dsh_sessions._launch(spec, {}, (), run_id="c" * 32,
        before_dispatch=before_dispatch, after_dispatch=after_dispatch)

  return Backend()


def test_snapshot_is_dispatched_while_the_native_child_is_still_waiting(tmp_path, fake_popen):
  target = known(sessions, tmp_path)
  backend = backend_for(target)
  coordinator = sessions.ResumeCoordinator(backend)
  during = []
  def on_wait():
    snapshot = coordinator.snapshot()
    assert_pending(snapshot, target, status="launch_dispatched")
    assert snapshot.reason == "load_unconfirmed" and snapshot.run_id == "c" * 32
    assert coordinator.resume(target, location="here") == snapshot
    during.append(snapshot)
  fake_popen.queue(returncode=0, on_wait=on_wait)
  outcome = coordinator.resume(target, location="here")
  assert_pending(outcome, target, status="launch_dispatched")
  assert len(during) == 1 and backend.calls == 1 and len(fake_popen.calls) == 1
  assert fake_popen.children[0].wait_calls == 1


def test_launch_calls_before_popen_after_then_wait_in_order(tmp_path, fake_popen):
  fake_popen.queue(returncode=17)
  spec = SimpleNamespace(argv=("synthetic-native",), cwd=tmp_path)
  receipt = dsh_sessions._launch(spec, {"SYNTHETIC": "plain"}, (), run_id="c" * 32,
    before_dispatch=lambda run_id: fake_popen.trace.append("before"),
    after_dispatch=lambda run_id: fake_popen.trace.append("after"))
  assert fake_popen.trace == ["before", "popen", "after", "wait"]
  assert receipt == sessions.LaunchReceipt(run_id="c" * 32, exit_code=17)


def test_failed_spawn_never_calls_after_or_wait(tmp_path, fake_popen):
  fake_popen.queue(spawn_error=OSError("synthetic-spawn-detail"))
  spec = SimpleNamespace(argv=("synthetic-native",), cwd=tmp_path)
  with pytest.raises(OSError):
    dsh_sessions._launch(spec, {}, (), run_id="c" * 32,
      before_dispatch=lambda run_id: fake_popen.trace.append("before"),
      after_dispatch=lambda run_id: pytest.fail("spawn失败不能证明派发完成"))
  assert fake_popen.trace == ["before", "popen"] and fake_popen.children == []


@pytest.mark.parametrize("failure", [RuntimeError, ConnectionError])
def test_after_callback_failure_keeps_waiting_and_preserves_native_exit(tmp_path, fake_popen, failure):
  fake_popen.queue(returncode=-15)
  spec = SimpleNamespace(argv=("synthetic-native",), cwd=tmp_path)
  def broken(run_id):
    fake_popen.trace.append("after")
    raise failure("synthetic-observer-detail")
  receipt = dsh_sessions._launch(spec, {}, (), run_id="c" * 32,
    before_dispatch=lambda run_id: fake_popen.trace.append("before"), after_dispatch=broken)
  assert receipt.exit_code == 143
  assert fake_popen.trace == ["before", "popen", "after", "wait"]
  assert fake_popen.children[0].wait_calls == 1


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError])
def test_wait_failure_is_unknown_without_kill_wait_retry_or_redispatch(tmp_path, fake_popen, failure):
  target = known(sessions, tmp_path)
  backend = backend_for(target)
  coordinator = sessions.ResumeCoordinator(backend)
  fake_popen.queue(wait_error=failure("synthetic-private-wait"))
  outcome = coordinator.resume(target, location="here")
  assert_pending(outcome, target, status="unknown")
  assert outcome.run_id == "c" * 32 and "synthetic-private" not in str(outcome)
  assert coordinator.resume(target, location="here") == outcome
  assert backend.calls == 1 and len(fake_popen.calls) == 1
  assert fake_popen.children[0].wait_calls == 1
  # 此处不证明退出；真实 child 的继承 FD 与既有 unknown owner 负责保护资源。
  assert fake_popen.children[0].returncode is None


@pytest.mark.parametrize("code", [0, 4, 17, -15])
def test_notice_failure_does_not_change_control_or_exit_code(tmp_path, fake_popen, code):
  target = known(sessions, tmp_path)
  seen = []
  def notice(outcome):
    seen.append(outcome.status)
    raise RuntimeError("synthetic-display-detail")
  backend = backend_for(target)
  coordinator = sessions.ResumeCoordinator(backend, notice=notice)
  fake_popen.queue(returncode=code)
  outcome = coordinator.resume(target, location="here")
  assert_pending(outcome, target, status="launch_dispatched" if code == 0 else "failed")
  assert outcome.exit_code == (128 - code if code < 0 else code)
  assert "launch_dispatched" in seen
  assert backend.calls == 1 and fake_popen.children[0].wait_calls == 1
  assert "synthetic-display" not in str(outcome)


@pytest.mark.parametrize("violation", ["before-missing", "wrong-run", "duplicate"])
def test_after_dispatch_rejects_invalid_protocol_and_never_reexecutes(tmp_path, violation):
  target = known(sessions, tmp_path)
  class Backend(sessions.HostResumeBackend):
    calls = 0
    def resume_session(self, selected, *, location, before_dispatch, after_dispatch):
      self.calls += 1
      if violation != "before-missing":
        before_dispatch("c" * 32)
      after_dispatch("d" * 32 if violation == "wrong-run" else "c" * 32)
      if violation == "duplicate":
        after_dispatch("c" * 32)
      return sessions.LaunchReceipt(run_id="c" * 32)
  backend = Backend()
  coordinator = sessions.ResumeCoordinator(backend)
  for _ in range(2):
    with pytest.raises(sessions.SessionError) as caught:
      coordinator.resume(target, location="here")
    assert caught.value.code == 4
  assert coordinator.snapshot().status == "unknown" and backend.calls == 1
