"""逐受管项三方部署；单份 previous 和可恢复 pending，不保存混合原生文件。"""

import base64
from copy import deepcopy
from dataclasses import dataclass, field
import json
import hashlib
from pathlib import Path

import yaml

from .adapter import Ownership
from .config import _credential_name
from .storage import Conflict, Tree, instance_lock


ABSENT = {"present": False}


def encoded(value):
  return {"present": True, "value": value}


def json_bytes(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False, separators=(",", ":")) + "\n").encode()


def same(left, right):
  # 原生 false 与数字 0 不是同一个部署值。
  return json_bytes(left) == json_bytes(right)


def safe_projection(value):
  """拒绝受管投影中的明文凭据通道与可执行对象；未知原生字段不参与快照。"""
  if isinstance(value, dict):
    for key, child in value.items():
      if not isinstance(key, str) or key == "__jsExpr" or (_credential_name(key) and not key.endswith("_ref")):
        raise Conflict("受管字段出现凭据或可执行内容，不能备份")
      safe_projection(child)
  elif isinstance(value, list):
    for child in value:
      safe_projection(child)


def pointer(selector):
  if not selector.startswith("/"):
    raise Conflict("字段选择器必须为 JSON Pointer")
  return tuple(part.replace("~1", "/").replace("~0", "~") for part in selector[1:].split("/"))


def get_field(document, selector):
  current = document
  for key in pointer(selector):
    if not isinstance(current, dict):
      raise Conflict("原生父字段类型已变化")
    if key not in current:
      return ABSENT.copy()
    current = current[key]
  safe_projection(current)
  return encoded(deepcopy(current))


def put_field(document, selector, value):
  parts = pointer(selector)
  current = document
  for key in parts[:-1]:
    if key not in current:
      if not value["present"]:
        return
      current[key] = {}
    if not isinstance(current[key], dict):
      raise Conflict("无法修改类型已变化的原生父字段")
    current = current[key]
  if value["present"]:
    current[parts[-1]] = deepcopy(value["value"])
  else:
    current.pop(parts[-1], None)


def missing_parents(document, selector):
  result, parts, current = [], [], document
  for key in pointer(selector)[:-1]:
    parts.append(key.replace("~", "~0").replace("/", "~1"))
    if key not in current:
      result.append("/" + "/".join(parts))
      current = {}
    else:
      current = current[key]
      if not isinstance(current, dict):
        raise Conflict("原生父字段类型已变化")
  return result


def prune_created_parents(document, selectors):
  for selector in sorted(selectors, key=lambda value: len(pointer(value)), reverse=True):
    parts = pointer(selector)
    current = document
    for key in parts[:-1]:
      current = current.get(key, {})
      if not isinstance(current, dict):
        break
    if isinstance(current, dict) and current.get(parts[-1]) == {}:
      current.pop(parts[-1], None)


def parse_native(content, codec):
  try:
    value = NATIVE_CODECS[codec][0](content)
  except Exception:
    raise Conflict("原生配置格式无效或包含未允许 YAML 标签") from None
  if value is None:
    value = {}
  if not isinstance(value, dict):
    raise Conflict("字段受管文件必须为对象")
  return value


def encode_native(value, codec):
  if codec not in NATIVE_CODECS:
    raise Conflict("字段原生格式尚未注册")
  return NATIVE_CODECS[codec][1](value)


NATIVE_CODECS = {"json": (json.loads, json_bytes),
                 "yaml": (yaml.safe_load, lambda value: yaml.safe_dump(value, allow_unicode=True, sort_keys=True).encode())}


def register_codec(name, decode, encode):
  if name in NATIVE_CODECS or not callable(decode) or not callable(encode):
    raise Conflict("原生格式重复注册或缺少安全编解码器")
  NATIVE_CODECS[name] = (decode, encode)


def item_key(item):
  return json.dumps([item["path"], item["selector"]], ensure_ascii=False)


def target_id(key):
  return "target-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def desired_items(candidate):
  result = {}
  for artifact in candidate.artifacts:
    target = artifact.target
    if target.selector:
      if target.serialization not in NATIVE_CODECS:
        raise Conflict("字段原生格式尚未注册")
      value = json.loads(artifact.content)
      safe_projection(value)
      desired = encoded(value)
    else:
      desired = encoded({"bytes": base64.b64encode(artifact.content).decode(), "mode": artifact.mode})
    item = {"path": target.path, "selector": target.selector,
            "codec": target.serialization, "ownership": target.ownership.value,
            "desired": desired}
    result[item_key(item)] = item
  values = list(result.values())
  for index, a in enumerate(values):
    for b in values[:index]:
      if a["path"] == b["path"] and (not a["selector"] or not b["selector"]
          or pointer(a["selector"])[:len(pointer(b["selector"]))] == pointer(b["selector"])
          or pointer(b["selector"])[:len(pointer(a["selector"]))] == pointer(a["selector"])):
        raise Conflict("受管字段选择器重叠")
  return result


