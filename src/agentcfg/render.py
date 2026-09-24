"""确定性候选原语；不读取当前原生文件、不写缓存/目标、不解析秘密。

adapter 与模板根必须是调用者明确信任的仓库代码/资源，不能来自本地任意字符串。
数据校验不能辨认伪装成普通合法字符串的秘密；adapter 须保证内容是非秘密投影。
私有 endpoint 可以影响 generation；哈希不是低熵私有值的保密措施。
"""

from copy import deepcopy
from dataclasses import dataclass, field
from functools import wraps
import hashlib
import json
import math
import os
from pathlib import Path
import stat

from jinja2 import StrictUndefined
from jinja2.sandbox import ImmutableSandboxedEnvironment
import yaml

from .adapter import Adapter, AdapterDeclaration, Artifact, ManagedTarget, Ownership, RenderContext
from .config import (ResolvedConfig, _adapter_policy, _authentication, _credential_url,
                     _machine_layers, _selected)
from .paths import trusted_source_directory, _open_directory, relative_path
from .schema import AdapterSchemas, _bundle, validate_document
from .skills import collect_skills


class RenderError(Exception):
  """固定错误，不保留模板、私有 ID/路径或底层异常。"""

  exit_code = 2

  def __init__(self):
    super().__init__("渲染失败；请检查已校验配置、可信模板及产物契约")


def _redacted(function):
  @wraps(function)
  def checked(*args, **kwargs):
    failed = False
    result = None
    try:
      result = function(*args, **kwargs)
    except Exception:
      failed = True
    # 不仅隐藏 traceback 链，还移除 __context__ 对原始私有异常的引用。
    if failed:
      raise RenderError()
    return result
  return checked


def _data(value):
  """仅复制标准 JSON 数据，拒绝对象、子类、非有限数和循环；字典按键排序。"""
  kind = type(value)
  if value is None or kind in (bool, int, str):
    return value
  if kind is float and math.isfinite(value):
    return value
  if kind is list:
    return [_data(child) for child in value]
  if kind is dict and all(type(key) is str for key in value):
    return {key: _data(value[key]) for key in sorted(value)}
  raise ValueError()


def _json(value) -> bytes:
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                     separators=(",", ":")) + "\n").encode("utf-8")


@_redacted
def concatenate_rules(rules: tuple[bytes, ...]) -> bytes:
  """按调用者的选中顺序拼接；仅在段间插入 b'\\n\\n'，不解码或修剪原文字节。"""
  if type(rules) is not tuple or any(type(rule) is not bytes for rule in rules):
    raise ValueError()
  return b"\n\n".join(rules)


@_redacted
def serialize_structured(value, *, format: str) -> bytes:
  """非秘密标准数据 -> UTF-8、排序对象键、LF 结尾；数组保序，无 repr/原生 JS 标签。

  JSON 为紧凑编码；YAML 为 safe_dump 块格式。确定性依赖仓库锁定的序列化器版本。
  字符串中的换行/引号/!!js 均作为数据编码，而非手工插入原生语法。
  """
  data = _data(value)
  if type(format) is not str or format not in ("json", "yaml"):
    raise ValueError()
  if format == "json":
    return _json(data)
  return yaml.safe_dump(data, allow_unicode=True, sort_keys=True, default_flow_style=False,
                        line_break="\n").encode("utf-8")


class _TextEnvironment(ImmutableSandboxedEnvironment):
  def is_safe_attribute(self, obj, attr, value):
    return False

  def is_safe_callable(self, obj):
    return False


def _template_bytes(trusted_root: Path, asset: str) -> bytes:
  relative = relative_path(asset)
  if not isinstance(trusted_root, Path) or not trusted_root.is_absolute() or ".." in trusted_root.parts:
    raise ValueError()
  # 根的每层及资源的每层均拒绝符号链接；仅打开普通文件，不执行资源。
  with trusted_source_directory(trusted_root) as root:
    directory = os.dup(root)
    try:
      for name in relative.parts[:-1]:
        child = _open_directory(directory, name)
        os.close(directory)
        directory = child
      fd = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                   dir_fd=directory)
      with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
          raise ValueError()
        return source.read()
    finally:
      os.close(directory)


@_redacted
def render_text(trusted_root: Path, asset: str, context: dict) -> bytes:
  """显式 TEXT 模板入口；不接受模板字符串，不自动检测花括号。

  调用者负责根是可信仓库资产而非 local/原生目录；只传非秘密标准数据。
  Jinja 文本自身 CR/CRLF 规范为 LF、保留末尾换行，插值字符串逐字保留。
  无 loader/include、globals、filters、对象属性或函数调用；支持数据索引/循环/条件。
  """
  if type(context) is not dict:
    raise ValueError()
  data = _data(context)
  environment = _TextEnvironment(undefined=StrictUndefined, autoescape=False,
                                 keep_trailing_newline=True, newline_sequence="\n")
  environment.globals.clear()
  environment.filters.clear()
  template = environment.from_string(_template_bytes(trusted_root, asset).decode("utf-8"))
  return template.render(data).encode("utf-8")


