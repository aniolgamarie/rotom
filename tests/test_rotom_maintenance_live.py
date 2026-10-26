"""只读 live 接缝；真实临时锁/owner，虚构进程且不发送信号。"""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import fcntl
import json
import os
from types import SimpleNamespace

import pytest

from agentcfg import maintenance, maintenance_live as live, resource_owners as owners, run_owners
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance import acceptance as make_acceptance
from test_rotom_maintenance_recovery import group, RUNS
from test_rotom_omp_setup_admission import contents
from test_rotom_resource_owners import IDENTITY, MANAGER, attach, metadata, owner_path, reserve


@pytest.fixture
def ready(group):
  case = group()
  for row in case.rows:
    row.workspace.cache = row.cache
  return case


@contextmanager
def leased(case, chosen=None):
  chosen = RUNS[:2] if chosen is None else chosen
  with ExitStack() as stack:
    result, opened = {}, {}
    for row in case.rows:
      if row.run not in chosen:
        continue
      key = (row.workspace.instance, row.workspace.state_root)
      if key not in opened:
        ws = row.workspace
        physical = stack.enter_context(_shared_file(ws.instance, ".agentcfg-omp.lock"))
        home = stack.enter_context(Tree(ws.instance / "user-home"))
        state = stack.enter_context(_shared_file(ws.state_root, "instance.lock"))
        package = stack.enter_context(_shared_file(row.cache, "leases/" + getattr(row, "identity", IDENTITY) + ".lock"))
        opened[key] = {"workspace": ws, "instance_fd": physical, "state_fd": state,
          "native_home_fd": home.fd, "runtime_fds": {row.runtime["resource_id"]: package}}
      result[row.run] = dict(opened[key])
    yield result


def call(case, value, leases, stack):
  with case.domain._transaction() as state:
    return live.hold_stop_owners(case.domain, state, acceptance=value, leases=leases, stack=stack)


def fd_values(leases):
  return {fd for value in leases.values() for fd in (value["instance_fd"], value["state_fd"],
    value["native_home_fd"], *value["runtime_fds"].values())}


def test_success_is_readonly_and_owner_locks_survive_domain_transaction_until_caller_stack_exits(ready):
  value = make_acceptance(ready)
  before = contents(ready.cache.parent)
  with leased(ready) as leases:
    with ExitStack() as stack:
      assert call(ready, value, leases, stack) is None
      for row in ready.rows[:2]:
        with Tree(row.workspace.state_root / "run-owners") as tree:
          with pytest.raises(BlockingIOError):
            fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      for fd in fd_values(leases): os.fstat(fd)
    for row in ready.rows[:2]:
      with Tree(row.workspace.state_root / "run-owners") as tree:
        fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    for fd in fd_values(leases): os.fstat(fd)
  assert contents(ready.cache.parent) == before


def test_owner_file_can_drift_independently_of_unchanged_coordination_digest_and_is_rejected(ready):
  value = make_acceptance(ready)
  path = owner_path(ready.rows[0].workspace, RUNS[0])
  record = json.loads(path.read_bytes())
  record["start_cwd"]["path"] = "/synthetic-private-drift"
  path.write_bytes(run_owners._encode(record))
  before = contents(ready.cache.parent)
  with leased(ready) as leases, ExitStack() as stack, pytest.raises(Conflict) as caught:
    call(ready, value, leases, stack)
  assert "synthetic-private" not in str(caught.value) and contents(ready.cache.parent) == before


@pytest.mark.parametrize("field", ["instance_fd", "state_fd", "native_home_fd", "runtime"])
@pytest.mark.parametrize("fault", ["closed", "wrong", "bool", "negative"])
def test_bad_fds_never_close_other_borrowed_fds_or_mutate(ready, field, fault):
  value = make_acceptance(ready)
  with leased(ready) as original, ExitStack() as stack:
    leases = {run: {**item, "runtime_fds": dict(item["runtime_fds"])} for run, item in original.items()}
    item = leases[RUNS[0]]
    if fault == "closed":
      replacement = os.dup(item["state_fd"])
      os.close(replacement)
    elif fault == "wrong": replacement = item["instance_fd"] if field != "instance_fd" else item["state_fd"]
    elif fault == "bool": replacement = True
    else: replacement = -1
    if field == "runtime": item["runtime_fds"] = {next(iter(item["runtime_fds"])): replacement}
    else: item[field] = replacement
    before = contents(ready.cache.parent)
    with pytest.raises(Conflict): call(ready, value, leases, stack)
    for fd in fd_values(original): os.fstat(fd)
    assert contents(ready.cache.parent) == before


