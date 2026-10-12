"""初始化纯wire/frame；合成元数据不签发grant，不调用真实pipe或宿主。"""

from copy import deepcopy
from dataclasses import FrozenInstanceError, fields, replace
import json
import traceback

import pytest

from agentcfg import pi_durable_init_message as codec
from agentcfg import pi_durable_registration_record as registration_codec
from agentcfg import pi_durable_owner_record as owner_codec
from agentcfg.storage import Conflict


TOKEN = "0123456789abcdef" * 4
SECRET = "SYNTHETIC_PRIVATE_SOURCE"
U64 = 2**64 - 1
KINDS = ("slot", "offer", "offer-ack", "fresh-storage", "acquired", "registered", "registered-ack", "release", "release-ack")


def process():
  return {"platform": "linux", "boot_id": "01234567-89ab-cdef-0123-456789abcdef", "pid": 10, "ppid": 0,
    "pgid": 10, "start_time": "0", "namespace": "pid:[1]", "uid": 1000}


def registration(stage):
  return {"schema": 1, "platform": "linux", "service_id": "f" * 64, "stage": stage,
    "account_home": "/synthetic/账户", "account_identity": {"device": 0, "inode": 1, "uid": 1000},
    "index_identity": {"device": 2, "inode": 3, "uid": 1000},
    "initial_binding": {"machine": "fixture", "local": "/synthetic/local.toml", "profile": "pi-full"},
    "initial_instance": "/synthetic/instance", "initial_state_root": "/synthetic/state",
    "storage_path": "/synthetic/state/durable/storage",
    "storage_identity": None if stage == "reserved" else {"device": 0, "inode": 17}, "initial_deployment_identity": "7" * 64}


def owner():
  return {"schema": 1, "deployment_identity": "7" * 64, "storage_identity": {"device": 0, "inode": 17},
    "epoch": "8" * 64, "controller": process(), "writer": None, "stage": "acquired"}


def wire(kind):
  if kind == "slot": return {"schema": 1, "type": kind, "controller": process(), "slot_identity": {"device": 0, "inode": 1}, "fd": 3, "close_on_exec": True}
  value = {"schema": 1, "type": kind, "context_id": "a" * 64, "token": TOKEN}
  if kind in ("offer", "offer-ack"):
    value.update(initialization_request_id="b" * 64, initialization_identity="c" * 64, source_identity="d" * 64,
      policy_digest="e" * 64, policy_generation=0, cancel_generation=0, deadline_monotonic_ns=1)
  elif kind == "fresh-storage":
    value.update(registration=registration("reserved"), index_generation=1, initialization_request_id="b" * 64, initialization_identity="c" * 64)
  elif kind == "acquired":
    value.update(service_id="f" * 64, reserved_registration_identity="1" * 64, record=owner(),
      lock_identity={"device": 2, "inode": 3}, fd=3, close_on_exec=True)
  elif kind == "registered":
    value.update(registration=registration("registered"), index_generation=2,
      reserved_registration_identity="1" * 64, acquired_record_identity="2" * 64)
  else: value.update(service_id="f" * 64, index_generation=2, registration_identity="3" * 64, acquired_record_identity="2" * 64)
  return value


def payload(value):
  return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def frame(raw):
  if type(raw) is str: raw = raw.encode("utf-8")
  return len(raw).to_bytes(4, "big") + raw


def invalid(action):
  try: raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Conflict) as caught: action()
  error = caught.value
  assert type(error) is Conflict and error.args == ("Durable初始化消息无效",)
  assert error.__cause__ is None and error.__context__ is None and not hasattr(error, "doc")
  rendered = "".join(traceback.format_exception(error))
  assert SECRET not in rendered and TOKEN not in rendered
  return error


def captured(kind):
  return codec.capture_init_message(wire(kind))


