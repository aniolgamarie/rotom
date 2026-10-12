"""仅临时账户、真实私人文件和假故障，不加载SDK/账号/模型/进程。"""
from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import pi_reviewer_account as module
from agentcfg.pi_reviewer_account import ReviewerAccountLedger
from agentcfg.pi_registered_roots import RegisteredRoots
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict, Tree
from agentcfg.paths import PathError

LIMITS = {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000}


def request(index=1, intent=1):
  return {"binding": {"operation_id": f"{index:032x}", "request_id": f"{index+100:032x}",
    "operation_digest": "a" * 64, "context_digest": "b" * 64, "reviewer_identity": "c" * 64},
    "scope": {"session_scope": "d" * 32, "intent_ref": f"{intent:032x}"},
    "pricing": {"identity": "e" * 64, "currency": "USD", "input_units_per_million": 1000000,
      "output_units_per_million": 2000000, "cache_read_units_per_million": 500000, "cache_write_units_per_million": 3000000},
    "token_limits": {"input_tokens": 100, "output_tokens": 10}}


@pytest.fixture
def account(tmp_path):
  home = tmp_path / "account"
  home.mkdir(mode=0o700)
  return home


def budget(home):
  return home / ".agentcfg-workspaces/reviewer-budget"


def sentinel(home):
  return home / ".agentcfg-workspaces/reviewer-budget.json"


def create(home, **limits):
  return ReviewerAccountLedger(account_home=home, limits={**LIMITS, **limits})


def test_initialization_and_private_projection(account):
  value = create(account)
  assert value.snapshot()["record_count"] == 0
  assert value.snapshot()["product_gate"] is False
  assert json.loads(sentinel(account).read_bytes())["state"] == "ready"
  assert {p.name for p in budget(account).iterdir()} == {"reviewer-ledger.json", "instance.lock"}
  assert budget(account).stat().st_mode & 0o777 == 0o700
  assert sentinel(account).stat().st_mode & 0o777 == 0o600
  assert (budget(account) / "reviewer-ledger.json").stat().st_mode & 0o777 == 0o600
  assert not hasattr(value, "ledger") and not hasattr(value, "root")
  row = value.reserve(**request())
  row["binding"]["operation_id"] = "f" * 32
  assert value.get("0" * 31 + "1")["binding"]["operation_id"] == "0" * 31 + "1"


def test_passwd_account_ignores_home_xdg_and_recreated_controller(account, tmp_path, monkeypatch):
  import agentcfg.pi_registered_roots as roots
  monkeypatch.setattr(roots.pwd, "getpwuid", lambda uid: SimpleNamespace(pw_dir=str(account)))
  first = ReviewerAccountLedger(limits=LIMITS)
  op = first.reserve(**request())["binding"]["operation_id"]
  first.claim_attempt(op)
  for name in ("HOME", "XDG_STATE_HOME", "XDG_CONFIG_HOME"):
    monkeypatch.setenv(name, str(tmp_path / "unrelated"))
  second = ReviewerAccountLedger(limits=LIMITS)
  assert second.get(op)["attempt_claimed"] is True
  with pytest.raises(Conflict): second.claim_attempt(op)
  assert not (tmp_path / "unrelated").exists()


def test_unknown_reservation_and_deny_intent_survive_controller_recreation(account):
  value = create(account)
  op = value.reserve(**request())["binding"]["operation_id"]
  value.claim_attempt(op)
  value.commit_send(op)
  reopened = create(account)
  assert reopened.get(op)["requests"] is None
  assert reopened.snapshot()["unknown_requests"] == 1
  with pytest.raises(Conflict): reopened.commit_send(op)
  with pytest.raises(Conflict): reopened.reserve(**request(2))
  reopened.mark_sent(op)
  reopened.finish(op, requests=1, outcome="valid", decision="deny", reason_code="outside-user-scope")
  with pytest.raises(Conflict): create(account).reserve(**request(2))


def test_budget_tightening_and_currency_or_increase_rejected(account):
  value = create(account)
  value.reserve(**request())
  assert create(account, max_calls=10).snapshot()["limits"]["max_calls"] == 10
  with pytest.raises(Conflict): create(account)
  with pytest.raises(Conflict): create(account, currency="EUR", max_calls=10)
  with pytest.raises(Conflict): value.snapshot()


