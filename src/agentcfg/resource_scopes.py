"""全新 OMP 实例的内部域登记；不采用旧目录，不授予启动、维护或历史覆盖证明。"""

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import secrets
import stat
import uuid

from . import omp_identity
from .deployment import json_bytes
from .paths import _absolute_directory
from .resource_coordination import _boundary, _physical, _absent
from .resource_keys import resource_key
from .resource_protocol import decode, encode
from .storage import Conflict, Tree, advisory_lock, identity


_CLAIMS = ".rotom-scope-claims"
_ANCHOR = ".rotom-resource.json"
_LOCK = ".agentcfg-omp.lock"
_OWNER = ".agentcfg-omp-owner.json"
_ERROR = "OMP实例资源协调不能确认；保留声明并重新核验"
_LIMIT = 65536


def _digest(raw):
  return hashlib.sha256(raw).hexdigest()


def _claim_name(instance):
  return _digest(instance.name.encode("utf8")) + ".json"


def _exists(tree, name):
  if tree.fd is None:
    return False
  try:
    with tree.parent(name) as (parent, leaf):
      os.stat(leaf, dir_fd=parent, follow_symlinks=False)
    return True
  except FileNotFoundError:
    return False


def scope_claim_exists(instance):
  """只读拒绝降级：独立声明、目录锚点或非空锁任一存在均保留保护。"""
  instance = Path(instance)
  with _boundary(), Tree(instance.parent / _CLAIMS) as claims:
    if _exists(claims, _claim_name(instance)):
      return True
    with Tree(instance) as tree:
      if tree.fd is None:
        return False
      if _exists(tree, _ANCHOR) or _exists(tree, "user-home/" + _ANCHOR):
        return True
      try:
        with tree.parent(_LOCK) as (parent, name):
          info = os.stat(name, dir_fd=parent, follow_symlinks=False)
          return info.st_size != 0
      except FileNotFoundError:
        return False


def _sync_ancestors(path):
  while True:
    with _absolute_directory(path) as fd:
      os.fsync(fd)
    if path == path.parent:
      break
    path = path.parent


def _read(tree, name, kind):
  result = tree.read(name, max_bytes=_LIMIT)
  if result is None or result[1] != 0o600:
    raise Conflict(_ERROR)
  return decode(result[0], kind=kind), result[0]


def _owner_ref(workspace):
  if (workspace.agent != "omp" or workspace.profile != workspace.binding["profile"]
      or not workspace.instance.is_absolute() or workspace.instance == Path("/")):
    raise Conflict(_ERROR)
  return {"state_root": str(workspace.state_root), "binding": workspace.binding.copy()}


def _records(anchor):
  digest = _digest(encode(anchor))
  return {anchor[name]["resource_id"]: {**anchor[name], "scope_id": anchor["scope_id"],
    "anchor_digest": digest, "status": "ready"} for name in ("instance", "native_home")}


def _verify(state, workspace, *, instance_fd, native_home_fd, expected=None, registered=True):
  # fd 只提供物理身份；调用方须持续持有原实例/状态/包租约，HOME fd 不假称额外锁。
  native = omp_identity.native_identity(workspace.profile, workspace.instance)
  omp_identity.validate_layout(native)
  if (not stat.S_ISREG(os.fstat(instance_fd).st_mode)
      or not stat.S_ISDIR(os.fstat(native_home_fd).st_mode)):
    raise Conflict(_ERROR)
  with Tree(workspace.instance.parent / _CLAIMS) as claims, Tree(workspace.instance) as tree, Tree(native.home) as home:
    claim, raw_claim = _read(claims, _claim_name(workspace.instance), "scope-claim")
    anchor, _ = _read(tree, _ANCHOR, "scope-anchor")
    home_anchor, _ = _read(home, _ANCHOR, "scope-anchor")
    before = os.fstat(instance_fd)
    raw = os.pread(instance_fd, _LIMIT + 1, 0)
    if (before.st_size != len(raw) or identity(before) != identity(os.fstat(instance_fd))
        or decode(raw, kind="scope-anchor") != anchor or home_anchor != anchor
        or (expected is not None and anchor != expected)):
      raise Conflict(_ERROR)
    with _absolute_directory(workspace.instance.parent) as parent:
      parent_physical = _physical(parent)
    expected_claim = {"schema_version": 1, "kind": "scope-claim", "protocol": "rotom-scope-v1",
      "scope_id": anchor["scope_id"], "domain_id": state["domain_id"],
      "domain_physical": state["physical"], "parent_physical": parent_physical,
      "instance_path": str(workspace.instance), "owner_ref": _owner_ref(workspace)}
    if (claim != expected_claim or anchor["domain_id"] != state["domain_id"]
        or anchor["domain_physical"] != state["physical"] or anchor["parent_physical"] != parent_physical
        or anchor["instance_physical"] != _physical(tree.fd)
        or anchor["owner_ref"] != expected_claim["owner_ref"] or anchor["claim_digest"] != _digest(raw_claim)):
      raise Conflict(_ERROR)
    for name, path, fd in (("instance", workspace.instance / _LOCK, instance_fd),
        ("native_home", native.home, native_home_fd)):
      kind = "instance" if name == "instance" else "native-home"
      if anchor[name]["path"] != str(path) or anchor[name]["key"] != resource_key(kind, path, lease_fd=fd).as_dict():
        raise Conflict(_ERROR)
    owner = tree.read(_OWNER, max_bytes=_LIMIT)
    if owner is None or _digest(owner[0]) != anchor["ownership_digest"]:
      raise Conflict(_ERROR)
    omp_identity._validate_saved_owner(owner, omp_identity.ownership(workspace))
    records = _records(anchor)
    if registered and any(state["resources"].get(rid) != record for rid, record in records.items()):
      raise Conflict(_ERROR)
    # 最后重新读取不可变证据；Tree 同时重核命名目录，拒绝读取期间的目录/文件替换。
    if (_read(claims, _claim_name(workspace.instance), "scope-claim")[1] != raw_claim
        or _read(tree, _ANCHOR, "scope-anchor")[0] != anchor
        or _read(home, _ANCHOR, "scope-anchor")[0] != anchor
        or tree.read(_OWNER, max_bytes=_LIMIT) != owner
        or os.pread(instance_fd, _LIMIT + 1, 0) != raw):
      raise Conflict(_ERROR)
    for name, path, fd in (("instance", workspace.instance / _LOCK, instance_fd),
        ("native_home", native.home, native_home_fd)):
      if resource_key("instance" if name == "instance" else "native-home", path, lease_fd=fd).as_dict() != anchor[name]["key"]:
        raise Conflict(_ERROR)
    return set(records)


