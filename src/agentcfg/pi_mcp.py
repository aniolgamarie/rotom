"""MCP 服务来自 registry 与机器绑定；不读取宿主自己的 MCP 配置。"""
from .paths import configured_path
from .schema import ConfigError
from urllib.parse import urlsplit


def direct_tools(binding):
  value = binding.get("direct_tools", {})
  if value.get("enabled") is not True:
    if "tools" in value: raise ConfigError("pi-mcp-direct-tools-not-selected")
    return False
  return value.get("tools", True)


def oauth_configuration(binding, source, variable):
  options = binding.get("oauth")
  if not options: raise ConfigError("pi-mcp-oauth-binding-required")
  def endpoint(value, *, origin=False, callback=False):
    if not isinstance(value, str) or not value or any(ord(char) < 32 or char in "$!" for char in value):
      raise ConfigError("pi-mcp-oauth-endpoint")
    try:
      parsed = urlsplit(value)
      port = parsed.port
    except ValueError: raise ConfigError("pi-mcp-oauth-endpoint") from None
    local = callback and parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1") and port not in (None, 0, 80)
    if (not local and parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
        or origin and parsed.path not in ("", "/")):
      raise ConfigError("pi-mcp-oauth-endpoint")
    if callback and parsed.scheme == "https" and parsed.hostname in ("localhost", "127.0.0.1", "::1"):
      raise ConfigError("pi-mcp-oauth-endpoint")
    try: return parsed.hostname.lower(), parsed.port or 443
    except ValueError: raise ConfigError("pi-mcp-oauth-endpoint") from None
  allowed = {endpoint(url, origin=True) for url in options["allowed_origins"]}
  native = {"grantType": options["grant_type"]}
  if options["grant_type"] == "authorization_code":
    # 远端 HTTPS 使用手工回调；本地 HTTP 只允许明确 loopback 与固定端口。
    if "redirect_uri" not in options: raise ConfigError("pi-mcp-oauth-redirect-required")
    endpoint(options["redirect_uri"], callback=True)
    native["redirectUri"] = options["redirect_uri"]
  elif options["grant_type"] == "client_credentials":
    if not options.get("client_id") or not source.get("credential_ref") or "redirect_uri" in options:
      raise ConfigError("pi-mcp-oauth-client-binding")
  else: raise ConfigError("pi-mcp-oauth-grant")
  for public, field in (("client_id", "clientId"), ("scope", "scope")):
    if public in options:
      value = options[public]
      if not value.strip() or any(ord(char) < 32 or char in "$!" for char in value): raise ConfigError("pi-mcp-oauth-literal")
      native[field] = value
  if "auth_server_metadata_url" in options:
    if endpoint(options["auth_server_metadata_url"]) not in allowed: raise ConfigError("pi-mcp-oauth-origin")
    native["authServerMetadataUrl"] = options["auth_server_metadata_url"]
  if source.get("credential_ref"):
    if not options.get("client_id"): raise ConfigError("pi-mcp-oauth-client-binding")
    native["clientSecret"] = "${" + variable + "}"
  return native


