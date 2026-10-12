"""纯init回复状态/关联；没有真实channel、进程、source或grant。"""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import traceback

import pytest

from agentcfg import pi_durable_init_channel as channel
from agentcfg import pi_durable_init_message as codec
from agentcfg import pi_durable_registration_record as registration_codec
from agentcfg import pi_durable_owner_record as owner_codec
from agentcfg.storage import Conflict
from test_pi_durable_init_message import wire, registration, payload, frame, TOKEN


SECRET = "SYNTHETIC_WINDOW_PRIVATE_SOURCE"
REPLIES = ("slot", "offer-ack", "acquired", "registered-ack", "release-ack")
EXPORTS = (
  (codec, ("InitMessage", "capture_init_message", "encode_init_message_frame", "decode_init_message_frame",
    "ServiceRegistration", "capture_service_registration", "encode_service_registration", "LinuxProcessIdentity",
    "OwnerRecord", "StorageIdentity", "capture_owner_record", "encode_owner_record")),
  (registration_codec, ("ServiceRegistration", "DirectoryIdentity", "InitialBinding", "StorageIdentity",
    "capture_service_registration", "encode_service_registration", "decode_service_registration")),
  (owner_codec, ("OwnerRecord", "LinuxProcessIdentity", "StorageIdentity", "capture_owner_record", "encode_owner_record", "decode_owner_record")),
)
EXPORT_CASES = [(module, name) for module, names in EXPORTS for name in names]
LOCAL_NAMES = ("_message", "_registration", "_owner", "_ENCODE_INIT", "_DECODE_INIT", "_INIT_MESSAGE",
  "_ENCODE_REGISTRATION", "_DECODE_REGISTRATION", "_SERVICE_REGISTRATION", "_LINUX_PROCESS_IDENTITY")


def materials(kind):
  value = wire(kind)
  reserved = registration_codec.capture_service_registration(registration("reserved"))
  controller = codec.capture_init_message(wire("slot")).controller
  if kind == "slot": expected = {"type": kind, "controller": controller}
  elif kind == "offer-ack": expected = {"type": kind, "offer": codec.capture_init_message(wire("offer"))}
  elif kind == "acquired":
    value["reserved_registration_identity"] = hashlib.sha256(registration_codec.encode_service_registration(reserved)).hexdigest()
    expected = {"type": kind, "context_id": value["context_id"], "token": value["token"],
      "service_id": reserved.service_id, "reserved_registration": reserved, "controller": controller}
  else:
    registered = registration_codec.capture_service_registration(registration("registered"))
    acquired = codec.capture_init_message(wire("acquired")).record
    value["registration_identity"] = hashlib.sha256(registration_codec.encode_service_registration(registered)).hexdigest()
    value["acquired_record_identity"] = hashlib.sha256(owner_codec.encode_owner_record(acquired)).hexdigest()
    expected = {"type": kind, "reply": codec.capture_init_message(value)}
  message = codec.capture_init_message(value)
  raw = codec.encode_init_message_frame(message)
  assert codec.decode_init_message_frame(raw) == message
  return expected, value, message, raw


def window_for(kind="offer-ack"):
  expected, value, message, raw = materials(kind)
  window = channel.InitReplyWindow()
  assert window.arm(kind) is None and window.bind(expected) is None
  return window, expected, value, message, raw


def invalid(action):
  try: raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Conflict) as caught: action()
  error = caught.value
  assert type(error) is Conflict and error.args == ("Durable初始化回复窗口无效",)
  assert error.__context__ is None and error.__cause__ is None and not hasattr(error, "doc")
  rendered = "".join(traceback.format_exception(error))
  assert SECRET not in rendered and TOKEN not in rendered
  return error


def stopped(window):
  assert window.has_complete_frame is False
  assert window.writer_lock_verified is False and window.database_allowed is False and window.can_take_over is False
  invalid(lambda: window.arm("slot")); invalid(lambda: window.bind({})); invalid(lambda: window.feed(b"x")); invalid(window.consume)
  assert window.retire() is None and window.retire() is None


