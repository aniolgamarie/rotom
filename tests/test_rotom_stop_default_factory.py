"""默认入口只给已支持的新登记提供停止工厂；无宿主、内核控制或网络。"""
import os

import pytest

from agentcfg import dsh_process, dsh_sessions, dsh_stop_control, runtime
from agentcfg.storage import Conflict
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_runtime_observation import observation


_CHILD = runtime._run_dsh_child


@pytest.mark.parametrize("supported,failure", [(False, False), (True, False), (True, True)])
def test_normal_start_factory_borrows_original_fds_and_failure_keeps_launch(managed, tmp_path,
    monkeypatch, fake_subprocess, supported, failure):
  workspace, lock, package, observed = managed
  seen = []; control = lambda **kw: None
  monkeypatch.setattr(runtime, "_run_dsh_child", _CHILD)
  monkeypatch.setattr(dsh_stop_control, "supported", lambda row: supported)
  def factory(ws, *, instance_fd, state_fd):
    assert ws is workspace
    os.fstat(instance_fd); os.fstat(state_fd)
    assert_exclusive_busy(ws.instance); assert_exclusive_busy(ws.state_root / "instance.lock")
    seen.append("factory")
    if failure: raise Conflict("synthetic-private-canary")
    return control
  monkeypatch.setattr(dsh_stop_control, "factory_for", factory)
  def launch(spec, env, pass_fds, **kwargs):
    assert (kwargs.get("control_factory") is control) == (supported and not failure)
    assert "control_factory" in kwargs or not supported or failure
    seen.append("launch")
    return 17
  monkeypatch.setattr(dsh_process, "launch", launch)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  assert runtime.run(workspace, cwd=tmp_path) == 17
  assert seen == (["factory", "launch"] if supported else ["launch"])


@pytest.mark.parametrize("enabled", [False, True])
def test_resume_shared_launch_forwards_only_current_factory(monkeypatch, enabled):
  control = lambda **kw: None
  calls = []
  def launch(*args, **kwargs): calls.append(kwargs); return 0
  monkeypatch.setattr(dsh_process, "launch", launch)
  receipt = dsh_sessions._launch(None, {}, (), run_id="a" * 32, before_dispatch=lambda: None,
    after_dispatch=lambda: None, control_factory=control if enabled else None)
  assert receipt.exit_code == 0 and calls[0]["resume"] is True
  assert (calls[0].get("control_factory") is control) == enabled
  assert ("control_factory" in calls[0]) == enabled