def projection(tree, item):
  raw = tree.read(item["path"])
  if raw is None:
    return ABSENT.copy()
  if item["selector"]:
    return get_field(parse_native(raw[0], item["codec"]), item["selector"])
  return encoded({"bytes": base64.b64encode(raw[0]).decode(), "mode": raw[1]})


def read_state(tree):
  raw = tree.read("deployment.json")
  if raw is None:
    return {"version": 1, "current": None, "previous": None, "owner": None}
  if raw[1] != 0o600:
    raise Conflict("部署状态文件必须为 0600")
  try:
    state = json.loads(raw[0])
    if state["version"] != 1 or set(state) not in ({"version", "current", "previous"}, {"version", "current", "previous", "owner"}):
      raise ValueError()
    return normalize_state(state)
  except Exception:
    raise Conflict("部署状态损坏；不能自动接管") from None


def normalize_state(state):
  state = deepcopy(state)
  if "owner" not in state:
    current = state["current"]
    state["owner"] = {"binding": current["binding"], "shared_files": current["launch"].get("shared_files", [])} if current else None
  return state


@dataclass
class Plan:
  current: dict = field(repr=False)
  changes: list = field(repr=False)
  drift: list = field(repr=False)
  conflicts: list = field(repr=False)

  def public(self):
    # 不输出文件名或动态 selector，可能含私有模型和 endpoint。
    known = {"dsh-home/settings.yaml", "dsh-home/AGENTS.md", "dsh-home/agentcfg.patch.yml", "env-guard.mjs",
             "user-home/.dsh-tui/themes/rotom-poimandres.json"}
    entries = [{"id": target_id(item_key(c["item"])), "target": c["item"]["path"] if c["item"]["path"] in known else "<managed-resource>",
                "field": "<managed-field>" if c["item"]["selector"] else None,
                "action": "add" if not c["before"]["present"] else "remove" if not c["after"]["present"] else "update",
                "value": "<redacted>"} for c in self.changes]
    def locations(keys):
      result = []
      for key in keys:
        path, selector = json.loads(key)
        result.append({"id": target_id(key), "target": path if path in known else "<managed-resource>",
                       "field": "<managed-field>" if selector else None})
      return result
    return {"changes": len(self.changes), "drift": len(self.drift), "conflicts": len(self.conflicts), "diff": entries,
            "drift_targets": locations(self.drift), "conflict_targets": locations(self.conflicts)}

  def private_locations(self):
    keys = {item_key(change["item"]) for change in self.changes} | set(self.drift) | set(self.conflicts)
    return [{"id": target_id(key), "path": json.loads(key)[0], "selector": json.loads(key)[1]} for key in sorted(keys)]


def plan(tree, state, candidate, binding, launch):
  old = state["current"]
  owner = state.get("owner")
  if owner is not None and owner["binding"] != binding:
    raise Conflict("实例属于另一份机器配置，不能在恢复后重新接管其运行数据")
  if old is not None and old["binding"] != binding:
    raise Conflict("实例已绑定另一份机器配置；请使用独立 profile 或实例根")
  wanted = desired_items(candidate)
  previous = old["items"] if old else {}
  result, changes, drift, conflicts = {}, [], [], []
  for key in sorted(previous.keys() | wanted.keys()):
    spec = deepcopy(wanted.get(key, previous[key] if key in previous else None))
    before = previous.get(key)
    current = projection(tree, spec)
    baseline = before["baseline"] if before else ABSENT.copy()
    desired = wanted[key]["desired"] if key in wanted else ABSENT.copy()
    if before and any(before[name] != spec[name] for name in ("codec", "ownership", "selector", "path")):
      conflicts.append(key)
      continue
    if before is None and tree.read(spec["path"]) is not None:
      raw = tree.read(spec["path"])
      # 首次接管按文件检查：即使要管理的字段不存在也不能接管非空文件。
      known_file = spec["selector"] and (any(i["path"] == spec["path"] and i["selector"] for i in previous.values())
        or owner is not None and spec["path"] in owner["shared_files"])
      if raw[0] and (not known_file or current["present"]):
        conflicts.append(key)
        continue
    if spec["ownership"] == Ownership.INITIALIZE.value and before:
      result[key] = deepcopy(before)
      continue
    if same(current, desired):
      baseline = desired
    elif same(current, baseline):
      raw_file = tree.read(spec["path"])
      parents = missing_parents(parse_native(raw_file[0], spec["codec"]) if raw_file else {}, spec["selector"]) if spec["selector"] else []
      changes.append({"item": spec, "before": current, "after": desired,
                      "created_file": raw_file is None, "created_parents": parents})
      baseline = desired
    elif same(desired, baseline):
      drift.append(key)
    else:
      conflicts.append(key)
      continue
    if key in wanted or not same(current, desired):
      spec["baseline"] = baseline
      spec.pop("desired", None)
      result[key] = spec
  manifest = {"generation": candidate.generation, "binding": binding, "launch": launch, "items": result}
  return Plan(manifest, changes, drift, conflicts)


