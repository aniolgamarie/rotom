"""独立持续SH资源默认验收；真实自有Tree/flock，无宿主或来源资格。"""

import builtins
from copy import copy, deepcopy
import errno
import fcntl
import gc
import os
from pathlib import Path
import pickle
import traceback
import weakref
from types import SimpleNamespace

import pytest

from agentcfg import pi_source_reader as readers
from agentcfg import pi_source_latch as latch
from agentcfg import pi_lifecycle as lifecycle
from agentcfg.config import ResolvedConfig
from agentcfg.deployment import json_bytes
from agentcfg.merge import Provenance
from agentcfg.pi import PiAdapter
from agentcfg.storage import Conflict, Tree, ensure_private, instance_lock
from agentcfg.workspace import Workspace


CODE = "PI_SOURCE_READER_INVALID"
SECRET = "SYNTHETIC_SOURCE_READER_PRIVATE"


def rejected(action):
  try:
    raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Exception) as caught: action()
  error = caught.value
  assert error.args == (CODE,) and getattr(error, "exit_code", None) == 4
  assert error.__cause__ is None and error.__context__ is None
  assert SECRET not in "".join(traceback.format_exception(error))


@pytest.fixture
def workspace(tmp_path):
  data = {"profile": {"id": "pi-base", "agent": "pi"}, "machine": {"id": "synthetic", "paths": {
    "instances_root": str(tmp_path / "instances"), "state_root": str(tmp_path / "states"), "cache_root": str(tmp_path / "cache")}}}
  actual = Workspace(tmp_path, tmp_path / "local.toml", ResolvedConfig(data, Provenance({}), 1), PiAdapter(tmp_path), None, None)
  ensure_private(actual.instance); ensure_private(actual.state_root)
  with Tree(actual.instance) as tree:
    tree.write_new(".agentcfg-instance.json", marker(actual))
  with latch.source_latch(actual, shared=True, create=True): pass
  return actual


def marker(workspace):
  return json_bytes({"schema_version": 1, "state_root": str(workspace.state_root), "binding": workspace.binding})


def record(reader): return readers._records[id(reader)]


def test_reader_retains_sh_after_foreground_source_life_and_true_state_ex_exit(workspace):
  reader = readers.hold_source_reader(workspace)
  saved = record(reader)
  try:
    for turn in range(2):
      with lifecycle.source_guard(workspace, shared=True, create=False):
        with Tree(workspace.state_root) as state, instance_lock(state):
          pass
      reader.check()
      writes = []
      with pytest.raises(Conflict):
        with lifecycle.source_guard(workspace, create=False):
          writes.append(True)
          (workspace.instance / "mutator-wrote").write_bytes(b"forbidden")
      assert writes == [] and not (workspace.instance / "mutator-wrote").exists()
    reader.close()
    with lifecycle.source_guard(workspace, create=False):
      with Tree(workspace.state_root) as state, instance_lock(state): pass
  finally:
    if not saved.retired: reader.close()


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_two_readers_coexist_and_neither_reader_keeps_life_or_state_ex(workspace, profile):
  workspace.resolved.data["profile"]["id"] = profile
  if profile == "pi-full":
    ensure_private(workspace.instance); ensure_private(workspace.state_root)
    with Tree(workspace.instance) as tree: tree.write_new(".agentcfg-instance.json", marker(workspace))
    with latch.source_latch(workspace, create=True): pass
  first = readers.hold_source_reader(workspace)
  second = readers.hold_source_reader(workspace)
  saved_records = (record(first), record(second))
  try:
    first.check(); second.check()
    first.close()
    with pytest.raises(Conflict):
      with latch.source_latch(workspace): pytest.fail("second reader lost SH")
    with lifecycle.source_guard(workspace, shared=True, create=False):
      with Tree(workspace.state_root) as state, instance_lock(state): pass
    second.close()
    with latch.source_latch(workspace): pass
  finally:
    for value, saved in zip((first, second), saved_records):
      if not saved.retired: value.close()


@pytest.mark.parametrize("profile", ["pi-base", "pi-full"])
def test_no_full_optional_import_or_observation_for_base_and_full(workspace, monkeypatch, profile):
  if profile == "pi-full":
    workspace.resolved.data["profile"]["id"] = profile
    ensure_private(workspace.instance); ensure_private(workspace.state_root)
    with Tree(workspace.instance) as tree: tree.write_new(".agentcfg-instance.json", marker(workspace))
    with latch.source_latch(workspace, create=True): pass
  original_import = builtins.__import__
  seen = []
  def importing(name, *args, **kwargs):
    if name.endswith(("pi_current_full_source", "pi_owner_origin", "pi_installed_source")):
      seen.append(name); raise AssertionError("Full import")
    return original_import(name, *args, **kwargs)
  monkeypatch.setattr(builtins, "__import__", importing)
  value = readers.hold_source_reader(workspace)
  value.check(); value.close()
  assert seen == []


