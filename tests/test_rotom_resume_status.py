"""实例列表展示请求和派发状态，不把它们当作当前会话。"""

import json

import pytest

from agentcfg import run_owners, sessions
from agentcfg.dsh_sessions import scope_key
from agentcfg.resume_attempts import ResumeAttempts
from rotom import cli
from test_rotom_instances import machine, register


def prepare(machine):
  workspace = machine.workspaces["dsh-default"]
  registry, run = register(machine)
  owner = registry.snapshot()[run]
  target = sessions.KnownSession(sessions.SessionRef("dsh", "managed",
    run_owners.native_home_key(owner["native_home_ref"]), "synthetic-session"),
    scope_key(workspace.binding), workspace.profile, owner["start_cwd"]["path"],
    "historical", "historical", 1, "a" * 32)
  journal = ResumeAttempts(workspace.state_root / "resume-attempts", workspace.binding)
  return journal, journal.begin(target, owner), run


@pytest.mark.parametrize("phase,expected", [("intent", "unknown"), ("launched", "launch_dispatched"),
  ("exited", "launch_dispatched"), ("failed", "failed")])
def test_instance_request_status_is_separate_read_only_fact(machine, sentinel_factory, phase, expected):
  journal, handle, run = prepare(machine)
  if phase != "intent": handle.launched()
  if phase in ("exited", "failed"): handle.exited(0 if phase == "exited" else 9)
  sentinel = sentinel_factory(machine.local.parent)
  result = run_owners.instances(machine.local, profile="dsh-default")
  row, = result["instances"]
  request = row["resume_request"]
  assert request["status"] == expected
  assert request["requested_session"]["native_ref"] == "synthetic-session"
  assert request["load_confirmation"] == "unknown" and request["continue_status"] == "not_sent"
  assert row["session"]["ref"] is None and row["session_cwd"] is None
  assert row["process"]["status"] == "active" and result["incomplete"] is False
  assert result["capabilities"]["resume"] is False
  sentinel.assert_unchanged()


@pytest.mark.parametrize("damage", ["manager", "scope", "corrupt", "mode"])
def test_untrusted_request_preserves_process_evidence_and_reports_incomplete(machine, damage):
  journal, handle, run = prepare(machine)
  path = journal.root / (run + ".json")
  value = json.loads(path.read_bytes())
  if damage == "manager": value["manager_identity"]["birth_id"] = "different"
  elif damage == "scope": value["requested"]["session"]["native_home_ref"] = "other"
  elif damage == "corrupt": value["secret"] = "synthetic-secret"
  if damage == "mode": path.chmod(0o644)
  else: path.write_text(json.dumps(value))
  result = run_owners.instances(machine.local, profile="dsh-default")
  row, = result["instances"]
  assert result["incomplete"] is True and row["process"]["status"] == "active"
  assert row["resume_request"] == {"status": "unknown", "source": "resume-request-unavailable"}
  assert "synthetic-secret" not in json.dumps(result)


def test_absent_request_does_not_create_directory(machine, sentinel_factory):
  register(machine)
  sentinel = sentinel_factory(machine.local.parent)
  row, = run_owners.instances(machine.local, profile="dsh-default")["instances"]
  assert row["resume_request"] is None
  sentinel.assert_unchanged()


def test_bulk_view_opens_request_directory_once_and_reuses_validated_owners(machine, monkeypatch):
  from contextlib import contextmanager
  import agentcfg.resume_attempts as attempts
  for _ in range(8): register(machine)
  opened = []
  original = attempts.ResumeAttempts._locked
  @contextmanager
  def locked(store, **kwargs):
    opened.append(store.root)
    with original(store, **kwargs) as tree:
      yield tree
  monkeypatch.setattr(attempts.ResumeAttempts, "_locked", locked)
  result = run_owners.instances(machine.local, profile="dsh-default")
  assert len(result["instances"]) == 8 and result["incomplete"] is False
  assert len(opened) == 1


def test_human_status_says_request_pending_and_zero_input(machine, capsys):
  journal, handle, run = prepare(machine)
  handle.launched()
  assert cli.main(["agent", "--local", str(machine.local), "--profile", "dsh-default",
    "instances", "list", "--format", "human"]) == 0
  output = capsys.readouterr().out
  assert "requested_session=synthetic-session" in output and "launch_dispatched" in output
  assert "加载待确认" in output and "未发送继续" in output
  assert "session=unknown" in output and "session_cwd=unknown" in output


def test_untrusted_request_human_status_does_not_drop_entire_instance(machine, capsys):
  journal, handle, run = prepare(machine)
  (journal.root / (run + ".json")).write_text("corrupt")
  assert cli.main(["agent", "--local", str(machine.local), "--profile", "dsh-default",
    "instances", "list", "--format", "human"]) == 4
  output = capsys.readouterr().out
  assert "process=active" in output and "恢复请求记录不可核实" in output
