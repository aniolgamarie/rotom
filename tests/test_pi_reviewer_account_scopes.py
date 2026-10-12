"""账户锁内的scope/发送提交组合；临时账户、合成发送事实、零SDK/进程。"""
from copy import deepcopy
import inspect
import json
import traceback

import pytest

from agentcfg.pi_reviewer_account import ReviewerAccountLedger
from agentcfg.pi_reviewer_ledger import ReviewerLedger
from agentcfg.pi_reviewer_scopes import ReviewerScopeStore
from agentcfg.pi_registered_roots import RegisteredRoots
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict
from test_pi_reviewer_scopes import fixture as scope_fixture, refs
from test_pi_reviewer_scopes_account import request


def bound(f):
  # 最终suite必须使用新模式；旧签名的条件仅存在于已保存行为红历史。
  assert "scope_required" in inspect.signature(ReviewerAccountLedger).parameters
  return ReviewerAccountLedger(account_home=f["home"], authority_identity=f["authority_snapshot"]["identity"],
    now=lambda: f["clock"][0], scope_required=True)


def setup(tmp_path):
  f = scope_fixture(tmp_path); f["refs"] = refs(f); f["ledger"] = bound(f)
  return f


def raw_budget(home):
  root = home / ".agentcfg-workspaces"
  return {name: (root / name).read_bytes() for name in
    ("reviewer-budget.json", "reviewer-budget/reviewer-ledger.json")}


def stage(f, name):
  op = request(f["refs"])["binding"]["operation_id"]
  if name != "reserve": f["ledger"].reserve(**request(f["refs"]))
  if name == "commit_send": f["ledger"].claim_attempt(op)
  return op


def invoke(f, name, op):
  return f["ledger"].reserve(**request(f["refs"])) if name == "reserve" else getattr(f["ledger"], name)(op)


def test_retire_after_scope_predicate_before_commit_rejects_without_budget_change(tmp_path):
  f = setup(tmp_path); op = stage(f, "commit_send")
  assert f["store"].verify_current(f["refs"]) is True
  f["store"].retire_intent(f["refs"]["session_scope"], f["refs"]["intent_ref"])
  before = raw_budget(f["home"])
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"): f["ledger"].commit_send(op)
  assert raw_budget(f["home"]) == before
  assert f["ledger"].snapshot()["committed_calls"] == 0


@pytest.mark.parametrize("invalid", [None, 0, 1, "true", {}, []])
def test_flag_type_and_missing_authority_fail_before_registered_roots(tmp_path, monkeypatch, invalid):
  def forbidden(*args, **kwargs): raise AssertionError("account lookup before configuration validation")
  monkeypatch.setattr(RegisteredRoots, "__init__", forbidden)
  with pytest.raises(ConfigError): ReviewerAccountLedger(scope_required=invalid)
  with pytest.raises(ConfigError): ReviewerAccountLedger(scope_required=True, limits={"currency": "USD", "max_calls": 1, "max_cost_units": 1})


@pytest.mark.parametrize("change", ["missing-directory", "missing-table", "corrupt", "mode", "replaced-directory"])
def test_bound_constructor_validates_scope_before_creating_money_budget(tmp_path, change):
  f = scope_fixture(tmp_path)
  if change == "missing-directory": f["file"].unlink(); f["directory"].rmdir()
  elif change == "missing-table": f["file"].unlink()
  elif change == "corrupt": f["file"].write_text("{invalid}")
  elif change == "mode": f["file"].chmod(0o644)
  else:
    old = f["directory"].with_name("old-scope")
    f["directory"].rename(old); f["directory"].mkdir(mode=0o700)
    (f["directory"] / "scopes.json").write_bytes((old / "scopes.json").read_bytes())
    (f["directory"] / "scopes.json").chmod(0o600)
    (old / "scopes.json").unlink(); old.rmdir()
  with pytest.raises((Conflict, ConfigError)): bound(f)
  anchor = f["home"] / ".agentcfg-workspaces"
  assert not (anchor / "reviewer-budget").exists() and not (anchor / "reviewer-budget.json").exists()


def test_scope_initialization_precedes_budget_and_empty_live_table_is_valid(tmp_path):
  f = scope_fixture(tmp_path, initialized=False)
  with pytest.raises(Conflict): bound(f)
  assert not (f["home"] / ".agentcfg-workspaces/reviewer-budget.json").exists()
  f["store"].initialize(); ledger = bound(f)
  assert ledger.snapshot()["record_count"] == 0
  assert f["store"].snapshot()["requests"] == 0


@pytest.mark.parametrize("name", ["reserve", "claim_attempt", "commit_send"])
@pytest.mark.parametrize("change", ["retire-intent", "retire-session", "missing-table", "corrupt-table"])
def test_each_money_authorization_checks_persisted_scope_without_budget_write(tmp_path, name, change):
  f = setup(tmp_path); op = stage(f, name)
  if change == "retire-intent": f["store"].retire_intent(f["refs"]["session_scope"], f["refs"]["intent_ref"])
  elif change == "retire-session": f["store"].retire_session(f["refs"]["session_scope"])
  elif change == "missing-table": f["file"].unlink()
  else: f["file"].write_text("{invalid}")
  before = raw_budget(f["home"])
  with pytest.raises((Conflict, ConfigError)) as caught: invoke(f, name, op)
  if change.startswith("retire"): assert str(caught.value) == "REVIEW_SCOPE_RETIRED"
  assert raw_budget(f["home"]) == before
  assert f["ledger"].snapshot()["committed_calls"] == 0