def check_scope(domain, workspace, *, instance_fd, native_home_fd):
  """只读核验完整同域资源；根来自可信配置，不从记录中追踪任意路径。"""
  with domain._transaction() as state:
    return _verify(state, workspace, instance_fd=instance_fd, native_home_fd=native_home_fd)


def enroll_scope(domain, workspace):
  """仅创建全新实例；声明先持久化，失败留下保护，不重试、清理或采用旧内容。"""
  with _boundary(), ExitStack() as stack:
    owner_ref = _owner_ref(workspace)
    native = omp_identity.native_identity(workspace.profile, workspace.instance)
    state = domain.snapshot()
    parent = stack.enter_context(Tree(workspace.instance.parent, create=True))
    _absent(parent, workspace.instance.name)
    claims = stack.enter_context(Tree(parent.root / _CLAIMS, create=True))
    claim = {"schema_version": 1, "kind": "scope-claim", "protocol": "rotom-scope-v1",
      "scope_id": uuid.uuid4().hex, "domain_id": state["domain_id"], "domain_physical": state["physical"],
      "parent_physical": _physical(parent.fd), "instance_path": str(workspace.instance), "owner_ref": owner_ref}
    raw_claim = encode(claim)
    claims.write_new(_claim_name(workspace.instance), raw_claim)
    _sync_ancestors(claims.root)
    if _read(claims, _claim_name(workspace.instance), "scope-claim")[1] != raw_claim:
      raise Conflict(_ERROR)
    with parent.parent(workspace.instance.name) as (fd, name):
      os.mkdir(name, 0o700, dir_fd=fd)
    tree = stack.enter_context(Tree(workspace.instance))
    if os.listdir(tree.fd):
      raise Conflict(_ERROR)
    with tree.parent(_LOCK) as (fd, name):
      instance_fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
    stack.callback(os.close, instance_fd)
    stack.enter_context(advisory_lock(instance_fd, unlock=False))
    with tree.parent("user-home") as (fd, name):
      os.mkdir(name, 0o700, dir_fd=fd)
    home = stack.enter_context(Tree(native.home))
    if os.listdir(home.fd):
      raise Conflict(_ERROR)
    owner = json_bytes({**omp_identity.ownership(workspace), "owner_nonce": secrets.token_hex(16)})
    anchor = {"schema_version": 1, "kind": "scope-anchor", "protocol": "rotom-scope-v1",
      "scope_id": claim["scope_id"], "domain_id": state["domain_id"], "domain_physical": state["physical"],
      "parent_physical": _physical(parent.fd), "instance_physical": _physical(tree.fd),
      "owner_ref": owner_ref, "claim_digest": _digest(raw_claim), "ownership_digest": _digest(owner),
      "instance": {"resource_id": uuid.uuid4().hex, "path": str(workspace.instance / _LOCK),
        "key": resource_key("instance", workspace.instance / _LOCK, lease_fd=instance_fd).as_dict()},
      "native_home": {"resource_id": uuid.uuid4().hex, "path": str(native.home),
        "key": resource_key("native-home", native.home, lease_fd=home.fd).as_dict()}}
    raw = encode(anchor)
    tree.write_new(_OWNER, owner)
    tree.write_new(_ANCHOR, raw)
    home.write_new(_ANCHOR, raw)
    remaining = memoryview(raw)
    while remaining:
      written = os.write(instance_fd, remaining)
      if written <= 0:
        raise Conflict(_ERROR)
      remaining = remaining[written:]
    os.fsync(instance_fd)
    _sync_ancestors(home.root)
    with domain._transaction(write=True) as latest:
      if latest["domain_id"] != state["domain_id"] or latest["physical"] != state["physical"]:
        raise Conflict(_ERROR)
      _verify(latest, workspace, instance_fd=instance_fd, native_home_fd=home.fd, expected=anchor, registered=False)
      for rid, record in _records(anchor).items():
        if rid in latest["resources"] or any(existing["key"] == record["key"]
            or existing.get("path") == record["path"] for existing in latest["resources"].values()):
          raise Conflict(_ERROR)
        latest["resources"][rid] = record
    return anchor
