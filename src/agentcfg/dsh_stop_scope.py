"""DSH 停止前的当前部署与物理包含关系；不授予停止或维护权限。

调用方维持实例/状态 SH；目录 fd 只固定包含关系，不是额外租约。
不证明运行包完整性、完整运行集合、外部 writer、批准、历史实际追加参数或退出/释放。
"""
from copy import deepcopy
from contextlib import contextmanager
import fcntl
import os
import json
import re
import time

from . import deployment, run_owners, runtime, run_stop_fence, run_stop_snapshot, stop_requests
from .omp_lifecycle import _same_file
from .resource_keys import resource_key
from .storage import Conflict, Tree


_ERROR = "DSH 当前部署或受管目录包含关系不能确认；保留现有保护"


def _marker(tree, workspace):
  raw = tree.read(".agentcfg-instance.json")
  expected = {"schema_version": 1, "state_root": str(workspace.state_root), "binding": workspace.binding}
  if raw is None or raw[1] != 0o600 or raw[0] != deployment.json_bytes(expected):
    raise ValueError()
  return raw


def _directory(path, fd):
  with Tree(path) as named:
    if named.fd is None:
      raise ValueError()
    before, current = os.fstat(fd), os.fstat(named.fd)
    if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
      raise ValueError()
    return {"device": before.st_dev, "inode": before.st_ino}


def _environment(contract, workspace):
  rows = contract["environment"]
  if type(rows) is not list:
    raise ValueError()
  environment = {}
  for row in rows:
    if (type(row) is not dict or set(row) not in ({"name", "required", "literal"}, {"name", "required", "secret_ref"})
        or type(row["name"]) is not str or not row["name"] or "\0" in row["name"]
        or type(row["required"]) is not bool or row["name"] in environment):
      raise ValueError()
    value = row.get("literal", row.get("secret_ref"))
    if type(value) is not str or "\0" in value:
      raise ValueError()
    environment[row["name"]] = row
  for name, path in (("DSH_HOME", workspace.instance / "dsh-home"), ("HOME", workspace.instance / "user-home")):
    if environment[name].get("literal") != str(path):
      raise ValueError()
  route = environment.get("AGENTCFG_DSH_EXECUTION")
  if route is not None and route.get("literal") != "local":
    raise ValueError()


