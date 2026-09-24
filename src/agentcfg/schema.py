"""离线严格结构校验；合并后的引用、能力及机器策略由解析阶段负责。"""

from copy import deepcopy
from dataclasses import dataclass, field
from functools import lru_cache
import json
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator
from referencing import Registry

from .adapter import AdapterDeclaration
from .secrets import CredentialError, SecretStore


class ConfigError(Exception):
  """仅包含固定代码及 schema 自有位置，不携带原始校验异常。"""

  exit_code = 2

  def __init__(self, code: str, path: tuple[str, ...] = ()):
    self.code = code
    self.path = path
    super().__init__(f"配置校验失败: {code}" + (" @ " + ".".join(path) if path else ""))


@dataclass(frozen=True)
class AuthenticationClaim:
  """adapter 规范化的显式认证路由；无认证也需声明其拥有者。"""

  provider: str = field(repr=False)
  owner: str = field(repr=False)


@dataclass(frozen=True)
class AdapterPolicy:
  """由已校验 adapter 文档投影，不规定任何原生文档字段拼写。"""

  defaults: dict = field(default_factory=dict, repr=False)
  plugins: dict[str, dict] = field(default_factory=dict, repr=False)
  credential_targets: frozenset[str] = field(default_factory=frozenset, repr=False)
  reserved_environment: frozenset[str] = field(default_factory=frozenset, repr=False)


@dataclass(frozen=True)
class AdapterSchemaBundle:
  """独立于七钩子 ABC；policy 投影已校验文档，validate 的 resolved 阶段检查选中配置。

  authentication_claims 针对每个已解析 profile 返回显式拥有者；两种投影缺失时 resolver 失败。
  """

  declaration: AdapterDeclaration = field(repr=False)
  documents: dict[str, dict] = field(repr=False)
  agent_options: dict = field(repr=False)
  validate: Callable[[str, dict], None] = field(repr=False)
  policy: Callable[[dict], AdapterPolicy] | None = field(default=None, repr=False)
  authentication_claims: Callable[[dict], tuple[AuthenticationClaim, ...]] | None = field(default=None, repr=False)
  validate_selected: Callable[[dict], None] | None = field(default=None, repr=False)


@dataclass(frozen=True)
class AdapterSchemas:
  bundles: dict[str, AdapterSchemaBundle] = field(default_factory=dict, repr=False)
  profile_agents: dict[str, str] = field(default_factory=dict, repr=False)


_FRAMEWORK_KINDS = ("registry", "profile", "local")
_ADAPTER_KINDS = ("agent", "bindings", "plugins")


# 不注册任何远程获取回调；jsonschema 的默认 registry 会隐式访问网络。
_LOCAL_REGISTRY = Registry()
_SCHEMA_MAPS = ("properties", "patternProperties", "$defs", "dependentSchemas")
_SCHEMA_VALUES = ("additionalProperties", "items", "propertyNames", "not", "if", "then", "else",
                  "contains", "unevaluatedProperties", "unevaluatedItems")
_SCHEMA_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")
_SCALAR_CONSTRAINTS = ("minLength", "maxLength", "pattern", "minimum", "maximum",
                       "exclusiveMinimum", "exclusiveMaximum", "multipleOf")
_SCHEMA_KEYWORDS = frozenset(
  _SCHEMA_MAPS + _SCHEMA_VALUES + _SCHEMA_LISTS + _SCALAR_CONSTRAINTS
  + ("$schema", "$ref", "$comment", "type", "title", "description", "default", "examples",
     "deprecated", "readOnly", "writeOnly", "enum", "const", "required", "dependentRequired",
     "minProperties", "maxProperties", "minItems", "maxItems", "uniqueItems", "minContains", "maxContains")
)


def _local_target(schema: dict, ref: str) -> dict:
  # 子集仅支持未进行百分号编码的本地 JSON Pointer，避免双重解码歧义。
  if not isinstance(ref, str) or not ref.startswith("#/$defs/") or "%" in ref:
    raise ValueError()
  target = schema
  for part in ref[2:].split("/"):
    part = part.replace("~1", "/").replace("~0", "~")
    target = target[int(part)] if isinstance(target, list) else target[part]
  return target


def _strict_schema(schema: dict) -> None:
  # 按内容缓存，调用方原地修改注入 schema 后仍会重新检查；限制缓存大小。
  _strict_schema_serialized(json.dumps(schema, sort_keys=True, allow_nan=False, separators=(",", ":")))


