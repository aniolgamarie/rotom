"""维护快照的纯数据核心；不采集现场、加锁、写状态、构造许可或执行动作。

唯一读取的是仓库自有 schema。所有身份、覆盖与能力均为调用方提供的快照；
规范摘要不是授权，反序列化不会恢复文件描述符、稳定句柄或观察器的现场证明。
"""

from copy import deepcopy
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

from .resource_keys import ResourceKey
from .storage import Conflict


_MAX_BYTES = 2 * 1024 * 1024
_MAX_DEPTH = 32
_MAX_NODES = 100000
_ERROR = "维护计划或批次数据无效"
_PROTOCOL = "rotom-maintenance-v1"


def _invalid(*args):
  raise ValueError()


def _pairs(pairs):
  result = {}
  for key, child in pairs:
    if key in result:
      _invalid()
    result[key] = child
  return result


def _shape(value):
  pending, nodes = [(value, 0)], 0
  while pending:
    current, depth = pending.pop()
    nodes += 1
    if nodes > _MAX_NODES:
      _invalid()
    if type(current) in (dict, list):
      if depth >= _MAX_DEPTH or len(current) > _MAX_NODES - nodes - len(pending):
        _invalid()
      if type(current) is dict:
        for key in current:
          if type(key) is not str or len(key) > 65536:
            _invalid()
          key.encode("utf8")
        children = current.values()
      else:
        children = current
      pending.extend((child, depth + 1) for child in children)
    elif type(current) is str:
      if len(current) > 65536:
        _invalid()
      current.encode("utf8")
    elif current is not None and type(current) not in (bool, int):
      _invalid()


def _dump(value):
  raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf8")
  if len(raw) + 1 > _MAX_BYTES:
    _invalid()
  return raw


def _digest(value):
  return hashlib.sha256(_dump(value)).hexdigest()


@lru_cache(maxsize=1)
def _validators():
  from jsonschema import Draft202012Validator
  schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/rotom/maintenance.schema.json").read_bytes())
  Draft202012Validator.check_schema(schema)
  return {kind: Draft202012Validator({"$ref": "#/$defs/" + kind, "$defs": schema["$defs"]})
    for kind in ("scope", "snapshot", "resource", "stop-plan", "batch", "stop-acceptance",
      "dsh-stop-plan", "local-resource", "registry-coordinator")}


def _validate(value, kind):
  _shape(value)
  if not _validators()[kind].is_valid(value):
    _invalid()


def _path(value):
  if (not value.startswith("/") or "//" in value or (value != "/" and value.endswith("/"))
      or any(part in (".", "..") for part in value.split("/")) or "\\" in value
      or any(ord(char) < 32 or ord(char) == 127 for char in value)):
    _invalid()


def _scope(value):
  _path(value["local"])
  for name in ("machine", "profile"):
    if name in value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,254}", value[name]):
      _invalid()


def _unique(values, field):
  result = {}
  for value in values:
    identifier = value[field]
    if identifier in result:
      _invalid()
    result[identifier] = value
  return result


def _resource_catalog(resources):
  by_id = _unique(resources, "resource_id")
  physical = set()
  for resource in resources:
    ResourceKey.from_dict(resource["key"])
    key = (resource["key"]["device"], resource["key"]["inode"])
    if key in physical:
      _invalid()
    physical.add(key)
  return by_id


