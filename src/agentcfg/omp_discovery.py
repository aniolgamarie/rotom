"""固定 OMP 本地来源清单与默认拒绝检查。"""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit
from .storage import Conflict
import yaml

IGNORED_PROVIDER_SOURCES = (".agent", ".agents", ".claude", ".codex", ".gemini",
  "AGENTS.md", "CLAUDE.md", "GEMINI.md")
DISCOVERY_NAMES = (".omp", "TITLE_SYSTEM.md", ".env", ".env.local", ".env.development", ".env.production", ".env.test")
DISABLED_PROVIDERS = ("agent-plugins", "agents-md", "claude-md", "claude", "claude-plugins", "cline", "agents", "codex", "cursor",
  "gemini", "opencode", "github", "mcp-json", "omp-plugins", "skillshare", "ssh-json", "vscode", "windsurf")
DOTENV_NAMES = (".env", ".env.local", ".env.development", ".env.production", ".env.test")
NATIVE_PROFILE_SOURCES = ("settings.json", "config.yml", "models.yml", "RULES.md", "AGENTS.md", "TITLE_SYSTEM.md",
  "SYSTEM.md", "SYSTEM_TEMPLATE.md", "APPEND_SYSTEM.md", "PERSONALITY.md", "rules", "skills", "prompts", "extensions", "hooks", "tools",
  "mcp.json", ".mcp.json", "agents", "themes")
NATIVE_ROOT_PATTERNS = (tuple("$HOME/" + name for name in DOTENV_NAMES) + ("$HOME/.omp/.env",)
  + tuple("$ACTIVE_AGENT/" + name for name in DOTENV_NAMES)
  + tuple("$ACTIVE_AGENT/" + name for name in NATIVE_PROFILE_SOURCES)
  + tuple("$DEFAULT_AGENT/" + name for name in NATIVE_PROFILE_SOURCES)
  + ("$HOME/.omp/plugins/installed_plugins.json", "$HOME/.omp/marketplaces.json"))
NATIVE_SETTING_CONTROLS = {
  "configExact": ("/skills/enablePiUser", "/skills/enablePiProject", "/mcp/enableProjectConfig", "/enabledProviders",
    "/disabledProviders", "/startup/checkUpdate", "/marketplace/autoUpdate", "/autolearn/enabled", "/extensions"),
  "configForbidden": ("/auth/broker", "/auth/gateway", "/skills/customDirectories", "/memory", "/tiny", "/speech",
    "/browser", "/eval", "/providers/tinyModel", "/providers/tinyModelDevice", "/providers/tinyModelDtype"),
  "modelsExact": ("/providers",), "mcpExact": ("/mcpServers",),
}


def discovery_manifest():
  return {"version": 1, "ancestors": list(DISCOVERY_NAMES), "nativeRoots": list(NATIVE_ROOT_PATTERNS),
    "ignoredProviderSources": {"paths": list(IGNORED_PROVIDER_SOURCES),
      "reason": "all-loading-providers-disabled-before-discovery"},
    "disabledProviders": list(DISABLED_PROVIDERS),
    "nativeControls": {key: list(value) for key, value in NATIVE_SETTING_CONTROLS.items()},
    "authBroker": "disabled", "gateway": "disabled"}


