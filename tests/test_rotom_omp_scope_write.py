"""已有合作 scope 的显式写入租约；不授予共享包维护或旧记录采用。"""
import fcntl
import os

import pytest

from agentcfg import lifecycle, run_owners
from agentcfg.storage import Conflict, Tree
from test_rotom_omp_launch_admission import prepared
from test_rotom_resource_scopes import claim_path, held_scope, scope_ids
from test_rotom_resource_owners import IDENTITY, MANAGER, metadata


def test_idle_scope_opens_existing_exact_ex_and_does_not_create_state(prepared):
  ws, domain, scope, _ = prepared
  before = domain.snapshot()
  with lifecycle.omp_scope_write_guard(ws) as fd:
    assert os.fstat(fd).st_ino == scope["instance"]["key"]["inode"]
    other = os.open(ws.instance / ".agentcfg-omp.lock", os.O_RDONLY)
    try:
      with pytest.raises(BlockingIOError):
        fcntl.flock(other, fcntl.LOCK_SH | fcntl.LOCK_NB)
    finally:
      os.close(other)
    with domain._transaction(write=True):
      pass
  after = domain.snapshot()
  assert after["resources"] == before["resources"] and after["reservations"] == before["reservations"]
  assert not ws.state_root.exists()


@pytest.mark.parametrize("state", ["reserved", "unknown", "intent", "unlinked-owner"])
def test_durable_or_unlinked_occupancy_refuses_scope_writes(prepared, state):
  ws, domain, scope, runtime = prepared
  if state == "intent":
    domain.accept_intent(batch_id="a" * 32, generation=1, operation="setup",
      expected_revision=domain.snapshot()["revision"], resources=sorted(scope_ids(scope)), selected_runs=[])
  elif state == "unlinked-owner":
    run_owners.Registry(ws.state_root / "run-owners", ws.binding).register_v2(MANAGER, metadata(ws))
  else:
    token = lifecycle.reserve_omp_launch(ws, IDENTITY)
    if state == "unknown":
      domain.mark_unknown(token.run_id)
  before = domain.snapshot()
  with pytest.raises(Conflict), lifecycle.omp_scope_write_guard(ws):
    pytest.fail("scope remains protected")
  assert domain.snapshot() == before


def test_physical_sh_refuses_even_without_registered_run(prepared):
  ws, domain, _, runtime = prepared
  before = domain.snapshot()
  with held_scope(ws, ws.cache, runtime), pytest.raises(Conflict), lifecycle.omp_scope_write_guard(ws):
    pytest.fail("physical lease remains authoritative")
  assert domain.snapshot() == before


@pytest.mark.parametrize("damage", ["claim", "anchor", "domain"])
def test_missing_provenance_refuses_without_replacement(prepared, damage):
  ws, domain, _, _ = prepared
  if damage == "claim":
    claim_path(ws).unlink()
  elif damage == "anchor":
    (ws.instance / "user-home/.rotom-resource.json").unlink()
  else:
    (domain.root / "coordination.json").unlink()
  before = {p: p.read_bytes() for p in ws.instance.rglob("*") if p.is_file()}
  with pytest.raises(Conflict), lifecycle.omp_scope_write_guard(ws):
    pytest.fail("incomplete provenance cannot be adopted")
  assert {p: p.read_bytes() for p in ws.instance.rglob("*") if p.is_file()} == before
  assert not ws.state_root.exists()


def test_owner_lock_contention_is_nonblocking_and_releases_coordinator(prepared):
  ws, domain, _, _ = prepared
  registry = run_owners.Registry(ws.state_root / "run-owners", ws.binding)
  with registry._locked(create=True):
    with pytest.raises(Conflict), lifecycle.omp_scope_write_guard(ws):
      pytest.fail("must not wait on owner while coordinating")
    with domain._transaction(write=True):
      pass


def test_scope_guard_does_not_grant_runtime_maintenance(prepared):
  ws, domain, _, runtime = prepared
  domain.reserve(run_id="a" * 32, op_id="b" * 32, resources=[runtime["resource_id"]],
    owner_ref={"state_root": str(ws.state_root.parent / "other"), "binding": {**ws.binding, "profile": "other"}})
  domain.mark_unknown("a" * 32)
  with lifecycle.omp_scope_write_guard(ws):
    fd = os.open(ws.cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR)
    try:
      fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      with pytest.raises(Conflict):
        domain.check_runtime(ws.cache, IDENTITY, lease_fd=fd, idle=True)
    finally:
      os.close(fd)
