"""实网 SDK 服务运行器；复用部署与宿主监督，第三方正文不进入验收日志。"""
import json
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile

from .activity import digest
from .adapter import SecretRef
from .deployment import json_bytes
from .pi_lifecycle import assert_inactive
from .pi_live_project import inspect_project
from .pi_validation_native import cancel_fixture
from .runtime import run as run_runtime
from .storage import Conflict, Tree, ensure_private


def service_preflight(context):
  data = context["workspace"].resolved.data
  options = data["profile"]["agent_options"]
  capability = context["item"]["capability_id"]
  if not data["profile"]["roles"].get("main"): return "live-main-model-binding-required"
  if capability == "mcp" and ("pi-mcp" not in data["plugins"] or not data["profile"]["mcp"]): return "live-mcp-binding-required"
  if capability == "web":
    web = options.get("web", {})
    selected = web.get("providers", web.get("settings", {}).get("searchProvider", web.get("settings", {}).get("provider")))
    providers = selected if isinstance(selected, list) else [selected] if isinstance(selected, str) else []
    if ("pi-web" not in data["plugins"] or not providers or any(name in ("auto", "all") or name not in web.get("services", {}) for name in providers)):
      return "live-web-provider-selection-required"
  if capability == "terminal" and ("gentle-agent-state" not in options.get("resources", {}).get("extensions", []) or options.get("agent_state", {}).get("mode") != "service"):
    return "live-terminal-service-binding-required"
  if capability == "task-keeper":
    task = options.get("task_keeper", {})
    second = context["item"]["scenario_id"].endswith(".second-view")
    roles = {"task_keeper_reader", "task_keeper_writer", "task_keeper_reviewer"} | ({"second_view"} if task.get("second_view_enabled") else set())
    if ("task-keeper" not in data["plugins"] or not task.get("enabled") or roles - data["profile"]["roles"].keys()
        or not task.get("check_ids") or second and not task.get("second_view_enabled")):
      return "live-managed-binding-required"
    root = options.get("paths", {}).get("roots", {}).get(task.get("project_root"), {})
    if Path(root.get("path", "/")).resolve() != context["project"].resolve(): return "live-managed-probe-root-required"
    try: inspect_project(context["project"])
    except (Conflict, OSError, ValueError): return "live-managed-probe-project-required"
    transport = "proxy" if ".live-proxy." in context["item"]["scenario_id"] else "direct"
    if transport not in context.get("native_transports", []): return "live-native-transport-not-covered"
    for name in roles:
      if data["models"][data["profile"]["roles"][name]].get("remote_id", "").startswith("agentcfg-native-"): return "live-synthetic-model-forbidden"
      provider = data["models"][data["profile"]["roles"][name]]["provider"]
      routes = [row for row in options.get("network", {}).get("routes", {}).values() if provider in row.get("provider_ids", [])]
      if len(routes) != 1 or routes[0]["mode"] != transport: return "live-managed-transport-mismatch"
      if routes[0].get("credential_ref") and not context.get("native_proxy_authentication"): return "live-native-proxy-authentication-not-covered"
  if capability not in ("mcp", "web", "terminal", "task-keeper"): return "live-service-unsupported"
  return None


def selected_secrets(context):
  data = context["workspace"].resolved.data
  options = data["profile"]["agent_options"]
  capability = context["item"]["capability_id"]
  refs = set()
  main = data["profile"]["roles"].get("main")
  model_providers = set()
  if main:
    model_providers.add(data["models"][main]["provider"])
    provider = data["providers"][data["models"][main]["provider"]]
    if provider.get("credential_ref"): refs.add(provider["credential_ref"])
  if capability == "task-keeper":
    for role in ("task_keeper_reader", "task_keeper_writer", "task_keeper_reviewer", "second_view"):
      model = data["profile"]["roles"].get(role)
      if model:
        provider = data["models"][model]["provider"]
        model_providers.add(provider)
        reference = data["providers"][provider].get("credential_ref")
        if reference: refs.add(reference)
  if capability == "mcp":
    for name in data["profile"]["mcp"]:
      reference = data["mcp"][name].get("credential_ref")
      if reference: refs.add(reference)
    sampling = options.get("mcp", {}).get("sampling", {})
    if sampling.get("enabled") and sampling.get("model"):
      for model in data["models"].values():
        if context["workspace"].adapter.route(data, model["provider"]) + "/" + model["remote_id"] == sampling["model"]:
          model_providers.add(model["provider"])
          reference = data["providers"][model["provider"]].get("credential_ref")
          if reference: refs.add(reference)
  if capability == "web":
    web = options.get("web", {})
    refs.update(web.get("credentials", {}).values())
    for headers in web.get("header_credentials", {}).values(): refs.update(headers.values())
  for route in options.get("network", {}).get("routes", {}).values():
    # 路线秘密只供本次选中的服务或主模型；模型路线由显式 openai-proxy 插件使用。
    ids = route.get("service_ids", [])
    if route.get("credential_ref") and (model_providers.intersection(route.get("provider_ids", [])) or any(value.startswith(capability + ":") for value in ids)):
      refs.add(route["credential_ref"])
  return refs


