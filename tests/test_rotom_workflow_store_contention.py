"""维护批次Store仅等待首次真实短锁竞争；锁体/CAS/写入不重放。"""

from concurrent.futures import ThreadPoolExecutor, TimeoutError
import errno
import fcntl
import os
import threading

import pytest

from agentcfg import lifecycle, resource_coordination, stop_locks, tool_maintenance as flow
from agentcfg.paths import PathError
from agentcfg.storage import Conflict, Tree
from test_rotom_tool_maintenance import BATCH, RUNS, workflow


def waiting_operation(store, operation, *, rejected=False):
  fd = os.open(store.registry.root, os.O_RDONLY | os.O_DIRECTORY)
  fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  started = threading.Event()
  def work():
    started.set()
    return operation()
  try:
    with ThreadPoolExecutor(max_workers=1) as pool:
      future = pool.submit(work)
      try:
        assert started.wait(timeout=1)
        with pytest.raises(TimeoutError):
          future.result(timeout=0.03)
      finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
      if rejected:
        with pytest.raises(Conflict):
          future.result(timeout=3)
        return None
      return future.result(timeout=3)
  finally:
    os.close(fd)


def test_read_waits_for_real_store_flock_then_reads_same_manifest(workflow):
  store = flow.Store(workflow.ws, BATCH)
  initial = store.begin(workflow.plan)
  assert waiting_operation(store, store.read) == initial


def setup_intent(store, plan):
  initial = store.begin(plan)
  return store.append(initial, "setup-intent", plan_id="a" * 64, deployment="b" * 64)


def restore_intent(store, plan):
  setup = setup_intent(store, plan)
  complete = store.complete_setup(setup, 0, deployment="b" * 64)
  return store.append(complete, "restore-intent", run_id=RUNS[0])


def payloads(store):
  return {path.name: path.read_bytes() for path in store.registry.root.iterdir() if path.is_file()}


def test_begin_waits_for_real_store_flock_before_publishing_manifest(workflow):
  store = flow.Store(workflow.ws, BATCH)
  store.registry.root.mkdir(mode=0o700, parents=True)
  saved = waiting_operation(store, lambda: store.begin(workflow.plan))
  assert saved["manifest"]["plan"] == workflow.plan and saved["revision"] == 0
  assert store.read() == saved


def test_append_waits_but_does_not_refresh_or_accept_stale_cas(workflow):
  store = flow.Store(workflow.ws, BATCH)
  initial = store.begin(workflow.plan)
  latest = store.append(initial, "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  before = payloads(store)
  waiting_operation(store, lambda: store.append(initial, "cancel"), rejected=True)
  assert store.read() == latest and payloads(store) == before


@pytest.mark.parametrize("same_run", [False, True])
def test_complete_waits_and_only_accepts_other_run_tail(workflow, same_run):
  store = flow.Store(workflow.ws, BATCH)
  intent = restore_intent(store, workflow.plan)
  if same_run:
    current = store.complete_restore(intent, RUNS[0], 17)
  else:
    current = store.append(intent, "restore-intent", run_id=RUNS[1])
  before = payloads(store)
  completed = waiting_operation(store, lambda: store.complete_restore(intent, RUNS[0], 0), rejected=same_run)
  if same_run:
    assert store.read() == current and payloads(store) == before
  else:
    assert completed["events"][:-1] == current["events"]
    assert completed["events"][-1]["run_id"] == RUNS[0]
    assert completed["events"][-1]["action"] == "restore-result"
    assert completed["events"][-1]["exit_code"] == 0


@pytest.mark.parametrize("external", [False, True])
def test_lock_wait_exhaustion_respects_earlier_external_deadline_and_writes_nothing(workflow,
    monkeypatch, external):
  base = flow.Store(workflow.ws, BATCH)
  initial = base.begin(workflow.plan)
  before = payloads(base)
  now, slept = [1_000_000_000], []
  elapsed = 7_000_000 if external else 2_000_000_000
  fd = os.open(base.registry.root, os.O_RDONLY | os.O_DIRECTORY)
  fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
  try:
    with monkeypatch.context() as patch:
      patch.setattr(stop_locks.time, "monotonic_ns", lambda: now[0])
      def sleep(seconds):
        slept.append(seconds)
        now[0] += round(seconds * 1_000_000_000)
      patch.setattr(stop_locks.time, "sleep", sleep)
      patch.setattr(Tree, "write_new", lambda *args, **kwargs: pytest.fail("expired Store wrote"))
      options = {"deadline_ns": now[0] + elapsed} if external else {}
      bounded = flow.Store(workflow.ws, BATCH, **options)
      with pytest.raises(Conflict):
        bounded.append(initial, "cancel")
      assert slept and now[0] == 1_000_000_000 + elapsed
      assert all(0 < seconds <= 0.01 for seconds in slept)
  finally:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)
  assert payloads(base) == before


