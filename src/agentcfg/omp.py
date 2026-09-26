"""Oh My Pi adapter：隔离身份、非秘密意图与受控启动契约。"""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import stat
from urllib.parse import parse_qsl, urlsplit
import re

from .adapter import Adapter, AdapterDeclaration, Artifact, DependencyPlan, EnvironmentBinding, LaunchSpec, ManagedTarget, Ownership, SecretRef
from .schema import AdapterPolicy, AdapterSchemaBundle, AdapterSchemas, AuthenticationClaim, ConfigError
from .omp_identity import lifecycle_guard, native_identity
from .omp_discovery import DISABLED_PROVIDERS, SourcePolicy, assert_native_sources, inspect_project_sources
from .omp_env import generated_name
from .omp_settings import RUNTIME, PROVIDER_OPTIONS, MODEL_OPTIONS, ROLE_THINKING, runtime_values, validate_options
from .render import render_rules
from .paths import relative_path


def closed(properties, required=()):
  return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


STRING = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": STRING, "uniqueItems": True}
VERSION = {"type": "integer", "const": 1}
KEY_BINDING = {"oneOf": [STRING, STRINGS]}
OPTIONS = closed({"discovery": closed({"project_resources": {"type": "boolean"}, "project_roots": STRINGS}),
                  "resources": closed({"prompts": STRINGS, "themes": STRINGS, "agents": STRINGS}),
                  "runtime": RUNTIME, "provider_options": PROVIDER_OPTIONS, "model_options": MODEL_OPTIONS,
                  "role_thinking": ROLE_THINKING,
                  "tiny_model": {"type": "string", "const": "local/lfm2.5-230m"},
                  "ui": closed({"theme_dark": STRING, "theme_light": STRING,
                                "keybindings": {"type": "object", "additionalProperties": KEY_BINDING}}),
                  "mcp": {"type": "object", "additionalProperties": closed({"environment_refs": {
                    "type": "object", "additionalProperties": STRING}}, ("environment_refs",))}})


FORBIDDEN_OPTIONS = {"--profile", "--alias", "--config", "--session-dir", "--extension", "--trusted-extension", "-e", "--hook", "--plugin-dir", "--cwd", "-C", "--from-claude", "--from-codex", "--add-dir",
  "--continue", "-c", "--resume", "-r", "--session", "--fork",
  "--api-key", "--token", "--secret", "--auth-broker", "--broker", "--gateway", "--agent-dir"}
DANGEROUS_COMMANDS = {"install", "update", "upgrade", "uninstall", "plugin", "plugins", "marketplace", "config", "auth-broker", "auth-gateway", "gateway"}
NATIVE_SUBCOMMANDS = {"launch", "acp", "auth-broker", "auth-gateway", "agents", "bench", "browser-relay", "cleanse",
  "collab", "commit", "completions", "__complete", "compress", "config", "dry-balance", "find", "gc", "grep",
  "gallery", "git", "grievances", "images", "img", "if-bench", "install", "join", "login", "models", "plugin",
  "plugins", "ps", "say", "clip", "play", "share", "setup", "shell", "read", "render", "skill", "skills", "ssh",
  "stats", "stream", "update", "usage", "tiny-models", "token", "toks", "ttsr", "worktree", "wt", "search", "q",
  "web-search", "daemon", "serve", "help"}
WORKER_SELECTORS = {"__omp_worker_blob_broker", "__omp_worker_computer", "__omp_worker_daemon_broker",
  "__omp_worker_lsp_mux", "__omp_worker_stats_activity", "__omp_worker_terminal_output"}
CALLER_IDENTITY_ENV = {"OMP_PROFILE", "OMP_AUTH_BROKER_URL", "OMP_AUTH_BROKER_TOKEN", "PI_PROFILE",
  "PI_CODING_AGENT_DIR", "PI_CONFIG_DIR", "PI_CONFIG_FILES", "PI_SESSION_DIR", "PI_CODING_AGENT_SESSION_DIR"}
ALLOWED_VALUELESS = {"--help", "-h", "--version", "-v", "--no-title", "--print", "-p"}
ALLOWED_VALUE_OPTIONS = {"--provider", "--model", "--smol", "--slow", "--plan", "--thinking", "--service-tier", "--max-time"}
ROLE_MAP = {"main": "default", "smol": "smol", "slow": "slow", "vision": "vision", "plan": "plan", "advisor": "advisor", "task": "task"}
PROTOCOL_MAP = {"openai-compatible": "openai-completions", "openai-responses": "openai-responses", "anthropic-messages": "anthropic-messages"}
KEYBINDING_ACTIONS = {"app.model.cycleForward", "app.history.search"}
ENV_EXPANSION = re.compile(r"\$\{[^}]+\}")


def validate_managed_argv(arguments):
  """解析原生 option token；第二个 `--` 后是普通提示文本。"""
  if arguments and arguments[0] == "usage":
    from .usage import validate_managed_tail
    validate_managed_tail(tuple(arguments[1:]))
    return
  positional = []
  seen_options = set()
  tokens = list(arguments)
  index = 0
  while index < len(tokens):
    token = tokens[index]
    if token == "--":
      break
    if not isinstance(token, str) or "\0" in token:
      raise ConfigError("omp-argv-invalid")
    option = token.split("=", 1)[0]
    if option in FORBIDDEN_OPTIONS:
      raise ConfigError("omp-argv-managed-boundary")
    if token.startswith("-"):
      if option in ALLOWED_VALUELESS:
        if "=" in token:
          raise ConfigError("omp-argv-invalid")
      elif option in ALLOWED_VALUE_OPTIONS:
        if option in seen_options:
          raise ConfigError("omp-argv-option-repeated")
        seen_options.add(option)
        if "=" in token:
          if not token.partition("=")[2]:
            raise ConfigError("omp-argv-invalid")
        else:
          index += 1
          if index >= len(tokens) or tokens[index] == "--" or tokens[index].startswith("-"):
            raise ConfigError("omp-argv-invalid")
      else:
        raise ConfigError("omp-argv-flag-not-allowed")
    if not token.startswith("-") and not (index > 0 and tokens[index - 1].split("=", 1)[0] in ALLOWED_VALUE_OPTIONS
                                           and "=" not in tokens[index - 1]):
      positional.append(token)
    index += 1
  first = next((item for item in positional if not item.startswith("-")), None)
  if first in WORKER_SELECTORS or first in NATIVE_SUBCOMMANDS - {"login", "usage"}:
    raise ConfigError("omp-operation-not-managed")
  if first == "login" and tuple(arguments) != ("login", "openai-codex"):
    raise ConfigError("omp-login-provider-not-supported")


