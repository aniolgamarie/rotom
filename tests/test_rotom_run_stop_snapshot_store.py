"""DSH 人工恢复快照先于停止意图；仅临时文件，不提供批准/停止/恢复能力。"""
from copy import deepcopy
import fcntl
import hashlib
import json
import os

import pytest

from agentcfg import run_owners, run_stop_fence as fence
from agentcfg.storage import Conflict, Tree
from test_rotom_run_records import MANAGER, store


BATCH, PLAN = "a" * 32, "b" * 64


def digest(value): return hashlib.sha256(run_owners._encode(value)).hexdigest()


def marker(case): return case.registry.root.with_name(case.registry.root.name + ".stop-fence.json")


def checkpoint(case):
  return case.registry.root.with_name(case.registry.root.name + ".stop-snapshot-" + BATCH + ".json")


@pytest.fixture
def case(store):
  ids = [store.registry.register_v2(MANAGER, store.metadata) for _ in range(3)]
  store.expected = store.registry.snapshot(); store.selected = sorted(ids[:2]); store.third = ids[2]
  info = store.registry.root.stat()
  store.snapshot = {"schema_version": 1, "kind": "run-stop-snapshot", "binding": deepcopy(store.binding),
    "binding_digest": store.registry.binding_digest, "registry_physical": {"device": info.st_dev, "inode": info.st_ino},
    "batch_id": BATCH, "plan_id": PLAN, "records_digest": digest(store.expected),
    "selected_runs": store.selected[:], "records": {run: deepcopy(store.expected[run]) for run in store.selected},
    "restore_mode": "manual"}
  return store


def install(case, **options):
  return fence.install(case.registry, batch_id=BATCH, plan_id=PLAN, expected_records=case.expected,
    recovery_snapshot=case.snapshot, **options)


