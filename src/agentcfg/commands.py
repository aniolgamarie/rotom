"""统一命令入口：显式副作用边界，输出默认脱敏。"""

from dataclasses import dataclass
import inspect
from contextlib import nullcontext
from pathlib import Path
import sys

from . import deployment, runtime
from .config import public_diagnostics
from .local import initialize_local
from .progress import Progress, failure_context
from .setup_preview import setup_plan_digest
from .schema import ConfigError
from .storage import Conflict, Tree
from .workspace import load_workspace
from .presentation import command_line, emit_result, table


def workspace(args):
  result = load_workspace(args.local, args.profile)
  if getattr(args, "agent", None) not in (None, result.agent):
    from .schema import ConfigError
    raise ConfigError("agent-profile-mismatch")
  return result


def output(w, command, result, *, args=None):
  emit_result({"command": command, "agent": w.agent, "profile": w.profile,
    "instance": str(w.instance), **result}, args=args)
  return 0


def cmd_init_local(args):
  context = getattr(args, "invocation_context", None)
  if context is not None and "command" not in context.explicit_fields:
    context.input_gateway.confirm("初始化所选机器配置与共享占位文件", policy=context.input_policy)
  result = initialize_local(args.machine, config_home=args.local.parent.parent.parent,
    profile_id=args.init_profile)
  actions = {"created": "已创建", "supplemented": "已补齐", "unchanged": "无需变化"}
  print(f"配置占位检查  {args.machine} / {result.profile}\n")
  print(f"机器配置  {actions[result.machine_action]}\n  {result.machine_path}")
  if result.local_fields:
    print("  新增 URL 字段：" + ", ".join(result.local_fields))
  print(f"密钥文件  {actions[result.secrets_action]}\n  {result.secrets_path}")
  if result.secret_fields:
    print("  新增 key 字段：" + ", ".join(result.secret_fields))
  print("\n可直接编辑上述文件；查看待填写项：")
  print("  " + command_line(args, "model", "status", profile=result.profile))
  return 0


def cmd_profiles(args):
  from .local import available_profiles
  profiles = available_profiles()
  if sys.stdout.isatty():
    print("可用配置\n")
    table(("Profile", "工具"), profiles)
    print("\n初始化或补齐：./agentcfg init-local --machine NAME --profile ID")
  else:
    for profile_id, agent in profiles:
      print(f"{profile_id}\t{agent}")
  return 0


def cmd_model(args):
  from .model_wizard import add_model, enable_preset, list_presets, model_status
  if args.model_command == "presets":
    return list_presets(args)
  if args.model_command == "status":
    return model_status(args)
  if args.model_command == "key":
    from .model_keys import set_model_key
    return set_model_key(args)
  if args.model_command == "url":
    from .model_urls import set_model_url
    return set_model_url(args)
  if args.model_command == "enable":
    return enable_preset(args)
  return add_model(args)


def prepared(args):
  w = workspace(args)
  lock = w.backend.read_lock(w.repository)
  # 消费所选 profile 的完整依赖身份，再进行任何渲染或部署。
  runtime.runtime_identity(w, lock)
  return w, lock, w.candidate(lock.identity)


def cmd_validate(args):
  Progress("validate", args).stage("校验配置、引用与锁", hint="doctor")
  w, lock, candidate = prepared(args)
  return output(w, "validate", {"valid": True, "artifacts": len(candidate.artifacts),
    "profiles_checked": w.resolved.validated_profiles, "credentials": "not-checked-offline"}, args=args)


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
  return output(w, "render", {"artifacts": len(candidate.artifacts), "cache": str(w.cache / "rendered" / candidate.generation)}, args=args)


def current_plan(w, lock, candidate):
  with Tree(w.state_root) as state, Tree(w.instance) as target:
    deployment.guard_saved_state(state, getattr(w.adapter, "validate_deployment_state", None))
    if state.read("pending.json"):
      raise Conflict("存在待恢复部署；请先执行 apply 或 rollback")
    return deployment.plan(target, deployment.read_state(state), candidate, w.binding, runtime.record(w, lock))


def cmd_plan(args):
  Progress("plan", args).stage("检查配置与部署差异", hint="doctor")
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
  output(w, "plan", result, args=args)
  return 4 if plan.conflicts else 0


