"""服务索引纯快照；世代、登记与关联不授予任何运行权限。"""

from dataclasses import dataclass
from functools import wraps
import hashlib
import json
import math
import re

from .deployment import json_bytes
from .pi_durable_registration_record import (
  DirectoryIdentity, InitialBinding, ServiceRegistration,
  capture_service_registration, encode_service_registration,
)
from .storage import Conflict


_MAX_BYTES = 16 * 1024 * 1024
_U64 = 2**64 - 1
_TOP = ("schema", "platform", "account_home", "account_identity", "index_identity", "generation", "services", "associations")
_ENTRY = ("registration", "initialization_request_id", "initialization_identity")
_ASSOCIATION = ("association_id", "binding", "instance", "state_root", "service_id")
_DIRECTORY = ("device", "inode", "uid")
_BINDING = ("machine", "local", "profile")


@dataclass(frozen=True, slots=True)
class ServiceIndexEntry:
  registration: ServiceRegistration
  initialization_request_id: str
  initialization_identity: str


@dataclass(frozen=True, slots=True)
class ServiceAssociation:
  association_id: str
  binding: InitialBinding
  instance: str
  state_root: str
  service_id: str


@dataclass(frozen=True, slots=True)
class ServiceIndexSnapshot:
  schema: int
  platform: str
  account_home: str
  account_identity: DirectoryIdentity
  index_identity: DirectoryIdentity
  generation: int
  services: tuple[ServiceIndexEntry, ...]
  associations: tuple[ServiceAssociation, ...]

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False


def _invalid():
  error = Conflict("Durable服务索引无效")
  try:
    raise error
  except Conflict:
    error.__cause__ = None
    error.__context__ = None
    raise


def _boundary(action):
  # 在原异常处理块外创建本模块自己的异常，不修改外来异常。
  @wraps(action)
  def checked(*args, **kwargs):
    failed = False
    try:
      result = action(*args, **kwargs)
    except Exception:
      failed = True
    if failed: _invalid()
    return result
  return checked


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
  if re.fullmatch(r"[0-9a-f]{64}", value, re.ASCII) is None: _invalid()
  return value


def _path(value):
  value = _string(value)
  if not 1 <= len(value) <= 4096: _invalid()
  if (not value.startswith("/") or value == "/" or "\\" in value
      or any(part in ("", ".", "..") for part in value[1:].split("/"))): _invalid()
  if any(ord(char) < 32 or 0x7f <= ord(char) <= 0x9f or 0xd800 <= ord(char) <= 0xdfff for char in value): _invalid()
  if len(value.encode("utf-8")) > 4096: _invalid()
  return value


def _directory(value):
  data = _data(value, _DIRECTORY)
  return DirectoryIdentity(_integer(data["device"], 0, _U64), _integer(data["inode"], 1, _U64), _integer(data["uid"], 0, 2**32 - 2))


def _binding(value):
  data = _data(value, _BINDING)
  machine = _string(data["machine"])
  if re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", machine, re.ASCII) is None: _invalid()
  local = _path(data["local"])
  profile = _string(data["profile"])
  if profile != "pi-full": _invalid()
  return InitialBinding(machine, local, profile)


def _slots(value, cls, fields):
  if type(value) is not cls: _invalid()
  return {name: getattr(value, name) for name in fields}


def _association_identity(binding, instance, state_root):
  return hashlib.sha256(json_bytes({"schema": 1, "kind": "pi-durable-service-association",
    "binding": _slots(binding, InitialBinding, _BINDING), "instance": instance, "state_root": state_root})).hexdigest()


@_boundary
def service_association_identity(binding, instance, state_root):
  return _association_identity(_binding(binding), _path(instance), _path(state_root))


