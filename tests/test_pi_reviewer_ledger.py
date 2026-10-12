"""纯临时文件与线程故障测试；不启动宿主、SDK、模型或网络。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from agentcfg.pi_reviewer_ledger import ReviewerLedger, FILE
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree


LIMITS = {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000}
PRICING = {"identity": "e" * 64, "currency": "USD", "input_units_per_million": 1000000,
  "output_units_per_million": 2000000, "cache_read_units_per_million": 500000,
  "cache_write_units_per_million": 3000000}
TOKENS = {"input_tokens": 100, "output_tokens": 10}
USAGE = {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}


def request(index=1, *, intent=1, session=1):
  return {"binding": {"operation_id": f"{index:032x}", "request_id": f"{index + 100:032x}",
    "operation_digest": "a" * 64, "context_digest": "b" * 64, "reviewer_identity": "c" * 64},
    "scope": {"session_scope": f"{session:032x}", "intent_ref": f"{intent:032x}"},
    "pricing": deepcopy(PRICING), "token_limits": deepcopy(TOKENS)}


def ledger(tmp_path, **changes):
  return ReviewerLedger(tmp_path / "account-ledger", limits={**LIMITS, **changes})


def sent(value, index=1, *, intent=1, session=1):
  row = value.reserve(**request(index, intent=intent, session=session))
  value.claim_attempt(row["binding"]["operation_id"])
  value.commit_send(row["binding"]["operation_id"])
  value.mark_sent(row["binding"]["operation_id"])
  return row["binding"]["operation_id"]


def finish(value, operation, decision="allow"):
  reason = {"allow": "authorized-in-scope", "ask": "needs-human", "deny": "outside-user-scope"}[decision]
  return value.finish(operation, requests=1, outcome="valid", decision=decision, reason_code=reason)


def test_reservation_cache_premium_and_private_projection(tmp_path):
  value = ledger(tmp_path)
  row = value.reserve(**request())
  assert row["reservation_units"] == 320
  assert value.reserve(**request()) == row
  result = value.snapshot()
  assert (result["reserved_calls"], result["committed_calls"], result["charged_cost_units"]) == (1, 0, 320)
  assert result["product_gate"] is False
  text = (value.root / FILE).read_text()
  assert "prompt" not in text and "apiKey" not in text and "user_intent" not in text
  assert (value.root / FILE).stat().st_mode & 0o777 == 0o600
  assert value.root.stat().st_mode & 0o777 == 0o700
  row["binding"]["operation_id"] = "f" * 32
  result["limits"]["max_calls"] = 999
  assert value.get("0" * 31 + "1")["binding"]["operation_id"] == "0" * 31 + "1"
  assert value.snapshot()["limits"] == LIMITS


def test_commit_unknown_survives_restart_and_never_resends(tmp_path):
  value = ledger(tmp_path)
  operation = value.reserve(**request())["binding"]["operation_id"]
  value.claim_attempt(operation)
  value.commit_send(operation)
  reopened = ledger(tmp_path)
  assert reopened.get(operation)["requests"] is None
  assert reopened.snapshot()["unknown_requests"] == 1
  assert reopened.snapshot()["charged_cost_units"] == 320
  with pytest.raises(Conflict, match="REVIEW_SEND_ALREADY_CLAIMED"): reopened.commit_send(operation)
  with pytest.raises(Conflict, match="REVIEW_INTENT_BLOCKED"): reopened.reserve(**request(2))


def test_attempt_claim_survives_restart_before_first_send(tmp_path):
  value = ledger(tmp_path); operation = value.reserve(**request())["binding"]["operation_id"]
  value.claim_attempt(operation)
  reopened = ledger(tmp_path)
  assert reopened.get(operation)["attempt_claimed"] is True
  assert reopened.get(operation)["requests"] == 0
  with pytest.raises(Conflict, match="REVIEW_ATTEMPT_ALREADY_CLAIMED"): reopened.claim_attempt(operation)
  # 失去启动回执也不再建第二个SDK进程；模型计量预留仍保留。
  assert reopened.snapshot()["reserved_cost_units"] == 320


def test_concurrent_attempt_claim_has_exactly_one_sdk_dispatch_owner(tmp_path):
  value = ledger(tmp_path); operation = value.reserve(**request())["binding"]["operation_id"]
  def claim(_):
    try: value.claim_attempt(operation); return "winner"
    except Conflict: return "blocked"
  with ThreadPoolExecutor(max_workers=8) as executor: results = list(executor.map(claim, range(24)))
  assert results.count("winner") == 1


def test_send_requires_previous_durable_sdk_attempt_claim(tmp_path):
  value = ledger(tmp_path); operation = value.reserve(**request())["binding"]["operation_id"]
  with pytest.raises(Conflict, match="REVIEW_ATTEMPT_NOT_CLAIMED"): value.commit_send(operation)
  assert value.get(operation)["attempt_claimed"] is False


def test_stored_final_usage_requires_terminal_outcome(tmp_path):
  value = ledger(tmp_path); operation = sent(value); finish(value, operation)
  value.record_usage(operation, USAGE, final=True, process_terminated=True)
  path = value.root / FILE; data = json.loads(path.read_text())
  data["rows"][operation].update(outcome=None, decision=None, reason_code=None)
  path.write_text(json.dumps(data))
  with pytest.raises(ConfigError, match="PI_RISK_REVIEW_LEDGER_INVALID"): value.snapshot()


def test_commit_write_failure_prevents_platform_callback_and_retries_are_observations(tmp_path):
  value = ledger(tmp_path)
  operation = value.reserve(**request())["binding"]["operation_id"]
  value.claim_attempt(operation)
  sends = []
  with patch.object(Tree, "replace", side_effect=OSError("synthetic disk full")):
    with pytest.raises(OSError):
      value.commit_send(operation)
      sends.append("platform invoked")
  assert sends == [] and value.get(operation)["send_state"] == "reserved"


def test_after_replace_failure_keeps_commit_tombstone(tmp_path):
  value = ledger(tmp_path)
  operation = value.reserve(**request())["binding"]["operation_id"]
  value.claim_attempt(operation)
  replace = Tree.replace
  def failed_receipt(tree, *args, **kwargs):
    replace(tree, *args, **kwargs)
    raise OSError("synthetic receipt loss")
  with patch.object(Tree, "replace", failed_receipt):
    with pytest.raises(OSError): value.commit_send(operation)
  reopened = ledger(tmp_path)
  assert reopened.get(operation)["send_state"] == "committed"
  with pytest.raises(Conflict, match="REVIEW_SEND_ALREADY_CLAIMED"): reopened.commit_send(operation)


def test_cancel_after_send_keeps_requests_and_unknown_cost(tmp_path):
  value = ledger(tmp_path); operation = sent(value)
  value.finish(operation, requests=1, outcome="canceled")
  assert value.snapshot()["committed_calls"] == 1
  assert value.snapshot()["observed_requests"] == 1
  assert value.snapshot()["reserved_cost_units"] == 320
  with pytest.raises(Conflict, match="REVIEW_TERMINAL_CONFLICT"): finish(value, operation)
  with pytest.raises(Conflict, match="REVIEW_REQUEST_FACT_CONFLICT"):
    value.finish(sent(value, 2, intent=2), requests=0, outcome="canceled")


@pytest.mark.parametrize("outcome", ["canceled", "timeout", "not-called", "policy-blocked", "human-required", "discarded", "transport-failure"])
def test_zero_send_releases_reservation_but_keeps_tombstone(tmp_path, outcome):
  value = ledger(tmp_path); operation = value.reserve(**request())["binding"]["operation_id"]
  result = value.finish(operation, requests=0, outcome=outcome)
  assert result["send_state"] == "not-sent" and result["settled_units"] == 0
  assert value.snapshot()["charged_cost_units"] == 0
  assert value.snapshot()["reserved_calls"] == value.snapshot()["committed_calls"] == 0
  with pytest.raises(Conflict, match="REVIEW_SEND_ALREADY_CLAIMED"): value.commit_send(operation)
  assert value.reserve(**request())["outcome"] == outcome


def test_late_usage_does_not_revive_canceled_candidate(tmp_path):
  value = ledger(tmp_path); operation = sent(value)
  value.finish(operation, requests=1, outcome="canceled")
  value.record_usage(operation, USAGE)
  assert value.get(operation)["outcome"] == "canceled"
  assert value.snapshot()["reserved_cost_units"] == 320
  value.record_usage(operation, USAGE, final=True, process_terminated=True)
  result = value.snapshot()
  assert result["charged_cost_units"] == 21 and result["reserved_cost_units"] == 0
  assert result["reported_estimated_cost_units"] == 21 and result["committed_calls"] == 1
  assert value.get(operation)["decision"] is None


def test_final_usage_requires_terminal_and_whole_process_proof(tmp_path):
  value = ledger(tmp_path); operation = sent(value)
  with pytest.raises(Conflict, match="REVIEW_NOT_TERMINAL"):
    value.record_usage(operation, USAGE, final=True, process_terminated=True)
  assert value.get(operation)["usage"] is None
  finish(value, operation)
  with pytest.raises(Conflict, match="REVIEW_TERMINATION_UNKNOWN"): value.record_usage(operation, USAGE, final=True)
  assert value.get(operation)["usage"] is None
  value.record_usage(operation, USAGE, process_terminated=True)
  assert value.snapshot()["reserved_cost_units"] == 320
  value.record_usage(operation, USAGE, final=True)
  with pytest.raises(Conflict, match="REVIEW_FINAL_USAGE_CHANGED"):
    value.record_usage(operation, {"input_tokens": 6, "output_tokens": 3, "total_tokens": 9})


def test_usage_cannot_regress_overrun_or_appear_without_send(tmp_path):
  value = ledger(tmp_path); operation = value.reserve(**request())["binding"]["operation_id"]
  with pytest.raises(Conflict, match="REVIEW_USAGE_WITHOUT_SEND"): value.record_usage(operation, USAGE)
  value.claim_attempt(operation); value.commit_send(operation); value.mark_sent(operation); value.record_usage(operation, USAGE)
  for usage in ({"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
      {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}):
    with pytest.raises(Conflict, match="REVIEW_USAGE_REGRESSED"): value.record_usage(operation, usage)
  for usage in ({"input_tokens": 101, "output_tokens": 0, "total_tokens": 101},
      {"input_tokens": 5, "output_tokens": 3, "total_tokens": 9},
      {"input_tokens": True, "output_tokens": 3, "total_tokens": 4}):
    with pytest.raises(ConfigError): value.record_usage(operation, usage)


@pytest.mark.parametrize("decision,code", [("deny", "REVIEW_INTENT_DENIED"), ("ask", "REVIEW_INTENT_BLOCKED")])
def test_decision_latch_blocks_rewrite_and_route_hop_across_restart(tmp_path, decision, code):
  value = ledger(tmp_path); operation = sent(value); finish(value, operation, decision)
  next_request = request(2); next_request["binding"]["reviewer_identity"] = "f" * 64
  next_request["binding"]["operation_digest"] = "d" * 64
  with pytest.raises(Conflict, match=code): ledger(tmp_path).reserve(**next_request)
  next_request["scope"]["intent_ref"] = "0" * 31 + "2"
  assert ledger(tmp_path).reserve(**next_request)["send_state"] == "reserved"


def test_pending_intent_serializes_review_and_allow_reopens_next_operation(tmp_path):
  value = ledger(tmp_path); row = value.reserve(**request())
  with pytest.raises(Conflict, match="REVIEW_INTENT_BUSY"): value.reserve(**request(2))
  value.claim_attempt(row["binding"]["operation_id"])
  value.commit_send(row["binding"]["operation_id"]); value.mark_sent(row["binding"]["operation_id"])
  finish(value, row["binding"]["operation_id"])
  assert value.reserve(**request(2))["send_state"] == "reserved"


def test_original_request_cannot_receive_new_operation_identity(tmp_path):
  value = ledger(tmp_path); operation = sent(value); finish(value, operation)
  changed = request(2); changed["binding"]["request_id"] = request()["binding"]["request_id"]
  with pytest.raises(Conflict, match="REVIEW_IDEMPOTENCY_CONFLICT"): value.reserve(**changed)
  changed["scope"]["session_scope"] = "f" * 32
  assert value.reserve(**changed)["send_state"] == "reserved"


@pytest.mark.parametrize("field", ["operation_digest", "context_digest", "reviewer_identity", "request_id"])
def test_existing_operation_binding_changes_conflict(tmp_path, field):
  value = ledger(tmp_path); value.reserve(**request()); changed = request()
  changed["binding"][field] = "f" * len(changed["binding"][field])
  with pytest.raises(Conflict, match="REVIEW_IDEMPOTENCY_CONFLICT"): value.reserve(**changed)


@pytest.mark.parametrize("limits", [{"max_calls": 0}, {"max_cost_units": 319}])
def test_budget_denial_is_atomic_and_does_not_create_a_tombstone(tmp_path, limits):
  value = ledger(tmp_path, **limits)
  with pytest.raises(Conflict, match="REVIEW_BUDGET_EXHAUSTED"): value.reserve(**request())
  assert value.snapshot()["record_count"] == 0


def test_cumulative_calls_and_cost_do_not_reset_or_cross_currency(tmp_path):
  value = ledger(tmp_path, max_calls=1); operation = sent(value); finish(value, operation)
  with pytest.raises(Conflict, match="REVIEW_BUDGET_EXHAUSTED"):
    ledger(tmp_path, max_calls=1).reserve(**request(2, intent=2))
  with pytest.raises(Conflict, match="REVIEW_BUDGET_INCREASE_REQUIRES_AUTHORITY"): ledger(tmp_path)
  with pytest.raises(Conflict, match="REVIEW_BUDGET_INCREASE_REQUIRES_AUTHORITY"): ledger(tmp_path, currency="CNY", max_calls=1)


def test_tightened_budget_blocks_pending_send_and_old_authority(tmp_path):
  value = ledger(tmp_path); row = value.reserve(**request())
  value.claim_attempt(row["binding"]["operation_id"])
  tighter = ledger(tmp_path, max_calls=0)
  assert tighter.snapshot()["over_budget"] is True
  with pytest.raises(Conflict, match="REVIEW_BUDGET_EXHAUSTED"): tighter.commit_send(row["binding"]["operation_id"])
  with pytest.raises(Conflict, match="REVIEW_BUDGET_INCREASE_REQUIRES_AUTHORITY"): value.commit_send(row["binding"]["operation_id"])


def test_concurrent_commit_has_exactly_one_dispatch_owner(tmp_path):
  value = ledger(tmp_path); operation = value.reserve(**request())["binding"]["operation_id"]
  value.claim_attempt(operation)
  def claim(_):
    try: value.commit_send(operation); return "winner"
    except Conflict: return "blocked"
  with ThreadPoolExecutor(max_workers=8) as executor: results = list(executor.map(claim, range(24)))
  assert results.count("winner") == 1 and value.snapshot()["committed_calls"] == 1


def test_record_capacity_never_evicts_tombstones(tmp_path):
  value = ReviewerLedger(tmp_path / "account-ledger", limits=LIMITS, max_records=1)
  operation = value.reserve(**request())["binding"]["operation_id"]
  value.finish(operation, requests=0, outcome="canceled")
  with pytest.raises(Conflict, match="REVIEW_LEDGER_CAPACITY"): value.reserve(**request(2, intent=2))
  assert value.reserve(**request())["outcome"] == "canceled"


def test_rounding_never_under_reserves_fractional_units(tmp_path):
  value = ledger(tmp_path); item = request()
  for key in list(PRICING)[2:]: item["pricing"][key] = 1
  item["token_limits"] = {"input_tokens": 1, "output_tokens": 1}
  assert value.reserve(**item)["reservation_units"] == 1


@pytest.mark.parametrize("change", [lambda value: value.update(prompt="synthetic secret"),
  lambda value: value["binding"].update(source="human"),
  lambda value: value["pricing"].update(input_units_per_million=True),
  lambda value: value["scope"].update(intent_ref="user text or secret hash"),
  lambda value: value["token_limits"].update(output_tokens=4097)])
def test_closed_input_errors_do_not_echo_private_data(tmp_path, change):
  value = ledger(tmp_path); item = request(); change(item)
  with pytest.raises((ConfigError, TypeError)) as caught: value.reserve(**item)
  assert "synthetic secret" not in str(caught.value)
  assert value.snapshot()["record_count"] == 0


@pytest.mark.parametrize("edit", [lambda value: value.update(schema_version=True),
  lambda value: value.update(source="reviewer"),
  lambda value: value["rows"]["0" * 31 + "1"].update(settled_units=False),
  lambda value: value["rows"]["0" * 31 + "1"].update(requests=1),
  lambda value: value["rows"]["0" * 31 + "1"].update(outcome="valid", decision="allow", reason_code="authorized-in-scope")])
def test_closed_stored_state_fails_instead_of_repairing(tmp_path, edit):
  value = ledger(tmp_path); value.reserve(**request())
  path = value.root / FILE; state = json.loads(path.read_text()); edit(state)
  text = json.dumps(state); path.write_text(text)
  with pytest.raises(ConfigError, match="PI_RISK_REVIEW_LEDGER_INVALID"): value.snapshot()
  assert path.read_text() == text


def test_duplicate_json_keys_symlink_hardlink_and_modes_are_rejected(tmp_path):
  value = ledger(tmp_path); path = value.root / FILE
  text = path.read_text(); path.write_text(text.replace('"schema_version":1', '"schema_version":1,"schema_version":1'))
  with pytest.raises(ConfigError): value.snapshot()
  path.write_text(text); path.chmod(0o644)
  with pytest.raises(Conflict, match="REVIEW_LEDGER_MODE"): value.snapshot()
  path.chmod(0o600); path.rename(value.root / "original.json"); path.symlink_to("original.json")
  with pytest.raises(Conflict): value.snapshot()
  path.unlink(); path.hardlink_to(value.root / "original.json")
  with pytest.raises(Conflict): value.snapshot()


def test_explicit_no_create_missing_root_never_initializes(tmp_path):
  root = tmp_path / "missing-ledger"
  with pytest.raises(Conflict, match="REVIEW_LEDGER_MISSING"):
    ReviewerLedger(root, limits=LIMITS, create=False)
  assert not root.exists()


def test_explicit_no_create_missing_file_never_replenishes_empty_budget(tmp_path):
  value = ledger(tmp_path)
  (value.root / FILE).unlink()
  with pytest.raises(Conflict, match="REVIEW_LEDGER_MISSING"):
    ReviewerLedger(value.root, limits=LIMITS, create=False)
  assert not (value.root / FILE).exists()


def test_explicit_no_create_reopens_existing_attempt_tombstone(tmp_path):
  value = ledger(tmp_path)
  op = value.reserve(**request())["binding"]["operation_id"]
  value.claim_attempt(op)
  reopened = ReviewerLedger(value.root, limits=LIMITS, create=False)
  with pytest.raises(Conflict, match="REVIEW_ATTEMPT_ALREADY_CLAIMED"):
    reopened.claim_attempt(op)
