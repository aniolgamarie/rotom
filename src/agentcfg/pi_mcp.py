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


def configuration(data):
  selected = data["mcp"]
  options = data["profile"]["agent_options"]
  settings = options.get("mcp", {})
  bindings = settings.get("servers", {})
  if "pi-mcp" not in data["plugins"]:
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
