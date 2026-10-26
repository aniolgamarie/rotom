"""嵌入完整DSH v2计划的人工参考；无现场I/O或控制许可。"""
from copy import deepcopy
import hashlib
import json

import pytest

from agentcfg import dsh_stop_plan, maintenance, run_owners, run_stop_snapshot as codec
from agentcfg.resource_keys import ResourceKey
from agentcfg.storage import Conflict
from test_rotom_run_stop_snapshot import RUNS, source
from test_rotom_known_sessions import saved


def digest(value): return hashlib.sha256(run_owners._encode(value)).hexdigest()


def make_plan(data, *, capability="unavailable", coverage="unknown"):
  records = data["expected_records"]
  references = sorted(run for run, record in records.items() if run_owners.record_state(record) != "idle_confirmed")
  resources = [{"resource_id": str(index + 1) * 32, "key": ResourceKey(kind, 7, 100 + index).as_dict(),
    "reference_runs": references, "coverage": coverage} for index, kind in enumerate(("instance", "native-home", "runtime"))]
  scope = data["binding"] | {"agent": "dsh"}
  runs = []
  for run in data["selected_runs"]:
    record = records[run]; observation = record["session_observation"]
    runs.append({"run_id": run, "scope": deepcopy(scope), "observation": {"state": "active",
      "manager_identity": deepcopy(record["manager_identity"]),
      "host_identity": deepcopy(record["host_identity"]["identity"]) if record["host_identity"] else None,
      "record_digest": digest(record)}, "deployment_digest": digest(record["deployed_identity"]),
      "resource_ids": [r["resource_id"] for r in resources], "restore": {"mode": "manual", "capability": "unavailable",
        "session_status": "historical" if observation and observation["confirmation"] in ("confirmed", "historical") else "unknown",
        "target_digest": None}})
  coordinator = {"kind": "dsh-instance-registry", "binding_digest": digest(data["binding"]),
    "registry_physical": deepcopy(data["registry_physical"]), "records_digest": digest(records)}
  return dsh_stop_plan.build(scope=scope, operation="stop_only", selected_runs=data["selected_runs"],
    runs=runs, resources=resources, coordinator=coordinator, control_capability=capability)


@pytest.fixture
def data(source):
  return {key: deepcopy(source[key]) for key in ("binding", "registry_physical", "batch_id", "expected_records", "selected_runs")}


def build(data, plan=None, **changes):
  args = {k: v for k, v in data.items() if k != "selected_runs"}
  return codec.build_plan_snapshot(**(args | changes), plan=make_plan(data) if plan is None else plan)


def reject(value):
  for action in (lambda: codec.encode_snapshot(value), lambda: codec.decode_snapshot(run_owners._encode(value))):
    with pytest.raises(Conflict) as caught: action()
    assert "private-canary" not in str(caught.value)


def test_v2_roundtrip_detached_full_plan_blocked_unknown_facts(data):
  original = deepcopy(data); plan = make_plan(data); expected = deepcopy(plan)
  value = build(data, plan)
  assert value["schema_version"] == 2 and value["plan"] == expected
  assert value["plan_id"] == expected["plan_id"] and value["selected_runs"] == sorted(data["selected_runs"])
  assert value["records"] == {run: original["expected_records"][run] for run in sorted(data["selected_runs"])}
  assert value["plan"]["readiness"] == "blocked"
  assert value["records"][RUNS[0]]["host_identity"] is None
  assert value["records"][RUNS[0]]["session_observation"] is None and value["records"][RUNS[0]]["session_cwd"] is None
  raw = codec.encode_snapshot(value)
  assert raw == run_owners._encode(value) and codec.decode_snapshot(raw) == value
  plan.clear(); value["plan"]["runs"][0]["scope"]["machine"] = "external-change"
  assert codec.decode_snapshot(raw)["plan"] == expected and data == original


def test_v1_api_and_canonical_bytes_unchanged(data):
  args = data | {"plan_id": "e" * 64}
  value = codec.build_snapshot(**args)
  assert value["schema_version"] == 1 and "plan" not in value
  assert codec.encode_snapshot(value) == run_owners._encode(value)
  assert codec.decode_snapshot(codec.encode_snapshot(value)) == value


