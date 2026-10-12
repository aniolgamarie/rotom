"""七个自有合成 wheel 的真实临时 FD 验证；不执行 wheel 正文。"""

import builtins
import copy
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import zipfile

import pytest

from agentcfg import pi_python_bundle as bundle
from agentcfg import pi_python_bundle_stage as stage
from test_pi_python_bundle import _fixture, _finish, _rebuild


_OWNER = (os.getuid(), os.geteuid(), os.getgid(), os.getegid())


@pytest.fixture(autouse=True)
def original_owner_and_offline(offline_guards, isolated_environment):
  assert _OWNER[0] != 0 and _OWNER[0] == _OWNER[1]
  assert (os.getuid(), os.geteuid(), os.getgid(), os.getegid()) == _OWNER
  assert Path(os.environ["HOME"]).is_relative_to(isolated_environment.root)
  with pytest.raises(RuntimeError, match="test network disabled"):
    socket.socket()


@pytest.fixture
def scratch(tmp_path):
  root = tmp_path / "stage"
  root.mkdir(mode=0o700)
  supervisor = root / "supervisor"
  supervisor.mkdir(mode=0o750)
  supervisor.chmod(0o750)
  (root / "sentinel").write_bytes(b"stage unchanged")
  (supervisor / "sentinel").write_bytes(b"supervisor unchanged")
  borrowed = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
  before = [(path, path.stat().st_ino, path.read_bytes(), path.stat().st_mode)
            for path in (root / "sentinel", supervisor / "sentinel")]
  yield root, supervisor, borrowed
  assert os.fstat(borrowed).st_ino == root.stat().st_ino
  os.close(borrowed)
  assert supervisor.stat().st_mode & 0o7777 == 0o750
  for path, inode, raw, mode in before:
    assert (path.stat().st_ino, path.read_bytes(), path.stat().st_mode) == (inode, raw, mode)


def _call(scratch, declaration=None, artifacts=None, occupied=None):
  if declaration is None:
    declaration, artifacts, _ = _fixture()
  return stage.install_python_bundle_stage(scratch[2], declaration, artifacts,
                                           occupied_files=[] if occupied is None else occupied)


def _reject(scratch, declaration=None, artifacts=None, occupied=None):
  with pytest.raises(ValueError) as caught:
    _call(scratch, declaration, artifacts, occupied)
  assert str(caught.value) == "pi-python-bundle-stage"
  assert caught.value.__cause__ is None
  assert caught.value.__context__ is None
  assert os.fstat(scratch[2]).st_ino == scratch[0].stat().st_ino
  return caught.value


