"""OMP kernel 配置的显式非秘密字段契约；不接受任意原生配置透传。"""

from copy import deepcopy
import re

from .schema import ConfigError


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
RUNTIME = closed({
  "cycleOrder": {"type": "array", "items": enum(*NATIVE_ROLES), "uniqueItems": True},
  "retry": closed({"modelFallback": BOOL, "fallbackChains": closed({key: TEXTS for key in NATIVE_ROLES})}),
  "tools": closed({"approvalMode": enum("always-ask", "write", "yolo"),
    "approval": closed({key: APPROVAL for key in ("read", "find", "grep", "glob", "bash", "write", "edit", "python", "lsp", "task", "web_search", "fetch", "ast_grep")})}),
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
ROLE_THINKING = closed({key: THINKING for key in ("main", "smol", "slow", "vision", "plan", "advisor", "task")})


def runtime_values(options):
  """每个顶层设置拥有独立字段，避免与管理器身份/发现字段交叠。"""
  values = deepcopy(options.get("runtime", {}))
  if "tiny_model" in options:
    values["modelRoles/tiny"] = options["tiny_model"]
  return values


def validate_options(data):
  from jsonschema import Draft202012Validator
  options = data["profile"].get("agent_options", {})
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
  allowed = {provider + "/" + model["remote_id"] for model in data.get("models", {}).values()
             for provider in (model["provider"],)}
  runtime = options.get("runtime", {})
  for values in runtime.get("retry", {}).get("fallbackChains", {}).values():
    for value in values:
      if value in allowed:
        continue
      model, colon, level = value.rpartition(":")
      if not colon:
        model = value
      if model not in allowed or colon and level not in THINKING["enum"]:
        raise ConfigError("omp-fallback-model-reference")
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