def service_facts_valid(facts, capability, count):
  if not isinstance(facts, dict) or facts.get("sdk_session") is not True or facts.get("capability") != capability: return False
  fields = {"sdk_session", "capability"}
  if capability == "task-keeper":
    return (set(facts) == fields | {"inspect_verified", "fix_verified", "checks_verified", "review_verified", "second_view_verified", "job_count"}
      and all(facts[key] is True for key in ("inspect_verified", "fix_verified", "checks_verified", "review_verified"))
      and type(facts["second_view_verified"]) is bool and type(facts["job_count"]) is int and facts["job_count"] == 2)
  if capability == "mcp":
    return (set(facts) == fields | {"mcp_servers_verified", "metadata_refreshed"} and facts["metadata_refreshed"] is True
      and type(facts["mcp_servers_verified"]) is int and facts["mcp_servers_verified"] == count and count > 0)
  if capability == "web":
    return (set(facts) == fields | {"web_providers_verified", "search_response_verified"} and facts["search_response_verified"] is True
      and type(facts["web_providers_verified"]) is int and facts["web_providers_verified"] == count and count > 0)
  return capability == "terminal" and set(facts) == fields | {"terminal_reports_acknowledged"} and type(facts["terminal_reports_acknowledged"]) is int and facts["terminal_reports_acknowledged"] == 3