def classify_operation(arguments):
  """按已验证token分类；不读取值参数，也不扫描第二个`--`后的提示文本。"""
  tokens = list(arguments)
  if tokens and tokens[0] in ("login", "usage"):
    return tokens[0]
  information = False
  index = 0
  while index < len(tokens):
    token = tokens[index]
    if token == "--":
      break
    option, equal, _ = token.partition("=")
    if option in ("--help", "-h", "--version", "-v"):
      information = True
    if option in ALLOWED_VALUE_OPTIONS and not equal:
      index += 2
      continue
    index += 1
  return "information" if information else "session"


def _option_values(arguments, names):
  result = []
  tokens = list(arguments)
  index = 0
  while index < len(tokens):
    token = tokens[index]
    if token == "--":
      break
    name, equal, inline = token.partition("=")
    if name in names:
      if equal:
        value = inline
      else:
        index += 1
        if index >= len(tokens) or tokens[index] == "--":
          raise ConfigError("omp-model-selection-invalid")
        value = tokens[index]
      if not value:
        raise ConfigError("omp-model-selection-invalid")
      result.append(value)
    index += 1
  if len(result) > 1:
    raise ConfigError("omp-model-selection-repeated")
  return result[0] if result else None


def validate_model_selection(data, arguments):
  provider = _option_values(arguments, {"--provider"})
  model = _option_values(arguments, {"--model"})
  providers = set(data.get("providers", {}))
  models = data.get("models", {})
  if provider is not None and provider not in providers:
    raise ConfigError("omp-provider-not-declared")
  allowed = {item["provider"] + "/" + item["remote_id"] for item in models.values()}
  for selected in (model, *(_option_values(arguments, {name}) for name in ("--smol", "--slow", "--plan"))):
    if selected is not None and selected not in allowed:
      raise ConfigError("omp-model-not-declared-or-ambiguous")
    if selected is not None and provider is not None and not selected.startswith(provider + "/"):
      raise ConfigError("omp-model-provider-mismatch")


def _pointer(value):
  return value.replace("~", "~0").replace("/", "~1")


def _has_url_credential(value):
  try:
    parsed = urlsplit(value)
    return (parsed.username is not None or parsed.password is not None
      or any(key.lower().replace("-", "_") in {"key", "api_key", "token", "secret", "password", "authorization"}
             for key, _ in parse_qsl(parsed.query)))
  except (TypeError, ValueError):
    return True


def _native_provider_id(provider_id, provider):
  if provider.get("protocol") == "oauth-dynamic":
    if provider_id != "codex" or provider.get("auth_kind") != "oauth":
      raise ConfigError("omp-oauth-provider-not-supported")
    return "openai-codex"
  return provider_id


def _native_base(data):
  profile_id = data["profile"]["id"]
  instance = Path(data["machine"]["paths"]["instances_root"]) / "omp" / profile_id
  identity = native_identity(profile_id, instance)
  return "user-home/.omp/profiles/" + identity.native_name + "/agent"


def _native_model_providers(data):
  """构造原生models.yml的完整provider集合，供渲染与启动前复核共用。"""
  claimed = {}
  result = {}
  for provider_id, provider in sorted(data.get("providers", {}).items()):
    if provider["protocol"] == "oauth-dynamic":
      continue
    native = _native_provider_id(provider_id, provider)
    models = []
    for model_id in data["profile"]["models"]:
      model = data["models"][model_id]
      if model["provider"] == provider_id:
        models.append({"name": model_id, "id": model["remote_id"], "contextWindow": model["context_window"],
          "maxTokens": model["max_output_tokens"], "input": model["input"],
          **data["profile"].get("agent_options", {}).get("model_options", {}).get(model_id, {})})
    result[native] = {"baseUrl": provider["base_url"], "api": PROTOCOL_MAP[provider["protocol"]],
      "apiKey": generated_name("provider", provider_id, "key", claimed=claimed), "models": models,
      **data["profile"].get("agent_options", {}).get("provider_options", {}).get(provider_id, {})}
  return result


def _resource_bytes(repository, definition, kind):
  try:
    path = relative_path(definition["path"])
    if definition != {"kind": kind, "path": definition["path"], "scope": "global"}:
      raise ValueError()
    expected = Path("agents/omp/resources") / {"prompt": "prompts", "theme": "themes", "agent": "agents"}[kind]
    if not path.is_relative_to(expected):
      raise ValueError()
    from .storage import Tree
    with Tree(repository, private=False) as tree:
      raw = tree.read(path.as_posix())
    if raw is None:
      raise ValueError()
    return raw[0]
  except Exception:
    raise ConfigError("omp-resource-invalid") from None


def _validate_theme(content):
  try:
    from jsonschema import Draft202012Validator
    theme = json.loads(content)
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/omp-theme.schema.json").read_bytes())
    Draft202012Validator(schema).validate(theme)
    variables = theme.get("vars", {})
    visiting = set()
    resolved = set()
    def check(value):
      if isinstance(value, int):
        return 0 <= value <= 255
      if not isinstance(value, str):
        return False
      if value == "" or re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        return True
      if value not in variables or value in visiting:
        return False
      if value in resolved:
        return True
      visiting.add(value)
      valid = check(variables[value])
      visiting.remove(value)
      if valid:
        resolved.add(value)
      return valid
    if not all(check(value) for value in variables.values()) or not all(check(value) for value in theme["colors"].values()):
      raise ValueError()
    return theme
  except Exception:
    raise ConfigError("omp-theme-invalid") from None