@_boundary
def capture_service_index(value):
  data = _data(value, _TOP)
  schema = _integer(data["schema"], 1, 1)
  platform = _string(data["platform"])
  if platform != "linux": _invalid()
  account = _path(data["account_home"])
  account_identity = _directory(data["account_identity"])
  index_identity = _directory(data["index_identity"])
  if account_identity.uid != index_identity.uid: _invalid()
  generation = _integer(data["generation"], 1, _U64)
  services = data["services"]
  associations = data["associations"]
  if type(services) is not list or type(associations) is not list: _invalid()
  if not 1 <= len(services) <= 64 or not 1 <= len(associations) <= 512: _invalid()
  entries = {}
  requests = set()
  for value in services:
    entry = _data(value, _ENTRY)
    registration = capture_service_registration(entry["registration"])
    # 原 capture 没有字节上限；公开 encoder 必须在每次捕获时核验。
    encode_service_registration(registration)
    request = _hash(entry["initialization_request_id"])
    identity = _hash(entry["initialization_identity"])
    if (registration.account_home != account or registration.account_identity != account_identity
        or registration.index_identity != index_identity): _invalid()
    if registration.service_id in entries or request in requests: _invalid()
    entries[registration.service_id] = ServiceIndexEntry(registration, request, identity)
    requests.add(request)
  captured = {}
  initial = set()
  for value in associations:
    association = _data(value, _ASSOCIATION)
    identity = _hash(association["association_id"])
    binding = _binding(association["binding"])
    instance = _path(association["instance"])
    state_root = _path(association["state_root"])
    service = _hash(association["service_id"])
    if identity != _association_identity(binding, instance, state_root): _invalid()
    if identity in captured or service not in entries: _invalid()
    registration = entries[service].registration
    if (binding == registration.initial_binding and instance == registration.initial_instance
        and state_root == registration.initial_state_root): initial.add(service)
    captured[identity] = ServiceAssociation(identity, binding, instance, state_root, service)
  if initial != set(entries): _invalid()
  return ServiceIndexSnapshot(schema, platform, account, account_identity, index_identity, generation,
    tuple(entries[key] for key in sorted(entries)), tuple(captured[key] for key in sorted(captured)))


def _pairs(items):
  data = {}
  for key, value in items:
    if key in data: raise ValueError("invalid index JSON")
    data[key] = value
  return data


def _constant(_value):
  raise ValueError("invalid index JSON")


def _float(value):
  result = float(value)
  if not math.isfinite(result): raise ValueError("invalid index JSON")
  return result


@_boundary
def decode_service_index(data):
  if type(data) is not bytes or not data or len(data) > _MAX_BYTES: _invalid()
  value = json.loads(data.decode("utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant, parse_float=_float)
  return capture_service_index(value)


@_boundary
def encode_service_index(index):
  data = _slots(index, ServiceIndexSnapshot, _TOP)
  if type(data["services"]) is not tuple or type(data["associations"]) is not tuple: _invalid()
  if not 1 <= len(data["services"]) <= 64 or not 1 <= len(data["associations"]) <= 512: _invalid()
  data["account_identity"] = _slots(data["account_identity"], DirectoryIdentity, _DIRECTORY)
  data["index_identity"] = _slots(data["index_identity"], DirectoryIdentity, _DIRECTORY)
  services = []
  for entry in data["services"]:
    value = _slots(entry, ServiceIndexEntry, _ENTRY)
    value["registration"] = json.loads(encode_service_registration(value["registration"]))
    services.append(value)
  associations = []
  for association in data["associations"]:
    value = _slots(association, ServiceAssociation, _ASSOCIATION)
    value["binding"] = _slots(value["binding"], InitialBinding, _BINDING)
    associations.append(value)
  data["services"] = services
  data["associations"] = associations
  capture_service_index(data)
  data["services"] = sorted(services, key=lambda entry: entry["registration"]["service_id"])
  data["associations"] = sorted(associations, key=lambda association: association["association_id"])
  encoded = json_bytes(data)
  if len(encoded) > _MAX_BYTES: _invalid()
  return encoded
