"""逐主运行归属：真实目录锁、合成身份和观察；不启动宿主或调查任务。"""

from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest

from agentcfg.lifecycle import guard
from agentcfg.run_owners import Registry, ReleaseObservation, current_process_identity
from agentcfg.storage import Conflict


IDENTITY = {"pid": 12345, "birth_id": "synthetic-boot:100"}


@pytest.fixture
def ownership(tmp_path):
  workspace = SimpleNamespace(instance=tmp_path / "instance", state_root=tmp_path / "state",
    profile="synthetic-profile", binding={"profile": "synthetic-profile", "machine": "fixture"})
  with guard(workspace):
    pass
  return workspace, Registry(workspace.state_root / "run-owners", workspace.binding)


def register(workspace, registry, identity=IDENTITY, session_ref=None):
  with guard(workspace, shared=True, create=False):
    return registry.register(identity, session_ref=session_ref)


def released(record):
  return ReleaseObservation(record["run_id"], record["manager_identity"], True, True)


def test_two_runs_are_private_and_one_exit_never_clears_another(ownership):
  workspace, registry = ownership
  first = register(workspace, registry)
  second = register(workspace, registry, {"pid": 12346, "birth_id": "synthetic-boot:200"})
  before = registry.snapshot()[second]
  with guard(workspace, shared=True, create=False):
    registry.mark_unknown(first, IDENTITY)
  records = registry.snapshot()
  assert first != second and len(first) == len(second) == 32
  assert records[first]["state"] == "unknown"
  assert records[first]["session_ref"] is None
  assert records[second] == before and records[second]["state"] == "active"
  root = workspace.state_root / "run-owners"
  assert root.stat().st_mode & 0o777 == 0o700
  assert all(path.stat().st_mode & 0o777 == 0o600 for path in root.iterdir())
  assert workspace.binding not in [record.get("binding") for record in records.values()]
  with guard(workspace, create=False), pytest.raises(Conflict):
    registry.assert_inactive()


@pytest.mark.parametrize("state", ["active", "unknown"])
def test_active_or_unknown_blocks_maintenance_but_valid_owner_allows_registration(ownership, state):
  workspace, registry = ownership
  run_id = register(workspace, registry)
  if state == "unknown":
    with guard(workspace, shared=True, create=False):
      registry.mark_unknown(run_id, IDENTITY)
  before = registry.snapshot()[run_id]
  second = register(workspace, registry)
  assert registry.snapshot()[run_id] == before
  assert registry.snapshot()[second]["state"] == "active"
  with guard(workspace, create=False), pytest.raises(Conflict):
    registry.assert_inactive()
  assert registry.snapshot()[run_id]["state"] == state


def test_pid_reuse_and_partial_identity_cannot_update_owner(ownership, sentinel_factory):
  workspace, registry = ownership
  run_id = register(workspace, registry)
  sentinel = sentinel_factory(registry.root)
  for identity in ({"pid": IDENTITY["pid"], "birth_id": "synthetic-new-birth"}, {"pid": IDENTITY["pid"]}):
    with guard(workspace, shared=True, create=False), pytest.raises(Conflict):
      registry.mark_unknown(run_id, identity)
  sentinel.assert_unchanged()


def test_all_identity_fields_must_match_without_boolean_integer_equivalence(ownership):
  workspace, registry = ownership
  manager = {**IDENTITY, "namespace": 1}
  run_id = register(workspace, registry, manager)
  with guard(workspace, shared=True, create=False), pytest.raises(Conflict):
    registry.mark_unknown(run_id, {**manager, "namespace": True})
  assert registry.snapshot()[run_id]["state"] == "active"


def test_snapshot_is_independent_and_session_ref_only_records_explicit_evidence(ownership):
  workspace, registry = ownership
  identity = deepcopy(IDENTITY)
  run_id = register(workspace, registry, identity, session_ref="synthetic-session")
  identity["birth_id"] = "changed-caller"
  snapshot = registry.snapshot()
  snapshot[run_id]["manager_identity"]["birth_id"] = "changed-result"
  assert registry.snapshot()[run_id]["manager_identity"] == IDENTITY
  assert registry.snapshot()[run_id]["session_ref"] == "synthetic-session"


