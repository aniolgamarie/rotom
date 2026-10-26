"""完整集合摘要与选中人工恢复记录；不读取Registry/native目标。"""
from collections import UserDict
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg import run_owners as owners, run_stop_snapshot as codec
from agentcfg.storage import Conflict
from test_rotom_known_sessions import saved


RUNS = tuple(char * 32 for char in "abc")
BATCH, PLAN = "d" * 32, "e" * 64


def digest(value): return hashlib.sha256(owners._encode(value)).hexdigest()


@pytest.fixture
def source(saved):
  machine, template = saved
  binding = {**machine, "profile": template["profile"]}
  first = deepcopy(template); first.update(session_observation=None, session_cwd=None)
  second = deepcopy(template); second["run_id"] = RUNS[1]
  second["session_observation"].update(run_id=RUNS[1], confirmation="historical")
  second["session_cwd"]["confirmation"] = "historical"
  legacy = {"schema_version": 1, "binding_digest": template["binding_digest"], "run_id": RUNS[2],
    "manager_identity": deepcopy(template["manager_identity"]), "session_ref": None, "state": "unknown",
    "affected_resources": ["instance", "runtime", "native-home"],
    "observation": {"kind": "manager_scope_ended", "observed_at_ns": 3, "coverage": "unknown"}}
  return {"binding": binding, "registry_physical": {"device": 4, "inode": 5}, "batch_id": BATCH, "plan_id": PLAN,
    "expected_records": {RUNS[0]: first, RUNS[1]: second, RUNS[2]: legacy}, "selected_runs": list(reversed(RUNS[:2]))}


def build(source, **changes): return codec.build_snapshot(**{**source, **changes})


def reject(value):
  for action in (lambda: codec.encode_snapshot(value), lambda: codec.decode_snapshot(owners._encode(value))):
    with pytest.raises(Conflict) as caught: action()
    assert "synthetic-private-canary" not in str(caught.value)


def test_full_digest_but_only_selected_records_and_manual_unknowns_remain_unchanged(source, capsys):
  original = deepcopy(source); value = build(source)
  assert set(value) == {"schema_version", "kind", "binding", "binding_digest", "registry_physical", "batch_id", "plan_id",
    "records_digest", "selected_runs", "records", "restore_mode"}
  assert value["schema_version"] == 1 and value["kind"] == "run-stop-snapshot" and value["restore_mode"] == "manual"
  assert value["binding_digest"] == owners.Registry(Path("/run-owners"), source["binding"]).binding_digest
  assert value["records_digest"] == digest(source["expected_records"])
  assert value["selected_runs"] == list(RUNS[:2]) and set(value["records"]) == set(RUNS[:2])
  assert value["records"] == {run: source["expected_records"][run] for run in RUNS[:2]}
  first, second = value["records"].values()
  assert first["host_identity"] is None and first["session_cwd"] is None and first["session_observation"] is None
  assert second["session_cwd"]["path"] != second["start_cwd"]["path"]
  assert second["session_observation"]["confirmation"] == second["session_cwd"]["confirmation"] == "historical"
  assert source == original and capsys.readouterr() == ("", "")


def test_roundtrip_canonical_independent_and_full_unselected_change_affects_digest_only(source):
  value = build(source); raw = codec.encode_snapshot(value)
  assert raw == owners._encode(value)
  reversed_source = deepcopy(source); reversed_source["expected_records"] = dict(reversed(list(source["expected_records"].items())))
  assert codec.encode_snapshot(build(reversed_source, selected_runs=list(RUNS[:2]))) == raw
  decoded = codec.decode_snapshot(raw)
  decoded["records"][RUNS[0]]["manager_identity"]["birth_id"] = "caller-change"
  assert codec.decode_snapshot(raw) == value and value["records"][RUNS[0]] == source["expected_records"][RUNS[0]]
  source["expected_records"][RUNS[2]]["session_ref"] = "synthetic-old-reference"
  changed = build(source)
  assert changed["records"] == value["records"] and changed["records_digest"] != value["records_digest"]


@pytest.mark.parametrize("state", ["active", "unknown", "idle_confirmed"])
def test_unselected_legacy_states_are_valid_data_but_not_selected_restore_targets(source, state):
  legacy = source["expected_records"][RUNS[2]]; legacy["state"] = state
  kind, coverage = owners._OBSERVATIONS[state]
  legacy["observation"].update(kind=kind, coverage=coverage)
  assert RUNS[2] not in build(source)["records"]
  with pytest.raises(Conflict): build(source, selected_runs=[RUNS[2]])