@pytest.mark.parametrize("kind", REPLIES)
def test_five_replies_fragmented_and_withheld_until_one_consume(kind):
  window, expected, value, message, raw = window_for(kind)
  assert not hasattr(window, "__dict__") and not hasattr(window, "finish") and not hasattr(window, "end")
  assert TOKEN not in repr(window) and SECRET not in repr(window)
  for index, byte in enumerate(raw):
    assert window.feed(bytes([byte])) is None
    assert window.has_complete_frame is (index == len(raw) - 1)
  actual = window.consume()
  assert actual == message and actual is not message and window.has_complete_frame is False
  assert actual.writer_lock_verified is False and actual.database_allowed is False and actual.can_take_over is False
  invalid(window.consume); stopped(window)


def test_all_header_and_payload_split_points_whitespace_and_order():
  expected, value, message, raw = materials("offer-ack")
  for split in range(1, len(raw)):
    window = channel.InitReplyWindow(); window.arm("offer-ack"); window.bind(expected)
    window.feed(raw[:split]); assert window.has_complete_frame is False
    window.feed(raw[split:]); assert window.consume() == message
  text = json.dumps(dict(reversed(list(value.items()))), indent=1).encode()
  window, _, _, _, _ = window_for()
  window.feed(frame(b" \n" + text + b"\t ")); assert window.consume() == message


def test_slot_arm_without_process_then_bind_before_feed():
  expected, value, message, raw = materials("slot")
  window = channel.InitReplyWindow(); window.arm(reply_type="slot")
  assert window.has_complete_frame is False
  window.bind(expected=expected); window.feed(chunk=raw); assert window.consume() == message
  window = channel.InitReplyWindow(); window.arm("slot")
  invalid(lambda: window.feed(raw)); stopped(window)


@pytest.mark.parametrize("kind", ["slot", "acquired"])
def test_new_results_are_full_metadata_not_guessed_expectations(kind):
  window, _, value, message, _ = window_for(kind)
  if kind == "slot": value["slot_identity"] = {"device": 99, "inode": 101}
  else:
    value["record"]["epoch"] = "9" * 64
    value["record"]["storage_identity"] = {"device": 99, "inode": 101}
    value["lock_identity"] = {"device": 99, "inode": 103}
  new = codec.capture_init_message(value); raw = codec.encode_init_message_frame(new)
  assert codec.decode_init_message_frame(raw) == new
  window.feed(raw); actual = window.consume()
  assert actual == new and actual.database_allowed is False
  if kind == "acquired": assert actual.record.storage_identity != actual.lock_identity


@pytest.mark.parametrize("field", ["platform", "boot_id", "pid", "ppid", "pgid", "start_time", "namespace", "uid"])
def test_slot_complete_process_mismatch(field):
  window, _, value, _, _ = window_for("slot")
  changes = {"platform": "linux", "boot_id": "ffffffff-ffff-ffff-ffff-ffffffffffff", "pid": 11,
    "ppid": 1, "pgid": 11, "start_time": "1", "namespace": "pid:[2]", "uid": 1001}
  if field == "platform":
    # 唯一合法platform是linux；未知platform属于codec层，不造合法关系反例。
    value["controller"][field] = "darwin"
    with pytest.raises(Conflict): codec.capture_init_message(value)
    return
  value["controller"][field] = changes[field]
  message = codec.capture_init_message(value); raw = codec.encode_init_message_frame(message)
  assert codec.decode_init_message_frame(raw) == message
  invalid(lambda: window.feed(raw)); stopped(window)


@pytest.mark.parametrize("field", ["context_id", "token", "service_id", "reserved_registration_identity", "deployment", "controller"])
def test_acquired_each_known_link_with_codec_legal_reply(field):
  window, _, value, _, _ = window_for("acquired")
  if field == "deployment": value["record"]["deployment_identity"] = "6" * 64
  elif field == "controller": value["record"]["controller"]["pid"] += 1
  else: value[field] = "6" * 64
  message = codec.capture_init_message(value); raw = codec.encode_init_message_frame(message)
  assert codec.decode_init_message_frame(raw) == message
  invalid(lambda: window.feed(raw)); stopped(window)


