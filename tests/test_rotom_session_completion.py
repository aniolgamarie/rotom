"""会话补全只投影受管元数据；默认隔离且不访问原生存储。"""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import fcntl
import os
import time

import pytest

from agentcfg.sessions import KnownSession, SessionError, SessionRef
from rotom import cli, resume


def query(*extra):
  return ["_complete", "--kind", "session", "--machine", "synthetic", "--tool", "dsh", *extra]


def known(identifier="example", **changes):
  return replace(KnownSession(SessionRef("dsh", "managed", "home-a", identifier),
    "scope-a", "dsh-default", "/synthetic/project", "historical", "historical", 1, "a" * 32), **changes)


@pytest.fixture
def projection(monkeypatch):
  calls = []
  def install(rows):
    def load(scope, **kwargs):
      assert kwargs == {"nonblocking": True}
      calls.append(scope)
      return "scope-a", tuple(rows)
    monkeypatch.setattr(resume, "load_known", load)
  return install, calls


@pytest.mark.parametrize("selector", [["--machine", "synthetic"], ["--local", "/synthetic/local.toml"]])
def test_session_projection_requires_explicit_scope_without_default_profile(selector, projection, capsys):
  install, calls = projection
  target = known("会话_1")
  install([target, replace(target, observed_at_ns=2), known("alpha")])
  assert cli.main(["_complete", "--kind", "session", *selector, "--tool", "dsh"]) == 0
  assert capsys.readouterr().out == "alpha\0会话_1\0"
  assert len(calls) == 1 and calls[0].profile is None and calls[0].agent == "dsh"
  expected = ("synthetic", None) if selector[0] == "--machine" else (None, selector[1])
  assert (calls[0].machine, calls[0].local) == expected
  assert target.confirmation == "historical"


def test_projection_filters_scope_tool_and_profile_before_grouping(projection, capsys):
  install, _ = projection
  install([known("selected"), known("foreign-scope", scope="scope-b"),
    known("foreign-tool", ref=SessionRef("pi", "managed", "home-a", "foreign-tool")),
    known("foreign-profile", profile="dsh-cn")])
  assert cli.main(query("--profile", "dsh-default")) == 0
  assert capsys.readouterr().out == "selected\0"


@pytest.mark.parametrize("tool,profile", [("dsh", "dsh-default"), ("pi", "pi-base"), ("omp", "omp-default")])
def test_each_managed_tool_projects_its_own_known_ids(projection, capsys, tool, profile):
  install, calls = projection
  install([known("known-session", ref=SessionRef(tool, "managed", "home-a", "known-session"),
    profile=profile)])
  assert cli.main(["_complete", "--kind", "session", "--machine", "synthetic",
    "--tool", tool, "--profile", profile]) == 0
  assert capsys.readouterr().out == "known-session\0"
  assert calls[0].agent == tool and calls[0].profile == profile


@pytest.mark.parametrize("change", [{"profile": "dsh-cn"}, {"cwd": "/synthetic/other"},
  {"ref": SessionRef("dsh", "managed", "home-b", "example")},
  {"ref": SessionRef("dsh", "other", "home-a", "example")}])
def test_ambiguous_bare_id_is_not_offered(projection, capsys, change):
  install, _ = projection
  install([known(), known(**change), known("unique")])
  assert cli.main(query()) == 0
  assert capsys.readouterr().out == "unique\0"


def test_explicit_profile_can_disambiguate_same_bare_id(projection, capsys):
  install, _ = projection
  install([known(), known(profile="dsh-cn")])
  assert cli.main(query("--profile", "dsh-default")) == 0
  assert capsys.readouterr().out == "example\0"


@pytest.mark.parametrize("identifier", ["/synthetic/session.json", "bad value", "bad\nvalue", "-option"])
def test_non_cli_session_reference_is_never_emitted(projection, capsys, identifier):
  install, _ = projection
  install([known(identifier), known("valid")])
  assert cli.main(query()) == 2
  assert capsys.readouterr().out == ""


@pytest.mark.parametrize("code", [2, 4])
def test_broken_projection_preserves_failure_and_emits_no_partial_ids(monkeypatch, capsys, code):
  def load(scope, **kwargs):
    raise SessionError(code, "synthetic_broken_index")
  monkeypatch.setattr(resume, "load_known", load)
  assert cli.main(query()) == code
  output = capsys.readouterr()
  assert output.out == "" and "synthetic_broken_index" not in output.err