def execute_services(context, *, recheck, execute=run_runtime, popen=subprocess.Popen, cancel=cancel_fixture):
  reason = service_preflight(context)
  scenario = context["item"]["scenario_id"]
  if reason: return {"scenario_id": scenario, "status": "not-run", "reason": reason}
  workspace, runtime = context["workspace"], context["runtime"]
  with Tree(runtime.root) as tree:
    if tree.read("runtime/service-validation.mjs") is None: return {"scenario_id": scenario, "status": "not-run", "reason": "live-service-entrypoint-missing"}
  directory = workspace.state_root / "live-validation" / secrets.token_hex(16); ensure_private(directory)
  managed = context["item"]["capability_id"] == "task-keeper"
  marker = inspect_project(context["project"]) if managed else None
  variant = "second-view" if scenario.endswith(".second-view") else "workflow"
  nonce = secrets.token_hex(32)
  path = directory / "input.json"
  with Tree(directory) as tree:
    tree.write_new(path.name, json_bytes({"schema_version": 1, "nonce": nonce, "capability": context["item"]["capability_id"],
      "instance_root": str(workspace.instance), "project": str(context["project"]), "runtime_identity": runtime.identity, "output": str(directory / "service-result.json"),
      **({"variant": variant} if managed else {})}))
  refs = selected_secrets(context)
  outcome = {"exit_code": None, "timed_out": False, "started": False}
  def operation(w, spec, env, lease_fd, saved, *, lifecycle_fd):
    with Tree(w.instance) as tree: manifest = json.loads(tree.read("pi-home/agentcfg-manifest.json")[0])
    argv = list(spec.argv); at = argv.index(str(runtime.root / "runtime/launch.mjs"))
    argv = [*argv[:at], str(runtime.root / "runtime/service-validation.mjs"), "--input", str(path)]
    config = {"state_root": str(w.state_root), "instance_root": str(w.instance), "repository": str(runtime.root / "supervisor"),
      "runtime_root": str(runtime.root), "instance_id": digest({"instance": str(w.instance), "binding": w.binding}),
      "lock_identity": runtime.lock_identity, "slice_identity": runtime.slice_identity, "policy_digest": digest(manifest["permission_policy"]),
      "manifest_digest": digest(manifest), "cwd": str(spec.cwd), "engine": runtime.engine, "argv": argv,
      "protected_roots": [str(w.local_path), str(w.instance), str(w.state_root)]}
    with tempfile.TemporaryFile(dir=w.state_root) as bootstrap:
      bootstrap.write(json_bytes(config)); bootstrap.flush(); bootstrap.seek(0)
      child = popen([sys.executable, "-B", "-I", str(runtime.root / "supervisor/scripts/pi-supervisor.py"),
        "--bootstrap-fd", str(bootstrap.fileno()), "--lease-fd", str(lease_fd), "--instance-fd", str(lifecycle_fd), "--", *argv],
        cwd=spec.cwd, env={**env, "AGENTCFG_SERVICE_VALIDATION": "1"}, pass_fds=(bootstrap.fileno(), lease_fd, lifecycle_fd),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
      outcome["started"] = True
    try: outcome["exit_code"] = child.wait(timeout=600)
    except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
      outcome["timed_out"] = isinstance(error, subprocess.TimeoutExpired)
      try: cancel(w.state_root)
      except Exception: pass
      try: outcome["exit_code"] = child.wait(timeout=30)
      except subprocess.TimeoutExpired:
        child.terminate()
        try: outcome["exit_code"] = child.wait(timeout=5)
        except subprocess.TimeoutExpired:
          child.kill(); outcome["exit_code"] = child.wait(timeout=5)
      if isinstance(error, KeyboardInterrupt): raise
    return outcome["exit_code"]
  current = recheck()
  if current.get("reason") or current["identity"] != context["identity"] or current["scope_digest"] != context["scope_digest"]:
    return {"scenario_id": scenario, "status": "not-run", "reason": "live-context-changed"}
  try:
    execute(workspace, cwd=context["project"], launch_operation=operation,
      select_environment=lambda binding: not isinstance(binding.value, SecretRef) or binding.value.reference in refs)
  except (Exception, KeyboardInterrupt) as error: outcome["exit_code"] = getattr(error, "exit_code", 5)
  ended = True
  try: assert_inactive(workspace.state_root)
  except Exception: ended = False
  with Tree(directory) as tree: raw = tree.read("service-result.json", max_bytes=1024 * 1024)
  try: result = json.loads(raw[0]) if raw and raw[1] == 0o600 else None
  except (ValueError, UnicodeError): result = None
  capability = context["item"]["capability_id"]
  options = workspace.resolved.data["profile"]["agent_options"]
  web = options.get("web", {}); providers = web.get("providers", web.get("settings", {}).get("searchProvider", web.get("settings", {}).get("provider", [])))
  count = len(workspace.resolved.data["profile"]["mcp"]) if capability == "mcp" else len(providers) if isinstance(providers, list) else 1
  valid = (isinstance(result, dict) and set(result) == {"schema_version", "nonce", "capability", "runtime_identity", "status", "failure_code", "facts"}
    and type(result["schema_version"]) is int and result["schema_version"] == 1 and result["nonce"] == nonce
    and result["runtime_identity"] == runtime.identity and result["capability"] == context["item"]["capability_id"] and result["status"] == "passed" and result["failure_code"] is None
    and service_facts_valid(result["facts"], capability, count))
  if managed:
    try: preserved = inspect_project(context["project"]) == marker
    except (Conflict, OSError, ValueError): preserved = False
    valid = valid and preserved and (variant != "second-view" or result["facts"]["second_view_verified"] is True)
  passed = valid and ended and outcome["exit_code"] == 0 and not outcome["timed_out"]
  if not outcome["started"] and ended:
    return {"scenario_id": scenario, "status": "not-run", "reason": "live-credentials-missing" if outcome["exit_code"] == 3 else "live-service-prerequisite-unavailable"}
  return {"scenario_id": scenario, "status": "passed" if passed else "failed", "artifact_directory": str(directory),
    "facts": {**(result["facts"] if valid else {"sdk_session": False, "capability": context["item"]["capability_id"]}),
      "scope_restricted": True, "termination_confirmed": ended}, **({} if passed else {"reason": "live-service-not-verified"})}
