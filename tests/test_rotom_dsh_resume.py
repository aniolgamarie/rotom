"""DSH 受管恢复候选；临时部署、假进程，不运行或准入第三方宿主。"""

from dataclasses import replace
import importlib

import pytest

from agentcfg import native, run_owners, sessions
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.secrets import CredentialError
from agentcfg.storage import StateError
from test_rotom_resume_dispatch import fake_popen
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation


@pytest.fixture
def candidate(managed, tmp_path):
  module = importlib.import_module("agentcfg.dsh_sessions")
  workspace, lock, package, observed = managed
  cwd = tmp_path / "original project"
  cwd.mkdir()
  target = sessions.KnownSession(
    ref=sessions.SessionRef(agent="dsh", backend="managed",
      native_home_ref=run_owners.native_home_key({"kind": "dsh-home",
        "path": str(workspace.instance / "dsh-home")}), native_ref="session-example"),
    scope=module.scope_key(workspace.binding), profile=workspace.profile,
    cwd=str(cwd), cwd_status="historical", confirmation="historical",
    observed_at_ns=1, run_id="a" * 32)
  return module, workspace, lock, target, package


def invoke(candidate, fake, processes, *, code=0):
  module, workspace, lock, target, package = candidate
  fake.queue(returncode=0, stdout="v24.2.0")
  processes.queue(returncode=code)
  coordinator = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace))
  return coordinator, coordinator.resume(target, location="here")


@pytest.mark.parametrize("code", [0, 4, 17, -15])
def test_candidate_uses_exact_deployed_launch_and_original_cwd_without_input(candidate,
    fake_subprocess, fake_popen, code):
  module, workspace, lock, target, package = candidate
  coordinator, result = invoke(candidate, fake_subprocess, fake_popen, code=code)
  assert result.status == ("launch_dispatched" if code == 0 else "failed")
  assert result.exit_code == (128 - code if code < 0 else code)
  assert result.run_id != target.run_id and result.session is None and result.cwd is None
  assert result.requested_session == target.ref and result.requested_cwd == target.cwd
  assert result.continue_status == "not_sent" and result.input_ready is False
  call = fake_popen.calls[-1]
  assert call["argv"] == ["node", str(workspace.instance / "launch.mjs"),
    str(workspace.backend.root(workspace, lock.identity)),
    str(workspace.instance / "dsh-home/agentcfg.patch.yml"),
    "--profile", "agentcfg", "--resume", "session-example"]
  assert str(call["cwd"]) == target.cwd
  assert call["env"]["DSH_HOME"] == str(workspace.instance / "dsh-home")
  assert call["env"]["DSH_TUI_SESSION_ROOT"] == str(workspace.instance / "dsh-home/sessions")
  assert call["env"]["DSH_TUI_RESUME_SESSION"] == "session-example"
  assert call["env"]["DSH_TUI_BACKEND"] == "dsh"
  assert len(call["pass_fds"]) == 3 and len(fake_subprocess.calls) == 1 and len(fake_popen.calls) == 1
  assert coordinator.resume(target, location="here") == result
  assert len(fake_subprocess.calls) == 1 and len(fake_popen.calls) == 1
  assert not (workspace.instance / "dsh-home/sessions").exists()


@pytest.mark.parametrize("field", ["scope", "profile", "home", "backend", "agent", "native_ref"])
def test_candidate_rejects_target_outside_its_exact_binding_before_runtime(candidate,
    fake_subprocess, field):
  module, workspace, lock, target, package = candidate
  if field in ("scope", "profile"):
    target = replace(target, **{field: "other"})
  else:
    name = "native_home_ref" if field == "home" else field
    value = "pi" if field == "agent" else "--resume" if field == "native_ref" else "other"
    target = replace(target, ref=replace(target.ref, **{name: value}))
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(module.DshResumeCandidate(workspace)).resume(target, location="here")
  assert caught.value.code == 2 and fake_subprocess.calls == []