def test_separator_never_queries_session_metadata(monkeypatch, capsys):
  def forbidden(scope, **kwargs):
    pytest.fail("native tail must not query metadata")
  monkeypatch.setattr(resume, "load_known", forbidden)
  assert cli.main(query("--", "--session", "example")) == 0
  assert capsys.readouterr().out == ""


@pytest.fixture
def managed_metadata(tmp_path, monkeypatch):
  import agentcfg.local
  import agentcfg.workspace
  from agentcfg.deployment import json_bytes
  from test_rotom_known_sessions import saved
  machine, record = saved.__wrapped__(tmp_path)
  Path(machine["local"]).write_text('schema_version=1\n[machine]\nid="synthetic"\n')
  instance = tmp_path / "instance"
  instance.mkdir(mode=0o700)
  state = tmp_path / "state"
  owners = state / "run-owners"
  owners.mkdir(mode=0o700, parents=True)
  binding = {**machine, "profile": "dsh-default"}
  marker = instance / ".agentcfg-instance.json"
  marker.write_bytes(json_bytes({"schema_version": 1, "state_root": str(state), "binding": binding}))
  record_path = owners / (record["run_id"] + ".json")
  record_path.write_text(json.dumps(record))
  workspace = SimpleNamespace(instance=instance, state_root=state, binding=binding, profile="dsh-default", agent="dsh")
  monkeypatch.setattr(agentcfg.local, "available_profiles", lambda: [("dsh-default", "dsh")])
  monkeypatch.setattr(agentcfg.workspace, "load_instance_workspaces", lambda *args: (workspace,))
  return machine, record, record_path, marker


@pytest.mark.parametrize("damage", [None, "missing-index", "no-observation", "json", "permission", "binding", "home"])
def test_real_owner_projection_is_readonly_and_rejects_bad_metadata(managed_metadata, damage, tmp_path, sentinel_factory, capsys):
  machine, record, record_path, marker = managed_metadata
  if damage == "missing-index":
    record_path.unlink()
    record_path.parent.rmdir()
  elif damage == "no-observation":
    record["session_observation"] = None
    record_path.write_text(json.dumps(record))
  elif damage == "json":
    record_path.write_text("{")
  elif damage == "permission":
    record_path.chmod(0o644)
  elif damage == "binding":
    marker.write_text("{}")
  elif damage == "home":
    record["session_observation"]["session"]["native_home_ref"] = "foreign-home"
    record_path.write_text(json.dumps(record))
  before = sentinel_factory(tmp_path)
  result = cli.main(["_complete", "--kind", "session", "--local", machine["local"], "--tool", "dsh"])
  output = capsys.readouterr().out
  if damage is None:
    assert result == 0 and output == "synthetic-session\0"
  elif damage in ("missing-index", "no-observation"):
    assert result == 0 and output == ""
  else:
    assert result != 0 and output == ""
  before.assert_unchanged()


@pytest.mark.parametrize("lock_scope", ["owners", "instance"])
def test_busy_owner_metadata_fails_without_waiting_or_writing(managed_metadata, tmp_path, sentinel_factory, capsys, lock_scope):
  machine, _, record_path, marker = managed_metadata
  before = sentinel_factory(tmp_path)
  lock_root = record_path.parent if lock_scope == "owners" else marker.parent
  descriptor = os.open(lock_root, os.O_RDONLY | os.O_DIRECTORY)
  try:
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    started = time.monotonic()
    result = cli.main(["_complete", "--kind", "session", "--local", machine["local"], "--tool", "dsh"])
    elapsed = time.monotonic() - started
    assert result == 4
    assert elapsed < 2
    assert capsys.readouterr().out == ""
  finally:
    os.close(descriptor)
  before.assert_unchanged()


@pytest.mark.parametrize("change", [{"confirmation": "unknown"}, {"cwd": None, "cwd_status": "unknown"},
  {"cwd_status": "unknown"}, {"ref": SessionRef("dsh", "other", "home-a", "example")}])
def test_unadmitted_saved_targets_do_not_become_candidates(projection, capsys, change):
  install, _ = projection
  install([known(**change)])
  assert cli.main(query()) == 0
  assert capsys.readouterr().out == ""
