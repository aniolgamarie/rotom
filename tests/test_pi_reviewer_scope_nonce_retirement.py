"""分配回执未知时按原私有nonce退役；临时账户，无宿主/模型/进程。"""
import json

import pytest

from agentcfg import pi_reviewer_scopes as module
from agentcfg.pi_reviewer_scopes import ReviewerScopeStore
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_reviewer_scopes import fixture, reopen, refs, counts, SESSION, CONFIRM


def test_retirement_before_delayed_session_allocation_is_durable(tmp_path):
  f = fixture(tmp_path)
  assert f["store"].retire_session_activation(SESSION) == counts(1, retired_sessions=1)
  before = f["file"].read_bytes()
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"):
    reopen(f).allocate_session(SESSION)
  assert f["file"].read_bytes() == before


def test_retirement_before_delayed_confirmation_prevents_new_permission(tmp_path):
  f = fixture(tmp_path); session = f["store"].allocate_session(SESSION)
  assert f["store"].retire_intent_confirmation(session, CONFIRM) == counts(1, 1, retired_intents=1)
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"):
    reopen(f).allocate_intent(session, CONFIRM)
  assert reopen(f).allocate_intent(session, "3" * 32)["session_scope"] == session


@pytest.mark.parametrize("kind", ["session", "intent"])
def test_lost_allocation_ack_can_be_retired_without_returned_ref(tmp_path, monkeypatch, kind):
  f = fixture(tmp_path)
  session = f["store"].allocate_session(SESSION) if kind == "intent" else None
  original = Tree.replace
  def lost_ack(tree, path, raw, **kwargs):
    result = original(tree, path, raw, **kwargs)
    if tree.root == f["directory"]: raise OSError("SYNTHETIC_PRIVATE_LOST_ACK")
    return result
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", lost_ack)
    with pytest.raises(Conflict, match="REVIEW_SCOPE_WRITE_UNCONFIRMED") as failure:
      if kind == "session": f["store"].allocate_session(SESSION)
      else: f["store"].allocate_intent(session, CONFIRM)
    assert "SYNTHETIC_PRIVATE" not in str(failure.value)
  if kind == "session":
    assert reopen(f).retire_session_activation(SESSION) == counts(1, retired_sessions=1)
    with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"): reopen(f).allocate_session(SESSION)
  else:
    assert reopen(f).retire_intent_confirmation(session, CONFIRM) == counts(1, 1, retired_intents=1)
    with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"): reopen(f).allocate_intent(session, CONFIRM)


@pytest.mark.parametrize("kind", ["session", "intent"])
def test_retirement_does_not_need_live_authority_and_never_grants(tmp_path, kind):
  f = fixture(tmp_path); session = f["store"].allocate_session(SESSION) if kind == "intent" else None
  f["clock"][0] = 100000
  private = ReviewerScopeStore(account_home=f["home"])
  if kind == "session": private.retire_session_activation(SESSION)
  else: private.retire_intent_confirmation(session, CONFIRM)
  value = json.loads(f["file"].read_text())
  assert value["requests"] == {}
  rows = value["sessions"] if kind == "session" else value["intents"]
  assert len(rows) == 1 and all(row["retired"] is True for row in rows.values())
  with pytest.raises(Conflict, match="REVIEW_SCOPE_AUTHORITY_REQUIRED"):
    private.allocate_session(SESSION)


@pytest.mark.parametrize("kind", ["session", "intent"])
def test_nonce_retirement_reuses_existing_row_without_evicting_request(tmp_path, monkeypatch, kind):
  f = fixture(tmp_path); binding = refs(f)
  call = (lambda store: store.retire_session_activation(SESSION)) if kind == "session" else (
    lambda store: store.retire_intent_confirmation(binding["session_scope"], CONFIRM))
  expected = counts(1, 1, 1, retired_sessions=int(kind == "session"), retired_intents=int(kind == "intent"))
  with monkeypatch.context() as patch:
    patch.setattr(ReviewerScopeStore, "_ReviewerScopeStore__new_ref", lambda *args: pytest.fail("retirement allocated a second reference"))
    assert call(f["store"]) == expected
    before = f["file"].read_bytes()
    assert call(reopen(f)) == expected and f["file"].read_bytes() == before
  assert json.loads(before)["requests"][binding["request_ref"]]["tool_call_id"] == "SYNTHETIC_PRIVATE_TOOL"
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"): reopen(f).verify_current(binding)


