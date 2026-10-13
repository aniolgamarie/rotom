"""OMP kernel 配置的显式非秘密字段契约；不接受任意原生配置透传。"""

from copy import deepcopy
import re

from .schema import ConfigError
from .omp_model_presets import materialize_presets, validate_fallback_chains


def closed(properties, required=()):
  return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def enum(*values):
  return {"type": "string", "enum": list(values)}


TEXT = {"type": "string", "minLength": 1}
BOOL = {"type": "boolean"}
POSITIVE = {"type": "integer", "minimum": 1}
TEXTS = {"type": "array", "items": TEXT}
THINKING = enum("off", "minimal", "low", "medium", "high", "xhigh", "max", "auto")
APPROVAL = enum("allow", "deny", "prompt")
NATIVE_ROLES = ("default", "smol", "slow", "vision", "plan", "advisor", "task", "tiny")
PUBLIC_ROLES = ("main", "smol", "slow", "vision", "plan", "advisor", "task")
NATIVE_MODEL_ID = {"type": "string", "pattern":
  "^cursor/[^/\\s:\\x00-\\x1f\\x7f]+(?::(?:off|minimal|low|medium|high|xhigh|max|auto))?$(?![\\s\\S])"}
NATIVE_MODEL_ROLES = closed({key: NATIVE_MODEL_ID for key in PUBLIC_ROLES})
RUNTIME = closed({
  "cycleOrder": {"type": "array", "items": enum(*NATIVE_ROLES), "uniqueItems": True},
  "modelRoleStorage": enum("global", "project"),
  "retry": closed({"modelFallback": BOOL, "fallbackChains": {"type": "object",
    "propertyNames": {"oneOf": [enum(*NATIVE_ROLES), {"type": "string", "pattern":
      r"^[^/\s:\x00-\x1f\x7f]+/(?:\*|[^*?\[\]\s\x00-\x1f\x7f]+)$(?![\s\S])"}]},
    "additionalProperties": TEXTS}}),
  "tools": closed({"approvalMode": enum("always-ask", "write", "yolo"),
    "approval": closed({key: APPROVAL for key in ("read", "find", "grep", "glob", "bash", "permission_bash", "write", "edit", "python", "lsp", "task", "eval", "web_search", "fetch", "ast_grep")})}),
  "bash": closed({"allowCompoundCommands": BOOL, "patterns": {"type": "array", "items": closed({
    "match": TEXT, "approval": APPROVAL}, ("match", "approval"))}}),
  "bashInterceptor": closed({"enabled": BOOL, "patterns": {"type": "array", "items": closed({
    "pattern": TEXT, "tool": TEXT, "message": TEXT}, ("pattern", "tool", "message"))}}),
  "task": closed({"maxConcurrency": POSITIVE, "maxRecursionDepth": {"type": "integer", "minimum": 0}, "showResolvedModelBadge": BOOL}),
  "compaction": closed({"handoffSaveToDisk": BOOL}),
  "memories": closed({"enabled": {"type": "boolean", "const": False}}),
  "memory": closed({"backend": {"type": "string", "const": "off"}}),
  "lsp": closed({key: BOOL for key in ("enabled", "lazy", "formatOnWrite", "diagnosticsOnWrite", "diagnosticsOnEdit")}),
  "statusLine": closed({"preset": TEXT, "separator": TEXT, "contextLine": TEXT, "sessionAccent": BOOL,
    "showHookStatus": BOOL, "compactThinkingLevel": BOOL, "leftSegments": TEXTS, "rightSegments": TEXTS,
    "segmentOptions": closed({"model": closed({"showThinkingLevel": BOOL}),
      "path": closed({"abbreviate": BOOL, "stripWorkPrefix": BOOL, "maxLength": POSITIVE})})}),
  "display": closed({key: BOOL for key in ("hideToolActivity", "showTokenUsage", "showTurnTime", "cacheMissMarker")}),
  "symbolPreset": TEXT, "composer": closed({"shape": TEXT}), "tui": closed({"vimMode": BOOL}),
  "setupVersion": {"type": "integer", "minimum": 0},
})
COMPAT = closed({key: BOOL for key in ("supportsDeveloperRole", "supportsReasoningEffort")})
PROVIDER_OPTIONS = {"type": "object", "additionalProperties": closed({"name": TEXT, "compat": COMPAT})}
MODEL_OPTIONS = {"type": "object", "additionalProperties": closed({"name": TEXT, "reasoning": BOOL,
  "cost": closed({key: {"type": "number", "minimum": 0} for key in ("input", "output", "cacheRead", "cacheWrite")})})}
