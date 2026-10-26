"""维护计划/批次严格数据codec；格式不授予现场证明或执行许可。"""

from copy import deepcopy
import json

import pytest

from agentcfg import maintenance
from agentcfg.storage import Conflict
from test_rotom_maintenance_plan import RUNS, plan, scope, snapshots


PHASES = ("accepted", "stop_requested", "stopped_confirmed", "maintenance_dispatch_intent",
  "maintenance_running", "maintenance_succeeded", "restore_pending", "launch_dispatched", "restored", "failed", "partial", "unknown")


def batch(phase="accepted", *, operation="stop_only"):
  runs, resources = snapshots()
  restoring = phase in ("restore_pending", "launch_dispatched", "restored")
  if restoring:
    for run in runs:
      run["restore"] = {"mode": "new-location", "capability": "supported", "session_status": "sealed", "target_digest": "5" * 64}
  chosen = RUNS if operation == "setup" else RUNS[:2]
  original = maintenance.build_stop_plan(scope=scope(), operation=operation, selected_runs=chosen, runs=runs, resources=resources)
  items = [{"run_id": run, "stop_phase": "accepted", "restore_phase": "not_requested",
    "facts": {"stop_requested": False, "exit_confirmed": False, "resources_released": False, "session_sealed": restoring},
    "launch_dispatch": {"state": "not_dispatched", "dispatch_id": None, "new_run_id": None}} for run in chosen]
  value = {"schema_version": 1, "kind": "maintenance-batch", "protocol": "rotom-maintenance-v1",
    "batch_id": "6" * 32, "revision": 0, "plan": original, "operation": operation,
    "accepted_runs": list(chosen), "phase": phase, "items": items,
    "maintenance_dispatch": {"state": "not_dispatched", "dispatch_id": None}, "operation_result": None,
    "review_required": phase in ("failed", "partial", "unknown")}
  if phase == "stop_requested":
    for item in items:
      item["stop_phase"] = "stop_requested"; item["facts"]["stop_requested"] = True
  elif phase in ("failed", "partial", "unknown"):
    items[0]["stop_phase"] = "failed" if phase == "failed" else "unknown"
  elif phase != "accepted":
    for item in items:
      item["stop_phase"] = "stopped_confirmed"
      item["facts"].update(stop_requested=True, exit_confirmed=True, resources_released=True)
  if phase.startswith("maintenance_") or operation == "setup" and restoring:
    state = {"maintenance_dispatch_intent": "dispatch_intent", "maintenance_running": "dispatched"}.get(phase, "confirmed")
    value["maintenance_dispatch"] = {"state": state, "dispatch_id": "7" * 32}
    if state == "confirmed":
      value["operation_result"] = {"operation": "setup", "status": "succeeded", "exit_code": 0, "result_digest": "8" * 64}
  if restoring:
    for index, item in enumerate(items):
      item["restore_phase"] = phase
      if phase != "restore_pending":
        item["launch_dispatch"] = {"state": "confirmed" if phase == "restored" else "dispatched",
          "dispatch_id": format(100 + index, "032x"), "new_run_id": format(200 + index, "032x")}
  return value


def reject(value, *, kind="batch"):
  encode = maintenance.encode_batch if kind == "batch" else maintenance.encode_stop_plan
  decode = maintenance.decode_batch if kind == "batch" else maintenance.decode_stop_plan
  for call in (lambda: encode(value), lambda: decode(json.dumps(value).encode())):
    with pytest.raises(Conflict) as caught:
      call()
    assert str(caught.value) == "维护计划或批次数据无效"
    assert caught.value.__cause__ is None


@pytest.mark.parametrize("phase", PHASES)
def test_all_declared_batch_stages_have_strict_roundtrip_representation(phase):
  operation = "setup" if phase.startswith("maintenance_") else "stop_only"
  value = batch(phase, operation=operation); before = deepcopy(value)
  raw = maintenance.encode_batch(value)
  assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
  decoded = maintenance.decode_batch(raw)
  assert maintenance.encode_batch(decoded) == raw and value == before
  decoded["items"][0]["facts"]["session_sealed"] = not value["items"][0]["facts"]["session_sealed"]
  assert value == before


