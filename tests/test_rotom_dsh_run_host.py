"""普通 managed DSH 与恢复共用进程边界；假进程，不探测真实身份。"""

from contextlib import nullcontext

import pytest

from agentcfg import run_owners, runtime, spawned_host
from agentcfg.process import DependencyError
from agentcfg.storage import Conflict
from test_rotom_resume_dispatch import fake_popen
from test_rotom_resume_host import HOST, capture, owner
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_runtime_observation import observation


_REAL_CHILD = runtime._run_dsh_child


@pytest.fixture
def normal(managed, fake_subprocess, fake_popen, capture, monkeypatch):
  # 只在本专属集成测试恢复本仓库的边界；Popen仍由显式假子进程接管。
  monkeypatch.setattr(runtime, "_run_dsh_child", _REAL_CHILD)
  # 本套验证原宿主登记边界；默认停止工厂另由独立接线套和原生验收覆盖。
  from agentcfg import dsh_stop_control
  monkeypatch.setattr(dsh_stop_control, "default_factory", lambda *args, **kwargs: None)
  return managed


def queue(fake_subprocess, fake_popen, code, **kwargs):
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  # 先行旧路径也有明确假结果，避免把fixture队列不足冒充缺实现。
  fake_subprocess.queue(returncode=code)
  fake_popen.queue(returncode=code, **kwargs)


@pytest.mark.parametrize("code", [0, 17, -15])
def test_normal_run_binds_child_and_keeps_original_stdio_argv_and_leases(normal,
    fake_subprocess, fake_popen, capture, tmp_path, code):
  workspace, lock, package, observed = normal
  during = []
  def wait():
    record = owner(workspace)
    assert record["host_identity"] == HOST and record["lifecycle_state"] == "active"
    assert record["protocol"]["control"] is None and record["session_observation"] is None
    assert capture["closed"] == 0 and package["active"]
    for path in (workspace.instance, workspace.state_root / "instance.lock", package["path"]):
      assert_exclusive_busy(path)
    during.append(record)
  queue(fake_subprocess, fake_popen, code, on_wait=wait)
  assert runtime.run(workspace, cwd=tmp_path, arguments=("--synthetic-arg",)) == (code if code >= 0 else 128-code)
  assert len(during) == 1 and len(fake_subprocess.calls) == 1 and len(fake_popen.calls) == 1
  call = fake_popen.calls[0]
  assert call["argv"][-1] == "--synthetic-arg" and call["cwd"] == tmp_path
  assert len(call["pass_fds"]) == 3 and call["env"]["DSH_HOME"] == str(workspace.instance / "dsh-home")
  assert capture["closed"] == 1 and owner(workspace)["host_identity"] == HOST
  assert not (workspace.state_root / "resume-attempts").exists()


@pytest.mark.parametrize("failure", ["capture", "attach"])
def test_observation_failure_keeps_native_result_without_resume_diagnostics(normal,
    fake_subprocess, fake_popen, capture, monkeypatch, capsys, tmp_path, failure):
  workspace, *_ = normal
  if failure == "capture":
    monkeypatch.setattr(spawned_host, "capture_spawned_host", lambda *args: None)
  else:
    def fail(*args): raise Conflict("synthetic private exception")
    monkeypatch.setattr(run_owners.Registry, "bind_current_host", fail)
  queue(fake_subprocess, fake_popen, 23)
  assert runtime.run(workspace, cwd=tmp_path) == 23
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1
  assert owner(workspace)["host_identity"] is None
  assert capture["closed"] == (0 if failure == "capture" else 1)
  out = capsys.readouterr().err
  assert "启动进程身份" in out and "恢复进程身份" not in out
  assert "synthetic private exception" not in out


@pytest.mark.parametrize("error", [ValueError, OSError, KeyboardInterrupt, SystemExit])
def test_uncertain_wait_preserves_unknown_and_never_kills_or_retries(normal,
    fake_subprocess, fake_popen, capture, tmp_path, error):
  workspace, *_ = normal
  problem = error("synthetic private wait")
  queue(fake_subprocess, fake_popen, 29, wait_error=problem)
  expected = Conflict if error in (ValueError, OSError) else error
  with pytest.raises(expected) as caught:
    runtime.run(workspace, cwd=tmp_path)
  if expected is Conflict:
    assert "synthetic private wait" not in str(caught.value)
  else:
    assert caught.value is problem
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1 and capture["closed"] == 1
  assert owner(workspace)["lifecycle_state"] == "unknown"
  assert not (workspace.state_root / "resume-attempts").exists()


def test_spawn_failure_keeps_dependency_error_without_claiming_host(normal,
    fake_subprocess, fake_popen, capture, tmp_path):
  workspace, *_ = normal
  queue(fake_subprocess, fake_popen, 0, spawn_error=OSError("synthetic private spawn"))
  with pytest.raises(DependencyError): runtime.run(workspace, cwd=tmp_path)
  assert len(fake_popen.calls) == 1 and fake_popen.children == [] and capture["captured"] == 0
  assert owner(workspace)["host_identity"] is None


@pytest.mark.parametrize("hook", ["launch", "resume", "adapter"])
def test_existing_explicit_hooks_take_precedence_over_normal_launch(normal,
    fake_subprocess, fake_popen, capture, monkeypatch, tmp_path, hook):
  workspace, *_ = normal
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  def execute(*args, **kwargs): return 37
  options = {}
  if hook == "adapter":
    monkeypatch.setattr(workspace.adapter, "launch_executor", lambda: execute, raising=False)
  else:
    options[hook + "_operation"] = execute
  assert runtime.run(workspace, cwd=tmp_path, **options) == 37
  assert fake_popen.calls == [] and capture["captured"] == 0


@pytest.mark.parametrize("route", ["ssh", "unregistered"])
def test_remote_or_unregistered_launch_keeps_existing_unobserved_route(normal,
    fake_subprocess, fake_popen, capture, monkeypatch, tmp_path, route):
  workspace, *_ = normal
  if route == "ssh":
    metadata = runtime.run_metadata
    monkeypatch.setattr(runtime, "run_metadata", lambda *args: {**metadata(*args), "backend": "ssh"})
  else:
    monkeypatch.setattr(workspace.adapter, "run_owner_guard", lambda *args, **kwargs: nullcontext())
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_subprocess.queue(returncode=41)
  assert runtime.run(workspace, cwd=tmp_path) == 41
  assert len(fake_subprocess.calls) == 2 and fake_popen.calls == [] and capture["captured"] == 0