@lru_cache(maxsize=128)
def _strict_schema_serialized(serialized: str) -> None:
  """仅支持显式类型/本地引用、闭合对象及已列出的 2020-12 关键字。"""
  schema = json.loads(serialized)
  meta = Draft202012Validator(Draft202012Validator.META_SCHEMA, registry=_LOCAL_REGISTRY,
                              format_checker=Draft202012Validator.FORMAT_CHECKER)
  # 元 schema 自身递归验证全部子节点，不需在每个节点重新验证整棵子树。
  meta.validate(schema)
  visited = set()

  def visit(node):
    if not isinstance(node, dict) or not node or set(node) - _SCHEMA_KEYWORDS:
      raise ValueError()
    if id(node) in visited:
      return
    visited.add(id(node))
    if "$schema" in node and node["$schema"] != "https://json-schema.org/draft/2020-12/schema":
      raise ValueError()
    if "$ref" in node:
      target = _local_target(schema, node["$ref"])
      # 引用可指向 default 等注解内部；根元 schema 不会把该值当 schema 验证。
      meta.validate(target)
      visit(target)
    elif node.get("type") not in ("object", "array", "string", "integer", "number", "boolean", "null"):
      raise ValueError()
    if node.get("type") == "object":
      additional = node.get("additionalProperties")
      if additional is not False and not isinstance(additional, dict):
        raise ValueError()
    if node.get("type") == "array" and "items" not in node:
      raise ValueError()
    for key in _SCHEMA_MAPS:
      for child in node.get(key, {}).values():
        visit(child)
    for key in _SCHEMA_VALUES:
      if key in node and node[key] is not False:
        visit(node[key])
    for key in _SCHEMA_LISTS:
      for child in node.get(key, []):
        visit(child)

  visit(schema)


def _read_schema(kind: str) -> dict:
  # 源码模式不依赖调用者 cwd；为显式分发场景保留包内 schemas 读取方式。
  package = Path(__file__).resolve().parent
  root = package / "schemas"
  if not root.is_dir() and package.parent.name == "src":
    root = package.parent.parent / "schemas"
  result = None
  try:
    result = json.loads((root / f"{kind}.schema.json").read_text(encoding="utf-8"))
    _strict_schema(result)
  except Exception:
    result = None
  if result is None:
    raise ConfigError("schema-resource", (kind,))
  return result


def _bundle(context: AdapterSchemas | None, adapter_id: str | None) -> AdapterSchemaBundle:
  result = None
  try:
    result = context.bundles[adapter_id]
    if (not isinstance(result, AdapterSchemaBundle)
        or result.declaration.adapter_id != adapter_id
        or set(result.documents) != set(_ADAPTER_KINDS)
        or not callable(result.validate)
        or result.validate_selected is not None and not callable(result.validate_selected)):
      raise ValueError()
    for document in result.documents.values():
      _strict_schema(document)
    _strict_schema(result.agent_options)
    if result.agent_options.get("type") != "object":
      raise ValueError()
  except Exception:
    result = None
  if result is None:
    raise ConfigError("adapter-schema", ("adapter",))
  return result


def _version(data: dict, expected: int, kind: str) -> None:
  if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
      or data["schema_version"] != expected):
    raise ConfigError("version", (kind, "schema_version"))


def _validate(schema: dict, data: dict, path: tuple[str, ...], *, private_schema=False) -> None:
  location = None
  try:
    error = next(Draft202012Validator(schema, registry=_LOCAL_REGISTRY).iter_errors(data), None)
    if error is not None:
      segments = list(path)
      schema_path = list(error.absolute_schema_path)
      for index, segment in enumerate(schema_path):
        if segment == "properties" and index + 1 < len(schema_path):
          segments.append("<field>" if private_schema else schema_path[index + 1])
        elif segment in ("additionalProperties", "propertyNames", "patternProperties"):
          segments.append("<key>")
        elif segment == "items":
          segments.append("<item>")
      location = tuple(segments)
  except Exception:
    location = path
  # 在 except 外抛出，连 __context__ 也不保留原始私有异常。
  if location is not None:
    raise ConfigError("schema", location)