@pytest.mark.parametrize("kind", KINDS)
def test_nine_independent_canonical_frames_and_false_facade(kind):
  value = wire(kind); message = codec.capture_init_message(value)
  expected = frame(payload(value))
  assert codec.encode_init_message_frame(message) == expected
  assert codec.decode_init_message_frame(expected) == message
  assert expected[4:] == payload(value) and not expected.endswith(b"\n")
  assert type(message) is codec.InitMessage and not hasattr(message, "__dict__")
  assert all(getattr(message, flag) is False for flag in ("writer_lock_verified", "database_allowed", "can_take_over"))
  if kind != "slot": assert TOKEN not in repr(message) and "token=" not in repr(message)
  for field in fields(message):
    if field.name not in value: assert getattr(message, field.name) is None
  with pytest.raises(FrozenInstanceError): message.type = "release"
  if kind == "acquired": assert message.lock_identity != message.record.storage_identity
  if "registration" in value:
    assert type(message.registration) is registration_codec.ServiceRegistration
    original = registration_codec.encode_service_registration(message.registration)
    assert original.endswith(b"\n") and payload(value["registration"]) == original[:-1]
  if "record" in value:
    assert type(message.record) is owner_codec.OwnerRecord
    assert payload(value["record"]) == owner_codec.encode_owner_record(message.record)[:-1]


@pytest.mark.parametrize("kind", KINDS)
def test_exact_top_keys_missing_extra_and_inactive_dto_fields(kind):
  baseline = captured(kind); value = wire(kind)
  for field in value:
    changed = deepcopy(value); changed.pop(field)
    invalid(lambda: codec.capture_init_message(changed))
  for field in ("unknown", "approved", "writer_lock_verified", "database_allowed", "can_take_over"):
    changed = deepcopy(value); changed[field] = True
    invalid(lambda: codec.capture_init_message(changed))
  for field in fields(baseline):
    if field.name not in value:
      invalid(lambda: codec.encode_init_message_frame(replace(baseline, **{field.name: SECRET})))


@pytest.mark.parametrize("kind", ["slot", "fresh-storage", "acquired", "registered"])
def test_deep_input_and_public_dto_independence(kind):
  value = wire(kind); message = codec.capture_init_message(value); encoded = codec.encode_init_message_frame(message)
  if kind == "slot": value["controller"]["pid"] = 90; value["slot_identity"]["device"] = 90
  elif kind == "acquired": value["record"]["controller"]["pid"] = 90; value["record"]["storage_identity"]["inode"] = 90
  else: value["registration"]["initial_binding"]["machine"] = "changed"; value["registration"]["account_identity"]["inode"] = 90
  assert codec.encode_init_message_frame(message) == encoded
  clone = codec.decode_init_message_frame(encoded)
  if message.registration is not None: assert clone.registration is not message.registration and clone.registration.initial_binding is not message.registration.initial_binding
  if message.record is not None: assert clone.record is not message.record and clone.record.controller is not message.record.controller
  if message.controller is not None: assert clone.controller is not message.controller


@pytest.mark.parametrize("kind", KINDS)
def test_schema_type_and_fd_flags_are_exact(kind):
  for field, bad in [("schema", True), ("schema", 2), ("type", "unknown"), ("type", None)]:
    value = wire(kind); value[field] = bad; invalid(lambda: codec.capture_init_message(value))
  if kind in ("slot", "acquired"):
    for field, bad in [("fd", True), ("fd", 4), ("close_on_exec", 1), ("close_on_exec", False)]:
      value = wire(kind); value[field] = bad; invalid(lambda: codec.capture_init_message(value))


@pytest.mark.parametrize("field", ["context_id", "token", "initialization_request_id", "initialization_identity", "source_identity", "policy_digest"])
@pytest.mark.parametrize("bad", ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "界" * 64, True, None])
def test_offer_fixed_opaque_and_digest_formats(field, bad):
  value = wire("offer"); value[field] = bad
  invalid(lambda: codec.capture_init_message(value))


@pytest.mark.parametrize("kind,field", [("acquired", "service_id"), ("acquired", "reserved_registration_identity"),
  ("registered", "reserved_registration_identity"), ("registered", "acquired_record_identity"),
  ("registered-ack", "registration_identity"), ("release", "acquired_record_identity")])