def test_resource_scope_and_observation_follow_state_without_timeout_release(ownership, monkeypatch):
  import agentcfg.run_owners as owners
  workspace, registry = ownership
  monkeypatch.setattr(owners.time, "time_ns", lambda: 1)
  run_id = register(workspace, registry)
  record = registry.snapshot()[run_id]
  assert record["affected_resources"] == ["instance", "runtime", "native-home"]
  assert record["observation"] == {"kind": "manager_registered", "observed_at_ns": 1, "coverage": "unknown"}
  monkeypatch.setattr(owners.time, "time_ns", lambda: 10 ** 20)
  with guard(workspace, create=False), pytest.raises(Conflict):
    registry.assert_inactive()
  assert registry.snapshot()[run_id] == record
  with guard(workspace, shared=True, create=False):
    registry.mark_unknown(run_id, IDENTITY)
  record = registry.snapshot()[run_id]
  assert record["observation"] == {"kind": "manager_scope_ended", "observed_at_ns": 10 ** 20, "coverage": "unknown"}
  registry.reconcile(run_id, maintenance_guard=guard(workspace, create=False), observe=released)
  record = registry.snapshot()[run_id]
  assert record["affected_resources"] == ["instance", "runtime", "native-home"]
  assert record["observation"] == {"kind": "complete_release", "observed_at_ns": 10 ** 20, "coverage": "complete"}


@pytest.mark.parametrize("damage", ["resources", "resource-extra", "observation-extra", "kind", "coverage", "time-bool", "time-zero", "time-string"])
def test_invalid_resource_or_observation_fields_block_maintenance(ownership, damage, sentinel_factory):
  workspace, registry = ownership
  run_id = register(workspace, registry)
  path = registry.root / (run_id + ".json")
  record = json.loads(path.read_bytes())
  if damage == "resources":
    record["affected_resources"] = ["instance"]
  elif damage == "resource-extra":
    record["affected_resources"].append("user-defined")
  elif damage == "observation-extra":
    record["observation"]["unexpected"] = True
  else:
    key, value = {"kind": ("kind", "complete_release"), "coverage": ("coverage", "complete"),
      "time-bool": ("observed_at_ns", True), "time-zero": ("observed_at_ns", 0),
      "time-string": ("observed_at_ns", "123")}[damage]
    record["observation"][key] = value
  path.write_text(json.dumps(record))
  sentinel = sentinel_factory(registry.root)
  with guard(workspace, create=False), pytest.raises(Conflict):
    registry.assert_inactive()
  sentinel.assert_unchanged()


def test_deep_corrupt_json_blocks_maintenance_without_changing_another_run(ownership, sentinel_factory):
  workspace, registry = ownership
  first = register(workspace, registry)
  second = register(workspace, registry)
  second_path = registry.root / (second + ".json")
  before = second_path.read_bytes()
  depth = sys.getrecursionlimit() + 100
  (registry.root / (first + ".json")).write_bytes(b'{"nested":' + b"[" * depth + b"0" + b"]" * depth + b"}")
  sentinel = sentinel_factory(registry.root)
  with guard(workspace, create=False), pytest.raises(Conflict, match="记录格式无效"):
    registry.assert_inactive()
  assert second_path.read_bytes() == before
  sentinel.assert_unchanged()


@pytest.mark.parametrize("target", ["binding", "manager"])
@pytest.mark.parametrize("shape", ["deep", "cycle"])
def test_recursive_identity_or_binding_is_fixed_conflict_without_writes(ownership, target, shape):
  workspace, registry = ownership
  nested = {}
  if shape == "cycle":
    nested["synthetic-private-content"] = nested
  else:
    cursor = nested
    for _ in range(sys.getrecursionlimit() + 100):
      cursor["synthetic-private-content"] = {}
      cursor = cursor["synthetic-private-content"]
  with pytest.raises(Conflict) as caught:
    if target == "binding":
      Registry(registry.root, nested)
    else:
      register(workspace, registry, {**IDENTITY, "nested": nested})
  assert "synthetic-private-content" not in str(caught.value)
  assert not registry.root.exists()


