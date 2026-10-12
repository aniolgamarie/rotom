"""从实际受管 current 导出点时 Full 数据观察；不签发 SourceHold 或角色资格。"""

from functools import wraps
import os
import re

from .deployment import json_bytes, read_state
from .pi import PiAdapter
from .pi_dependencies import PiBackend
from .storage import Tree
from .workspace import Workspace


MAX_DEPLOYMENT = 8 * 1024 * 1024
MAX_RECEIPT = 16 * 1024 * 1024
_GET_PROFILE = Workspace.profile.fget
_GET_AGENT = Workspace.agent.fget
_GET_INSTANCE = Workspace.instance.fget
_GET_STATE_ROOT = Workspace.state_root.fget
_GET_BINDING = Workspace.binding.fget
_BACKEND = PiAdapter.dependency_backend
_ROOT = PiBackend.root
_READ_STATE = read_state
_TREE_READ = Tree.read
_TREE_PARENT = Tree.parent
_FSTAT = os.fstat
_STAT = os.stat
_LAUNCH = {"argv", "lock_identity", "runtime_identity", "shared_files", "preflight",
  "runtime_guards", "machine", "adapter_binding", "environment"}


class CurrentFullSourceError(Exception):
  code = "PI_CURRENT_FULL_SOURCE_INVALID"
  exit_code = 4

  def __init__(self):
    super().__init__(self.code)


def _reject():
  error = CurrentFullSourceError()
  try:
    raise error
  except CurrentFullSourceError:
    error.__cause__ = None
    error.__context__ = None
    raise


def _boundary(action):
  @wraps(action)
  def checked(*args, **kwargs):
    failed = False
    try:
      result = action(*args, **kwargs)
    except BaseException:
      failed = True
    if failed:
      _reject()
    return result
  return checked


def _invalid():
  raise ValueError()


def _directory(tree):
  if tree.fd is None:
    _invalid()
  info = _FSTAT(tree.fd)
  return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid)


def _pending(tree):
  with _TREE_PARENT(tree, "pending.json") as (parent, name):
    try:
      _STAT(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
      return
    _invalid()


class _MemoryReader:
  """只把这次原有界读取的 bytes/mode 交给原 read_state，不重开文件。"""

  __slots__ = ("_raw",)

  def __init__(self, raw):
    self._raw = raw

  def read(self, path):
    if path != "deployment.json":
      _invalid()
    return self._raw


def _current(tree, binding):
  _pending(tree)
  raw = _TREE_READ(tree, "deployment.json", max_bytes=MAX_DEPLOYMENT)
  if raw is None:
    _invalid()
  saved = _READ_STATE(_MemoryReader(raw))
  current = saved["current"]
  if type(current) is not dict or set(current) != {"generation", "binding", "launch", "items"}:
    _invalid()
  if current["binding"] != binding or type(current["generation"]) is not str:
    _invalid()
  launch = current["launch"]
  if type(launch) is not dict or not {"lock_identity", "runtime_identity"} <= set(launch) <= _LAUNCH:
    _invalid()
  lock, runtime = launch["lock_identity"], launch["runtime_identity"]
  if any(type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None for value in (lock, runtime)):
    _invalid()
  _pending(tree)
  return current["binding"], current["generation"], lock, runtime


def _same_marker(tree, expected):
  raw = _TREE_READ(tree, ".agentcfg-instance.json", max_bytes=len(expected))
  if raw is None or raw[1] != 0o600 or raw[0] != expected:
    _invalid()


def _same_receipt(tree, expected):
  raw = _TREE_READ(tree, ".agentcfg-receipt.json", max_bytes=MAX_RECEIPT)
  if raw is None or raw[1] != 0o600 or expected is not None and raw[0] != expected:
    _invalid()
  return raw[0]


@_boundary
def observe_current_full_source(workspace):
  if type(workspace) is not Workspace or type(workspace.adapter) is not PiAdapter:
    _invalid()
  if _GET_PROFILE(workspace) != "pi-full" or _GET_AGENT(workspace) != "pi":
    _invalid()
  instance = _GET_INSTANCE(workspace)
  state_root = _GET_STATE_ROOT(workspace)
  binding = _GET_BINDING(workspace)
  expected_marker = json_bytes({"schema_version": 1, "state_root": str(state_root), "binding": binding})
  with Tree(instance) as instance_tree:
    instance_physical = _directory(instance_tree)
    _same_marker(instance_tree, expected_marker)
    # marker 先匹配；仅使用既有anchor，不创建目录/锁端点。
    from .pi_source_latch import source_latch
    with source_latch(workspace, shared=True, create=False):
      with Tree(state_root) as state_tree:
        current = _current(state_tree, binding)
        lock_identity, runtime_identity = current[2:]
        backend = _BACKEND(workspace.adapter, profile="pi-full")
        root = _ROOT(backend, workspace, runtime_identity)
        with Tree(root) as runtime_tree:
          runtime_physical = _directory(runtime_tree)
          receipt_bytes = _same_receipt(runtime_tree, None)
          from .pi_runtime_packages import _validated_receipt
          validated = _validated_receipt(root, runtime_identity)
          if validated is None:
            _invalid()
          receipt, original_bytes = validated
          if (receipt_bytes != original_bytes or type(receipt["schema_version"]) is not int or receipt["schema_version"] != 2
              or receipt["identity"] != runtime_identity or receipt["lock_identity"] != lock_identity
              or receipt["platform"] != "linux-x86_64" or receipt["binding_identity"]["profile"] != "pi-full"):
            _invalid()
          piece = receipt["slice"]
          context = {"identity": runtime_identity, "lock_identity": lock_identity, "platform": receipt["platform"],
            "toolchains": receipt["toolchains"], "binding_identity": receipt["binding_identity"]}
          from .pi_owner_origin import validate_installed_owner_origin
          envelope = validate_installed_owner_origin(root, piece, **context)
          # 原owner validator已完整核selection与accepted digest；状态本身不是激活资格。
          selected = envelope["metadata"]["capability_bindings"]["selections"]["pi-full"]
          if selected["state"] not in ("current", "accepted"):
            _invalid()
          from .pi_installed_source import capture_installed_full_source
          result = capture_installed_full_source(str(root), piece, **context)
          if _current(state_tree, binding) != current:
            _invalid()
          if _directory(runtime_tree) != runtime_physical:
            _invalid()
          _same_receipt(runtime_tree, receipt_bytes)
          with Tree(root) as named_runtime:
            if _directory(named_runtime) != runtime_physical:
              _invalid()
          if _directory(instance_tree) != instance_physical:
            _invalid()
          _same_marker(instance_tree, expected_marker)
          with Tree(instance) as named_instance:
            if _directory(named_instance) != instance_physical:
              _invalid()
  # 所有Tree与原SH退出/末核成功后才返回；不是连续持有或原子快照。
  return result