def _plan(value, *, verify=True):
  if type(value) is dict and type(value.get("schema_version")) is int and value["schema_version"] == 2:
    from .dsh_stop_plan import normalize
    return normalize(value, verify=verify)
  _validate(value, "stop-plan")
  result = deepcopy(value)
  _scope(result["scope"])
  result["selected_runs"].sort()
  runs = _unique(result["runs"], "run_id")
  resources = _resource_catalog(result["resources"])
  selected = set(result["selected_runs"])
  if set(runs) != selected:
    _invalid()
  blockers, required, domains = set(), set(), set()
  for run in runs.values():
    _scope(run["scope"])
    if any(run["scope"][name] != expected for name, expected in result["scope"].items()):
      _invalid()
    observation = run["observation"]
    if run["observation_digest"] != _digest(observation):
      _invalid()
    if observation["state"] == "unknown":
      blockers.add("control-observation-unknown")
    elif (observation["manager_identity"] is None or observation["host_identity"] is None
        or observation["manager_identity"]["pid"] == observation["host_identity"]["pid"]):
      _invalid()
    run["resource_ids"].sort()
    if not set(run["resource_ids"]).issubset(resources):
      _invalid()
    kinds = [resources[rid]["key"]["kind"] for rid in run["resource_ids"]]
    if kinds.count("instance") != 1 or kinds.count("native-home") != 1 or kinds.count("runtime") < 1:
      _invalid()
    required.update(run["resource_ids"])
    restore = run["restore"]
    if restore["mode"] != "manual":
      if restore["capability"] != "supported":
        blockers.add("restore-capability-unavailable")
      if restore["session_status"] not in ("confirmed", "sealed"):
        blockers.add("session-unsealed")
  if required != set(resources):
    _invalid()
  for rid, resource in resources.items():
    resource["reference_runs"].sort()
    owners = {run_id for run_id, run in runs.items() if rid in run["resource_ids"]}
    if owners != set(resource["reference_runs"]) & selected:
      _invalid()
    domains.add((resource["domain_id"], resource["domain_physical"]["device"], resource["domain_physical"]["inode"]))
    if resource["coverage"] != "complete":
      blockers.add("resource-coverage-unknown")
    if result["operation"] == "setup" and set(resource["reference_runs"]) - selected:
      blockers.add("unselected-run-reference")
  if len(domains) != 1:
    _invalid()
  result["runs"] = [runs[run_id] for run_id in sorted(runs)]
  result["resources"] = [resources[rid] for rid in sorted(resources)]
  expected = sorted(blockers)
  readiness = "blocked" if blockers else "ready"
  if verify and (result["blockers"] != expected or result["readiness"] != readiness):
    _invalid()
  result.update(blockers=expected, readiness=readiness)
  old_digest = result.pop("plan_id")
  plan_id = _digest(result)
  if verify and old_digest != plan_id:
    _invalid()
  result["plan_id"] = plan_id
  return result


def build_stop_plan(*, scope, operation, selected_runs, runs, resources):
  """仅选择明确 run，规范化完整闭包；共享第三项不自动加入停止目标。"""
  try:
    supplied = {"scope": scope, "operation": operation, "selected_runs": selected_runs, "runs": runs, "resources": resources}
    _shape(supplied)
    _dump(supplied)
    _validate(scope, "scope")
    if type(selected_runs) is not list or not selected_runs or len(selected_runs) != len(set(selected_runs)):
      _invalid()
    if type(runs) is not list or type(resources) is not list or len(runs) > 1024 or len(resources) > 4096:
      _invalid()
    for run in runs:
      _validate(run, "snapshot")
    for resource in resources:
      _validate(resource, "resource")
    run_map, resource_map = _unique(runs, "run_id"), _resource_catalog(resources)
    if not set(selected_runs).issubset(run_map):
      _invalid()
    for run in runs:
      for rid in run["resource_ids"]:
        if rid not in resource_map or run["run_id"] not in resource_map[rid]["reference_runs"]:
          _invalid()
    chosen = [deepcopy(run_map[run_id]) for run_id in selected_runs]
    required = set()
    for run in chosen:
      run["observation_digest"] = _digest(run["observation"])
      required.update(run["resource_ids"])
    if not required.issubset(resource_map):
      _invalid()
    return _plan({"schema_version": 1, "kind": "stop-plan", "protocol": _PROTOCOL,
      "plan_id": "0" * 64, "scope": deepcopy(scope), "operation": operation,
      "selected_runs": deepcopy(selected_runs), "runs": chosen,
      "resources": [deepcopy(resource_map[rid]) for rid in required], "readiness": "ready", "blockers": []}, verify=False)
  except Exception:
    raise Conflict(_ERROR) from None


