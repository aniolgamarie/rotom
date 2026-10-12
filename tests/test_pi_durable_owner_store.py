"""临时私人目录与合成进程/锁；不读取 /proc 或启动第三方。"""
from dataclasses import FrozenInstanceError, replace
import errno
import fcntl
import os
from pathlib import Path
import traceback

import pytest

from agentcfg import pi_durable_owner_store as owner
from agentcfg import storage
from agentcfg.pi_durable_owner_record import encode_owner_record


DEPLOYMENT = "a" * 64
SECRET = "SYNTHETIC_PRIVATE_OWNER_FAILURE"


@pytest.fixture(autouse=True)
def synthetic(monkeypatch):
  events = []
  class Processes:
    def __init__(self, root): events.append("process-constructor")
    def identity(self, pid):
      events.append("identity")
      return {"platform": "linux", "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
        "pid": pid, "ppid": 0, "pgid": pid, "start_time": "0", "namespace": "pid:[1]", "uid": os.geteuid()}
    def observe(self, expected): events.append("alive"); return "alive"
  def flock(fd, flags): events.append(("flock", flags))
  def epoch(count): events.append(("epoch", count)); return "b" * 64
  monkeypatch.setattr(owner, "LinuxProcesses", Processes)
  monkeypatch.setattr(owner.secrets, "token_hex", epoch)
  monkeypatch.setattr(fcntl, "flock", flock)
  yield events


@pytest.fixture
def root(): return Path(os.environ["HOME"]) / "owner"


def create(root): return owner.create_owner_record_scope(str(root), DEPLOYMENT)


def existing(root): return owner.open_owner_record_scope(str(root), DEPLOYMENT)


def invalid(call, kind=storage.Conflict):
  with pytest.raises(kind) as caught: call()
  error = caught.value
  assert type(error) is kind
  assert error.args == ("Durable所有者记录范围无效或需要恢复",)
  assert error.__context__ is None and error.__cause__ is None
  assert SECRET not in "".join(traceback.format_exception(error))
  return error


def enter(manager):
  with manager: pass


def seed(root):
  with create(root) as scope: return scope.observe()