def migration_plan(args):
  """提案使用有效机器的私人缓存，不依赖尚未安装的 Pi 或虚构适配器。"""
  from .pi_inventory import build_inventory
  from .paths import safe_id
  w = load_workspace(args.local, args.profile)
  target_profile = args.profile
  safe_id(target_profile)
  report = build_inventory(args.from_pi_home, repository=w.repository, profile=target_profile)
  cache = Path(w.resolved.data["machine"]["paths"]["cache_root"]) / "migration" / target_profile
  with Tree(cache, create=True) as output_tree:
    output_tree.write_state("inventory.json", deployment.json_bytes(report))
  emit_result({"command": "plan", "agent": "pi", "profile": target_profile,
    "mode": "migration-preview", "items": len(report["items"]), "blockers": len(report["blockers"]),
    "ready_to_deploy": False, "proposal": str(cache / "inventory.json")}, args=args)
  return 0


def cmd_apply(args):
  Progress("apply", args).stage("复核并部署配置", hint="plan")
  w, lock, candidate = prepared(args)
  return output(w, "apply", apply_candidate(w, lock, candidate), args=args)


def apply_candidate(w, lock, candidate, *, expected_plan=None, maintenance=None):
  guard = getattr(w.adapter, "apply_lifecycle_guard", None) or getattr(w.adapter, "lifecycle_guard", None)
  guard_for = getattr(w.adapter, "apply_lifecycle_guard_for", None)
  if maintenance is not None and guard_for is None:
    raise Conflict("维护 setup 需要支持维护准入的原部署门禁")
  options = {"maintenance": maintenance} if maintenance is not None else {}
  admission = guard_for(w, lock, **options) if guard_for is not None else guard(w) if guard else nullcontext()
  with admission as instance_fd:
    apply_options = {"maintenance_guard": lambda state_fd: maintenance.apply_guard(w, lock, candidate,
      expected_plan, instance_fd=instance_fd, state_fd=state_fd)} if maintenance is not None else {}
    return deployment.apply(w.instance, w.state_root, candidate, w.binding, runtime.record(w, lock),
      expected_plan=expected_plan, state_guard=getattr(w.adapter, "validate_deployment_state", None),
      prepare=lambda launch: prepare_launch(w, launch), **apply_options)


def prepare_launch(workspace, launch):
  """调用者持物理实例和部署状态排他锁；只准备已声明资源，不安装依赖。"""
  root = workspace.backend.root(workspace, launch.get("runtime_identity", launch["lock_identity"]))
  workspace.adapter.prepare_runtime(workspace, root)


def sync_backend(w, lock, progress, proxy=None, *, maintenance=None):
  """可选进度/代理/维护准入能力；旧扩展后端继续使用原有双参数 sync 契约。"""
  action = w.backend.sync
  try:
    parameters = inspect.signature(action).parameters
  except (TypeError, ValueError):
    parameters = {}
  var_keyword = any(item.kind is inspect.Parameter.VAR_KEYWORD for item in parameters.values())
  options = {}
  if maintenance is not None:
    parameter = parameters.get("maintenance")
    if parameter is None or parameter.kind not in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY):
      raise Conflict("维护 setup 需要后端显式支持维护同步准入")
    options["maintenance"] = maintenance
  if "progress" in parameters or var_keyword:
    options["progress"] = progress
  else:
    progress("检查运行包")
  if proxy is not None and ("proxy" in parameters or var_keyword):
    options["proxy"] = proxy
  return action(w, lock, **options)


@dataclass(frozen=True)
class SetupResult:
  workspace: object
  code: int
  result: object
  reason: str | None = None
  hint: str | None = None