@pytest.mark.parametrize("change", ["session", "root", "backend", "retry", "workspace", "insert", "duplicate", "js", "name"])
def test_profile_override_or_unreviewed_shape_refuses_dispatch(candidate, fake_subprocess, change):
  module, workspace, lock, target, package = candidate
  path = workspace.instance / "dsh-home/profiles/agentcfg/cordis.patch.yml"
  document = native.load_cordis(path.read_bytes())
  config = document["dsh-tui"]["config"]
  if change == "session":
    config["sessionId"] = "different"
  elif change == "root":
    document["session-persistence-jsonl"] = {"config": {"root": str(workspace.instance / "elsewhere")}}
  elif change == "backend":
    config["backend"] = "other"
  elif change == "retry":
    config["upstreamRetry"] = True
  elif change == "workspace":
    config["workspace"] = "/tmp/other-project"
  elif change == "insert":
    document.rows.append({"insert": [{"id": "extra", "name": "synthetic-plugin"}]})
  elif change == "js":
    config["brand"] = native.JS("process.env.SYNTHETIC_UNKNOWN")
  elif change == "name":
    document["dsh-tui"]["name"] = "other-plugin"
  data = native.dump_cordis(document)
  if change == "duplicate":
    data += b"- id: dsh-tui\n  config: {}\n"
  path.write_bytes(data)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(module.DshResumeCandidate(workspace)).resume(target, location="here")
  assert caught.value.code == 4 and len(fake_subprocess.calls) == 1


@pytest.mark.parametrize("kind", ["home-patch", "managed-patch", "launcher", "symlink"])
def test_home_patch_and_whole_file_drift_refuse_without_repair(candidate, fake_subprocess, kind):
  module, workspace, lock, target, package = candidate
  path = workspace.instance / ({"home-patch": "dsh-home/cordis.patch.yml",
    "managed-patch": "dsh-home/agentcfg.patch.yml", "launcher": "launch.mjs",
    "symlink": "dsh-home/cordis.patch.yml"}[kind])
  if kind == "symlink":
    path.symlink_to(workspace.instance / "dsh-home/agentcfg.patch.yml")
  else:
    path.write_bytes(b"- id: session-persistence-jsonl\n  disabled: true\n")
  def content_identity():
    info = path.lstat()
    content = str(path.readlink()) if path.is_symlink() else path.read_bytes()
    return info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, content
  before = content_identity()
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(module.DshResumeCandidate(workspace)).resume(target, location="here")
  assert caught.value.code == 4 and len(fake_subprocess.calls) == 1
  # 只读检查可能更新 atime；内容、身份、权限和写入时间仍须完全相同。
  assert content_identity() == before


def test_native_ui_preferences_remain_user_owned_and_empty_home_patch_is_allowed(candidate,
    fake_subprocess, fake_popen):
  module, workspace, lock, target, package = candidate
  path = workspace.instance / "dsh-home/profiles/agentcfg/cordis.patch.yml"
  document = native.load_cordis(path.read_bytes())
  document["dsh-tui"]["config"]["brand"] = "synthetic-preference"
  data = native.dump_cordis(document)
  path.write_bytes(data)
  (workspace.instance / "dsh-home/cordis.patch.yml").write_bytes(b"# native empty patch\n[]\n")
  coordinator, result = invoke(candidate, fake_subprocess, fake_popen)
  assert result.status == "launch_dispatched" and path.read_bytes() == data


def test_caller_resume_environment_cannot_redirect_candidate(candidate, fake_subprocess, fake_popen, monkeypatch):
  module, workspace, lock, target, package = candidate
  monkeypatch.setenv("DSH_TUI_RESUME_SESSION", "different")
  monkeypatch.setenv("DSH_TUI_SESSION_ROOT", "/tmp/different-store")
  monkeypatch.setenv("DSH_TUI_BACKEND", "other")
  coordinator, result = invoke(candidate, fake_subprocess, fake_popen)
  assert result.status == "launch_dispatched"
  assert fake_popen.calls[-1]["env"]["DSH_TUI_RESUME_SESSION"] == target.ref.native_ref
  assert fake_popen.calls[-1]["env"]["DSH_TUI_SESSION_ROOT"] == str(workspace.instance / "dsh-home/sessions")


def test_candidate_has_no_independent_lock_or_runtime_route(candidate, fake_subprocess, monkeypatch):
  module, workspace, lock, target, package = candidate
  def reject(*args, **kwargs):
    raise module.Conflict("synthetic-existing-runtime-preflight")
  monkeypatch.setattr(module.runtime, "run", reject)
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(module.DshResumeCandidate(workspace)).resume(target, location="here")
  assert caught.value.code == 4 and fake_subprocess.calls == []


@pytest.mark.parametrize("failure,code", [(CredentialError(), 3), (StateError("synthetic-private"), 6),
  (DependencyError("synthetic-private"), 5), (ConfigError("synthetic-private"), 2)])
def test_candidate_preserves_existing_runtime_error_categories(candidate, fake_subprocess,
    monkeypatch, failure, code):
  module, workspace, lock, target, package = candidate
  def reject(*args, **kwargs):
    raise failure
  monkeypatch.setattr(module.runtime, "run", reject)
  with pytest.raises(sessions.SessionError) as caught:
    sessions.ResumeCoordinator(module.DshResumeCandidate(workspace)).resume(target, location="here")
  assert caught.value.code == code and "synthetic-private" not in str(caught.value)
  assert fake_subprocess.calls == []


