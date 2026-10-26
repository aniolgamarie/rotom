"""事件归并契约；合成事件不代表公开宿主回调或真实最终封口证据。"""

from copy import deepcopy
import importlib

import pytest

from agentcfg.run_owners import ReleaseObservation


@pytest.fixture
def sessions():
  return importlib.import_module("agentcfg.sessions")


def tracker(sessions):
  return sessions.SessionEventTracker(run_id="a" * 32, emitter_epoch="epoch-current",
    manager_identity={"pid": 1234, "birth_id": "synthetic-birth"})


def event(sessions, sequence, *, kind="session-confirmed", native_ref="session-a",
    run_id="a" * 32, epoch="epoch-current"):
  return sessions.SessionEvent(run_id=run_id, emitter_epoch=epoch, sequence=sequence,
    kind=kind, session=sessions.SessionRef(agent="dsh", backend="managed",
      native_home_ref="home-a", native_ref=native_ref),
    cwd="/home/example/project", observed_at_ns=sequence,
    source="synthetic-public-completion")


def release(*, complete=True, all_related_exited=True, run_id="a" * 32, birth_id="synthetic-birth"):
  return ReleaseObservation(run_id=run_id, manager_identity={"pid": 1234, "birth_id": birth_id},
    all_related_exited=all_related_exited, complete=complete)


def test_selection_intent_does_not_replace_current_or_prove_load(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="session-selection", native_ref="session-b"))
  value = state.snapshot()
  assert value["current"].native_ref == "session-a"
  assert value["load_confirmed"] is False and value["final"] is None
  state.accept(event(sessions, 3, native_ref="session-b"))
  assert state.snapshot()["current"].native_ref == "session-b"
  assert state.snapshot()["load_confirmed"] is False


def test_identical_duplicate_is_idempotent_but_conflicting_sequence_is_rejected(sessions):
  state = tracker(sessions)
  first = event(sessions, 1)
  state.accept(first)
  before = deepcopy(state.snapshot())
  assert state.accept(first) is False and state.snapshot() == before
  with pytest.raises(sessions.SessionError) as caught:
    state.accept(event(sessions, 1, native_ref="different"))
  assert caught.value.code == 4
  assert state.snapshot()["final"] is None


@pytest.mark.parametrize("foreign", ["run", "epoch"])
def test_old_run_or_emitter_epoch_cannot_update_current(sessions, foreign):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  before = deepcopy(state.snapshot())
  state.accept(event(sessions, 2, native_ref="different",
    run_id="b" * 32 if foreign == "run" else "a" * 32,
    epoch="old-epoch" if foreign == "epoch" else "epoch-current"))
  assert state.snapshot() == before


def test_gap_late_events_and_seal_never_invent_final_exact_session(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 3, native_ref="session-c"))
  state.accept(event(sessions, 2, native_ref="session-b"))
  state.accept(event(sessions, 4, kind="session-sealed", native_ref="session-c"))
  state.record_release(release())
  value = state.snapshot()
  assert value["confirmation"] in ("historical", "unknown")
  assert value["final"] is None and value["process_exit_proven"] is True


def test_load_confirmation_and_final_seal_are_independent(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="load-confirmed"))
  assert state.snapshot()["load_confirmed"] is True
  assert state.snapshot()["final"] is None
  state.accept(event(sessions, 3, kind="session-sealed"))
  assert state.snapshot()["final"] is None
  state.record_release(release())
  assert state.snapshot()["final"].native_ref == "session-a"


@pytest.mark.parametrize("kind", ["load-confirmed", "session-sealed"])
@pytest.mark.parametrize("different", ["native_ref", "backend", "native_home"])
def test_confirmation_or_seal_must_match_the_exact_current_session(sessions, kind, different):
  from dataclasses import replace
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  wrong = event(sessions, 2, kind=kind)
  wrong_ref = sessions.SessionRef(agent="dsh",
    backend="other" if different == "backend" else "managed",
    native_home_ref="other-home" if different == "native_home" else "home-a",
    native_ref="session-b" if different == "native_ref" else "session-a")
  state.accept(replace(wrong, session=wrong_ref))
  assert state.snapshot()["load_confirmed"] is False
  state.record_release(release())
  assert state.snapshot()["final"] is None
  assert state.snapshot()["process_exit_proven"] is True


@pytest.mark.parametrize("failure", ["incomplete", "descendant_alive", "wrong_run", "wrong_birth"])
def test_seal_without_complete_same_identity_release_cannot_be_final(sessions, failure):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="session-sealed"))
  observation = release(complete=failure != "incomplete", all_related_exited=failure != "descendant_alive",
    run_id="b" * 32 if failure == "wrong_run" else "a" * 32,
    birth_id="other-birth" if failure == "wrong_birth" else "synthetic-birth")
  state.record_release(observation)
  assert state.snapshot()["final"] is None
  assert state.snapshot()["process_exit_proven"] is False


