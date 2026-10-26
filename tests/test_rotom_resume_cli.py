"""受控 Python 候选接缝；不开放日常 CLI 或执行第三方宿主。"""
from dataclasses import replace
import io

import pytest

from agentcfg.sessions import HostResumeBackend, KnownSession, LaunchReceipt, SessionRef
from rotom import cli
from rotom.context import InputGateway


class Stream(io.StringIO):
  def isatty(self):
    return True


@pytest.fixture
def setup(tmp_path, monkeypatch):
  from rotom.resume import CandidateResume
  cwd = tmp_path / "working"
  cwd.mkdir()
  target = KnownSession(SessionRef("dsh", "managed", "home-a", "example"),
    "scope-a", "dsh-default", str(cwd), "historical", "historical", 1, "a" * 32)
  calls = []
  streams = InputGateway(Stream("1\n"), Stream(), Stream())
  monkeypatch.setattr(cli, "InputGateway", lambda: streams)

  class Backend(HostResumeBackend):
    code = 0
    def resume_session(self, selected, *, location, before_dispatch, after_dispatch):
      calls.append(selected)
      before_dispatch("b" * 32)
      after_dispatch("b" * 32)
      assert "加载待确认" in streams.stderr.getvalue()
      return LaunchReceipt("b" * 32, self.code)

  backend = Backend()
  loads = []
  def candidate(rows=(target,), lookup=None):
    def load(scope):
      loads.append(scope)
      return "scope-a", tuple(rows)
    return CandidateResume(load, lambda selected: backend, lookup_explicit=lookup)
  return target, candidate, calls, streams, backend, loads


def test_default_resume_builds_factory_once_but_help_and_completion_do_not(setup, monkeypatch):
  from rotom import resume
  target, candidate, calls, _, _, loads = setup
  factories = []
  def factory():
    factories.append(True)
    return candidate()
  monkeypatch.setattr(resume, "dsh_candidate", factory)
  assert cli.main(["resume", "--help"]) == 0
  assert cli.main(["_complete", "--kind", "session", "--tool", "dsh", "--machine", "synthetic"]) == 0
  assert factories == calls == loads == []
  assert cli.main(["--no-input", "resume", "dsh", "--session", "example"]) == 0
  assert factories == [True] and calls == [target] and len(loads) == 1


def test_root_menu_resume_uses_the_same_single_default_factory(setup, monkeypatch):
  from rotom import resume
  target, candidate, calls, streams, _, loads = setup
  names = list(cli._subparsers(cli.build_parser()).choices)
  streams.stdin.seek(0)
  streams.stdin.truncate()
  streams.stdin.write(str(names.index("resume") + 1) + "\n1\n")
  streams.stdin.seek(0)
  factories = []
  monkeypatch.setattr(resume, "dsh_candidate", lambda: factories.append(True) or candidate())
  assert cli.main([]) == 0
  assert factories == [True] and calls == [target] and len(loads) == 1


def test_unique_id_infers_tool_and_pending_keeps_native_exit(setup):
  target, candidate, calls, streams, backend, loads = setup
  backend.code = 7
  assert cli.main(["--no-input", "resume", "--session", "example", "--machine", "synthetic"], resume_candidate=candidate()) == 7
  assert calls == [target] and loads[0].machine == "synthetic"
  text = streams.stderr.getvalue()
  assert "--machine synthetic" in text and "--profile dsh-default" in text
  assert "未发送继续" in text and "example" in text and target.cwd in text


def test_missing_session_uses_menu_even_single_candidate(setup):
  target, candidate, calls, streams, _, _ = setup
  assert cli.main(["resume"], resume_candidate=candidate()) == 0
  assert calls == [target] and "历史" in streams.stderr.getvalue()


@pytest.mark.parametrize("change", [{"ref": SessionRef("dsh", "other", "home-a", "example")},
  {"ref": SessionRef("dsh", "managed", "home-b", "example")}, {"profile": "dsh-cn"}])
def test_same_id_different_complete_target_is_ambiguous_noinput(setup, change):
  target, candidate, calls, _, _, _ = setup
  assert cli.main(["--no-input", "resume", "--session", "example"], resume_candidate=candidate((target, replace(target, **change)))) == 2
  assert calls == []


