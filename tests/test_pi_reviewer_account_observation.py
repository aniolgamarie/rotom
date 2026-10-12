"""持久原请求的纯读取观察；临时账户、真实文件、零宿主/模型/网络。"""
import json

import pytest

from agentcfg.pi_registered_roots import RegisteredRoots
from agentcfg.pi_reviewer_account import ReviewerAccountLedger
from agentcfg.pi_reviewer_ledger import ReviewerLedger
from agentcfg.storage import Conflict, Tree
from test_pi_reviewer_account import create, request
from test_pi_reviewer_account_scopes import bound
from test_pi_reviewer_scopes import fixture as scope_fixture, refs
from test_pi_reviewer_scopes_account import request as scoped_request


def home(tmp_path):
  value = tmp_path / "account"
  value.mkdir(mode=0o700)
  return value


def files(account):
  root = account / ".agentcfg-workspaces"
  return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_ino,
    path.stat().st_mtime_ns, path.stat().st_ctime_ns) for path in root.rglob("*") if path.is_file()}


def prepared(tmp_path, state="reserved"):
  account = home(tmp_path)
  ledger = create(account)
  operation = ledger.reserve(**request())["binding"]["operation_id"]
  ledger.claim_attempt(operation)
  if state in ("committed", "sent", "finished"):
    ledger.commit_send(operation)
  if state in ("sent", "finished"):
    ledger.mark_sent(operation)
  if state == "finished":
    ledger.finish(operation, requests=1, outcome="canceled")
  return account, ledger, operation


@pytest.mark.parametrize("state,send_state,requests,outcome", [
  ("reserved", "reserved", 0, None), ("committed", "committed", None, None),
  ("sent", "committed", 1, None), ("finished", "committed", 1, "canceled")])
def test_observe_returns_original_facts_without_constructor_or_disk_mutation(tmp_path, monkeypatch,
    state, send_state, requests, outcome):
  account, ledger, operation = prepared(tmp_path, state)
  original = files(account)
  def forbidden(*args, **kwargs): raise AssertionError("observation wrote or constructed ledger")
  monkeypatch.setattr(Tree, "replace", forbidden)
  monkeypatch.setattr(ReviewerLedger, "__init__", forbidden)
  row = ledger.observe(operation)
  assert (row["send_state"], row["requests"], row["outcome"]) == (send_state, requests, outcome)
  assert row["binding"] == request()["binding"] and row["scope"] == request()["scope"]
  assert row["reservation_units"] > 0 and row["settled_units"] is None
  row["binding"]["request_id"] = "f" * 32
  assert ledger.observe(operation)["binding"] == request()["binding"]
  assert files(account) == original


@pytest.mark.parametrize("state", ["preparing", "updating", "missing-sentinel", "missing-ledger",
  "missing-budget", "bad-hash", "bad-ledger-identity", "ledger-mode", "lock-mode", "extra-budget-member"])
def test_observe_refuses_partial_or_changed_binding_without_repair(tmp_path, state):
  account, ledger, operation = prepared(tmp_path, "committed")
  root = account / ".agentcfg-workspaces"
  sentinel, budget = root / "reviewer-budget.json", root / "reviewer-budget"
  if state in ("preparing", "updating", "bad-hash", "bad-ledger-identity"):
    document = json.loads(sentinel.read_bytes())
    if state in ("preparing", "updating"): document["state"] = state
    if state == "bad-hash": document["ledger_sha256"] = "0" * 64
    if state == "bad-ledger-identity": document["ledger_identity"][0] += 1
    sentinel.write_text(json.dumps(document))
  if state == "missing-sentinel": sentinel.unlink()
  if state == "missing-ledger": (budget / "reviewer-ledger.json").unlink()
  if state == "missing-budget": budget.rename(account / "detached-budget")
  if state == "ledger-mode": (budget / "reviewer-ledger.json").chmod(0o644)
  if state == "lock-mode": (budget / "instance.lock").chmod(0o644)
  if state == "extra-budget-member": (budget / "unexpected").write_text("synthetic")
  original = files(account)
  with pytest.raises(Conflict): ledger.observe(operation)
  assert files(account) == original