def _setup_operation(args, *, progress, preview, approve, maintenance=None) -> SetupResult:
  """可信内部复用接口，不授予维护权限；副作用仍通过原有 guard。

  preview 只展示；approve 通过抛异常拒绝，不接受用户 JSON 或布尔许可。
  """
  progress.stage("校验配置与锁", hint="validate")
  w, lock, candidate = prepared(args)
  progress.stage("预览部署差异", hint="plan")
  plan = current_plan(w, lock, candidate)
  summary = plan.public()
  initial_digest = setup_plan_digest(w, lock, candidate, plan) if not (plan.conflicts or plan.drift) else None
  preview(w, summary)
  if plan.conflicts or plan.drift:
    return SetupResult(w, 4, None, "存在冲突或漂移，部署已停止。", "plan")
  approve(w, lock, candidate, plan)
  options = {"maintenance": maintenance} if maintenance is not None else {}
  pre_sync_preflight = getattr(w.adapter, "pre_sync_preflight", None)
  if pre_sync_preflight is not None:
    pre_sync_preflight(w, **options)
  prepare_resources = getattr(w.adapter, "prepare_setup_resources", None)
  if prepare_resources is not None:
    prepare_resources(w, lock, **options)
  progress.stage("同步依赖（缺失时可能联网）", hint="doctor")
  with progress.heartbeat():
    sync_backend(w, lock, progress.sync_stage, **options)
  # 同步期间来源或目标可能改变；重新读取并比对预览，再进入 apply 的写入门禁。
  progress.stage("复核配置与部署计划", hint="plan")
  current, current_lock, current_candidate = prepared(args)
  updated = current_plan(current, current_lock, current_candidate)
  if (current_candidate.generation != candidate.generation or current_lock.identity != lock.identity
      or updated.public() != summary
      or setup_plan_digest(current, current_lock, current_candidate, updated) != initial_digest):
    return SetupResult(current, 4, None, "同步期间配置或目标发生变化；请重新运行 setup。", "setup")
  progress.stage("写入部署", hint="plan")
  result = apply_candidate(current, current_lock, current_candidate, expected_plan=updated, **options)
  return SetupResult(current, 0, result)


def cmd_setup(args):
  progress = Progress("setup", args)
  def preview(w, summary):
    context = getattr(args, "invocation_context", None)
    preview_stream = sys.stderr if context is not None else sys.stdout
    print(f"部署预览  {w.agent} / {w.profile}", file=preview_stream, flush=True)
    print(f"  变更 {summary['changes']}  ·  漂移 {summary['drift']}  ·  冲突 {summary['conflicts']}", file=preview_stream, flush=True)
  def approve(w, lock, candidate, plan):
    context = getattr(args, "invocation_context", None)
    if context is not None and "command" not in context.explicit_fields:
      context.input_gateway.confirm("按此预览同步依赖并部署", policy=context.input_policy)
  outcome = _setup_operation(args, progress=progress, preview=preview, approve=approve)
  if outcome.code:
    failure_context(args, outcome.code, reason=outcome.reason, hint=outcome.hint)
    return outcome.code
  current, result = outcome.workspace, outcome.result
  state = f"已应用 {result['changes']} 项变更" if result["changes"] else "配置已同步，无需修改"
  print(f"\n部署完成  {current.agent} / {current.profile}\n  {state}", flush=True)
  print("下一步:\n  " + command_line(args, "run"), flush=True)
  return 0


def cmd_rollback(args):
  w = workspace(args)
  guard = getattr(w.adapter, "lifecycle_guard", None)
  with guard(w) if guard else nullcontext():
    return output(w, "rollback", deployment.rollback(w.instance, w.state_root, w.binding,
      prepare=lambda launch: prepare_launch(w, launch)), args=args)


