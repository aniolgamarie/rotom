"""只读目录与租约文件身份；真实临时 fd 不证明 writer、域归属或维护准入。"""

from dataclasses import FrozenInstanceError
import hashlib
import json
import os

import pytest

from agentcfg.resource_keys import ResourceKey, resource_key
from agentcfg.storage import Conflict


@pytest.fixture
def directory(tmp_path):
  path = tmp_path / "private-resource"
  path.mkdir(mode=0o700)
  return path


@pytest.fixture
def lease_fd(directory):
  fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
  try:
    yield fd
  finally:
    os.close(fd)


def reject(call):
  with pytest.raises(Conflict) as caught:
    call()
  assert caught.value.exit_code == 4
  assert str(caught.value) == "无法核验资源物理身份"
  assert caught.value.__cause__ is None


def test_identity_aliases_duplicate_fd_and_read_only_directory(directory, lease_fd):
  before = directory.stat()
  key = resource_key("instance", directory, lease_fd=lease_fd)
  assert (key.kind, key.device, key.inode) == ("instance", before.st_dev, before.st_ino)
  assert resource_key("instance", str(directory) + "/./", lease_fd=lease_fd) == key
  duplicate = os.dup(lease_fd)
  try:
    assert resource_key("instance", directory, lease_fd=duplicate) == key
    assert os.fstat(duplicate).st_ino == before.st_ino
  finally:
    os.close(duplicate)
  after = directory.stat()
  assert (before.st_mtime_ns, before.st_ctime_ns) == (after.st_mtime_ns, after.st_ctime_ns)
  assert list(directory.iterdir()) == []
  assert os.fstat(lease_fd).st_ino == before.st_ino


def test_distinct_physical_resources_with_same_profile_name(tmp_path):
  keys = []
  for machine in ("machine-a", "machine-b"):
    parent = tmp_path / machine
    parent.mkdir(mode=0o700)
    path = parent / "same-profile"
    path.mkdir(mode=0o700)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
      keys.append(resource_key("instance", path, lease_fd=fd))
    finally:
      os.close(fd)
  assert keys[0] != keys[1]
  assert keys[0].as_dict()["key_id"] != keys[1].as_dict()["key_id"]


def test_kinds_separate_same_inode(directory, lease_fd):
  keys = [resource_key(kind, directory, lease_fd=lease_fd) for kind in ("instance", "runtime", "native-home")]
  assert len(set(keys)) == 3
  assert len({key.as_dict()["key_id"] for key in keys}) == 3
  assert len({(key.device, key.inode) for key in keys}) == 1


def test_minimal_canonical_serialization_and_immutable_value():
  key = ResourceKey("instance", 0, 1)
  data = key.as_dict()
  assert set(data) == {"kind", "device", "inode", "key_id"}
  assert data["key_id"] == hashlib.sha256(b'{"device":0,"inode":1,"kind":"instance"}').hexdigest()
  assert ResourceKey.from_dict(json.loads(json.dumps(data))) == key
  assert ResourceKey.from_dict(dict(reversed(list(data.items())))) == key
  with pytest.raises(FrozenInstanceError):
    key.inode = 2
  data["inode"] = 2
  assert key.inode == 1


@pytest.mark.parametrize("kind", ["", "profile", "omp-file", None, True, 1])
def test_unknown_kind(kind):
  reject(lambda: ResourceKey(kind, 0, 1))


@pytest.mark.parametrize("device,inode", [
  (True, 1), (False, 1), (-1, 1), (1.0, 1), ("1", 1), (None, 1),
  (0, True), (0, False), (0, 0), (0, -1), (0, 1.0), (0, "1"), (0, None),
])
def test_exact_integer_boundaries(device, inode):
  reject(lambda: ResourceKey("runtime", device, inode))


@pytest.mark.parametrize("change", [
  lambda data: data.update(extra=True), lambda data: data.pop("key_id"),
  lambda data: data.update(key_id="0" * 64), lambda data: data.update(key_id=data["key_id"].upper()),
  lambda data: data.update(inode=2), lambda data: data.update(kind="native-home"),
  lambda data: data.update(device=True), lambda data: data.update(inode=1.0),
])
def test_deserialization_validates_exact_fields_and_digest(change):
  data = ResourceKey("instance", 0, 1).as_dict()
  change(data)
  reject(lambda: ResourceKey.from_dict(data))


@pytest.mark.parametrize("data", [None, [], "synthetic-private", True, 1])
def test_deserialization_requires_object(data):
  reject(lambda: ResourceKey.from_dict(data))


def test_missing_path_is_not_created(tmp_path, lease_fd):
  missing = tmp_path / "synthetic-private-missing"
  reject(lambda: resource_key("instance", missing, lease_fd=lease_fd))
  assert not missing.exists()


