"""受控工厂接线；公开查询和宿主后端全部是假实现。"""
from dataclasses import replace
import io
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import dsh_sessions, sessions
from rotom import cli, resume
from rotom.context import InputGateway, Scope


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
    return SimpleNamespace(agent=damage.get("agent", "dsh"), profile=damage.get("profile", profile), binding=binding)
  def target(workspace, identifier):
    return sessions.KnownSession(sessions.SessionRef("dsh", "managed", "home-a", identifier),
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


@pytest.mark.parametrize("damage", [{"agent": "pi"}, {"profile": "dsh-ssh"},
  {"binding": {"machine": "different"}}, {"binding": {"local": "/tmp/other-synthetic.toml"}}])
def test_workspace_source_or_scope_change_refuses_before_metadata(factory, damage):
  factory.damage.update(damage)
  assert invoke(factory, "dsh", "--profile", "dsh-default", "--session", "native-only") == 4
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


def test_known_nondsh_target_remains_capability5(factory):
  workspace = factory.workspace(factory.local, "dsh-default")
  target = factory.target(workspace, "known-id")
  factory.known.append(replace(target, ref=replace(target.ref, agent="pi"), profile="pi-base"))
  factory.trace.clear()
  assert invoke(factory, "--session", "known-id") == 5
  assert [row[0] for row in factory.trace] == ["known"]


def test_scope_key_cannot_be_remapped_to_another_local(factory, monkeypatch):
  monkeypatch.setattr(resume, "load_known", lambda scope: ("fixed-key", ()))
  candidate = resume.dsh_candidate()
  assert cli.main(["--no-input", "resume", "dsh", "--local", str(factory.local), "--session", "native-only"], resume_candidate=candidate) == 4
  factory.trace.clear()
  assert cli.main(["--no-input", "resume", "dsh", "--local", str(factory.local) + ".other", "--session", "native-only"], resume_candidate=candidate) == 4
  assert factory.trace == []


def test_nondsh_unknown_id_rejects_without_profile_menu_or_lookup(factory):
  factory.profiles.extend((("pi-base", "pi"), ("pi-pro", "pi")))
  assert invoke(factory, "pi", "--session", "native-only") == 5
  assert [row[0] for row in factory.trace] == []
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
def test_default_tool_menu_lists_pi_omp_but_does_not_query_or_launch_them(factory, choice):
  factory.profiles.extend((("pi-base", "pi"), ("omp-default", "omp")))
  answer(factory, choice + "\nnative-only\n")
  assert cli.main(["resume", "--local", str(factory.local)]) == 5
  assert [row[0] for row in factory.trace] == ["known"]
  text = factory.streams.stderr.getvalue()
  assert "Pi" in text and "OMP" in text and "尚未准入" in text


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