def test_acquired_once_order_readback_immutable_and_retired(root, synthetic, monkeypatch):
  original = owner.Tree.write_new
  def write(tree, name, data): synthetic.append("write"); return original(tree, name, data)
  monkeypatch.setattr(owner.Tree, "write_new", write)
  with create(root) as scope:
    record = scope.observe()
    assert record.stage == "acquired" and record.writer is None and record.epoch == "b" * 64
    assert (record.storage_identity.device, record.storage_identity.inode) == (root.stat().st_dev, root.stat().st_ino)
    assert record.controller.pid == os.getpid() and record.controller.uid == os.geteuid()
    assert scope.observe() is record
    assert scope.writer_lock_verified is scope.database_allowed is scope.can_take_over is False
    assert not any(hasattr(scope, key) for key in ("fd", "tree", "write", "close"))
    with pytest.raises(FrozenInstanceError): scope._observe = None
  invalid(scope.observe)
  assert synthetic.count("identity") == 1 and synthetic.count(("epoch", 32)) == 1 and synthetic.count("write") == 1
  assert synthetic.index("identity") < synthetic.index("alive") < synthetic.index(("epoch", 32)) < synthetic.index("write")
  assert synthetic.count(("flock", fcntl.LOCK_EX | fcntl.LOCK_NB)) == 1
  assert not any(isinstance(e, tuple) and e[0] == "flock" and e[1] & fcntl.LOCK_UN for e in synthetic)
  assert (root / "owner.json").read_bytes() == encode_owner_record(record)
  assert (root / "owner.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_existing_path_never_reused_or_modified(root, kind, synthetic):
  if kind == "directory": root.mkdir(); (root / "sentinel").write_bytes(b"keep")
  elif kind == "file": root.write_bytes(b"keep")
  else: root.symlink_to(root.parent)
  before = root.lstat()
  invalid(lambda: enter(create(root)))
  assert root.lstat() == before and synthetic == []
  if kind == "directory": assert list(p.name for p in root.iterdir()) == ["sentinel"]


@pytest.mark.parametrize("root_value", [None, 1, "relative", "/", "/tmp//x", "/tmp/./x", "/tmp/../x", "/tmp/x/", "/tmp/\\x", "/tmp/\nx"])
def test_bad_literal_input_before_dependency(root_value, synthetic):
  invalid(lambda: enter(owner.create_owner_record_scope(root_value, DEPLOYMENT)))
  assert synthetic == []


def test_foreign_argument_hooks_never_called(root, synthetic):
  class Poison:
    def __fspath__(self): pytest.fail("fspath called")
    def __str__(self): pytest.fail("str called")
    def __repr__(self): pytest.fail("repr called")
    def __eq__(self, value): pytest.fail("eq called")
  invalid(lambda: enter(owner.create_owner_record_scope(Poison(), DEPLOYMENT)))
  invalid(lambda: enter(owner.create_owner_record_scope(str(root), Poison())))
  invalid(lambda: enter(owner.create_owner_record_scope(str(root), "A" * 64)))
  assert synthetic == [] and not root.exists()


@pytest.mark.parametrize("case", ["missing-parent", "unsafe-parent", "symlink-parent"])
def test_parent_is_existing_private_and_not_created(root, case, synthetic):
  parent = root.parent / "parent"
  if case == "unsafe-parent": parent.mkdir(mode=0o755); parent.chmod(0o755)
  if case == "symlink-parent": parent.symlink_to(root.parent)
  invalid(lambda: enter(create(parent / "new")))
  assert not (parent / "new").exists() and synthetic == []


def test_busy_leaves_new_directory_without_owner_or_epoch(root, synthetic, monkeypatch):
  def busy(fd, flags): raise BlockingIOError(errno.EAGAIN, SECRET)
  monkeypatch.setattr(fcntl, "flock", busy)
  invalid(lambda: enter(create(root)))
  assert root.is_dir() and not (root / "owner.json").exists()
  assert not any(isinstance(e, tuple) and e[0] == "epoch" for e in synthetic)
  invalid(lambda: enter(create(root)))


@pytest.mark.parametrize("problem", ["missing-directory", "missing-lock", "missing-owner"])
def test_existing_missing_is_zero_creation_or_current_identity(root, synthetic, problem):
  if problem != "missing-directory": root.mkdir(mode=0o700)
  if problem == "missing-owner": (root / "instance.lock").write_bytes(b""); (root / "instance.lock").chmod(0o600)
  before = sorted(p.name for p in root.iterdir()) if root.exists() else None
  invalid(lambda: enter(existing(root)))
  assert (sorted(p.name for p in root.iterdir()) if root.exists() else None) == before
  assert all(isinstance(e, tuple) and e[0] == "flock" for e in synthetic)


@pytest.mark.parametrize("stage,has_writer", [("acquired", False), ("bound", True), ("ready", True), ("closing", False), ("released", True)])
def test_existing_all_stages_are_only_read(root, synthetic, stage, has_writer):
  record = seed(root)
  writer = replace(record.controller, pid=record.controller.pid + 1) if has_writer else None
  record = replace(record, stage=stage, writer=writer)
  (root / "owner.json").write_bytes(encode_owner_record(record))
  before = (root / "owner.json").read_bytes(); synthetic.clear()
  with existing(root) as scope:
    assert scope.observe() == record and scope.database_allowed is False
  assert (root / "owner.json").read_bytes() == before
  assert synthetic == [("flock", fcntl.LOCK_EX | fcntl.LOCK_NB)]


@pytest.mark.parametrize("problem", ["lock-replace", "root-replace", "owner-replace", "owner-content", "owner-permission", "owner-missing", "tree-method"])
def test_observe_drift_permanently_retires_zero_writes(root, problem, monkeypatch):
  with create(root) as scope:
    if problem == "lock-replace": (root / "instance.lock").unlink(); (root / "instance.lock").write_bytes(b"")
    elif problem == "root-replace": root.rename(root.with_name("old")); root.mkdir(mode=0o700)
    elif problem == "owner-replace":
      data = (root / "owner.json").read_bytes(); (root / "owner.json").unlink(); (root / "owner.json").write_bytes(data)
    elif problem == "owner-content": (root / "owner.json").write_bytes(b"bad")
    elif problem == "owner-permission": (root / "owner.json").chmod(0o644)
    elif problem == "owner-missing": (root / "owner.json").unlink()
    else: monkeypatch.setattr(owner.Tree, "read", lambda *a, **k: pytest.fail("drift method called"))
    invalid(scope.observe)
    invalid(scope.observe)
  assert not (root / "owner.json").exists() or b"released" not in (root / "owner.json").read_bytes()


@pytest.mark.parametrize("phase", ["identity-pid", "identity-uid", "observer-unknown", "last-observer-drift", "write-ack", "post-read"])
def test_failure_cutpoints_never_rewrite_or_regenerate(root, synthetic, monkeypatch, phase):
  processes = owner.LinuxProcesses
  original_identity, original_observe = processes.identity, processes.observe
  original_write, original_read = owner.Tree.write_new, owner.Tree.read
  writes = []
  def write(tree, name, data):
    writes.append(data); original_write(tree, name, data)
    if phase == "write-ack": raise OSError(SECRET)
  monkeypatch.setattr(owner.Tree, "write_new", write)
  if phase.startswith("identity-"):
    def identity(self, pid):
      value = original_identity(self, pid); value["pid" if phase.endswith("pid") else "uid"] += 1; return value
    monkeypatch.setattr(processes, "identity", identity)
  if phase == "observer-unknown": monkeypatch.setattr(processes, "observe", lambda *a: "unknown")
  if phase == "last-observer-drift":
    count = []
    def observe(self, expected):
      count.append(1)
      if len(count) == 2: monkeypatch.setattr(owner.Tree, "read", lambda *a, **k: pytest.fail("changed read called"))
      return original_observe(self, expected)
    monkeypatch.setattr(processes, "observe", observe)
  if phase == "post-read":
    def read(tree, name, **kw):
      if writes: raise OSError(SECRET)
      return original_read(tree, name, **kw)
    monkeypatch.setattr(owner.Tree, "read", read)
  invalid(lambda: enter(create(root)), storage.StateError if phase in ("write-ack", "post-read") else storage.Conflict)
  assert len(writes) == (1 if phase in ("last-observer-drift", "write-ack", "post-read") else 0)
  assert synthetic.count(("epoch", 32)) <= 1
  invalid(lambda: enter(create(root)))


def test_tree_birth_binding_rejects_other_directory(root, monkeypatch):
  other = root.parent / "other"; other.mkdir(mode=0o700)
  original = owner.Tree.__init__
  def init(tree, path, **kwargs): original(tree, other, **kwargs); tree.root = path
  monkeypatch.setattr(owner.Tree, "__init__", init)
  invalid(lambda: enter(create(root)))
  assert not (root / "instance.lock").exists() and not (other / "instance.lock").exists()


def test_foreign_tree_fd_not_closed_on_drift(root, monkeypatch):
  original = owner.Tree.__init__; trees = []
  def init(tree, path, **kwargs): original(tree, path, **kwargs); trees.append(tree)
  monkeypatch.setattr(owner.Tree, "__init__", init)
  foreign = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY)
  try:
    with create(root) as scope:
      tree = trees[0]; own_fd = tree.fd; tree.fd = foreign
      invalid(scope.observe)
    os.fstat(foreign)
    with pytest.raises(OSError): os.fstat(own_fd)
    assert tree.fd == foreign
  finally: os.close(foreign)


