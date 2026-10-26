"""停止前快照的内部持久化接缝；不授予停止或维护许可。

基础入口只核验协调元数据；live 入口借用可信调用者已持有的物理 SH，核验
当前部署/受保护文件及 owner/资源关联，让 owner 锁覆盖意图提交。reviewed
入口另消费本进程明确审阅；真实 host 及控制通道仍须另行核验，用户 JSON、
已存清单和这里的返回值都不能构造执行许可。
先持久发布不可覆盖的私人恢复清单，再提交带摘要的资源意图。任一失败都
保留可能已发布的事实，不清理、不重试，不调用宿主或恢复执行器。
"""

from contextlib import contextmanager, ExitStack
from copy import deepcopy
import hashlib

from . import maintenance, resource_owners, run_owners
from .resource_coordination import _physical
from .storage import Conflict, Tree


_ERROR = "停止前恢复清单或资源意图不能确认；保留现场并重新核验"


@contextmanager
def _boundary():
  try:
    yield
  except Exception:
    raise Conflict(_ERROR) from None


def _name(batch_id):
  run_owners._run_id(batch_id)
  return "stop-acceptance-" + batch_id + ".json"


def _snapshot_matches(domain, state, value):
  """同一个短协调事务内复核范围与双向摘要；不是现场物理/进程证明。"""
  plan = value["batch"]["plan"]
  if value["domain_id"] != state["domain_id"] or value["domain_physical"] != state["physical"]:
    raise Conflict(_ERROR)
  resources = domain._resources(state, [item["resource_id"] for item in plan["resources"]])
  domain._intent_selection(state, resources, plan["selected_runs"], plan["operation"])
  for item in plan["resources"]:
    rid = item["resource_id"]
    references = sorted(run for run, entry in state["reservations"].items()
      if rid in entry["resources"] and entry["phase"] not in ("cancelled", "released"))
    if (item["key"] != state["resources"][rid]["key"]
        or item["generation"] != value["expected_revision"]
        or item["reference_runs"] != references):
      raise Conflict(_ERROR)
    # 未选共享运行也必须属于已关联协议；缺关联不能假称引用已知且完整。
    if any("owner_link" not in state["reservations"][run] for run in references):
      raise Conflict(_ERROR)
  for planned in plan["runs"]:
    run = planned["run_id"]
    record, entry = value["records"][run], state["reservations"][run]
    link = entry["owner_link"]
    evidence = {key: child for key, child in link.items() if key != "record_digest"}
    if (record["agent"] != "omp" or record["backend"] != "managed"
        or entry["resources"] != planned["resource_ids"]
        or entry["owner_ref"]["binding"] != {**record["machine_ref"], "profile": record["profile"]}
        or link["record_digest"] != planned["observation"]["record_digest"]
        or record["coordination_domain"] != resource_owners._coordination(state, entry, evidence)
        or record["deployed_identity"]["runtime"] != resource_owners._runtime_digest(state, entry)
        or record["native_home_ref"]["path"] != link["native_home"]["path"]):
      raise Conflict(_ERROR)
    for kind, name in (("instance", "instance"), ("native-home", "native_home")):
      selected = [state["resources"][rid] for rid in entry["resources"]
        if state["resources"][rid]["key"]["kind"] == kind]
      if len(selected) != 1 or selected[0]["key"] != link[name]["key"] or selected[0]["path"] != link[name]["path"]:
        raise Conflict(_ERROR)


def _read(state, tree, batch_id):
  raw = tree.read(_name(batch_id), max_bytes=maintenance._MAX_BYTES)
  intent = state["intents"].get(batch_id)
  if raw is None and intent is None:
    return None
  if raw is None or raw[1] != 0o600 or intent is None:
    raise Conflict(_ERROR)
  if intent.get("acceptance_digest") != hashlib.sha256(raw[0]).hexdigest():
    raise Conflict(_ERROR)
  value = maintenance.decode_stop_acceptance(raw[0])
  batch, plan = value["batch"], value["batch"]["plan"]
  if (batch["batch_id"] != batch_id or value["domain_id"] != state["domain_id"]
      or value["domain_physical"] != state["physical"]
      or intent["generation"] != value["expected_revision"] + 1
      or intent["generation"] > state["revision"]
      or intent["operation"] != plan["operation"] or intent["selected_runs"] != plan["selected_runs"]
      or intent["resources"] != sorted(item["resource_id"] for item in plan["resources"])):
    raise Conflict(_ERROR)
  if "progress" in intent:
    progress = maintenance.decode_batch(maintenance.encode_batch(intent["progress"]))
    if any(progress[name] != batch[name] for name in
        ("schema_version", "kind", "protocol", "batch_id", "plan", "operation", "accepted_runs")):
      raise Conflict(_ERROR)
  return {"acceptance": value, "intent": deepcopy(intent)}


def _check_acceptance(domain, state, value):
  if state["revision"] != value["expected_revision"] or value["batch"]["batch_id"] in state["intents"]:
    raise Conflict(_ERROR)
  _snapshot_matches(domain, state, value)
  resources = sorted(item["resource_id"] for item in value["batch"]["plan"]["resources"])
  domain._unfenced(state, set(resources))
  return resources


