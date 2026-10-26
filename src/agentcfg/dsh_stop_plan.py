"""DSH v2 本地停止计划纯数据；不证明现场、批准、释放或控制资格。

supported/complete 和完整 owner 摘要均为调用方声明，现场 CAS 由调用方另行核验。
只复用公开仓库 schema，不读取 Registry、原生文件、进程或时钟，不创建协调域。
"""
from copy import deepcopy
import hashlib

from . import maintenance, run_owners
from .storage import Conflict


_ERROR = "DSH 停止计划数据无效；不授予停止或维护权限"


def _scope(value):
  maintenance._validate(value, "scope")
  maintenance._scope(value)
  if set(value) != {"machine", "local", "agent", "profile"} or value["agent"] != "dsh":
    raise ValueError()


def _run_scope(run, scope):
  _scope(run["scope"])
  if run["scope"] != scope or run["restore"]["mode"] != "manual":
    raise ValueError()


def normalize(value, *, verify=True):
  """规范排序并校验完整摘要；verify=False 只用于可信数据重新计算，不作批准。"""
  try:
    maintenance._validate(value, "dsh-stop-plan")
    maintenance._dump(value)
    result = deepcopy(value)
    _scope(result["scope"])
    binding = {key: result["scope"][key] for key in ("machine", "local", "profile")}
    if result["coordinator"]["binding_digest"] != hashlib.sha256(run_owners._encode(binding)).hexdigest():
      raise ValueError()
    result["selected_runs"].sort()
    runs = maintenance._unique(result["runs"], "run_id")
    resources = maintenance._resource_catalog(result["resources"])
    selected = set(result["selected_runs"])
    if set(runs) != selected:
      raise ValueError()
    blockers, required = set(), set()
    if result["control_capability"] != "supported":
      blockers.add("stop-capability-unavailable")
    for run in runs.values():
      _run_scope(run, result["scope"])
      observation = run["observation"]
      if run["observation_digest"] != maintenance._digest(observation):
        raise ValueError()
      manager, host = observation["manager_identity"], observation["host_identity"]
      if manager is not None and host is not None and manager["pid"] == host["pid"]:
        raise ValueError()
      # active 只是历史登记；没有已知 host 仍可展示阻断计划，不改动 v1 规则。
      if observation["state"] == "unknown" or manager is None or host is None:
        blockers.add("control-observation-unknown")
      run["resource_ids"].sort()
      if not set(run["resource_ids"]) <= set(resources):
        raise ValueError()
      kinds = [resources[rid]["key"]["kind"] for rid in run["resource_ids"]]
      if kinds.count("instance") != 1 or kinds.count("native-home") != 1 or kinds.count("runtime") < 1:
        raise ValueError()
      required.update(run["resource_ids"])
    if required != set(resources):
      raise ValueError()
    for rid, resource in resources.items():
      resource["reference_runs"].sort()
      owners = {run_id for run_id, run in runs.items() if rid in run["resource_ids"]}
      if owners != set(resource["reference_runs"]) & selected:
        raise ValueError()
      # 精确停止只选择已核实的目标；资源完整覆盖仍是 setup 写入的前提。
      if result["operation"] == "setup" and resource["coverage"] != "complete":
        blockers.add("resource-coverage-unknown")
      if result["operation"] == "setup" and set(resource["reference_runs"]) - selected:
        blockers.add("unselected-run-reference")
    result["runs"] = [runs[run] for run in sorted(runs)]
    result["resources"] = [resources[rid] for rid in sorted(resources)]
    expected = sorted(blockers)
    readiness = "blocked" if blockers else "ready"
    if verify and (result["blockers"] != expected or result["readiness"] != readiness):
      raise ValueError()
    result.update(blockers=expected, readiness=readiness)
    previous = result.pop("plan_id")
    digest = maintenance._digest(result)
    if verify and previous != digest:
      raise ValueError()
    result["plan_id"] = digest
    return result
  except Exception:
    raise Conflict(_ERROR) from None


def build(*, scope, operation, selected_runs, runs, resources, coordinator, control_capability):
  """选择显式运行及其资源闭包，不自动吸收共享第三项，不构造 Batch。"""
  try:
    supplied = {"scope": scope, "operation": operation, "selected_runs": selected_runs,
      "runs": runs, "resources": resources, "coordinator": coordinator, "control_capability": control_capability}
    maintenance._shape(supplied)
    maintenance._dump(supplied)
    _scope(scope)
    if (type(selected_runs) is not list or not selected_runs or len(selected_runs) > 1024
        or len(selected_runs) != len(set(selected_runs)) or type(runs) is not list
        or type(resources) is not list or len(runs) > 1024 or len(resources) > 4096):
      raise ValueError()
    for run in runs:
      maintenance._validate(run, "snapshot")
      _run_scope(run, scope)
    for resource in resources:
      maintenance._validate(resource, "local-resource")
    run_map = maintenance._unique(runs, "run_id")
    resource_map = maintenance._resource_catalog(resources)
    if not set(selected_runs) <= set(run_map):
      raise ValueError()
    for run in runs:
      for rid in run["resource_ids"]:
        if rid not in resource_map or run["run_id"] not in resource_map[rid]["reference_runs"]:
          raise ValueError()
    chosen = [deepcopy(run_map[run]) for run in selected_runs]
    required = set()
    for run in chosen:
      run["observation_digest"] = maintenance._digest(run["observation"])
      required.update(run["resource_ids"])
    return normalize({"schema_version": 2, "kind": "stop-plan", "protocol": "rotom-maintenance-v2",
      "plan_id": "0" * 64, "scope": deepcopy(scope), "operation": operation,
      "selected_runs": deepcopy(selected_runs), "runs": chosen,
      "resources": [deepcopy(resource_map[rid]) for rid in required], "readiness": "ready", "blockers": [],
      "coordinator": deepcopy(coordinator), "control_capability": control_capability}, verify=False)
  except Exception:
    raise Conflict(_ERROR) from None
