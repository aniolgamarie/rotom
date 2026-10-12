"""读取内容memo不替代磁盘、schema、所有权或进程状态核验。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil

import pytest

from agentcfg import activity, pi_catalog
from agentcfg.deployment import json_bytes
from agentcfg.storage import Conflict, Tree
from test_pi_activity import begin, identity, make_store


@pytest.fixture
def saved(tmp_path):
  store, processes = make_store(tmp_path)
  worker = identity(201); processes.current[201] = worker
  lease = begin(store, lambda _: worker)
  processes.current.pop(201)
  lease = store.finish(lease["lease_id"], store.owner)
  path = store.root / store._path(lease["lease_id"])
  return store, lease, path


def test_identical_fresh_reads_skip_repeated_schema_and_allocation_work(saved, monkeypatch):
  store, lease, path = saved
  counts = {"schema": 0, "allocation": 0, "read": 0, "decode": 0}
  schema = pi_catalog.Draft202012Validator.is_valid
  allocation = activity.allocation_digest
  read = Tree.read
  decode = json.loads
  raw = path.read_bytes()
  def checked_schema(validator, value):
    if "lease_id" in validator.schema.get("properties", {}): counts["schema"] += 1
    return schema(validator, value)
  def checked_allocation(value):
    counts["allocation"] += 1
    return allocation(value)
  def checked_read(tree, name, **kwargs):
    if str(name).startswith("activity/leases/"): counts["read"] += 1
    return read(tree, name, **kwargs)
  def checked_decode(data, *args, **kwargs):
    if data == raw: counts["decode"] += 1
    return decode(data, *args, **kwargs)
  monkeypatch.setattr(pi_catalog.Draft202012Validator, "is_valid", checked_schema)
  monkeypatch.setattr(activity, "allocation_digest", checked_allocation)
  monkeypatch.setattr(Tree, "read", checked_read)
  monkeypatch.setattr(json, "loads", checked_decode)
  for _ in range(8): assert store.records()[0] == lease
  assert counts["read"] == 8
  assert counts["allocation"] == 1
  assert counts["decode"] == 1
  assert counts["schema"] <= 2


def test_raw_drift_and_unknown_fields_are_revalidated(saved):
  store, lease, path = saved; store.read(lease["lease_id"])
  changed = deepcopy(lease); changed["grant_generation"] += 1
  path.write_bytes(json_bytes(changed))
  with pytest.raises(Conflict): store.read(lease["lease_id"])
  changed = deepcopy(lease); changed["unknown_cache_field"] = True
  path.write_bytes(json_bytes(changed))
  with pytest.raises(Conflict): store.read(lease["lease_id"])


@pytest.mark.parametrize("action", ["rule", "delete"])
def test_schema_rules_and_deletion_never_reuse_old_proof(saved, tmp_path, monkeypatch, action):
  store, lease, _ = saved
  schemas = tmp_path / "schemas"; shutil.copytree(pi_catalog.SCHEMAS, schemas)
  monkeypatch.setattr(pi_catalog, "SCHEMAS", schemas)
  assert store.read(lease["lease_id"]) == lease
  path = schemas / "execution-lease.schema.json"
  if action == "delete": path.unlink()
  else:
    document = json.loads(path.read_text()); document["properties"]["grant_generation"] = {"const": 999}
    path.write_text(json.dumps(document))
  with pytest.raises(Conflict): store.read(lease["lease_id"])


def test_owner_changes_are_not_cached(saved):
  store, lease, _ = saved; store.read(lease["lease_id"])
  store.owner["instance_id"] = "other-instance"
  with pytest.raises(Conflict): store.read(lease["lease_id"])


@pytest.mark.parametrize("action", ["chmod", "hardlink", "symlink", "delete"])
def test_cached_bytes_do_not_replace_tree_safety_checks(saved, action):
  store, lease, path = saved; store.read(lease["lease_id"])
  if action == "chmod": path.chmod(0o644)
  elif action == "hardlink": os.link(path, path.with_suffix(".alias"))
  elif action == "symlink":
    target = path.with_suffix(".target"); path.rename(target); path.symlink_to(target)
  else: path.unlink()
  with pytest.raises(Conflict): store.read(lease["lease_id"])


def test_path_identity_check_is_kept_even_for_identical_bytes(saved):
  store, lease, path = saved; store.read(lease["lease_id"])
  alias = path.with_name("different-lease.json"); alias.write_bytes(path.read_bytes()); alias.chmod(0o600)
  with pytest.raises(Conflict, match="路径身份"): store.read("different-lease")


def test_returned_objects_are_independent_of_memo(saved):
  store, lease, _ = saved
  for _ in range(3):
    value = store.read(lease["lease_id"]); value["state"] = "running"; value["termination_evidence"]["verified"] = False
    assert store.read(lease["lease_id"]) == lease


def test_concurrent_reads_keep_fresh_values_and_independent_objects(saved):
  store, lease, _ = saved
  with ThreadPoolExecutor(max_workers=8) as executor:
    values = list(executor.map(lambda _: store.read(lease["lease_id"]), range(24)))
  assert values == [lease] * 24
  values[0]["active_external_work_ids"].append("caller-change")
  assert all(value == lease for value in values[1:])


def test_schema_aba_does_not_cache_validation_under_unproved_token(saved, tmp_path, monkeypatch):
  store, lease, _ = saved
  schemas = tmp_path / "schemas"; shutil.copytree(pi_catalog.SCHEMAS, schemas)
  monkeypatch.setattr(pi_catalog, "SCHEMAS", schemas)
  path = schemas / "execution-lease.schema.json"; accepted = path.read_text()
  document = json.loads(accepted); document["properties"]["grant_generation"] = {"const": 999}
  rejected = json.dumps(document); path.write_text(rejected)
  validate = store._validate
  def swapped(value):
    path.write_text(accepted)
    validate(value)
    path.write_text(rejected)
  monkeypatch.setattr(store, "_validate", swapped)
  assert store.read(lease["lease_id"]) == lease
  monkeypatch.setattr(store, "_validate", validate)
  with pytest.raises(Conflict): store.read(lease["lease_id"])


def test_validator_token_uses_identity_without_eq_or_hash(saved, monkeypatch):
  store, lease, _ = saved
  original = pi_catalog._validator
  class Token:
    def is_valid(self, value): return original("execution-lease").is_valid(value)
    def __eq__(self, other): raise AssertionError("validator equality invoked")
    def __hash__(self): raise AssertionError("validator hashing invoked")
  token = Token()
  monkeypatch.setattr(pi_catalog, "_validator", lambda kind: token if kind == "execution-lease" else original(kind))
  assert store.read(lease["lease_id"]) == lease
  assert store.read(lease["lease_id"]) == lease


def test_entry_eviction_and_byte_capacity_do_not_reject_valid_reads(saved, monkeypatch):
  store, lease, path = saved
  second = store.allocate(kind="worker", execution_id="execution-two", task_id="task-two", attempt_id="attempt-two",
    lock_identity="a" * 64, slice_identity="b" * 64, policy_digest="c" * 64, candidate_digest=None, planned_workspaces=[])
  monkeypatch.setattr(activity, "READ_VALIDATION_CACHE_MAX_ENTRIES", 1)
  assert store.read(lease["lease_id"]) == lease
  assert store.read(second["lease_id"]) == second
  assert store.read(lease["lease_id"]) == lease
  assert len(store._read_cache) == 1
  monkeypatch.setattr(activity, "READ_VALIDATION_CACHE_MAX_BYTES", len(path.read_bytes()) - 1)
  uncached, _ = make_store(store.root.parent)
  assert uncached.read(lease["lease_id"]) == lease
  assert not uncached._read_cache
  assert uncached._read_cache_bytes == 0


def test_schema_and_tree_callbacks_run_outside_memo_lock(saved, monkeypatch):
  import threading
  store, lease, _ = saved
  class AuditLock:
    def __init__(self): self.lock = threading.Lock(); self.owner = None
    def __enter__(self): self.lock.acquire(); self.owner = threading.get_ident()
    def __exit__(self, *exc): self.owner = None; self.lock.release()
  audit = AuditLock(); store._read_cache_lock = audit
  schema = pi_catalog._validator; read = Tree.read; validate = store._validate
  def checked_schema(kind):
    assert audit.owner != threading.get_ident()
    return schema(kind)
  def checked_read(tree, name, **kwargs):
    assert audit.owner != threading.get_ident()
    return read(tree, name, **kwargs)
  def checked_validate(value):
    assert audit.owner != threading.get_ident()
    return validate(value)
  monkeypatch.setattr(pi_catalog, "_validator", checked_schema)
  monkeypatch.setattr(Tree, "read", checked_read)
  monkeypatch.setattr(store, "_validate", checked_validate)
  with ThreadPoolExecutor(max_workers=6) as executor:
    assert list(executor.map(lambda _: store.read(lease["lease_id"]), range(18))) == [lease] * 18


def test_valid_raw_byte_change_repeats_original_validation(saved, monkeypatch):
  store, lease, path = saved
  calls = []; original = store._validate
  def checked(value): calls.append(1); return original(value)
  monkeypatch.setattr(store, "_validate", checked)
  assert store.read(lease["lease_id"]) == lease
  path.write_text(json.dumps(lease, indent=2))
  assert store.read(lease["lease_id"]) == lease
  assert store.read(lease["lease_id"]) == lease
  assert len(calls) == 2


def test_latest_schema_disappearing_after_original_validation_only_skips_memo(saved, tmp_path, monkeypatch):
  store, lease, _ = saved
  schemas = tmp_path / "schemas"; shutil.copytree(pi_catalog.SCHEMAS, schemas)
  monkeypatch.setattr(pi_catalog, "SCHEMAS", schemas)
  path = schemas / "execution-lease.schema.json"; original = store._validate
  def removed(value): original(value); path.unlink()
  monkeypatch.setattr(store, "_validate", removed)
  assert store.read(lease["lease_id"]) == lease
  assert not store._read_cache
  monkeypatch.setattr(store, "_validate", original)
  with pytest.raises(Conflict): store.read(lease["lease_id"])


def test_concurrent_old_snapshot_does_not_mask_new_disk_bytes(saved, monkeypatch):
  import threading
  store, lease, path = saved
  entered = threading.Event(); resume = threading.Event(); original = Tree.read
  blocked = {"once": False}
  def old_snapshot(tree, name, **kwargs):
    result = original(tree, name, **kwargs)
    if str(name).startswith("activity/leases/") and not blocked["once"]:
      blocked["once"] = True; entered.set()
      assert resume.wait(3)
    return result
  monkeypatch.setattr(Tree, "read", old_snapshot)
  with ThreadPoolExecutor(max_workers=2) as executor:
    old = executor.submit(store.read, lease["lease_id"])
    assert entered.wait(3)
    changed = deepcopy(lease); changed["last_sequence"] += 1
    path.write_bytes(json_bytes(changed))
    new = executor.submit(store.read, lease["lease_id"]).result(timeout=3)
    resume.set(); previous = old.result(timeout=3)
  assert previous == lease and new == changed
  assert store.read(lease["lease_id"]) == changed