@pytest.mark.parametrize("change", ["missing-run", "extra-run", "extra-field", "missing-field", "runtime-missing", "runtime-extra", "cache", "scope", "revision"])
def test_exact_sets_workspace_cache_scope_and_revision_are_rechecked(ready, change):
  value = make_acceptance(ready)
  with leased(ready) as leases, ExitStack() as stack:
    item = leases[RUNS[0]]
    if change == "missing-run": del leases[RUNS[0]]
    elif change == "extra-run": leases[RUNS[2]] = dict(item)
    elif change == "extra-field": item["extra"] = True
    elif change == "missing-field": del item["state_fd"]
    elif change == "runtime-missing": item["runtime_fds"] = {}
    elif change == "runtime-extra": item["runtime_fds"]["f" * 32] = item["instance_fd"]
    elif change == "revision": value["expected_revision"] += 1
    else:
      item["workspace"] = SimpleNamespace(**vars(item["workspace"]))
      if change == "cache": item["workspace"].cache = item["workspace"].cache.parent / "other-cache"
      else: item["workspace"].binding = {**item["workspace"].binding, "profile": "different-profile"}
    before = contents(ready.cache.parent)
    with pytest.raises(Conflict): call(ready, value, leases, stack)
    assert contents(ready.cache.parent) == before


def test_owner_lock_contention_is_nonblocking_and_does_not_create_files(ready):
  value = make_acceptance(ready)
  registry = run_owners.Registry(ready.rows[0].workspace.state_root / "run-owners", ready.rows[0].workspace.binding)
  with leased(ready) as leases, registry._locked(), ExitStack() as stack:
    before = contents(ready.cache.parent)
    with pytest.raises(Conflict): call(ready, value, leases, stack)
    assert contents(ready.cache.parent) == before


@pytest.mark.parametrize("damage", ["missing-owner", "owner-null-link", "orphan-owner", "pending", "unknown"])
def test_missing_or_unlinked_or_unconfirmed_coverage_refuses_without_cleanup(ready, damage):
  value = make_acceptance(ready)
  if damage == "missing-owner": owner_path(ready.rows[0].workspace, RUNS[0]).unlink()
  elif damage in ("owner-null-link", "orphan-owner"):
    path = owner_path(ready.rows[0].workspace, RUNS[0])
    record = json.loads(path.read_bytes())
    if damage == "owner-null-link": record["coordination_domain"] = None
    else:
      record["run_id"] = "f" * 32
      path = path.with_name(record["run_id"] + ".json")
    path.write_bytes(run_owners._encode(record))
  else:
    with ready.domain._transaction(write=True) as state:
      state["reservations"][RUNS[0]]["phase"] = "owner_pending" if damage == "pending" else "unknown"
    value["expected_revision"] = ready.domain.snapshot()["revision"]
    for resource in value["batch"]["plan"]["resources"]: resource["generation"] = value["expected_revision"]
    value["batch"]["plan"] = maintenance._plan(value["batch"]["plan"], verify=False)
  before = contents(ready.cache.parent)
  with leased(ready) as leases, ExitStack() as stack, pytest.raises(Conflict):
    call(ready, value, leases, stack)
  assert contents(ready.cache.parent) == before


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit])
def test_control_interrupt_propagates_original_object(ready, monkeypatch, error_type):
  value = make_acceptance(ready)
  error = error_type("synthetic-control")
  def interrupted(*args, **kwargs): raise error
  monkeypatch.setattr(owners, "_check_link", interrupted)
  with leased(ready) as leases, ExitStack() as stack, pytest.raises(error_type) as caught:
    call(ready, value, leases, stack)
  assert caught.value is error


