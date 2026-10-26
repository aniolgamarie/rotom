"""真实临时物理锁和协调表；假退出观察，不启动宿主或发送信号。"""
from copy import deepcopy
from contextlib import contextmanager, ExitStack
import fcntl
import json

import pytest

from agentcfg import maintenance, maintenance_progress as progress, maintenance_release as release
from agentcfg import maintenance_store as store, resource_owners as owners, run_owners
from agentcfg.storage import Conflict, Tree
from agentcfg.omp_lifecycle import _shared_file
from test_rotom_maintenance_live_store import acceptance, leases_for
from test_rotom_maintenance_recovery import BATCH, RUNS, group, ledger
from test_rotom_resource_coordination import locked
from test_rotom_resource_owners import IDENTITY, MANAGER, owner_path


def build_stopped(group, *, operation="setup"):
  case = group(separate_third=True)
  value = acceptance(case)
  old = value["batch"]["plan"]
  plan = maintenance._plan({**old, "operation": operation}, verify=False)
  value = maintenance.build_stop_acceptance(batch_id=BATCH, plan=plan,
    records=value["records"], expected_revision=value["expected_revision"])
  with leases_for(case) as leases:
    store.accept_stop_snapshot_live(case.domain, value, leases=leases)
    for run in RUNS[:2]:
      observation = run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True)
      owners.finish_owner(case.domain, run, observation=observation,
        **{key: child for key, child in leases[run].items() if key != "state_fd"})
  for revision, run in enumerate(RUNS[:2]):
    progress.record_exit(case.domain, BATCH, expected_revision=revision,
      proof=run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True))
  return case, {row.run: row.workspace for row in case.rows[:2]}


@pytest.fixture
def stopped(group):
  return build_stopped(group)


def test_original_ex_and_released_owners_confirm_only_setup_stop_facts(stopped):
  case, workspaces = stopped
  before = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  reservations = deepcopy(case.domain.snapshot()["reservations"])
  batch = release.confirm_setup_release(case.domain, BATCH, expected_revision=2, workspaces=workspaces)
  assert batch["revision"] == 3 and batch["phase"] == "stopped_confirmed"
  for item in batch["items"]:
    assert item["stop_phase"] == "stopped_confirmed"
    assert item["facts"] == {"stop_requested": False, "exit_confirmed": True,
      "resources_released": True, "session_sealed": False}
  assert batch["maintenance_dispatch"]["state"] == "not_dispatched"
  assert case.domain.snapshot()["intents"][BATCH]["phase"] == "active"
  assert case.domain.snapshot()["reservations"] == reservations
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == before
  with pytest.raises(Conflict):
    release.confirm_setup_release(case.domain, BATCH, expected_revision=3, workspaces=workspaces)


def test_runtime_shared_lease_blocks_despite_complete_exit_and_released_owner(stopped):
  case, workspaces = stopped
  before = ledger(case.domain)
  with locked(case.cache, IDENTITY):
    with pytest.raises(Conflict):
      release.confirm_setup_release(case.domain, BATCH, expected_revision=2, workspaces=workspaces)
  assert ledger(case.domain) == before


def confirm(case, workspaces, revision=2):
  return release.confirm_setup_release(case.domain, BATCH,
    expected_revision=revision, workspaces=workspaces)


def assert_rejected_unchanged(case, workspaces, revision=2):
  before = ledger(case.domain)
  with pytest.raises(Conflict) as caught:
    confirm(case, workspaces, revision)
  assert "private-canary" not in str(caught.value)
  assert ledger(case.domain) == before


@pytest.mark.parametrize("kind", ["instance", "state"])
def test_original_scope_shared_lock_prevents_release(stopped, kind):
  case, workspaces = stopped
  ws = workspaces[RUNS[0]]
  root, name = ((ws.instance, ".agentcfg-omp.lock") if kind == "instance"
    else (ws.state_root, "instance.lock"))
  with _shared_file(root, name):
    assert_rejected_unchanged(case, workspaces)
  assert confirm(case, workspaces)["phase"] == "stopped_confirmed"


@pytest.mark.parametrize("revision", [True, -1, 1, 3])
def test_bad_or_stale_batch_revision_preserves_facts(stopped, revision):
  case, workspaces = stopped
  assert_rejected_unchanged(case, workspaces, revision)


