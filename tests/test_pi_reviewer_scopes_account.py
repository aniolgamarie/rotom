"""持久scope/预算组合；临时账户与合成发送事实，不启动进程/SDK。"""
from copy import deepcopy

import pytest

from agentcfg.pi_reviewer_account import ReviewerAccountLedger
from agentcfg.pi_reviewer_authority import ReviewerAuthorityStore
from agentcfg.pi_reviewer_authority_protocol import price_identity, RATES
from agentcfg.pi_reviewer_scopes import ReviewerScopeStore
from agentcfg.storage import Conflict


def document():
  return {"schema_version": 1, "authority_ref": "a" * 32, "generation": 1,
    "route": {"logical_provider": "synthetic", "native_route": "synthetic", "model_id": "synthetic-model",
      "auth_kind": "api-key", "owner": "pi-environment", "api": "openai-completions", "base_url": "https://synthetic.invalid/v1"},
    "pricing": {"revision": "b" * 32, "currency": "USD", "input_units_per_million": 1000000,
      "output_units_per_million": 2000000, "cache_read_units_per_million": 500000,
      "cache_write_units_per_million": 3000000, "source": "https://synthetic.invalid/pricing", "checked_on": "2026-10-05"},
    "limits": {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000},
    "token_limits": {"input_tokens": 100, "output_tokens": 10},
    "categories": ["file-read", "file-write", "shell"], "valid_from": 100, "valid_until": 200}


def setup(tmp_path):
  home = tmp_path / "account"; home.mkdir(mode=0o700)
  authority = ReviewerAuthorityStore(account_home=home)
  grant = authority.create(document()); clock = [150]
  scopes = ReviewerScopeStore(account_home=home, authority_identity=grant["identity"], now=lambda: clock[0])
  scopes.initialize()
  session = scopes.allocate_session("1" * 32)
  intent = scopes.allocate_intent(session, "2" * 32)
  binding = {**intent, "request_ref": scopes.allocate_request({**intent, "tool_call_id": "original-tool"})}
  ledger = ReviewerAccountLedger(account_home=home, authority_identity=grant["identity"], now=lambda: clock[0])
  return home, authority, grant, clock, scopes, binding, ledger


def request(binding, index=1, *, authority=None):
  value = document() if authority is None else authority
  return {"binding": {"operation_id": f"{index:032x}", "request_id": binding["request_ref"],
      "operation_digest": "a" * 64, "context_digest": "b" * 64, "reviewer_identity": "c" * 64},
    "scope": {key: binding[key] for key in ("session_scope", "intent_ref")},
    "pricing": {"identity": price_identity(value), "currency": value["pricing"]["currency"],
      **{key: value["pricing"][key] for key in RATES}}, "token_limits": deepcopy(value["token_limits"])}


def committed(ledger, binding):
  op = ledger.reserve(**request(binding))["binding"]["operation_id"]
  ledger.claim_attempt(op); ledger.commit_send(op)
  return op


def test_reopened_scope_uses_same_request_and_cannot_start_second_attempt(tmp_path):
  home, authority, grant, clock, scopes, binding, ledger = setup(tmp_path)
  op = committed(ledger, binding)
  reopened = ReviewerScopeStore(account_home=home, authority_identity=grant["identity"], now=lambda: clock[0])
  session = reopened.allocate_session("1" * 32)
  intent = reopened.allocate_intent(session, "2" * 32)
  ref = reopened.allocate_request({**intent, "tool_call_id": "original-tool"})
  assert {**intent, "request_ref": ref} == binding
  newer = ReviewerAccountLedger(account_home=home, authority_identity=grant["identity"], now=lambda: clock[0])
  assert newer.reserve(**request(binding))["binding"]["request_id"] == ref
  with pytest.raises(Conflict, match="REVIEW_ATTEMPT_ALREADY_CLAIMED"): newer.claim_attempt(op)
  with pytest.raises(Conflict, match="REVIEW_SEND_ALREADY_CLAIMED"): newer.commit_send(op)
  assert newer.snapshot()["unknown_requests"] == 1
  assert newer.snapshot()["reserved_cost_units"] == 320


