"""纯 frame/metadata 合成检查；无 pipe/锁/proc/进程/SDK。"""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import traceback

import pytest
from agentcfg.pi_durable_owner_message import OwnerMessage, capture_owner_message, decode_owner_message_frame, encode_owner_message_frame
from agentcfg.pi_durable_owner_record import StorageIdentity, LinuxProcessIdentity, OwnerRecord
from agentcfg.storage import Conflict

SECRET = "SYNTHETIC_OWNER_MESSAGE_SECRET"
FIXTURE = Path(__file__).parent / "fixtures/pi/durable-owner-message-codec/vectors.json"
VECTORS = json.loads(FIXTURE.read_text())["vectors"]


def raw(kind="bind"): return deepcopy(next(value["value"] for value in VECTORS if value["name"] == kind + "_minimal"))
def frame(text):
  data = text.encode("utf-8") if type(text) is str else text
  return len(data).to_bytes(4, "big") + data

def invalid(call):
  with pytest.raises(Conflict) as caught: call()
  error = caught.value
  assert type(error) is Conflict and error.args == ("Durable所有者消息无效",)
  assert error.__context__ is None and error.__cause__ is None and not hasattr(error, "doc")
  assert SECRET not in "".join(traceback.format_exception(error))


@pytest.mark.parametrize("vector", VECTORS, ids=lambda value: value["name"])
def test_shared_wire_bytes_all_five_and_u64_without_rounding(vector):
  value = vector["value"]; message = capture_owner_message(value); encoded = bytes.fromhex(vector["hex"])
  assert encode_owner_message_frame(message) == encoded
  assert decode_owner_message_frame(encoded) == message
  assert message.writer_lock_verified is False and message.database_allowed is False and message.can_take_over is False
  assert type(message.lock_identity) is StorageIdentity
  if message.record:
    assert type(message.record) is OwnerRecord and type(message.record.writer) is LinuxProcessIdentity
    assert message.record.storage_identity.inode != message.lock_identity.inode
  if vector["name"].endswith("u64_max"):
    assert message.lock_identity.device == 2**64-1
    assert (message.writer or message.record.writer).start_time == str(2**64-1)
  assert encoded[4:] == json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def test_independent_frozen_slots_and_exact_encoder_types():
  source = raw(); message = capture_owner_message(source); original = encode_owner_message_frame(message)
  source["record"]["controller"]["pid"] = 99; source["lock_identity"]["inode"] = "99"
  assert encode_owner_message_frame(message) == original
  for value, field in [(message, "type"), (message.lock_identity, "inode"), (message.record, "stage"), (message.record.writer, "pid")]:
    with pytest.raises(FrozenInstanceError): setattr(value, field, 1)
    assert not hasattr(value, "__dict__")
  for wrong in [raw(), object(), None, object.__new__(OwnerMessage)]: invalid(lambda: encode_owner_message_frame(wrong))
  invalid(lambda: encode_owner_message_frame(replace(message, writer=message.record.writer)))
  invalid(lambda: encode_owner_message_frame(replace(message, descriptor_closed=True)))
  invalid(lambda: encode_owner_message_frame(replace(message, lock_identity=StorageIdentity(True, 1))))
  invalid(lambda: encode_owner_message_frame(replace(message, record=replace(message.record, writer=None))))
  invalid(lambda: encode_owner_message_frame(replace(message, schema=True)))


@pytest.mark.parametrize("kind", ["hello", "bind", "bound", "close", "closed"])
def test_closed_root_and_applicable_flags(kind):
  value = raw(kind)
  for key in list(value):
    missing = deepcopy(value); missing.pop(key); invalid(lambda: capture_owner_message(missing))
  for key in ["extra", "writer_lock_verified", "database_allowed", "can_take_over"]:
    other = deepcopy(value); other[key] = True; invalid(lambda: capture_owner_message(other))
  for key in ["schema", "fd"]:
    other = deepcopy(value); other[key] = True; invalid(lambda: capture_owner_message(other))
  other = deepcopy(value); other["descriptor_closed" if kind == "closed" else "close_on_exec"] = False; invalid(lambda: capture_owner_message(other))
  if kind != "hello":
    for stage in ["acquired", "ready", "released", "closing" if kind in ("bind", "bound") else "bound"]:
      other = deepcopy(value); other["record"]["stage"] = stage; invalid(lambda: capture_owner_message(other))


@pytest.mark.parametrize("bad", ["00", "01", "+1", "-1", "1.0", " 1", "1\n", "١", str(2**64), 1, True])
def test_decimal_string_fields_reject_noncanonical_and_u64_overflow(bad):
  for target in ["lock_identity", "storage_identity"]:
    value = raw(); location = value[target] if target == "lock_identity" else value["record"][target]; location["device"] = bad
    invalid(lambda: capture_owner_message(value))


@pytest.mark.parametrize("location,field,bad", [
  ("controller", "pid", 0), ("writer", "pid", 2**31), ("writer", "uid", 2**32-1), ("writer", "uid", True),
  ("writer", "ppid", -1), ("writer", "start_time", str(2**64)), ("writer", "namespace", "pid:[0]"), ("writer", "boot_id", "bad"),
])
def test_linux_identity_boundaries(location, field, bad):
  value = raw(); value["record"][location][field] = bad; invalid(lambda: capture_owner_message(value))


