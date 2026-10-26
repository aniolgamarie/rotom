"""双向释放记账的离线验收；合成内核观察不等于实际宿主验证。"""

from copy import deepcopy
import fcntl
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import resource_owners as owners, run_owners
from agentcfg.resource_protocol import encode
from agentcfg.storage import Conflict, Tree
from test_rotom_resource_owners import (
  RUN, MANAGER, IDENTITY, setup_case, held, attach, owner_path, make_workspace, reserve,
)


@pytest.fixture(autouse=True)
def synthetic_manager(monkeypatch):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))


def observation(**changes):
  values = {"run_id": RUN, "manager_identity": deepcopy(MANAGER), "complete": True, "all_related_exited": True}
  values.update(changes)
  return run_owners.ReleaseObservation(**values)


def dispatched(root):
  ws, domain, cache, anchor = setup_case(root)
  with held(ws, cache, anchor) as args:
    attach(domain, args)
    owners.dispatch_owner(domain, RUN, **args)
  return ws, domain, cache, anchor


def finish(domain, args, *, observed=None, run=RUN):
  return owners.finish_owner(domain, run, observation=observation() if observed is None else observed, **args)


def reconcile(domain, args, *, observed=None):
  return owners.reconcile_owner_release(domain, RUN, observation=observation() if observed is None else observed, **args)


def record(ws):
  return run_owners.Registry(ws.state_root / "run-owners", ws.binding).snapshot()[RUN]


def assert_idle(domain, cache, anchor, *, blocked):
  fd = os.open(cache / "leases" / (IDENTITY + ".lock"), os.O_RDWR | os.O_NOFOLLOW)
  try:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if blocked:
      with pytest.raises(Conflict):
        domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True)
    else:
      assert domain.check_runtime(cache, IDENTITY, lease_fd=fd, idle=True) == anchor["resource_id"]
  finally:
    os.close(fd)


def test_release_binds_receipt_idle_record_and_only_then_unblocks(tmp_path):
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    finish(domain, args)
    entry = domain.snapshot()["reservations"][RUN]
    saved = record(ws)
    assert entry["phase"] == "released"
    assert saved["lifecycle_state"] == "idle_confirmed"
    assert entry["release_receipt"]["observed_at_ns"] == saved["process_observation"]["observed_at_ns"]
    assert entry["release_receipt"]["owner_record_digest"] == owners._digest(saved)
    for call in (lambda: finish(domain, args), lambda: owners.dispatch_owner(domain, RUN, **args),
        lambda: domain.mark_unknown(RUN), lambda: domain.cancel_reserved(RUN)):
      with pytest.raises(Conflict):
        call()
  assert_idle(domain, cache, anchor, blocked=False)
  domain.accept_intent(batch_id="e" * 32, generation=1, operation="stop_only",
    expected_revision=domain.snapshot()["revision"], resources=[anchor["resource_id"]], selected_runs=[])
  assert_idle(domain, cache, anchor, blocked=True)


@pytest.mark.parametrize("fault", ["run", "manager", "complete", "exited", "bool-int", "dict", "fake-type", "current-manager", "manager-unavailable"])
def test_invalid_observation_or_manager_never_changes_records(tmp_path, monkeypatch, fault):
  ws, domain, cache, anchor = dispatched(tmp_path)
  observed = observation()
  if fault == "run":
    observed = observation(run_id="e" * 32)
  elif fault == "manager":
    observed = observation(manager_identity={"pid": 3133714, "birth_id": "other"})
  elif fault == "complete":
    observed = observation(complete=False)
  elif fault == "exited":
    observed = observation(all_related_exited=False)
  elif fault == "bool-int":
    observed = observation(complete=1)
  elif fault == "dict":
    observed = dict(observed.__dict__)
  elif fault == "fake-type":
    observed = SimpleNamespace(**observed.__dict__)
  elif fault == "current-manager":
    monkeypatch.setattr(run_owners, "current_process_identity", lambda: {"pid": 3133714, "birth_id": "other"})
  else:
    def unavailable():
      raise Conflict("synthetic-private-manager")
    monkeypatch.setattr(run_owners, "current_process_identity", unavailable)
  before, owner_before = domain.snapshot(), owner_path(ws).read_bytes()
  with held(ws, cache, anchor) as args, pytest.raises(Conflict):
    finish(domain, args, observed=observed)
  assert domain.snapshot() == before
  assert owner_path(ws).read_bytes() == owner_before