def test_remaining_hash_fields_are_exact(kind, field):
  value = wire(kind); value[field] = "A" * 64; invalid(lambda: codec.capture_init_message(value))


@pytest.mark.parametrize("field,minimum", [("policy_generation", 0), ("cancel_generation", 0), ("deadline_monotonic_ns", 1)])
def test_unsigned_python_u64_not_node_safe53_and_positive_deadline(field, minimum):
  value = wire("offer")
  for valid in (minimum, 2**53, U64):
    value[field] = valid
    message = codec.capture_init_message(value)
    assert getattr(codec.decode_init_message_frame(codec.encode_init_message_frame(message)), field) == valid
  for bad in (True, -1, U64 + 1, 1.0, "1", minimum - 1):
    value[field] = bad; invalid(lambda: codec.capture_init_message(value))


@pytest.mark.parametrize("kind", ["fresh-storage", "registered", "registered-ack", "release", "release-ack"])
def test_index_generation_range(kind):
  value = wire(kind); value["index_generation"] = U64
  assert codec.decode_init_message_frame(codec.encode_init_message_frame(codec.capture_init_message(value))).index_generation == U64
  for bad in (True, 0, -1, U64 + 1, 1.0):
    value["index_generation"] = bad; invalid(lambda: codec.capture_init_message(value))


@pytest.mark.parametrize("where", ["slot_identity", "lock_identity"])
@pytest.mark.parametrize("field,bad", [("device", True), ("device", -1), ("device", U64 + 1), ("inode", 0), ("inode", U64 + 1), ("extra", 1)])
def test_s_range_and_exact_keys(where, field, bad):
  value = wire("slot" if where == "slot_identity" else "acquired"); value[where][field] = bad
  invalid(lambda: codec.capture_init_message(value))


def test_original_process_and_pair_maxima():
  value = wire("slot")
  value["controller"] = {"platform": "linux", "boot_id": "ffffffff-ffff-ffff-ffff-ffffffffffff", "pid": 2**31-1,
    "ppid": 2**31-1, "pgid": 2**31-1, "uid": 2**32-2, "start_time": str(U64), "namespace": "pid:[" + str(U64) + "]"}
  value["slot_identity"] = {"device": U64, "inode": U64}
  assert len(payload(value["controller"])) == 216 and len(payload(value["slot_identity"])) == 60
  assert len(codec.encode_init_message_frame(codec.capture_init_message(value))) == 365


@pytest.mark.parametrize("field,bad", [("platform", "darwin"), ("boot_id", "01234567-89AB-cdef-0123-456789abcdef"),
  ("pid", 0), ("pid", 2**31), ("pid", True), ("ppid", -1), ("pgid", 0), ("uid", 2**32-1),
  ("start_time", "00"), ("start_time", str(U64 + 1)), ("start_time", 1), ("namespace", "pid:[0]"),
  ("namespace", "pid:[01]"), ("namespace", "pid:[" + str(U64 + 1) + "]"), ("extra", 1)])
def test_process_primitive_domain_without_fake_owner_record(field, bad):
  value = wire("slot"); value["controller"][field] = bad
  invalid(lambda: codec.capture_init_message(value))


@pytest.mark.parametrize("kind", ["fresh-storage", "registered"])
def test_full_registration_stage_and_public_capture_then_encode_bound(kind):
  value = wire(kind); original = codec.capture_init_message(value)
  value["registration"] = registration("registered" if kind == "fresh-storage" else "reserved")
  registration_codec.encode_service_registration(registration_codec.capture_service_registration(value["registration"]))
  invalid(lambda: codec.capture_init_message(value))
  invalid(lambda: codec.encode_init_message_frame(replace(original, registration=registration_codec.capture_service_registration(value["registration"]))))


