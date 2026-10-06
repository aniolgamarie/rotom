"""公共单层模型规格物化；地址、凭据、计价和协议兼容由路线绑定管理。"""

from copy import deepcopy

from .schema import ConfigError, validate_document


def materialize_models(registry):
  """校验原始目录，再返回没有模板控制字段的完整旧接口目录。"""
  validate_document("registry", {"schema_version": 1, **registry})
  result = deepcopy(registry)
  templates = result.pop("model_templates", {})
  for model_id, binding in result.get("models", {}).items():
    template_id = binding.pop("template", None)
    if template_id is not None:
      if template_id not in templates:
        raise ConfigError("reference", ("registry", "models", "<key>", "template"))
      model = deepcopy(templates[template_id])
      # notes 是明确的来源说明控制字段，不进入宿主原生模型配置。
      model.pop("notes", None)
      model.update(binding)
      result["models"][model_id] = model
    model = result["models"][model_id]
    pi = model.get("native", {}).get("pi", {})
    # TOML 不支持 null；明确的禁用声明转换为 SDK 合法的 JSON null。
    disabled = pi.pop("disabled_thinking_levels", [])
    for level in disabled:
      levels = pi.setdefault("thinkingLevelMap", {})
      if level in levels:
        raise ConfigError("model-thinking-level-conflict", ("registry", "models", "<key>", "native", "pi"))
      levels[level] = None
  validate_document("registry", {"schema_version": 1, **result})
  return result
