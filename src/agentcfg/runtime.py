"""使用已部署启动契约；密钥值下次启动解析，不解释未部署的模型变更。"""

from dataclasses import replace
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from types import SimpleNamespace

from .adapter import EnvironmentBinding, LaunchSpec, SecretRef
from .deployment import read_state, recover
from .presentation import command_line
from .lifecycle import CooperativeRunLease
from .process import DependencyError, checked
from .toolchain import ensure_compatible_toolchain, ensure_minimum_toolchain
from .storage import Conflict, Tree, ensure_private, instance_lock
from . import execution_environment as execution_env


def runtime_identity(workspace, lock):
  # 原有后端保持旧锁身份，新增后端可以使用包含平台/切片的安装身份。
  from .paths import safe_id
  resolve = getattr(workspace.backend, "runtime_identity", None)
  identity = resolve(workspace, lock) if resolve is not None else lock.identity
  safe_id(identity)
  return identity


def record(workspace, lock):
  identity = runtime_identity(workspace, lock)
  spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=Path("/"),
    runtime_root=workspace.backend.root(workspace, identity), instance_root=workspace.instance, lock_identity=lock.identity)
  preflight_for = getattr(workspace.adapter, "launch_preflight_for", None)
  preflight = preflight_for(workspace.resolved.data, lock) if preflight_for is not None else workspace.adapter.launch_preflight(lock)
  guards = getattr(workspace.adapter, "runtime_guards", None)
  binding = getattr(workspace.adapter, "runtime_binding", None)
  return {"argv": list(spec.argv), "lock_identity": lock.identity,
    **({"environment_version": 1, "environment_policy": spec.environment_policy,
      "caller_paths": execution_env.caller_paths()} if spec.environment_policy != "legacy" else {}),
    **({"runtime_identity": identity} if identity != lock.identity else {}),
    "shared_files": list(workspace.adapter.shared_files),
    "preflight": preflight,
    **({"runtime_guards": guards(workspace.resolved.data)} if guards is not None else {}),
    "machine": workspace.resolved.data["machine"],
    **({"adapter_binding": binding(workspace.resolved.data, workspace.instance)} if binding is not None else {}),
    "environment": [{"name": e.name, "required": e.required,
      **({"secret_ref": e.value.reference} if isinstance(e.value, SecretRef) else {"literal": e.value})} for e in spec.environment]
      + [{"name": "AGENTCFG_REPOSITORY", "required": True, "literal": str(workspace.repository)},
         {"name": "AGENTCFG_LOCAL_FILE", "required": True, "literal": str(workspace.local_path)},
         {"name": "AGENTCFG_PROFILE", "required": True, "literal": workspace.profile}]}


def decode(value, cwd, arguments):
  return LaunchSpec(tuple(value["argv"]) + tuple(arguments), cwd, value["lock_identity"],
    tuple(EnvironmentBinding(e["name"], SecretRef(e["secret_ref"]) if "secret_ref" in e else e["literal"], e["required"])
          for e in value["environment"]), value.get("runtime_identity", value["lock_identity"]),
    value.get("environment_policy", "legacy"))


