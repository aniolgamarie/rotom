"""登记根的共享 Writer 契约；纯临时文件测试，不代表非 Git OS 证据。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from agentcfg.pi_registered_roots import RegisteredRoots
from agentcfg.storage import Conflict
from agentcfg.workspace_leases import WorkspaceLeases
from test_pi_workspace_claims import proof
from test_pi_workspace_leases import allocation, worktree


@pytest.fixture(autouse=True)
def synthetic_ancestor_boundary(tmp_path, monkeypatch):
  # 当前机器 /tmp/.git 属于外部环境；仅本单元套件模拟边界，真实 O 另验。
  import agentcfg.pi_registered_roots as module
  original = module._has_git_marker
  monkeypatch.setattr(module, "_has_git_marker", lambda path: original(path) if path.is_relative_to(tmp_path) else False)


def registered(tmp_path, name="business"):
  root = tmp_path / name
  root.mkdir(mode=0o700)
  RegisteredRoots().register(root)
  return root


def lease_for(planned, name="one"):
  lease = allocation(planned, name)
  lease["allocation_journal_digest"] = "e" * 64
  return lease


def test_registered_root_alias_and_subdirectory_share_one_writer(tmp_path):
  root = registered(tmp_path)
  child = root / "subdirectory"; child.mkdir()
  alias = tmp_path / "alias"; alias.symlink_to(root, target_is_directory=True)
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(root)
  assert planned == manager.identify(child) == manager.identify(alias)
  assert planned["worktree_path"] == str(root)
  lease = lease_for(planned)
  assert manager.reserve(planned, lease)["state"] == "reserved"
  with pytest.raises(Conflict): manager.reserve(planned, lease_for(planned, "two"))
  assert not (root / ".git").exists()
  assert list(root.iterdir()) == [child]


def test_unregistered_non_git_directory_never_gets_a_writer(tmp_path):
  root = tmp_path / "unregistered"; root.mkdir()
  manager = WorkspaceLeases("fixture-boot")
  with pytest.raises(Conflict): manager.identify(root)
  assert list(root.iterdir()) == []


def test_non_git_diagnostics_do_not_create_or_start_a_reservation(tmp_path):
  root = registered(tmp_path)
  registry = RegisteredRoots(); before = (registry.anchor / "registry.json").read_bytes()
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(root)
  assert manager.read(planned) is None
  assert (registry.anchor / "registry.json").read_bytes() == before
  assert sorted(path.name for path in registry.anchor.iterdir()) == ["registry.json"]
  assert list(root.iterdir()) == []


@pytest.mark.parametrize("child_first", [False, True])
def test_registered_parent_and_child_cannot_admit_two_writers(tmp_path, child_first):
  root = registered(tmp_path)
  child = root / "nested"; child.mkdir()
  RegisteredRoots().register(child)
  manager = WorkspaceLeases("fixture-boot")
  parent_plan, child_plan = manager.identify(root), manager.identify(child)
  assert parent_plan != child_plan
  one, two = (child_plan, parent_plan) if child_first else (parent_plan, child_plan)
  manager.reserve(one, lease_for(one))
  with pytest.raises(Conflict): manager.reserve(two, lease_for(two, "two"))


def test_one_allocation_can_cover_nested_registered_roots(tmp_path):
  root = registered(tmp_path)
  child = root / "nested"; child.mkdir()
  RegisteredRoots().register(child)
  manager = WorkspaceLeases("fixture-boot")
  parent_plan, child_plan = manager.identify(root), manager.identify(child)
  lease = lease_for(parent_plan); lease["planned_workspaces"] = [parent_plan, child_plan]
  manager.reserve(parent_plan, lease); manager.reserve(child_plan, lease)
  assert manager.assert_reserved(parent_plan, lease)["execution_lease_id"] == lease["lease_id"]
  assert manager.assert_reserved(child_plan, lease)["execution_lease_id"] == lease["lease_id"]


@pytest.mark.parametrize("git_first", [False, True])
def test_git_child_and_registered_parent_share_physical_claims(tmp_path, git_first):
  root = registered(tmp_path)
  git_child = worktree(root, "git-child")
  manager = WorkspaceLeases("fixture-boot")
  nongit_plan, git_plan = manager.identify(root), manager.identify(git_child)
  one, two = (git_plan, nongit_plan) if git_first else (nongit_plan, git_plan)
  manager.reserve(one, lease_for(one))
  with pytest.raises(Conflict): manager.reserve(two, lease_for(two, "two"))


def test_unrelated_registered_roots_can_reserve_independently(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  first, second = [manager.identify(registered(tmp_path, name)) for name in ("one", "two")]
  one, two = lease_for(first), lease_for(second, "two")
  manager.reserve(first, one); manager.reserve(second, two)
  assert manager.read(first)["execution_lease_id"] != manager.read(second)["execution_lease_id"]


def test_root_replacement_or_new_git_marker_requires_explicit_resolution(tmp_path):
  root = registered(tmp_path)
  manager = WorkspaceLeases("fixture-boot"); planned = manager.identify(root)
  root.rename(tmp_path / "old-business"); root.mkdir()
  with pytest.raises(Conflict): manager.identify(root)
  with pytest.raises(Conflict): manager.reserve(planned, lease_for(planned))
  other = registered(tmp_path, "other")
  (other / ".git").mkdir(); (other / ".git/HEAD").write_text("ref: refs/heads/fixture\n")
  with pytest.raises(Conflict): manager.identify(other)


def test_non_git_release_proof_retains_revocation_and_prevents_replay(tmp_path):
  root = registered(tmp_path); manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(root); lease = lease_for(planned)
  manager.reserve(planned, lease)
  revoked = dict(lease, grant_generation=2)
  manager.release(planned, revoked, proof(revoked))
  assert manager.read(planned)["state"] == "released"
  assert manager.read(planned)["grant_generation"] == 2
  with pytest.raises(Conflict): manager.release(planned, lease, proof(lease))
  with pytest.raises(Conflict): manager.reserve(planned, revoked)
  assert manager.reserve(planned, lease_for(planned, "next"))["state"] == "reserved"
  assert not (root / ".git").exists()


def test_registered_identity_must_not_be_supplied_by_the_model(tmp_path):
  root = registered(tmp_path); manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(root)
  forged = deepcopy(planned); forged["canonical_worktree_identity"]["inode"] += 1
  with pytest.raises(Conflict): manager.reserve(forged, lease_for(forged))
  assert not (RegisteredRoots().anchor / "claims.json").exists() or json.loads((RegisteredRoots().anchor / "claims.json").read_bytes())["claims"] == []


def test_non_git_project_guard_keeps_ownership_journal_in_control_directory(tmp_path, monkeypatch):
  from contextlib import nullcontext
  import agentcfg.pi_lifecycle as lifecycle
  from agentcfg.pi import PiAdapter
  from agentcfg.project import apply_generated
  from test_project import generated
  root = registered(tmp_path); stage = generated(tmp_path)
  adapter = PiAdapter(Path(__file__).resolve().parents[1])
  monkeypatch.setattr(lifecycle, "guard", lambda _: nullcontext())
  with adapter.project_write_guard(None, root) as metadata:
    assert metadata.is_relative_to(RegisteredRoots().anchor / "project-metadata")
    assert apply_generated(root, stage, metadata_root=metadata)["changed"] == 2
  with adapter.project_write_guard(None, root) as metadata:
    assert apply_generated(root, stage, metadata_root=metadata)["changed"] == 0
  assert not (root / ".agentcfg-openspec.json").exists() and not (root / ".git").exists()
  assert RegisteredRoots().inspect(root)["status"] == "current"


def convert_fixture_project(root, tmp_path):
  (root / ".git").rename(tmp_path / "unused-fixture-git")
  RegisteredRoots().register(root)


def test_ordinary_non_git_file_write_uses_the_shared_execution_lifecycle(tmp_path):
  from agentcfg.pi_supervisor import Principal
  from test_pi_operations import setup
  from test_pi_activity import identity
  operations, host, cwd, principal = setup(tmp_path)
  root = Path(cwd); convert_fixture_project(root, tmp_path)
  ticket = operations.prepare(principal, {"operation_id": "non-git-write", "role_id": "main", "cwd": cwd,
    "tool_name": "write", "input": {"path": "new.txt", "content": "synthetic content"}})
  lease = host.store.read(ticket["lease_id"])
  planned = lease["planned_workspaces"][0]
  assert planned["workspace_kind"] == "registered-root"
  operations.stage_write(principal, {"operation_id": ticket["operation_id"], "content": "synthetic content", "expected_digest": None})
  host.store.processes.current[203] = identity(203)
  host.store.start(lease["lease_id"], host.store.owner, spawn=lambda _: identity(203))
  worker = Principal("worker", lease["lease_id"], lease["grant_generation"])
  assert operations.perform(worker, {"operation_id": ticket["operation_id"]})["changed"]
  assert (root / "new.txt").read_text() == "synthetic content"
  host.store.processes.current.pop(203)
  host.store.finish(lease["lease_id"], host.store.owner)
  assert host.store.workspaces.read(planned)["state"] == "released"
  assert not (root / ".git").exists()


def test_non_git_writable_command_and_file_write_compete_for_same_lease(tmp_path):
  from agentcfg.pi_operations import OrdinaryOperations
  from test_pi_commands import fixture
  commands, host, args, principal = fixture(tmp_path, writable=True)
  root = Path(args["cwd"]); convert_fixture_project(root, tmp_path)
  ticket = commands.prepare(principal, args)
  planned = host.store.read(ticket["lease_id"])["planned_workspaces"][0]
  assert planned["git_dir_identity"] is None
  assert host.store.workspaces.read(planned)["state"] == "reserved"
  with pytest.raises(Conflict):
    OrdinaryOperations(host).prepare(principal, {**args, "operation_id": "competing", "tool_name": "write",
      "input": {"path": "new.txt", "content": "forbidden while command owns Writer"}})
  assert not (root / "new.txt").exists()


def test_file_checkpoints_capture_and_restore_registered_non_git_roots(tmp_path):
  from test_pi_checkpoints import fixture
  service, _, root, manager, base, _, _, perform = fixture(tmp_path)
  convert_fixture_project(root, tmp_path)
  checkpoint = perform("capture")["checkpoint_id"]
  (root / "src/a.py").write_text("changed")
  preview = service.preview(manager, {**base, "checkpoint_id": checkpoint})
  assert perform("restore", **{key: preview[key] for key in ("checkpoint_id", "before_digest", "scope_digest")})["status"] == "completed"
  assert (root / "src/a.py").read_text() == "original"
  saved = json.loads((service.root / "objects" / (checkpoint + ".json")).read_bytes())
  assert saved["scope"]["registered_root_id"] == RegisteredRoots().inspect(root)["record"]["root_id"]
  assert not (root / ".git").exists()


def test_git_only_identity_and_native_mapping_reject_registered_non_git_explicitly(tmp_path):
  from agentcfg.pi_native_roots import project_anchor
  root = registered(tmp_path)
  with pytest.raises(Conflict, match="WORKSPACE_GIT_REQUIRED"): WorkspaceLeases("fixture-boot").identify_git(root)
  with pytest.raises(Conflict, match="WORKSPACE_GIT_REQUIRED"): project_anchor(root)


@pytest.mark.parametrize("fault", ["root-id", "kind", "git-path", "git-identity", "extra"])
def test_non_git_claim_identity_cannot_be_partially_reinterpreted(tmp_path, fault):
  root = registered(tmp_path); manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(root); lease = lease_for(planned)
  manager.reserve(planned, lease)
  path = RegisteredRoots().anchor / "claims.json"
  table = json.loads(path.read_bytes()); record = table["claims"][0]["record"]
  if fault == "root-id": record.pop("registered_root_id")
  if fault == "kind": record.pop("workspace_kind")
  if fault == "git-path": record["git_dir_path"] = str(root / ".git")
  if fault == "git-identity": record["git_dir_identity"] = dict(record["canonical_worktree_identity"])
  if fault == "extra": record["untrusted"] = True
  path.write_text(json.dumps(table))
  with pytest.raises(Conflict): manager.read(planned)


def test_non_git_global_commit_without_local_marker_is_protected_and_recoverable(tmp_path, monkeypatch):
  from agentcfg.storage import Tree
  root = registered(tmp_path); manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(root); lease = lease_for(planned)
  original = Tree.write_state
  def fail_local(tree, name, value):
    if name == "write-lease.json": raise OSError("synthetic")
    return original(tree, name, value)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_state", fail_local)
    with pytest.raises(Conflict): manager.reserve(planned, lease)
  with pytest.raises(Conflict): manager.reserve(planned, lease_for(planned, "two"))
  assert manager.release(planned, lease, proof(lease), missing_ok=True)
  assert manager.reserve(planned, lease_for(planned, "two"))["state"] == "reserved"