def test_ambiguous_id_interactive_selects_complete_target(setup):
  target, candidate, calls, streams, _, _ = setup
  other = replace(target, ref=replace(target.ref, native_home_ref="home-b"))
  streams.stdin.seek(0)
  streams.stdin.truncate()
  streams.stdin.write("2\n")
  streams.stdin.seek(0)
  assert cli.main(["resume", "--session", "example"], resume_candidate=candidate((target, other))) == 0
  assert calls == [other]


@pytest.mark.parametrize("argv", [["--no-input", "resume"], ["--no-input", "resume", "dsh"]])
def test_missing_id_noinput_reads_nothing(setup, argv):
  _, candidate, calls, streams, _, _ = setup
  assert cli.main(argv, resume_candidate=candidate()) == 2
  assert calls == [] and streams.stdin.tell() == 0


def test_menu_cancel_has_no_dispatch(setup):
  _, candidate, calls, streams, _, _ = setup
  streams.stdin.seek(0)
  streams.stdin.truncate()
  assert cli.main(["resume"], resume_candidate=candidate()) == 130
  assert calls == []


@pytest.mark.parametrize("option", ["--original", "--new-tab"])
def test_location_rejected_with_full_scope_here_advice(setup, option):
  _, candidate, calls, streams, _, _ = setup
  assert cli.main(["resume", "dsh", "--local", "/tmp/synthetic.toml", "--session", "example", option], resume_candidate=candidate()) == 5
  assert calls == []
  assert "--here" in streams.stderr.getvalue() and "尚未准入" in streams.stderr.getvalue()


def test_explicit_filters_never_fall_back(setup):
  target, candidate, calls, _, _, loads = setup
  other = replace(target, profile="dsh-cn")
  assert cli.main(["--no-input", "resume", "dsh", "--profile", "dsh-default", "--local", "/tmp/synthetic.toml", "--session", "example"], resume_candidate=candidate((other, target))) == 0
  assert calls == [target] and loads[0].local == "/tmp/synthetic.toml"


def test_foreign_scope_is_never_selected(setup):
  target, candidate, calls, _, _, _ = setup
  assert cli.main(["--no-input", "resume", "dsh", "--session", "example"], resume_candidate=candidate((replace(target, scope="foreign"),))) == 5
  assert calls == []


def test_unknown_id_without_lookup_is_capability_failure(setup):
  _, candidate, calls, _, _, _ = setup
  assert cli.main(["--no-input", "resume", "dsh", "--session", "absent"], resume_candidate=candidate()) == 5
  assert calls == []


def test_lookup_only_selected_explicit_tool_and_id(setup):
  target, candidate, calls, _, _, _ = setup
  lookups = []
  def lookup(scope, tool, identifier):
    lookups.append((scope.machine, tool, identifier))
    return replace(target, ref=replace(target.ref, native_ref=identifier))
  assert cli.main(["--no-input", "resume", "dsh", "--machine", "synthetic", "--session", "absent"], resume_candidate=candidate((), lookup)) == 0
  assert lookups == [("synthetic", "dsh", "absent")] and calls[0].ref.native_ref == "absent"


def test_lookup_cannot_return_other_target(setup):
  target, candidate, calls, _, _, _ = setup
  assert cli.main(["--no-input", "resume", "dsh", "--session", "absent"], resume_candidate=candidate((), lambda *a: target)) == 5
  assert calls == []


def test_unknown_cwd_not_automatically_restored(setup):
  target, candidate, calls, streams, _, _ = setup
  target = replace(target, cwd=None, cwd_status="unknown", confirmation="unknown")
  assert cli.main(["resume"], resume_candidate=candidate((target,))) == 5
  assert calls == [] and "不可自动恢复" in streams.stderr.getvalue()


def test_backend_lost_reply_returns_unknown4_not_secret(setup):
  _, candidate, calls, streams, backend, _ = setup
  def lost(*args, **kwargs):
    kwargs["before_dispatch"]("b" * 32)
    raise ConnectionError("synthetic-private-value")
  backend.resume_session = lost
  assert cli.main(["--no-input", "resume", "--session", "example"], resume_candidate=candidate()) == 4
  assert "synthetic-private-value" not in streams.stderr.getvalue()