@pytest.mark.parametrize("change", ["missing", "extra", "other-instance"])
def test_workspace_selection_is_exact(stopped, change):
  case, workspaces = stopped
  chosen = dict(workspaces)
  if change == "missing":
    del chosen[RUNS[0]]
  elif change == "extra":
    chosen[RUNS[2]] = case.rows[2].workspace
  else:
    chosen[RUNS[0]] = case.rows[2].workspace
  assert_rejected_unchanged(case, chosen)


@pytest.mark.parametrize("change", ["unknown", "release_pending"])
def test_unconfirmed_metadata_blocks_even_when_all_ex_are_available(stopped, change):
  case, workspaces = stopped
  with case.domain._transaction(write=True) as state:
    state["reservations"][RUNS[0]]["phase"] = change
  assert_rejected_unchanged(case, workspaces)


@pytest.mark.parametrize("change", ["drift", "unknown", "orphan", "deployment", "birth", "session"])
def test_actual_owner_change_cannot_be_hidden_by_original_receipt(stopped, change):
  case, workspaces = stopped
  ws = workspaces[RUNS[0]]
  path = owner_path(ws, RUNS[0])
  record = json.loads(path.read_bytes())
  name = RUNS[0] + ".json"
  if change == "drift":
    record["start_cwd"]["path"] = "/synthetic/private-canary"
  elif change == "unknown":
    run_owners._set_state(record, "unknown")
  elif change == "deployment":
    record["deployed_identity"]["deployment"] = "e" * 64
  elif change == "birth":
    record["manager_identity"]["birth_id"] = "synthetic-changed-birth"
    record["process_observation"]["manager_identity"] = deepcopy(record["manager_identity"])
    record["host_identity"]["manager_identity"] = deepcopy(record["manager_identity"])
    record["process_observation"]["host_identity"] = deepcopy(record["host_identity"])
  elif change == "session":
    record["session_cwd"] = {"path": "/synthetic/private-canary", "source": "historical",
      "confirmation": "historical", "observed_at_ns": 1}
  else:
    record["run_id"] = "a" * 32
    name = record["run_id"] + ".json"
  run_owners.Registry(ws.state_root / "run-owners", ws.binding)._validate_record(name, record)
  with Tree(ws.state_root / "run-owners") as tree:
    tree.write_state(name, run_owners._encode(record))
  assert_rejected_unchanged(case, workspaces)


@pytest.mark.parametrize("kind", ["instance", "runtime"])
def test_same_mode_new_lease_inode_is_not_original_resource(stopped, kind):
  case, workspaces = stopped
  ws = workspaces[RUNS[0]]
  path = {"instance": ws.instance / ".agentcfg-omp.lock",
    "runtime": case.cache / "leases" / (IDENTITY + ".lock")}[kind]
  old = path.with_name(path.name + ".original")
  path.rename(old)
  path.write_bytes(old.read_bytes())
  path.chmod(0o600)
  assert_rejected_unchanged(case, workspaces)


@pytest.mark.parametrize("change", ["guarded", "generation", "pending"])
def test_deployment_change_blocks_resource_confirmation(stopped, change):
  case, workspaces = stopped
  ws = workspaces[RUNS[0]]
  if change == "guarded":
    (ws.instance / "managed.txt").write_bytes(b"private-canary")
  elif change == "pending":
    (ws.state_root / "pending.json").write_bytes(b"")
    (ws.state_root / "pending.json").chmod(0o600)
  else:
    path = ws.state_root / "deployment.json"
    current = json.loads(path.read_bytes())
    current["current"]["generation"] = "f" * 64
    path.write_bytes(run_owners._encode(current))
  assert_rejected_unchanged(case, workspaces)


@pytest.mark.parametrize("kind", ["owner", "domain"])
def test_metadata_lock_contention_is_nonblocking_and_keeps_batch(stopped, kind):
  case, workspaces = stopped
  root = (workspaces[RUNS[0]].state_root / "run-owners"
    if kind == "owner" else case.domain.root)
  before = ledger(case.domain)
  with Tree(root) as tree:
    fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(Conflict):
      confirm(case, workspaces)
  assert ledger(case.domain) == before
  assert confirm(case, workspaces)["phase"] == "stopped_confirmed"


