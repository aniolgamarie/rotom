"""DSH v2 数据计划；不创建域，不访问现场或授予停止许可。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from agentcfg import dsh_stop_plan as codec, maintenance, run_owners, stop_review
from agentcfg.storage import Conflict
from test_rotom_maintenance_plan import RUNS, snapshots


@pytest.fixture
def source():
  scope = {"machine": "synthetic-machine", "local": "/synthetic/local.toml", "agent": "dsh", "profile": "dsh-default"}
  runs, old = snapshots()
  for run in runs: run["scope"] = deepcopy(scope)
  resources = [{k: deepcopy(r[k]) for k in ("resource_id", "key", "reference_runs", "coverage")} for r in old]
  binding = {k: scope[k] for k in ("machine", "local", "profile")}
  coordinator = {"kind": "dsh-instance-registry", "binding_digest": hashlib.sha256(run_owners._encode(binding)).hexdigest(),
    "registry_physical": {"device": 4, "inode": 5}, "records_digest": "f" * 64}
  return dict(scope=scope, operation="stop_only", selected_runs=list(reversed(RUNS[:2])), runs=runs,
    resources=resources, coordinator=coordinator, control_capability="supported")


def build(source, **changes): return codec.build(**(source | changes))


def test_canonical_v2_three_choose_two_manual_unknown_session(source):
  original = deepcopy(source); value = build(source)
  assert value["schema_version"] == 2 and value["kind"] == "stop-plan" and value["protocol"] == "rotom-maintenance-v2"
  assert value["selected_runs"] == RUNS[:2] and len(value["runs"]) == 2 and len(value["resources"]) == 5
  assert value["readiness"] == "ready" and value["blockers"] == []
  assert RUNS[2] in next(r for r in value["resources"] if r["key"]["kind"] == "runtime")["reference_runs"]
  assert all(set(r) == {"resource_id", "key", "reference_runs", "coverage"} for r in value["resources"])
  assert all(r["restore"]["session_status"] == "unknown" for r in value["runs"])
  assert source == original
  binding = {k: source["scope"][k] for k in ("machine", "local", "profile")}
  assert value["coordinator"]["binding_digest"] == run_owners.Registry(Path("/unused"), binding).binding_digest
  assert codec.normalize(value) == value
  reordered = deepcopy(source)
  reordered["runs"].reverse(); reordered["resources"].reverse(); reordered["selected_runs"].reverse()
  for r in reordered["resources"]: r["reference_runs"].reverse()
  for r in reordered["runs"]: r["resource_ids"].reverse()
  assert build(reordered) == value
  value["runs"][0]["scope"]["profile"] = "mutated"
  assert source == original


@pytest.mark.parametrize("change", ["manager", "host", "record", "deployment", "physical", "digest", "coverage", "capability", "selection", "operation", "scope", "restore"])
def test_changes_bind_new_hash_and_stale_hash_rejected(source, change):
  first = build(source)
  if change in ("manager", "host"):
    source["runs"][0]["observation"][change + "_identity"]["birth_id"] = "changed"
  elif change == "record": source["runs"][0]["observation"]["record_digest"] = "1" * 64
  elif change == "deployment": source["runs"][0]["deployment_digest"] = "2" * 64
  elif change == "physical": source["coordinator"]["registry_physical"]["inode"] += 1
  elif change == "digest": source["coordinator"]["records_digest"] = "3" * 64
  elif change == "coverage": source["resources"][0]["coverage"] = "unknown"
  elif change == "capability": source["control_capability"] = "unavailable"
  elif change == "selection": source["selected_runs"] = RUNS[:1]
  elif change == "scope":
    source["scope"]["machine"] = "other-machine"
    for run in source["runs"]: run["scope"] = deepcopy(source["scope"])
    binding = {k: source["scope"][k] for k in ("machine", "local", "profile")}
    source["coordinator"]["binding_digest"] = hashlib.sha256(run_owners._encode(binding)).hexdigest()
  elif change == "restore": source["runs"][0]["restore"]["session_status"] = "historical"
  else: source["operation"] = "setup"
  current = build(source)
  assert current["plan_id"] != first["plan_id"]
  current["plan_id"] = first["plan_id"]
  with pytest.raises(Conflict): codec.normalize(current)
  assert codec.normalize(current, verify=False)["plan_id"] != first["plan_id"]


@pytest.mark.parametrize("missing", ["manager_identity", "host_identity", "state"])
def test_missing_identity_or_unknown_observation_is_blocked(source, missing):
  if missing == "state": source["runs"][0]["observation"]["state"] = "unknown"
  else: source["runs"][0]["observation"][missing] = None
  assert build(source)["blockers"] == ["control-observation-unknown"]


def test_setup_and_capability_coverage_blockers(source):
  assert build(source, operation="setup")["blockers"] == ["unselected-run-reference"]
  source["resources"][0]["coverage"] = "unknown"
  value = build(source, control_capability="unavailable")
  assert value["readiness"] == "blocked" and value["blockers"] == ["stop-capability-unavailable"]


def test_exact_selected_stop_keeps_unknown_coverage_but_setup_requires_complete(source):
  for resource in source["resources"]: resource["coverage"] = "unknown"
  stopped = build(source)
  assert stopped["readiness"] == "ready" and stopped["blockers"] == []
  assert stopped["selected_runs"] == RUNS[:2]
  assert all(resource["coverage"] == "unknown" for resource in stopped["resources"])
  setup = build(source, operation="setup")
  assert setup["readiness"] == "blocked"
  assert setup["blockers"] == ["resource-coverage-unknown", "unselected-run-reference"]
  assert stopped["plan_id"] != setup["plan_id"]


@pytest.mark.parametrize("damage", ["scope-missing", "scope-extra", "scope-agent", "scope-profile", "scope-local", "run-scope",
  "binding", "physical-bool", "physical-float", "physical-range", "coordinator-extra", "coordinator-kind", "digest",
  "domain_id", "domain_physical", "generation", "duplicate-selection", "missing-selection", "duplicate-resource", "physical-alias",
  "missing-runtime", "reference", "restore", "same-pid", "capability"])
def test_strict_input_rejections(source, damage):
  if damage == "scope-missing": del source["scope"]["profile"]
  elif damage == "scope-extra": source["scope"]["extra"] = "private-canary"
  elif damage == "scope-agent": source["scope"]["agent"] = "omp"
  elif damage == "scope-profile": source["scope"]["profile"] = "../bad"
  elif damage == "scope-local": source["scope"]["local"] = "/synthetic/../other"
  elif damage == "run-scope": source["runs"][2]["scope"]["profile"] = "other"
  elif damage == "binding": source["coordinator"]["binding_digest"] = "0" * 64
  elif damage.startswith("physical-") and damage != "physical-alias":
    source["coordinator"]["registry_physical"]["device"] = {"physical-bool": True, "physical-float": 1.0, "physical-range": 2**64}[damage]
  elif damage == "coordinator-extra": source["coordinator"]["path"] = "private-canary"
  elif damage == "coordinator-kind": source["coordinator"]["kind"] = "domain"
  elif damage == "digest": source["coordinator"]["records_digest"] = "BAD"
  elif damage in ("domain_id", "domain_physical", "generation"):
    source["resources"][0][damage] = {"domain_id": "a" * 32, "domain_physical": {"device": 1, "inode": 2}, "generation": 1}[damage]
  elif damage == "duplicate-selection": source["selected_runs"] = [RUNS[0], RUNS[0]]
  elif damage == "missing-selection": source["selected_runs"] = ["9" * 32]
  elif damage == "duplicate-resource": source["resources"].append(deepcopy(source["resources"][0]))
  elif damage == "physical-alias": source["resources"][1]["key"] = deepcopy(source["resources"][0]["key"])
  elif damage == "missing-runtime": source["resources"][0]["key"]["kind"] = "instance"
  elif damage == "reference": source["resources"][0]["reference_runs"].remove(RUNS[0])
  elif damage == "restore": source["runs"][0]["restore"].update(mode="new-location", target_digest="0" * 64)
  elif damage == "same-pid": source["runs"][0]["observation"]["host_identity"]["pid"] = source["runs"][0]["observation"]["manager_identity"]["pid"]
  else: source["control_capability"] = "unknown"
  with pytest.raises(Conflict) as caught: build(source)
  assert "private-canary" not in str(caught.value)


@pytest.mark.parametrize("field,value", [("schema_version", 1), ("schema_version", True), ("protocol", "rotom-maintenance-v1"),
  ("extra", "private-canary"), ("readiness", "blocked"), ("blockers", ["stop-capability-unavailable"])])
def test_normalized_envelope_strict_and_no_silent_repair(source, field, value):
  plan = build(source); plan[field] = value
  with pytest.raises(Conflict): codec.normalize(plan)


def test_public_codec_and_single_use_review_v2(source):
  value = build(source)
  assert maintenance.decode_stop_plan(maintenance.encode_stop_plan(value)) == value
  assert maintenance.build_dsh_stop_plan(**source) == value
  options = dict(scope=value["scope"], operation=value["operation"], selected_runs=value["selected_runs"],
    plan_id=value["plan_id"], batch_id="a" * 32)
  for approved in (False, None, 1):
    with pytest.raises(Conflict): stop_review.review_stop_plan(value, **options, approve=lambda p: approved)
  seen = []
  def approve(plan):
    seen.append(deepcopy(plan)); plan.clear(); return True
  review = stop_review.review_stop_plan(value, **options, approve=approve)
  assert seen == [value]
  stop_review.consume_stop_review(review, plan=value, batch_id="a" * 32)
  with pytest.raises(Conflict): stop_review.consume_stop_review(review, plan=value, batch_id="a" * 32)


def test_v2_cannot_enter_v1_batch_or_acceptance(source):
  value = build(source)
  batch = maintenance._initial_batch("a" * 32, value)
  with pytest.raises(Conflict): maintenance.encode_batch(batch)
  acceptance = {"schema_version": 1, "kind": "stop-acceptance", "protocol": "rotom-maintenance-v1",
    "domain_id": "d" * 32, "domain_physical": {"device": 1, "inode": 2}, "expected_revision": 1,
    "batch": batch, "records": {RUNS[0]: {"schema_version": 2}}}
  with pytest.raises(Conflict): maintenance.encode_stop_acceptance(acceptance)


def test_no_target_io_and_control_exceptions_original(source, monkeypatch):
  def forbidden(*a, **kw): pytest.fail("pure plan must not access Registry targets")
  monkeypatch.setattr(run_owners.Registry, "_locked", forbidden)
  assert build(source)["readiness"] == "ready"
  for error in (KeyboardInterrupt(), SystemExit(7)):
    def fail(*a, **kw): raise error
    with monkeypatch.context() as patch:
      patch.setattr(maintenance, "_resource_catalog", fail)
      with pytest.raises(type(error)) as caught: build(source)
      assert caught.value is error


def test_schema_v2_is_distinct_and_old_batch_remains_v1(source):
  from jsonschema import Draft202012Validator
  schema = json.loads((Path(__file__).resolve().parents[1] / "schemas/rotom/maintenance.schema.json").read_bytes())
  value = build(source)
  assert Draft202012Validator(schema).is_valid(value)
  assert schema["$defs"]["batch"]["properties"]["plan"] == {"$ref": "#/$defs/stop-plan"}
  assert schema["$defs"]["stop-acceptance"]["properties"]["batch"] == {"$ref": "#/$defs/batch"}
  assert schema["$defs"]["stop-plan"]["properties"]["schema_version"]["const"] == 1
  assert schema["$defs"]["dsh-stop-plan"]["properties"]["schema_version"]["const"] == 2


def test_blocked_v2_not_reviewable_or_approved(source):
  value = build(source, control_capability="unavailable")
  calls = []
  with pytest.raises(Conflict):
    stop_review.review_stop_plan(value, scope=value["scope"], operation=value["operation"],
      selected_runs=value["selected_runs"], plan_id=value["plan_id"], batch_id="a" * 32,
      approve=lambda p: calls.append(p) or True)
  assert calls == []
