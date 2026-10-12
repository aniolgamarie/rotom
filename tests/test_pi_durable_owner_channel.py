"""纯 owner 回复窗口；帧拆片与来源漂移，不调用 pipe/SDK/进程。"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import traceback

import pytest
from agentcfg import pi_durable_owner_message as codec
from agentcfg import pi_durable_owner_record as record_codec
from agentcfg.pi_durable_owner_channel import OwnerReplyWindow
from agentcfg.storage import Conflict

VECTORS = json.loads((Path(__file__).parent / "fixtures/pi/durable-owner-message-codec/vectors.json").read_text())["vectors"]
SECRET = "SYNTHETIC_REPLY_WINDOW_SECRET"
MESSAGE_EXPORTS = ("OwnerMessage", "OwnerRecord", "LinuxProcessIdentity", "StorageIdentity", "capture_owner_message", "decode_owner_message_frame", "encode_owner_message_frame", "capture_owner_record", "encode_owner_record")
RECORD_EXPORTS = ("OwnerRecord", "LinuxProcessIdentity", "StorageIdentity", "capture_owner_record", "encode_owner_record")


def value(kind="bound"):
  return deepcopy(next(vector["value"] for vector in VECTORS if vector["name"] == kind + "_minimal"))

def expected(kind="bound"): return codec.capture_owner_message(value(kind))
def frame(kind="bound"): return codec.encode_owner_message_frame(expected(kind))

def invalid(call):
  with pytest.raises(Conflict) as caught: call()
  error = caught.value
  assert type(error) is Conflict and error.args == ("Durable所有者回复窗口无效",)
  assert error.__context__ is None and error.__cause__ is None and not hasattr(error, "doc")
  assert SECRET not in "".join(traceback.format_exception(error))
  return error


def stopped(window):
  assert window.has_complete_frame is False
  assert window.writer_lock_verified is False and window.database_allowed is False and window.can_take_over is False
  invalid(lambda: window.feed(b"x")); invalid(window.take); invalid(window.end)
  assert window.close() is None and window.close() is None


@pytest.mark.parametrize("kind", ["hello", "bound", "closed"])
def test_single_byte_candidate_withheld_until_take(kind):
  source = expected(kind); window = OwnerReplyWindow(source); wire = codec.encode_owner_message_frame(source)
  assert window.has_complete_frame is False
  for index, byte in enumerate(wire):
    assert window.feed(bytes([byte])) is None
    assert window.has_complete_frame is (index == len(wire) - 1)
  actual = window.take(); assert actual == source and actual is not source
  assert window.has_complete_frame is False
  assert actual.writer_lock_verified is False and actual.database_allowed is False
  assert window.end() is None
  invalid(window.take); stopped(window)


def test_all_header_payload_split_points_and_key_order_whitespace():
  source = expected(); wire = codec.encode_owner_message_frame(source)
  for split in range(1, len(wire)):
    window = OwnerReplyWindow(source); assert window.feed(wire[:split]) is None
    assert window.has_complete_frame is False
    assert window.feed(wire[split:]) is None; assert window.take() == source
  payload = (" \n" + json.dumps(value(), indent=1) + "\t ").encode()
  window = OwnerReplyWindow(source); window.feed(len(payload).to_bytes(4, "big") + payload); assert window.take() == source


@pytest.mark.parametrize("mode", ["epoch", "deployment", "storage", "lock", "writer", "controller", "kind"])
def test_complete_metadata_mismatch_permanently_invalid(mode):
  source = expected(); changed = value()
  if mode == "epoch": changed["record"]["epoch"] = "c"*64
  if mode == "deployment": changed["record"]["deployment_identity"] = "c"*64
  if mode == "storage": changed["record"]["storage_identity"]["inode"] = "3"
  if mode == "lock": changed["lock_identity"]["inode"] = "3"
  if mode == "writer": changed["record"]["writer"]["pid"] = 12
  if mode == "controller": changed["record"]["controller"]["pid"] = 12
  if mode == "kind": changed = value("hello")
  wire = codec.encode_owner_message_frame(codec.capture_owner_message(changed)); window = OwnerReplyWindow(source)
  invalid(lambda: window.feed(wire)); stopped(window)


@pytest.mark.parametrize("mode", ["early-take", "empty", "partial-end", "extra", "twoframes", "late-extra", "after-end", "double-end", "double-take"])
def test_invalid_end_consumption_and_late_bytes_never_reopen(mode):
  window = OwnerReplyWindow(expected()); wire = frame()
  if mode == "early-take": invalid(window.take)
  if mode == "empty": invalid(lambda: window.feed(b""))
  if mode == "partial-end": window.feed(wire[:4]); invalid(window.end)
  if mode == "extra": invalid(lambda: window.feed(wire+b"x"))
  if mode == "twoframes": invalid(lambda: window.feed(wire+wire))
  if mode == "late-extra": window.feed(wire); invalid(lambda: window.feed(frame("closed")))
  if mode == "after-end": window.feed(wire); window.end(); invalid(lambda: window.feed(b"x"))
  if mode == "double-end": window.feed(wire); window.end(); invalid(window.end)
  if mode == "double-take": window.feed(wire); window.take(); invalid(window.take)
  stopped(window)


def test_eof_observed_on_complete_unconsumed_metadata_is_not_capability():
  window = OwnerReplyWindow(expected()); window.feed(frame()); window.end()
  assert window.has_complete_frame is True
  assert window.database_allowed is False and window.writer_lock_verified is False and window.can_take_over is False
  assert window.take() == expected(); assert window.has_complete_frame is False
  invalid(window.end); stopped(window)


@pytest.mark.parametrize("state", ["initial", "partial", "candidate", "consumed", "invalid", "ended"])
def test_close_is_idempotent_and_all_public_properties_readonly(state):
  window = OwnerReplyWindow(expected()); wire = frame()
  if state == "partial": window.feed(wire[:2])
  if state in ("candidate", "consumed", "ended"): window.feed(wire)
  if state == "consumed": window.take()
  if state == "ended": window.end()
  if state == "invalid": invalid(lambda: window.feed(b""))
  assert not hasattr(window, "__dict__")
  for name in ["has_complete_frame", "writer_lock_verified", "database_allowed", "can_take_over", "buffer", "candidate"]:
    with pytest.raises((AttributeError, TypeError)): setattr(window, name, True)
  window.close(); window.close(); stopped(window)


@pytest.mark.parametrize("source", ["hello", "bound", "closed"])
def test_expected_independent_of_later_caller_slot_changes(source):
  original = expected(source); wire = codec.encode_owner_message_frame(original); window = OwnerReplyWindow(original)
  object.__setattr__(original, "fd", 99)
  window.feed(wire); assert window.take().fd == 3


@pytest.mark.parametrize("module,names", [(codec, MESSAGE_EXPORTS), (record_codec, RECORD_EXPORTS)])
def test_every_selected_class_function_alias_drift_refuses_without_replacement_call(module, names, monkeypatch):
  for name in names:
    window = OwnerReplyWindow(expected()); original = getattr(module, name); calls = []
    def replacement(*args, **kwargs): calls.append(1); raise RuntimeError(SECRET)
    monkeypatch.setattr(module, name, replacement)
    invalid(lambda: window.feed(b"x")); assert calls == []
    assert window.has_complete_frame is False and window.database_allowed is False
    window.close(); window.close()
    monkeypatch.setattr(module, name, original)


def test_replacement_before_constructor_is_not_a_new_baseline(monkeypatch):
  original = codec.decode_owner_message_frame; calls = []
  # 替换依赖是非法来源，不能作为 constructor 新baseline。
  def replacement(raw): calls.append(1); return original(raw)
  monkeypatch.setattr(codec, "decode_owner_message_frame", replacement)
  invalid(lambda: OwnerReplyWindow(expected())); assert calls == []


def test_has_complete_drift_returns_false_and_close_false_getters_need_no_source(monkeypatch):
  window = OwnerReplyWindow(expected()); window.feed(frame()); assert window.has_complete_frame is True
  calls = []
  def replacement(*args): calls.append(1); raise RuntimeError(SECRET)
  monkeypatch.setattr(codec, "encode_owner_message_frame", replacement)
  assert window.has_complete_frame is False; assert calls == []
  window.close(); window.close()
  assert window.writer_lock_verified is False and window.database_allowed is False and window.can_take_over is False
  invalid(window.take); assert calls == []


@pytest.mark.parametrize("source", [None, b"bad", "hello", object()])
def test_constructor_rejects_foreign_and_wrong_expected(source): invalid(lambda: OwnerReplyWindow(source))


def test_bind_close_are_not_reply_expectations():
  invalid(lambda: OwnerReplyWindow(expected("bind"))); invalid(lambda: OwnerReplyWindow(expected("close")))


def test_exact_type_before_hooks_and_fixed_ambient_context():
  calls = []
  class Payload(bytes):
    def __bool__(self): calls.append("bool"); raise RuntimeError(SECRET)
    def __len__(self): calls.append("len"); raise RuntimeError(SECRET)
    def __getitem__(self, key): calls.append("slice"); raise RuntimeError(SECRET)
  class Poison:
    def __getattribute__(self, key): calls.append(key); raise RuntimeError(SECRET)
  for bad in [Payload(b"x"), bytearray(b"x"), memoryview(b"x"), "x", Poison()]:
    window = OwnerReplyWindow(expected())
    try: raise RuntimeError(SECRET)
    except RuntimeError: invalid(lambda: window.feed(bad))
  try: raise RuntimeError(SECRET)
  except RuntimeError: invalid(lambda: OwnerReplyWindow(Poison()))
  assert calls == []


def test_maximum_payload_whitespace_and_oversize_rejects_before_codec():
  payload = frame()[4:]; padded = payload + b" "*(4096-len(payload)); window = OwnerReplyWindow(expected())
  assert window.feed((4096).to_bytes(4,"big") + padded) is None
  assert window.take() == expected()
  for chunks in [[b"x"*4102], [(0).to_bytes(4,"big")], [(4097).to_bytes(4,"big")], [(4096).to_bytes(4,"big"), b"x"*4098]]:
    window = OwnerReplyWindow(expected())
    for chunk in chunks[:-1]: window.feed(chunk)
    invalid(lambda: window.feed(chunks[-1])); stopped(window)


def test_actual_original_decoder_return_source_drift_prevents_canonical_encoder(monkeypatch):
  original_pairs = codec._pairs; armed = [False]; replacement_calls = []
  def replacement(*args): replacement_calls.append(1); raise RuntimeError(SECRET)
  def pairs(items):
    result = original_pairs(items)
    if armed[0]: monkeypatch.setattr(codec, "encode_owner_message_frame", replacement)
    return result
  # 私有受控测试 seam 仅在真实 decoder 期间改变已核出口，不复制 parser/window。
  monkeypatch.setattr(codec, "_pairs", pairs)
  source = expected(); wire = codec.encode_owner_message_frame(source); window = OwnerReplyWindow(source); armed[0] = True
  invalid(lambda: window.feed(wire)); assert replacement_calls == [] and window.has_complete_frame is False
  window.close(); window.close()


@pytest.mark.parametrize("operation", ["take", "end"])
def test_source_drift_at_complete_candidate_operation_never_returns(operation, monkeypatch):
  window = OwnerReplyWindow(expected()); window.feed(frame()); calls = []
  def replacement(*args): calls.append(1); raise RuntimeError(SECRET)
  monkeypatch.setattr(record_codec, "encode_owner_record", replacement)
  invalid(getattr(window, operation)); assert window.has_complete_frame is False and calls == []
  window.close()


def test_original_foreign_codec_exception_untouched_and_window_error_cleared(monkeypatch):
  window = OwnerReplyWindow(expected()); wire = frame(); original = Conflict(SECRET); cause = RuntimeError(SECRET); original.__cause__ = cause
  def pairs(items): raise original
  monkeypatch.setattr(codec, "_pairs", pairs)
  try: raise RuntimeError(SECRET)
  except RuntimeError as ambient:
    invalid(lambda: window.feed(wire)); assert original.args == (SECRET,) and original.__cause__ is cause and original.__context__ is ambient
  assert window.has_complete_frame is False


def test_invalid_header_and_tail_limit_before_actual_decoder_callbacks(monkeypatch):
  original = codec._pairs; calls = []
  def pairs(items): calls.append(1); return original(items)
  monkeypatch.setattr(codec, "_pairs", pairs)
  source = expected(); wire = codec.encode_owner_message_frame(source)
  for chunks in [[(4097).to_bytes(4,"big")+b"x"], [wire+b"x"], [b"x"*4102], [wire[:2], wire[2:]+b"x"]]:
    window = OwnerReplyWindow(source); calls.clear()
    for chunk in chunks[:-1]: window.feed(chunk)
    invalid(lambda: window.feed(chunks[-1])); assert calls == []