@pytest.mark.parametrize("state", ["unknown", "idle_confirmed"])
def test_unselected_valid_v2_state_allowed_while_selected_state_rejects(source, state):
  other = deepcopy(source["expected_records"][RUNS[0]]); other["run_id"] = RUNS[2]
  other["lifecycle_state"] = state
  kind, coverage = owners._OBSERVATIONS[state]
  other["process_observation"].update(kind=kind, coverage=coverage, source=owners._SOURCES[state])
  source["expected_records"][RUNS[2]] = other
  assert build(source)["records_digest"] == digest(source["expected_records"])
  with pytest.raises(Conflict): build(source, selected_runs=[RUNS[2]])


@pytest.mark.parametrize("damage", ["binding-extra", "binding-missing", "binding-type", "physical-extra", "physical-bool", "physical-negative", "physical-zero", "batch", "plan", "records-empty", "records-type", "records-too-many", "key-mismatch", "bad-unselected", "foreign-binding", "selected-empty", "selected-duplicate", "selected-tuple", "selected-unknown", "selected-type", "selected-agent", "selected-backend", "selected-coordination"])
def test_build_validates_entire_expected_set_and_strict_inputs(source, damage):
  if damage == "binding-extra": source["binding"]["extra"] = "synthetic-private-canary"
  elif damage == "binding-missing": del source["binding"]["profile"]
  elif damage == "binding-type": source["binding"] = UserDict(source["binding"])
  elif damage == "physical-extra": source["registry_physical"]["extra"] = 0
  elif damage == "physical-bool": source["registry_physical"]["device"] = True
  elif damage == "physical-negative": source["registry_physical"]["device"] = -1
  elif damage == "physical-zero": source["registry_physical"]["inode"] = 0
  elif damage == "batch": source["batch_id"] = "D" * 32
  elif damage == "plan": source["plan_id"] = "e" * 63
  elif damage == "records-empty": source["expected_records"] = {}
  elif damage == "records-type": source["expected_records"] = UserDict(source["expected_records"])
  elif damage == "records-too-many": source["expected_records"] = {format(i, "032x"): {} for i in range(1025)}
  elif damage == "key-mismatch": source["expected_records"][RUNS[2]]["run_id"] = "f" * 32
  elif damage == "bad-unselected": source["expected_records"][RUNS[2]]["extra"] = "synthetic-private-canary"
  elif damage == "foreign-binding": source["expected_records"][RUNS[2]]["binding_digest"] = "0" * 64
  elif damage == "selected-empty": source["selected_runs"] = []
  elif damage == "selected-duplicate": source["selected_runs"] = [RUNS[0], RUNS[0]]
  elif damage == "selected-tuple": source["selected_runs"] = RUNS[:2]
  elif damage == "selected-unknown": source["selected_runs"] = ["f" * 32]
  elif damage == "selected-type": source["selected_runs"] = [True]
  elif damage == "selected-agent": source["expected_records"][RUNS[0]]["agent"] = "pi"
  elif damage == "selected-backend": source["expected_records"][RUNS[0]]["backend"] = "ssh"
  else: source["expected_records"][RUNS[0]]["coordination_domain"] = {"synthetic-private-canary": True}
  with pytest.raises(Conflict) as caught: build(source)
  assert "synthetic-private-canary" not in str(caught.value)


@pytest.mark.parametrize("field,value", [("schema_version", True), ("schema_version", 2), ("kind", "other"),
  ("binding_digest", "0" * 64), ("registry_physical", {"device": 0, "inode": True}),
  ("batch_id", "bad"), ("plan_id", "bad"), ("records_digest", "bad"), ("restore_mode", "automatic"),
  ("selected_runs", []), ("selected_runs", [RUNS[0], RUNS[0]])])
def test_strict_envelope_and_no_inferred_schema_extensions(source, field, value):
  snapshot = build(source); snapshot[field] = value; reject(snapshot)


@pytest.mark.parametrize("damage", ["extra", "missing", "record-extra", "missing-record", "extra-record", "v1", "unknown", "manager-bool", "float", "coordination"])
def test_records_and_envelope_tampering_reject(source, damage):
  value = build(source)
  if damage == "extra": value["permit"] = "synthetic-private-canary"
  elif damage == "missing": del value["restore_mode"]
  elif damage == "record-extra": value["records"][RUNS[0]]["extra"] = "synthetic-private-canary"
  elif damage == "missing-record": del value["records"][RUNS[0]]
  elif damage == "extra-record": value["records"][RUNS[2]] = source["expected_records"][RUNS[2]]
  elif damage == "v1": value["records"][RUNS[0]] = source["expected_records"][RUNS[2]]
  elif damage == "unknown": value["records"][RUNS[0]]["lifecycle_state"] = "unknown"
  elif damage == "manager-bool": value["records"][RUNS[0]]["manager_identity"]["pid"] = True
  elif damage == "float": value["registry_physical"]["device"] = 4.0
  else: value["records"][RUNS[0]]["coordination_domain"] = {"synthetic-private-canary": True}
  reject(value)