@pytest.mark.parametrize("mutation", ["same-pid", "uid", "boot", "no-writer", "unknown-process", "unknown-record"])
def test_record_identity_relationship_and_unknown_fields(mutation):
  value = raw(); record = value["record"]
  if mutation == "same-pid": record["writer"]["pid"] = record["controller"]["pid"]
  if mutation == "uid": record["writer"]["uid"] += 1
  if mutation == "boot": record["writer"]["boot_id"] = "ffffffff-ffff-ffff-ffff-ffffffffffff"
  if mutation == "no-writer": record["writer"] = None
  if mutation == "unknown-process": record["writer"]["extra"] = 0
  if mutation == "unknown-record": record["extra"] = 0
  invalid(lambda: capture_owner_message(value))


@pytest.mark.parametrize("token", ["1.0", "1e0", "-0", "-1", "NaN", "Infinity", "1e999", "9007199254740992"])
def test_wire_numeric_lexical_rules_before_json_normalization(token):
  text = json.dumps(raw("hello"), separators=(",", ":")).replace('"schema":1', '"schema":' + token)
  invalid(lambda: decode_owner_message_frame(frame(text)))


@pytest.mark.parametrize("cut", ["root", "record", "process", "storage"])
def test_decoded_duplicates_including_escaped_keys_at_every_level(cut):
  text = json.dumps(raw(), separators=(",", ":"))
  if cut == "root": text = text.replace('"fd":3', '"fd":2,"\\u0066d":3')
  if cut == "record": text = text.replace('"stage":"bound"', '"stage":"ready","st\\u0061ge":"bound"')
  if cut == "process": text = text.replace('"pid":10', '"pid":9,"\\u0070id":10')
  if cut == "storage": text = text.replace('"inode":"1"', '"inode":"2","\\u0069node":"1"')
  invalid(lambda: decode_owner_message_frame(frame(text)))


@pytest.mark.parametrize("bad", [b"", b"\x00\x00\x00\x00", b"\x00\x00\x10\x01"+b" "*4097, b"\x00\x00\x00\x01", b"\xff", bytearray(b"{}"), memoryview(b"{}"), "{}"])
def test_frame_exact_type_size_prefix_truncation(bad): invalid(lambda: decode_owner_message_frame(bad))


def test_multiple_extra_and_bad_utf8_bom_surrogate_resources():
  valid = bytes.fromhex(VECTORS[0]["hex"])
  for bad in [valid+valid, valid+b"x", frame(b"\xff"), frame(b"\xef\xbb\xbf"+valid[4:]), frame(b"\xfe\xff"+'{}'.encode("utf-16-be"))]: invalid(lambda: decode_owner_message_frame(bad))
  for value in [{"x": []}, {"x": "\ud800"}, {"x": "x"*129}, {"x": {"x": {"x": {"x": 0}}}}, {str(i): 0 for i in range(65)}]: invalid(lambda: capture_owner_message(value))
  invalid(lambda: decode_owner_message_frame(frame('{"x":"\\ud800"}')))
  invalid(lambda: decode_owner_message_frame(frame('{"x":'+ '['*10+'0'+']'*10+'}')))


def test_whitespace_and_key_order_are_valid_but_encoder_is_canonical():
  value = raw(); text = " \n\t" + json.dumps(value, indent=1) + "\r\n "
  message = decode_owner_message_frame(frame(text)); assert encode_owner_message_frame(message) == bytes.fromhex(VECTORS[1]["hex"])


def test_foreign_hooks_never_run_and_ambient_errors_cleared():
  calls = []
  class Poison:
    def __getattribute__(self, name): calls.append(name); raise RuntimeError(SECRET)
  class Key(str):
    def __hash__(self): calls.append("hash"); return super().__hash__()
    def __eq__(self, other): calls.append("eq"); raise RuntimeError(SECRET)
  class Payload(bytes):
    def __len__(self): calls.append("len"); raise RuntimeError(SECRET)
    def decode(self, *args): calls.append("decode"); raise RuntimeError(SECRET)
  foreign = {Key("schema"): 1}; calls.clear()
  class Wrong(dict):
    def items(self): calls.append("items"); raise RuntimeError(SECRET)
  tests = [lambda: capture_owner_message(Poison()), lambda: capture_owner_message(foreign), lambda: capture_owner_message(Wrong()),
    lambda: capture_owner_message({"schema": Poison()}), lambda: decode_owner_message_frame(Payload(b"12345")), lambda: encode_owner_message_frame(Poison()),
    lambda: encode_owner_message_frame(object.__new__(OwnerMessage)), lambda: decode_owner_message_frame(frame('{"secret":'))]
  for call in tests:
    try: raise RuntimeError(SECRET)
    except RuntimeError: invalid(call)
  assert calls == []


def test_inode_zero_is_not_device_zero_and_namespace_is_not_authority():
  for location in ["lock_identity", "storage_identity"]:
    value = raw(); target = value[location] if location == "lock_identity" else value["record"][location]; target["inode"] = "0"
    invalid(lambda: capture_owner_message(value))
  value = raw(); value["record"]["writer"]["namespace"] = "pid:[2]"
  message = capture_owner_message(value)
  assert message.record.writer.namespace == "pid:[2]" and message.database_allowed is False
  invalid(lambda: encode_owner_message_frame(replace(message, close_on_exec=None)))
