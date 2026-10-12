"""scope live gate组合；只用真实临时账本/范围表与fake callback/clock。"""
from copy import deepcopy
import json

import pytest

from agentcfg.pi_reviewer_decision import ReviewerDecisionControl
from agentcfg.storage import Conflict
from agentcfg.schema import ConfigError
from test_pi_reviewer_decision import fixture as decision_fixture, wire
from test_pi_reviewer_scopes import fixture as scope_fixture, refs


def test_missing_scope_gate_blocks_enabled_full_before_ledger_reservation(tmp_path):
  f = decision_fixture(tmp_path)
  config = {key: value for key, value in f["config"].items() if key != "scope_current"}
  control = ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  with pytest.raises(Conflict, match="REVIEW_SCOPE_UNQUALIFIED"):
    control.begin(f["prepared"]["operation_id"])
  assert f["ledger"].snapshot()["record_count"] == 0


def configured(tmp_path, gate, **kwargs):
  f = decision_fixture(tmp_path, **kwargs)
  config = dict(f["config"]); config["scope_current"] = gate
  f["control"] = ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  return f


def begin(f):
  return f["control"].begin(f["prepared"]["operation_id"])


def conclude(f, attempt, requests=1):
  return f["control"].conclude(attempt["ticket"],
    {"outcome": "valid", "requests": requests, "response": wire(attempt)})


def secret_error():
  raise RuntimeError("SYNTHETIC_PRIVATE_SCOPE")


@pytest.mark.parametrize("answer", [False, None, 0, 1, "true", {}, [], secret_error])
@pytest.mark.parametrize("phase", ["begin", "commit", "conclude"])
def test_only_exact_true_qualifies_each_authorization_stage(tmp_path, answer, phase):
  state = [True]
  def gate(prepared, scoped_refs):
    return state[0]() if callable(state[0]) else state[0]
  f = configured(tmp_path, gate)
  if phase == "begin":
    state[0] = answer
    with pytest.raises(Conflict, match="REVIEW_SCOPE_UNQUALIFIED") as caught: begin(f)
    assert "SYNTHETIC_PRIVATE_SCOPE" not in str(caught.value)
    assert f["ledger"].snapshot()["record_count"] == 0
    return
  attempt = begin(f)
  if phase == "conclude": f["control"].commit_send(attempt["ticket"])
  state[0] = answer
  if phase == "commit":
    with pytest.raises(Conflict, match="REVIEW_SCOPE_UNQUALIFIED") as caught:
      f["control"].commit_send(attempt["ticket"])
    assert "SYNTHETIC_PRIVATE_SCOPE" not in str(caught.value)
    row = f["ledger"].get(f["prepared"]["operation_id"])
    assert row["send_state"] == "reserved" and row["requests"] == 0
    state[0] = True
    with pytest.raises(Conflict): f["control"].commit_send(attempt["ticket"])
    with pytest.raises(Conflict): begin(f)
    result = conclude(f, attempt, requests=0)
  else:
    reserved = f["ledger"].snapshot()["reserved_cost_units"]
    # 资格退出不阻止已经发送的一次事实记账。
    f["control"].mark_sent(attempt["ticket"])
    result = conclude(f, attempt)
    row = f["ledger"].get(f["prepared"]["operation_id"])
    assert row["requests"] == 1 and row["outcome"] == "discarded"
    assert f["ledger"].snapshot()["reserved_cost_units"] == reserved
    with pytest.raises(Conflict): conclude(f, attempt)
  assert result["permit"] is None and result["reason_code"] == "discarded"
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"] == "revoked"


def test_callback_copies_original_refs_and_public_prepared_and_provider_runs_once(tmp_path):
  seen = []; allocations = []
  def gate(prepared, scoped_refs):
    seen.append((deepcopy(prepared), deepcopy(scoped_refs)))
    assert "SYNTHETIC_PRIVATE_BODY" not in json.dumps(prepared)
    assert "private_input" not in prepared
    prepared["context"]["cancel_epoch"] = 777
    prepared["resolution"]["target"]["path"] = "/tampered"
    scoped_refs.clear()
    return True
  f = configured(tmp_path, gate); config = dict(f["config"])
  config["scope_current"] = gate
  def allocate(prepared):
    allocations.append(deepcopy(prepared)); return deepcopy(f["scope"])
  config["scope_provider"] = allocate
  f["control"] = ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  original = deepcopy(f["scope"]); original_prepared = deepcopy(f["prepared"])
  attempt = begin(f); f["scope"].update(request_ref="4" * 32, intent_ref="5" * 32)
  f["control"].commit_send(attempt["ticket"]); f["control"].mark_sent(attempt["ticket"])
  result = conclude(f, attempt)
  assert len(allocations) == 1 and len(seen) == 4
  assert all(p == original_prepared and s == original for p, s in seen)
  assert attempt["binding"]["request_id"] == original["request_ref"]
  assert f["prepared"] == original_prepared and f["current"]["cancel_epoch"] == 0
  assert f["admissions"].consume(result["permit"], current=f["current"], resolved=f["resolved"])["private_input"] == f["private"]
  with pytest.raises(Conflict): f["admissions"].consume(result["permit"], current=f["current"], resolved=f["resolved"])


