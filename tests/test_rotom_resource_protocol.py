"""共享资源协调纯数据契约；虚构记录不授予锁、历史或维护能力。"""

from copy import deepcopy
import json

import pytest

from agentcfg.resource_keys import ResourceKey
from agentcfg.resource_protocol import decode, encode
from agentcfg.storage import Conflict


RESOURCE = "a" * 32
RUN = "b" * 32
BATCH = "c" * 32
DOMAIN = "d" * 32
OP = "e" * 32


def anchor():
  return {"schema_version": 1, "kind": "runtime-anchor", "protocol": "rotom-resource-v1",
    "domain_id": DOMAIN, "domain_physical": {"device": 2, "inode": 3},
    "resource_id": RESOURCE, "resource_key": ResourceKey("runtime", 7, 11).as_dict()}


def domain():
  return {"schema_version": 1, "kind": "domain", "domain_id": DOMAIN,
    "physical": {"device": 2, "inode": 3}, "revision": 0,
    "resources": {RESOURCE: {"resource_id": RESOURCE, "key": ResourceKey("runtime", 7, 11).as_dict(),
      "cache": "/synthetic/cache", "runtime_identity": "synthetic-runtime.v1", "status": "ready"}},
    "reservations": {RUN: {"run_id": RUN, "op_id": OP,
      "owner_ref": {"state_root": "/synthetic/state", "binding": {
        "machine": "synthetic-machine", "local": "/synthetic/local.toml", "profile": "synthetic-profile"}},
      "resources": [RESOURCE], "phase": "reserved"}},
    "intents": {BATCH: {"batch_id": BATCH, "generation": 1, "operation": "setup",
      "resources": [RESOURCE], "selected_runs": [RUN], "phase": "active"}}}


def reject(call):
  with pytest.raises(Conflict) as caught:
    call()
  assert str(caught.value) == "共享资源协调记录无效"
  assert caught.value.exit_code == 4
  assert caught.value.__cause__ is None


def invalid(value):
  reject(lambda: encode(value))
  reject(lambda: decode(json.dumps(value).encode(), kind=value.get("kind", "domain")))


@pytest.mark.parametrize("factory", [anchor, domain])
def test_roundtrip_is_canonical_utf8_and_does_not_mutate(factory):
  value = factory()
  before = deepcopy(value)
  raw = encode(value)
  assert type(raw) is bytes and raw.endswith(b"\n") and not raw.endswith(b"\n\n")
  assert decode(raw, kind=value["kind"]) == value
  assert value == before
  assert encode(dict(reversed(list(value.items())))) == raw
  assert encode(decode(raw, kind=value["kind"])) == raw


def test_empty_domain_is_valid_without_invented_timestamp_or_authority():
  value = domain()
  value.update(resources={}, reservations={}, intents={})
  assert decode(encode(value), kind="domain") == value
  assert set(value) == {"schema_version", "kind", "domain_id", "physical", "revision", "resources", "reservations", "intents"}


def test_unicode_absolute_paths_and_literal_braces_are_data_only():
  value = domain()
  value["resources"][RESOURCE]["cache"] = "/虚构 路径/{" + "[" * 100
  assert "虚构".encode() in encode(value)
  assert decode(encode(value), kind="domain") == value


@pytest.mark.parametrize("factory", [anchor, domain])
def test_decode_kind_is_exact(factory):
  value = factory()
  wrong = "domain" if value["kind"] == "runtime-anchor" else "runtime-anchor"
  reject(lambda: decode(encode(value), kind=wrong))
  for kind in ("unknown", "", None, True):
    reject(lambda: decode(encode(value), kind=kind))


@pytest.mark.parametrize("path", [
  (), ("physical",), ("resources", RESOURCE), ("resources", RESOURCE, "key"),
  ("reservations", RUN), ("reservations", RUN, "owner_ref"),
  ("reservations", RUN, "owner_ref", "binding"), ("intents", BATCH),
])
def test_unknown_fields_rejected_at_every_object(path):
  value = domain(); current = value
  for key in path:
    current = current[key]
  current["synthetic-private-unknown"] = "must-not-appear"
  invalid(value)