@pytest.mark.parametrize("stage,writer", [("bound", process() | {"pid": 11}), ("closing", None), ("released", None)])
def test_owner_valid_record_wrong_init_stage_is_not_allowed(stage, writer):
  value = wire("acquired"); value["record"].update(stage=stage, writer=writer)
  owner_codec.encode_owner_record(owner_codec.capture_owner_record(value["record"]))
  invalid(lambda: codec.capture_init_message(value))


@pytest.mark.parametrize("path", ["/", "relative", "/a/../b", "/a\\b", "/a\x00b", "/a\ud800", "/" + "😀" * 1024])
def test_original_registration_path_rule_not_4096_character_approximation(path):
  value = wire("fresh-storage"); value["registration"]["account_home"] = path
  invalid(lambda: codec.capture_init_message(value))


def test_quote_astral_and_lexical_delimiters_inside_strings():
  value = wire("fresh-storage")
  value["registration"]["account_home"] = "/" + "😀" * 1023
  value["registration"]["initial_binding"]["local"] = '/synthetic/"{}[]quote'
  message = codec.capture_init_message(value)
  assert codec.decode_init_message_frame(codec.encode_init_message_frame(message)) == message
  value["registration"]["account_home"] = "/" + '"' * 4095
  assert codec.decode_init_message_frame(codec.encode_init_message_frame(codec.capture_init_message(value))).registration.account_home == value["registration"]["account_home"]


def test_registration_capture_can_be_valid_but_original_encoder_overflows():
  value = wire("fresh-storage"); record = value["registration"]; path = "/" + '"' * 4079
  for name in ("account_home", "initial_instance", "initial_state_root"): record[name] = path
  record["initial_binding"]["local"] = path; record["storage_path"] = path + "/durable/storage"
  original = registration_codec.capture_service_registration(record)
  with pytest.raises(Conflict): registration_codec.encode_service_registration(original)
  invalid(lambda: codec.capture_init_message(value))
  invalid(lambda: codec.encode_init_message_frame(replace(captured("fresh-storage"), registration=original)))


def test_canonical_overhead_independent_arithmetic_and_body_not_double_escaped():
  expected = {"slot": 361, "offer": 665, "offer-ack": 669, "fresh-storage": 434, "acquired": 480,
    "registered": 437, "registered-ack": 496, "release": 489, "release-ack": 493}
  for kind in KINDS:
    value = wire(kind)
    for key, child in value.items():
      if type(child) is str and key != "type": value[key] = "f" * 64
      elif type(child) is int and key not in ("schema", "fd"): value[key] = U64
    if kind == "slot":
      value["controller"] = {"platform": "linux", "boot_id": "ffffffff-ffff-ffff-ffff-ffffffffffff", "pid": 2**31-1,
        "ppid": 2**31-1, "pgid": 2**31-1, "uid": 2**32-2, "start_time": str(U64), "namespace": "pid:[" + str(U64) + "]"}
      value["slot_identity"] = {"device": U64, "inode": U64}
    if kind == "acquired": value["lock_identity"] = {"device": U64, "inode": U64}
    nested = "registration" if kind in ("fresh-storage", "registered") else "record" if kind == "acquired" else None
    actual = codec.encode_init_message_frame(codec.capture_init_message(value))[4:]
    if nested:
      body = payload(value[nested]); original = deepcopy(value); original[nested] = {}
      # 空对象只算constant shell；从未传给codec作为合法record。
      overhead = len(payload(original)) - 2
      assert overhead == expected[kind] and len(actual) == overhead + len(body)
      assert actual == payload(value) and b'"' + nested.encode() + b'":{' in actual
    else: assert len(actual) == expected[kind]
  assert 437 + 32767 == 33204 and 33204 < 65536


@pytest.mark.parametrize("kind", ["slot", "offer", "fresh-storage", "acquired", "registered"])
def test_reordered_whitespace_exact_raw_limit_and_canonical_output(kind):
  value = wire(kind); expected = captured(kind)
  text = json.dumps(dict(reversed(list(value.items()))), ensure_ascii=False, indent=2).encode()
  assert codec.decode_init_message_frame(frame(text)) == expected
  padded = text + b" " * (65536 - len(text))
  assert codec.decode_init_message_frame(frame(padded)) == expected
  invalid(lambda: codec.decode_init_message_frame(frame(padded + b" ")))
  assert codec.encode_init_message_frame(codec.decode_init_message_frame(frame(text))) == frame(payload(value))