@_redacted
def render_rules(trusted_root: Path, rules: tuple[dict, ...], context: dict) -> bytes:
  """读取已选规则并拼接；adapter 按 profile.rules 顺序从选中 rules 表取出定义。

  只接受 registry 的 path/template 字段；template 缺失或 false 时完全绕过 Jinja。
  根及 context 遵循 render_text 的信任契约，不发现文件、不复制技能资源。
  """
  if type(rules) is not tuple or type(context) is not dict:
    raise ValueError()
  data = _data(context)
  parts = []
  for rule in rules:
    if (type(rule) is not dict or not {"path"} <= set(rule) <= {"path", "template"}
        or type(rule["path"]) is not str or type(rule.get("template", False)) is not bool):
      raise ValueError()
    parts.append(render_text(trusted_root, rule["path"], data) if rule.get("template", False)
                 else _template_bytes(trusted_root, rule["path"]))
  return concatenate_rules(tuple(parts))


_REGISTRY = ("providers", "models", "mcp", "rules", "skills")
_SELECTIONS = (*_REGISTRY, "plugins")


def _selected_data(resolved: ResolvedConfig, schemas: AdapterSchemas, declaration: AdapterDeclaration) -> dict:
  if type(resolved) is not ResolvedConfig:
    raise ValueError()
  data = _data(resolved.data)
  if type(data) is not dict or set(data) != {*_SELECTIONS, "profile", "machine", "adapter_documents"}:
    raise ValueError()
  profile = data["profile"]
  if profile["agent"] != declaration.adapter_id or not set(_SELECTIONS) <= set(profile):
    raise ValueError()
  bundle = _bundle(schemas, profile["agent"])
  if bundle.declaration != declaration:
    raise ValueError()
  validate_document("registry", {"schema_version": 1, **{key: data[key] for key in _REGISTRY}})
  validate_document("profile", profile, adapter_schemas=schemas)
  validate_document("local", {"schema_version": 1, "machine": data["machine"]}, adapter_schemas=schemas)
  documents = data["adapter_documents"]
  if set(documents) != {"agent", "bindings", "plugins"}:
    raise ValueError()
  for kind, document in documents.items():
    validate_document(kind, document, adapter_schemas=schemas, adapter_id=declaration.adapter_id)
  context = AdapterSchemas(schemas.bundles, {profile["id"]: profile["agent"]})
  policy = _adapter_policy(bundle, documents, context, profile["id"])
  if data["plugins"] != {key: policy.plugins[key] for key in profile["plugins"]}:
    raise ValueError()
  if _selected(data, profile) != data:
    raise ValueError()
  for kind, field_name in (("providers", "base_url"), ("mcp", "url")):
    if any(_credential_url(entity[field_name]) for entity in data[kind].values() if field_name in entity):
      raise ValueError()
  machine = data["machine"]
  if (set(machine.get("paths", {})) != {"instances_root", "state_root", "cache_root"}
      or set(machine.get("environment", {})) != {"inherit", "values"}
      or any(not path.startswith("/") for path in machine["paths"].values())):
    raise ValueError()
  # 已解析路径全部存在，不读取环境默认值；复用机器秘密通道及字面路径校验。
  _, normalized_machine = _machine_layers(machine, policy.credential_targets,
    reserved_environment=policy.reserved_environment)
  if normalized_machine != machine:
    raise ValueError()
  bundle.validate("resolved", deepcopy(data))
  if bundle.validate_selected is not None:
    bundle.validate_selected(deepcopy(data))
  _authentication(bundle, data)
  return data


def _target(target: ManagedTarget) -> ManagedTarget:
  if (type(target) is not ManagedTarget or type(target.path) is not str
      or type(target.serialization) is not str
      or target.selector is not None and type(target.selector) is not str):
    raise ValueError()
  return ManagedTarget(target.path, target.ownership, target.serialization, target.selector, target.reference_tokens)


def _target_key(target: ManagedTarget):
  return target.path, target.selector or ""


def _targets(values) -> tuple[ManagedTarget, ...]:
  if type(values) is not tuple:
    raise ValueError()
  targets = tuple(sorted((_target(value) for value in values), key=_target_key))
  for index, target in enumerate(targets):
    for other in targets[:index]:
      if target.path == other.path:
        if (target.selector is None or other.selector is None or target.selector == other.selector
            or target.serialization != other.serialization):
          raise ValueError()
      elif target.path.startswith(other.path + "/") or other.path.startswith(target.path + "/"):
        raise ValueError()
  return targets


