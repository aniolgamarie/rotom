"""仅为原生项目角色切换开放非秘密配置，不开放一般项目设置。"""

from dataclasses import dataclass
import yaml

from .omp_model_presets import materialize_presets
from .omp_settings import NATIVE_ROLES
from .storage import Conflict, Tree


ROLE_BACKUP_NAME = "config.yml.agentcfg-backup"


@dataclass(frozen=True)
class ProjectRolePolicy:
  roles: dict[str, frozenset[str]]


def project_role_policy(data):
  options = data["profile"].get("agent_options", {})
  if not options.get("model_presets") or options.get("runtime", {}).get("modelRoleStorage") != "project":
    return None
  # 可选池不等于项目角色授权：仅接受声明套件和明确初始角色的同一角色赋值。
  allowed = {role: set() for role in NATIVE_ROLES}
  for preset in materialize_presets(data).values():
    for role, selector in preset["modelRoles"].items():
      allowed[role].add(selector)
  for role, model_id in data["profile"].get("roles", {}).items():
    native_role = "default" if role == "main" else role
    selector = options.get("native_model_roles", {}).get(role)
    if selector is None:
      model = data["models"][model_id]
      selector = model["provider"] + "/" + model["remote_id"]
      level = options.get("role_thinking", {}).get(role)
      if level:
        selector += ":" + level
    allowed[native_role].add(selector)
  if options.get("tiny_model") == "local/lfm2.5-230m":
    allowed["tiny"].add("local/lfm2.5-230m")
  return ProjectRolePolicy({role: frozenset(values) for role, values in allowed.items()})


class _RoleLoader(yaml.SafeLoader):
  pass


def _mapping(loader, node):
  result = {}
  for key_node, value_node in node.value:
    key = loader.construct_object(key_node)
    if not isinstance(key, str) or key in result:
      raise ValueError()
    result[key] = loader.construct_object(value_node)
  return result


_RoleLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def validate_project_role_file(path, policy):
  """固定普通文件读取，拒绝重复键、别名和模型之外的设置；报告不含配置值。"""
  try:
    with Tree(path.parent, private=False) as tree:
      raw = tree.read(path.name, max_bytes=64 * 1024)
    if raw is None:
      raise ValueError()
    content = raw[0]
    for event in yaml.parse(content):
      if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) is not None:
        raise ValueError()
    document = yaml.load(content, Loader=_RoleLoader)
    if document is None:
      document = {}
    if not isinstance(document, dict) or set(document) - {"modelRoles"}:
      raise ValueError()
    roles = document.get("modelRoles", {})
    if not isinstance(roles, dict) or set(roles) - set(NATIVE_ROLES):
      raise ValueError()
    for role, selector in roles.items():
      if selector is None:
        continue
      if not isinstance(selector, str) or any(char in selector for char in "$%*?[]"):
        raise ValueError()
      if selector not in policy.roles[role]:
        raise ValueError()
    return content
  except Exception:
    raise Conflict("OMP项目角色配置不符合仅模型引用契约") from None


def quarantine_project_role_file(path):
  """契约冲突时保留最后一份0600备份并移除原文件；链接、硬链接与超限文件仍拒绝。"""
  with Tree(path.parent, private=False) as tree:
    current = tree.read(path.name, max_bytes=64 * 1024)
    if current is None:
      raise Conflict("OMP项目角色配置在隔离前发生变化")
    content, _, expected = current
    backup = tree.read(ROLE_BACKUP_NAME)
    tree.replace(ROLE_BACKUP_NAME, content, expected=backup[2] if backup else None)
    tree.replace(path.name, None, expected=expected)
  return path.with_name(ROLE_BACKUP_NAME), content
