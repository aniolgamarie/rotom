"""恢复启动即绑定当次 host；观察失败不杀进程、不改原生退出结果。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from agentcfg import run_owners, sessions, spawned_host
from agentcfg.resume_attempts import ResumeAttempts
from agentcfg.storage import Conflict, Tree
from test_rotom_dsh_resume import candidate
from test_rotom_resume_dispatch import fake_popen
from test_rotom_resume_runtime import managed, assert_exclusive_busy
from test_rotom_runtime_observation import MANAGER, observation


HOST = {"identity": {"pid": 31338, "birth_id": "synthetic-child-birth"},
  "manager_identity": MANAGER, "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}


@pytest.fixture(autouse=True)
def isolate_default_control_factory(monkeypatch):
  # 本模块只验证 host 观察接缝；默认控制工厂由独立测试覆盖。
  from agentcfg import dsh_stop_control
  monkeypatch.setattr(dsh_stop_control, "default_factory", lambda *args, **kwargs: None)


@pytest.fixture
def capture(monkeypatch):
  handle = object.__new__(spawned_host.SpawnedHost)
  state = {"captured": 0, "closed": 0, "handle": handle}
  def take(child, manager):
    assert child.returncode is None and child.wait_calls == 0
    assert manager == MANAGER
    state["captured"] += 1
    state["child"] = child
    return handle
  def snapshot(self):
    assert state["closed"] == 0
    return deepcopy(HOST)
  def close(self):
    state["closed"] += 1
  monkeypatch.setattr(spawned_host, "capture_spawned_host", take)
  monkeypatch.setattr(spawned_host.SpawnedHost, "snapshot", snapshot)
  monkeypatch.setattr(spawned_host.SpawnedHost, "close", close)
  return state


def owner(workspace):
  value, = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot().values()
  return value


@pytest.mark.parametrize("code", [0, 17, -15])
def test_resume_records_exact_child_before_wait_and_keeps_all_leases(candidate,
    fake_subprocess, fake_popen, capture, code):
  module, workspace, lock, target, package = candidate
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  seen = []
  def waiting():
    record = owner(workspace)
    assert record["host_identity"] == HOST and record["protocol"]["control"] is None
    assert record["lifecycle_state"] == "active"
    assert record["session_observation"] is None and record["session_cwd"] is None
    assert capture["captured"] == 1 and capture["closed"] == 0 and package["active"]
    for path in (workspace.instance, workspace.state_root / "instance.lock", package["path"]):
      assert_exclusive_busy(path)
    attempt = ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).for_owner(record)
    assert attempt["dispatch"] == "launched" and attempt["load_confirmation"] == "unknown"
    assert attempt["continue_status"] == "not_sent"
    seen.append(record)
  fake_popen.queue(returncode=code, on_wait=waiting)
  result = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace)).resume(target, location="here")
  assert result.exit_code == (code if code >= 0 else 128 - code)
  assert result.continue_status == "not_sent" and result.input_ready is False
  assert len(seen) == 1 and len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1
  assert capture["closed"] == 1 and owner(workspace)["host_identity"] == HOST


@pytest.mark.parametrize("failure", ["unavailable", "capture-error", "attach-error", "write-before", "write-after"])
def test_optional_host_observation_failure_preserves_wait_exit_and_unknown_control(candidate,
    fake_subprocess, fake_popen, capture, monkeypatch, capsys, failure):
  module, workspace, lock, target, package = candidate
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_popen.queue(returncode=23)
  private = "synthetic-private-host-error"
  def fail(*args, **kwargs):
    raise OSError(private)
  if failure == "unavailable":
    monkeypatch.setattr(spawned_host, "capture_spawned_host", lambda *args: None)
  elif failure == "capture-error":
    monkeypatch.setattr(spawned_host, "capture_spawned_host", fail)
  elif failure == "attach-error":
    monkeypatch.setattr(run_owners.Registry, "bind_current_host", fail)
  else:
    replace = Tree.replace
    def write(tree, path, data, **kwargs):
      if tree.root == workspace.state_root / "run-owners":
        if failure == "write-after":
          replace(tree, path, data, **kwargs)
        raise OSError(private)
      return replace(tree, path, data, **kwargs)
    monkeypatch.setattr(Tree, "replace", write)
  result = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace)).resume(target, location="here")
  assert result.exit_code == 23 and result.continue_status == "not_sent"
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1
  assert capture["closed"] == (0 if failure in ("unavailable", "capture-error") else 1)
  assert owner(workspace)["host_identity"] == (HOST if failure == "write-after" else None)
  assert owner(workspace)["protocol"]["control"] is None
  assert private not in capsys.readouterr().err


@pytest.mark.parametrize("failure", ["attach-control", "wait-error", "wait-control", "after-error"])
def test_acquired_handle_closes_without_kill_retry_or_replacing_control(candidate,
    fake_subprocess, fake_popen, capture, monkeypatch, failure):
  module, workspace, lock, target, package = candidate
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  error = KeyboardInterrupt("synthetic interrupt")
  if failure == "attach-control":
    def attach(*args):
      raise error
    monkeypatch.setattr(run_owners.Registry, "bind_current_host", attach)
  fake_popen.queue(returncode=31,
    wait_error=ValueError("synthetic wait") if failure == "wait-error" else error if failure == "wait-control" else None)
  def after(run_id):
    if failure == "after-error":
      raise ValueError("synthetic notification")
  backend = module.DshResumeCandidate(workspace)
  if failure in ("attach-control", "wait-control"):
    with pytest.raises(KeyboardInterrupt) as caught:
      backend.resume_session(target, location="here", before_dispatch=lambda run: None, after_dispatch=after)
    assert caught.value is error
  elif failure == "wait-error":
    with pytest.raises(module._WaitUnconfirmed):
      backend.resume_session(target, location="here", before_dispatch=lambda run: None, after_dispatch=after)
  else:
    receipt = backend.resume_session(target, location="here", before_dispatch=lambda run: None, after_dispatch=after)
    assert receipt.exit_code == 31
  assert capture["closed"] == 1 and len(fake_popen.calls) == 1
  assert fake_popen.children[0].wait_calls == (0 if failure == "attach-control" else 1)


@pytest.mark.parametrize("primary", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("secondary", [KeyboardInterrupt, SystemExit])
def test_handle_cleanup_cannot_replace_original_control_exception(tmp_path, fake_popen,
    capture, monkeypatch, primary, secondary):
  from agentcfg import dsh_sessions
  original = primary("original synthetic interruption")
  def close(self):
    capture["closed"] += 1
    raise secondary("secondary synthetic interruption")
  monkeypatch.setattr(spawned_host.SpawnedHost, "close", close)
  fake_popen.queue(returncode=0, wait_error=original)
  with pytest.raises(BaseException) as caught:
    dsh_sessions._launch(SimpleNamespace(argv=("synthetic-native",), cwd=tmp_path), {}, (),
      run_id="a" * 32, before_dispatch=lambda run: None, after_dispatch=lambda run: None,
      owner_registry=SimpleNamespace(bind_current_host=lambda *args: None), manager_identity=MANAGER)
  assert caught.value is original
  assert capture["closed"] == 1 and fake_popen.children[0].wait_calls == 1


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
def test_new_cleanup_interrupt_propagates_after_native_exit_fact_is_saved(candidate,
    fake_subprocess, fake_popen, capture, monkeypatch, kind):
  module, workspace, lock, target, package = candidate
  interruption = kind("new synthetic interruption")
  def close(self):
    capture["closed"] += 1
    raise interruption
  monkeypatch.setattr(spawned_host.SpawnedHost, "close", close)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_popen.queue(returncode=17)
  with pytest.raises(kind) as caught:
    module.DshResumeCandidate(workspace).resume_session(target, location="here",
      before_dispatch=lambda run: None, after_dispatch=lambda run: None)
  assert caught.value is interruption
  record = owner(workspace)
  attempt = ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).for_owner(record)
  assert attempt["dispatch"] == "launched" and attempt["exit_code"] == 17
  assert attempt["load_confirmation"] == "unknown" and attempt["continue_status"] == "not_sent"
  assert record["host_identity"] == HOST and record["protocol"]["control"] is None
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1 and capture["closed"] == 1
