"""Linux 所有者记录纯编解码；元数据不能证明持锁、活性或准入。"""
from dataclasses import dataclass
import json
import re

from .storage import Conflict


_MAX_BYTES = 16384
_MAX_U64 = 2**64 - 1
_MESSAGE = "Durable所有者记录无效"
_RECORD_FIELDS = ("schema", "deployment_identity", "storage_identity", "epoch", "controller", "writer", "stage")
_PROCESS_FIELDS = ("platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid")
_HEX = re.compile(r"[0-9a-f]{64}", re.ASCII)
_BOOT = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.ASCII)
_DECIMAL = re.compile(r"0|[1-9][0-9]*", re.ASCII)
_NAMESPACE = re.compile(r"pid:\[([1-9][0-9]*)\]", re.ASCII)


@dataclass(frozen=True, slots=True)
class StorageIdentity:
  device: int
  inode: int


@dataclass(frozen=True, slots=True)
class LinuxProcessIdentity:
  platform: str
  boot_id: str
  pid: int
  ppid: int
  pgid: int
  start_time: str
  namespace: str
  uid: int


@dataclass(frozen=True, slots=True)
class OwnerRecord:
  schema: int
  deployment_identity: str
  storage_identity: StorageIdentity
  epoch: str
  controller: LinuxProcessIdentity
  writer: LinuxProcessIdentity | None
  stage: str

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
    # 只清除自有错误的链；bare raise 不重新绑定调用方正在处理的异常。
    error.__context__ = None
    error.__cause__ = None
    raise


def _data(value, fields):
  if type(value) is not dict: _invalid()
  # 先捕获 exact dict 的原键值；全体键类型核完以前不哈希/比较其内容。
  items = tuple(dict.items(value))
  if len(items) != len(fields) or any(type(key) is not str for key, _ in items): _invalid()
  if {key for key, _ in items} != set(fields): _invalid()
  return {key: child for key, child in items}


def _integer(value, minimum, maximum):
  if type(value) is not int: _invalid()
  if not minimum <= value <= maximum: _invalid()
  return value


def _string(value):
  if type(value) is not str: _invalid()
  return value


def _hash(value):
  value = _string(value)
  if len(value) != 64 or _HEX.fullmatch(value) is None: _invalid()
  return value


def _process(value):
  fields = _data(value, _PROCESS_FIELDS)
  platform = _string(fields["platform"])
  if platform != "linux": _invalid()
  boot = _string(fields["boot_id"])
  if len(boot) != 36 or _BOOT.fullmatch(boot) is None: _invalid()
  start = _string(fields["start_time"])
  if len(start) > 20 or _DECIMAL.fullmatch(start) is None or int(start) > _MAX_U64: _invalid()
  namespace = _string(fields["namespace"])
  if len(namespace) > 26: _invalid()
  match = _NAMESPACE.fullmatch(namespace)
  if match is None or int(match.group(1)) > _MAX_U64: _invalid()
  return LinuxProcessIdentity(platform, boot,
    _integer(fields["pid"], 1, 2**31 - 1), _integer(fields["ppid"], 0, 2**31 - 1),
    _integer(fields["pgid"], 1, 2**31 - 1), start, namespace,
    _integer(fields["uid"], 0, 2**32 - 2))


def capture_owner_record(value):
  """仅捕获精确闭合原 dict，所有嵌套记录独立且冻结。"""
  fields = _data(value, _RECORD_FIELDS)
  schema = _integer(fields["schema"], 1, 1)
  deployment = _hash(fields["deployment_identity"])
  epoch = _hash(fields["epoch"])
  storage = _data(fields["storage_identity"], ("device", "inode"))
  identity = StorageIdentity(_integer(storage["device"], 0, _MAX_U64), _integer(storage["inode"], 1, _MAX_U64))
  controller = _process(fields["controller"])
  writer = None if fields["writer"] is None else _process(fields["writer"])
  stage = _string(fields["stage"])
  if stage not in ("acquired", "bound", "ready", "closing", "released"): _invalid()
  if stage == "acquired" and writer is not None or stage in ("bound", "ready") and writer is None: _invalid()
  if writer is not None and (writer.pid == controller.pid or writer.boot_id != controller.boot_id or writer.uid != controller.uid): _invalid()
  return OwnerRecord(schema, deployment, identity, epoch, controller, writer, stage)


def _pairs(items):
  result = {}
  for key, value in items:
    if type(key) is not str or key in result: raise ValueError("invalid owner JSON")
    result[key] = value
  return result


def _constant(_value):
  raise ValueError("invalid owner JSON")


def decode_owner_record(data):
  """严格 bytes/UTF-8/JSON；退出异常处理作用域后只抛固定错误。"""
  if type(data) is not bytes or len(data) > _MAX_BYTES: _invalid()
  failed = False
  try:
    value = json.loads(bytes.decode(data, "utf-8", "strict"), object_pairs_hook=_pairs, parse_constant=_constant)
  except (ValueError, UnicodeError, RecursionError):
    failed = True
  if failed: _invalid()
  return capture_owner_record(value)


def _process_dict(value):
  if type(value) is not LinuxProcessIdentity: _invalid()
  return {name: getattr(value, name) for name in _PROCESS_FIELDS}


def encode_owner_record(record):
  """原 class 核验先于 slots 读取；不深拷或序列化任何外来对象。"""
  if type(record) is not OwnerRecord: _invalid()
  failed = False
  try:
    if type(record.storage_identity) is not StorageIdentity: _invalid()
    value = {
      "schema": record.schema,
      "deployment_identity": record.deployment_identity,
      "storage_identity": {"device": record.storage_identity.device, "inode": record.storage_identity.inode},
      "epoch": record.epoch,
      "controller": _process_dict(record.controller),
      "writer": None if record.writer is None else _process_dict(record.writer),
      "stage": record.stage,
    }
  except AttributeError:
    failed = True
  if failed: _invalid()
  capture_owner_record(value)
  # 全部原字段已经重验为 exact native values；仅序列化自有结构。
  encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8") + b"\n"
  if len(encoded) > _MAX_BYTES: _invalid()
  return encoded