@pytest.mark.parametrize("fault", ["legacy", "agent", "foreign-workspace", "foreign-adapter", "marker-missing", "marker-mode", "marker-binding", "anchor-missing", "instance-mode"])
def test_reject_input_marker_or_anchor_without_creation(workspace, monkeypatch, fault):
  actual = workspace
  marker_path = actual.instance / ".agentcfg-instance.json"
  anchor_path = actual.instance / "source.lock"
  if fault == "legacy": actual.resolved.data["profile"]["id"] = "pi-legacy"
  if fault == "agent": actual.resolved.data["profile"]["agent"] = "dsh"
  if fault == "foreign-workspace": actual = SimpleNamespace(**workspace.__dict__)
  if fault == "foreign-adapter": actual.adapter = object()
  if fault == "marker-missing": marker_path.unlink()
  if fault == "marker-mode": marker_path.chmod(0o644)
  if fault == "marker-binding": marker_path.write_bytes(b"wrong")
  if fault == "anchor-missing": anchor_path.unlink()
  if fault == "instance-mode": actual.instance.chmod(0o755)
  rejected(lambda: readers.hold_source_reader(actual))
  if fault == "marker-missing": assert not marker_path.exists()
  if fault == "anchor-missing": assert not anchor_path.exists()
  if fault == "legacy": assert not actual.instance.exists()


def test_nonmain_factory_zero_marker_or_acquisition_io(workspace, monkeypatch):
  calls = []
  monkeypatch.setattr(readers, "threading", SimpleNamespace(current_thread=lambda: object(), main_thread=lambda: object()))
  monkeypatch.setattr(readers, "Tree", lambda *args, **kwargs: calls.append(True) or pytest.fail("nonmain Tree"))
  rejected(lambda: readers.hold_source_reader(workspace))
  assert calls == []


@pytest.mark.parametrize("kind", ["profile", "agent", "instance", "state", "binding", "adapter", "marker", "named-anchor", "named-root"])
def test_check_and_close_stale_named_or_workspace_context_still_cleanup_known_owned(workspace, kind):
  value = readers.hold_source_reader(workspace)
  saved = record(value)
  original_source, original_tree = saved.source, saved.tree_fd
  if kind == "profile": workspace.resolved.data["profile"]["id"] = "pi-full"
  if kind == "agent": workspace.resolved.data["profile"]["agent"] = "dsh"
  if kind == "instance": workspace.resolved.data["machine"]["paths"]["instances_root"] += "-other"
  if kind == "state": workspace.resolved.data["machine"]["paths"]["state_root"] += "-other"
  if kind == "binding": workspace.resolved.data["machine"]["id"] += "-other"
  if kind == "adapter": workspace.adapter = PiAdapter(Path("/unused"))
  if kind == "marker": (saved.instance / ".agentcfg-instance.json").write_bytes(b"other marker")
  if kind == "named-anchor":
    anchor = saved.instance / "source.lock"; anchor.rename(anchor.with_name("old-source.lock")); anchor.write_bytes(b""); anchor.chmod(0o600)
  if kind == "named-root":
    saved.instance.rename(saved.instance.with_name("old-instance")); saved.instance.mkdir(mode=0o700)
  rejected(value.check)
  rejected(value.close)
  assert saved.retired
  for fd in (original_source, original_tree):
    with pytest.raises(OSError) as caught: os.fstat(fd)
    assert caught.value.errno == errno.EBADF


def test_mutable_directory_activity_and_unrelated_repo_cache_changes_are_not_stale(workspace):
  value = readers.hold_source_reader(workspace)
  saved = record(value)
  try:
    (workspace.instance / "activity-directory").mkdir(mode=0o700)
    (workspace.state_root / "heartbeat").write_bytes(b"activity")
    workspace.repository = object()
    workspace.resolved.data["machine"]["paths"]["cache_root"] = object()
    value.check()
    value.close()
  finally:
    if not saved.retired: value.close()