@pytest.mark.parametrize("field", ["session_scope", "intent_ref", "request_ref"])
def test_reserve_requires_all_three_original_request_refs(tmp_path, field):
  f = setup(tmp_path); wrong = deepcopy(f["refs"]); wrong[field] = "f" * 32
  before = raw_budget(f["home"])
  with pytest.raises(Conflict, match="REVIEW_SCOPE_UNKNOWN"): f["ledger"].reserve(**request(wrong))
  assert raw_budget(f["home"]) == before


def test_known_request_cannot_be_moved_to_another_live_intent(tmp_path):
  f = setup(tmp_path); other = f["store"].allocate_intent(f["refs"]["session_scope"], "5" * 32)
  foreign = {**other, "request_ref": f["refs"]["request_ref"]}; before = raw_budget(f["home"])
  with pytest.raises(Conflict): f["ledger"].reserve(**request(foreign))
  assert raw_budget(f["home"]) == before


def test_atomic_checker_does_not_reenter_public_scope_lock(tmp_path, monkeypatch):
  f = scope_fixture(tmp_path); f["refs"] = refs(f)
  def forbidden(*args, **kwargs): raise AssertionError("nested public scope lock")
  monkeypatch.setattr(ReviewerScopeStore, "verify_current", forbidden)
  ledger = bound(f); op = ledger.reserve(**request(f["refs"]))["binding"]["operation_id"]
  ledger.claim_attempt(op); ledger.commit_send(op)
  row = ledger.get(op)
  assert row["scope"] == {key: f["refs"][key] for key in ("session_scope", "intent_ref")}
  assert row["binding"]["request_id"] == f["refs"]["request_ref"]
  assert ledger.snapshot()["unknown_requests"] == 1


def test_commit_holds_same_account_lock_against_retirement_and_authority_update(tmp_path, monkeypatch):
  f = setup(tmp_path); op = stage(f, "commit_send"); original = ReviewerLedger.commit_send; observed = []
  def during_commit(ledger, operation_id):
    with pytest.raises(Conflict, match="REVIEW_ACCOUNT_BUSY"):
      f["store"].retire_intent(f["refs"]["session_scope"], f["refs"]["intent_ref"])
    updated = deepcopy(f["authority_snapshot"]["document"]); updated["generation"] += 1
    with pytest.raises(Conflict, match="REVIEW_ACCOUNT_BUSY"):
      f["authority"].update(updated, expected_identity=f["authority_snapshot"]["identity"])
    observed.append(operation_id)
    return original(ledger, operation_id)
  monkeypatch.setattr(ReviewerLedger, "commit_send", during_commit)
  f["ledger"].commit_send(op); assert observed == [op]
  f["store"].retire_intent(f["refs"]["session_scope"], f["refs"]["intent_ref"])
  assert f["ledger"].snapshot()["unknown_requests"] == 1
  assert f["ledger"].snapshot()["reserved_cost_units"] == 320
  # commit是线性化点；之后退役不把已commit请求或预留清零。
  facts = ReviewerAccountLedger.for_settlement(account_home=f["home"])
  facts.mark_sent(op); facts.finish(op, requests=1, outcome="canceled")
  facts.record_usage(op, {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
  assert facts.get(op)["requests"] == 1 and facts.get(op)["outcome"] == "canceled"
  assert facts.snapshot()["reserved_cost_units"] == 320


def test_default_false_mode_remains_independent_offline_component(tmp_path):
  f = scope_fixture(tmp_path, initialized=False)
  ledger = ReviewerAccountLedger(account_home=f["home"], authority_identity=f["authority_snapshot"]["identity"], now=lambda: 150)
  made_up = {"session_scope": "d" * 32, "intent_ref": "e" * 32, "request_ref": "f" * 32}
  op = ledger.reserve(**request(made_up))["binding"]["operation_id"]
  ledger.claim_attempt(op); ledger.commit_send(op)
  assert ledger.snapshot()["committed_calls"] == 1 and not f["directory"].exists()


@pytest.mark.parametrize("name", ["claim_attempt", "commit_send"])
def test_claim_and_commit_read_original_row_request_ref_from_current_table(tmp_path, name):
  f = setup(tmp_path); op = stage(f, name)
  # 表仍闭合合法，但原row的request_ref已经不在当前表；不能只验session/intent。
  table = json.loads(f["file"].read_bytes()); del table["requests"][f["refs"]["request_ref"]]
  f["file"].write_text(json.dumps(table)); before = raw_budget(f["home"])
  with pytest.raises(Conflict, match="REVIEW_SCOPE_UNKNOWN"): invoke(f, name, op)
  assert raw_budget(f["home"]) == before


def test_unknown_scope_checker_error_suppresses_private_traceback_chain(tmp_path, monkeypatch):
  from agentcfg import pi_reviewer_account as account
  f = setup(tmp_path); before = raw_budget(f["home"])
  marker = "synthetic-private" + "-token-trace-canary"
  def fail(*args, **kwargs):
    raise RuntimeError(marker)
  monkeypatch.setattr(account, "_check_scope_binding", fail)
  with pytest.raises(Conflict, match="^REVIEW_ACCOUNT_INVALID$") as caught:
    f["ledger"].reserve(**request(f["refs"]))
  rendered = "".join(traceback.format_exception(caught.value))
  assert raw_budget(f["home"]) == before
  assert marker not in rendered