def cmd_lock(args):
  proxy_name = getattr(args, "proxy", None)
  if getattr(args, "agent", None) == "omp":
    if proxy_name is not None:
      from .schema import ConfigError
      raise ConfigError("lock-proxy-unsupported")
    from .omp_dependencies import OmpBackend
    repository = Path(__file__).resolve().parents[2]
    OmpBackend().resolve_lock(repository)
    emit_result({"command": "lock", "agent": "omp", "locked": True}, args=args)
    return 0
  w = workspace(args)
  from .execution_environment import selected_proxy
  _, proxy = selected_proxy(w.resolved.data["machine"], proxy_name)
  resolve_for = getattr(w.backend, "resolve_lock_for", None)
  action = resolve_for if resolve_for is not None else w.backend.resolve_lock
  target = w if resolve_for is not None else w.repository
  if proxy is None:
    action(target)
    return output(w, "lock", {"locked": True}, args=args)
  import inspect
  try:
    parameters = inspect.signature(action).parameters
  except (TypeError, ValueError):
    parameters = {}
  accepts = "proxy" in parameters or any(
    parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
  if not accepts:
    from .schema import ConfigError
    raise ConfigError("lock-proxy-unsupported")
  action(target, proxy=proxy)
  return output(w, "lock", {"locked": True}, args=args)


def cmd_sync(args):
  progress = Progress("sync", args)
  progress.stage("校验配置与锁", hint="validate")
  w = workspace(args)
  from .execution_environment import selected_proxy
  _, proxy = selected_proxy(w.resolved.data["machine"], getattr(args, "proxy", None))
  lock = w.backend.read_lock(w.repository)
  progress.stage("同步依赖", hint="doctor")
  with progress.heartbeat():
    result = sync_backend(w, lock, progress.sync_stage, proxy=proxy)
  return output(w, "sync", result, args=args)


def _run_followup(args, context, original_code):
  """失败后的查看/准备是独立动作，原启动结果不被覆盖。"""
  from dataclasses import replace
  import shlex
  from rotom.context import InputError, TypedInvocation
  scope = replace(context.scope, profile=args.profile)
  invocation = TypedInvocation(replace(context, scope=scope), ())
  print(f"run: 保留原启动结果（退出码 {original_code}）；可显式查看计划或准备部署：", file=sys.stderr)
  for name in ("plan", "setup"):
    print("  " + shlex.join(invocation.advice_tokens(("agent", name))), file=sys.stderr)
  if not context.input_gateway.allows_input(context.input_policy):
    return
  try:
    action = context.input_gateway.choose([("plan", "只读查看同范围计划"),
      ("setup", "另行审阅并准备部署；准备后不自动启动"), ("return", "保留原启动结果并结束")],
      policy=context.input_policy, label="失败后续")
    if action == "return":
      return
    selected = replace(context, command_path=("agent", action), scope=scope,
      explicit_fields=context.explicit_fields - {"command"})
    from .cli import main
    tokens = []
    if scope.machine is not None:
      tokens += ["--machine", scope.machine]
    elif scope.local is not None:
      tokens += ["--local", scope.local]
    tokens += ["--profile", args.profile, action]
    code = main(tokens, context=selected)
    print(f"run: 独立后续 {action} 退出码 {code}；原启动结果仍为 {original_code}", file=sys.stderr)
  except InputError:
    print(f"run: 后续未接受，已取消；原启动结果仍为 {original_code}", file=sys.stderr)


def cmd_run(args):
  Progress("run", args).stage("检查部署、依赖与启动条件", hint="doctor")
  w = workspace(args)
  context = getattr(args, "invocation_context", None)
  options = {}
  if context is not None:
    from dataclasses import replace
    import shlex
    from rotom.context import TypedInvocation
    scope = replace(context.scope, profile=w.profile)
    invocation = TypedInvocation(replace(context, scope=scope), ())
    def notice(status):
      if status == "current":
        return
      reason = "检查时观察到运行包声明有待更新；继续使用已部署运行包" if status == "pending" else "更新状态无法核实；继续使用已部署运行包"
      print("run: " + reason, file=sys.stderr)
      print("显式检查与部署：\n  " + shlex.join(invocation.advice_tokens(("agent", "plan")))
        + "\n  " + shlex.join(invocation.advice_tokens(("agent", "apply"))), file=sys.stderr)
    options["runtime_notice"] = notice
    options["observed_identity"] = runtime.current_identity_snapshot(w)
  try:
    code = runtime.run(w, cwd=args.cwd.absolute(), arguments=args.passthrough,
      inherit_env=getattr(args, "inherit_env", ()), unset_env=getattr(args, "unset_env", ()),
      proxy=getattr(args, "proxy", None), **options)
  except Conflict as error:
    if context is not None:
      _run_followup(args, context, error.exit_code)
    raise
  if code:
    print(f"run: 原生进程已退出（退出码 {code}）", file=sys.stderr)
    print("检查离线状态：\n  " + command_line(args, "doctor"), file=sys.stderr)
  return code


def cmd_usage(args):
  from .usage import run_managed
  return run_managed(workspace(args), args.passthrough)


def cmd_inventory(args):
  from .omp_inventory import write_inventory
  w = workspace(args)
  return output(w, "inventory", write_inventory(w, args.source), args=args)


def doctor_verification(report):
  """只描述本次doctor实际完成的管理检查，不推断原生或账号证据。"""
  dependencies = {"installed": "passed", "damaged": "failed"}.get(report["dependencies"], "not_run")
  if report.get("lock") == "missing-or-invalid":
    dependencies = "blocked"
  if not report["deployed"]:
    deployed = "not_run"
  elif (report.get("lock") == "missing-or-invalid" or report["recovery_pending"]
      or report.get("drift") or report.get("conflicts") or report.get("changes_pending")
      or report.get("deployed_runtime_matches_current") is False
      or report.get("deployed_binding_matches_current") is False):
    deployed = "blocked"
  else:
    deployed = "passed"
  return {"configuration": "passed", "dependencies": dependencies, "deployment": deployed,
    "loading": "not_run", "account": "not_inspected", "runtime": "not_run"}


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
    result["verification"] = doctor_verification(result)
    features = getattr(w.adapter, "feature_readiness", None)
    if features is not None:
      result["feature_readiness"] = features(w.resolved.data)
    approvals = getattr(w.adapter, "approval_diagnostics", None)
    if approvals is not None:
      result["approval_review"] = approvals(w.resolved.data)
    output(w, "doctor", result, args=args)
    print("doctor: 依赖锁缺失或校验失败（退出码 2）；请核对仓库锁文件。", file=sys.stderr)
    print("仅在需要重新解析依赖版本时执行：\n  " + command_line(args, "lock", "--agent", w.agent), file=sys.stderr)
    return 2
  with Tree(w.state_root) as state:
    saved = deployment.read_state(state)
    result = {"deployed": saved["current"] is not None, "previous_backup": saved["previous"] is not None,
      "recovery_pending": state.read("pending.json") is not None,
      "dependencies": dependency_status(w, lock),
      "authentication": "not-inspected; use native auth status", "live": False,
      "notes": list(w.adapter.doctor({}))}
  result["required_toolchain"] = w.backend.toolchain(lock)
  features = getattr(w.adapter, "feature_readiness", None)
  if features is not None:
    result["feature_readiness"] = features(w.resolved.data)
  approvals = getattr(w.adapter, "approval_diagnostics", None)
  if approvals is not None:
    result["approval_review"] = approvals(w.resolved.data)
  if getattr(args, "environment", False):
    result["environment"] = runtime.environment_diagnostics(w, saved["current"])
  identity_report = getattr(w.adapter, "identity_diagnostics", None)
  if identity_report is not None:
    result["identity"] = identity_report(w)
  platforms = lock.metadata.get("platforms", {})
  result["platform_evidence"] = platforms.get(sys.platform, "not-recorded") if isinstance(platforms, dict) else "not-recorded"
  if saved["current"] is not None:
    launch = saved["current"]["launch"]
    validate_binding = getattr(w.adapter, "validate_runtime_binding", None)
    if validate_binding is not None:
      try:
        validate_binding(w, launch.get("adapter_binding"))
      except Conflict:
        result["deployed_binding_matches_current"] = False
      else:
        result["deployed_binding_matches_current"] = True
    result["deployed_runtime_matches_current"] = launch.get("runtime_identity", launch["lock_identity"]) == runtime.runtime_identity(w, lock)
    result["deployed_dependencies"] = w.backend.status(w, launch.get("runtime_identity", launch["lock_identity"]))
  drift = None
  if result["deployed"] and not result["recovery_pending"]:
    drift = current_plan(w, lock, w.candidate(lock.identity))
    result.update(drift=bool(drift.drift), conflicts=bool(drift.conflicts), changes_pending=len(drift.changes))
  result["diagnostics"] = write_diagnostics(w, lock, drift)
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
  result["verification"] = doctor_verification(result)
  output(w, "doctor", result, args=args)
  return 0


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
  return output(w, "capture", {"captured_fields": len(projection), "proposal": str(w.cache / "proposals/capture.json")}, args=args)


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
