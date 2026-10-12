"""授权与账户发送提交组合；只用临时账户和假时钟，不启动SDK或进程。"""
from copy import deepcopy

import pytest

from agentcfg.pi_reviewer_account import ReviewerAccountLedger
from agentcfg.pi_reviewer_authority import ReviewerAuthorityStore
from agentcfg.pi_reviewer_authority_protocol import price_identity, RATES
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree


def document():
  return {"schema_version": 1, "authority_ref": "a" * 32, "generation": 1,
    "route": {"logical_provider": "synthetic", "native_route": "synthetic",
      "model_id": "synthetic-model", "auth_kind": "api-key", "owner": "pi-environment",
      "api": "openai-completions", "base_url": "https://synthetic.invalid/v1"},
    "pricing": {"revision": "b" * 32, "currency": "USD", "input_units_per_million": 1000000,
      "output_units_per_million": 2000000, "cache_read_units_per_million": 500000,
      "cache_write_units_per_million": 3000000, "source": "https://synthetic.invalid/pricing",
      "checked_on": "2026-10-05"},
    "limits": {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000},
    "token_limits": {"input_tokens": 100, "output_tokens": 10},
    "categories": ["file-read", "file-write", "shell"], "valid_from": 100, "valid_until": 200}


def request(index=1, *, authority=None):
  value = document() if authority is None else authority
  return {"binding": {"operation_id": f"{index:032x}", "request_id": f"{index+100:032x}",
      "operation_digest": "a" * 64, "context_digest": "b" * 64, "reviewer_identity": "c" * 64},
    "scope": {"session_scope": "d" * 32, "intent_ref": f"{index:032x}"},
    "pricing": {"identity": price_identity(value), "currency": value["pricing"]["currency"],
      **{key: value["pricing"][key] for key in RATES}},
    "token_limits": deepcopy(value["token_limits"])}


def fixture(tmp_path):
  home = tmp_path / "account"; home.mkdir(mode=0o700)
  store = ReviewerAuthorityStore(account_home=home)
  snapshot = store.create(document()); clock = [150]
  ledger = ReviewerAccountLedger(account_home=home, authority_identity=snapshot["identity"], now=lambda: clock[0])
  return home, store, snapshot, clock, ledger


def budget_bytes(home):
  anchor = home / ".agentcfg-workspaces"
  return {str(path.relative_to(anchor)): path.read_bytes() for path in anchor.rglob("*")
    if path.is_file() and path.name != "reviewer-authority.json"}


def test_bound_ledger_uses_authority_as_only_limits_source(tmp_path):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  assert ledger.snapshot()["limits"] == document()["limits"]
  op = ledger.reserve(**request())["binding"]["operation_id"]
  ledger.claim_attempt(op); ledger.commit_send(op)
  assert ledger.get(op)["requests"] is None
  with pytest.raises(ConfigError):
    ReviewerAccountLedger(account_home=home, authority_identity=snapshot["identity"], limits=document()["limits"])


@pytest.mark.parametrize("stage", ["reserve", "claim_attempt", "commit_send"])
def test_changed_authority_blocks_old_grant_without_budget_write(tmp_path, stage):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  op = request()["binding"]["operation_id"]
  if stage != "reserve": ledger.reserve(**request())
  if stage == "commit_send": ledger.claim_attempt(op)
  updated = document(); updated["generation"] = 2; updated["limits"]["max_calls"] = 0
  store.update(updated, expected_identity=snapshot["identity"])
  before = budget_bytes(home)
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_STALE"):
    ledger.reserve(**request()) if stage == "reserve" else getattr(ledger, stage)(op)
  assert budget_bytes(home) == before


@pytest.mark.parametrize("when", [99, 200])
def test_expired_or_not_yet_active_grant_never_writes_budget(tmp_path, when):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  clock[0] = when; before = budget_bytes(home)
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_INACTIVE"): ledger.reserve(**request())
  assert budget_bytes(home) == before


@pytest.mark.parametrize("field", ["identity", "currency", "input_units_per_million", "output_units_per_million",
  "cache_read_units_per_million", "cache_write_units_per_million", "input_tokens", "output_tokens"])
def test_profile_or_request_cannot_override_authority_prices_or_caps(tmp_path, field):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  value = request()
  target = value["token_limits"] if field.endswith("tokens") else value["pricing"]
  target[field] = "f" * 64 if field == "identity" else "EUR" if field == "currency" else target[field] + 1
  before = budget_bytes(home)
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_REQUEST_MISMATCH"): ledger.reserve(**value)
  assert budget_bytes(home) == before


