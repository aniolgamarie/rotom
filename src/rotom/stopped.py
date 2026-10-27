"""已保存停止记录的只读选择；恢复仍经过原有部署和会话门禁。"""
import json
from pathlib import Path
import shlex
import unicodedata

from agentcfg.presentation import _text
from agentcfg.storage import Conflict

from .context import Scope
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
  result = _query(context.scope, batch_id=args.batch, run_id=args.run)
  if args.list:
    _render(result, context)
    return 4 if result["incomplete"] else 0
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
      policy=policy, label="选择在当前终端恢复的停止会话（不需要 Herdr，不发送继续）")
    selected = rows[int(choice)]
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
  from .maintenance import restore_selected
  return restore_selected(workspace, row["batch_id"], row["run_id"], context)
