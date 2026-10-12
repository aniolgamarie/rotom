"""Pi 替换侧记录；部署 journal 是唯一配置提交权威，侧记录不授予权限。"""
import json
import re

from . import deployment
from .activity import digest
from .storage import Conflict, Tree, instance_lock


PHASES = frozenset({"staged", "validated", "activation-pending", "active", "retired", "restored", "recovery-required"})
MAX_RECORD = 1024 * 1024


def _fail():
  raise Conflict("Pi提供者替换记录或兼容材料无效；保留旧运行包")


def _hex(value):
  if type(value) is not str or not re.fullmatch(r"[0-9a-f]{64}", value): _fail()
  return value


def _runtime(launch):
  return None if launch is None else _hex(launch.get("runtime_identity", launch.get("lock_identity")))


def _launch_digest(launch):
  if launch is None: return digest(None)
  # 仅原 runtime/lock 两个闭合身份，不散列 argv/machine/env 任意用户正文。
  # 配置项仍由唯一 deployment journal 校验；侧记录只判断包的选择关系。
  return digest({"runtime": _runtime(launch), "lock": _hex(launch.get("lock_identity"))})


def _descriptor(value):
  if type(value) is not dict or set(value) != {"schema_version", "profile", "providers"}: _fail()
  if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["profile"] not in ("pi-base", "pi-full"): _fail()
  if type(value["providers"]) is not list or not value["providers"]: _fail()
  seen = set()
  for row in value["providers"]:
    if type(row) is not dict or set(row) != {"capability_id", "provider_id", "contract_version", "source_identity", "implementation_identity", "state_owners", "config_fields"}: _fail()
    for name in ("capability_id", "provider_id"):
      if type(row[name]) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", row[name]): _fail()
    if row["capability_id"] in seen: _fail()
    seen.add(row["capability_id"])
    if type(row["contract_version"]) is not str or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", row["contract_version"]): _fail()
    _hex(row["source_identity"])
    _hex(row["implementation_identity"])
    for name in ("state_owners", "config_fields"):
      if type(row[name]) is not list or any(type(item) is not str for item in row[name]) or len(set(row[name])) != len(row[name]): _fail()
    from .pi_capabilities import _ids, _pointers
    try:
      _ids(row["state_owners"]); _pointers(row["config_fields"])
    except Exception: _fail()
  return value


def descriptor(lock, profile):
  """仅从后端已验证过的能力选择提取非秘密兼容声明。"""
  selected = lock.validated_bindings[profile]
  if selected.state == "candidate": _fail()
  bindings = lock.metadata["capability_bindings"]
  rows = []
  for pair in bindings["selections"][profile]["bindings"]:
    provider = bindings["providers"][pair["provider_id"]]
    row = {name: provider[name] for name in ("capability_id", "provider_id", "contract_version", "source_identity", "state_owners", "config_fields")}
    # 辅助依赖、实际实现入口及版本同时绑定；主 source 没变不代表有状态实现没变。
    row["implementation_identity"] = digest(provider)
    rows.append(row)
  return _descriptor({"schema_version": 1, "profile": profile, "providers": sorted(rows, key=lambda row: row["capability_id"])})


def _read(tree):
  raw = tree.read("replacement.json", max_bytes=MAX_RECORD)
  if raw is None: return None
  try:
    record = json.loads(raw[0])
    fields = {"schema_version", "binding", "phase", "old_runtime", "new_runtime", "old_launch_digest", "new_launch_digest", "contracts"}
    if raw[1] != 0o600 or type(record) is not dict or set(record) != fields: _fail()
    if type(record["schema_version"]) is not int or record["schema_version"] != 1 or record["phase"] not in PHASES: _fail()
    for name in ("old_runtime", "old_launch_digest"):
      if record[name] is not None: _hex(record[name])
    _hex(record["new_runtime"]); _hex(record["new_launch_digest"])
    if type(record["binding"]) is not dict or type(record["contracts"]) is not dict or len(record["contracts"]) > 64: _fail()
    for identity, value in record["contracts"].items(): _hex(identity); _descriptor(value)
    if record["new_runtime"] not in record["contracts"]: _fail()
    if (record["old_runtime"] is None) != (record["old_launch_digest"] is None): _fail()
    if any(value["profile"] != record["contracts"][record["new_runtime"]]["profile"] for value in record["contracts"].values()): _fail()
    return record
  except (ValueError, KeyError, TypeError): _fail()


def _write(tree, record):
  raw = deployment.json_bytes(record)
  if len(raw) > MAX_RECORD: _fail()
  tree.write_state("replacement.json", raw)


