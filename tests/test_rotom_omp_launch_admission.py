"""内部 OMP 预留候选与 fd 重核；不启动宿主或写入 run owner。"""
from dataclasses import FrozenInstanceError, replace
import json
import fcntl
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentcfg import lifecycle, resource_coordination as core
from agentcfg.resource_protocol import encode
from agentcfg.storage import Conflict, Tree
from test_rotom_resource_owners import IDENTITY
from test_rotom_resource_scopes import claim_path, held_scope, scope_ids, scopes, workspace


@pytest.fixture
def prepared(tmp_path):
  ws = workspace(tmp_path)
  global_state = tmp_path / "global-state"
  ws.state_root = global_state / "omp" / ws.profile
  ws.resolved = SimpleNamespace(data={"machine": {"paths": {"state_root": str(global_state)}}})
  ws.cache = tmp_path / "cache"
  domain = core.initialize_domain(global_state / "lifecycle")
  scope = scopes().enroll_scope(domain, ws)
  runtime = core.enroll_runtime(domain, ws.cache, IDENTITY)
  return ws, domain, scope, runtime


def reserve(prepared):
  return lifecycle.reserve_omp_launch(prepared[0], IDENTITY)


def check(token, prepared, **change):
  ws, _, _, runtime = prepared
  with held_scope(ws, ws.cache, runtime) as args:
    values = {"instance_fd": args["instance_fd"], "native_home_fd": args["native_home_fd"],
      "package_fd": args["runtime_fds"][runtime["resource_id"]]}
    values.update(change)
    return lifecycle.check_omp_launch(token, ws, **values)


def test_three_resource_candidate_uses_global_domain_and_checks_existing_fds(prepared):
  ws, domain, scope, runtime = prepared
  ws.resolved.data["unrelated-secret"] = "synthetic-private-not-in-token"
  token = reserve(prepared)
  assert "synthetic-private-not-in-token" not in repr(vars(token))
  assert token.domain_root == Path(ws.resolved.data["machine"]["paths"]["state_root"]) / "lifecycle"
  assert token.domain_root != ws.state_root / "lifecycle"
  assert token.resources == tuple(sorted(scope_ids(scope) | {runtime["resource_id"]}))
  assert token.runtime_resource_id == runtime["resource_id"] and token.runtime_identity == IDENTITY
  record = domain.snapshot()["reservations"][token.run_id]
  assert record["generation"] == token.generation and record["op_id"] == token.op_id
  assert record["owner_ref"] == {"state_root": str(ws.state_root), "binding": ws.binding}
  assert record["phase"] == "reserved" and check(token, prepared) is None
  assert not (ws.state_root / "run-owners").exists()
  with pytest.raises(FrozenInstanceError):
    token.generation = 1
  assert all(not isinstance(value, (dict, list)) for value in vars(token).values())


