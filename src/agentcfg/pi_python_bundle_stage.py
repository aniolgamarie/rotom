"""私有 scratch 的有限原字节写入；成功不授予来源、加载或发布资格。"""

from contextlib import contextmanager
import hashlib
import io
import json
import os
import stat
import zipfile

from .pi_python_bundle import plan_python_bundle_install


_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_FILE_FLAGS = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_PREFIX = "supervisor/python-bundle"
_BLOCK = 65536


def _fail():
  raise ValueError()


def _snapshot(value):
  nodes = 0
  active = set()
  def walk(item, depth):
    nonlocal nodes
    nodes += 1
    if nodes > 100000 or depth > 16:
      _fail()
    kind = type(item)
    if kind is str:
      if len(item) > 4096:
        _fail()
      item.encode("utf-8", "strict")
      return item
    if kind is int:
      if not -(2 ** 63) <= item < 2 ** 63:
        _fail()
      return item
    if kind in (bool, type(None)):
      return item
    if kind not in (dict, list) or len(item) > 100000 or id(item) in active:
      _fail()
    active.add(id(item))
    try:
      result = {} if kind is dict else []
      if kind is dict:
        for key, child in item.items():
          if type(key) is not str:
            _fail()
          copied_key = walk(key, depth + 1)
          copied_child = walk(child, depth + 1)
          result[copied_key] = copied_child
      else:
        for child in item:
          result.append(walk(child, depth + 1))
      return result
    finally:
      active.remove(id(item))
  return walk(value, 0)


def _artifacts(value):
  if type(value) is not dict or len(value) != 7:
    _fail()
  result = {}
  total = 0
  for key, raw in value.items():
    if len(result) >= 7 or type(key) is not str or type(raw) is not bytes:
      _fail()
    if len(key) > 4096 or not 1 <= len(raw) <= 2097152:
      _fail()
    key.encode("utf-8", "strict")
    total += len(raw)
    if total > 8388608:
      _fail()
    result[key] = raw
  if len(result) != 7:
    _fail()
  return result


class _Cleanup:
  def __init__(self):
    self.failed = False
    self.control = None

  @contextmanager
  def fd(self, acquire, *args, **kwargs):
    # acquire 在 enter 内运行；成功后立即进入 finally，不另登记整数 FD。
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


def _identity(info):
  return info.st_dev, info.st_ino


def _directory(fd, device=None, *, supervisor=False):
  info = os.fstat(fd)
  mode = stat.S_IMODE(info.st_mode)
  if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
      or mode & 0o7000 or (mode & 0o022 if supervisor else mode != 0o700)
      or (device is not None and info.st_dev != device)):
    _fail()
  return info


def _file(fd, device):
  info = os.fstat(fd)
  if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
      or info.st_uid != os.geteuid() or info.st_dev != device or info.st_nlink != 1):
    _fail()
  return info


def _stable_file(info):
  return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
          info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _stable_directory(info):
  return info.st_dev, info.st_ino, info.st_mode, info.st_uid


def _names(fd, cap, *, case_unique=True):
  names = []
  folded = set()
  with os.scandir(fd) as entries:
    for entry in entries:
      if len(names) >= cap or (case_unique and entry.name.casefold() in folded):
        _fail()
      folded.add(entry.name.casefold())
      names.append(entry.name)
  return names


def _canonical(value):
  parts = []
  characters = 0
  size = 0
  encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
  for part in encoder.iterencode(value):
    characters += len(part)
    if characters > 16777216:
      _fail()
    raw = part.encode("utf-8", "strict")
    size += len(raw)
    if size > 16777216:
      _fail()
    parts.append(raw)
  return b"".join(parts)


def _write(fd, chunks, expected):
  digest = hashlib.sha256()
  size = 0
  for raw in chunks:
    if len(raw) > _BLOCK:
      _fail()
    size += len(raw)
    if size > expected[0]:
      _fail()
    digest.update(raw)
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
      count = os.write(fd, view[offset:])
      if type(count) is not int or not 0 < count <= len(view) - offset:
        _fail()
      offset += count
  if size != expected[0] or digest.hexdigest() != expected[1]:
    _fail()
  os.fsync(fd)


def _chunks(stream):
  while True:
    raw = stream.read(_BLOCK)
    if not raw:
      return
    yield raw


def _create_file(cleanup, parent, name, path, chunks, expected, device, identities):
  with cleanup.fd(os.open, name, os.O_WRONLY | _FILE_FLAGS | os.O_CREAT | os.O_EXCL,
                  0o600, dir_fd=parent) as fd:
    os.fchmod(fd, 0o600)
    identities[path] = _identity(_file(fd, device))
    _write(fd, chunks, expected)
    if _identity(_file(fd, device)) != identities[path]:
      _fail()
  cleanup.check()


def _tree(plan):
  root = {"directories": {}, "files": {}}
  nodes = {_PREFIX: root}
  for row in sorted(plan["directories"], key=lambda row: (row["target"].count("/"), row["target"])):
    path = row["target"]
    if path == _PREFIX:
      continue
    parent, name = path.rsplit("/", 1)
    node = {"directories": {}, "files": {}}
    nodes[parent]["directories"][name] = node
    nodes[path] = node
  for row in plan["files"]:
    parent, name = row["target"].rsplit("/", 1)
    nodes[parent]["files"][name] = row
  return root