def test_missing_seal_keeps_known_history_without_undoing_complete_exit(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.record_release(release())
  value = state.snapshot()
  assert value["current"].native_ref == "session-a" and value["final"] is None
  assert value["process_exit_proven"] is True


def test_event_after_seal_invalidates_final_proof_but_not_kernel_exit(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="session-sealed"))
  state.record_release(release())
  assert state.snapshot()["final"] is not None
  state.accept(event(sessions, 3, native_ref="late-session"))
  assert state.snapshot()["final"] is None
  assert state.snapshot()["process_exit_proven"] is True


@pytest.mark.parametrize("sequence", [True, 1.0, 0, -1])
def test_event_sequence_requires_positive_exact_integer(sessions, sequence):
  with pytest.raises((sessions.SessionError, ValueError)):
    event(sessions, sequence)


@pytest.mark.parametrize("field,value", [
  ("run_id", "invalid"), ("run_id", "A" * 32),
  ("emitter_epoch", "invalid epoch"), ("source", ""),
  ("observed_at_ns", True), ("observed_at_ns", 1.0), ("observed_at_ns", 0),
  ("kind", "ready"), ("session", {}),
  ("cwd", "relative"), ("cwd", "/workspace/../other"), ("cwd", "/workspace\0other"),
])
def test_event_fields_are_strict_and_do_not_echo_invalid_values(sessions, field, value):
  from dataclasses import replace
  with pytest.raises(sessions.SessionError) as caught:
    replace(event(sessions, 1), **{field: value})
  assert caught.value.code == 2
  assert str(caught.value) == "invalid_session_event"


@pytest.mark.parametrize("field,value", [
  ("run_id", "old"), ("emitter_epoch", "bad epoch"),
  ("manager_identity", {"pid": True, "birth_id": "synthetic-birth"}),
  ("manager_identity", {"pid": 1234, "birth_id": ""}),
])
def test_tracker_identity_is_validated(sessions, field, value):
  options = {"run_id": "a" * 32, "emitter_epoch": "epoch-current",
    "manager_identity": {"pid": 1234, "birth_id": "synthetic-birth"}}
  options[field] = value
  with pytest.raises(sessions.SessionError) as caught:
    sessions.SessionEventTracker(**options)
  assert caught.value.code == 2


@pytest.mark.parametrize("kind", ["load-confirmed", "session-sealed"])
def test_matching_ref_with_wrong_cwd_never_proves_load_or_seal(sessions, kind):
  from dataclasses import replace
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(replace(event(sessions, 2, kind=kind), cwd="/workspace/different"))
  state.record_release(release())
  value = state.snapshot()
  assert value["cwd"] == "/home/example/project"
  assert value["load_confirmed"] is False and value["final"] is None
  assert value["process_exit_proven"] is True


def test_conflict_permanently_removes_load_and_seal_trust(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="load-confirmed"))
  with pytest.raises(sessions.SessionError):
    state.accept(event(sessions, 2, native_ref="conflicting"))
  state.accept(event(sessions, 3, kind="load-confirmed"))
  state.accept(event(sessions, 4, kind="session-sealed"))
  state.record_release(release())
  value = state.snapshot()
  assert value["load_confirmed"] is False and value["final"] is None
  assert value["confirmation"] == "historical" and value["process_exit_proven"] is True


def test_sequence_must_start_at_one_and_late_event_cannot_recover_trust(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 2, native_ref="newer"))
  state.accept(event(sessions, 1, native_ref="older"))
  state.accept(event(sessions, 3, kind="load-confirmed", native_ref="newer"))
  assert state.snapshot()["current"].native_ref == "newer"
  assert state.snapshot()["load_confirmed"] is False
  assert state.snapshot()["confirmation"] == "historical"


@pytest.mark.parametrize("kind", ["session-selection", "session-confirmed", "load-confirmed", "session-sealed"])
def test_every_new_event_after_seal_permanently_invalidates_final(sessions, kind):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  sealed = event(sessions, 2, kind="session-sealed")
  state.accept(sealed)
  state.record_release(release())
  before = state.snapshot()
  assert state.accept(sealed) is False and state.snapshot() == before
  state.accept(event(sessions, 3, kind=kind))
  state.accept(event(sessions, 4, kind="load-confirmed"))
  state.accept(event(sessions, 5, kind="session-sealed"))
  state.record_release(release())
  assert state.snapshot()["final"] is None
  assert state.snapshot()["load_confirmed"] is False
  assert state.snapshot()["process_exit_proven"] is True


@pytest.mark.parametrize("flag", ["complete", "all_related_exited"])
@pytest.mark.parametrize("value", [1, "true"])
def test_release_requires_exact_true_not_truthy_flags(sessions, flag, value):
  from dataclasses import replace
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="session-sealed"))
  assert state.record_release(replace(release(), **{flag: value})) is False
  assert state.snapshot()["process_exit_proven"] is False
  assert state.snapshot()["final"] is None


