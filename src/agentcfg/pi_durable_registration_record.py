"""服务登记纯元数据；合法记录不提供初始化、持锁或接管权限。"""

from dataclasses import dataclass
import json
import math
import re

from .pi_durable_owner_record import StorageIdentity
from .storage import Conflict


_MAX_BYTES = 32768
_U64 = 2**64 - 1
_FIELDS = ("schema", "platform", "service_id", "stage", "account_home", "account_identity", "index_identity", "initial_binding", "initial_instance", "initial_state_root", "storage_path", "storage_identity", "initial_deployment_identity")
_DIRECTORY = ("device", "inode", "uid")
_BINDING = ("machine", "local", "profile")


@dataclass(frozen=True, slots=True)
class DirectoryIdentity:
  device: int
  inode: int
  uid: int


@dataclass(frozen=True, slots=True)
class InitialBinding:
  machine: str
  local: str
  profile: str


@dataclass(frozen=True, slots=True)
class ServiceRegistration:
  schema: int
  platform: str
  service_id: str
  stage: str
  account_home: str
  account_identity: DirectoryIdentity
  index_identity: DirectoryIdentity
  initial_binding: InitialBinding
  initial_instance: str
  initial_state_root: str
  storage_path: str
  storage_identity: StorageIdentity | None
  initial_deployment_identity: str

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False


def _invalid():
  error = Conflict("Durable服务登记无效")
  try:
    raise error
  except Conflict:
    error.__cause__ = None
    error.__context__ = None
    raise


def _data(value, fields):
  if type(value) is not dict: _invalid()
  items = tuple(dict.items(value))
  if any(type(key) is not str for key, _ in items): _invalid()
  data = dict(items)
  if set(data) != set(fields): _invalid()
  return data


def _integer(value, minimum, maximum):
  if type(value) is not int: _invalid()
  if not minimum <= value <= maximum: _invalid()
  return value


def _string(value):
  if type(value) is not str: _invalid()
  return value


def _hash(value):
  value = _string(value)
  if len(value) != 64 or re.fullmatch(r"[0-9a-f]{64}", value, re.ASCII) is None: _invalid()
  return value


def _path(value):
  value = _string(value)
  if not 1 <= len(value) <= 4096: _invalid()
  if (not value.startswith("/") or value == "/" or "\\" in value
      or any(part in ("", ".", "..") for part in value[1:].split("/"))): _invalid()
  if any(ord(char) < 32 or 0x7f <= ord(char) <= 0x9f or 0xd800 <= ord(char) <= 0xdfff for char in value): _invalid()
  if not 1 <= len(value.encode("utf-8")) <= 4096: _invalid()
  return value


def _directory(value):
  data = _data(value, _DIRECTORY)
  return DirectoryIdentity(_integer(data["device"], 0, _U64), _integer(data["inode"], 1, _U64), _integer(data["uid"], 0, 2**32 - 2))


def capture_service_registration(value):
  data = _data(value, _FIELDS)
  schema = _integer(data["schema"], 1, 1)
  platform = _string(data["platform"])
  if platform != "linux": _invalid()
  service = _hash(data["service_id"])
  stage = _string(data["stage"])
  if stage not in ("reserved", "registered"): _invalid()
  account = _path(data["account_home"])
  account_identity = _directory(data["account_identity"])
  index_identity = _directory(data["index_identity"])
  if account_identity.uid != index_identity.uid: _invalid()
  binding = _data(data["initial_binding"], _BINDING)
  machine = _string(binding["machine"])
  if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", machine, re.ASCII) is None: _invalid()
  local = _path(binding["local"])
  profile = _string(binding["profile"])
  if profile != "pi-full": _invalid()
  initial_instance = _path(data["initial_instance"])
  initial_state_root = _path(data["initial_state_root"])
  storage_path = _path(data["storage_path"])
  if storage_path != initial_state_root + "/durable/storage": _invalid()
  storage = data["storage_identity"]
  if stage == "reserved":
    if storage is not None: _invalid()
  else:
    identity = _data(storage, ("device", "inode"))
    storage = StorageIdentity(_integer(identity["device"], 0, _U64), _integer(identity["inode"], 1, _U64))
  deployment = _hash(data["initial_deployment_identity"])
  return ServiceRegistration(schema, platform, service, stage, account, account_identity, index_identity,
    InitialBinding(machine, local, profile), initial_instance, initial_state_root, storage_path, storage, deployment)


def _pairs(items):
  data = {}
  for key, value in items:
    if key in data: raise ValueError("invalid registration JSON")
    data[key] = value
  return data


def _constant(_value):
  raise ValueError("invalid registration JSON")


def _float(value):
  result = float(value)
  if not math.isfinite(result): raise ValueError("invalid registration JSON")
  return result


def decode_service_registration(data):
  if type(data) is not bytes or not data or len(data) > _MAX_BYTES: _invalid()
  failed = False
  try:
    value = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
  except (ValueError, UnicodeError, RecursionError):
    failed = True
  if failed: _invalid()
  return capture_service_registration(value)


def _slots(value, cls, names):
  if type(value) is not cls: _invalid()
  return {name: getattr(value, name) for name in names}


def encode_service_registration(record):
  if type(record) is not ServiceRegistration: _invalid()
  failed = False
  try:
    data = {name: getattr(record, name) for name in _FIELDS}
    data["account_identity"] = _slots(record.account_identity, DirectoryIdentity, _DIRECTORY)
    data["index_identity"] = _slots(record.index_identity, DirectoryIdentity, _DIRECTORY)
    data["initial_binding"] = _slots(record.initial_binding, InitialBinding, _BINDING)
    if record.storage_identity is not None:
      data["storage_identity"] = _slots(record.storage_identity, StorageIdentity, ("device", "inode"))
  except AttributeError:
    failed = True
  if failed: _invalid()
  capture_service_registration(data)
  encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
  if len(encoded) > _MAX_BYTES: _invalid()
  return encoded