@pytest.mark.parametrize("change", ["scope", "binding", "physical", "records-digest", "plan-id", "selected",
  "record-digest", "deployment", "manager", "host", "state", "session"])
def test_all_plan_record_links_checked_even_with_recomputed_plan_id(data, change):
  value = build(data); plan = value["plan"]
  if change == "scope":
    plan["scope"]["machine"] = "other"
    for run in plan["runs"]: run["scope"]["machine"] = "other"
    plan["coordinator"]["binding_digest"] = digest({k: plan["scope"][k] for k in ("machine", "local", "profile")})
  elif change == "binding": value["binding_digest"] = "0" * 64
  elif change == "physical": plan["coordinator"]["registry_physical"]["inode"] += 1
  elif change == "records-digest": plan["coordinator"]["records_digest"] = "0" * 64
  elif change == "plan-id": value["plan_id"] = "0" * 64
  elif change == "selected": value["selected_runs"] = [RUNS[0]]; del value["records"][RUNS[1]]
  elif change == "record-digest": plan["runs"][0]["observation"]["record_digest"] = "0" * 64
  elif change == "deployment": plan["runs"][0]["deployment_digest"] = "0" * 64
  elif change == "manager": plan["runs"][0]["observation"]["manager_identity"]["birth_id"] = "other"
  elif change == "host": plan["runs"][0]["observation"]["host_identity"] = {"pid": 45678, "birth_id": "other"}
  elif change == "state": plan["runs"][0]["observation"]["state"] = "unknown"
  else: plan["runs"][0]["restore"]["session_status"] = "historical"
  for run in plan["runs"]: run["observation_digest"] = maintenance._digest(run["observation"])
  value["plan"] = dsh_stop_plan.normalize(plan, verify=False)
  if change != "plan-id": value["plan_id"] = value["plan"]["plan_id"]
  reject(value)


@pytest.mark.parametrize("change", ["deployment", "cwd", "manager", "host", "session"])
def test_record_drift_rejected_despite_valid_record_shape(data, change):
  value = build(data); record = value["records"][RUNS[0]]
  if change == "deployment": record["deployed_identity"]["deployment"] = "0" * 64
  elif change == "cwd": record["start_cwd"]["path"] = "/changed"
  elif change == "manager":
    record["manager_identity"]["birth_id"] = "changed"
    record["process_observation"]["manager_identity"]["birth_id"] = "changed"
  elif change == "host":
    host = {"identity": {"pid": 45678, "birth_id": "synthetic-host"}, "manager_identity": deepcopy(record["manager_identity"]),
      "source": "linux-spawn-pidfd", "relationship": "reported-by-current-run"}
    record["host_identity"] = deepcopy(host); record["process_observation"]["host_identity"] = host
  else: record["session_cwd"] = {"path": "/history", "source": "synthetic-event", "confirmation": "historical", "observed_at_ns": 2}
  reject(value)


@pytest.mark.parametrize("state", ["active", "unknown", "idle_confirmed"])
def test_builder_checks_all_nonidle_references_without_saving_third(data, state):
  third = data["expected_records"][RUNS[2]]
  run_owners._set_state(third, state)
  value = build(data)
  expected = sorted(data["selected_runs"] + ([RUNS[2]] if state != "idle_confirmed" else []))
  assert all(r["reference_runs"] == expected for r in value["plan"]["resources"])
  assert RUNS[2] not in value["records"]
  plan = make_plan(data)
  for resource in plan["resources"]:
    resource["reference_runs"] = sorted(data["selected_runs"]) if state != "idle_confirmed" else sorted(data["expected_records"])
  plan = dsh_stop_plan.normalize(plan, verify=False)
  with pytest.raises(Conflict): build(data, plan)


@pytest.mark.parametrize("confirmation,expected", [("confirmed", "historical"), ("historical", "historical"), ("unknown", "unknown")])
def test_session_confirmation_maps_only_to_history_or_unknown(data, confirmation, expected):
  record = data["expected_records"][RUNS[1]]
  record["session_observation"]["confirmation"] = confirmation
  record["session_cwd"]["confirmation"] = confirmation
  value = build(data)
  assert next(r for r in value["plan"]["runs"] if r["run_id"] == RUNS[1])["restore"]["session_status"] == expected
  assert value["records"][RUNS[1]] == record


