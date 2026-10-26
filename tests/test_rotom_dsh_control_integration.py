"""候选停止服务贯穿真实临时部署/租约/记录；宿主、内核和批准证据完全模拟。"""

from copy import deepcopy
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from agentcfg import dsh_process, run_owners, runtime, sessions, spawned_host
from agentcfg.backends import DshBackend
from agentcfg.resume_attempts import ResumeAttempts
from agentcfg.stop_dispatches import StopDispatches
from agentcfg.stop_inbox import StopInbox
from agentcfg.stop_service import StopService
from agentcfg.storage import Conflict
from test_rotom_dsh_resume import candidate
from test_rotom_resume_runtime import managed, assert_exclusive_busy, assert_exclusive_free
from test_rotom_runtime_observation import observation
from test_rotom_spawned_host import fake


_RUN_CHILD = runtime._run_dsh_child


@pytest.fixture
def chain(candidate, fake, fake_subprocess, monkeypatch):
  module, workspace, lock, target, package = candidate
  # 本套专测显式 fake 服务接缝；默认工厂由独立套件验证，不叠加两次工厂。
  monkeypatch.setattr("agentcfg.dsh_stop_control.default_factory", lambda *args, **kwargs: None)
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  resumes = ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding)
  case = SimpleNamespace(module=module, workspace=workspace, target=target, package=package,
    fake=fake, calls=[], waits=[], signals=[], complete=False, mode="run", failure=None,
    now=1000000000, exit_code=-15, registry=registry, resumes=resumes, extra_package_lease=True)
  monkeypatch.setattr("agentcfg.stop_locks.time.monotonic_ns", lambda: case.now)
  paths = (workspace.instance, workspace.state_root / "instance.lock", package["path"])
  def leases():
    assert package["active"] is case.extra_package_lease
    for path in case.paths:
      assert_exclusive_busy(path)
  case.leases = leases
  case.paths = paths

  class FakeScope:
    def __init__(self, identity):
      assert identity == fake.manager
    def __enter__(self): return self
    def observe(self, run_id):
      if case.complete:
        return run_owners.ReleaseObservation(run_id, deepcopy(fake.manager), True, True)
    def __exit__(self, *args): pass
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(fake.manager))
  monkeypatch.setattr("agentcfg.descendants.DescendantScope", FakeScope)
  # fake_subprocess 默认隔离普通 DSH 启动；此处恢复真实 Python 调用链，仅在 Popen 边界造假。
  monkeypatch.setattr(runtime, "_run_dsh_child", _RUN_CHILD)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")

  def popen(argv, **kwargs):
    leases()
    assert len(kwargs["pass_fds"]) == len(set(kwargs["pass_fds"])) == (3 if case.extra_package_lease else 2)
    for fd in kwargs["pass_fds"]: os.fstat(fd)
    case.calls.append({"argv": argv, **kwargs})
    return fake.child
  monkeypatch.setattr(dsh_process.subprocess, "Popen", popen)
  def wait(**kwargs):
    leases()
    case.waits.append(kwargs)
    if len(case.waits) == 1:
      raise subprocess.TimeoutExpired("synthetic-host", kwargs["timeout"])
    if case.failure == "wait":
      raise OSError("synthetic-private-canary")
    fake.child.returncode = case.exit_code
    return case.exit_code
  fake.child.wait = wait

  def factory(*, run_id, host):
    leases()
    case.run_id, case.host = run_id, host
    owner = registry.snapshot()[run_id]
    assert owner["lifecycle_state"] == "active"
    assert owner["host_identity"] == host.snapshot()
    assert owner["session_observation"] is None and owner["protocol"]["control"] is None
    attempt = resumes.for_owner(owner)
    if case.mode == "resume":
      assert attempt["dispatch"] == "launched"
      assert attempt["load_confirmation"] == "unknown" and attempt["continue_status"] == "not_sent"
    else:
      assert attempt is None
    case.inbox = StopInbox(workspace.state_root / "control" / run_id, workspace.binding)
    case.journal = StopDispatches(workspace.state_root / "stop-dispatches", workspace.binding)
    def verify(request):
      # 这是测试批准，不是生产 DSH 的资源闭包/批次授权实现。
      leases()
      current = registry.snapshot()[run_id]
      assert current["lifecycle_state"] == "active" and current["host_identity"] == host.snapshot()
      assert request == case.request
      return case.failure != "denied"
    case.service = StopService(run_id, host, inbox=case.inbox, journal=case.journal,
      verify=verify, clock=lambda: case.now)
    bound = host.snapshot()
    case.request = {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop",
      "request_id": "b" * 32, "batch_id": "c" * 32, "plan_id": "d" * 64,
      "run_id": run_id, "manager_identity": bound["manager_identity"],
      "host_identity": bound["identity"], "deadline_ns": 2000000000}
    case.inbox.submit(case.request, expected=case.inbox.describe())
    if case.failure == "expired": case.now = case.request["deadline_ns"]
    return case.service
  launch = dsh_process.launch
  def controlled(*args, **kwargs):
    return launch(*args, **kwargs, control_factory=factory)
  monkeypatch.setattr(dsh_process, "launch", controlled)
  def send(fd, number, info, flags):
    assert (fd, number, info, flags) == (77, 15, None, 0)
    leases()
    assert case.journal.read(case.run_id)["dispatch"] == "unknown"
    assert registry.snapshot()[case.run_id]["lifecycle_state"] == "active"
    case.signals.append((fd, number, info, flags))
    if case.failure == "send": raise InterruptedError("synthetic-private-canary")
  monkeypatch.setattr(spawned_host.signal, "SIGTERM", 15, raising=False)
  monkeypatch.setattr(spawned_host.signal, "pidfd_send_signal", send, raising=False)
  return case