def test_registry_and_budget_members_coexist(account, tmp_path, monkeypatch):
  import agentcfg.pi_registered_roots as roots
  monkeypatch.setattr(roots, "_has_git_marker", lambda path: False)
  create(account)
  business = tmp_path / "business"
  business.mkdir(mode=0o700)
  registry = RegisteredRoots(account_home=account)
  assert registry.register(business)["status"] == "current"
  assert len(registry.list()) == 1
  assert create(account).snapshot()["record_count"] == 0


@pytest.mark.parametrize("fault", ["preparing", "updating", "missing-budget", "missing-ledger", "missing-sentinel", "budget-link", "ledger-fifo", "replace-budget", "replace-ledger", "inplace-ledger", "sentinel-mode", "budget-mode", "ledger-mode", "lock-mode", "unknown-budget", "unknown-anchor", "sentinel-link", "ledger-link", "lock-link", "sentinel-hardlink", "ledger-hardlink", "lock-hardlink", "sentinel-duplicate", "ledger-duplicate", "sentinel-extra", "sentinel-version", "binding-hash", "binding-identity"])
def test_ready_or_partial_state_never_reinitializes(account, tmp_path, fault):
  value = create(account)
  ledger = budget(account) / "reviewer-ledger.json"
  if fault in ("preparing", "updating"):
    state = json.loads(sentinel(account).read_bytes())
    state["state"] = fault
    sentinel(account).write_text(json.dumps(state))
  if fault == "missing-budget": budget(account).rename(account / "detached-budget")
  if fault == "missing-ledger": ledger.unlink()
  if fault == "missing-sentinel": sentinel(account).unlink()
  if fault == "budget-link":
    budget(account).rename(account / "detached-budget")
    budget(account).symlink_to(account / "detached-budget", target_is_directory=True)
  if fault == "ledger-fifo":
    ledger.unlink()
    os.mkfifo(ledger, 0o600)
  if fault == "replace-budget":
    budget(account).rename(account / "detached-budget")
    budget(account).mkdir(mode=0o700)
  if fault == "replace-ledger":
    replacement = budget(account) / "replacement"
    replacement.write_bytes(ledger.read_bytes())
    replacement.chmod(0o600)
    replacement.replace(ledger)
  if fault == "inplace-ledger": ledger.write_bytes(ledger.read_bytes())
  modes = {"sentinel-mode": sentinel(account), "budget-mode": budget(account), "ledger-mode": ledger, "lock-mode": budget(account) / "instance.lock"}
  if fault in modes: modes[fault].chmod(0o755 if fault == "budget-mode" else 0o644)
  if fault == "unknown-budget": (budget(account) / "extra").write_bytes(b"inert")
  if fault == "unknown-anchor": (sentinel(account).parent / "extra").write_bytes(b"inert")
  linked = {"sentinel-link": sentinel(account), "ledger-link": ledger, "lock-link": budget(account) / "instance.lock"}
  if fault in linked:
    target = tmp_path / "link-target"
    target.write_bytes(linked[fault].read_bytes())
    linked[fault].unlink()
    linked[fault].symlink_to(target)
  hard = {"sentinel-hardlink": sentinel(account), "ledger-hardlink": ledger, "lock-hardlink": budget(account) / "instance.lock"}
  if fault in hard: os.link(hard[fault], tmp_path / "second-link")
  if fault == "sentinel-duplicate": sentinel(account).write_bytes(sentinel(account).read_bytes().replace(b'"state":', b'"state":"ready","state":', 1))
  if fault == "ledger-duplicate": ledger.write_bytes(ledger.read_bytes().replace(b'"rows":', b'"rows":{},"rows":', 1))
  if fault in ("sentinel-extra", "sentinel-version", "binding-hash", "binding-identity"):
    state = json.loads(sentinel(account).read_bytes())
    if fault == "sentinel-extra": state["credential"] = "SYNTHETIC_PRIVATE"
    if fault == "sentinel-version": state["schema_version"] = True
    if fault == "binding-hash": state["ledger_sha256"] = "0" * 64
    if fault == "binding-identity": state["ledger_identity"][1] += 1
    sentinel(account).write_text(json.dumps(state))
  for action in (value.snapshot, lambda: create(account)):
    with pytest.raises((Conflict, ConfigError)) as caught:
      action()
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
  if fault == "missing-ledger": assert not ledger.exists()
  if fault == "replace-budget": assert list(budget(account).iterdir()) == []