def prepare_environment(workspace, contract, spec, *, inherit=(), unset=(), proxy=None):
  from .config import validate_environment_settings
  schemas = getattr(workspace, "schemas", None)
  data = workspace.resolved.data
  if schemas is not None and data.get("adapter_documents"):
    bundle = schemas.bundles[data["profile"]["agent"]]
    policy = bundle.policy(data["adapter_documents"])
    validate_environment_settings({"inherit": list(inherit), "unset": list(unset)},
      policy.credential_targets, reserved_environment=policy.reserved_environment)
  extra = getattr(workspace.adapter, "tool_environment_names", ())
  observed = tuple(item.name for item in spec.environment if isinstance(item.value, str))
  names, caller = execution_env.capture_caller(contract["machine"], inherit, (*extra, *observed))
  result = execution_env.prepare(spec, contract["machine"], caller=caller, inherit=inherit, unset=unset,
    proxy=proxy, extra_names=extra)
  env = execution_env.apply_bindings(result, spec)
  adjust = getattr(workspace.adapter, "adjust_launch_environment", None)
  if adjust is not None:
    env = adjust(workspace, spec, env, contract.get("adapter_binding"))
  if spec.environment_policy == "legacy":
    root = workspace.backend.root(workspace, contract.get("runtime_identity", contract["lock_identity"]))
    env["PATH"] = os.pathsep.join([*(str(path) for path in workspace.backend.executable_paths(root)), env.get("PATH", "")])
  if spec.environment_policy == "isolated":
    # 每次启动生成；只含声明过的非秘密开发环境，不进入部署/渲染或日志。
    env["AGENTCFG_DEVELOPMENT_ENV"] = json.dumps({"version": 1, "values": result.values,
      "unset": sorted(result.removed)}, ensure_ascii=False, separators=(",", ":"))
  sources = {**result.sources, **{item.name: "adapter-policy" for item in spec.environment if isinstance(item.value, str)}}
  return env, execution_env.differences(caller, env, sources=sources, names=names)


def environment_diagnostics(workspace, current):
  if current is None:
    return {"status": "not-deployed", "values": "not-disclosed"}
  contract = current["launch"]
  spec = decode(contract, Path.cwd(), ())
  _, report = prepare_environment(workspace, contract, spec)
  return {"status": "host-preview", "policy": spec.environment_policy, **report,
    "declarations_pending": execution_env.declarations(contract["machine"]) != execution_env.declarations(workspace.resolved.data["machine"]),
    "downstream": "requires per-channel native evidence"}


def current_identity_snapshot(workspace):
  """运行锁外只读观察当前声明；无法核实则不阻塞旧部署。"""
  try:
    lock = workspace.backend.read_lock(workspace.repository)
    return runtime_identity(workspace, lock)
  except Exception:
    # 不输出原始异常，坏锁及读取失败只表示更新状态未知。
    return None


def run_metadata(workspace, current, spec):
  """仅投影已验证部署的非秘密身份；不保存 argv/env，不推导 SessionRef。"""
  try:
    agent = workspace.agent
    relative, kind, variable = {"dsh": ("dsh-home", "dsh-home", "DSH_HOME"),
      "pi": ("pi-home", "pi-home", "PI_CODING_AGENT_DIR"),
      "omp": ("user-home", "omp-managed-home", None)}[agent]
    expected = str(workspace.instance / relative)
    if variable is None:
      # OMP 的受管存储与实际执行 HOME 是两种事实，后者不用于恢复归属。
      home = current["launch"]["adapter_binding"]["identity"]["home"]
    else:
      values = [item.value for item in spec.environment if item.name == variable]
      if len(values) != 1:
        raise ValueError()
      home = values[0]
    if type(home) is not str or home != expected:
      raise ValueError()
    route = [item.value for item in spec.environment if item.name == "AGENTCFG_DSH_EXECUTION"]
    if route and (agent != "dsh" or route != ["ssh"]):
      raise ValueError()
    # resolve遵循symlink/..的真实目录语义，只用于观察，不改原生chdir参数。
    directory = Path(spec.cwd).resolve(strict=True)
    if not directory.is_dir():
      raise ValueError()
    identity = current["launch"].get("runtime_identity", current["launch"]["lock_identity"])
    from .paths import safe_id
    safe_id(identity)
    digest = identity if len(identity) == 64 and all(char in "0123456789abcdef" for char in identity) else hashlib.sha256(identity.encode()).hexdigest()
    return {"agent": agent, "backend": "ssh" if route else "managed", "profile": workspace.profile,
      "machine_ref": {key: workspace.binding[key] for key in ("machine", "local")},
      "start_cwd": {"path": str(directory), "source": "launch-spec", "confirmation": "confirmed",
        "observed_at_ns": time.time_ns()},
      "native_home_ref": {"kind": kind, "path": home, "source": "deployed-contract", "confirmation": "confirmed"},
      "deployed_identity": {"deployment": current["generation"], "runtime": digest}, "coordination_domain": None}
  except (KeyError, TypeError, ValueError, OSError, RuntimeError):
    raise Conflict("无法从已部署契约核实运行归属、目录或受管存储") from None