def _partial(schema: dict) -> dict:
  """只投影显式结构及标量约束，不判断是否存在合法的完整扩展。"""
  definitions = {}
  references = {}

  def project(node):
    if node is False:
      return False
    result = {key: deepcopy(node[key]) for key in ("type",) + _SCALAR_CONSTRAINTS if key in node}
    typed = node
    seen = set()
    while "type" not in typed and "$ref" in typed and id(typed) not in seen:
      seen.add(id(typed))
      typed = _local_target(schema, typed["$ref"])
    scalar = typed.get("type") in ("string", "integer", "number", "boolean", "null")
    for key in ("const", "enum"):
      if key in node:
        values = [node[key]] if key == "const" else node[key]
        if scalar or not any(isinstance(value, (dict, list)) for value in values):
          result[key] = deepcopy(node[key])
    for key in ("properties", "patternProperties"):
      if key in node:
        result[key] = {name: project(child) for name, child in node[key].items()}
    for key in ("additionalProperties", "propertyNames", "items"):
      if key in node:
        result[key] = project(node[key])
    if "prefixItems" in node:
      result["prefixItems"] = [project(child) for child in node["prefixItems"]]
    if "$ref" in node:
      target = _local_target(schema, node["$ref"])
      identity = id(target)
      if identity not in references:
        name = f"partial_{len(references)}"
        references[identity] = name
        # 先登记再递归；独立定义保留原始根上下文，包括被延后谓词/注解内的目标。
        definitions[name] = project(target)
      result["$ref"] = "#/$defs/" + references[identity]
    return result

  # required、对象/数组值约束及逻辑/条件/依赖谓词留给合并后原始 schema 全量校验。
  result = project(schema)
  if definitions:
    result["$defs"] = definitions
  return result


def separate_local(data: dict) -> tuple[dict, SecretStore]:
  """先分离 secrets 再构造普通对象；不修改调用者的原始文档。"""
  if not isinstance(data, dict):
    raise ConfigError("schema", ("local",))
  ordinary = {key: value for key, value in data.items() if key != "secrets"}
  store = None
  try:
    store = SecretStore(data.get("secrets", {}))
  except CredentialError:
    pass
  if store is None:
    raise ConfigError("schema", ("local", "secrets", "<key>"))
  return ordinary, store


def validate_document(kind: str, data: dict, *, adapter_schemas: AdapterSchemas | None = None,
                      adapter_id: str | None = None, partial_options: bool = False) -> None:
  """单一来源校验；partial_options 仅供待合并 profile 源，最终解析必须使用默认完整校验。"""
  if kind not in _FRAMEWORK_KINDS + _ADAPTER_KINDS:
    raise ConfigError("kind")
  if kind in _ADAPTER_KINDS:
    bundle = _bundle(adapter_schemas, adapter_id)
    _version(data, bundle.declaration.schema_version, kind)
    _validate(bundle.documents[kind], data, (kind,), private_schema=True)
    failed = False
    try:
      bundle.validate(kind, deepcopy(data))
    except Exception:
      failed = True
    if failed:
      raise ConfigError("adapter", (kind,))
    return

  if kind == "local":
    data, _ = separate_local(data)
  _version(data, 1, kind)
  schema = _read_schema(kind)
  checked = deepcopy(data)
  options = []
  if kind == "profile":
    bundle = _bundle(adapter_schemas, data.get("agent"))
    if "agent_options" in data:
      options.append((data["agent_options"], bundle, (kind, "agent_options"), partial_options))
      checked["agent_options"] = {}
  elif kind == "local":
    overrides = data.get("overrides", {})
    profiles = overrides.get("profiles", {}) if isinstance(overrides, dict) else {}
    if isinstance(profiles, dict):
      for profile_id, profile in profiles.items():
        if isinstance(profile, dict) and "agent_options" in profile:
          agent = adapter_schemas.profile_agents.get(profile_id) if adapter_schemas else None
          bundle = _bundle(adapter_schemas, agent)
          options.append((profile["agent_options"], bundle,
                          (kind, "overrides", "profiles", "<key>", "agent_options"), True))
          checked["overrides"]["profiles"][profile_id]["agent_options"] = {}
  _validate(schema, checked, (kind,))
  if kind == "registry":
    # OAuth 目录由插件发现，不为通过校验而伪造静态 endpoint。
    for provider in checked.get("providers", {}).values():
      if provider["auth_kind"] == "api-key" and "base_url" not in provider:
        raise ConfigError("schema", ("registry", "providers", "<key>", "base_url"))
  for value, bundle, path, partial in options:
    option_schema = _partial(bundle.agent_options) if partial else bundle.agent_options
    _validate(option_schema, value, path, private_schema=True)