def _dispatch(value):
  if (value["state"] == "not_dispatched") != (value["dispatch_id"] is None):
    _invalid()


def build_dsh_stop_plan(*, scope, operation, selected_runs, runs, resources, coordinator, control_capability):
  """实例 Registry 协调的 DSH 只读计划；不构造 OMP 域或执行许可。"""
  from .dsh_stop_plan import build
  return build(scope=scope, operation=operation, selected_runs=selected_runs, runs=runs,
    resources=resources, coordinator=coordinator, control_capability=control_capability)


def _batch(value):
  _validate(value, "batch")
  result = deepcopy(value)
  result["plan"] = _plan(result["plan"])
  plan = result["plan"]
  result["accepted_runs"].sort()
  items = _unique(result["items"], "run_id")
  if (plan["readiness"] != "ready" or result["operation"] != plan["operation"]
      or result["accepted_runs"] != plan["selected_runs"] or set(items) != set(result["accepted_runs"])):
    _invalid()
  planned = {run["run_id"]: run for run in plan["runs"]}
  dispatch = result["maintenance_dispatch"]
  _dispatch(dispatch)
  ids = {dispatch["dispatch_id"]} - {None}
  successors, unknown, failed = set(), dispatch["state"] == "unknown", False
  for run_id, item in items.items():
    facts, launch = item["facts"], item["launch_dispatch"]
    _dispatch(launch)
    if (item["stop_phase"] == "accepted" and facts["stop_requested"]
        or item["stop_phase"] == "stop_requested" and not facts["stop_requested"]
        or item["stop_phase"] == "stopped_confirmed" and not (facts["exit_confirmed"] and facts["resources_released"])):
      _invalid()
    if launch["state"] == "not_dispatched":
      if launch["new_run_id"] is not None or item["restore_phase"] in ("launch_dispatched", "restored"):
        _invalid()
    else:
      successor = launch["new_run_id"]
      if successor is None or successor in result["accepted_runs"] or successor in successors or launch["dispatch_id"] in ids:
        _invalid()
      successors.add(successor)
      ids.add(launch["dispatch_id"])
      if (item["stop_phase"] not in ("stopped_confirmed", "unknown")
          or not (facts["exit_confirmed"] and facts["resources_released"])
          or not facts["session_sealed"]
          or planned[run_id]["restore"]["mode"] == "manual"):
        _invalid()
      expected = {"dispatch_intent": "restore_pending", "dispatched": "launch_dispatched", "confirmed": "restored", "unknown": "unknown"}
      if item["restore_phase"] != expected[launch["state"]]:
        _invalid()
    if item["restore_phase"] == "manual" and planned[run_id]["restore"]["mode"] != "manual":
      _invalid()
    unknown |= item["stop_phase"] == "unknown" or item["restore_phase"] == "unknown" or launch["state"] == "unknown"
    failed |= item["stop_phase"] == "failed" or item["restore_phase"] == "failed"
  operation_result = result["operation_result"]
  if result["operation"] == "stop_only":
    if dispatch["state"] != "not_dispatched" or operation_result is not None or result["phase"].startswith("maintenance_"):
      _invalid()
  elif dispatch["state"] != "not_dispatched" and any(not all(item["facts"][name] for name in ("exit_confirmed", "resources_released")) for item in items.values()):
    _invalid()
  if dispatch["state"] == "not_dispatched" and operation_result is not None:
    _invalid()
  if dispatch["state"] in ("dispatch_intent", "dispatched"):
    expected_phase = "maintenance_dispatch_intent" if dispatch["state"] == "dispatch_intent" else "maintenance_running"
    if result["phase"] not in (expected_phase, "unknown", "partial") or operation_result is not None:
      _invalid()
  if dispatch["state"] == "confirmed" and operation_result is None:
    if result["phase"] != "unknown" or not result["review_required"]:
      _invalid()
    unknown = True
  if operation_result is not None:
    status = operation_result["status"]
    if dispatch["state"] not in ("confirmed", "unknown"):
      _invalid()
    if status == "unknown":
      unknown = True
    elif operation_result["exit_code"] is None or operation_result["result_digest"] is None:
      _invalid()
    if status == "succeeded" and (operation_result["exit_code"] != 0 or dispatch["state"] != "confirmed"):
      _invalid()
    if status == "failed":
      failed = True
      if operation_result["exit_code"] == 0:
        _invalid()
    if status == "partial":
      unknown = True
  if unknown and (result["phase"] not in ("unknown", "partial") or not result["review_required"]):
    _invalid()
  if result["phase"] in ("failed", "partial", "unknown") and not result["review_required"]:
    _invalid()
  if failed and result["phase"] not in ("failed", "partial", "unknown"):
    _invalid()
  all_stopped = all(item["stop_phase"] == "stopped_confirmed" for item in items.values())
  if result["phase"] == "accepted" and (dispatch["state"] != "not_dispatched" or any(item["stop_phase"] != "accepted" or item["restore_phase"] != "not_requested" for item in items.values())):
    _invalid()
  if result["phase"] == "stop_requested" and (dispatch["state"] != "not_dispatched" or not any(item["stop_phase"] in ("stop_requested", "stopped_confirmed") for item in items.values())):
    _invalid()
  if result["phase"] == "stopped_confirmed" and (dispatch["state"] != "not_dispatched" or any(item["launch_dispatch"]["state"] != "not_dispatched" for item in items.values())):
    _invalid()
  if result["phase"] in ("stopped_confirmed", "restore_pending", "launch_dispatched", "restored") and not all_stopped:
    _invalid()
  expected_dispatch = {"maintenance_dispatch_intent": "dispatch_intent", "maintenance_running": "dispatched", "maintenance_succeeded": "confirmed"}
  if result["phase"] in expected_dispatch and (not all_stopped or dispatch["state"] != expected_dispatch[result["phase"]]):
    _invalid()
  if result["phase"] == "maintenance_succeeded" and (operation_result is None or operation_result["status"] != "succeeded"):
    _invalid()
  restoring = any(item["restore_phase"] in ("restore_pending", "launch_dispatched", "restored") or item["launch_dispatch"]["state"] != "not_dispatched" for item in items.values())
  if result["operation"] == "setup" and restoring:
    old_contract = dispatch["state"] == "not_dispatched" and operation_result is None
    new_contract = dispatch["state"] == "confirmed" and operation_result is not None and operation_result["status"] == "succeeded"
    if not (old_contract or new_contract):
      _invalid()
  if result["phase"] == "restore_pending" and not any(item["restore_phase"] == "restore_pending" for item in items.values()):
    _invalid()
  if result["phase"] == "launch_dispatched" and not any(item["launch_dispatch"]["state"] == "dispatched" for item in items.values()):
    _invalid()
  if result["phase"] == "restored" and any(item["restore_phase"] != "restored" for item in items.values()):
    _invalid()
  result["items"] = [items[run_id] for run_id in sorted(items)]
  return result


