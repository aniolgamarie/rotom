"""纯协议/合成路线与价目；不读取账户、文件或执行SDK。"""
from copy import deepcopy
import hashlib
import json

import pytest

from agentcfg import pi_reviewer_authority_protocol as protocol
from agentcfg.schema import ConfigError
from agentcfg.storage import Conflict


def authority():
  return {"schema_version": 1, "authority_ref": "a" * 32, "generation": 1,
    "route": {"logical_provider": "synthetic", "native_route": "synthetic-route", "model_id": "synthetic-model",
      "auth_kind": "api-key", "owner": "pi-environment", "api": "openai-completions", "base_url": "https://example.invalid/v1"},
    "pricing": {"revision": "b" * 32, "currency": "USD", "input_units_per_million": 1000000,
      "output_units_per_million": 2000000, "cache_read_units_per_million": 500000, "cache_write_units_per_million": 3000000,
      "source": "https://example.invalid/pricing", "checked_on": "2026-10-05"},
    "limits": {"currency": "USD", "max_calls": 20, "max_cost_units": 1000000},
    "token_limits": {"input_tokens": 100, "output_tokens": 10}, "categories": ["file-read", "file-write", "shell"],
    "valid_from": 100, "valid_until": 200}


def test_valid_record_is_independent_canonical_and_roundtrips():
  value = authority(); saved = deepcopy(value)
  copied = protocol.validate_authority(value)
  assert copied == value and copied is not value
  copied["pricing"]["input_units_per_million"] = 0; copied["categories"].clear()
  assert value == saved
  raw = protocol.encode_authority(value)
  assert type(raw) is bytes and raw.isascii() and not raw.endswith(b"\n")
  assert protocol.decode_authority(raw) == saved
  assert protocol.authority_identity(value) == hashlib.sha256(raw).hexdigest()
  reordered = dict(reversed(list(value.items())))
  assert protocol.encode_authority(reordered) == raw


@pytest.mark.parametrize("path,value", [
  (("schema_version",), True), (("schema_version",), 2), (("authority_ref",), "A" * 32), (("generation",), 0), (("generation",), 1000001),
  (("generation",), True), (("route", "logical_provider"), "space name"), (("route", "logical_provider"), "line\nbreak"),
  (("route", "logical_provider"), "é"), (("route", "model_id"), "x" * 513), (("route", "model_id"), "\ud800"),
  (("route", "auth_kind"), "none"), (("route", "owner"), "pi-native"), (("route", "api"), "made-up-api"),
  (("route", "base_url"), None), (("route", "base_url"), "https://key@example.invalid"),
  (("route", "base_url"), "https://example.invalid?key=synthetic"), (("route", "base_url"), "https://example.invalid/#fragment"),
  (("route", "base_url"), "https://example.invalid\\evil"), (("route", "base_url"), "https://example.invalid/$KEY"),
  (("route", "base_url"), "https://example.invalid:"), (("route", "base_url"), "https://example.invalid:65536"),
  (("pricing", "revision"), "0" * 31), (("pricing", "currency"), "usd"), (("pricing", "input_units_per_million"), -1),
  (("pricing", "output_units_per_million"), 10**15 + 1), (("pricing", "cache_read_units_per_million"), True),
  (("pricing", "cache_write_units_per_million"), 1.0), (("pricing", "source"), "http://example.invalid/pricing"),
  (("pricing", "source"), "https://example.invalid?secret=x"), (("pricing", "checked_on"), "2026-02-29"),
  (("pricing", "checked_on"), "2026-1-01"), (("pricing", "checked_on"), "0000-01-01"),
  (("limits", "currency"), "EUR"), (("limits", "max_calls"), 1000001), (("limits", "max_calls"), True),
  (("limits", "max_cost_units"), 10**18 + 1), (("token_limits", "input_tokens"), 0), (("token_limits", "output_tokens"), 4097),
  (("categories",), []), (("categories",), ["shell", "file-read"]), (("categories",), ["shell", "shell"]),
  (("categories",), ["human"]), (("categories",), ("shell",)), (("valid_from",), True), (("valid_from",), -1),
  (("valid_until",), 100), (("valid_until",), 2**53),
])
def test_closed_types_and_numeric_route_price_boundaries(path, value):
  item = authority(); target = item
  for key in path[:-1]: target = target[key]
  target[path[-1]] = value
  with pytest.raises(ConfigError) as error: protocol.validate_authority(item)
  assert error.value.code == "PI_RISK_REVIEW_AUTHORITY_INVALID"
  assert str(value) not in str(error.value) if len(str(value)) > 20 else True