@pytest.mark.parametrize("fault", ["preparing-ack", "directory-fsync", "initial-ledger", "initial-ready-before", "initial-ready-after"])
def test_initialization_ack_loss_leaves_explicit_state_not_automatic_cleanup(account, monkeypatch, fault):
  original = Tree.replace
  fsync = os.fsync
  def replace(tree, name, data, *args, **kwargs):
    state = json.loads(data).get("state") if name == "reviewer-budget.json" else None
    if fault == "initial-ready-before" and state == "ready": raise OSError("SYNTHETIC_PRIVATE")
    result = original(tree, name, data, *args, **kwargs)
    if fault == "preparing-ack" and state == "preparing" or fault == "initial-ready-after" and state == "ready":
      raise OSError("SYNTHETIC_PRIVATE")
    return result
  def failing_fsync(fd):
    if fault == "directory-fsync" and budget(account).exists() and os.fstat(fd).st_ino == sentinel(account).parent.stat().st_ino:
      raise OSError("SYNTHETIC_PRIVATE")
    return fsync(fd)
  def failing_ledger(*args, **kwargs):
    raise OSError("SYNTHETIC_PRIVATE")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", replace)
    patch.setattr(os, "fsync", failing_fsync)
    if fault == "initial-ledger": patch.setattr(module, "ReviewerLedger", failing_ledger)
    with pytest.raises(Conflict) as caught: create(account)
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
  assert sentinel(account).exists()
  state = json.loads(sentinel(account).read_bytes())
  if fault == "initial-ready-after":
    assert state["state"] == "ready"
    assert create(account).snapshot()["record_count"] == 0
  else:
    assert state["state"] == "preparing"
    with pytest.raises(Conflict): create(account)


@pytest.mark.parametrize("fault", ["updating-before", "updating-after", "ledger-after", "ready-before", "ready-after"])
def test_attempt_write_fault_never_returns_success_and_replay_cannot_resend(account, monkeypatch, fault):
  value = create(account)
  op = value.reserve(**request())["binding"]["operation_id"]
  original = Tree.replace
  def replacement(tree, name, data, *args, **kwargs):
    state = json.loads(data).get("state") if name == "reviewer-budget.json" else None
    if fault == "updating-before" and state == "updating" or fault == "ready-before" and state == "ready":
      raise OSError("SYNTHETIC_PRIVATE")
    result = original(tree, name, data, *args, **kwargs)
    if fault == "updating-after" and state == "updating" or fault == "ready-after" and state == "ready" or fault == "ledger-after" and name == "reviewer-ledger.json":
      raise OSError("SYNTHETIC_PRIVATE")
    return result
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", replacement)
    with pytest.raises(Conflict) as caught: value.claim_attempt(op)
    assert "SYNTHETIC_PRIVATE" not in str(caught.value)
  state = json.loads(sentinel(account).read_bytes())
  row = json.loads((budget(account) / "reviewer-ledger.json").read_bytes())["rows"][op]
  assert row["attempt_claimed"] is (fault in ("ledger-after", "ready-before", "ready-after"))
  if fault in ("updating-after", "ledger-after", "ready-before"):
    assert state["state"] == "updating"
    with pytest.raises(Conflict): create(account)
    with pytest.raises(Conflict): value.commit_send(op)
  elif fault == "ready-after":
    assert state["state"] == "ready"
    with pytest.raises(Conflict): create(account).claim_attempt(op)
  else:
    assert state["state"] == "ready" and row["attempt_claimed"] is False


def test_updating_is_durable_before_no_create_constructor_and_original_method(account, monkeypatch):
  value = create(account)
  original = module.ReviewerLedger
  seen = []
  def factory(*args, **kwargs):
    seen.append((json.loads(sentinel(account).read_bytes())["state"], kwargs["create"]))
    return original(*args, **kwargs)
  monkeypatch.setattr(module, "ReviewerLedger", factory)
  value.reserve(**request())
  assert seen == [("updating", False)]
  assert json.loads(sentinel(account).read_bytes())["state"] == "ready"


def test_expected_unchanged_failure_restores_ready_without_mutating_ledger(account):
  value = create(account)
  op = value.reserve(**request())["binding"]["operation_id"]
  old = (budget(account) / "reviewer-ledger.json").read_bytes()
  with pytest.raises(Conflict, match="REVIEW_ATTEMPT_NOT_CLAIMED"): value.commit_send(op)
  assert json.loads(sentinel(account).read_bytes())["state"] == "ready"
  assert (budget(account) / "reviewer-ledger.json").read_bytes() == old
  value.claim_attempt(op)
  assert value.get(op)["attempt_claimed"] is True


