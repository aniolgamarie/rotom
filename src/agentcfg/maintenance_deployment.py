"""停止前的只读部署核验；不授予控制权，也不检查调用者环境。"""
import hashlib

from . import deployment, run_owners, runtime
from .omp_lifecycle import _same_file
from .paths import safe_id
from .storage import Conflict, Tree


_ERROR = "停止接受前的已部署资源或部署代际不能确认；保留现有保护"


def check_stop_deployment(workspace, record, *, instance_fd, state_fd):
  """调用方持续持有物理/状态/包 SH；仅借用 fd，不获取锁或追踪保存路径。"""
  try:
    if (workspace.agent != "omp" or workspace.profile != workspace.binding["profile"]
        or type(record) is not dict or type(record.get("schema_version")) is not int
        or record["schema_version"] != 2 or record["agent"] != "omp"
        or record["backend"] != "managed" or record["lifecycle_state"] != "active"):
      raise ValueError()
    registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
    registry._validate_record(record["run_id"] + ".json", record)
    with Tree(workspace.instance) as target, Tree(workspace.state_root) as state:
      _same_file(target, ".agentcfg-omp.lock", instance_fd)
      _same_file(state, "instance.lock", state_fd)
      if state.read("pending.json") is not None:
        raise ValueError()
      saved = deployment.read_state(state)
      current = saved["current"]
      if (current is None or current["binding"] != workspace.binding
          or saved["owner"]["binding"] != workspace.binding
          or current["generation"] != record["deployed_identity"]["deployment"]):
        raise ValueError()
      contract = current["launch"]
      identity = contract.get("runtime_identity", contract["lock_identity"])
      safe_id(identity)
      digest = (identity if len(identity) == 64 and all(char in "0123456789abcdef" for char in identity)
        else hashlib.sha256(identity.encode()).hexdigest())
      home = str(workspace.instance / "user-home")
      if (digest != record["deployed_identity"]["runtime"]
          or contract["adapter_binding"]["identity"]["home"] != home
          or record["native_home_ref"]["path"] != home):
        raise ValueError()
      runtime.check_deployed_resources(current, target)
      # 读取受保护文件期间命名状态锁也可能被替换；不能沿旧 fd 认领新对象。
      _same_file(state, "instance.lock", state_fd)
  except Exception:
    raise Conflict(_ERROR) from None