@pytest.mark.parametrize("kind", ["offer-ack", "registered-ack", "release-ack"])
def test_ack_each_active_field_matches_whole_capture(kind):
  expected, value, message, raw = materials(kind)
  for field in value:
    if field in ("schema", "type"): continue
    changed = deepcopy(value)
    changed[field] = changed[field] + 1 if type(changed[field]) is int else "6" * 64
    captured = codec.capture_init_message(changed); mutated = codec.encode_init_message_frame(captured)
    assert codec.decode_init_message_frame(mutated) == captured
    window = channel.InitReplyWindow(); window.arm(kind); window.bind(expected)
    invalid(lambda: window.feed(mutated)); stopped(window)


@pytest.mark.parametrize("wrong_kind", ["slot", "offer", "fresh-storage", "acquired", "registered", "registered-ack", "release", "release-ack"])
def test_wrong_complete_kind_refused_with_public_codec_control(wrong_kind):
  window, _, _, _, _ = window_for("offer-ack")
  message = codec.capture_init_message(wire(wrong_kind)); raw = codec.encode_init_message_frame(message)
  assert codec.decode_init_message_frame(raw) == message
  invalid(lambda: window.feed(raw)); stopped(window)


@pytest.mark.parametrize("state", ["new", "armed", "bound", "partial", "candidate", "consumed", "invalid", "retired"])
def test_retire_legal_in_every_state_idempotent_properties_readonly(state):
  expected, _, _, raw = materials("offer-ack")
  window = channel.InitReplyWindow()
  if state != "new": window.arm("offer-ack")
  if state not in ("new", "armed"): window.bind(expected)
  if state == "partial": window.feed(raw[:2])
  if state in ("candidate", "consumed"): window.feed(raw)
  if state == "consumed": window.consume()
  if state == "invalid": invalid(lambda: window.feed(b""))
  if state == "retired": window.retire()
  for name in ("has_complete_frame", "writer_lock_verified", "database_allowed", "can_take_over", "buffer", "candidate", "expected"):
    with pytest.raises((AttributeError, TypeError)): setattr(window, name, True)
  assert window.retire() is None and window.retire() is None
  stopped(window)


@pytest.mark.parametrize("case", ["arm-twice", "bind-new", "bind-twice", "consume-new", "consume-armed", "consume-partial", "reinit", "empty", "double-consume", "after-candidate"])
def test_wrong_calls_permanently_retire(case):
  expected, _, _, raw = materials("offer-ack"); window = channel.InitReplyWindow()
  if case in ("arm-twice", "consume-armed"): window.arm("offer-ack")
  if case in ("bind-twice", "consume-partial", "empty", "double-consume", "after-candidate"):
    window.arm("offer-ack"); window.bind(expected)
  if case == "consume-partial": window.feed(raw[:4])
  if case in ("double-consume", "after-candidate"): window.feed(raw)
  if case == "double-consume": window.consume()
  actions = {"arm-twice": lambda: window.arm("slot"), "bind-new": lambda: window.bind(expected),
    "bind-twice": lambda: window.bind(expected), "consume-new": window.consume, "consume-armed": window.consume,
    "consume-partial": window.consume, "reinit": window.__init__, "empty": lambda: window.feed(b""),
    "double-consume": window.consume, "after-candidate": lambda: window.feed(raw)}
  invalid(actions[case]); stopped(window)


@pytest.mark.parametrize("method,args,kwargs", [("arm", (), {}), ("arm", ("slot", "offer-ack"), {}),
  ("bind", (), {}), ("bind", ({},), {"approved": True}), ("feed", (), {}), ("feed", (b"x", b"y"), {}),
  ("consume", (True,), {}), ("consume", (), {"send_complete": True}), ("retire", (True,), {}),
  ("retire", (), {"eof": True})])
