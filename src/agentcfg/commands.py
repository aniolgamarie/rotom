"""统一命令入口：显式副作用边界，输出默认脱敏。"""

import json
from contextlib import nullcontext
from pathlib import Path

from . import deployment, runtime
from .config import public_diagnostics
from .local import initialize_local
from .storage import Conflict, Tree
from .workspace import load_workspace


def workspace(args):
  result = load_workspace(args.local, args.profile)
  if getattr(args, "agent", result.agent) != result.agent:
    from .schema import ConfigError
    raise ConfigError("agent-profile-mismatch")
  return result


def output(w, command, result):
  print(json.dumps({"command": command, "agent": w.agent, "profile": w.profile,
    "instance": str(w.instance), **result}, ensure_ascii=False, sort_keys=True))
  return 0


def cmd_init_local(args):
  initialize_local(args.machine, config_home=args.local.parent.parent.parent)
  print("init-local: 已创建空密钥本地配置；使用前仍需校验所选 profile")
  return 0


def prepared(args):
  w = workspace(args)
  lock = w.backend.read_lock(w.repository)
  return w, lock, w.candidate(lock.identity)


def cmd_validate(args):
  w, lock, candidate = prepared(args)
  return output(w, "validate", {"valid": True, "artifacts": len(candidate.artifacts),
    "profiles_checked": w.resolved.validated_profiles, "credentials": "not-checked-offline"})


def cmd_render(args):
  w, lock, candidate = prepared(args)
  with Tree(w.cache / "rendered" / candidate.generation, create=True) as cache:
    for artifact in candidate.artifacts:
      name = artifact.target.path
      if artifact.target.selector:
        import hashlib
        name = "field-intents/" + hashlib.sha256((name + artifact.target.selector).encode()).hexdigest() + ".json"
      old = cache.read(name)
      if old is None or (old[0], old[1]) != (artifact.content, artifact.mode):
        cache.replace(name, artifact.content, artifact.mode, expected=old[2] if old else None)
  return output(w, "render", {"artifacts": len(candidate.artifacts), "cache": str(w.cache / "rendered" / candidate.generation)})


def current_plan(w, lock, candidate):
  with Tree(w.state_root) as state, Tree(w.instance) as target:
    if state.read("pending.json"):
      raise Conflict("存在待恢复部署；请先执行 apply 或 rollback")
    return deployment.plan(target, deployment.read_state(state), candidate, w.binding, runtime.record(w, lock))


def cmd_plan(args):
  if getattr(args, "from_starter", None) is not None and getattr(args, "from_pi_home", None) is None:
    from .schema import ConfigError
    raise ConfigError("pi-source-requires-home")
  if getattr(args, "from_pi_home", None) is not None:
    return migration_plan(args)
  w, lock, candidate = prepared(args)
  plan = current_plan(w, lock, candidate)
  result = plan.public()
  result["sources"] = [{"field": ".".join(path), "source": layer} for path, layer in public_diagnostics(w.resolved)]
  result["dependencies"] = dependency_status(w, lock)
  identity_report = getattr(w.adapter, "identity_diagnostics", None)
  if identity_report is not None:
    result["identity"] = identity_report(w)
  upgrade = getattr(w.adapter, "upgrade_diagnostics", None)
  if upgrade is not None:
    with Tree(w.state_root) as state:
      result["upgrade"] = upgrade({"current": deployment.read_state(state)["current"], "candidate": candidate, "runtime_identity": runtime.runtime_identity(w, lock)})
  result["diagnostics"] = write_diagnostics(w, lock, plan)
  output(w, "plan", result)
  return 4 if plan.conflicts else 0