def test_decoder_only_checks_digest_shape_not_unknown_unselected_records(source):
  value = build(source); value["records_digest"] = "f" * 64
  assert codec.decode_snapshot(codec.encode_snapshot(value))["records_digest"] == "f" * 64
  assert set(value["records"]) != set(source["expected_records"])


@pytest.mark.parametrize("raw", [None, "{}", bytearray(b"{}"), b"\xef\xbb\xbf{}", b"\xff", b"[]", b"null", b"{}{}", b"NaN"])
def test_bad_raw_type_encoding_and_root_shape_fail(raw):
  with pytest.raises(Conflict): codec.decode_snapshot(raw)


@pytest.mark.parametrize("number", ["1.0", "1e0", "NaN", "Infinity"])
def test_float_nonfinite_and_duplicate_keys_fail(source, number):
  raw = owners._encode(build(source))
  with pytest.raises(Conflict): codec.decode_snapshot(raw.replace(b'"schema_version":1', b'"schema_version":' + number.encode(), 1))
  with pytest.raises(Conflict): codec.decode_snapshot(raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1))


def test_cycles_deep_shapes_and_oversized_raw_are_fixed_conflicts(source):
  value = build(source); value["records"][RUNS[0]]["synthetic-private-canary"] = value
  with pytest.raises(Conflict): codec.encode_snapshot(value)
  value = build(source)
  for _ in range(80): value = {"synthetic-private-canary": value}
  with pytest.raises(Conflict): codec.encode_snapshot(value)
  with pytest.raises(Conflict): codec.decode_snapshot(b" " * (16 * 1024 * 1024 + 1))


def test_validation_never_opens_registry_native_or_process_targets(source, monkeypatch):
  def forbidden(*args, **kwargs): pytest.fail("codec touched a live target")
  for name in ("_locked", "snapshot", "_records", "_prepare_v2"):
    monkeypatch.setattr(owners.Registry, name, forbidden)
  monkeypatch.setattr(owners, "Tree", forbidden)
  monkeypatch.setattr(owners, "current_process_identity", forbidden)
  monkeypatch.setattr(owners, "observed_process_identity", forbidden)
  value = build(source)
  assert codec.decode_snapshot(codec.encode_snapshot(value)) == value


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("operation", ["build", "encode", "decode"])
def test_control_exception_is_original(source, monkeypatch, kind, operation):
  value = build(source); raw = owners._encode(value); error = kind("synthetic-control")
  def interrupted(*args): raise error
  monkeypatch.setattr(owners.Registry, "_validate_record", interrupted)
  with pytest.raises(kind) as caught:
    if operation == "build": build(source)
    elif operation == "encode": codec.encode_snapshot(value)
    else: codec.decode_snapshot(raw)
  assert caught.value is error


def test_1024_valid_records_and_exact_16mib_envelope_boundary(source):
  value = build(source); template = deepcopy(value["records"][RUNS[0]])
  records = {}
  for number in range(1024):
    run = format(number, "032x"); record = deepcopy(template); record["run_id"] = run
    record["start_cwd"]["path"] = "/" + "x" * 8191
    records[run] = record
  value["records"], value["selected_runs"] = records, list(records)
  assert codec._MAX_BYTES == 16 * 1024 * 1024
  left = codec._MAX_BYTES - len(owners._encode(value))
  assert left > 0
  for record in records.values():
    room = 8192 - len(record["native_home_ref"]["path"])
    count = min(left, room)
    record["native_home_ref"]["path"] += "x" * count
    left -= count
  assert left == 0
  raw = codec.encode_snapshot(value)
  assert len(raw) == codec._MAX_BYTES and codec.decode_snapshot(raw) == value
  record = next(record for record in records.values() if len(record["native_home_ref"]["path"]) < 8192)
  record["native_home_ref"]["path"] += "x"
  with pytest.raises(Conflict): codec.encode_snapshot(value)
  with pytest.raises(Conflict): codec.decode_snapshot(owners._encode(value))


def test_oversized_unselected_input_still_bounded_without_target_access(source):
  source["expected_records"][RUNS[2]]["session_ref"] = "x" * codec._MAX_BYTES
  with pytest.raises(Conflict): build(source)


def test_alias_expansion_and_subclasses_cannot_bypass_shape_or_raw_types(source):
  class Mapping(dict): pass
  class Raw(bytes): pass
  value = build(source)
  with pytest.raises(Conflict): codec.encode_snapshot(Mapping(value))
  with pytest.raises(Conflict): codec.decode_snapshot(Raw(owners._encode(value)))
  nested = []
  for _ in range(21): nested = [nested, nested]
  value["synthetic-private-canary"] = nested
  with pytest.raises(Conflict): codec.encode_snapshot(value)
