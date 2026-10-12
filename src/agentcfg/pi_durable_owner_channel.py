"""单次 owner 回复元数据窗口；不持有 pipe、锁或发送能力。"""
from . import pi_durable_owner_message as _message
from . import pi_durable_owner_record as _record
from .storage import Conflict


_MESSAGE_NAMES = ("OwnerMessage", "OwnerRecord", "LinuxProcessIdentity", "StorageIdentity",
  "capture_owner_message", "decode_owner_message_frame", "encode_owner_message_frame",
  "capture_owner_record", "encode_owner_record")
_RECORD_NAMES = ("OwnerRecord", "LinuxProcessIdentity", "StorageIdentity", "capture_owner_record", "encode_owner_record")
_SOURCES = tuple((module, name, vars(module)[name]) for module, names in
  ((_message, _MESSAGE_NAMES), (_record, _RECORD_NAMES)) for name in names)
_ENCODE = _message.encode_owner_message_frame
_DECODE = _message.decode_owner_message_frame
_OWNER_MESSAGE = _message.OwnerMessage


def _sources_valid():
  return all(vars(module).get(name) is original for module, name, original in _SOURCES)


def _invalid():
  error = Conflict("Durable所有者回复窗口无效")
  try:
    raise error
  except Conflict:
    error.__context__ = None
    error.__cause__ = None
    raise


class OwnerReplyWindow:
  __slots__ = ("_buffer", "_candidate", "_expected_frame", "_closed", "_invalid", "_consumed", "_ended")

  def __init__(self, expected):
    self._buffer = bytearray()
    self._candidate = self._expected_frame = None
    self._closed = self._invalid = self._consumed = self._ended = False
    encoded = self._call(_ENCODE, expected)
    captured = self._call(_DECODE, encoded)
    if type(captured) is not _OWNER_MESSAGE or captured.type not in ("hello", "bound", "closed"): self._fail()
    self._expected_frame = encoded

  def _discard(self):
    self._buffer.clear()
    self._candidate = None

  def _fail(self):
    self._invalid = True
    self._discard()
    _invalid()

  def _guard(self):
    if self._closed or self._invalid or not _sources_valid(): self._fail()

  def _call(self, original, *args):
    self._guard()
    failed = False
    try: result = original(*args)
    except Exception: failed = True
    if failed: self._fail()
    self._guard()
    return result

  def feed(self, chunk):
    self._guard()
    if type(chunk) is not bytes: self._fail()
    if not chunk or self._ended or self._consumed or self._candidate is not None: self._fail()
    if len(chunk) > 4101 or len(self._buffer) + len(chunk) > 4101: self._fail()
    # 先取得并检查 header；不因同 chunk 含后续 payload 而跳过长度核验。
    offset = min(4 - len(self._buffer), len(chunk)) if len(self._buffer) < 4 else 0
    self._buffer.extend(chunk[:offset])
    if len(self._buffer) < 4: return None
    size = int.from_bytes(self._buffer[:4], "big")
    if not 1 <= size <= 4096: self._fail()
    if len(self._buffer) + len(chunk) - offset > size + 4: self._fail()
    self._buffer.extend(chunk[offset:])
    if len(self._buffer) < size + 4: return None
    captured = self._call(_DECODE, bytes(self._buffer))
    encoded = self._call(_ENCODE, captured)
    if encoded != self._expected_frame: self._fail()
    self._candidate = captured
    self._buffer.clear()
    return None

  def take(self):
    self._guard()
    if self._consumed or self._candidate is None: self._fail()
    candidate = self._candidate
    self._candidate = None
    self._consumed = True
    return candidate

  def end(self):
    self._guard()
    if self._ended or (not self._consumed and self._candidate is None): self._fail()
    self._ended = True
    return None

  def close(self):
    self._closed = True
    self._discard()
    self._expected_frame = None
    return None

  @property
  def has_complete_frame(self):
    if self._closed or self._invalid or self._consumed: return False
    if not _sources_valid():
      self._invalid = True
      self._discard()
      return False
    return self._candidate is not None

  @property
  def writer_lock_verified(self): return False

  @property
  def database_allowed(self): return False

  @property
  def can_take_over(self): return False
