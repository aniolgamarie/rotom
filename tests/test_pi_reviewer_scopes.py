"""真实临时私有范围表、authority与短锁；不启动SDK/模型/进程。"""
from copy import deepcopy
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import pi_reviewer_scopes as module
from agentcfg.pi_reviewer_scopes import ReviewerScopeStore
from agentcfg.pi_reviewer_authority import ReviewerAuthorityStore
from agentcfg.pi_reviewer_account import ReviewerAccountLedger
from agentcfg.pi_registered_roots import RegisteredRoots
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from test_pi_reviewer_account_authority import document


SESSION = "1" * 32
CONFIRM = "2" * 32


def fixture(tmp_path, *, initialized=True, max_records=4096):
  home = tmp_path / "account"; home.mkdir(mode=0o700)
  authority = ReviewerAuthorityStore(account_home=home); snapshot = authority.create(document()); clock = [150]
  store = ReviewerScopeStore(account_home=home, authority_identity=snapshot["identity"], now=lambda: clock[0], max_records=max_records)
  if initialized: store.initialize()
  return {"home": home, "authority": authority, "authority_snapshot": snapshot, "clock": clock, "store": store,
    "directory": home / ".agentcfg-workspaces/reviewer-scopes", "file": home / ".agentcfg-workspaces/reviewer-scopes/scopes.json",
    "max_records": max_records}


def reopen(f, *, authorized=True):
  kwargs = {"account_home": f["home"], "max_records": f["max_records"]}
  if authorized: kwargs.update(authority_identity=f["authority_snapshot"]["identity"], now=lambda: f["clock"][0])
  return ReviewerScopeStore(**kwargs)


def refs(f, *, activation=SESSION, confirmation=CONFIRM, tool="SYNTHETIC_PRIVATE_TOOL"):
  session = f["store"].allocate_session(activation)
  intent = f["store"].allocate_intent(session, confirmation)
  request = f["store"].allocate_request({**intent, "tool_call_id": tool})
  return {**intent, "request_ref": request}


def counts(sessions=0, intents=0, requests=0, retired_sessions=0, retired_intents=0):
  return {"sessions": sessions, "intents": intents, "requests": requests, "retired_sessions": retired_sessions, "retired_intents": retired_intents}


def test_constructor_and_snapshot_never_create_missing_control_root(tmp_path):
  home = tmp_path / "empty-account"; home.mkdir(mode=0o700)
  store = ReviewerScopeStore(account_home=home)
  assert list(home.iterdir()) == []
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RECOVERY_REQUIRED"): store.snapshot()
  assert list(home.iterdir()) == []


def test_first_bootstrap_private_modes_and_reopen_stable_mappings(tmp_path):
  f = fixture(tmp_path, initialized=False)
  assert not f["directory"].exists()
  assert f["store"].initialize() == counts()
  assert f["directory"].stat().st_mode & 0o777 == 0o700 and f["file"].stat().st_mode & 0o777 == 0o600
  before = refs(f); saved = f["file"].read_bytes()
  fresh = reopen(f); f["store"] = fresh
  assert refs(f) == before and f["file"].read_bytes() == saved and fresh.verify_current(before) is True
  assert fresh.snapshot() == counts(1, 1, 1)
  public = json.dumps(fresh.snapshot())
  assert "SYNTHETIC_PRIVATE_TOOL" not in public and before["request_ref"] not in public
  with pytest.raises(Conflict, match="REVIEW_SCOPE_EXISTS"): fresh.initialize()


def test_ids_are_distinct_and_tool_mapping_is_only_within_original_intent(tmp_path):
  f = fixture(tmp_path); first = refs(f)
  second = refs(f, confirmation="3" * 32)
  third = refs(f, activation="4" * 32, confirmation="5" * 32)
  assert first["session_scope"] == second["session_scope"] and first["intent_ref"] != second["intent_ref"]
  assert len(set([first["session_scope"], first["intent_ref"], first["request_ref"], second["intent_ref"], second["request_ref"], *third.values()])) == 8
  for value in (first, second, third): assert f["store"].verify_current(value) is True
  assert f["store"].snapshot() == counts(2, 3, 3)


def test_private_confirmation_nonce_cannot_be_rebound_to_second_session(tmp_path):
  f = fixture(tmp_path); first = refs(f); other = f["store"].allocate_session("3" * 32); before = f["file"].read_bytes()
  with pytest.raises(Conflict, match="REVIEW_SCOPE_NONCE_CONFLICT"): f["store"].allocate_intent(other, CONFIRM)
  assert f["file"].read_bytes() == before and f["store"].verify_current(first) is True


