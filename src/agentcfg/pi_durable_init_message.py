"""初始化纯消息帧；元数据、token和公开构造器不授予任何权限。"""

from dataclasses import dataclass, field
from functools import wraps
import json
import re

from .pi_durable_registration_record import ServiceRegistration, capture_service_registration, encode_service_registration
from .pi_durable_owner_record import (
  LinuxProcessIdentity, OwnerRecord, StorageIdentity, capture_owner_record, encode_owner_record,
)
from .storage import Conflict


_MAX_BYTES = 65536
_U64 = 2**64 - 1
_COMMON = ("schema", "type", "context_id", "token")
_OFFER = ("initialization_request_id", "initialization_identity", "source_identity", "policy_digest",
  "policy_generation", "cancel_generation", "deadline_monotonic_ns")
_RECEIPT = ("service_id", "index_generation", "registration_identity", "acquired_record_identity")
_SHAPES = {
  "slot": ("schema", "type", "controller", "slot_identity", "fd", "close_on_exec"),
  "offer": _COMMON + _OFFER,
  "offer-ack": _COMMON + _OFFER,
  "fresh-storage": _COMMON + ("registration", "index_generation", "initialization_request_id", "initialization_identity"),
  "acquired": _COMMON + ("service_id", "reserved_registration_identity", "record", "lock_identity", "fd", "close_on_exec"),
  "registered": _COMMON + ("registration", "index_generation", "reserved_registration_identity", "acquired_record_identity"),
  "registered-ack": _COMMON + _RECEIPT,
  "release": _COMMON + _RECEIPT,
  "release-ack": _COMMON + _RECEIPT,
}
_PROCESS = ("platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid")
_STORAGE = ("device", "inode")
_HASHES = ("context_id", "token", "initialization_request_id", "initialization_identity", "source_identity",
  "policy_digest", "service_id", "reserved_registration_identity", "acquired_record_identity", "registration_identity")
_UNSIGNED = ("policy_generation", "cancel_generation")
_POSITIVE = ("deadline_monotonic_ns", "index_generation")
_ALL = ("schema", "type", "controller", "slot_identity", "fd", "close_on_exec", "context_id", "token") + _OFFER + (
  "registration", "index_generation", "service_id", "reserved_registration_identity", "record", "lock_identity",
  "acquired_record_identity", "registration_identity")
_LOADS = json.loads


@dataclass(frozen=True, slots=True)
class InitMessage:
  schema: int
  type: str
  controller: LinuxProcessIdentity | None = None
  slot_identity: StorageIdentity | None = None
  fd: int | None = None
  close_on_exec: bool | None = None
  context_id: str | None = None
  token: str | None = field(default=None, repr=False)
  initialization_request_id: str | None = None
  initialization_identity: str | None = None
  source_identity: str | None = None
  policy_digest: str | None = None
  policy_generation: int | None = None
  cancel_generation: int | None = None
  deadline_monotonic_ns: int | None = None
  registration: ServiceRegistration | None = None
  index_generation: int | None = None
  service_id: str | None = None
  reserved_registration_identity: str | None = None
  record: OwnerRecord | None = None
  lock_identity: StorageIdentity | None = None
  acquired_record_identity: str | None = None
  registration_identity: str | None = None

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False


def _invalid():
  raise ValueError("invalid init message")


def _reject():
  error = Conflict("Durable初始化消息无效")
  try:
    raise error
  except Conflict:
    error.__cause__ = None
    error.__context__ = None
    raise


def _boundary(action):
  @wraps(action)
  def checked(*args, **kwargs):
    failed = False
    try:
      result = action(*args, **kwargs)
    except Exception:
      failed = True
    if failed: _reject()
    return result
  return checked


def _string(value, maximum=4096):
  if type(value) is not str or len(value) > maximum: _invalid()
  if any(0xd800 <= ord(char) <= 0xdfff for char in value): _invalid()
  return value


def _integer(value, minimum=0, maximum=_U64):
  if type(value) is not int or not minimum <= value <= maximum: _invalid()
  return value


def _copy(value, depth=1, count=None):
  if count is None: count = [0, 0]
  count[0] += 1
  if count[0] > 48 or depth > 4: _invalid()
  kind = type(value)
  if kind is str: return _string(value)
  if kind is int: return _integer(value)
  if value is None or kind is bool: return value
  if kind is not dict or depth > 3 or len(value) > 13: _invalid()
  count[1] += 1
  if count[1] > 6: _invalid()
  items = tuple(dict.items(value))
  if any(type(key) is not str for key, _ in items): _invalid()
  for key, _ in items: _string(key, 32)
  return {key: _copy(child, depth + 1, count) for key, child in items}


def _data(value, names):
  if type(value) is not dict or set(value) != set(names): _invalid()
  return value


def _hash(value):
  value = _string(value, 64)
  if re.fullmatch(r"[0-9a-f]{64}", value, re.ASCII) is None: _invalid()
  return value


def _storage(value):
  data = _data(value, _STORAGE)
  return StorageIdentity(_integer(data["device"]), _integer(data["inode"], 1))


