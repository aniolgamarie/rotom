"""纯 bootstrap 数据边界；不消费真实 token、source 或角色 IO。"""

from copy import copy, deepcopy
from dataclasses import fields, replace, FrozenInstanceError
import json
from pathlib import Path
import traceback
from types import SimpleNamespace

import pytest

from agentcfg import pi_initializer_bootstrap as codec


FIXTURE = json.loads((Path(__file__).parent / "fixtures/pi/initializer-bootstrap-v1.json").read_text())
TOKEN = FIXTURE["input"]["role_token"]
GOLDEN = bytes.fromhex(FIXTURE["frame_hex"])
CODE = "PI_INITIALIZER_BOOTSTRAP_INVALID"
SECRET = "SYNTHETIC_FOREIGN_BOOTSTRAP_EXCEPTION"
NAMES = tuple(FIXTURE["input"])
MAX_GENERATION = 9007199254740991


def value(): return dict(FIXTURE["input"])


def framed(payload):
  if type(payload) is str: payload = payload.encode("ascii")
  return len(payload).to_bytes(4, "big") + payload


def rejected(action):
  try:
    raise RuntimeError(SECRET)
  except RuntimeError:
    with pytest.raises(Exception) as caught: action()
  error = caught.value
  assert error.args == (CODE,)
  assert getattr(error, "exit_code", None) == 4
  assert error.__cause__ is None and error.__context__ is None
  rendered = "".join(traceback.format_exception(error))
  assert SECRET not in rendered and TOKEN not in rendered


def test_golden_canonical_and_roundtrip_match_independent_fixture():
  dto = codec.capture_initializer_bootstrap(value())
  frame = codec.encode_initializer_bootstrap_frame(dto)
  if frame != GOLDEN: pytest.fail("synthetic golden frame mismatch")
  assert len(frame) == FIXTURE["frame_bytes"] == 746
  assert len(frame[4:]) == FIXTURE["payload_bytes"] == 742
  decoded = codec.decode_initializer_bootstrap_frame(GOLDEN)
  if codec.encode_initializer_bootstrap_frame(decoded) != GOLDEN: pytest.fail("roundtrip golden mismatch")
  assert type(dto) is codec.InitializerBootstrap
  assert {field.name for field in fields(dto)} == set(NAMES)


@pytest.mark.parametrize("generation", [0, 1, MAX_GENERATION])
def test_generation_safe_integer_extremes(generation):
  data = value(); data["grant_generation"] = generation
  dto = codec.capture_initializer_bootstrap(data)
  frame = codec.encode_initializer_bootstrap_frame(dto)
  assert len(frame[4:]) == (757 if generation == MAX_GENERATION else 742)
  assert codec.decode_initializer_bootstrap_frame(frame).grant_generation == generation


def test_capture_snapshots_input_and_dto_repr_redacts_private_data():
  data = value()
  dto = codec.capture_initializer_bootstrap(data)
  data["role_token"] = "a" * 64
  data["grant_generation"] = 123
  if codec.encode_initializer_bootstrap_frame(dto) != GOLDEN: pytest.fail("capture aliases input")
  assert TOKEN not in repr(dto) and TOKEN not in str(dto)
  assert "redacted" in repr(dto).lower()
  with pytest.raises(FrozenInstanceError): dto.grant_generation = 4
  assert not hasattr(dto, "__dict__")
  assert not hasattr(dto, "fileno") and not hasattr(dto, "launch")


def test_public_constructor_and_copies_are_data_and_are_revalidated():
  dto = codec.InitializerBootstrap(**value())
  for candidate in (dto, copy(dto), deepcopy(dto), replace(dto, grant_generation=0)):
    if codec.encode_initializer_bootstrap_frame(candidate) != GOLDEN: pytest.fail("valid DTO data rejected")
  object.__setattr__(dto, "role_token", "invalid")
  rejected(lambda: codec.encode_initializer_bootstrap_frame(dto))


@pytest.mark.parametrize("field", NAMES)
def test_missing_and_unknown_fields_are_closed(field):
  data = value(); data.pop(field)
  rejected(lambda: codec.capture_initializer_bootstrap(data))
  data = value(); data["extra"] = "unused"
  rejected(lambda: codec.capture_initializer_bootstrap(data))


@pytest.mark.parametrize("field", NAMES)
@pytest.mark.parametrize("bad", [None, True, [], {}, 1.0])
def test_exact_scalar_types(field, bad):
  data = value(); data[field] = bad
  rejected(lambda: codec.capture_initializer_bootstrap(data))


@pytest.mark.parametrize("field", [name for name in NAMES if name not in ("schema_version", "role", "grant_generation")])
@pytest.mark.parametrize("mutation", ["uppercase", "short", "long", "newline", "nonascii", "surrogate"])
def test_hex_width_alphabet_and_ascii_are_exact(field, mutation):
  data = value(); width = len(data[field])
  data[field] = {"uppercase": "A" * width, "short": "a" * (width - 1), "long": "a" * (width + 1),
    "newline": "a" * (width - 1) + "\n", "nonascii": "é" * width, "surrogate": "\ud800" * width}[mutation]
  rejected(lambda: codec.capture_initializer_bootstrap(data))


