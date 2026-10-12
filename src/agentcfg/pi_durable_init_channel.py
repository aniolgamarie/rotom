"""一次初始化回复纯窗口；不持有IO、grant或真实来源权限。"""

from dataclasses import replace
from functools import wraps
import hashlib
import re

from . import pi_durable_init_message as _message
from . import pi_durable_registration_record as _registration
from . import pi_durable_owner_record as _owner
from .storage import Conflict


_MESSAGE_NAMES = ("InitMessage", "capture_init_message", "encode_init_message_frame", "decode_init_message_frame",
  "ServiceRegistration", "capture_service_registration", "encode_service_registration", "LinuxProcessIdentity",
  "OwnerRecord", "StorageIdentity", "capture_owner_record", "encode_owner_record")
_REGISTRATION_NAMES = ("ServiceRegistration", "DirectoryIdentity", "InitialBinding", "StorageIdentity",
  "capture_service_registration", "encode_service_registration", "decode_service_registration")
_OWNER_NAMES = ("OwnerRecord", "LinuxProcessIdentity", "StorageIdentity", "capture_owner_record", "encode_owner_record", "decode_owner_record")
_SOURCES = tuple((module, name, vars(module)[name]) for module, names in
  ((_message, _MESSAGE_NAMES), (_registration, _REGISTRATION_NAMES), (_owner, _OWNER_NAMES)) for name in names)
_ENCODE_INIT = _message.encode_init_message_frame
_DECODE_INIT = _message.decode_init_message_frame
_INIT_MESSAGE = _message.InitMessage
_ENCODE_REGISTRATION = _registration.encode_service_registration
_DECODE_REGISTRATION = _registration.decode_service_registration
_SERVICE_REGISTRATION = _registration.ServiceRegistration
_LINUX_PROCESS_IDENTITY = _owner.LinuxProcessIdentity
_LOCAL_NAMES = ("_message", "_registration", "_owner", "_ENCODE_INIT", "_DECODE_INIT", "_INIT_MESSAGE",
  "_ENCODE_REGISTRATION", "_DECODE_REGISTRATION", "_SERVICE_REGISTRATION", "_LINUX_PROCESS_IDENTITY")
_LOCAL_SOURCES = tuple((name, globals()[name]) for name in _LOCAL_NAMES)
_REPLIES = ("slot", "offer-ack", "acquired", "registered-ack", "release-ack")
_EXPECTED = {
  "slot": ("type", "controller"),
  "offer-ack": ("type", "offer"),
  "acquired": ("type", "context_id", "token", "service_id", "reserved_registration", "controller"),
  "registered-ack": ("type", "reply"),
  "release-ack": ("type", "reply"),
}
_PROCESS = ("platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid")
_U64 = 2**64 - 1


def _sources_valid():
  return (all(globals().get(name) is original for name, original in _LOCAL_SOURCES)
    and all(vars(module).get(name) is original for module, name, original in _SOURCES))


def _invalid():
  raise ValueError("invalid init reply window")


def _reject():
  error = Conflict("Durable初始化回复窗口无效")
  try:
    raise error
  except Conflict:
    error.__cause__ = None
    error.__context__ = None
    raise


def _method(action):
  # 包含参数绑定错误：TypeError不能留下一个可恢复candidate。
  @wraps(action)
  def checked(self, *args, **kwargs):
    if type(self) is not InitReplyWindow: _reject()
    failed = False
    try:
      if not _sources_valid(): _invalid()
      result = action(self, *args, **kwargs)
      if not _sources_valid(): _invalid()
    except Exception:
      failed = True
    if failed:
      InitReplyWindow._discard(self, "RETIRED")
      _reject()
    return result
  return checked


def _integer(value, minimum, maximum):
  if type(value) is not int or not minimum <= value <= maximum: _invalid()
  return value


def _string(value, maximum):
  if type(value) is not str or len(value) > maximum: _invalid()
  return value


def _hash(value):
  value = _string(value, 64)
  if re.fullmatch(r"[0-9a-f]{64}", value, re.ASCII) is None: _invalid()
  return value


def _process(value):
  if type(value) is not _LINUX_PROCESS_IDENTITY: _invalid()
  data = {name: getattr(value, name) for name in _PROCESS}
  platform = _string(data["platform"], 5)
  if platform != "linux": _invalid()
  boot = _string(data["boot_id"], 36)
  if re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", boot, re.ASCII) is None: _invalid()
  start = _string(data["start_time"], 20)
  if re.fullmatch(r"0|[1-9][0-9]*", start, re.ASCII) is None or int(start) > _U64: _invalid()
  namespace = _string(data["namespace"], 26)
  match = re.fullmatch(r"pid:\[([1-9][0-9]*)\]", namespace, re.ASCII)
  if match is None or int(match.group(1)) > _U64: _invalid()
  return _LINUX_PROCESS_IDENTITY(platform, boot, _integer(data["pid"], 1, 2**31-1),
    _integer(data["ppid"], 0, 2**31-1), _integer(data["pgid"], 1, 2**31-1), start, namespace,
    _integer(data["uid"], 0, 2**32-2))