def _artifacts(values, targets: tuple[ManagedTarget, ...]) -> tuple[Artifact, ...]:
  if type(values) is not tuple:
    raise ValueError()
  artifacts = []
  seen = set()
  modes = {}
  for value in values:
    if type(value) is not Artifact or type(value.content) is not bytes:
      raise ValueError()
    target = _target(value.target)
    key = _target_key(target)
    if target not in targets or key in seen or modes.get(target.path, value.mode) != value.mode:
      raise ValueError()
    seen.add(key)
    modes[target.path] = value.mode
    artifacts.append(Artifact(target, value.content, value.mode))
  return tuple(sorted(artifacts, key=lambda artifact: _target_key(artifact.target)))


def _target_data(target: ManagedTarget) -> dict:
  return {"path": target.path, "ownership": target.ownership.value,
          "serialization": target.serialization, "selector": target.selector,
          **({"reference_tokens": list(target.reference_tokens)} if target.reference_tokens else {})}


@dataclass(frozen=True)
class RenderCandidate:
  """私人候选：字段产物仅是期望值；不是共享文件、删除计划或部署所有权证明。

  技能资源通过同一 Artifact 契约加入；4.4 才负责缓存、脱敏计划与当前文件合成。
  generation/preimage 不作为公开诊断，也不保存 raw local、来源树或秘密值。
  """

  generation: str = field(repr=False)
  artifacts: tuple[Artifact, ...] = field(repr=False)


@_redacted
def render_candidate(resolved: ResolvedConfig, *, adapter: Adapter, adapter_schemas: AdapterSchemas,
                     lock_identity: str, skill_root: Path | None = None,
                     skill_target_root: str | None = None, context: RenderContext | None = None) -> RenderCandidate:
  """对真实 resolver 的选中结果生成纯候选，adapter 七钩子中的 config 参数仍为 dict。

  复查可变结果的严格结构、选择/引用、机器秘密通道及 adapter 策略，不重建来源 catalog，
  不声称重做未选中 profile/同层重复定义校验。调用者须先 load/resolve 全部来源，并提供
  已验证的非秘密锁身份；此处不解析锁。adapter 必须无副作用且确定性，不能读取当前文件。
  输入字典及回调字典分离，返回产物重建以避免 adapter 持有可变别名。
  技能收集须显式传入可信仓库根及目标目录；adapter 须以 FILE/skill-directory 声明该
  独占目录作用域（无 selector、无目录字节），只展开为选中包文件的声明，不授予部署所有权。
  """
  if not isinstance(adapter, Adapter) or type(lock_identity) is not str or not lock_identity or "\0" in lock_identity:
    raise ValueError()
  declaration = adapter.declaration
  if (type(declaration) is not AdapterDeclaration or type(declaration.adapter_id) is not str
      or type(declaration.adapter_version) is not str):
    raise ValueError()
  declaration = AdapterDeclaration(declaration.adapter_id, declaration.schema_version, declaration.adapter_version)
  data = _selected_data(resolved, adapter_schemas, declaration)
  adapter.validate(deepcopy(data))
  targets = _targets(adapter.managed_targets(deepcopy(data)))
  if context is not None and (type(context) is not RenderContext or context.lock_identity != lock_identity):
    raise ValueError()
  artifacts = _artifacts(adapter.render_with_context(deepcopy(data), context) if context is not None
    else adapter.render(deepcopy(data)), targets)
  scopes = tuple(target for target in targets if target.serialization == "skill-directory")
  if skill_root is not None or skill_target_root is not None:
    if skill_root is None or skill_target_root is None:
      raise ValueError()
    scope = ManagedTarget(skill_target_root, Ownership.FILE, "skill-directory")
    if scopes != (scope,) or any(artifact.target == scope for artifact in artifacts):
      raise ValueError()
    packages = collect_skills(skill_root, data["skills"], target_root=skill_target_root)
    targets = _targets(tuple(target for target in targets if target != scope)
                       + tuple(artifact.target for artifact in packages))
    artifacts = _artifacts(artifacts + packages, targets)
  elif scopes:
    raise ValueError()
  preimage = {"render_version": 1, "config": data, "lock_identity": lock_identity,
              "adapter": {"id": declaration.adapter_id, "schema_version": declaration.schema_version,
                          "adapter_version": declaration.adapter_version},
              "targets": [_target_data(target) for target in targets],
              "artifacts": [{"target": _target_data(artifact.target), "mode": artifact.mode,
                             "sha256": hashlib.sha256(artifact.content).hexdigest()} for artifact in artifacts]}
  return RenderCandidate(hashlib.sha256(_json(preimage)).hexdigest(), artifacts)