def test_state_lock_replaced_after_owner_lock_acquisition_is_rejected(ready, monkeypatch):
  value = make_acceptance(ready)
  ws = ready.rows[0].workspace
  original = run_owners.Registry._locked
  replacements = []
  @contextmanager
  def locked(registry, *args, **kwargs):
    with original(registry, *args, **kwargs) as tree:
      if registry.root == ws.state_root / "run-owners" and not replacements:
        path = ws.state_root / "instance.lock"
        old = path.stat().st_ino
        raw = path.read_bytes()
        path.unlink()
        path.write_bytes(raw)
        path.chmod(0o600)
        assert path.stat().st_ino != old
        replacements.append(True)
      yield tree
  monkeypatch.setattr(run_owners.Registry, "_locked", locked)
  with leased(ready) as leases, ExitStack() as stack, pytest.raises(Conflict):
    call(ready, value, leases, stack)
  assert replacements == [True]


def test_two_selected_runs_in_same_registry_take_only_one_owner_lock(ready, monkeypatch):
  row = ready.rows[0]
  run = "f" * 32
  reserve(ready.domain, row.workspace, sorted(row.resources), run=run, op="e" * 32)
  with leased(ready, chosen=[row.run]) as leases:
    args = {name: leases[row.run][name] for name in ("workspace", "instance_fd", "native_home_fd", "runtime_fds")}
    attach(ready.domain, args, run=run)
    owners.dispatch_owner(ready.domain, run, **args)
  ready.rows.append(SimpleNamespace(**{**vars(row), "run": run}))
  chosen = [row.run, run]
  value = make_acceptance(ready, chosen=chosen)
  original, calls = run_owners.Registry._locked, []
  @contextmanager
  def locked(registry, *args, **kwargs):
    assert kwargs.get("nonblocking") is True
    calls.append(registry.root)
    with original(registry, *args, **kwargs) as tree:
      yield tree
  monkeypatch.setattr(run_owners.Registry, "_locked", locked)
  with leased(ready, chosen=chosen) as leases, ExitStack() as stack:
    assert call(ready, value, leases, stack) is None
  assert calls == [row.workspace.state_root / "run-owners"]


@pytest.mark.parametrize("resource", ["instance", "home", "runtime"])
def test_replaced_named_resources_reject_still_open_original_fds(ready, resource):
  value = make_acceptance(ready)
  row = ready.rows[0]
  with leased(ready) as leases, ExitStack() as stack:
    if resource == "home":
      home = row.workspace.instance / "user-home"
      home.rename(home.with_name("synthetic-old-home"))
      home.mkdir(mode=0o700)
    else:
      path = (row.workspace.instance / ".agentcfg-omp.lock" if resource == "instance"
        else row.cache / "leases" / (IDENTITY + ".lock"))
      data = path.read_bytes()
      path.unlink()
      path.write_bytes(data)
      path.chmod(0o600)
    with pytest.raises(Conflict): call(ready, value, leases, stack)
    for fd in fd_values(leases): os.fstat(fd)


def test_historical_released_record_does_not_require_its_old_package_anchor(ready):
  from agentcfg import resource_coordination as core
  from test_rotom_resource_scopes import scope_ids
  old = ready.rows[0]
  with leased(ready, chosen=[old.run]) as leases:
    args = {name: leases[old.run][name] for name in ("workspace", "instance_fd", "native_home_fd", "runtime_fds")}
    owners.finish_owner(ready.domain, old.run,
      observation=run_owners.ReleaseObservation(old.run, MANAGER, True, True), **args)
  identity, run = "e" * 64, "f" * 32
  anchor = core.enroll_runtime(ready.domain, old.cache, identity)
  row = SimpleNamespace(workspace=old.workspace, cache=old.cache, runtime=anchor, identity=identity,
    scope=old.scope, resources=scope_ids(old.scope) | {anchor["resource_id"]}, run=run)
  ready.rows[0] = row
  reserve(ready.domain, row.workspace, sorted(row.resources), run=run, op="e" * 32)
  with leased(ready, chosen=[run]) as leases:
    args = {name: leases[run][name] for name in ("workspace", "instance_fd", "native_home_fd", "runtime_fds")}
    supplied = metadata(row.workspace)
    supplied["deployed_identity"]["runtime"] = identity
    attach(ready.domain, args, run=run, supplied=supplied)
    owners.dispatch_owner(ready.domain, run, **args)
  value = make_acceptance(ready, chosen=[run])
  (old.cache / "leases" / (IDENTITY + ".lock")).unlink()
  before = contents(ready.cache.parent)
  with leased(ready, chosen=[run]) as leases, ExitStack() as stack:
    assert call(ready, value, leases, stack) is None
  assert contents(ready.cache.parent) == before
