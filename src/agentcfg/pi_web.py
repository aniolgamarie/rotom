"""Web 服务、凭据和模型均来自显式机器绑定；不读取旧配置或账号。"""
from copy import deepcopy
from urllib.parse import urlsplit
import ipaddress

from .adapter import EnvironmentBinding, SecretRef
from .schema import ConfigError
from .paths import configured_path


SERVICES = ("authenticated", "public", "openai", "brave", "parallel", "parallel-mcp", "tinyfish", "search1api", "searchinfinity",
  "querit", "tavily", "firecrawl", "jina", "jina-reader", "serpdive", "kagi", "bocha", "ollama", "searxng",
  "duckduckgo", "exa", "perplexity", "gemini-api", "gemini-auth", "gemini-web", "kimi", "anysearch", "xcrawl",
  "valyu", "xai", "brightdata", "brightdata-unlocker", "serpbase", "serper", "datalab", "github")
CREDENTIAL_SERVICES = {name + "ApiKey": (name,) for name in (
  "brave", "exa", "openai", "perplexity", "parallel", "tinyfish", "search1api", "searchinfinity", "querit", "tavily",
  "firecrawl", "jina", "serpdive", "kagi", "bocha", "ollama", "anysearch", "xcrawl", "valyu", "xai", "serpbase", "serper", "datalab")}
CREDENTIAL_SERVICES.update(geminiApiKey=("gemini-api",), cloudflareApiKey=("gemini-api",),
  brightdataApiKey=("brightdata", "brightdata-unlocker"), geminiAdcCredentials=("gemini-auth",), githubToken=("github",))
ENDPOINT_SERVICES = {"datalabApiBase": "datalab", "braveBaseUrl": "brave", "exaBaseUrl": "exa", "tavilyBaseUrl": "tavily",
  "firecrawlBaseUrl": "firecrawl", "geminiBaseUrl": "gemini-api", "openaiResponsesUrl": "openai", "searxngBaseUrl": "searxng"}


def origin(value, *, endpoint=False):
  if not isinstance(value, str) or not value or any(ord(char) < 32 or char in "$!" for char in value): raise ConfigError("pi-web-url")
  try:
    parsed = urlsplit(value)
    port = parsed.port
    if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None or parsed.password is not None
        or parsed.query or parsed.fragment or not endpoint and parsed.path not in ("", "/")):
      raise ValueError()
    host = parsed.hostname.encode("idna").decode().lower()
    if ":" in host: host = "[" + ipaddress.IPv6Address(host).compressed + "]"
    default = 443 if parsed.scheme == "https" else 80
    return parsed.scheme + "://" + host + (":" + str(port) if port and port != default else "")
  except (ValueError, UnicodeError): raise ConfigError("pi-web-url") from None