def invoke(case):
  if case.mode == "run":
    return runtime.run(case.workspace, cwd=Path(case.target.cwd))
  result = sessions.ResumeCoordinator(case.module.DshResumeCandidate(case.workspace)).resume(
    case.target, location="here")
  assert result.status == "failed" and result.exit_code == 143
  assert result.session is None and result.cwd is None and result.input_ready is False
  assert result.requested_session == case.target.ref and result.requested_cwd == case.target.cwd
  assert result.continue_status == "not_sent"
  return result.exit_code


def assert_closed(case):
  assert len(case.calls) == 1 and case.calls[0]["cwd"] == Path(case.target.cwd)
  assert case.fake.opens == [(202, 0)] and case.fake.closes == [77]
  assert not case.service.belongs_to(case.run_id, case.host)
  with pytest.raises(Conflict): case.service()
  assert len(case.inbox.pending(expected=case.inbox.describe())) == 1
  assert case.package["active"] is False
  for path in case.paths: assert_exclusive_free(path)
  owner = case.registry.snapshot()[case.run_id]
  assert owner["lifecycle_state"] == ("idle_confirmed" if case.complete else "unknown")
  assert owner["session_observation"] is None and owner["protocol"]["control"] is None
  attempt = case.resumes.for_owner(owner)
  if case.mode == "resume":
    assert attempt["exit_code"] == 143 and attempt["load_confirmation"] == "unknown"
    assert attempt["continue_status"] == "not_sent"


@pytest.mark.parametrize("mode", ["run", "resume"])
@pytest.mark.parametrize("complete", [False, True])
def test_stop_keeps_three_leases_and_release_requires_independent_scope_proof(chain, mode, complete):
  chain.mode, chain.complete = mode, complete
  assert invoke(chain) == 143
  assert chain.signals == [(77, 15, None, 0)]
  assert chain.journal.read(chain.run_id)["dispatch"] == "signal_sent"
  assert chain.waits == [{"timeout": 0.1}, {"timeout": 0.1}]
  assert_closed(chain)


@pytest.mark.parametrize("mode", ["run", "resume"])
@pytest.mark.parametrize("failure", ["expired", "denied", "send"])
def test_unconfirmed_stop_disables_service_and_waits_same_host_without_replay(chain, mode, failure, capsys):
  chain.mode, chain.failure = mode, failure
  assert invoke(chain) == 143
  assert len(chain.signals) == (1 if failure == "send" else 0)
  saved = chain.journal.read(chain.run_id)
  assert saved is None if failure != "send" else saved["dispatch"] == "unknown"
  assert chain.waits == [{"timeout": 0.1}, {}]
  assert_closed(chain)
  diagnostic = capsys.readouterr().err
  assert "停止请求处理未能确认" in diagnostic and "synthetic-private-canary" not in diagnostic


def test_wait_failure_after_sent_request_keeps_unknown_owner_and_does_not_wait_again(chain, capsys):
  chain.failure = "wait"
  with pytest.raises(Conflict) as caught: invoke(chain)
  assert "synthetic-private-canary" not in str(caught.value)
  assert len(chain.signals) == 1 and chain.journal.read(chain.run_id)["dispatch"] == "signal_sent"
  assert chain.waits == [{"timeout": 0.1}, {"timeout": 0.1}]
  assert_closed(chain)


@pytest.mark.parametrize("mode", ["run", "resume"])
def test_actual_dsh_backend_without_extra_package_guard_keeps_instance_and_state_leases(chain, mode, monkeypatch):
  # 正式 DSH 包在实例目录内，后端没有独立 package_guard；第三把租约只属上方扩展接缝测试。
  monkeypatch.delattr(DshBackend, "runtime_guard")
  chain.mode, chain.extra_package_lease = mode, False
  chain.paths = chain.paths[:2]
  assert invoke(chain) == 143
  assert len(chain.calls[0]["pass_fds"]) == 2 and len(chain.signals) == 1
  assert chain.journal.read(chain.run_id)["dispatch"] == "signal_sent"
  assert not chain.package["path"].exists()
  assert_closed(chain)
