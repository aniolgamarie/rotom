"""已登记实例同步只写目标共享包；合成 fd 验证顺序与完整归属。"""
import fcntl
import os

import pytest

from agentcfg import resource_coordination as coordination, resource_scopes as scopes
from agentcfg.omp_dependencies import OmpBackend
from agentcfg.storage import Conflict
from test_rotom_omp_launch_admission import prepared
from test_rotom_resource_owners import IDENTITY
from test_rotom_resource_scopes import claim_path, scope_ids


def test_complete_scope_sync_holds_physical_sh_and_package_ex_without_state(prepared):
  ws, domain, _, runtime = prepared
  before = domain.snapshot()
  with OmpBackend().runtime_guard(ws, IDENTITY, exclusive=True) as fd:
    assert os.fstat(fd).st_ino == runtime["resource_key"]["inode"]
    physical = os.open(ws.instance / ".agentcfg-omp.lock", os.O_RDONLY)
    package = os.open(ws.cache / "leases" / (IDENTITY + ".lock"), os.O_RDONLY)
    try:
      fcntl.flock(physical, fcntl.LOCK_SH | fcntl.LOCK_NB)
      with pytest.raises(BlockingIOError):
        fcntl.flock(physical, fcntl.LOCK_EX | fcntl.LOCK_NB)
      with pytest.raises(BlockingIOError):
        fcntl.flock(package, fcntl.LOCK_SH | fcntl.LOCK_NB)
      with domain._transaction(write=True):
        pass
    finally:
      os.close(package)
      os.close(physical)
  after = domain.snapshot()
  assert after["resources"] == before["resources"] and after["reservations"] == before["reservations"]
  assert not ws.state_root.exists()


def test_physical_ex_is_checked_before_taking_package_ex(prepared, monkeypatch):
  ws, _, _, _ = prepared
  physical = os.open(ws.instance / ".agentcfg-omp.lock", os.O_RDONLY)
  real_open = os.open
  def open_file(name, *args, **kwargs):
    assert name != IDENTITY + ".lock", "实例锁冲突必须在包锁前结束"
    return real_open(name, *args, **kwargs)
  try:
    fcntl.flock(physical, fcntl.LOCK_EX | fcntl.LOCK_NB)
    monkeypatch.setattr(os, "open", open_file)
    with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, IDENTITY, exclusive=True):
      pytest.fail("instance maintenance must retain its original exclusion")
  finally:
    os.close(physical)


@pytest.mark.parametrize("damage", ["claim", "home-anchor", "runtime-claim", "lease", "foreign-domain"])
def test_incomplete_scope_or_runtime_is_never_repaired(prepared, damage):
  ws, domain, _, _ = prepared
  lease = ws.cache / "leases" / (IDENTITY + ".lock")
  if damage == "claim":
    claim_path(ws).unlink()
  elif damage == "home-anchor":
    (ws.instance / "user-home/.rotom-resource.json").unlink()
  elif damage == "runtime-claim":
    (ws.cache / "runtime-claims" / (IDENTITY + ".json")).unlink()
  elif damage == "lease":
    lease.unlink()
  else:
    root = domain.root.parent.with_name("foreign-state")
    ws.resolved.data["machine"]["paths"]["state_root"] = str(root)
    ws.state_root = root / "omp" / ws.profile
  before = set(ws.instance.parent.parent.rglob("*"))
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, IDENTITY, exclusive=True):
    pytest.fail("incomplete evidence must fail closed")
  assert set(ws.instance.parent.parent.rglob("*")) == before
  assert not ws.state_root.exists()


def test_foreign_unknown_sharing_package_blocks_even_when_this_scope_idle(prepared):
  ws, domain, _, runtime = prepared
  domain.reserve(run_id="a" * 32, op_id="b" * 32, resources=[runtime["resource_id"]],
    owner_ref={"state_root": str(ws.state_root.with_name("other")), "binding": {**ws.binding, "profile": "other"}})
  domain.mark_unknown("a" * 32)
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, IDENTITY, exclusive=True):
    pytest.fail("other instance unknown protects the shared package")


def test_sync_another_package_does_not_require_other_runtime_idle(prepared):
  ws, domain, scope, runtime = prepared
  other = "other-runtime"
  coordination.enroll_runtime(domain, ws.cache, other)
  domain.reserve(run_id="a" * 32, op_id="b" * 32,
    resources=sorted(scope_ids(scope) | {runtime["resource_id"]}),
    owner_ref={"state_root": str(ws.state_root), "binding": ws.binding})
  domain.mark_unknown("a" * 32)
  with OmpBackend().runtime_guard(ws, other, exclusive=True):
    pass
  assert domain.snapshot()["reservations"]["a" * 32]["phase"] == "unknown"


def test_scope_maintenance_intent_prevents_new_sync(prepared):
  ws, domain, scope, _ = prepared
  domain.accept_intent(batch_id="a" * 32, generation=1, operation="setup",
    expected_revision=domain.snapshot()["revision"], resources=sorted(scope_ids(scope)), selected_runs=[])
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, IDENTITY, exclusive=True):
    pytest.fail("do not enter a scope fenced by pending maintenance")


def test_shared_entry_cannot_replace_cooperative_run_registration(prepared):
  ws, _, _, _ = prepared
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, IDENTITY):
    pytest.fail("ordinary shared guard is not run admission")


def test_scope_appearing_after_package_lock_does_not_invert_lock_order(prepared, monkeypatch):
  ws, _, _, _ = prepared
  original = scopes.scope_claim_exists
  calls = []
  def changed(instance):
    calls.append(instance)
    return False if len(calls) <= 2 else original(instance)
  monkeypatch.setattr(scopes, "scope_claim_exists", changed)
  with pytest.raises(Conflict), OmpBackend().runtime_guard(ws, IDENTITY, exclusive=True):
    pytest.fail("late scope must not be acquired under package EX")
  assert len(calls) == 3


def test_operation_failure_preserves_identity(prepared):
  ws, _, _, _ = prepared
  failure = RuntimeError("synthetic-sync-failure")
  with pytest.raises(RuntimeError) as error:
    with OmpBackend().runtime_guard(ws, IDENTITY, exclusive=True):
      raise failure
  assert error.value is failure