@pytest.mark.parametrize("phase", ["reserved", "owner_attached", "unknown", "single-sided-idle"])
def test_finish_rejects_non_dispatched_or_preexisting_idle(tmp_path, phase):
  ws, domain, cache, anchor = setup_case(tmp_path)
  with held(ws, cache, anchor) as args:
    if phase != "reserved":
      attach(domain, args)
    if phase in ("unknown", "single-sided-idle"):
      owners.dispatch_owner(domain, RUN, **args)
    if phase == "unknown":
      domain.mark_unknown(RUN)
    if phase == "single-sided-idle":
      run_owners.Registry(ws.state_root / "run-owners", ws.binding).finish_current(RUN, MANAGER, observation())
    before = domain.snapshot()
    with pytest.raises(Conflict):
      finish(domain, args)
    with pytest.raises(Conflict):
      reconcile(domain, args)
    assert domain.snapshot() == before


@pytest.mark.parametrize("target", ["pending", "owner-idle", "released"])
@pytest.mark.parametrize("committed", [False, True])
def test_release_interruption_and_response_loss_are_reconcilable(tmp_path, monkeypatch, target, committed):
  ws, domain, cache, anchor = dispatched(tmp_path)
  original = Tree.replace
  fired, receipt = [], []
  def replace(tree, name, data, *a, **kw):
    parsed = json.loads(data)
    entry = parsed.get("reservations", {}).get(RUN, {})
    if entry.get("phase") == "release_pending":
      receipt.append(deepcopy(entry["release_receipt"]))
    matches = (name == "coordination.json" and entry.get("phase") ==
      {"pending": "release_pending", "released": "released"}.get(target)) or (
      target == "owner-idle" and name == RUN + ".json" and parsed.get("lifecycle_state") == "idle_confirmed")
    if matches and not fired:
      fired.append(True)
      if committed:
        original(tree, name, data, *a, **kw)
      raise OSError("synthetic-private-release-write")
    return original(tree, name, data, *a, **kw)
  with held(ws, cache, anchor) as args:
    monkeypatch.setattr(Tree, "replace", replace)
    with pytest.raises(Conflict):
      finish(domain, args)
    monkeypatch.setattr(Tree, "replace", original)
    assert fired
    entry = domain.snapshot()["reservations"][RUN]
    expected = "dispatched" if target == "pending" and not committed else (
      "released" if target == "released" and committed else "release_pending")
    assert entry["phase"] == expected
    saved_receipt = deepcopy(entry.get("release_receipt"))
  assert_idle(domain, cache, anchor, blocked=expected != "released")
  with held(ws, cache, anchor) as args:
    if expected == "release_pending":
      reconcile(domain, args)
      assert domain.snapshot()["reservations"][RUN]["release_receipt"] == saved_receipt
      assert record(ws)["process_observation"]["observed_at_ns"] == saved_receipt["observed_at_ns"]
    elif expected == "dispatched":
      with pytest.raises(Conflict):
        reconcile(domain, args)
      finish(domain, args)
    else:
      before_owner = owner_path(ws).read_bytes()
      reconcile(domain, args)
      assert owner_path(ws).read_bytes() == before_owner
      assert domain.snapshot()["reservations"][RUN]["release_receipt"] == saved_receipt
  assert_idle(domain, cache, anchor, blocked=False)