def test_body_exception_unchanged_even_cleanup_fails(root, monkeypatch):
  original_close = owner.Tree.close
  def broken_close(tree): original_close(tree); raise OSError(SECRET)
  monkeypatch.setattr(owner.Tree, "close", broken_close)
  body = OSError("OWN_BODY_SECRET")
  with pytest.raises(OSError) as caught:
    with create(root) as scope: raise body
  assert caught.value is body and body.args == ("OWN_BODY_SECRET",)
  invalid(scope.observe)
  assert b"acquired" in (root / "owner.json").read_bytes()


def test_cleanup_failure_without_primary_fixed_stateerror(root, monkeypatch):
  original_close = owner.Tree.close
  def broken_close(tree): original_close(tree); raise OSError(SECRET)
  monkeypatch.setattr(owner.Tree, "close", broken_close)
  invalid(lambda: enter(create(root)), storage.StateError)
  assert b"acquired" in (root / "owner.json").read_bytes()


def test_ambient_caller_error_does_not_enter_own_error(root):
  try: raise RuntimeError(SECRET)
  except RuntimeError as original:
    invalid(lambda: enter(existing(root)))
    assert original.args == (SECRET,) and original.__context__ is None


def test_existing_shared_lock_flags_no_create_nonblock_and_exact_bool(root, monkeypatch):
  root.mkdir(mode=0o700)
  calls = []; original_open = os.open
  def opened(path, flags, *args, **kwargs):
    if path == "instance.lock": calls.append(flags)
    return original_open(path, flags, *args, **kwargs)
  monkeypatch.setattr(os, "open", opened)
  with storage.Tree(root, create=False) as tree:
    with pytest.raises(FileNotFoundError):
      with storage.instance_lock(tree, create=False): pass
    assert not (root / "instance.lock").exists()
    with storage.instance_lock(tree): pass
    with storage.instance_lock(tree, create=False): pass
    with pytest.raises(storage.Conflict):
      with storage.instance_lock(tree, create=1): pass
  assert not calls[0] & os.O_CREAT and calls[0] & os.O_NONBLOCK
  assert calls[1] & os.O_CREAT and not calls[2] & os.O_CREAT