def _encode(value, kind):
  try:
    _shape(value)
    normalized = {"stop-plan": _plan, "batch": _batch, "stop-acceptance": _acceptance}[kind](value)
    return _dump(normalized) + b"\n"
  except Exception:
    raise Conflict(_ERROR) from None


def _decode(raw, kind):
  try:
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
      _invalid()
    value = json.loads(raw.decode("utf8"), object_pairs_hook=_pairs, parse_float=_invalid, parse_constant=_invalid)
    _shape(value)
    return {"stop-plan": _plan, "batch": _batch, "stop-acceptance": _acceptance}[kind](value)
  except Exception:
    raise Conflict(_ERROR) from None


def encode_stop_plan(plan):
  return _encode(plan, "stop-plan")


def decode_stop_plan(raw):
  return _decode(raw, "stop-plan")


def encode_batch(batch):
  return _encode(batch, "batch")


def decode_batch(raw):
  return _decode(raw, "batch")



def _initial_batch(batch_id, plan):
  return {"schema_version": 1, "kind": "maintenance-batch", "protocol": _PROTOCOL,
    "batch_id": batch_id, "revision": 0, "plan": plan, "operation": plan["operation"],
    "accepted_runs": list(plan["selected_runs"]), "phase": "accepted",
    "items": [{"run_id": run, "stop_phase": "accepted", "restore_phase": "not_requested",
      "facts": {"stop_requested": False, "exit_confirmed": False, "resources_released": False, "session_sealed": False},
      "launch_dispatch": {"state": "not_dispatched", "dispatch_id": None, "new_run_id": None}}
      for run in plan["selected_runs"]],
    "maintenance_dispatch": {"state": "not_dispatched", "dispatch_id": None},
    "operation_result": None, "review_required": False}


