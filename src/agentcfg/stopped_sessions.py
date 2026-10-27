"""已保存停止记录的只读目录；展示候选，不授予恢复或清理许可。"""
from copy import deepcopy
from dataclasses import asdict
import os
from pathlib import Path
import re
import unicodedata

from . import run_owners
from .sessions import SessionError
from .storage import Conflict, Tree


_ID = re.compile(r"[0-9a-f]{32}")
_SNAPSHOT = re.compile(r"run-owners\.stop-snapshot-([0-9a-f]{32})\.json")
_LIMIT = 4096


def validate_title(value):
  """显式备注拒绝控制字符和过长输入，不能静默改写用户标题。"""
  if (type(value) is not str or not value.strip() or value != value.strip() or len(value) > 160
      or any(unicodedata.category(char).startswith("C") or char in "\u2028\u2029" for char in value)
      or len(value.encode("utf-8")) > 640):
    raise ValueError("标题需为 1–160 字符的单行文字，不能包含控制字符或首尾空白")
  return value


def display_title(value):
  """原生标题是不可信显示文字；不执行转义序列，也不作为会话身份。"""
  if type(value) is not str:
    return None
  result = "".join("?" if unicodedata.category(char).startswith("C") or char in "\u2028\u2029" else char
    for char in value).strip()[:160].rstrip()
  return result or None


def _issue(workspace, batch_id, reason):
  return {"profile": workspace.profile, "batch_id": batch_id, "reason": reason}


def _discover(workspace, issues):
  workflows, snapshots = set(), set()
  try:
    with Tree(workspace.state_root / "maintenance-workflows") as tree:
      if tree.fd is not None:
        with os.scandir(tree.fd) as entries:
          for index, entry in enumerate(entries):
            if index >= _LIMIT:
              raise Conflict("停止记录过多")
            if _ID.fullmatch(entry.name) is None:
              issues.append(_issue(workspace, None, "invalid-workflow-entry"))
              continue
            # 即使清单损坏也保留 batch ID，防止退回 stop-only 旁路恢复。
            workflows.add(entry.name)
    with Tree(workspace.state_root) as tree:
      if tree.fd is not None:
        with os.scandir(tree.fd) as entries:
          for index, entry in enumerate(entries):
            if index >= _LIMIT:
              raise Conflict("停止记录过多")
            match = _SNAPSHOT.fullmatch(entry.name)
            if match:
              snapshots.add(match[1])
            elif entry.name.startswith("run-owners.stop-snapshot-"):
              issues.append(_issue(workspace, None, "invalid-stop-entry"))
  except (Conflict, OSError):
    # 根目录不可读时不能证明缺失 workflow；整范围不提供 stop-only 候选。
    issues.append(_issue(workspace, None, "history-unavailable"))
    return set(), set()
  return workflows, snapshots


def _row(workspace, batch_id, run, ref, cwd, *, source, title=None, title_source="unavailable",
    observed_at_ns=None, stop_status="unknown", restore_status="stop-unconfirmed"):
  scope = {**workspace.binding, "agent": workspace.agent}
  prefix = ["rotom", "agent", "--local", scope["local"], "--profile", scope["profile"], "maintenance"]
  ready = restore_status == "available"
  return {"agent": workspace.agent, "profile": workspace.profile, "scope": scope,
    "batch_id": batch_id, "run_id": run, "source": source, "session_ref": deepcopy(ref),
    "session_id": ref["native_ref"] if ref is not None else None, "cwd": cwd,
    "title": title, "title_source": title_source, "observed_at_ns": observed_at_ns,
    "stop_status": stop_status, "restore_status": restore_status, "restorable": ready,
    "next_commands": {"status": [*prefix, "status", "--batch", batch_id],
      "restore": ["rotom", "resume", workspace.agent, "--local", scope["local"], "--profile", scope["profile"],
        "--stopped", "--batch", batch_id, "--run", run, "--here"] if ready else None,
      "manual_restore": ["rotom", "resume", workspace.agent, "--local", scope["local"], "--profile", scope["profile"],
        "--session", ref["native_ref"], "--here"] if restore_status == "manual-review" else None}}