@pytest.mark.parametrize("operation", ["begin", "append", "complete"])
@pytest.mark.parametrize("kind", [BlockingIOError, Conflict, PathError])
def test_post_write_failure_keeps_one_commit_without_busy_retry(workflow, monkeypatch, operation, kind):
  store = flow.Store(workflow.ws, BATCH)
  if operation == "begin":
    invoke, name, revision = lambda: store.begin(workflow.plan), "manifest.json", 0
  elif operation == "append":
    initial = store.begin(workflow.plan)
    invoke, name, revision = lambda: store.append(initial, "cancel"), "event-0001.json", 1
  else:
    intent = setup_intent(store, workflow.plan)
    invoke = lambda: store.complete_setup(intent, 0, deployment="b" * 64)
    name, revision = "event-0002.json", 2
  write, writes = Tree.write_new, []
  error = BlockingIOError(errno.EAGAIN, "synthetic-private-canary") if kind is BlockingIOError else kind("synthetic-private-canary")
  def lost(tree, target, *args, **kwargs):
    writes.append(target)
    write(tree, target, *args, **kwargs)
    raise error
  with monkeypatch.context() as patch:
    patch.setattr(Tree, "write_new", lost)
    patch.setattr(stop_locks.time, "sleep", lambda seconds: pytest.fail("Store body failure waited"))
    with pytest.raises(Conflict) as caught:
      invoke()
    assert "synthetic-private-canary" not in str(caught.value)
  assert writes == [name]
  assert store.read()["revision"] == revision


@pytest.mark.parametrize("kind", [BlockingIOError, Conflict, PathError])
def test_read_body_failure_is_not_reclassified_as_first_lock_contention(workflow, monkeypatch, kind):
  store = flow.Store(workflow.ws, BATCH)
  store.begin(workflow.plan)
  before = payloads(store)
  read, calls = store._read, []
  error = BlockingIOError(errno.EAGAIN, "synthetic-private-canary") if kind is BlockingIOError else kind("synthetic-private-canary")
  def lost(tree):
    calls.append(True)
    read(tree)
    raise error
  monkeypatch.setattr(store, "_read", lost)
  monkeypatch.setattr(stop_locks.time, "sleep", lambda seconds: pytest.fail("Store read body failure waited"))
  monkeypatch.setattr(Tree, "write_new", lambda *args, **kwargs: pytest.fail("Store read failure wrote"))
  with pytest.raises(Conflict) as caught:
    store.read()
  assert "synthetic-private-canary" not in str(caught.value)
  assert calls == [True] and payloads(store) == before


def test_missing_store_read_is_none_and_does_not_create_directories(workflow):
  store = flow.Store(workflow.ws, BATCH)
  assert store.read() is None
  assert not store.registry.root.exists()
  assert not store.registry.root.parent.exists()


def test_store_operations_acquire_only_their_own_metadata_lock(workflow, monkeypatch):
  store = flow.Store(workflow.ws, BATCH)
  store.registry.root.mkdir(mode=0o700, parents=True)
  root, flock, seen = store.registry.root.stat(), fcntl.flock, []
  def own_lock(fd, flags):
    info = os.fstat(fd)
    assert (info.st_dev, info.st_ino) == (root.st_dev, root.st_ino)
    seen.append(flags)
    return flock(fd, flags)
  def forbidden(*args, **kwargs):
    pytest.fail("Store acquired a Domain or physical operation guard")
  monkeypatch.setattr(fcntl, "flock", own_lock)
  monkeypatch.setattr(resource_coordination.Domain, "_transaction", forbidden)
  monkeypatch.setattr(lifecycle, "inactive_guard", forbidden)
  initial = store.begin(workflow.plan)
  assert store.read() == initial
  intent = store.append(initial, "setup-intent", plan_id="a" * 64, deployment="b" * 64)
  completed = store.complete_setup(intent, 0, deployment="b" * 64)
  assert completed["revision"] == 2
  assert seen and all(flags in (fcntl.LOCK_EX | fcntl.LOCK_NB, fcntl.LOCK_UN) for flags in seen)