def inspect_deployment(workspace, record, *, instance_fd, state_fd) -> dict:
  """只打开可信 workspace 路径，不从 record/保存的任意路径选择资源。"""
  if workspace.agent in ("pi", "omp"):
    from .tool_stop_layout import inspect_deployment as inspect_tool
    return inspect_tool(workspace, record, instance_fd=instance_fd, state_fd=state_fd)
  try:
    # 先核实借入编号仍开放，避免后续本函数打开目录时复用已关闭的编号。
    for fd in (instance_fd, state_fd):
      if type(fd) is not int or fd < 0:
        raise ValueError()
      os.fstat(fd)
    if (workspace.agent != "dsh" or workspace.profile != workspace.binding["profile"]
        or type(record) is not dict or type(record.get("schema_version")) is not int
        or record["schema_version"] != 2 or record["agent"] != "dsh" or record["backend"] != "managed"
        or record["lifecycle_state"] != "active" or record["coordination_domain"] is not None):
      raise ValueError()
    registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
    registry._validate_record(record["run_id"] + ".json", record)
    with Tree(workspace.instance) as target, Tree(workspace.state_root) as state:
      instance = resource_key("instance", workspace.instance, lease_fd=instance_fd)
      _same_file(state, "instance.lock", state_fd)
      marker = _marker(target, workspace)
      if state.read("pending.json") is not None:
        raise ValueError()
      saved_raw = state.read("deployment.json")
      saved = deployment.read_state(state)
      current = saved["current"]
      if (current is None or current["binding"] != workspace.binding or saved["owner"]["binding"] != workspace.binding
          or current["generation"] != record["deployed_identity"]["deployment"]):
        raise ValueError()
      contract = current["launch"]
      identity = contract["lock_identity"]
      if (type(identity) is not str or re.fullmatch(r"[0-9a-f]{64}", identity) is None
          or contract.get("runtime_identity", identity) != identity or record["deployed_identity"]["runtime"] != identity):
        raise ValueError()
      root = workspace.instance / "runtimes" / identity
      native = workspace.instance / "dsh-home"
      user = workspace.instance / "user-home"
      if (contract["argv"] != ["node", str(workspace.instance / "launch.mjs"), str(root),
          str(native / "agentcfg.patch.yml"), "--profile", "agentcfg"]
          or record["native_home_ref"]["path"] != str(native)):
        raise ValueError()
      _environment(contract, workspace)
      with Tree(native) as home_tree, Tree(root) as package_tree, Tree(user) as user_tree:
        native_key = resource_key("native-home", native, lease_fd=home_tree.fd)
        runtime_key = resource_key("runtime", root, lease_fd=package_tree.fd)
        user_home = _directory(user, user_tree.fd)
        runtime.check_deployed_resources(current, target)
        # 基础 argv 依赖保存的 launcher 内容；仅本接缝额外验证，不改变普通运行 guards。
        launchers = [item for item in current["items"].values() if item["path"] == "launch.mjs"]
        if (len(launchers) != 1 or launchers[0]["selector"] is not None
            or launchers[0]["ownership"] != "file" or launchers[0]["baseline"].get("present") is not True
            or not deployment.same(deployment.projection(target, launchers[0]), launchers[0]["baseline"])):
          raise ValueError()
        if (resource_key("instance", workspace.instance, lease_fd=instance_fd) != instance
            or resource_key("native-home", native, lease_fd=home_tree.fd) != native_key
            or resource_key("runtime", root, lease_fd=package_tree.fd) != runtime_key
            or _directory(user, user_tree.fd) != user_home or _marker(target, workspace) != marker
            or state.read("deployment.json") != saved_raw or state.read("pending.json") is not None):
          raise ValueError()
        _same_file(state, "instance.lock", state_fd)
        return {"instance": instance.as_dict(), "native_home": native_key.as_dict(), "runtime": runtime_key.as_dict(),
          "user_home": user_home, "deployed_identity": deepcopy(record["deployed_identity"])}
  except Exception:
    raise Conflict(_ERROR) from None


def save_reviewed_snapshot(workspace, *, instance_fd, state_fd, expected_records, expected_layout,
    plan, batch_id, review, deadline_ns=None):
  """保存完整已审阅计划及阻断事实；不提供 host/覆盖证明或控制许可。

  审阅已在锁外完成。两 SH 和完整 owner CAS 内，先消费单次内存审阅，再发布
  快照和 fence；失败不恢复审阅，不重放文件。可选期限只用于首次写入前等待 owner 短锁。
  """
  from . import maintenance, stop_review
  try:
    for fd in (instance_fd, state_fd):
      if type(fd) is not int or fd < 0:
        raise ValueError()
      os.fstat(fd)
    frozen = maintenance.decode_stop_plan(maintenance.encode_stop_plan(plan))
    if (frozen["schema_version"] != 2 or frozen["readiness"] != "ready"
        or type(review) is not stop_review.StopReview):
      raise ValueError()
    _save_snapshot(workspace, instance_fd=instance_fd, state_fd=state_fd,
      expected_records=expected_records, selected_runs=frozen["selected_runs"],
      expected_layout=expected_layout, batch_id=batch_id, plan_id=frozen["plan_id"],
      plan=frozen, review=review, **({} if deadline_ns is None else {"deadline_ns": deadline_ns}))
  except Exception:
    raise Conflict(_ERROR) from None


def save_manual_snapshot(workspace, *, instance_fd, state_fd, expected_records, selected_runs,
    expected_layout, batch_id, plan_id, before_publish=None):
  """保存人工参考及阻断；调用方持两 SH，不授予停止或维护许可。

  before_publish 仅限 owner 短锁内可信内存消费，不得交互或重新取锁。
  未选历史记录只参与全集 CAS，不证明完整合作覆盖或当前会话确认。
  """
  return _save_snapshot(workspace, instance_fd=instance_fd, state_fd=state_fd,
    expected_records=expected_records, selected_runs=selected_runs, expected_layout=expected_layout,
    batch_id=batch_id, plan_id=plan_id, before_publish=before_publish)


