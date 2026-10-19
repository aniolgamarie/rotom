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
from .native import load_cordis, dump_cordis
from .native_projection import (reference_guard, reverse_change, transition_guard,
                                validate_change, validate_projection, validate_saved_state)


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
                 "yaml": (yaml.safe_load, lambda value: yaml.safe_dump(value, allow_unicode=True, sort_keys=True).encode()),
                 "cordis-yaml": (load_cordis, dump_cordis)}


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
    if target.reference_tokens:
      item["guard"] = reference_guard(target.reference_tokens)
      validate_projection(desired, item["guard"])
    from .native_projection import validate_item_guard
    validate_item_guard(item, desired)
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
  from .native_projection import validate_item_guard
  validate_item_guard(item, item.get("baseline", item.get("desired", ABSENT)))
  raw = tree.read(item["path"])
  if raw is None:
    return ABSENT.copy()
  if item["selector"]:
    result = get_field(parse_native(raw[0], item["codec"]), item["selector"])
    validate_projection(result, item.get("guard"))
    return result
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
    state = normalize_state(state)
    validate_saved_state(state)
    return state
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
  validate_saved_state(state)
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
    # 空祖先只有最初由管理器创建时才拥有；跨多次部署保留这份来源，
    # 使退出模块能删除自己的空容器而不清理用户原生对象。
    if spec["selector"]:
      spec["created_parents"] = deepcopy(before.get("created_parents", [])) if before else missing_parents(
        parse_native(tree.read(spec["path"])[0], spec["codec"]) if tree.read(spec["path"]) else {}, spec["selector"])
    if before is not None and key in wanted and bool(before.get("guard")) != bool(spec.get("guard")):
      raise Conflict("既有字段的引用保护不能隐式新增或移除")
    current = projection(tree, before if before is not None else spec)
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
      if known_file and current["present"] and spec["ownership"] == Ownership.INITIALIZE.value:
        # 已拥有共享文件中的原生偏好只消费初始化机会，不认领其值为基线。
        spec["baseline"] = ABSENT.copy()
        spec.pop("desired", None)
        result[key] = spec
        continue
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
      parents = list(dict.fromkeys(spec.get("created_parents", []) + (
        missing_parents(parse_native(raw_file[0], spec["codec"]) if raw_file else {}, spec["selector"]) if spec["selector"] else [])))
      changes.append({"item": spec, "before": current, "after": desired,
                      "created_file": raw_file is None, "created_parents": parents,
                      **({"before_guard": before["guard"]} if before and before.get("guard") else {})})
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
    validate_change(change)
    if reverse:
      change = reverse_change(change)
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
      before, after = change["before"], change["after"]
      current = get_field(document, item["selector"]) if item["selector"] else projection(target, item)
      validate_projection(current, transition_guard(change.get("before_guard"), item.get("guard")))
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


def recover(target, state, *, prepare=None):
  raw = state.read("pending.json")
  if raw is None:
    return False
  try:
    journal = json.loads(raw[0])
    if "prepare_launch" in journal and journal["prepare_launch"] is not True:
      raise ValueError()
    validate_saved_state(journal["after_state"])
    for change in journal["changes"]:
      validate_change(change)
    committed = same(read_state(state), normalize_state(journal["after_state"]))
  except Exception:
    raise Conflict("恢复记录损坏，停止修改") from None
  # 在恢复任何文件前检查整个当前/待恢复受管认证集合，不能等逐文件
  # 恢复到末尾才发现后面的原生引用已被替换成明文。
  validate_reference_targets(target, read_state(state), journal["after_state"], changes=journal["changes"])
  if journal.get("prepare_launch") and prepare is None:
    raise Conflict("启动资源准备待恢复；请执行 apply/rollback")
  if not committed:
    write_changes(target, journal["changes"], reverse=True)
  if journal.get("prepare_launch"):
    # 配置事实决定恢复到哪套投影；成功准备后才允许移除恢复记录。
    current = read_state(state)["current"]
    if current is not None:
      prepare(current["launch"])
  state.replace("pending.json", None, expected=raw[2])
  return True


def validate_reference_targets(target, *states, changes=()):
  from .native_projection import is_omp_credential, is_pi_credential, validate_item_guard
  items = {}
  for state in states:
    current = state.get("current")
    for item in (current or {}).get("items", {}).values():
      if is_omp_credential(item) or is_pi_credential(item):
        key = item_key(item)
        previous = items.get(key, {})
        items[key] = {**item, "guard": transition_guard(previous.get("guard"), item.get("guard"))}
  for change in changes:
    item = change["item"]
    if is_omp_credential(item) or is_pi_credential(item):
      key = item_key(item)
      items[key] = {**item, "guard": transition_guard(items.get(key, {}).get("guard"),
        transition_guard(change.get("before_guard"), item.get("guard")))}
  for item in items.values():
    value = projection(target, item)
    validate_item_guard(item, value)


