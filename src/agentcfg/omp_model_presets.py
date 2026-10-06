"""OMP 公开 modelPresets 投影与选中模型引用校验；不发现账号目录。"""

import re

from .schema import ConfigError


ROLES = ("main", "smol", "slow", "plan", "task", "advisor", "vision", "tiny")
LEVELS = ("minimal", "low", "medium", "high", "xhigh", "max")
SELECTOR = r"^[^/\s:\x00-\x1f\x7f]+(?::(?:minimal|low|medium|high|xhigh|max))?$|^cursor/[^/\s:\x00-\x1f\x7f]+:(?:minimal|low|medium|high|xhigh|max)$"
MODEL_PRESETS = {
  "type": "object", "propertyNames": {"type": "string", "pattern": r"^[a-z][a-z0-9-]*$(?![\s\S])"},
  "additionalProperties": {"type": "object", "additionalProperties": False, "required": ["roles"],
    "properties": {"roles": {"type": "object", "additionalProperties": False, "required": list(ROLES),
      "properties": {role: ({"type": "string", "const": "local/lfm2.5-230m"} if role == "tiny" else
        {"type": "string", "pattern": SELECTOR}) for role in ROLES}}}},
}
CURSOR_LEVELS = {
  "kimi-k3": {"low", "high", "max"}, "glm-5.2": {"high", "max"},
  "composer-2.5": {"minimal", "low", "medium", "high"},
  "grok-4.7": {"low", "medium", "high", "xhigh"},
  "kimi-k2.7-code": {"minimal", "low", "medium", "high"},
}
_CURSOR = re.compile(r"^cursor/([^/\s:\x00-\x1f\x7f]+)(?::(minimal|low|medium|high|xhigh|max))?$")


def _selected_provider(data, provider):
  return provider in data["profile"].get("providers", ()) and provider in data.get("providers", {})


def _cursor(data, remote, level):
  provider = data.get("providers", {}).get("cursor", {})
  if (not _selected_provider(data, "cursor") or provider.get("protocol") != "oauth-dynamic"
      or provider.get("auth_kind") != "oauth"):
    raise ConfigError("omp-preset-cursor-provider")
  # 已核对目录的型号使用其公开档位；其他动态 ID 仅做语法校验，不声称账号可用。
  if level is not None and level not in CURSOR_LEVELS.get(remote, set(LEVELS)):
    raise ConfigError("omp-model-thinking-level")


def _static(data, model_id, level, role=None):
  model = data.get("models", {}).get(model_id)
  if (not isinstance(model, dict) or model_id not in data["profile"].get("models", ())
      or not _selected_provider(data, model["provider"])):
    raise ConfigError("omp-preset-model-reference")
  if role == "vision" and "image" not in model.get("input", ()):
    raise ConfigError("omp-preset-vision-input")
  if level is not None:
    allowed = model.get("reasoning_efforts")
    thinking = model.get("native", {}).get("omp", {}).get("thinking", {})
    if not allowed and thinking.get("minLevel") == thinking.get("maxLevel") and thinking.get("minLevel"):
      allowed = [thinking["minLevel"]]
    reasoning = data["profile"].get("agent_options", {}).get("model_options", {}).get(
      model_id, {}).get("reasoning", model.get("reasoning"))
    if not reasoning or level not in (allowed or LEVELS):
      raise ConfigError("omp-model-thinking-level")
  return model["provider"] + "/" + model["remote_id"] + (":" + level if level else "")


def resolve_selector(data, value, *, public=False, require_level=False, role=None):
  """先精确匹配完整已选引用，再解析档位；动态 Cursor 只声明语法与所选 OAuth。"""
  if not isinstance(value, str) or any(char in value for char in "*?[]"):
    raise ConfigError("omp-preset-selector")
  selected = data["profile"].get("models", ())
  references = [(model_id if public else model["provider"] + "/" + model["remote_id"], model_id)
    for model_id in selected for model in (data.get("models", {}).get(model_id),) if isinstance(model, dict)]
  base, colon, suffix = value.rpartition(":")
  candidates = [(value, None)]
  if colon and suffix in LEVELS:
    candidates.append((base, suffix))
  for reference, level in candidates:
    matches = [model_id for native, model_id in references if native == reference]
    if len(matches) > 1:
      raise ConfigError("omp-preset-model-reference")
    if matches:
      if require_level and level is None:
        raise ConfigError("omp-preset-thinking-required")
      return _static(data, matches[0], level, role)
  match = _CURSOR.fullmatch(value)
  if match:
    remote, level = match.groups()
    if require_level and level is None:
      raise ConfigError("omp-preset-thinking-required")
    _cursor(data, remote, level)
    return value
  raise ConfigError("omp-preset-model-reference" if public else "omp-fallback-model-reference")


def materialize_presets(data):
  from jsonschema import Draft202012Validator
  presets = data["profile"].get("agent_options", {}).get("model_presets", {})
  if not Draft202012Validator(MODEL_PRESETS).is_valid(presets):
    raise ConfigError("omp-model-preset-schema")
  result = {}
  for name, preset in presets.items():
    roles = {}
    for role, value in preset["roles"].items():
      roles["default" if role == "main" else role] = value if role == "tiny" else resolve_selector(
        data, value, public=True, require_level=True, role=role)
    result[name] = {"modelRoles": roles}
  return result


def validate_fallback_chains(data, chains):
  roles = {"default", "smol", "slow", "plan", "task", "advisor", "vision", "tiny"}
  for key, values in chains.items():
    if key not in roles:
      if key.endswith("/*"):
        if not _selected_provider(data, key[:-2]):
          raise ConfigError("omp-fallback-provider-reference")
      else:
        resolve_selector(data, key)
    for value in values:
      resolve_selector(data, value)