@pytest.mark.parametrize("ceiling", ["base", "off", "hard", "human", "role", "risk"])
def test_policy_ceilings_precede_scope_allocation_and_live_callback(tmp_path, ceiling):
  calls = []
  f = configured(tmp_path, lambda p, s: calls.append("current") or True,
    profile="pi-base" if ceiling == "base" else "pi-full", enabled=ceiling != "off",
    requires_human=ceiling == "human")
  config = dict(f["config"]); config["scope_current"] = lambda p, s: calls.append("current") or True
  config["scope_provider"] = lambda p: calls.append("allocate") or deepcopy(f["scope"])
  f["control"] = ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  if ceiling == "hard": f["resolved"]["policy"]["hard_policy"] = "deny"
  if ceiling == "role": f["qualify"]["role_allows"] = False
  if ceiling == "risk": f["qualify"]["automatic_risk_allowed"] = False
  if ceiling == "hard":
    with pytest.raises(Conflict): begin(f)
  else: assert begin(f)["ticket"] is None
  assert calls == [] and f["ledger"].snapshot()["record_count"] == 0


@pytest.mark.parametrize("phase", ["commit", "conclude"])
def test_actual_scope_retirement_is_seen_without_reallocation(tmp_path, phase):
  sf = scope_fixture(tmp_path); original = refs(sf); calls = []
  def gate(prepared, scoped_refs):
    calls.append(deepcopy(scoped_refs)); return sf["store"].verify_current(scoped_refs)
  f = configured(tmp_path, gate); config = dict(f["config"]); config["scope_current"] = gate
  allocations = []
  config["scope_provider"] = lambda p: allocations.append(1) or deepcopy(original)
  f["control"] = ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  attempt = begin(f)
  if phase == "commit": sf["store"].retire_intent(original["session_scope"], original["intent_ref"])
  else:
    f["control"].commit_send(attempt["ticket"])
    sf["store"].retire_session(original["session_scope"])
  if phase == "commit":
    with pytest.raises(Conflict, match="REVIEW_SCOPE_UNQUALIFIED"): f["control"].commit_send(attempt["ticket"])
    assert f["ledger"].get(f["prepared"]["operation_id"])["send_state"] == "reserved"
    result = conclude(f, attempt, requests=0)
  else:
    # 未确认是否发出保留unknown请求和全部预留，不因退役变成not-sent。
    reserved = f["ledger"].snapshot()["reserved_cost_units"]
    result = conclude(f, attempt, requests=None)
    row = f["ledger"].get(f["prepared"]["operation_id"])
    assert row["requests"] is None and row["outcome"] == "discarded"
    assert f["ledger"].snapshot()["reserved_cost_units"] == reserved
  assert result["permit"] is None and result["reason_code"] == "discarded"
  assert allocations == [1] and all(value == original for value in calls)


def test_scope_changes_during_finish_are_rechecked_before_issue(tmp_path):
  active = [True]; f = configured(tmp_path, lambda p, s: active[0]); attempt = begin(f)
  f["control"].commit_send(attempt["ticket"]); f["control"].mark_sent(attempt["ticket"])
  original = f["ledger"].finish
  def finish(*args, **kwargs):
    value = original(*args, **kwargs); active[0] = False; return value
  f["ledger"].finish = finish
  result = conclude(f, attempt)
  assert result["permit"] is None and result["reason_code"] == "discarded"
  assert f["ledger"].get(f["prepared"]["operation_id"])["decision"] == "allow"


def test_invalid_callback_constructor_and_provider_exception_are_fixed(tmp_path):
  f = decision_fixture(tmp_path); config = dict(f["config"]); config["scope_current"] = 1
  with pytest.raises(ConfigError): ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  config["scope_current"] = lambda p, s: True
  config["scope_provider"] = lambda p: secret_error()
  control = ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  with pytest.raises(Conflict, match="REVIEW_SCOPE_UNQUALIFIED") as caught: control.begin(f["prepared"]["operation_id"])
  assert "SYNTHETIC_PRIVATE_SCOPE" not in str(caught.value)
  assert f["ledger"].snapshot()["record_count"] == 0


def test_late_reported_usage_records_fact_without_reviving_discarded_operation(tmp_path):
  active = [True]; calls = []
  f = configured(tmp_path, lambda p, s: calls.append(active[0]) or active[0]); attempt = begin(f)
  f["control"].commit_send(attempt["ticket"]); active[0] = False
  count = len(calls); f["control"].mark_sent(attempt["ticket"])
  assert len(calls) == count
  result = conclude(f, attempt)
  reserved = f["ledger"].snapshot()["reserved_cost_units"]
  usage = {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
  row = f["ledger"].record_usage(f["prepared"]["operation_id"], usage)
  assert row["usage"] == usage and row["outcome"] == "discarded" and row["requests"] == 1
  assert row["final_usage"] is False and row["settled_units"] is None
  assert f["ledger"].snapshot()["reserved_cost_units"] == reserved
  active[0] = True
  assert result["permit"] is None
  with pytest.raises(Conflict): begin(f)
  with pytest.raises(Conflict): conclude(f, attempt)


def test_context_change_during_scope_allocation_blocks_before_budget_or_scope_gate(tmp_path):
  f = decision_fixture(tmp_path); calls = []; config = dict(f["config"])
  config["scope_current"] = lambda p, s: calls.append("current") or True
  def allocate(prepared):
    calls.append("allocate"); f["current"]["cancel_epoch"] += 1
    return deepcopy(f["scope"])
  config["scope_provider"] = allocate
  control = ReviewerDecisionControl(f["admissions"], f["ledger"], **config)
  with pytest.raises(Conflict, match="REVIEW_CONTEXT_STALE"): control.begin(f["prepared"]["operation_id"])
  assert calls == ["allocate"] and f["ledger"].snapshot()["record_count"] == 0