@pytest.mark.parametrize("field", ["timestamp", "expire", "complete", "protocol"])
def test_unrequested_domain_fields_are_rejected(field):
  value = domain(); value[field] = True; invalid(value)


@pytest.mark.parametrize("field", list(anchor()))
def test_anchor_required_fields(field):
  value = anchor(); del value[field]; invalid(value)


@pytest.mark.parametrize("field", ["resources", "reservations", "intents", "revision", "physical", "domain_id"])
def test_domain_required_fields(field):
  value = domain(); del value[field]; invalid(value)


@pytest.mark.parametrize("path", [
  ("schema_version",), ("physical", "device"), ("physical", "inode"), ("revision",),
  ("resources", RESOURCE, "key", "device"), ("resources", RESOURCE, "key", "inode"),
  ("intents", BATCH, "generation"),
])
@pytest.mark.parametrize("bad", [True, False, 1.0, float("nan"), float("inf")])
def test_integer_fields_refuse_bool_float_and_nonfinite(path, bad):
  value = domain(); current = value
  for key in path[:-1]:
    current = current[key]
  current[path[-1]] = bad; invalid(value)


@pytest.mark.parametrize("field,bad", [("device", -1), ("inode", 0), ("inode", -1)])
def test_physical_boundaries(field, bad):
  value = anchor(); value["domain_physical"][field] = bad; invalid(value)


@pytest.mark.parametrize("bad", [-1, True, 1.0])
def test_revision_is_nonnegative_exact_integer(bad):
  value = domain(); value["revision"] = bad; invalid(value)


@pytest.mark.parametrize("bad", [0, -1, True, 1.0])
def test_generation_is_positive_exact_integer(bad):
  value = domain(); value["intents"][BATCH]["generation"] = bad; invalid(value)


@pytest.mark.parametrize("bad", ["", "a" * 31, "a" * 33, "A" * 32, "z" * 32, "a" * 32 + "\n", "../private"])
def test_ids_are_lowercase_exact_32_hex(bad):
  value = anchor(); value["domain_id"] = bad; invalid(value)


@pytest.mark.parametrize("table,inside", [("resources", "resource_id"), ("reservations", "run_id"), ("intents", "batch_id")])
def test_mapping_key_must_match_internal_id(table, inside):
  value = domain(); entry = next(iter(value[table].values())); entry[inside] = "f" * 32; invalid(value)


@pytest.mark.parametrize("table", ["resources", "reservations", "intents"])
def test_mapping_keys_are_ids_not_arbitrary_names(table):
  value = domain(); value[table]["synthetic-private-key"] = value[table].pop(next(iter(value[table]))); invalid(value)


@pytest.mark.parametrize("bad", ["relative", "/a/../b", "/a/./b", "/a//b", "/a/", "//a", "/bad\0path"])
@pytest.mark.parametrize("field", ["cache", "state_root", "local"])
def test_paths_are_absolute_normalized_data(field, bad):
  value = domain()
  if field == "cache":
    value["resources"][RESOURCE][field] = bad
  elif field == "state_root":
    value["reservations"][RUN]["owner_ref"][field] = bad
  else:
    value["reservations"][RUN]["owner_ref"]["binding"][field] = bad
  invalid(value)


def test_root_is_a_normalized_absolute_path():
  value = domain(); value["resources"][RESOURCE]["cache"] = "/"
  assert decode(encode(value), kind="domain") == value


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\n", "name with spaces", "a" * 193])
def test_runtime_identity_is_safe_bounded_ascii(bad):
  value = domain(); value["resources"][RESOURCE]["runtime_identity"] = bad; invalid(value)


