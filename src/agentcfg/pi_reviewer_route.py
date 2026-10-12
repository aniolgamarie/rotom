"""纯非秘密reviewer路线匹配；不IO、读取账户、检查时钟或执行SDK。

调用方须先检查公开describe及private完整Model baseline（含headers），提供
可信configuration_identity，并另验owner安装、价目真实性、当前窗口及资格。
本组件不证明调用方受信、不签permit，也未接产品factory。
"""
from copy import deepcopy
import hashlib
import json
import re

from .pi_reviewer_authority_protocol import validate_authority, authority_identity, price_identity, RATES
from .schema import ConfigError

MODEL_FIELDS = ("provider", "id", "api", "baseUrl", "input", "contextWindow", "maxTokens", "configuration_identity")
LEVELS = ("off", "minimal", "low", "medium", "high", "xhigh", "max")


def _invalid():
  raise ConfigError("PI_RISK_REVIEW_ROUTE_INVALID") from None


def _mapping(value):
  if type(value) is not dict or any(type(key) is not str for key in value): _invalid()


def _closed(value, keys):
  _mapping(value)
  if set(value) != set(keys): _invalid()


def _identifier(value, maximum=512):
  if type(value) is not str or not 1 <= len(value) <= maximum or any(not "!" <= char <= "~" for char in value): _invalid()


def _text(value, maximum=4096):
  if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum or any(ord(char) < 32 or ord(char) == 127 for char in value): _invalid()


def _integer(value):
  if type(value) is not int or not 1 <= value <= 2**53 - 1: _invalid()


def _input(value):
  if type(value) is not list or not 1 <= len(value) <= 2 or any(type(item) is not str or item not in ("text", "image") for item in value) or len(set(value)) != len(value) or "text" not in value: _invalid()


def _strings(value):
  if type(value) is not list or len(value) > 4096: _invalid()
  for item in value: _identifier(item)
  if len(set(value)) != len(value): _invalid()


def _model_row(row):
  _mapping(row)
  if not {"id", "input"} <= set(row) or set(row) - {"id", "input", "name", "reasoning", "contextWindow", "maxTokens", "thinkingLevelMap", "compat"}: _invalid()
  _identifier(row["id"]); _input(row["input"])
  if "name" in row: _text(row["name"])
  if "reasoning" in row and type(row["reasoning"]) is not bool: _invalid()
  for key in ("contextWindow", "maxTokens"):
    if key in row: _integer(row[key])
  if "thinkingLevelMap" in row:
    _mapping(row["thinkingLevelMap"])
    if set(row["thinkingLevelMap"]) - set(LEVELS): _invalid()
    for value in row["thinkingLevelMap"].values():
      if value is not None: _text(value)
  if "compat" in row:
    compat = row["compat"]; _mapping(compat)
    if set(compat) - {"requiresReasoningContentOnAssistantMessages", "thinkingFormat"}: _invalid()
    if "requiresReasoningContentOnAssistantMessages" in compat and type(compat["requiresReasoningContentOnAssistantMessages"]) is not bool: _invalid()
    if "thinkingFormat" in compat and (type(compat["thinkingFormat"]) is not str or compat["thinkingFormat"] != "deepseek"): _invalid()