def migration_plan(args):
  """提案使用有效机器的私人缓存，不依赖尚未安装的 Pi 或虚构适配器。"""
  from .pi_inventory import build_inventory
  from .paths import safe_id
  w = load_workspace(args.local)
  target_profile = args.profile if args.profile.startswith("pi-") else "pi-default"
  safe_id(target_profile)
  report = build_inventory(args.from_pi_home, getattr(args, "from_starter", None), repository=w.repository)
  overrides = report["proposed_overrides"]
  if "pi-default" in overrides.get("profiles", {}) and target_profile != "pi-default":
    overrides["profiles"][target_profile] = overrides["profiles"].pop("pi-default")
  cache = Path(w.resolved.data["machine"]["paths"]["cache_root"]) / "migration" / target_profile
  with Tree(cache, create=True) as output_tree:
    output_tree.write_state("inventory.json", deployment.json_bytes(report))
  print(json.dumps({"command": "plan", "agent": "pi", "profile": target_profile,
    "mode": "migration-preview", "items": len(report["items"]), "blockers": len(report["blockers"]),
    "ready_to_deploy": False, "proposal": str(cache / "inventory.json")}, ensure_ascii=False, sort_keys=True))
  return 0


def cmd_apply(args):
  w, lock, candidate = prepared(args)
  guard = getattr(w.adapter, "apply_lifecycle_guard", None) or getattr(w.adapter, "lifecycle_guard", None)
  with guard(w) if guard else nullcontext():
    result = deployment.apply(w.instance, w.state_root, candidate, w.binding, runtime.record(w, lock))
  return output(w, "apply", result)


def cmd_rollback(args):
  w = workspace(args)
  guard = getattr(w.adapter, "lifecycle_guard", None)
  with guard(w) if guard else nullcontext():
    return output(w, "rollback", deployment.rollback(w.instance, w.state_root, w.binding))


def cmd_lock(args):
  if getattr(args, "agent", None) == "omp":
    from .omp_dependencies import OmpBackend
    repository = Path(__file__).resolve().parents[2]
    OmpBackend().resolve_lock(repository)
    print(json.dumps({"command": "lock", "agent": "omp", "locked": True}, ensure_ascii=False, sort_keys=True))
    return 0
  w = workspace(args)
  w.backend.resolve_lock(w.repository)
  return output(w, "lock", {"locked": True})


def cmd_sync(args):
  w = workspace(args)
  return output(w, "sync", w.backend.sync(w, w.backend.read_lock(w.repository)))


def cmd_run(args):
  w = workspace(args)
  return runtime.run(w, cwd=args.cwd.absolute(), arguments=args.passthrough)


def cmd_usage(args):
  from .usage import run_managed
  return run_managed(workspace(args), args.passthrough)


def cmd_inventory(args):
  from .omp_inventory import write_inventory
  w = workspace(args)
  return output(w, "inventory", write_inventory(w, args.source))


def cmd_recover(args):
  from .pi_recovery import recover
  w, result = recover(args)
  return output(w, "recover", result)


def cmd_doctor(args):
  w = workspace(args)
  lock = w.backend.read_lock(w.repository)
  with Tree(w.state_root) as state:
    saved = deployment.read_state(state)
    result = {"deployed": saved["current"] is not None, "previous_backup": saved["previous"] is not None,
      "recovery_pending": state.read("pending.json") is not None,
      "dependencies": dependency_status(w, lock),
      "authentication": "not-inspected; use native auth status", "live": False,
      "notes": list(w.adapter.doctor({}))}
  result["required_toolchain"] = w.backend.toolchain(lock)
  identity_report = getattr(w.adapter, "identity_diagnostics", None)
  if identity_report is not None:
    result["identity"] = identity_report(w)
  import sys
  platforms = lock.metadata.get("platforms", {})
  result["platform_evidence"] = platforms.get(sys.platform, "not-recorded") if isinstance(platforms, dict) else "not-recorded"
  if saved["current"] is not None:
    launch = saved["current"]["launch"]
    result["deployed_dependencies"] = w.backend.status(w, launch.get("runtime_identity", launch["lock_identity"]))
  drift = None
  if result["deployed"] and not result["recovery_pending"]:
    drift = current_plan(w, lock, w.candidate(lock.identity))
    result.update(drift=bool(drift.drift), conflicts=bool(drift.conflicts), changes_pending=len(drift.changes))
  result["diagnostics"] = write_diagnostics(w, lock, drift)
  capabilities = getattr(w.adapter, "capability_diagnostics", lambda _: None)({"data": w.resolved.data, "repository": w.repository, "deployed": result["deployed"] and not result["recovery_pending"] and not result.get("changes_pending") and not result.get("conflicts"),
    "dependencies": result["dependencies"], "lock_identity": lock.identity, "runtime_identity": runtime.runtime_identity(w, lock)})
  if capabilities is not None: result["capabilities"] = capabilities
  if args.live:
    checks = getattr(w.adapter, "live_diagnostics", lambda _: None)(w.resolved.data)
    if checks is None:
      import urllib.request
      checks = []
      for provider in w.resolved.data["providers"].values():
        if provider["auth_kind"] == "api-key":
          try:
            with urllib.request.urlopen(urllib.request.Request(provider["base_url"], method="HEAD"), timeout=5):
              checks.append("reachable")
          except Exception:
            checks.append("unverified")
    result.update(live=True, service_checks=checks)
  output(w, "doctor", result)
  return getattr(w.adapter, "diagnostic_exit_code", lambda _: 0)(capabilities)


