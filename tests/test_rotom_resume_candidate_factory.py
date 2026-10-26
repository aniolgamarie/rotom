"""受控工厂接线；公开查询和宿主后端全部是假实现。"""
from dataclasses import replace
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import dsh_sessions, sessions, tool_sessions, tool_session_headers
from rotom import cli, resume
from rotom.context import InputGateway, Scope


_PI_CANDIDATE = tool_sessions.PiResumeCandidate
_OMP_CANDIDATE = tool_sessions.OmpResumeCandidate


class Stream(io.StringIO):
  def isatty(self):
    return True


@pytest.fixture
def factory(tmp_path, monkeypatch):
  import agentcfg.local
  import agentcfg.workspace
  from agentcfg.paths import xdg_config_home
  local = tmp_path / "local.toml"
  cwd = tmp_path / "original"
  cwd.mkdir()
  streams = InputGateway(Stream("1\n"), Stream(), Stream())
  monkeypatch.setattr(cli, "InputGateway", lambda: streams)
  profiles = [("dsh-default", "dsh")]
  trace = []
  known = []
  damage = {}
  def selected_local(scope):
    return Path(scope.local) if scope.local else xdg_config_home() / "agentcfg/machines" / (scope.machine + ".toml")
  def load(scope):
    trace.append(("known", scope))
    key = dsh_sessions.scope_key({"machine": "synthetic", "local": str(selected_local(scope))})
    return key, tuple(known)
  def workspace(path, profile):
    trace.append(("workspace", Path(path), profile))
    binding = {"machine": "synthetic", "local": str(path), "profile": profile}
    binding.update(damage.get("binding", {}))
    return SimpleNamespace(agent=damage.get("agent", dict(profiles).get(profile, "dsh")),
      profile=damage.get("profile", profile), binding=binding)
  def target(workspace, identifier):
    return sessions.KnownSession(sessions.SessionRef(workspace.agent, "managed", "home-a", identifier),
      dsh_sessions.scope_key(workspace.binding), workspace.profile, str(cwd), "historical", "historical", 1, None)
  def lookup(workspace, identifier):
    trace.append(("lookup", workspace, identifier))
    value = target(workspace, identifier)
    return replace(value, **damage.get("target", {}))
  class Backend(sessions.HostResumeBackend):
    def __init__(self, workspace):
      self.workspace = workspace
      trace.append(("backend", workspace))
    def resume_session(self, target, *, location, before_dispatch, after_dispatch):
      trace.append(("launch", target, self.workspace))
      before_dispatch("c" * 32)
      after_dispatch("c" * 32)
      return sessions.LaunchReceipt("c" * 32, 0)
  monkeypatch.setattr(resume, "load_known", load)
  monkeypatch.setattr(agentcfg.local, "available_profiles", lambda: list(profiles))
  monkeypatch.setattr(agentcfg.workspace, "load_workspace", workspace)
  monkeypatch.setattr(dsh_sessions, "lookup_metadata", lookup)
  monkeypatch.setattr(dsh_sessions, "DshResumeCandidate", Backend)
  monkeypatch.setattr(tool_sessions, "PiResumeCandidate", Backend)
  monkeypatch.setattr(tool_sessions, "OmpResumeCandidate", Backend)
  monkeypatch.setattr(tool_session_headers, "lookup", lambda workspace, identifier:
    SimpleNamespace(known=lookup(workspace, identifier)))
  return SimpleNamespace(local=local, streams=streams, profiles=profiles, trace=trace,
    known=known, damage=damage, target=target, workspace=workspace)


def invoke(factory, *args, noinput=True):
  return cli.main([*(["--no-input"] if noinput else []), "resume", *args,
    "--local", str(factory.local)], resume_candidate=resume.dsh_candidate())


def test_explicit_lookup_and_backend_use_same_local_profile_without_previous_run(factory):
  assert invoke(factory, "dsh", "--profile", "dsh-default", "--session", "native-only") == 0
  assert [row[0] for row in factory.trace] == ["known", "workspace", "lookup", "workspace", "backend", "launch"]
  workspaces = [row for row in factory.trace if row[0] == "workspace"]
  assert workspaces == [("workspace", factory.local, "dsh-default")] * 2
  assert factory.trace[-1][1].run_id is None


def test_unique_public_profile_is_inferred_without_run_defaults(factory):
  assert invoke(factory, "dsh", "--session", "native-only") == 0
  assert [row[2] for row in factory.trace if row[0] == "workspace"] == ["dsh-default"] * 2


def test_profile_only_id_uses_inferred_tool_for_lookup(factory):
  assert invoke(factory, "--profile", "dsh-default", "--session", "native-only") == 0
  assert [row[0] for row in factory.trace].count("lookup") == 1


def test_multiple_profiles_noinput_refuses_without_lookup(factory):
  factory.profiles.append(("dsh-ssh", "dsh"))
  assert invoke(factory, "dsh", "--session", "native-only") == 2
  assert [row[0] for row in factory.trace] == ["known"]
  assert factory.streams.stdin.tell() == 0