@pytest.mark.parametrize("shape", ["shared-tree", "shared-text", "cycle"])
def test_config_alias_expansion_is_bounded(shape):
  module = importlib.import_module("agentcfg.dsh_sessions")
  if shape == "shared-tree":
    # 少量原生 YAML 锚点可以表示指数大小的逻辑树。
    lines = ["- id: dsh-tui", "  config:", "    value0: &v0 [plain]"]
    for level in range(1, 13):
      lines.append(f"    value{level}: &v{level} [*v{level - 1}, *v{level - 1}, *v{level - 1}]")
    value = native.load_cordis("\n".join(lines).encode())
  elif shape == "shared-text":
    text = "x" * 600000
    value = [text, text]
  else:
    value = []
    value.append(value)
  assert module._plain(value) is False


def test_small_plain_aliases_remain_accepted():
  module = importlib.import_module("agentcfg.dsh_sessions")
  value = {"label": "synthetic", "enabled": True}
  assert module._plain([value, value]) is True


def test_live_dispatch_journal_orders_intent_spawn_launched_wait_and_exit(candidate,
    fake_subprocess, fake_popen, monkeypatch):
  module, workspace, lock, target, package = candidate
  coordinator = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace))
  journal = module.ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding)
  original_spawn = type(fake_popen).__call__
  seen = []
  def spawn(factory, *args, **kwargs):
    owner, = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot().values()
    assert journal.read(owner["run_id"])["dispatch"]["state"] == "intent"
    assert coordinator.snapshot().status == "unknown"
    assert coordinator.snapshot().run_id == owner["run_id"]
    assert owner["session_observation"] is None and owner["session_cwd"] is None
    seen.append(owner["run_id"])
    return original_spawn(factory, *args, **kwargs)
  monkeypatch.setattr(type(fake_popen), "__call__", spawn)
  def on_wait():
    record = journal.read(seen[0])
    assert record["dispatch"]["state"] == "launched" and record["exit_code"] is None
    assert coordinator.snapshot().status == "launch_dispatched" and package["active"]
    assert record["load_confirmation"] == "unknown" and record["continue_status"] == "not_sent"
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_popen.queue(returncode=0, on_wait=on_wait)
  outcome = coordinator.resume(target, location="here")
  assert outcome.status == "launch_dispatched" and outcome.run_id == seen[0]
  assert journal.read(outcome.run_id)["exit_code"] == 0
  owner = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()[outcome.run_id]
  assert owner["session_observation"] is None and owner["session_cwd"] is None


def test_intent_failure_never_spawns_or_retries(candidate, fake_subprocess, fake_popen, monkeypatch):
  module, workspace, lock, target, package = candidate
  def broken(*args, **kwargs):
    raise StateError("synthetic-private-begin")
  monkeypatch.setattr(module.ResumeAttempts, "begin", broken)
  coordinator = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace))
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  for _ in range(2):
    with pytest.raises(sessions.SessionError) as caught:
      coordinator.resume(target, location="here")
    assert caught.value.code == 6 and "synthetic-private" not in str(caught.value)
  assert fake_popen.calls == [] and len(fake_subprocess.calls) == 1


def test_spawn_failure_preserves_intent_and_never_records_launched(candidate,
    fake_subprocess, fake_popen):
  module, workspace, lock, target, package = candidate
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_popen.queue(spawn_error=OSError("synthetic-private-spawn"))
  coordinator = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace))
  for _ in range(2):
    with pytest.raises(sessions.SessionError):
      coordinator.resume(target, location="here")
  outcome = coordinator.snapshot()
  assert outcome.status == "unknown" and outcome.run_id is not None
  record = module.ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).read(outcome.run_id)
  assert record["dispatch"]["state"] == "intent" and record["exit_code"] is None
  assert len(fake_popen.calls) == 1 and fake_popen.children == []


@pytest.mark.parametrize("failure", [TimeoutError, ConnectionError])
def test_candidate_wait_failure_keeps_launched_unknown_and_never_retries(candidate,
    fake_subprocess, fake_popen, failure):
  module, workspace, lock, target, package = candidate
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_popen.queue(wait_error=failure("synthetic-private-wait"))
  coordinator = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace))
  outcome = coordinator.resume(target, location="here")
  assert outcome.status == "unknown" and "synthetic-private" not in str(outcome)
  assert coordinator.resume(target, location="here") == outcome
  record = module.ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).read(outcome.run_id)
  assert record["dispatch"]["state"] == "launched" and record["exit_code"] is None
  owner = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()[outcome.run_id]
  assert owner["lifecycle_state"] == "unknown"
  assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1
  # 不证明退出或父 guard 继续持有；实际 child 继承 FD，既有 owner 未知保护仍有效。