def test_argument_binding_errors_discard_candidate(method, args, kwargs):
  window, _, _, _, raw = window_for(); window.feed(raw)
  invalid(lambda: getattr(window, method)(*args, **kwargs)); stopped(window)


def test_bad_constructor_arity_and_accepted_method_keyword():
  invalid(lambda: channel.InitReplyWindow(True)); invalid(lambda: channel.InitReplyWindow(approved=True))
  expected, _, message, raw = materials("offer-ack")
  window = channel.InitReplyWindow(); window.arm(reply_type="offer-ack"); window.bind(expected=expected); window.feed(chunk=raw)
  assert window.consume() == message


@pytest.mark.parametrize("kind", REPLIES)
def test_expected_exact_keys_types_and_uninitialized_no_wildcards(kind):
  expected, _, _, _ = materials(kind)
  for field in expected:
    bad = dict(expected); bad.pop(field)
    window = channel.InitReplyWindow(); window.arm(kind)
    invalid(lambda: window.bind(bad)); stopped(window)
  for field in expected:
    bad = dict(expected); bad[field] = None
    window = channel.InitReplyWindow(); window.arm(kind)
    invalid(lambda: window.bind(bad)); stopped(window)
  bad = dict(expected); bad["approved"] = True
  window = channel.InitReplyWindow(); window.arm(kind); invalid(lambda: window.bind(bad)); stopped(window)


@pytest.mark.parametrize("case", ["service-id", "registered", "uninitialized", "process", "inactive"])
def test_expected_acquired_registration_and_public_dto_validation(case):
  expected, _, _, _ = materials("acquired")
  if case == "service-id": expected["service_id"] = "6" * 64
  elif case == "registered": expected["reserved_registration"] = registration_codec.capture_service_registration(registration("registered"))
  elif case == "uninitialized": expected["reserved_registration"] = object.__new__(registration_codec.ServiceRegistration)
  elif case == "process": expected["controller"] = object.__new__(owner_codec.LinuxProcessIdentity)
  else: expected = {"type": "offer-ack", "offer": replace(codec.capture_init_message(wire("offer")), registration=registration_codec.capture_service_registration(registration("reserved")))}
  window = channel.InitReplyWindow(); window.arm(expected["type"])
  invalid(lambda: window.bind(expected)); stopped(window)


@pytest.mark.parametrize("kind", REPLIES)
def test_bind_capture_independent_of_caller_mutation(kind):
  window, expected, value, message, raw = window_for(kind)
  if kind == "slot": object.__setattr__(expected["controller"], "pid", 90)
  elif kind == "acquired":
    object.__setattr__(expected["reserved_registration"], "initial_deployment_identity", "6" * 64)
    object.__setattr__(expected["controller"], "pid", 90)
  else: object.__setattr__(expected["offer" if kind == "offer-ack" else "reply"], "token", "6" * 64)
  expected.clear()
  window.feed(raw); assert window.consume() == message


def test_early_candidate_external_send_postpure_or_retirement():
  events = []
  window, _, _, message, raw = window_for()
  events.append("partial-send")
  assert window.feed(raw) is None and window.has_complete_frame is True
  events.extend(("complete-local-send", "postpure"))
  actual = window.consume(); events.append("metadata-consumed")
  assert events == ["partial-send", "complete-local-send", "postpure", "metadata-consumed"]
  assert actual == message and actual.database_allowed is False
  for reason in ("EOF", "cancel", "deadline", "source-failure", "interrupted-send"):
    window, _, _, _, raw = window_for(); window.feed(raw)
    window.retire(); invalid(window.consume); stopped(window)