def write_changes(target, changes, *, reverse=False):
  """按文件合并当前原生数据；恢复时同样逐字段检查，不复制整文件前值。"""
  groups = {}
  for change in changes:
    groups.setdefault(change["item"]["path"], []).append(change)
  for path, group in groups.items():
    raw = target.read(path)
    item = group[0]["item"]
    document = parse_native(raw[0], item["codec"]) if raw and item["selector"] else {}
    changed = False
    content = None
    mode = 0o600
    for change in group:
      item = change["item"]
      before, after = (change["after"], change["before"]) if reverse else (change["before"], change["after"])
      current = get_field(document, item["selector"]) if item["selector"] else projection(target, item)
      if same(current, after):
        continue
      if not same(current, before):
        raise Conflict("受管字段在操作期间变化；保留恢复记录，请先处理冲突")
      changed = True
      if item["selector"]:
        put_field(document, item["selector"], after)
        if not after["present"]:
          prune_created_parents(document, change.get("created_parents", []))
      elif after["present"]:
        content = base64.b64decode(after["value"]["bytes"], validate=True)
        mode = after["value"]["mode"]
    if not changed:
      continue
    if item["selector"]:
      content = None if not document and any(c.get("created_file") for c in group) else encode_native(document, item["codec"])
      mode = 0o600
    target.replace(path, content, mode, expected=raw[2] if raw else None)


def recover(target, state):
  raw = state.read("pending.json")
  if raw is None:
    return False
  try:
    journal = json.loads(raw[0])
    committed = same(read_state(state), normalize_state(journal["after_state"]))
  except Exception:
    raise Conflict("恢复记录损坏，停止修改") from None
  if not committed:
    write_changes(target, journal["changes"], reverse=True)
  state.replace("pending.json", None, expected=raw[2])
  return True


def transact(target, state, old_state, after_state, changes):
  journal = {"after_state": after_state, "changes": changes}
  state.write_state("pending.json", json_bytes(journal))
  try:
    write_changes(target, changes)
    state.write_state("deployment.json", json_bytes(after_state))
  except BaseException:
    # 若恢复也冲突则保留 journal。进程硬中断由下次操作恢复。
    recover(target, state)
    raise
  recover(target, state)


def apply(instance: Path, state_root: Path, candidate, binding, launch):
  with Tree(state_root, create=True) as state, instance_lock(state):
    with Tree(instance, create=True) as target:
      recover(target, state)
      old = read_state(state)
      change = plan(target, old, candidate, binding, launch)
      if change.conflicts:
        raise Conflict("部署有未接管目标或双方修改冲突；请先查看 plan")
      if same(old["current"], change.current) and not change.changes:
        return change.public()
      # 只变更基线（如 C=D）也记录当前事实，但无实际变更不轮换 previous。
      binding_changed = old["current"] is None or old["current"]["launch"] != launch
      previous = {"current": old["current"], "changes": change.changes} if change.changes or binding_changed else old["previous"]
      owner = old.get("owner") or {"binding": binding, "shared_files": launch.get("shared_files", [])}
      after = {"version": 1, "current": change.current, "previous": previous, "owner": owner}
      transact(target, state, old, after, change.changes)
      return change.public()


def rollback(instance: Path, state_root: Path, binding):
  with Tree(state_root, create=True) as state, instance_lock(state), Tree(instance) as target:
    recover(target, state)
    old = read_state(state)
    if not old["current"] or old["current"]["binding"] != binding:
      raise Conflict("不存在属于当前机器配置的部署")
    if old["previous"] is None:
      raise Conflict("没有上一版备份可恢复")
    backup = old["previous"]
    changes = [{**c, "before": c["after"], "after": c["before"]} for c in backup["changes"]]
    # 先检查全部受管项，避免已知冲突时进行部分恢复。
    for change in changes:
      current = projection(target, change["item"])
      if not same(current, change["before"]) and not same(current, change["after"]):
        raise Conflict("受管内容已在部署后修改；恢复冲突")
    after = {"version": 1, "current": backup["current"], "previous": None, "owner": old.get("owner")}
    transact(target, state, old, after, changes)
    return {"restored": len(changes)}
