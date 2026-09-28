"""统一命令入口：显式副作用边界，输出默认脱敏。"""

import json
import inspect
from contextlib import nullcontext
from pathlib import Path
import sys

from . import deployment, runtime
from .config import public_diagnostics
from .local import initialize_local
from .progress import Progress, failure_context
from .schema import ConfigError
from .storage import Conflict, Tree
from .workspace import load_workspace


def workspace(args):
  result = load_workspace(args.local, args.profile)
  if getattr(args, "agent", None) not in (None, result.agent):
    from .schema import ConfigError
    raise ConfigError("agent-profile-mismatch")
  return result


def output(w, command, result):
  print(json.dumps({"command": command, "agent": w.agent, "profile": w.profile,
    "instance": str(w.instance), **result}, ensure_ascii=False, sort_keys=True))
  return 0


def cmd_init_local(args):
  initialize_local(args.machine, config_home=args.local.parent.parent.parent, profile_id=args.init_profile)
  from shlex import quote
  selector = "" if args.machine == "default" else f"--machine {quote(args.machine)} "
  print(f"init-local: 已创建空密钥本地配置；默认 profile 为 {args.init_profile}；下一步: ./agentcfg {selector}setup")
  return 0


def cmd_profiles(args):
  from .local import available_profiles
  for profile_id, agent in available_profiles():
    print(f"{profile_id}\t{agent}")
  return 0


def cmd_model(args):
  from .model_wizard import add_model, enable_preset, list_presets, model_status
  if args.model_command == "presets":
    return list_presets(args)
  if args.model_command == "status":
    return model_status(args)
  if args.model_command == "enable":
    return enable_preset(args)
  return add_model(args)


def prepared(args):
  w = workspace(args)
  lock = w.backend.read_lock(w.repository)
  return w, lock, w.candidate(lock.identity)


def cmd_validate(args):
  Progress("validate", args).stage("校验配置、引用与锁", hint="doctor")
  w, lock, candidate = prepared(args)
  return output(w, "validate", {"valid": True, "artifacts": len(candidate.artifacts),
    "profiles_checked": w.resolved.validated_profiles, "credentials": "not-checked-offline"})


def cmd_render(args):
  Progress("render", args).stage("校验并生成原生产物", hint="validate")
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
  Progress("plan", args).stage("检查配置与部署差异", hint="doctor")
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
  Progress("apply", args).stage("复核并部署配置", hint="plan")
  w, lock, candidate = prepared(args)
  return output(w, "apply", apply_candidate(w, lock, candidate))


def apply_candidate(w, lock, candidate, *, expected_plan=None):
  guard = getattr(w.adapter, "apply_lifecycle_guard", None) or getattr(w.adapter, "lifecycle_guard", None)
  with guard(w) if guard else nullcontext():
    return deployment.apply(w.instance, w.state_root, candidate, w.binding, runtime.record(w, lock),
      expected_plan=expected_plan)


def sync_backend(w, lock, progress):
  """可选进度能力；旧扩展后端继续使用原有双参数 sync 契约。"""
  action = w.backend.sync
  try:
    parameters = inspect.signature(action).parameters
  except (TypeError, ValueError):
    parameters = {}
  if "progress" in parameters or any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
    return action(w, lock, progress=progress)
  progress("检查运行包")
  return action(w, lock)


