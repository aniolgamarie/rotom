"""受控 CLI → 官方只读查询包装 → 受管恢复；所有外部进程仍为假实现。"""

import json
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from agentcfg import run_owners, sessions, workspace as workspace_module
from agentcfg.resume_attempts import ResumeAttempts
from rotom import cli
from rotom.context import InputGateway
from rotom.resume import dsh_candidate
from test_rotom_resume_cli import Stream, setup as cli_setup
from test_rotom_resume_dispatch import fake_popen
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation
from test_rotom_dsh_resume import candidate


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("injected", [False, True])
def test_unregistered_native_id_traverses_candidate_query_and_launch_once(managed,
    monkeypatch, fake_popen, tmp_path, capsys, manual, injected):
  workspace, lock, package, _ = managed
  body = "synthetic-manual-only-private-text"
  streams = InputGateway(Stream("3\n" + body + "\nyes\n"), Stream(), Stream()) if manual else None
  if streams is not None:
    monkeypatch.setattr(cli, "InputGateway", lambda: streams)
  def displayed():
    return streams.stderr.getvalue() if streams is not None else capsys.readouterr().err
  calls = []
  original = tmp_path / "original-cwd"
  original.mkdir()
  def load(local, profile):
    assert Path(local) == workspace.local_path and profile == workspace.profile
    return workspace
  monkeypatch.setattr(workspace_module, "load_workspace", load)
  def run(argv, **kwargs):
    assert package["active"]
    calls.append(list(argv))
    if argv == ["node", "--version"]:
      return SimpleNamespace(returncode=0, stdout="v24.2.0", stderr="")
    assert argv[1:] == [str(workspace.repository / "agents/dsh/templates/session-metadata.mjs"),
      str(workspace.backend.root(workspace, lock.identity)),
      str(workspace.instance / "dsh-home/sessions"), "native-only"]
    assert kwargs["stdin"] == subprocess.DEVNULL
    assert not (workspace.state_root / "run-owners").exists()
    return SimpleNamespace(returncode=0, stdout=json.dumps({"status": "metadata",
      "session_id": "native-only", "cwd": str(original), "source": "session-persistence-stat"}), stderr="")
  monkeypatch.setattr(subprocess, "run", run)
  def waiting():
    owner, = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot().values()
    assert owner["session_observation"] is None and owner["session_cwd"] is None
    request = ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).read(owner["run_id"])
    assert request["requested"]["previous_run_id"] is None
    assert request["requested"]["session"]["native_ref"] == "native-only"
    assert request["requested"]["cwd"] == str(original)
    assert request["dispatch"]["state"] == "launched" and request["exit_code"] is None
    assert "已发起恢复，加载待确认" in displayed()
    if streams is not None:
      assert "仅在此展示供手工复制，不发送" in displayed() and body in displayed()
      assert streams.stdin.read() == ""
  fake_popen.queue(returncode=17, on_wait=waiting)
  code = cli.main(["--interactive" if manual else "--no-input", "resume", "dsh", "--local", str(workspace.local_path),
    "--profile", workspace.profile, "--session", "native-only", "--here"], **({"resume_candidate": dsh_candidate()} if injected else {}))
  assert code == 17 and len(fake_popen.calls) == 1 and len(calls) == 3
  assert fake_popen.calls[0]["argv"][-2:] == ["--resume", "native-only"]
  assert fake_popen.calls[0]["cwd"] == original
  assert "退出码 17" in displayed()
  owner, = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot().values()
  request = ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding).read(owner["run_id"])
  assert request["exit_code"] == 17 and request["load_confirmation"] == "unknown"
  assert request["continue_status"] == "not_sent"
  assert body not in repr(calls) and body not in repr(fake_popen.calls)
  for root in (workspace.state_root, workspace.instance):
    assert all(body.encode() not in path.read_bytes() for path in root.rglob("*") if path.is_file())


@pytest.mark.parametrize("previous", ["intent", "unknown", "active"])
def test_fresh_dsh_coordinator_refuses_unfinished_request_before_second_spawn(candidate,
    fake_subprocess, fake_popen, previous):
  module, workspace, _, target, _ = candidate
  def fresh():
    return sessions.ResumeCoordinator(module.DshResumeCandidate(workspace))
  def blocked():
    fake_subprocess.queue(returncode=0, stdout="v24.2.0")
    with pytest.raises(sessions.SessionError) as caught:
      fresh().resume(target, location="here")
    assert caught.value.code == 4
    assert "synthetic-private-canary" not in str(caught.value)
    assert len(fake_popen.calls) == 1
  fake_subprocess.queue(returncode=0, stdout="v24.2.0")
  if previous == "intent":
    fake_popen.queue(spawn_error=OSError("synthetic-private-canary"))
    with pytest.raises(sessions.SessionError):
      fresh().resume(target, location="here")
    blocked()
  elif previous == "unknown":
    fake_popen.queue(wait_error=TimeoutError("synthetic-private-canary"))
    assert fresh().resume(target, location="here").status == "unknown"
    blocked()
  else:
    observed = []
    def competing():
      fake_subprocess.queue(returncode=0, stdout="v24.2.0")
      try:
        fresh().resume(target, location="here")
      except sessions.SessionError as caught:
        observed.append(caught.code)
      else:
        observed.append(None)
    fake_popen.queue(returncode=0, on_wait=competing)
    assert fresh().resume(target, location="here").exit_code == 0
    assert observed == [4]
  assert len(fake_popen.calls) == 1


