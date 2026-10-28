"""受限只读补全；只返回ID，不打开认证、原生会话或项目路径。"""
import math
import os
from pathlib import Path
import stat
import sys

from agentcfg.paths import PathError, _absolute_directory, _check_private, trusted_source_directory, xdg_config_home


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ("dsh", "pi", "omp")
PUBLIC = frozenset(("profile", "tool", "preset", "component", "preference-key"))
WORK = frozenset(("work-type", "work-template", "work-source", "work-named"))


class QueryError(Exception):
  def __init__(self, exit_code=2):
    self.exit_code = exit_code
    super().__init__("completion query unavailable")


def _id(value):
  if (not isinstance(value, str) or not value or value in (".", "..") or len(value) > 255
      or not (value[0].isalnum() or value[0] == "_")
      or any(not (char.isalnum() or char in "_.-") for char in value)):
    raise QueryError(2)
  value.encode("utf-8")
  return value


def _finite(value):
  if isinstance(value, float) and not math.isfinite(value):
    raise QueryError(2)
  if isinstance(value, dict):
    for child in value.values():
      _finite(child)
  elif isinstance(value, list):
    for child in value:
      _finite(child)


def _public_files(directory, suffix):
  """只盘点明确公开目录；链接和可外部改写的输入拒绝。"""
  with trusted_source_directory(directory) as parent:
    names = sorted(name for name in os.listdir(parent) if name.endswith(suffix))
    for name in names:
      info = os.stat(name, dir_fd=parent, follow_symlinks=False)
      if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid())
          or info.st_nlink != 1 or info.st_mode & 0o022):
        raise QueryError(4)
    return [directory / name for name in names]


def _catalog():
  # 公共解析器只消费这些仓库来源；先拒绝可跟随到私人位置的链接。
  _public_files(ROOT / "profiles", ".toml")
  _public_files(ROOT / "shared", ".toml")
  _public_files(ROOT / "shared" / "defaults", ".toml")
  _public_files(ROOT / "schemas", ".json")
  _public_files(ROOT / "agents" / "pi" / "schemas", ".json")
  for tool in TOOLS:
    _public_files(ROOT / "agents" / tool, ".toml")
  from agentcfg.workspace import load_public_catalog
  catalog, _ = load_public_catalog(repository=ROOT)
  return catalog


def _profile_ids(tool):
  """完整校验公开配方源；ID 查询不加载无关 provider/model 或未引用的工具。"""
  from agentcfg.config import _read_toml
  from agentcfg.schema import AdapterSchemas, validate_profile_sources
  from agentcfg.workspace import ADAPTER_TYPES
  paths = _public_files(ROOT / "profiles", ".toml")
  _public_files(ROOT / "schemas", ".json")
  documents = [(path, _read_toml(path)) for path in paths]
  required = set()
  for _, document in documents:
    agent = document.get("agent")
    if type(agent) is not str or agent not in TOOLS:
      raise QueryError(2)
    required.add(agent)
  bundles = {}
  for agent in sorted(required):
    if agent == "pi":
      _public_files(ROOT / "agents" / "pi" / "schemas", ".json")
    bundles[agent] = ADAPTER_TYPES[agent](ROOT).schemas().bundles[agent]
  context = AdapterSchemas(bundles)
  for _, document in documents:
    _finite(document)
  validate_profile_sources((document for _, document in documents), adapter_schemas=context)
  result, seen = [], set()
  for path, document in documents:
    identifier = _id(document["id"])
    if identifier != path.stem or identifier in seen:
      raise QueryError(2)
    seen.add(identifier)
    if tool is None or document["agent"] == tool:
      result.append(identifier)
  return result


def _selected_path(args, namespace):
  if args.local is not None:
    path = Path(args.local)
    if not path.is_absolute():
      path = Path.cwd() / path
    if ".." in path.parts:
      raise QueryError(2)
    return path
  if args.machine is None:
    raise QueryError(2)
  return xdg_config_home() / ("termcfg" if namespace == "term" else "agentcfg") / "machines" / (_id(args.machine) + ".toml")


def _local(path, catalog=None):
  from agentcfg.config import load_local
  from agentcfg.schema import ConfigError
  try:
    local, _ = load_local(path, load_credentials=False)
  except ConfigError as error:
    if error.code == "read":
      # load_local 将不存在包装为配置错误；仅安全读取器确认的缺失是空候选。
      from agentcfg.paths import read_private_file
      read_private_file(path)
      raise
    if error.code != "adapter-schema":
      raise
    catalog = catalog or _catalog()
    local, _ = load_local(path, load_credentials=False, adapter_schemas=catalog.adapter_schemas)
  _finite(local.data)
  return local.data


