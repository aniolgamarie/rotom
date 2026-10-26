"""临时 Registry 停止意图与登记互斥；不构造停止许可或调用宿主。"""
from copy import deepcopy
import fcntl
import importlib
import json
import os

import pytest

from agentcfg import run_owners
from agentcfg.storage import Conflict, Tree
from test_rotom_run_records import MANAGER, store


def module(): return importlib.import_module("agentcfg.run_stop_fence")


def path(store):
  return store.registry.root.with_name(store.registry.root.name + ".stop-fence.json")


def install(store, **kwargs):
  return module().install(store.registry, batch_id="a" * 32, plan_id="b" * 64,
    expected_records=store.registry.snapshot(), **kwargs)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("form", ["empty", "invalid", "directory", "symlink"])
def test_any_fence_presence_blocks_new_owner_without_reading_body(store, version, form):
  store.registry.register_v2(MANAGER, store.metadata)
  before = store.registry.snapshot()
  if form == "directory": path(store).mkdir(mode=0o700)
  elif form == "symlink": path(store).symlink_to(store.native / "do-not-read")
  else: path(store).write_bytes(b"" if form == "empty" else b"synthetic-private-canary")
  with pytest.raises(Conflict) as caught:
    if version == 1: store.registry.register(MANAGER)
    else: store.registry.register_v2(MANAGER, store.metadata)
  assert "synthetic-private-canary" not in str(caught.value)
  assert store.registry.snapshot() == before


def test_fence_does_not_block_current_exit_accounting_but_still_blocks_maintenance(store):
  run = store.registry.register_v2(MANAGER, store.metadata)
  assert install(store) is None
  store.registry.finish_current(run, MANAGER, run_owners.ReleaseObservation(run, deepcopy(MANAGER), True, True))
  assert store.registry.snapshot()[run]["lifecycle_state"] == "idle_confirmed"
  with pytest.raises(Conflict): store.registry.assert_inactive()
  assert module().read(store.registry)["batch_id"] == "a" * 32


def test_fence_allows_unknown_and_readonly_observation_and_does_not_clear_itself(store):
  run = store.registry.register_v2(MANAGER, store.metadata)
  install(store)
  before = path(store).read_bytes()
  store.registry.mark_unknown(run, MANAGER)
  assert store.registry.snapshot()[run]["lifecycle_state"] == "unknown"
  assert module().read(store.registry)["records_digest"]
  assert path(store).read_bytes() == before


