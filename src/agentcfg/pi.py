"""Pi的严格原生映射；渲染只读可信来源，安装与启动由公共命令执行。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

import yaml

from .adapter import Adapter, AdapterDeclaration, Artifact, DependencyPlan, EnvironmentBinding, LaunchSpec, ManagedTarget, Ownership, SecretRef
from .pi_catalog import read_schema, validate as check, validate_policy, validate_resources
from .render import render_rules
from .schema import AdapterPolicy, AdapterSchemaBundle, AdapterSchemas, AuthenticationClaim, ConfigError, validate_document
from .storage import Tree, ensure_private
from .paths import configured_path


def closed(properties, required=()):
  return {"type": "object", "properties": properties, "required": list(required), "additionalProperties": False}


def encode(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


def pointer(*parts):
  return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def key_variable(provider):
  return "AGENTCFG_PI_CREDENTIAL_" + hashlib.sha256(provider.encode()).hexdigest()[:16].upper()


def route_key_variable(route):
  return "AGENTCFG_PI_ROUTE_CREDENTIAL_" + hashlib.sha256(route.encode()).hexdigest()[:16].upper()


class PiAdapter(Adapter):
  declaration = AdapterDeclaration("pi", 1, "pi-1")
  shared_files = ("pi-home/settings.json", "pi-home/models.json")

  def __init__(self, repository):
    self.repository = Path(repository)

  def dependency_backend(self):
    from .pi_dependencies import PiBackend
    return PiBackend()

  def route(self, data, provider_id):
    provider = data["providers"][provider_id]
    if provider["auth_kind"] == "oauth":
      return data["adapter_documents"]["bindings"]["oauth"][provider_id]["route"]
    return "agentcfg-" + provider_id

  def validate(self, data):
    profile = data["profile"]
    options = profile["agent_options"]
    check("options", options)
    validate_document("registry", {"schema_version": 1, **{key: data[key] for key in ("providers", "models", "rules", "skills", "mcp")}})
    if profile["agent"] != "pi" or set(profile["roles"].values()) - data["models"].keys():
      raise ConfigError("pi-model-reference")
    if set(profile["plugins"]) != data["plugins"].keys():
      raise ConfigError("pi-plugin-selection")
    engine = options.get("runtime", {}).get("engine", "node")
    for plugin in data["plugins"].values():
      if (not plugin["enabled"] or engine not in plugin["engines"]
          or set(plugin["requires"]) - data["plugins"].keys()
          or set(plugin["conflicts"]) & data["plugins"].keys()):
        raise ConfigError("pi-plugin-combination")
    from .pi_mcp import configuration as mcp_configuration
    mcp_configuration(data)
    from .pi_web import configuration as web_configuration
    web_configuration(data)
    bindings = data["adapter_documents"]["bindings"]
    for identity, provider in data["providers"].items():
      if provider["auth_kind"] == "api-key":
        if provider["protocol"] not in bindings["protocols"] or not provider.get("base_url") or not provider.get("credential_ref"):
          raise ConfigError("pi-provider-binding")
      elif provider["auth_kind"] == "oauth":
        owner = bindings["oauth"].get(identity)
        if (not owner or provider["protocol"] != "oauth-dynamic" or "base_url" in provider or "credential_ref" in provider
            or (owner["owner"] != "pi-native" and owner["owner"] not in data["plugins"])):
          raise ConfigError("pi-authentication-owner")
      else:
        raise ConfigError("pi-auth-kind")
    for model in data["models"].values():
      if model["provider"] not in data["providers"] or set(model["input"]) - {"text", "image"}:
        raise ConfigError("pi-model-capability")
    if set(options.get("model_settings", {})) - data["models"].keys():
      raise ConfigError("pi-model-settings-reference")
    if any(data["providers"][data["models"][name]["provider"]]["auth_kind"] != "api-key" for name in options.get("model_settings", {})):
      raise ConfigError("pi-model-settings-native-owner")
    for settings in options.get("model_settings", {}).values():
      if set(settings.get("thinking_level_map", {})) & set(settings.get("disabled_thinking_levels", [])):
        raise ConfigError("pi-thinking-level-conflict")
    native_models = [(self.route(data, model["provider"]), model["remote_id"]) for model in data["models"].values()]
    if len(native_models) != len(set(native_models)):
      raise ConfigError("pi-model-mapping-ambiguous")
    shortcut = options.get("todo", {}).get("collapseKey")
    if shortcut is not None and shortcut != "off":
      parts = shortcut.split("+"); modifiers, key = parts[:-1], parts[-1]
      names = {"escape", "esc", "enter", "return", "tab", "space", "backspace", "delete", "insert", "clear", "home", "end", "pageup", "pagedown", "up", "down", "left", "right", *["f" + str(number) for number in range(1, 25)]}
      if (shortcut != shortcut.strip().lower() or len(set(modifiers)) != len(modifiers) or set(modifiers) - {"ctrl", "shift", "alt", "super"}
          or key not in names and not (len(key) == 1 and key.isascii() and (key.isalnum() or key in "_-!@#$%^&*()|~`'\":;,./<>?[]{}=\\"))):
        raise ConfigError("pi-todo-shortcut")
    declaration = data["adapter_documents"]["agent"]
    resources = declaration["resources"]
    allowed_roles = {"main", "second_view"} | {item["model_role"] for item in resources.values() if item["kind"] == "role"}
    if set(profile["roles"]) - allowed_roles:
      raise ConfigError("pi-role-reference")
    if "git-checkpoint" in options.get("resources", {}).get("extensions", []):
      if "pi-subagents" not in data["plugins"] or not options.get("checkpoints", {}).get("paths"):
        raise ConfigError("pi-checkpoint-binding-required")
    if "dirty-repo-guard" in options.get("resources", {}).get("extensions", []):
      from .pi_git_status import validate_binding
      if "pi-subagents" not in data["plugins"]:
        raise ConfigError("pi-git-status-manager-required")
      validate_binding(options)
    if "gentle-agent-state" in options.get("resources", {}).get("extensions", []):
      from .pi_services import validate_report_binding
      binding = validate_report_binding(options)
      if binding["mode"] == "service" and "pi-subagents" not in data["plugins"]:
        raise ConfigError("pi-agent-state-manager-required")
    if "pi-slopchop" in data["plugins"]:
      from .pi_git_status import validate_binding
      if not options.get("slopchop", {}).get("git_tool_ref"):
        raise ConfigError("pi-git-review-binding-required")
      validate_binding(options, name=options["slopchop"]["git_tool_ref"])
    if "pi-rules" in data["plugins"]:
      from .pi_rules import validate_rules
      validate_rules(options)
    targets = set()
    for kind, names in options.get("resources", {}).items():
      expected = {"roles": "role", "prompts": "prompt", "themes": "theme", "extensions": "extension"}[kind]
      if any(name not in resources or resources[name]["kind"] != expected for name in names):
        raise ConfigError("pi-resource-reference")
      for name in names:
        resource = resources[name]
        target = (kind, Path(resource["path"]).name)
        if resource["scope"] == "global" and target in targets:
          raise ConfigError("pi-resource-conflict")
        if resource["scope"] == "global":
          targets.add(target)
        if resource["scope"] == "project" and not options.get("discovery", {}).get("project_resources"):
          raise ConfigError("pi-project-resource-disabled")
        if resource.get("override", "").startswith("task-keeper-"):
          raise ConfigError("pi-managed-role-conflict")
        if resource["scope"] == "project" and resource["kind"] == "role" and (resource["model_role"].startswith("task_keeper_") or name.startswith("task-keeper-")):
          raise ConfigError("pi-managed-role-conflict")
    from urllib.parse import urlsplit
    codex = options.get("model_delegate", {}).get("codex", {})
    if "api_base_url" in codex:
      from .pi_delegate_policy import codex_api_base_url
      codex_api_base_url(codex["api_base_url"])
    for route in options.get("network", {}).get("routes", {}).values():
      services = set(route.get("service_ids", []))
      selected_services = {"mcp:" + name for name in data["mcp"]}
      selected_services |= {"web:" + name for name in options.get("web", {}).get("services", {})}
      if (not route["provider_ids"] and not services or set(route["provider_ids"]) - data["providers"].keys()
          or services - selected_services):
        raise ConfigError("pi-network-provider-reference")
      if route["mode"] == "direct":
        if "proxy_url" in route or "credential_ref" in route:
          raise ConfigError("pi-direct-route-fields")
      else:
        try:
          proxy = urlsplit(route.get("proxy_url", ""))
          valid = proxy.scheme in ("http", "https") and proxy.hostname and not proxy.username and not proxy.password and not proxy.query and not proxy.fragment and proxy.path in ("", "/")
          port = proxy.port
        except ValueError:
          valid = False
        if not valid:
          raise ConfigError("pi-proxy-route")
    if "pi-cursor" in data["plugins"]:
      cursor = options.get("cursor", {})
      route = options.get("network", {}).get("routes", {}).get(cursor.get("network_route"))
      endpoint = urlsplit(cursor.get("endpoint", ""))
      if (not route or route["mode"] != "direct" or "cursor" not in route["provider_ids"]
          or endpoint.scheme != "https" or not endpoint.hostname or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment or endpoint.path not in ("", "/")
          or not (endpoint.hostname in ("cursor.sh", "cursor.com") or endpoint.hostname.endswith((".cursor.sh", ".cursor.com")))):
        raise ConfigError("pi-cursor-direct-binding-required")
    theme = options.get("ui", {}).get("theme")
    if theme and theme not in options.get("resources", {}).get("themes", []):
      raise ConfigError("pi-theme-selection")
    owner = options.get("compaction", {}).get("owner", "native")
    if (owner == "smart-compact") != ("pi-smart-compact" in data["plugins"]):
      raise ConfigError("pi-compaction-owner-conflict")
    if owner == "smart-compact" and options.get("smart_compact", {}).get("autoTriggerStrategy", "settled") != "settled":
      raise ConfigError("pi-compaction-trigger-conflict")
    if "openai-proxy" in data["plugins"]:
      routes = options.get("network", {}).get("routes", {})
      route = routes.get(options.get("network", {}).get("openai_proxy_route"))
      if not route or route["mode"] != "proxy":
        raise ConfigError("pi-openai-proxy-route-required")
    allowed_helpers = {self.route(data, row["provider"]) + "/" + row["remote_id"] for row in data["models"].values()}
    helper_models = [options.get("btw", {}).get("model"), options.get("mcp", {}).get("sampling", {}).get("model"),
      *[options.get("smart_compact", {}).get(key) for key in ("summaryModel", "segmentationModel", "verificationModel")]]
    if any(model is not None and model not in allowed_helpers for model in helper_models):
      raise ConfigError("pi-helper-model-unbound")
    for name in options.get("discovery", {}).get("external_skills", []):
      if name not in declaration.get("external_skills", {}):
        raise ConfigError("pi-external-skill-reference")
    policy = options.get("permissions", {}).get("policy_ref")
    if policy and policy not in declaration.get("policies", {}):
      raise ConfigError("pi-policy-reference")
    if options.get("diagnostics"):
      from .pi_evidence import evidence_path
      configured_path(options["diagnostics"]["evidence_root"])
      for path in options["diagnostics"]["evidence_paths"]: evidence_path(path)
    roots = options.get("paths", {}).get("roots", {})
    limits = options.get("permissions", {})
    if (set(limits.get("readonly_roots", [])) | set(limits.get("denied_roots", []))) - (set(roots) | {"project"}):
      raise ConfigError("pi-permission-root-reference")
    for rule in declaration.get("policies", {}).get(policy, {}).get("rules", []):
      if rule["kind"] == "file" and rule["root_ref"] not in set(roots) | {"project"}:
        raise ConfigError("pi-permission-root-reference")
      if rule["kind"] == "command":
        kind, name = rule["command_ref"].split(":", 1)
        if name not in options.get("checks" if kind == "check" else "external_tools", {}):
          raise ConfigError("pi-permission-command-reference")
    if any(binding["project_root"] not in roots or set(binding.get("read_roots", [])) - roots.keys() for binding in options.get("checks", {}).values()):
      raise ConfigError("pi-check-root-reference")
    if options.get("task_keeper", {}).get("enabled") and engine != "node":
      raise ConfigError("pi-managed-engine")

  def validate_selected(self, data):
    self.validate(data)
    options = data["profile"]["agent_options"]
    if data["profile"]["roles"].get("main"):
      declarations = data["adapter_documents"]["agent"]["resources"]
      if any(declarations[name]["model_role"] not in data["profile"]["roles"] for name in options.get("resources", {}).get("roles", [])):
        raise ConfigError("pi-role-model-unbound")
    task = options.get("task_keeper", {})
    if task.get("enabled"):
      required = {"task_keeper_reader", "task_keeper_writer", "task_keeper_reviewer"}
      if task.get("second_view_enabled"):
        required.add("second_view")
      if required - data["profile"]["roles"].keys() or "task-keeper" not in data["plugins"]:
        raise ConfigError("pi-managed-role-binding")
      limits = task.get("limits", {})
      if "cost_limit" in limits:
        raise ConfigError("pi-managed-cost-bound-unavailable")
      if "token_limit" in limits and any(not all(key in data["models"][data["profile"]["roles"][role]]
          for key in ("context_window", "max_output_tokens")) for role in required):
        raise ConfigError("pi-managed-token-bound-unavailable")
      if not task.get("check_ids") or set(task["check_ids"]) - options.get("checks", {}).keys():
        raise ConfigError("pi-managed-check-binding")
      if any(options["checks"][name]["project_root"] != task.get("project_root") for name in task["check_ids"]):
        raise ConfigError("pi-managed-check-project")
      if any({"kind", "parser", "minimum_tests", "inputs"} - options["checks"][name].keys() for name in task["check_ids"]):
        raise ConfigError("pi-managed-check-result-contract")
      if any(options["checks"][name]["kind"] == "tests" and options["checks"][name]["parser"] == "exit-code" for name in task["check_ids"]):
        raise ConfigError("pi-managed-test-count-required")
      if task.get("project_root") not in options.get("paths", {}).get("roots", {}):
        raise ConfigError("pi-managed-project-binding")
    for name in options.get("discovery", {}).get("external_skills", []):
      if not options.get("external_skills", {}).get(name, {}).get("path"):
        raise ConfigError("pi-external-skill-binding")
      configured_path(options["external_skills"][name]["path"])

  def _fields(self, data):
    options = data["profile"]["agent_options"]
    settings = {"packages": [], "skills": [], "extensions": [], "prompts": [], "themes": []}
    for source, native in (("quiet_startup", "quietStartup"), ("hide_thinking", "hideThinkingBlock")):
      if source in options.get("ui", {}):
        settings[native] = options["ui"][source]
    theme = options.get("ui", {}).get("theme")
    if theme:
      settings["theme"] = Path(data["adapter_documents"]["agent"]["resources"][theme]["path"]).stem
    main = data["profile"]["roles"].get("main")
    if main:
      model = data["models"][main]
      settings.update(defaultProvider=self.route(data, model["provider"]), defaultModel=model["remote_id"])
    for name, value in settings.items():
      yield ManagedTarget("pi-home/settings.json", Ownership.FIELDS, "json", pointer(name)), value
    for identity, provider in data["providers"].items():
      if provider["auth_kind"] != "api-key":
        continue
      route = self.route(data, identity)
      prefix = ("providers", route)
      values = {"baseUrl": provider["base_url"], "api": data["adapter_documents"]["bindings"]["protocols"][provider["protocol"]]}
      models = []
      for model_id, model in data["models"].items():
        if model["provider"] != identity:
          continue
        native = {"id": model["remote_id"], "input": model["input"]}
        for key, target in (("context_window", "contextWindow"), ("max_output_tokens", "maxTokens")):
          if key in model:
            native[target] = model[key]
        native_options = options.get("model_settings", {}).get(model_id, {})
        for key, target in (("reasoning", "reasoning"), ("thinking_level_map", "thinkingLevelMap")):
          if key in native_options:
            native[target] = deepcopy(native_options[key])
        if "disabled_thinking_levels" in native_options:
          native.setdefault("thinkingLevelMap", {}).update({level: None for level in native_options["disabled_thinking_levels"]})
        models.append(native)
      values["models"] = models
      for name, value in values.items():
        yield ManagedTarget("pi-home/models.json", Ownership.FIELDS, "json", pointer(*prefix, name)), value
      token = "$" + key_variable(identity)
      yield ManagedTarget("pi-home/models.json", Ownership.FIELDS, "json", pointer(*prefix, "apiKey"), (token,)), token

  def _resources(self, data):
    declarations = data["adapter_documents"]["agent"]["resources"]
    for group, ids in data["profile"]["agent_options"].get("resources", {}).items():
      for identity in ids:
        resource = declarations[identity]
        if resource["scope"] == "project":
          continue
        if resource["kind"] == "role" and resource["model_role"] not in data["profile"]["roles"]:
          continue
        directory = {"roles": "agents", "themes": "themes", "prompts": "prompts", "extensions": "extensions"}[group]
        name = Path(resource["path"]).name
        yield identity, resource, ManagedTarget("pi-home/" + directory + "/" + name, Ownership.FILE, "bytes")

    options = data["profile"]["agent_options"]
    if options.get("task_keeper", {}).get("second_view_enabled") and "second_view" in data["profile"]["roles"]:
      resource = {**declarations["task-keeper-reviewer"], "model_role": "second_view"}
      yield "task-keeper-second-view", resource, ManagedTarget("pi-home/agents/task-keeper-second-view.md", Ownership.FILE, "bytes")

  def managed_targets(self, data):
    self.validate(data)
    fixed = [ManagedTarget("pi-home/agentcfg-manifest.json", Ownership.FILE, "json"),
      ManagedTarget("pi-home/AGENTS.md", Ownership.FILE, "text"),
      ManagedTarget("pi-home/APPEND_SYSTEM.md", Ownership.FILE, "text"),
      ManagedTarget("pi-home/keybindings.json", Ownership.INITIALIZE, "json"),
      ManagedTarget("pi-home/subagents.json", Ownership.FILE, "json"),
      ManagedTarget("pi-home/agentcfg-runtime-api.mjs", Ownership.FILE, "text"),
      ManagedTarget("pi-home/skills", Ownership.FILE, "skill-directory"),
      ManagedTarget(".agentcfg-instance.json", Ownership.RUNTIME, "json"),
      *[ManagedTarget(path, Ownership.RUNTIME, "native") for path in ("pi-home/auth.json", "pi-home/sessions", "pi-home/task-keeper", "codex-home", "cursor-home", "pi-home/cursor-cache")],
      ManagedTarget("runtimes", Ownership.PACKAGE, "npm")]
    return tuple(fixed + [target for target, _ in self._fields(data)] + [target for _, _, target in self._resources(data)])

  def render(self, data):
    self.validate(data)
    artifacts = [Artifact(target, encode(value)) for target, value in self._fields(data)]
    resource_paths = {key: [] for key in ("roles", "prompts", "themes", "extensions", "skills")}
    resource_ids = {key: {} for key in resource_paths}
    for identity, resource, target in self._resources(data):
      with Tree(self.repository, private=False) as tree:
        raw = tree.read(resource["path"])
      if raw is None:
        raise ConfigError("pi-resource-missing")
      content = raw[0]
      if resource["kind"] == "extension":
        from .pi_extension_bridge import extension_source
        content = extension_source(content)
      if resource["kind"] == "role":
        model = data["models"][data["profile"]["roles"][resource["model_role"]]]
        # 只继承角色正文，原生frontmatter全部从明确配置序列化，避免旧模型/权限残留。
        text = content.decode("utf-8")
        body = text.split("---", 2)[-1].lstrip() if text.startswith("---\n") else text
        header = {"name": identity, "description": "Managed role " + identity,
          "model": self.route(data, model["provider"]) + "/" + model["remote_id"],
          "tools": ", ".join(resource["tools"]), "extensions": False, "skills": False,
          "inherit_context": False, "prompt_mode": "replace", "allowed_subagents": False,
          "memory": False, "persist_session": False, "isolation": "off"}
        if "thinking" in resource:
          header["thinking"] = resource["thinking"]
        content = ("---\n" + yaml.safe_dump(header, sort_keys=True, allow_unicode=True) + "---\n\n" + body).encode()
      artifacts.append(Artifact(target, content))
      group = {"role": "roles", "prompt": "prompts", "theme": "themes", "extension": "extensions"}[resource["kind"]]
      resource_paths[group].append(target.path)
      resource_ids[group][identity] = target.path
    resource_paths["skills"] = ["pi-home/skills/" + identity for identity in data["profile"]["skills"]]
    resource_ids["skills"] = {identity: "pi-home/skills/" + identity for identity in data["profile"]["skills"]}
    options = deepcopy(data["profile"]["agent_options"])
    for binding in options.get("paths", {}).get("roots", {}).values():
      binding["path"] = str(configured_path(binding["path"]))
    for binding in options.get("checks", {}).values():
      binding["executable"] = str(configured_path(binding["executable"]))
    for binding in options.get("external_tools", {}).values():
      binding["executable"] = str(configured_path(binding["executable"]))
    if "pi-web" in data["plugins"]:
      from .pi_web import protected_browser_roots
      browser_roots = protected_browser_roots(options)
      if browser_roots:
        permissions = options.setdefault("permissions", {})
        permissions["denied_roots"] = sorted(set(permissions.get("denied_roots", [])) | set(browser_roots))
    declarations = data["adapter_documents"]["agent"]["resources"]
    project = [{"id": identity, "kind": group, "path": declarations[identity]["path"],
      **({"override": declarations[identity]["override"]} if "override" in declarations[identity] else {})}
      for group, ids in options.get("resources", {}).items() for identity in ids if declarations[identity]["scope"] == "project"
      and (group != "roles" or declarations[identity]["model_role"] in data["profile"]["roles"])]
    manifest = {"schema_version": 1, "adapter_version": self.declaration.adapter_version,
      "profile_id": data["profile"]["id"], "bootstrap": not bool(data["profile"]["roles"].get("main")),
      "engine": options.get("runtime", {}).get("engine", "node"), "resources": resource_paths, "resource_ids": resource_ids,
      "plugins": list(data["plugins"]), "options": options,
      "provider_bindings": {self.route(data, identity): {"logical_id": identity, "auth_kind": provider["auth_kind"],
        "owner": data["adapter_documents"]["bindings"]["oauth"][identity]["owner"] if provider["auth_kind"] == "oauth" else "pi-environment"}
        for identity, provider in data["providers"].items()},
      "permission_policy": deepcopy(data["adapter_documents"]["agent"]["policies"].get(options.get("permissions", {}).get("policy_ref"))),
      "bootstrap_plugins": sorted({data["adapter_documents"]["bindings"]["oauth"][identity]["owner"]
        for identity, provider in data["providers"].items() if provider["auth_kind"] == "oauth"
        and data["adapter_documents"]["bindings"]["oauth"][identity]["owner"] != "pi-native"}),
      "project_resources": project,
      "external_skills": [{"id": identity, "root": str(configured_path(options["external_skills"][identity]["path"]).parent),
        "path": configured_path(options["external_skills"][identity]["path"]).name}
        for identity in options.get("discovery", {}).get("external_skills", [])],
      "allowed_models": [{"provider": self.route(data, model["provider"]), "model": model["remote_id"]} for model in data["models"].values()],
      "model_bindings": {role: {"provider": self.route(data, data["models"][model]["provider"]), "model": data["models"][model]["remote_id"]}
        for role, model in data["profile"]["roles"].items()}}
    from .pi_mcp import configuration as mcp_configuration
    if "pi-mcp" in data["plugins"]: manifest["mcp_config"] = mcp_configuration(data)
    if "pi-web" in data["plugins"]:
      from .pi_web import configuration as web_configuration
      manifest.update(web_configuration(data))
    if "openai-proxy" in data["plugins"]:
      manifest["bootstrap_plugins"] = sorted(set(manifest["bootstrap_plugins"]) | {"openai-proxy"})
    if ("model-delegate" in data["plugins"] and "codex" in options.get("model_delegate", {}).get("backends", [])):
      manifest["bootstrap_plugins"] = sorted(set(manifest["bootstrap_plugins"]) | {"model-delegate"})
    manifest["role_bindings"] = {declarations[identity].get("override", identity): {"model": manifest["model_bindings"][declarations[identity]["model_role"]],
      "tools": declarations[identity]["tools"], "read_roots": declarations[identity]["read_roots"],
      "write_roots": declarations[identity]["write_roots"],
      **({"thinking": declarations[identity]["thinking"]} if "thinking" in declarations[identity] else {}), "managed": declarations[identity]["model_role"].startswith("task_keeper_")}
      for identity in sorted(options.get("resources", {}).get("roles", []), key=lambda name: declarations[name]["scope"] == "project")
      if declarations[identity]["model_role"] in manifest["model_bindings"]}
    if options.get("task_keeper", {}).get("second_view_enabled") and "second_view" in manifest["model_bindings"]:
      base = declarations["task-keeper-reviewer"]
      manifest["role_bindings"]["task-keeper-second-view"] = {"model": manifest["model_bindings"]["second_view"],
        "tools": base["tools"], "read_roots": base["read_roots"], "write_roots": [], "managed": True}
    subagents = {"disableDefaultAgents": True, "fallbackSubagent": "none", "maxSubagentDepth": 0,
      "maxConcurrent": 2, "maxConcurrentForeground": 2, "workflowsEnabled": False,
      "schedulingEnabled": False, "worktreeIsolation": False, "strictAgentFiles": True}
    with Tree(self.repository, private=False) as tree:
      templates = {name: tree.read("agents/pi/templates/" + name) for name in ("AGENTS.template.md", "APPEND_SYSTEM.template.md", "keybindings.template.jsonc")}
    if not all(templates.values()):
      raise ConfigError("pi-template-missing")
    # 此输入为仓库固定 JSONC，逐行注释被移除；不接受用户原生文件作为模板。
    keybindings = json.loads("\n".join(line for line in templates["keybindings.template.jsonc"][0].decode().splitlines() if not line.lstrip().startswith("//")))
    rules = render_rules(self.repository, tuple(data["rules"][key] for key in data["profile"]["rules"]), {})
    from .pi_extension_bridge import bridge_source
    artifacts.append(Artifact(ManagedTarget("pi-home/agentcfg-runtime-api.mjs", Ownership.FILE, "text"), bridge_source()))
    artifacts.extend((Artifact(ManagedTarget("pi-home/agentcfg-manifest.json", Ownership.FILE, "json"), encode(manifest)),
      Artifact(ManagedTarget("pi-home/subagents.json", Ownership.FILE, "json"), encode(subagents)),
      Artifact(ManagedTarget("pi-home/keybindings.json", Ownership.INITIALIZE, "json"), encode(keybindings)),
      Artifact(ManagedTarget("pi-home/APPEND_SYSTEM.md", Ownership.FILE, "text"), templates["APPEND_SYSTEM.template.md"][0]),
      Artifact(ManagedTarget("pi-home/AGENTS.md", Ownership.FILE, "text"), rules + b"\n" + templates["AGENTS.template.md"][0])))
    return tuple(artifacts)

  def dependency_plan(self, data):
    return DependencyPlan(tuple(plugin["package"] + "@" + plugin["version"] for plugin in data["plugins"].values()))

  def lifecycle_guard(self, workspace):
    from .pi_lifecycle import guard
    return guard(workspace)

  def launch_executor(self):
    from .pi_host import execute
    return execute

  def launch_spec(self, data, *, cwd, runtime_root, instance_root, lock_identity):
    self.validate_selected(data)
    engine = data["profile"]["agent_options"].get("runtime", {}).get("engine", "node")
    env = [EnvironmentBinding("HOME", str(instance_root / "user-home")),
      EnvironmentBinding("PI_CODING_AGENT_DIR", str(instance_root / "pi-home")),
      EnvironmentBinding("PI_CODING_AGENT_SESSION_DIR", str(instance_root / "pi-home/sessions"))]
    if "codex" in data["profile"]["agent_options"].get("model_delegate", {}).get("backends", []):
      env.append(EnvironmentBinding("CODEX_HOME", str(instance_root / "codex-home")))
    if "pi-cursor" in data["plugins"]:
      # Cursor 原生账号只属于本实例；关闭系统 Keychain/IDE/CLI 复用和环境令牌旁路。
      env.extend(EnvironmentBinding(name, value) for name, value in {
        "CURSOR_CONFIG_DIR": str(instance_root / "cursor-home"),
        "PI_CURSOR_CACHE_DIR": str(instance_root / "pi-home/cursor-cache"),
        "PI_CURSOR_SYSTEM_CREDENTIALS": "deny", "CURSOR_ACCESS_TOKEN": "",
        "PI_CURSOR_AGENT_URL": data["profile"]["agent_options"]["cursor"]["endpoint"], "CURSOR_AGENT_URL": "",
        "PI_CURSOR_PROVIDER_DEBUG": "0", "PI_CURSOR_STREAM_IDLE_MAX_RETRIES": "0",
        "PI_CURSOR_LIFECYCLE_LOG": str(instance_root / "pi-home/cursor-cache/lifecycle.jsonl"),
        "PI_CURSOR_PROVIDER_DEBUG_FILE": str(instance_root / "pi-home/cursor-cache/provider.log"),
        "PI_CURSOR_PROVIDER_EXTENSION_DEBUG_FILE": str(instance_root / "pi-home/cursor-cache/extension.log"),
        "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "", "NO_PROXY": "",
        "http_proxy": "", "https_proxy": "", "all_proxy": "", "no_proxy": "",
      }.items())
    for key, provider in data["providers"].items():
      if provider["auth_kind"] == "api-key":
        env.append(EnvironmentBinding(key_variable(key), SecretRef(provider["credential_ref"])))
    for key, service in data["mcp"].items():
      if service.get("credential_ref"):
        env.append(EnvironmentBinding(key_variable("mcp:" + key), SecretRef(service["credential_ref"])))
    from .pi_web import environment_bindings as web_environment_bindings
    env.extend(web_environment_bindings(data))
    for route, binding in data["profile"]["agent_options"].get("network", {}).get("routes", {}).items():
      if binding.get("credential_ref") and (set(binding.get("provider_ids", [])) & data["providers"].keys() or binding.get("service_ids")):
        env.append(EnvironmentBinding(route_key_variable(route), SecretRef(binding["credential_ref"])))
    flags = ()
    if engine == "bun":
      flags = ("--no-install", "--no-env-file", "--no-macros", "--config=" + str(runtime_root / "runtime/bunfig.locked.toml"),
        "--tsconfig-override=" + str(runtime_root / "runtime/tsconfig.locked.json"))
      env.extend((EnvironmentBinding("BUN_OPTIONS", ""), EnvironmentBinding("BUN_RUNTIME_TRANSPILER_CACHE_PATH", "0")))
    return LaunchSpec((engine, *flags, str(runtime_root / "runtime/launch.mjs"), "--manifest", str(instance_root / "pi-home/agentcfg-manifest.json")), cwd, lock_identity, tuple(env))

  def prepare_runtime(self, workspace, root):
    directories = ["pi-home", "user-home", "pi-home/sessions"]
    if "pi-cursor" in workspace.resolved.data["plugins"]: directories += ["cursor-home", "pi-home/cursor-cache"]
    for name in directories:
      ensure_private(workspace.instance / name)

  def launch_preflight_for(self, data, lock):
    engine = data["profile"]["agent_options"].get("runtime", {}).get("engine", "node")
    return [{"argv": [engine, "--version"], "version": lock.metadata["toolchains"][engine], "match": "exact"}]

  def runtime_guards(self, data):
    return {"files": ["pi-home/agentcfg-manifest.json", "pi-home/subagents.json", "pi-home/AGENTS.md", "pi-home/APPEND_SYSTEM.md", "pi-home/agentcfg-runtime-api.mjs"],
      "roots": ["pi-home/agents", "pi-home/extensions", "pi-home/skills"]}

  def validate_arguments(self, arguments):
    args = iter(arguments)
    for arg in args:
      if not isinstance(arg, str) or "\0" in arg:
        raise ConfigError("pi-arguments")
      if arg == "--":
        break
      if arg == "--thinking":
        if next(args, None) not in ("off", "minimal", "low", "medium", "high", "xhigh", "max"):
          raise ConfigError("pi-arguments")
      elif arg.startswith("-") and arg not in ("--print", "-p", "--help", "-h"):
        raise ConfigError("pi-arguments")

  def capture_projection(self, tree):
    from .deployment import get_field, parse_native
    raw = tree.read("pi-home/settings.json")
    if raw is None:
      return {}
    native = parse_native(raw[0], "json")
    return {key: get_field(native, pointer(key))["value"] for key in ("theme", "defaultProvider", "defaultModel") if key in native}

  def capture(self, projection):
    raise ConfigError("pi-capture-requires-selection")

  def capture_configuration(self, projection, data):
    if (not isinstance(projection, dict) or set(projection) - {"theme", "defaultProvider", "defaultModel"}
        or any(not isinstance(value, str) or not value for value in projection.values())):
      raise ConfigError("pi-capture-projection")
    result = {}
    if "theme" in projection:
      resources = data["adapter_documents"]["agent"]["resources"]
      matches = [name for name in data["profile"]["agent_options"].get("resources", {}).get("themes", []) if Path(resources[name]["path"]).stem == projection["theme"]]
      if len(matches) != 1:
        raise ConfigError("pi-capture-theme")
      result["agent_options"] = {"ui": {"theme": matches[0]}}
    if "defaultProvider" in projection or "defaultModel" in projection:
      matches = [identity for identity, model in data["models"].items() if model["remote_id"] == projection.get("defaultModel") and self.route(data, model["provider"]) == projection.get("defaultProvider")]
      if len(matches) != 1:
        raise ConfigError("pi-capture-model")
      result["roles"] = {"main": matches[0]}
    return result

  def upgrade_diagnostics(self, projection):
    from .pi_upgrade import upgrade_diagnostics
    return upgrade_diagnostics(projection)

  def project_metadata_root(self, workspace, project):
    from .workspace_leases import WorkspaceLeases
    return Path(WorkspaceLeases("project-maintenance").identify(project)["git_dir_path"]) / "agentcfg-project"

  def project_write_guard(self, workspace, project):
    from contextlib import contextmanager
    from .pi_lifecycle import guard
    from .workspace_leases import WorkspaceLeases
    @contextmanager
    def protected_project():
      with guard(workspace):
        # 只包住父进程同步的产物 CAS，不在业务树中执行 OpenSpec 子进程。
        with WorkspaceLeases("project-maintenance").maintenance(project):
          yield
    return protected_project()

  def diagnostic_exit_code(self, capabilities):
    return 5 if any(row["selected"] and row["dependencies"] != "installed" for row in capabilities) else 0

  def capability_diagnostics(self, projection):
    from .pi_diagnostics import capabilities
    return capabilities(projection)

  def live_diagnostics(self, data):
    from .pi_diagnostics import service_reachability
    return service_reachability(data)

  def doctor(self, projection):
    return ("pi-native-execution-not-verified",)

  def schemas(self):
    string = {"type": "string", "minLength": 1}
    strings = {"type": "array", "items": string, "uniqueItems": True}
    mapping = lambda value: {"type": "object", "additionalProperties": value}
    bindings = closed({"schema_version": {"type": "integer", "const": 1}, "protocols": mapping(string),
      "oauth": mapping(closed({"route": string, "owner": string}, ("route", "owner")))}, ("schema_version", "protocols", "oauth"))
    plugin = closed({"package": string, "version": string, "enabled": {"type": "boolean"},
      "requires": strings, "conflicts": strings, "engines": {"type": "array", "items": {"type": "string", "enum": ["node", "bun"]}, "uniqueItems": True}}, ("package", "version", "enabled", "requires", "conflicts", "engines"))
    documents = {"agent": read_schema("agent"), "bindings": bindings,
      "plugins": closed({"schema_version": {"type": "integer", "const": 1}, "plugins": mapping(plugin)}, ("schema_version", "plugins"))}

    def validate(kind, value):
      if kind == "resolved":
        self.validate(value)
      elif kind == "agent":
        validate_resources(value["resources"])
        for policy in value.get("policies", {}).values():
          validate_policy(policy)

    def policy(documents):
      return AdapterPolicy(defaults=documents["agent"]["defaults"], plugins=documents["plugins"]["plugins"],
        reserved_environment=frozenset({"PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR", "CODEX_HOME", "BUN_OPTIONS", "BUN_RUNTIME_TRANSPILER_CACHE_PATH"}))

    def claims(data):
      return tuple(AuthenticationClaim(key, data["adapter_documents"]["bindings"]["oauth"][key]["owner"] if provider["auth_kind"] == "oauth" else "pi-environment") for key, provider in data["providers"].items())

    return AdapterSchemas({"pi": AdapterSchemaBundle(self.declaration, documents, read_schema("options"), validate,
      policy=policy, authentication_claims=claims, validate_selected=self.validate_selected)})
