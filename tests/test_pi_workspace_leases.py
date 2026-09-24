"""临时 Git 形状与本机文件锁；不执行 Git 或第三方宿主。"""

from copy import deepcopy
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from agentcfg.workspace_leases import WorkspaceLeases
from agentcfg.storage import Conflict
from test_pi_activity import make_store, identity


def worktree(tmp_path, name="work"):
  root = tmp_path / name
  (root / ".git").mkdir(parents=True)
  (root / ".git/HEAD").write_text("ref: refs/heads/fixture\n")
  return root


def allocation(planned, name="one"):
  return {"instance_id": "instance-" + name, "lease_id": "execution-" + name,
    "allocation_id": "execution-" + name, "task_id": None, "attempt_id": "attempt-" + name,
    "owner_nonce": "nonce-" + name, "supervisor_activation_id": "supervisor-" + name,
    "grant_generation": 1, "planned_workspaces": [planned], "state": "allocating", "spawn_committed": False}


def test_aliases_and_different_profiles_share_git_inode_and_unknown_is_busy(tmp_path):
  root = worktree(tmp_path)
  alias = tmp_path / "alias"
  alias.symlink_to(root, target_is_directory=True)
  manager = WorkspaceLeases("fixture-boot")
  first, second = manager.identify(root), manager.identify(alias)
  assert first == second
  one, two = allocation(first), allocation(second, "two")
  saved = manager.reserve(first, one)
  assert saved["state"] == "reserved"
  with pytest.raises(Conflict):
    manager.reserve(second, two)
  path = root / ".git/agentcfg/write-lease.json"
  value = json.loads(path.read_bytes())
  value["state"] = "unknown"
  path.write_text(json.dumps(value))
  with pytest.raises(Conflict):
    manager.reserve(second, two)
  assert json.loads(path.read_bytes())["instance_id"] == "instance-one"


def test_two_concurrent_profiles_have_exactly_one_writer(tmp_path):
  root = worktree(tmp_path)
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(root)
  barrier = Barrier(2)
  def compete(name):
    barrier.wait()
    try:
      return manager.reserve(planned, allocation(planned, name))["instance_id"]
    except Conflict:
      return "busy"
  with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(compete, ["one", "two"]))
  assert results.count("busy") == 1
  assert sum(result.startswith("instance-") for result in results) == 1


def test_distinct_worktrees_can_reserve_and_foreign_release_is_rejected(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  first = manager.identify(worktree(tmp_path, "first"))
  second = manager.identify(worktree(tmp_path, "second"))
  one, two = allocation(first), allocation(second, "two")
  assert manager.reserve(first, one)["workspace_key"] != manager.reserve(second, two)["workspace_key"]
  with pytest.raises(Conflict):
    manager.release(first, two, {"verified": True, "kind": "terminated"})


def test_shared_reservation_is_never_written_before_full_durable_intent(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path))
  phases = []
  store, processes = make_store(tmp_path, fault=lambda phase, lease: phases.append((phase, deepcopy(lease))))
  store.workspaces = manager
  original = manager.reserve
  def reserve(plan, lease):
    disk = store.read(lease["lease_id"])
    assert disk["state"] == "allocating" and disk["spawn_committed"] is False
    assert disk["planned_workspaces"] == [planned]
    return original(plan, lease)
  manager.reserve = reserve
  worker = identity(201)
  processes.current[201] = worker
  lease = store.begin(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
    planned_workspaces=[planned], spawn=lambda _: worker)
  assert [phase for phase, _ in phases] == ["intent", "reserved", "journal", "starting", "spawned"]
  assert len(lease["workspace_write_lease_ids"]) == 1
  assert manager.read(planned)["state"] == "active"
  processes.current.pop(201)
  assert store.finish(lease["lease_id"], store.owner)["state"] == "reclaimed"
  assert manager.read(planned)["state"] == "released"