@pytest.mark.parametrize("damage", ["json", "mode", "binding", "run-id", "state", "unknown-field", "duplicate-key", "symlink", "hardlink", "directory"])
def test_invalid_record_blocks_all_registry_operations_without_repair(ownership, damage, sentinel_factory):
  workspace, registry = ownership
  run_id = register(workspace, registry)
  path = registry.root / (run_id + ".json")
  if damage == "json":
    path.write_bytes(b"not json")
  elif damage == "mode":
    path.chmod(0o640)
  elif damage == "symlink":
    outside = registry.root.parent / "synthetic-target"
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
  elif damage == "hardlink":
    os.link(path, registry.root.parent / "synthetic-alias")
  elif damage == "directory":
    path.unlink()
    path.mkdir()
  elif damage == "duplicate-key":
    path.write_bytes(path.read_bytes().rstrip()[:-1] + b',"state":"idle_confirmed"}\n')
  else:
    record = json.loads(path.read_bytes())
    record[{"binding": "binding_digest", "run-id": "run_id", "state": "state", "unknown-field": "unexpected"}[damage]] = "wrong"
    path.write_text(json.dumps(record))
  sentinel = sentinel_factory(registry.root.parent)
  with pytest.raises(Conflict):
    registry.snapshot()
  with guard(workspace, create=False), pytest.raises(Conflict):
    registry.assert_inactive()
  with pytest.raises(Conflict):
    register(workspace, registry)
  with guard(workspace, shared=True, create=False), pytest.raises(Conflict):
    registry.mark_unknown(run_id, IDENTITY)
  sentinel.assert_unchanged()


def test_other_binding_cannot_read_or_register_in_same_registry(ownership):
  workspace, registry = ownership
  register(workspace, registry)
  other = Registry(registry.root, {"profile": "another-profile"})
  with pytest.raises(Conflict):
    other.snapshot()
  with pytest.raises(Conflict):
    register(workspace, other)


def test_root_symlink_or_mode_is_conflict(ownership):
  workspace, registry = ownership
  register(workspace, registry)
  registry.root.chmod(0o750)
  with pytest.raises(Conflict):
    registry.snapshot()
  registry.root.chmod(0o700)
  original = registry.root.with_name("original-run-owners")
  registry.root.rename(original)
  registry.root.symlink_to(original, target_is_directory=True)
  with pytest.raises(Conflict):
    registry.snapshot()


def test_record_owned_by_another_user_is_conflict(ownership, monkeypatch):
  workspace, registry = ownership
  run_id = register(workspace, registry)
  original_stat = os.stat
  def wrong_owner(path, *args, **kwargs):
    result = original_stat(path, *args, **kwargs)
    if path == run_id + ".json" and "dir_fd" in kwargs:
      fields = list(result)
      fields[4] = os.geteuid() + 100000
      return os.stat_result(fields)
    return result
  monkeypatch.setattr(os, "stat", wrong_owner)
  with pytest.raises(Conflict):
    registry.snapshot()


def test_observer_cannot_switch_root_inode_before_confirming_release(ownership):
  workspace, registry = ownership
  run_id = register(workspace, registry)
  before = (registry.root / (run_id + ".json")).read_bytes()
  original = registry.root.with_name("original-run-owners")
  def switch_root(record):
    registry.root.rename(original)
    registry.root.mkdir(mode=0o700)
    return released(record)
  with pytest.raises(Conflict):
    registry.reconcile(run_id, maintenance_guard=guard(workspace, create=False), observe=switch_root)
  assert (original / (run_id + ".json")).read_bytes() == before
  assert list(registry.root.iterdir()) == []


@pytest.mark.parametrize("failure", ["missing", "incomplete", "related-active", "identity", "run-id", "exception", "wrong-type"])
def test_reconcile_failure_preserves_record(ownership, failure, sentinel_factory):
  workspace, registry = ownership
  run_id = register(workspace, registry)
  with guard(workspace, shared=True, create=False):
    registry.mark_unknown(run_id, IDENTITY)
  sentinel = sentinel_factory(registry.root)
  def observe(record):
    if failure == "exception":
      raise RuntimeError("synthetic incomplete process observation")
    if failure == "wrong-type":
      return {"complete": True}
    return ReleaseObservation("f" * 32 if failure == "run-id" else run_id,
      {"pid": IDENTITY["pid"], "birth_id": "reused"} if failure == "identity" else IDENTITY,
      failure != "related-active", failure != "incomplete")
  with pytest.raises(Conflict):
    registry.reconcile(run_id, maintenance_guard=guard(workspace, create=False),
      observe=None if failure == "missing" else observe)
  sentinel.assert_unchanged()


def test_observer_executes_under_exclusive_maintenance_and_metadata_lock(ownership):
  workspace, registry = ownership
  first = register(workspace, registry)
  second = register(workspace, registry)
  def observe(record):
    with pytest.raises(Conflict):
      with guard(workspace, shared=True, create=False):
        pytest.fail("maintenance allowed concurrent registration")
    fd = os.open(registry.root, os.O_RDONLY | os.O_DIRECTORY)
    try:
      with pytest.raises(BlockingIOError):
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
      os.close(fd)
    return released(record)
  registry.reconcile(first, maintenance_guard=guard(workspace, create=False), observe=observe)
  assert registry.snapshot()[first]["state"] == "idle_confirmed"
  assert registry.snapshot()[second]["state"] == "active"
  with guard(workspace, create=False), pytest.raises(Conflict):
    registry.assert_inactive()
  registry.reconcile(second, maintenance_guard=guard(workspace, create=False), observe=released)
  with guard(workspace, create=False):
    registry.assert_inactive()