def _process(value):
  data = _data(value, _PROCESS)
  platform = _string(data["platform"], 5)
  if platform != "linux": _invalid()
  boot = _string(data["boot_id"], 36)
  if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot, re.ASCII) is None: _invalid()
  start = _string(data["start_time"], 20)
  if re.fullmatch(r"0|[1-9][0-9]*", start, re.ASCII) is None or int(start) > _U64: _invalid()
  namespace = _string(data["namespace"], 26)
  match = re.fullmatch(r"pid:\[([1-9][0-9]*)\]", namespace, re.ASCII)
  if match is None or int(match.group(1)) > _U64: _invalid()
  return LinuxProcessIdentity(platform, boot, _integer(data["pid"], 1, 2**31 - 1),
    _integer(data["ppid"], 0, 2**31 - 1), _integer(data["pgid"], 1, 2**31 - 1), start,
    namespace, _integer(data["uid"], 0, 2**32 - 2))


@_boundary
def capture_init_message(value):
  if type(value) is not dict or len(value) > 11: _invalid()
  data = _copy(value)
  kind = data.get("type")
  if type(kind) is not str or kind not in _SHAPES: _invalid()
  _data(data, _SHAPES[kind])
  _integer(data["schema"], 1, 1)
  for name in _HASHES:
    if name in data: data[name] = _hash(data[name])
  for name in _UNSIGNED:
    if name in data: data[name] = _integer(data[name])
  for name in _POSITIVE:
    if name in data: data[name] = _integer(data[name], 1)
  if kind in ("slot", "acquired"):
    _integer(data["fd"], 3, 3)
    if data["close_on_exec"] is not True: _invalid()
  if kind == "slot":
    data["controller"] = _process(data["controller"])
    data["slot_identity"] = _storage(data["slot_identity"])
  elif kind in ("fresh-storage", "registered"):
    record = capture_service_registration(data["registration"])
    encode_service_registration(record)
    if record.stage != ("reserved" if kind == "fresh-storage" else "registered"): _invalid()
    data["registration"] = record
  elif kind == "acquired":
    record = capture_owner_record(data["record"])
    encode_owner_record(record)
    if record.stage != "acquired" or record.writer is not None: _invalid()
    data["record"] = record
    data["lock_identity"] = _storage(data["lock_identity"])
  return InitMessage(**data)


def _slots(value, cls, names):
  if type(value) is not cls: _invalid()
  return {name: getattr(value, name) for name in names}


@_boundary
def encode_init_message_frame(message):
  fields = _slots(message, InitMessage, _ALL)
  kind = fields["type"]
  if type(kind) is not str or kind not in _SHAPES: _invalid()
  names = _SHAPES[kind]
  if any(value is not None for name, value in fields.items() if name not in names): _invalid()
  data = {name: fields[name] for name in names}
  if kind == "slot":
    data["controller"] = _slots(data["controller"], LinuxProcessIdentity, _PROCESS)
    data["slot_identity"] = _slots(data["slot_identity"], StorageIdentity, _STORAGE)
  elif kind in ("fresh-storage", "registered"):
    data["registration"] = _LOADS(encode_service_registration(data["registration"]))
  elif kind == "acquired":
    data["record"] = _LOADS(encode_owner_record(data["record"]))
    data["lock_identity"] = _slots(data["lock_identity"], StorageIdentity, _STORAGE)
  capture_init_message(data)
  payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
  if not 1 <= len(payload) <= _MAX_BYTES: _invalid()
  return len(payload).to_bytes(4, "big") + payload


def _preflight(text):
  depth = objects = 0
  quoted = escaped = False
  for char in text:
    if quoted:
      if escaped: escaped = False
      elif char == "\\": escaped = True
      elif char == '"': quoted = False
    elif char == '"': quoted = True
    elif char in "[]": _invalid()
    elif char == "{":
      depth += 1
      objects += 1
      if depth > 3 or objects > 6: _invalid()
    elif char == "}":
      depth -= 1
      if depth < 0: _invalid()
  if quoted or depth: _invalid()


def _pairs(items):
  if len(items) > 13: _invalid()
  data = {}
  for key, value in items:
    _string(key, 32)
    if key in data: _invalid()
    data[key] = value
  return data


def _number(token):
  if len(token) > 20 or re.fullmatch(r"0|[1-9][0-9]*", token, re.ASCII) is None: _invalid()
  return _integer(int(token))


def _forbidden(_value):
  _invalid()


@_boundary
def decode_init_message_frame(data):
  if type(data) is not bytes or not 5 <= len(data) <= _MAX_BYTES + 4: _invalid()
  size = int.from_bytes(data[:4], "big")
  if not 1 <= size <= _MAX_BYTES or len(data) != size + 4: _invalid()
  text = bytes.decode(data[4:], "utf-8", "strict")
  _preflight(text)
  value = _LOADS(text, object_pairs_hook=_pairs, parse_int=_number,
    parse_float=_forbidden, parse_constant=_forbidden)
  return capture_init_message(value)