def test_maximum_raw_payload_and_tail_limits():
  expected, value, message, raw = materials("offer-ack")
  canonical = payload(value); padded = canonical + b" " * (65536 - len(canonical))
  window, _, _, _, _ = window_for(); window.feed(frame(padded)); assert window.consume() == message
  for chunks in ([frame(padded) + b"x"], [frame(padded)[:-1], frame(padded)[-1:] + b"x"],
    [b"x" * 65542], [(65536).to_bytes(4, "big"), b"x" * 65538]):
    window, _, _, _, _ = window_for()
    for chunk in chunks[:-1]: window.feed(chunk)
    invalid(lambda: window.feed(chunks[-1])); stopped(window)


@pytest.mark.parametrize("case", ["zero", "oversized-header", "huge", "same-tail", "two-frames", "split-tail", "late-tail"])
def test_header_tail_rejection_before_decoder_with_valid_forward_control(case, monkeypatch):
  original = codec._pairs; calls = []
  def pairs(items): calls.append("decode"); return original(items)
  monkeypatch.setattr(codec, "_pairs", pairs)
  window, _, _, message, raw = window_for(); calls.clear(); window.feed(raw); assert window.consume() == message and calls
  window, _, _, _, raw = window_for(); calls.clear()
  if case == "zero": chunks = [(0).to_bytes(4, "big") + b"x"]
  elif case == "oversized-header": chunks = [(65537).to_bytes(4, "big") + b"x"]
  elif case == "huge": chunks = [b"x" * 65542]
  elif case == "same-tail": chunks = [raw + b"x"]
  elif case == "two-frames": chunks = [raw + raw]
  elif case == "split-tail": chunks = [raw[:2], raw[2:] + b"x"]
  else: window.feed(raw); calls.clear(); chunks = [b"x"]
  for chunk in chunks[:-1]: window.feed(chunk)
  invalid(lambda: window.feed(chunks[-1])); assert calls == []; stopped(window)


@pytest.mark.parametrize("raw", [b"{bad", b'{"schema":1,"schema":1}', b'{"x":NaN}', b'{"x":[]}', b"\xff"])
def test_complete_bad_codec_reply_retires_without_mirroring_whole_codec(raw):
  window, _, _, _, _ = window_for(); invalid(lambda: window.feed(frame(raw))); stopped(window)


def test_foreign_hooks_zero_and_private_repr():
  calls = []; armed = False
  class Text(str):
    def __hash__(self):
      if armed: calls.append("hash"); raise AssertionError()
      return str.__hash__(self)
    def __eq__(self, other): calls.append("eq"); raise AssertionError()
  class Bytes(bytes):
    def __len__(self): calls.append("len"); raise AssertionError()
    def __bool__(self): calls.append("bool"); raise AssertionError()
    def __getitem__(self, key): calls.append("slice"); raise AssertionError()
  class Dict(dict):
    def items(self): calls.append("items"); raise AssertionError()
  class Foreign:
    def __getattribute__(self, name): calls.append(name); raise AssertionError()
  keyed = {Text("type"): "slot", "controller": Foreign()}; armed = True
  for bad in (keyed, Dict(), Foreign()):
    window = channel.InitReplyWindow(); window.arm("slot"); invalid(lambda: window.bind(bad)); stopped(window)
  for bad in (Text("slot"), Foreign(), 1):
    window = channel.InitReplyWindow(); invalid(lambda: window.arm(bad)); stopped(window)
  for bad in (Bytes(b"x"), bytearray(b"x"), memoryview(b"x"), Foreign()):
    window, _, _, _, _ = window_for(); invalid(lambda: window.feed(bad)); stopped(window)
  for kind, field in (("slot", "controller"), ("acquired", "reserved_registration"), ("offer-ack", "offer")):
    expected, _, _, _ = materials(kind); expected[field] = Foreign()
    window = channel.InitReplyWindow(); window.arm(kind); invalid(lambda: window.bind(expected)); stopped(window)
  assert calls == []
  window, _, _, _, raw = window_for(); window.feed(raw); assert TOKEN not in repr(window)


