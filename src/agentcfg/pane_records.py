"""驻留容器的私人元数据；不提供进程、终端或现场能力控制。

更新严格比较当前原字节与 expected 的规范编码：合法非规范 JSON 可以只读观察，
不能静默规范化或忽略格式漂移。同一 Store 首次看到已有根后固定其物理身份。
状态只作格式与局部不变量校验，转换资格由持有完整生命周期证据的调用层决定。
"""

from contextlib import contextmanager
from functools import lru_cache
import json
import os
from pathlib import Path

from . import run_owners, storage
from .paths import PathError
from .storage import Conflict, StateError


_MAX_BYTES = 1024 * 1024
_MUTABLE = {"state", "run_id", "child_identity", "consumed_request_ids", "last_request_id"}
_INVALID = "驻留容器记录无效或绑定不匹配"
_ACCESS = "无法安全访问驻留容器记录；保留已有证据"


@lru_cache(maxsize=1)
def _validator():
  from jsonschema import Draft202012Validator
  schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/rotom/container.schema.json").read_bytes())
  return Draft202012Validator(schema)


def _json_types(value):
  # JSON Schema 接受 1.0 为整数；持久格式仍要求精确整数且拒绝 bool 冒充数值。
  if type(value) is dict:
    for key, item in value.items():
      if type(key) is not str:
        raise ValueError()
      _json_types(item)
  elif type(value) is list:
    for item in value:
      _json_types(item)
  elif value is not None and type(value) not in (str, int, bool):
    raise ValueError()
  if type(value) is bool:
    # 此固定格式没有任何布尔字段。
    raise ValueError()


def _validate(value, container_id):
  try:
    _json_types(value)
    if not _validator().is_valid(value) or value["container_id"] != container_id:
      raise ValueError()
    terminal, endpoint = value["terminal_ref"], value["endpoint_identity"]
    for path in (terminal["socket_path"], terminal["cwd"], endpoint["path"], value["scope"]["local"]):
      run_owners._absolute(path)
    if (value["last_request_id"] is not None and value["last_request_id"] not in value["consumed_request_ids"]
        or value["state"] in ("parked", "closed") and value["child_identity"] is not None):
      raise ValueError()
    _encode(value)
  except (TypeError, ValueError, UnicodeError, RecursionError, KeyError, OSError):
    raise Conflict(_INVALID) from None


def _encode(value):
  try:
    encoded = run_owners._encode(value)
    if len(encoded) > _MAX_BYTES:
      raise ValueError()
    return encoded
  except (TypeError, ValueError, UnicodeError, RecursionError):
    raise Conflict(_INVALID) from None


def _decode(data, container_id):
  try:
    value = json.loads(data, object_pairs_hook=run_owners._pairs, parse_constant=run_owners._invalid_constant)
  except (ValueError, UnicodeError, RecursionError):
    raise Conflict(_INVALID) from None
  _validate(value, container_id)
  return value


class ContainerStore:
  def __init__(self, root: Path, container_id: str):
    try:
      if not isinstance(root, Path):
        raise ValueError()
      run_owners._absolute(str(root))
      if root == Path("/"):
        raise ValueError()
      run_owners._run_id(container_id)
    except (ValueError, Conflict):
      raise Conflict(_INVALID) from None
    self.root = root
    self.container_id = container_id
    self._registry = run_owners.Registry(root, {"container_id": container_id})
    self._root_identity = None

  def _verify_root(self, tree):
    self._registry._verify_root(tree)
    info = os.fstat(tree.fd)
    current = info.st_dev, info.st_ino
    if self._root_identity is None:
      self._root_identity = current
    elif current != self._root_identity:
      raise Conflict(_ACCESS)

  @contextmanager
  def _locked(self, *, create=False):
    try:
      with self._registry._locked(create=create and self._root_identity is None) as tree:
        if tree is None:
          if self._root_identity is not None:
            raise Conflict(_ACCESS)
          yield None
          return
        self._verify_root(tree)
        yield tree
        self._verify_root(tree)
    except (OSError, PathError, StateError):
      raise Conflict(_ACCESS) from None

  def _read(self, tree):
    if tree is None:
      return None, None
    raw = tree.read("container.json", max_bytes=_MAX_BYTES)
    if raw is None:
      return None, None
    if raw[1] != 0o600:
      raise Conflict(_ACCESS)
    return _decode(raw[0], self.container_id), raw

  def _snapshot(self, value):
    _validate(value, self.container_id)
    encoded = _encode(value)
    return _decode(encoded, self.container_id), encoded

  def _readback(self, tree, encoded):
    value, raw = self._read(tree)
    if raw is None or raw[0] != encoded:
      raise Conflict(_ACCESS)
    return value

  def read(self) -> dict | None:
    """缺目录或记录时返回 None；不创建、不修复、不推断现场状态。"""
    with self._locked() as tree:
      value, _ = self._read(tree)
      return value

  def create(self, record: dict) -> dict:
    """仅创建新的 container.json；既有文件即使损坏也不覆盖。"""
    _, encoded = self._snapshot(record)
    with self._locked(create=True) as tree:
      tree.write_new("container.json", encoded)
      storage.sync_directory_ancestors(self.root.parent)
      return self._readback(tree, encoded)

  def update(self, expected: dict, replacement: dict) -> dict:
    """短元数据锁内原字节 CAS；不承担状态转换的控制资格判断。"""
    previous, expected_bytes = self._snapshot(expected)
    following, encoded = self._snapshot(replacement)
    if any(previous[key] != following[key] for key in previous.keys() - _MUTABLE):
      raise Conflict(_INVALID)
    old_ids, new_ids = previous["consumed_request_ids"], following["consumed_request_ids"]
    if new_ids[:len(old_ids)] != old_ids or not len(old_ids) <= len(new_ids) <= len(old_ids) + 1:
      raise Conflict(_INVALID)
    with self._locked() as tree:
      _, raw = self._read(tree)
      if raw is None or raw[0] != expected_bytes:
        raise Conflict(_ACCESS)
      tree.replace("container.json", encoded, expected=raw[2])
      return self._readback(tree, encoded)