def test_physical_shared_run_blocks_reconcile_before_observer(ownership):
  workspace, registry = ownership
  run_id = register(workspace, registry)
  with guard(workspace, shared=True, create=False), pytest.raises(Conflict):
    registry.reconcile(run_id, maintenance_guard=guard(workspace, create=False),
      observe=lambda record: pytest.fail("observer ran without maintenance admission"))
  assert registry.snapshot()[run_id]["state"] == "active"


def test_metadata_operations_serialize_on_directory_inode(ownership):
  workspace, registry = ownership
  register(workspace, registry)
  entered, finished = threading.Event(), threading.Event()
  errors = []
  fd = os.open(registry.root, os.O_RDONLY | os.O_DIRECTORY)
  fcntl.flock(fd, fcntl.LOCK_EX)
  def another_registration():
    entered.set()
    try:
      register(workspace, registry)
    except BaseException as error:
      errors.append(error)
    finally:
      finished.set()
  thread = threading.Thread(target=another_registration)
  thread.start()
  try:
    assert entered.wait(2)
    assert not finished.wait(0.05)
  finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
    thread.join(3)
  assert finished.is_set() and not errors and not thread.is_alive()
  assert len(registry.snapshot()) == 2


def test_current_identity_requires_reliable_linux_proc_source(monkeypatch):
  import agentcfg.run_owners as owners
  monkeypatch.setattr(owners.sys, "platform", "linux")
  def missing(*args, **kwargs):
    raise OSError("synthetic proc unavailable")
  monkeypatch.setattr(Path, "read_text", missing)
  with pytest.raises(Conflict):
    current_process_identity()


def test_current_linux_identity_uses_boot_and_start_ticks_with_complex_comm(monkeypatch):
  import agentcfg.run_owners as owners
  monkeypatch.setattr(owners.sys, "platform", "linux")
  boot = "00000000-0000-4000-8000-000000000001"
  fields = ["S"] + ["0"] * 18 + ["345"]
  def proc(path, **kwargs):
    if path == Path("/proc/sys/kernel/random/boot_id"):
      return boot + "\n"
    assert path == Path("/proc/self/stat")
    return str(os.getpid()) + " (synthetic ) process) " + " ".join(fields)
  monkeypatch.setattr(Path, "read_text", proc)
  assert current_process_identity() == {"pid": os.getpid(), "birth_id": "linux:" + boot + ":345"}


@pytest.mark.parametrize("identity", [{"pid": True, "birth_id": "x"}, {"pid": 0, "birth_id": "x"},
  {"pid": 1, "birth_id": ""}, {"pid": 1}, {}])
def test_invalid_manager_does_not_create_registry(ownership, identity):
  workspace, registry = ownership
  with pytest.raises(Conflict):
    register(workspace, registry, identity)
  assert not registry.root.exists()


def test_empty_registry_read_is_non_mutating_and_guard_is_required_for_reconcile(ownership):
  workspace, registry = ownership
  assert registry.snapshot() == {}
  with guard(workspace, create=False):
    registry.assert_inactive()
  with pytest.raises(Conflict):
    registry.reconcile("a" * 32, maintenance_guard=None, observe=released)
  assert not registry.root.exists()


@pytest.mark.parametrize("run_id", ["../outside", "z" * 32, [], None])
def test_invalid_run_id_is_conflict_without_mutation(ownership, run_id, sentinel_factory):
  workspace, registry = ownership
  register(workspace, registry)
  sentinel = sentinel_factory(registry.root)
  with guard(workspace, shared=True, create=False), pytest.raises(Conflict):
    registry.mark_unknown(run_id, IDENTITY)
  with pytest.raises(Conflict):
    registry.reconcile(run_id, maintenance_guard=guard(workspace, create=False), observe=released)
  sentinel.assert_unchanged()


def test_current_identity_does_not_guess_other_platform(monkeypatch):
  import agentcfg.run_owners as owners
  monkeypatch.setattr(owners.sys, "platform", "darwin")
  with pytest.raises(Conflict):
    current_process_identity()