def test_directory_and_parent_fsync_precede_lock_and_owner_publication(root, synthetic, monkeypatch):
  original_sync = os.fsync
  def sync(fd): synthetic.append("fsync"); original_sync(fd)
  monkeypatch.setattr(os, "fsync", sync)
  with create(root): pass
  lock = synthetic.index(("flock", fcntl.LOCK_EX | fcntl.LOCK_NB))
  assert synthetic[:lock].count("fsync") == 2
  assert synthetic[lock:].count("fsync") >= 2


@pytest.mark.parametrize("problem", ["lock-symlink", "lock-hardlink", "lock-mode", "owner-hardlink", "deployment", "storage"])
def test_existing_unsafe_records_and_files_fail_without_repair(root, problem, synthetic):
  record = seed(root)
  if problem == "lock-symlink": (root / "instance.lock").unlink(); (root / "instance.lock").symlink_to(root / "owner.json")
  elif problem == "lock-hardlink": os.link(root / "instance.lock", root / "alias")
  elif problem == "lock-mode": (root / "instance.lock").chmod(0o644)
  elif problem == "owner-hardlink": os.link(root / "owner.json", root / "alias")
  elif problem == "deployment": (root / "owner.json").write_bytes(encode_owner_record(replace(record, deployment_identity="c" * 64)))
  else:
    identity = replace(record.storage_identity, inode=record.storage_identity.inode + 1)
    (root / "owner.json").write_bytes(encode_owner_record(replace(record, storage_identity=identity)))
  before = (root / "owner.json").read_bytes(); synthetic.clear()
  invalid(lambda: enter(existing(root)))
  assert (root / "owner.json").read_bytes() == before
  assert "identity" not in synthetic and ("epoch", 32) not in synthetic


def test_read_callback_source_drift_cannot_return_valid_record(root, monkeypatch):
  original = owner.Tree.read
  active = []
  def read(tree, name, **kwargs):
    result = original(tree, name, **kwargs)
    if active: monkeypatch.setattr(owner, "instance_lock", lambda *a, **k: pytest.fail("new lock used"))
    return result
  monkeypatch.setattr(owner.Tree, "read", read)
  with create(root) as scope:
    active.append(True)
    invalid(scope.observe)
    active.clear()
    invalid(scope.observe)


def test_initialization_primary_survives_cleanup_failure(root, monkeypatch):
  original_write, original_close = owner.Tree.write_new, owner.Tree.close
  def write(tree, name, data): original_write(tree, name, data); raise OSError(SECRET)
  def close(tree): original_close(tree); raise OSError("SECONDARY_SECRET")
  monkeypatch.setattr(owner.Tree, "write_new", write)
  monkeypatch.setattr(owner.Tree, "close", close)
  invalid(lambda: enter(create(root)), storage.StateError)
  assert b"acquired" in (root / "owner.json").read_bytes()


def test_existing_never_calls_write_identity_epoch_or_mkdir(root, monkeypatch):
  seed(root)
  def forbidden(*args, **kwargs): pytest.fail("readonly called mutation/current identity")
  monkeypatch.setattr(owner.Tree, "write_new", forbidden)
  monkeypatch.setattr(owner.LinuxProcesses, "identity", forbidden)
  monkeypatch.setattr(owner.secrets, "token_hex", forbidden)
  monkeypatch.setattr(os, "mkdir", forbidden)
  with existing(root) as scope: assert scope.observe().stage == "acquired"


def test_no_creation_on_non_linux(root, monkeypatch, synthetic):
  monkeypatch.setattr(owner.sys, "platform", "darwin")
  invalid(lambda: enter(create(root)))
  assert not root.exists() and synthetic == []


def test_observer_cannot_mutate_selected_self_identity(root, monkeypatch, synthetic):
  def observe(self, expected): expected["pid"] += 1; return "alive"
  monkeypatch.setattr(owner.LinuxProcesses, "observe", observe)
  invalid(lambda: enter(create(root)))
  assert not (root / "owner.json").exists() and ("epoch", 32) not in synthetic