def test_missing_deployment_does_not_initialize_anything(tmp_path):
  ws = workspace(tmp_path)
  root = tmp_path / "absent-state"
  ws.state_root, ws.cache = root / "omp" / ws.profile, tmp_path / "absent-cache"
  ws.resolved = SimpleNamespace(data={"machine": {"paths": {"state_root": str(root)}}})
  before = set(tmp_path.rglob("*"))
  with pytest.raises(Conflict):
    lifecycle.reserve_omp_launch(ws, IDENTITY)
  assert set(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("damage", ["scope-claim", "runtime-claim", "home-record", "runtime-record", "single-package"])
def test_missing_claim_or_complete_three_resource_set_refuses_without_write(prepared, damage):
  ws, domain, scope, runtime = prepared
  if damage == "scope-claim":
    claim_path(ws).unlink()
  elif damage == "runtime-claim":
    (ws.cache / "runtime-claims" / (IDENTITY + ".json")).unlink()
  else:
    state = domain.snapshot()
    if damage == "single-package":
      for rid in scope_ids(scope):
        del state["resources"][rid]
    else:
      rid = scope["native_home"]["resource_id"] if damage == "home-record" else runtime["resource_id"]
      del state["resources"][rid]
    (domain.root / "coordination.json").write_bytes(encode(state))
  before = (domain.root / "coordination.json").read_bytes()
  with pytest.raises(Conflict):
    reserve(prepared)
  assert (domain.root / "coordination.json").read_bytes() == before


@pytest.mark.parametrize("raw", ["/", "/tmp/../invalid", "/tmp//invalid", "/tmp/invalid/", "/tmp/invalid\n", "//tmp/invalid", "/tmp\\invalid", "relative"])
def test_noncanonical_original_config_path_is_rejected_before_access(prepared, raw, monkeypatch):
  ws, domain, _, _ = prepared
  ws.resolved.data["machine"]["paths"]["state_root"] = raw
  ws.state_root = Path(raw) / "omp" / ws.profile
  monkeypatch.setattr(core, "Domain", lambda *a: pytest.fail("非法原始路径不得访问协调域"))
  before = (domain.root / "coordination.json").read_bytes()
  with pytest.raises(Conflict):
    reserve(prepared)
  assert (domain.root / "coordination.json").read_bytes() == before


@pytest.mark.parametrize("field", ["agent", "profile", "state_root", "cache-alias", "domain-alias"])
def test_wrong_workspace_or_alias_refuses(prepared, field):
  ws, domain, _, _ = prepared
  if field == "agent":
    ws.agent = "pi"
  elif field == "profile":
    ws.profile = "omp-other"
  elif field == "state_root":
    ws.state_root = ws.state_root.parent / "other"
  elif field == "cache-alias":
    alias = ws.cache.parent / "alias-cache"
    alias.symlink_to(ws.cache, target_is_directory=True)
    ws.cache = alias
  else:
    renamed = domain.root.with_name("original-domain")
    domain.root.rename(renamed)
    domain.root.symlink_to(renamed, target_is_directory=True)
  with pytest.raises(Conflict):
    reserve(prepared)


def test_intersecting_legacy_generationless_reservation_is_not_adopted(prepared):
  ws, domain, _, runtime = prepared
  domain.reserve(run_id="a" * 32, op_id="b" * 32,
    owner_ref={"state_root": str(ws.state_root), "binding": ws.binding}, resources=[runtime["resource_id"]])
  state = domain.snapshot()
  state["reservations"]["a" * 32].pop("generation")
  (domain.root / "coordination.json").write_bytes(encode(state))
  before = (domain.root / "coordination.json").read_bytes()
  with pytest.raises(Conflict):
    reserve(prepared)
  assert (domain.root / "coordination.json").read_bytes() == before


def test_launch_selection_and_reservation_use_one_write_transaction(prepared, monkeypatch):
  _, domain, _, _ = prepared
  snapshot = core.Domain.snapshot
  monkeypatch.setattr(core.Domain, "snapshot", lambda *args: pytest.fail("launch must not select from an unlocked snapshot"))
  token = reserve(prepared)
  assert snapshot(domain)["reservations"][token.run_id]["generation"] == token.generation


def test_generic_reserve_keeps_exact_revision_cas(prepared):
  ws, domain, _, runtime = prepared
  old = domain.snapshot()["revision"]
  domain.reserve(run_id="a" * 32, op_id="b" * 32,
    owner_ref={"state_root": str(ws.state_root), "binding": ws.binding}, resources=[runtime["resource_id"]])
  before = (domain.root / "coordination.json").read_bytes()
  with pytest.raises(Conflict):
    domain.reserve(run_id="c" * 32, op_id="d" * 32,
      owner_ref={"state_root": str(ws.state_root), "binding": ws.binding},
      resources=[runtime["resource_id"]], expected_revision=old)
  assert (domain.root / "coordination.json").read_bytes() == before


def test_launch_fence_is_checked_inside_atomic_reservation(prepared):
  _, domain, _, runtime = prepared
  domain.accept_intent(batch_id="a" * 32, generation=1, operation="stop_only",
    expected_revision=domain.snapshot()["revision"], resources=[runtime["resource_id"]], selected_runs=[])
  before = (domain.root / "coordination.json").read_bytes()
  with pytest.raises(Conflict): reserve(prepared)
  assert (domain.root / "coordination.json").read_bytes() == before
  assert not domain.snapshot()["reservations"]


def test_two_concurrent_launches_reserve_distinct_runs_without_snapshot_drift(prepared, monkeypatch):
  import threading
  import time
  _, domain, _, _ = prepared
  barrier = threading.Barrier(2)
  original = core.Domain._reserve_locked
  calls, results = [], []
  def reserve_once(selected, state, **kwargs):
    calls.append(kwargs["run_id"])
    time.sleep(0.03)
    return original(selected, state, **kwargs)
  monkeypatch.setattr(core.Domain, "_reserve_locked", reserve_once)
  def launch():
    try:
      barrier.wait(timeout=2)
      results.append(reserve(prepared))
    except BaseException as error: results.append(error)
  threads = [threading.Thread(target=launch) for _ in range(2)]
  before = domain.snapshot()["revision"]
  for thread in threads: thread.start()
  for thread in threads: thread.join(timeout=3)
  assert not any(thread.is_alive() for thread in threads)
  assert len(results) == 2 and all(isinstance(item, lifecycle.OmpLaunchReservation) for item in results), results
  assert len(calls) == len(set(calls)) == 2
  state = domain.snapshot()
  assert state["revision"] == before + 2
  assert set(state["reservations"]) == {item.run_id for item in results}
  assert {entry["phase"] for entry in state["reservations"].values()} == {"reserved"}
  assert results[0].resources == results[1].resources


def test_startup_physical_verification_waits_for_short_domain_writer(prepared):
  from test_rotom_start_stop_lock_contention import owner_lock
  _, domain, _, _ = prepared
  token = reserve(prepared)
  before = (domain.root / "coordination.json").read_bytes()
  with owner_lock(domain.root, release=True) as released:
    assert check(token, prepared) is None
  assert released.is_set()
  assert (domain.root / "coordination.json").read_bytes() == before


@pytest.mark.parametrize("field,value", [("generation", 999), ("domain_id", "a" * 32),
  ("domain_root", Path("/tmp/synthetic-other-domain")), ("runtime_identity", "d" * 64),
  ("domain_physical", (1, 2)), ("run_id", "a" * 32), ("op_id", "b" * 32),
  ("resources", ("a" * 32,)), ("runtime_resource_id", "a" * 32), ("owner_ref_digest", "0" * 64)])
def test_tampered_token_never_passes_physical_check(prepared, field, value):
  token = reserve(prepared)
  with pytest.raises(Conflict):
    check(replace(token, **{field: value}), prepared)


@pytest.mark.parametrize("fault", ["package-fd", "home-fd", "unknown", "anchor", "replaced-domain"])
def test_changed_physical_or_durable_evidence_is_rejected(prepared, fault):
  ws, domain, _, runtime = prepared
  token = reserve(prepared)
  if fault == "unknown":
    domain.mark_unknown(token.run_id)
  elif fault == "anchor":
    claim_path(ws).unlink()
  elif fault == "replaced-domain":
    domain.root.rename(domain.root.with_name("retired-domain"))
    core.initialize_domain(domain.root)
  with held_scope(ws, ws.cache, runtime) as args:
    values = {"instance_fd": args["instance_fd"], "native_home_fd": args["native_home_fd"],
      "package_fd": args["runtime_fds"][runtime["resource_id"]]}
    if fault == "package-fd":
      values["package_fd"] = args["instance_fd"]
    elif fault == "home-fd":
      values["native_home_fd"] = args["instance_fd"]
    with pytest.raises(Conflict):
      lifecycle.check_omp_launch(token, ws, **values)


def test_committed_reserve_response_loss_keeps_reserved_protection(prepared, monkeypatch):
  _, domain, _, _ = prepared
  original = Tree.replace
  writes = []
  def lost(tree, name, data, *args, **kwargs):
    result = original(tree, name, data, *args, **kwargs)
    if name == "coordination.json" and json.loads(data)["reservations"]:
      writes.append(True)
      raise OSError("synthetic-private-response-lost")
    return result
  monkeypatch.setattr(Tree, "replace", lost)
  with pytest.raises(Conflict) as error:
    reserve(prepared)
  assert "synthetic-private" not in str(error.value)
  records = domain.snapshot()["reservations"]
  assert len(writes) == len(records) == 1 and next(iter(records.values()))["phase"] == "reserved"


def test_reservation_does_not_acquire_physical_sh_or_claim_it_verified(prepared):
  from test_rotom_resource_coordination import locked
  ws, domain, _, _ = prepared
  fd = os.open(ws.instance / ".agentcfg-omp.lock", os.O_RDWR | os.O_NOFOLLOW)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with locked(ws.cache, IDENTITY, exclusive=True):
      token = reserve(prepared)
      assert domain.snapshot()["reservations"][token.run_id]["phase"] == "reserved"
  finally:
    os.close(fd)


def test_new_intent_fence_blocks_reserved_token_even_with_matching_fds(prepared):
  _, domain, _, runtime = prepared
  token = reserve(prepared)
  state = domain.snapshot()
  # 合成已经存在的协调fence；不声称reserved run能通过正常accept_intent。
  state["intents"]["a" * 32] = {"batch_id": "a" * 32, "generation": 1,
    "operation": "stop_only", "resources": [runtime["resource_id"]], "selected_runs": [], "phase": "active"}
  (domain.root / "coordination.json").write_bytes(encode(state))
  with pytest.raises(Conflict):
    check(token, prepared)


@pytest.mark.parametrize("field", ["scope_id", "anchor_digest"])
def test_scope_record_pair_must_share_scope_and_anchor_digest(prepared, field):
  _, domain, scope, _ = prepared
  state = domain.snapshot()
  state["resources"][scope["native_home"]["resource_id"]][field] = "f" * (32 if field == "scope_id" else 64)
  (domain.root / "coordination.json").write_bytes(encode(state))
  before = (domain.root / "coordination.json").read_bytes()
  with pytest.raises(Conflict):
    reserve(prepared)
  assert (domain.root / "coordination.json").read_bytes() == before