@pytest.mark.parametrize("method", [0, 8])
@pytest.mark.parametrize("large", [False, True])
def test_complete_bytes_modes_sets_canonical_and_no_execution(scratch, monkeypatch, method, large):
  declaration, artifacts, originals = _fixture(method)
  if large:
    # 固定伪随机正文避免 deflate 比率上限；从不加载这个合成 .so。
    payload = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(33000))
    def transform(files, row):
      member = next(path for path in files if path.endswith(".so"))
      files[member] = payload
    _rebuild(declaration, artifacts, originals, 3, transform=transform, method=method)
  plan = bundle.plan_python_bundle_install(declaration, artifacts, occupied_files=[])
  before = copy.deepcopy((declaration, artifacts))
  # stdlib ZipFile 的公开读取会按需载入 CP437；先完成编解码器初始化。
  b"ascii".decode("cp437")
  with monkeypatch.context() as patch:
    def prohibited(*args, **kwargs): raise AssertionError("candidate execution attempted")
    patch.setattr(zipfile.ZipFile, "extract", prohibited)
    patch.setattr(zipfile.ZipFile, "extractall", prohibited)
    patch.setattr(os, "chdir", prohibited)
    patch.setattr(Path, "resolve", prohibited)
    patch.setattr(builtins, "__import__", prohibited)
    assert _call(scratch, declaration, artifacts) is None
  assert (declaration, artifacts) == before
  prefix = scratch[1] / "python-bundle"
  observed_files = set()
  observed_dirs = {"supervisor/python-bundle"}
  for path in prefix.rglob("*"):
    target = str(path.relative_to(scratch[0]))
    info = path.lstat()
    assert info.st_uid == os.geteuid() and info.st_dev == scratch[0].stat().st_dev
    if path.is_dir():
      observed_dirs.add(target)
      assert stat.S_IMODE(info.st_mode) == 0o700
    else:
      observed_files.add(target)
      assert stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
  assert observed_dirs == {row["target"] for row in plan["directories"]}
  assert observed_files == {row["target"] for row in plan["files"]} | {plan["inventory_path"]}
  for row in plan["files"]:
    owner = next(wheel["name"] for wheel in declaration["wheels"] if wheel["source_id"] == row["source_id"])
    assert (scratch[0] / row["target"]).read_bytes() == originals[owner][row["member"]]
  canonical = json.dumps(plan["inventory_template"], sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode()
  assert (scratch[0] / plan["inventory_path"]).read_bytes() == canonical


@pytest.mark.parametrize("fault", ["unknown", "hash", "record", "path", "occupied", "directory-occupied"])
def test_data_failures_before_prefix(scratch, fault):
  declaration, artifacts, originals = _fixture()
  occupied = []
  if fault == "unknown": declaration["unknown"] = True
  if fault == "hash": declaration["wheels"][0]["archive_sha256"] = "0" * 64
  if fault == "record":
    def transform(files, row): files[row["dist_info"] + "/RECORD"] = b"bad,record,data\n"
    _rebuild(declaration, artifacts, originals, 0, transform=transform, regenerate_record=False)
  if fault == "path": declaration["wheels"][0]["members"][0]["path"] = "../escape"
  if fault == "occupied": occupied = [{"kind": "file", "path": "supervisor/python-bundle/other"}]
  if fault == "directory-occupied": occupied = [{"kind": "directory", "path": "supervisor"}]
  _reject(scratch, declaration, artifacts, occupied)
  assert not (scratch[1] / "python-bundle").exists()


class _Foreign(dict):
  calls = 0
  def _callback(self, *args, **kwargs):
    type(self).calls += 1
    raise AssertionError("foreign callback")
  __iter__ = items = __len__ = __repr__ = __deepcopy__ = _callback


class _ForeignList(list):
  def __iter__(self): raise AssertionError("foreign iterator")
  def __len__(self): raise AssertionError("foreign length")


class _ForeignString(str):
  calls = 0
  def __hash__(self):
    type(self).calls += 1
    return super().__hash__()
  def __repr__(self):
    type(self).calls += 1
    return "foreign"


@pytest.mark.parametrize("fault", ["dict", "list", "nested", "key", "artifact", "artifact-key", "bytes", "cycle", "depth", "nodes", "string", "utf8", "integer", "artifact-count", "archive-cap", "set-cap"])
def test_snapshots_closed_and_bounded_before_planner(scratch, monkeypatch, fault):
  declaration, artifacts, _ = _fixture()
  occupied = []
  if fault == "dict": declaration = _Foreign()
  if fault == "list": occupied = _ForeignList()
  if fault == "nested": declaration["unknown"] = _Foreign()
  if fault == "key":
    declaration[_ForeignString("unknown")] = 1
    _ForeignString.calls = 0
  if fault == "artifact": artifacts = _Foreign()
  if fault == "artifact-key":
    raw = artifacts.pop(next(iter(artifacts)))
    artifacts[_ForeignString("unknown")] = raw
    _ForeignString.calls = 0
  if fault == "bytes": artifacts[next(iter(artifacts))] = bytearray(b"x")
  if fault == "cycle": declaration["unknown"] = declaration
  if fault == "depth":
    nested = []
    for _ in range(17): nested = [nested]
    declaration["unknown"] = nested
  if fault == "nodes": occupied = [None] * 100000
  if fault == "string": declaration["unknown"] = "x" * 4097
  if fault == "utf8": declaration["unknown"] = "\ud800"
  if fault == "integer": declaration["unknown"] = 2 ** 63
  if fault == "artifact-count": artifacts.clear()
  if fault == "archive-cap": artifacts[next(iter(artifacts))] = b"x" * 2097153
  if fault == "set-cap": artifacts = {str(i): b"x" * 2097152 for i in range(7)}
  calls = []
  monkeypatch.setattr(stage, "plan_python_bundle_install", lambda *args, **kwargs: calls.append(1))
  _reject(scratch, declaration, artifacts, occupied)
  assert calls == [] and _Foreign.calls == 0 and _ForeignString.calls == 0
  assert not (scratch[1] / "python-bundle").exists()


def test_snapshot_detaches_before_original_public_planner(scratch, monkeypatch):
  declaration, artifacts, originals = _fixture()
  occupied = []
  original = stage.plan_python_bundle_install
  def planner(local_declaration, local_artifacts, *, occupied_files):
    assert local_declaration is not declaration and local_artifacts is not artifacts and occupied_files is not occupied
    assert local_artifacts[next(iter(local_artifacts))] is artifacts[next(iter(artifacts))]
    declaration.clear()
    artifacts.clear()
    occupied.append(_Foreign())
    return original(local_declaration, local_artifacts, occupied_files=occupied_files)
  monkeypatch.setattr(stage, "plan_python_bundle_install", planner)
  _call(scratch, declaration, artifacts, occupied)
  assert (scratch[1] / "python-bundle/site-packages/attr/__init__.py").read_bytes() == originals["attrs"]["attr/__init__.py"]


@pytest.mark.parametrize("bad", [True, False, -1, 2147483648, 1.0, None, "1"])
def test_bad_fd_types(scratch, bad):
  with pytest.raises(ValueError, match="^pi-python-bundle-stage$"):
    declaration, artifacts, _ = _fixture()
    stage.install_python_bundle_stage(bad, declaration, artifacts, occupied_files=[])
  assert not (scratch[1] / "python-bundle").exists()


@pytest.mark.parametrize("fault", ["closed", "file", "owner", "mode", "special-mode", "missing", "link", "supervisor-mode", "alias", "duplicate", "prefix", "prefix-link", "prefix-alias"])
def test_physical_preconditions(scratch, monkeypatch, tmp_path, fault):
  root, supervisor, borrowed = scratch
  invalid_fd = None
  if fault == "closed":
    invalid_fd = os.dup(borrowed)
    os.close(invalid_fd)
  if fault == "file": invalid_fd = os.open(root / "sentinel", os.O_RDONLY)
  if fault == "owner": monkeypatch.setattr(stage.os, "geteuid", lambda: _OWNER[1] + 1)
  if fault in ("mode", "special-mode"): root.chmod(0o750 if fault == "mode" else 0o1700)
  if fault in ("missing", "link", "alias"):
    supervisor.rename(root / "saved")
    if fault == "link": (root / "supervisor").symlink_to(root / "saved", target_is_directory=True)
    if fault == "alias": (root / "Supervisor").mkdir()
  if fault == "supervisor-mode": supervisor.chmod(0o770)
  if fault == "duplicate": (root / "Supervisor").mkdir()
  if fault == "prefix": (supervisor / "python-bundle").mkdir()
  if fault == "prefix-link": (supervisor / "python-bundle").symlink_to(root, target_is_directory=True)
  if fault == "prefix-alias": (supervisor / "Python-Bundle").mkdir()
  try:
    _reject((root, supervisor, invalid_fd if invalid_fd is not None else borrowed)) if fault not in ("closed", "file") else _reject_invalid(invalid_fd)
  finally:
    if fault == "file": os.close(invalid_fd)
    root.chmod(0o700)
    if fault == "supervisor-mode": supervisor.chmod(0o750)
    if fault in ("missing", "link", "alias"):
      if fault == "link": (root / "supervisor").unlink()
      if fault == "alias": (root / "Supervisor").rmdir()
      (root / "saved").rename(supervisor)


def _reject_invalid(fd):
  declaration, artifacts, _ = _fixture()
  with pytest.raises(ValueError, match="^pi-python-bundle-stage$"):
    stage.install_python_bundle_stage(fd, declaration, artifacts, occupied_files=[])


def test_short_writes_are_completed(scratch, monkeypatch):
  original = os.write
  calls = []
  def short(fd, raw):
    calls.append(len(raw))
    return original(fd, raw[:7])
  monkeypatch.setattr(stage.os, "write", short)
  _call(scratch)
  assert len(calls) > 1000


class _Events:
  """按获取事件配对；同一个整数重复使用仍是不同 acquisition。"""
  def __init__(self, patch):
    self.events = []
    self.live = {}
    self.close_fault = None
    self.real_close = os.close
    for name in ("open", "dup"):
      original = getattr(os, name)
      def acquire(*args, _name=name, _original=original, **kwargs):
        fd = _original(*args, **kwargs)
        event = {"fd": fd, "operation": _name, "attempts": 0, "closed": False}
        self.events.append(event)
        assert fd not in self.live
        self.live[fd] = event
        return fd
      patch.setattr(stage.os, name, acquire)
    def close(fd):
      event = self.live.pop(fd)
      event["attempts"] += 1
      if self.close_fault is not None:
        error = self.close_fault(event)
        if error is not None:
          # 故意不假称内核已关闭；测试 finally 另用 real_close 回收泄漏。
          event["ambiguous"] = True
          raise error
      self.real_close(fd)
      event["closed"] = True
    patch.setattr(stage.os, "close", close)

  def finish(self):
    assert self.live == {}
    assert all(event["attempts"] == 1 for event in self.events)
    for event in self.events:
      if event.get("ambiguous"):
        self.real_close(event["fd"])


@pytest.mark.parametrize("operation", ["dup", "open", "mkdir", "fchmod", "write", "read", "fsync"])
@pytest.mark.parametrize("position", [1, 3])
def test_io_faults_no_success_and_every_owned_close(scratch, monkeypatch, operation, position):
  with monkeypatch.context() as patch:
    events = _Events(patch)
    original = getattr(os, operation)
    calls = 0
    def broken(*args, **kwargs):
      nonlocal calls
      calls += 1
      if calls == position or operation == "dup": raise OSError("private payload")
      return original(*args, **kwargs)
    patch.setattr(stage.os, operation, broken)
    _reject(scratch)
    events.finish()
  assert calls >= position or operation == "dup"


def test_zero_write_keeps_partial_prefix(scratch, monkeypatch):
  monkeypatch.setattr(stage.os, "write", lambda *args: 0)
  _reject(scratch)
  assert (scratch[1] / "python-bundle").is_dir()
  assert not (scratch[1] / "python-bundle/inventory.json").exists()


@pytest.mark.parametrize("body_kind,cleanup_kind", [("control", "ordinary"), ("ordinary", "control"), ("control", "control"), ("ordinary", "ordinary"), ("none", "control"), ("none", "ordinary")])
@pytest.mark.parametrize("control_type", [KeyboardInterrupt, SystemExit])
def test_cleanup_exception_priority_and_continues(scratch, monkeypatch, body_kind, cleanup_kind, control_type):
  body = control_type("body") if body_kind == "control" else OSError("body")
  control = control_type("first cleanup")
  with monkeypatch.context() as patch:
    events = _Events(patch)
    close_errors = []
    def close_fault(event):
      error = control if cleanup_kind == "control" and not close_errors else OSError("cleanup")
      close_errors.append(error)
      return error
    events.close_fault = close_fault
    if body_kind != "none":
      def broken(*args): raise body
      patch.setattr(stage.os, "write", broken)
    expected = body if body_kind == "control" else control if cleanup_kind == "control" else None
    try:
      if expected is None:
        _reject(scratch)
      else:
        with pytest.raises(control_type) as caught: _call(scratch)
        assert caught.value is expected
    finally:
      events.finish()
    assert len(close_errors) >= 4
    assert not (scratch[1] / "python-bundle/inventory.json").exists()


def test_outer_exception_is_not_mutated(scratch):
  outer = RuntimeError("outer private")
  cause = LookupError("outer cause")
  outer.__cause__ = cause
  try:
    raise outer
  except RuntimeError:
    error = _reject(scratch, {}, {})
    assert error is not outer
    assert outer.__cause__ is cause and outer.__context__ is None


@pytest.mark.parametrize("fault", ["extra", "missing", "alias", "symlink", "hardlink", "file-mode", "file-identity", "directory-mode", "directory-identity", "prefix-identity", "size", "bytes"])
def test_readback_rejects_created_tree_drift(scratch, monkeypatch, fault):
  original = stage._read_tree
  altered = False
  prefix = scratch[1] / "python-bundle"
  def mutate(*args, **kwargs):
    nonlocal altered
    if not altered:
      altered = True
      target = prefix / "site-packages/attr/__init__.py"
      directory = prefix / "site-packages/attr"
      if fault == "extra": (prefix / "extra").write_bytes(b"x")
      if fault == "missing": target.unlink()
      if fault == "alias": (prefix / "Site-Packages").mkdir()
      if fault == "symlink":
        target.unlink()
        target.symlink_to(scratch[0] / "sentinel")
      if fault == "hardlink": os.link(target, prefix / "hardlink")
      if fault == "file-mode": target.chmod(0o640)
      if fault == "file-identity":
        raw = target.read_bytes()
        target.rename(prefix / "saved")
        target.write_bytes(raw)
        target.chmod(0o600)
        (prefix / "saved").unlink()
      if fault == "directory-mode": directory.chmod(0o750)
      if fault == "directory-identity":
        directory.rename(prefix / "saved")
        directory.mkdir(mode=0o700)
        (prefix / "saved/__init__.py").rename(directory / "__init__.py")
        (prefix / "saved/data").rename(directory / "data")
        (prefix / "saved").rmdir()
      if fault == "prefix-identity":
        prefix.rename(scratch[1] / "saved")
        prefix.mkdir(mode=0o700)
      if fault == "size": target.write_bytes(b"short")
      if fault == "bytes": target.write_bytes(b"x" * target.stat().st_size)
    return original(*args, **kwargs)
  monkeypatch.setattr(stage, "_read_tree", mutate)
  _reject(scratch)
  assert altered


@pytest.mark.parametrize("fault", ["identity", "mode", "size", "bytes", "hardlink"])
def test_inventory_drift_rejected(scratch, monkeypatch, fault):
  original = stage._read_file
  def read(cleanup, fd, name, path, *args):
    if name == "inventory.json":
      target = scratch[1] / "python-bundle/inventory.json"
      if fault == "identity":
        raw = target.read_bytes()
        saved = target.with_name("saved")
        target.rename(saved)
        target.write_bytes(raw)
        target.chmod(0o600)
        saved.unlink()
      if fault == "mode": target.chmod(0o640)
      if fault == "size": target.write_bytes(b"short")
      if fault == "bytes": target.write_bytes(b"x" * target.stat().st_size)
      if fault == "hardlink": os.link(target, target.with_name("hardlink"))
    return original(cleanup, fd, name, path, *args)
  monkeypatch.setattr(stage, "_read_file", read)
  _reject(scratch)


@pytest.mark.parametrize("field", ["st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns", "st_dev"])
def test_same_fd_readback_stability(scratch, monkeypatch, field):
  original = os.fstat
  counts = {}
  def fstat(fd):
    info = original(fd)
    if stat.S_ISREG(info.st_mode):
      counts[fd] = counts.get(fd, 0) + 1
      # 写时两次 fstat；readback 重新取得同数 FD 时可能累积，依据读标志另追踪。
      if reading[0] and counts[fd] % 2 == 0:
        from types import SimpleNamespace
        values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        values[field] += 1
        return SimpleNamespace(**values)
    return info
  reading = [False]
  original_read = os.read
  def read(*args):
    reading[0] = True
    return original_read(*args)
  monkeypatch.setattr(stage.os, "fstat", fstat)
  monkeypatch.setattr(stage.os, "read", read)
  _reject(scratch)


@pytest.mark.parametrize("where", ["stage", "supervisor"])
def test_bounded_physical_scan(scratch, monkeypatch, where):
  fd = scratch[2] if where == "stage" else os.open(scratch[1], os.O_RDONLY | os.O_DIRECTORY)
  try:
    for index in range(4097):
      descriptor = os.open("bounded-" + str(index), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
      os.close(descriptor)
    _reject(scratch)
    assert not (scratch[1] / "python-bundle").exists()
  finally:
    if where == "supervisor": os.close(fd)


def test_acquisition_events_cover_reused_numbers_on_success(scratch, monkeypatch):
  with monkeypatch.context() as patch:
    events = _Events(patch)
    _call(scratch)
    events.finish()
    assert len(events.events) > len({event["fd"] for event in events.events})


@pytest.mark.parametrize("value", [-(2 ** 63), 2 ** 63 - 1, "x" * 4096, [None] * 99999])
def test_snapshot_exact_boundaries(value):
  assert stage._snapshot(value) == value
  nested = None
  for _ in range(16): nested = [nested]
  assert stage._snapshot(nested) == nested


def test_relative_held_fd_operations_and_bounded_streams(scratch, monkeypatch):
  with monkeypatch.context() as patch:
    events = _Events(patch)
    open_original = os.open
    mkdir_original = os.mkdir
    read_original = os.read
    write_original = os.write
    observed = []
    def opened(path, flags, *args, **kwargs):
      assert type(path) is str and "/" not in path and not os.path.isabs(path)
      assert kwargs["dir_fd"] in events.live
      assert flags & os.O_NOFOLLOW and flags & os.O_CLOEXEC
      if flags & os.O_CREAT:
        assert flags & os.O_EXCL and args == (0o600,)
      else:
        assert flags & os.O_DIRECTORY or flags & os.O_NONBLOCK
      observed.append(path)
      return open_original(path, flags, *args, **kwargs)
    def mkdir(path, mode, *, dir_fd):
      assert type(path) is str and "/" not in path and mode == 0o700
      assert dir_fd in events.live
      return mkdir_original(path, mode, dir_fd=dir_fd)
    def read(fd, size):
      assert size <= 65536
      return read_original(fd, size)
    def write(fd, raw):
      assert len(raw) <= 65536
      return write_original(fd, raw)
    patch.setattr(stage.os, "open", opened)
    patch.setattr(stage.os, "mkdir", mkdir)
    patch.setattr(stage.os, "read", read)
    patch.setattr(stage.os, "write", write)
    _call(scratch)
    events.finish()
  assert "inventory.json" in observed


@pytest.mark.parametrize("fault", ["open", "fchmod", "fsync", "close", "zero-write"])
def test_inventory_creation_faults_do_not_return_success(scratch, monkeypatch, fault):
  with monkeypatch.context() as patch:
    events = _Events(patch)
    original_open = os.open
    active = [False]
    inventory_fd = [None]
    def opened(name, flags, *args, **kwargs):
      if name == "inventory.json" and flags & os.O_CREAT:
        active[0] = True
        if fault == "open": raise OSError("inventory create")
        inventory_fd[0] = original_open(name, flags, *args, **kwargs)
        return inventory_fd[0]
      return original_open(name, flags, *args, **kwargs)
    patch.setattr(stage.os, "open", opened)
    if fault in ("fchmod", "fsync", "zero-write"):
      operation = "write" if fault == "zero-write" else fault
      original = getattr(os, operation)
      def broken(fd, *args):
        if active[0] and fd == inventory_fd[0]:
          if fault == "zero-write": return 0
          raise OSError("inventory fault")
        return original(fd, *args)
      patch.setattr(stage.os, operation, broken)
    if fault == "close":
      events.close_fault = lambda event: OSError("inventory close") if active[0] and event["fd"] == inventory_fd[0] else None
    try:
      _reject(scratch)
    finally:
      events.finish()
    assert active[0]


def test_first_cleanup_control_wins_after_ordinary_cleanup(scratch, monkeypatch):
  first = KeyboardInterrupt("first control")
  second = SystemExit("second control")
  with monkeypatch.context() as patch:
    events = _Events(patch)
    errors = [OSError("ordinary"), first, second]
    calls = []
    def fault(event):
      calls.append(event)
      return errors.pop(0) if errors else OSError("later ordinary")
    events.close_fault = fault
    def write(*args): raise OSError("body")
    patch.setattr(stage.os, "write", write)
    try:
      with pytest.raises(KeyboardInterrupt) as caught: _call(scratch)
      assert caught.value is first
    finally:
      events.finish()
    assert len(calls) >= 4


@pytest.mark.parametrize("operation", ["prefix", "supervisor", "descendant"])
def test_bottom_up_directory_fsync_faults(scratch, monkeypatch, operation):
  original_open = os.open
  original_fsync = os.fsync
  selected = set()
  fired = []
  with monkeypatch.context() as patch:
    events = _Events(patch)
    original_open = os.open
    def opened(name, flags, *args, **kwargs):
      fd = original_open(name, flags, *args, **kwargs)
      chosen = "python-bundle" if operation == "prefix" else "supervisor" if operation == "supervisor" else "attr"
      if flags & os.O_DIRECTORY and name == chosen: selected.add(fd)
      else: selected.discard(fd)
      return fd
    def sync(fd):
      if fd in selected:
        fired.append(fd)
        raise OSError("directory fsync")
      return original_fsync(fd)
    patch.setattr(stage.os, "open", opened)
    patch.setattr(stage.os, "fsync", sync)
    _reject(scratch)
    events.finish()
  assert fired


def test_partial_output_and_existing_prefix_are_never_reused(scratch, monkeypatch):
  with monkeypatch.context() as patch:
    patch.setattr(stage.os, "write", lambda *args: 0)
    _reject(scratch)
  prefix = scratch[1] / "python-bundle"
  partial = {str(path.relative_to(prefix)): (path.lstat().st_ino, path.lstat().st_mode)
             for path in prefix.rglob("*")}
  _reject(scratch)
  assert partial == {str(path.relative_to(prefix)): (path.lstat().st_ino, path.lstat().st_mode)
                     for path in prefix.rglob("*")}
  assert not (prefix / "inventory.json").exists()


def test_preexisting_prefix_content_is_untouched(scratch):
  prefix = scratch[1] / "python-bundle"
  prefix.mkdir()
  path = prefix / "preexisting"
  path.write_bytes(b"retained original bytes")
  before = path.stat()
  _reject(scratch)
  # 先核完整 metadata；随后测试自身读取可以合法更新 atime。
  assert path.stat() == before
  assert path.read_bytes() == b"retained original bytes"


def test_planner_control_failure_is_preserved_without_output(scratch, monkeypatch):
  error = KeyboardInterrupt("planner control")
  def planner(*args, **kwargs): raise error
  monkeypatch.setattr(stage, "plan_python_bundle_install", planner)
  with pytest.raises(KeyboardInterrupt) as caught: _call(scratch)
  assert caught.value is error
  assert not (scratch[1] / "python-bundle").exists()


def _identity_targets():
  declaration, artifacts, _ = _fixture()
  plan = bundle.plan_python_bundle_install(declaration, artifacts, occupied_files=[])
  return [("directory", row["target"]) for row in plan["directories"]] + [("file", row["target"]) for row in plan["files"]]


@pytest.mark.parametrize("kind,target", _identity_targets())
def test_every_created_member_and_directory_identity_is_checked(scratch, monkeypatch, kind, target):
  original = stage._read_tree
  changed = []
  def read(*args, **kwargs):
    if not changed:
      changed.append(target)
      path = scratch[0] / target
      saved = path.with_name("identity-drift-saved")
      path.rename(saved)
      if kind == "directory":
        path.mkdir(mode=0o700)
        for child in list(saved.iterdir()): child.rename(path / child.name)
        saved.rmdir()
      else:
        path.write_bytes(saved.read_bytes())
        path.chmod(0o600)
        saved.unlink()
    return original(*args, **kwargs)
  monkeypatch.setattr(stage, "_read_tree", read)
  _reject(scratch)
  assert changed == [target]


def test_directory_fsync_order_is_bottom_up(scratch, monkeypatch):
  original_open = os.open
  original_fsync = os.fsync
  paths = {}
  synced = []
  def opened(name, flags, *args, **kwargs):
    fd = original_open(name, flags, *args, **kwargs)
    parent = paths.get(kwargs.get("dir_fd"), "")
    paths[fd] = parent + "/" + name
    return fd
  def fsync(fd):
    if stat.S_ISDIR(os.fstat(fd).st_mode): synced.append(paths[fd])
    return original_fsync(fd)
  monkeypatch.setattr(stage.os, "open", opened)
  monkeypatch.setattr(stage.os, "fsync", fsync)
  _call(scratch)
  assert synced[-1] == "/supervisor"
  assert synced[-2] == "/supervisor/python-bundle"
  assert len(synced) == len(set(synced))
  for index, path in enumerate(synced):
    for later in synced[index + 1:]:
      assert not later.startswith(path + "/")


@pytest.mark.parametrize("context,names", [("stage", ("A", "a")), ("supervisor", ("B", "b"))])
def test_unrelated_existing_case_aliases_are_preserved(scratch, context, names):
  parent = scratch[0] if context == "stage" else scratch[1]
  retained = []
  for index, name in enumerate(names):
    path = parent / name
    raw = b"retained case alias " + name.encode()
    path.write_bytes(raw)
    path.chmod(0o600 if index == 0 else 0o640)
    info = path.stat()
    retained.append((path, info.st_ino, info.st_mode, raw))
  assert _call(scratch) is None
  for path, inode, mode, raw in retained:
    assert (path.stat().st_ino, path.stat().st_mode, path.read_bytes()) == (inode, mode, raw)
  assert (scratch[1] / "python-bundle/inventory.json").is_file()


@pytest.mark.parametrize("context,critical", [("stage", "Supervisor"), ("supervisor", "Python-Bundle")])
def test_reserved_existing_case_aliases_still_reject(scratch, context, critical):
  parent = scratch[0] if context == "stage" else scratch[1]
  for name in ("unrelated", "UNRELATED"):
    (parent / name).write_bytes(b"retained unrelated alias")
  reserved = parent / critical
  reserved.mkdir(mode=0o700)
  sentinel = reserved / "retained"
  sentinel.write_bytes(b"reserved alias retained")
  before = sentinel.stat()
  _reject(scratch)
  assert sentinel.stat() == before
  assert sentinel.read_bytes() == b"reserved alias retained"
  assert not (scratch[1] / "python-bundle").exists()


def test_late_supervisor_named_replacement_rejects_and_restores(scratch, monkeypatch):
  original = stage._populate
  root, supervisor, borrowed = scratch
  saved = root / "saved-original-supervisor"
  before = supervisor.stat()
  replaced = []
  def populate(*args, **kwargs):
    if not replaced:
      supervisor.rename(saved)
      supervisor.mkdir(mode=0o750)
      supervisor.chmod(0o750)
      replaced.append(supervisor.stat().st_ino)
      assert replaced[0] != before.st_ino
    return original(*args, **kwargs)
  monkeypatch.setattr(stage, "_populate", populate)
  try:
    _reject(scratch)
    assert replaced
    assert (saved / "python-bundle/inventory.json").is_file()
    assert list(supervisor.iterdir()) == []
  finally:
    if replaced:
      supervisor.rmdir()
      saved.rename(supervisor)
  assert (supervisor.stat().st_ino, supervisor.stat().st_mode) == (before.st_ino, before.st_mode)
  assert os.fstat(borrowed).st_ino == root.stat().st_ino