def _save_snapshot(workspace, *, instance_fd, state_fd, expected_records, selected_runs,
    expected_layout, batch_id, plan_id, before_publish=None, plan=None, review=None, deadline_ns=None):
  try:
    # 任何 schema/Tree 打开前先拒绝关闭的借入 fd，避免整数被新文件复用。
    for fd in (instance_fd, state_fd):
      if type(fd) is not int or fd < 0:
        raise ValueError()
      os.fstat(fd)
    if (type(expected_records) is not dict or not expected_records or type(selected_runs) is not list
        or not selected_runs or type(expected_layout) is not dict
        or (before_publish is not None and not callable(before_publish))):
      raise ValueError()
    frozen = []
    for value in (expected_records, selected_runs, expected_layout):
      run_stop_snapshot._shape(value)
      frozen.append(json.loads(run_stop_snapshot._encoded(value).decode("utf-8"),
        object_pairs_hook=run_owners._pairs, parse_float=run_owners._invalid_constant,
        parse_constant=run_owners._invalid_constant))
    records, selected, layout = frozen
    selected = run_stop_snapshot._selection(selected)
    validator = run_stop_snapshot._registry(workspace.binding)
    if not set(selected) <= set(records):
      raise ValueError()
    run_stop_snapshot._records(validator, records, selected=set(selected))
    expected = run_owners._encode(layout)
    if plan is not None:
      # 计划中的物理资源必须就是经部署核实的三个目录，不能只比较调用方摘要。
      keys = {layout[name]["key_id"][:32]: layout[name] for name in ("instance", "native_home", "runtime")}
      if {item["resource_id"]: item["key"] for item in plan["resources"]} != keys:
        raise ValueError()
    def check_layout():
      for run in selected:
        current = inspect_deployment(workspace, records[run], instance_fd=instance_fd, state_fd=state_fd)
        if run_owners._encode(current) != expected:
          raise ValueError()
    check_layout()
    registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
    with Tree(registry.root) as tree:
      if tree.fd is None:
        raise ValueError()
      info = os.fstat(tree.fd)
      physical = {"device": info.st_dev, "inode": info.st_ino}
    if plan is None:
      snapshot = run_stop_snapshot.build_snapshot(binding=registry.binding, registry_physical=physical,
        batch_id=batch_id, plan_id=plan_id, expected_records=records, selected_runs=selected)
    else:
      snapshot = run_stop_snapshot.build_plan_snapshot(binding=registry.binding, registry_physical=physical,
        batch_id=batch_id, expected_records=records, plan=plan)
    def before():
      check_layout()
      if before_publish is not None:
        before_publish()
      if plan is not None:
        from .stop_review import consume_stop_review
        consume_stop_review(review, plan=plan, batch_id=batch_id)
    run_stop_fence.install(registry, batch_id=batch_id, plan_id=plan_id, expected_records=records,
      recovery_snapshot=snapshot, before_publish=before,
      **({} if deadline_ns is None else {"deadline_ns": deadline_ns}))
  except Exception:
    raise Conflict(_ERROR) from None