def _machine_ids(namespace):
  parent_path = xdg_config_home() / ("termcfg" if namespace == "term" else "agentcfg") / "machines"
  try:
    with _absolute_directory(parent_path) as parent:
      _check_private(parent)
      result = []
      for name in sorted(os.listdir(parent)):
        if not name.endswith(".toml"):
          continue
        identifier = _id(name[:-5])
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600):
          raise QueryError(4)
        if namespace == "term":
          from termcfg.config import MACHINE_ID
          if not MACHINE_ID.fullmatch(identifier):
            raise QueryError(2)
        result.append(identifier)
      return result
  except FileNotFoundError:
    return []


def _providers(args, path):
  from agentcfg.model_defaults import model_default_selection, merge_model_selections
  catalog = _catalog()
  if args.profile not in catalog.profiles:
    raise QueryError(2)
  profile = catalog.profiles[args.profile]
  tool = profile["agent"]
  if args.tool is not None and args.tool != tool:
    raise QueryError(2)
  document = _local(path, catalog)
  overrides = document.get("overrides", {})
  if set(overrides.get("profiles", {})) - set(catalog.profiles):
    raise QueryError(2)
  # 复用模型选择的合并契约，仅投影providers列表和auth_kind；不物化URL或SecretRef。
  layers = (model_default_selection(catalog.model_defaults, tool),
    catalog.adapter_documents[tool]["agent"]["defaults"], profile,
    overrides.get("profiles", {}).get(args.profile, {}))
  selected, _ = merge_model_selections(layers)
  registry = dict(catalog.registry["providers"])
  from agentcfg.merge import merge_layers
  registry = merge_layers((("registry", registry), ("local", overrides.get("providers", {})))).data
  if any(identifier not in registry for identifier in selected):
    raise QueryError(2)
  operation = args.command
  keys = [identifier for identifier in selected if operation is None or registry[identifier].get("auth_kind") == "api-key"]
  if operation == "agent model key":
    keys = ["kimi-code", "glm-code", "deepseek", *keys]
  return keys


def _work_ids(args, path):
  document = _local(path)
  work = document["machine"].get("work")
  if not work:
    return []
  templates = work.get("templates", {})
  if work.get("model") == "structured-v1" and (work.get("include_rotom", True) or "rotom_template" in work):
    if work.get("rotom_template", "development") not in templates:
      raise QueryError(2)
  for template in templates.values():
    order, types = template["order"], template["tab_types"]
    if len(order) != len(set(order)) or set(order) != set(types) or template["initial"] not in types:
      raise QueryError(2)
  sources = work.get("sources", [])
  if len({source["id"] for source in sources}) != len(sources):
    raise QueryError(2)
  named = {}
  for item in work.get("workspaces", []):
    if item["template"] not in templates:
      raise QueryError(2)
    if item["kind"] == "named":
      if item["id"] in named and named[item["id"]] != item:
        raise QueryError(2)
      named[item["id"]] = item
  if any(source["template"] not in templates for source in sources):
    raise QueryError(2)
  allowed = {key for key, template in templates.items() if args.tool is None or
    any(value["launcher"] == args.tool for value in template["tab_types"].values())}
  if args.kind == "work-template":
    return sorted(allowed)
  if args.kind == "work-type":
    return [key for template in templates.values() for key, value in template["tab_types"].items()
      if args.tool is None or value["launcher"] == args.tool]
  if args.kind == "work-source":
    return [source["id"] for source in sources if source["template"] in allowed]
  return [key for key, value in named.items() if value["template"] in allowed]


