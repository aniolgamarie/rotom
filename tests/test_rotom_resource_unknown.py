"""当前 manager 的不完整退出记账；unknown 不是释放证据，不执行宿主。"""

from copy import deepcopy
import fcntl
import json
import os
import stat

import pytest

from agentcfg import lifecycle, resource_owners as owners, run_owners
from agentcfg.storage import Conflict, Tree
from test_rotom_omp_launch_admission import prepared
from test_rotom_resource_owners import IDENTITY, MANAGER, metadata, owner_path
from test_rotom_resource_scopes import held_scope


@pytest.fixture
def active(prepared, monkeypatch):
  ws, domain, _, runtime = prepared
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  token = lifecycle.reserve_omp_launch(ws, IDENTITY)
  with held_scope(ws, ws.cache, runtime) as args:
    owners.attach_owner(domain, token.run_id, manager_identity=MANAGER, metadata=metadata(ws), **args)
    owners.dispatch_owner(domain, token.run_id, **args)
    yield ws, domain, token, args


def unknown(active, **overrides):
  _, domain, token, args = active
  return owners.mark_owner_unknown(domain, token.run_id, manager_identity=MANAGER, **{**args, **overrides})


def test_unknown_is_durable_before_owner_change_and_never_clears_references(active, monkeypatch):
  ws, domain, token, _ = active
  phases = []
  original = Tree.replace
  def record(tree, name, data, *args, **kwargs):
    if name == token.run_id + ".json":
      state = json.loads((domain.root / "coordination.json").read_bytes())
      phases.append(state["reservations"][token.run_id]["phase"])
    return original(tree, name, data, *args, **kwargs)
  monkeypatch.setattr(Tree, "replace", record)
  before = domain.snapshot()
  assert unknown(active) == token.run_id
  saved = domain.snapshot()
  assert phases == ["unknown"]
  assert saved["resources"] == before["resources"] and saved["intents"] == before["intents"]
  entry = saved["reservations"][token.run_id]
  assert entry["phase"] == "unknown" and entry["resources"] == list(token.resources)
  record = run_owners.Registry(ws.state_root / "run-owners", ws.binding).snapshot()[token.run_id]
  assert run_owners.record_state(record) == "unknown"
  assert owners._digest(record) == entry["owner_link"]["record_digest"]
  assert "release_receipt" not in entry
  with pytest.raises(Conflict):
    domain.cancel_reserved(token.run_id)
  with pytest.raises(Conflict):
    unknown(active)


@pytest.mark.parametrize("fault", ["manager", "workspace", "package-fd", "home-fd", "owner-lock"])
def test_invalid_identity_or_evidence_cannot_mutate_unknown(active, monkeypatch, fault):
  ws, domain, token, _ = active
  before, raw = domain.snapshot(), owner_path(ws, token.run_id).read_bytes()
  changes = {}
  if fault == "manager":
    monkeypatch.setattr(run_owners, "current_process_identity", lambda: {**MANAGER, "birth_id": "reused"})
  elif fault == "workspace":
    wrong = deepcopy(ws)
    wrong.binding["machine"] = "other"
    changes["workspace"] = wrong
  elif fault == "package-fd":
    changes["runtime_fds"] = {}
  elif fault == "home-fd":
    changes["native_home_fd"] = -1
  if fault == "owner-lock":
    with Tree(ws.state_root / "run-owners") as tree:
      fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      with pytest.raises(Conflict):
        unknown(active)
  else:
    with pytest.raises(Conflict):
      unknown(active, **changes)
  assert domain.snapshot() == before and owner_path(ws, token.run_id).read_bytes() == raw


@pytest.mark.parametrize("point", ["first-before", "first-response", "owner-before", "owner-fsync", "last-response"])
def test_each_unknown_publication_failure_preserves_protection_without_retry(active, monkeypatch, point):
  ws, domain, token, args = active
  original, real_fsync = Tree.replace, os.fsync
  writes, triggered = [], []
  def fail(tree, name, data, *pos, **kwargs):
    if name == "coordination.json":
      entry = json.loads(data)["reservations"][token.run_id]
      if entry["phase"] == "unknown":
        writes.append("ledger")
    elif name == token.run_id + ".json":
      writes.append("owner")
    hit = ((point.startswith("first") and writes == ["ledger"])
      or (point.startswith("owner") and writes == ["ledger", "owner"])
      or (point == "last-response" and writes == ["ledger", "owner", "ledger"]))
    if not hit or triggered:
      return original(tree, name, data, *pos, **kwargs)
    triggered.append(True)
    if point.endswith("before"):
      raise OSError("synthetic-private-write-failure")
    if point == "owner-fsync":
      def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
          raise OSError("synthetic-private-fsync-failure")
        return real_fsync(fd)
      with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fsync)
        return original(tree, name, data, *pos, **kwargs)
    original(tree, name, data, *pos, **kwargs)
    raise OSError("synthetic-private-response-lost")
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", fail)
    with pytest.raises(Conflict) as error:
      unknown(active)
  assert triggered and "synthetic-private" not in str(error.value)
  phase = domain.snapshot()["reservations"][token.run_id]["phase"]
  assert phase == ("dispatched" if point == "first-before" else "unknown")
  assert len(writes) <= 3
  with pytest.raises(Conflict):
    domain.cancel_reserved(token.run_id)
  with pytest.raises(Conflict):
    domain.check_runtime(ws.cache, IDENTITY, lease_fd=next(iter(args["runtime_fds"].values())), idle=True)