def test_snapshot_durable_under_owner_lock_before_fence_and_preserves_unknowns(case, monkeypatch):
  write, sync = Tree.write_new, fence.storage.sync_directory_ancestors
  events = []
  def busy():
    with Tree(case.registry.root) as other:
      with pytest.raises(BlockingIOError): fcntl.flock(other.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  def callback(): busy(); events.append("review")
  def publish(tree, name, raw):
    busy()
    if name == checkpoint(case).name:
      assert events == ["review"]; events.append("snapshot")
    elif name == marker(case).name:
      assert events == ["review", "snapshot", "sync"]
      assert json.loads(checkpoint(case).read_bytes()) == case.snapshot
      events.append("fence")
    return write(tree, name, raw)
  def synced(path):
    busy(); result = sync(path); events.append("sync"); return result
  monkeypatch.setattr(Tree, "write_new", publish)
  monkeypatch.setattr(fence.storage, "sync_directory_ancestors", synced)
  assert install(case, before_publish=callback) is None
  assert events == ["review", "snapshot", "sync", "fence", "sync"]
  saved = fence.read(case.registry)
  assert saved["schema_version"] == 2
  assert saved["snapshot_digest"] == hashlib.sha256(checkpoint(case).read_bytes()).hexdigest()
  value = fence.read_snapshot(case.registry, BATCH)
  assert value == case.snapshot and value["records"][case.selected[0]]["session_cwd"] is None
  assert value["records"][case.selected[0]]["session_observation"] is None
  assert value["records"][case.selected[0]]["host_identity"] is None
  assert case.third not in value["records"] and case.registry.snapshot() == case.expected
  assert checkpoint(case).stat().st_mode & 0o777 == 0o600
  value["records"].clear()
  assert fence.read_snapshot(case.registry, BATCH) == case.snapshot


@pytest.mark.parametrize("damage", ["batch", "plan", "binding", "physical", "digest", "record", "late-owner"])
def test_invalid_or_stale_link_refuses_before_callback_or_any_publication(case, damage):
  if damage == "batch": case.snapshot["batch_id"] = "c" * 32
  elif damage == "plan": case.snapshot["plan_id"] = "c" * 64
  elif damage == "binding": case.snapshot["binding"]["machine"] = "other"
  elif damage == "physical": case.snapshot["registry_physical"]["inode"] += 1
  elif damage == "digest": case.snapshot["records_digest"] = "c" * 64
  elif damage == "record": case.snapshot["records"][case.selected[0]]["start_cwd"]["path"] = "/synthetic/other"
  else: case.registry.register_v2(MANAGER, case.metadata)
  with pytest.raises(Conflict): install(case, before_publish=lambda: pytest.fail("invalid snapshot cannot consume review"))
  assert not checkpoint(case).exists() and not marker(case).exists()


@pytest.mark.parametrize("stage", ["snapshot-before", "snapshot-after", "snapshot-sync", "snapshot-read", "fence-before", "fence-after", "fence-sync", "fence-read"])
@pytest.mark.parametrize("kind", [OSError, KeyboardInterrupt, SystemExit])
def test_partial_publication_preserves_facts_without_retry_or_approval_reuse(case, monkeypatch, stage, kind):
  error = kind("synthetic-private-canary")
  write, read, sync = Tree.write_new, Tree.read, fence.storage.sync_directory_ancestors
  events = []; syncs = []
  def publish(tree, name, raw):
    item = "snapshot" if name == checkpoint(case).name else "fence"
    if stage == item + "-before": raise error
    result = write(tree, name, raw)
    if stage == item + "-after": raise error
    return result
  def synced(path):
    syncs.append(True)
    if stage == ("snapshot-sync" if len(syncs) == 1 else "fence-sync"): raise error
    return sync(path)
  def reading(tree, name, **kwargs):
    if stage == "snapshot-read" and name == checkpoint(case).name and checkpoint(case).exists(): raise error
    if stage == "fence-read" and name == marker(case).name and marker(case).exists(): raise error
    return read(tree, name, **kwargs)
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", publish); patch.setattr(Tree, "read", reading)
    patch.setattr(fence.storage, "sync_directory_ancestors", synced)
    with pytest.raises(Conflict if kind is OSError else kind) as caught:
      install(case, before_publish=lambda: events.append("consumed"))
  assert events == ["consumed"]
  if kind is not OSError: assert caught.value is error
  else: assert "synthetic-private-canary" not in str(caught.value)
  assert checkpoint(case).exists() == (stage != "snapshot-before")
  assert marker(case).exists() == (stage in ("fence-after", "fence-sync", "fence-read"))
  if checkpoint(case).exists():
    before = checkpoint(case).read_bytes()
    assert fence.read_snapshot(case.registry, BATCH) == case.snapshot
    with pytest.raises(Conflict): install(case, before_publish=lambda: pytest.fail("cannot replay after possible publication"))
    assert checkpoint(case).read_bytes() == before
  assert case.registry.snapshot() == case.expected


@pytest.mark.parametrize("damage", ["missing", "contents", "mode", "symlink", "hardlink"])
def test_missing_or_corrupt_linked_snapshot_keeps_registration_and_maintenance_blocked(case, tmp_path, damage):
  install(case); saved_fence = marker(case).read_bytes(); path = checkpoint(case)
  if damage == "missing": path.unlink()
  elif damage == "contents": path.write_bytes(b"{}\n")
  elif damage == "mode": path.chmod(0o644)
  elif damage == "symlink":
    alternate = tmp_path / "saved-snapshot"; path.rename(alternate); path.symlink_to(alternate)
  else: os.link(path, tmp_path / "linked-snapshot")
  with pytest.raises(Conflict): fence.read(case.registry)
  with pytest.raises(Conflict): case.registry.register_v2(MANAGER, case.metadata)
  with pytest.raises(Conflict): case.registry.assert_inactive()
  assert marker(case).read_bytes() == saved_fence


def test_read_keeps_historical_snapshot_after_exit_without_returning_a_permit(case):
  install(case)
  for run in case.expected:
    case.registry.finish_current(run, MANAGER, run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True))
  assert fence.read_snapshot(case.registry, BATCH) == case.snapshot
  assert fence.read(case.registry)["snapshot_digest"]
  with pytest.raises(Conflict): case.registry.assert_inactive()


def test_snapshot_read_does_not_create_absent_registry_or_parent(store):
  assert fence.read_snapshot(store.registry, BATCH) is None
  assert not store.registry.root.exists() and not checkpoint(store).exists()