def test_symlink_and_symlink_ancestor_rejected(tmp_path, directory, lease_fd):
  link = tmp_path / "synthetic-private-link"
  link.symlink_to(directory, target_is_directory=True)
  reject(lambda: resource_key("instance", link, lease_fd=lease_fd))
  parent_link = tmp_path / "parent-alias"
  parent_link.symlink_to(tmp_path, target_is_directory=True)
  reject(lambda: resource_key("instance", parent_link / directory.name, lease_fd=lease_fd))


def test_hardlinked_lease_files_are_rejected(tmp_path):
  path = tmp_path / "synthetic-private-file"
  path.write_bytes(b"synthetic")
  alias = tmp_path / "synthetic-private-hardlink"
  os.link(path, alias)
  fd = os.open(path, os.O_RDONLY)
  try:
    assert path.stat().st_nlink == 2
    for candidate in (path, alias):
      reject(lambda: resource_key("native-home", candidate, lease_fd=fd))
    assert os.fstat(fd).st_nlink == 2
  finally:
    os.close(fd)


@pytest.mark.parametrize("mode", [0o755, 0o777, 0o750, 0o600])
def test_unsafe_mode_rejected_without_permission_repair(directory, lease_fd, mode):
  directory.chmod(mode)
  try:
    reject(lambda: resource_key("runtime", directory, lease_fd=lease_fd))
    assert directory.stat().st_mode & 0o777 == mode
  finally:
    directory.chmod(0o700)


def test_unsafe_ancestor_rejected(tmp_path):
  parent = tmp_path / "unsafe-parent"
  parent.mkdir(mode=0o700)
  path = parent / "private"
  path.mkdir(mode=0o700)
  fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
  parent.chmod(0o777)
  try:
    reject(lambda: resource_key("instance", path, lease_fd=fd))
  finally:
    os.close(fd)
    parent.chmod(0o700)


def test_mismatched_or_replaced_directory_rejected(tmp_path, directory, lease_fd):
  other = tmp_path / "other"
  other.mkdir(mode=0o700)
  reject(lambda: resource_key("instance", other, lease_fd=lease_fd))
  directory.rename(tmp_path / "renamed")
  directory.mkdir(mode=0o700)
  reject(lambda: resource_key("instance", directory, lease_fd=lease_fd))
  assert os.fstat(lease_fd).st_ino != directory.stat().st_ino


@pytest.mark.parametrize("fd", [None, True, False, -1, "0", 1.0])
def test_invalid_fd_type_or_value(directory, fd):
  reject(lambda: resource_key("instance", directory, lease_fd=fd))


def test_closed_fd_rejected(directory):
  fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
  os.close(fd)
  reject(lambda: resource_key("instance", directory, lease_fd=fd))


def test_unknown_kind_relative_and_escape_paths_rejected(directory, lease_fd):
  reject(lambda: resource_key("profile", directory, lease_fd=lease_fd))
  reject(lambda: resource_key("instance", directory.name, lease_fd=lease_fd))
  reject(lambda: resource_key("instance", directory / ".." / directory.name, lease_fd=lease_fd))


@pytest.fixture
def runtime_lease(tmp_path):
  cache = tmp_path / "cache"
  cache.mkdir(mode=0o700)
  leases = cache / "leases"
  leases.mkdir(mode=0o700)
  path = leases / "synthetic-identity.lock"
  path.write_bytes(b"synthetic-native-body-must-not-be-read")
  fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
  try:
    yield path, fd
  finally:
    os.close(fd)


def test_omp_runtime_file_identity_survives_runtime_directory_replacement(tmp_path, runtime_lease):
  path, fd = runtime_lease
  active = tmp_path / "runtime-active"
  active.mkdir(mode=0o700)
  key = resource_key("runtime", path, lease_fd=fd)
  active.rename(tmp_path / "runtime-previous")
  active.mkdir(mode=0o700)
  assert resource_key("runtime", path, lease_fd=fd) == key
  assert (key.device, key.inode) == (path.stat().st_dev, path.stat().st_ino)
  assert os.fstat(fd).st_ino == key.inode


def test_two_instance_references_to_same_package_lease_share_key(runtime_lease):
  path, fd = runtime_lease
  configurations = {"instance-a": {"runtime_lease": path}, "instance-b": {"runtime_lease": path}}
  keys = [resource_key("runtime", config["runtime_lease"], lease_fd=fd) for config in configurations.values()]
  assert keys[0] == keys[1]
  assert keys[0].as_dict() == keys[1].as_dict()


def test_file_identity_never_reads_native_body(runtime_lease, monkeypatch):
  from agentcfg import resource_keys, storage
  path, fd = runtime_lease
  before = path.stat()
  def forbidden(*args, **kwargs):
    pytest.fail("resource identity must not read native file body")
  monkeypatch.setattr(resource_keys.os, "read", forbidden)
  monkeypatch.setattr(storage.Tree, "read", forbidden)
  monkeypatch.setattr(storage.Tree, "open_read", forbidden)
  key = resource_key("native-home", path, lease_fd=fd)
  after = path.stat()
  assert key.inode == before.st_ino
  assert (before.st_mtime_ns, before.st_ctime_ns, before.st_atime_ns) == (after.st_mtime_ns, after.st_ctime_ns, after.st_atime_ns)
  assert os.fstat(fd).st_ino == before.st_ino


