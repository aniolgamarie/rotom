"""Pi/OMP 真实管理路径和假宿主：精确目标、原目录、writer及原退出结果。"""
from dataclasses import replace
from types import SimpleNamespace
import json
import os

import pytest

from agentcfg import pi_session_guard, run_owners, sessions, tool_sessions
from agentcfg.omp_identity import native_identity
from agentcfg.tool_session_headers import lookup
from test_pi_reboot_dependencies import fake_npm, recipe_repository
from test_pi_reboot_pipeline import pipeline
from test_rotom_pi_run_host import pi
from test_rotom_resume_host import capture
from test_rotom_dsh_resume import candidate
from test_rotom_resume_runtime import managed
from test_rotom_resume_dispatch import fake_popen
from test_rotom_runtime_observation import observation
from test_rotom_omp_cooperative_launch import case
from test_rotom_omp_run_host import managed as omp_managed
from test_rotom_resume_runtime import assert_exclusive_busy


SESSION = "12345678-1234-4234-8234-123456789abc"


@pytest.fixture(params=["pi", "omp"])
def tool(request, tmp_path, monkeypatch):
  # 合成包仅测事务路径；真实完整锁的静态矩阵由能力测试独立约束。
  monkeypatch.setattr(tool_sessions, "session_capability", lambda **kwargs: SimpleNamespace(handoff="admitted"))
  if request.param == "pi":
    workspace, observed, _ = request.getfixturevalue("pi")
    observed["value"] = True
    monkeypatch.setattr(pi_session_guard, "source_identity", lambda: "c" * 64)
    root = workspace.instance / "pi-home/sessions"
    backend = tool_sessions.PiResumeCandidate(workspace)
  else:
    request.getfixturevalue("omp_managed")
    selected = request.getfixturevalue("case")
    workspace = selected.ws
    selected.lock.metadata = {"tag": "v18.12.6", "commit": "45c35e40c46166dc726ccc52f5d27f40f2449f99"}
    monkeypatch.setattr(workspace.backend, "read_lock", lambda repository: selected.lock, raising=False)
    root = native_identity(workspace.profile, workspace.instance).agent_dir / "sessions/bucket"
    backend = tool_sessions.OmpResumeCandidate(workspace)
  root.mkdir(parents=True, exist_ok=True)
  cwd = tmp_path / "original-project"
  cwd.mkdir()
  file = root / ("2026-10-26T00-00-00_" + SESSION + ".jsonl")
  file.write_text(json.dumps({"type": "session", "version": 3, "id": SESSION,
    "cwd": str(cwd), "timestamp": "2026-10-26T00:00:00Z"}) + "\nBODY-SENTINEL\n")
  target = replace(lookup(workspace, SESSION).known, run_id="a" * 32)
  return workspace, backend, target, file


@pytest.mark.parametrize("code", [0, 17, -15])
def test_exact_native_path_and_cwd_without_continue_preserve_exit(tool, fake_popen, code):
  workspace, backend, target, file = tool
  def waiting():
    row, = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot().values()
    assert row["host_identity"] is not None and row["protocol"]["control"] is None
    assert row["session_observation"] is None
    if workspace.agent == "pi":
      assert_exclusive_busy(workspace.state_root / "pi-session-claims" / (SESSION + ".lock"))
      context = json.loads(fake_popen.calls[0]["env"]["ROTOM_PI_CONTROL_CONTEXT"])
      assert context["initial_session"] == SESSION and context["run_id"] == row["run_id"]
      assert context["lease_fd"] in fake_popen.calls[0]["pass_fds"]
    for fd in fake_popen.calls[0]["pass_fds"]:
      os.fstat(fd)
  fake_popen.queue(returncode=code, on_wait=waiting)
  coordinator = sessions.ResumeCoordinator(backend)
  result = coordinator.resume(target, location="here")
  assert result.exit_code == (code if code >= 0 else 128 - code)
  assert result.status == ("launch_dispatched" if code == 0 else "failed")
  assert result.session is None and result.cwd is None and result.continue_status == "not_sent"
  assert result.run_id != target.run_id and not result.input_ready
  call = fake_popen.calls[0]
  option = "--session" if workspace.agent == "pi" else "--resume"
  assert call["argv"][call["argv"].index(option)+1] == str(file)
  assert str(call["cwd"]) == target.cwd and SESSION not in call["argv"]
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1
  assert coordinator.resume(target, location="here") == result and len(fake_popen.calls) == 1