def _match(authority, manifest, role, model):
  value = validate_authority(authority)
  _closed(model, MODEL_FIELDS)
  for key in ("provider", "id", "api"): _identifier(model[key])
  _input(model["input"])
  _integer(model["contextWindow"]); _integer(model["maxTokens"])
  if type(model["configuration_identity"]) is not str or not re.fullmatch("[0-9a-f]{64}", model["configuration_identity"]): _invalid()
  # endpoint已由authority协议验证；只接受同一明确endpoint，绝不补默认。
  if type(model["baseUrl"]) is not str or model["baseUrl"] != value["route"]["base_url"]: _invalid()
  _mapping(manifest); _identifier(role, 256)
  bindings = manifest["model_bindings"]; _mapping(bindings)
  selected = bindings[role]; _closed(selected, ("provider", "model"))
  for item in selected.values(): _identifier(item)
  if selected != {"provider": model["provider"], "model": model["id"]}: _invalid()
  allowed = manifest["allowed_models"]
  if type(allowed) is not list or not 1 <= len(allowed) <= 4096: _invalid()
  for row in allowed:
    _closed(row, ("provider", "model"))
    for item in row.values(): _identifier(item)
  if sum(row == selected for row in allowed) != 1: _invalid()
  providers = manifest["provider_bindings"]; _mapping(providers)
  binding = providers[model["provider"]]; _closed(binding, ("logical_id", "auth_kind", "owner"))
  for item in binding.values(): _identifier(item, 256)
  config = manifest["model_configuration"]; _closed(config, ("schema_version", "providers"))
  if type(config["schema_version"]) is not int or config["schema_version"] != 1: _invalid()
  _mapping(config["providers"])
  provider = config["providers"][model["provider"]]
  _closed(provider, ("logical_id", "auth_kind", "owner", "credential_ref", "config"))
  for key in binding: _identifier(provider[key], 256)
  if {key: provider[key] for key in binding} != binding: _invalid()
  if binding["auth_kind"] == "api-key":
    if binding["owner"] != "pi-environment": _invalid()
    reference = provider["credential_ref"]
    if type(reference) is not str or not reference.startswith("secret:") or len(reference) > 8192: _invalid()
    _identifier(reference[7:], 8185)
    if "/" in reference or "\\" in reference or ".." in reference: _invalid()
    declaration = provider["config"]; _closed(declaration, ("api", "baseUrl", "models"))
    _identifier(declaration["api"])
    if type(declaration["baseUrl"]) is not str: _invalid()
    if declaration["api"] != model["api"] or declaration["baseUrl"] != model["baseUrl"]: _invalid()
    rows = declaration["models"]
    if type(rows) is not list or not 1 <= len(rows) <= 4096: _invalid()
    for row in rows: _model_row(row)
    matches = [row for row in rows if row["id"] == model["id"]]
    if len(matches) != 1: _invalid()
    row = matches[0]
    if row["input"] != model["input"] or row.get("contextWindow", 128000) != model["contextWindow"] or row.get("maxTokens", 16384) != model["maxTokens"]: _invalid()
  elif binding["auth_kind"] == "oauth":
    if provider["credential_ref"] is not None or provider["config"] is not None: _invalid()
    if binding["owner"] != "pi-native":
      plugins = manifest["plugins"]; bootstrap = manifest["bootstrap_plugins"]
      _strings(plugins); _strings(bootstrap)
      if binding["owner"] not in plugins or binding["owner"] not in bootstrap: _invalid()
  else: _invalid()
  route = {"logical_provider": binding["logical_id"], "native_route": model["provider"], "model_id": model["id"], "auth_kind": binding["auth_kind"], "owner": binding["owner"], "api": model["api"], "base_url": model["baseUrl"]}
  if route != value["route"]: _invalid()
  tokens = value["token_limits"]
  if tokens["input_tokens"] + tokens["output_tokens"] > model["contextWindow"] or tokens["output_tokens"] > model["maxTokens"]: _invalid()
  encoded = json.dumps({"route": route, "model": model}, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
  pricing = {"identity": price_identity(value), "currency": value["pricing"]["currency"], **{key: value["pricing"][key] for key in RATES}}
  return deepcopy({"route": route, "model_identity": hashlib.sha256(encoded).hexdigest(), "authority_document_identity": authority_identity(value), "pricing": pricing, "limits": value["limits"], "token_limits": tokens, "categories": value["categories"]})


def match_reviewer_route(authority, *, manifest, role, model):
  try:
    return _match(authority, manifest, role, model)
  except Exception:
    _invalid()
