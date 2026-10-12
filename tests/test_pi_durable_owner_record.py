"""纯合成记录；不调用锁、/proc、信号、子进程、SDK、SQL或网络。"""
from dataclasses import FrozenInstanceError, replace
import json

import pytest

from agentcfg.pi_durable_owner_record import (
  LinuxProcessIdentity, OwnerRecord, StorageIdentity,
  capture_owner_record, decode_owner_record, encode_owner_record,
)
from agentcfg.storage import Conflict


SECRET = "SYNTHETIC_PRIVATE input credential source"


def process(pid=10, **extra):
  return {"platform": "linux", "boot_id": "01234567-89ab-cdef-0123-456789abcdef", "pid": pid, "ppid": 0, "pgid": pid,
    "start_time": "0", "namespace": "pid:[1]", "uid": 1000, **extra}


def raw(stage="acquired", writer=None):
  return {"schema": 1, "deployment_identity": "a" * 64, "storage_identity": {"device": 0, "inode": 1}, "epoch": "b" * 64,
    "controller": process(), "writer": writer, "stage": stage}


def invalid(call):
  with pytest.raises(Conflict) as caught: call()
  error = caught.value
  assert str(error) == "Durable所有者记录无效"
  assert error.__context__ is None and error.__cause__ is None
  assert SECRET not in str(error) and SECRET not in repr(error)
  return error