def configuration(data, *, native=False):
  selected = data["mcp"]
  options = data["profile"]["agent_options"]
  settings = options.get("mcp", {})
  bindings = settings.get("servers", {})
  if native and data["profile"]["id"] not in ("pi-base", "pi-full"):
    raise ConfigError("pi-mcp-native-profile")
  if not native and "allowed_tools" in settings:
    raise ConfigError("pi-mcp-native-tools-unselected")
  if native and not selected and not settings: return None
  if not native and "pi-mcp" not in data["plugins"]:
    if selected or settings:
      raise ConfigError("pi-mcp-not-selected")
    return None
  if not selected or set(selected) != set(bindings):
    raise ConfigError("pi-mcp-service-binding-required")
  servers = {}
  for name, source in selected.items():
    binding = bindings[name]
    if source["transport"] != binding["transport"]:
      raise ConfigError("pi-mcp-transport-mismatch")
    if binding["transport"] == "stdio":
      command = options.get("external_tools", {}).get(binding["command_ref"])
      if (not command or command.get("interactive") is not True or "credential_ref" in source or "url" in source
          or str(configured_path(source.get("command", ""))) != str(configured_path(command["executable"]))
          or source.get("args", []) != command.get("args", [])):
        raise ConfigError("pi-mcp-command-binding-required")
      servers[name] = {"command": str(configured_path(command["executable"])), "args": command.get("args", []),
        "directTools": direct_tools(binding), "lifecycle": "lazy", "debug": False}
    else:
      endpoint = urlsplit(source.get("url", ""))
      route = options.get("network", {}).get("routes", {}).get(binding["network_route"])
      if (endpoint.scheme not in ("http", "https") or not endpoint.hostname or endpoint.username or endpoint.password
          or endpoint.query or endpoint.fragment or "command" in source or "args" in source
          or not route or "mcp:" + name not in route.get("service_ids", [])):
        raise ConfigError("pi-mcp-http-route-required")
      auth = binding["authentication"]
      if auth not in ("none", "bearer", "oauth") or auth != "oauth" and (auth == "bearer") != bool(source.get("credential_ref")):
        raise ConfigError("pi-mcp-authentication-binding")
      from .pi import key_variable
      if auth != "oauth" and "oauth" in binding: raise ConfigError("pi-mcp-oauth-not-selected")
      native_oauth = oauth_configuration(binding, source, key_variable("mcp:" + name)) if auth == "oauth" else False
      servers[name] = {"url": source["url"], "httpTransport": binding["transport"], "auth": auth if auth in ("bearer", "oauth") else False,
        "oauth": native_oauth, "directTools": direct_tools(binding), "lifecycle": "lazy", "debug": False,
        **({"bearerTokenEnv": key_variable("mcp:" + name)} if auth == "bearer" else {})}
  sampling = settings.get("sampling", {})
  if sampling.get("enabled") is not True and set(sampling) - {"enabled"}:
    raise ConfigError("pi-mcp-sampling-not-selected")
  scripting = settings.get("scripting", {})
  if scripting.get("enabled"):
    from .pi_mcp_script import script_binding
    script_binding(options)
  elif set(scripting) - {"enabled"}:
    raise ConfigError("pi-mcp-scripting-not-selected")
  apps = settings.get("apps", {})
  if apps.get("enabled"):
    if apps.get("browser_network") != "user-browser": raise ConfigError("pi-mcp-apps-browser-binding")
    if apps.get("host_port", 0) and apps.get("host_port") == apps.get("proxy_port"): raise ConfigError("pi-mcp-apps-port-conflict")
    for value in apps.get("allowed_browser_origins", []):
      parsed = urlsplit(value)
      if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
          or parsed.path not in ("", "/") or "*" in value or any(ord(char) < 32 for char in value)):
        raise ConfigError("pi-mcp-apps-origin")
  elif set(apps) - {"enabled"}:
    raise ConfigError("pi-mcp-apps-not-selected")
  return {"mcpServers": servers, "settings": {"hostConfigDiscovery": "off", "agentPluginPaths": [],
    "directTools": False, "scriptMode": scripting.get("enabled", False), "sampling": sampling.get("enabled", False),
    "samplingAutoApprove": sampling.get("auto_approve", False), "elicitation": settings.get("elicitation", False), "autoAuth": False,
    "outputGuard": True, "notifyOnStartupConnect": False}}