def _current(state):
  current = deployment.read_state(state)["current"]
  return current, None if current is None else current["launch"]


def _equivalent(old, new):
  """首个自动切换边界仅接纳无状态等价提供者；同名 owner 不证明格式兼容。"""
  old = _descriptor(old); new = _descriptor(new)
  if old["profile"] != new["profile"]: _fail()
  left = {row["capability_id"]: row for row in old["providers"]}
  right = {row["capability_id"]: row for row in new["providers"]}
  if set(left) != set(right): _fail()
  for name, row in left.items():
    following = right[name]
    if row == following: continue
    if row["state_owners"] or following["state_owners"]: _fail()
    if row["contract_version"] != following["contract_version"] or set(row["config_fields"]) != set(following["config_fields"]): _fail()


def _owned(w, record):
  if record is not None and (record["binding"] != w.binding or record["contracts"][record["new_runtime"]]["profile"] != w.profile): _fail()


def _bind(contracts, identity, contract):
  if identity in contracts and contracts[identity] != contract: _fail()
  contracts[identity] = contract


def _settle(w, tree, record):
  current, launch = _current(tree)
  _owned(w, record)
  if tree.read("pending.json"):
    phase = "recovery-required"
  elif current is not None and current["binding"] != w.binding:
    phase = "recovery-required"
  elif _launch_digest(launch) == record["new_launch_digest"]:
    phase = "active" if w.backend.status(w, record["new_runtime"]) == "installed" else "recovery-required"
  elif (launch is None and record["old_runtime"] is None
      or launch is not None and _launch_digest(launch) == record["old_launch_digest"]):
    phase = "restored" if launch is None or w.backend.status(w, _runtime(launch)) == "installed" else "recovery-required"
  else:
    phase = "recovery-required"
  _write(tree, {**record, "phase": phase})
  return phase


def record_validated(w, launch, contract):
  """调用方持原 source/lifecycle guard；安装事实不能宣称被选中。"""
  _descriptor(contract)
  identity = _runtime(launch)
  if contract["profile"] != w.profile or w.backend.status(w, identity) != "installed": _fail()
  with Tree(w.state_root, create=True) as tree, instance_lock(tree):
    if tree.read("pending.json"): _fail()
    record = _read(tree); _owned(w, record)
    if record is not None and record["phase"] in ("activation-pending", "recovery-required"): _fail()
    current, old = _current(tree)
    if current is not None and current["binding"] != w.binding: _fail()
    contracts = {} if record is None else dict(record["contracts"])
    _bind(contracts, identity, contract)
    value = {"schema_version": 1, "binding": w.binding, "phase": "validated", "old_runtime": _runtime(old), "new_runtime": identity,
      "old_launch_digest": None if old is None else _launch_digest(old), "new_launch_digest": _launch_digest(launch), "contracts": contracts}
    # 重复 sync 当前包保持已结算状态，不轮换为 pending。
    if record is not None and old == launch and record["new_runtime"] == identity and record["phase"] == "active":
      value["phase"] = "active"
    _write(tree, value)


def apply(w, candidate, launch, contract, *, expected_plan=None):
  _descriptor(contract)
  identity = _runtime(launch)
  if contract["profile"] != w.profile or w.backend.status(w, identity) != "installed": _fail()
  with Tree(w.state_root, create=True) as tree, instance_lock(tree):
    if tree.read("pending.json"): _fail()
    record = _read(tree); _owned(w, record)
    if record is not None and record["phase"] in ("activation-pending", "recovery-required"): _fail()
    current, old = _current(tree)
    if current is not None and current["binding"] != w.binding: _fail()
    contracts = {} if record is None else dict(record["contracts"])
    if old is not None and _runtime(old) != identity:
      if _runtime(old) not in contracts: _fail()
      _equivalent(contracts[_runtime(old)], contract)
    _bind(contracts, identity, contract)
    record = {"schema_version": 1, "binding": w.binding, "phase": "activation-pending", "old_runtime": _runtime(old), "new_runtime": identity,
      "old_launch_digest": None if old is None else _launch_digest(old), "new_launch_digest": _launch_digest(launch), "contracts": contracts}
    _write(tree, record)
  try:
    result = deployment.apply(w.instance, w.state_root, candidate, w.binding, launch, expected_plan=expected_plan)
  except BaseException:
    # 保留原错误；侧记录失败不伪造恢复成功或遮盖原 journal。
    try:
      with Tree(w.state_root) as tree, instance_lock(tree): _settle(w, tree, record)
    except Exception:
      pass
    raise
  with Tree(w.state_root) as tree, instance_lock(tree):
    if _settle(w, tree, record) != "active": _fail()
  return result