def test_multiple_profiles_menu_uses_selected_full_profile(factory):
  factory.profiles.append(("dsh-ssh", "dsh"))
  factory.streams.stdin.seek(0)
  factory.streams.stdin.truncate()
  factory.streams.stdin.write("2\n")
  factory.streams.stdin.seek(0)
  assert invoke(factory, "dsh", "--session", "native-only", noinput=False) == 0
  assert [row[2] for row in factory.trace if row[0] == "workspace"] == ["dsh-ssh"] * 2


def test_profile_menu_cancel_does_not_query(factory):
  factory.profiles.append(("dsh-ssh", "dsh"))
  factory.streams.stdin.seek(0)
  factory.streams.stdin.truncate()
  assert invoke(factory, "dsh", "--session", "native-only", noinput=False) == 130
  assert [row[0] for row in factory.trace] == ["known"]


@pytest.mark.parametrize("damage,expected", [({"agent": "pi"}, 2), ({"profile": "dsh-ssh"}, 4),
  ({"binding": {"machine": "different"}}, 4), ({"binding": {"local": "/tmp/other-synthetic.toml"}}, 4)])
def test_workspace_source_or_scope_change_refuses_before_metadata(factory, damage, expected):
  factory.damage.update(damage)
  assert invoke(factory, "dsh", "--profile", "dsh-default", "--session", "native-only") == expected
  assert [row[0] for row in factory.trace] == ["known", "workspace"]


def test_wrong_lookup_profile_never_reaches_backend(factory):
  factory.damage["target"] = {"profile": "dsh-ssh"}
  assert invoke(factory, "dsh", "--session", "native-only") == 5
  assert "backend" not in [row[0] for row in factory.trace]


def test_known_target_skips_metadata_and_loads_its_exact_workspace(factory):
  workspace = factory.workspace(factory.local, "dsh-default")
  factory.known.append(factory.target(workspace, "known-id"))
  factory.trace.clear()
  assert invoke(factory, "--session", "known-id") == 0
  assert [row[0] for row in factory.trace] == ["known", "workspace", "backend", "launch"]


@pytest.mark.parametrize("tool,profile", [("pi", "pi-base"), ("omp", "omp-default")])
def test_known_tool_target_uses_its_exact_workspace_without_metadata_fallback(factory, tool, profile):
  factory.profiles.append((profile, tool))
  workspace = factory.workspace(factory.local, profile)
  factory.known.append(factory.target(workspace, "known-id"))
  factory.trace.clear()
  assert invoke(factory, "--session", "known-id") == 0
  assert [row[0] for row in factory.trace] == ["known", "workspace", "backend", "launch"]
  assert factory.trace[1] == ("workspace", factory.local, profile)
  assert factory.trace[-1][1].ref.agent == tool
  assert factory.trace[-1][2].agent == tool


def test_scope_key_cannot_be_remapped_to_another_local(factory, monkeypatch):
  monkeypatch.setattr(resume, "load_known", lambda scope: ("fixed-key", ()))
  candidate = resume.dsh_candidate()
  assert cli.main(["--no-input", "resume", "dsh", "--local", str(factory.local), "--session", "native-only"], resume_candidate=candidate) == 4
  factory.trace.clear()
  assert cli.main(["--no-input", "resume", "dsh", "--local", str(factory.local) + ".other", "--session", "native-only"], resume_candidate=candidate) == 4
  assert factory.trace == []


def test_ambiguous_tool_profile_unknown_id_refuses_without_guessing_or_lookup(factory):
  factory.profiles.extend((("pi-base", "pi"), ("pi-pro", "pi")))
  assert invoke(factory, "pi", "--session", "native-only") == 2
  assert [row[0] for row in factory.trace] == ["known"]
  assert factory.streams.stdin.tell() == 0


def test_machine_selector_resolves_only_its_exact_local_file(factory):
  from agentcfg.paths import xdg_config_home
  candidate = resume.dsh_candidate()
  assert cli.main(["--no-input", "resume", "dsh", "--machine", "synthetic", "--profile", "dsh-default",
    "--session", "native-only"], resume_candidate=candidate) == 0
  expected = xdg_config_home() / "agentcfg/machines/synthetic.toml"
  assert [row[1] for row in factory.trace if row[0] == "workspace"] == [expected] * 2


def test_factory_rejects_scope_change_after_metadata_before_backend(factory, monkeypatch):
  original = dsh_sessions.lookup_metadata
  def changed(workspace, identifier):
    target = original(workspace, identifier)
    factory.damage["binding"] = {"machine": "changed-after-query"}
    return target
  monkeypatch.setattr(dsh_sessions, "lookup_metadata", changed)
  assert invoke(factory, "dsh", "--profile", "dsh-default", "--session", "native-only") == 4
  assert "backend" not in [row[0] for row in factory.trace]