def official_configuration(data, *, allowed_tools):
  """静态公开SDK配置与受管transport绑定；不连接服务、不读取秘密或宿主配置。"""
  from pathlib import PurePosixPath
  import re
  from .paths import PathError

  def invalid(code="pi-mcp-official-configuration"):
    raise ConfigError(code)

  def record(value, allowed, required=()):
    if type(value) is not dict or set(value) - set(allowed) or set(required) - set(value): invalid()
    return value

  def literal(value):
    return isinstance(value, str) and bool(value) and not any(ord(char) < 32 or ord(char) == 127 for char in value)

  def names(value):
    if (type(value) is not list or len(value) > 64
        or any(not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) or "__" in name for name in value)
        or len(set(value)) != len(value)): invalid("pi-mcp-official-allowed-tools")
    return list(value)

  def absolute(value):
    if (not literal(value) or "\\" in value or "$" in value or "!" in value
        or not PurePosixPath(value).is_absolute() or str(PurePosixPath(value)) != value
        or ".." in PurePosixPath(value).parts): invalid("pi-mcp-official-stdio-binding")
    return value

  try:
    # 沿用原registry/机器绑定校验，旧配置返回与语义不变。
    legacy = configuration(data, native=data["profile"]["id"] in ("pi-base", "pi-full"))
    if type(allowed_tools) is not dict: invalid("pi-mcp-official-allowed-tools")
    if legacy is None:
      if allowed_tools: invalid("pi-mcp-official-allowed-tools")
      return None
    selected = data["mcp"]
    if set(allowed_tools) != set(selected): invalid("pi-mcp-official-allowed-tools")
    options = data["profile"]["agent_options"]
    settings = record(options["mcp"], ("servers", "allowed_tools", "sampling", "scripting", "apps", "elicitation", "callback_max_seconds"), ("servers",))
    if "allowed_tools" in settings and settings["allowed_tools"] != allowed_tools:
      invalid("pi-mcp-official-allowed-tools")
    for feature in ("sampling", "scripting", "apps"):
      value = settings.get(feature, {})
      if type(value) is not dict: invalid()
      if value.get("enabled", False) is not False: invalid("pi-mcp-official-" + feature + "-unavailable")
      record(value, ("enabled",))
    if settings.get("elicitation", False) is not False:
      invalid("pi-mcp-official-elicitation-unavailable")
    deadline = settings.get("callback_max_seconds")
    if "callback_max_seconds" in settings and (type(deadline) is not int or not 30 <= deadline <= 900): invalid()
    if "callback_max_seconds" in settings and not any(row.get("authentication") == "oauth" for row in settings["servers"].values()):
      invalid("pi-mcp-official-callback-unavailable")
    entries, bindings, explicit = [], {}, {}
    namespaces, tool_names = set(), set()
    for name, source in selected.items():
      if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name): invalid()
      namespace = name.replace("-", "_")
      if namespace in namespaces or "__" in namespace: invalid("pi-mcp-official-server-collision")
      namespaces.add(namespace)
      record(source, ("transport", "command", "args", "url", "credential_ref"), ("transport",))
      binding = settings["servers"][name]
      transport = source["transport"]
      if transport not in ("stdio", "sse", "streamable-http"): invalid()
      fields = ("transport", "command_ref", "direct_tools") if transport == "stdio" else ("transport", "network_route", "authentication", "direct_tools", "oauth")
      record(binding, fields, ("transport", "command_ref") if transport == "stdio" else ("transport", "network_route", "authentication"))
      reference = binding["command_ref"] if transport == "stdio" else binding["network_route"]
      if not isinstance(reference, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", reference): invalid()
      allow = names(allowed_tools[name]); explicit[name] = allow
      for tool in allow:
        generated = "mcp__" + namespace + "__" + tool.replace("-", "_")
        if len(generated) > 64 or generated in tool_names: invalid("pi-mcp-official-allowed-tools")
        tool_names.add(generated)
      direct = record(binding.get("direct_tools", {}), ("enabled", "tools"))
      if "enabled" in direct and type(direct["enabled"]) is not bool: invalid()
      exposure = "codemode"
      if direct.get("enabled") is True:
        declared = names(direct.get("tools"))
        if declared != allow: invalid("pi-mcp-official-direct-tools-scope")
        exposure = "direct"
      config = {"exposure": "hidden", "toolExposure": {tool: exposure for tool in allow}}
      bound = {"transport": transport, "authentication": "none" if transport == "stdio" else binding["authentication"]}
      credential = source.get("credential_ref")
      if "credential_ref" in source:
        if not isinstance(credential, str) or not re.fullmatch(r"secret:(?!\.{1,2}$)[^/\\\x00-\x1f\x7f]+", credential): invalid()
        bound["credential_ref"] = credential
      if transport == "stdio":
        reference = binding["command_ref"]
        command = record(options["external_tools"][reference], ("executable", "args", "version", "project_root", "read_roots", "write_roots", "timeout_seconds", "interactive"), ("executable", "project_root"))
        root = record(options["paths"]["roots"][command["project_root"]], ("path", "purpose"), ("path", "purpose"))
        if root["purpose"] != "project": invalid("pi-mcp-official-stdio-binding")
        args = command.get("args", [])
        if type(args) is not list or any(not isinstance(arg, str) or any(ord(char) < 32 or ord(char) == 127 for char in arg) for arg in args): invalid()
        config.update(type="stdio", command=absolute(command["executable"]), args=list(args), cwd=absolute(root["path"]), env={})
        bound["command_ref"] = reference
      else:
        if not literal(source["url"]) or any(char in source["url"] for char in "$!"): invalid()
        config.update(type="http", url=source["url"])
        bound["network_route"] = binding["network_route"]
        auth = binding["authentication"]
        if auth == "none":
          # 官方以Authorization键存在判断关闭默认OAuth；受控transport外发前必须去掉空marker。
          config["headers"] = {"Authorization": ""}
        elif auth == "bearer":
          config["headers"] = {"Authorization": "Bearer ${" + legacy["mcpServers"][name]["bearerTokenEnv"] + "}"}
        elif auth == "oauth":
          oauth = record(binding["oauth"], ("grant_type", "client_id", "scope", "redirect_uri", "allowed_origins", "auth_server_metadata_url"), ("grant_type", "allowed_origins"))
          native = legacy["mcpServers"][name]["oauth"]
          if oauth["grant_type"] != "authorization_code": invalid("pi-mcp-official-oauth-grant-unavailable")
          redirect = oauth["redirect_uri"]; parsed = urlsplit(redirect)
          if parsed.scheme != "http" or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            invalid("pi-mcp-official-oauth-callback-unavailable")
          origins = oauth["allowed_origins"]
          if type(origins) is not list or not 1 <= len(origins) <= 16 or len(set(origins)) != len(origins): invalid()
          bound["oauth_policy"] = {"allowed_origins": list(origins), **({"callback_max_seconds": deadline} if deadline is not None else {})}
          config["oauth"] = {**{field: native[field] for field in ("clientId", "clientSecret", "scope", "authServerMetadataUrl") if field in native}, "callbackUrl": redirect}
        elif auth != "none": invalid()
      entries.append({"name": name, "config": config, "source": "agentcfg:registry/mcp/" + name, "scope": "extension"})
      bindings[name] = bound
    return {"schema_version": 1, "loaded_config": {"servers": entries, "errors": [], "autoEnableCodemode": False},
      "bindings": bindings, "allowed_tools": explicit}
  except ConfigError:
    raise
  except (KeyError, TypeError, ValueError, AttributeError, PathError):
    raise ConfigError("pi-mcp-official-configuration") from None