def _sessions(args, path):
  """只投影已有受管索引；历史引用不授予加载、writer或恢复资格。"""
  from agentcfg.schema import ConfigError
  from agentcfg.sessions import SessionError, SessionIndex
  from .context import Scope
  from .resume import load_known
  scope = Scope(machine=args.machine, local=str(path) if args.local is not None else None,
    profile=args.profile, agent=args.tool)
  try:
    key, known = load_known(scope, nonblocking=True)
  except ConfigError as error:
    if error.code == "read":
      # 只将安全读取器确认的缺文件视为空；权限/链接或坏配置不能伪装成缺索引。
      from agentcfg.paths import read_private_file
      read_private_file(path)
    raise
  except SessionError as error:
    raise QueryError(error.code if type(error.code) is int and error.code in (2, 4, 5, 6) else 6) from None
  groups = {}
  for target in SessionIndex(known).candidates(scope=key, agent=args.tool, profile=args.profile):
    groups.setdefault(target.ref.native_ref, []).append(target)
  # 同裸ID的多profile/HOME/backend/cwd不能由一个补全值掩盖；不按时间选“最近”。
  return [identifier for identifier, rows in groups.items() if len(rows) == 1
    and rows[0].ref.backend == "managed" and rows[0].confirmation != "unknown"
    and rows[0].cwd is not None and rows[0].cwd_status != "unknown"]


def _validate_query(args):
  namespace = args.completion_namespace
  if args.machine is not None:
    _id(args.machine)
  if args.profile is not None:
    _id(args.profile)
  if args.command is not None:
    from .cli import COMMANDS
    path = tuple(args.command.split(" "))
    if path not in COMMANDS:
      raise QueryError(2)
    inferred = path[0] if path[0] in ("agent", "term", "work") else "agent" if path[0] in ("run", "resume") else None
    if inferred is None:
      raise QueryError(2)
    if namespace is not None and inferred is not None and namespace != inferred:
      raise QueryError(2)
    namespace = namespace or inferred
  if args.kind in WORK:
    if namespace not in (None, "work") or args.profile is not None:
      raise QueryError(2)
    namespace = "work"
  elif args.kind in ("provider", "session", "profile", "tool", "preset"):
    if namespace not in (None, "agent"):
      raise QueryError(2)
    namespace = "agent"
  elif args.kind == "component":
    if namespace not in (None, "term") or args.tool is not None:
      raise QueryError(2)
    namespace = "term"
  if args.kind == "machine" and (namespace is None or args.machine is not None or args.local is not None or args.profile is not None or args.tool is not None):
    raise QueryError(2)
  if args.kind in PUBLIC and (args.machine is not None or args.local is not None or args.profile is not None):
    raise QueryError(2)
  if args.kind == "preference-key" and (namespace is not None or args.tool is not None or args.command is not None):
    raise QueryError(2)
  if args.kind == "provider" and (args.profile is None or args.machine is None and args.local is None):
    raise QueryError(2)
  if args.kind == "provider" and args.command not in (None, "agent model key", "agent model url"):
    raise QueryError(2)
  if args.kind in WORK | {"session"} and args.machine is None and args.local is None:
    raise QueryError(2)
  if args.kind == "session" and args.tool is None:
    raise QueryError(2)
  if args.kind == "session" and args.command not in (None, "resume"):
    raise QueryError(2)
  if args.kind == "preset" and args.command not in (None, "agent model enable", "agent model presets"):
    raise QueryError(2)
  return namespace


def collect(args):
  namespace = _validate_query(args)
  if args.kind == "tool":
    return [args.tool] if args.tool is not None else list(TOOLS)
  if args.kind == "profile":
    return _profile_ids(args.tool)
  if args.kind == "preset":
    return ["kimi-code", "glm-code", "deepseek"]
  if args.kind == "component":
    from termcfg.config import COMPONENTS
    choices = set(COMPONENTS)
    if args.command in ("term lock", "term sync"):
      choices &= {"zsh", "tmux"}
    return sorted(choices)
  if args.kind == "preference-key":
    from .preferences import KEYS
    return list(KEYS)
  if args.kind == "machine":
    return _machine_ids(namespace)
  path = _selected_path(args, namespace)
  try:
    if args.kind == "session":
      return _sessions(args, path)
    return _providers(args, path) if args.kind == "provider" else _work_ids(args, path)
  except FileNotFoundError:
    return []


def main(args):
  try:
    result = sorted({_id(value) for value in collect(args)})
    if result:
      sys.stdout.write("".join(value + "\0" for value in result))
    return 0
  except Exception as error:
    from agentcfg.schema import ConfigError
    from agentcfg.storage import Conflict
    if isinstance(error, QueryError):
      code = error.exit_code
    elif isinstance(error, (PathError, Conflict)):
      code = 4
    elif isinstance(error, ConfigError):
      code = 2
    else:
      code = 6
    print("rotom: 补全查询不可用", file=sys.stderr)
    return code
