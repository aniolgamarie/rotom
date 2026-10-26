"""明确成功且转人工恢复的严格终态；保存历史不构造新的执行许可。"""
from copy import deepcopy
import json

import pytest

from agentcfg import maintenance, omp_observation, resource_protocol as protocol
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.resource_coordination import Domain
from agentcfg.storage import Conflict
from test_rotom_maintenance_execution import case, execute
from test_rotom_maintenance_recovery import BATCH, RUNS, ledger


@pytest.fixture
def completed(case):
  execute(case)
  state = case.domain.snapshot()
  intent = state["intents"][BATCH]
  intent["phase"] = "completed"
  for item in intent["progress"]["items"]:
    item["restore_phase"] = "manual"
  return case, state


def test_completed_roundtrip_preserves_complete_history(completed):
  case, state = completed
  before = deepcopy(state)
  restored = protocol.decode(protocol.encode(state), kind="domain")
  assert restored == before and state == before
  assert restored["reservations"] == case.domain.snapshot()["reservations"]
  assert restored["intents"][BATCH]["progress"]["operation_result"] == (
    case.domain.snapshot()["intents"][BATCH]["progress"]["operation_result"])


@pytest.mark.parametrize("damage", ["no-progress", "no-acceptance", "operation", "batch-phase",
  "review", "dispatch", "no-plan-digest", "no-target-digest", "no-result", "result-status",
  "result-code", "result-digest", "restore-phase", "restore-mode", "stop-phase", "exit-proof", "release-proof",
  "launch", "reservation", "receipt", "unknown-intent", "cancelled-intent"])
def test_completed_requires_all_success_and_manual_recovery_facts(completed, damage):
  _, state = completed
  intent = state["intents"][BATCH]
  batch = intent["progress"]
  item = batch["items"][0]
  if damage == "no-progress": intent.pop("progress")
  elif damage == "no-acceptance": intent.pop("acceptance_digest")
  elif damage == "operation": intent["operation"] = "stop_only"
  elif damage == "batch-phase": batch["phase"] = "partial"; batch["review_required"] = True
  elif damage == "review": batch["review_required"] = True
  elif damage == "dispatch": batch["maintenance_dispatch"]["state"] = "unknown"
  elif damage.startswith("no-") and damage.endswith("digest"):
    batch["maintenance_dispatch"].pop("setup_plan_digest" if damage == "no-plan-digest" else "target_deployment_digest")
  elif damage == "no-result": batch["operation_result"] = None
  elif damage.startswith("result-"):
    field, value = {"result-status": ("status", "partial"), "result-code": ("exit_code", 4),
      "result-digest": ("result_digest", None)}[damage]
    batch["operation_result"][field] = value
  elif damage == "restore-phase": item["restore_phase"] = "not_requested"
  elif damage == "restore-mode":
    plan = batch["plan"]
    runs = deepcopy(plan["runs"])
    for run in runs:
      run.pop("observation_digest")
    runs[0]["restore"] = {"mode": "new-location", "capability": "supported",
      "session_status": "sealed", "target_digest": "5" * 64}
    batch["plan"] = maintenance.build_stop_plan(scope=plan["scope"], operation="setup",
      selected_runs=batch["accepted_runs"], runs=runs, resources=plan["resources"])
    item["restore_phase"] = "not_requested"
    # 普通成功批次可尚未转人工；completed 不能把自动恢复计划当作人工完成。
    maintenance.encode_batch(batch)
  elif damage == "stop-phase": item["stop_phase"] = "stop_requested"
  elif damage == "exit-proof": item["facts"]["exit_confirmed"] = False
  elif damage == "release-proof": item["facts"]["resources_released"] = False
  elif damage == "launch": item["launch_dispatch"].update(state="dispatch_intent", dispatch_id="9" * 32)
  elif damage == "reservation": state["reservations"][RUNS[0]]["phase"] = "unknown"
  elif damage == "receipt": state["reservations"][RUNS[0]].pop("release_receipt")
  else: intent["phase"] = "unknown" if damage == "unknown-intent" else "cancelled"
  for call in (lambda: protocol.encode(state), lambda: protocol.decode(json.dumps(state).encode(), kind="domain")):
    with pytest.raises(Conflict, match="^共享资源协调记录无效$"): call()


def test_terminal_intent_set_is_explicit_and_immutable():
  assert protocol.TERMINAL_INTENT_PHASES == ("cancelled", "completed")


@pytest.mark.parametrize("phase", ["active", "dispatched", "unknown", "cancelled", "completed"])
@pytest.mark.parametrize("gate", ["idle", "unfenced"])
def test_ordinary_resource_gates_ignore_only_terminal_intents(phase, gate):
  resources = {"a" * 32}
  state = {"reservations": {}, "intents": {BATCH: {"phase": phase, "resources": list(resources)}}}
  check = Domain._idle if gate == "idle" else Domain._unfenced
  if phase in ("cancelled", "completed"):
    check(state, resources)
  else:
    with pytest.raises(Conflict): check(state, resources)


def test_completed_live_history_allows_ordinary_guards_but_not_execution_or_transitions(completed):
  case, state = completed
  with case.domain._transaction(write=True) as actual:
    actual["intents"][BATCH] = state["intents"][BATCH]
  before = ledger(case.domain)
  with case.workspace.backend.runtime_guard(case.workspace, case.identity, exclusive=True):
    pass
  with case.workspace.adapter.apply_lifecycle_guard(case.workspace):
    pass
  with _shared_file(case.workspace.instance, ".agentcfg-omp.lock") as fd:
    _, pending = omp_observation.snapshot(case.workspace, instance_fd=fd)
  assert pending is False
  for call in (lambda: execute(case), lambda: case.domain.dispatch_intent(BATCH),
      lambda: case.domain.mark_intent_unknown(BATCH), lambda: case.domain.cancel_intent(BATCH)):
    with pytest.raises(Conflict): call()
  assert ledger(case.domain) == before