def configuration(data):
  from .pi import key_variable
  options = data["profile"]["agent_options"]; selected = options.get("web", {})
  if "pi-web" not in data["plugins"]:
    if selected: raise ConfigError("pi-web-not-selected")
    return None
  native = {"workflow": "none", "autoOpenBrowser": False, **deepcopy(selected.get("settings", {}))}
  if "provider" in native and "searchProvider" in native and native["provider"] != native["searchProvider"]:
    raise ConfigError("pi-web-provider-conflict")
  if "providers" in selected:
    if "provider" in native or "searchProvider" in native: raise ConfigError("pi-web-provider-conflict")
    native["searchProvider"] = deepcopy(selected["providers"])
  if "searchRouting" in native and any(key in native for key in ("provider", "searchProvider")): raise ConfigError("pi-web-routing-conflict")
  output = selected.get("pdf_output_root_ref")
  if output is not None:
    root = options.get("paths", {}).get("roots", {}).get(output)
    if not root or root["purpose"] != "write": raise ConfigError("pi-web-pdf-output-root")
  curator = selected.get("curator", {})
  if curator.get("enabled") and curator.get("browser_network") != "user-browser": raise ConfigError("pi-web-curator-browser-binding")
  if curator:
    try: bind = ipaddress.ip_address(curator.get("bind", "127.0.0.1"))
    except ValueError: raise ConfigError("pi-web-curator-bind") from None
    if curator.get("bind", "127.0.0.1") not in ("127.0.0.1", "::1") and not curator.get("advertised_origin"): raise ConfigError("pi-web-curator-origin-required")
    if curator.get("advertised_origin") is not None: origin(curator["advertised_origin"])
  if native.get("workflow") == "summary-review" and not curator.get("enabled"): raise ConfigError("pi-web-curator-required")
  for key in ("ffmpeg_tool_ref", "ffprobe_tool_ref", "yt_dlp_tool_ref", "javascript_tool_ref"):
    name = selected.get("media", {}).get(key)
    if name is None: continue
    binding = options.get("external_tools", {}).get(name)
    if not binding or binding.get("args", []) or binding.get("interactive", False): raise ConfigError("pi-web-media-tool-binding")
    roots = options.get("paths", {}).get("roots", {})
    if any(ref not in roots or roots[ref]["purpose"] != "read" for ref in binding.get("read_roots", [])): raise ConfigError("pi-web-media-read-root")
  if selected.get("media", {}).get("yt_dlp_tool_ref") and not selected.get("media", {}).get("javascript_tool_ref"):
    raise ConfigError("pi-web-youtube-javascript-binding")
  services = deepcopy(selected.get("services", {})); variables = []
  clone = selected.get("github_clone")
  native["githubClone"] = {"enabled": clone is not None, "maxRepoSizeMB": clone.get("max_repo_size_mb", 350) if clone else 350}
  if clone is not None:
    tool = options.get("external_tools", {}).get(clone["git_tool_ref"])
    root = options.get("paths", {}).get("roots", {}).get(clone["root_ref"])
    if not root or root["purpose"] != "write": raise ConfigError("pi-web-github-output-root")
    if not tool or tool.get("args", []) or tool.get("interactive", False): raise ConfigError("pi-web-github-tool-binding")
    roots = options.get("paths", {}).get("roots", {})
    if any(ref not in roots or roots[ref]["purpose"] != "read" for ref in tool.get("read_roots", [])): raise ConfigError("pi-web-media-read-root")
    if "https://github.com" not in [origin(value) for value in services.get("github", {}).get("origins", [])]: raise ConfigError("pi-web-github-origin")
  public = services.get("public")
  if public is not None:
    for source, destination in ((native.get("ssrf", {}).get("allowRanges"), "allow_ranges"),
        (native.get("fetchContent", {}).get("domainPolicy", {}).get("allow"), "domain_allow"),
        (native.get("fetchContent", {}).get("domainPolicy", {}).get("deny"), "domain_deny")):
      if source is not None:
        if destination in public and public[destination] != source: raise ConfigError("pi-web-scope-conflict")
        public[destination] = source
    native["ssrf"] = {"allowRanges": public.get("allow_ranges", []), "trustEnvProxy": False}
    native["fetchContent"] = {"domainPolicy": {"allow": public.get("domain_allow", []), "deny": public.get("domain_deny", [])}}
  for name, binding in services.items():
    if name not in SERVICES or (name == "public") != (binding["type"] == "public"): raise ConfigError("pi-web-service-kind")
    route = options.get("network", {}).get("routes", {}).get(binding["network_route"])
    if not route or "web:" + name not in route.get("service_ids", []): raise ConfigError("pi-web-route-required")
    if binding["type"] == "api":
      if not binding.get("origins"): raise ConfigError("pi-web-origin-required")
      binding["origins"] = [origin(value) for value in binding["origins"]]
      if len(set(binding["origins"])) != len(binding["origins"]): raise ConfigError("pi-web-origin-duplicate")
    elif binding.get("origins"): raise ConfigError("pi-web-public-origin-fields")
    for network in binding.get("allow_ranges", []):
      try:
        parsed = ipaddress.ip_network(network, strict=True)
        if parsed.prefixlen == 0: raise ValueError()
      except ValueError: raise ConfigError("pi-web-address-range") from None
  for field, reference in selected.get("credentials", {}).items():
    if field not in CREDENTIAL_SERVICES or not set(CREDENTIAL_SERVICES[field]) & services.keys(): raise ConfigError("pi-web-credential-service")
    SecretRef(reference)
    variable = key_variable("web:" + field); variables.append(variable)
    native[field] = "${" + variable + "}"
  for service, headers in selected.get("header_credentials", {}).items():
    if service != "searxng" or service not in services: raise ConfigError("pi-web-header-service")
    normalized = set()
    for name, reference in headers.items():
      if name.lower() in normalized or name.lower() in ("host", "proxy-authorization", "content-length", "connection", "transfer-encoding"):
        raise ConfigError("pi-web-header-name")
      normalized.add(name.lower()); SecretRef(reference)
      variable = key_variable("web-header:" + service + ":" + name); variables.append(variable)
      native.setdefault("searxngHeaders", {})[name] = "${" + variable + "}"
  for field, value in selected.get("endpoints", {}).items():
    service = ENDPOINT_SERVICES.get(field)
    if service not in services or origin(value, endpoint=True) not in services[service].get("origins", []): raise ConfigError("pi-web-endpoint-origin")
    native[field] = value
  browser_profiles = {}
  for name, binding in selected.get("browser_profiles", {}).items():
    root = options.get("paths", {}).get("roots", {}).get(binding["root_ref"])
    if (not root or root["purpose"] != "read" or binding["profile"] in (".", "..") or binding["profile"] != binding["profile"].strip()
        or any(ord(char) < 32 or ord(char) == 127 or char in "/\\" for char in binding["profile"])): raise ConfigError("pi-web-browser-root")
    if any(".." in host or host.startswith(".") or host.endswith(".") for host in binding["allowed_hosts"]): raise ConfigError("pi-web-browser-host")
    SecretRef(binding["password_ref"])
    variable = key_variable("web-browser:" + name); variables.append(variable)
    browser_profiles[name] = {"root": str(configured_path(root["path"])), "profile": binding["profile"], "browser": binding["browser"],
      "allowed_hosts": list(binding["allowed_hosts"]), "max_bytes": binding.get("max_bytes", 32 * 1024 * 1024), "password_reference": "${" + variable + "}"}
  gemini_profile = selected.get("gemini_browser_profile")
  if gemini_profile is not None:
    browser = browser_profiles.get(gemini_profile)
    if not browser or "gemini-web" not in services: raise ConfigError("pi-web-browser-service")
    if not {"gemini.google.com", "accounts.google.com", "www.google.com"} <= set(browser["allowed_hosts"]): raise ConfigError("pi-web-browser-host")
    native["agentcfgBrowserProfile"] = gemini_profile
    native["browserCookies"] = {"browser": browser["browser"], "profile": browser["profile"]}
  native["allowBrowserCookies"] = bool(browser_profiles)
  auth_fetch = {}
  for name, binding in selected.get("auth_fetch", {}).items():
    service = services.get("authenticated")
    if not service: raise ConfigError("pi-web-auth-fetch-service")
    origins = [origin(value) for value in binding["origins"]]
    if any(not value.startswith("https://") or value not in service.get("origins", []) for value in origins): raise ConfigError("pi-web-auth-fetch-origin")
    if len(set(origins)) != len(origins): raise ConfigError("pi-web-origin-duplicate")
    if ("cookie_ref" in binding) == ("browser_profile" in binding): raise ConfigError("pi-web-auth-fetch-source")
    if "cookie_ref" in binding:
      SecretRef(binding["cookie_ref"])
      variable = key_variable("web-auth:" + name); variables.append(variable)
      auth_fetch[name] = {"origins": origins, "cookie_reference": "${" + variable + "}"}
    else:
      browser = browser_profiles.get(binding["browser_profile"])
      if not browser or any(urlsplit(value).hostname not in browser["allowed_hosts"] for value in origins): raise ConfigError("pi-web-auth-fetch-browser")
      auth_fetch[name] = {"origins": origins, "browser_profile": binding["browser_profile"]}
    native.setdefault("authFetch", {})[name] = {"hosts": sorted({urlsplit(value).hostname for value in origins}), "redirects": "same-origin", "cache": "off"}
  preferences = native.get("searchProvider", native.get("provider", "auto"))
  choices = preferences if isinstance(preferences, list) else [preferences]
  for choice in choices:
    candidates = ("gemini-api", "gemini-web") if choice == "gemini" else (choice,)
    if choice not in ("auto", "all") and not set(candidates) & services.keys(): raise ConfigError("pi-web-provider-not-selected")
  for choice in native.get("searchRouting", {}).get("providers", []):
    candidates = ("gemini-api", "gemini-web") if choice == "gemini" else (choice,)
    if not set(candidates) & services.keys(): raise ConfigError("pi-web-provider-not-selected")
  fetch_services = {"http": ("public",), "jina": ("jina-reader",), "brightdata": ("brightdata-unlocker",), "gemini": ("gemini-api", "gemini-web")}
  for choice in native.get("fetchRouting", {}).get("providers", []):
    if not set(fetch_services.get(choice, (choice,))) & services.keys(): raise ConfigError("pi-web-fetch-provider-not-selected")
  pdf_provider = native.get("pdf", {}).get("provider", "auto")
  if pdf_provider == "datalab" and "datalab" not in services or pdf_provider == "gemini" and "gemini-api" not in services:
    raise ConfigError("pi-web-pdf-provider-not-selected")
  models = {}
  fields = {"summary": "summaryModel", "gemini": "searchModel", "openai": "openaiSearchModel", "xai": "xaiSearchModel"}
  for purpose, name in selected.get("models", {}).items():
    model = data["models"].get(name)
    if model is None: raise ConfigError("pi-web-model-not-selected")
    provider = data["providers"][model["provider"]]
    route = data["adapter_documents"]["bindings"]["oauth"][model["provider"]]["route"] if provider["auth_kind"] == "oauth" else "agentcfg-" + model["provider"]
    models[purpose] = {"provider": route, "model": model["remote_id"]}
    if purpose in fields: native[fields[purpose]] = route + "/" + model["remote_id"] if purpose == "summary" else model["remote_id"]
    if purpose == "gemini":
      for key in ("video", "youtube"): native.setdefault(key, {})["preferredModel"] = model["remote_id"]
  return {"web_config": native, "web_services": services, "web_credential_variables": sorted(variables), "web_model_bindings": models, "web_auth_fetch": auth_fetch, "web_browser_profiles": browser_profiles}