@pytest.mark.parametrize("container,field", [(None, "secret"), ("route", "credential_ref"), ("route", "headers"), ("route", "auth_file"),
  ("pricing", "identity"), ("limits", "reset"), ("token_limits", "default")])
def test_unknown_secret_fields_never_leak(container, field):
  item = authority(); (item if container is None else item[container])[field] = "SYNTHETIC_PRIVATE_BODY"
  with pytest.raises(ConfigError) as error: protocol.encode_authority(item)
  assert error.value.code == "PI_RISK_REVIEW_AUTHORITY_INVALID" and "SYNTHETIC_PRIVATE_BODY" not in str(error.value)


@pytest.mark.parametrize("raw", [b"", b"{}", b"[]", b"null", b"NaN", b"{\"schema_version\":1,\"schema_version\":1}",
  b'{"route":{"owner":1,"\\u006fwner":2}}', b"{} trailing", b"\xff", b" " * 16385, "{}", bytearray(b"{}")])
def test_raw_document_bound_duplicate_and_nonfinite(raw):
  with pytest.raises(ConfigError) as error: protocol.decode_authority(raw)
  assert error.value.code == "PI_RISK_REVIEW_AUTHORITY_INVALID"


def test_price_identity_changes_only_for_actual_price_revision_or_fields():
  first = authority(); second = deepcopy(first); second["generation"] += 1
  assert protocol.price_identity(first) == protocol.price_identity(second)
  assert protocol.authority_identity(first) != protocol.authority_identity(second)
  second["pricing"]["revision"] = "c" * 32
  assert protocol.price_identity(first) != protocol.price_identity(second)
  second = deepcopy(first); second["route"]["model_id"] = "new-model"
  assert protocol.price_identity(first) == protocol.price_identity(second)
  assert protocol.authority_identity(first) != protocol.authority_identity(second)


def test_explicit_free_price_and_valid_leap_day_are_allowed():
  item = authority()
  for field in ("input_units_per_million", "output_units_per_million", "cache_read_units_per_million", "cache_write_units_per_million"): item["pricing"][field] = 0
  item["pricing"]["checked_on"] = "2024-02-29"
  item["limits"].update(max_calls=0, max_cost_units=0)
  assert protocol.validate_authority(item) == item
  del item["pricing"]["source"]
  with pytest.raises(ConfigError): protocol.validate_authority(item)


@pytest.mark.parametrize("owner", ["pi-native", "pi-cursor"])
def test_oauth_requires_explicit_endpoint_and_declared_owner_shape(owner):
  item = authority(); item["route"].update(auth_kind="oauth", owner=owner)
  assert protocol.validate_authority(item) == item
  del item["route"]["base_url"]
  with pytest.raises(ConfigError): protocol.validate_authority(item)


def test_update_preserves_ref_and_cumulative_currency_and_nonincrease():
  old = authority(); new = deepcopy(old); new["generation"] = 2
  new["limits"].update(max_calls=10, max_cost_units=0); new["categories"] = ["file-read"]
  assert protocol.validate_update(old, new) == new
  assert old == authority()