@pytest.mark.parametrize("field,bad", [("schema_version", 0), ("schema_version", 2), ("role", "initializer"),
  ("grant_generation", -1), ("grant_generation", MAX_GENERATION + 1), ("grant_generation", float("nan")),
  ("grant_generation", float("inf"))])
def test_fixed_values_and_integer_range(field, bad):
  data = value(); data[field] = bad
  rejected(lambda: codec.capture_initializer_bootstrap(data))


def test_dict_and_scalar_subclasses_are_rejected_without_foreign_methods():
  touched = []
  class ForeignDict(dict):
    def items(self): touched.append(True); raise RuntimeError(SECRET)
  class ForeignStr(str): pass
  class ForeignInt(int): pass
  rejected(lambda: codec.capture_initializer_bootstrap(ForeignDict(value())))
  for field, bad in (("role_token", ForeignStr(TOKEN)), ("grant_generation", ForeignInt(0))):
    data = value(); data[field] = bad
    rejected(lambda: codec.capture_initializer_bootstrap(data))
  assert touched == []


@pytest.mark.parametrize("factory", [list, tuple, lambda: None])
def test_non_dict_capture_rejected(factory):
  rejected(lambda: codec.capture_initializer_bootstrap(factory()))


@pytest.mark.parametrize("case", range(12))
def test_size_caps_and_single_complete_frame(case):
  cases = (b"", b"\x00", b"\x00\x00\x00", b"\x00\x00\x00\x00", b"\x00\x00\x08\x01",
    b"\xff\xff\xff\xff", (2048).to_bytes(4, "big") + b"x" * 2048,
    (2049).to_bytes(4, "big") + b"x" * 2049, (2048).to_bytes(4, "big") + b"x" * 2049,
    GOLDEN + b"\x00", GOLDEN + GOLDEN, GOLDEN[:-1])
  rejected(lambda: codec.decode_initializer_bootstrap_frame(cases[case]))


def test_cap_and_total_length_are_checked_before_payload_decoder(monkeypatch):
  touched = []
  def unexpected(*args, **kwargs): touched.append(True); raise RuntimeError(SECRET)
  monkeypatch.setattr(codec, "json", SimpleNamespace(loads=unexpected, dumps=json.dumps))
  for raw in ((2049).to_bytes(4, "big") + b"x" * 2049, GOLDEN + b"x", GOLDEN[:-1]):
    rejected(lambda: codec.decode_initializer_bootstrap_frame(raw))
  assert touched == []


@pytest.mark.parametrize("transform", [
  lambda raw: " " + raw, lambda raw: raw + "\n", lambda raw: raw.replace(",", ", ", 1),
  lambda raw: raw.replace('"grant_generation":0', '"grant_generation":0.0'),
  lambda raw: raw.replace('"grant_generation":0', '"grant_generation":0e0'),
  lambda raw: raw.replace('"grant_generation":0', '"grant_generation":-0'),
  lambda raw: raw.replace('"grant_generation":0', '"grant_generation":00'),
  lambda raw: raw.replace('"grant_generation":0', '"grant_generation":NaN'),
  lambda raw: raw.replace('"schema_version":1', '"schema_version":1,"schema_version":1'),
  lambda raw: raw.replace('"role":"durable-initializer"', '"role":"durable-\\u0069nitializer"'),
  lambda raw: raw[:-1] + ',"extra":0}', lambda raw: json.dumps(value()),
  lambda raw: "[]", lambda raw: '"text"', lambda raw: "null",
])
def test_noncanonical_duplicate_unknown_and_json_shapes(transform):
  rejected(lambda: codec.decode_initializer_bootstrap_frame(framed(transform(FIXTURE["canonical_payload"]))))


@pytest.mark.parametrize("case", range(4))
def test_bom_utf8_and_surrogate_wire_rejected(case):
  payloads = (b"\xef\xbb\xbf" + GOLDEN[4:], b"\xff", b'{"role":"\xc3\xa9"}', b'{"role":"\\ud800"}')
  rejected(lambda: codec.decode_initializer_bootstrap_frame(framed(payloads[case])))


def test_only_exact_bytes_and_exact_self_dto_are_encoded():
  class ForeignBytes(bytes): pass
  class ForeignDTO(codec.InitializerBootstrap): pass
  for raw in (bytearray(GOLDEN), memoryview(GOLDEN), ForeignBytes(GOLDEN), GOLDEN.hex(), None):
    rejected(lambda: codec.decode_initializer_bootstrap_frame(raw))
  for candidate in (value(), None, ForeignDTO(**value())):
    rejected(lambda: codec.encode_initializer_bootstrap_frame(candidate))


@pytest.mark.parametrize("function", ["capture_initializer_bootstrap", "encode_initializer_bootstrap_frame", "decode_initializer_bootstrap_frame", "InitializerBootstrap"])
def test_bad_binding_is_fixed_without_keyword_echo(function):
  action = getattr(codec, function)
  for args, kwargs in (((), {}), ((1, 2), {}), ((), {SECRET: TOKEN})):
    rejected(lambda: action(*args, **kwargs))
