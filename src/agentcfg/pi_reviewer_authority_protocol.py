"""非秘密账户authority的纯协议；不读取账户/配置，不签许可或执行SDK。

owner、路线与价目来源只验证声明形状；可信调用方仍须核对安装声明及当前
公开SDKdescriptor，不能凭本记录自证认证、价格真实性或自动审批资格。
"""
from copy import deepcopy
from datetime import date
import hashlib
import json
import re
from urllib.parse import urlsplit

from .pi_model_config import validate_endpoint
from .schema import ConfigError
from .storage import Conflict

MAX_BYTES = 16384
FIELDS = ("schema_version", "authority_ref", "generation", "route", "pricing", "limits", "token_limits", "categories", "valid_from", "valid_until")
ROUTE = ("logical_provider", "native_route", "model_id", "auth_kind", "owner", "api", "base_url")
RATES = ("input_units_per_million", "output_units_per_million", "cache_read_units_per_million", "cache_write_units_per_million")
PRICING = ("revision", "currency", *RATES, "source", "checked_on")
APIS = ("openai-completions", "openai-responses", "openai-codex-responses")


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_AUTHORITY_INVALID") from None


def _closed(value, keys):
  if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != set(keys): _invalid()


def _integer(value, low, high):
  if type(value) is not int or not low <= value <= high: _invalid()


def _hex(value, length):
  if type(value) is not str or not re.fullmatch("[0-9a-f]{" + str(length) + "}", value): _invalid()


def _identifier(value, maximum):
  if type(value) is not str or not 1 <= len(value) <= maximum or any(not "!" <= char <= "~" for char in value): _invalid()


def _currency(value):
  if type(value) is not str or not re.fullmatch("[A-Z]{3}", value): _invalid()


def _endpoint(value, *, source=False):
  if type(value) is not str or not 1 <= len(value) <= (2048 if source else MAX_BYTES): _invalid()
  try:
    if source and len(value.encode("utf-8")) > 2048: _invalid()
    validate_endpoint(value)
    if source and urlsplit(value).scheme != "https": _invalid()
  except (ValueError, UnicodeError, ConfigError):
    _invalid()


def _canonical(value):
  return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def validate_authority(value):
  _closed(value, FIELDS)
  _integer(value["schema_version"], 1, 1)
  _hex(value["authority_ref"], 32)
  _integer(value["generation"], 1, 1000000)
  route = value["route"]; _closed(route, ROUTE)
  for key in ("logical_provider", "native_route", "owner"): _identifier(route[key], 256)
  _identifier(route["model_id"], 512); _identifier(route["api"], 64)
  if type(route["auth_kind"]) is not str or route["auth_kind"] not in ("api-key", "oauth"): _invalid()
  if route["api"] not in APIS: _invalid()
  if route["auth_kind"] == "api-key":
    if route["owner"] != "pi-environment" or route["api"] not in APIS[:2]: _invalid()
  else:
    # 插件ID只是形状，安装受信关系由调用方核对；pi-environment不是OAuth owner。
    if route["owner"] == "pi-environment" or not re.fullmatch("[a-z][a-z0-9_-]{0,255}", route["owner"]): _invalid()
    if route["api"] == "openai-codex-responses" and (route["native_route"] != "openai-codex" or route["owner"] != "pi-native"): _invalid()
  _endpoint(route["base_url"])
  pricing = value["pricing"]; _closed(pricing, PRICING)
  _hex(pricing["revision"], 32); _currency(pricing["currency"])
  for key in RATES: _integer(pricing[key], 0, 10**15)
  _endpoint(pricing["source"], source=True)
  checked = pricing["checked_on"]
  if type(checked) is not str or not re.fullmatch("[0-9]{4}-[0-9]{2}-[0-9]{2}", checked): _invalid()
  try: date.fromisoformat(checked)
  except ValueError: _invalid()
  limits = value["limits"]; _closed(limits, ("currency", "max_calls", "max_cost_units"))
  _currency(limits["currency"])
  if limits["currency"] != pricing["currency"]: _invalid()
  _integer(limits["max_calls"], 0, 1000000); _integer(limits["max_cost_units"], 0, 10**18)
  tokens = value["token_limits"]; _closed(tokens, ("input_tokens", "output_tokens"))
  _integer(tokens["input_tokens"], 1, 10000000); _integer(tokens["output_tokens"], 1, 4096)
  categories = value["categories"]
  if type(categories) is not list or not 1 <= len(categories) <= 3: _invalid()
  if any(type(item) is not str or item not in ("file-read", "file-write", "shell") for item in categories): _invalid()
  if categories != sorted(set(categories)): _invalid()
  _integer(value["valid_from"], 0, 2**53 - 1); _integer(value["valid_until"], 0, 2**53 - 1)
  if value["valid_from"] >= value["valid_until"]: _invalid()
  if len(_canonical(value)) > MAX_BYTES: _invalid()
  return deepcopy(value)


def _pairs(items):
  result = {}
  for key, value in items:
    if key in result: _invalid()
    result[key] = value
  return result


def decode_authority(raw):
  if type(raw) is not bytes or not 1 <= len(raw) <= MAX_BYTES: _invalid()
  try:
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=lambda _: _invalid())
  except (ValueError, UnicodeError, RecursionError):
    _invalid()
  return validate_authority(value)


def encode_authority(value):
  return _canonical(validate_authority(value))


def authority_identity(value):
  return hashlib.sha256(encode_authority(value)).hexdigest()


def price_identity(value):
  return hashlib.sha256(_canonical(validate_authority(value)["pricing"])).hexdigest()


def validate_update(old, new):
  previous, result = validate_authority(old), validate_authority(new)
  if (result["authority_ref"] != previous["authority_ref"] or result["generation"] != previous["generation"] + 1
      or result["limits"]["currency"] != previous["limits"]["currency"]
      or result["limits"]["max_calls"] > previous["limits"]["max_calls"]
      or result["limits"]["max_cost_units"] > previous["limits"]["max_cost_units"]): _invalid()
  return result


def check_effective(value, now):
  if type(now) is not int: _invalid()
  authority = validate_authority(value)
  if not authority["valid_from"] <= now < authority["valid_until"]: raise Conflict("REVIEW_AUTHORITY_INACTIVE")