def test_profile_selection_and_cancel_never_write_files(factory, tmp_path):
  factory.profiles.append(("dsh-ssh", "dsh"))
  factory.streams.stdin.seek(0)
  factory.streams.stdin.truncate()
  before = set(tmp_path.rglob("*"))
  assert invoke(factory, "dsh", "--session", "native-only", noinput=False) == 130
  assert set(tmp_path.rglob("*")) == before


def answer(factory, value):
  factory.streams.stdin.seek(0)
  factory.streams.stdin.truncate()
  factory.streams.stdin.write(value)
  factory.streams.stdin.seek(0)


def test_default_empty_scope_offers_tool_then_id_without_scope_or_profile_fallback(factory):
  answer(factory, "1\nnative-only\n")
  assert cli.main(["resume", "--local", str(factory.local)]) == 0
  assert [row[0] for row in factory.trace] == ["known", "workspace", "lookup", "workspace", "backend", "launch"]
  assert [row[1] for row in factory.trace if row[0] == "workspace"] == [factory.local, factory.local]
  assert [row[2] for row in factory.trace if row[0] == "workspace"] == ["dsh-default", "dsh-default"]
  assert factory.trace[-1][1].ref.native_ref == "native-only"
  assert "选择恢复工具" in factory.streams.stderr.getvalue()


@pytest.mark.parametrize("choice", ["2", "3"])
def test_default_tool_menu_queries_and_launches_only_selected_tool_and_profile(factory, choice):
  factory.profiles.extend((("pi-base", "pi"), ("omp-default", "omp")))
  answer(factory, choice + "\nnative-only\n")
  assert cli.main(["resume", "--local", str(factory.local)]) == 0
  assert [row[0] for row in factory.trace] == ["known", "workspace", "lookup", "workspace", "backend", "launch"]
  profile, tool = ("pi-base", "pi") if choice == "2" else ("omp-default", "omp")
  assert [row[2] for row in factory.trace if row[0] == "workspace"] == [profile, profile]
  assert factory.trace[-1][1].ref.agent == factory.trace[-1][2].agent == tool
  text = factory.streams.stderr.getvalue()
  assert "Pi" in text and "OMP" in text and "选择恢复工具" in text


def test_default_empty_scope_cancellation_never_queries(factory):
  answer(factory, "")
  assert cli.main(["resume", "--local", str(factory.local)]) == 130
  assert [row[0] for row in factory.trace] == ["known"]


def test_default_noinput_missing_tool_is2_and_does_not_read_stdin(factory):
  answer(factory, "1\nunused\n")
  assert cli.main(["--no-input", "resume", "--local", str(factory.local), "--session", "native-only"]) == 2
  assert [row[0] for row in factory.trace] == ["known"] and factory.streams.stdin.tell() == 0


def test_default_empty_scope_non_tty_never_reads_or_queries(factory):
  factory.streams.stdin.isatty = lambda: False
  answer(factory, "1\nunused\n")
  assert cli.main(["resume", "--local", str(factory.local)]) == 2
  assert factory.trace == [] and factory.streams.stdin.tell() == 0


@pytest.mark.parametrize("tool,profile", [("pi", "pi-base"), ("omp", "omp-default")])
def test_missing_explicit_tool_session_never_falls_back_or_constructs_backend(factory, monkeypatch, tool, profile):
  factory.profiles.append((profile, tool))
  def missing(workspace, identifier):
    factory.trace.append(("lookup", workspace, identifier))
    raise sessions.SessionError(4, "synthetic-native-session-missing")
  monkeypatch.setattr(tool_session_headers, "lookup", missing)
  assert invoke(factory, tool, "--profile", profile, "--session", "missing-id") == 4
  assert [row[0] for row in factory.trace] == ["known", "workspace", "lookup"]
  assert factory.trace[-1][1].profile == profile and factory.trace[-1][2] == "missing-id"
  assert factory.streams.stdin.tell() == 0


@pytest.mark.parametrize("tool,profile,candidate", [
  ("pi", "pi-base", _PI_CANDIDATE), ("omp", "omp-default", _OMP_CANDIDATE),
])
def test_real_tool_candidate_still_rejects_unverified_platform_before_native_lookup_or_launch(
    factory, monkeypatch, tool, profile, candidate):
  factory.profiles.append((profile, tool))
  monkeypatch.setattr(tool_sessions, "PiResumeCandidate" if tool == "pi" else "OmpResumeCandidate", candidate)
  monkeypatch.setattr(tool_sessions.sys, "platform", "unverified-platform")
  monkeypatch.setattr(tool_sessions, "lookup", lambda *a: pytest.fail("unverified native lookup"))
  monkeypatch.setattr(tool_sessions.runtime, "run", lambda *a, **kw: pytest.fail("unverified runtime"))
  assert invoke(factory, tool, "--profile", profile, "--session", "native-only") == 5
  assert [row[0] for row in factory.trace] == ["known", "workspace", "lookup", "workspace"]