@pytest.mark.parametrize("damage", ["v1-plan", "v1-with-plan", "v2-without-plan", "version", "extra", "float", "bool", "cycle"])
def test_strict_versions_and_shape(data, damage):
  value = build(data)
  if damage == "v1-plan": value["plan"]["schema_version"] = 1
  elif damage == "v1-with-plan": value["schema_version"] = 1
  elif damage == "v2-without-plan": del value["plan"]
  elif damage == "version": value["schema_version"] = 3
  elif damage == "extra": value["extra"] = "private-canary"
  elif damage == "float": value["registry_physical"]["device"] = 1.0
  elif damage == "bool": value["schema_version"] = True
  else:
    value["plan"]["loop"] = value
    with pytest.raises(Conflict): codec.encode_snapshot(value)
    return
  reject(value)


def test_json_duplicate_float_bom_and_total_size_boundary(data, monkeypatch):
  value = build(data); raw = codec.encode_snapshot(value)
  for damaged in (b'{' + b'"schema_version":2,' + raw[1:], b'\xef\xbb\xbf' + raw,
      raw.replace(b'"device":4', b'"device":4.0')):
    with pytest.raises(Conflict): codec.decode_snapshot(damaged)
  with monkeypatch.context() as patch:
    patch.setattr(codec, "_MAX_BYTES", len(raw))
    assert codec.encode_snapshot(value) == raw and codec.decode_snapshot(raw) == value
    patch.setattr(codec, "_MAX_BYTES", len(raw) - 1)
    with pytest.raises(Conflict): codec.encode_snapshot(value)
    with pytest.raises(Conflict): codec.decode_snapshot(raw)


def test_no_registry_io_or_permission_construction_and_controls(data, monkeypatch):
  def forbidden(*a, **kw): pytest.fail("pure snapshot must not read Registry or create permit")
  monkeypatch.setattr(run_owners.Registry, "_locked", forbidden)
  from agentcfg import stop_review
  monkeypatch.setattr(stop_review, "review_stop_plan", forbidden)
  assert build(data)["schema_version"] == 2
  for error in (KeyboardInterrupt(), SystemExit(7)):
    with monkeypatch.context() as patch:
      def fail(*a, **kw): raise error
      patch.setattr(maintenance, "encode_stop_plan", fail)
      with pytest.raises(type(error)) as caught: build(data)
      assert caught.value is error


def test_known_host_ready_plan_saved_without_issuing_authority(data):
  for run in data["selected_runs"]:
    record = data["expected_records"][run]
    host = {"identity": {"pid": 45678, "birth_id": "synthetic-host"},
      "manager_identity": deepcopy(record["manager_identity"]), "source": "linux-spawn-pidfd",
      "relationship": "reported-by-current-run"}
    record["host_identity"] = deepcopy(host)
    record["process_observation"]["host_identity"] = deepcopy(host)
  plan = make_plan(data, capability="supported", coverage="complete")
  assert plan["readiness"] == "ready"
  value = build(data, plan)
  assert codec.decode_snapshot(codec.encode_snapshot(value)) == value
  assert value["restore_mode"] == "manual" and value["records"][RUNS[0]]["session_cwd"] is None


@pytest.mark.parametrize("change", ["references", "full-digest"])
def test_reader_does_not_claim_unselected_full_set_validation_builder_does(data, change):
  value = build(data); plan = value["plan"]
  if change == "references":
    for resource in plan["resources"]: resource["reference_runs"].append("9" * 32)
  else:
    value["records_digest"] = "9" * 64
    plan["coordinator"]["records_digest"] = value["records_digest"]
  plan = dsh_stop_plan.normalize(plan, verify=False)
  value.update(plan=plan, plan_id=plan["plan_id"])
  # reader 无未选记录，保存规范历史参考；这不是现场匹配或完整集合证明。
  assert codec.decode_snapshot(codec.encode_snapshot(value)) == value
  with pytest.raises(Conflict): build(data, plan)


def test_proper_legacy_plan_is_not_upgraded_to_dsh_v2(data):
  from test_rotom_maintenance_plan import plan
  with pytest.raises(Conflict): build(data, plan())


def test_active_final_session_record_not_accepted_as_history(data):
  data["expected_records"][RUNS[1]]["session_observation"]["confirmation"] = "final"
  with pytest.raises(Conflict): build(data)
