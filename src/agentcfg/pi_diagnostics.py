"""Pi 离线分层诊断；不读取认证文件，不以安装存在冒充执行通过。"""
from copy import deepcopy
import platform
import sys

from .activity import digest
from .paths import configured_path
from .pi_evidence import EvidenceStore, identity_for, timestamp


def probe_endpoint(endpoint, route):
  """HEAD 只检查明确路线的 HTTP 响应；不发送账号或模型请求，不跟随跳转。"""
  import http.client
  from urllib.parse import urlsplit
  target = urlsplit(endpoint)
  if target.scheme not in ("http", "https") or not target.hostname or target.username or target.password:
    return {"status": "unverified", "reason": "endpoint-unavailable"}
  if route.get("credential_ref"):
    return {"status": "unverified", "reason": "proxy-authentication-not-inspected"}
  connection = None
  try:
    path = target.path or "/"
    if route["mode"] == "direct":
      factory = http.client.HTTPSConnection if target.scheme == "https" else http.client.HTTPConnection
      connection = factory(target.hostname, target.port, timeout=5)
    else:
      proxy = urlsplit(route["proxy_url"])
      if proxy.scheme != "http":
        return {"status": "unverified", "reason": "proxy-probe-transport-unavailable"}
      if target.scheme == "https":
        connection = http.client.HTTPSConnection(proxy.hostname, proxy.port or 80, timeout=5)
        connection.set_tunnel(target.hostname, target.port or 443)
      else:
        connection = http.client.HTTPConnection(proxy.hostname, proxy.port or 80, timeout=5)
        path = endpoint
    connection.request("HEAD", path, headers={"User-Agent": "agentcfg-doctor"})
    response = connection.getresponse()
    # 401/403 仍证明 HTTP 可达，不证明登录、API 路径或模型调用可用。
    return {"status": "reachable", "http_status": response.status}
  except Exception:
    return {"status": "unverified", "reason": "endpoint-unreachable"}
  finally:
    if connection is not None:
      connection.close()


def service_reachability(data):
  options = data["profile"]["agent_options"]
  routes = options.get("network", {}).get("routes", {})
  checks = []
  for provider_id, provider in sorted(data["providers"].items()):
    endpoint = provider.get("base_url")
    if provider_id == "cursor" and "pi-cursor" in data["plugins"]:
      endpoint = options.get("cursor", {}).get("endpoint")
    selected = [(key, value) for key, value in sorted(routes.items()) if provider_id in value.get("provider_ids", [])]
    if not selected:
      checks.append({"location_id": "provider:" + digest(provider_id)[:20], "status": "unverified", "reason": "explicit-route-required"})
    for key, route in selected:
      result = probe_endpoint(endpoint, route) if endpoint else {"status": "unverified", "reason": "endpoint-unavailable"}
      checks.append({"location_id": "route:" + digest([provider_id, key])[:20], **result})
  for name, service in sorted(data["mcp"].items()):
    binding = options.get("mcp", {}).get("servers", {}).get(name, {})
    route = routes.get(binding.get("network_route"))
    if service["transport"] == "stdio":
      result = {"status": "unverified", "reason": "native-service-not-inspected"}
    elif not route:
      result = {"status": "unverified", "reason": "explicit-route-required"}
    else:
      result = probe_endpoint(service["url"], route)
    checks.append({"location_id": "service:" + digest(["mcp", name])[:20], **result})
  if "pi-web" in data["plugins"]:
    for name, binding in sorted(options.get("web", {}).get("services", {}).items()):
      route = routes.get(binding.get("network_route"))
      origins = binding.get("origins", []) if binding.get("type") == "api" else []
      if not route or "web:" + name not in route.get("service_ids", []):
        checks.append({"location_id": "service:" + digest(["web", name])[:20], "status": "unverified", "reason": "explicit-route-required"})
      elif not origins:
        checks.append({"location_id": "service:" + digest(["web", name])[:20], "status": "unverified", "reason": "public-target-not-selected"})
      else:
        for origin in origins:
          checks.append({"location_id": "service:" + digest(["web", name, origin])[:20], **probe_endpoint(origin, route)})
  return checks


def diagnostic_identity(projection):
  from pathlib import Path
  import hashlib
  from .pi import PiAdapter
  data = projection["data"]; options = data["profile"]["agent_options"]
  public = deepcopy(data); public["profile"]["agent_options"].pop("diagnostics", None)
  repository = Path(projection.get("repository", Path(__file__).resolve().parents[2]))
  artifacts = PiAdapter(repository).render(public)
  from .pi_resource_reads import tree_digest
  skills = {name: tree_digest(repository / data["skills"][name]["path"]) for name in data["profile"]["skills"]}
  content = [{"path": item.target.path, "selector": item.target.selector, "sha256": hashlib.sha256(item.content).hexdigest()} for item in artifacts]
  return identity_for(lock=projection["lock_identity"], runtime=projection["runtime_identity"],
    policy=data["adapter_documents"]["agent"]["policies"].get(options.get("permissions", {}).get("policy_ref")),
    resources={"selections": options.get("resources", {}), "skills": skills, "plugins": data["plugins"], "content": content},
    roles={"roles": data["profile"]["roles"], "models": data["models"]},
    machine_contract={"options": {key: value for key, value in options.items() if key != "diagnostics"}, "providers": data["providers"], "mcp": data["mcp"]})


