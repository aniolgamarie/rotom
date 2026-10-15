"""控制目录 anchor 仅授权精确只读端点；普通调用不采用 ambient 接线。"""

from contextlib import contextmanager
import errno
import io
import json
import os
from pathlib import Path
import stat
from types import SimpleNamespace

import pytest

from agentcfg import pi_control as control
from agentcfg.paths import PathError
from agentcfg.storage import Conflict


@pytest.fixture(autouse=True)
def verify_configured_source(pytestconfig):
  roots = [Path(path) if Path(path).is_absolute() else pytestconfig.rootpath / path
    for path in pytestconfig.getini("pythonpath")]
  assert Path(control.__file__).resolve() in [(root / "agentcfg/pi_control.py").resolve() for root in roots]


@pytest.fixture
def endpoint(tmp_path):
  parent = tmp_path / "control"
  parent.mkdir(mode=0o700)
  path = parent / "control.json"
  path.write_bytes(b'{"synthetic":true}\n')
  path.chmod(0o600)
  return path


def anchor(endpoint):
  info = endpoint.parent.stat()
  return {"device": info.st_dev, "inode": info.st_ino, "uid": info.st_uid}


def changed(info, **values):
  fields = ("st_mode", "st_uid", "st_nlink", "st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
  return SimpleNamespace(**{**{key: getattr(info, key) for key in fields}, **values})


@contextmanager
def tracked_descriptors(monkeypatch):
  original = os.open
  descriptors = []
  def opened(*args, **kwargs):
    fd = original(*args, **kwargs)
    descriptors.append(fd)
    return fd
  with monkeypatch.context() as patch:
    patch.setattr(os, "open", opened)
    try:
      yield descriptors
    finally:
      for fd in descriptors:
        with pytest.raises(OSError) as caught:
          os.fstat(fd)
        assert caught.value.errno == errno.EBADF


def test_valid_anchor_reads_exact_record_and_closes_all_descriptors(endpoint, monkeypatch):
  with tracked_descriptors(monkeypatch) as descriptors:
    with control.control_directory(endpoint, anchor(endpoint)) as (fd, raw):
      assert os.fstat(fd).st_ino == endpoint.parent.stat().st_ino
      assert raw[:2] == (b'{"synthetic":true}\n', 0o600)
    assert len(descriptors) == 2


def test_consumer_exception_closes_anchor_descriptor(endpoint, monkeypatch):
  with tracked_descriptors(monkeypatch):
    with pytest.raises(RuntimeError, match="synthetic consumer"):
      with control.control_directory(endpoint, anchor(endpoint)):
        raise RuntimeError("synthetic consumer")


def test_ambient_identity_never_downgrades_ordinary_request(endpoint, monkeypatch):
  import agentcfg.paths as paths
  expected = anchor(endpoint)
  monkeypatch.setenv(control.DIRECTORY_ENV, json.dumps(expected))
  @contextmanager
  def untrusted_ancestor(_path):
    raise PathError("synthetic unmapped ancestor")
    yield
  monkeypatch.setattr(paths, "_absolute_directory", untrusted_ancestor)
  with pytest.raises(PathError):
    control.request(endpoint, "synthetic-capability", {})
  with control.control_directory(endpoint, expected) as (_, raw):
    assert raw[0] == endpoint.read_bytes()


@pytest.mark.parametrize("invalid", [[], "identity", {}, {"unknown": 1}])
def test_anchor_rejects_nonclosed_identity_before_open(endpoint, monkeypatch, invalid):
  with monkeypatch.context() as patch:
    patch.setattr(os, "open", lambda *a, **k: pytest.fail("invalid identity opened a path"))
    with pytest.raises(Conflict):
      with control.control_directory(endpoint, invalid):
        pytest.fail("invalid identity accepted")


@pytest.mark.parametrize("field", ["device", "inode", "uid"])
@pytest.mark.parametrize("value", [True, 1.0, -1, "1"])
def test_anchor_fields_require_exact_nonnegative_integers(endpoint, monkeypatch, field, value):
  expected = {**anchor(endpoint), field: value}
  with monkeypatch.context() as patch:
    patch.setattr(os, "open", lambda *a, **k: pytest.fail("invalid identity opened a path"))
    with pytest.raises(Conflict):
      with control.control_directory(endpoint, expected):
        pytest.fail("invalid integer accepted")


@pytest.mark.parametrize("damage", ["unknown", "missing", "device", "inode", "uid"])
def test_anchor_rejects_unknown_missing_and_stale_directory_identity(endpoint, monkeypatch, damage):
  expected = anchor(endpoint)
  if damage == "unknown": expected["extra"] = 1
  elif damage == "missing": expected.pop("uid")
  else: expected[damage] += 1
  with tracked_descriptors(monkeypatch):
    with pytest.raises(Conflict):
      with control.control_directory(endpoint, expected):
        pytest.fail("stale directory accepted")


@pytest.mark.parametrize("damage", ["mode", "owner", "replacement", "symlink"])
def test_anchor_requires_same_private_owned_directory(endpoint, monkeypatch, damage):
  expected = anchor(endpoint)
  if damage == "mode": endpoint.parent.chmod(0o750)
  elif damage == "owner":
    original = os.fstat
    def fstat(fd):
      info = original(fd)
      return changed(info, st_uid=os.geteuid() + 1) if stat.S_ISDIR(info.st_mode) else info
    monkeypatch.setattr(os, "fstat", fstat)
  else:
    parent = endpoint.parent
    previous = parent.with_name("previous-control")
    parent.rename(previous)
    if damage == "replacement":
      parent.mkdir(mode=0o700)
      endpoint.write_bytes(b"synthetic replacement")
    else: parent.symlink_to(previous, target_is_directory=True)
  with tracked_descriptors(monkeypatch):
    with pytest.raises((Conflict, OSError)):
      with control.control_directory(endpoint, expected):
        pytest.fail("unsafe directory accepted")


@pytest.mark.parametrize("damage", ["relative", "filename", "parent"])
def test_anchor_only_accepts_absolute_fixed_control_path_without_parent_segments(endpoint, monkeypatch, damage):
  path = {"relative": Path("control.json"), "filename": endpoint.with_name("other.json"),
    "parent": endpoint.parent / ".." / endpoint.parent.name / "control.json"}[damage]
  with monkeypatch.context() as patch:
    patch.setattr(os, "open", lambda *a, **k: pytest.fail("invalid endpoint opened a path"))
    with pytest.raises(Conflict):
      with control.control_directory(path, anchor(endpoint)):
        pytest.fail("invalid endpoint accepted")


@pytest.mark.parametrize("damage", ["symlink", "hardlink", "mode", "owner", "directory", "oversize"])
def test_anchor_rejects_unsafe_records_without_leaking_descriptors(endpoint, monkeypatch, damage):
  expected = anchor(endpoint)
  if damage == "symlink":
    target = endpoint.with_name("synthetic-target")
    endpoint.rename(target)
    endpoint.symlink_to(target)
  elif damage == "hardlink": os.link(endpoint, endpoint.with_name("synthetic-hardlink"))
  elif damage == "mode": endpoint.chmod(0o644)
  elif damage == "directory":
    endpoint.unlink()
    endpoint.mkdir(mode=0o700)
  elif damage == "oversize": endpoint.write_bytes(b"x" * (control.MAX_FRAME + 1))
  else:
    original = os.stat
    def observed(path, *args, **kwargs):
      info = original(path, *args, **kwargs)
      return changed(info, st_uid=os.geteuid() + 1) if path == "control.json" else info
    monkeypatch.setattr(os, "stat", observed)
  with tracked_descriptors(monkeypatch):
    with pytest.raises(Conflict):
      with control.control_directory(endpoint, expected):
        pytest.fail("unsafe record accepted")


def test_record_replacement_between_stat_and_open_is_rejected(endpoint, monkeypatch):
  expected = anchor(endpoint)
  replacement = endpoint.with_name("synthetic-replacement")
  replacement.write_bytes(endpoint.read_bytes())
  original = os.open
  def replaced(path, *args, **kwargs):
    if path == "control.json": os.replace(replacement, endpoint)
    return original(path, *args, **kwargs)
  monkeypatch.setattr(os, "open", replaced)
  with tracked_descriptors(monkeypatch):
    with pytest.raises(Conflict, match="读取前"):
      with control.control_directory(endpoint, expected):
        pytest.fail("replacement accepted")


@pytest.mark.parametrize("phase", ["read", "close"])
def test_record_mutation_during_read_and_path_replacement_after_close_are_rejected(endpoint, monkeypatch, phase):
  expected = anchor(endpoint)
  replacement = endpoint.with_name("synthetic-replacement")
  replacement.write_bytes(endpoint.read_bytes())
  original = os.fdopen
  class Stream:
    def __init__(self, stream): self.stream = stream
    def __enter__(self): return self
    def __exit__(self, *_args):
      self.stream.close()
      if phase == "close": os.replace(replacement, endpoint)
    def fileno(self): return self.stream.fileno()
    def read(self, size):
      content = self.stream.read(size)
      if phase == "read": endpoint.write_bytes(b"synthetic mutated record with another size")
      return content
  monkeypatch.setattr(os, "fdopen", lambda *args, **kwargs: Stream(original(*args, **kwargs)))
  with tracked_descriptors(monkeypatch):
    with pytest.raises(Conflict, match="读取时" if phase == "read" else "路径"):
      with control.control_directory(endpoint, expected):
        pytest.fail("mutation accepted")


@pytest.mark.parametrize("value,expected", [(None, None), ('{"device":1,"inode":2,"uid":3}', {"device": 1, "inode": 2, "uid": 3})])
def test_runtime_request_explicitly_forwards_only_runtime_environment_identity(monkeypatch, value, expected):
  if value is None: monkeypatch.delenv(control.DIRECTORY_ENV, raising=False)
  else: monkeypatch.setenv(control.DIRECTORY_ENV, value)
  calls = []
  def request(endpoint, capability, message, **kwargs):
    calls.append((endpoint, capability, message, kwargs))
    return {"ok": True}
  monkeypatch.setattr(control, "request", request)
  assert control.runtime_request("/synthetic/control.json", "synthetic-capability", {"method": "handshake"}) == {"ok": True}
  assert len(calls) == 1
  assert calls[0][:3] == ("/synthetic/control.json", "synthetic-capability", {"method": "handshake"})
  assert calls[0][3].get("directory_identity") == expected
  assert set(calls[0][3]) <= {"directory_identity"}


@pytest.mark.parametrize("value", ["", "null", "{synthetic-invalid"])
def test_runtime_request_malformed_environment_never_retries_without_identity(monkeypatch, value):
  monkeypatch.setenv(control.DIRECTORY_ENV, value)
  monkeypatch.setattr(control, "request", lambda *a, **k: pytest.fail("malformed anchor reached RPC"))
  with pytest.raises(Conflict):
    control.runtime_request("/synthetic/control.json", "synthetic-capability", {})


@pytest.mark.parametrize("damage", [None, "socket", "peer", "capability"])
def test_anchored_request_preserves_socket_peer_and_capability_checks(endpoint, monkeypatch, damage):
  expected = anchor(endpoint)
  socket_info = {"device": 7, "inode": 8}
  endpoint.write_text(json.dumps({"schema_version": 1, "owner": {}, "socket_name": "control.sock",
    "socket_identity": socket_info, "user_capability": "synthetic-capability"}))
  original = os.stat
  def observed(path, *args, **kwargs):
    if path == "control.sock":
      return SimpleNamespace(st_mode=stat.S_IFSOCK | 0o600, st_uid=os.geteuid(), st_dev=7,
        st_ino=9 if damage == "socket" else 8)
    return original(path, *args, **kwargs)
  monkeypatch.setattr(os, "stat", observed)
  sent = []
  reply = {"ok": False, "exit_code": 4} if damage == "capability" else {"ok": True, "result": {}}
  class Channel(io.BytesIO):
    def write(self, data):
      sent.append(json.loads(data))
      return len(data)
  class Connection:
    def __enter__(self): return self
    def __exit__(self, *_args): pass
    def settimeout(self, value): assert value == 30
    def connect(self, name): assert name == "control.sock"
    def makefile(self, mode):
      assert mode == "rwb"
      return Channel(json.dumps(reply).encode() + b"\n")
  monkeypatch.setattr(control.socket, "socket", lambda *_: Connection())
  monkeypatch.setattr(control, "peer_uid", lambda _: os.geteuid() + (damage == "peer"))
  capability = "synthetic-wrong" if damage == "capability" else "synthetic-capability"
  if damage in ("socket", "peer"):
    with pytest.raises(Conflict): control.request(endpoint, capability, {}, directory_identity=expected)
    assert sent == []
  else:
    assert control.request(endpoint, capability, {}, directory_identity=expected) == reply
    assert sent == [{"capability": capability, "message": {}}]



def test_maximum_allowed_record_length_is_read_without_truncation(endpoint):
  endpoint.write_bytes(b"x" * control.MAX_FRAME)
  with control.control_directory(endpoint, anchor(endpoint)) as (_, raw):
    assert len(raw[0]) == control.MAX_FRAME


@pytest.mark.parametrize("value", ["[]", "{}", '{"device":true,"inode":1,"uid":1}', '{"device":1,"inode":2,"uid":3,"extra":4}'])
def test_runtime_request_invalid_declared_identity_never_uses_ordinary_path(endpoint, monkeypatch, value):
  monkeypatch.setenv(control.DIRECTORY_ENV, value)
  monkeypatch.setattr(control, "Tree", lambda *_: pytest.fail("invalid runtime identity fell back"))
  with pytest.raises(Conflict):
    control.runtime_request(endpoint, "synthetic-capability", {})