def test_captured_syscalls_threads_and_method_receivers_remain_original(workspace, monkeypatch):
  value = readers.hold_source_reader(workspace)
  saved = record(value)
  assert saved.parent.__self__ is saved.tree and saved.tree_close.__self__ is saved.tree
  def forbidden(*args, **kwargs): raise RuntimeError(SECRET)
  monkeypatch.setattr(readers, "os", SimpleNamespace(fstat=forbidden, stat=forbidden, close=forbidden, geteuid=forbidden))
  monkeypatch.setattr(readers, "fcntl", SimpleNamespace(fcntl=forbidden))
  monkeypatch.setattr(readers, "threading", SimpleNamespace(current_thread=forbidden, main_thread=forbidden))
  value.check(); value.close()
  assert saved.retired


@pytest.mark.parametrize("kind", ["raw", "foreign", "subclass", "constructor", "copy", "deepcopy", "pickle"])
def test_private_original_registration_cannot_be_reconstructed(workspace, kind):
  value = readers.hold_source_reader(workspace)
  try:
    if kind == "raw": action = lambda: readers.SourceReader.check(object.__new__(readers.SourceReader))
    elif kind == "foreign": action = lambda: readers.SourceReader.close(object())
    elif kind == "subclass":
      class Foreign(readers.SourceReader): pass
      action = lambda: readers.SourceReader.check(object.__new__(Foreign))
    elif kind == "constructor": action = readers.SourceReader
    elif kind == "copy": action = lambda: copy(value)
    elif kind == "deepcopy": action = lambda: deepcopy(value)
    else: action = lambda: pickle.dumps(value)
    rejected(action)
    for name in ("fileno", "fd", "authority", "__dict__", "__enter__", "__del__"):
      assert not hasattr(value, name)
    value.check()
  finally: value.close()


def test_wrong_thread_does_not_retire_owner_and_close_reentry_is_fixed(workspace, monkeypatch):
  owner = object(); other = object(); state = {"current": owner}
  monkeypatch.setattr(readers, "threading", SimpleNamespace(current_thread=lambda: state["current"], main_thread=lambda: owner))
  value = readers.hold_source_reader(workspace)
  saved = record(value)
  state["current"] = other
  rejected(value.check); rejected(value.close)
  assert not saved.retired
  state["current"] = owner
  original = saved.methods.close
  calls = []
  def close(fd):
    calls.append(fd); rejected(value.check); rejected(value.close); return original(fd)
  saved.resources.source_close = close
  value.close()
  assert calls == [saved.source]
  rejected(value.check); rejected(value.close)


@pytest.mark.parametrize("fault", ["source-tuple", "source-flags", "source-unknown", "tree-tuple", "tree-unknown"])
def test_foreign_or_unknown_held_resources_skipped_other_owned_resource_closes_once(workspace, fault):
  value = readers.hold_source_reader(workspace)
  saved = record(value)
  fstat_original, fcntl_original = saved.methods.fstat, saved.methods.fcntl
  source_fd, tree_fd = saved.source, saved.tree_fd
  def fstat(fd):
    info = fstat_original(fd)
    target = source_fd if fault.startswith("source") else tree_fd
    if fd == target and fault.endswith("unknown"): raise OSError(errno.EIO, SECRET)
    if fd == target and fault.endswith("tuple"):
      row = list(info); row[5] += 1; return os.stat_result(row)
    return info
  def flags(fd, command):
    result = fcntl_original(fd, command)
    return result ^ os.O_NONBLOCK if fault == "source-flags" and command == fcntl.F_GETFL else result
  saved.methods.fstat = fstat
  saved.methods.fcntl = flags
  rejected(value.close)
  assert saved.retired
  skipped = source_fd if fault.startswith("source") else tree_fd
  closed = tree_fd if fault.startswith("source") else source_fd
  with pytest.raises(OSError): os.fstat(closed)
  os.fstat(skipped)
  os.close(skipped)


@pytest.mark.parametrize("target", ["source", "tree", "both"])
def test_close_failures_do_not_retry_or_block_other_resource(workspace, target):
  value = readers.hold_source_reader(workspace)
  saved = record(value)
  source_close, tree_close = saved.resources.source_close, saved.resources.tree_close
  calls = []
  def close_source(fd):
    calls.append("source"); source_close(fd)
    if target in ("source", "both"): raise OSError(errno.EIO, SECRET)
  def close_tree():
    calls.append("tree"); tree_close()
    if target in ("tree", "both"): raise OSError(errno.EIO, SECRET)
  saved.resources.source_close, saved.resources.tree_close = close_source, close_tree
  rejected(value.close)
  assert calls == ["source", "tree"] and saved.retired
  rejected(value.close)
  assert calls == ["source", "tree"]