def capabilities(projection):
  data = projection["data"]; options = data["profile"]["agent_options"]
  settings = options.get("diagnostics", {}); evidence = []
  if settings:
    store = EvidenceStore(configured_path(settings["evidence_root"]))
    evidence = [value for path in settings["evidence_paths"] if (value := store.read(path)) is not None]
  identity = diagnostic_identity(projection)
  current_platform = projection.get("platform") or {"os": sys.platform,
    "architecture": {"aarch64": "arm64", "amd64": "x86_64"}.get(platform.machine().lower(), platform.machine().lower()),
    "engine": options.get("runtime", {}).get("engine", "node")}
  selected = {"pi-host", *data["plugins"], *options.get("resources", {}).get("extensions", [])}
  backends = options.get("model_delegate", {}).get("backends", []) if options.get("model_delegate", {}).get("enabled") and "model-delegate" in data["plugins"] else []
  selected.update("model-delegate:" + name for name in backends)
  all_ids = ["pi-host", *sorted((set(data["adapter_documents"]["plugins"]["plugins"]) | selected | {"model-delegate:pi", "model-delegate:codex"}) - {"pi-host"})]
  web = options.get("web", {})
  web_auth = bool(web.get("credentials") or web.get("header_credentials") or web.get("auth_fetch") or set(web.get("models", {})) & {"openai", "xai", "kimi"}
    or web.get("browser_profiles") or set(web.get("services", {})) - {"public", "duckduckgo", "searxng", "exa", "parallel-mcp", "github", "authenticated"})
  rows = []
  for name in all_ids:
    enabled = name in selected
    auth = enabled and (name == "pi-host" and bool(data["providers"])
      or name == "pi-mcp" and (any(service.get("credential_ref") for service in data["mcp"].values())
        or any(binding.get("authentication") == "oauth" for binding in options.get("mcp", {}).get("servers", {}).values()))
      or name == "pi-web" and web_auth
      or name in ("pi-cursor", "model-delegate:codex", "model-delegate:pi"))
    row = {"id": name, "selected": enabled, "configured": enabled, "deployed": enabled and projection["deployed"],
      "dependencies": projection["dependencies"] if enabled else "not-selected", "load_evidence": "not-run", "execution_evidence": "not-run",
      "authentication": "not-inspected" if auth else "not-required", "observed_at": {}, "blockers": [], "location_id": "capability:" + digest(name)[:20]}
    if enabled:
      if name == "model-delegate:codex":
        from .pi_codex_admission import POLICY_ID
        row["configuration_admission"] = {"policy": POLICY_ID, "status": "not-inspected",
          "checked_at": "before-each-execution", "atomic_config_binding": False,
          "limitations": ["system-config-directory-must-be-absent-or-empty", "managed-preferences-must-be-absent",
            "organization-or-unknown-account-not-supported", "stable-trusted-machine-and-account-required"]}
      if name == "pi-host" and not data["profile"]["roles"].get("main"):
        row["configured"] = False; row["blockers"].append("PI_MODEL_UNBOUND")
      if not row["deployed"]: row["blockers"].append("PI_DEPLOYMENT_MISSING")
      if row["dependencies"] != "installed": row["blockers"].append("PI_DEPENDENCIES_MISSING")
      for stage in ("load", "authentication", "execution"):
        candidates = [value for value in evidence if value["capability_id"] == name and value["test_case_id"] == stage and value["level"] in ("native", "live")]
        matching = [value for value in candidates if value["identity"] == identity and value["platform"] == current_platform]
        state = "stale" if candidates else "not-run"
        if matching:
          executed = [value for value in matching if value["finished_at"]]
          latest = max(executed, key=lambda value: timestamp(value["finished_at"])) if executed else matching[-1]
          row["observed_at"][stage] = latest["finished_at"]
          state = "verified" if latest["status"] == "passed" else "not-run"
          if latest["status"] == "failed": row["blockers"].append("PI_" + stage.upper() + "_FAILED")
          if stage == "authentication" and auth:
            if state == "verified": row["authentication"] = "observed-ready"
            elif latest["reason"] == "authentication-required": row["authentication"] = "pending-login"
        if stage != "authentication": row[stage + "_evidence"] = state
      if row["authentication"] == "pending-login": row["blockers"].append("PI_AUTHENTICATION_PENDING")
    rows.append(row)
  return rows