def test_install_holds_same_owner_lock_through_callback_write_sync_and_readback(store, monkeypatch):
  store.registry.register_v2(MANAGER, store.metadata)
  events = []
  def busy():
    with Tree(store.registry.root) as other:
      with pytest.raises(BlockingIOError): fcntl.flock(other.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  def callback(): busy(); events.append("callback")
  original = Tree.write_new
  def write(tree, name, data):
    if name == path(store).name:
      busy(); assert events == ["callback"]; events.append("write")
    return original(tree, name, data)
  monkeypatch.setattr(Tree, "write_new", write)
  assert install(store, before_publish=callback) is None
  assert events == ["callback", "write"]
  saved = module().read(store.registry)
  assert saved["binding_digest"] == store.registry.binding_digest
  assert set(saved) == {"schema_version", "kind", "binding_digest", "registry_physical", "batch_id", "plan_id", "records_digest"}
  assert path(store).stat().st_mode & 0o777 == 0o600
  with pytest.raises(Conflict): install(store, before_publish=lambda: pytest.fail("cannot replay callback"))


@pytest.mark.parametrize("damage", ["new-run", "changed", "missing", "empty", "bad-batch", "bad-plan", "callback"])
def test_stale_or_invalid_acceptance_does_not_publish_or_call_review(store, damage):
  run = store.registry.register_v2(MANAGER, store.metadata)
  expected = store.registry.snapshot()
  options = {"batch_id": "a" * 32, "plan_id": "b" * 64, "expected_records": expected,
    "before_publish": lambda: pytest.fail("must validate before callback")}
  if damage == "new-run": store.registry.register_v2(MANAGER, store.metadata)
  elif damage == "changed": store.registry.mark_unknown(run, MANAGER)
  elif damage == "missing": (store.registry.root / (run + ".json")).unlink()
  elif damage == "empty": options["expected_records"] = {}
  elif damage == "bad-batch": options["batch_id"] = "bad"
  elif damage == "bad-plan": options["plan_id"] = "bad"
  else: options["before_publish"] = 1
  with pytest.raises(Conflict): module().install(store.registry, **options)
  assert not path(store).exists()


def test_callback_cannot_change_records_then_publish_stale_fence(store):
  run = store.registry.register_v2(MANAGER, store.metadata)
  def changed():
    record = store.registry.root / (run + ".json")
    value = json.loads(record.read_bytes()); run_owners._set_state(value, "unknown")
    record.write_bytes(run_owners._encode(value))
  with pytest.raises(Conflict): install(store, before_publish=changed)
  assert not path(store).exists()


@pytest.mark.parametrize("stage", ["callback", "write-before", "write-after", "sync"])
@pytest.mark.parametrize("error_type", [OSError, KeyboardInterrupt, SystemExit])
def test_failure_preserves_possible_intent_and_control_interrupt(store, monkeypatch, stage, error_type):
  store.registry.register_v2(MANAGER, store.metadata)
  error = error_type("synthetic-private-canary")
  mod = module(); original = Tree.write_new
  def callback():
    if stage == "callback": raise error
  def write(tree, name, data):
    if stage == "write-before": raise error
    result = original(tree, name, data)
    if stage == "write-after": raise error
    return result
  def sync(*args): raise error
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", write)
    if stage == "sync": patch.setattr(mod.storage, "sync_directory_ancestors", sync)
    with pytest.raises(Conflict if error_type is OSError else error_type) as caught:
      install(store, before_publish=callback)
  if error_type is not OSError: assert caught.value is error
  else: assert "synthetic-private-canary" not in str(caught.value)
  assert path(store).exists() == (stage in ("write-after", "sync"))
  if path(store).exists():
    before = path(store).read_bytes()
    with pytest.raises(Conflict): install(store)
    assert path(store).read_bytes() == before


@pytest.mark.parametrize("damage", ["extra", "binding", "physical", "schema", "batch", "plan", "digest", "mode", "symlink"])
def test_read_refuses_damaged_fence_without_repair_or_authority(store, damage):
  store.registry.register_v2(MANAGER, store.metadata); install(store)
  marker = path(store)
  if damage == "mode": marker.chmod(0o644)
  elif damage == "symlink": marker.unlink(); marker.symlink_to(store.native / "missing")
  else:
    value = json.loads(marker.read_bytes())
    if damage == "extra": value["token"] = "synthetic-private-canary"
    elif damage == "binding": value["binding_digest"] = "0" * 64
    elif damage == "physical": value["registry_physical"]["inode"] += 1
    elif damage == "schema": value["schema_version"] = True
    else: value[{"batch": "batch_id", "plan": "plan_id", "digest": "records_digest"}[damage]] = "bad"
    marker.write_bytes(run_owners._encode(value))
  with pytest.raises(Conflict) as caught: module().read(store.registry)
  assert "synthetic-private-canary" not in str(caught.value)
  with pytest.raises(Conflict): store.registry.register_v2(MANAGER, store.metadata)


def test_absent_fence_read_is_no_create_and_unrelated_registry_is_unaffected(store):
  assert module().read(store.registry) is None and not store.registry.root.exists()
  store.registry.register_v2(MANAGER, store.metadata); install(store)
  other = run_owners.Registry(store.registry.root.with_name("other-owners"), store.binding)
  assert other.register_v2(MANAGER, store.metadata) in other.snapshot()


def test_disappeared_registry_does_not_make_existing_fence_absent(store):
  store.registry.register_v2(MANAGER, store.metadata); install(store)
  store.registry.root.rename(store.registry.root.with_name("saved-owners"))
  with pytest.raises(Conflict): module().read(store.registry)
  with pytest.raises(Conflict): store.registry.assert_inactive()


@pytest.mark.parametrize("stage", ["callback", "sync"])
@pytest.mark.parametrize("replacement", ["owner-root", "parent", "marker"])
def test_replaced_roots_or_marker_cannot_return_success_or_overwrite_fact(store, monkeypatch, stage, replacement):
  # 只替换本测试的元数据容器，保留隔离 HOME 和外围文件哨兵。
  container = store.registry.root.parent / "fence-scope"
  container.mkdir(mode=0o700)
  store.registry = run_owners.Registry(container / "run-owners", store.binding)
  store.registry.register_v2(MANAGER, store.metadata)
  original_parent = store.registry.root.parent
  marker = path(store)
  changed = []
  def replace():
    if changed: return
    changed.append(True)
    if replacement == "marker":
      if marker.exists(): marker.unlink()
      marker.write_bytes(b"synthetic-private-canary"); marker.chmod(0o600)
    elif replacement == "owner-root":
      root = store.registry.root; root.rename(root.with_name("saved-owners")); root.mkdir(mode=0o700)
    else:
      original_parent.rename(original_parent.with_name(original_parent.name + "-saved"))
      original_parent.mkdir(mode=0o700)
  mod = module(); sync = mod.storage.sync_directory_ancestors
  def syncing(parent):
    result = sync(parent)
    replace()
    return result
  with monkeypatch.context() as patch:
    if stage == "sync": patch.setattr(mod.storage, "sync_directory_ancestors", syncing)
    with pytest.raises(Conflict) as caught:
      install(store, before_publish=replace if stage == "callback" else None)
  assert changed and "synthetic-private-canary" not in str(caught.value)
  if replacement == "marker": assert marker.read_bytes() == b"synthetic-private-canary"


def test_second_installer_cannot_enter_locked_registry_or_run_callback(store):
  store.registry.register_v2(MANAGER, store.metadata)
  expected = store.registry.snapshot()
  def first_callback():
    with pytest.raises(Conflict):
      module().install(store.registry, batch_id="b" * 32, plan_id="c" * 64,
        expected_records=expected,
        before_publish=lambda: pytest.fail("second installer must not enter callback"))
  install(store, before_publish=first_callback)
  assert module().read(store.registry)["batch_id"] == "a" * 32
