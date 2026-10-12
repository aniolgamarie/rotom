"""账户协调先于Git局部标记；仅使用临时目录及合成执行意图。"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from agentcfg.activity import digest
from agentcfg.pi_registered_roots import RegisteredRoots
from agentcfg.storage import Conflict, Tree
from agentcfg.workspace_leases import WorkspaceLeases
from test_pi_workspace_leases import allocation, worktree
from test_pi_workspace_overlap import nested_worktree


def setup(tmp_path):
  manager = WorkspaceLeases("fixture-boot")
  planned = manager.identify(worktree(tmp_path))
  lease = allocation(planned)
  lease["allocation_journal_digest"] = "e" * 64
  return manager, planned, lease


def proof(lease):
  value = {"schema_version": 1, "kind": "never-started", "execution_lease_id": lease["lease_id"],
    "process_identities": [], "external_work_ids": [], "recorded_at": "fixture", "verified": True,
    "allocation_journal_digest": lease["allocation_journal_digest"], "grant_generation": lease["grant_generation"]}
  return {**value, "evidence_digest": digest(value)}


def claim_path():
  return RegisteredRoots().anchor / "claims.json"


@pytest.mark.parametrize("fault", ["missing", "unknown", "duplicate", "mode", "digest"])
def test_claim_table_damage_fails_closed(tmp_path, fault):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  path = claim_path()
  value = json.loads(path.read_bytes())
  if fault == "missing": path.unlink()
  if fault == "unknown": value["unknown"] = True
  if fault == "duplicate": value["claims"].append(deepcopy(value["claims"][0]))
  if fault == "mode": path.chmod(0o644)
  if fault == "digest": value["claims"][0]["stable_root_key"] = "f" * 64
  if fault in ("unknown", "duplicate", "digest"): path.write_text(json.dumps(value))
  with pytest.raises(Conflict): manager.read(planned)


@pytest.mark.parametrize("field", ["planned_workspaces", "policy_digest", "lock_identity", "manager_activation_id"])
def test_same_ids_do_not_exempt_changed_allocation_context(tmp_path, field):
  parent, child = nested_worktree(tmp_path, "nested-git")
  manager = WorkspaceLeases("fixture-boot")
  outer, inner = manager.identify(parent), manager.identify(child)
  lease = allocation(outer)
  lease["planned_workspaces"] = [outer, inner]
  manager.reserve(outer, lease)
  changed = deepcopy(lease)
  changed[field] = [inner] if field == "planned_workspaces" else ("f" * 64 if field.endswith("digest") or field.endswith("identity") else "changed")
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"): manager.reserve(inner, changed)


def test_global_commit_without_local_reply_retains_protection_and_can_release(tmp_path, monkeypatch):
  manager, planned, lease = setup(tmp_path)
  original = Tree.write_state
  def fail_local(tree, name, value):
    if name == "write-lease.json": raise OSError("synthetic")
    return original(tree, name, value)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_state", fail_local)
    with pytest.raises(Conflict): manager.reserve(planned, lease)
  assert not (Path(planned["git_dir_path"]) / "agentcfg/write-lease.json").exists()
  with pytest.raises(Conflict): manager.reserve(planned, allocation(planned, "other"))
  assert manager.release(planned, lease, proof(lease), missing_ok=True)
  assert manager.reserve(planned, allocation(planned, "other"))["state"] == "reserved"


def test_local_release_then_global_failure_is_protected_and_retryable(tmp_path, monkeypatch):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  original = Tree.write_state
  def fail_global(tree, name, value):
    if name == "claims.json": raise OSError("synthetic")
    return original(tree, name, value)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_state", fail_global)
    with pytest.raises(Conflict): manager.release(planned, lease, proof(lease))
  assert json.loads((Path(planned["git_dir_path"]) / "agentcfg/write-lease.json").read_bytes())["state"] == "released"
  with pytest.raises(Conflict): manager.reserve(planned, allocation(planned, "other"))
  assert manager.release(planned, lease, proof(lease))
  with pytest.raises(Conflict): manager.reserve(planned, lease)


def test_old_generation_and_foreign_release_do_not_clear_claim(tmp_path):
  manager, planned, lease = setup(tmp_path)
  lease["grant_generation"] = 2
  manager.reserve(planned, lease)
  before = claim_path().read_bytes()
  for changed in (dict(lease, grant_generation=1), dict(lease, owner_nonce="foreign", grant_generation=3)):
    with pytest.raises(Conflict): manager.release(planned, changed, proof(changed), missing_ok=True)
    assert claim_path().read_bytes() == before


def test_old_boot_overlapping_claim_remains_protected(tmp_path):
  parent, child = nested_worktree(tmp_path, "nested-git")
  old = WorkspaceLeases("old-boot")
  planned = old.identify(parent)
  old.reserve(planned, allocation(planned))
  new = WorkspaceLeases("new-boot")
  inner = new.identify(child)
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"): new.reserve(inner, allocation(inner, "next"))


def test_active_unknown_physical_root_blocks_unrelated_writer(tmp_path):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  Path(planned["worktree_path"]).rename(tmp_path / "lost")
  other = manager.identify(worktree(tmp_path, "other"))
  with pytest.raises(Conflict, match="WORKSPACE_UNKNOWN"): manager.reserve(other, allocation(other, "next"))


def test_registry_v2_preserves_roots_and_missing_claims_is_not_repaired(tmp_path, monkeypatch):
  import agentcfg.pi_registered_roots as module
  original = module._has_git_marker
  monkeypatch.setattr(module, "_has_git_marker", lambda directory: original(directory) if directory.is_relative_to(tmp_path) else False)
  registry = RegisteredRoots()
  business = tmp_path / "non-git-business"; business.mkdir(mode=0o700)
  observed = registry.register(business)
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  assert registry.list() == [observed]
  other = tmp_path / "non-git-other"; other.mkdir(mode=0o700)
  registry.register(other)
  manifest = json.loads((registry.anchor / "registry.json").read_bytes())
  assert manifest["schema_version"] == 2 and manifest["claim_protocol"] == 1
  claim_path().unlink()
  with pytest.raises(Conflict): registry.list()
  with pytest.raises(Conflict): manager.reserve(planned, lease)
  assert not claim_path().exists()


@pytest.mark.parametrize("fault", ["after-registry", "after-empty-claims"])
def test_initialization_interruption_can_only_resume_empty_same_coordinator(tmp_path, monkeypatch, fault):
  manager, planned, lease = setup(tmp_path)
  original_new, original_state = Tree.write_new, Tree.write_state
  def interrupted_new(tree, name, value):
    original_new(tree, name, value)
    if name == "registry.json" and fault == "after-registry": raise OSError("synthetic")
  def interrupted_state(tree, name, value):
    if name == "registry.json" and fault == "after-empty-claims": raise OSError("synthetic")
    original_state(tree, name, value)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", interrupted_new)
    patch.setattr(Tree, "write_state", interrupted_state)
    with pytest.raises(Conflict): manager.reserve(planned, lease)
  manifest = json.loads((RegisteredRoots().anchor / "registry.json").read_bytes())
  assert manifest["schema_version"] == 1
  assert manager.reserve(planned, lease)["state"] == "reserved"


@pytest.mark.parametrize("fault", ["journal", "hash", "mode", "link", "unknown"])
def test_global_released_proof_damage_fails_closed(tmp_path, fault):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  evidence = proof(lease)
  manager.release(planned, lease, evidence)
  path = RegisteredRoots().anchor / "claim-evidence" / (evidence["evidence_digest"] + ".json")
  value = json.loads(path.read_bytes())
  if fault == "journal": value["allocation_journal_digest"] = "f" * 64
  if fault == "hash": value["recorded_at"] = "tampered"
  if fault == "mode": path.chmod(0o644)
  if fault == "link": (path.parent / "other.json").symlink_to(path)
  if fault == "unknown": value["secret"] = "synthetic-forbidden"
  if fault in ("journal", "hash", "unknown"): path.write_text(json.dumps(value))
  with pytest.raises(Conflict): manager.reserve(planned, allocation(planned, "next"))


def test_foreign_or_missing_global_cannot_spawn_legacy_local_reservation(tmp_path):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  path = claim_path(); table = json.loads(path.read_bytes()); table["claims"] = []; path.write_text(json.dumps(table))
  with pytest.raises(Conflict): manager.assert_reserved(planned, lease)
  with pytest.raises(Conflict): manager.reserve(planned, lease)


def test_context_digest_and_journal_cannot_be_self_reported(tmp_path):
  from agentcfg.pi_workspace_claims import context
  from test_pi_activity import make_store, identity
  manager, planned, _ = setup(tmp_path)
  store, processes = make_store(tmp_path / "store")
  store.workspaces = manager
  worker = identity(201); processes.current[201] = worker
  lease = store.begin(kind="worker", execution_id="execution", task_id="task", attempt_id="attempt",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest="d" * 64,
    planned_workspaces=[planned], spawn=lambda _: worker)
  assert context(lease)["allocation_journal_digest"] == lease["allocation_journal_digest"]
  changed = deepcopy(lease); changed["execution_id"] = "substituted"
  with pytest.raises(Conflict): context(changed)


@pytest.mark.parametrize("fault", ["context-unknown", "context-hash", "record-plan", "bool", "json-duplicate", "hardlink"])
def test_claim_context_cannot_be_mutated_or_alias_file(tmp_path, fault):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  path = claim_path(); table = json.loads(path.read_bytes()); item = table["claims"][0]
  if fault == "context-unknown": item["allocation_context"]["credentials"] = "forbidden"
  if fault == "context-hash": item["allocation_context"]["attempt_id"] = "substituted"
  if fault == "record-plan": item["record"]["worktree_path"] = str(tmp_path)
  if fault == "bool": item["record"]["grant_generation"] = True
  if fault == "json-duplicate": path.write_text('{"schema_version":1,"schema_version":1}')
  elif fault == "hardlink":
    import os
    os.link(path, tmp_path / "extra-link")
  else: path.write_text(json.dumps(table))
  with pytest.raises(Conflict): manager.read(planned)


def test_released_physical_root_reuses_table_slot_after_git_dir_replacement(tmp_path):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease); manager.release(planned, lease, proof(lease))
  root = Path(planned["worktree_path"])
  (root / ".git").rename(root / "old-git")
  (root / ".git").mkdir(); (root / ".git/HEAD").write_text("ref: refs/heads/fixture\n")
  changed = manager.identify(root)
  manager.reserve(changed, allocation(changed, "next"))
  assert len(json.loads(claim_path().read_bytes())["claims"]) == 1


def test_minimal_null_journal_cannot_accept_nonnull_proof(tmp_path):
  manager, planned, lease = setup(tmp_path)
  lease.pop("allocation_journal_digest")
  manager.reserve(planned, lease)
  external = dict(lease, allocation_journal_digest="f" * 64)
  with pytest.raises(Conflict): manager.release(planned, lease, proof(external))
  assert json.loads(claim_path().read_bytes())["claims"][0]["record"]["state"] == "reserved"


def test_registry_v1_cannot_adopt_nonempty_claims_before_protocol_upgrade(tmp_path):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  registry = RegisteredRoots(); path = registry.anchor / "registry.json"
  manifest = json.loads(path.read_bytes()); manifest.update(schema_version=1); manifest.pop("claim_protocol")
  path.write_text(json.dumps(manifest))
  with pytest.raises(Conflict): manager.read(planned)


def test_termination_proof_must_match_the_frozen_journal(tmp_path):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  value = proof(dict(lease, allocation_journal_digest="f" * 64))
  before = claim_path().read_bytes()
  with pytest.raises(Conflict): manager.release(planned, lease, value)
  assert claim_path().read_bytes() == before


def test_release_revocation_advances_generation_without_reauthorizing_allocation(tmp_path):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  revoked = dict(lease, grant_generation=2)
  evidence = proof(revoked)
  assert manager.release(planned, revoked, evidence)
  global_record = json.loads(claim_path().read_bytes())["claims"][0]["record"]
  local = manager.read(planned)
  assert global_record == local
  assert local["grant_generation"] == 2 and local["termination_evidence_refs"] == [evidence["evidence_digest"]]
  with pytest.raises(Conflict): manager.release(planned, lease, proof(lease))
  with pytest.raises(Conflict): manager.reserve(planned, revoked)


def test_newer_release_repairs_local_released_global_active_cut(tmp_path, monkeypatch):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  original = Tree.write_state
  def fail_global(tree, name, value):
    if name == "claims.json": raise OSError("synthetic")
    return original(tree, name, value)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_state", fail_global)
    with pytest.raises(Conflict): manager.release(planned, lease, proof(lease))
  revoked = dict(lease, grant_generation=2)
  evidence = proof(revoked)
  assert manager.release(planned, revoked, evidence)
  assert manager.read(planned)["grant_generation"] == 2
  assert json.loads(claim_path().read_bytes())["claims"][0]["record"] == manager.read(planned)


def test_new_generation_does_not_bypass_context_binding(tmp_path):
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  changed = dict(lease, grant_generation=2, policy_digest="f" * 64)
  with pytest.raises(Conflict): manager.release(planned, changed, proof(changed))
  assert manager.read(planned)["state"] == "reserved"


def test_unstarted_foreign_allocation_compensation_leaves_existing_writer_unchanged(tmp_path):
  from agentcfg.activity import protected
  from test_pi_activity import make_store
  manager, planned, lease = setup(tmp_path)
  manager.reserve(planned, lease)
  before = claim_path().read_bytes()
  store, _ = make_store(tmp_path / "second-store")
  store.workspaces = manager
  with pytest.raises(Conflict, match="WORKSPACE_BUSY"):
    store.allocate(kind="worker", execution_id="second", task_id="task", attempt_id="attempt",
      lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest=None,
      planned_workspaces=[planned])
  rejected = store.records()[0]
  assert rejected["state"] == "failed" and rejected["spawn_committed"] is False
  assert not protected(rejected)
  assert claim_path().read_bytes() == before
  assert manager.read(planned)["execution_lease_id"] == lease["lease_id"]