@pytest.mark.parametrize("stage", ["launched", "exited"])
def test_postspawn_journal_error_does_not_skip_live_notice_wait_or_native_exit(candidate,
    fake_subprocess, fake_popen, monkeypatch, capsys, stage):
  from agentcfg import resume_attempts
  module, workspace, lock, target, package = candidate
  original = getattr(resume_attempts._Attempt, stage)
  def broken(self, *args):
    original(self, *args)
    raise StateError("synthetic-private-journal")
  monkeypatch.setattr(resume_attempts._Attempt, stage, broken)
  coordinator = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace))
  def on_wait():
    assert coordinator.snapshot().status == "launch_dispatched"
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  fake_popen.queue(returncode=17, on_wait=on_wait)
  outcome = coordinator.resume(target, location="here")
  assert outcome.status == "failed" and outcome.exit_code == 17
  assert fake_popen.children[0].wait_calls == 1 and len(fake_popen.calls) == 1
  record = module.ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).read(outcome.run_id)
  assert record["exit_code"] == 17 and record["load_confirmation"] == "unknown"
  warning = capsys.readouterr().err
  assert "记账未完成" in warning and "synthetic-private" not in warning


@pytest.mark.parametrize("stage", ["intent", "launched"])
def test_journal_commit_response_loss_does_not_replay_spawn(candidate, fake_subprocess,
    fake_popen, monkeypatch, stage):
  from agentcfg.storage import Tree
  module, workspace, lock, target, package = candidate
  operation = "write_new" if stage == "intent" else "replace"
  original = getattr(Tree, operation)
  lost = []
  def lose_response(tree, *args, **kwargs):
    result = original(tree, *args, **kwargs)
    if tree.root == workspace.state_root / "resume-attempts" and not lost:
      lost.append(True)
      raise StateError("synthetic-fsync-response-lost")
    return result
  monkeypatch.setattr(Tree, operation, lose_response)
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  coordinator = sessions.ResumeCoordinator(module.DshResumeCandidate(workspace))
  if stage == "intent":
    for _ in range(2):
      with pytest.raises(sessions.SessionError) as caught:
        coordinator.resume(target, location="here")
      assert caught.value.code == 6
    assert fake_popen.calls == []
    owner, = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot().values()
    record = module.ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).read(owner["run_id"])
    assert record["dispatch"]["state"] == "intent" and record["exit_code"] is None
  else:
    fake_popen.queue(returncode=17)
    outcome = coordinator.resume(target, location="here")
    assert outcome.exit_code == 17 and coordinator.resume(target, location="here") == outcome
    assert len(fake_popen.calls) == 1 and fake_popen.children[0].wait_calls == 1
    record = module.ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).read(outcome.run_id)
    assert record["dispatch"]["state"] == "launched" and record["exit_code"] == 17
  assert lost == [True] and len(fake_subprocess.calls) == 1


@pytest.mark.parametrize("change", ["darwin", "win32", "full-lock"])
def test_actual_resume_admission_rejects_before_runtime_or_host(candidate, monkeypatch, fake_popen, change):
  from types import SimpleNamespace
  module, workspace, lock, target, package = candidate
  if change == "full-lock":
    monkeypatch.setattr(type(workspace.backend), "read_lock", lambda *args: replace(lock, identity="0" * 64))
  else:
    monkeypatch.setattr(module, "sys", SimpleNamespace(platform=change), raising=False)
  calls = []
  monkeypatch.setattr(module.runtime, "run", lambda *args, **kwargs: calls.append(True))
  with pytest.raises(sessions.SessionError) as caught:
    module.DshResumeCandidate(workspace).resume_session(target, location="here",
      before_dispatch=lambda run: None, after_dispatch=lambda run: None)
  assert caught.value.code == 5 and calls == [] and fake_popen.calls == []


def test_contract_rechecks_full_lock_even_when_top_level_versions_are_unchanged(candidate, monkeypatch):
  module, workspace, lock, target, package = candidate
  from agentcfg.deployment import read_state
  from agentcfg.storage import Tree
  with Tree(workspace.state_root) as state:
    contract = read_state(state)["current"]["launch"]
  changed = replace(lock, identity="0" * 64)
  monkeypatch.setattr(type(workspace.backend), "read_lock", lambda *args: changed)
  contract = {**contract, "lock_identity": changed.identity}
  with pytest.raises(DependencyError):
    module._contract(workspace, contract)
