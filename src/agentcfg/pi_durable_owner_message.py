"""单条私有 owner 元数据帧；不授予锁、进程或数据库能力。"""
from dataclasses import dataclass
import json
import re

from .pi_durable_owner_record import (
  LinuxProcessIdentity, OwnerRecord, StorageIdentity,
  capture_owner_record, encode_owner_record,
)
from .storage import Conflict


_MESSAGE = "Durable所有者消息无效"
_U64 = 2**64 - 1
_SAFE = 2**53 - 1
_TYPES = ("hello", "bind", "bound", "close", "closed")
_PROCESS = ("platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid")
_RECORD = ("schema", "deployment_identity", "storage_identity", "epoch", "controller", "writer", "stage")
_DECIMAL = re.compile(r"0|[1-9][0-9]*", re.ASCII)


@dataclass(frozen=True, slots=True)
class OwnerMessage:
  schema: int
  type: str
  writer: LinuxProcessIdentity | None
  record: OwnerRecord | None
  lock_identity: StorageIdentity
  fd: int
  close_on_exec: bool | None
  descriptor_closed: bool | None

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False


def _invalid():
  error = Conflict(_MESSAGE)
  try:
    raise error
  except Conflict:
    error.__context__ = None
    error.__cause__ = None
    raise


def _string(value):
  if type(value) is not str or len(value) > 128: _invalid()
  if any(0xd800 <= ord(char) <= 0xdfff for char in value): _invalid()
  return value


def _copy(value, depth=1, count=None):
  if count is None: count = [0]
  count[0] += 1
  if depth > 4 or count[0] > 64: _invalid()
  kind = type(value)
  if kind is str: return _string(value)
  if kind is int:
    if not 0 <= value <= _SAFE: _invalid()
    return value
  if value is None or kind is bool: return value
  if kind is not dict or len(value) > 64: _invalid()
  items = tuple(dict.items(value))
  # 全体键先核原类型，再进行哈希／读取；外来对象没有执行机会。
  if any(type(key) is not str for key, _ in items): _invalid()
  for key, _ in items: _string(key)
  return {key: _copy(child, depth + 1, count) for key, child in items}


def _data(value, names):
  if type(value) is not dict or set(value) != set(names): _invalid()
  return value


def _decimal(value, minimum=0):
  if type(value) is not str or len(value) > 20 or _DECIMAL.fullmatch(value) is None: _invalid()
  number = int(value)
  if not minimum <= number <= _U64: _invalid()
  return number


def _storage(value):
  fields = _data(value, ("device", "inode"))
  return StorageIdentity(_decimal(fields["device"]), _decimal(fields["inode"], 1))


def _record(value):
  fields = dict(_data(value, _RECORD))
  storage = _storage(fields["storage_identity"])
  fields["storage_identity"] = {"device": storage.device, "inode": storage.inode}
  failed = False
  try: record = capture_owner_record(fields)
  except Conflict: failed = True
  if failed: _invalid()
  return record


def _process(value):
  record = _record({"schema": 1, "deployment_identity": "0" * 64,
    "storage_identity": {"device": "0", "inode": "1"}, "epoch": "0" * 64,
    "controller": value, "writer": None, "stage": "acquired"})
  return record.controller


def capture_owner_message(value):
  """wire 原字典独立捕获；返回不可变无权限元数据。"""
  fields = _copy(value)
  if type(fields) is not dict: _invalid()
  kind = fields.get("type")
  if type(kind) is not str or kind not in _TYPES: _invalid()
  flag = "descriptor_closed" if kind == "closed" else "close_on_exec"
  body = "writer" if kind == "hello" else "record"
  _data(fields, ("schema", "type", body, "lock_identity", "fd", flag))
  if type(fields["schema"]) is not int or fields["schema"] != 1 or type(fields["fd"]) is not int or fields["fd"] != 3 or fields[flag] is not True: _invalid()
  lock = _storage(fields["lock_identity"])
  writer = _process(fields["writer"]) if kind == "hello" else None
  record = None if kind == "hello" else _record(fields["record"])
  if record is not None and (record.writer is None or record.stage != ("bound" if kind in ("bind", "bound") else "closing")): _invalid()
  return OwnerMessage(1, kind, writer, record, lock, 3, None if kind == "closed" else True, True if kind == "closed" else None)


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result: raise ValueError()
    result[key] = value
  return result


def _number(token):
  if _DECIMAL.fullmatch(token) is None or len(token) > 16: raise ValueError()
  value = int(token)
  if value > _SAFE: raise ValueError()
  return value


def _forbidden(_value): raise ValueError()


def decode_owner_message_frame(data):
  if type(data) is not bytes or not 5 <= len(data) <= 4100: _invalid()
  size = int.from_bytes(data[:4], "big")
  if not 1 <= size <= 4096 or len(data) != size + 4: _invalid()
  failed = False
  try:
    value = json.loads(bytes.decode(data[4:], "utf-8", "strict"), object_pairs_hook=_pairs,
      parse_int=_number, parse_float=_forbidden, parse_constant=_forbidden)
  except (ValueError, UnicodeError, RecursionError): failed = True
  if failed: _invalid()
  return capture_owner_message(value)


def _storage_wire(value):
  if type(value) is not StorageIdentity: _invalid()
  device, inode = value.device, value.inode
  if type(device) is not int or type(inode) is not int: _invalid()
  if not 0 <= device <= _U64 or not 1 <= inode <= _U64: _invalid()
  return {"device": str(device), "inode": str(inode)}


def _process_wire(value):
  if type(value) is not LinuxProcessIdentity: _invalid()
  return {name: getattr(value, name) for name in _PROCESS}


def encode_owner_message_frame(message):
  if type(message) is not OwnerMessage: _invalid()
  failed = False
  try:
    kind = message.type
    if type(kind) is not str or kind not in _TYPES: _invalid()
    value = {"schema": message.schema, "type": kind, "lock_identity": _storage_wire(message.lock_identity), "fd": message.fd}
    if kind == "hello":
      if message.record is not None or message.descriptor_closed is not None: _invalid()
      value["writer"] = _process_wire(message.writer)
    else:
      if message.writer is not None or type(message.record) is not OwnerRecord: _invalid()
      record = json.loads(encode_owner_record(message.record).decode("utf-8"))
      record["storage_identity"] = _storage_wire(message.record.storage_identity)
      value["record"] = record
    if kind == "closed":
      if message.close_on_exec is not None: _invalid()
      value["descriptor_closed"] = message.descriptor_closed
    else:
      if message.descriptor_closed is not None: _invalid()
      value["close_on_exec"] = message.close_on_exec
  except (AttributeError, Conflict, ValueError): failed = True
  if failed: _invalid()
  capture_owner_message(value)
  payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
  if not 1 <= len(payload) <= 4096: _invalid()
  return len(payload).to_bytes(4, "big") + payload
