"""停止请求严格数据边界；无IPC/时钟/进程/文件动作。"""
from collections import UserDict
from copy import deepcopy
import json

import pytest

from agentcfg import run_owners, stop_requests as codec
from agentcfg.storage import Conflict


def request():
  return {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop",
    "request_id": "a" * 32, "batch_id": "b" * 32, "run_id": "c" * 32, "plan_id": "d" * 64,
    "manager_identity": {"pid": 101, "birth_id": "synthetic-manager"},
    "host_identity": {"pid": 202, "birth_id": "synthetic-host"}, "deadline_ns": 1}


def raw(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def test_canonical_deterministic_roundtrip_preserves_exact_values_and_independence(capsys):
  value = request(); original = deepcopy(value)
  encoded = codec.encode_stop_request(value)
  assert encoded == raw(value)
  assert codec.encode_stop_request(dict(reversed(list(value.items())))) == encoded
  decoded = codec.decode_stop_request(encoded)
  assert decoded == value and decoded is not value
  decoded["manager_identity"]["birth_id"] = "changed"
  value["host_identity"]["pid"] = 999
  assert codec.decode_stop_request(encoded) == original
  assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("identity", ["manager_identity", "host_identity"])
@pytest.mark.parametrize("field,value", [("pid", 303), ("birth_id", "synthetic-new-birth"), ("birth_id", "合成出生身份")])
def test_identity_changes_preserved_without_live_lookup(identity, field, value):
  data = request(); data[identity][field] = value
  assert codec.decode_stop_request(codec.encode_stop_request(data)) == data


@pytest.mark.parametrize("deadline", [1, 2**63 - 1])
def test_deadline_range_is_data_only(deadline):
  value = request(); value["deadline_ns"] = deadline
  assert codec.decode_stop_request(codec.encode_stop_request(value))["deadline_ns"] == deadline


@pytest.mark.parametrize("damage", ["missing", "extra", "version-bool", "version", "kind", "action", "request-uppercase", "request-length", "batch-type", "run-type", "plan-length", "plan-uppercase", "deadline-bool", "deadline-zero", "deadline-negative", "deadline-overflow", "deadline-float", "same-pid", "manager-extra", "host-extra", "manager-missing", "host-missing", "pid-bool", "pid-zero", "pid-float", "birth-empty", "birth-nul", "birth-type", "surrogate"])
@pytest.mark.parametrize("mode", ["encode", "decode"])
def test_invalid_fields_are_fixed_conflict_without_payload_echo(damage, mode):
  value = request()
  if damage == "missing": del value["action"]
  elif damage == "extra": value["text"] = "synthetic-private-canary"
  elif damage == "version-bool": value["schema_version"] = True
  elif damage == "version": value["schema_version"] = 2
  elif damage == "kind": value["kind"] = "synthetic-private-canary"
  elif damage == "action": value["action"] = "force"
  elif damage == "request-uppercase": value["request_id"] = "A" * 32
  elif damage == "request-length": value["request_id"] = "a" * 31
  elif damage == "batch-type": value["batch_id"] = True
  elif damage == "run-type": value["run_id"] = 12
  elif damage == "plan-length": value["plan_id"] = "a" * 32
  elif damage == "plan-uppercase": value["plan_id"] = "A" * 64
  elif damage.startswith("deadline-"):
    value["deadline_ns"] = {"bool": True, "zero": 0, "negative": -1, "overflow": 2**63, "float": 1.0}[damage.removeprefix("deadline-")]
  elif damage == "same-pid": value["host_identity"]["pid"] = value["manager_identity"]["pid"]
  elif damage == "manager-extra": value["manager_identity"]["generation"] = 1.0
  elif damage == "host-extra": value["host_identity"]["generation"] = "synthetic-private-canary"
  elif damage == "manager-missing": del value["manager_identity"]["birth_id"]
  elif damage == "host-missing": del value["host_identity"]["pid"]
  elif damage == "pid-bool": value["host_identity"]["pid"] = True
  elif damage == "pid-zero": value["manager_identity"]["pid"] = 0
  elif damage == "pid-float": value["host_identity"]["pid"] = 202.0
  elif damage == "birth-empty": value["manager_identity"]["birth_id"] = ""
  elif damage == "birth-nul": value["host_identity"]["birth_id"] = "synthetic\0private"
  elif damage == "birth-type": value["manager_identity"]["birth_id"] = ["synthetic-private-canary"]
  else: value["manager_identity"]["birth_id"] = "synthetic\ud800private"
  if mode == "decode":
    # 使用ASCII转义保留孤立surrogate，让拒绝发生在codec内部。
    payload = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode()
  with pytest.raises(Conflict) as caught:
    codec.encode_stop_request(value) if mode == "encode" else codec.decode_stop_request(payload)
  assert "synthetic-private-canary" not in str(caught.value) and "synthetic" not in str(caught.value)


@pytest.mark.parametrize("payload", [None, "{}", bytearray(b"{}"), memoryview(b"{}"), b"\xef\xbb\xbf{}", b"\xff", b"[]", b"true", b"null", b"{", b"{} {}"])
def test_raw_type_utf8_bom_shape_and_trailing_values_reject(payload):
  with pytest.raises(Conflict): codec.decode_stop_request(payload)


@pytest.mark.parametrize("payload", [{}, [], UserDict(request()), True])
def test_encode_only_exact_dict(payload):
  with pytest.raises(Conflict): codec.encode_stop_request(payload)


@pytest.mark.parametrize("field", ["schema_version", "manager_identity"])
def test_duplicate_keys_at_any_level_reject(field):
  payload = raw(request())
  if field == "schema_version": payload = payload.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1')
  else: payload = payload.replace(b'"pid":101', b'"pid":101,"pid":101')
  with pytest.raises(Conflict): codec.decode_stop_request(payload)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1.0", "1e0"])
def test_nonfinite_and_every_json_float_reject(number):
  payload = raw(request()).replace(b'"deadline_ns":1', b'"deadline_ns":' + number.encode())
  with pytest.raises(Conflict): codec.decode_stop_request(payload)


@pytest.mark.parametrize("utf8", [False, True])
def test_exact_16k_encoded_boundary_and_one_byte_over(utf8):
  value = request()
  if utf8: value["host_identity"]["birth_id"] = "合成身份"
  length = len(raw(value))
  value["manager_identity"]["birth_id"] += "x" * (16384 - length)
  assert len(raw(value)) == 16384
  assert codec.encode_stop_request(value) == raw(value)
  assert codec.decode_stop_request(raw(value)) == value
  value["manager_identity"]["birth_id"] += "x"
  with pytest.raises(Conflict): codec.encode_stop_request(value)
  with pytest.raises(Conflict): codec.decode_stop_request(raw(value))


def test_raw_whitespace_over_bound_is_not_normalized_into_acceptance():
  payload = raw(request())
  with pytest.raises(Conflict): codec.decode_stop_request(payload + b" " * (16385 - len(payload)))


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("mode", ["encode", "decode"])
def test_control_exceptions_propagate_original(monkeypatch, kind, mode):
  error = kind("synthetic-control")
  def fail(*args): raise error
  monkeypatch.setattr(run_owners, "_manager", fail)
  with pytest.raises(kind) as caught:
    codec.encode_stop_request(request()) if mode == "encode" else codec.decode_stop_request(raw(request()))
  assert caught.value is error


def test_cyclic_payload_fails_fixed_without_recursion_details():
  value = request(); value["manager_identity"]["birth_id"] = value
  with pytest.raises(Conflict) as caught: codec.encode_stop_request(value)
  assert "recursion" not in str(caught.value)


def test_root_and_raw_subclasses_are_not_exact_protocol_types():
  class DictSubclass(dict): pass
  class BytesSubclass(bytes): pass
  with pytest.raises(Conflict): codec.encode_stop_request(DictSubclass(request()))
  with pytest.raises(Conflict): codec.decode_stop_request(BytesSubclass(raw(request())))


def test_canonical_newline_cannot_make_decoded_value_exceed_size_limit():
  value = request()
  value["manager_identity"]["birth_id"] += "x" * (16385 - len(raw(value)))
  payload = raw(value).removesuffix(b"\n")
  assert len(payload) == 16384
  with pytest.raises(Conflict): codec.decode_stop_request(payload)
