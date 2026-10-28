"""已保存停止记录的只读选择；恢复仍经过原有部署和会话门禁。"""
from dataclasses import replace
import io
import json
from pathlib import Path
import shlex
import unicodedata

from agentcfg.presentation import _text
from agentcfg.storage import Conflict
from termcfg.errors import TermcfgError

from .restore_deadline import ReadyDeadline

from .context import Scope, InputGateway
from .resume import _local_path


def _query(scope, *, batch_id=None, run_id=None):
  from agentcfg.stopped_sessions import for_scope
  return for_scope(Path(_local_path(scope)), profile=scope.profile, agent=scope.agent,
    batch_id=batch_id, run_id=run_id)


def _display(value):
  # 保留原展示函数的可见换行转义，另替换 bidi 等格式控制；完整 ID/cwd 不截断。
  return "".join("?" if unicodedata.category(char).startswith("C") or char in "\u2028\u2029"
    else char for char in _text(value))


def _description(row):
  return _display(f"{row['agent']} / {row['profile']} / session={row['session_id']} / cwd={row['cwd']} / "
    f"title={row['title'] or '无标题'} / stop={row['stop_status']} / restore={row['restore_status']} / "
    f"batch={row['batch_id']} / run={row['run_id']} / " + (
      "可尝试恢复（启动前复核）" if row["source"] == "workflow" and row["restorable"] else "暂不可快速恢复"))


def _render(result, context):
  gateway = context.input_gateway
  if context.output_mode == "json" or context.output_mode == "auto" and not gateway.stdout.isatty():
    print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=gateway.stdout)
    return
  for row in result["sessions"]:
    print(_description(row), file=gateway.stdout)
    location = row.get("location_request")
    if location is not None:
      print(_display("  位置请求：" + location["location"] + " / " + location["phase"] +
        "；加载待确认，不发送继续。"), file=gateway.stdout)
    manual = row["next_commands"].get("manual_restore")
    if manual is not None:
      print("人工核对后可自行执行：" + _display(shlex.join(manual)), file=gateway.stdout)
  if not result["sessions"] and not result["incomplete"]:
    print("没有已保存的停止记录。", file=gateway.stdout)
  for issue in result["issues"]:
    print(_display(f"停止记录待核验：profile={issue['profile']} / batch={issue['batch_id']} / {issue['reason']}"), file=gateway.stderr)
  if result["incomplete"]:
    print("停止记录查询不完整；已保留可读取的记录，请先核验异常批次。", file=gateway.stderr)


def dispatch(invocation, args):
  context = invocation.context
  gateway, policy = context.input_gateway, context.input_policy
  location = "original" if args.original else "new-tab" if args.new_tab else "here"
  deadline = None
  if not args.list and location != "here" and (args.all or args.batch is not None and args.run is not None):
    deadline = ReadyDeadline(getattr(args, "wait_seconds", None) or 30)
  result = _query(context.scope, batch_id=args.batch, run_id=args.run)
  if args.list:
    _render(result, context)
    return 4 if result["incomplete"] else 0
  if args.all:
    return _restore_all(context, args.batch, result, location,
      deadline=deadline)
  label = ("选择在当前终端恢复的停止会话（不需要 Herdr，不发送继续）" if location == "here" else
    "选择停止会话恢复到" + ("原 pane" if location == "original" else "新标签页") + "（须逐工具/Linux/Herdr/驻留准入，不发送继续）")
  rows = [row for row in result["sessions"] if row["source"] == "workflow" and row["restorable"] is True]
  if not rows:
    _render(result, context)
    return 4
  if args.batch is not None and args.run is not None:
    if len(rows) != 1:
      raise Conflict("停止记录归属不唯一")
    selected = rows[0]
  else:
    choice = gateway.choose([(str(index), _description(row)) for index, row in enumerate(rows)],
      policy=policy, label=label)
    selected = rows[int(choice)]
  if deadline is None and location != "here":
    deadline = ReadyDeadline(getattr(args, "wait_seconds", None) or 30)
  try:
    if deadline is not None:
      deadline.remaining()
    workspace, row = _validated_row(context, selected)
    if deadline is not None:
      deadline.remaining()
  except TermcfgError as error:
    if error.reason != "restore_ready_timeout":
      raise
    _batch_result(context, selected["batch_id"], location, [{"run_id": selected["run_id"],
      "exit_code": 4, "result": {"status": "not_dispatched", "reason": error.reason}}], reason=error.reason)
    return 4
  if location != "here":
    from .pane_dispatch import dispatch_location
    return dispatch_location(workspace, row["batch_id"], row["run_id"], context, location=location, deadline=deadline)
  from .maintenance import restore_selected
  return restore_selected(workspace, row["batch_id"], row["run_id"], context)


def _validated_row(context, selected):
  """每项只加载明确范围，并重查精确原记录；不选择替代目标。"""
  if (context.scope.agent not in (None, selected["agent"])
      or context.scope.profile not in (None, selected["profile"])):
    raise Conflict("停止记录不属于所选工具或配方")

  from agentcfg.workspace import load_workspace
  workspace = load_workspace(Path(selected["scope"]["local"]), selected["profile"])
  binding = {key: selected["scope"][key] for key in ("machine", "local", "profile")}
  if (workspace.binding != binding or workspace.profile != selected["profile"]
      or workspace.agent != selected["agent"] or selected["scope"]["agent"] != workspace.agent):
    raise Conflict("停止记录的恢复范围发生变化")
  exact = Scope(local=selected["scope"]["local"], profile=workspace.profile, agent=workspace.agent)
  current = _query(exact, batch_id=selected["batch_id"], run_id=selected["run_id"])
  if current["incomplete"] or len(current["sessions"]) != 1:
    raise Conflict("停止记录的恢复条件不能确认")
  row = current["sessions"][0]
  if (row["restorable"] is not True or any(row[key] != selected[key] for key in (
      "scope", "agent", "profile", "batch_id", "run_id", "session_id", "session_ref", "cwd", "source"))):
    raise Conflict("停止记录的恢复目标发生变化")
  if row["source"] != "workflow":
    raise Conflict("停止记录来源不能确认")
  return workspace, row