def cmd_setup(args):
  progress = Progress("setup", args)
  progress.stage("校验配置与锁", hint="validate")
  w, lock, candidate = prepared(args)
  progress.stage("预览部署差异", hint="plan")
  preview = current_plan(w, lock, candidate)
  summary = preview.public()
  print(f"预览 {w.agent}/{w.profile}: {summary['changes']} 项变更，{summary['drift']} 项漂移，{summary['conflicts']} 项冲突", flush=True)
  if preview.conflicts or preview.drift:
    failure_context(args, 4)
    print("setup 已停止：存在冲突或漂移", file=sys.stderr)
    return 4
  pre_sync_preflight = getattr(w.adapter, "pre_sync_preflight", None)
  if pre_sync_preflight is not None:
    pre_sync_preflight(w)
  progress.stage("同步依赖（缺失时可能联网）", hint="doctor")
  with progress.heartbeat():
    sync_backend(w, lock, progress.sync_stage)
  # 同步期间来源或目标可能改变；重新读取并比对预览，再进入 apply 的写入门禁。
  progress.stage("复核配置与部署计划", hint="plan")
  current, current_lock, current_candidate = prepared(args)
  updated = current_plan(current, current_lock, current_candidate)
  if (current_candidate.generation != candidate.generation or current_lock.identity != lock.identity
      or updated.public() != summary):
    failure_context(args, 4)
    print("setup 已停止：同步期间配置或目标发生变化；请重新运行 setup", file=sys.stderr)
    return 4
  progress.stage("写入部署", hint="plan")
  result = apply_candidate(current, current_lock, current_candidate, expected_plan=updated)
  print(f"部署完成 {current.agent}/{current.profile}: {result['changes']} 项变更；现在可以运行 run", flush=True)
  return 0


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
  progress = Progress("sync", args)
  progress.stage("校验配置与锁", hint="validate")
  w = workspace(args)
  lock = w.backend.read_lock(w.repository)
  progress.stage("同步依赖", hint="doctor")
  with progress.heartbeat():
    result = sync_backend(w, lock, progress.sync_stage)
  return output(w, "sync", result)


def cmd_run(args):
  Progress("run", args).stage("检查部署、依赖与启动条件", hint="doctor")
  w = workspace(args)
  code = runtime.run(w, cwd=args.cwd.absolute(), arguments=args.passthrough)
  if code:
    print(f"run: 原生进程已退出（退出码 {code}）；可运行 ./agentcfg doctor 检查离线状态", file=sys.stderr)
  return code


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
  Progress("doctor", args).stage("检查配置、部署与依赖", hint="plan")
  w = workspace(args)
  try:
    lock = w.backend.read_lock(w.repository)
  except ConfigError:
    with Tree(w.state_root) as state:
      saved = deployment.read_state(state)
      result = {"deployed": saved["current"] is not None,
        "recovery_pending": state.read("pending.json") is not None,
        "dependencies": "unknown", "lock": "missing-or-invalid",
        "authentication": "not-inspected; use native auth status", "live": False,
        "readiness": {"status": "action-required", "blockers": ["lock-missing-or-invalid"],
          "next_commands": [f"lock --agent {w.agent}"], "authentication": "not-inspected"}}
    if getattr(args, "input", False):
      from .interaction_diagnostics import terminal_state
      result["input_diagnostics"] = {"diagnostic_terminal": terminal_state(),
        "readiness": result["readiness"], "host_events": {"status": "not-checked", "reason": "先修复依赖锁"},
        "note": "终端标志只描述诊断进程；不记录按键"}
    output(w, "doctor", result)
    print(f"doctor: 依赖锁缺失或校验失败（退出码 2）；检查后运行 ./agentcfg lock --agent {w.agent}", file=sys.stderr)
    return 2
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
  platforms = lock.metadata.get("platforms", {})
  result["platform_evidence"] = platforms.get(sys.platform, "not-recorded") if isinstance(platforms, dict) else "not-recorded"
  if saved["current"] is not None:
    launch = saved["current"]["launch"]
    result["deployed_runtime_matches_current"] = launch.get("runtime_identity", launch["lock_identity"]) == runtime.runtime_identity(w, lock)
    result["deployed_dependencies"] = w.backend.status(w, launch.get("runtime_identity", launch["lock_identity"]))
  drift = None
  if result["deployed"] and not result["recovery_pending"]:
    drift = current_plan(w, lock, w.candidate(lock.identity))
    result.update(drift=bool(drift.drift), conflicts=bool(drift.conflicts), changes_pending=len(drift.changes))
  result["diagnostics"] = write_diagnostics(w, lock, drift)
  capabilities = getattr(w.adapter, "capability_diagnostics", lambda _: None)({"data": w.resolved.data, "repository": w.repository, "deployed": result["deployed"] and not result["recovery_pending"] and not result.get("changes_pending") and not result.get("conflicts") and not result.get("drift"),
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
  if getattr(args, "input", False):
    from .interaction_diagnostics import inspect
    result["input_diagnostics"] = inspect(w, result)
  else:
    from .interaction_diagnostics import readiness
    result["readiness"] = readiness(result)
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