ROLE_THINKING = closed({key: THINKING for key in PUBLIC_ROLES})
IDENTITY_TEXT = {"type": "string", "minLength": 1, "pattern": "^[^\\x00-\\x1f\\x7f]+$(?![\\s\\S])"}
SHA256 = {"type": "string", "pattern": "^[0-9a-f]{64}$(?![\\s\\S])"}
DEFAULT_REVIEW_TIMEOUTS = {"primary_ms": 30000, "remote_ms": 30000, "total_ms": 60000}
REVIEW_TIMEOUTS = closed({key: {"type": "integer", "minimum": 1000,
  "maximum": 240000 if key == "total_ms" else 120000}
  for key in DEFAULT_REVIEW_TIMEOUTS}, tuple(DEFAULT_REVIEW_TIMEOUTS))
NATIVE_REVIEW_TIMEOUTS = closed({native: REVIEW_TIMEOUTS["properties"][public]
  for public, native in (("primary_ms", "primaryMs"), ("remote_ms", "remoteMs"), ("total_ms", "totalMs"))},
  ("primaryMs", "remoteMs", "totalMs"))
REVIEW_MAX_OUTPUT_TOKENS = {"type": "integer", "minimum": 256, "maximum": 8192}
PERMISSION_CONTROL = closed({"default_mode": enum("smart", "manual"), "reviewer_model": IDENTITY_TEXT,
  "native_bash": BOOL, "review_timeouts": REVIEW_TIMEOUTS,
  "review_max_output_tokens": REVIEW_MAX_OUTPUT_TOKENS,
  "remote_fallback_model": IDENTITY_TEXT,
  "fallback_model": {"type": "string", "const": "local/lfm2.5-230m"}}, ("default_mode",))
RUNTIME_VARIANT = enum("official")
NATIVE_PERMISSION_CONTROL = closed({
  "schemaVersion": {"type": "integer", "const": 2}, "defaultMode": enum("smart", "manual"),
  "nativeBash": BOOL, "reviewTimeouts": NATIVE_REVIEW_TIMEOUTS,
  "reviewMaxOutputTokens": REVIEW_MAX_OUTPUT_TOKENS,
  "reviewer": {"oneOf": [{"type": "string", "const": "session"},
    closed({"provider": IDENTITY_TEXT, "model": IDENTITY_TEXT}, ("provider", "model"))]},
  "remoteFallback": closed({"provider": IDENTITY_TEXT, "model": IDENTITY_TEXT}, ("provider", "model")),
  "fallback": closed({"provider": {"type": "string", "const": "local"},
    "model": {"type": "string", "const": "lfm2.5-230m"},
    "installedOnly": {"type": "boolean", "const": True}}, ("provider", "model", "installedOnly")),
  "pluginId": {"type": "string", "const": "omp-permission-control"},
  "pluginDigest": SHA256, "policyVersion": SHA256,
  "nativePatterns": {"type": "array", "items": closed({"match": IDENTITY_TEXT,
    "approval": APPROVAL}, ("match", "approval"))},
}, ("schemaVersion", "defaultMode", "reviewer", "pluginId", "pluginDigest", "policyVersion", "nativePatterns"))


