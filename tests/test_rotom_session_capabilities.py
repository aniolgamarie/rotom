"""描述性精确组合矩阵，不构成真实宿主或生产能力准入。"""
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path

import pytest

from agentcfg import sessions


RUNTIME = "e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d"
KEY = {"agent": "dsh", "backend": "managed", "runtime_identity": RUNTIME,
  "observer_identity": "none", "platform": "linux", "location": "here"}


def query(**changes):
  return sessions.session_capability(**{**KEY, **changes})


def test_exact_admitted_handoff_does_not_claim_loaded_or_automatic_input():
  result = query()
  assert result.handoff == "admitted" and result.reason == "verified_linux_dsh_handoff"
  assert result.load_confirmation is False and result.automatic_continue is False and result.final_seal is False
  assert result.manual_guidance
  assert all(getattr(result, key) == value for key, value in KEY.items())
  assert "admitted" in asdict(result).values()


@pytest.mark.parametrize("change", [{"agent": "pi"}, {"agent": "omp"}, {"agent": "unknown"},
  {"backend": "other"}, {"runtime_identity": "0" * 64}, {"runtime_identity": "unknown"},
  {"observer_identity": "plugin-example"}, {"observer_identity": "ready"},
  {"platform": "darwin"}, {"platform": "win32"}, {"platform": "Linux"},
  {"location": "original"}, {"location": "new-tab"}, {"location": "unknown"}])
def test_every_other_exact_combination_is_unavailable_without_fallback(change):
  result = query(**change)
  assert result.handoff == "unavailable" and result.reason == "exact_combination_unavailable"
  assert result.load_confirmation is False and result.automatic_continue is False and result.final_seal is False
  assert result.manual_guidance


def test_return_value_is_frozen_and_queries_do_not_mutate_the_matrix():
  result = query()
  with pytest.raises(FrozenInstanceError):
    result.handoff = "admitted"
  with pytest.raises(FrozenInstanceError):
    result.automatic_continue = True
  query(agent="pi")
  assert query() == result and query() is not result


@pytest.mark.parametrize("field", list(KEY))
@pytest.mark.parametrize("value", [None, True, 1, 1.0, [], {}, "", "bad\0key", "bad\nkey"])
def test_invalid_key_values_fail_without_coercion(field, value):
  with pytest.raises(sessions.SessionError) as caught:
    query(**{field: value})
  assert caught.value.code == 2


@pytest.mark.parametrize("missing", list(KEY))
def test_all_dimensions_are_required_without_implicit_defaults(missing):
  key = dict(KEY)
  del key[missing]
  with pytest.raises(TypeError):
    sessions.session_capability(**key)


def test_unknown_dimension_is_not_silently_ignored():
  with pytest.raises(TypeError):
    query(loaded=True)


def test_current_full_dsh_lock_identity_must_match_reviewed_candidate():
  from agentcfg.dependencies import read_lock
  repository = Path(__file__).resolve().parents[1]
  lock = read_lock(repository, "dsh")
  assert lock.identity == RUNTIME, "完整运行锁变化后必须重新审查候选能力组合"
  assert query(runtime_identity=lock.identity).handoff == "admitted"


@pytest.mark.parametrize("agent", ["pi", "omp"])
def test_tool_handoff_requires_reviewed_complete_lock_and_control_sources(agent):
  import json
  from agentcfg.pi_session_guard import source_identity
  root = Path(__file__).resolve().parents[1]
  identity = json.loads((root / "locks" / agent / "manifest.json").read_text())["identity"]
  observer = source_identity() if agent == "pi" else "none"
  key = {**KEY, "agent": agent, "runtime_identity": identity, "observer_identity": observer}
  result = sessions.session_capability(**key)
  assert result.handoff == "admitted" and not result.load_confirmation and not result.automatic_continue
  assert sessions.session_capability(**{**key, "runtime_identity": "0" * 64}).handoff == "unavailable"
  assert sessions.session_capability(**{**key, "observer_identity": "other"}).handoff == "unavailable"


def test_query_has_no_config_environment_or_subprocess_dependency(monkeypatch):
  import builtins
  import os
  import subprocess
  def forbidden(*args, **kwargs):
    pytest.fail("描述性查询不得访问配置、环境或派发进程")
  with monkeypatch.context() as guard:
    guard.setattr(builtins, "open", forbidden)
    guard.setattr(Path, "open", forbidden)
    guard.setattr(os, "getenv", forbidden)
    guard.setattr(subprocess, "Popen", forbidden)
    guard.setattr(subprocess, "run", forbidden)
    assert query().handoff == "admitted"
    assert query(observer_identity="ready").handoff == "unavailable"