@pytest.mark.parametrize("field", ["machine", "profile"])
@pytest.mark.parametrize("bad", ["", "a/b", "a\n", ".", "..", "a" * 129])
def test_binding_tokens_are_strict(field, bad):
  value = domain(); value["reservations"][RUN]["owner_ref"]["binding"][field] = bad; invalid(value)


@pytest.mark.parametrize("factory,key_field", [(anchor, "resource_key"), (domain, None)])
def test_resource_key_digest_and_runtime_kind_are_checked(factory, key_field):
  for replacement in [{"key_id": "0" * 64}, ResourceKey("instance", 7, 11).as_dict()]:
    value = factory()
    key = value[key_field] if key_field else value["resources"][RESOURCE]["key"]
    key.update(replacement); invalid(value)


@pytest.mark.parametrize("table", ["reservations", "intents"])
@pytest.mark.parametrize("refs", [[], [RESOURCE, RESOURCE], ["f" * 32]])
def test_resource_references_are_existing_nonempty_unique(table, refs):
  value = domain(); next(iter(value[table].values()))["resources"] = refs; invalid(value)


@pytest.mark.parametrize("runs", [[RUN, RUN], ["f" * 32]])
def test_selected_run_references_are_existing_unique(runs):
  value = domain(); value["intents"][BATCH]["selected_runs"] = runs; invalid(value)


def test_selected_run_requires_actual_resource_intersection():
  value = domain(); other = "f" * 32
  value["resources"][other] = {**deepcopy(value["resources"][RESOURCE]), "resource_id": other}
  value["reservations"][RUN]["resources"] = [other]
  invalid(value)


def test_selected_runs_may_be_empty():
  value = domain(); value["intents"][BATCH]["selected_runs"] = []
  assert decode(encode(value), kind="domain") == value


def test_op_id_cannot_be_reused_across_runs():
  value = domain(); other = "f" * 32
  value["reservations"][other] = {**deepcopy(value["reservations"][RUN]), "run_id": other}
  invalid(value)


@pytest.mark.parametrize("raw", [
  b'{"kind":"domain","kind":"domain"}', b'{"x":{"device":1,"device":1}}',
  b'{"kind":"domain","x":NaN}', b'{"x":Infinity}', b'{"x":1.0}', b'{"x":1e0}',
  b'\xff', b'\xef\xbb\xbf{}', b'{} {}', b'[]', b'null', b'true', b'',
])
def test_invalid_json_grammar_types_or_duplicates_are_redacted(raw):
  reject(lambda: decode(raw, kind="domain"))


def test_size_limit_is_two_mib_including_whitespace_and_newline():
  raw = encode(domain())
  assert decode(b" " * (2 * 1024 * 1024 - len(raw)) + raw, kind="domain") == domain()
  reject(lambda: decode(b" " * (2 * 1024 * 1024 + 1), kind="domain"))
  value = domain(); value["resources"][RESOURCE]["cache"] = "/" + "a" * (2 * 1024 * 1024)
  reject(lambda: encode(value))


def test_deep_and_cyclic_inputs_are_bounded_and_redacted():
  reject(lambda: decode(b"[" * 10000 + b"0" + b"]" * 10000, kind="domain"))
  value = domain(); value["cycle"] = value
  reject(lambda: encode(value))


@pytest.mark.parametrize("value", [None, True, [], "synthetic-private", {"kind": "private"}])
def test_encode_requires_recognized_object(value):
  reject(lambda: encode(value))


def test_runtime_identity_allows_internal_double_dot_like_repository_safe_id():
  value = domain(); value["resources"][RESOURCE]["runtime_identity"] = "runtime..identity"
  assert decode(encode(value), kind="domain") == value


@pytest.mark.parametrize("location", ["root", "nested"])
def test_duplicate_keys_in_otherwise_valid_record_are_rejected(location):
  raw = encode(domain())
  original = b'"revision":0' if location == "root" else b'"device":2'
  duplicate = b'"revision":0,"revision":0' if location == "root" else b'"device":2,"device":2'
  assert original in raw
  reject(lambda: decode(raw.replace(original, duplicate, 1), kind="domain"))