def resolve_permission_control(data):
  """解析意图但不生成交付身份；不会静默修改原生执行配置或选择模型。"""
  from jsonschema import Draft202012Validator
  profile = data["profile"]
  options = profile.get("agent_options", {})
  runtime = options.get("runtime", {})
  forbidden = {"permissionControl", "disabledModelProviders", "bridgeAbi", "pluginDigest", "runtimeIdentity", "policyVersion"}
  if forbidden.intersection(options) or forbidden.intersection(runtime):
    raise ConfigError("omp-permission-native-input")
  variant = options.get("runtime_variant", "official")
  if not Draft202012Validator(RUNTIME_VARIANT).is_valid(variant):
    raise ConfigError("omp-permission-variant")
  selected = "omp-permission-control" in profile.get("plugins", [])
  configured = "permission_control" in options
  if not (selected or configured or variant != "official"):
    return None
  if not selected or not configured or variant != "official":
    raise ConfigError("omp-permission-selection-mismatch")
  config = options["permission_control"]
  if not Draft202012Validator(PERMISSION_CONTROL).is_valid(config):
    raise ConfigError("omp-permission-config")
  tools = runtime.get("tools", {})
  approval = tools.get("approval", {})
  if (approval.get("bash") != "prompt" or approval.get("permission_bash") != "allow" or
      tools.get("approvalMode") == "yolo"):
    raise ConfigError("omp-permission-native-protection")
  timeouts = config.get("review_timeouts", DEFAULT_REVIEW_TIMEOUTS)
  if any(type(value) is not int for value in timeouts.values()):
    raise ConfigError("omp-permission-config")
  minimum_total = timeouts["primary_ms"]
  if "remote_fallback_model" in config:
    minimum_total += timeouts["remote_ms"]
  if timeouts["total_ms"] < minimum_total:
    raise ConfigError("omp-permission-review-timeouts")
  result = {"defaultMode": config["default_mode"], "reviewer": "session",
    "reviewTimeouts": {"primaryMs": timeouts["primary_ms"], "remoteMs": timeouts["remote_ms"],
      "totalMs": timeouts["total_ms"]}}
  if "native_bash" in config:
    result["nativeBash"] = config["native_bash"]
  if "review_max_output_tokens" in config:
    output_tokens = config["review_max_output_tokens"]
    if type(output_tokens) is not int:
      raise ConfigError("omp-permission-config")
    result["reviewMaxOutputTokens"] = output_tokens
  requested = tuple(config[key] for key in ("reviewer_model", "remote_fallback_model")
    if key in config and not (key == "reviewer_model" and config[key] == "session"))
  identities = {}
  if requested:
    from .omp import _native_provider_id
    chosen = profile.get("models", [])
    for model_id in chosen:
      model = data.get("models", {}).get(model_id, {})
      provider_id = model.get("provider")
      provider = data.get("providers", {}).get(provider_id)
      remote_id = model.get("remote_id")
      if provider is None or not Draft202012Validator(IDENTITY_TEXT).is_valid(remote_id):
        raise ConfigError("omp-permission-reviewer-reference")
      native_provider = _native_provider_id(provider_id, provider)
      if not Draft202012Validator(IDENTITY_TEXT).is_valid(native_provider):
        raise ConfigError("omp-permission-reviewer-reference")
      identities[model_id] = (native_provider, remote_id)
    if any(chosen.count(model_id) != 1 or model_id not in identities for model_id in requested):
      raise ConfigError("omp-permission-reviewer-reference")
  if "reviewer_model" in config and config["reviewer_model"] != "session":
    reviewer = config["reviewer_model"]
    target = identities[reviewer]
    if list(identities.values()).count(target) != 1:
      raise ConfigError("omp-permission-reviewer-ambiguous")
    result["reviewer"] = {"provider": target[0], "model": target[1]}
  if "remote_fallback_model" in config:
    remote = identities[config["remote_fallback_model"]]
    if list(identities.values()).count(remote) != 1:
      raise ConfigError("omp-permission-remote-fallback-ambiguous")
    result["remoteFallback"] = {"provider": remote[0], "model": remote[1]}
  if "fallback_model" in config:
    result["fallback"] = {"provider": "local", "model": "lfm2.5-230m", "installedOnly": True}
  return result


