"""T063 部分原语组合：不实现 setup、stop 或恢复部署，不执行宿主进程。"""
from copy import deepcopy
import fcntl
import json
import os
import stat
from types import SimpleNamespace

import pytest

from agentcfg import resource_coordination as core, resource_owners as owners, run_owners
from agentcfg.storage import Conflict, Tree
from test_rotom_resource_coordination import locked
from test_rotom_resource_owners import IDENTITY, MANAGER, attach, owner_path, reserve
from test_rotom_resource_scopes import held_scope, scope_ids, scopes, workspace


RUNS = tuple(character * 32 for character in "123")
OPS = tuple(character * 32 for character in "456")
BATCH = "7" * 32


@pytest.fixture
def group(tmp_path, monkeypatch):
  monkeypatch.setattr(run_owners, "current_process_identity", lambda: deepcopy(MANAGER))
  def build(*, separate_third=False):
    domain = core.initialize_domain(tmp_path / "domain")
    cache = tmp_path / "shared-cache"
    runtime = core.enroll_runtime(domain, cache, IDENTITY)
    rows = []
    for index, (run, op) in enumerate(zip(RUNS, OPS)):
      ws = workspace(tmp_path, "omp-" + str(index))
      anchor = scopes().enroll_scope(domain, ws)
      selected_cache, selected_runtime = cache, runtime
      if index == 2 and separate_third:
        selected_cache = tmp_path / "independent-cache"
        selected_runtime = core.enroll_runtime(domain, selected_cache, IDENTITY)
      resources = scope_ids(anchor) | {selected_runtime["resource_id"]}
      reserve(domain, ws, sorted(resources), run=run, op=op)
      with held_scope(ws, selected_cache, selected_runtime) as args:
        attach(domain, args, run=run)
        owners.dispatch_owner(domain, run, **args)
      rows.append(SimpleNamespace(workspace=ws, cache=selected_cache, runtime=selected_runtime,
        scope=anchor, resources=resources, run=run))
    return SimpleNamespace(domain=domain, rows=rows, cache=cache, runtime=runtime)
  return build


def accept(domain, resources, selected, *, revision=None, operation="setup"):
  domain.accept_intent(batch_id=BATCH, generation=1, operation=operation,
    expected_revision=domain.snapshot()["revision"] if revision is None else revision,
    resources=sorted(resources), selected_runs=list(selected))


def ledger(domain):
  return (domain.root / "coordination.json").read_bytes()


def idle_blocked(group):
  # 取得物理 EX 只证明这次 fd 可排他，不代替持久 owner 的退出证明。
  with locked(group.cache, IDENTITY, exclusive=True) as fd:
    with pytest.raises(Conflict):
      group.domain.check_runtime(group.cache, IDENTITY, lease_fd=fd, idle=True)


def test_three_shared_runtime_owners_cannot_be_silently_reduced_to_two(group):
  case = group()
  selected = set.union(*(row.resources for row in case.rows[:2]))
  before = ledger(case.domain)
  owners_before = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  with pytest.raises(Conflict):
    accept(case.domain, selected, RUNS[:2])
  assert ledger(case.domain) == before and case.domain.snapshot()["intents"] == {}
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == owners_before
  assert set(case.domain.snapshot()["reservations"]) == set(RUNS)


def test_stop_only_accepts_two_known_owners_without_touching_the_shared_third(group):
  case = group()
  selected = set.union(*(row.resources for row in case.rows[:2]))
  third = deepcopy(case.domain.snapshot()["reservations"][RUNS[2]])
  owners_before = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  accept(case.domain, selected, RUNS[:2], operation="stop_only")
  case.domain.dispatch_intent(BATCH)
  saved = case.domain.snapshot()
  assert saved["intents"][BATCH]["operation"] == "stop_only"
  assert saved["intents"][BATCH]["selected_runs"] == list(RUNS[:2])
  assert saved["reservations"][RUNS[2]] == third
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == owners_before
  idle_blocked(case)


@pytest.mark.parametrize("operation", ["setup", "stop_only"])
@pytest.mark.parametrize("missing", ["instance", "native-home", "runtime"])
def test_intent_cannot_omit_any_selected_run_resource(group, operation, missing):
  case = group()
  chosen = case.rows if operation == "setup" else case.rows[:2]
  resources = set.union(*(row.resources for row in chosen))
  state = case.domain.snapshot()
  omitted = next(rid for rid in case.rows[0].resources if state["resources"][rid]["key"]["kind"] == missing)
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    accept(case.domain, resources - {omitted}, [row.run for row in chosen], operation=operation)
  assert ledger(case.domain) == before and case.domain.snapshot()["intents"] == {}