def test_registration_after_insert_interrupt_retires_before_known_owned_cleanup(workspace, monkeypatch):
  original = readers._register_record
  records = []
  def interrupted(value):
    original(value); records.append(value); raise KeyboardInterrupt(SECRET)
  monkeypatch.setattr(readers, "_register_record", interrupted)
  rejected(lambda: readers.hold_source_reader(workspace))
  saved = records[0]
  assert saved.retired
  rejected(saved.receiver.check); rejected(saved.receiver.close)
  for fd in (saved.source, saved.tree_fd):
    with pytest.raises(OSError): os.fstat(fd)


def test_bad_binding_is_fixed():
  for args, kwargs in (((), {}), ((None, None), {}), ((), {SECRET: SECRET}), ((object(),), {})):
    rejected(lambda: readers.hold_source_reader(*args, **kwargs))


def test_repeated_success_close_does_not_accumulate_and_old_receivers_stay_rejected(workspace):
  before = len(readers._records)
  for turn in range(12):
    value = readers.hold_source_reader(workspace)
    value.close()
    assert len(readers._records) == before
    rejected(value.check); rejected(value.close)


def test_success_closed_reader_does_not_keep_workspace_alive(workspace):
  clone = Workspace(**workspace.__dict__)
  weak = weakref.ref(clone)
  value = readers.hold_source_reader(clone)
  value.close()
  del clone
  gc.collect()
  assert weak() is None
  rejected(value.check)


def test_named_failure_with_both_known_closes_deletes_retired_record(workspace):
  value = readers.hold_source_reader(workspace)
  saved = record(value)
  (workspace.instance / ".agentcfg-instance.json").write_bytes(b"stale")
  rejected(value.close)
  assert saved.retired and id(value) not in readers._records
  rejected(value.check); rejected(value.close)


def test_unknown_retired_counts_towards_quota_and_full_quota_rejects_before_io(workspace, monkeypatch):
  before = len(readers._records)
  monkeypatch.setattr(readers, "_MAX_READERS", before + 1, raising=False)
  value = readers.hold_source_reader(workspace)
  saved = record(value)
  original = saved.methods.fstat
  def unknown(fd):
    if fd == saved.source: raise OSError(errno.EIO, SECRET)
    return original(fd)
  saved.methods.fstat = unknown
  rejected(value.close)
  assert readers._records[id(value)] is saved and saved.retired
  io = []
  original_marker, original_acquire = readers._marker, readers._acquire
  def forbidden(*args, **kwargs): io.append(True); raise AssertionError("quota IO")
  monkeypatch.setattr(readers, "_marker", forbidden)
  monkeypatch.setattr(readers, "_acquire", forbidden)
  rejected(lambda: readers.hold_source_reader(workspace))
  assert io == [] and getattr(readers, "_starting", 0) == 0
  os.close(saved.source)


def test_post_insert_interrupt_success_cleanup_forgets_its_original_record(workspace, monkeypatch):
  original = readers._register_record
  inserted = []
  def interrupted(value):
    original(value); inserted.append(value); raise KeyboardInterrupt(SECRET)
  monkeypatch.setattr(readers, "_register_record", interrupted)
  rejected(lambda: readers.hold_source_reader(workspace))
  saved = inserted[0]
  assert saved.retired and id(saved.receiver) not in readers._records
  rejected(saved.receiver.check); rejected(saved.receiver.close)
  assert getattr(readers, "_starting", 0) == 0


def test_reentrant_factory_starting_reservation_counts_before_marker_io(workspace, monkeypatch):
  monkeypatch.setattr(readers, "_MAX_READERS", len(readers._records) + 1, raising=False)
  original = readers._marker
  observations = []
  in_callback = False
  def marker(read, expected):
    nonlocal in_callback
    if not in_callback:
      in_callback = True
      try:
        observations.append(getattr(readers, "_starting", 0))
        rejected(lambda: readers.hold_source_reader(workspace))
      finally: in_callback = False
    return original(read, expected)
  monkeypatch.setattr(readers, "_marker", marker)
  value = readers.hold_source_reader(workspace)
  assert observations and all(count == 1 for count in observations)
  assert readers._starting == 0
  value.close()
  assert readers._starting == 0


def test_starting_reservation_released_once_on_bad_context(workspace, monkeypatch):
  monkeypatch.setattr(readers, "_MAX_READERS", len(readers._records) + 1, raising=False)
  workspace.resolved.data["profile"]["id"] = "pi-legacy"
  rejected(lambda: readers.hold_source_reader(workspace))
  assert getattr(readers, "_starting", 0) == 0
  workspace.resolved.data["profile"]["id"] = "pi-base"
  value = readers.hold_source_reader(workspace)
  value.close()
  assert getattr(readers, "_starting", 0) == 0