def test_replaced_lease_file_rejects_old_fd(runtime_lease):
  path, fd = runtime_lease
  path.rename(path.with_suffix(".old"))
  path.write_bytes(b"synthetic-replacement")
  reject(lambda: resource_key("runtime", path, lease_fd=fd))
  assert os.fstat(fd).st_ino != path.stat().st_ino


def test_lease_path_replacement_during_open_rejected(runtime_lease, monkeypatch):
  from agentcfg import resource_keys
  path, fd = runtime_lease
  original_open = resource_keys.os.open
  replaced = False
  def replacing_open(name, flags, *args, **kwargs):
    nonlocal replaced
    opened = original_open(name, flags, *args, **kwargs)
    if name == path.name and not flags & os.O_DIRECTORY and not replaced:
      replaced = True
      path.rename(path.with_suffix(".old"))
      path.write_bytes(b"synthetic-replacement")
    return opened
  monkeypatch.setattr(resource_keys.os, "open", replacing_open)
  reject(lambda: resource_key("runtime", path, lease_fd=fd))
  assert replaced


@pytest.mark.parametrize("mode", [0o644, 0o666, 0o400])
def test_unsafe_lease_file_mode_not_repaired(runtime_lease, mode):
  path, fd = runtime_lease
  path.chmod(mode)
  try:
    reject(lambda: resource_key("runtime", path, lease_fd=fd))
    assert path.stat().st_mode & 0o777 == mode
  finally:
    path.chmod(0o600)


def test_lease_symlink_and_unsafe_parent_rejected(runtime_lease):
  path, fd = runtime_lease
  link = path.with_suffix(".symlink")
  link.symlink_to(path)
  reject(lambda: resource_key("runtime", link, lease_fd=fd))
  path.parent.chmod(0o755)
  try:
    reject(lambda: resource_key("runtime", path, lease_fd=fd))
  finally:
    path.parent.chmod(0o700)


def test_lease_and_target_object_types_must_match(directory, lease_fd, runtime_lease):
  path, file_fd = runtime_lease
  reject(lambda: resource_key("runtime", path, lease_fd=lease_fd))
  reject(lambda: resource_key("instance", directory, lease_fd=file_fd))
  other = path.with_suffix(".other")
  other.write_bytes(b"synthetic")
  reject(lambda: resource_key("runtime", other, lease_fd=file_fd))


def test_lease_parent_replacement_during_open_rejected(runtime_lease, monkeypatch):
  from agentcfg import resource_keys
  path, fd = runtime_lease
  original_open = resource_keys.os.open
  replaced = False
  def replacing_open(name, flags, *args, **kwargs):
    nonlocal replaced
    opened = original_open(name, flags, *args, **kwargs)
    if name == path.name and not flags & os.O_DIRECTORY and not replaced:
      replaced = True
      path.parent.rename(path.parent.with_name("leases-previous"))
      path.parent.mkdir(mode=0o700)
      path.write_bytes(b"synthetic-new-parent")
    return opened
  monkeypatch.setattr(resource_keys.os, "open", replacing_open)
  reject(lambda: resource_key("runtime", path, lease_fd=fd))
  assert replaced


def test_directory_named_root_replacement_after_tree_open_rejected(directory, lease_fd, monkeypatch):
  from agentcfg import resource_keys
  original_tree = resource_keys.Tree
  replaced = False
  class ReplacingTree(original_tree):
    def __init__(self, path, **kwargs):
      nonlocal replaced
      super().__init__(path, **kwargs)
      if path == directory and not replaced:
        replaced = True
        directory.rename(directory.with_name("directory-previous"))
        directory.mkdir(mode=0o700)
  monkeypatch.setattr(resource_keys, "Tree", ReplacingTree)
  reject(lambda: resource_key("instance", directory, lease_fd=lease_fd))
  assert replaced
  assert os.fstat(lease_fd).st_ino != directory.stat().st_ino


def test_same_runtime_identity_in_distinct_cache_roots_has_distinct_keys(tmp_path):
  keys = []
  for cache_name in ("cache-a", "cache-b"):
    cache = tmp_path / cache_name
    cache.mkdir(mode=0o700)
    leases = cache / "leases"
    leases.mkdir(mode=0o700)
    path = leases / "same-runtime-identity.lock"
    path.write_bytes(b"synthetic-lease")
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
    try:
      keys.append(resource_key("runtime", path, lease_fd=fd))
      assert os.fstat(fd).st_ino == keys[-1].inode
    finally:
      os.close(fd)
  assert keys[0] != keys[1]
  assert keys[0].as_dict()["key_id"] != keys[1].as_dict()["key_id"]