def _populate(cleanup, fd, path, node, artifacts, device, identities):
  for name, child in node["directories"].items():
    target = path + "/" + name
    os.mkdir(name, 0o700, dir_fd=fd)
    with cleanup.fd(os.open, name, _DIRECTORY_FLAGS, dir_fd=fd) as child_fd:
      identities[target] = _identity(_directory(child_fd, device))
      _populate(cleanup, child_fd, target, child, artifacts, device, identities)
    cleanup.check()
  for name, row in node["files"].items():
    with zipfile.ZipFile(io.BytesIO(artifacts[row["source_id"]])) as archive:
      with archive.open(row["member"], "r") as stream:
        _create_file(cleanup, fd, name, row["target"], _chunks(stream),
                     (row["size"], row["sha256"]), device, identities)


def _read_file(cleanup, fd, name, path, expected, device, identities):
  with cleanup.fd(os.open, name, os.O_RDONLY | _FILE_FLAGS, dir_fd=fd) as member:
    before = _file(member, device)
    if _identity(before) != identities[path]:
      _fail()
    digest = hashlib.sha256()
    size = 0
    while True:
      raw = os.read(member, _BLOCK)
      if not raw:
        break
      size += len(raw)
      if size > expected[0]:
        _fail()
      digest.update(raw)
    after = _file(member, device)
    if (_stable_file(before) != _stable_file(after) or size != expected[0]
        or before.st_size != size or digest.hexdigest() != expected[1]
        or _stable_file(after) != _stable_file(os.stat(name, dir_fd=fd, follow_symlinks=False))):
      _fail()
  cleanup.check()


def _read_tree(cleanup, fd, path, node, device, identities, *, sync=False):
  before = _directory(fd, device)
  if _identity(before) != identities[path]:
    _fail()
  expected_names = set(node["directories"]) | set(node["files"])
  if set(_names(fd, len(expected_names))) != expected_names:
    _fail()
  for name, child in node["directories"].items():
    with cleanup.fd(os.open, name, _DIRECTORY_FLAGS, dir_fd=fd) as child_fd:
      _read_tree(cleanup, child_fd, path + "/" + name, child, device, identities, sync=sync)
      linked = os.stat(name, dir_fd=fd, follow_symlinks=False)
      if _stable_directory(linked) != _stable_directory(_directory(child_fd, device)):
        _fail()
    cleanup.check()
  for name, row in node["files"].items():
    _read_file(cleanup, fd, name, path + "/" + name,
               (row["size"], row["sha256"]), device, identities)
  if _stable_directory(before) != _stable_directory(_directory(fd, device)):
    _fail()
  if sync:
    os.fsync(fd)


def _install(cleanup, stage_fd, declaration, artifact_bytes, occupied_files):
  if type(stage_fd) is not int or not 0 <= stage_fd <= 2147483647:
    _fail()
  declaration = _snapshot(declaration)
  occupied_files = _snapshot(occupied_files)
  artifact_bytes = _artifacts(artifact_bytes)
  plan = plan_python_bundle_install(declaration, artifact_bytes, occupied_files=occupied_files)
  tree = _tree(plan)
  with cleanup.fd(os.dup, stage_fd) as stage:
    stage_before = _directory(stage)
    device = stage_before.st_dev
    names = _names(stage, 4096, case_unique=False)
    if [name for name in names if name.casefold() == "supervisor"] != ["supervisor"]:
      _fail()
    with cleanup.fd(os.open, "supervisor", _DIRECTORY_FLAGS, dir_fd=stage) as supervisor:
      supervisor_before = _directory(supervisor, device, supervisor=True)
      if any(name.casefold() == "python-bundle" for name in _names(supervisor, 4096, case_unique=False)):
        _fail()
      os.mkdir("python-bundle", 0o700, dir_fd=supervisor)
      with cleanup.fd(os.open, "python-bundle", _DIRECTORY_FLAGS, dir_fd=supervisor) as prefix:
        identities = {_PREFIX: _identity(_directory(prefix, device))}
        _populate(cleanup, prefix, _PREFIX, tree, artifact_bytes, device, identities)
        _read_tree(cleanup, prefix, _PREFIX, tree, device, identities)
        inventory = _canonical(plan["inventory_template"])
        inventory_path = _PREFIX + "/inventory.json"
        expected = len(inventory), hashlib.sha256(inventory).hexdigest()
        _create_file(cleanup, prefix, "inventory.json", inventory_path,
                     (inventory[start:start + _BLOCK] for start in range(0, len(inventory), _BLOCK)),
                     expected, device, identities)
        tree["files"]["inventory.json"] = {"size": expected[0], "sha256": expected[1]}
        _read_tree(cleanup, prefix, _PREFIX, tree, device, identities, sync=True)
        linked = os.stat("python-bundle", dir_fd=supervisor, follow_symlinks=False)
        if _stable_directory(linked) != _stable_directory(_directory(prefix, device)):
          _fail()
      cleanup.check()
      if (_stable_directory(supervisor_before) != _stable_directory(_directory(supervisor, device, supervisor=True))
          or _stable_directory(supervisor_before) != _stable_directory(os.stat("supervisor", dir_fd=stage, follow_symlinks=False))):
        _fail()
      os.fsync(supervisor)
    cleanup.check()
    if _stable_directory(stage_before) != _stable_directory(_directory(stage, device)):
      _fail()
  cleanup.check()


def install_python_bundle_stage(stage_fd, declaration, artifact_bytes, *, occupied_files):
  """仅写排他 scratch prefix；借用 FD 保留，任何失败保留部分输出。"""
  cleanup = _Cleanup()
  body_control = None
  failed = False
  try:
    _install(cleanup, stage_fd, declaration, artifact_bytes, occupied_files)
  except BaseException as error:
    failed = True
    if not isinstance(error, Exception):
      body_control = error
  if body_control is not None:
    raise body_control
  if cleanup.control is not None:
    raise cleanup.control
  if failed or cleanup.failed:
    try:
      raise ValueError("pi-python-bundle-stage")
    except ValueError as error:
      error.__cause__ = None
      error.__context__ = None
      raise