@pytest.mark.parametrize("kind", ["generation", "skip", "ref", "currency", "calls", "cost"])
def test_updates_cannot_reauthorize_by_reset_or_increase(kind):
  old = authority(); new = deepcopy(old); new["generation"] = 2
  if kind == "generation": new["generation"] = 1
  if kind == "skip": new["generation"] = 3
  if kind == "ref": new["authority_ref"] = "d" * 32
  if kind == "currency": new["pricing"]["currency"] = new["limits"]["currency"] = "EUR"
  if kind == "calls": new["limits"]["max_calls"] += 1
  if kind == "cost": new["limits"]["max_cost_units"] += 1
  with pytest.raises(ConfigError): protocol.validate_update(old, new)


@pytest.mark.parametrize("now,active", [(99, False), (100, True), (199, True), (200, False)])
def test_effective_window_is_half_open(now, active):
  if active: assert protocol.check_effective(authority(), now) is None
  else:
    with pytest.raises(Conflict, match="^REVIEW_AUTHORITY_INACTIVE$"): protocol.check_effective(authority(), now)

@pytest.mark.parametrize("now", [True, 100.0, "100", None])
def test_effective_time_requires_exact_int(now):
  with pytest.raises(ConfigError): protocol.check_effective(authority(), now)

@pytest.mark.parametrize("api,auth_kind,native_route,owner,allowed", [
  ("openai-completions", "api-key", "custom", "pi-environment", True),
  ("openai-responses", "api-key", "custom", "pi-environment", True),
  ("openai-codex-responses", "api-key", "openai-codex", "pi-environment", False),
  ("openai-codex-responses", "oauth", "openai-codex", "pi-native", True),
  ("openai-codex-responses", "oauth", "cursor", "pi-cursor", False),
  ("openai-responses", "oauth", "cursor", "pi-cursor", True),
  ("openai-responses", "oauth", "custom", "pi-environment", False),
])
def test_fixed_supported_api_boundary_not_arbitrary_protocol(api, auth_kind, native_route, owner, allowed):
  item = authority(); item["route"].update(api=api, auth_kind=auth_kind, native_route=native_route, owner=owner)
  if allowed: assert protocol.validate_authority(item) == item
  else:
    with pytest.raises(ConfigError): protocol.validate_authority(item)

@pytest.mark.parametrize("field", ["input_units_per_million", "output_units_per_million", "cache_read_units_per_million", "cache_write_units_per_million"])
def test_integer_rate_upper_limit_valid_and_each_price_change_invalidates(field):
  item = authority(); before = protocol.price_identity(item)
  item["pricing"][field] = 10**15
  assert protocol.validate_authority(item) == item
  assert protocol.price_identity(item) != before


def test_nested_duplicate_and_nonfinite_in_otherwise_valid_record():
  raw = protocol.encode_authority(authority())
  mutated = raw.replace(b'"owner":"pi-environment"', b'"owner":"pi-environment","\\u006fwner":"pi-environment"')
  with pytest.raises(ConfigError): protocol.decode_authority(mutated)
  for number in (b"NaN", b"Infinity", b"-Infinity", b"1.0", b"1e0", b"1.00000000000000001"):
    with pytest.raises(ConfigError): protocol.decode_authority(raw.replace(b'"generation":1', b'"generation":' + number))


def test_missing_explicit_rate_cannot_be_defaulted_to_free():
  item = authority(); del item["pricing"]["cache_write_units_per_million"]
  with pytest.raises(ConfigError): protocol.validate_authority(item)


def test_date_source_and_document_bounds_fail_without_original_cause():
  item = authority(); item["pricing"]["source"] = "https://example.invalid/" + "x" * 2048
  with pytest.raises(ConfigError) as error: protocol.validate_authority(item)
  assert error.value.__cause__ is None and error.value.__suppress_context__ is True
  item = authority(); item["route"]["base_url"] = "https://example.invalid/" + "x" * 16384
  with pytest.raises(ConfigError): protocol.encode_authority(item)
  with pytest.raises(ConfigError): protocol.decode_authority(b"[" * 2000 + b"]" * 2000)


def test_input_nonstring_key_rejected_without_formatting_it():
  class Key:
    def __str__(self): raise AssertionError("must not format raw key")
  item = authority(); item[Key()] = "synthetic"
  with pytest.raises(ConfigError): protocol.validate_authority(item)