@pytest.mark.parametrize("target", ["session", "intent"])
def test_retirement_is_permanent_even_after_reopen_and_authority_missing(tmp_path, target):
  f = fixture(tmp_path); value = refs(f)
  (f["home"] / ".agentcfg-workspaces/reviewer-authority.json").unlink()
  unbound = reopen(f, authorized=False)
  retire = lambda: unbound.retire_session(value["session_scope"]) if target == "session" else unbound.retire_intent(value["session_scope"], value["intent_ref"])
  expected = counts(1, 1, 1, int(target == "session"), int(target == "intent"))
  assert retire() == expected
  before = f["file"].read_bytes(); assert retire() == expected and f["file"].read_bytes() == before
  fresh = reopen(f, authorized=False); assert fresh.snapshot() == expected
  with pytest.raises(Conflict, match="REVIEW_SCOPE_AUTHORITY_REQUIRED"): fresh.verify_current(value)
  # 恢复authority后以新live身份重新授权，旧scope/nonce仍不可复活。
  path = f["home"] / ".agentcfg-workspaces/reviewer-authority.json"; path.write_text(json.dumps(document())); path.chmod(0o600)
  latest = f["authority"].read()
  active = ReviewerScopeStore(account_home=f["home"], authority_identity=latest["identity"], now=lambda: 150)
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"): active.verify_current(value)
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"):
    active.allocate_session(SESSION) if target == "session" else active.allocate_intent(value["session_scope"], CONFIRM)
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RETIRED"): active.allocate_request({"session_scope": value["session_scope"], "intent_ref": value["intent_ref"], "tool_call_id": "new"})
  assert active.snapshot() == expected


def test_unbound_store_may_snapshot_and_retire_but_not_grant(tmp_path):
  f = fixture(tmp_path); value = refs(f); unbound = reopen(f, authorized=False); before = f["file"].read_bytes()
  for call in (unbound.initialize, lambda: unbound.allocate_session("3" * 32), lambda: unbound.allocate_intent(value["session_scope"], "4" * 32),
      lambda: unbound.allocate_request({"session_scope": value["session_scope"], "intent_ref": value["intent_ref"], "tool_call_id": "other"}), lambda: unbound.verify_current(value)):
    with pytest.raises(Conflict, match="REVIEW_SCOPE_AUTHORITY_REQUIRED"): call()
  assert unbound.snapshot() == counts(1, 1, 1) and f["file"].read_bytes() == before
  assert unbound.retire_intent(value["session_scope"], value["intent_ref"])["retired_intents"] == 1