def environment_bindings(data):
  from .pi import key_variable
  if "pi-web" not in data["plugins"]: return []
  # 上游按请求解析凭据；缺失可延迟报告，不能让一个可选服务阻止主会话启动。
  values = [EnvironmentBinding(key_variable("web:" + name), SecretRef(reference), required=False)
    for name, reference in data["profile"]["agent_options"].get("web", {}).get("credentials", {}).items()]
  values.extend(EnvironmentBinding(key_variable("web-auth:" + name), SecretRef(binding["cookie_ref"]), required=False)
    for name, binding in data["profile"]["agent_options"].get("web", {}).get("auth_fetch", {}).items() if "cookie_ref" in binding)
  values.extend(EnvironmentBinding(key_variable("web-browser:" + name), SecretRef(binding["password_ref"]), required=False)
    for name, binding in data["profile"]["agent_options"].get("web", {}).get("browser_profiles", {}).items())
  values.extend(EnvironmentBinding(key_variable("web-header:" + service + ":" + name), SecretRef(reference), required=False)
    for service, headers in data["profile"]["agent_options"].get("web", {}).get("header_credentials", {}).items() for name, reference in headers.items())
  return values


def protected_browser_roots(options):
  """浏览器认证目录自动加入普通工具的硬拒绝范围，专用读端仍按 profile 授权。"""
  return sorted({value["root_ref"] for value in options.get("web", {}).get("browser_profiles", {}).values()})
