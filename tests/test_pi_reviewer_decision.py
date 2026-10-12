"""实际许可账本与持久reviewer账本组合；进程/SDK/send均计数替身。"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from threading import RLock
from unittest.mock import patch

import pytest

from agentcfg.pi_operation_admission import OperationAdmissions
from agentcfg.pi_reviewer_decision import ReviewerDecisionControl
from agentcfg.pi_reviewer_ledger import ReviewerLedger
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def fixture(tmp_path, *, profile="pi-full", enabled=True, requires_human=False, max_calls=20,
    reviewer_current=lambda prepared, current: True):
  clock = [1000]
  # 本组合测试显式安装fake live qualifier，真实宿主资格仍未接线。
  admissions = OperationAdmissions("activation", now_ms=lambda: clock[0], reviewer_current=reviewer_current)
  current = {"activation_id": "activation", "profile": profile, "session_id": "session", "role_id": "main",
    "cwd": "/project", "user_intent_ref": "user-turn-1", "restrictions_digest": "a" * 64,
    "policy_generation": 1, "cancel_epoch": 0, "runtime_identity": "b" * 64, "config_identity": "c" * 64,
    "reviewer_identity": "9" * 64 if profile == "pi-full" else None, "deadline_ms": 5000}
  resolved = {"kind": "file", "tool_name": "write", "target": {"path": "/project/file", "destination": None},
    "read_roots": [], "write_roots": [{"path": "/project", "identity": "d" * 64}], "workspace_keys": ["e" * 64],
    "network": "deny", "services": [], "backend": "guarded-files-v1",
    "policy": {"generation": 1, "policy_digest": "f" * 64, "ceiling_digest": "0" * 64,
      "hard_policy": "allow", "requires_human": requires_human}}
  qualify = {"enabled": enabled, "role_allows": True, "automatic_risk_allowed": True}
  private = {"path": "file", "content": "SYNTHETIC_PRIVATE_BODY"}
  prepared = admissions.prepare("sdk-call", current=current, resolved=resolved, private_input=private)
  scope = {"session_scope": "1" * 32, "intent_ref": "2" * 32, "request_ref": "3" * 32}
  limits = {"currency": "USD", "max_calls": max_calls, "max_cost_units": 1000000}
  ledger = ReviewerLedger(tmp_path / "reviewer", limits=limits)
  config = {"current_provider": lambda _: deepcopy(current), "resolution_provider": lambda _: deepcopy(resolved),
    "qualification_provider": lambda _: deepcopy(qualify), "scope_provider": lambda _: deepcopy(scope),
    "scope_current": lambda prepared, scoped_refs: True,  # 显式fake；真实live scope由组合测试验证。
    "human_available": lambda prepared: True,  # 本fixture原ask场景明确具有可信fake UI。
    "route_identity": "9" * 64,
    "pricing": {"identity": "8" * 64, "currency": "USD", "input_units_per_million": 1000000,
      "output_units_per_million": 2000000, "cache_read_units_per_million": 1000000, "cache_write_units_per_million": 1000000},
    "token_limits": {"input_tokens": 100, "output_tokens": 10}, "mutex": RLock()}
  control = ReviewerDecisionControl(admissions, ledger, **config)
  return {"admissions": admissions, "ledger": ledger, "control": control, "prepared": prepared, "current": current,
    "resolved": resolved, "qualify": qualify, "scope": scope, "config": config, "clock": clock, "private": private}


def wire(begin, decision="allow"):
  return json.dumps({"schema_version": 1, **begin["binding"], "decision": decision,
    "reason_code": {"allow": "authorized-in-scope", "ask": "needs-human", "deny": "outside-user-scope"}[decision]})


def dispatch(f):
  begin = f["control"].begin(f["prepared"]["operation_id"])
  f["control"].commit_send(begin["ticket"])
  f["control"].mark_sent(begin["ticket"])
  return begin


def conclude(f, begin, decision="allow"):
  return f["control"].conclude(begin["ticket"], {"outcome": "valid", "requests": 1, "response": wire(begin, decision)})


def test_valid_allow_uses_original_once_permit_and_has_no_execution_callback(tmp_path):
  f = fixture(tmp_path); begin = dispatch(f); result = conclude(f, begin)
  assert result["status"] == "permitted" and result["source"] == "reviewer"
  permit = result["permit"]
  assert permit["operation_id"] == f["prepared"]["operation_id"]
  assert permit["operation_digest"] == f["prepared"]["operation_digest"]
  assert permit["source"] == "reviewer" and permit["reviewer_identity"] == "9" * 64
  executions = []
  for _ in range(2):
    try:
      value = f["admissions"].consume(permit, current=f["current"], resolved=f["resolved"])
      executions.append(value)
    except Conflict: pass
  assert len(executions) == 1 and executions[0]["private_input"] == f["private"]
  assert "SYNTHETIC_PRIVATE_BODY" not in json.dumps(f["ledger"].snapshot())
  with pytest.raises(Conflict, match="REVIEW_DECISION_ALREADY_SETTLED"): conclude(f, begin)


@pytest.mark.parametrize("changes,status", [({"profile": "pi-base"}, "not-called"),
  ({"enabled": False}, "not-called"), ({"requires_human": True}, "human-required")])
def test_ineligible_begin_makes_zero_ledger_attempt_worker_send(tmp_path, changes, status):
  f = fixture(tmp_path, **changes)
  result = f["control"].begin(f["prepared"]["operation_id"])
  assert result["status"] == status and result["ticket"] is None
  assert f["ledger"].snapshot()["record_count"] == 0


@pytest.mark.parametrize("change,status", [("role_allows", "policy-blocked"), ("automatic_risk_allowed", "human-required")])
def test_ceiling_and_risk_categories_are_checked_before_model_dispatch(tmp_path, change, status):
  f = fixture(tmp_path); f["qualify"][change] = False
  assert f["control"].begin(f["prepared"]["operation_id"])["status"] == status
  assert f["ledger"].snapshot()["record_count"] == 0


def test_hard_deny_zero_attempt_and_cannot_issue_human_or_reviewer(tmp_path):
  f = fixture(tmp_path); f["resolved"]["policy"]["hard_policy"] = "deny"
  with pytest.raises(Conflict, match="OPERATION_HARD_DENIED"): f["control"].begin(f["prepared"]["operation_id"])
  assert f["ledger"].snapshot()["record_count"] == 0
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"] == "revoked"


def test_scope_denial_survives_new_controller_route_and_command_rewrite(tmp_path):
  f = fixture(tmp_path); begin = dispatch(f); result = conclude(f, begin, "deny")
  assert result["permit"] is None and result["reason_code"] == "outside-user-scope"
  f["scope"]["request_ref"] = "4" * 32
  f["private"]["content"] = "equivalent rewrite"
  newer = f["admissions"].prepare("rewritten-sdk-call", current=f["current"], resolved=f["resolved"], private_input=f["private"])
  replacement = ReviewerDecisionControl(f["admissions"], f["ledger"], **f["config"])
  with pytest.raises(Conflict, match="REVIEW_INTENT_DENIED"): replacement.begin(newer["operation_id"])
  assert f["ledger"].snapshot()["committed_calls"] == 1


def test_ask_stays_prepared_for_one_explicit_human_decision(tmp_path):
  f = fixture(tmp_path); begin = dispatch(f); result = conclude(f, begin, "ask")
  assert result["status"] == "awaiting-human" and result["permit"] is None
  assert f["admissions"].prepared(f["prepared"]["operation_id"]) == f["prepared"]
  permit = f["admissions"].issue(f["prepared"]["operation_id"], operation_digest=f["prepared"]["operation_digest"],
    current=f["current"], source="human")
  assert permit["source"] == "human" and permit["reviewer_identity"] is None
  assert f["admissions"].consume(permit, current=f["current"], resolved=f["resolved"])["prepared"] == f["prepared"]


@pytest.mark.parametrize("field", ["user_intent_ref", "restrictions_digest", "policy_generation", "cancel_epoch",
  "runtime_identity", "config_identity", "reviewer_identity", "cwd", "role_id", "session_id"])
def test_current_changes_while_waiting_discard_without_permit(tmp_path, field):
  f = fixture(tmp_path); begin = dispatch(f)
  f["current"][field] = f["current"][field] + 1 if type(f["current"][field]) is int else "7" * 64 if field.endswith("identity") or field == "restrictions_digest" else "/other" if field == "cwd" else "changed"
  result = conclude(f, begin)
  assert result["status"] == "blocked" and result["source"] == "system-failure" and result["permit"] is None
  assert f["ledger"].get(f["prepared"]["operation_id"])["outcome"] == "discarded"


@pytest.mark.parametrize("change", ["target", "root", "policy", "deadline", "revoked", "disabled", "human"])
def test_physical_or_policy_changes_while_waiting_never_issue(tmp_path, change):
  f = fixture(tmp_path); begin = dispatch(f)
  if change == "target": f["resolved"]["target"]["path"] = "/project/other"
  elif change == "root": f["resolved"]["write_roots"][0]["identity"] = "7" * 64
  elif change == "policy": f["resolved"]["policy"]["hard_policy"] = "deny"
  elif change == "deadline": f["clock"][0] = 5000
  elif change == "revoked": f["admissions"].revoke(f["prepared"]["operation_id"])
  elif change == "disabled": f["qualify"]["enabled"] = False
  else: f["resolved"]["policy"]["requires_human"] = True
  result = conclude(f, begin)
  assert result["permit"] is None and result["source"] == "system-failure"


def test_change_after_durable_allow_but_before_issue_is_rechecked(tmp_path):
  f = fixture(tmp_path); begin = dispatch(f); original = f["ledger"].finish
  def finish_then_tighten(*args, **kwargs):
    result = original(*args, **kwargs); f["current"]["cancel_epoch"] += 1; return result
  with patch.object(f["ledger"], "finish", finish_then_tighten): result = conclude(f, begin)
  assert result["permit"] is None and result["reason_code"] == "discarded"
  # 传输结论仍是有效模型allow，授权结论单独是discarded，不改写历史模型质量。
  assert f["ledger"].get(f["prepared"]["operation_id"])["decision"] == "allow"


@pytest.mark.parametrize("change", ["source", "permit", "binding", "reason", "duplicate", "literal", "unicode"])
def test_model_claims_malformed_or_wrong_binding_never_become_authority(tmp_path, change):
  f = fixture(tmp_path); begin = dispatch(f); raw = wire(begin); parsed = json.loads(raw)
  if change == "source": parsed["source"] = "human"
  elif change == "permit": parsed["permit"] = {"allow": True}
  elif change == "binding": parsed["operation_digest"] = "f" * 64
  elif change == "reason": parsed["reason_code"] = "please execute SYNTHETIC_SECRET"
  elif change == "duplicate": raw = raw.replace('"schema_version": 1', '"schema_version": 1,"schema_version": 1')
  elif change == "literal": raw = raw.replace('"schema_version": 1', '"schema_version": 1.0000000000000000001')
  else: raw = raw.replace('"authorized-in-scope"', '"\\ud800"')
  if change in ("source", "permit", "binding", "reason"): raw = json.dumps(parsed)
  result = f["control"].conclude(begin["ticket"], {"outcome": "valid", "requests": 1, "response": raw})
  assert result["permit"] is None and result["reason_code"] == "protocol-failure"
  assert "SYNTHETIC_SECRET" not in json.dumps(result)


def test_capability_is_object_identity_and_does_not_invoke_caller_hash(tmp_path):
  f = fixture(tmp_path); begin = f["control"].begin(f["prepared"]["operation_id"])
  class Hostile:
    def __hash__(self): raise AssertionError("caller hash executed")
  for token in (object(), "3" * 32, {}, Hostile()):
    with pytest.raises(Conflict, match="REVIEW_CAPABILITY_UNKNOWN"): f["control"].commit_send(token)
  f["control"].commit_send(begin["ticket"])


def test_concurrent_begins_start_exactly_one_model_attempt(tmp_path):
  f = fixture(tmp_path)
  def begin(_):
    try: return f["control"].begin(f["prepared"]["operation_id"])
    except Conflict: return None
  with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(begin, range(24)))
  assert sum(value is not None for value in results) == 1
  assert f["ledger"].snapshot()["record_count"] == 1


def test_concurrent_valid_results_issue_only_one_original_permit(tmp_path):
  f = fixture(tmp_path); begin = dispatch(f)
  def result(_):
    try: return conclude(f, begin)
    except Conflict: return None
  with ThreadPoolExecutor(max_workers=8) as pool: results = list(pool.map(result, range(24)))
  assert sum(value is not None and value["permit"] is not None for value in results) == 1


def test_budget_denial_and_lost_start_receipt_make_zero_new_dispatch(tmp_path):
  f = fixture(tmp_path, max_calls=0)
  with pytest.raises(Conflict, match="REVIEW_BUDGET_EXHAUSTED"): f["control"].begin(f["prepared"]["operation_id"])
  assert f["ledger"].snapshot()["record_count"] == 0
  f = fixture(tmp_path / "second"); f["control"].begin(f["prepared"]["operation_id"])
  replaced = ReviewerDecisionControl(f["admissions"], f["ledger"], **f["config"])
  with pytest.raises(Conflict, match="REVIEW_ATTEMPT_ALREADY_CLAIMED"): replaced.begin(f["prepared"]["operation_id"])


def test_failed_decision_commit_never_issues_or_retries_permit(tmp_path):
  f = fixture(tmp_path); begin = dispatch(f)
  with patch.object(f["ledger"], "finish", side_effect=OSError("synthetic disk failure")):
    with pytest.raises(OSError): conclude(f, begin)
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"] == "revoked"
  with pytest.raises(Conflict, match="REVIEW_DECISION_ALREADY_SETTLED"): conclude(f, begin)
  assert f["ledger"].snapshot()["committed_calls"] == 1


@pytest.mark.parametrize("outcome", ["canceled", "timeout", "transport-failure", "protocol-failure", "discarded"])
def test_sent_failure_remains_one_request_and_no_permission(tmp_path, outcome):
  f = fixture(tmp_path); begin = dispatch(f)
  result = f["control"].conclude(begin["ticket"], {"outcome": outcome, "requests": 1, "response": None})
  assert result["permit"] is None and result["source"] == "system-failure"
  assert f["ledger"].snapshot()["observed_requests"] == 1
  assert f["ledger"].snapshot()["reserved_cost_units"] == 120


def test_prepared_view_returns_original_copy_and_refuses_terminal(tmp_path):
  f = fixture(tmp_path); view = f["admissions"].prepared(f["prepared"]["operation_id"])
  view["context"]["cwd"] = "/elsewhere"
  assert f["admissions"].prepared(f["prepared"]["operation_id"]) == f["prepared"]
  f["admissions"].revoke(f["prepared"]["operation_id"])
  with pytest.raises(Conflict, match="OPERATION_NOT_PENDING"): f["admissions"].prepared(f["prepared"]["operation_id"])


def test_live_qualifier_exit_after_result_before_issue_produces_no_permit(tmp_path):
  live = [True]; calls = []
  def hook(prepared, current):
    calls.append(True); return live[0]
  f = fixture(tmp_path, reviewer_current=hook); begin = dispatch(f); original = deepcopy(f["current"])
  live[0] = False
  result = conclude(f, begin)
  assert result["permit"] is None and result["source"] == "system-failure"
  assert f["current"] == original and calls == [True]
  assert f["admissions"].status(f["prepared"]["operation_id"])["state"] == "revoked"


def test_live_qualifier_exit_after_decision_permit_blocks_consumption_once(tmp_path):
  live = [True]
  f = fixture(tmp_path, reviewer_current=lambda prepared, current: live[0]); begin = dispatch(f)
  permit = conclude(f, begin)["permit"]; original = deepcopy(f["current"]); executions = []
  live[0] = False
  with pytest.raises(Conflict, match="OPERATION_REVIEWER_UNQUALIFIED"):
    executions.append(f["admissions"].consume(permit, current=f["current"], resolved=f["resolved"]))
  assert executions == [] and f["current"] == original
  live[0] = True
  with pytest.raises(Conflict, match="PERMIT_USED"):
    f["admissions"].consume(permit, current=f["current"], resolved=f["resolved"])
  with pytest.raises(Conflict, match="NOT_PENDING"):
    f["admissions"].issue(f["prepared"]["operation_id"], operation_digest=f["prepared"]["operation_digest"],
      current=f["current"], source="reviewer", reviewer_identity="9" * 64)