def runtime_values(options):
  """每个顶层设置拥有独立字段，避免与管理器身份/发现字段交叠。"""
  values = deepcopy(options.get("runtime", {}))
  if "tiny_model" in options:
    values["modelRoles/tiny"] = options["tiny_model"]
  return values


def native_model_roles(data):
  """解析官方宿主动态 OAuth 模型引用；不将它们伪装为静态 catalog 模型。"""
  from jsonschema import Draft202012Validator
  profile = data["profile"]
  values = profile.get("agent_options", {}).get("native_model_roles", {})
  if not Draft202012Validator(NATIVE_MODEL_ROLES).is_valid(values):
    raise ConfigError("omp-native-model-role")
  if not values:
    return {}
  if set(values) - set(profile.get("roles", {})):
    raise ConfigError("omp-native-model-role-reference")
  provider = data.get("providers", {}).get("cursor")
  if ("cursor" not in profile.get("providers", ()) or not isinstance(provider, dict)
      or provider.get("protocol") != "oauth-dynamic" or provider.get("auth_kind") != "oauth"):
    raise ConfigError("omp-native-model-role-provider")
  return deepcopy(values)


def validate_options(data):
  from jsonschema import Draft202012Validator
  options = data["profile"].get("agent_options", {})
  resolve_permission_control(data)
  native_model_roles(data)
  materialize_presets(data)
  for key, schema in (("runtime", RUNTIME), ("provider_options", PROVIDER_OPTIONS),
      ("model_options", MODEL_OPTIONS), ("role_thinking", ROLE_THINKING)):
    if not Draft202012Validator(schema).is_valid(options.get(key, {})):
      raise ConfigError("omp-kernel-options")
  if set(options.get("provider_options", {})) - set(data.get("providers", {})):
    raise ConfigError("omp-provider-options-reference")
  if set(options.get("model_options", {})) - set(data.get("models", {})):
    raise ConfigError("omp-model-options-reference")
  if set(options.get("role_thinking", {})) - set(data["profile"].get("roles", {})):
    raise ConfigError("omp-role-thinking-reference")
  if "tiny_model" in options and options["tiny_model"] != "local/lfm2.5-230m":
    raise ConfigError("omp-tiny-model-not-supported")
  runtime = options.get("runtime", {})
  validate_fallback_chains(data, runtime.get("retry", {}).get("fallbackChains", {}))
  for item in runtime.get("bashInterceptor", {}).get("patterns", []):
    try:
      re.compile(item["pattern"])
    except re.error:
      raise ConfigError("omp-interceptor-pattern") from None


def validate_agent(content, name, data):
  """锁定的原生 agent 只接受声明式 frontmatter，不接纳预执行脚本字段。"""
  import yaml
  try:
    text = content.decode("utf-8")
    if not text.startswith("---\n"):
      raise ValueError()
    front, body = text[4:].split("\n---", 1)
    value = yaml.safe_load(front)
    allowed = {"name", "description", "tools", "model", "thinkingLevel", "spawns", "output"}
    if not isinstance(value, dict) or set(value) - allowed or value.get("name") != name or not body.strip():
      raise ValueError()
    if not isinstance(value.get("description"), str):
      raise ValueError()
    for key in ("tools", "model"):
      if key in value and (not isinstance(value[key], list) or not all(isinstance(x, str) and x for x in value[key])):
        raise ValueError()
    if "thinkingLevel" in value and value["thinkingLevel"] not in THINKING["enum"]:
      raise ValueError()
    if "spawns" in value and value["spawns"] != "*" and (not isinstance(value["spawns"], list)
        or not all(isinstance(x, str) for x in value["spawns"])):
      raise ValueError()
    roles = {"default" if role == "main" else role for role in data["profile"].get("roles", {})}
    for model in value.get("model", []):
      if not model.startswith("@") or model[1:] not in roles:
        raise ValueError()
    if "output" in value and not isinstance(value["output"], dict):
      raise ValueError()
  except Exception:
    raise ConfigError("omp-agent-resource-invalid") from None