@pytest.mark.parametrize("operation", ["setup", "stop_only"])
@pytest.mark.parametrize("missing", ["instance", "native-home", "runtime"])
def test_intent_rechecks_selected_resource_closure_before_dispatch(group, operation, missing):
  case = group()
  chosen = case.rows if operation == "setup" else case.rows[:2]
  resources = set.union(*(row.resources for row in chosen))
  accept(case.domain, resources, [row.run for row in chosen], operation=operation)
  with case.domain._transaction(write=True) as state:
    omitted = next(rid for rid in case.rows[0].resources if state["resources"][rid]["key"]["kind"] == missing)
    state["intents"][BATCH]["resources"].remove(omitted)
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    case.domain.dispatch_intent(BATCH)
  assert ledger(case.domain) == before
  assert case.domain.snapshot()["intents"][BATCH]["phase"] == "active"


@pytest.mark.parametrize("stage", ["accept", "dispatch"])
def test_stop_only_cannot_fence_unselected_third_scope(group, stage):
  case = group()
  resources = set.union(*(row.resources for row in case.rows[:2]))
  third_scope = case.rows[2].resources - resources
  if stage == "dispatch":
    accept(case.domain, resources, RUNS[:2], operation="stop_only")
    with case.domain._transaction(write=True) as state:
      state["intents"][BATCH]["resources"] = sorted(resources | third_scope)
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    if stage == "accept":
      accept(case.domain, resources | third_scope, RUNS[:2], operation="stop_only")
    else:
      case.domain.dispatch_intent(BATCH)
  assert ledger(case.domain) == before


@pytest.mark.parametrize("phase", ["reserved", "unknown"])
def test_stop_only_does_not_ignore_unconfirmed_shared_references(group, tmp_path, phase):
  case = group()
  if phase == "unknown":
    case.domain.mark_unknown(RUNS[2])
  else:
    other = workspace(tmp_path, "omp-pending")
    anchor = scopes().enroll_scope(case.domain, other)
    reserve(case.domain, other, sorted(scope_ids(anchor) | {case.runtime["resource_id"]}),
      run="8" * 32, op="9" * 32)
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    accept(case.domain, set.union(*(row.resources for row in case.rows[:2])), RUNS[:2], operation="stop_only")
  assert ledger(case.domain) == before


def test_stop_only_rechecks_unknown_third_before_dispatch_and_blocks_new_reservations(group, tmp_path):
  case = group()
  resources = set.union(*(row.resources for row in case.rows[:2]))
  accept(case.domain, resources, RUNS[:2], operation="stop_only")
  late = workspace(tmp_path, "omp-late")
  anchor = scopes().enroll_scope(case.domain, late)
  with pytest.raises(Conflict):
    reserve(case.domain, late, sorted(scope_ids(anchor) | {case.runtime["resource_id"]}),
      run="8" * 32, op="9" * 32)
  case.domain.mark_unknown(RUNS[2])
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    case.domain.dispatch_intent(BATCH)
  assert ledger(case.domain) == before


def test_unknown_third_blocks_despite_closed_leases_empty_other_registry_and_package_ex(group, tmp_path):
  case = group()
  for row in case.rows[:2]:
    with held_scope(row.workspace, row.cache, row.runtime) as args:
      observed = run_owners.ReleaseObservation(row.run, deepcopy(MANAGER), True, True)
      owners.finish_owner(case.domain, row.run, observation=observed, **args)
  third = case.rows[2]
  case.domain.mark_unknown(third.run)
  # 另一个 Registry 的空快照不能证明共享包全局空闲。
  empty = run_owners.Registry(tmp_path / "other-empty-state/run-owners", {
    "machine": "synthetic-machine", "local": str(tmp_path / "other.toml"), "profile": "omp-empty"})
  assert empty.snapshot() == {} and not empty.root.exists()
  before, owner_before = ledger(case.domain), owner_path(third.workspace, third.run).read_bytes()
  idle_blocked(case)
  for selected in ([], [third.run]):
    with pytest.raises(Conflict):
      accept(case.domain, {case.runtime["resource_id"]}, selected)
  assert ledger(case.domain) == before and owner_path(third.workspace, third.run).read_bytes() == owner_before
  assert case.domain.snapshot()["reservations"][third.run]["phase"] == "unknown"


def test_independent_third_runtime_is_not_added_or_rewritten_when_accepting_two(group):
  case = group(separate_third=True)
  third = case.rows[2]
  before = deepcopy(case.domain.snapshot()["reservations"][third.run])
  owner_before = owner_path(third.workspace, third.run).read_bytes()
  selected = set.union(*(row.resources for row in case.rows[:2]))
  snapshot = case.domain.snapshot()
  accept(case.domain, selected, RUNS[:2], revision=snapshot["revision"])
  saved = case.domain.snapshot()
  assert saved["intents"][BATCH]["selected_runs"] == list(RUNS[:2])
  assert saved["intents"][BATCH]["resources"] == sorted(selected)
  assert saved["reservations"][third.run] == before
  assert owner_path(third.workspace, third.run).read_bytes() == owner_before