@contextmanager
def _request_owner(registry, deadline_ns):
  """仅等待本请求的短元数据锁；没有续期、重发或持短锁睡眠。"""
  last = None
  def remaining():
    nonlocal last
    now = time.monotonic_ns()
    if (type(now) is not int or now < 0 or last is not None and now < last
        or not 0 < deadline_ns - now <= 300000000000):
      raise ValueError()
    last = now
    return (deadline_ns - now) / 1000000000
  with Tree(registry.root) as owner:
    if owner.fd is None:
      raise ValueError()
    while True:
      left = remaining()
      try:
        fcntl.flock(owner.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
      except BlockingIOError:
        time.sleep(min(0.01, left))
    try:
      remaining()
      registry._verify_root(owner)
      yield owner
      registry._verify_root(owner)
      remaining()
    finally:
      fcntl.flock(owner.fd, fcntl.LOCK_UN)


def inspect_stop_request(workspace, request, *, instance_fd, state_fd, expected_layout,
    require_reviewed_stop=False):
  """只读当前请求与人工快照关联，返回历史记录副本，不是批准或许可。

  调用方维持原两把 SH。当前 manager、所选目标记录及部署必须仍匹配；
  其它所选运行可以已经退出，本函数不证明完整资源覆盖、来源或当前 host。
  原句柄、显式批准、endpoint 和期限仍须在实际派发前独立核验。
  """
  try:
    for fd in (instance_fd, state_fd):
      if type(fd) is not int or fd < 0:
        raise ValueError()
      os.fstat(fd)
    request = stop_requests.decode_stop_request(stop_requests.encode_stop_request(request))
    run_stop_snapshot._shape(expected_layout)
    layout = run_stop_snapshot._encoded(expected_layout)
    registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
    guard = _request_owner(registry, request["deadline_ns"]) if require_reviewed_stop else registry._locked(nonblocking=True)
    with guard as owner, Tree(registry.root.parent) as parent:
      if owner is None:
        raise ValueError()
      from .dsh_stop_completion import close_name
      run_stop_fence._assert_missing(parent, close_name(registry, request["batch_id"]))
      # 固定可信目录内的三个名称；同内容替换也不能延续本次观察。
      files = ((parent, run_stop_fence._name(registry)),
        (parent, run_stop_fence._snapshot_name(registry, request["batch_id"])),
        (owner, request["run_id"] + ".json"))
      def file_identities():
        result = []
        for tree, name in files:
          with tree.parent(name) as (fd, leaf):
            info = os.stat(leaf, dir_fd=fd, follow_symlinks=False)
            result.append((info.st_dev, info.st_ino))
        return result
      identities = file_identities()
      fence = run_stop_fence._read_locked(registry, owner, parent)
      if (fence is None or fence["schema_version"] != 2
          or fence["batch_id"] != request["batch_id"] or fence["plan_id"] != request["plan_id"]):
        raise ValueError()
      snapshot = run_stop_fence._check_snapshot_link(parent, registry, owner, fence)
      if require_reviewed_stop and (snapshot["schema_version"] != 2
          or snapshot["plan"]["operation"] != "stop_only"
          or snapshot["plan"]["readiness"] != "ready"
          or snapshot["plan"]["control_capability"] != "supported"):
        raise ValueError()
      if request["run_id"] not in snapshot["selected_runs"]:
        raise ValueError()
      record = snapshot["records"][request["run_id"]]
      host = record["host_identity"]
      if (host is None or host["source"] != "linux-spawn-pidfd"
          or host["relationship"] != "reported-by-current-run"
          or host["identity"] != request["host_identity"]
          or record["manager_identity"] != request["manager_identity"]
          or host["manager_identity"] != request["manager_identity"]
          or run_owners.current_process_identity() != request["manager_identity"]):
        raise ValueError()
      expected = run_owners._encode(record)
      def check_target():
        current, _ = registry._records(owner)
        if run_owners._encode(current.get(request["run_id"])) != expected:
          raise ValueError()
      check_target()
      current_layout = inspect_deployment(workspace, record, instance_fd=instance_fd, state_fd=state_fd)
      if run_stop_snapshot._encoded(current_layout) != layout:
        raise ValueError()
      check_target()
      if (run_owners._encode(run_stop_fence._read_locked(registry, owner, parent)) != run_owners._encode(fence)
          or file_identities() != identities
          or run_owners.current_process_identity() != request["manager_identity"]):
        raise ValueError()
      run_stop_fence._assert_missing(parent, close_name(registry, request["batch_id"]))
      registry._verify_root(owner)
      return deepcopy(record)
  except Exception:
    raise Conflict("DSH 停止请求与原快照的关联不能确认；保留保护且不派发") from None