@pytest.mark.parametrize("change", ["operation-id", "digest", "context", "route"])
def test_same_sdk_request_cannot_be_rebound_to_a_new_operation(tmp_path, change):
  home, authority, grant, clock, scopes, binding, ledger = setup(tmp_path)
  committed(ledger, binding)
  different = request(binding)
  field = {"operation-id": "operation_id", "digest": "operation_digest", "context": "context_digest", "route": "reviewer_identity"}[change]
  different["binding"][field] = "f" * (32 if field == "operation_id" else 64)
  with pytest.raises(Conflict, match="REVIEW_IDEMPOTENCY_CONFLICT"): ledger.reserve(**different)
  assert ledger.snapshot()["committed_calls"] == 1 and scopes.snapshot()["requests"] == 1


def test_new_tool_id_in_same_persisted_intent_cannot_evade_deny(tmp_path):
  home, authority, grant, clock, scopes, binding, ledger = setup(tmp_path)
  op = committed(ledger, binding)
  ledger.finish(op, requests=1, outcome="valid", decision="deny", reason_code="outside-user-scope")
  reopened = ReviewerScopeStore(account_home=home, authority_identity=grant["identity"], now=lambda: clock[0])
  ref = reopened.allocate_request({"session_scope": binding["session_scope"], "intent_ref": binding["intent_ref"], "tool_call_id": "equivalent-rewrite"})
  assert ref != binding["request_ref"]
  with pytest.raises(Conflict, match="REVIEW_INTENT_DENIED"):
    ledger.reserve(**request({**binding, "request_ref": ref}, 2))
  assert ledger.snapshot()["committed_calls"] == 1
  assert ledger.snapshot()["unknown_requests"] == 0


@pytest.mark.parametrize("retire", ["intent", "session"])
def test_retiring_confirmation_does_not_release_unknown_send_reservation(tmp_path, retire):
  home, authority, grant, clock, scopes, binding, ledger = setup(tmp_path)
  op = committed(ledger, binding)
  if retire == "intent": scopes.retire_intent(binding["session_scope"], binding["intent_ref"])
  else: scopes.retire_session(binding["session_scope"])
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"): scopes.verify_current(binding)
  assert ledger.get(op)["requests"] is None
  assert ledger.snapshot()["committed_calls"] == 1 and ledger.snapshot()["reserved_cost_units"] == 320
  ledger.mark_sent(op); ledger.finish(op, requests=1, outcome="canceled")
  assert ledger.get(op)["requests"] == 1 and ledger.snapshot()["reserved_cost_units"] == 320


def test_expiry_between_scope_allocation_and_budget_reserve_is_zero_send(tmp_path):
  home, authority, grant, clock, scopes, binding, ledger = setup(tmp_path)
  clock[0] = 200
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_INACTIVE"): ledger.reserve(**request(binding))
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_INACTIVE"): scopes.verify_current(binding)
  assert ledger.snapshot()["committed_calls"] == 0 and ledger.snapshot()["reserved_calls"] == 0
  assert scopes.snapshot()["requests"] == 1


def test_authority_tightening_preserves_scope_mapping_and_unknown_account_facts(tmp_path):
  home, authority, grant, clock, scopes, binding, ledger = setup(tmp_path)
  op = committed(ledger, binding)
  updated = document(); updated["generation"] = 2; updated["limits"]["max_calls"] = 0
  latest = authority.update(updated, expected_identity=grant["identity"])
  newer = ReviewerScopeStore(account_home=home, authority_identity=latest["identity"], now=lambda: clock[0])
  same = newer.allocate_request({"session_scope": binding["session_scope"], "intent_ref": binding["intent_ref"], "tool_call_id": "original-tool"})
  assert same == binding["request_ref"]
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_STALE"): scopes.verify_current(binding)
  newer.retire_intent(binding["session_scope"], binding["intent_ref"])
  facts = ReviewerAccountLedger.for_settlement(account_home=home)
  facts.mark_sent(op); facts.finish(op, requests=1, outcome="canceled")
  assert facts.snapshot()["committed_calls"] == 1 and facts.snapshot()["reserved_cost_units"] == 320


def test_missing_scope_directory_with_existing_budget_never_reinitializes(tmp_path):
  home, authority, grant, clock, scopes, binding, ledger = setup(tmp_path)
  path = home / ".agentcfg-workspaces/reviewer-scopes"
  (path / "scopes.json").unlink(); path.rmdir()
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RECOVERY_REQUIRED"): scopes.initialize()
  assert not path.exists() and ledger.snapshot()["committed_calls"] == 0
