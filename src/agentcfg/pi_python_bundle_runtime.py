"""所选 wheel 的 scratch 接线和严格物理回读；不授予来源、加载或发布资格。"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat


_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_PREFIX = ("supervisor", "python-bundle")
_BODY = "runtime/durable-python-bundle.json"
_INVENTORY = "supervisor/python-bundle/inventory.json"
_BLOCK = 65536


def _fail():
  raise ValueError()


class _Snapshot:
  def __init__(self):
    self.nodes = 0
    self.active = set()

  def walk(self, value, depth=0):
    self.nodes += 1
    if self.nodes > 100000 or depth > 16:
      _fail()
    kind = type(value)
    if kind is str:
      if len(value) > 4096:
        _fail()
      value.encode("utf-8", "strict")
      return value
    if kind is int:
      if not -(2 ** 63) <= value < 2 ** 63:
        _fail()
      return value
    if kind in (bool, type(None)):
      return value
    if kind not in (dict, list) or len(value) > 100000 or id(value) in self.active:
      _fail()
    self.active.add(id(value))
    try:
      if kind is dict:
        result = {}
        for key, child in value.items():
          if type(key) is not str:
            _fail()
          copied_key = self.walk(key, depth + 1)
          result[copied_key] = self.walk(child, depth + 1)
        return result
      return [self.walk(child, depth + 1) for child in value]
    finally:
      self.active.remove(id(value))


class _Cleanup:
  def __init__(self):
    self.failed = False
    self.control = None

  @contextmanager
  def fd(self, acquire, *args, **kwargs):
    descriptor = acquire(*args, **kwargs)
    try:
      yield descriptor
    finally:
      try:
        os.close(descriptor)
      except BaseException as error:
        self.failed = True
        if not isinstance(error, Exception) and self.control is None:
          self.control = error

  def check(self):
    if self.failed:
      _fail()

  @contextmanager
  def entries(self, fd):
    iterator = os.scandir(fd)
    try:
      yield iterator
    finally:
      try:
        iterator.close()
      except BaseException as error:
        self.failed = True
        if not isinstance(error, Exception) and self.control is None:
          self.control = error


def _boundary(function, *args):
  cleanup = _Cleanup()
  failed = False
  control = None
  try:
    result = function(cleanup, *args)
  except BaseException as error:
    failed = True
    if not isinstance(error, Exception):
      control = error
  if control is not None:
    raise control
  if cleanup.control is not None:
    raise cleanup.control
  if failed or cleanup.failed:
    try:
      raise ValueError("pi-python-bundle-runtime")
    except ValueError as error:
      error.__cause__ = None
      error.__context__ = None
      raise
  return result


def _path(value):
  if type(value) is not str and type(value) is not type(Path()):
    _fail()
  text = value if type(value) is str else str(value)
  if not 1 <= len(text) <= 4096 or len(text.encode("utf-8", "strict")) > 4096 or "\0" in text:
    _fail()
  return text


def _directory(fd, device=None, *, strict=False):
  info = os.fstat(fd)
  mode = stat.S_IMODE(info.st_mode)
  if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
      or (device is not None and info.st_dev != device) or mode & 0o7022
      or strict and mode != 0o700):
    _fail()
  return info


def _dir_identity(info):
  return info.st_dev, info.st_ino, info.st_mode, info.st_uid


def _file_identity(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
    info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@contextmanager
def _root(cleanup, path):
  before = os.stat(path, follow_symlinks=False)
  with cleanup.fd(os.open, path, _DIRECTORY) as fd:
    info = _directory(fd, strict=True)
    if _dir_identity(info) != _dir_identity(before):
      _fail()
    yield fd, info.st_dev
    if _dir_identity(_directory(fd, strict=True)) != _dir_identity(os.stat(path, follow_symlinks=False)):
      _fail()


@contextmanager
def _child(cleanup, parent, name, device, *, strict=False):
  before = os.stat(name, dir_fd=parent, follow_symlinks=False)
  with cleanup.fd(os.open, name, _DIRECTORY, dir_fd=parent) as fd:
    info = _directory(fd, device, strict=strict)
    if _dir_identity(info) != _dir_identity(before):
      _fail()
    yield fd
    if _dir_identity(_directory(fd, device, strict=strict)) != _dir_identity(os.stat(name, dir_fd=parent, follow_symlinks=False)):
      _fail()


@contextmanager
def _parent(cleanup, fd, parts, device):
  if not parts:
    yield fd
  else:
    with _child(cleanup, fd, parts[0], device) as child:
      with _parent(cleanup, child, parts[1:], device) as parent:
        yield parent


def _read_file(cleanup, parent, name, device, cap, *, expected=None, collect=False):
  named = os.stat(name, dir_fd=parent, follow_symlinks=False)
  with cleanup.fd(os.open, name, _FILE, dir_fd=parent) as fd:
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.geteuid() or before.st_dev != device or before.st_nlink != 1
        or not 0 <= before.st_size <= cap or _file_identity(before) != _file_identity(named)):
      _fail()
    checksum, size, chunks = hashlib.sha256(), 0, []
    while True:
      raw = os.read(fd, _BLOCK)
      if not raw:
        break
      size += len(raw)
      if size > cap or size > before.st_size:
        _fail()
      checksum.update(raw)
      if collect:
        chunks.append(raw)
    after = os.fstat(fd)
    if (size != before.st_size or _file_identity(before) != _file_identity(after)
        or _file_identity(after) != _file_identity(os.stat(name, dir_fd=parent, follow_symlinks=False))):
      _fail()
    if expected is not None and (size != expected["size"] or checksum.hexdigest() != expected["sha256"]):
      _fail()
    return b"".join(chunks) if collect else None


def _read(cleanup, fd, path, device, cap):
  parts = path.split("/")
  if len(parts) > 64 or any(part in ("", ".", "..") for part in parts) or "\\" in path:
    _fail()
  with _parent(cleanup, fd, parts[:-1], device) as parent:
    raw = _read_file(cleanup, parent, parts[-1], device, cap, collect=True)
  cleanup.check()
  return raw


def _pairs(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      _fail()
    result[key] = value
  return result


def _constant(value):
  _fail()


def _decode(raw):
  return _Snapshot().walk(json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant))


def _canonical(value):
  chunks, size = [], 0
  encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
  for text in encoder.iterencode(value):
    raw = text.encode("utf-8", "strict")
    size += len(raw)
    if size > 16777216:
      _fail()
    chunks.append(raw)
  return b"".join(chunks)


def _reference(reference):
  if (type(reference) is not dict or set(reference) != {"schema_version", "source", "path", "sha256", "size"}
      or type(reference["schema_version"]) is not int or reference["schema_version"] != 1
      or reference["source"] != "agents/pi/" + _BODY or reference["path"] != _BODY
      or type(reference["size"]) is not int or not 1 <= reference["size"] <= 8388608
      or type(reference["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]) is None):
    _fail()


def _body(cleanup, fd, device, reference):
  _reference(reference)
  raw = _read(cleanup, fd, _BODY, device, 8388608)
  if len(raw) != reference["size"] or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
    _fail()
  return raw


def _related(parts):
  folded = tuple(part.casefold() for part in parts)
  return folded == _PREFIX[:len(folded)] or _PREFIX == folded[:len(_PREFIX)]


def _occupied_path(parts):
  path = "/".join(parts)
  if len(parts) > 64 or len(path.encode("utf-8", "strict")) > 1024:
    _fail()
  for part in parts:
    low = part.lower()
    if (re.fullmatch(r"[A-Za-z0-9_.-]+", part) is None or part in (".", "..")
        or low.endswith((".data", ".pth", ".pyc", ".pyo")) or low == "__pycache__"
        or low.split(".")[0] in ("sitecustomize", "usercustomize")):
      _fail()
  return path


def _occupied(cleanup, root, device):
  records = []
  nodes = 0
  def walk(fd, parts):
    nonlocal nodes
    if len(parts) > 256:
      _fail()
    before = _directory(fd, device)
    names = set()
    with cleanup.entries(fd) as entries:
      for entry in entries:
        nodes += 1
        if nodes > 262144 or entry.name in names:
          _fail()
        names.add(entry.name)
        child_parts = (*parts, entry.name)
        info = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(info.st_mode):
          folded = tuple(part.casefold() for part in child_parts)
          if (folded == _PREFIX or folded == _PREFIX[:len(folded)] and child_parts != _PREFIX[:len(child_parts)]):
            _fail()
          with _child(cleanup, fd, entry.name, device) as child:
            walk(child, child_parts)
          cleanup.check()
        elif stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
          if _related(child_parts):
            if len(records) >= 16384:
              _fail()
            records.append({"kind": "file", "path": _occupied_path(child_parts)})
        else:
          _fail()
    cleanup.check()
    if _dir_identity(before) != _dir_identity(_directory(fd, device)):
      _fail()
  walk(root, ())
  records.sort(key=lambda row: row["path"])
  if len({row["path"] for row in records}) != len(records):
    _fail()
  return records


def _layout(cleanup, root, device, reference):
  raw = _body(cleanup, root, device, reference)
  declaration = _decode(raw)
  from .pi_python_bundle import validate_python_bundle_declaration, validate_python_bundle_inventory
  validate_python_bundle_declaration(declaration)
  inventory_raw = _read(cleanup, root, _INVENTORY, device, 16777216)
  inventory = _decode(inventory_raw)
  validate_python_bundle_inventory(declaration, inventory)
  if inventory_raw != _canonical(inventory):
    _fail()
  files = [{"path": row["target"], "sha256": row["sha256"], "size": row["size"], "mode": row["mode"]} for row in inventory["files"]]
  files.append({"path": _INVENTORY, "sha256": hashlib.sha256(inventory_raw).hexdigest(), "size": len(inventory_raw), "mode": 384})
  files.sort(key=lambda row: row["path"])
  directories = sorted(row["target"] for row in inventory["directories"])
  tree = {path: {"files": {}, "directories": {}} for path in directories}
  for path in directories:
    if path != "/".join(_PREFIX):
      parent, name = path.rsplit("/", 1)
      tree[parent]["directories"][name] = tree[path]
  for row in files:
    parent, name = row["path"].rsplit("/", 1)
    tree[parent]["files"][name] = row
  def verify(fd, node):
    before = _directory(fd, device, strict=True)
    expected = set(node["files"]) | set(node["directories"])
    seen = set()
    with cleanup.entries(fd) as entries:
      for entry in entries:
        if entry.name in seen or entry.name not in expected:
          _fail()
        seen.add(entry.name)
    cleanup.check()
    if seen != expected:
      _fail()
    for name, child in node["directories"].items():
      with _child(cleanup, fd, name, device, strict=True) as child_fd:
        verify(child_fd, child)
      cleanup.check()
    for name, row in node["files"].items():
      _read_file(cleanup, fd, name, device, row["size"], expected=row)
      cleanup.check()
    if _dir_identity(before) != _dir_identity(_directory(fd, device, strict=True)):
      _fail()
  with _child(cleanup, root, "supervisor", device) as supervisor:
    with _child(cleanup, supervisor, "python-bundle", device, strict=True) as prefix:
      verify(prefix, tree["/".join(_PREFIX)])
  return {"files": files, "directories": directories}


def _install(cleanup, stage, piece, sources):
  snapshot = _Snapshot()
  piece = snapshot.walk(piece)
  sources = snapshot.walk(sources)
  path = _path(stage)
  from .pi_wheel_sources import validate_python_bundle_reference, validate_selected_python_bundle
  validate_python_bundle_reference("pi-full", piece, sources, locked=True)
  if "python_bundle" not in piece:
    _fail()
  with _root(cleanup, path) as (fd, device):
    raw = _body(cleanup, fd, device, piece["python_bundle"])
    declaration = validate_selected_python_bundle(raw, piece, sources)
    artifacts = {}
    for identity in piece["source_ids"]:
      source = sources[identity]
      if source["kind"] != "wheel":
        continue
      archive = _read(cleanup, fd, source["vendor_path"], device, 2097152)
      if len(archive) != source["size"] or hashlib.sha256(archive).hexdigest() != source["archive_digest"]:
        _fail()
      artifacts[identity] = archive
    occupied = _occupied(cleanup, fd, device)
    from .pi_python_bundle_stage import install_python_bundle_stage
    install_python_bundle_stage(fd, declaration, artifacts, occupied_files=occupied)
    _layout(cleanup, fd, device, piece["python_bundle"])


def install_locked_python_bundle_stage(stage, piece, sources):
  """借用自有 scratch FD 接所选原bytes，成功不发布或授予加载资格。"""
  return _boundary(_install, stage, piece, sources)


def _validate(cleanup, root, reference):
  reference = _Snapshot().walk(reference)
  path = _path(root)
  _reference(reference)
  with _root(cleanup, path) as (fd, device):
    return _layout(cleanup, fd, device, reference)


def validate_installed_python_bundle(root, reference):
  """回读固定声明、canonical inventory和完整物理集合，返回 detached 布局。"""
  return _boundary(_validate, root, reference)
