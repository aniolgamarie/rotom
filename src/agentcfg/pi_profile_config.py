"""现代 Pi 配置投影；配置可解析不代表候选包已经安装或通过验收。"""

from pathlib import PurePosixPath
import re

from .schema import AdapterPolicy, ConfigError


MODERN_PROFILES = frozenset({"pi-base", "pi-full"})
RESERVED_ENVIRONMENT = frozenset({"PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR",
  "CODEX_HOME", "BUN_OPTIONS", "BUN_RUNTIME_TRANSPILER_CACHE_PATH"})
BASE_OPTIONS = frozenset({"runtime", "resources", "ui", "discovery", "external_tools",
  "paths", "checks", "permissions", "network", "terminal", "model_settings",
  "compaction", "loop_guard", "todo", "diagnostics", "mcp"})


def profile_policy(documents, profile_id):
  if profile_id not in MODERN_PROFILES:
    defaults, plugins = documents["agent"]["defaults"], documents["plugins"]["plugins"]
  else:
    defaults = documents["agent"].get("profile_defaults", {}).get(profile_id)
    plugins = documents["plugins"].get("profile_plugins", {}).get(profile_id)
    if not isinstance(defaults, dict) or not isinstance(plugins, dict):
      raise ConfigError("pi-profile-projection-missing")
  return AdapterPolicy(defaults=defaults, plugins=plugins, reserved_environment=RESERVED_ENVIRONMENT)


def validate_projection(data):
  profile = data["profile"]
  if profile["id"] not in MODERN_PROFILES:
    return
  policy = profile_policy(data["adapter_documents"], profile["id"])
  if any(name not in policy.plugins or row != policy.plugins[name] for name, row in data["plugins"].items()):
    raise ConfigError("pi-profile-plugin-projection")
  capabilities, tools = set(), set()
  if set(data["plugins"]) != set(profile["plugins"]):
    raise ConfigError("pi-profile-plugin-projection")
  for row in data["plugins"].values():
    capability, names = row.get("capability_id"), row.get("model_tools")
    if (set(row) != {"package", "version", "enabled", "requires", "conflicts", "engines", "capability_id", "model_tools"}
        or not isinstance(capability, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", capability)
        or capability in capabilities or type(names) is not list or len(names) > 64
        or any(not isinstance(name, str) or not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]{0,63}", name) for name in names)
        or len(set(names)) != len(names) or tools.intersection(names)):
      raise ConfigError("pi-profile-plugin-capability")
    capabilities.add(capability)
    tools.update(names)
  options = profile["agent_options"]
  if options.get("runtime", {}).get("engine", "node") != "node":
    raise ConfigError("pi-profile-engine")
  # 旧资源依赖私有桥接。新公开扩展需先进入能力绑定和加载清单，不能自动包装旧资源。
  if options.get("resources", {}).get("extensions"):
    raise ConfigError("pi-profile-extension-unavailable")
  if profile["id"] != "pi-base":
    return
  defaults = policy.defaults
  if (set(options) - BASE_OPTIONS or set(profile["roles"]) - {"main"}
      or set(profile["skills"]) - set(defaults.get("skills", []))):
    raise ConfigError("pi-base-capability-selection")
  resources = options.get("resources", {})
  allowed = {kind: set(names) for kind, names in defaults.get("agent_options", {}).get("resources", {}).items()}
  declaration = data["adapter_documents"]["agent"]
  available = declaration.get("profile_available_resources", {}).get("pi-base", {})
  # 显式可选集合与默认加载分离；此版本只开放仓库普通提示词，不授予其他能力。
  if set(available) - {"prompts"}:
    raise ConfigError("pi-base-resource-selection")
  for name in available.get("prompts", []):
    resource = declaration["resources"].get(name)
    if not isinstance(resource, dict):
      raise ConfigError("pi-base-resource-selection")
    path = resource.get("path")
    if (resource.get("kind") != "prompt" or resource.get("scope") != "global"
        or not isinstance(path, str) or "\\" in path
        or str(PurePosixPath(path)) != path or ".." in PurePosixPath(path).parts
        or PurePosixPath(path).parent != PurePosixPath("agents/pi/prompts/ordinary")
        or PurePosixPath(path).suffix != ".md"):
      raise ConfigError("pi-base-resource-selection")
  allowed.setdefault("prompts", set()).update(available.get("prompts", []))
  if any(set(names) - set(allowed.get(kind, [])) for kind, names in resources.items()):
    raise ConfigError("pi-base-resource-selection")
  discovery = options.get("discovery", {})
  if discovery.get("project_resources") or discovery.get("external_skills"):
    raise ConfigError("pi-base-resource-selection")