def test_manager_identity_and_snapshot_cannot_be_mutated_by_callers(sessions):
  from dataclasses import replace
  manager = {"pid": 1234, "birth_id": "synthetic-birth", "extra": {"generation": 1}}
  state = sessions.SessionEventTracker(run_id="a" * 32, emitter_epoch="epoch-current",
    manager_identity=manager)
  manager["extra"]["generation"] = 2
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="session-sealed"))
  state.record_release(replace(release(), manager_identity={"pid": 1234,
    "birth_id": "synthetic-birth", "extra": {"generation": 1}}))
  snapshot = state.snapshot()
  snapshot["current"] = None
  snapshot["process_exit_proven"] = False
  assert state.snapshot()["current"].native_ref == "session-a"
  assert state.snapshot()["final"].native_ref == "session-a"
  assert state.snapshot()["process_exit_proven"] is True


def test_bad_or_foreign_release_never_undoes_existing_exit_proof(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.record_release(release())
  for invalid in ({"complete": True}, release(complete=False), release(run_id="b" * 32)):
    assert state.record_release(invalid) is False
  assert state.snapshot()["process_exit_proven"] is True


def test_event_retention_is_bounded_and_evicted_old_event_cannot_restore_trust(sessions):
  import gc
  import weakref
  state = tracker(sessions)
  references = []
  for sequence in range(1, 301):
    observed = event(sessions, sequence)
    references.append(weakref.ref(observed))
    state.accept(observed)
  del observed
  gc.collect()
  assert sum(reference() is not None for reference in references) == 256
  state.accept(event(sessions, 301, kind="load-confirmed"))
  assert state.snapshot()["load_confirmed"] is True
  assert state.accept(event(sessions, 1)) is False
  assert state.snapshot()["current"].native_ref == "session-a"
  assert state.snapshot()["load_confirmed"] is False
  assert state.snapshot()["confirmation"] == "historical"


@pytest.mark.parametrize("kind", ["load-confirmed", "session-sealed"])
@pytest.mark.parametrize("different", ["session", "cwd"])
def test_mismatched_proof_cannot_be_repaired_by_later_matching_event(sessions, kind, different):
  from dataclasses import replace
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="load-confirmed"))
  contradictory = event(sessions, 3, kind=kind,
    native_ref="different-session" if different == "session" else "session-a")
  if different == "cwd":
    contradictory = replace(contradictory, cwd="/workspace/different")
  state.accept(contradictory)
  state.accept(event(sessions, 4, kind="load-confirmed"))
  state.accept(event(sessions, 5, kind="session-sealed"))
  state.record_release(release())
  value = state.snapshot()
  assert value["current"].native_ref == "session-a"
  assert value["cwd"] == "/home/example/project"
  assert value["load_confirmed"] is False and value["final"] is None
  assert value["confirmation"] == "historical" and value["process_exit_proven"] is True


@pytest.mark.parametrize("foreign", ["run", "epoch"])
def test_foreign_event_after_final_seal_does_not_invalidate_this_epoch(sessions, foreign):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="session-sealed"))
  state.record_release(release())
  before = state.snapshot()
  assert state.accept(event(sessions, 99,
    run_id="b" * 32 if foreign == "run" else "a" * 32,
    epoch="other-epoch" if foreign == "epoch" else "epoch-current")) is False
  assert state.snapshot() == before


def test_release_and_seal_can_arrive_independently_without_inventing_load(sessions):
  state = tracker(sessions)
  state.accept(event(sessions, 1))
  state.record_release(release())
  assert state.snapshot()["final"] is None
  state.accept(event(sessions, 2, kind="session-sealed"))
  assert state.snapshot()["final"].native_ref == "session-a"
  assert state.snapshot()["load_confirmed"] is False
  assert state.snapshot()["process_exit_proven"] is True


def test_user_mapping_is_not_a_trusted_event(sessions):
  state = tracker(sessions)
  before = state.snapshot()
  with pytest.raises(sessions.SessionError) as caught:
    state.accept({"kind": "load-confirmed", "sequence": 1})
  assert caught.value.code == 2 and state.snapshot() == before


@pytest.mark.parametrize("expected,observed", [
  (1, True), (1, 1.0), (True, 1), (True, 1.0), (1.0, 1), (1.0, True),
])
def test_extended_manager_identity_requires_exact_json_type(sessions, expected, observed):
  from dataclasses import replace
  manager = {"pid": 1234, "birth_id": "synthetic-birth", "extra": expected}
  state = sessions.SessionEventTracker(run_id="a" * 32, emitter_epoch="epoch-current",
    manager_identity=manager)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="session-sealed"))
  observation = replace(release(), manager_identity={**manager, "extra": observed})
  assert state.record_release(observation) is False
  assert state.snapshot()["process_exit_proven"] is False
  assert state.snapshot()["final"] is None


@pytest.mark.parametrize("value", [1, True, 1.0])
def test_extended_manager_identity_accepts_fully_matching_extra_fields(sessions, value):
  from dataclasses import replace
  manager = {"pid": 1234, "birth_id": "synthetic-birth", "extra": value}
  state = sessions.SessionEventTracker(run_id="a" * 32, emitter_epoch="epoch-current",
    manager_identity=manager)
  state.accept(event(sessions, 1))
  state.accept(event(sessions, 2, kind="session-sealed"))
  assert state.record_release(replace(release(), manager_identity=dict(manager))) is True
  assert state.snapshot()["process_exit_proven"] is True
  assert state.snapshot()["final"].native_ref == "session-a"