def test_final_usage_updates_binding_and_holds_unknown_until_termination(account):
  value = create(account)
  op = value.reserve(**request())["binding"]["operation_id"]
  value.claim_attempt(op)
  value.commit_send(op)
  value.mark_sent(op)
  value.finish(op, requests=1, outcome="valid", decision="allow", reason_code="authorized-in-scope")
  usage = {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8}
  with pytest.raises(Conflict, match="REVIEW_TERMINATION_UNKNOWN"): value.record_usage(op, usage, final=True)
  assert value.snapshot()["reserved_cost_units"] == 320
  value.record_usage(op, usage, final=True, process_terminated=True)
  assert create(account).get(op)["final_usage"] is True
  assert create(account).snapshot()["reported_estimated_cost_units"] == 21


@pytest.mark.parametrize("which", ["account", "anchor"])
def test_account_or_coordinator_replacement_cannot_rebind_old_control_state(account, which):
  value = create(account)
  target = account if which == "account" else sentinel(account).parent
  detached = target.parent / ("detached-" + target.name)
  target.rename(detached)
  target.mkdir(mode=0o700)
  with pytest.raises(Conflict): value.snapshot()
  assert list(target.iterdir()) == []
  # 缺原物理根的同一门面不能重建；不提供账户管理员删除全部控制根的恢复入口。


def test_valid_cloned_budget_directory_is_identity_change(account):
  value = create(account)
  detached = account / "detached-budget"
  budget(account).rename(detached)
  budget(account).mkdir(mode=0o700)
  for name in ("reviewer-ledger.json", "instance.lock"):
    file = budget(account) / name
    file.write_bytes((detached / name).read_bytes())
    file.chmod(0o600)
  with pytest.raises(Conflict): value.snapshot()
  with pytest.raises(Conflict): create(account)


def test_two_controllers_concurrently_claim_at_most_one_actual_attempt(account):
  from concurrent.futures import ThreadPoolExecutor
  from threading import Barrier
  first = create(account)
  op = first.reserve(**request())["binding"]["operation_id"]
  second = create(account)
  barrier = Barrier(2)
  def claim(value):
    barrier.wait()
    try:
      return value.claim_attempt(op)["attempt_claimed"]
    except Conflict:
      return False
  with ThreadPoolExecutor(max_workers=2) as pool:
    result = list(pool.map(claim, (first, second)))
  assert result.count(True) == 1
  assert first.get(op)["attempt_claimed"] is True
  assert first.snapshot()["record_count"] == 1


def test_account_lock_busy_is_explicit_and_has_no_ledger_or_sentinel_write(account, monkeypatch):
  import agentcfg.pi_registered_roots as roots
  value = create(account)
  op = value.reserve(**request())["binding"]["operation_id"]
  before = {path: path.read_bytes() for path in (sentinel(account), budget(account) / "reviewer-ledger.json")}
  def busy(fd, flags):
    raise BlockingIOError("SYNTHETIC_PRIVATE")
  monkeypatch.setattr(roots.fcntl, "flock", busy)
  with pytest.raises(Conflict) as caught:
    value.claim_attempt(op)
  assert str(caught.value) == "REVIEW_ACCOUNT_BUSY"
  assert {path: path.read_bytes() for path in before} == before


def test_facade_capacity_no_eviction_or_new_cycle(account):
  value = ReviewerAccountLedger(account_home=account, limits=LIMITS, max_records=1)
  value.reserve(**request())
  with pytest.raises(Conflict, match="REVIEW_LEDGER_CAPACITY"):
    value.reserve(**request(2, intent=2))
  assert value.snapshot()["record_count"] == 1
  assert create(account).get("0" * 31 + "1")["attempt_claimed"] is False


def test_invalid_account_argument_error_is_fixed_and_does_not_echo_object():
  class PrivateArgument:
    def __repr__(self): return "SYNTHETIC_PRIVATE"
  with pytest.raises(Conflict) as caught:
    ReviewerAccountLedger(limits=LIMITS, account_home=PrivateArgument())
  assert str(caught.value) == "REVIEW_ACCOUNT_INVALID"