def recover(w):
  """显式原配置恢复后对账，不重放 apply，不更改 pointer 来猜测提交。"""
  with Tree(w.state_root, create=True) as tree, instance_lock(tree), Tree(w.instance) as target:
    record = _read(tree); _owned(w, record)
    current, _ = _current(tree)
    if current is not None and current["binding"] != w.binding: _fail()
    recovered = deployment.recover(target, tree)
    phase = None if record is None else _settle(w, tree, record)
    return {"configuration_recovered": recovered, "replacement_phase": phase}


def rollback(w):
  with Tree(w.state_root) as tree, instance_lock(tree):
    _owned(w, _read(tree))
  result = deployment.rollback(w.instance, w.state_root, w.binding)
  with Tree(w.state_root) as tree, instance_lock(tree):
    record = _read(tree); _owned(w, record)
    if record is not None: _settle(w, tree, record)
  return result


def status(w):
  """只读：保存阶段与原实际指针分开返回，查询不触发恢复。"""
  with Tree(w.state_root) as tree:
    if tree.fd is None: return {"phase": None, "pointer_relation": "absent", "recovery_pending": False}
    record = _read(tree); _owned(w, record)
    _, launch = _current(tree)
    relation = "untracked"
    if record is not None:
      if launch is not None and _launch_digest(launch) == record["new_launch_digest"]: relation = "new"
      elif launch is None and record["old_runtime"] is None or launch is not None and _launch_digest(launch) == record["old_launch_digest"]: relation = "old"
      else: relation = "other"
    return {"phase": None if record is None else record["phase"], "pointer_relation": relation, "recovery_pending": tree.read("pending.json") is not None}


def assert_runnable(w):
  value = status(w)
  if value["phase"] in ("activation-pending", "recovery-required") or value["phase"] == "active" and value["pointer_relation"] != "new":
    raise Conflict("Pi提供者替换尚待明确恢复；未重新部署或重派旧工作")


def references(w, identity):
  """只解释固定原权威；未知会话/任务 store 不猜为空，不触发清理。"""
  _hex(identity)
  result = []
  with Tree(w.state_root) as tree:
    if tree.fd is not None:
      state = deployment.read_state(tree)
      current = state["current"]
      previous = None if state["previous"] is None else state["previous"]["current"]
      for name, value in (("deployment-current", current), ("deployment-previous", previous)):
        if value is not None and _runtime(value["launch"]) == identity: result.append(name)
      if tree.read("pending.json"): result.append("deployment-pending-unknown")
      record = _read(tree); _owned(w, record)
      if record is not None and record["phase"] in ("activation-pending", "recovery-required") and identity in (record["old_runtime"], record["new_runtime"]): result.append("replacement-recovery")
  from .pi_lifecycle import assert_inactive
  try: assert_inactive(w.state_root)
  except Conflict: result.append("execution-active-or-unknown")
  for name in ("delegate", "durable", "task-keeper", "activity"):
    path = w.state_root / name
    if path.exists() or path.is_symlink(): result.append(name + "-reference-unknown")
  for name in ("model-delegate", "durable", "task-keeper"):
    path = w.instance / "pi-home" / name
    if path.exists() or path.is_symlink(): result.append(name + "-reference-unknown")
  # 原生 session 没有跨 runtime 版本的引用退休 API；存在即保守保护。
  for path in (w.instance / "session.jsonl", w.instance / "pi-home/sessions", w.instance / "user-home/.pi/agent/sessions"):
    if path.exists() or path.is_symlink(): result.append("native-session-unknown"); break
  # Full 的额外存储格式尚没有完整退休查询，不能用空目录或 lease 已终止推定引用清零。
  if w.profile == "pi-full": result.append("full-store-reference-unknown")
  return sorted(set(result))


def uninstall(w, identity):
  """调用方持原独占生命周期 guard；只删除原 backend 管理的无引用包。"""
  _hex(identity)
  root = w.backend.root(w, identity)
  if root != w.instance / "runtimes" / identity: _fail()
  with Tree(w.state_root, create=True) as tree, instance_lock(tree):
    blockers = references(w, identity)
    if blockers:
      raise Conflict("Pi旧包仍有活动、配置或未知恢复引用；未删除任何资源")
    if w.backend.status(w, identity) != "installed": _fail()
    from .runtime_packages import remove_backup
    remove_backup(root, identity)
    record = _read(tree); _owned(w, record)
    if record is not None and record["new_runtime"] == identity:
      _write(tree, {**record, "phase": "retired"})
  return {"removed": True, "runtime_identity": identity, "user_data_removed": False}
