"""使用已部署启动契约；密钥值下次启动解析，不解释未部署的模型变更。"""

from dataclasses import replace
import json
from pathlib import Path
import subprocess

from .adapter import EnvironmentBinding, LaunchSpec, SecretRef
from .deployment import read_state, recover
from .process import DependencyError, checked, environment, launch_environment
from .toolchain import ensure_compatible_toolchain
from .storage import Conflict, Tree, ensure_private, instance_lock


def record(workspace, lock):
  spec = workspace.adapter.launch_spec(workspace.resolved.data, cwd=Path("/"),
    runtime_root=workspace.backend.root(workspace, lock.identity), instance_root=workspace.instance, lock_identity=lock.identity)
  return {"argv": list(spec.argv), "lock_identity": lock.identity,
    "shared_files": list(workspace.adapter.shared_files),
    "preflight": workspace.adapter.launch_preflight(lock),
    "machine": workspace.resolved.data["machine"],
    "environment": [{"name": e.name, "required": e.required,
      **({"secret_ref": e.value.reference} if isinstance(e.value, SecretRef) else {"literal": e.value})} for e in spec.environment]
      + [{"name": "AGENTCFG_REPOSITORY", "required": True, "literal": str(workspace.repository)},
         {"name": "AGENTCFG_LOCAL_FILE", "required": True, "literal": str(workspace.local_path)},
         {"name": "AGENTCFG_PROFILE", "required": True, "literal": workspace.profile}]}


def decode(value, cwd, arguments):
  return LaunchSpec(tuple(value["argv"]) + tuple(arguments), cwd, value["lock_identity"],
    tuple(EnvironmentBinding(e["name"], SecretRef(e["secret_ref"]) if "secret_ref" in e else e["literal"], e["required"])
          for e in value["environment"]))


def run(workspace, *, cwd, arguments=()):
  with Tree(workspace.state_root, create=True) as state, instance_lock(state) as lease, Tree(workspace.instance) as target:
    if state.read("pending.json"):
      raise Conflict("存在待恢复部署，请先 apply/rollback 恢复后再启动")
    current = read_state(state)["current"]
    if current is None or current["binding"] != workspace.binding:
      raise Conflict("未部署当前实例，请先 apply")
    contract = current["launch"]
    root = workspace.backend.root(workspace, contract["lock_identity"])
    if workspace.backend.status(workspace, contract["lock_identity"]) != "installed":
      raise DependencyError("当前部署的运行包缺失或损坏；请 sync 对应依赖锁修复")
    workspace.adapter.prepare_runtime(workspace, root)
    spec = decode(contract, cwd, arguments)
    preflight_env = environment(contract["machine"], home=workspace.instance / "user-home")
    for check in contract.get("preflight", []):
      actual = checked(check["argv"], cwd=cwd, env=preflight_env)
      tool = "Node" if check["argv"][0] == "node" else check["argv"][0]
      if tool in ("Node", "npm"):
        ensure_compatible_toolchain(tool, check["version"], actual)
      elif actual != check["version"]:
        # 其他适配器保留原有精确匹配，不将任意原生输出当作公开版本。
        raise DependencyError("运行时工具链版本不匹配已部署契约；实际输出已隐藏，请检查对应适配器工具链")
    env = launch_environment(spec, contract["machine"], workspace.secret_store)
    import os
    env["PATH"] = os.pathsep.join([*(str(path) for path in workspace.backend.executable_paths(root)), env.get("PATH", "")])
    # 不打印 argv/env，原生子进程继承终端用于正常 TUI 交互。
    try:
      # 原生宿主也持有 lease：管理器先退出时仍阻止修改活动实例；不靠 PID 猜测。
      child = subprocess.run(list(spec.argv), cwd=spec.cwd, env=env, pass_fds=(lease,))
    except OSError:
      raise DependencyError("原生启动失败；检查 Node 与锁定运行包") from None
    return child.returncode if child.returncode >= 0 else 128 - child.returncode
