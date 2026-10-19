"""官方Pi CLI薄适配：纯配置投影、显式资源与只读启动检查。"""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry

from .adapter import (Adapter, AdapterDeclaration, Artifact, DependencyPlan, EnvironmentBinding,
  LaunchSpec, ManagedTarget, Ownership, SecretRef)
from .render import render_rules
from .schema import AdapterPolicy, AdapterSchemaBundle, AdapterSchemas, AuthenticationClaim, ConfigError, validate_document
from .storage import Conflict, Tree, ensure_private
from .paths import PathError, relative_path
from .pi_modules import MCP, MODULES, PLUGINS, SUPPORT


FLAVORS = tuple("catppuccin-" + name for name in ("latte", "frappe", "macchiato", "mocha"))
BUILTINS = ("builtin:codemode", "builtin:tool-search")
OFFICIAL_ENTRY = "node_modules/@earendil-works/pi-coding-agent/dist/bundle/cli.js"
THEME_ROOT = "node_modules/catppuccin-pi-theme/themes"
LOAD_ARRAYS = ("packages", "skills", "extensions", "prompts", "promptTemplates", "themes")


def encode(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


def pointer(*parts):
  return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def key_variable(provider):
  return "AGENTCFG_PI_CREDENTIAL_" + hashlib.sha256(provider.encode()).hexdigest()[:16].upper()


def _leaves(value, prefix=()):
  for key, item in value.items():
    if isinstance(item, dict):
      yield from _leaves(item, (*prefix, key))
    else:
      yield (*prefix, key), item


def _unique(items):
  result = {}
  for key, value in items:
    if key in result:
      raise ValueError()
    result[key] = value
  return result


def _native_settings(home):
  """仅投影非秘密加载声明与主题；不读取auth、trust或session。"""
  try:
    with Tree(home) as tree:
      raw = tree.read("settings.json", max_bytes=1048576)
    if raw is None:
      return {}
    value = json.loads(raw[0], object_pairs_hook=_unique)
    if not isinstance(value, dict):
      raise ValueError()
    return {key: value[key] for key in (*LOAD_ARRAYS, "theme") if key in value}
  except (OSError, ValueError, UnicodeError, RecursionError, PathError):
    raise Conflict("Pi原生资源声明无法安全校验") from None


class PiAdapter(Adapter):
  declaration = AdapterDeclaration("pi", 1, "pi-2")
  shared_files = ("pi-home/settings.json", "pi-home/models.json")
  shared_run_lease = True

  def __init__(self, repository):
    self.repository = Path(repository)

  def dependency_backend(self):
    from .pi_dependencies import PiBackend
    return PiBackend()

  def _schema(self, name):
    try:
      value = json.loads((self.repository / "agents/pi/schemas" / (name + ".schema.json")).read_bytes())
      Draft202012Validator.check_schema(value)
      return value
    except Exception:
      raise ConfigError("pi-schema-resource") from None

  def _check(self, name, value):
    if not Draft202012Validator(self._schema(name), registry=Registry()).is_valid(value):
      raise ConfigError("pi-schema", (name,))

  def route(self, data, provider_id):
    if data["providers"][provider_id]["auth_kind"] == "oauth":
      return data["adapter_documents"]["bindings"]["oauth"][provider_id]["route"]
    return "agentcfg-" + provider_id

  def validate(self, data):
    profile = data["profile"]
    options = profile["agent_options"]
    self._check("options", options)
    if profile["agent"] != "pi" or set(profile["roles"]) - {"main"} or set(profile["roles"].values()) - data["models"].keys():
      raise ConfigError("pi-model-reference")
    if (set(profile["plugins"]) - set(PLUGINS) or set(data["plugins"]) != set(profile["plugins"])
        or any(value != PLUGINS[name] for name, value in data["plugins"].items())):
      raise ConfigError("pi-plugin-module-not-admitted")
    if "pi-cursor" in data["plugins"] and "cursor" not in data["providers"]:
      raise ConfigError("pi-cursor-provider-required")
    if set(profile["mcp"]) - set(MCP) or set(data["mcp"]) != set(profile["mcp"]):
      raise ConfigError("pi-mcp-module-not-admitted")
    for name, server in data["mcp"].items():
      expected = {"transport": "stdio", "command": "node", "args": MCP[name]["args"]}
      if (set(server) - {*expected, "credential_ref"} or any(server.get(k) != v for k, v in expected.items())
          or name == "pi-brave" and not server.get("credential_ref")):
        raise ConfigError("pi-mcp-module-not-admitted")
    if options.get("collaboration", {}).get("enabled", False):
      raise ConfigError("pi-collaboration-not-ready")
    declarations = data["adapter_documents"]["agent"]["resources"]
    self._check("resources", declarations)
    try:
      for resource in declarations.values():
        relative_path(resource["path"])
    except PathError:
      raise ConfigError("pi-resource-path") from None
    resources = options.get("resources", {})
    for name in resources.get("prompts", []):
      if name not in declarations or declarations[name]["kind"] != "prompt":
        raise ConfigError("pi-resource-reference")
    paths = [declarations[name]["path"] for name in resources.get("prompts", [])]
    if len({Path(path).name for path in paths}) != len(paths):
      raise ConfigError("pi-resource-conflict")
    bindings = data["adapter_documents"]["bindings"]
    for identity, provider in data["providers"].items():
      if identity == "cursor" and provider["auth_kind"] != "oauth":
        raise ConfigError("pi-authentication-owner")
      if provider["auth_kind"] == "api-key":
        if provider["protocol"] not in bindings["protocols"] or not provider.get("base_url") or not provider.get("credential_ref"):
          raise ConfigError("pi-provider-binding")
      elif provider["auth_kind"] == "oauth":
        owner = bindings["oauth"].get(identity)
        cursor = identity == "cursor"
        valid_owner = (owner == {"route": "cursor", "owner": "pi-cursor"} and "pi-cursor" in data["plugins"]) if cursor else bool(owner and owner["owner"] == "pi-native")
        if (not valid_owner or provider["protocol"] != "oauth-dynamic"
            or "base_url" in provider or "credential_ref" in provider):
          raise ConfigError("pi-authentication-owner")
      else:
        raise ConfigError("pi-auth-kind")
    mappings = []
    for model in data["models"].values():
      if model["provider"] not in data["providers"] or set(model["input"]) - {"text", "image"}:
        raise ConfigError("pi-model-capability")
      mappings.append((self.route(data, model["provider"]), model["remote_id"]))
    if len(mappings) != len(set(mappings)):
      raise ConfigError("pi-model-mapping-ambiguous")
    validate_document("registry", {"schema_version": 1,
      **{key: data[key] for key in ("providers", "models", "rules", "skills", "mcp")}})

  def validate_selected(self, data):
    self.validate(data)

  def _fields(self, data):
    options = data["profile"]["agent_options"]
    settings = deepcopy(options.get("settings", {}))
    if "builtin:codemode" not in options.get("resources", {}).get("extensions", []):
      settings.pop("codemode", None)
    settings.update({name: [] for name in LOAD_ARRAYS})
    main = data["profile"]["roles"].get("main")
    if main:
      model = data["models"][main]
      settings.update(defaultProvider=self.route(data, model["provider"]), defaultModel=model["remote_id"])
    settings["enabledModels"] = [self.route(data, model["provider"]) + "/" + model["remote_id"] for model in data["models"].values()]
    for parts, value in _leaves(settings):
      yield ManagedTarget("pi-home/settings.json", Ownership.FIELDS, "json", pointer(*parts)), value
    for parts, value in _leaves(options.get("ui", {})):
      if parts == ("theme",) and "catppuccin" not in options.get("resources", {}).get("themes", []):
        continue
      yield ManagedTarget("pi-home/settings.json", Ownership.INITIALIZE, "json", pointer(*parts)), value
    for identity, provider in data["providers"].items():
      if provider["auth_kind"] != "api-key":
        continue
      prefix = ("providers", self.route(data, identity))
      models = []
      for model in data["models"].values():
        if model["provider"] != identity:
          continue
        native = {"id": model["remote_id"], "input": model["input"]}
        for source, target in (("name", "name"), ("reasoning", "reasoning"), ("context_window", "contextWindow"), ("max_output_tokens", "maxTokens")):
          if source in model:
            native[target] = model[source]
        native_options = deepcopy(model.get("native", {}).get("pi", {}))
        disabled = native_options.pop("disabled_thinking_levels", [])
        native.update(native_options)
        if disabled:
          native.setdefault("thinkingLevelMap", {}).update({level: None for level in disabled})
        models.append(native)
      for name, value in {"baseUrl": provider["base_url"], "api": data["adapter_documents"]["bindings"]["protocols"][provider["protocol"]], "models": models}.items():
        yield ManagedTarget("pi-home/models.json", Ownership.FIELDS, "json", pointer(*prefix, name)), value
      token = "$" + key_variable(identity)
      yield ManagedTarget("pi-home/models.json", Ownership.FIELDS, "json", pointer(*prefix, "apiKey"), (token,)), token

  def _instance(self, data):
    return Path(data["machine"]["paths"]["instances_root"]) / "pi" / data["profile"]["id"]

  def _mcp_values(self, data, instance):
    for name, server in data["mcp"].items():
      base = instance / "pi-mcp" / name
      values = {"HOME": str(base / "home"), **{key: str(base / key.lower())
        for key in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME")}}
      if name == "pi-brave":
        values["BRAVE_MCP_ENABLED_TOOLS"] = "brave_web_search"
      if "credential_ref" in server:
        values[MCP[name]["key"]] = SecretRef(server["credential_ref"])
      yield name, values

  def _mcp_variable(self, name, field):
    return "AGENTCFG_PI_MCP_" + hashlib.sha256((name + ":" + field).encode()).hexdigest()[:16].upper()

  def _mcp_fields(self, data, runtime_root):
    instance = self._instance(data)
    for name, values in self._mcp_values(data, instance):
      spec = MCP[name]
      fields = {"command": sys.executable, "args": [str(runtime_root / SUPPORT["target"]), spec["module"]],
        "cwd": str(instance / "pi-mcp" / name / "cwd"), "exposure": "hidden",
        "toolExposure": {tool: "direct" for tool in spec["tools"]}}
      for key, value in fields.items():
        yield ManagedTarget("pi-home/mcp.json", Ownership.FIELDS, "json", pointer("mcpServers", name, key)), value
      for key in values:
        token = "${" + self._mcp_variable(name, key) + "}"
        yield ManagedTarget("pi-home/mcp.json", Ownership.FIELDS, "json", pointer("mcpServers", name, "env", key), (token,)), token

  def _prompt_resources(self, data):
    declarations = data["adapter_documents"]["agent"]["resources"]
    for name in data["profile"]["agent_options"].get("resources", {}).get("prompts", []):
      source = declarations[name]["path"]
      yield name, source, "pi-home/prompts/" + Path(source).name

  def _browser_selected(self, data):
    return "playwright-cli" in data["profile"]["skills"]

  def _browser_wrapper(self, data, runtime_root):
    root = self._instance(data) / "pi-browser"
    content = ("#!" + sys.executable + " -I\nimport runpy\nrunpy.run_path(" + repr(str(runtime_root / "support/browser-launch.py"))
      + ", run_name=\"__main__\", init_globals={\"RUNTIME_ROOT\": " + repr(str(runtime_root))
      + ", \"BROWSER_ROOT\": " + repr(str(root)) + "})\n").encode()
    return Artifact(ManagedTarget("pi-home/bin/playwright-cli", Ownership.FILE, "bytes"), content, 0o700)

  def managed_targets(self, data):
    fixed = [ManagedTarget(path, Ownership.FILE, "text") for path in ("pi-home/AGENTS.md", "pi-home/APPEND_SYSTEM.md")]
    fixed += [ManagedTarget("pi-home/keybindings.json", Ownership.INITIALIZE, "json"),
      ManagedTarget("pi-home/resource-manifest.json", Ownership.FILE, "json"),
      ManagedTarget("pi-home/skills", Ownership.FILE, "skill-directory"),
      ManagedTarget(".agentcfg-instance.json", Ownership.RUNTIME, "json"),
      ManagedTarget("pi-home/auth.json", Ownership.RUNTIME, "native"),
      ManagedTarget("pi-home/sessions", Ownership.RUNTIME, "native"),
      ManagedTarget("pi-mcp", Ownership.RUNTIME, "native"),
      ManagedTarget("pi-cursor", Ownership.RUNTIME, "native"),
      ManagedTarget("runtimes", Ownership.PACKAGE, "npm")]
    if self._browser_selected(data):
      fixed += [ManagedTarget("pi-home/bin/playwright-cli", Ownership.FILE, "bytes"),
        ManagedTarget("pi-browser", Ownership.RUNTIME, "native")]
    if "pi-footer" in data["plugins"]:
      fixed.append(ManagedTarget("pi-home/extensions/pi-footer.json", Ownership.INITIALIZE, "json"))
    return tuple(fixed + [target for target, _ in self._fields(data)]
      + [target for target, _ in self._mcp_fields(data, Path("runtime-placeholder"))]
      + [ManagedTarget(target, Ownership.FILE, "text") for _, _, target in self._prompt_resources(data)])

  def render_context_required(self, data):
    return bool(data["profile"]["mcp"] or self._browser_selected(data))

  def render(self, data):
    if self.render_context_required(data):
      raise ConfigError("pi-render-context-required")
    return self._render(data, None)

  def render_with_context(self, data, context):
    from .adapter import RenderContext
    if type(context) is not RenderContext:
      raise ConfigError("pi-render-context-required")
    return self._render(data, context)

  def _render(self, data, context):
    self.validate(data)
    artifacts = [Artifact(target, encode(value)) for target, value in self._fields(data)]
    if self._browser_selected(data):
      artifacts.append(self._browser_wrapper(data, context.runtime_root))
    if context is not None:
      artifacts.extend(Artifact(target, encode(value)) for target, value in self._mcp_fields(data, context.runtime_root))
    selection = []
    with Tree(self.repository, private=False) as tree:
      if "pi-footer" in data["plugins"]:
        raw = tree.read("agents/pi/templates/pi-footer.json")
        if raw is None:
          raise ConfigError("pi-footer-template-missing")
        try:
          value = json.loads(raw[0], object_pairs_hook=_unique)
        except (ValueError, UnicodeError, RecursionError):
          raise ConfigError("pi-footer-template-invalid") from None
        self._check("footer", value)
        artifacts.append(Artifact(ManagedTarget("pi-home/extensions/pi-footer.json", Ownership.INITIALIZE, "json"), encode(value)))
      for name, source, target in self._prompt_resources(data):
        raw = tree.read(source)
        if raw is None:
          raise ConfigError("pi-resource-missing")
        artifacts.append(Artifact(ManagedTarget(target, Ownership.FILE, "text"), raw[0]))
        selection.append({"id": name, "type": "prompt", "source": source, "entry": target,
          "content_identity": hashlib.sha256(raw[0]).hexdigest(), "order": len(selection), "owner": "pi-adapter"})
      for filename, target in (("AGENTS.template.md", "AGENTS.md"), ("APPEND_SYSTEM.template.md", "APPEND_SYSTEM.md")):
        raw = tree.read("agents/pi/templates/" + filename)
        if raw is None:
          raise ConfigError("pi-template-missing")
        content = raw[0]
        if target == "AGENTS.md":
          content = render_rules(self.repository, tuple(data["rules"].values()), {}) + b"\n" + content
        artifacts.append(Artifact(ManagedTarget("pi-home/" + target, Ownership.FILE, "text"), content))
      keybindings = tree.read("agents/pi/templates/keybindings.template.jsonc")
      if keybindings is None:
        raise ConfigError("pi-template-missing")
      try:
        keys = json.loads(keybindings[0])
      except (ValueError, UnicodeError):
        raise ConfigError("pi-keybindings-template") from None
      artifacts.append(Artifact(ManagedTarget("pi-home/keybindings.json", Ownership.INITIALIZE, "json"), encode(keys)))
    from .skills import collect_skills
    skill_files = collect_skills(self.repository, data["skills"], target_root="pi-home/skills")
    for name in data["profile"]["skills"]:
      entries = [{"path": item.target.path, "sha256": hashlib.sha256(item.content).hexdigest()}
        for item in skill_files if item.target.path.startswith("pi-home/skills/" + name + "/")]
      selection.append({"id": name, "type": "skill", "source": data["skills"][name]["path"],
        "entry": "pi-home/skills/" + name, "content_identity": hashlib.sha256(encode(entries)).hexdigest(),
        "order": len(selection), "owner": "pi-adapter"})
    themed = "catppuccin" in data["profile"]["agent_options"].get("resources", {}).get("themes", [])
    manifest = {"schema_version": 1, "profile": data["profile"]["id"], "resource_selection": selection,
      "theme_source": "catppuccin-pi-theme@0.1.6" if themed else None, "themes": list(FLAVORS) if themed else [],
      "extensions": data["profile"]["agent_options"].get("resources", {}).get("extensions", [])}
    artifacts.append(Artifact(ManagedTarget("pi-home/resource-manifest.json", Ownership.FILE, "json"), encode(manifest)))
    return tuple(artifacts)

  def dependency_plan(self, data):
    themes = data["profile"]["agent_options"].get("resources", {}).get("themes", [])
    selected = sorted(set(themes + data["profile"]["plugins"] + data["profile"]["mcp"]
      + (["playwright-cli"] if self._browser_selected(data) else [])))
    return DependencyPlan(("@earendil-works/pi-coding-agent@1.3.0",)
      + tuple(MODULES[name][0] + "@" + MODULES[name][1] for name in selected))

  def lifecycle_guard(self, workspace):
    from .pi_lifecycle import guard
    return guard(workspace)

  def run_lifecycle_guard(self, workspace):
    from .pi_lifecycle import guard
    return guard(workspace, shared=True, allow_active=True, create=False)

  def run_owner_guard(self, workspace):
    from .lifecycle import registered_run
    return registered_run(workspace)

  def runtime_binding(self, data, instance):
    selected = {"profile": data["profile"]["id"], "resources": data["profile"]["agent_options"].get("resources", {}),
      "skills": data["profile"]["skills"], "plugins": data["profile"]["plugins"], "mcp": data["profile"]["mcp"], "mcp_bindings": data["mcp"],
      "providers": data["providers"], "models": data["models"], "roles": data["profile"]["roles"],
      "settings": data["profile"]["agent_options"].get("settings", {})}
    return {"cli_contract": "official-pi-1.3", "selection_digest": hashlib.sha256(encode(selected)).hexdigest(),
      "agent_home": str(instance / "pi-home"), "project_resources": False}

  def validate_runtime_binding(self, workspace, saved):
    if saved != self.runtime_binding(workspace.resolved.data, workspace.instance):
      raise Conflict("Pi运行选择与已部署契约不匹配；请检查plan并显式apply")

  def launch_spec(self, data, *, cwd, runtime_root, instance_root, lock_identity):
    self.validate_selected(data)
    options = data["profile"]["agent_options"]
    argv = ["node", str(runtime_root / OFFICIAL_ENTRY), "--session-dir", str(instance_root / "pi-home/sessions"),
      "--no-approve", "--no-extensions", "--no-skills", "--no-prompt-templates", "--no-themes"]
    if data["mcp"]:
      argv += ["-e", "builtin:mcp"]
    else:
      argv += ["--no-mcp"]
    for name in data["profile"]["plugins"]:
      plugin = PLUGINS[name]
      argv += ["-e", str(runtime_root / "node_modules" / plugin["package"] / plugin["entry"])]
    for name in data["profile"]["skills"]:
      argv += ["--skill", str(instance_root / "pi-home/skills" / name)]
    for _, _, target in self._prompt_resources(data):
      argv += ["--prompt-template", str(instance_root / target)]
    if "catppuccin" in options.get("resources", {}).get("themes", []):
      for name in FLAVORS:
        argv += ["--theme", str(runtime_root / THEME_ROOT / (name + ".json"))]
      argv += ["--use-theme", options.get("ui", {}).get("theme", "catppuccin-mocha")]
    for extension in options.get("resources", {}).get("extensions", []):
      argv += ["-e", extension]
    if "pi-footer" in data["plugins"]:
      argv += ["-e", str(runtime_root / "support/status-observer.mjs")]
    env = [EnvironmentBinding("PI_OFFLINE", "1"),
      EnvironmentBinding("PI_CODING_AGENT_DIR", str(instance_root / "pi-home")),
      EnvironmentBinding("PI_CODING_AGENT_SESSION_DIR", str(instance_root / "pi-home/sessions"))]
    if "pi-footer" in data["plugins"]:
      env.append(EnvironmentBinding("PI_FOOTER_CONFIG", str(instance_root / "pi-home/extensions/pi-footer.json")))
    if "pi-cursor" in data["plugins"]:
      env += [EnvironmentBinding("PI_CURSOR_SYSTEM_CREDENTIALS", "0"),
        EnvironmentBinding("PI_CURSOR_CACHE_DIR", str(instance_root / "pi-cursor"))]
    for key, provider in data["providers"].items():
      if provider["auth_kind"] == "api-key":
        env.append(EnvironmentBinding(key_variable(key), SecretRef(provider["credential_ref"]), required=False))
    for name, values in self._mcp_values(data, instance_root):
      env.extend(EnvironmentBinding(self._mcp_variable(name, key), value) for key, value in values.items())
    return LaunchSpec(tuple(argv), cwd, lock_identity, tuple(env), environment_policy="caller")

  def operation_environment(self, spec, arguments):
    homes = [item.value for item in spec.environment if item.name == "PI_CODING_AGENT_DIR"]
    if len(homes) != 1 or not isinstance(homes[0], str):
      raise Conflict("Pi原生目录身份无效")
    settings = _native_settings(Path(homes[0]))
    if "theme" not in settings:
      return spec
    theme = settings["theme"]
    if type(theme) is not str or theme not in FLAVORS or "--use-theme" not in spec.argv:
      raise Conflict("Pi原生主题不属于已锁定来源")
    argv = list(spec.argv)
    argv[argv.index("--use-theme") + 1] = theme
    return replace(spec, argv=tuple(argv))

  def prepare_runtime(self, workspace, root):
    for name in ("pi-home", "pi-home/sessions"):
      ensure_private(workspace.instance / name)
    if "pi-cursor" in workspace.resolved.data["plugins"]:
      ensure_private(workspace.instance / "pi-cursor")
    if self._browser_selected(workspace.resolved.data):
      for name in ("home", "cwd", "cwd/.playwright", "config", "cache", "data", "state", "browsers"):
        ensure_private(workspace.instance / "pi-browser" / name)
    for name, values in self._mcp_values(workspace.resolved.data, workspace.instance):
      for path in [workspace.instance / "pi-mcp" / name / "cwd", *[Path(value) for key, value in values.items() if key == "HOME" or key.startswith("XDG_")]]:
        ensure_private(path)

  def adjust_launch_environment(self, workspace, spec, env, saved_binding):
    # 旧部署也禁止宿主启动时自动下载安装；模型和MCP仍按各自声明联网。
    env["PI_OFFLINE"] = "1"
    # 原生SDK会继承宿主环境；服务仍由密封launcher再次白名单过滤。
    for name in list(env):
      if name.startswith(("CURSOR_", "PI_CURSOR_", "USAGE_SESSION_TOKEN")):
        env.pop(name)
    if "pi-cursor" in workspace.resolved.data["plugins"]:
      env.update(PI_CURSOR_SYSTEM_CREDENTIALS="0", PI_CURSOR_CACHE_DIR=str(workspace.instance / "pi-cursor"))
    for name in list(env):
      if name.startswith("PLAYWRIGHT_") or name == "AGENTCFG_PI_BROWSER_SESSION":
        env.pop(name)
    if self._browser_selected(workspace.resolved.data):
      env["AGENTCFG_PI_BROWSER_SESSION"] = secrets.token_hex(16)
      env["PATH"] = str(workspace.instance / "pi-home/bin") + os.pathsep + env.get("PATH", "")
    if "pi-footer" not in workspace.resolved.data["plugins"]:
      env.pop("PI_FOOTER_CONFIG", None)
    for key in list(env):
      if key.startswith(("CONTEXT7_", "BRAVE_")):
        env.pop(key)
    return env

  def validate_operation_environment(self, workspace, spec=None, env=None):
    if env is not None:
      cursor = {name: value for name, value in env.items() if name.startswith(("CURSOR_", "PI_CURSOR_", "USAGE_SESSION_TOKEN"))}
      expected_cursor = {"PI_CURSOR_SYSTEM_CREDENTIALS": "0", "PI_CURSOR_CACHE_DIR": str(workspace.instance / "pi-cursor")} if "pi-cursor" in workspace.resolved.data["plugins"] else {}
      if cursor != expected_cursor:
        raise Conflict("Pi Cursor凭据或路由环境与本实例声明不匹配")
      browser = self._browser_selected(workspace.resolved.data)
      session = env.get("AGENTCFG_PI_BROWSER_SESSION")
      if (browser and (type(session) is not str or not re.fullmatch(r"[a-f0-9]{32}", session)
          or not env.get("PATH", "").startswith(str(workspace.instance / "pi-home/bin") + os.pathsep))
          or not browser and session is not None or any(name.startswith("PLAYWRIGHT_") for name in env)):
        raise Conflict("Pi浏览器主运行环境与受管声明不匹配")
      expected = str(workspace.instance / "pi-home/extensions/pi-footer.json") if "pi-footer" in workspace.resolved.data["plugins"] else None
      if env.get("PI_FOOTER_CONFIG") != expected:
        raise Conflict("Pi状态栏配置路径与已部署声明不匹配")
    if env is not None and any(key.startswith(("CONTEXT7_", "BRAVE_")) for key in env):
      raise Conflict("Pi MCP环境含未声明的原生服务变量")

  def validate_runtime(self, workspace, root):
    settings = _native_settings(workspace.instance / "pi-home")
    if any(key in settings and settings[key] != [] for key in LOAD_ARRAYS):
      raise Conflict("Pi原生配置包含未准入的包或自动加载资源；请显式审阅，管理器不会删除或安装")
    if "theme" in settings and (type(settings["theme"]) is not str or settings["theme"] not in FLAVORS):
      raise Conflict("Pi原生主题不属于已锁定来源")

    data = workspace.resolved.data
    if "pi-cursor" in data["plugins"]:
      try:
        with Tree(workspace.instance / "pi-cursor") as tree:
          with tree.parent(".identity-probe"):
            pass
      except (OSError, PathError):
        raise Conflict("Pi Cursor私有缓存目录与本实例声明不匹配") from None
    if self._browser_selected(data):
      try:
        with Tree(workspace.instance / "pi-home/bin") as tree:
          with tree.parent(".identity-probe") as (fd, _):
            if set(os.listdir(fd)) != {"playwright-cli"}:
              raise ValueError()
        for name in ("home", "cwd", "cwd/.playwright", "config", "cache", "data", "state", "browsers"):
          with Tree(workspace.instance / "pi-browser" / name) as tree:
            with tree.parent(".identity-probe"):
              pass
      except (OSError, ValueError, PathError):
        raise Conflict("Pi浏览器入口或私有目录不匹配") from None
    try:
      with Tree(workspace.instance) as tree:
        raw = tree.read("pi-home/mcp.json", max_bytes=1048576)
      actual = json.loads(raw[0], object_pairs_hook=_unique) if raw else {"mcpServers": {}}
      expected = {"mcpServers": {}}
      for target, value in self._mcp_fields(data, root or Path("runtime-placeholder")):
        parts = target.selector.split("/")[1:]
        current = expected
        for part in parts[:-1]:
          current = current.setdefault(part, {})
        current[parts[-1]] = value
      if actual != expected and not (actual == {} and not data["mcp"]):
        raise ValueError()
      for name in data["mcp"]:
        base = workspace.instance / "pi-mcp" / name
        with Tree(base / "cwd") as tree:
          with tree.parent(".identity-probe") as (fd, _):
            if os.listdir(fd):
              raise ValueError()
        for directory in ("home", "xdg_config_home", "xdg_cache_home", "xdg_data_home", "xdg_state_home"):
          with Tree(base / directory) as tree:
            with tree.parent(".identity-probe"):
              pass
    except (OSError, ValueError, TypeError, RecursionError, PathError):
      raise Conflict("Pi MCP配置或私有服务目录与已部署声明不匹配") from None

  def launch_preflight_for(self, data, lock):
    return [{"argv": ["node", "--version"], "version": "v22.19.0", "match": "minimum"}]

  def runtime_guards(self, data):
    return {"files": ["pi-home/resource-manifest.json", "pi-home/AGENTS.md", "pi-home/APPEND_SYSTEM.md"] + (["pi-home/mcp.json"] if data["mcp"] else []),
      "roots": ["pi-home/prompts", "pi-home/skills"] + (["pi-home/bin"] if self._browser_selected(data) else [])}

  def validate_arguments(self, arguments):
    tokens = list(arguments)
    if any(not isinstance(token, str) or "\0" in token for token in tokens):
      raise ConfigError("pi-arguments")
    index = 0
    positional = []
    no_value = {"--continue", "-c", "--print", "-p", "--help", "-h", "--version", "-v", "--verbose", "--no-tools"}
    values = {"--session", "--fork", "--model", "--provider", "--thinking"}
    while index < len(tokens):
      token = tokens[index]
      if not isinstance(token, str) or "\0" in token:
        raise ConfigError("pi-arguments")
      if token == "--":
        if any(not isinstance(value, str) or "\0" in value for value in tokens[index + 1:]):
          raise ConfigError("pi-arguments")
        break
      option, equal, inline = token.partition("=")
      if option in no_value:
        if equal:
          raise ConfigError("pi-arguments")
      elif option in values or option in ("--resume", "-r"):
        # Pi 1.3 的 fork 必须显式接会话 ID，不支持等号形式。
        if option == "--fork" and equal:
          raise ConfigError("pi-arguments")
        if equal:
          value = inline
        elif index + 1 < len(tokens) and not tokens[index + 1].startswith("-"):
          index += 1
          value = tokens[index]
        elif option in ("--resume", "-r"):
          value = None
        else:
          raise ConfigError("pi-arguments")
        if value is not None:
          if not value or "\0" in value:
            raise ConfigError("pi-arguments")
          if option == "--thinking" and value not in ("off", "minimal", "low", "medium", "high", "xhigh", "max"):
            raise ConfigError("pi-arguments")
          # 原生 CLI 将相对 .jsonl 也视为路径，不能绕过实例会话目录。
          if option in ("--session", "--fork", "--resume", "-r") and (
              "/" in value or "\\" in value or value in (".", "..") or value.lower().endswith(".jsonl")):
            raise ConfigError("pi-session-directory-boundary")
      elif token.startswith("-"):
        raise ConfigError("pi-arguments")
      else:
        positional.append(token)
      index += 1
    if positional and positional[0] in ("install", "update", "remove", "uninstall", "config", "package", "packages"):
      raise ConfigError("pi-operation-not-managed")

  def validate_before_spawn(self, workspace, cwd, arguments, env):
    from .pi_lifecycle import assert_no_legacy_workspace_owner
    assert_no_legacy_workspace_owner(cwd)
    root = None
    if workspace.resolved.data["mcp"]:
      lock = workspace.backend.read_lock(workspace.repository)
      root = workspace.backend.root(workspace, workspace.backend.runtime_identity(workspace, lock))
    self.validate_runtime(workspace, root)
    data = workspace.resolved.data
    choices = {}
    tokens = list(arguments)
    for index, token in enumerate(tokens):
      if token == "--":
        break
      option, equal, value = token.partition("=")
      if option in ("--provider", "--model"):
        if option in choices:
          raise ConfigError("pi-model-option-repeated")
        choices[option] = value if equal else tokens[index + 1]
    routes = {self.route(data, name) for name in data["providers"]}
    provider = choices.get("--provider")
    if provider is not None and provider not in routes:
      raise ConfigError("pi-provider-not-selected")
    selected = choices.get("--model")
    if selected is not None:
      matches = [(self.route(data, model["provider"]), model["remote_id"]) for model in data["models"].values()
        if (provider is None or self.route(data, model["provider"]) == provider)
        and selected in (model["remote_id"], self.route(data, model["provider"]) + "/" + model["remote_id"])]
      if len(matches) != 1:
        raise ConfigError("pi-model-not-selected-or-ambiguous")

  def capture_projection(self, tree):
    raw = tree.read("pi-home/settings.json")
    if raw is None:
      return {}
    try:
      value = json.loads(raw[0], object_pairs_hook=_unique)
      return {key: value[key] for key in ("theme", "defaultProvider", "defaultModel") if key in value}
    except (ValueError, TypeError, UnicodeError, RecursionError):
      raise ConfigError("pi-capture-projection") from None

  def capture(self, projection):
    raise ConfigError("pi-capture-requires-selection")

  def capture_configuration(self, projection, data):
    if (not isinstance(projection, dict) or set(projection) - {"theme", "defaultProvider", "defaultModel"}
        or any(not isinstance(value, str) or not value for value in projection.values())):
      raise ConfigError("pi-capture-projection")
    result = {}
    if "theme" in projection:
      if projection["theme"] not in FLAVORS:
        raise ConfigError("pi-capture-theme")
      result["agent_options"] = {"ui": {"theme": projection["theme"]}}
    if "defaultProvider" in projection or "defaultModel" in projection:
      matches = [name for name, model in data["models"].items()
        if model["remote_id"] == projection.get("defaultModel") and self.route(data, model["provider"]) == projection.get("defaultProvider")]
      if len(matches) != 1:
        raise ConfigError("pi-capture-model")
      result["roles"] = {"main": matches[0]}
    return result

  def doctor(self, projection):
    return ("pi-native-execution-not-verified", "pi-collaboration-not-ready", "pi-status-parity-not-verified", "pi-optional-native-execution-not-verified")

  def feature_readiness(self, data):
    """声明能力准入与缺口；不把依赖已安装视为插件已加载。"""
    return {
      "status_bar": ({"status": "not_verified", "decision": "admitted", "candidate": "pi-footer@0.5.1",
        "fallback": "native", "information_parity": "not_verified"} if "pi-footer" in data["plugins"] else
        {"status": "not_selected", "decision": "admitted", "candidate": "pi-footer@0.5.1",
        "fallback": "native", "information_parity": "not_verified"}),
      "collaboration": {"status": "not_ready", "decision": "held", "candidate": "@mjakl/pi-subagent@3.1.0",
        "requested": bool(data["profile"]["agent_options"].get("collaboration", {}).get("enabled", False))},
      "optional_modules": {"status": "not_verified" if data["plugins"] or data["mcp"] or self._browser_selected(data) else "not_selected",
        "decision": "admitted" if data["plugins"] or data["mcp"] or self._browser_selected(data) else "candidate",
        "selected": sorted([*data["plugins"], *data["mcp"], *(["playwright-cli"] if self._browser_selected(data) else [])])},
    }

  def schemas(self):
    options = self._schema("options")
    documents = {name: self._schema(name) for name in ("agent", "bindings", "plugins")}
    # options为唯一活动选项定义，agent默认值使用同一严格schema。
    documents["agent"]["properties"]["defaults"]["properties"]["agent_options"] = deepcopy(options)
    def validate(kind, value):
      if kind == "resolved":
        self.validate(value)
      elif kind == "agent":
        self._check("resources", value["resources"])
    return AdapterSchemas({"pi": AdapterSchemaBundle(self.declaration, documents, options, validate,
      policy=lambda docs: AdapterPolicy(deepcopy(docs["agent"]["defaults"]), deepcopy(docs["plugins"]["plugins"]),
        frozenset(), frozenset({"PI_OFFLINE", "PI_CODING_AGENT_DIR", "PI_CODING_AGENT_SESSION_DIR", "PI_FOOTER_CONFIG", "AGENTCFG_PI_BROWSER_SESSION", "PLAYWRIGHT_CLI_SESSION", "PI_CURSOR_SYSTEM_CREDENTIALS", "PI_CURSOR_CACHE_DIR"})),
      authentication_claims=lambda data: tuple(AuthenticationClaim(key,
        ("pi-cursor" if key == "cursor" else "pi-native") if provider["auth_kind"] == "oauth" else "pi-environment") for key, provider in data["providers"].items()),
      validate_selected=self.validate_selected)})
