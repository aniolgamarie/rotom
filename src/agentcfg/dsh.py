"""锁定 DSH/TUI 配方的真实数据映射；秘密和宿主启动交由公共核心。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .adapter import (Adapter, AdapterDeclaration, Artifact, DependencyPlan,
                      EnvironmentBinding, LaunchSpec, ManagedTarget, Ownership, SecretRef)
from . import native
from .render import render_rules
from .schema import AdapterPolicy, AdapterSchemaBundle, AdapterSchemas, AuthenticationClaim, ConfigError


def closed(properties, required=()):
  return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


STRING = {"type": "string", "minLength": 1}
STRINGS = {"type": "array", "items": STRING, "uniqueItems": True}
BOOL = {"type": "boolean"}
VERSION = {"type": "integer", "const": 1}
SHA = {"type": "string", "minLength": 40, "maxLength": 40, "pattern": "^[a-f0-9]{40}$"}
PROVIDER_OPTIONS = closed({"reasoning": {"type": "string", "enum": ["off", "minimal", "low", "medium", "high", "xhigh", "max"]}, "transport": {"type": "string", "enum": ["sse", "websocket", "websocket-cached", "auto"]},
  "retryPolicy": closed({"mode": {"type": "string", "enum": ["normal", "always"]}, "maxRetries": {"type": "integer", "minimum": 0}}, ("mode",)),
  "timeoutMs": {"type": "integer", "minimum": 1}})
OPTIONS = closed({"preset": {"type": "string", "enum": ["standard"]},
                  "theme": {"type": "string", "enum": ["rotom-poimandres", "auto", "dark", "dark-ansi", "light"]},
                  "terminal_images": BOOL,
                  "cursor_port": {"type": "integer", "minimum": 1024, "maximum": 65535},
                  "provider_options": {"type": "object", "additionalProperties": PROVIDER_OPTIONS}},
                 ("preset", "theme", "terminal_images"))


def env_name(kind, identity):
  return "AGENTCFG_" + kind + "_" + hashlib.sha256(identity.encode()).hexdigest()[:16].upper()


def escaped(value):
  return value.replace("~", "~0").replace("/", "~1")


class DshAdapter(Adapter):
  declaration = AdapterDeclaration("dsh", 1, "dsh-1")
  # 首次空实例部署声明原生会创建此共享文件；不接管任何既有字段。
  shared_files = ("dsh-home/settings.yaml",)

  def __init__(self, repository: Path):
    self.repository = repository

  def dependency_backend(self):
    from .backends import DshBackend
    return DshBackend()

  def route(self, data, provider):
    binding = data["adapter_documents"]["bindings"]
    if data["providers"][provider]["auth_kind"] == "oauth":
      return binding["oauth"][provider]["route"]
    # 私有服务不能隐式继承同名内置 provider 的能力。
    return "agentcfg-" + provider

  def validate(self, data):
    bindings = data["adapter_documents"]["bindings"]
    selected = data["profile"]
    if "tui" not in data["plugins"]:
      raise ConfigError("dsh-tui-required")
    if set(data["plugins"]) - {"tui", "codex-auth", "cursor-auth"}:
      raise ConfigError("plugin-mapping-not-implemented")
    for key, plugin in data["plugins"].items():
      if not plugin["enabled"] or any(p not in data["plugins"] for p in plugin["requires"]):
        raise ConfigError("plugin-dependency")
      if any(p in data["plugins"] for p in plugin["conflicts"]):
        raise ConfigError("plugin-conflict")
    routes = []
    for key, provider in data["providers"].items():
      if provider["auth_kind"] == "oauth":
        expected = {"codex": ("openai-codex", "codex-auth"), "cursor": ("oauth-cursor", "cursor-auth")}
        if key not in expected or (bindings["oauth"].get(key, {}).get("route"), bindings["oauth"].get(key, {}).get("owner")) != expected[key]:
          raise ConfigError("oauth-native-route-mismatch")
        if key not in bindings["oauth"] or bindings["oauth"][key]["owner"] not in data["plugins"]:
          raise ConfigError("oauth-binding")
        if provider["protocol"] != "oauth-dynamic" or "credential_ref" in provider:
          raise ConfigError("oauth-credential")
      elif provider["auth_kind"] == "api-key":
        if provider["protocol"] not in bindings["protocols"] or "credential_ref" not in provider:
          raise ConfigError("api-binding")
      else:
        raise ConfigError("auth-kind")
      routes.append(self.route(data, key))
    if len(routes) != len(set(routes)):
      raise ConfigError("route-conflict")
    if set(selected["roles"]) - {"main"}:
      raise ConfigError("role-unsupported")
    for model in data["models"].values():
      if set(model["input"]) - {"text", "image"}:
        raise ConfigError("model-input")
    if set(selected["agent_options"].get("provider_options", {})) - set(data["providers"]):
      raise ConfigError("provider-options-reference")
    for options in selected["agent_options"].get("provider_options", {}).values():
      retry = options.get("retryPolicy", {})
      if retry.get("mode") == "always" and "maxRetries" in retry:
        raise ConfigError("retry-always-has-no-limit")
    if any(data["providers"][key]["auth_kind"] == "oauth" and options
           for key, options in selected["agent_options"].get("provider_options", {}).items()):
      raise ConfigError("oauth-provider-options-not-supported")
    for server in data["mcp"].values():
      if server["transport"] == "stdio":
        if "command" not in server or "url" in server or "credential_ref" in server:
          raise ConfigError("mcp-stdio-mapping")
      elif server["transport"] in ("http", "streamable-http"):
        if "url" not in server or "command" in server or "args" in server:
          raise ConfigError("mcp-http-mapping")
      else:
        raise ConfigError("mcp-transport")

  def _api_fields(self, data):
    for key, provider in data["providers"].items():
      if provider["auth_kind"] != "api-key":
        continue
      route = self.route(data, key)
      fields = {"apiKeyEnv": env_name("KEY", key), "baseURL": provider["base_url"],
                "api": data["adapter_documents"]["bindings"]["protocols"][provider["protocol"]]}
      models = [{"id": model["remote_id"], "input": model["input"],
                 **({"contextWindow": model["context_window"]} if "context_window" in model else {}),
                 **({"maxTokens": model["max_output_tokens"]} if "max_output_tokens" in model else {})} for model in data["models"].values()
                if model["provider"] == key]
      if models:
        fields["models"] = models
      fields.update(data["profile"]["agent_options"].get("provider_options", {}).get(key, {}))
      for field, value in fields.items():
        yield "/llm-pi-ai/providers/" + escaped(route) + "/" + field, value

  def managed_targets(self, data):
    return (
      ManagedTarget("dsh-home/AGENTS.md", Ownership.FILE, "bytes"),
      ManagedTarget("dsh-home/agentcfg.patch.yml", Ownership.FILE, "bytes"),
      ManagedTarget("dsh-home/skills", Ownership.FILE, "skill-directory"),
      ManagedTarget("env-guard.mjs", Ownership.FILE, "bytes"),
      ManagedTarget("user-home/.dsh-tui/themes/rotom-poimandres.json", Ownership.FILE, "json"),
      *(ManagedTarget("dsh-home/settings.yaml", Ownership.FIELDS, "yaml", path) for path, _ in self._api_fields(data)),
    )

  def render(self, data):
    self.validate(data)
    targets = self.managed_targets(data)
    rules = tuple(data["rules"][key] for key in data["profile"]["rules"])
    result = [Artifact(targets[0], render_rules(self.repository, rules, {}))]
    base = native.load((self.repository / "agents/dsh/templates/tui.yaml").read_bytes())
    main = data["profile"]["roles"].get("main")
    provider = data["models"][main]["provider"] if main else next(iter(data["providers"]), None)
    config = {"terminalImages": data["profile"]["agent_options"]["terminal_images"]}
    if provider:
      config["provider"] = self.route(data, provider)
    if main:
      config["model"] = data["models"][main]["remote_id"]
    codex_enabled = data["providers"].get("codex", {}).get("auth_kind") == "oauth" and "codex-auth" in data["plugins"]
    patch = [native.replace_config(base, "dsh-tui", config), {"id": "llm-deepseek", "disabled": True},
             {"id": "dsh-tui-auth", "disabled": not codex_enabled, "config": {"providers": ["openai-codex"]}}]
    inserts = []
    for key, server in data["mcp"].items():
      conf = {"serverName": key}
      if server["transport"] == "stdio":
        conf.update(transport="stdio", command=server["command"], args=server.get("args", []))
      else:
        conf["transport"] = "streamable-http"
        conf["url"] = server["url"]
        if "credential_ref" in server:
          conf["headers"] = {"Authorization": native.JS("process.env." + env_name("MCP", key))}
      inserts.append({"id": "agentcfg-mcp-" + key, "name": "@deepseek-ai/dsh-mcp-client", "config": conf})
    if "cursor-auth" in data["plugins"] and data["providers"].get("cursor", {}).get("auth_kind") == "oauth":
      private_data = Path(data["machine"]["paths"]["instances_root"]) / "dsh" / data["profile"]["id"] / "dsh-home/oauth-subs"
      inserts.append({"id": "agentcfg-cursor-auth", "name": "dsh-plugin-oauth-subs",
                      "config": {"provider": "oauth", "port": data["profile"]["agent_options"].get("cursor_port", 8318), "dataDir": str(private_data)}})
    if inserts:
      patch.append({"insert": inserts})
    result.append(Artifact(targets[1], native.dump(patch)))
    result.append(Artifact(ManagedTarget("env-guard.mjs", Ownership.FILE, "bytes"),
      (self.repository / "agents/dsh/templates/env-guard.mjs").read_bytes()))
    result.append(Artifact(ManagedTarget("user-home/.dsh-tui/themes/rotom-poimandres.json", Ownership.FILE, "json"),
      (self.repository / "agents/dsh/templates/theme.json").read_bytes()))
    result.extend(Artifact(ManagedTarget("dsh-home/settings.yaml", Ownership.FIELDS, "yaml", path),
                           json.dumps(value, ensure_ascii=False).encode()) for path, value in self._api_fields(data))
    return tuple(result)

  def dependency_plan(self, data):
    return DependencyPlan(tuple(p["package"] + "@" + p["version"] for p in data["plugins"].values() if not p["bundled"]))

  def launch_spec(self, data, *, cwd, runtime_root, instance_root, lock_identity):
    environment = [EnvironmentBinding("DSH_HOME", str(instance_root / "dsh-home")),
      EnvironmentBinding("HOME", str(instance_root / "user-home")),
      EnvironmentBinding("DSH_TUI_PRESET", data["profile"]["agent_options"]["preset"]),
      EnvironmentBinding("DSH_TUI_THEME", data["profile"]["agent_options"]["theme"]),
      EnvironmentBinding("DSH_PERMISSION_MODE", "workspace-write"),
      EnvironmentBinding("DSH_TELEMETRY_DISABLED", "1")]
    if not data["profile"]["agent_options"]["terminal_images"]:
      environment.append(EnvironmentBinding("DSH_TUI_DISABLE_TERMINAL_IMAGES", "1"))
    for key, provider in data["providers"].items():
      if provider["auth_kind"] == "api-key":
        environment.append(EnvironmentBinding(env_name("KEY", key), SecretRef(provider["credential_ref"])))
    for key, server in data["mcp"].items():
      if "credential_ref" in server:
        environment.append(EnvironmentBinding(env_name("MCP", key), SecretRef(server["credential_ref"])))
    return LaunchSpec(("node", "--import", str(instance_root / "env-guard.mjs"),
                       str(runtime_root / "node_modules/@deepseek-ai/dsh/lib/bin.js"),
                       "--profile", "agentcfg", "--patch", str(instance_root / "dsh-home/agentcfg.patch.yml")),
                      cwd, lock_identity, tuple(environment))

  def launch_preflight(self, lock):
    return [{"argv": ["node", "--version"], "version": lock.metadata["node"]}]

  def prepare_runtime(self, workspace, root):
    from .profile_runtime import prepare
    from .storage import ensure_private
    for relative in ("user-home", "dsh-home", "dsh-home/oauth-subs"):
      ensure_private(workspace.instance / relative)
    prepare(workspace, root)

  def capture_projection(self, tree):
    from .deployment import parse_native
    projection = {}
    raw = tree.read("dsh-home/settings.yaml")
    if raw:
      section = parse_native(raw[0], "yaml").get("dsh-tui", {})
      if isinstance(section, dict) and type(section.get("terminalImages")) is bool:
        projection["terminal_images"] = section["terminalImages"]
    for name, keys in (("theme", ("theme",)), ("model", ("provider", "model"))):
      raw = tree.read("user-home/.dsh-tui/" + name + ".json")
      if raw:
        try:
          value = json.loads(raw[0])
          if not isinstance(value, dict) or any(not isinstance(value.get(key), str) or not value[key] for key in keys):
            raise ValueError()
          projection[name] = {key: value[key] for key in keys}
        except (ValueError, TypeError):
          raise ConfigError("capture-invalid-native-preference") from None
    return projection

  def capture(self, projection):
    options = {key: value for key, value in projection.items() if key == "terminal_images"}
    if "theme" in projection:
      theme = projection["theme"]["theme"]
      if theme not in OPTIONS["properties"]["theme"]["enum"]:
        raise ConfigError("capture-theme-not-supported")
      options["theme"] = theme
    return {"agent_options": options}

  def capture_configuration(self, projection, data):
    result = self.capture(projection)
    if "model" in projection:
      route = projection["model"]
      matches = [key for key, model in data["models"].items()
                 if self.route(data, model["provider"]) == route["provider"] and model["remote_id"] == route["model"]]
      if len(matches) != 1:
        raise ConfigError("capture-model-not-uniquely-declared: 先在本地配置声明并选择该模型，再 capture")
      result["roles"] = {"main": matches[0]}
    return result

  def doctor(self, projection):
    return ("oauth-status-owned-by-native-plugin", "native-user-preferences-isolated")

  def schemas(self):
    defaults = closed({**{key: STRINGS for key in ("providers", "models", "rules", "skills", "plugins", "mcp")},
                       "agent_options": OPTIONS})
    plugin = closed({"package": STRING, "version": STRING, "commit": SHA, "bundled": BOOL,
                     "enabled": BOOL, "requires": STRINGS, "conflicts": STRINGS},
                    ("package", "version", "bundled", "enabled", "requires", "conflicts"))
    documents = {
      "agent": closed({"schema_version": VERSION, "adapter_version": STRING, "upstream_commit": SHA,
                        "tui_commit": SHA, "defaults": defaults},
                       ("schema_version", "adapter_version", "upstream_commit", "tui_commit", "defaults")),
      "bindings": closed({"schema_version": VERSION, "settings_namespace": {"type": "string", "const": "llm-pi-ai"}, "credential_field": {"type": "string", "const": "apiKeyEnv"},
                           "protocols": {"type": "object", "additionalProperties": {"type": "string", "enum": ["openai-completions", "openai-responses"]}},
                           "oauth": {"type": "object", "additionalProperties": closed({"route": STRING, "owner": STRING}, ("route", "owner"))}},
                          ("schema_version", "settings_namespace", "credential_field", "protocols", "oauth")),
      "plugins": closed({"schema_version": VERSION, "plugins": {"type": "object", "additionalProperties": plugin}}, ("schema_version", "plugins")),
    }
    bundle = AdapterSchemaBundle(self.declaration, documents, OPTIONS,
      lambda kind, value: self.validate(value) if kind == "resolved" else None,
      policy=lambda docs: AdapterPolicy(deepcopy(docs["agent"]["defaults"]), deepcopy(docs["plugins"]["plugins"]), frozenset()),
      authentication_claims=lambda data: tuple(AuthenticationClaim(key,
        data["adapter_documents"]["bindings"]["oauth"][key]["owner"] if value["auth_kind"] == "oauth" else "api-key")
        for key, value in data["providers"].items()))
    return AdapterSchemas({"dsh": bundle})
