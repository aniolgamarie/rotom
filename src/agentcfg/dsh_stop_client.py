"""精确 DSH 停止客户端；先保存恢复快照，再投递一次请求，分别观察退出。"""
from contextlib import ExitStack
from copy import deepcopy
import time
import uuid

from . import dsh_stop, dsh_stop_completion, dsh_stop_control, dsh_stop_scope
from . import lifecycle, maintenance, run_owners, run_stop_fence, stop_review, stop_locks
from .control_deadline import ControlDeadline
from .manager_exit import ManagerExit
from .stop_inbox import StopInbox
from .storage import Conflict, Tree, instance_lock


_ERROR = "停止接受或当前状态不能确认；保留已保存的事实，不自动重发"


def _registry(workspace):
  return run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)


def workspace_for_batch(local, *, batch_id, profile=None):
  """按显式机器范围查找原批次，不从用户输入拼接外部目录。"""
  from .local import available_profiles
  from .process import DependencyError
  from .workspace import load_instance_workspaces
  try:
    run_owners._run_id(batch_id)
  except Exception:
    raise ValueError("batch 必须为完整的 32 位小写十六进制 ID") from None
  profiles = dict(available_profiles())
  if profile is not None and profile not in profiles:
    raise ValueError("未知 profile")
  names = [profile] if profile is not None else sorted(name for name, agent in profiles.items() if agent in ("dsh", "pi", "omp"))
  if any(profiles[name] not in ("dsh", "pi", "omp") for name in names):
    raise DependencyError("当前批次查询仅支持 DSH 普通停止")
  matches = []
  for workspace in load_instance_workspaces(local, names):
    with Tree(workspace.state_root) as state:
      if state.fd is None:
        continue
    snapshot = run_stop_fence.read_snapshot(_registry(workspace), batch_id)
    if snapshot is not None:
      if snapshot["schema_version"] != 2 or snapshot["plan"]["operation"] != "stop_only":
        raise DependencyError("此批次尚不支持当前操作")
      matches.append(workspace)
  if len(matches) != 1:
    raise Conflict("无法唯一确认所选 DSH 停止批次")
  return matches[0]


def publish_request(workspace, request, *, expected_record):
  """与取消共用 owner 锁；本次失败即交回，不重投、不撤销已保存请求。"""
  registry = _registry(workspace)
  try:
    with stop_locks.locked(registry, request["deadline_ns"]) as owner, Tree(workspace.state_root) as parent:
      run_stop_fence._assert_missing(parent, dsh_stop_completion.close_name(registry, request["batch_id"]))
      fence = run_stop_fence._read_locked(registry, owner, parent)
      if fence is None or fence["batch_id"] != request["batch_id"] or fence["plan_id"] != request["plan_id"]:
        raise ValueError()
      snapshot = dsh_stop_completion._snapshot(registry, owner, parent, fence)
      run = request["run_id"]
      records, _ = registry._records(owner)
      if (run not in snapshot["records"] or records.get(run) != expected_record
          or snapshot["records"][run] != expected_record
          or not dsh_stop_control.available_locked(workspace, expected_record, deadline_ns=request["deadline_ns"])):
        raise ValueError()
      if not 0 < request["deadline_ns"] - time.monotonic_ns() <= 300000000000:
        raise ValueError()
      inbox = StopInbox(workspace.state_root / "stop-inboxes" / run, workspace.binding)
      registry._verify_root(owner)
      endpoint = dsh_stop_control.channel_state(workspace, expected_record, deadline_ns=request["deadline_ns"])["endpoint"]
      inbox.submit(request, expected=endpoint, wait_for_lock=True)
      registry._verify_root(owner)
  except Exception:
    raise Conflict(_ERROR) from None