def _workflow_rows(workspace, batch_id):
  from . import tool_maintenance as flow
  value = flow.status(workspace, batch_id)
  rows = []
  for run, target in value["targets"].items():
    stage = value["restores"][run]
    status = "available"
    if value["stop_status"] != "stopped":
      status = "stop-unconfirmed"
    elif value["cancelled"]:
      status = "cancelled"
    elif stage is not None:
      status = "unknown" if stage["action"] == "restore-intent" else "dispatched"
    elif value["setup"] is not None and value["setup"]["action"] == "setup-intent":
      status = "unknown"
    elif value["status"] != "updated":
      status = "update-required"
    elif value["current_deployment_match"] is not True:
      status = "deployment-changed"
    label = value.get("display", {}).get(run, {"title": None, "source": "unavailable"})
    rows.append(_row(workspace, batch_id, run, target["ref"], target["cwd"], source="workflow",
      title=label["title"], title_source=label["source"], observed_at_ns=target["observed_at_ns"],
      stop_status=value["stop_status"], restore_status=status))
  return rows


def _stop_rows(workspace, batch_id):
  from . import dsh_stop_client, run_stop_fence
  from .dsh_sessions import scope_key
  from .sessions import from_run_records
  registry = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding)
  snapshot = run_stop_fence.read_snapshot(registry, batch_id)
  if snapshot is None or snapshot["schema_version"] != 2:
    raise Conflict("停止快照不可确认")
  value = dsh_stop_client.status_stop(workspace, batch_id=batch_id)
  if value["scope"] != {**workspace.binding, "agent": workspace.agent}:
    raise Conflict("停止归属不可确认")
  known = {target.run_id: target for target in from_run_records(snapshot["records"],
    scope=scope_key(workspace.binding), machine_ref={k: workspace.binding[k] for k in ("machine", "local")},
    profile=workspace.profile)}
  if workspace.agent == "pi":
    from .pi_session_observation import from_records
    known.update({target.run_id: target for target in from_records(workspace, snapshot["records"])})
  rows = []
  for target in value["targets"]:
    run = target["run_id"]
    session = known.get(run)
    # 旧快照不标记 workflow 来源；不能把缺失日志推断成独立 stop 并绕过取消/恢复意图。
    # 保留精确人工参考命令，只有完整 workflow 提供自动选择交接。
    status = "manual-review"
    if value["status"] != "stopped" or value["protected"] or target["lifecycle_state"] != "idle_confirmed":
      status = "stop-unconfirmed"
    elif session is None or session.cwd is None or session.confirmation == "unknown" or session.cwd_status == "unknown":
      status = "session-unknown"
    rows.append(_row(workspace, batch_id, run, asdict(session.ref) if session else None,
      session.cwd if session else None, source="stop", observed_at_ns=session.observed_at_ns if session else None,
      stop_status=value["status"], restore_status=status))
  return rows


def history(workspaces, *, batch_id=None, run_id=None):
  """只读已选机器/profile 的自有记录，不扫描真实会话正文或系统进程列表。"""
  if any(value is not None and (type(value) is not str or _ID.fullmatch(value) is None)
      for value in (batch_id, run_id)):
    raise ValueError("batch/run 需为完整 ID")
  rows, issues = [], []
  for workspace in workspaces:
    workflows, snapshots = _discover(workspace, issues)
    for batch in sorted(workflows | snapshots):
      if batch_id is not None and batch != batch_id:
        continue
      try:
        found = _workflow_rows(workspace, batch) if batch in workflows else _stop_rows(workspace, batch)
        rows.extend(row for row in found if run_id is None or row["run_id"] == run_id)
        if len(rows) > _LIMIT:
          rows = rows[:_LIMIT]
          issues.append(_issue(workspace, batch, "history-limit"))
          break
      except (Conflict, SessionError, OSError, ValueError):
        issues.append(_issue(workspace, batch, "batch-unavailable"))
  rows.sort(key=lambda row: (-(row["observed_at_ns"] or 0), row["profile"], row["batch_id"], row["run_id"]))
  return {"schema_version": 1, "sessions": rows, "issues": issues, "incomplete": bool(issues)}


def for_scope(local, *, profile=None, agent=None, batch_id=None, run_id=None):
  from .local import available_profiles
  from .workspace import load_instance_workspaces
  available = dict(available_profiles())
  if profile is not None and profile not in available or agent not in (None, "dsh", "pi", "omp"):
    raise ValueError("无效的停止记录范围")
  selected = {name: tool for name, tool in available.items()
    if profile in (None, name) and agent in (None, tool) and tool in ("dsh", "pi", "omp")}
  if not selected:
    raise ValueError("工具和配方不匹配")
  workspaces = load_instance_workspaces(Path(local), sorted(selected))
  if ([ws.profile for ws in workspaces] != sorted(selected)
      or any(ws.agent != selected[ws.profile] for ws in workspaces)):
    raise Conflict("停止记录范围发生变化")
  return history(workspaces, batch_id=batch_id, run_id=run_id)