@pytest.mark.parametrize("table,field,allowed", [
  ("resources", "status", "preparing"), ("resources", "status", "ready"), ("resources", "status", "unknown"),
  ("reservations", "phase", "reserved"), ("reservations", "phase", "dispatched"),
  ("reservations", "phase", "unknown"), ("reservations", "phase", "cancelled"),
  ("intents", "phase", "active"), ("intents", "phase", "dispatched"),
  ("intents", "phase", "unknown"), ("intents", "phase", "cancelled"),
  ("intents", "operation", "setup"), ("intents", "operation", "stop_only"),
])
def test_protocol_enums_remain_data_without_invented_admission(table, field, allowed):
  value = domain(); next(iter(value[table].values()))[field] = allowed
  assert decode(encode(value), kind="domain") == value


@pytest.mark.parametrize("table,field,bad", [
  ("resources", "status", "complete"), ("reservations", "phase", "ready"),
  ("intents", "phase", "complete"), ("intents", "operation", "stop"),
])
def test_unrecognized_protocol_states_are_rejected(table, field, bad):
  value = domain(); next(iter(value[table].values()))[field] = bad; invalid(value)


def test_identity_length_limits_include_maximum_ascii_values():
  value = domain()
  value["resources"][RESOURCE]["runtime_identity"] = "a" * 192
  value["reservations"][RUN]["owner_ref"]["binding"].update(machine="m" * 128, profile="p" * 128)
  assert decode(encode(value), kind="domain") == value


@pytest.mark.parametrize("bad", ["/line\npath", "/tab\tpath", "/back\\slash", "/delete\x7fpath", "/bad\ud800path"])
def test_path_controls_backslash_and_invalid_unicode_are_rejected(bad):
  value = domain(); value["resources"][RESOURCE]["cache"] = bad; invalid(value)


@pytest.mark.parametrize("raw", ["{}", bytearray(b"{}"), memoryview(b"{}"), None])
def test_decode_requires_utf8_bytes(raw):
  reject(lambda: decode(raw, kind="domain"))


def test_static_schema_is_valid_and_validator_load_is_lazy_cached(monkeypatch):
  from pathlib import Path
  from jsonschema import Draft202012Validator
  from agentcfg import resource_protocol
  schema_path = Path(resource_protocol.__file__).resolve().parents[2] / "schemas/rotom/resource-coordination.schema.json"
  schema = json.loads(schema_path.read_bytes())
  Draft202012Validator.check_schema(schema)
  resource_protocol._validators.cache_clear()
  reads = []
  original = Path.read_bytes
  def read_own_schema(path):
    assert path == schema_path, "codec must never open a record path or native body"
    reads.append(path)
    return original(path)
  monkeypatch.setattr(Path, "read_bytes", read_own_schema)
  for value in [domain(), anchor(), domain()]:
    assert decode(encode(value), kind=value["kind"]) == value
  assert reads == [schema_path]


def test_encode_allows_exact_two_mib_and_rejects_the_next_byte():
  value = domain()
  remainder = 2 * 1024 * 1024 - len(encode(value))
  value["resources"][RESOURCE]["cache"] += "a" * remainder
  raw = encode(value)
  assert len(raw) == 2 * 1024 * 1024
  assert decode(raw, kind="domain") == value
  value["resources"][RESOURCE]["cache"] += "a"
  reject(lambda: encode(value))


def test_schema_itself_rejects_unnormalized_and_control_paths():
  from agentcfg import resource_protocol
  validator = resource_protocol._validators()["domain"]
  for bad in ["relative", "/a/../b", "/a/./b", "/a//b", "/a/", "//a", "/a\n", "/a\\b"]:
    value = domain(); value["resources"][RESOURCE]["cache"] = bad
    assert not validator.is_valid(value)
