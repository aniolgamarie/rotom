"""统一命令入口：显式副作用边界，输出默认脱敏。"""

import json
from pathlib import Path

from . import dependencies, deployment, runtime
from .config import public_diagnostics
from .local import initialize_local
from .storage import Conflict, Tree
from .workspace import load_workspace


def workspace(args):
  return load_workspace(args.local, args.profile)


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
  lock = dependencies.read_lock(w.repository)
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
  w, lock, candidate = prepared(args)
  plan = current_plan(w, lock, candidate)
  result = plan.public()
  result["sources"] = [{"field": ".".join(path), "source": layer} for path, layer in public_diagnostics(w.resolved)]
  result["dependencies"] = "installed" if dependencies.installed(w, lock) else "sync-required"
  output(w, "plan", result)
  return 4 if plan.conflicts else 0


def cmd_apply(args):
  w, lock, candidate = prepared(args)
  result = deployment.apply(w.instance, w.state_root, candidate, w.binding, runtime.record(w, lock))
  return output(w, "apply", result)


def cmd_rollback(args):
  w = workspace(args)
  return output(w, "rollback", deployment.rollback(w.instance, w.state_root, w.binding))


def cmd_lock(args):
  w = workspace(args)
  dependencies.resolve_lock(w.repository)
  return output(w, "lock", {"locked": True})


def cmd_sync(args):
  w = workspace(args)
  return output(w, "sync", dependencies.sync(w, dependencies.read_lock(w.repository)))


def cmd_run(args):
  w = workspace(args)
  return runtime.run(w, cwd=args.cwd.absolute(), arguments=args.passthrough)


def cmd_doctor(args):
  w = workspace(args)
  lock = dependencies.read_lock(w.repository)
  with Tree(w.state_root) as state:
    saved = deployment.read_state(state)
    result = {"deployed": saved["current"] is not None, "previous_backup": saved["previous"] is not None,
      "recovery_pending": state.read("pending.json") is not None,
      "dependencies": "installed" if dependencies.installed(w, lock) else "sync-required",
      "authentication": "not-inspected; use native auth status", "live": False,
      "notes": list(w.adapter.doctor({}))}
  result["required_toolchain"] = {"node": lock.metadata["node"], "npm": lock.metadata["npm"]}
  if result["deployed"] and not result["recovery_pending"]:
    drift = current_plan(w, lock, w.candidate(lock.identity))
    result.update(drift=bool(drift.drift), conflicts=bool(drift.conflicts), changes_pending=len(drift.changes))
  if args.live:
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
  return output(w, "doctor", result)


def cmd_capture(args):
  w = workspace(args)
  with Tree(w.instance) as target:
    projection = w.adapter.capture_projection(target)
  proposal = {"schema_version": 1, "overrides": {"profiles": {w.profile: w.adapter.capture(projection)}}}
  from .schema import validate_document
  validate_document("local", {**proposal, "machine": {"id": w.resolved.data["machine"]["id"]}}, adapter_schemas=w.schemas)
  with Tree(w.cache / "proposals", create=True) as cache:
    cache.write_state("capture.json", deployment.json_bytes(proposal))
  return output(w, "capture", {"captured_fields": len(projection), "proposal": str(w.cache / "proposals/capture.json")})


def cmd_project(args):
  from .project import initialize_openspec
  w = workspace(args)
  return output(w, "project", initialize_openspec(w, dependencies.read_lock(w.repository), args.path.absolute()))
