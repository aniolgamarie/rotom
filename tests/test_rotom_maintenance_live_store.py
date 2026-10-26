"""将实际 owner 核验与清单发布置于同一事务；只使用临时文件和合成身份。"""

from contextlib import contextmanager, ExitStack
import base64
import fcntl
import json
import os

import pytest

from agentcfg import deployment, maintenance_store as store, run_owners
from agentcfg.omp_lifecycle import _shared_file
from agentcfg.storage import Conflict, Tree
from test_rotom_maintenance import acceptance as metadata_acceptance, checkpoint
from test_rotom_maintenance_recovery import BATCH, RUNS, group, ledger
from test_rotom_resource_owners import IDENTITY, owner_path


def acceptance(case):
  value = metadata_acceptance(case)
  # 停止接受还需现场部署；只构造最小合成受保护文件，不准备第三方运行包。
  for row in case.rows:
    record = json.loads(owner_path(row.workspace, row.run).read_bytes())
    content = b"synthetic guarded configuration\n"
    with Tree(row.workspace.instance) as tree:
      tree.write_new("managed.txt", content)
    current = {"generation": record["deployed_identity"]["deployment"], "binding": row.workspace.binding,
      "launch": {"lock_identity": IDENTITY, "shared_files": [],
        "adapter_binding": {"identity": {"home": record["native_home_ref"]["path"]}},
        "runtime_guards": {"files": ["managed.txt"], "roots": []}},
      "items": {"managed": {"path": "managed.txt", "selector": "", "codec": "bytes",
        "baseline": deployment.encoded({"bytes": base64.b64encode(content).decode(), "mode": 0o600})}}}
    state = {"version": 1, "current": current, "previous": None,
      "owner": {"binding": row.workspace.binding, "shared_files": []}}
    with Tree(row.workspace.state_root) as tree:
      tree.write_new("deployment.json", deployment.json_bytes(state))
  return value


@contextmanager
def leases_for(case, selected=RUNS[:2]):
  with ExitStack() as stack:
    leases = {}
    for row in case.rows:
      if row.run not in selected:
        continue
      ws = row.workspace
      ws.cache = row.cache
      instance = stack.enter_context(_shared_file(ws.instance, ".agentcfg-omp.lock"))
      home = stack.enter_context(Tree(ws.instance / "user-home"))
      state = stack.enter_context(_shared_file(ws.state_root, "instance.lock"))
      runtime = stack.enter_context(_shared_file(row.cache, "leases/" + IDENTITY + ".lock"))
      leases[row.run] = {"workspace": ws, "instance_fd": instance, "native_home_fd": home.fd,
        "state_fd": state, "runtime_fds": {row.runtime["resource_id"]: runtime}}
    yield leases