def manifest_digest():
  return hashlib.sha256(json.dumps(discovery_manifest(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class SourcePolicy:
  manifest_sha256: str
  project_resources: bool
  project_roots: tuple[Path, ...]

  @classmethod
  def from_options(cls, options):
    raw = tuple(Path(item) for item in options.get("project_roots", ()))
    if any(not root.is_absolute() or root.is_symlink() for root in raw):
      from .schema import ConfigError
      raise ConfigError("omp-project-root-not-absolute")
    roots = tuple(root.resolve() for root in raw)
    enabled = options.get("project_resources", False)
    if (enabled and not roots) or (not enabled and roots) or len(set(roots)) != len(roots):
      from .schema import ConfigError
      raise ConfigError("omp-project-source-policy")
    return cls(manifest_digest(), enabled, roots)


def assert_clean_sources(cwd, allowed=()):
  allowed = {Path(item).resolve() for item in allowed}
  current = Path(cwd).resolve()
  while True:
    for name in DISCOVERY_NAMES:
      candidate = current / name
      if (candidate.exists() or candidate.is_symlink()) and candidate.resolve() not in allowed:
        raise Conflict(f"OMP检测到未声明的项目配置来源: {candidate}")
    if current == current.parent:
      break
    current = current.parent


_SECRET_TEXT = re.compile(
  rb"(?im)(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|^\s*(?:api[_-]?key|token|password|authorization)\s*[:=])")
_EXPANSION = re.compile(r"\$|%[A-Za-z_][A-Za-z0-9_]*%")


def source_present(path):
  return path.exists() or path.is_symlink()


def _digest_files(root, files):
  digest = hashlib.sha256()
  for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
    relative = path.relative_to(root).as_posix().encode()
    content = path.read_bytes()
    digest.update(len(relative).to_bytes(8, "big") + relative)
    digest.update(len(content).to_bytes(8, "big") + content)
  return digest.hexdigest()


def _skill_reports(skills):
  if skills.is_symlink() or not skills.is_dir():
    raise Conflict("OMP项目skill来源不得使用符号链接")
  reports = []
  for package in sorted(skills.iterdir(), key=lambda item: item.name):
    if package.is_symlink():
      raise Conflict("OMP项目skill来源不得使用符号链接")
    if not package.is_dir() or not (package / "SKILL.md").is_file():
      raise Conflict("OMP项目skill包结构无效")
    files = []
    for child in package.rglob("*"):
      if child.is_symlink():
        raise Conflict("OMP项目skill来源不得使用符号链接")
      if child.is_file():
        content = child.read_bytes()
        if _SECRET_TEXT.search(content):
          raise Conflict("OMP项目skill包含疑似秘密内容")
        files.append(child)
      elif not child.is_dir():
        raise Conflict("OMP项目skill包含不支持的文件类型")
    reports.append({"category": "skill", "path": str(package), "sha256": _digest_files(package, files)})
  return reports


def _valid_http_url(value):
  try:
    parsed = urlsplit(value)
    sensitive = {"key", "api_key", "token", "secret", "password", "authorization"}
    return (parsed.scheme == "https" and bool(parsed.netloc) and parsed.username is None and parsed.password is None
      and not _EXPANSION.search(value)
      and not any(key.lower().replace("-", "_") in sensitive for key, _ in parse_qsl(parsed.query)))
  except (TypeError, ValueError):
    return False


def _validate_project_mcp(path, managed_mcp_ids, expected_python, expected_echo):
  try:
    if path.is_symlink():
      raise ValueError()
    value = json.loads(path.read_bytes())
    servers = value["mcpServers"]
    if set(value) != {"mcpServers"} or not isinstance(servers, dict) or set(servers) & set(managed_mcp_ids):
      raise ValueError()
    for server in servers.values():
      if not isinstance(server, dict):
        raise ValueError()
      if server.get("type") == "http":
        if set(server) != {"type", "url"} or not _valid_http_url(server["url"]):
          raise ValueError()
      elif server.get("type") == "stdio":
        if (set(server) != {"type", "command", "args"} or expected_python is None or expected_echo is None
            or server["command"] != str(Path(expected_python).absolute())
            or not isinstance(server["args"], list) or not server["args"]
            or server["args"][0] != str(Path(expected_echo).absolute())
            or any(not isinstance(argument, str) or _EXPANSION.search(argument) for argument in server["args"])):
          raise ValueError()
      else:
        raise ValueError()
  except Exception:
    raise Conflict("OMP项目MCP来源不符合只读非秘密契约") from None


def inspect_project_sources(cwd, policy, *, managed_mcp_ids=(), expected_python=None, expected_echo=None):
  """重新读取固定发现路径并返回仅含路径和摘要的非秘密报告。"""
  current = Path(cwd).resolve()
  ancestors = []
  cursor = current
  while True:
    ancestors.append(cursor)
    if cursor == cursor.parent:
      break
    cursor = cursor.parent
  roots = set(policy.project_roots)
  if policy.project_resources and (not roots or not roots.issubset(set(ancestors))):
    raise Conflict("OMP项目来源根必须是当前目录或其祖先")
  reports = []
  for directory in ancestors:
    for name in DISCOVERY_NAMES:
      if name == ".omp":
        continue
      candidate = directory / name
      if source_present(candidate):
        raise Conflict(f"OMP检测到未声明的项目配置来源: {candidate}")
    omp = directory / ".omp"
    if ".omp" not in DISCOVERY_NAMES:
      continue
    if not source_present(omp):
      continue
    if omp.is_symlink() or not omp.is_dir() or not policy.project_resources:
      raise Conflict(f"OMP检测到未声明的项目配置来源: {omp}")
    allowed = set()
    if directory in roots:
      allowed.add("skills")
    if directory == current and directory in roots:
      allowed.update(("mcp.json", ".mcp.json"))
    children = list(omp.iterdir())
    if any(child.name not in allowed for child in children):
      raise Conflict(f"OMP检测到未声明的项目配置来源: {omp}（仅允许声明的skills/MCP）")
    skills = omp / "skills"
    if source_present(skills):
      reports.extend(_skill_reports(skills))
    mcps = [path for path in (omp / "mcp.json", omp / ".mcp.json") if source_present(path)]
    if len(mcps) > 1:
      raise Conflict("OMP项目MCP来源存在歧义")
    if mcps:
      _validate_project_mcp(mcps[0], managed_mcp_ids, expected_python, expected_echo)
      reports.append({"category": "mcp", "path": str(mcps[0]), "sha256": hashlib.sha256(mcps[0].read_bytes()).hexdigest()})
  return tuple(sorted(reports, key=lambda item: (item["path"], item["category"])))


def assert_native_sources(identity, allowed=(), mcp_shape=None, project_resources=False, *,
    model_providers=None, extension_suffixes=()):
  allowed = {Path(path) for path in allowed}
  def accepted(path):
    if path.is_symlink():
      return False
    if path in allowed:
      return path.is_file()
    if path.is_dir() and any(candidate.is_relative_to(path) for candidate in allowed):
      for child in path.rglob("*"):
        if child.is_symlink() or child.is_file() and child not in allowed:
          return False
        if child.is_dir() and not any(candidate == child or candidate.is_relative_to(child) for candidate in allowed):
          return False
      return True
    return False
  for root in (identity.home, identity.agent_dir):
    for name in DOTENV_NAMES:
      path = root / name
      if path.exists() or path.is_symlink():
        raise Conflict("OMP检测到未声明的dotenv来源")
  home_env = identity.home / ".omp/.env"
  if home_env.exists() or home_env.is_symlink():
    raise Conflict("OMP检测到未声明的dotenv来源")
  source_names = tuple(name for name in NATIVE_PROFILE_SOURCES if name not in ("config.yml", "models.yml"))
  default_agent = identity.home / ".omp/agent"
  for root in (default_agent, identity.agent_dir):
    names = source_names + (("config.yml", "models.yml") if root == default_agent else ())
    for name in names:
      path = root / name
      if (path.exists() or path.is_symlink()) and not accepted(path):
        raise Conflict("OMP检测到未声明的profile配置来源")
  for path in (identity.home / ".omp/plugins/installed_plugins.json", identity.home / ".omp/marketplaces.json"):
    if path.exists() or path.is_symlink():
      raise Conflict("OMP检测到未声明的插件或marketplace来源")
  config = identity.agent_dir / "config.yml"
  if config.exists() or config.is_symlink():
    try:
      if config.is_symlink():
        raise ValueError()
      value = yaml.safe_load(config.read_bytes()) or {}
      auth = value.get("auth", {}) if isinstance(value, dict) else None
      protected = (("skills", "enablePiUser", True), ("skills", "enablePiProject", project_resources),
        ("mcp", "enableProjectConfig", project_resources), ("startup", "checkUpdate", False),
        ("marketplace", "autoUpdate", "off"), ("autolearn", "enabled", False))
      if (not isinstance(auth, dict) or auth.get("broker") or auth.get("gateway")
          or value.get("enabledProviders") != [] or value.get("disabledProviders") != list(DISABLED_PROVIDERS)):
        raise ValueError()
      for parent, key, expected in protected:
        section = value.get(parent)
        if not isinstance(section, dict) or section.get(key) != expected:
          raise ValueError()
      for feature in ("memory", "tiny", "speech", "browser", "eval"):
        section = value.get(feature)
        if section not in (None, False, {"enabled": False}) and not (feature == "memory" and section == {"backend": "off"}):
          raise ValueError()
        if any(key.startswith(feature + ".") for key in value):
          raise ValueError()
      providers = value.get("providers", {})
      if (not isinstance(providers, dict)
          or any(key in providers for key in ("tinyModel", "tinyModelDevice", "tinyModelDtype"))
          or any(key.startswith("providers.tinyModel") for key in value)):
        raise ValueError()
      skills = value.get("skills", {})
      if (not isinstance(skills, dict) or "customDirectories" in skills
          or "skills.customDirectories" in value):
        raise ValueError()
      extensions = value.get("extensions", [])
      suffixes = tuple(extension_suffixes)
      if (not isinstance(extensions, list) or len(extensions) != len(suffixes)
          or any(not isinstance(path, str) or not Path(path).is_absolute()
                 or not path.replace("\\", "/").endswith("/" + suffix)
                 for path, suffix in zip(extensions, suffixes))):
        raise ValueError()
    except Exception:
      raise Conflict("OMP原生配置含无效或受禁认证来源") from None
  models = identity.agent_dir / "models.yml"
  if models.exists() or models.is_symlink():
    try:
      if models.is_symlink():
        raise ValueError()
      value = yaml.safe_load(models.read_bytes()) or {}
      if value != {"providers": model_providers or {}}:
        raise ValueError()
    except Exception:
      raise Conflict("OMP原生模型provider集合或字段不符合受管声明") from None
  elif model_providers:
    raise Conflict("OMP原生模型provider集合或字段不符合受管声明")
  mcp = identity.agent_dir / "mcp.json"
  if (mcp.exists() or mcp.is_symlink()) and mcp_shape is not None:
    try:
      if mcp.is_symlink():
        raise ValueError()
      value = json.loads(mcp.read_bytes())
      servers = value["mcpServers"]
      if set(value) != {"mcpServers"} or not isinstance(servers, dict) or set(servers) != set(mcp_shape):
        raise ValueError()
      for server_id, expected in mcp_shape.items():
        server = servers[server_id]
        if not isinstance(server, dict) or set(server) != set(expected):
          raise ValueError()
        for section, names in expected.items():
          if names is not None and (not isinstance(server[section], dict) or set(server[section]) != set(names)):
            raise ValueError()
    except Exception:
      raise Conflict("OMP原生MCP包含未声明server或字段") from None
