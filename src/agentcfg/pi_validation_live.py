"""实网执行准入：固定选择、当前部署和同平台原生证据先于账号调用。"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .activity import digest
from .deployment import read_state
from .pi_acceptance import read_scope
from .pi_diagnostics import diagnostic_identity
from .pi_lifecycle import assert_inactive
from .pi_validation_report import validate_run_report
from .pi_validation_runtime import inspect_runtime
from .schema import ConfigError
from .runtime import record
from .storage import Conflict, Tree
from .workspace import load_workspace
from .pi_validation_live_delegate import execute_delegate
from .pi_validation_live_services import execute_services


ROOT = Path(__file__).resolve().parents[2]
CASE_CAPABILITIES = {"codex-receipts": {"codex"}, "model-delegate-replacement": {"cursor", "proxy"},
  "taskkeeper-lifecycle": {"task-keeper"}, "host-resources": {"mcp", "web", "terminal"}}
SCENARIOS = {name: {"live-" + name} for name in ("codex", "cursor", "proxy", "mcp", "web", "terminal")}
SCENARIOS["task-keeper"] = {"live-" + route + "." + action for route in ("direct", "proxy") for action in ("inspect-fix-review", "second-view")}


def selected_item(scope, *, scenario, profile, case):
  rows = [row for row in scope["items"] if row["scenario_id"] == scenario]
  # 同场景在多个架构中存在；平台在检查运行包身份后再限定。
  if not rows or not scenario.startswith(profile + ".") or case not in CASE_CAPABILITIES:
    raise ConfigError("pi-live-scope-selection")
  if any(row["capability_id"] not in CASE_CAPABILITIES[case] or row["levels"] != ["live"] for row in rows):
    raise ConfigError("pi-live-scope-selection")
  if any(scenario[len(profile) + 1:] not in SCENARIOS[row["capability_id"]] for row in rows): raise ConfigError("pi-live-scope-selection")
  return rows


def native_prerequisite(value, runtime, case):
  validate_run_report(value, tier="native", case=case)
  if value["runtime"] != runtime.public_identity(): return "native-runtime-mismatch"
  if value["status"] != "passed": return "native-scenarios-not-passed"
  return None


def inspect_context(args):
  scope = read_scope(args.scope)
  selected = selected_item(scope, scenario=args.live_item, profile=args.profile, case=args.case)
  if all(row["applicability"] == "not_selected" for row in selected):
    return {"reason": "live-capability-not-selected", "scope_digest": scope["scope_digest"]}
  if all(row["identity"] is None for row in selected):
    return {"reason": "live-candidate-unfrozen", "scope_digest": scope["scope_digest"]}
  runtime = inspect_runtime(args.runtime)
  system, architecture = runtime.platform.split("-", 1)
  platform = {"os": system, "architecture": architecture, "engine": runtime.engine}
  rows = [row for row in selected if row["platform"] == platform]
  if len(rows) != 1 or runtime.profile != args.profile: raise ConfigError("pi-live-platform-selection")
  item = rows[0]
  if item["applicability"] == "not_selected": return {"reason": "live-capability-not-selected", "scope_digest": scope["scope_digest"]}
  if item["identity"] is None: return {"reason": "live-candidate-unfrozen", "scope_digest": scope["scope_digest"]}
  report_path = args.native_report.absolute()
  with Tree(report_path.parent, private=False) as tree: raw = tree.read(report_path.name, max_bytes=8 * 1024 * 1024)
  if raw is None: return {"reason": "native-report-missing", "scope_digest": scope["scope_digest"]}
  if raw[1] & 0o022: raise Conflict("PI_NATIVE_REPORT_WRITABLE_BY_OTHERS")
  native = json.loads(raw[0])
  native_case = "optional-services" if item["capability_id"] in ("mcp", "web", "terminal") else args.case
  reason = native_prerequisite(native, runtime, native_case)
  if reason: return {"reason": reason, "scope_digest": scope["scope_digest"]}
  workspace = load_workspace(args.local, args.profile, repository=ROOT)
  lock = workspace.backend.read_lock(ROOT)
  if (workspace.agent != "pi" or lock.identity != runtime.lock_identity
      or workspace.backend.runtime_identity(workspace, lock) != runtime.identity
      or workspace.backend.root(workspace, runtime.identity) != runtime.root):
    raise Conflict("PI_LIVE_RUNTIME_INSTANCE_MISMATCH")
  with Tree(workspace.state_root) as tree:
    if tree.read("pending.json") is not None: raise Conflict("PI_LIVE_DEPLOYMENT_PENDING")
    current = read_state(tree)["current"]
  if (not current or current["binding"] != workspace.binding or current["launch"].get("runtime_identity") != runtime.identity
      or current["launch"]["lock_identity"] != runtime.lock_identity): raise Conflict("PI_LIVE_DEPLOYMENT_MISMATCH")
  candidate = workspace.candidate(lock.identity)
  if current["generation"] != candidate.generation or current["launch"] != record(workspace, lock):
    return {"reason": "live-configuration-not-deployed", "scope_digest": scope["scope_digest"]}
  try: assert_inactive(workspace.state_root)
  except Conflict: return {"reason": "live-instance-active", "scope_digest": scope["scope_digest"]}
  identity = diagnostic_identity({"data": workspace.resolved.data, "repository": workspace.repository,
    "lock_identity": lock.identity, "runtime_identity": runtime.identity})
  if identity != item["identity"]: return {"reason": "live-scope-identity-stale", "scope_digest": scope["scope_digest"]}
  project = args.project.absolute().resolve(strict=True)
  roots = workspace.resolved.data["profile"]["agent_options"].get("paths", {}).get("roots", {})
  if not project.is_dir() or not any(row["purpose"] == "project" and project.is_relative_to(Path(row["path"]).resolve(strict=True)) for row in roots.values()):
    raise ConfigError("pi-live-project-unbound")
  return {"workspace": workspace, "runtime": runtime, "item": item, "project": project,
    "identity": identity, "scope_digest": scope["scope_digest"], "native_report_digest": digest(native),
    "native_transports": sorted({row.get("facts", {}).get("transport") for row in native["results"] if row.get("facts", {}).get("transport") in ("direct", "proxy")}),
    "native_proxy_authentication": any(row.get("facts", {}).get("proxy_authentication_verified") is True for row in native["results"]),
    "native_services": sorted({row.get("facts", {}).get("capability") for row in native["results"] if row.get("facts", {}).get("capability") in ("mcp", "web", "terminal")})}


def execute(args):
  if args.allow_host is not True or args.allow_live is not True: raise ConfigError("pi-live-authorization")
  context = inspect_context(args)
  base = {"schema_version": 1, "tier": "live", "case": args.case, "scope_digest": context["scope_digest"]}
  if context.get("reason"): return {**base, "status": "not-run", "results": [], "reason": context["reason"]}
  capability = context["item"]["capability_id"]
  if capability not in ("codex", "cursor", "proxy", "mcp", "web", "terminal", "task-keeper"):
    return {**base, "status": "not-run", "results": [], "reason": "live-scenario-runner-not-ready"}
  if capability in ("mcp", "web", "terminal") and capability not in context["native_services"]:
    return {**base, "status": "not-run", "results": [], "reason": "live-native-service-not-covered"}
  started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
  operation = execute_services if capability in ("mcp", "web", "terminal", "task-keeper") else execute_delegate
  result = operation(context, recheck=lambda: inspect_context(args))
  return {**base, "status": result["status"], "results": [result], "runtime": context["runtime"].public_identity(),
    "native_report_digest": context["native_report_digest"], "identity": context["identity"],
    "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "limitations": ["live evidence covers this selected scope item only"]}
