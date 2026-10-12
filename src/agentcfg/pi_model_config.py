"""从已选部署声明构造模型配置；不解析秘密、读取账号或环境变量。"""

from copy import deepcopy
from urllib.parse import urlsplit
import unicodedata

from .schema import ConfigError


_LEVELS = frozenset(("off", "minimal", "low", "medium", "high", "xhigh", "max"))
_MODEL_FIELDS = frozenset(("provider", "remote_id", "input", "name", "reasoning", "context_window", "max_output_tokens",
  "max_output_supported", "source", "reasoning_efforts", "pricing", "native"))
_PROVIDER_FIELDS = frozenset(("protocol", "auth_kind", "base_url", "base_url_ref", "credential_ref", "omp_auth_header"))


def _closed(value, fields):
  if not isinstance(value, dict) or set(value) - set(fields): raise ConfigError("pi-model-config-fields")


def validate_endpoint(value):
  """新profile只接受字面HTTP端点；错误不携带可能含凭据的URL。"""
  try:
    if (not isinstance(value, str) or not value or any(char.isspace() or unicodedata.category(char) in ("Cc", "Cf", "Cs") for char in value)
        or any(char in value for char in ("\\", "?", "#", "$"))): raise ValueError
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None
        or parsed.netloc.endswith(":")): raise ValueError
    if parsed.port is not None and not 1 <= parsed.port <= 65535: raise ValueError
  except (ValueError, TypeError):
    raise ConfigError("pi-model-config-endpoint") from None


def _native_fields(model, settings):
  # 固定投影allowlist独立于将来registry schema扩充，不能透传headers/apiKey/token。
  _closed(model, _MODEL_FIELDS)
  native = model.get("native", {})
  _closed(native, ("pi", "omp"))
  pi = native.get("pi", {})
  _closed(pi, ("compat",))
  compat = pi.get("compat", {})
  _closed(compat, ("requiresReasoningContentOnAssistantMessages", "thinkingFormat", "reasoningEffortMap"))
  if "requiresReasoningContentOnAssistantMessages" in compat and type(compat["requiresReasoningContentOnAssistantMessages"]) is not bool:
    raise ConfigError("pi-model-config-fields")
  if "thinkingFormat" in compat and compat["thinkingFormat"] != "deepseek": raise ConfigError("pi-model-config-fields")
  if "reasoningEffortMap" in compat:
    mapping = compat["reasoningEffortMap"]
    _closed(mapping, _LEVELS - {"off"})
    if any(value not in ("low", "high", "max") for value in mapping.values()): raise ConfigError("pi-model-config-fields")
  _closed(settings, ("reasoning", "thinking_level_map", "disabled_thinking_levels"))
  if "reasoning" in settings and type(settings["reasoning"]) is not bool: raise ConfigError("pi-model-config-fields")
  if "thinking_level_map" in settings:
    mapping = settings["thinking_level_map"]
    _closed(mapping, _LEVELS)
    if any(not isinstance(value, str) or not value or "\0" in value for value in mapping.values()): raise ConfigError("pi-model-config-fields")
  if "disabled_thinking_levels" in settings:
    disabled = settings["disabled_thinking_levels"]
    if not isinstance(disabled, list) or any(not isinstance(value, str) or value not in _LEVELS for value in disabled): raise ConfigError("pi-model-config-fields")
    if set(settings.get("thinking_level_map", {})) & set(disabled): raise ConfigError("pi-thinking-level-conflict")


def provider_config(data, identity, *, strict=False):
  """与models.json字段同源；strict仅用于新profile的现代产物及公开投影。"""
  provider = data["providers"][identity]
  if strict:
    _closed(provider, _PROVIDER_FIELDS)
    validate_endpoint(provider["base_url"])
  values = {"baseUrl": provider["base_url"], "api": data["adapter_documents"]["bindings"]["protocols"][provider["protocol"]]}
  models = []
  for model_id, model in data["models"].items():
    if model["provider"] != identity: continue
    settings = data["profile"]["agent_options"].get("model_settings", {}).get(model_id, {})
    if strict: _native_fields(model, settings)
    native = {"id": model["remote_id"], "input": deepcopy(model["input"])}
    for key in ("name", "reasoning"):
      if key in model: native[key] = deepcopy(model[key])
    native.update(deepcopy(model.get("native", {}).get("pi", {})))
    if strict and "reasoningEffortMap" in native.get("compat", {}):
      # 官方1.0.1只读取顶层字段；旧映射作为默认，显式设置随后覆盖。
      native["thinkingLevelMap"] = native["compat"].pop("reasoningEffortMap")
      if not native["compat"]: del native["compat"]
    for key, target in (("context_window", "contextWindow"), ("max_output_tokens", "maxTokens")):
      if key in model: native[target] = model[key]
    for key, target in (("reasoning", "reasoning"), ("thinking_level_map", "thinkingLevelMap")):
      if key in settings:
        if strict and key == "thinking_level_map": native.setdefault(target, {}).update(deepcopy(settings[key]))
        else: native[target] = deepcopy(settings[key])
    if "disabled_thinking_levels" in settings:
      native.setdefault("thinkingLevelMap", {}).update({level: None for level in settings["disabled_thinking_levels"]})
    models.append(native)
  values["models"] = models
  return deepcopy(values)


def model_configuration(data, route):
  """调用方提供PiAdapter.route；OAuth只声明来源，不能伪造未知原生配置。"""
  providers = {}
  for identity, provider in data["providers"].items():
    _closed(provider, _PROVIDER_FIELDS)
    native_route = route(data, identity)
    if native_route in providers: raise ConfigError("pi-model-config-route")
    oauth = provider["auth_kind"] == "oauth"
    if provider["auth_kind"] not in ("oauth", "api-key"): raise ConfigError("pi-model-config-fields")
    providers[native_route] = {"logical_id": identity, "auth_kind": provider["auth_kind"],
      "owner": data["adapter_documents"]["bindings"]["oauth"][identity]["owner"] if oauth else "pi-environment",
      "credential_ref": None if oauth else provider["credential_ref"], "config": None if oauth else provider_config(data, identity, strict=True)}
  return deepcopy({"schema_version": 1, "providers": providers})