def _expected_data(value, reply_type):
  if type(value) is not dict or len(value) > 6: _invalid()
  items = tuple(dict.items(value))
  if any(type(key) is not str for key, _ in items): _invalid()
  for key, _ in items: _string(key, 32)
  data = dict(items)
  if set(data) != set(_EXPECTED[reply_type]): _invalid()
  kind = _string(data["type"], 14)
  if kind != reply_type: _invalid()
  return data


class InitReplyWindow:
  __slots__ = ("_state", "_reply_type", "_buffer", "_expected", "_candidate", "_observed")

  @_method
  def __init__(self):
    try:
      object.__getattribute__(self, "_state")
    except AttributeError:
      pass
    else:
      _invalid()
    self._state = "NEW"
    self._reply_type = self._expected = self._candidate = None
    self._buffer = bytearray()
    self._observed = 0

  def _discard(self, state):
    self._reply_type = self._expected = self._candidate = self._buffer = None
    self._observed = 0
    self._state = state

  def _call(self, original, *args):
    if not _sources_valid(): _invalid()
    result = original(*args)
    if not _sources_valid(): _invalid()
    return result

  def _clone_message(self, value):
    if type(value) is not _INIT_MESSAGE: _invalid()
    encoded = self._call(_ENCODE_INIT, value)
    return self._call(_DECODE_INIT, encoded)

  @_method
  def arm(self, reply_type):
    if self._state != "NEW" or type(reply_type) is not str or reply_type not in _REPLIES: _invalid()
    self._reply_type = reply_type
    self._state = "ARMED_UNBOUND"
    return None

  @_method
  def bind(self, expected):
    if self._state != "ARMED_UNBOUND": _invalid()
    data = _expected_data(expected, self._reply_type)
    if self._reply_type == "slot":
      self._expected = _process(data["controller"])
    elif self._reply_type == "acquired":
      context = _hash(data["context_id"])
      token = _hash(data["token"])
      service = _hash(data["service_id"])
      record = data["reserved_registration"]
      if type(record) is not _SERVICE_REGISTRATION: _invalid()
      encoded = self._call(_ENCODE_REGISTRATION, record)
      record = self._call(_DECODE_REGISTRATION, encoded)
      if record.stage != "reserved" or service != record.service_id: _invalid()
      controller = _process(data["controller"])
      self._expected = (context, token, service, record, hashlib.sha256(encoded).hexdigest(), controller)
    else:
      value = self._clone_message(data["offer" if self._reply_type == "offer-ack" else "reply"])
      if value.type != ("offer" if self._reply_type == "offer-ack" else self._reply_type): _invalid()
      self._expected = replace(value, type="offer-ack") if self._reply_type == "offer-ack" else value
    self._state = "BOUND_READING"
    return None

  def _matches(self, message):
    if type(message) is not _INIT_MESSAGE or message.type != self._reply_type: return False
    if self._reply_type == "slot": return message.controller == self._expected
    if self._reply_type == "acquired":
      context, token, service, record, digest, controller = self._expected
      return (message.context_id == context and message.token == token and message.service_id == service
        and message.reserved_registration_identity == digest
        and message.record.deployment_identity == record.initial_deployment_identity
        and message.record.controller == controller)
    return message == self._expected

  @_method
  def feed(self, chunk):
    if self._state != "BOUND_READING" or type(chunk) is not bytes: _invalid()
    if not chunk or len(chunk) > 65541 or self._observed + len(chunk) > 65541: _invalid()
    self._observed += len(chunk)
    offset = min(4 - len(self._buffer), len(chunk)) if len(self._buffer) < 4 else 0
    self._buffer.extend(chunk[:offset])
    if len(self._buffer) < 4: return None
    size = int.from_bytes(self._buffer[:4], "big")
    if not 1 <= size <= 65536: _invalid()
    if len(self._buffer) + len(chunk) - offset > size + 4: _invalid()
    self._buffer.extend(chunk[offset:])
    if len(self._buffer) < size + 4: return None
    message = self._call(_DECODE_INIT, bytes(self._buffer))
    if not self._matches(message): _invalid()
    self._buffer.clear()
    self._candidate = message
    self._state = "CANDIDATE"
    return None

  @_method
  def consume(self):
    if self._state != "CANDIDATE": _invalid()
    candidate = self._candidate
    self._discard("CONSUMED")
    return candidate

  def retire(self, *args, **kwargs):
    if type(self) is not InitReplyWindow: _reject()
    self._discard("RETIRED")
    if args or kwargs: _reject()
    return None

  @property
  def has_complete_frame(self):
    if not _sources_valid():
      self._discard("RETIRED")
      return False
    return self._state == "CANDIDATE"

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False