def assert_locks(case, workspaces, *, held):
  with ExitStack() as stack:
    paths = [(ws.instance, ".agentcfg-omp.lock") for ws in workspaces.values()]
    paths += [(ws.state_root, "instance.lock") for ws in workspaces.values()]
    paths += [(case.cache, "leases/" + IDENTITY + ".lock")]
    for root, name in paths:
      tree = stack.enter_context(Tree(root))
      stream, _ = stack.enter_context(tree.open_read(name))
      if held:
        with pytest.raises(BlockingIOError):
          fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
      else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    for ws in workspaces.values():
      tree = stack.enter_context(Tree(ws.state_root / "run-owners"))
      if held:
        with pytest.raises(BlockingIOError):
          fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      else:
        fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize("fault", [None, "before", "after"])
def test_commit_holds_every_ex_and_owner_and_never_retries(stopped, monkeypatch, fault):
  case, workspaces = stopped
  before = ledger(case.domain)
  owner_bytes = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  replace = Tree.replace
  calls = []
  def commit(tree, name, data, *args, **kwargs):
    if name != "coordination.json":
      return replace(tree, name, data, *args, **kwargs)
    calls.append(name)
    assert_locks(case, workspaces, held=True)
    if fault == "before":
      raise OSError("private-canary")
    result = replace(tree, name, data, *args, **kwargs)
    assert_locks(case, workspaces, held=True)
    if fault == "after":
      raise OSError("private-canary")
    return result
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "replace", commit)
    if fault:
      with pytest.raises(Conflict) as caught:
        confirm(case, workspaces)
      assert "private-canary" not in str(caught.value)
    else:
      assert confirm(case, workspaces)["phase"] == "stopped_confirmed"
  assert calls == ["coordination.json"]
  assert_locks(case, workspaces, held=False)
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == owner_bytes
  saved = progress.read_batch(case.domain, BATCH)
  assert saved["phase"] == ("accepted" if fault == "before" else "stopped_confirmed")
  assert (ledger(case.domain) == before) is (fault == "before")
  assert BATCH in case.domain.snapshot()["intents"]


def test_state_lock_replaced_after_acquisition_is_rejected(stopped, monkeypatch):
  case, workspaces = stopped
  original = run_owners.Registry._locked
  replaced = []
  @contextmanager
  def race(registry, **kwargs):
    with original(registry, **kwargs) as tree:
      if not replaced:
        path = workspaces[RUNS[0]].state_root / "instance.lock"
        path.rename(path.with_name("instance.lock.original"))
        path.write_bytes(b"")
        path.chmod(0o600)
        replaced.append(True)
      yield tree
  with monkeypatch.context() as patch:
    patch.setattr(run_owners.Registry, "_locked", race)
    assert_rejected_unchanged(case, workspaces)
  assert replaced == [True]


def test_extra_shared_runtime_reference_blocks_release(stopped):
  case, workspaces = stopped
  with case.domain._transaction(write=True) as state:
    third = state["reservations"][RUNS[2]]
    third["resources"] = sorted(set(third["resources"]) | {case.runtime["resource_id"]})
  third_before = deepcopy(case.domain.snapshot()["reservations"][RUNS[2]])
  assert_rejected_unchanged(case, workspaces)
  assert case.domain.snapshot()["reservations"][RUNS[2]] == third_before


def test_stop_only_batch_is_not_setup_release_authority(group):
  case, workspaces = build_stopped(group, operation="stop_only")
  assert_rejected_unchanged(case, workspaces)


def test_missing_exit_fact_cannot_be_replaced_by_idle_owner_and_ex(stopped):
  case, workspaces = stopped
  with case.domain._transaction(write=True) as state:
    state["intents"][BATCH]["progress"]["items"][0]["facts"]["exit_confirmed"] = False
  assert_rejected_unchanged(case, workspaces)


def test_replaced_home_is_not_original_enrolled_scope(stopped):
  case, workspaces = stopped
  path = workspaces[RUNS[0]].instance / "user-home"
  original = path.with_name("user-home.original")
  path.rename(original)
  path.mkdir(mode=0o700)
  anchor = path / ".rotom-resource.json"
  anchor.write_bytes((original / ".rotom-resource.json").read_bytes())
  anchor.chmod(0o600)
  assert_rejected_unchanged(case, workspaces)