def test_confirmation_nonce_cannot_retire_another_session(tmp_path):
  f = fixture(tmp_path); binding = refs(f); other = f["store"].allocate_session("3" * 32)
  before = f["file"].read_bytes()
  with pytest.raises(Conflict, match="REVIEW_SCOPE_NONCE_CONFLICT"):
    f["store"].retire_intent_confirmation(other, CONFIRM)
  assert f["file"].read_bytes() == before and f["store"].verify_current(binding) is True
  with pytest.raises(Conflict, match="REVIEW_SCOPE_UNKNOWN"):
    f["store"].retire_intent_confirmation("9" * 32, "8" * 32)
  assert f["file"].read_bytes() == before


@pytest.mark.parametrize("kind", ["session", "intent"])
def test_failed_tombstone_ack_is_unknown_and_retry_confirms_same_tombstone(tmp_path, monkeypatch, kind):
  f = fixture(tmp_path); session = f["store"].allocate_session(SESSION) if kind == "intent" else None
  original = Tree.replace
  def lost_ack(tree, path, raw, **kwargs):
    result = original(tree, path, raw, **kwargs)
    if tree.root == f["directory"]: raise OSError("SYNTHETIC_PRIVATE_TOMBSTONE_ACK")
    return result
  call = (lambda store: store.retire_session_activation(SESSION)) if kind == "session" else (
    lambda store: store.retire_intent_confirmation(session, CONFIRM))
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", lost_ack)
    with pytest.raises(Conflict, match="REVIEW_SCOPE_WRITE_UNCONFIRMED"): call(f["store"])
  before = f["file"].read_bytes()
  call(reopen(f))
  assert f["file"].read_bytes() == before


@pytest.mark.parametrize("kind", ["session", "intent"])
def test_missing_scope_file_is_not_bootstrapped_by_retirement(tmp_path, kind):
  f = fixture(tmp_path, initialized=False)
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RECOVERY_REQUIRED"):
    if kind == "session": f["store"].retire_session_activation(SESSION)
    else: f["store"].retire_intent_confirmation("1" * 32, CONFIRM)
  assert not f["directory"].exists()


def test_capacity_limits_new_tombstones_but_allows_existing_retirement(tmp_path):
  f = fixture(tmp_path, max_records=2); binding = f["store"].allocate_intent(f["store"].allocate_session(SESSION), CONFIRM)
  before = f["file"].read_bytes()
  for call in (lambda: f["store"].retire_session_activation("3" * 32),
      lambda: f["store"].retire_intent_confirmation(binding["session_scope"], "4" * 32)):
    with pytest.raises(Conflict, match="REVIEW_SCOPE_CAPACITY"): call()
    assert f["file"].read_bytes() == before
  assert f["store"].retire_intent_confirmation(binding["session_scope"], CONFIRM) == counts(1, 1, retired_intents=1)


@pytest.mark.parametrize("invalid", [None, True, 1, "", "f" * 31, "g" * 32, "F" * 32, "f" * 33])
def test_invalid_nonce_has_no_write(tmp_path, invalid):
  f = fixture(tmp_path); session = f["store"].allocate_session(SESSION); before = f["file"].read_bytes()
  for call in (lambda: f["store"].retire_session_activation(invalid),
      lambda: f["store"].retire_intent_confirmation(session, invalid),
      lambda: f["store"].retire_intent_confirmation(invalid, CONFIRM)):
    with pytest.raises(ConfigError): call()
    assert f["file"].read_bytes() == before
