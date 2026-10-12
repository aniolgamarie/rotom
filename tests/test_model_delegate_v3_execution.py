"""统一实际控制器使用的原子关联；本模块替身不提供来源/执行授权。"""
from copy import deepcopy
import json

import pytest

from agentcfg.model_delegate import DelegationRuns
from agentcfg.model_delegate_v3_execution import LogicalExecutions
from agentcfg.storage import Conflict, Tree
from test_model_delegate_v3_intents import ORIGIN, BINDING, submit, follow

BUDGET = {"scope_id": "budget-1", "currency": "USD", "max_calls": 4, "max_turns": 4,
  "max_input_tokens": 400, "max_output_tokens": 80, "max_cost_microunits": 100,
  "per_call_input_tokens": 100, "per_call_output_tokens": 20,
  "per_call_cost_microunits": 10, "wall_seconds": 60}


def core(tmp_path):
  return LogicalExecutions(DelegationRuns(tmp_path / "runs"), now_ms=lambda: 1000)


def test_sending_atomic_postimage_precedes_sender_and_replay_never_grants_again(tmp_path):
  ledger = core(tmp_path)
  first = ledger.begin(ORIGIN, submit(), BINDING, BUDGET)
  assert first["send"] is True
  row = json.loads((ledger.runs.root / "execution-v3" / (first["run_id"] + ".json")).read_text())
  assert row["actions"][0]["state"] == "sending"
  assert row["budget"]["reservations"]["cost_microunits"] == 100
  assert ledger.begin(ORIGIN, submit(), BINDING, BUDGET)["send"] is False
  public = ledger.query(ORIGIN, first["run_id"], BINDING)
  assert "request_digest" not in json.dumps(public) and "action_key" not in json.dumps(public)


def test_persistence_failure_before_sending_grants_zero_send(tmp_path, monkeypatch):
  ledger = core(tmp_path)
  original = Tree.write_state
  def broken(self, path, *args, **kwargs):
    if str(path).startswith("execution-v3/"):
      raise OSError("synthetic-secret")
    return original(self, path, *args, **kwargs)
  monkeypatch.setattr(Tree, "write_state", broken)
  with pytest.raises(Conflict, match="DELEGATE_EXECUTION_WRITE_FAILED"):
    ledger.begin(ORIGIN, submit(), BINDING, BUDGET)
  assert not (ledger.runs.root / "execution-v3").exists()


def test_unknown_keeps_entire_cost_reservation_and_query_writes_nothing(tmp_path):
  ledger = core(tmp_path)
  started = ledger.begin(ORIGIN, submit(), BINDING, BUDGET)
  ledger.unknown(started["run_id"], started["action_key"], "DELEGATE_SEND_UNKNOWN")
  before = {str(p): p.read_bytes() for p in ledger.runs.root.rglob("*.json")}
  assert ledger.query(ORIGIN, started["run_id"], BINDING)["status"] == "unknown"
  assert before == {str(p): p.read_bytes() for p in ledger.runs.root.rglob("*.json")}
  assert ledger.begin(ORIGIN, submit(), BINDING, BUDGET)["send"] is False


def test_registered_only_query_is_readonly_and_cancellation_does_not_refund(tmp_path):
  ledger = core(tmp_path)
  registration = ledger.runs.prepare_modern_intent(ORIGIN, submit(), BINDING)
  before = {str(p): p.read_bytes() for p in ledger.runs.root.rglob("*.json")}
  assert ledger.query(ORIGIN, registration["run_id"], BINDING)["status"] == "registered-not-started"
  assert before == {str(p): p.read_bytes() for p in ledger.runs.root.rglob("*.json")}
  first = ledger.begin(ORIGIN, submit(), BINDING, BUDGET)
  stopped = ledger.begin(ORIGIN, follow("cancel", first["run_id"], "cancel-1"), BINDING, BUDGET)
  assert stopped["send"] is True
  row = ledger.query(ORIGIN, first["run_id"], BINDING)
  assert row["cancel_requested"] is True and row["budget"]["reservations"]["cost_microunits"] == 100


def test_budget_missing_unknown_or_scope_drift_fail_before_registration(tmp_path):
  ledger = core(tmp_path)
  for config in [None, {**BUDGET, "max_calls": True}, {**BUDGET, "currency": "unknown"}, {**BUDGET, "secret": "synthetic-secret"}]:
    with pytest.raises(Exception): ledger.begin(ORIGIN, submit(), BINDING, config)
  assert not ledger.runs.root.exists()


def test_cancel_retains_original_budget_when_current_configuration_is_missing_or_tightened(tmp_path):
  ledger = core(tmp_path)
  first = ledger.begin(ORIGIN, submit(), BINDING, BUDGET)
  before = ledger.private(first["run_id"])["budget"]
  result = ledger.begin(ORIGIN, follow("cancel", first["run_id"], "close-without-config"), {**BINDING, "config_identity_digest": "9" * 64}, None)
  assert result["send"] is True
  assert ledger.private(first["run_id"])["budget"] == before
  assert ledger.query(ORIGIN, first["run_id"], BINDING)["cancel_requested"] is True


@pytest.mark.parametrize("state", ["prepared", "sending", "acknowledged", "completed", "rejected"])
def test_unknown_cannot_be_promoted_by_ordinary_ack_or_backwards_transition(tmp_path, state):
  ledger = core(tmp_path)
  first = ledger.begin(ORIGIN, submit(), BINDING, BUDGET)
  ledger.unknown(first["run_id"], first["action_key"], "DELEGATE_SEND_UNKNOWN")
  with pytest.raises(Conflict, match="DELEGATE_EXECUTION_TRANSITION"):
    ledger.update(first["run_id"], first["action_key"], state=state)
  assert ledger.private(first["run_id"])["budget"]["reservations"]["cost_microunits"] == 100


@pytest.mark.parametrize("corrupt", ["lost-reservation", "per-call-over-total", "aggregate-over-limit"])
def test_corrupt_budget_conservation_fails_closed(tmp_path, corrupt):
  ledger = core(tmp_path)
  first = ledger.begin(ORIGIN, submit(), BINDING, BUDGET)
  path = ledger.runs.root / "execution-v3" / (first["run_id"] + ".json")
  row = json.loads(path.read_text())
  if corrupt == "lost-reservation": row["budget"]["reservations"]["cost_microunits"] = 0
  elif corrupt == "per-call-over-total": row["budget"]["limits"]["per_call_input_tokens"] = 401
  else: row["budget"]["totals"]["known_cost_microunits"] = 1
  path.write_text(json.dumps(row))
  with pytest.raises(Conflict, match="DELEGATE_EXECUTION_STATE_INVALID"):
    ledger.query(ORIGIN, first["run_id"], BINDING)


def test_unknown_action_cannot_get_another_model_or_turn_admission_even_with_synthetic_oracle(tmp_path):
  ledger = core(tmp_path)
  first = ledger.begin(ORIGIN, submit(), BINDING, BUDGET)
  ledger.unknown(first["run_id"], first["action_key"], "DELEGATE_SEND_UNKNOWN")
  before = ledger.private(first["run_id"])
  for metric in ("calls", "turns"):
    with pytest.raises(Conflict, match="DELEGATE_EXECUTION_ATTEMPT_UNKNOWN"):
      ledger.meter_claim(first["run_id"], first["action_key"], metric, 1, synthetic_cost=0)
  assert ledger.private(first["run_id"]) == before