@pytest.mark.parametrize("fault", ["empty-dir", "missing-table", "corrupt", "duplicate", "unknown", "bool-version", "mode", "dir-mode", "symlink-file", "hardlink", "symlink-dir", "replace-dir", "extra"])
def test_partial_or_untrusted_scope_state_is_never_reset(tmp_path, fault):
  f = fixture(tmp_path); value = refs(f); path = f["file"]; directory = f["directory"]
  if fault in ("empty-dir", "missing-table"): path.unlink()
  if fault == "corrupt": path.write_bytes(b'{"SYNTHETIC_PRIVATE":invalid}')
  if fault == "duplicate": path.write_bytes(path.read_bytes().replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'))
  if fault in ("unknown", "bool-version"):
    data = json.loads(path.read_bytes()); data["extra"] = "SYNTHETIC_PRIVATE" if fault == "unknown" else None
    if fault == "bool-version": data.pop("extra"); data["schema_version"] = True
    path.write_text(json.dumps(data))
  if fault == "mode": path.chmod(0o644)
  if fault == "dir-mode": directory.chmod(0o755)
  if fault == "symlink-file": path.rename(directory / "saved"); path.symlink_to(directory / "saved")
  if fault == "hardlink": os.link(path, f["home"] / "outside-link")
  if fault == "symlink-dir": directory.rename(directory.with_name("saved-scopes")); directory.symlink_to(directory.with_name("saved-scopes"))
  if fault == "replace-dir":
    raw = path.read_bytes(); directory.rename(f["home"] / "saved-scopes"); directory.mkdir(mode=0o700); path.write_bytes(raw); path.chmod(0o600)
  if fault == "extra": (directory / "extra").write_bytes(b"SYNTHETIC_PRIVATE")
  for controller in (f["store"], reopen(f)):
    with pytest.raises((Conflict, ConfigError)) as error: controller.snapshot()
    assert "SYNTHETIC_PRIVATE" not in str(error.value)
    with pytest.raises((Conflict, ConfigError)): controller.initialize()
    with pytest.raises((Conflict, ConfigError)): controller.verify_current(value)
  if fault in ("empty-dir", "missing-table"): assert not path.exists()


@pytest.mark.parametrize("fault", ["expired", "missing", "replace", "update"])
@pytest.mark.parametrize("method", ["session", "intent", "request", "verify"])
def test_every_grant_rechecks_actual_authority_without_scope_write(tmp_path, fault, method):
  f = fixture(tmp_path); value = refs(f); path = f["home"] / ".agentcfg-workspaces/reviewer-authority.json"
  if fault == "expired": f["clock"][0] = 200
  if fault == "missing": path.unlink()
  if fault == "replace":
    with Tree(path.parent) as tree:
      raw = tree.read(path.name); tree.replace(path.name, raw[0], expected=raw[2])
  if fault == "update":
    changed = document(); changed["generation"] = 2; changed["limits"]["max_calls"] = 1
    f["authority"].update(changed, expected_identity=f["authority_snapshot"]["identity"])
  before = f["file"].read_bytes()
  call = {"session": lambda: f["store"].allocate_session("6" * 32), "intent": lambda: f["store"].allocate_intent(value["session_scope"], "6" * 32),
    "request": lambda: f["store"].allocate_request({"session_scope": value["session_scope"], "intent_ref": value["intent_ref"], "tool_call_id": "next"}), "verify": lambda: f["store"].verify_current(value)}[method]
  with pytest.raises((Conflict, ConfigError)): call()
  assert f["file"].read_bytes() == before and reopen(f, authorized=False).snapshot() == counts(1, 1, 1)


@pytest.mark.parametrize("value", [True, 1, None, "a" * 31, "A" * 32, "SYNTHETIC_PRIVATE", "界" * 32])
def test_bad_refs_fail_before_any_scope_write(tmp_path, value):
  f = fixture(tmp_path); mapped = refs(f); before = f["file"].read_bytes()
  for call in (lambda: f["store"].allocate_session(value), lambda: f["store"].allocate_intent(mapped["session_scope"], value),
      lambda: f["store"].retire_session(value), lambda: f["store"].verify_current({**mapped, "request_ref": value})):
    with pytest.raises(ConfigError) as error: call()
    assert error.value.code == "PI_RISK_REVIEW_SCOPE_INVALID" and "SYNTHETIC_PRIVATE" not in str(error.value)
  assert f["file"].read_bytes() == before


@pytest.mark.parametrize("tool", [True, 1, None, "", "x" * 513, "界", "bad id", "bad\n", "bad\x00", "bad\ud800"])
def test_tool_id_is_bounded_graphic_ascii_and_never_leaks_error(tmp_path, tool):
  f = fixture(tmp_path); mapped = refs(f); before = f["file"].read_bytes()
  with pytest.raises(ConfigError): f["store"].allocate_request({"session_scope": mapped["session_scope"], "intent_ref": mapped["intent_ref"], "tool_call_id": tool})
  assert f["file"].read_bytes() == before


@pytest.mark.parametrize("kind", ["request", "verify"])
def test_unknown_binding_field_rejected_without_write(tmp_path, kind):
  f = fixture(tmp_path); mapped = refs(f); before = f["file"].read_bytes()
  value = {"session_scope": mapped["session_scope"], "intent_ref": mapped["intent_ref"], "tool_call_id": "sdk"} if kind == "request" else mapped
  value = {**value, "source": "human"}
  with pytest.raises(ConfigError): f["store"].allocate_request(value) if kind == "request" else f["store"].verify_current(value)
  assert f["file"].read_bytes() == before


def test_exact_capacity_includes_tombstones_and_full_table_idempotency(tmp_path, monkeypatch):
  f = fixture(tmp_path, max_records=3); value = refs(f); before = f["file"].read_bytes()
  with monkeypatch.context() as patch:
    patch.setattr(module.uuid, "uuid4", lambda: pytest.fail("idempotent lookup generated new ref"))
    assert refs(f) == value
  for call in (lambda: f["store"].allocate_session("3" * 32), lambda: f["store"].allocate_intent(value["session_scope"], "4" * 32),
      lambda: f["store"].allocate_request({"session_scope": value["session_scope"], "intent_ref": value["intent_ref"], "tool_call_id": "different"})):
    with pytest.raises(Conflict, match="REVIEW_SCOPE_CAPACITY"): call()
  assert f["file"].read_bytes() == before
  f["store"].retire_session(value["session_scope"])
  with pytest.raises(Conflict, match="REVIEW_SCOPE_CAPACITY"): f["store"].allocate_session("3" * 32)
  assert f["store"].snapshot() == counts(1, 1, 1, 1)


@pytest.mark.parametrize("invalid", [True, 0, 4097, None, 1.5])
def test_constructor_bad_capacity_before_account_lookup(monkeypatch, invalid):
  monkeypatch.setattr(module, "RegisteredRoots", lambda **_: pytest.fail("bad constructor queried account"))
  with pytest.raises(ConfigError): ReviewerScopeStore(max_records=invalid)


def test_existing_budget_never_bootstraps_missing_scope_table(tmp_path):
  f = fixture(tmp_path, initialized=False)
  ReviewerAccountLedger(account_home=f["home"], authority_identity=f["authority_snapshot"]["identity"], now=lambda: 150)
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RECOVERY_REQUIRED"): f["store"].initialize()
  assert not f["directory"].exists()


def test_scope_directory_prevents_recreation_of_missing_authority(tmp_path):
  f = fixture(tmp_path); (f["home"] / ".agentcfg-workspaces/reviewer-authority.json").unlink()
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_RECOVERY_REQUIRED"): f["authority"].create(document())
  assert not (f["home"] / ".agentcfg-workspaces/reviewer-authority.json").exists()


def test_real_busy_account_short_lock_preserves_table(tmp_path):
  f = fixture(tmp_path); value = refs(f); before = f["file"].read_bytes()
  roots = RegisteredRoots(account_home=f["home"])
  with roots._locked(write=True):
    with pytest.raises(Conflict, match="REVIEW_ACCOUNT_BUSY"): f["store"].allocate_session("3" * 32)
    with pytest.raises(Conflict, match="REVIEW_ACCOUNT_BUSY"): f["store"].verify_current(value)
  assert f["file"].read_bytes() == before


def test_uuid_generation_and_scope_write_hold_account_lock_against_update(tmp_path, monkeypatch):
  f = fixture(tmp_path); original = module.uuid.uuid4; calls = []
  def uuid():
    changed = document(); changed["generation"] = 2; changed["limits"]["max_calls"] = 1
    with pytest.raises(Conflict, match="REVIEW_ACCOUNT_BUSY"):
      f["authority"].update(changed, expected_identity=f["authority_snapshot"]["identity"])
    calls.append("busy"); return original()
  with monkeypatch.context() as patch:
    patch.setattr(module.uuid, "uuid4", uuid); value = refs(f)
  assert calls and f["store"].verify_current(value) is True
  assert f["authority"].read()["identity"] == f["authority_snapshot"]["identity"]


@pytest.mark.parametrize("after", [False, True])
@pytest.mark.parametrize("stage", ["session", "intent", "request"])
def test_allocate_ack_loss_fresh_reopen_never_returns_unconfirmed_reference(tmp_path, monkeypatch, after, stage):
  f = fixture(tmp_path); original = Tree.replace; captured = []; binding = None; session = None
  if stage != "session": session = f["store"].allocate_session(SESSION)
  if stage == "request": binding = {**f["store"].allocate_intent(session, CONFIRM), "tool_call_id": "SYNTHETIC_PRIVATE_TOOL"}
  before = f["store"].snapshot()
  def allocate(store):
    if stage == "session": return store.allocate_session(SESSION)
    if stage == "intent": return store.allocate_intent(session, CONFIRM)
    return store.allocate_request(binding)
  def replace(tree, path, raw, *args, **kwargs):
    if tree.root == f["directory"] and path == "scopes.json":
      value = json.loads(raw)
      captured.append(value["sessions"][SESSION]["session_scope"] if stage == "session" else
        {key: value["intents"][CONFIRM][key] for key in ("session_scope", "intent_ref")} if stage == "intent" else next(iter(value["requests"])))
      if after: original(tree, path, raw, *args, **kwargs)
      raise OSError("SYNTHETIC_PRIVATE_ACK")
    return original(tree, path, raw, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", replace)
    with pytest.raises(Conflict, match="REVIEW_SCOPE_WRITE_UNCONFIRMED") as error: allocate(f["store"])
    assert "SYNTHETIC_PRIVATE" not in str(error.value)
  fresh = reopen(f); expected = deepcopy(before)
  if after: expected[{"session": "sessions", "intent": "intents", "request": "requests"}[stage]] += 1
  assert fresh.snapshot() == expected
  if after:
    with monkeypatch.context() as patch:
      patch.setattr(module.uuid, "uuid4", lambda: pytest.fail("lost ack reallocated reference"))
      assert allocate(fresh) == captured[0]
  else: assert fresh.snapshot() == before


@pytest.mark.parametrize("after", [False, True])
def test_initialize_ack_loss_leaves_durable_directory_no_reset(tmp_path, monkeypatch, after):
  f = fixture(tmp_path, initialized=False); original = Tree.replace
  def replace(tree, path, raw, *args, **kwargs):
    if tree.root == f["directory"] and path == "scopes.json":
      if after: original(tree, path, raw, *args, **kwargs)
      raise OSError("SYNTHETIC_PRIVATE_ACK")
    return original(tree, path, raw, *args, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", replace)
    with pytest.raises(Conflict, match="REVIEW_SCOPE_WRITE_UNCONFIRMED"): f["store"].initialize()
  assert f["directory"].is_dir() and f["file"].exists() is after
  fresh = reopen(f)
  if after:
    assert fresh.snapshot() == counts()
    with pytest.raises(Conflict, match="REVIEW_SCOPE_EXISTS"): fresh.initialize()
  else:
    with pytest.raises(Conflict, match="REVIEW_SCOPE_RECOVERY_REQUIRED"): fresh.snapshot()
    with pytest.raises(Conflict, match="REVIEW_SCOPE_RECOVERY_REQUIRED"): fresh.initialize()
    assert not f["file"].exists()


@pytest.mark.parametrize("fault", ["session-row-extra", "retired-bool", "intent-foreign-session", "request-foreign-intent", "duplicate-tool", "colliding-ref", "identity-extra"])
def test_closed_persistent_graph_rejects_tampered_mappings(tmp_path, fault):
  f = fixture(tmp_path); value = refs(f); data = json.loads(f["file"].read_bytes())
  if fault == "session-row-extra": data["sessions"][SESSION]["secret"] = "SYNTHETIC_PRIVATE"
  if fault == "retired-bool": data["sessions"][SESSION]["retired"] = 0
  if fault == "intent-foreign-session": data["intents"][CONFIRM]["session_scope"] = "f" * 32
  if fault == "request-foreign-intent": data["requests"][value["request_ref"]]["intent_ref"] = "f" * 32
  if fault == "duplicate-tool": data["requests"]["f" * 32] = deepcopy(data["requests"][value["request_ref"]])
  if fault == "colliding-ref": data["intents"][CONFIRM]["intent_ref"] = value["session_scope"]
  if fault == "identity-extra": data["scopes_identity"]["secret"] = "SYNTHETIC_PRIVATE"
  f["file"].write_text(json.dumps(data)); before = f["file"].read_bytes()
  for controller in (f["store"], reopen(f)):
    with pytest.raises((ConfigError, Conflict)) as error: controller.snapshot()
    assert "SYNTHETIC_PRIVATE" not in str(error.value)
    with pytest.raises((ConfigError, Conflict)): controller.allocate_session("9" * 32)
  assert f["file"].read_bytes() == before


@pytest.mark.parametrize("mismatch", ["session", "intent", "request"])
def test_valid_reference_shape_does_not_authorize_foreign_mapping(tmp_path, mismatch):
  f = fixture(tmp_path); first = refs(f); second = refs(f, activation="3" * 32, confirmation="4" * 32)
  binding = deepcopy(first); binding[{"session": "session_scope", "intent": "intent_ref", "request": "request_ref"}[mismatch]] = second[{"session": "session_scope", "intent": "intent_ref", "request": "request_ref"}[mismatch]]
  before = f["file"].read_bytes()
  with pytest.raises(Conflict, match="REVIEW_SCOPE_UNKNOWN"): f["store"].verify_current(binding)
  assert f["file"].read_bytes() == before


def test_ref_collision_is_failure_without_retry_or_table_write(tmp_path, monkeypatch):
  f = fixture(tmp_path); value = refs(f); before = f["file"].read_bytes(); calls = []
  def collision(): calls.append(True); return SimpleNamespace(hex=value["request_ref"])
  with monkeypatch.context() as patch:
    patch.setattr(module.uuid, "uuid4", collision)
    with pytest.raises(Conflict, match="REVIEW_SCOPE_COLLISION"): f["store"].allocate_session("9" * 32)
  assert calls == [True] and f["file"].read_bytes() == before


def test_stale_authority_reopen_without_grant_can_still_retire(tmp_path):
  f = fixture(tmp_path); value = refs(f); changed = document(); changed["generation"] = 2
  f["authority"].update(changed, expected_identity=f["authority_snapshot"]["identity"])
  with pytest.raises(Conflict, match="REVIEW_AUTHORITY_STALE"): f["store"].verify_current(value)
  assert reopen(f, authorized=False).retire_session(value["session_scope"])["retired_sessions"] == 1


def test_parent_directory_fsync_lost_ack_leaves_empty_recovery_marker(tmp_path, monkeypatch):
  f = fixture(tmp_path, initialized=False); anchor = f["directory"].parent.stat(); original = module.os.fsync
  def fsync(fd):
    info = os.fstat(fd); original(fd)
    if (info.st_dev, info.st_ino) == (anchor.st_dev, anchor.st_ino): raise OSError("SYNTHETIC_PRIVATE_ACK")
  with monkeypatch.context() as patch:
    patch.setattr(module.os, "fsync", fsync)
    with pytest.raises(Conflict) as error: f["store"].initialize()
    assert "SYNTHETIC_PRIVATE" not in str(error.value)
  assert f["directory"].is_dir() and list(f["directory"].iterdir()) == []
  with pytest.raises(Conflict, match="REVIEW_SCOPE_RECOVERY_REQUIRED"): reopen(f).initialize()
  assert list(f["directory"].iterdir()) == []


def test_idempotent_fsync_failure_returns_no_ref_and_preserves_mapping(tmp_path, monkeypatch):
  f = fixture(tmp_path); session = f["store"].allocate_session(SESSION); info = f["file"].stat(); original = module.os.fsync
  before = f["file"].read_bytes(); returned = []
  def fsync(fd):
    current = os.fstat(fd)
    if (current.st_dev, current.st_ino) == (info.st_dev, info.st_ino): raise OSError("SYNTHETIC_PRIVATE_ACK")
    return original(fd)
  with monkeypatch.context() as patch:
    patch.setattr(module.os, "fsync", fsync)
    with pytest.raises(Conflict) as error: returned.append(f["store"].allocate_session(SESSION))
    assert "SYNTHETIC_PRIVATE" not in str(error.value)
  assert returned == [] and f["file"].read_bytes() == before
  assert reopen(f).allocate_session(SESSION) == session


def test_smaller_reopen_cap_preserves_existing_mapping_but_rejects_all_new_refs(tmp_path, monkeypatch):
  f = fixture(tmp_path); value = refs(f); before = f["file"].read_bytes()
  smaller = ReviewerScopeStore(account_home=f["home"], authority_identity=f["authority_snapshot"]["identity"],
    now=lambda: f["clock"][0], max_records=1)
  assert smaller.snapshot() == counts(1, 1, 1)
  with monkeypatch.context() as patch:
    patch.setattr(module.uuid, "uuid4", lambda: pytest.fail("smaller-cap idempotent lookup reallocated"))
    assert smaller.allocate_session(SESSION) == value["session_scope"]
    assert smaller.allocate_intent(value["session_scope"], CONFIRM) == {key: value[key] for key in ("session_scope", "intent_ref")}
    assert smaller.allocate_request({"session_scope": value["session_scope"], "intent_ref": value["intent_ref"], "tool_call_id": "SYNTHETIC_PRIVATE_TOOL"}) == value["request_ref"]
    assert smaller.verify_current(value) is True
  for call in (lambda: smaller.allocate_session("9" * 32),
      lambda: smaller.allocate_intent(value["session_scope"], "9" * 32),
      lambda: smaller.allocate_request({"session_scope": value["session_scope"], "intent_ref": value["intent_ref"], "tool_call_id": "new-tool"})):
    with pytest.raises(Conflict, match="REVIEW_SCOPE_CAPACITY"): call()
    assert f["file"].read_bytes() == before
  assert smaller.snapshot() == counts(1, 1, 1) and f["file"].read_bytes() == before
