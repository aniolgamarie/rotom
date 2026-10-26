"""manual 停止接受快照纯 codec；不授权控制，不读取任何目标。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg import maintenance as codec, run_owners
from agentcfg.storage import Conflict
from test_rotom_known_sessions import saved
from test_rotom_maintenance_plan import RUNS, DOMAIN, scope, snapshots


BATCH = "8" * 32


def digest(value):
  return hashlib.sha256(run_owners._encode(value)).hexdigest()


@pytest.fixture
def source(saved):
  _, template = saved
  runs, resources = snapshots()
  records = {}
  for index, run in enumerate(runs):
    record = deepcopy(template)
    selected = run["scope"]
    manager = deepcopy(run["observation"]["manager_identity"])
    host = {"identity": deepcopy(run["observation"]["host_identity"]),
      "manager_identity": deepcopy(manager), "source": "synthetic-host-report", "relationship": "reported-by-current-run"}
    record.update(run_id=run["run_id"], agent="omp", profile=selected["profile"],
      manager_identity=manager, host_identity=host,
      machine_ref={key: selected[key] for key in ("machine", "local")},
      coordination_domain={"protocol": "rotom-owner-link-v1", "domain_id": DOMAIN,
        "domain_physical": {"device": 4, "inode": 5}, "op_id": "9" * 32, "link_digest": "a" * 64})
    record["binding_digest"] = run_owners.Registry(Path("/run-owners"),
      {**record["machine_ref"], "profile": record["profile"]}).binding_digest
    record["native_home_ref"].update(kind="omp-managed-home", path="/synthetic/native-home/" + str(index))
    record["process_observation"].update(manager_identity=deepcopy(manager), host_identity=deepcopy(host))
    record["start_cwd"]["path"] = "/synthetic/start-cwd/" + str(index)
    if index == 0:
      record.update(session_observation=None, session_cwd=None)
    else:
      record["session_cwd"].update(path="/synthetic/session-cwd/" + str(index), confirmation="historical")
      record["session_observation"].update(run_id=run["run_id"], confirmation="historical")
      record["session_observation"]["session"].update(agent="omp",
        native_home_ref=run_owners.native_home_key(record["native_home_ref"]))
    run["observation"]["record_digest"] = digest(record)
    run["deployment_digest"] = digest(record["deployed_identity"])
    records[run["run_id"]] = record
  plan = codec.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  return plan, {key: records[key] for key in RUNS[:2]}, runs, resources, records


def build(source, **changes):
  plan, records, *_ = source
  return codec.build_stop_acceptance(**{"batch_id": BATCH, "plan": plan, "records": records, "expected_revision": 7, **changes})


def reject(value):
  for action in (lambda: codec.encode_stop_acceptance(value),
      lambda: codec.decode_stop_acceptance(json.dumps(value).encode())):
    with pytest.raises(Conflict) as caught:
      action()
    assert str(caught.value) == "维护计划或批次数据无效"


def test_two_selected_of_three_keep_complete_records_without_absorbing_third(source):
  value = build(source)
  assert set(value) == {"schema_version", "kind", "protocol", "domain_id", "domain_physical", "expected_revision", "batch", "records"}
  assert value["schema_version"] == 1 and value["kind"] == "stop-acceptance"
  assert value["domain_id"] == DOMAIN and value["domain_physical"] == {"device": 4, "inode": 5}
  assert value["expected_revision"] == 7 and value["protocol"] == "rotom-maintenance-v1"
  assert set(value["records"]) == set(RUNS[:2]) and value["records"] == source[1]
  assert RUNS[2] not in value["batch"]["accepted_runs"]
  assert RUNS[2] in next(r for r in value["batch"]["plan"]["resources"] if r["key"]["kind"] == "runtime")["reference_runs"]


def test_initial_batch_has_no_stop_release_restore_or_dispatch_fact(source):
  batch = build(source)["batch"]
  assert batch["batch_id"] == BATCH and batch["revision"] == 0 and batch["phase"] == "accepted"
  assert batch["maintenance_dispatch"] == {"state": "not_dispatched", "dispatch_id": None}
  assert batch["operation_result"] is None and batch["review_required"] is False
  for item in batch["items"]:
    assert item["stop_phase"] == "accepted" and item["restore_phase"] == "not_requested"
    assert set(item["facts"]) == {"stop_requested", "exit_confirmed", "resources_released", "session_sealed"}
    assert all(fact is False for fact in item["facts"].values())
    assert item["launch_dispatch"] == {"state": "not_dispatched", "dispatch_id": None, "new_run_id": None}


def test_roundtrip_is_canonical_detached_and_preserves_null_historical_cwd_deployment(source):
  before = deepcopy(source)
  value = build(source)
  raw = codec.encode_stop_acceptance(value)
  assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
  decoded = codec.decode_stop_acceptance(raw)
  assert codec.encode_stop_acceptance(decoded) == raw and source == before
  assert decoded["records"][RUNS[0]]["session_observation"] is None
  assert decoded["records"][RUNS[0]]["session_cwd"] is None
  second = decoded["records"][RUNS[1]]
  assert second["session_cwd"]["path"] != second["start_cwd"]["path"]
  assert second["session_observation"]["confirmation"] == "historical"
  assert second["session_cwd"]["confirmation"] == "historical"
  assert second["deployed_identity"] == source[1][RUNS[1]]["deployed_identity"]
  decoded["records"][RUNS[0]]["manager_identity"]["birth_id"] = "caller-change"
  assert value["records"] == source[1] and source == before


@pytest.mark.parametrize("revision", [0, 2 ** 64 - 2])
def test_expected_revision_boundaries(source, revision):
  assert build(source, expected_revision=revision)["expected_revision"] == revision


@pytest.mark.parametrize("field,bad", [("schema_version", True), ("schema_version", 2), ("kind", "other"),
  ("protocol", "future"), ("domain_id", "f" * 32), ("domain_physical", {"device": 4, "inode": 6}),
  ("expected_revision", True), ("expected_revision", -1), ("expected_revision", 2 ** 64 - 1), ("expected_revision", 1.0)])
def test_envelope_tampering_fails(source, field, bad):
  value = build(source)
  value[field] = bad
  reject(value)


@pytest.mark.parametrize("field", ["revision", "phase", "operation", "accepted_runs", "plan", "stop_phase", "restore_phase",
  "stop_requested", "exit_confirmed", "resources_released", "session_sealed", "maintenance_dispatch", "launch_dispatch", "operation_result", "review_required"])
def test_only_exact_initial_batch_is_accepted(source, field):
  value = build(source)
  batch = value["batch"]
  if field == "revision": batch[field] = 1
  elif field == "phase": batch[field] = "stop_requested"
  elif field == "operation": batch[field] = "setup"
  elif field == "accepted_runs": batch[field].pop()
  elif field == "plan": batch[field]["runs"][0]["observation"]["record_digest"] = "0" * 64
  elif field == "stop_phase": batch["items"][0][field] = "unknown"
  elif field == "restore_phase": batch["items"][0][field] = "manual"
  elif field in batch["items"][0]["facts"]: batch["items"][0]["facts"][field] = True
  elif field == "maintenance_dispatch": batch[field] = {"state": "dispatch_intent", "dispatch_id": "7" * 32}
  elif field == "launch_dispatch": batch["items"][0][field] = {"state": "dispatch_intent", "dispatch_id": "7" * 32, "new_run_id": "f" * 32}
  elif field == "operation_result": batch[field] = {"operation": "setup", "status": "unknown", "exit_code": None, "result_digest": None}
  else: batch[field] = True
  reject(value)


@pytest.mark.parametrize("damage", ["missing", "extra", "v1", "unknown", "owner-field", "manager-extra", "host-extra", "deployment", "session-cwd", "coordination"])
def test_record_set_and_full_owner_digest_are_bound(source, damage):
  value = build(source)
  records = value["records"]
  record = records[RUNS[0]]
  if damage == "missing": del records[RUNS[0]]
  elif damage == "extra": records[RUNS[2]] = source[4][RUNS[2]]
  elif damage == "v1": record["schema_version"] = 1
  elif damage == "unknown": record["lifecycle_state"] = "unknown"
  elif damage == "owner-field": record["unexpected"] = "synthetic-private-canary"
  elif damage == "manager-extra": record["manager_identity"]["synthetic_extra"] = True
  elif damage == "host-extra": record["host_identity"]["identity"]["synthetic_extra"] = True
  elif damage == "deployment": record["deployed_identity"]["runtime"] = "0" * 64
  elif damage == "session-cwd": record["session_cwd"] = deepcopy(source[1][RUNS[1]]["session_cwd"])
  else: record["coordination_domain"]["domain_physical"]["inode"] += 1
  reject(value)


@pytest.mark.parametrize("damage", ["scope", "deployment-digest", "manager", "host", "host-null", "domain", "inactive"])
def test_even_rehashed_records_must_match_plan_scope_observation_and_domain(source, damage):
  plan, records, runs, resources, _ = deepcopy(source)
  record = records[RUNS[0]]
  if damage == "scope":
    record["profile"] = "different-profile"
    record["binding_digest"] = run_owners.Registry(Path("/run-owners"), {**record["machine_ref"], "profile": record["profile"]}).binding_digest
  elif damage == "deployment-digest": record["deployed_identity"]["runtime"] = "0" * 64
  elif damage == "manager":
    record["manager_identity"]["birth_id"] = "new-manager-birth"
    record["host_identity"]["manager_identity"] = deepcopy(record["manager_identity"])
    record["process_observation"]["manager_identity"] = deepcopy(record["manager_identity"])
    record["process_observation"]["host_identity"] = deepcopy(record["host_identity"])
  elif damage == "host":
    record["host_identity"]["identity"]["birth_id"] = "new-host-birth"
    record["process_observation"]["host_identity"] = deepcopy(record["host_identity"])
  elif damage == "host-null": record["host_identity"] = record["process_observation"]["host_identity"] = None
  elif damage == "inactive":
    record["lifecycle_state"] = "unknown"
    record["process_observation"].update(kind="manager_scope_ended", source="manager-scope-end")
  else: record["coordination_domain"]["domain_id"] = "0" * 32
  runs[0]["observation"]["record_digest"] = digest(record)
  changed = codec.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  with pytest.raises(Conflict):
    build(source, plan=changed, records=records)


@pytest.mark.parametrize("mode", ["original", "new-location"])
def test_ready_nonmanual_plan_is_outside_acceptance_candidate(source, mode):
  _, records, runs, resources, _ = deepcopy(source)
  runs[0]["restore"] = {"mode": mode, "capability": "supported", "session_status": "sealed", "target_digest": "f" * 64}
  plan = codec.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  assert plan["readiness"] == "ready"
  with pytest.raises(Conflict): build(source, plan=plan, records=records)


def test_blocked_plan_does_not_become_acceptance(source):
  _, _, runs, resources, _ = source
  blocked = codec.build_stop_plan(scope=scope(), operation="setup", selected_runs=RUNS[:2], runs=runs, resources=resources)
  with pytest.raises(Conflict): build(source, plan=blocked)


@pytest.mark.parametrize("raw", [b'{"schema_version":1,"schema_version":1}', b'{"x":NaN}', b'{"x":1.0}', b'\xff', b'{}', b'[]', 'not-bytes', b' ' * (2 * 1024 * 1024 + 1)])
def test_untrusted_json_fails_closed(raw):
  with pytest.raises(Conflict): codec.decode_stop_acceptance(raw)


def test_cycles_oversize_and_unknown_envelope_fields_fail_closed(source):
  for name in ("unexpected", "cycle", "too-big"):
    value = build(source)
    if name == "cycle": value["records"][RUNS[0]]["manager_identity"]["cycle"] = value
    elif name == "too-big": value["extra"] = "x" * 65537
    else: value["unexpected"] = True
    with pytest.raises(Conflict): codec.encode_stop_acceptance(value)


def test_no_target_io_clock_or_random_and_control_exceptions_propagate(source, monkeypatch):
  def forbidden(*args, **kwargs): pytest.fail("target IO is forbidden")
  monkeypatch.setattr(run_owners.Registry, "_locked", forbidden)
  monkeypatch.setattr(run_owners.Tree, "__init__", forbidden)
  with monkeypatch.context() as patch:
    patch.setattr(run_owners.time, "time_ns", forbidden)
    patch.setattr(run_owners.uuid, "uuid4", forbidden)
    value = build(source)
    assert codec.decode_stop_acceptance(codec.encode_stop_acceptance(value)) == value
  for error_type in (KeyboardInterrupt, SystemExit):
    error = error_type("synthetic-control")
    def interrupted(*args): raise error
    with monkeypatch.context() as patch:
      patch.setattr(run_owners.Registry, "_validate_record", interrupted)
      with pytest.raises(error_type) as caught: build(source)
      assert caught.value is error


@pytest.mark.parametrize("batch_id", [None, True, "bad", "A" * 32, "8" * 31, "8" * 32 + "\n"])
def test_batch_identity_is_supplied_strictly_never_generated(source, batch_id):
  with pytest.raises(Conflict): build(source, batch_id=batch_id)


def test_null_coordination_is_preserved_without_inventing_a_link(source):
  _, records, runs, resources, _ = deepcopy(source)
  records[RUNS[0]]["coordination_domain"] = None
  runs[0]["observation"]["record_digest"] = digest(records[RUNS[0]])
  plan = codec.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  value = build(source, plan=plan, records=records)
  decoded = codec.decode_stop_acceptance(codec.encode_stop_acceptance(value))
  assert decoded["records"][RUNS[0]]["coordination_domain"] is None
  assert decoded["records"][RUNS[0]]["session_cwd"] is None


def test_ready_manual_setup_initial_batch_binds_exact_full_selection(source):
  _, _, runs, resources, records = source
  plan = codec.build_stop_plan(scope=scope(), operation="setup", selected_runs=RUNS, runs=runs, resources=resources)
  value = build(source, plan=plan, records=records)
  assert value["batch"]["operation"] == "setup" and value["batch"]["phase"] == "accepted"
  assert value["batch"]["accepted_runs"] == RUNS and set(value["records"]) == set(RUNS)


def test_reordering_input_lists_and_record_mapping_has_identical_canonical_bytes(source):
  value = build(source)
  first = codec.encode_stop_acceptance(value)
  value["records"] = dict(reversed(list(value["records"].items())))
  value["batch"]["items"].reverse()
  value["batch"]["accepted_runs"].reverse()
  value["batch"]["plan"]["runs"].reverse()
  value["batch"]["plan"]["resources"].reverse()
  assert codec.encode_stop_acceptance(value) == first


def test_build_bounds_complete_envelope_not_only_input_fields(source, monkeypatch):
  plan, records, *_ = source
  supplied = {"batch_id": BATCH, "plan": plan, "records": records, "expected_revision": 7}
  limit = len(codec._dump(supplied)) + 1
  monkeypatch.setattr(codec, "_MAX_BYTES", limit)
  with pytest.raises(Conflict):
    build(source)
