"""预留到 owner 提交的同事务绑定；全为隔离文件及假 manager。"""
from dataclasses import replace

import pytest

from agentcfg import lifecycle, resource_owners as owners
from agentcfg.resource_protocol import encode
from agentcfg.storage import Conflict
from test_rotom_omp_launch_admission import prepared, check
from test_rotom_resource_scopes import held_scope
from test_rotom_resource_owners import IDENTITY, MANAGER, metadata, owner_path


def attach(token, prepared):
  ws, domain, _, runtime = prepared
  with held_scope(ws, ws.cache, runtime) as args:
    return owners.attach_owner(domain, token.run_id, manager_identity=MANAGER,
      metadata=metadata(ws), expected_reservation=token, **args)


def test_original_token_binds_attach_and_dispatch(prepared):
  ws, domain, _, runtime = prepared
  token = lifecycle.reserve_omp_launch(ws, IDENTITY)
  assert attach(token, prepared) == token.run_id
  with held_scope(ws, ws.cache, runtime) as args:
    owners.dispatch_owner(domain, token.run_id, expected_reservation=token, **args)
  assert domain.snapshot()["reservations"][token.run_id]["phase"] == "dispatched"


@pytest.mark.parametrize("field,value", [("generation", 999), ("op_id", "b" * 32),
  ("domain_id", "c" * 32), ("runtime_identity", "d" * 64), ("owner_ref_digest", "e" * 64)])
def test_mismatched_token_refuses_before_owner_creation(prepared, field, value):
  ws, domain, _, _ = prepared
  token = lifecycle.reserve_omp_launch(ws, IDENTITY)
  before = domain.snapshot()
  with pytest.raises(Conflict):
    attach(replace(token, **{field: value}), prepared)
  assert domain.snapshot() == before and not (ws.state_root / "run-owners").exists()


def test_valid_check_cannot_authorize_generation_changed_before_attach(prepared):
  ws, domain, _, _ = prepared
  token = lifecycle.reserve_omp_launch(ws, IDENTITY)
  check(token, prepared)
  state = domain.snapshot()
  state["revision"] += 1
  state["reservations"][token.run_id]["generation"] = state["revision"]
  (domain.root / "coordination.json").write_bytes(encode(state))
  with pytest.raises(Conflict):
    attach(token, prepared)
  assert not (ws.state_root / "run-owners").exists()
  assert domain.snapshot()["reservations"][token.run_id]["phase"] == "reserved"


def test_wrong_dispatch_token_leaves_attached_owner_untouched(prepared):
  ws, domain, _, runtime = prepared
  token = lifecycle.reserve_omp_launch(ws, IDENTITY)
  attach(token, prepared)
  before = domain.snapshot(), owner_path(ws, token.run_id).read_bytes()
  with held_scope(ws, ws.cache, runtime) as args, pytest.raises(Conflict):
    owners.dispatch_owner(domain, token.run_id, expected_reservation=replace(token, generation=999), **args)
  assert (domain.snapshot(), owner_path(ws, token.run_id).read_bytes()) == before


def test_exact_reserved_cancellation_does_not_need_physical_lease(prepared):
  ws, domain, _, _ = prepared
  token = lifecycle.reserve_omp_launch(ws, IDENTITY)
  lifecycle.cancel_omp_launch(token, ws)
  assert domain.snapshot()["reservations"][token.run_id]["phase"] == "cancelled"
  assert not (ws.state_root / "run-owners").exists()


@pytest.mark.parametrize("change", ["generation", "owner-attached", "unknown"])
def test_cancellation_refuses_old_or_possibly_dispatched_facts(prepared, change):
  ws, domain, _, _ = prepared
  token = lifecycle.reserve_omp_launch(ws, IDENTITY)
  if change == "generation":
    token = replace(token, generation=999)
  elif change == "owner-attached":
    attach(token, prepared)
  else:
    domain.mark_unknown(token.run_id)
  before = domain.snapshot()
  with pytest.raises(Conflict):
    lifecycle.cancel_omp_launch(token, ws)
  assert domain.snapshot() == before


@pytest.mark.parametrize("operation", ["attach", "dispatch"])
def test_token_for_one_launch_cannot_authorize_another_run(prepared, operation):
  ws, domain, _, runtime = prepared
  first = lifecycle.reserve_omp_launch(ws, IDENTITY)
  second = lifecycle.reserve_omp_launch(ws, IDENTITY)
  if operation == "dispatch":
    attach(first, prepared)
    attach(second, prepared)
  before = domain.snapshot()
  before_owners = {p.name: p.read_bytes() for p in (ws.state_root / "run-owners").glob("*.json")}
  with held_scope(ws, ws.cache, runtime) as args, pytest.raises(Conflict):
    if operation == "attach":
      owners.attach_owner(domain, second.run_id, manager_identity=MANAGER,
        metadata=metadata(ws), expected_reservation=first, **args)
    else:
      owners.dispatch_owner(domain, second.run_id, expected_reservation=first, **args)
  assert domain.snapshot() == before
  assert {p.name: p.read_bytes() for p in (ws.state_root / "run-owners").glob("*.json")} == before_owners