def test_plan_codec_is_canonical_rechecks_digest_and_does_not_share_mutables():
  value = plan(); raw = maintenance.encode_stop_plan(value)
  decoded = maintenance.decode_stop_plan(raw)
  assert decoded == value and decoded is not value
  decoded["runs"][0]["scope"]["profile"] = "mutated"
  assert decoded != value
  value["runs"][0]["observation"]["host_identity"]["birth_id"] = "forged-control-target"
  reject(value, kind="plan")


def test_batch_arrays_are_sorted_without_changing_original():
  value = batch(); before = deepcopy(value)
  raw = maintenance.encode_batch(value)
  value["items"].reverse(); value["accepted_runs"].reverse()
  assert maintenance.encode_batch(value) == raw
  assert before["items"][0]["run_id"] != value["items"][0]["run_id"]


@pytest.mark.parametrize("kind", ["plan", "batch"])
@pytest.mark.parametrize("raw", [b'{"schema_version":1,"schema_version":1}', b'NaN', b'Infinity', b'-Infinity', b'1.5', b'\xff', b'{}', b'[]'])
def test_unsafe_or_wrong_shape_json_is_rejected(kind, raw):
  decode = maintenance.decode_stop_plan if kind == "plan" else maintenance.decode_batch
  with pytest.raises(Conflict, match="^维护计划或批次数据无效$"):
    decode(raw)


@pytest.mark.parametrize("path", [(), ("plan",), ("items", 0), ("items", 0, "facts"), ("maintenance_dispatch",), ("plan", "runs", 0, "restore"), ("plan", "resources", 0, "key")])
def test_unknown_fields_are_refused_without_echoing_private_values(path):
  value = batch(); current = value
  for key in path: current = current[key]
  current["unknown"] = "synthetic-secret-must-not-echo"
  reject(value)


@pytest.mark.parametrize("field,bad", [("schema_version", True), ("schema_version", 2), ("revision", True), ("revision", -1), ("revision", 1.0), ("review_required", 1)])
def test_batch_exact_types_and_versions(field, bad):
  value = batch(); value[field] = bad; reject(value)


@pytest.mark.parametrize("path,bad", [(("schema_version",), True), (("resources", 0, "generation"), True),
  (("resources", 0, "key", "device"), 1.0), (("resources", 0, "key", "inode"), False),
  (("scope", "local"), "/a/../b"), (("scope", "machine"), "bad\n"),
  (("resources", 0, "key", "key_id"), "0" * 64), (("plan_id",), "0" * 64)])
def test_plan_types_paths_physical_and_plan_digests_are_strict(path, bad):
  value = plan(); current = value
  for key in path[:-1]: current = current[key]
  current[path[-1]] = bad; reject(value, kind="plan")


@pytest.mark.parametrize("damage", ["accepted-set", "duplicate-accepted", "duplicate-item", "wrong-item", "operation", "blocked-plan", "missing-stop-proof", "claimed-restored", "dispatch-without-id", "id-without-dispatch"])
def test_batch_scope_and_fact_cross_references_are_checked(damage):
  value = batch()
  if damage == "accepted-set": value["accepted_runs"] = [RUNS[0]]
  elif damage == "duplicate-accepted": value["accepted_runs"].append(RUNS[0])
  elif damage == "duplicate-item": value["items"].append(deepcopy(value["items"][0]))
  elif damage == "wrong-item": value["items"][0]["run_id"] = RUNS[2]
  elif damage == "operation": value["operation"] = "setup"
  elif damage == "blocked-plan":
    value["plan"] = plan(operation="setup"); value["operation"] = "setup"
  elif damage == "missing-stop-proof":
    value = batch("stopped_confirmed"); value["items"][0]["facts"]["resources_released"] = False
  elif damage == "claimed-restored": value["phase"] = "restored"
  elif damage == "dispatch-without-id": value["maintenance_dispatch"]["state"] = "dispatch_intent"
  else: value["maintenance_dispatch"]["dispatch_id"] = "7" * 32
  reject(value)


