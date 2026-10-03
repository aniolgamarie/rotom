"""显式公共模型默认值；只校验和投影，不读取机器状态或秘密。"""

from copy import deepcopy
import json
from pathlib import Path
import tomllib

from jsonschema import Draft202012Validator
from referencing import Registry

from .schema import ConfigError


_SELECTIONS = ("providers", "models")


def _schema_path() -> Path:
  package = Path(__file__).resolve().parent
  root = package / "schemas"
  if not root.is_dir() and package.parent.name == "src":
    root = package.parent.parent / "schemas"
  return root / "model-defaults.schema.json"


def validate_model_defaults(document: dict) -> None:
  """使用闭合本地 schema 校验；错误不包含源值。"""
  try:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    error = next(Draft202012Validator(schema, registry=Registry()).iter_errors(document), None)
  except Exception:
    raise ConfigError("schema-resource", ("model-defaults",)) from None
  if error is not None:
    raise ConfigError("schema", ("model-defaults",))


def read_model_defaults(path: Path) -> dict:
  """读取状态命令所需的公开 adapter 投影；与 resolver 使用同一严格格式。"""
  try:
    document = tomllib.loads(path.read_text(encoding="utf-8"))
  except (OSError, UnicodeError, tomllib.TOMLDecodeError):
    raise ConfigError("read", ("model-defaults",)) from None
  validate_model_defaults(document)
  return deepcopy(document["adapters"])


def model_default_selection(document: dict, adapter_id: str) -> dict:
  """返回某 adapter 的独立默认投影，供 resolver 和状态展示共用。"""
  value = document.get("adapters", {}).get(adapter_id, {}) if isinstance(document, dict) else {}
  return deepcopy(value) if isinstance(value, dict) else {}


def merge_model_selections(layers) -> tuple[list[str], list[str]]:
  """按层去重追加 provider/model；不改变通用 merge 的数组语义。"""
  merged = {kind: [] for kind in _SELECTIONS}
  seen = {kind: set() for kind in _SELECTIONS}
  for value in layers:
    for kind in _SELECTIONS:
      for identity in value.get(kind, []):
        if identity not in seen[kind]:
          seen[kind].add(identity)
          merged[kind].append(identity)
  return merged["providers"], merged["models"]


def complete_pi_roles(profile: dict, agent_document: dict) -> dict:
  """Pi 启用主模型时，让已选角色资源及功能所需角色继承主模型。"""
  if profile.get("agent") != "pi" or "main" not in profile.get("roles", {}):
    return {}
  roles = profile["roles"]
  main = roles["main"]
  options = profile.get("agent_options", {})
  declarations = agent_document.get("resources", {})
  required = set()
  for resource_id in options.get("resources", {}).get("roles", []):
    declaration = declarations.get(resource_id, {})
    if declaration.get("kind") == "role" and isinstance(declaration.get("model_role"), str):
      required.add(declaration["model_role"])
  task_keeper = options.get("task_keeper", {})
  if task_keeper.get("enabled"):
    required.update(("task_keeper_reader", "task_keeper_writer", "task_keeper_reviewer"))
    if task_keeper.get("second_view_enabled"):
      required.add("second_view")
  return {role: main for role in sorted(required) if role not in roles}