def test_owner_changes_during_snapshot_sync_leave_orphan_and_no_fence(case, monkeypatch):
  sync = fence.storage.sync_directory_ancestors
  def changed(path):
    result = sync(path)
    selected = case.registry.root / (case.selected[0] + ".json")
    value = json.loads(selected.read_bytes()); run_owners._set_state(value, "unknown")
    selected.write_bytes(run_owners._encode(value))
    return result
  monkeypatch.setattr(fence.storage, "sync_directory_ancestors", changed)
  with pytest.raises(Conflict): install(case)
  assert not marker(case).exists() and checkpoint(case).exists()
  assert fence.read_snapshot(case.registry, BATCH) == case.snapshot


def test_owner_root_replacement_makes_saved_snapshot_untrusted_without_deleting_it(case):
  install(case); before = checkpoint(case).read_bytes()
  case.registry.root.rename(case.registry.root.with_name("saved-owners")); case.registry.root.mkdir(mode=0o700)
  with pytest.raises(Conflict): fence.read_snapshot(case.registry, BATCH)
  with pytest.raises(Conflict): fence.read(case.registry)
  assert checkpoint(case).read_bytes() == before


@pytest.mark.parametrize("stage", [1, 2], ids=["snapshot-sync", "fence-sync"])
@pytest.mark.parametrize("damage", ["snapshot-content", "snapshot-delete", "owner-root", "parent"])
def test_late_snapshot_or_directory_replacement_cannot_return_success(case, monkeypatch, stage, damage):
  # 独立容器防止替换测试误移动隔离 HOME 或外围哨兵。
  container = case.registry.root.parent / "snapshot-scope"; container.mkdir(mode=0o700)
  root = container / "run-owners"; case.registry.root.rename(root)
  case.registry = run_owners.Registry(root, case.binding)
  sync = fence.storage.sync_directory_ancestors; calls = []
  def changed(path):
    result = sync(path); calls.append(True)
    if len(calls) == stage:
      if damage == "snapshot-content": checkpoint(case).write_bytes(b"synthetic-private-canary")
      elif damage == "snapshot-delete": checkpoint(case).unlink()
      elif damage == "owner-root":
        root.rename(root.with_name("saved-owners")); root.mkdir(mode=0o700)
      else:
        container.rename(container.with_name("saved-container")); container.mkdir(mode=0o700)
    return result
  monkeypatch.setattr(fence.storage, "sync_directory_ancestors", changed)
  with pytest.raises(Conflict) as caught: install(case)
  assert len(calls) == stage and "synthetic-private-canary" not in str(caught.value)


def test_callback_cannot_mutate_frozen_snapshot_or_expected_records(case):
  original = deepcopy(case.snapshot)
  def changed():
    case.snapshot["records"].clear(); case.expected.clear()
  install(case, before_publish=changed)
  assert fence.read_snapshot(case.registry, BATCH) == original
  assert fence.read(case.registry)["records_digest"] == original["records_digest"]


@pytest.mark.parametrize("damage", ["missing-digest", "invalid-digest", "different-digest", "wrong-version"])
def test_invalid_v2_marker_never_falls_back_to_unlinked_snapshot(case, damage):
  install(case); path = marker(case); value = json.loads(path.read_bytes())
  if damage == "missing-digest": value.pop("snapshot_digest")
  elif damage == "invalid-digest": value["snapshot_digest"] = True
  elif damage == "different-digest": value["snapshot_digest"] = "0" * 64
  else: value["schema_version"] = 3
  path.write_bytes(run_owners._encode(value))
  with pytest.raises(Conflict): fence.read(case.registry)
  assert fence.read_snapshot(case.registry, BATCH) == case.snapshot
  with pytest.raises(Conflict): case.registry.register_v2(MANAGER, case.metadata)


@pytest.mark.parametrize("form", ["empty", "directory", "symlink"])
def test_any_existing_batch_snapshot_refuses_before_callback_without_reading_body(case, form):
  path = checkpoint(case)
  if form == "directory": path.mkdir(mode=0o700)
  elif form == "symlink": path.symlink_to(case.native / "do-not-read")
  else: path.write_bytes(b""); path.chmod(0o600)
  with pytest.raises(Conflict): install(case, before_publish=lambda: pytest.fail("existing snapshot cannot consume another review"))
  assert not marker(case).exists()