@pytest.mark.parametrize("stream", ["stdin", "stdout", "stderr"])
def test_menu_requires_all_three_streams(setup, monkeypatch, stream):
  _, candidate, calls, streams, _, _ = setup
  monkeypatch.setattr(getattr(streams, stream), "isatty", lambda: False)
  assert cli.main(["resume"], resume_candidate=candidate()) == 2
  assert calls == [] and streams.stdin.tell() == 0


def test_tool_is_hard_filter_and_does_not_lookup_other_tools(setup):
  target, candidate, calls, _, _, _ = setup
  other = replace(target, ref=replace(target.ref, agent="pi"), profile="pi-base")
  assert cli.main(["--no-input", "resume", "dsh", "--session", "example"], resume_candidate=candidate((other, target))) == 0
  assert calls == [target]


def test_manual_unknown_id_requires_verified_lookup(setup):
  target, candidate, calls, streams, _, _ = setup
  streams.stdin.seek(0)
  streams.stdin.truncate()
  streams.stdin.write("new-id\n")
  streams.stdin.seek(0)
  seen = []
  def lookup(scope, tool, identifier):
    seen.append((tool, identifier))
    return replace(target, ref=replace(target.ref, native_ref=identifier))
  assert cli.main(["resume", "dsh"], resume_candidate=candidate((), lookup)) == 0
  assert seen == [("dsh", "new-id")] and calls[0].ref.native_ref == "new-id"