def test_pending_request_typed_error_reaches_cli_with_original_runs_and_scoped_query(cli_setup,
    tmp_path, monkeypatch):
  target, candidate_factory, calls, streams, backend, _ = cli_setup
  pending = ("c" * 32, "d" * 32)
  def pending_request(selected, **kwargs):
    calls.append(selected)
    raise sessions.SessionError(4, "synthetic-private-canary", pending_run_ids=pending)
  monkeypatch.setattr(backend, "resume_session", pending_request)
  local = tmp_path / "machine.toml"
  assert cli.main(["--no-input", "resume", "dsh", "--local", str(local),
    "--profile", target.profile, "--session", target.ref.native_ref, "--here"],
    resume_candidate=candidate_factory()) == 4
  assert calls == [target]
  text = streams.stderr.getvalue()
  assert all(run_id in text for run_id in pending)
  query = next(line for line in text.splitlines() if line.startswith("同范围查询："))
  argv = shlex.split(query.split("：", 1)[1])
  assert argv[:2] == ["rotom", "agent"] and argv[-4:-2] == ["instances", "list"]
  parsed = cli.build_parser().parse_args(argv[1:])
  assert parsed.local == str(local) and parsed.profile == target.profile
  assert "--run " not in text and "synthetic-private-canary" not in text


def test_coordinator_retains_pending_run_references_without_reinvoking_backend(cli_setup, monkeypatch):
  target, _, calls, _, backend, _ = cli_setup
  pending = ("c" * 32,)
  def pending_request(selected, **kwargs):
    calls.append(selected)
    raise sessions.SessionError(4, "synthetic-private-canary", pending_run_ids=pending)
  monkeypatch.setattr(backend, "resume_session", pending_request)
  coordinator = sessions.ResumeCoordinator(backend)
  for _ in range(2):
    with pytest.raises(sessions.SessionError) as caught:
      coordinator.resume(target, location="here")
    assert caught.value.code == 4 and caught.value.pending_run_ids == pending
    assert "synthetic-private-canary" not in str(caught.value)
  assert calls == [target]


def test_conflict_without_known_pending_run_still_provides_scoped_query_without_invention(cli_setup,
    tmp_path, monkeypatch):
  target, candidate_factory, calls, streams, backend, _ = cli_setup
  def conflict(selected, **kwargs):
    calls.append(selected)
    raise sessions.SessionError(4, "synthetic-private-canary")
  monkeypatch.setattr(backend, "resume_session", conflict)
  local = tmp_path / "machine.toml"
  assert cli.main(["--no-input", "resume", "dsh", "--local", str(local),
    "--profile", target.profile, "--session", target.ref.native_ref, "--here"],
    resume_candidate=candidate_factory()) == 4
  text = streams.stderr.getvalue()
  query = next(line for line in text.splitlines() if line.startswith("同范围查询："))
  argv = shlex.split(query.split("：", 1)[1])
  parsed = cli.build_parser().parse_args(argv[1:])
  assert parsed.local == str(local) and parsed.profile == target.profile
  assert "未决恢复run：" not in text and target.run_id not in text
  assert "synthetic-private-canary" not in text and "--run " not in text
  assert calls == [target]


def test_4097_valid_pending_references_are_preserved_and_deduplicated_through_coordinator(cli_setup,
    monkeypatch):
  target, _, calls, _, backend, _ = cli_setup
  pending = tuple(format(index + 1, "032x") for index in range(4097))
  def conflict(selected, **kwargs):
    calls.append(selected)
    raise sessions.SessionError(4, "synthetic-private-canary", pending_run_ids=[*reversed(pending), pending[0]])
  monkeypatch.setattr(backend, "resume_session", conflict)
  coordinator = sessions.ResumeCoordinator(backend)
  for _ in range(2):
    with pytest.raises(sessions.SessionError) as caught:
      coordinator.resume(target, location="here")
    assert caught.value.code == 4 and caught.value.pending_run_ids == pending
    assert "synthetic-private-canary" not in str(caught.value)
  assert calls == [target]


@pytest.mark.parametrize("pending", [None, {"a" * 32}, "a" * 32,
  ["synthetic-private-canary"], ["G" * 32], [True], [1]])
def test_invalid_pending_reference_types_and_ids_remain_rejected(pending):
  with pytest.raises(ValueError) as caught:
    sessions.SessionError(4, "synthetic-private-canary", pending_run_ids=pending)
  assert "synthetic-private-canary" not in str(caught.value)