def owners_locked(case, *, held):
  for row in case.rows[:2]:
    with Tree(row.workspace.state_root / "run-owners") as tree:
      if held:
        with pytest.raises(BlockingIOError):
          fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
      else:
        fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def test_live_acceptance_holds_owners_through_domain_commit_and_leaves_borrowed_leases_open(group, monkeypatch):
  case = group(); value = acceptance(case)
  before = [owner_path(row.workspace, row.run).read_bytes() for row in case.rows]
  third = case.domain.snapshot()["reservations"][RUNS[2]]
  locked, replace = run_owners.Registry._locked, Tree.replace
  events = []
  @contextmanager
  def observe_owner(registry, *, create=False, nonblocking=False):
    assert not create and nonblocking
    with Tree(case.domain.root) as tree:
      with pytest.raises(BlockingIOError):
        fcntl.flock(tree.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with locked(registry, create=create, nonblocking=nonblocking) as tree:
      events.append("owner-lock")
      yield tree
  def observe_commit(tree, name, data, *args, **kwargs):
    if name == "coordination.json":
      assert checkpoint(case).is_file()
      owners_locked(case, held=True)
      events.append("commit-before")
    result = replace(tree, name, data, *args, **kwargs)
    if name == "coordination.json":
      owners_locked(case, held=True)
      events.append("commit-after")
    return result
  with leases_for(case) as leases, monkeypatch.context() as patch:
    patch.setattr(run_owners.Registry, "_locked", observe_owner)
    patch.setattr(Tree, "replace", observe_commit)
    assert store.accept_stop_snapshot_live(case.domain, value, leases=leases) is None
    owners_locked(case, held=False)
    for lease in leases.values():
      for fd in (lease["instance_fd"], lease["state_fd"], lease["native_home_fd"], *lease["runtime_fds"].values()):
        os.fstat(fd)
  assert events == ["owner-lock", "owner-lock", "commit-before", "commit-after"]
  saved = store.read_stop_snapshot(case.domain, BATCH)
  assert saved["acceptance"] == value and saved["intent"]["phase"] == "active"
  assert case.domain.snapshot()["reservations"][RUNS[2]] == third
  assert [owner_path(row.workspace, row.run).read_bytes() for row in case.rows] == before


def test_actual_owner_drift_with_unchanged_coordination_prevents_any_publication(group):
  case = group(); value = acceptance(case)
  row = case.rows[0]
  record = json.loads(owner_path(row.workspace, row.run).read_bytes())
  record["start_cwd"]["path"] = "/synthetic/changed-after-preview"
  registry = run_owners.Registry(row.workspace.state_root / "run-owners", row.workspace.binding)
  registry._validate_record(row.run + ".json", record)
  with Tree(registry.root) as tree:
    tree.write_state(row.run + ".json", run_owners._encode(record))
  before = ledger(case.domain), owner_path(row.workspace, row.run).read_bytes()
  with leases_for(case) as leases, pytest.raises(Conflict):
    store.accept_stop_snapshot_live(case.domain, value, leases=leases)
  assert before == (ledger(case.domain), owner_path(row.workspace, row.run).read_bytes())
  assert not checkpoint(case).exists()
  owners_locked(case, held=False)


@pytest.mark.parametrize("stage", ["checkpoint-before", "checkpoint-after", "commit-before", "commit-after"])
def test_partial_publication_keeps_evidence_and_releases_owner_locks(group, monkeypatch, stage):
  case = group(); value = acceptance(case)
  write, replace = Tree.write_new, Tree.replace
  def publish(tree, name, data, *args, **kwargs):
    owners_locked(case, held=True)
    if stage == "checkpoint-before":
      raise OSError("synthetic-private-value")
    result = write(tree, name, data, *args, **kwargs)
    if stage == "checkpoint-after":
      raise OSError("synthetic-private-value")
    return result
  def commit(tree, name, data, *args, **kwargs):
    owners_locked(case, held=True)
    if stage == "commit-before":
      raise OSError("synthetic-private-value")
    result = replace(tree, name, data, *args, **kwargs)
    if stage == "commit-after":
      raise OSError("synthetic-private-value")
    return result
  with leases_for(case) as leases, monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", publish)
    patch.setattr(Tree, "replace", commit)
    with pytest.raises(Conflict) as caught:
      store.accept_stop_snapshot_live(case.domain, value, leases=leases)
    assert "synthetic-private-value" not in str(caught.value)
  owners_locked(case, held=False)
  assert checkpoint(case).exists() == (stage != "checkpoint-before")
  assert (BATCH in case.domain.snapshot()["intents"]) == (stage == "commit-after")


@pytest.mark.parametrize("damage", ["missing-lease", "extra-lease", "revision"])
def test_invalid_live_acceptance_cannot_fall_back_to_metadata_only(group, damage):
  case = group(); value = acceptance(case)
  if damage == "revision":
    with case.domain._transaction(write=True):
      pass
  before = ledger(case.domain)
  with leases_for(case) as leases:
    if damage == "missing-lease":
      del leases[RUNS[0]]
    elif damage == "extra-lease":
      leases[RUNS[2]] = leases[RUNS[0]]
    with pytest.raises(Conflict):
      store.accept_stop_snapshot_live(case.domain, value, leases=leases)
  assert ledger(case.domain) == before and not checkpoint(case).exists()
  owners_locked(case, held=False)


@pytest.mark.parametrize("error", [KeyboardInterrupt, SystemExit])
def test_control_exception_during_publication_unwinds_locks_without_cleanup(group, monkeypatch, error):
  case = group(); value = acceptance(case)
  write = Tree.write_new
  def interrupt(tree, name, data, *args, **kwargs):
    result = write(tree, name, data, *args, **kwargs)
    owners_locked(case, held=True)
    raise error()
  with leases_for(case) as leases, monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", interrupt)
    with pytest.raises(error):
      store.accept_stop_snapshot_live(case.domain, value, leases=leases)
  owners_locked(case, held=False)
  assert checkpoint(case).exists() and BATCH not in case.domain.snapshot()["intents"]


def test_live_acceptance_rejects_metadata_snapshot_replay_without_releasing_intent(group):
  case = group(); value = acceptance(case)
  store.accept_stop_snapshot(case.domain, value)
  before = checkpoint(case).read_bytes(), ledger(case.domain)
  with leases_for(case) as leases, pytest.raises(Conflict):
    store.accept_stop_snapshot_live(case.domain, value, leases=leases)
  assert before == (checkpoint(case).read_bytes(), ledger(case.domain))
