"""使用已部署启动契约；密钥值下次启动解析，不解释未部署的模型变更。"""

from dataclasses import replace
from contextlib import nullcontext
import json
from pathlib import Path
import subprocess

from .adapter import EnvironmentBinding, LaunchSpec, SecretRef
from .deployment import read_state, recover
from .process import DependencyError, checked, environment, launch_environment
from .toolchain import ensure_compatible_toolchain
from .storage import Conflict, Tree, ensure_private, instance_lock


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
          for e in value["environment"]), value.get("runtime_identity", value["lock_identity"]))


def run(workspace, *, cwd, arguments=(), launch_operation=None, select_environment=None):
  validate_arguments = getattr(workspace.adapter, "validate_arguments", None)
  if validate_arguments is not None:
    validate_arguments(arguments)
  operation_cwd = getattr(workspace.adapter, "operation_cwd", None)
  effective_cwd = operation_cwd(workspace, cwd, arguments) if operation_cwd is not None else cwd
  operation_guard = getattr(workspace.adapter, "operation_guard", None)
  if operation_guard is not None:
    operation_guard(workspace, effective_cwd, arguments)
  lifecycle = getattr(workspace.adapter, "lifecycle_guard", None)
  with (lifecycle(workspace) if lifecycle else nullcontext()) as lifecycle_fd, Tree(workspace.state_root, create=True) as state, instance_lock(state) as lease, Tree(workspace.instance) as target:
    if state.read("pending.json"):
      raise Conflict("存在待恢复部署，请先 apply/rollback 恢复后再启动")
    current = read_state(state)["current"]
    if current is None or current["binding"] != workspace.binding:
      raise Conflict("未部署当前实例，请先 apply")
    contract = current["launch"]
    validate_binding = getattr(workspace.adapter, "validate_runtime_binding", None)
    if validate_binding is not None:
      validate_binding(workspace, contract.get("adapter_binding"))
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
    identity = contract.get("runtime_identity", contract["lock_identity"])
    root = workspace.backend.root(workspace, identity)
    package_guard = getattr(workspace.backend, "runtime_guard", None)
    with (package_guard(workspace, identity) if package_guard else nullcontext(None)) as package_fd:
      if workspace.backend.status(workspace, identity) != "installed":
        raise DependencyError("当前部署的运行包缺失或损坏；请 sync 对应依赖锁修复")
      workspace.adapter.prepare_runtime(workspace, root)
      operation_arguments = getattr(workspace.adapter, "operation_arguments", None)
      effective_arguments = operation_arguments(arguments) if operation_arguments is not None else arguments
      spec = decode(contract, effective_cwd, effective_arguments)
      operation_environment = getattr(workspace.adapter, "operation_environment", None)
      if operation_environment is not None:
        spec = operation_environment(spec, arguments)
      if select_environment is not None:
        # 受信操作可缩小环境绑定；复用同一部署/运行包/实例准入，不另建启动路径。
        spec = replace(spec, environment=tuple(item for item in spec.environment if select_environment(item)))
      preflight_env = environment(contract["machine"], home=workspace.instance / "user-home")
      for check in contract.get("preflight", []):
        actual = checked(check["argv"], cwd=effective_cwd, env=preflight_env)
        tool = "Node" if check["argv"][0] == "node" else check["argv"][0]
        if check.get("match") == "exact":
          if actual != check["version"]:
            raise DependencyError("运行时工具链不匹配所选Pi切片的精确版本")
        elif tool in ("Node", "npm"):
          ensure_compatible_toolchain(tool, check["version"], actual)
        elif actual != check["version"]:
          # 其他适配器保留原有精确匹配，不将任意原生输出当作公开版本。
          raise DependencyError("运行时工具链版本不匹配已部署契约；实际输出已隐藏，请检查对应适配器工具链")
      validate_environment = getattr(workspace.adapter, "validate_operation_environment", None)
      if validate_environment is not None:
        validate_environment(workspace, spec=spec)
      env = launch_environment(spec, contract["machine"], workspace.secret_store)
      import os
      env["PATH"] = os.pathsep.join([*(str(path) for path in workspace.backend.executable_paths(root)), env.get("PATH", "")])
      if validate_environment is not None:
        validate_environment(workspace, spec=spec, env=env)
      before_spawn = getattr(workspace.adapter, "validate_before_spawn", None)
      if before_spawn is not None:
        before_spawn(workspace, effective_cwd, arguments, env)
      # 不打印 argv/env，原生子进程继承终端用于正常 TUI 交互。
      try:
        if launch_operation is not None:
          return launch_operation(workspace, spec, env, lease, contract, lifecycle_fd=lifecycle_fd)
        executor = getattr(workspace.adapter, "launch_executor", None)
        if executor is not None:
          execute = executor()
          if execute is not None:
            return execute(workspace, spec, env, lease, contract, lifecycle_fd=lifecycle_fd)
        # 原生宿主继承三层租约：物理实例、状态和运行包均持有至退出。
        pass_fds = tuple(fd for fd in (lifecycle_fd, lease, package_fd) if isinstance(fd, int))
        child = subprocess.run(list(spec.argv), cwd=spec.cwd, env=env, pass_fds=pass_fds)
      except OSError:
        raise DependencyError("原生启动失败；检查 Node 与锁定运行包") from None
      return child.returncode if child.returncode >= 0 else 128 - child.returncode