def _publish_snapshot(domain, state, value, raw, resources):
  """调用方在同一事务中完成所需核验；本函数不取锁或授予控制权。"""
  batch = value["batch"]
  batch_id = batch["batch_id"]
  with Tree(domain.root) as tree:
    if tree.fd is None or _physical(tree.fd) != state["physical"]:
      raise Conflict(_ERROR)
    tree.write_new(_name(batch_id), raw)
    # write_new 已同步文件及目录；读回同时重核命名根，不能只信旧 fd。
    published = tree.read(_name(batch_id), max_bytes=maintenance._MAX_BYTES)
    if published is None or published[0] != raw or published[1] != 0o600:
      raise Conflict(_ERROR)
  state["intents"][batch_id] = {"batch_id": batch_id, "generation": value["expected_revision"] + 1,
    "operation": batch["operation"], "resources": resources,
    "selected_runs": list(batch["accepted_runs"]), "phase": "active",
    "acceptance_digest": hashlib.sha256(raw).hexdigest(), "progress": deepcopy(batch)}


def accept_stop_snapshot(domain, value):
  """内部元数据事务，返回 None；不恢复句柄、批准、现场证明或控制权。"""
  with _boundary():
    raw = maintenance.encode_stop_acceptance(value)
    value = maintenance.decode_stop_acceptance(raw)
    with domain._transaction(write=True) as state:
      resources = _check_acceptance(domain, state, value)
      _publish_snapshot(domain, state, value, raw, resources)


def accept_stop_snapshot_live(domain, value, *, leases):
  """内部现场 owner/资源事务；借用已持 SH，不提供进程控制或维护许可。"""
  _accept_stop_snapshot_live(domain, value, leases=leases)


def _accept_stop_snapshot_live(domain, value, *, leases, before_publish=None):
  """先现场核验，后短内存消费，再持久化；不在锁内交互确认。"""
  from .maintenance_deployment import check_stop_deployment
  from .maintenance_live import _KEYS, hold_stop_owners
  with _boundary():
    raw = maintenance.encode_stop_acceptance(value)
    value = maintenance.decode_stop_acceptance(raw)
    if type(leases) is not dict or set(leases) != set(value["batch"]["accepted_runs"]):
      raise Conflict(_ERROR)
    # 受管文件的读取在短协调锁外进行；已有实例/状态 SH 防止合作部署穿过检查。
    # 不因后续 owner 检查失败而回落，也不从恢复清单中的路径打开工作区。
    for run in sorted(leases):
      item = leases[run]
      if type(item) is not dict or set(item) != _KEYS:
        raise Conflict(_ERROR)
      check_stop_deployment(item["workspace"], value["records"][run],
        instance_fd=item["instance_fd"], state_fd=item["state_fd"])
    # 物理/状态/包 SH 已由可信调用者按原顺序持有。owner NB 在域锁内取得，
    # 外层 stack 保证提交协调表（含 fsync）退出后才释放；不反向等待物理锁。
    with ExitStack() as owners, domain._transaction(write=True) as state:
      resources = _check_acceptance(domain, state, value)
      hold_stop_owners(domain, state, acceptance=value, leases=leases, stack=owners)
      if before_publish is not None:
        before_publish(value)
      _publish_snapshot(domain, state, value, raw, resources)


def accept_reviewed_stop_snapshot_live(domain, value, *, leases, review):
  """在相同 live 接受边界内一次消费明确停止审阅；不提供控制许可。"""
  from .stop_review import consume_stop_review
  def consume(current):
    # 审阅回调已在获取锁之前完成；这里只检查并消耗内存对象。
    # 从这里开始的任一落盘/提交/响应失败都不能恢复本次审阅。
    consume_stop_review(review, plan=current["batch"]["plan"], batch_id=current["batch"]["batch_id"])
  _accept_stop_snapshot_live(domain, value, leases=leases, before_publish=consume)


def read_stop_snapshot(domain, batch_id):
  """只读历史清单及当前意图；缺一边是待核验，不重建、不清除或执行。"""
  with _boundary(), domain._transaction() as state, Tree(domain.root) as tree:
    if tree.fd is None or _physical(tree.fd) != state["physical"]:
      raise Conflict(_ERROR)
    return _read(state, tree, batch_id)


def check_stop_snapshot_for_dispatch(domain, state, intent):
  """调用方已持短协调锁；只核验落盘清单，不授予信号或维护许可。"""
  with _boundary(), Tree(domain.root) as tree:
    if tree.fd is None or _physical(tree.fd) != state["physical"]:
      raise Conflict(_ERROR)
    raw = tree.read(_name(intent["batch_id"]), max_bytes=maintenance._MAX_BYTES)
    # 兼容没有清单的早期内部 intent 原语；它们仍不是可执行 Batch。
    if raw is None and "acceptance_digest" not in intent:
      return
    saved = _read(state, tree, intent["batch_id"])
    _snapshot_matches(domain, state, saved["acceptance"])
