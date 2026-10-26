"""只读计划快照；虚构身份不代表现场证明或控制授权。"""

from copy import deepcopy
import json

import pytest

from agentcfg import maintenance
from agentcfg.resource_keys import ResourceKey
from agentcfg.storage import Conflict


RUNS = [letter * 32 for letter in ("a", "b", "c")]
DOMAIN = "d" * 32


def scope():
  return {"machine": "synthetic-machine", "local": "/synthetic/local.toml"}


def snapshots():
  resources, runs = [], []
  runtime = "e" * 32
  resources.append({"resource_id": runtime, "domain_id": DOMAIN,
    "domain_physical": {"device": 4, "inode": 5}, "generation": 1,
    "key": ResourceKey("runtime", 7, 100).as_dict(), "reference_runs": list(RUNS), "coverage": "complete"})
  for index, run in enumerate(RUNS):
    ids = [runtime]
    for kind_index, kind in enumerate(("instance", "native-home")):
      rid = format(index * 2 + kind_index + 1, "032x")
      ids.append(rid)
      resources.append({"resource_id": rid, "domain_id": DOMAIN,
        "domain_physical": {"device": 4, "inode": 5}, "generation": 1,
        "key": ResourceKey(kind, 7, 200 + index * 2 + kind_index).as_dict(),
        "reference_runs": [run], "coverage": "complete"})
    runs.append({"run_id": run, "scope": {**scope(), "agent": "omp", "profile": "omp-" + str(index)},
      "observation": {"state": "active", "manager_identity": {"pid": 30000 + index, "birth_id": "synthetic-manager-" + str(index)},
        "host_identity": {"pid": 40000 + index, "birth_id": "synthetic-host-" + str(index)}, "record_digest": "f" * 64},
      "deployment_digest": "1" * 64, "resource_ids": ids,
      "restore": {"mode": "manual", "capability": "unknown", "session_status": "unknown", "target_digest": None}})
  return runs, resources


def plan(*, operation="stop_only", selected=None):
  runs, resources = snapshots()
  return maintenance.build_stop_plan(scope=scope(), operation=operation,
    selected_runs=RUNS[:2] if selected is None else selected, runs=runs, resources=resources)


def test_exact_two_selected_targets_do_not_implicitly_absorb_third_shared_run():
  value = plan()
  assert value["selected_runs"] == RUNS[:2]
  assert [item["run_id"] for item in value["runs"]] == RUNS[:2]
  assert len(value["resources"]) == 5
  assert value["readiness"] == "ready" and value["blockers"] == []
  assert RUNS[2] in next(item for item in value["resources"] if item["key"]["kind"] == "runtime")["reference_runs"]


def test_setup_is_blocked_by_unselected_shared_owner_without_expanding_targets():
  value = plan(operation="setup")
  assert value["selected_runs"] == RUNS[:2]
  assert value["readiness"] == "blocked" and value["blockers"] == ["unselected-run-reference"]


def test_canonical_order_and_independent_output_without_clock_or_randomness():
  runs, resources = snapshots()
  original = deepcopy((runs, resources))
  a = maintenance.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  for run in runs:
    run["resource_ids"].reverse()
  for resource in resources:
    resource["reference_runs"].reverse()
  b = maintenance.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=list(reversed(RUNS[:2])), runs=list(reversed(runs)), resources=list(reversed(resources)))
  assert maintenance.encode_stop_plan(a) == maintenance.encode_stop_plan(b)
  assert a["plan_id"] == b["plan_id"]
  b["runs"][0]["scope"]["profile"] = "caller-change"
  assert a["runs"][0]["scope"]["profile"] == original[0][0]["scope"]["profile"]
  assert runs[0]["scope"] == original[0][0]["scope"]
  assert a["resources"][0] is not resources[0]


@pytest.mark.parametrize("field", ["scope", "deployment", "manager", "host", "observation-record", "generation", "domain", "restore", "selection"])
def test_control_relevant_snapshot_changes_change_plan_digest(field):
  before = plan()["plan_id"]
  runs, resources = snapshots(); selected = list(RUNS[:2]); selected_scope = scope()
  if field == "scope":
    selected_scope["agent"] = "omp"
  elif field == "deployment":
    runs[0]["deployment_digest"] = "2" * 64
  elif field in ("manager", "host"):
    runs[0]["observation"][field + "_identity"]["birth_id"] = "synthetic-new-birth"
  elif field == "observation-record":
    runs[0]["observation"]["record_digest"] = "3" * 64
  elif field == "generation":
    resources[0]["generation"] = 2
  elif field == "domain":
    for resource in resources:
      resource["domain_id"] = "4" * 32
  elif field == "restore":
    runs[0]["restore"] = {"mode": "new-location", "capability": "supported", "session_status": "sealed", "target_digest": "5" * 64}
  else:
    selected = [RUNS[0], RUNS[2]]
  after = maintenance.build_stop_plan(scope=selected_scope, operation="stop_only", selected_runs=selected, runs=runs, resources=resources)
  assert after["plan_id"] != before