def test_late_facts_survive_update_and_new_controller_tightening(tmp_path):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  op = ledger.reserve(**request())["binding"]["operation_id"]
  ledger.claim_attempt(op); ledger.commit_send(op)
  updated = document(); updated["generation"] = 2; updated["limits"]["max_calls"] = 0
  latest = store.update(updated, expected_identity=snapshot["identity"])
  newer = ReviewerAccountLedger(account_home=home, authority_identity=latest["identity"], now=lambda: clock[0])
  assert newer.snapshot()["limits"]["max_calls"] == 0
  ledger.mark_sent(op)
  ledger.finish(op, requests=1, outcome="valid", decision="deny", reason_code="outside-user-scope")
  ledger.record_usage(op, {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
  row = newer.get(op)
  assert row["decision"] == "deny" and row["usage"]["total_tokens"] == 8
  assert row["pricing"] == request()["pricing"] and row["settled_units"] is None
  assert newer.snapshot()["committed_calls"] == 1 and newer.snapshot()["reserved_cost_units"] == 320


@pytest.mark.parametrize("change", ["expired", "missing", "corrupt"])
def test_settlement_preserves_sent_facts_without_live_authorization(tmp_path, change):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  op = ledger.reserve(**request())["binding"]["operation_id"]
  ledger.claim_attempt(op); ledger.commit_send(op)
  path = home / ".agentcfg-workspaces/reviewer-authority.json"
  if change == "expired": clock[0] = 200
  elif change == "missing": path.unlink()
  else: path.write_text("{invalid}")
  ledger.mark_sent(op); ledger.finish(op, requests=1, outcome="canceled")
  assert ledger.get(op)["requests"] == 1 and ledger.snapshot()["committed_calls"] == 1
  with pytest.raises((Conflict, ConfigError)): ledger.reserve(**request(2))


def test_identical_authority_replacement_revokes_old_grant(tmp_path):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  anchor = home / ".agentcfg-workspaces"
  with Tree(anchor) as tree:
    raw = tree.read("reviewer-authority.json")
    tree.replace("reviewer-authority.json", raw[0], expected=raw[2])
  before = budget_bytes(home)
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_STALE"): ledger.reserve(**request())
  assert budget_bytes(home) == before


def test_missing_authority_constructs_no_account_or_budget(tmp_path):
  home = tmp_path / "account"; home.mkdir(mode=0o700)
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_MISSING"):
    ReviewerAccountLedger(account_home=home, authority_identity="a" * 64, now=lambda: 150)
  assert list(home.iterdir()) == []


@pytest.mark.parametrize("stage", ["claim_attempt", "commit_send"])
def test_expiration_is_checked_again_at_each_grant(tmp_path, stage):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  op = ledger.reserve(**request())["binding"]["operation_id"]
  if stage == "commit_send": ledger.claim_attempt(op)
  clock[0] = 200; before = budget_bytes(home)
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_INACTIVE"): getattr(ledger, stage)(op)
  assert budget_bytes(home) == before


@pytest.mark.parametrize("field", ["input_units_per_million", "input_tokens", "output_tokens"])
def test_boolean_caps_or_prices_fail_before_any_budget_write(tmp_path, field):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  value = request()
  target = value["token_limits"] if field.endswith("tokens") else value["pricing"]
  target[field] = True; before = budget_bytes(home)
  with pytest.raises(ConfigError): ledger.reserve(**value)
  assert budget_bytes(home) == before


@pytest.mark.parametrize("kind", ["bad-identity", "bool-identity", "supplied-limits", "bad-clock"])
def test_invalid_binding_fails_before_account_query(tmp_path, monkeypatch, kind):
  import agentcfg.pi_reviewer_account as module
  called = []
  def roots(**kwargs): called.append(kwargs); raise AssertionError("account queried")
  monkeypatch.setattr(module, "RegisteredRoots", roots)
  kwargs = {"authority_identity": "a" * 64, "now": lambda: 150}
  if kind == "bad-identity": kwargs["authority_identity"] = "SYNTHETIC_PRIVATE"
  if kind == "bool-identity": kwargs["authority_identity"] = True
  if kind == "supplied-limits": kwargs["limits"] = document()["limits"]
  if kind == "bad-clock": kwargs["now"] = 150
  with pytest.raises(ConfigError) as caught: ReviewerAccountLedger(**kwargs)
  assert "SYNTHETIC_PRIVATE" not in str(caught.value) and called == []


def test_authority_update_and_send_commit_hold_same_account_lock(tmp_path, monkeypatch):
  import agentcfg.pi_reviewer_account as module
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  op = ledger.reserve(**request())["binding"]["operation_id"]
  ledger.claim_attempt(op)
  updated = document(); updated["generation"] = 2; updated["limits"]["max_calls"] = 0
  original = module.ReviewerLedger.commit_send; observations = []
  def commit(inner, operation_id):
    with pytest.raises(Conflict, match="REVIEW_ACCOUNT_BUSY"):
      store.update(updated, expected_identity=snapshot["identity"])
    observations.append("update-busy-during-commit")
    return original(inner, operation_id)
  with monkeypatch.context() as patch:
    patch.setattr(module.ReviewerLedger, "commit_send", commit)
    result = ledger.commit_send(op)
  assert result["requests"] is None and observations == ["update-busy-during-commit"]
  store.update(updated, expected_identity=snapshot["identity"])
  assert ledger.get(op)["send_state"] == "committed"
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_STALE"): ledger.commit_send(op)


def test_tightened_bound_controller_never_resets_unknown_reservation(tmp_path):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  op = ledger.reserve(**request())["binding"]["operation_id"]
  ledger.claim_attempt(op); ledger.commit_send(op)
  updated = document(); updated["generation"] = 2; updated["limits"]["max_cost_units"] = 1
  latest = store.update(updated, expected_identity=snapshot["identity"])
  newer = ReviewerAccountLedger(account_home=home, authority_identity=latest["identity"], now=lambda: clock[0])
  facts = newer.snapshot()
  assert facts["over_budget"] is True and facts["unknown_requests"] == 1
  assert facts["reserved_cost_units"] == 320 and newer.get(op)["settled_units"] is None
  with pytest.raises(Conflict, match="REVIEW_BUDGET_EXHAUSTED"): newer.reserve(**request(2, authority=updated))


@pytest.mark.parametrize("change", ["expired", "missing", "corrupt"])
def test_reopened_settlement_records_facts_without_new_send_capability(tmp_path, change):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  op = ledger.reserve(**request())["binding"]["operation_id"]
  ledger.claim_attempt(op); ledger.commit_send(op)
  path = home / ".agentcfg-workspaces/reviewer-authority.json"
  if change == "expired": clock[0] = 200
  elif change == "missing": path.unlink()
  else: path.write_text("{invalid}")
  before = budget_bytes(home)
  resumed = ReviewerAccountLedger.for_settlement(account_home=home)
  assert budget_bytes(home) == before
  resumed.mark_sent(op); resumed.finish(op, requests=1, outcome="timeout")
  resumed.record_usage(op, {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
  assert resumed.get(op)["usage"]["total_tokens"] == 8
  for method in ("reserve", "claim_attempt", "commit_send"):
    before = budget_bytes(home)
    with pytest.raises(Conflict, match="REVIEW_SETTLEMENT_ONLY"):
      resumed.reserve(**request(2)) if method == "reserve" else getattr(resumed, method)(op)
    assert budget_bytes(home) == before


def test_settlement_reopen_never_creates_missing_control_root(tmp_path):
  home = tmp_path / "account"; home.mkdir(mode=0o700)
  with pytest.raises(Conflict, match="REVIEW_ACCOUNT_RECOVERY_REQUIRED"):
    ReviewerAccountLedger.for_settlement(account_home=home)
  assert list(home.iterdir()) == []


def test_settlement_reopen_preserves_recovery_required_after_unknown_write(tmp_path):
  home, store, snapshot, clock, ledger = fixture(tmp_path)
  sentinel = home / ".agentcfg-workspaces/reviewer-budget.json"
  before = sentinel.read_bytes()
  sentinel.write_bytes(before.replace(b'"state":"ready"', b'"state":"updating"'))
  frozen = budget_bytes(home)
  with pytest.raises(Conflict, match="REVIEW_ACCOUNT_RECOVERY_REQUIRED"):
    ReviewerAccountLedger.for_settlement(account_home=home)
  assert budget_bytes(home) == frozen