def test_menu_and_noinput_do_not_write_files(setup, tmp_path):
  _, candidate, calls, streams, _, _ = setup
  def files():
    return {str(path.relative_to(tmp_path)): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
  before = files()
  assert cli.main(["--no-input", "resume"], resume_candidate=candidate()) == 2
  streams.stdin.seek(0)
  streams.stdin.truncate()
  assert cli.main(["resume"], resume_candidate=candidate()) == 130
  assert files() == before and calls == []


def test_menu_escapes_control_characters(setup):
  target, candidate, _, streams, _, _ = setup
  target = replace(target, ref=replace(target.ref, native_ref="bad\nreference"))
  streams.stdin.seek(0)
  streams.stdin.truncate()
  assert cli.main(["resume"], resume_candidate=candidate((target,))) == 130
  assert "bad\\nreference" in streams.stderr.getvalue()
  assert "bad\nreference" not in streams.stderr.getvalue()


def test_snapshot_candidates_reuses_exact_grouping(setup):
  from agentcfg.sessions import SessionIndex
  target, _, _, _, _, _ = setup
  newer = replace(target, observed_at_ns=2)
  other = replace(target, ref=replace(target.ref, native_home_ref="home-b"))
  index = SessionIndex((target, newer, other))
  assert index.candidates(scope="scope-a", native_ref="example") == (newer, other)
  assert index.candidates(scope="elsewhere") == ()


@pytest.mark.parametrize("foreign", [None, "machine", "local"])
def test_local_loader_only_reads_selected_owner_projection(tmp_path, monkeypatch, foreign):
  from contextlib import nullcontext
  from types import SimpleNamespace
  import agentcfg.lifecycle
  import agentcfg.local
  import agentcfg.run_owners
  import agentcfg.workspace
  import rotom.resume as resume
  from rotom.context import Scope
  from test_rotom_known_sessions import saved
  # 使用同一记录fixture的公开合成构造器，不访问原生会话目录。
  machine, record = saved.__wrapped__(tmp_path)
  local = machine["local"]
  instance = tmp_path / "instance"
  instance.mkdir(mode=0o700)
  binding = {**machine, "profile": "dsh-default"}
  if foreign is not None:
    binding[foreign] += "-other"
  workspace = SimpleNamespace(instance=instance, state_root=tmp_path / "state", binding=binding,
    profile="dsh-default", agent="dsh")
  seen = []
  def workspaces(selected_local, profiles):
    seen.append((str(selected_local), profiles))
    return (workspace,)
  monkeypatch.setattr(agentcfg.local, "available_profiles", lambda: [("dsh-default", "dsh"), ("pi-base", "pi")])
  monkeypatch.setattr(agentcfg.workspace, "load_instance_workspaces", workspaces)
  monkeypatch.setattr(agentcfg.lifecycle, "observation_guard", lambda selected: nullcontext())
  monkeypatch.setattr(agentcfg.run_owners.Registry, "snapshot", lambda self: {record["run_id"]: record})
  before = set(tmp_path.rglob("*"))
  key, rows = resume.load_known(Scope(local=local, agent="dsh", profile="dsh-default"))
  from agentcfg.dsh_sessions import scope_key
  assert key == scope_key(binding)
  assert seen == [(local, ["dsh-default"])]
  assert len(rows) == (1 if foreign is None else 0)
  if rows:
    assert rows[0].scope == key and rows[0].confirmation == "historical"
  assert set(tmp_path.rglob("*")) == before


def test_help_completion_and_unrelated_command_do_not_import_resume_adapter(monkeypatch):
  import builtins
  original = builtins.__import__
  def checked(name, *args, **kwargs):
    if name in ("resume", "rotom.resume", "agentcfg.dsh_sessions"):
      pytest.fail("静态帮助、补全或无关命令不加载恢复后端")
    return original(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", checked)
  assert cli.main(["resume", "--help"]) == 0
  assert cli.main(["_complete", "--kind", "session", "--tool", "dsh", "--machine", "synthetic"]) == 0
  assert cli.main(["config", "--help"]) == 0


def test_live_pending_notice_only_once_after_then_exit_receipt(setup):
  _, candidate, _, streams, _, _ = setup
  assert cli.main(["--no-input", "resume", "--session", "example"], resume_candidate=candidate()) == 0
  assert streams.stderr.getvalue().count("已发起恢复，加载待确认") == 1


def test_native_failure_is_explicit_and_preserves_code(setup):
  _, candidate, _, streams, backend, _ = setup
  backend.code = 143
  assert cli.main(["--no-input", "resume", "--session", "example"], resume_candidate=candidate()) == 143
  assert "143" in streams.stderr.getvalue() and "加载未确认" in streams.stderr.getvalue()


def test_profile_source_tool_change_rejects_before_record_query(tmp_path, monkeypatch):
  from types import SimpleNamespace
  import agentcfg.local
  import agentcfg.workspace
  from agentcfg.sessions import SessionError
  from rotom.context import Scope
  from rotom.resume import load_known
  monkeypatch.setattr(agentcfg.local, "available_profiles", lambda: [("dsh-default", "dsh")])
  monkeypatch.setattr(agentcfg.workspace, "load_instance_workspaces", lambda *a: (
    SimpleNamespace(profile="dsh-default", agent="pi"),))
  with pytest.raises(SessionError) as failure:
    load_known(Scope(local=str(tmp_path / "local.toml"), agent="dsh"))
  assert failure.value.code == 4


def test_explicit_profile_imposes_its_public_tool(setup):
  target, candidate, calls, _, _, _ = setup
  other = replace(target, ref=replace(target.ref, agent="pi"))
  assert cli.main(["--no-input", "resume", "--profile", "dsh-default", "--session", "example"], resume_candidate=candidate((other, target))) == 0
  assert calls == [target]


def test_late_display_failure_does_not_replace_native_exit(setup, monkeypatch):
  _, candidate, calls, streams, backend, _ = setup
  backend.code = 9
  original = backend.resume_session
  def completed(*args, **kwargs):
    receipt = original(*args, **kwargs)
    def unavailable(*args, **kwargs):
      raise OSError("synthetic-display-unavailable")
    monkeypatch.setattr(streams.stderr, "write", unavailable)
    return receipt
  backend.resume_session = completed
  assert cli.main(["--no-input", "resume", "--session", "example"], resume_candidate=candidate()) == 9
  assert len(calls) == 1


def test_verified_native_only_lookup_keeps_absent_old_run(setup):
  target, candidate, calls, _, _, _ = setup
  target = replace(target, run_id=None)
  def lookup(scope, tool, identifier):
    return replace(target, ref=replace(target.ref, native_ref=identifier))
  assert cli.main(["--no-input", "resume", "dsh", "--session", "native-only"], resume_candidate=candidate((), lookup)) == 0
  assert len(calls) == 1 and calls[0].run_id is None