def check_deployed_resources(current, target):
  contract = current["launch"]
  from .deployment import projection, same
  guards = contract.get("runtime_guards", {"files": [], "roots": []})
  if not isinstance(guards, dict) or set(guards) != {"files", "roots"} or any(not isinstance(guards[key], list) for key in guards):
    raise Conflict("保存的启动资源保护声明无效")
  for item in current["items"].values():
    if item.get("guard"):
      projection(target, item)
    if item["path"] in guards["files"] or any(item["path"].startswith(root + "/") for root in guards["roots"]):
      if not same(projection(target, item), item["baseline"]):
        raise Conflict("受管启动资源发生漂移；请检查plan并从可信来源重新部署")


def _run_dsh_child(spec, env, pass_fds, *, run_id, owner_registry, manager_identity, control_factory=None):
  from .dsh_process import WaitUnconfirmed, launch
  try:
    options = {"control_factory": control_factory} if control_factory is not None else {}
    return launch(spec, env, pass_fds, run_id=run_id,
      owner_registry=owner_registry, manager_identity=manager_identity, **options)
  except WaitUnconfirmed:
    raise Conflict("原生宿主已启动，但退出结果尚未确认；保留运行记录，未自动终止或重试") from None


def run(workspace, *, cwd, arguments=(), launch_operation=None, resume_operation=None, select_environment=None, inherit_env=(), unset_env=(), proxy=None, runtime_notice=None, observed_identity=None):
  if launch_operation is not None and resume_operation is not None:
    from .schema import ConfigError
    raise ConfigError("conflicting-runtime-operations")
  override_supported = getattr(workspace.adapter, "environment_override_supported", None)
  if (inherit_env or unset_env or proxy is not None) and override_supported is not None and not override_supported(arguments):
    from .schema import ConfigError
    raise ConfigError("environment-overrides-operation")
  validate_arguments = getattr(workspace.adapter, "validate_arguments", None)
  if validate_arguments is not None:
    validate_arguments(arguments)
  operation_cwd = getattr(workspace.adapter, "operation_cwd", None)
  effective_cwd = operation_cwd(workspace, cwd, arguments) if operation_cwd is not None else cwd
  operation_guard = getattr(workspace.adapter, "operation_guard", None)
  if operation_guard is not None:
    operation_guard(workspace, effective_cwd, arguments)
  lifecycle = getattr(workspace.adapter, "run_lifecycle_guard", None) or getattr(workspace.adapter, "lifecycle_guard", None)
  operation_lifecycle = getattr(workspace.adapter, "run_lifecycle_guard_for", None)
  admission = (operation_lifecycle(workspace, tuple(arguments)) if operation_lifecycle is not None
    else lifecycle(workspace) if lifecycle else nullcontext())
  shared = getattr(workspace.adapter, "shared_run_lease", False)
  with admission as admitted, Tree(workspace.state_root, create=True) as state, instance_lock(state, shared=shared) as lease, Tree(workspace.instance) as target:
    cooperative = admitted if type(admitted) is CooperativeRunLease else None
    if cooperative is None and admitted is not None and not isinstance(admitted, int):
      raise DependencyError("可信运行租约上下文无效；不能启动原生宿主")
    lifecycle_fd = cooperative.physical_fd if cooperative is not None else admitted
    if state.read("pending.json"):
      raise Conflict("存在待恢复部署，请先 apply/rollback 恢复后再启动")
    current = read_state(state)["current"]
    if current is None:
      raise Conflict("实例尚未部署；请先 apply")
    if current["binding"] != workspace.binding:
      raise Conflict("部署绑定与当前选择不兼容；请先 plan/apply")
    contract = current["launch"]
    if execution_env.declarations(contract["machine"]) != execution_env.declarations(workspace.resolved.data["machine"]):
      raise Conflict("环境声明已变化；请先 plan/apply，不会静默使用旧声明")
    if "environment_version" in contract:
      if contract["environment_version"] != 1 or contract.get("caller_paths") != execution_env.caller_paths():
        raise Conflict("调用者HOME/XDG或环境契约已变化；请先 plan/apply")
    if (inherit_env or unset_env or proxy is not None) and (launch_operation is not None or resume_operation is not None or select_environment is not None):
      from .schema import ConfigError
      raise ConfigError("environment-overrides-operation")
    validate_binding = getattr(workspace.adapter, "validate_runtime_binding", None)
    if validate_binding is not None:
      validate_binding(workspace, contract.get("adapter_binding"))
    deployed_guard = getattr(workspace.adapter, "deployed_operation_guard", None)
    if deployed_guard is not None:
      deployed_guard(workspace, effective_cwd, arguments, contract)
    check_deployed_resources(current, target)
    identity = contract.get("runtime_identity", contract["lock_identity"])
    root = workspace.backend.root(workspace, identity)
    package_guard = cooperative.package_guard if cooperative is not None else getattr(workspace.backend, "runtime_guard", None)
    with (package_guard(workspace, identity) if package_guard else nullcontext(None)) as package_fd:
      if cooperative is not None:
        try:
          lease_fds = (lifecycle_fd, lease, package_fd)
          if any(type(fd) is not int or fd < 0 for fd in lease_fds):
            raise ValueError()
          for fd in lease_fds:
            os.fstat(fd)
        except (ValueError, OSError, OverflowError):
          raise DependencyError("可信运行租约 fd 无效；不能启动原生宿主") from None
      if workspace.backend.status(workspace, identity) != "installed":
        raise DependencyError("当前部署的运行包缺失或损坏；请 sync 对应依赖锁修复")
      validate_runtime = getattr(workspace.adapter, "validate_runtime", None)
      if validate_runtime is not None:
        validate_runtime(workspace, root)
      operation_arguments = getattr(workspace.adapter, "operation_arguments", None)
      effective_arguments = operation_arguments(arguments) if operation_arguments is not None else arguments
      spec = decode(contract, effective_cwd, effective_arguments)
      operation_environment = getattr(workspace.adapter, "operation_environment", None)
      if operation_environment is not None:
        spec = operation_environment(spec, arguments)
      if select_environment is not None:
        # 受信操作可缩小环境绑定；复用同一部署/运行包/实例准入，不另建启动路径。
        spec = replace(spec, environment=tuple(item for item in spec.environment if select_environment(item)))
      preflight_env, environment_report = prepare_environment(workspace, contract, spec,
        inherit=inherit_env, unset=unset_env, proxy=proxy)
      validate_environment = getattr(workspace.adapter, "validate_operation_environment", None)
      if validate_environment is not None:
        validate_environment(workspace, spec=spec, env=preflight_env)
      before_spawn = getattr(workspace.adapter, "validate_before_spawn", None)
      if before_spawn is not None:
        before_spawn(workspace, effective_cwd, arguments, preflight_env)
      execution_env.warn(environment_report)
      for check in contract.get("preflight", []):
        actual = checked(check["argv"], cwd=effective_cwd, env=preflight_env)
        tool = "Node" if check["argv"][0] == "node" else check["argv"][0]
        if check.get("match") == "exact":
          if actual != check["version"]:
            raise DependencyError("运行时工具链不匹配所选Pi切片的精确版本")
        elif check.get("match") == "minimum":
          ensure_minimum_toolchain(tool, check["version"], actual)
        elif tool in ("Node", "npm"):
          ensure_compatible_toolchain(tool, check["version"], actual)
        elif actual != check["version"]:
          # 其他适配器保留原有精确匹配，不将任意原生输出当作公开版本。
          raise DependencyError("运行时工具链版本不匹配已部署契约；实际输出已隐藏，请检查对应适配器工具链")
      validate_environment = getattr(workspace.adapter, "validate_operation_environment", None)
      if validate_environment is not None:
        validate_environment(workspace, spec=spec)
      optional = {item.value.reference for item in spec.environment
        if isinstance(item.value, SecretRef) and not item.required}
      missing = sum(workspace.secret_store.resolve(SecretRef(reference), required=False) is None
        for reference in optional)
      if missing:
        selector = SimpleNamespace(local=workspace.local_path, profile=workspace.profile)
        print(f"run: {missing} 个模型 key 未填写；工具仍可启动，对应模型暂不可调用。\n"
          "填写位置：\n  " + command_line(selector, "model", "status"), file=sys.stderr)
      env = dict(preflight_env)
      for binding in spec.environment:
        if isinstance(binding.value, SecretRef):
          value = workspace.secret_store.resolve(binding.value, required=binding.required)
          if value is not None:
            if "\0" in value:
              from .secrets import CredentialError
              raise CredentialError()
            env[binding.name] = value
      if validate_environment is not None:
        validate_environment(workspace, spec=spec, env=env)
      if before_spawn is not None:
        before_spawn(workspace, effective_cwd, arguments, env)
      if runtime_notice is not None:
        try:
          status = "unknown" if observed_identity is None else "current" if observed_identity == identity else "pending"
          runtime_notice(status)
        except Exception:
          # 可选展示接缝失败也不能改写原生运行结果。
          pass
      if cooperative is not None:
        owner_context = cooperative.owner_guard(workspace, metadata=run_metadata(workspace, current, spec),
          lifecycle_fd=lifecycle_fd, state_fd=lease, package_fd=package_fd)
      else:
        owner_guard = getattr(workspace.adapter, "run_owner_guard", None)
        owner_context = owner_guard(workspace, metadata=run_metadata(workspace, current, spec)) if owner_guard else nullcontext()
      with owner_context as run_id:
        # 不打印 argv/env，原生子进程继承终端用于正常 TUI 交互。
        try:
          if cooperative is not None and (type(run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", run_id) is None):
            raise DependencyError("合作运行缺少可核验的新运行登记；不能启动原生宿主")
          if resume_operation is not None:
            if type(run_id) is not str or re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
              raise DependencyError("恢复操作缺少可核验的新运行登记；请使用已支持的受管运行路径")
            # 可信回调沿用部署、三层租约及 owner 生命周期；原生 writer 仍由宿主取得。
            return resume_operation(workspace, spec, env, lease, contract, run_id=run_id,
              lifecycle_fd=lifecycle_fd, package_fd=package_fd)
          if launch_operation is not None:
            return launch_operation(workspace, spec, env, lease, contract, lifecycle_fd=lifecycle_fd)
          executor = getattr(workspace.adapter, "launch_executor", None)
          if executor is not None:
            execute = executor()
            if execute is not None:
              return execute(workspace, spec, env, lease, contract, lifecycle_fd=lifecycle_fd)
          # 原生宿主继承三层租约：物理实例、状态和运行包均持有至退出。
          pass_fds = tuple(fd for fd in (lifecycle_fd, lease, package_fd) if isinstance(fd, int))
          if run_id is not None and workspace.agent == "dsh":
            from .run_owners import Registry
            owner_registry = Registry(workspace.state_root / "run-owners", workspace.binding)
            owner = owner_registry.snapshot()[run_id]
            # SSH 的本地传输进程不代表远端 Agent；只登记受管宿主。
            if owner.get("backend") == "managed":
              from .dsh_stop_control import default_factory
              control = default_factory(workspace, owner, instance_fd=lifecycle_fd, state_fd=lease)
              options = {"control_factory": control} if control is not None else {}
              return _run_dsh_child(spec, env, pass_fds, run_id=run_id,
                owner_registry=owner_registry, manager_identity=owner["manager_identity"], **options)
          child = subprocess.run(list(spec.argv), cwd=spec.cwd, env=env, pass_fds=pass_fds)
        except OSError:
          raise DependencyError("原生启动失败；检查 Node 与锁定运行包") from None
        return child.returncode if child.returncode >= 0 else 128 - child.returncode
