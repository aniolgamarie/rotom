"""只读会话类型和保存记录索引；不执行宿主、不读取原生会话正文。"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def sessions():
  return importlib.import_module("agentcfg.sessions")


@pytest.fixture
def saved(tmp_path):
  from agentcfg.run_owners import Registry, native_home_key
  machine = {"machine": "synthetic", "local": str(tmp_path / "local.toml")}
  binding = {**machine, "profile": "dsh-default"}
  manager = {"pid": 12345, "birth_id": "synthetic-birth"}
  home = {"kind": "dsh-home", "path": str(tmp_path / "absent-native-home"),
    "source": "deployed-contract", "confirmation": "confirmed"}
  record = {"schema_version": 2, "run_id": "a" * 32,
    "binding_digest": Registry(tmp_path / "unused", binding).binding_digest,
    "manager_identity": manager, "host_identity": None, "agent": "dsh", "backend": "managed",
    "profile": "dsh-default", "machine_ref": machine,
    "start_cwd": {"path": str(tmp_path / "start-only"), "source": "launch-spec",
      "confirmation": "confirmed", "observed_at_ns": 1},
    "session_cwd": {"path": str(tmp_path / "absent-session-cwd"), "source": "synthetic-session-event",
      "confirmation": "confirmed", "observed_at_ns": 2},
    "native_home_ref": home, "deployed_identity": {"deployment": "b" * 64, "runtime": "c" * 64},
    "lifecycle_state": "active", "affected_resources": ["instance", "runtime", "native-home"],
    "process_observation": {"kind": "manager_registered", "coverage": "unknown",
      "source": "manager-registration", "observed_at_ns": 1,
      "manager_identity": deepcopy(manager), "host_identity": None},
    "session_observation": {"session": {"agent": "dsh", "backend": "managed",
      "native_home_ref": native_home_key(home), "native_ref": "synthetic-session"},
      "run_id": "a" * 32, "emitter_epoch": "synthetic-emitter", "sequence": 1,
      "confirmation": "confirmed", "source": "synthetic-session-event", "observed_at_ns": 2},
    "terminal_ref": None, "protocol": {"registration": 2, "control": None}, "coordination_domain": None}
  return machine, record


def test_ref_is_frozen_and_keeps_restricted_reference_without_filesystem_lookup(sessions):
  ref = sessions.SessionRef("dsh", "managed", "home-a", "/restricted/session-reference")
  assert ref.native_ref == "/restricted/session-reference"
  with pytest.raises(FrozenInstanceError):
    ref.native_ref = "other"


@pytest.mark.parametrize("changes", [{"agent": "other"}, {"backend": "bad/route"},
  {"native_home_ref": ""}, {"native_ref": ""}, {"native_ref": "bad\0ref"},
  {"native_ref": True}, {"native_ref": "x" * 1025}, {"unexpected": "field"}])
def test_ref_rejects_invalid_types_and_unknown_fields(sessions, changes):
  values = {"agent": "dsh", "backend": "managed", "native_home_ref": "home-a", "native_ref": "example"}
  values.update(changes)
  with pytest.raises((sessions.SessionError, TypeError)):
    sessions.SessionRef(**values)


@pytest.mark.parametrize("field,value", [("sequence", True), ("sequence", 1.0),
  ("sequence", 0), ("observed_at_ns", float("nan")), ("observed_at_ns", True),
  ("run_id", "bad"), ("run_id", "a" * 32 + "\n"), ("emitter_epoch", "bad/epoch"), ("source", ""),
  ("confirmation", "ready")])
def test_observation_rejects_inexact_numbers_and_untrusted_sources(sessions, field, value):
  values = {"session": sessions.SessionRef("pi", "managed", "home-a", "example"),
    "run_id": "a" * 32, "emitter_epoch": "synthetic-epoch", "sequence": 1,
    "confirmation": "confirmed", "source": "synthetic-event", "observed_at_ns": 1}
  values[field] = value
  with pytest.raises(sessions.SessionError):
    sessions.SessionObservation(**values)


def test_schema_is_an_unwrapped_ref_and_shared_definitions_match_run_record():
  root = Path(__file__).resolve().parents[1] / "schemas/rotom"
  schema = json.loads((root / "session.schema.json").read_text())
  run = json.loads((root / "run-record.schema.json").read_text())
  assert schema["$ref"] == "#/$defs/session_ref"
  for name in ("session_ref", "session_observation"):
    assert schema["$defs"][name] == run["$defs"][name]


def test_observation_is_frozen_and_keeps_exact_run_emitter_sequence_source(sessions):
  ref = sessions.SessionRef("dsh", "managed", "home-a", "session-example")
  observation = sessions.SessionObservation(ref, "a" * 32, "emitter-example", 4,
    "historical", "synthetic-native-event", 9)
  assert observation.session == ref and observation.sequence == 4
  assert observation.source == "synthetic-native-event" and observation.emitter_epoch == "emitter-example"
  with pytest.raises(FrozenInstanceError):
    observation.sequence = 5


@pytest.mark.parametrize("field,value", [("scope", ""), ("profile", "bad/id"),
  ("cwd", "relative"), ("cwd", "/tmp/../example"), ("cwd", None),
  ("cwd_status", "ready"), ("confirmation", "ready"),
  ("observed_at_ns", True), ("observed_at_ns", 1.0), ("observed_at_ns", float("nan")),
  ("run_id", "a" * 32 + "\n")])
def test_known_session_rejects_inexact_types_paths_and_guessed_status(sessions, saved, field, value):
  machine, record = saved
  target, = sessions.from_run_records({record["run_id"]: record}, scope="scope-a", machine_ref=machine)
  with pytest.raises(sessions.SessionError):
    replace(target, **{field: value})


def test_saved_view_is_historical_readonly_and_never_stats_missing_native_paths(sessions, saved, monkeypatch):
  machine, record = saved
  before = deepcopy(record)
  protected = [Path(record["native_home_ref"]["path"]), Path(record["session_cwd"]["path"])]
  original_stat, original_iterdir = Path.stat, Path.iterdir
  def guard(original):
    def checked(path, *args, **kwargs):
      if any(path == root or path.is_relative_to(root) for root in protected):
        pytest.fail("saved metadata must not inspect native storage or cwd")
      return original(path, *args, **kwargs)
    return checked
  monkeypatch.setattr(Path, "stat", guard(original_stat))
  monkeypatch.setattr(Path, "iterdir", guard(original_iterdir))
  view = sessions.from_run_records({record["run_id"]: record}, scope="opaque-scope", machine_ref=machine)
  result = sessions.SessionIndex(view).select(scope="opaque-scope", native_ref="synthetic-session")
  assert result.scope == "opaque-scope" and result.profile == "dsh-default"
  assert result.confirmation == "historical" and result.cwd_status == "historical"
  assert result.cwd == record["session_cwd"]["path"] and result.run_id == record["run_id"]
  assert result.observed_at_ns == 2 and record == before
  with pytest.raises(FrozenInstanceError):
    result.confirmation = "confirmed"


def test_absent_session_or_session_cwd_is_not_guessed_from_start_or_home(sessions, saved):
  machine, record = saved
  record["session_cwd"] = None
  view = sessions.from_run_records({record["run_id"]: record}, scope="scope-a", machine_ref=machine)
  assert view[0].cwd is None and view[0].cwd_status == "unknown"
  record["session_observation"] = None
  assert sessions.from_run_records({record["run_id"]: record}, scope="scope-a", machine_ref=machine) == ()


@pytest.mark.parametrize("filter", ["machine", "local", "profile"])
def test_view_filters_exact_machine_local_and_explicit_profile(sessions, saved, filter):
  machine, record = saved
  requested = deepcopy(machine)
  if filter in ("machine", "local"):
    requested[filter] += "-other"
  options = {"profile": "pi-base"} if filter == "profile" else {}
  assert sessions.from_run_records({record["run_id"]: record}, scope="scope-a", machine_ref=requested, **options) == ()


@pytest.mark.parametrize("damage", ["digest", "scope", "source", "version", "record-key", "float", "extra"])
def test_view_reuses_complete_record_validation_before_filtering(sessions, saved, damage):
  machine, record = saved
  if damage == "digest": record["binding_digest"] = "d" * 64
  elif damage == "scope": record["session_observation"]["session"]["native_home_ref"] = "different-home"
  elif damage == "source": record["process_observation"]["source"] = "forged"
  elif damage == "version": record["schema_version"] = True
  elif damage == "float": record["session_observation"]["sequence"] = 1.0
  elif damage == "extra": record["unknown"] = "field"
  key = "f" * 32 if damage == "record-key" else record["run_id"]
  requested = {**machine, "machine": "foreign-scope"}
  with pytest.raises(sessions.SessionError):
    sessions.from_run_records({key: record}, scope="scope-a", machine_ref=requested)


@pytest.mark.parametrize("machine", [{"machine": "bad/id", "local": "/tmp/example.toml"},
  {"machine": "synthetic", "local": "relative.toml"},
  {"machine": "synthetic", "local": "/tmp/../example.toml"},
  {"machine": "synthetic", "local": "/tmp/example.toml", "extra": True}])
def test_view_requires_explicit_exact_scope_binding(sessions, machine):
  with pytest.raises(sessions.SessionError):
    sessions.from_run_records({}, scope="scope-a", machine_ref=machine)


def test_view_ignores_valid_legacy_record_without_inventing_session(sessions, saved):
  machine, record = saved
  legacy = {key: deepcopy(record[key]) for key in ("binding_digest", "run_id", "manager_identity", "affected_resources")}
  legacy.update(schema_version=1, session_ref="opaque-v1-id", state="active",
    observation={"kind": "manager_registered", "observed_at_ns": 1, "coverage": "unknown"})
  assert sessions.from_run_records({legacy["run_id"]: legacy}, scope="scope-a", machine_ref=machine) == ()


@pytest.mark.parametrize("query", [{"native_ref": ""}, {"scope": ""}, {"agent": "other"}, {"profile": "bad/id"}])
def test_invalid_selection_never_falls_back_to_only_candidate(sessions, saved, query):
  machine, record = saved
  index = sessions.SessionIndex(sessions.from_run_records({record["run_id"]: record}, scope="scope-a", machine_ref=machine))
  options = {"scope": "scope-a", **query}
  with pytest.raises(sessions.SessionError) as caught:
    index.select(**options)
  assert caught.value.code == 2


@pytest.mark.parametrize("conflicting_cwd", [False, True])
def test_same_exact_target_across_runs_uses_latest_history_but_cwd_conflict_is_ambiguous(sessions, saved, conflicting_cwd):
  machine, first = saved
  second = deepcopy(first)
  second["run_id"] = second["session_observation"]["run_id"] = "d" * 32
  second["session_observation"]["observed_at_ns"] = 10
  if conflicting_cwd:
    second["session_cwd"]["path"] += "-other"
  view = sessions.from_run_records({first["run_id"]: first, second["run_id"]: second},
    scope="scope-a", machine_ref=machine)
  index = sessions.SessionIndex(view)
  if conflicting_cwd:
    with pytest.raises(sessions.SessionError) as caught:
      index.select(scope="scope-a", native_ref="synthetic-session")
    assert caught.value.code == 2
  else:
    result = index.select(scope="scope-a", native_ref="synthetic-session")
    assert result.run_id == second["run_id"] and result.observed_at_ns == 10
    assert result.confirmation == "historical"


def test_native_metadata_target_has_explicitly_absent_previous_rotom_run(sessions):
  import inspect
  target = sessions.KnownSession(sessions.SessionRef("dsh", "managed", "home-a", "native-only"),
    "scope-a", "dsh-default", "/tmp/synthetic-original", "historical", "historical", 1, None)
  assert target.run_id is None
  assert inspect.signature(sessions.KnownSession).parameters["run_id"].default is inspect.Parameter.empty
  for change in ({"cwd": "relative"}, {"confirmation": "loaded"}, {"ref": None},
      {"run_id": True}, {"run_id": 1}, {"run_id": 1.0}, {"run_id": ""}):
    with pytest.raises(sessions.SessionError):
      replace(target, **change)