def status_stop(workspace, *, batch_id):
  """只读原快照和当前事实；看不到进程不等于它已退出。"""
  registry = _registry(workspace)
  try:
    with registry._locked(nonblocking=True) as owner, Tree(workspace.state_root) as parent:
      saved = run_stop_fence._read_snapshot(parent, registry, batch_id, owner)
      if saved is None:
        raise ValueError()
      snapshot = saved[0]
      if snapshot["schema_version"] != 2 or snapshot["plan"]["operation"] != "stop_only":
        raise ValueError()
      fence = run_stop_fence._read_locked(registry, owner, parent)
      close = dsh_stop_completion._read_close(registry, owner, parent, batch_id)
      records, _ = registry._records(owner)
      rows = []
      for run in snapshot["selected_runs"]:
        historical, current = snapshot["records"][run], records.get(run)
        state = "unknown"
        if current is not None and dsh_stop_completion._unchanged(historical, current):
          state = current["lifecycle_state"]
        channel = dsh_stop_control.channel_state(workspace, historical)
        requests = channel["requests"]
        if len(requests) > 1 or any(item["batch_id"] != batch_id or item["plan_id"] != snapshot["plan_id"] for item in requests):
          raise ValueError()
        dispatch = channel["dispatch"]
        if dispatch is not None and (dispatch["request"] not in requests):
          raise ValueError()
        target = dsh_stop._target(historical)
        if target["session_status"] in ("confirmed", "final", "historical"):
          target["session_status"] = "historical"
        rows.append({"run_id": run, "lifecycle_state": state,
          "request": "posted" if requests else "not_posted",
          "dispatch": dispatch["dispatch"] if dispatch else "not_observed",
          "target": target})
      protected = fence is not None and fence["batch_id"] == batch_id
      if protected and fence["plan_id"] != snapshot["plan_id"]:
        raise ValueError()
      state = "pending"
      if close is not None and not protected:
        state = close["reason"]
      elif not protected:
        state = "snapshot_only"
      registry._verify_root(owner)
      return {"batch_id": batch_id, "plan_id": snapshot["plan_id"], "scope": deepcopy(snapshot["plan"]["scope"]),
        "status": state, "protected": protected, "targets": rows,
        "close_reason": close["reason"] if close is not None else None,
        "continue_status": "not_sent", "resource_coverage": "unknown"}
  except Exception:
    raise Conflict(_ERROR) from None


def execute_stop(workspace, *, expected_plan, approve, wait_seconds=30, batch_id=None):
  """明确审阅在锁外；每项使用同一截止点，失败保留 batch ID 和原始事实。"""
  if type(wait_seconds) is not int or not 1 <= wait_seconds <= 300:
    raise ValueError("停止等待时间须为 1..300 秒")
  if batch_id is not None:
    run_owners._run_id(batch_id)
  expected = maintenance.decode_stop_plan(maintenance.encode_stop_plan(expected_plan))
  observed, records, layout = dsh_stop.capture_stop(workspace, selected_runs=expected["selected_runs"])
  plan = observed["plan"]
  if plan != expected or plan["operation"] != "stop_only" or plan["readiness"] != "ready":
    raise Conflict(_ERROR)
  batch_id = uuid.uuid4().hex if batch_id is None else batch_id
  review = stop_review.review_stop_plan(plan, scope=plan["scope"], operation="stop_only",
    selected_runs=plan["selected_runs"], plan_id=plan["plan_id"], batch_id=batch_id, approve=approve)
  with ExitStack() as stack:
    # 捕获在任何持久化之前；不从 None、PID 消失或新 PID 推断原 manager 退出。
    exits = {run: stack.enter_context(ManagerExit(records[run]["manager_identity"])) for run in plan["selected_runs"]}
    deadline = ControlDeadline(wait_seconds)
    result = {"batch_id": batch_id, "plan_id": plan["plan_id"], "scope": deepcopy(plan["scope"]),
      "status": "pending", "continue_status": "not_sent", "resource_coverage": "unknown"}
    try:
      with lifecycle.observation_guard(workspace) as instance_fd, Tree(workspace.state_root) as state:
        with instance_lock(state, shared=True, create=False) as state_fd:
          if deadline.expired():
            raise ValueError()
          dsh_stop_scope.save_reviewed_snapshot(workspace, instance_fd=instance_fd, state_fd=state_fd,
            expected_records=records, expected_layout=layout, batch_id=batch_id, plan=plan, review=review)
          for run in plan["selected_runs"]:
            if deadline.expired():
              raise ValueError()
            record = records[run]
            request = {"schema_version": 1, "kind": "stop-request", "action": "graceful-stop",
              "request_id": uuid.uuid4().hex, "batch_id": batch_id, "plan_id": plan["plan_id"], "run_id": run,
              "manager_identity": deepcopy(record["manager_identity"]),
              "host_identity": deepcopy(record["host_identity"]["identity"]), "deadline_ns": deadline.deadline_ns}
            publish_request(workspace, request, expected_record=record)
      while not deadline.expired():
        # 只读竞争可等到原截止点；不会重新接受、投稿或派发。
        try:
          current = status_stop(workspace, batch_id=batch_id)
        except Conflict:
          current = None
        if (current is not None and all(row["lifecycle_state"] == "idle_confirmed" for row in current["targets"])
            and all(observer.exited() for observer in exits.values())):
          # 收尾写入只尝试一次；响应未知留给后续明确请求核对。
          dsh_stop_completion.close_stop(workspace, batch_id=batch_id, plan_id=plan["plan_id"], reason="stopped")
          return status_stop(workspace, batch_id=batch_id)
        time.sleep(min(0.05, deadline.remaining()))
    except Exception:
      # 已接受、局部投递、写后失败均不回滚；显式查询/取消必须核对落盘事实。
      pass
    try:
      return status_stop(workspace, batch_id=batch_id)
    except Conflict:
      return result | {"status": "unknown"}