@pytest.mark.parametrize("module,name", EXPORT_CASES, ids=lambda value: value.__name__ if hasattr(value, "__name__") else value)
@pytest.mark.parametrize("operation", ["constructor", "arm", "bind", "feed", "consume", "getter"])
def test_all_25_public_exports_drift_before_calls_and_no_restore_resurrection(module, name, operation, monkeypatch):
  expected, _, _, raw = materials("offer-ack")
  window = channel.InitReplyWindow()
  if operation in ("bind", "feed", "consume", "getter"): window.arm("offer-ack")
  if operation in ("feed", "consume", "getter"): window.bind(expected)
  if operation in ("consume", "getter"): window.feed(raw)
  original = getattr(module, name); calls = []
  def replacement(*args, **kwargs): calls.append("replacement"); raise RuntimeError(SECRET)
  monkeypatch.setattr(module, name, replacement)
  actions = {"constructor": channel.InitReplyWindow, "arm": lambda: window.arm("offer-ack"),
    "bind": lambda: window.bind(expected), "feed": lambda: window.feed(raw), "consume": window.consume}
  if operation == "getter": assert window.has_complete_frame is False
  else: invalid(actions[operation])
  assert calls == []
  assert window.retire() is None and window.retire() is None
  assert window.writer_lock_verified is False and window.database_allowed is False and window.can_take_over is False
  monkeypatch.setattr(module, name, original)
  stopped(window)


@pytest.mark.parametrize("name", LOCAL_NAMES)
@pytest.mark.parametrize("operation", ["constructor", "getter", "consume"])
def test_own_actual_module_and_cached_alias_drift(name, operation, monkeypatch):
  window, expected, value, message, raw = window_for(); window.feed(raw)
  original = getattr(channel, name); calls = []
  def replacement(*args, **kwargs): calls.append("replacement"); raise RuntimeError(SECRET)
  monkeypatch.setattr(channel, name, replacement)
  if operation == "constructor": invalid(channel.InitReplyWindow)
  elif operation == "getter": assert window.has_complete_frame is False
  else: invalid(window.consume)
  assert window.retire() is None and window.database_allowed is False and calls == []
  monkeypatch.setattr(channel, name, original); stopped(window)


def test_drift_inside_original_decode_checked_before_candidate(monkeypatch):
  original = codec._pairs; enabled = [False]; calls = []
  def replacement(*args): calls.append("replacement"); raise RuntimeError(SECRET)
  def pairs(items):
    result = original(items)
    if enabled[0]: monkeypatch.setattr(codec, "encode_init_message_frame", replacement)
    return result
  monkeypatch.setattr(codec, "_pairs", pairs)
  window, _, _, _, raw = window_for(); enabled[0] = True
  invalid(lambda: window.feed(raw)); assert calls == [] and window.has_complete_frame is False
  window.retire()


def test_drift_inside_original_registration_encode_prevents_next_decode(monkeypatch):
  original = registration_codec._path; enabled = [False]; calls = []
  def replacement(*args): calls.append("replacement"); raise RuntimeError(SECRET)
  def path(value):
    result = original(value)
    if enabled[0]: monkeypatch.setattr(registration_codec, "decode_service_registration", replacement)
    return result
  monkeypatch.setattr(registration_codec, "_path", path)
  expected, _, _, _ = materials("acquired")
  window = channel.InitReplyWindow(); window.arm("acquired"); enabled[0] = True
  invalid(lambda: window.bind(expected)); assert calls == [] and window.has_complete_frame is False


def test_original_foreign_exception_preserved_and_fresh_actual_chain(monkeypatch):
  window, _, _, _, raw = window_for()
  cause = ValueError("foreign cause"); context = RuntimeError("foreign context"); foreign = RuntimeError(SECRET)
  def pairs(items):
    try: raise foreign
    except RuntimeError:
      foreign.__cause__ = cause; foreign.__context__ = context
      raise
  monkeypatch.setattr(codec, "_pairs", pairs)
  first = invalid(lambda: window.feed(raw)); second = invalid(window.consume)
  assert first is not second and first is not foreign
  assert foreign.args == (SECRET,) and foreign.__cause__ is cause and foreign.__context__ is context
  stopped(window)