@pytest.mark.parametrize("replacement", ["lock", "home", "instance", "registry", "receipt", "runtime", "owner"])
def test_finish_rejects_replaced_evidence_without_release_receipt(tmp_path, replacement):
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    if replacement in ("receipt", "owner"):
      path = ws.instance / ".agentcfg-omp-owner.json" if replacement == "receipt" else owner_path(ws)
      value = json.loads(path.read_bytes())
      if replacement == "receipt":
        value["owner_nonce"] = "e" * 32
      else:
        value["start_cwd"]["path"] = str(tmp_path / "different")
      path.write_text(json.dumps(value))
    else:
      path = {"lock": ws.instance / ".agentcfg-omp.lock", "home": ws.instance / "user-home",
        "registry": ws.state_root / "run-owners", "instance": ws.instance, "runtime": cache / "leases" / (IDENTITY + ".lock")}[replacement]
      old = path.with_name(path.name + "-old")
      path.rename(old)
      if replacement in ("lock", "runtime"):
        path.write_bytes(old.read_bytes())
        path.chmod(0o600)
      else:
        path.mkdir(mode=0o700)
        if replacement == "registry":
          (path / (RUN + ".json")).write_bytes((old / (RUN + ".json")).read_bytes())
        elif replacement == "instance":
          for name in (".agentcfg-omp.lock", ".agentcfg-omp-owner.json"):
            (path / name).write_bytes((old / name).read_bytes())
          (path / "user-home").mkdir(mode=0o700)
    with pytest.raises(Conflict):
      finish(domain, args)
  entry = domain.snapshot()["reservations"][RUN]
  assert entry["phase"] == "dispatched" and "release_receipt" not in entry