@pytest.mark.parametrize("bad", [b"", b"\x00\x00\x00\x00", b"\x00\x01\x00\x01" + b" " * 65537,
  b"\x00\x00\x00\x01", b"x", bytearray(b"{}"), memoryview(b"{}"), "{}"])
def test_prefix_length_and_native_bytes(bad):
  invalid(lambda: codec.decode_init_message_frame(bad))


def test_extra_frames_utf8_bom_and_json_grammar():
  valid = frame(payload(wire("offer")))
  for bad in (valid + b"x", valid + valid, frame(b"\xff"), frame(b"\xef\xbb\xbf{}"), frame(b"{} {}"), frame(b"null")):
    invalid(lambda: codec.decode_init_message_frame(bad))
  for text in ('{"x":"\\ud800"}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}'):
    invalid(lambda: codec.decode_init_message_frame(frame(text)))


@pytest.mark.parametrize("number", ["1.0", "1e0", "-0", "-1", "+1", "01", "18446744073709551616", "9" * 1000])
def test_numeric_lexemes_before_normalization(number):
  text = payload(wire("offer")).decode().replace('"policy_generation":0', '"policy_generation":' + number)
  invalid(lambda: codec.decode_init_message_frame(frame(text)))


@pytest.mark.parametrize("kind,duplicate", [("offer", '"schema":1'), ("slot", '"pid":10'),
  ("fresh-storage", '"machine":"fixture"'), ("registered", '"inode":17'), ("acquired", '"epoch":"' + "8" * 64 + '"')])
def test_duplicate_keys_each_layer_and_escaped_key_alias(kind, duplicate):
  text = payload(wire(kind)).decode()
  key, rest = duplicate.split(":", 1)
  escaped = key[0] + "\\u" + format(ord(key[1]), "04x") + key[2:]
  changed = text.replace(duplicate, duplicate + "," + escaped + ":" + rest, 1)
  invalid(lambda: codec.decode_init_message_frame(frame(changed)))


@pytest.mark.parametrize("text", ['{"x":[]}', '{"x":{ "x":{ "x":{} }}}',
  '{"a":{},"b":{},"c":{},"d":{},"e":{},"f":{}}'])
def test_lexical_resource_refusal_before_json_parser(text, monkeypatch):
  original = codec._LOADS; calls = []
  def load(*args, **kwargs): calls.append("load"); return original(*args, **kwargs)
  monkeypatch.setattr(codec, "_LOADS", load)
  assert codec.decode_init_message_frame(frame(payload(wire("slot")))).type == "slot"
  calls.clear()
  invalid(lambda: codec.decode_init_message_frame(frame(text)))
  assert calls == []


def test_capture_resource_guards_before_foreign_or_serialization():
  for value in ({str(i): 0 for i in range(12)}, {"type": "offer", "x": "a" * 4097}, {"x": {str(i): 0 for i in range(14)}},
    {"x": {"x": {"x": {}}}}, {"x": []}, {"x": {"x": None}, "y": tuple()}):
    invalid(lambda: codec.capture_init_message(value))