def _batch_result(context, batch_id, location, results, *, reason=None):
  value = {"batch_id": batch_id, "location": location, "results": results,
    "load_confirmation": "unknown", "continue_status": "not_sent"}
  if reason is not None:
    value["reason"] = reason
  gateway = context.input_gateway
  if context.output_mode == "json" or context.output_mode == "auto" and not gateway.stdout.isatty():
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), file=gateway.stdout)
  else:
    for item in results:
      status = item["result"].get("status")
      description = ("未派发" if status == "not_dispatched" else "结果未知" if status == "unknown"
        else "已交接" if item["exit_code"] == 0 else "失败或结果未知")
      reason_text = " / reason=" + item["result"]["reason"] if "reason" in item["result"] else ""
      print(_display(f"run={item['run_id']} / {description} / exit={item['exit_code']}" + reason_text), file=gateway.stdout)
    if reason is not None:
      print("整批恢复未完成；请查询原批次，结果未知不自动重试。", file=gateway.stderr)
    print("加载待确认，不发送继续。", file=gateway.stdout)


def _restore_all(context, batch_id, observed, location, *, deadline=None):
  """只为整批明确目标建立独立位置请求，不让多个 TUI 共用输入。"""
  from agentcfg.sessions import SessionError
  from agentcfg.schema import ConfigError
  from agentcfg.secrets import CredentialError
  from agentcfg.storage import StateError
  from termcfg.errors import TermcfgError
  from .pane_dispatch import dispatch_location
  deadline = deadline if deadline is not None else ReadyDeadline()
  rows = sorted(observed["sessions"], key=lambda row: row["run_id"])
  def untouched(reason):
    return [{"run_id": row["run_id"], "exit_code": None, "result": {
      "status": "not_dispatched", "reason": reason, "restore_status": row["restore_status"]}}
      for row in rows]
  # 不能从同一查询中静默筛掉不可恢复、坏记录或其它来源。
  invalid = "history-incomplete" if observed["incomplete"] or observed["issues"] else "no-workflow-targets" if not rows else None
  if rows:
    if len({row["run_id"] for row in rows}) != len(rows):
      invalid = "duplicate-run"
    elif any(row["source"] != "workflow" for row in rows):
      invalid = "non-workflow-source"
    elif any(row["restorable"] is not True for row in rows):
      invalid = "target-unavailable"
    elif any(row["scope"] != rows[0]["scope"] or row["profile"] != rows[0]["profile"]
        or row["agent"] != rows[0]["agent"] or row["batch_id"] != batch_id for row in rows):
      invalid = "batch-scope-mismatch"
  try:
    if invalid:
      raise Conflict("完整批次不能恢复")
    for row in rows:
      deadline.remaining()
      _validated_row(context, row)
      deadline.remaining()
  except (StateError, ConfigError, CredentialError, SessionError, TermcfgError, OSError, ValueError) as error:
    if isinstance(error, TermcfgError) and error.reason == "restore_ready_timeout":
      invalid = error.reason
    print("整批核验失败：存在不可恢复、来源不明、范围漂移或不完整记录；未派发任何项。", file=context.input_gateway.stderr)
    _batch_result(context, batch_id, location, untouched(invalid or "target-recheck-failed"), reason=invalid or "target-recheck-failed")
    return 4
  results = []
  stopped = False
  timeout = False
  for selected in rows:
    if stopped:
      results.append({"run_id": selected["run_id"], "exit_code": None,
        "result": {"status": "not_dispatched", "reason": "restore_ready_timeout" if timeout else "earlier-item-unconfirmed"}})
      continue
    stream = io.StringIO()
    gateway = context.input_gateway
    item_context = replace(context, output_mode="json",
      input_gateway=InputGateway(gateway.stdin, stream, gateway.stderr))
    dispatch_started = False
    try:
      deadline.remaining()
      workspace, row = _validated_row(context, selected)
      deadline.remaining()
      dispatch_started = True
      code = dispatch_location(workspace, batch_id, row["run_id"], item_context, location=location, deadline=deadline)
      try:
        result = json.loads(stream.getvalue())
        if not isinstance(result, dict):
          raise ValueError()
      except (ValueError, TypeError):
        result = {"status": "unknown"}
    except (StateError, ConfigError, CredentialError, SessionError, TermcfgError, OSError, ValueError) as error:
      timeout = isinstance(error, TermcfgError) and error.reason == "restore_ready_timeout"
      code, result = 4, ({"status": "unknown" if dispatch_started else "not_dispatched", "reason": error.reason} if timeout else {"status": "unknown"})
    results.append({"run_id": selected["run_id"], "exit_code": code, "result": result})
    timeout = timeout or result.get("reason") == "restore_ready_timeout"
    stopped = code != 0 or result.get("status") == "unknown"
  _batch_result(context, batch_id, location, results, reason="item-unconfirmed" if stopped else None)
  return 4 if stopped else 0