@pytest.fixture
def allocated_directory_fds(monkeypatch):
  # 只记录自有测试调用实际取得的 fd，不枚举 /proc 或其他进程句柄。
  allocated, active, closes = [], set(), []
  original_dup, original_open_directory, original_close = os.dup, owner._open_directory, os.close
  def remember(fd): allocated.append(fd); active.add(fd); return fd
  def duplicate(fd): return remember(original_dup(fd))
  def opened(parent, name): return remember(original_open_directory(parent, name))
  def close(fd):
    if fd in active:
      closes.append(fd); active.remove(fd)
    return original_close(fd)
  monkeypatch.setattr(os, "dup", duplicate)
  monkeypatch.setattr(owner, "_open_directory", opened)
  monkeypatch.setattr(os, "close", close)
  try:
    yield allocated, active, closes
  finally:
    # 旧源码行为红也要关本测试 spy 已确认的泄漏，避免污染后续 pytest。
    for fd in tuple(active):
      try: original_close(fd)
      except OSError: pass


def assert_all_owned_fds_closed(receipts):
  allocated, active, closes = receipts
  assert allocated
  for fd in set(allocated):
    with pytest.raises(OSError) as caught: os.fstat(fd)
    assert caught.value.errno == errno.EBADF
  assert not active and len(closes) == len(allocated)


def test_initial_active_0755_rejected_but_owned_duplicate_closed(root, allocated_directory_fds, synthetic):
  root.mkdir(mode=0o755); root.chmod(0o755)
  invalid(lambda: enter(existing(root)))
  assert_all_owned_fds_closed(allocated_directory_fds)
  assert synthetic == [] and list(root.iterdir()) == []


def test_chmod_after_acquired_retires_and_closes_original_handles(root, allocated_directory_fds, monkeypatch):
  writes = []; original_write = owner.Tree.write_new
  def write(tree, name, data): writes.append(data); return original_write(tree, name, data)
  monkeypatch.setattr(owner.Tree, "write_new", write)
  with create(root) as scope:
    data = (root / "owner.json").read_bytes()
    root.chmod(0o755)
    invalid(scope.observe)
  assert_all_owned_fds_closed(allocated_directory_fds)
  assert len(writes) == 1 and (root / "owner.json").read_bytes() == data
  assert b"released" not in data


@pytest.mark.parametrize("different_physical_directory", [False, True])
def test_early_tree_unsafe_directory_closes_all_owned_handles(root, allocated_directory_fds, monkeypatch, different_physical_directory):
  other = root.parent / "other"
  if different_physical_directory: other.mkdir(mode=0o700)
  original = owner.Tree.__init__
  def init(tree, path, **kwargs):
    selected = other if different_physical_directory else path
    original(tree, selected, **kwargs)
    tree.root = path
    selected.chmod(0o755)
  monkeypatch.setattr(owner.Tree, "__init__", init)
  invalid(lambda: enter(create(root)))
  assert_all_owned_fds_closed(allocated_directory_fds)
  assert not (root / "owner.json").exists() and not (root / "instance.lock").exists()
  if different_physical_directory: assert list(other.iterdir()) == []


def test_parent_producer_explicit_exit_when_consumer_cleanup_fstat_unknown(root, monkeypatch):
  original_cm, original_fstat = owner._absolute_directory, os.fstat
  retained, events, parent_fds, cleanup = [], [], [], []
  class ParentProducer:
    def __init__(self, path):
      self.original = original_cm(path)
      self.exited = False
      retained.append(self)
    def __enter__(self):
      fd = self.original.__enter__()
      parent_fds.append(fd); events.append("enter")
      return fd
    def __exit__(self, *exc):
      events.append("exit"); self.exited = True
      return self.original.__exit__(*exc)
  def directory(path):
    return ParentProducer(path) if path == root.parent else original_cm(path)
  def fstat(fd):
    if cleanup and fd in parent_fds: raise OSError(SECRET)
    return original_fstat(fd)
  monkeypatch.setattr(owner, "_absolute_directory", directory)
  monkeypatch.setattr(os, "fstat", fstat)
  try:
    with create(root): cleanup.append(True)
    assert events == ["enter", "exit"]
    for fd in parent_fds:
      with pytest.raises(OSError) as caught: original_fstat(fd)
      assert caught.value.errno == errno.EBADF
    assert b"acquired" in (root / "owner.json").read_bytes()
  finally:
    # 保留原 producer 防止 GC 掩盖旧源码漏 exit；失败后由测试显式退出。
    for producer in retained:
      if not producer.exited: producer.__exit__(None, None, None)