def cmd_capture(args):
  w = workspace(args)
  validate_binding = getattr(w.adapter, "validate_runtime_binding", None)
  guard = getattr(w.adapter, "lifecycle_guard", None) if validate_binding is not None else None
  with (guard(w) if guard else nullcontext()), Tree(w.state_root) as state:
    from .storage import instance_lock
    with instance_lock(state) if validate_binding is not None else nullcontext():
      current = deployment.read_state(state)["current"]
      if validate_binding is not None:
        if state.read("pending.json") or current is None or current["binding"] != w.binding:
          raise Conflict("capture需要匹配的已部署身份且无待恢复事务")
        validate_binding(w, current["launch"].get("adapter_binding"))
      with Tree(w.instance) as target:
        # 受管OMP逐项强制分类，删除guard不能让历史秘密叶子进入投影。
        if current:
          for item in current["items"].values():
            if item.get("guard") is not None or validate_binding is not None:
              deployment.projection(target, item)
        capture_for = getattr(w.adapter, "capture_projection_for", None)
        projection = capture_for(w, target) if capture_for is not None else w.adapter.capture_projection(target)
  captured = w.adapter.capture_configuration(projection, w.resolved.data)
  proposal = {"schema_version": 1, "overrides": {"profiles": {w.profile: captured}}}
  from .schema import validate_document
  validate_document("local", {**proposal, "machine": {"id": w.resolved.data["machine"]["id"]}}, adapter_schemas=w.schemas)
  checked = load_workspace(w.local_path, w.profile, repository=w.repository, proposal=proposal)
  checked.candidate(w.backend.read_lock(w.repository).identity)
  with Tree(w.cache / "proposals", create=True) as cache:
    cache.write_state("capture.json", deployment.json_bytes(proposal))
  return output(w, "capture", {"captured_fields": len(projection), "proposal": str(w.cache / "proposals/capture.json")})


def cmd_project(args):
  from .project import initialize_openspec
  w = workspace(args)
  return output(w, "project", initialize_openspec(w, w.backend.read_lock(w.repository), args.path.absolute()))


def dependency_status(w, lock):
  status = w.backend.status(w, runtime.runtime_identity(w, lock))
  return "sync-required" if status == "missing" else status


def write_diagnostics(w, lock, plan=None):
  """仅存非秘密定位信息；不读取 OAuth 或 SecretStore，不保存字段值。"""
  from .secrets import credential_id
  contracts = [runtime.record(w, lock)]
  with Tree(w.state_root) as state:
    current = deployment.read_state(state)["current"]
    if current:
      contracts.append(current["launch"])
  references = {e["secret_ref"] for contract in contracts for e in contract["environment"] if "secret_ref" in e}
  document = {"credentials": [{"id": credential_id(ref), "reference": ref} for ref in sorted(references)],
              "targets": plan.private_locations() if plan else []}
  with Tree(w.cache / "diagnostics", create=True) as cache:
    cache.write_state("locations.json", deployment.json_bytes(document))
  return str(w.cache / "diagnostics/locations.json")