@pytest.mark.parametrize("stage,writer", [("acquired", None), ("bound", process(11)), ("ready", process(11)), ("closing", None), ("closing", process(11)), ("released", None), ("released", process(11))])
def test_complete_stage_roundtrip_and_flags_never_encoded(stage, writer):
  value = raw(stage, writer); record = capture_owner_record(value); encoded = encode_owner_record(record)
  assert type(record) is OwnerRecord and type(record.controller) is LinuxProcessIdentity and type(record.storage_identity) is StorageIdentity
  assert record.writer_lock_verified is False and record.database_allowed is False and record.can_take_over is False
  assert decode_owner_record(encoded) == record
  assert encoded.endswith(b"\n") and b" " not in encoded
  assert encoded == (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
  assert set(json.loads(encoded)) == {"schema", "deployment_identity", "storage_identity", "epoch", "controller", "writer", "stage"}
  assert not any(flag.encode() in encoded for flag in ("writer_lock_verified", "database_allowed", "can_take_over"))


def test_all_nested_sources_independent_and_frozen():
  value = raw("bound", process(11)); record = capture_owner_record(value)
  value["storage_identity"]["device"] = 7; value["controller"]["pid"] = 88; value["writer"]["uid"] = 9; value["epoch"] = "c" * 64
  assert record.storage_identity.device == 0 and record.controller.pid == 10 and record.writer.uid == 1000 and record.epoch == "b" * 64
  for target, name in [(record, "stage"), (record.controller, "pid"), (record.writer, "uid"), (record.storage_identity, "inode")]:
    with pytest.raises(FrozenInstanceError): setattr(target, name, 1)
    assert not hasattr(target, "__dict__")
  for name in ("writer_lock_verified", "database_allowed", "can_take_over"):
    with pytest.raises((FrozenInstanceError, AttributeError, TypeError)): setattr(record, name, True)


@pytest.mark.parametrize("field,values", [
  ("pid", [0, -1, 2**31, True, 1.0, "1"]), ("ppid", [-1, 2**31, False, 0.0]), ("pgid", [0, 2**31, True]),
  ("uid", [-1, 2**32 - 1, False, 1.0]), ("start_time", ["", "00", "01", "-1", "+1", "1.0", " 1", "١", str(2**64), 0]),
  ("namespace", ["pid:[0]", "pid:[01]", "pid:[-1]", "pid:[1]x", "pid:[" + str(2**64) + "]", "PID:[1]", None]),
  ("platform", ["Linux", "darwin", None]), ("boot_id", ["01234567-89AB-cdef-0123-456789abcdef", "bad", 1]),
])
def test_process_fields_exact_type_and_bound(field, values):
  for value in values:
    record = raw(); record["controller"][field] = value; invalid(lambda: capture_owner_record(record))


def test_numeric_boundaries_and_namespace_difference_are_metadata_only():
  controller = process(2**31 - 1, ppid=2**31 - 1, pgid=1, uid=2**32 - 2, start_time=str(2**64 - 1), namespace="pid:[" + str(2**64 - 1) + "]")
  writer = process(1, uid=2**32 - 2, namespace="pid:[2]", ppid=999, pgid=777)
  value = raw("ready", writer); value["controller"] = controller; value["storage_identity"] = {"device": 2**64 - 1, "inode": 2**64 - 1}
  record = capture_owner_record(value); assert decode_owner_record(encode_owner_record(record)) == record; assert record.database_allowed is False


@pytest.mark.parametrize("mutate", [
  lambda r: r.update(schema=True), lambda r: r.update(schema=1.0), lambda r: r.update(schema=2),
  lambda r: r.update(epoch="B" * 64), lambda r: r.update(deployment_identity="a" * 63), lambda r: r.update(stage="running"),
  lambda r: r.update(writer=process(11)), lambda r: r.update(stage="bound"),
  lambda r: r["storage_identity"].update(device=-1), lambda r: r["storage_identity"].update(inode=0),
  lambda r: r["storage_identity"].update(device=True), lambda r: r["storage_identity"].update(inode=2**64),
  lambda r: r.update(writer_lock_verified=True), lambda r: r.update(extra=SECRET),
])
def test_record_closure_schema_and_stage(mutate):
  value = raw(); mutate(value); invalid(lambda: capture_owner_record(value))


@pytest.mark.parametrize("mutate", [lambda w: w.update(pid=10), lambda w: w.update(uid=1001), lambda w: w.update(boot_id="ffffffff-ffff-ffff-ffff-ffffffffffff")])
def test_writer_relation_is_exact_without_parent_or_liveness_inference(mutate):
  writer = process(11); mutate(writer); invalid(lambda: capture_owner_record(raw("bound", writer)))


def test_missing_extra_fields_at_every_level():
  for path in [(), ("storage_identity",), ("controller",), ("writer",)]:
    for kind in ["missing", "extra"]:
      value = raw("bound", process(11)); nested = value if not path else value[path[0]]
      if kind == "missing": del nested[next(iter(nested))]
      else: nested["unexpected"] = SECRET
      invalid(lambda: capture_owner_record(value))


@pytest.mark.parametrize("data", [b"", b"{bad " + SECRET.encode(), b"\xff" + SECRET.encode(), b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1,"x":2}', b'{"x":{"a":1,"a":2}}', b"[]", b"null", b"true", b"1", b"[" * 5000 + b"0" + b"]" * 5000, b"x" * 16385])
def test_decode_strict_json_utf8_depth_size_and_exception_privacy(data):
  invalid(lambda: decode_owner_record(data))


def test_duplicate_valid_nested_fields_and_strict_bytes_capacity():
  encoded = encode_owner_record(capture_owner_record(raw()))
  invalid(lambda: decode_owner_record(encoded.replace(b'"pid":10', b'"pid":10,"pid":10')))
  padded = encoded + b" " * (16384 - len(encoded)); assert decode_owner_record(padded).schema == 1
  invalid(lambda: decode_owner_record(padded + b" "))
  for value in [encoded.decode(), bytearray(encoded), memoryview(encoded)]: invalid(lambda: decode_owner_record(value))


class PoisonString(str):
  calls = []
  def __eq__(self, other): self.calls.append("eq"); raise RuntimeError(SECRET)
  def __hash__(self): self.calls.append("hash"); return str.__hash__(self)
  def __str__(self): self.calls.append("str"); raise RuntimeError(SECRET)
  def __repr__(self): self.calls.append("repr"); raise RuntimeError(SECRET)


class PoisonInt(int):
  calls = []
  def __eq__(self, other): self.calls.append("eq"); raise RuntimeError(SECRET)
  def __lt__(self, other): self.calls.append("lt"); raise RuntimeError(SECRET)
  def __hash__(self): self.calls.append("hash"); raise RuntimeError(SECRET)
  def __repr__(self): self.calls.append("repr"); raise RuntimeError(SECRET)


class PoisonDict(dict):
  calls = []
  def __iter__(self): self.calls.append("iter"); raise RuntimeError(SECRET)
  def items(self): self.calls.append("items"); raise RuntimeError(SECRET)
  def __getitem__(self, key): self.calls.append("getitem"); raise RuntimeError(SECRET)


def test_dict_keys_typed_before_hash_set_equality_or_repr():
  value = raw(); del value["schema"]; value[PoisonString("schema")] = 1; PoisonString.calls.clear()
  invalid(lambda: capture_owner_record(value)); assert PoisonString.calls == []
  invalid(lambda: capture_owner_record(PoisonDict(raw()))); assert PoisonDict.calls == []


def test_string_and_integer_subclasses_never_compare_hash_or_coerce():
  for field in ["schema", "epoch", "stage"]:
    value = raw(); value[field] = PoisonInt(1) if field == "schema" else PoisonString(value[field]); PoisonInt.calls.clear(); PoisonString.calls.clear()
    invalid(lambda: capture_owner_record(value)); assert PoisonInt.calls == [] and PoisonString.calls == []
  for field in ["pid", "ppid", "pgid", "uid", "platform", "boot_id", "namespace", "start_time"]:
    value = raw(); current = value["controller"][field]; value["controller"][field] = PoisonInt(current) if type(current) is int else PoisonString(current); PoisonInt.calls.clear(); PoisonString.calls.clear()
    invalid(lambda: capture_owner_record(value)); assert PoisonInt.calls == [] and PoisonString.calls == []


def test_encode_revalidates_exact_classes_and_mutated_slots_without_foreign_getters():
  record = capture_owner_record(raw("bound", process(11)))
  invalid(lambda: encode_owner_record(replace(record, schema=True)))
  invalid(lambda: encode_owner_record(replace(record, writer=replace(record.writer, pid=record.controller.pid))))
  invalid(lambda: encode_owner_record(replace(record, epoch=PoisonString("b" * 64))))
  class Foreign:
    reads = []
    def __getattribute__(self, name): type(self).reads.append(name); raise RuntimeError(SECRET)
  invalid(lambda: encode_owner_record(Foreign())); assert Foreign.reads == []
  invalid(lambda: encode_owner_record(replace(record, controller=Foreign()))); assert Foreign.reads == []
  invalid(lambda: encode_owner_record(replace(record, storage_identity=Foreign()))); assert Foreign.reads == []
  class OtherRecord(OwnerRecord):
    def __getattribute__(self, name): Foreign.reads.append(name); raise RuntimeError(SECRET)
  other = object.__new__(OtherRecord); invalid(lambda: encode_owner_record(other)); assert Foreign.reads == []


def test_uninitialized_exact_dataclasses_are_fixed_invalid_not_raw_attribute_error():
  invalid(lambda: encode_owner_record(object.__new__(OwnerRecord)))
  record = capture_owner_record(raw())
  invalid(lambda: encode_owner_record(replace(record, controller=object.__new__(LinuxProcessIdentity))))
  invalid(lambda: encode_owner_record(replace(record, storage_identity=object.__new__(StorageIdentity))))


def test_bytes_subclass_and_class_identity_poison_never_execute():
  class PoisonBytes(bytes):
    calls = []
    def __len__(self): self.calls.append("len"); raise RuntimeError(SECRET)
    def decode(self, *args, **kwargs): self.calls.append("decode"); raise RuntimeError(SECRET)
  invalid(lambda: decode_owner_record(PoisonBytes(b"{}"))); assert PoisonBytes.calls == []
  class FakeRecord:
    calls = []
    @property
    def __class__(self): self.calls.append("class"); raise RuntimeError(SECRET)
    def __iter__(self): self.calls.append("iter"); raise RuntimeError(SECRET)
  invalid(lambda: capture_owner_record(FakeRecord())); invalid(lambda: encode_owner_record(FakeRecord())); assert FakeRecord.calls == []


def test_encode_all_classes_and_mutated_fields_are_revalidated():
  base = capture_owner_record(raw("bound", process(11)))
  for record in [replace(base, deployment_identity="short"), replace(base, stage="acquired"), replace(base, storage_identity=StorageIdentity(0, 0)),
      replace(base, controller=replace(base.controller, platform="darwin")), replace(base, controller=replace(base.controller, pid=True)),
      replace(base, writer=replace(base.writer, uid=999)), replace(base, writer=replace(base.writer, namespace="pid:[00]")),
      replace(base, writer=replace(base.writer, start_time=str(2**64)))]:
    invalid(lambda: encode_owner_record(record))
  object.__setattr__(base, "schema", PoisonInt(1)); PoisonInt.calls.clear(); invalid(lambda: encode_owner_record(base)); assert PoisonInt.calls == []


def test_nested_class_subtypes_rejected_before_reading_any_slots():
  calls = []
  class OtherStorage(StorageIdentity):
    def __getattribute__(self, name): calls.append(name); raise RuntimeError(SECRET)
  class OtherProcess(LinuxProcessIdentity):
    def __getattribute__(self, name): calls.append(name); raise RuntimeError(SECRET)
  base = capture_owner_record(raw("bound", process(11)))
  for record in [replace(base, storage_identity=object.__new__(OtherStorage)), replace(base, controller=object.__new__(OtherProcess)), replace(base, writer=object.__new__(OtherProcess))]: invalid(lambda: encode_owner_record(record))
  assert calls == []


def test_full_data_privacy_on_decode_and_unicode_forms():
  for value in [b'{"password":"' + SECRET.encode() + b'",', b'{"controller":{"password":"' + SECRET.encode() + b'","password":1}}']:
    error = invalid(lambda: decode_owner_record(value)); assert not any(isinstance(arg, BaseException) for arg in error.args)
  for field in ["epoch", "deployment_identity"]:
    value = raw(); value[field] = "\ud800" * 64; invalid(lambda: capture_owner_record(value))
  value = raw(); value["controller"]["namespace"] = "pid:[١]"; invalid(lambda: capture_owner_record(value))


def test_nested_dict_subclasses_and_mutable_input_do_not_share_children():
  for field in ["controller", "writer", "storage_identity"]:
    value = raw("bound", process(11)); value[field] = PoisonDict(value[field]); PoisonDict.calls.clear(); invalid(lambda: capture_owner_record(value)); assert PoisonDict.calls == []
  value = raw("ready", process(11)); record = capture_owner_record(value); value["controller"].clear(); value["writer"].clear(); value["storage_identity"].clear()
  assert decode_owner_record(encode_owner_record(record)) == record


@pytest.mark.parametrize("case", ["capture-shape", "decode-json", "decode-type", "encode-type", "encode-slots", "encode-revalidate"])
def test_ambient_caller_exception_never_becomes_codec_context(case):
  import traceback
  operation = {
    "capture-shape": lambda: capture_owner_record({}),
    "decode-json": lambda: decode_owner_record(b"{bad"),
    "decode-type": lambda: decode_owner_record("invalid"),
    "encode-type": lambda: encode_owner_record({}),
    "encode-slots": lambda: encode_owner_record(object.__new__(OwnerRecord)),
    "encode-revalidate": lambda: encode_owner_record(replace(capture_owner_record(raw()), schema=True)),
  }[case]
  try:
    raise RuntimeError(SECRET)
  except RuntimeError as caller_error:
    with pytest.raises(Conflict) as caught: operation()
    codec_error = caught.value
    assert type(codec_error) is Conflict
    assert codec_error.args == ("Durable所有者记录无效",)
    assert codec_error.__context__ is None
    assert codec_error.__cause__ is None
    assert SECRET not in "".join(traceback.format_exception(codec_error))
    # 外来 caller exception 不被 codec 改动或当成自己的错误清理。
    assert caller_error.args == (SECRET,)
    assert caller_error.__context__ is None and caller_error.__cause__ is None