def test_unknown_keeps_existing_stop_intent(active):
  _, domain, token, _ = active
  domain.accept_intent(batch_id="a" * 32, generation=1, operation="stop_only",
    expected_revision=domain.snapshot()["revision"], resources=list(token.resources), selected_runs=[token.run_id])
  intent = deepcopy(domain.snapshot()["intents"])
  unknown(active)
  assert domain.snapshot()["intents"] == intent


def test_completed_owner_cannot_be_rewritten_unknown(active):
  ws, domain, token, args = active
  observation = run_owners.ReleaseObservation(token.run_id, MANAGER, True, True)
  owners.finish_owner(domain, token.run_id, observation=observation, **args)
  before, raw = domain.snapshot(), owner_path(ws, token.run_id).read_bytes()
  with pytest.raises(Conflict):
    unknown(active)
  assert domain.snapshot() == before and owner_path(ws, token.run_id).read_bytes() == raw


def test_manager_change_after_first_commit_keeps_ledger_unknown_without_owner_write(active, monkeypatch):
  ws, domain, token, _ = active
  raw = owner_path(ws, token.run_id).read_bytes()
  original = Tree.replace
  def change(tree, name, data, *args, **kwargs):
    result = original(tree, name, data, *args, **kwargs)
    if name == "coordination.json" and json.loads(data)["reservations"][token.run_id]["phase"] == "unknown":
      monkeypatch.setattr(run_owners, "current_process_identity", lambda: {**MANAGER, "birth_id": "reused"})
    return result
  monkeypatch.setattr(Tree, "replace", change)
  with pytest.raises(Conflict):
    unknown(active)
  assert domain.snapshot()["reservations"][token.run_id]["phase"] == "unknown"
  assert owner_path(ws, token.run_id).read_bytes() == raw


def test_marking_one_unknown_preserves_other_shared_owner(active):
  from test_rotom_resource_scopes import workspace, scopes, scope_ids
  ws, domain, token, _ = active
  other = workspace(ws.instance.parent.parent, "omp-other")
  anchor = scopes().enroll_scope(domain, other)
  run = "a" * 32
  domain.reserve(run_id=run, op_id="b" * 32,
    owner_ref={"state_root": str(other.state_root), "binding": other.binding},
    resources=sorted(scope_ids(anchor) | {token.runtime_resource_id}))
  runtime = {"resource_id": token.runtime_resource_id}
  with held_scope(other, ws.cache, runtime) as args:
    owners.attach_owner(domain, run, manager_identity=MANAGER, metadata=metadata(other), **args)
    owners.dispatch_owner(domain, run, **args)
  entry, raw = deepcopy(domain.snapshot()["reservations"][run]), owner_path(other, run).read_bytes()
  unknown(active)
  assert domain.snapshot()["reservations"][run] == entry
  assert owner_path(other, run).read_bytes() == raw


def test_attached_but_not_dispatched_owner_can_be_marked_unknown(prepared, monkeypatch):
  ws, domain, _, runtime = prepared
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  token = lifecycle.reserve_omp_launch(ws, IDENTITY)
  with held_scope(ws, ws.cache, runtime) as args:
    owners.attach_owner(domain, token.run_id, manager_identity=MANAGER, metadata=metadata(ws), **args)
    assert domain.snapshot()["reservations"][token.run_id]["phase"] == "owner_attached"
    owners.mark_owner_unknown(domain, token.run_id, manager_identity=MANAGER, **args)
  assert domain.snapshot()["reservations"][token.run_id]["phase"] == "unknown"
  record = run_owners.Registry(ws.state_root / "run-owners", ws.binding).snapshot()[token.run_id]
  assert run_owners.record_state(record) == "unknown"
