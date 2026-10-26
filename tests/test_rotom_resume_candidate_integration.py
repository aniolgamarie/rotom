"""受控 CLI → 官方只读查询包装 → 受管恢复；所有外部进程仍为假实现。"""

import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from agentcfg import run_owners, workspace as workspace_module
from agentcfg.resume_attempts import ResumeAttempts
from rotom import cli
from rotom.context import InputGateway
from rotom.resume import dsh_candidate
from test_rotom_resume_cli import Stream
from test_rotom_resume_dispatch import fake_popen
from test_rotom_resume_runtime import managed
from test_rotom_runtime_observation import observation


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
