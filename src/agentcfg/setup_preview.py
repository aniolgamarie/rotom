"""私有 setup 预览摘要：仅绑定内存计划，不代表授权或物理状态证明。"""

import hashlib

from .deployment import Plan, json_bytes
from .storage import Conflict


def _strict_json(value):
  if type(value) is dict:
    for key, child in value.items():
      if type(key) is not str:
        raise ValueError
      _strict_json(child)
  elif type(value) is list:
    for child in value:
      _strict_json(child)
  elif value is not None and type(value) not in (str, bool, int, float):
    raise ValueError


def setup_deployment_digest(current):
  """只绑定完整内存部署契约；不读取文件，也不代表授权或当前现场证明。"""
  try:
    if type(current) is not dict:
      raise ValueError
    _strict_json(current)
    return hashlib.sha256(json_bytes({"version": 1, "current": current})).hexdigest()
  except Exception:
    raise Conflict("setup 目标部署无法生成摘要；请重新运行 setup。") from None


def setup_plan_digest(workspace, lock, candidate, plan):
  """摘要包含真实目标与完整部署计划；不读取文件、解析秘密或输出预像。"""
  try:
    if not isinstance(plan, Plan):
      raise ValueError
    value = {"version": 1, "operation": "setup", "workspace": {
      "agent": workspace.agent, "profile": workspace.profile, "binding": workspace.binding,
      "instance": str(workspace.instance), "state_root": str(workspace.state_root),
      "cache": str(workspace.cache)}, "lock_identity": lock.identity,
      "generation": candidate.generation, "plan": {"current": plan.current,
      "changes": plan.changes, "drift": plan.drift, "conflicts": plan.conflicts}}
    _strict_json(value)
    return hashlib.sha256(json_bytes(value)).hexdigest()
  except Exception:
    raise Conflict("setup 预览计划无法生成摘要；请重新运行 setup。") from None