def test_foreign_hooks_type_first_across_wire_and_dto():
  calls = []; armed = False
  class Text(str):
    def __hash__(self):
      if armed: calls.append("hash"); raise AssertionError()
      return str.__hash__(self)
    def __eq__(self, other): calls.append("eq"); raise AssertionError()
    def __repr__(self): calls.append("repr"); raise AssertionError()
  class Number(int):
    def __le__(self, other): calls.append("le"); raise AssertionError()
  class Mapping(dict):
    def items(self): calls.append("items"); raise AssertionError()
  class Foreign:
    def __getattribute__(self, name): calls.append(name); raise AssertionError()
  keyed = {Text("type"): "offer"}; armed = True
  invalid(lambda: codec.capture_init_message(keyed))
  invalid(lambda: codec.capture_init_message(Mapping()))
  for field, bad in [("type", Text("offer")), ("token", Text(TOKEN)), ("policy_generation", Number(1)), ("source_identity", Foreign())]:
    value = wire("offer"); value[field] = bad; invalid(lambda: codec.capture_init_message(value))
  invalid(lambda: codec.encode_init_message_frame(Foreign()))
  for kind, field in [("slot", "controller"), ("slot", "slot_identity"), ("acquired", "record"),
    ("acquired", "lock_identity"), ("fresh-storage", "registration")]:
    invalid(lambda: codec.encode_init_message_frame(replace(captured(kind), **{field: Foreign()})))
  invalid(lambda: codec.encode_init_message_frame(replace(captured("offer"), registration=Foreign())))
  assert calls == []


@pytest.mark.parametrize("kind,field,cls", [("slot", "controller", owner_codec.LinuxProcessIdentity),
  ("slot", "slot_identity", owner_codec.StorageIdentity), ("acquired", "record", owner_codec.OwnerRecord),
  ("acquired", "lock_identity", owner_codec.StorageIdentity), ("fresh-storage", "registration", registration_codec.ServiceRegistration)])
def test_uninitialized_active_slots_owned_error(kind, field, cls):
  invalid(lambda: codec.encode_init_message_frame(replace(captured(kind), **{field: object.__new__(cls)})))


def test_uninitialized_union_nested_slots_and_exact_class_only():
  invalid(lambda: codec.encode_init_message_frame(object.__new__(codec.InitMessage)))
  value = captured("offer")
  class Child(codec.InitMessage): pass
  child = Child(**{field.name: getattr(value, field.name) for field in fields(value)})
  invalid(lambda: codec.encode_init_message_frame(child))
  record = replace(captured("registered").registration, initial_binding=object.__new__(registration_codec.InitialBinding))
  invalid(lambda: codec.encode_init_message_frame(replace(captured("registered"), registration=record)))
  record = replace(captured("acquired").record, controller=object.__new__(owner_codec.LinuxProcessIdentity))
  invalid(lambda: codec.encode_init_message_frame(replace(captured("acquired"), record=record)))


@pytest.mark.parametrize("name,kind,action", [("capture_service_registration", "fresh-storage", "capture"),
  ("encode_service_registration", "fresh-storage", "capture"), ("encode_service_registration", "registered", "encode"),
  ("capture_owner_record", "acquired", "capture"), ("encode_owner_record", "acquired", "capture"), ("encode_owner_record", "acquired", "encode")])
def test_public_record_errors_unchanged_fresh_actual_chain(name, kind, action, monkeypatch):
  value = wire(kind); message = captured(kind)
  cause = ValueError("foreign cause"); context = RuntimeError("foreign context"); foreign = RuntimeError(SECRET)
  def fail(value):
    try: raise foreign
    except RuntimeError:
      foreign.__cause__ = cause; foreign.__context__ = context
      raise
  monkeypatch.setattr(codec, name, fail)
  call = (lambda: codec.capture_init_message(value)) if action == "capture" else (lambda: codec.encode_init_message_frame(message))
  first = invalid(call); second = invalid(call)
  assert first is not second and first is not foreign
  assert foreign.args == (SECRET,) and foreign.__cause__ is cause and foreign.__context__ is context


def test_field_and_json_data_never_mint_cross_stage_or_source_permission():
  for kind in KINDS:
    # 同一个合法body可重复纯解码；one-shot/原source/协议stage属于未授权actor，不在DTO里假造。
    data = codec.encode_init_message_frame(captured(kind))
    first, second = codec.decode_init_message_frame(data), codec.decode_init_message_frame(data)
    assert first == second and first is not second
    assert first.writer_lock_verified is False and first.database_allowed is False and first.can_take_over is False
