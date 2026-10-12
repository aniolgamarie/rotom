"""Initializer 私有 bootstrap 的纯数据 codec；DTO/frame 不授予任何角色资格。"""

from dataclasses import dataclass
from functools import wraps
import json
import re


_CODE = "PI_INITIALIZER_BOOTSTRAP_INVALID"
_CAP = 2048
_MAX_GENERATION = 9007199254740991
_FIELDS = ("schema_version", "role", "instance_id", "supervisor_activation_id",
  "manager_activation_id", "host_lease_id", "grant_generation", "runtime_identity",
  "lock_identity", "slice_identity", "adapter_identity", "role_token")
_SHORT = ("supervisor_activation_id", "manager_activation_id", "host_lease_id")


class InitializerBootstrapError(Exception):
  code = _CODE
  exit_code = 4

  def __init__(self):
    super().__init__(_CODE)


def _reject():
  error = InitializerBootstrapError()
  try:
    raise error
  except InitializerBootstrapError:
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


def _invalid(*args):
  raise ValueError()


@dataclass(frozen=True, slots=True, repr=False, eq=False, init=False)
class InitializerBootstrap:
  """可公开构造/copy 的数据；repr 不列私密值，无 token 派生身份。"""

  schema_version: int
  role: str
  instance_id: str
  supervisor_activation_id: str
  manager_activation_id: str
  host_lease_id: str
  grant_generation: int
  runtime_identity: str
  lock_identity: str
  slice_identity: str
  adapter_identity: str
  role_token: str

  @_boundary
  def __init__(self, schema_version, role, instance_id, supervisor_activation_id,
      manager_activation_id, host_lease_id, grant_generation, runtime_identity,
      lock_identity, slice_identity, adapter_identity, role_token):
    values = (schema_version, role, instance_id, supervisor_activation_id,
      manager_activation_id, host_lease_id, grant_generation, runtime_identity,
      lock_identity, slice_identity, adapter_identity, role_token)
    for name, value in zip(_FIELDS, values):
      object.__setattr__(self, name, value)

  def __repr__(self):
    return "InitializerBootstrap(<redacted>)"


def _validate(value):
  if type(value) is not dict or len(value) != len(_FIELDS):
    _invalid()
  if any(type(name) is not str for name in value) or any(name not in value for name in _FIELDS):
    _invalid()
  if type(value["schema_version"]) is not int or value["schema_version"] != 1:
    _invalid()
  if type(value["role"]) is not str or value["role"] != "durable-initializer":
    _invalid()
  generation = value["grant_generation"]
  if type(generation) is not int or not 0 <= generation <= _MAX_GENERATION:
    _invalid()
  for name in _FIELDS:
    if name in ("schema_version", "role", "grant_generation"):
      continue
    text = value[name]
    width = 32 if name in _SHORT else 64
    if type(text) is not str or len(text) != width or re.fullmatch("[0-9a-f]+", text) is None:
      _invalid()
  return value


def _payload(value):
  return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


@_boundary
def capture_initializer_bootstrap(value):
  _validate(value)
  return InitializerBootstrap(**value)


@_boundary
def encode_initializer_bootstrap_frame(value):
  if type(value) is not InitializerBootstrap:
    _invalid()
  data = _validate({name: getattr(value, name) for name in _FIELDS})
  payload = _payload(data)
  if not 0 < len(payload) <= _CAP:
    _invalid()
  return len(payload).to_bytes(4, "big") + payload


@_boundary
def decode_initializer_bootstrap_frame(frame):
  # 先核原 bytes 的完整大小与固定 header，再分配/解码 payload。
  if type(frame) is not bytes or not 4 <= len(frame) <= _CAP + 4:
    _invalid()
  size = int.from_bytes(frame[:4], "big")
  if not 0 < size <= _CAP or len(frame) != size + 4:
    _invalid()
  payload = frame[4:]
  data = _validate(json.loads(payload.decode("ascii"), parse_constant=_invalid))
  if payload != _payload(data):
    _invalid()
  return InitializerBootstrap(**data)