@pytest.mark.parametrize("bad", [True, 1.5, float("nan"), float("inf"), -1, "a" * 31, "A" * 32, "a" * 32 + "\n"])
def test_batch_id_requires_random_id_format_not_other_json_types(bad):
  value = batch(); value["batch_id"] = bad; reject(value)


def test_stop_only_never_carries_setup_dispatch_or_result():
  value = batch("maintenance_succeeded", operation="setup")
  value["operation"] = value["plan"]["operation"] = "stop_only"
  reject(value)
  value = batch(); value["operation_result"] = {"operation": "setup", "status": "unknown", "exit_code": None, "result_digest": None}
  reject(value)


def test_unknown_item_cannot_be_hidden_by_global_operation_success():
  value = batch("maintenance_succeeded", operation="setup")
  value["items"][0]["restore_phase"] = "unknown"
  reject(value)
  value.update(phase="unknown", review_required=True)
  decoded = maintenance.decode_batch(maintenance.encode_batch(value))
  assert decoded["operation_result"]["status"] == "succeeded"
  assert decoded["items"][0]["restore_phase"] == "unknown"


def test_possible_dispatch_without_confirmation_keeps_unknown_and_review():
  value = batch("stopped_confirmed", operation="setup")
  value.update(phase="unknown", review_required=True,
    maintenance_dispatch={"state": "unknown", "dispatch_id": "7" * 32},
    operation_result={"operation": "setup", "status": "unknown", "exit_code": None, "result_digest": None})
  assert maintenance.decode_batch(maintenance.encode_batch(value))["phase"] == "unknown"
  value["review_required"] = False; reject(value)


@pytest.mark.parametrize("damage", ["old-run", "shared-new-run", "reused-dispatch", "unsealed", "manual", "launch-without-dispatch", "mismatched-restore"])
def test_launch_audit_bindings_are_exact_and_do_not_inherit_old_run(damage):
  value = batch("launch_dispatched")
  if damage == "old-run": value["items"][0]["launch_dispatch"]["new_run_id"] = RUNS[0]
  elif damage == "shared-new-run": value["items"][1]["launch_dispatch"]["new_run_id"] = value["items"][0]["launch_dispatch"]["new_run_id"]
  elif damage == "reused-dispatch": value["items"][1]["launch_dispatch"]["dispatch_id"] = value["items"][0]["launch_dispatch"]["dispatch_id"]
  elif damage == "unsealed": value["items"][0]["facts"]["session_sealed"] = False
  elif damage == "manual":
    value["plan"] = plan()
  elif damage == "launch-without-dispatch": value["items"][0]["launch_dispatch"] = {"state": "not_dispatched", "dispatch_id": None, "new_run_id": None}
  else: value["items"][0]["restore_phase"] = "restored"
  reject(value)


def test_nonfinite_cyclic_deep_and_oversized_values_are_bounded():
  cyclic = {}; cyclic["cycle"] = cyclic
  deep = []; current = deep
  for _ in range(40):
    child = []; current.append(child); current = child
  for value in (cyclic, deep, {"synthetic": "x" * (2 * 1024 * 1024)}, {"synthetic": float("nan")}):
    with pytest.raises(Conflict): maintenance.encode_batch(value)
  with pytest.raises(Conflict): maintenance.decode_batch(b" " * (2 * 1024 * 1024 + 1))
  with pytest.raises(Conflict): maintenance.decode_stop_plan('{"bad":"\ud800"}'.encode('ascii',errors='backslashreplace'))


def test_no_execution_or_authority_fields_are_accepted():
  for field in ("permit", "argv", "input_text", "approved", "expires_at"):
    value = batch(); value[field] = "synthetic-secret-must-not-echo"; reject(value)