@pytest.mark.parametrize("operation", ["setup", "stop_only"])
def test_unknown_coverage_blocks_even_stop_only(operation):
  runs, resources = snapshots(); resources[0]["coverage"] = "unknown"
  value = maintenance.build_stop_plan(scope=scope(), operation=operation, selected_runs=RUNS[:2], runs=runs, resources=resources)
  assert value["readiness"] == "blocked" and "resource-coverage-unknown" in value["blockers"]


def test_manual_unsealed_is_explicit_but_unknown_original_location_is_not_satisfied():
  assert plan()["readiness"] == "ready"
  runs, resources = snapshots()
  runs[0]["restore"] = {"mode": "original", "capability": "unknown", "session_status": "unknown", "target_digest": "5" * 64}
  value = maintenance.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  assert value["readiness"] == "blocked"
  assert value["blockers"] == ["restore-capability-unavailable", "session-unsealed"]


def test_second_runtime_is_preserved_as_part_of_declared_resource_closure():
  runs, resources = snapshots()
  second = deepcopy(resources[0]); second.update(resource_id="9" * 32, key=ResourceKey("runtime", 7, 999).as_dict())
  resources.append(second)
  for run in runs:
    run["resource_ids"].append(second["resource_id"])
  value = maintenance.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  assert len(value["resources"]) == 6
  assert sum(resource["key"]["kind"] == "runtime" for resource in value["resources"]) == 2
  assert second["resource_id"] in value["runs"][0]["resource_ids"]


@pytest.mark.parametrize("damage", ["duplicate-selection", "empty-selection", "unknown-run", "duplicate-run", "duplicate-resource", "cross-domain", "domain-physical", "alias", "cross-kind-alias", "missing-resource", "missing-reference", "scope", "extra-field", "missing-home", "no-runtime"])
def test_invalid_selection_or_resource_closure_is_rejected(damage):
  runs, resources = snapshots(); selected = list(RUNS[:2]); wanted = scope()
  if damage == "duplicate-selection": selected.append(selected[0])
  elif damage == "empty-selection": selected = []
  elif damage == "unknown-run": selected = ["9" * 32]
  elif damage == "duplicate-run": runs.append(deepcopy(runs[0]))
  elif damage == "duplicate-resource": resources.append(deepcopy(resources[0]))
  elif damage == "cross-domain": resources[1]["domain_id"] = "9" * 32
  elif damage == "domain-physical": resources[1]["domain_physical"]["inode"] += 1
  elif damage == "alias": resources[1]["key"] = deepcopy(resources[0]["key"])
  elif damage == "cross-kind-alias": resources[1]["key"] = ResourceKey("instance", 7, 100).as_dict()
  elif damage == "missing-resource": resources.pop(1)
  elif damage == "missing-reference": resources[0]["reference_runs"].remove(RUNS[2])
  elif damage == "scope": wanted["profile"] = "omp-0"
  elif damage == "extra-field": runs[0]["untrusted"] = "synthetic-private-value"
  elif damage == "missing-home": runs[0]["resource_ids"].pop()
  else: runs[0]["resource_ids"].remove(resources[0]["resource_id"])
  with pytest.raises(Conflict, match="^维护计划或批次数据无效$"):
    maintenance.build_stop_plan(scope=wanted, operation="stop_only", selected_runs=selected, runs=runs, resources=resources)


def test_unknown_control_identity_is_blocked_not_inferred_from_other_run():
  runs, resources = snapshots(); runs[0]["observation"].update(state="unknown", host_identity=None)
  value = maintenance.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  assert value["blockers"] == ["control-observation-unknown"]


def test_builder_does_not_open_targets_create_state_or_change_input(tmp_path, monkeypatch):
  value = plan()
  runs, resources = snapshots(); before = deepcopy((runs, resources))
  before_paths = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
  # 先初始化仓库自有schema；计划函数不读取调用方scope所指的目标。
  def forbidden(*args, **kwargs):
    raise AssertionError("计划计算不得打开目标")
  with monkeypatch.context() as patch:
    patch.setattr(type(tmp_path), "open", forbidden)
    rebuilt = maintenance.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  assert rebuilt == value and (runs, resources) == before
  assert sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*")) == before_paths