def transact(target, state, old_state, after_state, changes, *, prepare=None):
  validate_saved_state(old_state)
  validate_saved_state(after_state)
  for change in changes:
    validate_change(change)
  journal = {"after_state": after_state, "changes": changes,
    **({"prepare_launch": True} if prepare is not None else {})}
  state.write_state("pending.json", json_bytes(journal))
  try:
    if prepare is not None and after_state["current"] is not None:
      prepare(after_state["current"]["launch"])
    write_changes(target, changes)
    state.write_state("deployment.json", json_bytes(after_state))
  except BaseException:
    # 若恢复也冲突则保留 journal。进程硬中断由下次操作恢复。
    recover(target, state, prepare=prepare)
    raise
  recover(target, state, prepare=prepare)


def guard_saved_state(state, state_guard):
  """可选适配器准入先于恢复；不改默认恢复与回滚协议。"""
  if state_guard is None:
    return
  saved = read_state(state)
  pending = state.read("pending.json")
  try:
    journal = json.loads(pending[0]) if pending else None
    if journal is not None and not isinstance(journal, dict):
      raise ValueError()
  except (ValueError, TypeError):
    raise Conflict("恢复记录损坏，停止修改") from None
  state_guard({**saved, "pending": journal})


def apply(instance: Path, state_root: Path, candidate, binding, launch, *, expected_plan=None, state_guard=None, prepare=None):
  with Tree(state_root, create=True) as state, instance_lock(state):
    guard_saved_state(state, state_guard)
    with Tree(instance, create=True) as target:
      recover(target, state, prepare=prepare)
      old = read_state(state)
      change = plan(target, old, candidate, binding, launch)
      if expected_plan is not None and change != expected_plan:
        raise Conflict("预览后部署状态已变化；请重新运行 setup")
      if change.conflicts:
        raise Conflict("部署有未接管目标或双方修改冲突；请先查看 plan")
      # 只在计划通过后保留实际管理过的共享文件来源，支持动态模块退出再选；
      # 不预认领候选路径，也不保存原生未知字段的内容。
      owner = deepcopy(old.get("owner")) or {"binding": binding, "shared_files": launch.get("shared_files", [])}
      shared = sorted({item["path"] for item in change.current["items"].values() if item["selector"]})
      owner["shared_files"] = list(dict.fromkeys([*owner["shared_files"], *shared]))
      if same(old["current"], change.current) and not change.changes and same(old.get("owner"), owner):
        if prepare is not None:
          transact(target, state, old, old, [], prepare=prepare)
        return change.public()
      # 只变更基线（如 C=D）也记录当前事实，但无实际变更不轮换 previous。
      binding_changed = old["current"] is None or old["current"]["launch"] != launch
      previous = {"current": old["current"], "changes": change.changes} if change.changes or binding_changed else old["previous"]
      after = {"version": 1, "current": change.current, "previous": previous, "owner": owner}
      transact(target, state, old, after, change.changes, prepare=prepare)
      return change.public()


def rollback(instance: Path, state_root: Path, binding, *, prepare=None):
  with Tree(state_root, create=True) as state, instance_lock(state), Tree(instance) as target:
    validate_reference_targets(target, read_state(state))
    recover(target, state, prepare=prepare)
    old = read_state(state)
    if not old["current"] or old["current"]["binding"] != binding:
      raise Conflict("不存在属于当前机器配置的部署")
    validate_reference_targets(target, old)
    if old["previous"] is None:
      raise Conflict("没有上一版备份可恢复")
    backup = old["previous"]
    changes = [reverse_change(c) for c in backup["changes"]]
    # 先检查全部受管项，避免已知冲突时进行部分恢复。
    for change in changes:
      item = {**change["item"], "guard": transition_guard(change.get("before_guard"), change["item"].get("guard"))}
      current = projection(target, item)
      if not same(current, change["before"]) and not same(current, change["after"]):
        raise Conflict("受管内容已在部署后修改；恢复冲突")
    after = {"version": 1, "current": backup["current"], "previous": None, "owner": old.get("owner")}
    transact(target, state, old, after, changes, prepare=prepare)
    return {"restored": len(changes)}