def _validate_keybindings(value):
  if set(value) - KEYBINDING_ACTIONS:
    raise ConfigError("omp-keybinding-action")
  for binding in value.values():
    keys = [binding] if isinstance(binding, str) else binding
    if (not isinstance(keys, list) or any(not isinstance(key, str) or not key
        or not re.fullmatch(r"[A-Za-z0-9]+(?:\+[A-Za-z0-9]+)*", key) for key in keys)):
      raise ConfigError("omp-keybinding-chord")


class OmpAdapter(Adapter):
  declaration = AdapterDeclaration("omp", 1, "omp-1")
  shared_files = ()

  def __init__(self, repository):
    self.repository = Path(repository)

  def dependency_backend(self):
    from .omp_dependencies import OmpBackend
    return OmpBackend()

  def validate(self, data):
    profile = data["profile"]
    if profile["agent"] != "omp":
      raise ConfigError("omp-profile-agent")
    validate_options(data)
    selected = set(data.get("providers", {}))
    if selected & set(DISABLED_PROVIDERS):
      raise ConfigError("omp-disabled-provider-conflict")
    native_providers = {}
    selected_models = set(profile.get("models", ()))
    exact_models = {}
    for provider_id, provider in data.get("providers", {}).items():
      protocol = provider.get("protocol")
      native_id = _native_provider_id(provider_id, provider)
      if native_id in native_providers:
        raise ConfigError("omp-native-provider-conflict")
      native_providers[native_id] = provider_id
      if protocol == "oauth-dynamic":
        if any(model.get("provider") == provider_id for model in data.get("models", {}).values()):
          raise ConfigError("omp-oauth-static-model-not-supported")
        continue
      if (protocol not in PROTOCOL_MAP or provider.get("auth_kind") != "api-key"
          or not isinstance(provider.get("base_url"), str) or _has_url_credential(provider["base_url"])
          or not isinstance(provider.get("credential_ref"), str)):
        raise ConfigError("omp-provider-not-supported")
    for model_id, model in data.get("models", {}).items():
      if model_id not in selected_models or model.get("provider") not in data.get("providers", {}):
        raise ConfigError("omp-model-not-selected")
      if (not isinstance(model.get("context_window"), int) or not isinstance(model.get("max_output_tokens"), int)
          or model["context_window"] < 1 or model["max_output_tokens"] < 1):
        raise ConfigError("omp-model-capacity-required")
      inputs = model.get("input")
      if not isinstance(inputs, list) or not inputs or set(inputs) - {"text", "image"}:
        raise ConfigError("omp-model-input-not-supported")
      remote = model.get("remote_id")
      if not isinstance(remote, str) or not remote or "/" in remote:
        raise ConfigError("omp-model-remote-id")
      native = _native_provider_id(model["provider"], data["providers"][model["provider"]]) + "/" + remote
      if native in exact_models:
        raise ConfigError("omp-native-model-conflict")
      exact_models[native] = model_id
    roles = profile.get("roles", {})
    if set(roles) - set(ROLE_MAP) or any(model_id not in selected_models or model_id not in data.get("models", {})
                                        for model_id in roles.values()):
      raise ConfigError("omp-model-role-reference")
    if "vision" in roles and "image" not in data["models"][roles["vision"]]["input"]:
      raise ConfigError("omp-vision-model-input")
    try:
      for plugin_id, package in data.get("plugins", {}).items():
        if package.get("id") != plugin_id:
          raise ValueError()
        relative_path(package["source"])
        for entrypoint in package["entrypoints"]:
          relative_path(entrypoint)
      for plugin_id in profile.get("plugins", ()):
        if plugin_id not in data.get("plugins", {}) or any(
            not entrypoint.endswith(".ts") for entrypoint in data["plugins"][plugin_id]["entrypoints"]):
          raise ValueError()
    except Exception:
      raise ConfigError("omp-plugin-package") from None
    options = profile.get("agent_options", {})
    catalog = data.get("adapter_documents", {}).get("agent", {}).get("resources", {})
    resources = options.get("resources", {})
    for kind, plural in (("prompt", "prompts"), ("theme", "themes"), ("agent", "agents")):
      for resource_id in resources.get(plural, []):
        if resource_id not in catalog or catalog[resource_id].get("kind") != kind:
          raise ConfigError("omp-resource-reference")
        content = _resource_bytes(self.repository, catalog[resource_id], kind)
        if kind == "agent":
          from .omp_settings import validate_agent
          validate_agent(content, resource_id, data)
        if kind == "theme":
          theme = _validate_theme(content)
          if theme.get("name") != resource_id:
            raise ConfigError("omp-theme-identity")
    ui = options.get("ui", {})
    themes = set(resources.get("themes", []))
    if any(ui.get(name) not in themes for name in ("theme_dark", "theme_light") if name in ui):
      raise ConfigError("omp-theme-not-selected")
    _validate_keybindings(ui.get("keybindings", {}))
    mcp_options = options.get("mcp", {})
    if set(mcp_options) - set(data.get("mcp", {})):
      raise ConfigError("omp-mcp-options-unselected")
    for server_id, server in data.get("mcp", {}).items():
      transport = server.get("transport")
      if transport == "stdio":
        if (server.get("command") != "omp-package:echo-mcp" or "url" in server
            or "credential_ref" in server or any(arg.startswith(("!", "npx", "uvx"))
            or ENV_EXPANSION.search(arg) for arg in server.get("args", []))):
          raise ConfigError("omp-mcp-stdio-not-locked")
      elif transport == "streamable-http":
        if ("command" in server or "args" in server or not isinstance(server.get("url"), str)
            or not server["url"].startswith("https://") or _has_url_credential(server["url"])
            or ENV_EXPANSION.search(server["url"])):
          raise ConfigError("omp-mcp-http-invalid")
        if mcp_options.get(server_id, {}).get("environment_refs"):
          raise ConfigError("omp-mcp-http-environment")
      else:
        raise ConfigError("omp-mcp-transport")
      refs = mcp_options.get(server_id, {}).get("environment_refs", {})
      if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) or not isinstance(ref, str) or not ref
             for name, ref in refs.items()):
        raise ConfigError("omp-mcp-environment-reference")
    required_packages = set(profile.get("plugins", ()))
    if any(server["transport"] == "stdio" for server in data.get("mcp", {}).values()):
      required_packages.add("echo-mcp")
    if required_packages:
      from .omp_dependencies import OmpBackend, TAG
      canonical = OmpBackend()._resources(self.repository)[1]
      declarations = data.get("adapter_documents", {}).get("plugins", {}).get("plugins", data.get("plugins", {}))
      for package_id in required_packages:
        declared = declarations.get(package_id)
        actual = canonical.get(package_id)
        if (declared is None or actual is None or declared != {"id": package_id, "source": actual["source"],
            "entrypoints": actual["entrypoints"], "tree_digest": actual["tree_digest"], "license": actual["license"],
            "compatibility": {"omp": TAG}}):
          raise ConfigError("omp-package-catalog-integrity")
    protected = {"HOME", "OMP_PROFILE", "OMP_AUTH_BROKER", "OMP_AUTH_BROKER_URL", "OMP_AUTH_BROKER_TOKEN", "PI_PROFILE", "PI_CODING_AGENT_DIR", "PI_CONFIG_DIR", "PI_CONFIG_FILES", "PI_SESSION_DIR",
                 "PI_CODING_AGENT_SESSION_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"}
    machine_env = data["machine"].get("environment", {})
    if protected & (set(machine_env.get("inherit", [])) | set(machine_env.get("values", {}))):
      raise ConfigError("omp-identity-environment-override")

  def managed_targets(self, data):
    self.validate(data)
    base = _native_base(data)
    targets = [ManagedTarget(base + "/config.yml", Ownership.FIELDS, "yaml", selector) for selector in (
      "/skills/enablePiUser", "/skills/enablePiProject", "/mcp/enableProjectConfig", "/enabledProviders",
      "/disabledProviders", "/startup/checkUpdate", "/marketplace/autoUpdate", "/autolearn/enabled")]
    claimed = {}
    for provider_id, provider in sorted(data.get("providers", {}).items()):
      if provider["protocol"] == "oauth-dynamic":
        continue
      native_id = _pointer(_native_provider_id(provider_id, provider))
      prefix = "/providers/" + native_id
      targets.extend((
        ManagedTarget(base + "/models.yml", Ownership.FIELDS, "yaml", prefix + "/baseUrl"),
        ManagedTarget(base + "/models.yml", Ownership.FIELDS, "yaml", prefix + "/api"),
        ManagedTarget(base + "/models.yml", Ownership.FIELDS, "yaml", prefix + "/apiKey",
          (generated_name("provider", provider_id, "key", claimed=claimed),)),
        ManagedTarget(base + "/models.yml", Ownership.FIELDS, "yaml", prefix + "/models"),
      ))
    for provider_id, provider in sorted(data.get("providers", {}).items()):
      if provider["protocol"] != "oauth-dynamic":
        for key in data["profile"].get("agent_options", {}).get("provider_options", {}).get(provider_id, {}):
          targets.append(ManagedTarget(base + "/models.yml", Ownership.FIELDS, "yaml",
            "/providers/" + _pointer(_native_provider_id(provider_id, provider)) + "/" + key))
    for role in sorted(data["profile"].get("roles", {})):
      targets.append(ManagedTarget(base + "/config.yml", Ownership.FIELDS, "yaml", "/modelRoles/" + ROLE_MAP[role]))
    if data["profile"].get("rules"):
      targets.append(ManagedTarget(base + "/RULES.md", Ownership.FILE, "bytes"))
    if data["profile"].get("skills"):
      targets.append(ManagedTarget(base + "/skills", Ownership.FILE, "skill-directory"))
    options = data["profile"].get("agent_options", {})
    resources = options.get("resources", {})
    for key in runtime_values(options):
      targets.append(ManagedTarget(base + "/config.yml", Ownership.FIELDS, "yaml", "/" + key))
    for resource_id in resources.get("agents", []):
      targets.append(ManagedTarget(f"{base}/agents/{resource_id}.md", Ownership.FILE, "bytes"))
    for resource_id in resources.get("prompts", []):
      targets.append(ManagedTarget(f"{base}/prompts/{resource_id}.md", Ownership.FILE, "bytes"))
    for resource_id in resources.get("themes", []):
      targets.append(ManagedTarget(f"{base}/themes/{resource_id}.json", Ownership.FILE, "json"))
    ui = options.get("ui", {})
    for name in ("theme_dark", "theme_light"):
      if name in ui:
        targets.append(ManagedTarget(base + "/config.yml", Ownership.FIELDS, "yaml",
          "/theme/" + name.removeprefix("theme_")))
    for action in sorted(ui.get("keybindings", {})):
      targets.append(ManagedTarget(base + "/keybindings.yml", Ownership.FIELDS, "yaml", "/" + _pointer(action)))
    if data["profile"].get("plugins"):
      targets.append(ManagedTarget(base + "/config.yml", Ownership.FIELDS, "yaml", "/extensions"))
    claimed = {}
    mcp_options = options.get("mcp", {})
    for server_id, server in sorted(data.get("mcp", {}).items()):
      prefix = "/mcpServers/" + _pointer(server_id)
      path = base + "/mcp.json"
      if server["transport"] == "stdio":
        for leaf in ("type", "command", "args"):
          targets.append(ManagedTarget(path, Ownership.FIELDS, "json", prefix + "/" + leaf))
        for name in sorted(mcp_options.get(server_id, {}).get("environment_refs", {})):
          token = generated_name("mcp", server_id, "env:" + name, claimed=claimed)
          targets.append(ManagedTarget(path, Ownership.FIELDS, "json", prefix + "/env/" + _pointer(name), (token,)))
      else:
        targets.extend((ManagedTarget(path, Ownership.FIELDS, "json", prefix + "/type"),
          ManagedTarget(path, Ownership.FIELDS, "json", prefix + "/url")))
        if "credential_ref" in server:
          token = generated_name("mcp", server_id, "header:Authorization", claimed=claimed)
          targets.append(ManagedTarget(path, Ownership.FIELDS, "json", prefix + "/headers/Authorization", (token,)))
    return tuple(targets)

  def render_context_required(self, data):
    return bool(data["profile"].get("plugins") or any(
      server.get("transport") == "stdio" for server in data.get("mcp", {}).values()))

  def render(self, data):
    if self.render_context_required(data):
      raise ConfigError("omp-render-context-required")
    return self._render(data, None)

  def render_with_context(self, data, context):
    from .adapter import RenderContext
    if type(context) is not RenderContext or ENV_EXPANSION.search(str(context.runtime_root)):
      raise ConfigError("omp-render-context-required")
    return self._render(data, context)

  def _render(self, data, context):
    self.validate(data)
    targets = self.managed_targets(data)
    project = SourcePolicy.from_options(data["profile"]["agent_options"].get("discovery", {})).project_resources
    protection_values = (True, project, project, [], list(DISABLED_PROVIDERS), False, "off", False)
    artifacts = [Artifact(target, json.dumps(value, ensure_ascii=False, sort_keys=True).encode()) for target, value in zip(targets[:8], protection_values)]
    by_key = {(target.path, target.selector): target for target in targets}
    base = _native_base(data)
    for native, provider_value in _native_model_providers(data).items():
      prefix = "/providers/" + _pointer(native)
      path = base + "/models.yml"
      provider_values = {prefix + "/" + key: value for key, value in provider_value.items()}
      for selector, value in provider_values.items():
        artifacts.append(Artifact(by_key[(path, selector)], json.dumps(value, ensure_ascii=False, sort_keys=True).encode()))
    for role, model_id in sorted(data["profile"].get("roles", {}).items()):
      model = data["models"][model_id]
      native = _native_provider_id(model["provider"], data["providers"][model["provider"]]) + "/" + model["remote_id"]
      level = data["profile"].get("agent_options", {}).get("role_thinking", {}).get(role)
      if level:
        native += ":" + level
      selector = "/modelRoles/" + ROLE_MAP[role]
      artifacts.append(Artifact(by_key[(base + "/config.yml", selector)], json.dumps(native).encode()))
    if data["profile"].get("rules"):
      rules = tuple(data["rules"][key] for key in data["profile"]["rules"])
      artifacts.append(Artifact(by_key[(base + "/RULES.md", None)], render_rules(self.repository, rules, {})))
    options = data["profile"].get("agent_options", {})
    catalog = data.get("adapter_documents", {}).get("agent", {}).get("resources", {})
    for key, value in runtime_values(options).items():
      artifacts.append(Artifact(by_key[(base + "/config.yml", "/" + key)],
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()))
    for resource_id in options.get("resources", {}).get("agents", []):
      artifacts.append(Artifact(by_key[(f"{base}/agents/{resource_id}.md", None)],
        _resource_bytes(self.repository, catalog[resource_id], "agent")))
    for resource_id in options.get("resources", {}).get("prompts", []):
      target = by_key[(f"{base}/prompts/{resource_id}.md", None)]
      artifacts.append(Artifact(target, _resource_bytes(self.repository, catalog[resource_id], "prompt")))
    for resource_id in options.get("resources", {}).get("themes", []):
      target = by_key[(f"{base}/themes/{resource_id}.json", None)]
      content = _resource_bytes(self.repository, catalog[resource_id], "theme")
      _validate_theme(content)
      artifacts.append(Artifact(target, content))
    ui = options.get("ui", {})
    for name in ("theme_dark", "theme_light"):
      if name in ui:
        selector = "/theme/" + name.removeprefix("theme_")
        artifacts.append(Artifact(by_key[(base + "/config.yml", selector)], json.dumps(ui[name]).encode()))
    for action, binding in sorted(ui.get("keybindings", {}).items()):
      selector = "/" + _pointer(action)
      artifacts.append(Artifact(by_key[(base + "/keybindings.yml", selector)],
        json.dumps(binding, ensure_ascii=False, sort_keys=True).encode()))
    if data["profile"].get("plugins"):
      if context is None:
        raise ConfigError("omp-render-context-required")
      extensions = []
      for plugin_id in data["profile"]["plugins"]:
        package = data["plugins"][plugin_id]
        extensions.extend(str(context.runtime_root / "packages" / plugin_id / entrypoint)
          for entrypoint in package["entrypoints"])
      artifacts.append(Artifact(by_key[(base + "/config.yml", "/extensions")],
        json.dumps(extensions, ensure_ascii=False).encode()))
    mcp_options = options.get("mcp", {})
    claimed = {}
    for server_id, server in sorted(data.get("mcp", {}).items()):
      prefix = "/mcpServers/" + _pointer(server_id)
      path = base + "/mcp.json"
      values = {prefix + "/type": "stdio" if server["transport"] == "stdio" else "http"}
      if server["transport"] == "stdio":
        if context is None:
          raise ConfigError("omp-render-context-required")
        from .omp_dependencies import PYTHON_REQUIREMENT, interpreter_identity
        python = interpreter_identity({"python": PYTHON_REQUIREMENT})["python"]["path"]
        values.update({prefix + "/command": python,
          prefix + "/args": [str(context.runtime_root / "packages/echo-mcp/server.py"), *server.get("args", [])]})
        for name in sorted(mcp_options.get(server_id, {}).get("environment_refs", {})):
          values[prefix + "/env/" + _pointer(name)] = generated_name("mcp", server_id, "env:" + name, claimed=claimed)
      else:
        values[prefix + "/url"] = server["url"]
        if "credential_ref" in server:
          values[prefix + "/headers/Authorization"] = generated_name("mcp", server_id, "header:Authorization", claimed=claimed)
      for selector, value in values.items():
        artifacts.append(Artifact(by_key[(path, selector)], json.dumps(value, ensure_ascii=False, sort_keys=True).encode()))
    from jsonschema import Draft202012Validator
    from .schema import _read_schema
    validator = Draft202012Validator(_read_schema("omp-native"))
    for artifact, value in zip(artifacts[:8], protection_values):
      intent = {"path": Path(artifact.target.path).name, "codec": artifact.target.serialization,
                "selector": artifact.target.selector, "value": value}
      if not validator.is_valid(intent):
        raise ConfigError("omp-generated-native-intent")
    return tuple(artifacts)

  def dependency_plan(self, data):
    return DependencyPlan(("oh-my-pi@18.3.0",))

  def lifecycle_guard(self, workspace):
    return lifecycle_guard(workspace, create=False)

  def apply_lifecycle_guard(self, workspace):
    return lifecycle_guard(workspace, create=True)

  def validate_arguments(self, arguments):
    validate_managed_argv(arguments)

  def operation_arguments(self, arguments):
    arguments = tuple(arguments)
    operation = classify_operation(arguments)
    managed = arguments[:arguments.index("--")] if "--" in arguments else arguments
    if operation != "session" or "--no-title" in managed:
      return arguments
    return ("--no-title", *arguments)

  def operation_cwd(self, workspace, cwd, arguments):
    if classify_operation(arguments) != "session":
      return native_identity(workspace.profile, workspace.instance).home
    return cwd

  def operation_environment(self, spec, arguments):
    """中性操作不解析会话provider或MCP秘密。"""
    if classify_operation(arguments) == "session":
      return spec
    return replace(spec, environment=tuple(item for item in spec.environment if not isinstance(item.value, SecretRef)))

  def operation_guard(self, workspace, cwd, arguments):
    self._validate_caller_environment()
    operation = classify_operation(arguments)
    if operation == "session":
      validate_model_selection(workspace.resolved.data, arguments)
    options = workspace.resolved.data["profile"]["agent_options"].get("discovery", {})
    policy = SourcePolicy.from_options(options)
    neutral = operation != "session"
    if not neutral:
      self._project_source_report(workspace, cwd, policy)
    identity = native_identity(workspace.profile, workspace.instance)
    assert_native_sources(identity, self._allowed_native_sources(workspace.resolved.data, identity),
      self._mcp_shape(workspace.resolved.data), policy.project_resources,
      model_providers=_native_model_providers(workspace.resolved.data),
      extension_suffixes=self._extension_suffixes(workspace.resolved.data))

  def _validate_caller_environment(self):
    import os
    if CALLER_IDENTITY_ENV & os.environ.keys():
      raise ConfigError("omp-caller-identity-environment")

  def validate_operation_environment(self, workspace, spec=None, env=None):
    self._validate_caller_environment()
    if env is not None:
      identity = native_identity(workspace.profile, workspace.instance)
      expected = {"HOME": str(identity.home), "XDG_CONFIG_HOME": str(identity.xdg_config),
        "XDG_DATA_HOME": str(identity.xdg_data), "XDG_CACHE_HOME": str(identity.xdg_cache),
        "XDG_STATE_HOME": str(identity.xdg_state)}
      if any(env.get(name) != value for name, value in expected.items()) or CALLER_IDENTITY_ENV & env.keys():
        raise ConfigError("omp-operation-environment-mismatch")

  def validate_before_spawn(self, workspace, cwd, arguments, env):
    self.validate_operation_environment(workspace, env=env)
    options = workspace.resolved.data["profile"]["agent_options"].get("discovery", {})
    policy = SourcePolicy.from_options(options)
    neutral = classify_operation(arguments) != "session"
    if not neutral:
      self._project_source_report(workspace, cwd, policy)
    identity = native_identity(workspace.profile, workspace.instance)
    assert_native_sources(identity, self._allowed_native_sources(workspace.resolved.data, identity),
      self._mcp_shape(workspace.resolved.data), policy.project_resources,
      model_providers=_native_model_providers(workspace.resolved.data),
      extension_suffixes=self._extension_suffixes(workspace.resolved.data))

  def _extension_suffixes(self, data):
    return tuple("packages/" + plugin_id + "/" + entrypoint
      for plugin_id in data["profile"].get("plugins", ())
      for entrypoint in data["plugins"][plugin_id]["entrypoints"])

  def _project_source_report(self, workspace, cwd, policy):
    expected_python = expected_echo = None
    if policy.project_resources:
      from .omp_dependencies import PYTHON_REQUIREMENT, interpreter_identity
      from .runtime import runtime_identity
      lock = workspace.backend.read_lock(workspace.repository)
      root = workspace.backend.root(workspace, runtime_identity(workspace, lock))
      metadata = getattr(lock, "metadata", {})
      targets = {entry.get("target") for entry in metadata.get("resources", ()) if isinstance(entry, dict)}
      if (metadata.get("interpreters") == {"python": PYTHON_REQUIREMENT}
          and "packages/echo-mcp/server.py" in targets):
        expected_python = Path(interpreter_identity({"python": PYTHON_REQUIREMENT})["python"]["path"])
        expected_echo = root / "packages/echo-mcp/server.py"
    return inspect_project_sources(cwd, policy, managed_mcp_ids=workspace.resolved.data.get("mcp", {}),
      expected_python=expected_python, expected_echo=expected_echo)

  def _allowed_native_sources(self, data, identity):
    prefix = _native_base(data) + "/"
    result = set()
    for target in self.managed_targets(data):
      if target.path.startswith(prefix) and target.path.endswith(("RULES.md", "mcp.json", ".md", ".json")):
        result.add(identity.instance_root / target.path)
    if data["profile"].get("skills"):
      from .skills import collect_skills
      for artifact in collect_skills(self.repository, data["skills"], target_root=prefix.rstrip("/") + "/skills"):
        result.add(identity.instance_root / artifact.target.path)
    return result

  def _mcp_shape(self, data):
    options = data["profile"].get("agent_options", {}).get("mcp", {})
    result = {}
    for server_id, server in data.get("mcp", {}).items():
      if server["transport"] == "stdio":
        result[server_id] = {"type": None, "command": None, "args": None,
          **({"env": set(options.get(server_id, {}).get("environment_refs", {}))}
             if options.get(server_id, {}).get("environment_refs") else {})}
      else:
        result[server_id] = {"type": None, "url": None,
          **({"headers": {"Authorization"}} if "credential_ref" in server else {})}
    return result

  def launch_spec(self, data, *, cwd, runtime_root, instance_root, lock_identity):
    identity = native_identity(data["profile"]["id"], instance_root)
    claimed = {}
    secrets = [EnvironmentBinding(generated_name("provider", provider_id, "key", claimed=claimed),
      SecretRef(provider["credential_ref"])) for provider_id, provider in sorted(data.get("providers", {}).items())
      if provider.get("protocol") in PROTOCOL_MAP]
    options = data["profile"].get("agent_options", {})
    for server_id, server in sorted(data.get("mcp", {}).items()):
      for name, reference in sorted(options.get("mcp", {}).get(server_id, {}).get("environment_refs", {}).items()):
        secrets.append(EnvironmentBinding(generated_name("mcp", server_id, "env:" + name, claimed=claimed),
          SecretRef(reference if reference.startswith("secret:") else "secret:" + reference)))
      if "credential_ref" in server:
        secrets.append(EnvironmentBinding(generated_name("mcp", server_id, "header:Authorization", claimed=claimed),
          SecretRef(server["credential_ref"])))
    return LaunchSpec((str(runtime_root / "bin/omp"), "--profile", identity.native_name), cwd, lock_identity,
      (EnvironmentBinding("HOME", str(identity.home)), EnvironmentBinding("XDG_CONFIG_HOME", str(identity.xdg_config)),
       EnvironmentBinding("XDG_DATA_HOME", str(identity.xdg_data)), EnvironmentBinding("XDG_CACHE_HOME", str(identity.xdg_cache)),
       EnvironmentBinding("XDG_STATE_HOME", str(identity.xdg_state)), *secrets))

  def runtime_binding(self, data, instance_root):
    identity = native_identity(data["profile"]["id"], instance_root)
    agent = data["profile"]["agent"]
    profile_id = data["profile"]["id"]
    paths = data["machine"]["paths"]
    state_root = Path(paths["state_root"]) / agent / profile_id
    cache_root = Path(paths["cache_root"]) / agent / profile_id
    options = data["profile"]["agent_options"].get("discovery", {})
    policy = SourcePolicy.from_options(options)
    return {"identity": {"profile_id": identity.profile_id, "profile_sha256": identity.profile_hash,
      "native_name": identity.native_name, "home": str(identity.home), "agent_dir": str(identity.agent_dir),
      "xdg": [str(identity.xdg_config), str(identity.xdg_data), str(identity.xdg_cache), str(identity.xdg_state)],
      "layout_version": identity.layout_version},
      "source_policy": {"manifest_sha256": policy.manifest_sha256, "project_resources": policy.project_resources,
                        "project_roots": [str(path) for path in policy.project_roots]},
      "storage": {"state_root": str(state_root), "cache_root": str(cache_root)}}

  def validate_runtime_binding(self, workspace, saved):
    expected = self.runtime_binding(workspace.resolved.data, workspace.instance)
    storage = expected["storage"]
    if (saved != expected or Path(storage["state_root"]) != workspace.state_root
        or Path(storage["cache_root"]) != workspace.cache):
      from .storage import Conflict
      raise Conflict("OMP部署身份或来源策略已变化；请重新plan/apply")

  def prepare_runtime(self, workspace, root):
    from .storage import ensure_private
    identity = native_identity(workspace.profile, workspace.instance)
    for path in (identity.home, identity.agent_dir, identity.xdg_config, identity.xdg_data, identity.xdg_cache, identity.xdg_state):
      ensure_private(path)

  def runtime_guards(self, data):
    targets = self.managed_targets(data)
    return {"files": [target.path for target in targets if target.serialization != "skill-directory"],
      "roots": [target.path for target in targets if target.serialization == "skill-directory"]}

  def launch_preflight_for(self, data, lock):
    return []

  def capture(self, projection):
    raise ConfigError("omp-capture-requires-selection")

  def capture_projection(self, tree):
    from .deployment import parse_native
    try:
      with tree.parent("user-home/.omp/profiles/_") as (directory, _):
        names = [name for name in os.listdir(directory) if name.startswith("rotom-")]
        if len(names) != 1:
          return {}
        info = os.stat(names[0], dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid():
          return {}
      base = "user-home/.omp/profiles/" + names[0] + "/agent"
    except Exception:
      return {}
    return self._capture_projection_at(tree, base)

  def capture_projection_for(self, workspace, tree):
    identity = native_identity(workspace.profile, workspace.instance)
    base = "user-home/.omp/profiles/" + identity.native_name + "/agent"
    return self._capture_projection_at(tree, base)

  def _capture_projection_at(self, tree, base):
    from .deployment import parse_native
    result = {}
    raw = tree.read(base + "/config.yml")
    if raw:
      value = parse_native(raw[0], "yaml")
      if isinstance(value.get("theme"), dict):
        result["theme"] = {key: value["theme"][key] for key in ("dark", "light") if isinstance(value["theme"].get(key), str)}
      if isinstance(value.get("modelRoles"), dict):
        result["modelRoles"] = {key: item for key, item in value["modelRoles"].items() if isinstance(item, str)}
    raw = tree.read(base + "/keybindings.yml")
    if raw:
      value = parse_native(raw[0], "yaml")
      if isinstance(value, dict):
        result["keybindings"] = {key: item for key, item in value.items() if key in KEYBINDING_ACTIONS}
    return result

  def identity_diagnostics(self, workspace, cwd=None):
    """返回身份和实际来源的非秘密诊断，不读取认证或会话数据。"""
    identity = native_identity(workspace.profile, workspace.instance)
    from .omp_identity import validate_layout
    from .storage import Conflict
    layout_conflict = None
    try:
      validate_layout(identity)
    except Conflict:
      layout_conflict = "xdg-or-identity-layout-conflict"
    keybindings = identity.home / ".omp/agent/keybindings.yml"
    default = None
    if keybindings.is_file() and not keybindings.is_symlink():
      content = keybindings.read_bytes()
      default = {"path": str(keybindings), "sha256": hashlib.sha256(content).hexdigest()}
    policy = SourcePolicy.from_options(workspace.resolved.data["profile"]["agent_options"].get("discovery", {}))
    sources = self._project_source_report(workspace, cwd, policy) if cwd is not None else ()
    return {"profile_id": identity.profile_id, "native_name": identity.native_name,
      "profile_sha256": identity.profile_hash, "home": str(identity.home), "agent_dir": str(identity.agent_dir),
      "xdg": {"config": str(identity.xdg_config), "data": str(identity.xdg_data),
        "cache": str(identity.xdg_cache), "state": str(identity.xdg_state)},
      "default_keybindings": default, "account_scope": "native-profile-home", "layout_conflict": layout_conflict,
      "source_policy": {"project_resources": policy.project_resources,
        "project_roots": [str(path) for path in policy.project_roots], "manifest_sha256": policy.manifest_sha256},
      "project_sources": list(sources),
      "project_sources_status": "inspected" if cwd is not None else "not-inspected-without-launch-cwd",
      "migration": "new-profile-relogin-required"}

  def capture_configuration(self, projection, data):
    if not isinstance(projection, dict):
      raise ConfigError("omp-capture-projection")
    result = {}
    options = data["profile"].get("agent_options", {})
    ui = {}
    theme = projection.get("theme", {})
    selected_themes = set(options.get("resources", {}).get("themes", []))
    if isinstance(theme, dict):
      for native, public in (("dark", "theme_dark"), ("light", "theme_light")):
        if native in theme:
          if theme[native] not in selected_themes:
            raise ConfigError("omp-capture-theme")
          ui[public] = theme[native]
    keybindings = projection.get("keybindings", {})
    declared_actions = set(options.get("ui", {}).get("keybindings", {}))
    if isinstance(keybindings, dict):
      captured = {key: value for key, value in keybindings.items() if key in declared_actions}
      _validate_keybindings(captured)
      if captured:
        ui["keybindings"] = captured
    if ui:
      result["agent_options"] = {"ui": ui}
    native_roles = projection.get("modelRoles", {})
    roles = {}
    role_thinking = {}
    if isinstance(native_roles, dict):
      inverse_roles = {native: public for public, native in ROLE_MAP.items()}
      for native_role, value in native_roles.items():
        if native_role not in inverse_roles:
          continue
        if not isinstance(value, str):
          raise ConfigError("omp-capture-model")
        candidates = {}
        for model_id, model in data["models"].items():
          selector = _native_provider_id(model["provider"], data["providers"][model["provider"]]) + "/" + model["remote_id"]
          candidates.setdefault(selector, []).append(model_id)
        level = None
        if value not in candidates:
          from .omp_settings import THINKING
          value, separator, level = value.rpartition(":")
          if not separator or level not in THINKING["enum"]:
            raise ConfigError("omp-capture-model")
        matches = candidates.get(value, [])
        if len(matches) != 1 or matches[0] not in data["profile"]["models"]:
          raise ConfigError("omp-capture-model")
        model_id = matches[0]
        roles[inverse_roles[native_role]] = model_id
        if level:
          role_thinking[inverse_roles[native_role]] = level
    if roles:
      result["roles"] = roles
    if role_thinking:
      result.setdefault("agent_options", {})["role_thinking"] = role_thinking
    return result

  def doctor(self, projection):
    return ("native-auth-is-profile-scoped", "project-discovery-denied-by-default")

  def live_diagnostics(self, data):
    return []

  def schemas(self):
    defaults = closed({key: STRINGS for key in ("providers", "models", "rules", "skills", "plugins", "mcp")} | {"agent_options": OPTIONS})
    resource = closed({"kind": {"type": "string", "enum": ["prompt", "theme", "agent"]}, "path": STRING,
                       "scope": {"type": "string", "const": "global"}}, ("kind", "path", "scope"))
    package = closed({"id": STRING, "source": STRING, "entrypoints": STRINGS,
      "tree_digest": {"type": "string", "pattern": "^[a-f0-9]{64}$"}, "license": STRING,
      "compatibility": closed({"omp": STRING}, ("omp",))},
      ("id", "source", "entrypoints", "tree_digest", "license", "compatibility"))
    documents = {
      "agent": closed({"schema_version": VERSION, "adapter_version": STRING, "upstream_commit": STRING,
        "defaults": defaults, "resources": {"type": "object", "additionalProperties": resource}},
        ("schema_version", "adapter_version", "upstream_commit", "defaults", "resources")),
      "bindings": closed({"schema_version": VERSION,
        "roles": closed({native: {"type": "string", "const": native} for native in ROLE_MAP.values()}, tuple(ROLE_MAP.values())),
        "mcp_transports": closed({"stdio": {"type": "string", "const": "stdio"},
                                  "streamable-http": {"type": "string", "const": "http"}}, ("stdio", "streamable-http"))},
        ("schema_version", "roles", "mcp_transports")),
      "plugins": closed({"schema_version": VERSION, "plugins": {"type": "object", "additionalProperties": package}}, ("schema_version", "plugins")),
    }
    bundle = AdapterSchemaBundle(self.declaration, documents, OPTIONS,
      lambda kind, value: self.validate(value) if kind == "resolved" else None,
      policy=lambda docs: AdapterPolicy(deepcopy(docs["agent"]["defaults"]), deepcopy(docs["plugins"]["plugins"]), frozenset(), frozenset({"OMP_PROFILE", "OMP_AUTH_BROKER_URL", "OMP_AUTH_BROKER_TOKEN", "HOME", "PI_PROFILE", "PI_CODING_AGENT_DIR", "PI_CONFIG_DIR", "PI_CONFIG_FILES", "PI_SESSION_DIR", "PI_CODING_AGENT_SESSION_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"})),
      authentication_claims=lambda data: tuple(AuthenticationClaim(provider_id,
        "omp-native-profile" if provider["auth_kind"] == "oauth" else "omp-environment")
        for provider_id, provider in sorted(data["providers"].items())))
    return AdapterSchemas({"omp": bundle})