def test_non_git_and_replaced_git_identity_are_rejected(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  with pytest.raises(Conflict):
    manager.identify(tmp_path)
  root = worktree(tmp_path)
  planned = manager.identify(root)
  (root / ".git").rename(root / "old-git")
  (root / ".git").mkdir()
  (root / ".git/HEAD").write_text("ref: refs/heads/fixture\n")
  with pytest.raises(Conflict):
    manager.reserve(planned, allocation(planned))


def test_linked_worktrees_use_dedicated_git_dirs_not_common_dir(tmp_path):
  main = worktree(tmp_path, "main")
  roots = []
  for name in ("first", "second"):
    root = tmp_path / name
    root.mkdir()
    git_dir = main / ".git/worktrees" / name
    git_dir.mkdir(parents=True)
    (root / ".git").write_text("gitdir: " + str(git_dir) + "\n")
    (git_dir / "HEAD").write_text("ref: refs/heads/" + name + "\n")
    (git_dir / "commondir").write_text("../..\n")
    (git_dir / "gitdir").write_text(str(root / ".git") + "\n")
    roots.append(root)
  manager = WorkspaceLeases("fixture-boot")
  first, second = map(manager.identify, roots)
  assert first["git_dir_identity"] != second["git_dir_identity"]
  assert first["workspace_key"] != second["workspace_key"]
  manager.reserve(first, allocation(first))
  manager.reserve(second, allocation(second, "two"))


def test_released_marker_without_durable_evidence_does_not_grant_new_writer(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path))
  manager.reserve(planned, allocation(planned))
  path = Path(planned["git_dir_path"]) / "agentcfg/write-lease.json"
  document = json.loads(path.read_bytes())
  document["state"] = "released"
  path.write_text(json.dumps(document))
  with pytest.raises(Conflict):
    manager.reserve(planned, allocation(planned, "two"))


def test_two_supervisors_with_distinct_state_roots_cannot_spawn_two_writers(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path))
  first, processes = make_store(tmp_path / "first")
  second, _ = make_store(tmp_path / "second", processes=processes, activation="supervisor-two")
  first.owner["instance_id"] = "first-profile"
  second.owner["instance_id"] = "second-profile"
  first.workspaces = second.workspaces = manager
  barrier, spawned = Barrier(2), []
  def compete(pair):
    store, pid = pair
    barrier.wait()
    def spawn(lease):
      worker = identity(pid)
      processes.current[pid] = worker
      spawned.append(pid)
      return worker
    try:
      return store.begin(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt",
        lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
        planned_workspaces=[planned], spawn=spawn)["state"]
    except Conflict:
      return "busy"
  with ThreadPoolExecutor(max_workers=2) as pool:
    results = list(pool.map(compete, [(first, 201), (second, 202)]))
  assert sorted(results) == ["busy", "running"]
  assert len(spawned) == 1
  assert manager.read(planned)["state"] == "active"


def test_released_workspace_can_be_reused_after_reboot_but_active_marker_cannot(tmp_path):
  root = worktree(tmp_path)
  old = WorkspaceLeases("fixture-boot")
  planned = old.identify(root)
  store, processes = make_store(tmp_path)
  store.workspaces = old
  worker = identity(201)
  processes.current[201] = worker
  lease = store.begin(kind="worker", execution_id="one", task_id="task", attempt_id="attempt", lock_identity="a" * 64,
    slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64, planned_workspaces=[planned], spawn=lambda _: worker)
  new = WorkspaceLeases("another-boot")
  next_planned = new.identify(root)
  with pytest.raises(Conflict):
    new.reserve(next_planned, allocation(next_planned, "next"))
  processes.current.pop(201)
  store.finish(lease["lease_id"], store.owner)
  assert new.reserve(next_planned, allocation(next_planned, "next"))["host_boot_id"] == "another-boot"


def test_subdirectories_cannot_create_independent_writer_locks(tmp_path):
  root = worktree(tmp_path)
  (root / "src").mkdir()
  (root / "tests").mkdir()
  manager = WorkspaceLeases("fixture-boot")
  left = manager.identify(root / "src")
  right = manager.identify(root / "tests")
  assert left == right == manager.identify(root)
  manager.reserve(left, allocation(left))
  with pytest.raises(Conflict):
    manager.reserve(right, allocation(right, "two"))


def test_synchronous_project_maintenance_holds_same_admission_lock(tmp_path):
  from agentcfg.workspace_leases import WorkspaceLeases
  root = worktree(tmp_path)
  first = WorkspaceLeases("fixture-boot"); other = WorkspaceLeases("fixture-boot")
  planned = first.identify(root)
  with first.maintenance(root):
    with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
      other.read(planned)
  assert other.read(planned) is None


def test_project_maintenance_rejects_an_existing_writer_without_changing_marker(tmp_path):
  root = worktree(tmp_path); manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(root); saved = manager.reserve(planned, allocation(planned))
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    with manager.maintenance(root): pytest.fail("must not write while another lease exists")
  assert manager.read(planned) == saved