def test_finish_keeps_owner_lock_through_both_domain_commits(tmp_path, monkeypatch):
  ws, domain, cache, anchor = dispatched(tmp_path)
  original = Tree.replace
  seen = []
  def replace(tree, name, data, *a, **kw):
    if name == "coordination.json":
      phase = json.loads(data)["reservations"][RUN]["phase"]
      if phase in ("release_pending", "released"):
        with Tree(ws.state_root / "run-owners") as other:
          with pytest.raises(BlockingIOError):
            fcntl.flock(other.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        seen.append(phase)
    return original(tree, name, data, *a, **kw)
  monkeypatch.setattr(Tree, "replace", replace)
  with held(ws, cache, anchor) as args:
    finish(domain, args)
  assert seen == ["release_pending", "released"]


def test_existing_intent_does_not_block_natural_release_or_change_other_entries(tmp_path):
  ws, domain, cache, anchor = dispatched(tmp_path)
  batch = "e" * 32
  domain.accept_intent(batch_id=batch, generation=1, operation="stop_only",
    expected_revision=domain.snapshot()["revision"], resources=[anchor["resource_id"]], selected_runs=[RUN])
  before = deepcopy(domain.snapshot()["intents"])
  with held(ws, cache, anchor) as args:
    finish(domain, args)
  assert domain.snapshot()["intents"] == before
  assert_idle(domain, cache, anchor, blocked=True)


def test_release_only_selected_of_three_shared_package_runs(tmp_path):
  ws, domain, cache, anchor = dispatched(tmp_path)
  second, third = "e" * 32, "f" * 32
  for profile, run, op in (("omp-b", second, "1" * 32), ("omp-c", third, "2" * 32)):
    other = make_workspace(tmp_path, profile)
    reserve(domain, other, [anchor["resource_id"]], run=run, op=op)
    with held(other, cache, anchor) as args:
      attach(domain, args, run=run)
      owners.dispatch_owner(domain, run, **args)
  domain.mark_unknown(third)
  before = domain.snapshot()["reservations"]
  with held(ws, cache, anchor) as args:
    finish(domain, args)
  after = domain.snapshot()["reservations"]
  assert after[RUN]["phase"] == "released"
  assert after[second] == before[second]
  assert after[third] == before[third]
  assert_idle(domain, cache, anchor, blocked=True)


@pytest.mark.parametrize("damage", ["unknown", "bool-time", "float-time", "negative-time", "bad-digest", "missing-receipt", "dispatched-receipt"])
def test_release_schema_is_strict(tmp_path, damage):
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    finish(domain, args)
  state = domain.snapshot()
  entry = state["reservations"][RUN]
  if damage == "unknown":
    entry["release_receipt"]["permission"] = True
  elif damage in ("bool-time", "float-time", "negative-time"):
    entry["release_receipt"]["observed_at_ns"] = {"bool-time": True, "float-time": 1.5, "negative-time": -1}[damage]
  elif damage == "bad-digest":
    entry["release_receipt"]["owner_record_digest"] = "bad"
  elif damage == "missing-receipt":
    del entry["release_receipt"]
  else:
    entry["phase"] = damage.split("-")[0]
  with pytest.raises(Conflict):
    encode(state)


def test_owner_directory_fsync_failure_never_commits_released_and_can_reconcile(tmp_path, monkeypatch):
  ws, domain, cache, anchor = dispatched(tmp_path)
  directory = (ws.state_root / "run-owners").stat()
  original = os.fsync
  fired = []
  def fsync(fd):
    info = os.fstat(fd)
    if ((info.st_dev, info.st_ino) == (directory.st_dev, directory.st_ino)
        and json.loads(owner_path(ws).read_bytes())["lifecycle_state"] == "idle_confirmed" and not fired):
      fired.append(True)
      raise OSError("synthetic-private-owner-fsync")
    return original(fd)
  with held(ws, cache, anchor) as args:
    monkeypatch.setattr(os, "fsync", fsync)
    with pytest.raises(Conflict):
      finish(domain, args)
    monkeypatch.setattr(os, "fsync", original)
    assert fired
    entry = domain.snapshot()["reservations"][RUN]
    assert entry["phase"] == "release_pending"
    saved = deepcopy(entry["release_receipt"])
  assert_idle(domain, cache, anchor, blocked=True)
  with held(ws, cache, anchor) as args:
    reconcile(domain, args)
  assert domain.snapshot()["reservations"][RUN]["release_receipt"] == saved
  assert_idle(domain, cache, anchor, blocked=False)


def make_pending(domain, args, monkeypatch):
  original = Tree.replace
  def replace(tree, name, data, *a, **kw):
    if name == RUN + ".json" and json.loads(data).get("lifecycle_state") == "idle_confirmed":
      raise OSError("synthetic-private-before-owner-idle")
    return original(tree, name, data, *a, **kw)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", replace)
    with pytest.raises(Conflict):
      finish(domain, args)
  assert domain.snapshot()["reservations"][RUN]["phase"] == "release_pending"


@pytest.mark.parametrize("damage", ["manager", "incomplete", "record", "receipt", "home"])
def test_reconcile_requires_fresh_complete_same_manager_and_matching_evidence(tmp_path, monkeypatch, damage):
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    make_pending(domain, args, monkeypatch)
    observed = observation()
    if damage == "manager":
      monkeypatch.setattr(run_owners, "current_process_identity", lambda: {"pid": 3133714, "birth_id": "other"})
    elif damage == "incomplete":
      observed = observation(complete=False)
    elif damage == "record":
      value = json.loads(owner_path(ws).read_bytes())
      value["start_cwd"]["path"] = str(tmp_path / "other")
      owner_path(ws).write_text(json.dumps(value))
    elif damage == "receipt":
      with Tree(tmp_path / "domain") as tree:
        raw = tree.read("coordination.json")
        state = json.loads(raw[0])
        state["reservations"][RUN]["release_receipt"]["owner_record_digest"] = "e" * 64
        tree.replace("coordination.json", encode(state), expected=raw[2])
    else:
      home = ws.instance / "user-home"
      home.rename(home.with_name("old-home"))
      home.mkdir(mode=0o700)
    before = domain.snapshot()
    with pytest.raises(Conflict):
      reconcile(domain, args, observed=observed)
    assert domain.snapshot() == before
  assert_idle(domain, cache, anchor, blocked=True)


def test_reconcile_rejects_receipt_time_different_from_existing_idle_record(tmp_path, monkeypatch):
  ws, domain, cache, anchor = dispatched(tmp_path)
  original = Tree.replace
  def replace(tree, name, data, *a, **kw):
    if name == "coordination.json" and json.loads(data)["reservations"][RUN]["phase"] == "released":
      raise OSError("synthetic-private-final-ledger")
    return original(tree, name, data, *a, **kw)
  with held(ws, cache, anchor) as args:
    with monkeypatch.context() as patch:
      patch.setattr(Tree, "replace", replace)
      with pytest.raises(Conflict):
        finish(domain, args)
    assert record(ws)["lifecycle_state"] == "idle_confirmed"
    with Tree(tmp_path / "domain") as tree:
      raw = tree.read("coordination.json")
      state = json.loads(raw[0])
      receipt = state["reservations"][RUN]["release_receipt"]
      receipt["observed_at_ns"] += 1
      tree.replace("coordination.json", encode(state), expected=raw[2])
    before = domain.snapshot()
    with pytest.raises(Conflict):
      reconcile(domain, args)
    assert domain.snapshot() == before


def test_unknown_retains_release_receipt_but_is_never_reconciled(tmp_path, monkeypatch):
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    make_pending(domain, args, monkeypatch)
    before = deepcopy(domain.snapshot()["reservations"][RUN]["release_receipt"])
    domain.mark_unknown(RUN)
    entry = domain.snapshot()["reservations"][RUN]
    assert entry["phase"] == "unknown" and entry["release_receipt"] == before
    encode(domain.snapshot())
    for call in (lambda: finish(domain, args), lambda: reconcile(domain, args), lambda: domain.cancel_reserved(RUN)):
      with pytest.raises(Conflict):
        call()
  assert_idle(domain, cache, anchor, blocked=True)


@pytest.mark.parametrize("target", ["owner-file", "owner-ancestor"])
@pytest.mark.parametrize("synced", [False, True])
def test_recheck_fsync_failure_preserves_pending_until_retry(tmp_path, monkeypatch, target, synced):
  ws, domain, cache, anchor = dispatched(tmp_path)
  original_sync, original_fsync = owners._sync_completed_owner, os.fsync
  in_recheck, fired = [], []
  def sync(*a, **kw):
    in_recheck.append(True)
    try:
      return original_sync(*a, **kw)
    finally:
      in_recheck.pop()
  def fsync(fd):
    info = os.fstat(fd)
    expected = (owner_path(ws) if target == "owner-file" else ws.state_root).stat()
    if in_recheck and not fired and (info.st_dev, info.st_ino) == (expected.st_dev, expected.st_ino):
      fired.append(True)
      if synced:
        original_fsync(fd)
      raise OSError("synthetic-private-recheck-fsync")
    return original_fsync(fd)
  with held(ws, cache, anchor) as args:
    with monkeypatch.context() as patch:
      patch.setattr(owners, "_sync_completed_owner", sync)
      patch.setattr(os, "fsync", fsync)
      with pytest.raises(Conflict):
        finish(domain, args)
    assert fired
    saved = deepcopy(domain.snapshot()["reservations"][RUN])
    assert saved["phase"] == "release_pending"
    assert record(ws)["lifecycle_state"] == "idle_confirmed"
  assert_idle(domain, cache, anchor, blocked=True)
  with held(ws, cache, anchor) as args:
    reconcile(domain, args)
  entry = domain.snapshot()["reservations"][RUN]
  assert entry["release_receipt"] == saved["release_receipt"]
  assert entry["phase"] == "released"


def test_busy_owner_lock_refuses_release_nonblocking(tmp_path, monkeypatch):
  ws, domain, cache, anchor = dispatched(tmp_path)
  original = fcntl.flock
  seen = []
  with held(ws, cache, anchor) as args, Tree(ws.state_root / "run-owners") as busy:
    original(busy.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    physical = os.fstat(busy.fd)
    def flock(fd, flags):
      info = os.fstat(fd)
      if fd != busy.fd and (info.st_dev, info.st_ino) == (physical.st_dev, physical.st_ino):
        assert flags & fcntl.LOCK_NB
        seen.append(flags)
      return original(fd, flags)
    monkeypatch.setattr(fcntl, "flock", flock)
    with pytest.raises(Conflict):
      finish(domain, args)
  assert seen
  assert domain.snapshot()["reservations"][RUN]["phase"] == "dispatched"


@pytest.mark.parametrize("target", ["instance", "home", "runtime", "missing-runtime", "extra-runtime"])
def test_release_requires_all_exact_physical_fds(tmp_path, target):
  ws, domain, cache, anchor = dispatched(tmp_path)
  with held(ws, cache, anchor) as args:
    bad = {**args, "runtime_fds": dict(args["runtime_fds"])}
    if target == "instance":
      bad["instance_fd"] = args["native_home_fd"]
    elif target == "home":
      bad["native_home_fd"] = args["instance_fd"]
    elif target == "runtime":
      bad["runtime_fds"][anchor["resource_id"]] = args["instance_fd"]
    elif target == "missing-runtime":
      bad["runtime_fds"] = {}
    else:
      bad["runtime_fds"]["e" * 32] = next(iter(args["runtime_fds"].values()))
    with pytest.raises(Conflict):
      finish(domain, bad)
  assert domain.snapshot()["reservations"][RUN]["phase"] == "dispatched"
  assert record(ws)["lifecycle_state"] == "active"


@pytest.mark.parametrize("replacement", ["owner-file", "registry-root"])
def test_post_sync_replacement_keeps_release_pending(tmp_path, monkeypatch, replacement):
  ws, domain, cache, anchor = dispatched(tmp_path)
  original = owners._sync_completed_owner
  fired = []
  def sync(*a, **kw):
    original(*a, **kw)
    fired.append(True)
    path = owner_path(ws) if replacement == "owner-file" else ws.state_root / "run-owners"
    old = path.with_name(path.name + "-old")
    path.rename(old)
    if replacement == "owner-file":
      value = json.loads(old.read_bytes())
      value["start_cwd"]["path"] = str(tmp_path / "different-cwd")
      path.write_text(json.dumps(value))
    else:
      path.mkdir(mode=0o700)
      (path / (RUN + ".json")).write_bytes((old / (RUN + ".json")).read_bytes())
  with held(ws, cache, anchor) as args:
    monkeypatch.setattr(owners, "_sync_completed_owner", sync)
    with pytest.raises(Conflict):
      finish(domain, args)
  assert fired
  assert domain.snapshot()["reservations"][RUN]["phase"] == "release_pending"
  assert_idle(domain, cache, anchor, blocked=True)


def test_released_directory_fsync_failure_can_only_repeat_exact_sync(tmp_path, monkeypatch):
  ws, domain, cache, anchor = dispatched(tmp_path)
  other = make_workspace(tmp_path, "omp-other")
  other_run = "e" * 32
  reserve(domain, other, [anchor["resource_id"]], run=other_run, op="f" * 32)
  with held(other, cache, anchor) as args:
    attach(domain, args, run=other_run)
    owners.dispatch_owner(domain, other_run, **args)
  domain.accept_intent(batch_id="1" * 32, generation=1, operation="stop_only",
    expected_revision=domain.snapshot()["revision"], resources=[anchor["resource_id"]], selected_runs=[RUN, other_run])
  before = domain.snapshot()
  physical = (tmp_path / "domain").stat()
  original_fsync, original_replace = os.fsync, Tree.replace
  fired = []
  def fsync(fd):
    info = os.fstat(fd)
    if ((info.st_dev, info.st_ino) == (physical.st_dev, physical.st_ino)
        and json.loads((tmp_path / "domain/coordination.json").read_bytes())["reservations"][RUN]["phase"] == "released"
        and not fired):
      fired.append(True)
      raise OSError("synthetic-private-after-ledger-rename-fsync")
    return original_fsync(fd)
  with held(ws, cache, anchor) as args:
    with monkeypatch.context() as patch:
      patch.setattr(os, "fsync", fsync)
      with pytest.raises(Conflict):
        finish(domain, args)
    assert fired
    visible = domain.snapshot()
    assert visible["reservations"][RUN]["phase"] == "released"
    assert record(ws)["lifecycle_state"] == "idle_confirmed"
    assert visible["reservations"][other_run] == before["reservations"][other_run]
    assert visible["intents"] == before["intents"]
    owner_bytes = owner_path(ws).read_bytes()
    receipt = deepcopy(visible["reservations"][RUN]["release_receipt"])
    def no_owner_write(tree, name, data, *a, **kw):
      assert name != RUN + ".json", "released reconciliation must not rewrite owner"
      return original_replace(tree, name, data, *a, **kw)
    with monkeypatch.context() as patch:
      patch.setattr(Tree, "replace", no_owner_write)
      reconcile(domain, args)
    after = domain.snapshot()
    assert after["reservations"][RUN]["release_receipt"] == receipt
    assert owner_path(ws).read_bytes() == owner_bytes
    assert after["reservations"][other_run] == before["reservations"][other_run]
    assert after["intents"] == before["intents"]


@pytest.mark.parametrize("damage", ["current-manager", "observation-manager", "incomplete", "active", "unknown", "home", "runtime", "registry", "receipt-time"])
def test_released_reconcile_still_requires_exact_idle_proof_and_physical_bindings(tmp_path, monkeypatch, damage):
  ws, domain, cache, anchor = dispatched(tmp_path)
  active_bytes = owner_path(ws).read_bytes()
  with held(ws, cache, anchor) as args:
    finish(domain, args)
    observed = observation()
    if damage == "current-manager":
      monkeypatch.setattr(run_owners, "current_process_identity", lambda: {"pid": 3133714, "birth_id": "other"})
    elif damage == "observation-manager":
      observed = observation(manager_identity={"pid": 3133714, "birth_id": "other"})
    elif damage == "incomplete":
      observed = observation(complete=False)
    elif damage in ("active", "unknown"):
      owner_path(ws).write_bytes(active_bytes)
      if damage == "unknown":
        run_owners.Registry(ws.state_root / "run-owners", ws.binding).mark_unknown(RUN, MANAGER)
    elif damage == "receipt-time":
      with Tree(tmp_path / "domain") as tree:
        raw = tree.read("coordination.json")
        state = json.loads(raw[0])
        state["reservations"][RUN]["release_receipt"]["observed_at_ns"] += 1
        tree.replace("coordination.json", encode(state), expected=raw[2])
    else:
      path = {"home": ws.instance / "user-home", "registry": ws.state_root / "run-owners",
        "runtime": cache / "leases" / (IDENTITY + ".lock")}[damage]
      old = path.with_name(path.name + "-old")
      path.rename(old)
      if damage == "runtime":
        path.write_bytes(old.read_bytes())
        path.chmod(0o600)
      else:
        path.mkdir(mode=0o700)
        if damage == "registry":
          (path / (RUN + ".json")).write_bytes((old / (RUN + ".json")).read_bytes())
    before = domain.snapshot()
    before_owner = owner_path(ws).read_bytes()
    with pytest.raises(Conflict):
      reconcile(domain, args, observed=observed)
    assert domain.snapshot() == before
    assert owner_path(ws).read_bytes() == before_owner