def test_confirmed_session_allows_ready_plan_but_does_not_prove_final_seal_for_launch():
  runs, resources = snapshots()
  for run in runs:
    run["restore"] = {"mode": "new-location", "capability": "supported", "session_status": "confirmed", "target_digest": "5" * 64}
  original = maintenance.build_stop_plan(scope=scope(), operation="stop_only", selected_runs=RUNS[:2], runs=runs, resources=resources)
  assert original["readiness"] == "ready"
  value = batch("launch_dispatched"); value["plan"] = original
  value["items"][0]["facts"]["session_sealed"] = False
  reject(value)


def test_cancelled_undispatched_setup_can_record_restore_under_original_contract():
  value = batch("launch_dispatched", operation="setup")
  value.update(maintenance_dispatch={"state": "not_dispatched", "dispatch_id": None}, operation_result=None)
  assert maintenance.decode_batch(maintenance.encode_batch(value))["phase"] == "launch_dispatched"
  value.update(phase="unknown", review_required=True)
  value["items"][0]["launch_dispatch"]["state"] = "unknown"
  value["items"][0]["restore_phase"] = "unknown"
  assert maintenance.decode_batch(maintenance.encode_batch(value))["items"][0]["launch_dispatch"]["state"] == "unknown"
  value["maintenance_dispatch"] = {"state": "unknown", "dispatch_id": "7" * 32}
  reject(value)


@pytest.mark.parametrize("state,phase", [("dispatch_intent", "stopped_confirmed"), ("dispatched", "stopped_confirmed"),
  ("confirmed", "stopped_confirmed"), ("confirmed", "maintenance_succeeded")])
def test_dispatched_maintenance_cannot_hide_under_early_or_success_phase_without_result(state, phase):
  value = batch("stopped_confirmed", operation="setup")
  value.update(phase=phase, maintenance_dispatch={"state": state, "dispatch_id": "7" * 32})
  reject(value)


def test_confirmed_dispatch_with_lost_result_is_only_explicit_unknown_review():
  value = batch("stopped_confirmed", operation="setup")
  value.update(phase="unknown", review_required=True, maintenance_dispatch={"state": "confirmed", "dispatch_id": "7" * 32})
  decoded = maintenance.decode_batch(maintenance.encode_batch(value))
  assert decoded["operation_result"] is None and decoded["maintenance_dispatch"]["state"] == "confirmed"


def test_natural_exit_can_be_confirmed_without_inventing_stop_request():
  value = batch("maintenance_succeeded", operation="setup")
  for item in value["items"]:
    item["facts"]["stop_requested"] = False
  decoded = maintenance.decode_batch(maintenance.encode_batch(value))
  assert all(item["facts"]["exit_confirmed"] and not item["facts"]["stop_requested"] for item in decoded["items"])


def test_shape_budget_rejects_large_python_container_before_expanding_stack():
  with pytest.raises(Conflict):
    maintenance.encode_batch([None] * (maintenance._MAX_NODES + 1))
  with pytest.raises(Conflict):
    maintenance.encode_stop_plan({"x" * 65537: "synthetic-private-value"})


@pytest.mark.parametrize("kind", ["plan", "batch"])
def test_duplicate_json_key_is_rejected_even_when_last_value_would_form_valid_record(kind):
  if kind == "plan":
    raw = maintenance.encode_stop_plan(plan())
    decode = maintenance.decode_stop_plan
  else:
    raw = maintenance.encode_batch(batch())
    decode = maintenance.decode_batch
  raw = raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1', 1)
  with pytest.raises(Conflict, match="^维护计划或批次数据无效$"):
    decode(raw)


def test_normal_maintenance_phase_requires_all_stop_phases_confirmed_but_unknown_retains_facts():
  value = batch("maintenance_running", operation="setup")
  value["items"][0]["stop_phase"] = "accepted"
  value["items"][0]["facts"]["stop_requested"] = False
  reject(value)
  value.update(phase="unknown", review_required=True)
  decoded = maintenance.decode_batch(maintenance.encode_batch(value))
  assert decoded["items"][0]["stop_phase"] == "accepted"
  assert decoded["items"][0]["facts"]["exit_confirmed"] is True
  assert decoded["maintenance_dispatch"]["state"] == "dispatched"