def test_observe_of_unknown_request_never_creates_row_or_updates_sentinel(tmp_path):
  account, ledger, operation = prepared(tmp_path)
  original = files(account)
  with pytest.raises(Conflict, match="^REVIEW_UNKNOWN$"): ledger.observe("f" * 32)
  assert files(account) == original and ledger.observe(operation)["send_state"] == "reserved"


def test_observe_rejects_busy_account_without_mutation(tmp_path):
  account, ledger, operation = prepared(tmp_path)
  original = files(account)
  with RegisteredRoots(account_home=account)._locked(write=True):
    with pytest.raises(Conflict, match="^REVIEW_ACCOUNT_BUSY$"): ledger.observe(operation)
  assert files(account) == original


@pytest.mark.parametrize("change", ["expired-authority", "removed-authority", "corrupt-authority", "retired-intent"])
def test_observe_remains_facts_only_after_live_authority_or_scope_retires(tmp_path, change):
  f = scope_fixture(tmp_path)
  f["refs"] = refs(f)
  ledger = bound(f)
  operation = ledger.reserve(**scoped_request(f["refs"]))["binding"]["operation_id"]
  ledger.claim_attempt(operation); ledger.commit_send(operation)
  if change == "expired-authority": f["clock"][0] = 200
  if change == "removed-authority": (f["home"] / ".agentcfg-workspaces/reviewer-authority.json").unlink()
  if change == "corrupt-authority": (f["home"] / ".agentcfg-workspaces/reviewer-authority.json").write_text("{invalid}")
  if change == "retired-intent": f["store"].retire_intent(f["refs"]["session_scope"], f["refs"]["intent_ref"])
  original = files(f["home"])
  row = ledger.observe(operation)
  assert row["requests"] is None and row["send_state"] == "committed"
  assert row["scope"] == {key: f["refs"][key] for key in ("session_scope", "intent_ref")}
  assert row["binding"]["request_id"] == f["refs"]["request_ref"]
  assert row["settled_units"] is None and files(f["home"]) == original
  settlement = ReviewerAccountLedger.for_settlement(account_home=f["home"])
  assert settlement.observe(operation) == row and files(f["home"]) == original
  with pytest.raises(Conflict): settlement.commit_send(operation)
  assert files(f["home"]) == original


def test_observe_still_rejects_replaced_account_directory(tmp_path):
  account, ledger, operation = prepared(tmp_path)
  account.rename(tmp_path / "detached-account")
  account.mkdir(mode=0o700)
  with pytest.raises(Conflict): ledger.observe(operation)
  assert list(account.iterdir()) == []


@pytest.mark.parametrize("after_write", [False, True])
def test_commit_write_failure_is_observed_only_if_ready_was_preserved(tmp_path, monkeypatch, after_write):
  account, ledger, operation = prepared(tmp_path)
  original = ReviewerLedger.commit_send
  def fail(value, operation_id):
    if after_write: original(value, operation_id)
    raise OSError("synthetic-private-fault-marker")
  with monkeypatch.context() as scoped:
    scoped.setattr(ReviewerLedger, "commit_send", fail)
    with pytest.raises(Conflict): ledger.commit_send(operation)
  before = files(account)
  if after_write:
    with pytest.raises(Conflict, match="^REVIEW_ACCOUNT_RECOVERY_REQUIRED$"): ledger.observe(operation)
    raw = json.loads((account / ".agentcfg-workspaces/reviewer-budget/reviewer-ledger.json").read_bytes())
    assert raw["rows"][operation]["send_state"] == "committed"
    assert raw["rows"][operation]["requests"] is None
  else:
    row = ledger.observe(operation)
    assert row["send_state"] == "reserved" and row["requests"] == 0
  assert files(account) == before