@pytest.mark.parametrize("damage", ["missing", "scope", "cwd", "home", "profile", "backend"])
def test_unknown_or_changed_target_never_spawns(tool, fake_popen, tmp_path, damage):
  workspace, backend, target, file = tool
  if damage == "missing":
    file.unlink()
  elif damage == "scope":
    target = replace(target, scope="different")
  elif damage == "cwd":
    target = replace(target, cwd=str(tmp_path))
  elif damage == "profile":
    target = replace(target, profile="different")
  else:
    field = "native_home_ref" if damage == "home" else damage
    target = replace(target, ref=replace(target.ref, **{field: "different"}))
  with pytest.raises(sessions.SessionError):
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert fake_popen.calls == []


def test_missing_target_between_preview_and_dispatch_is_not_recreated(tool, fake_popen, monkeypatch):
  workspace, backend, target, file = tool
  original = tool_sessions.runtime.run
  def changed(*args, **kwargs):
    file.unlink()
    return original(*args, **kwargs)
  monkeypatch.setattr(tool_sessions.runtime, "run", changed)
  with pytest.raises(sessions.SessionError):
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert fake_popen.calls == [] and not file.exists()


def test_unreviewed_runtime_combination_never_dispatches(tool, fake_popen, monkeypatch):
  workspace, backend, target, file = tool
  monkeypatch.setattr(tool_sessions, "session_capability", lambda **kwargs: SimpleNamespace(handoff="unavailable"))
  with pytest.raises(sessions.SessionError) as error:
    sessions.ResumeCoordinator(backend).resume(target, location="here")
  assert error.value.code == 5 and fake_popen.calls == []


def test_managed_cooperation_never_promotes_load_receipt(tmp_path):
  ref = sessions.SessionRef("pi", "managed", "home", SESSION)
  target = sessions.KnownSession(ref, "scope", "pi-base", str(tmp_path), "historical", "historical", 1, None)
  class Invalid(sessions.HandoffResumeBackend):
    def resume_session(self, target, *, location, before_dispatch, after_dispatch):
      before_dispatch("b" * 32)
      after_dispatch("b" * 32)
      return sessions.LoadReceipt("b" * 32, target.ref, target.cwd, True, True)
  coordinator = sessions.ResumeCoordinator(Invalid())
  with pytest.raises(sessions.SessionError):
    coordinator.resume(target, location="here")
  assert coordinator.snapshot().status == "unknown"


@pytest.mark.parametrize("binding", ["absent", "match", "changed"])
def test_pi_omp_candidate_binds_runtime_to_approved_deployment(tool, fake_popen, binding):
  from agentcfg import deployment
  from agentcfg.setup_preview import setup_deployment_digest
  from agentcfg.storage import Tree
  workspace, original, target, _ = tool
  with Tree(workspace.state_root) as state:
    approved = setup_deployment_digest(deployment.read_state(state)["current"])
  options = {} if binding == "absent" else {"expected_deployment": approved if binding == "match" else "0" * 64}
  backend = type(original)(workspace, **options)
  fake_popen.queue(returncode=17)
  if binding == "changed":
    with pytest.raises(sessions.SessionError) as caught:
      sessions.ResumeCoordinator(backend).resume(target, location="here")
    assert caught.value.code == 4 and fake_popen.calls == []
    assert run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot() == {}
  else:
    assert sessions.ResumeCoordinator(backend).resume(target, location="here").exit_code == 17
    assert len(fake_popen.calls) == 1


@pytest.mark.parametrize("binding", ["absent", "match", "changed"])
def test_dsh_candidate_binds_runtime_to_approved_deployment(candidate, fake_subprocess, fake_popen, binding):
  from agentcfg import deployment
  from agentcfg.setup_preview import setup_deployment_digest
  from agentcfg.storage import Tree
  module, workspace, _, target, _ = candidate
  with Tree(workspace.state_root) as state:
    approved = setup_deployment_digest(deployment.read_state(state)["current"])
  options = {} if binding == "absent" else {"expected_deployment": approved if binding == "match" else "0" * 64}
  backend = module.DshResumeCandidate(workspace, **options)
  if binding == "changed":
    with pytest.raises(sessions.SessionError) as caught:
      sessions.ResumeCoordinator(backend).resume(target, location="here")
    assert caught.value.code == 4 and fake_popen.calls == [] and fake_subprocess.calls == []
    assert run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot() == {}
  else:
    fake_subprocess.queue(returncode=0, stdout="v24.2.0")
    fake_popen.queue(returncode=17)
    assert sessions.ResumeCoordinator(backend).resume(target, location="here").exit_code == 17
    assert len(fake_popen.calls) == 1