def test_intersecting_reservation_after_snapshot_invalidates_old_revision(group, tmp_path):
  case = group(separate_third=True)
  other = workspace(tmp_path, "omp-late")
  anchor = scopes().enroll_scope(case.domain, other)
  snapshot = case.domain.snapshot()
  reserve(case.domain, other, sorted(scope_ids(anchor) | {case.runtime["resource_id"]}),
    run="8" * 32, op="9" * 32)
  assert case.domain.snapshot()["revision"] == snapshot["revision"] + 1
  before = ledger(case.domain)
  with pytest.raises(Conflict):
    accept(case.domain, {case.runtime["resource_id"]}, RUNS[:2], revision=snapshot["revision"])
  assert ledger(case.domain) == before and case.domain.snapshot()["intents"] == {}
  assert case.domain.snapshot()["reservations"]["8" * 32]["phase"] == "reserved"


@pytest.mark.parametrize("alias", ["same-cache", "symlink", "hardlink"])
def test_shared_cache_cannot_be_reenrolled_as_an_independent_domain(tmp_path, alias):
  first = core.initialize_domain(tmp_path / "domain-a")
  second = core.initialize_domain(tmp_path / "domain-b")
  cache = tmp_path / "cache"
  core.enroll_runtime(first, cache, IDENTITY)
  original = cache / "leases" / (IDENTITY + ".lock")
  raw = original.read_bytes()
  candidate = cache
  if alias == "symlink":
    candidate = tmp_path / "cache-alias"
    candidate.symlink_to(cache, target_is_directory=True)
  elif alias == "hardlink":
    candidate = tmp_path / "cache-alias"
    (candidate / "leases").mkdir(mode=0o700, parents=True)
    os.link(original, candidate / "leases" / original.name)
  before = ledger(first), ledger(second)
  with pytest.raises(Conflict):
    core.enroll_runtime(second, candidate, IDENTITY)
  assert (ledger(first), ledger(second)) == before
  assert second.snapshot()["resources"] == {} and original.read_bytes() == raw


@pytest.mark.parametrize("phase", ["owner_attached", "dispatched"])
@pytest.mark.parametrize("failure", ["directory-fsync", "lost-response"])
def test_committed_attach_or_dispatch_error_cannot_cancel_or_reaccept_away_protection(tmp_path, monkeypatch, phase, failure):
  domain = core.initialize_domain(tmp_path / "domain")
  ws = workspace(tmp_path)
  scope = scopes().enroll_scope(domain, ws)
  cache = tmp_path / "cache"
  runtime = core.enroll_runtime(domain, cache, IDENTITY)
  resources = scope_ids(scope) | {runtime["resource_id"]}
  reserve(domain, ws, sorted(resources), run=RUNS[0], op=OPS[0])
  original_replace, original_fsync = Tree.replace, os.fsync
  fired = []
  def replace(tree, name, data, *args, **kwargs):
    matches = name == "coordination.json" and json.loads(data)["reservations"].get(RUNS[0], {}).get("phase") == phase
    if not matches or fired:
      return original_replace(tree, name, data, *args, **kwargs)
    fired.append(True)
    if failure == "directory-fsync":
      def fsync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
          raise OSError("synthetic-private-fsync-failure")
        return original_fsync(fd)
      with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", fsync)
        return original_replace(tree, name, data, *args, **kwargs)
    original_replace(tree, name, data, *args, **kwargs)
    raise OSError("synthetic-private-lost-response")
  with held_scope(ws, cache, runtime) as args:
    if phase == "dispatched":
      attach(domain, args, run=RUNS[0])
    with monkeypatch.context() as patch:
      patch.setattr(Tree, "replace", replace)
      with pytest.raises(Conflict):
        if phase == "dispatched":
          owners.dispatch_owner(domain, RUNS[0], **args)
        else:
          attach(domain, args, run=RUNS[0])
  assert fired and domain.snapshot()["reservations"][RUNS[0]]["phase"] == phase
  before, owner_before = ledger(domain), owner_path(ws, RUNS[0]).read_bytes()
  with pytest.raises(Conflict):
    domain.cancel_reserved(RUNS[0])
  with pytest.raises(Conflict):
    accept(domain, resources, [])
  with pytest.raises(Conflict):
    reserve(domain, ws, sorted(resources), run=RUNS[0], op=OPS[0])
  assert ledger(domain) == before and owner_path(ws, RUNS[0]).read_bytes() == owner_before
  idle_blocked(SimpleNamespace(domain=domain, cache=cache))