def _acceptance(value):
  from . import run_owners
  _validate(value, "stop-acceptance")
  _dump(value)
  result = deepcopy(value)
  batch = _batch(result["batch"])
  plan = batch["plan"]
  if (type(result["expected_revision"]) is not int or not 0 <= result["expected_revision"] <= 2 ** 64 - 2
      or any(run["restore"]["mode"] != "manual" for run in plan["runs"])
      or _dump(batch) != _dump(_initial_batch(batch["batch_id"], plan))):
    _invalid()
  resource = plan["resources"][0]
  if (result["domain_id"] != resource["domain_id"] or result["domain_physical"] != resource["domain_physical"]
      or set(result["records"]) != set(plan["selected_runs"])):
    _invalid()
  for run in plan["runs"]:
    run_id, scope = run["run_id"], run["scope"]
    record = result["records"][run_id]
    binding = {name: scope[name] for name in ("machine", "local", "profile")}
    registry = run_owners.Registry(Path("/run-owners"), binding)
    if type(record.get("schema_version")) is not int or record["schema_version"] != 2:
      _invalid()
    # 仅内存校验；不调用 Registry 的目录/锁/快照方法，也不检查保存路径是否存在。
    registry._validate_record(run_id + ".json", record)
    if (run_owners.record_state(record) != "active" or record["agent"] != scope["agent"]
        or record["profile"] != scope["profile"]
        or record["machine_ref"] != {name: scope[name] for name in ("machine", "local")}
        or hashlib.sha256(run_owners._encode(record)).hexdigest() != run["observation"]["record_digest"]
        or hashlib.sha256(run_owners._encode(record["deployed_identity"])).hexdigest() != run["deployment_digest"]):
      _invalid()
    manager = {name: record["manager_identity"][name] for name in ("pid", "birth_id")}
    host = record["host_identity"]
    if (host is None or manager != run["observation"]["manager_identity"]
        or {name: host["identity"][name] for name in ("pid", "birth_id")} != run["observation"]["host_identity"]):
      _invalid()
    coordinated = record["coordination_domain"]
    if coordinated is not None and (coordinated["domain_id"] != result["domain_id"]
        or coordinated["domain_physical"] != result["domain_physical"]):
      _invalid()
  result["batch"] = batch
  result["records"] = {run: result["records"][run] for run in sorted(result["records"])}
  return result


def build_stop_acceptance(*, batch_id, plan, records, expected_revision):
  """保存仅 manual 的完整恢复快照；数据有效不表示当前确认或控制许可。"""
  try:
    supplied = {"batch_id": batch_id, "plan": plan, "records": records, "expected_revision": expected_revision}
    _shape(supplied)
    _dump(supplied)
    normalized = _plan(plan)
    resource = normalized["resources"][0]
    return _acceptance({"schema_version": 1, "kind": "stop-acceptance", "protocol": _PROTOCOL,
      "domain_id": resource["domain_id"], "domain_physical": deepcopy(resource["domain_physical"]),
      "expected_revision": expected_revision, "batch": _initial_batch(batch_id, normalized), "records": records})
  except Exception:
    raise Conflict(_ERROR) from None


def encode_stop_acceptance(value):
  return _encode(value, "stop-acceptance")


def decode_stop_acceptance(raw):
  return _decode(raw, "stop-acceptance")
