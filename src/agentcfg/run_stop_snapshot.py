"""人工恢复清单纯 codec；不重建许可、现场句柄或当前确认。

records 仅保存选中项；records_digest 绑定 build 时的完整 expected_records。
解码只能校验选中记录及摘要格式，调用方须在 owner 锁内与 fresh 全集精确匹配。
只读取仓库自有 RunRecord schema，不访问 Registry/native 目标或补造未知事实。
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from . import run_owners
from .storage import Conflict


_MAX_BYTES = 16 * 1024 * 1024
_MAX_DEPTH = 32
_MAX_NODES = 1000000
_ERROR = "人工恢复快照数据无效；保留已有保护"
_FIELDS = {"schema_version", "kind", "binding", "binding_digest", "registry_physical", "batch_id", "plan_id",
  "records_digest", "selected_runs", "records", "restore_mode"}


def _shape(value):
  # 有界逻辑展开；循环及共享 alias 都不能绕过深度、节点和字节下界预算。
  pending, nodes, text_bytes = [(value, 0)], 0, 0
  while pending:
    current, depth = pending.pop()
    nodes += 1
    if nodes > _MAX_NODES:
      raise ValueError()
    if type(current) in (dict, list):
      if depth >= _MAX_DEPTH or len(current) > _MAX_NODES - nodes - len(pending):
        raise ValueError()
      if type(current) is dict:
        for key in current:
          if type(key) is not str or len(key) > _MAX_BYTES:
            raise ValueError()
          text_bytes += len(key.encode("utf-8"))
        children = current.values()
      else:
        children = current
      pending.extend((child, depth + 1) for child in children)
    elif type(current) is str:
      if len(current) > _MAX_BYTES:
        raise ValueError()
      text_bytes += len(current.encode("utf-8"))
    elif current is not None and type(current) not in (int, bool):
      raise ValueError()
    if text_bytes > _MAX_BYTES:
      raise ValueError()


def _encoded(value):
  raw = run_owners._encode(value)
  if len(raw) > _MAX_BYTES:
    raise ValueError()
  return raw


def _registry(binding):
  if (type(binding) is not dict or set(binding) != {"machine", "local", "profile"}
      or any(type(value) is not str or not value or "\0" in value for value in binding.values())):
    raise ValueError()
  run_owners._absolute(binding["local"])
  return run_owners.Registry(Path("/run-owners"), binding)


def _physical(value):
  if (type(value) is not dict or set(value) != {"device", "inode"}
      or any(type(value[name]) is not int for name in value) or value["device"] < 0 or value["inode"] <= 0):
    raise ValueError()


def _hex64(value):
  if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
    raise ValueError()


def _selection(value):
  if type(value) is not list or not 1 <= len(value) <= 1024:
    raise ValueError()
  for run in value:
    run_owners._run_id(run)
  if len(set(value)) != len(value):
    raise ValueError()
  return sorted(value)


def _records(registry, records, *, selected):
  if type(records) is not dict or not 1 <= len(records) <= 1024:
    raise ValueError()
  for run, record in records.items():
    run_owners._run_id(run)
    registry._validate_record(run + ".json", record)
    if run in selected and (record["schema_version"] != 2 or record["lifecycle_state"] != "active"
        or record["agent"] != "dsh" or record["backend"] != "managed" or record["coordination_domain"] is not None):
      raise ValueError()


def _normalize(value):
  _shape(value)
  if (type(value) is not dict or type(value.get("schema_version")) is not int
      or value["schema_version"] not in (1, 2)
      or set(value) != (_FIELDS | {"plan"} if value["schema_version"] == 2 else _FIELDS)
      or type(value["kind"]) is not str or value["kind"] != "run-stop-snapshot"
      or type(value["restore_mode"]) is not str or value["restore_mode"] != "manual"):
    raise ValueError()
  registry = _registry(value["binding"])
  if value["binding_digest"] != registry.binding_digest:
    raise ValueError()
  _physical(value["registry_physical"])
  run_owners._run_id(value["batch_id"])
  _hex64(value["plan_id"])
  _hex64(value["records_digest"])
  selected = _selection(value["selected_runs"])
  if type(value["records"]) is not dict or set(value["records"]) != set(selected):
    raise ValueError()
  _records(registry, value["records"], selected=set(selected))
  result = deepcopy(value)
  result["selected_runs"] = selected
  result["records"] = {run: result["records"][run] for run in selected}
  if result["schema_version"] == 2:
    _bind_plan(result)
  _encoded(result)
  return result


def _canonical_plan(value):
  from . import maintenance
  plan = maintenance.decode_stop_plan(maintenance.encode_stop_plan(value))
  if plan["schema_version"] != 2:
    raise ValueError()
  return plan


def _bind_plan(value):
  # reader 只知道选中记录，不能把全集摘要和 reference_runs 当现场完整覆盖证明。
  plan = _canonical_plan(value["plan"])
  if (plan["scope"] != {**value["binding"], "agent": "dsh"}
      or plan["plan_id"] != value["plan_id"] or plan["selected_runs"] != value["selected_runs"]):
    raise ValueError()
  coordinator = plan["coordinator"]
  for name in ("binding_digest", "registry_physical", "records_digest"):
    if _encoded(coordinator[name]) != _encoded(value[name]):
      raise ValueError()
  for run in plan["runs"]:
    record = value["records"][run["run_id"]]
    observation = run["observation"]
    host = record["host_identity"]["identity"] if record["host_identity"] else None
    session = record["session_observation"]
    session_status = "historical" if session and session["confirmation"] in ("historical", "confirmed") else "unknown"
    if (observation["state"] != "active"
        or _encoded(observation["manager_identity"]) != _encoded(record["manager_identity"])
        or _encoded(observation["host_identity"]) != _encoded(host)
        or observation["record_digest"] != hashlib.sha256(_encoded(record)).hexdigest()
        or run["deployment_digest"] != hashlib.sha256(_encoded(record["deployed_identity"])).hexdigest()
        or run["restore"]["mode"] != "manual" or run["restore"]["session_status"] != session_status):
      raise ValueError()
  value["plan"] = plan


def build_snapshot(*, binding, registry_physical, batch_id, plan_id, expected_records, selected_runs) -> dict:
  try:
    _shape(expected_records)
    _shape(binding)
    registry = _registry(binding)
    _physical(registry_physical)
    run_owners._run_id(batch_id)
    _hex64(plan_id)
    selected = _selection(selected_runs)
    if type(expected_records) is not dict or not set(selected) <= set(expected_records):
      raise ValueError()
    _records(registry, expected_records, selected=set(selected))
    full_raw = _encoded(expected_records)
    return _normalize({"schema_version": 1, "kind": "run-stop-snapshot", "binding": binding,
      "binding_digest": registry.binding_digest, "registry_physical": registry_physical,
      "batch_id": batch_id, "plan_id": plan_id, "records_digest": hashlib.sha256(full_raw).hexdigest(),
      "selected_runs": selected, "records": {run: expected_records[run] for run in selected}, "restore_mode": "manual"})
  except Exception:
    raise Conflict(_ERROR) from None


def encode_snapshot(value) -> bytes:
  try:
    return _encoded(_normalize(value))
  except Exception:
    raise Conflict(_ERROR) from None


def decode_snapshot(raw) -> dict:
  try:
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
      raise ValueError()
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=run_owners._pairs,
      parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
    return _normalize(value)
  except Exception:
    raise Conflict(_ERROR) from None


def build_plan_snapshot(*, binding, registry_physical, batch_id, expected_records, plan) -> dict:
  """保存完整 DSH 计划及人工恢复记录；支持 blocked，不构造审阅或许可。

  builder 校验传入全集的非 idle 引用；解码仅保存历史，现场仍须重新 CAS。
  v1 builder、格式和规范字节保持不变，不访问任何目标文件。
  """
  try:
    _shape(expected_records)
    records = json.loads(_encoded(expected_records), object_pairs_hook=run_owners._pairs,
      parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
    normalized = _canonical_plan(plan)
    value = build_snapshot(binding=binding, registry_physical=registry_physical, batch_id=batch_id,
      expected_records=records, plan_id=normalized["plan_id"], selected_runs=normalized["selected_runs"])
    references = sorted(run for run, record in records.items() if run_owners.record_state(record) != "idle_confirmed")
    if any(resource["reference_runs"] != references for resource in normalized["resources"]):
      raise ValueError()
    value.update(schema_version=2, plan=normalized)
    return _normalize(value)
  except Exception:
    raise Conflict(_ERROR) from None
