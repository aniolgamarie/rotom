"""维护阶段的公开交互；旧批次保留原查询路径。"""
import json
import re
from pathlib import Path
import sys

from agentcfg import tool_maintenance as workflow
from agentcfg.presentation import _text
from agentcfg.sessions import ResumeCoordinator, SessionError
from agentcfg.storage import Conflict

from .context import InputError
from .resume import _local_path


def _render(value, context, *, stream=None):
  stream = sys.stdout if stream is None else stream
  if context.output_mode == "json" or context.output_mode == "auto" and not context.input_gateway.stdout.isatty():
    print(json.dumps(value, ensure_ascii=False, sort_keys=True), file=stream)
    return
  lines = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).split("\n")
  print("\n".join(_text(line) for line in lines), file=stream)


def _sessions(values):
  from agentcfg.cli import selection_id
  result = {}
  for value in values or ():
    run, separator, session = value.partition("=")
    if re.fullmatch(r"[0-9a-f]{32}", run) is None or not separator or not session or run in result:
      raise ValueError("session 需为不重复的 RUN_ID=SESSION_ID")
    try:
      result[run] = selection_id(session)
    except Exception:
      raise ValueError("session 需为不重复的 RUN_ID=SESSION_ID") from None
  return result


def _batch_workspace(scope, batch_id):
  from agentcfg.local import available_profiles
  from agentcfg.workspace import load_instance_workspaces
  profiles = [name for name, agent in available_profiles()
    if scope.profile in (None, name) and scope.agent in (None, agent)]
  if not profiles:
    return None
  matches = []
  for workspace in load_instance_workspaces(Path(_local_path(scope)), profiles):
    value = workflow.Store(workspace, batch_id).read()
    if value is not None:
      matches.append(workspace)
  if not matches:
    return None
  if len(matches) != 1:
    raise Conflict("维护批次归属不唯一")
  return matches[0]


def _next(value):
  scope = value["scope"]
  prefix = ["rotom", "agent", "--local", scope["local"], "--profile", scope["profile"], "maintenance"]
  batch = value["batch_id"]
  commands = {name: [*prefix, name, "--batch", batch] for name in ("plan", "execute", "status", "cancel")}
  commands["restore"] = {run: [*prefix, "restore", "--batch", batch, "--run", run]
    for run, state in value.get("restores", {}).items() if state is None}
  return {**value, "next_commands": commands}


def _choose_sessions(workspace, runs, supplied, context):
  if not context.input_gateway.allows_input(context.input_policy):
    return supplied
  from agentcfg.run_owners import Registry
  records = Registry(workspace.state_root / "run-owners", workspace.binding).snapshot()
  auxiliary = {}
  if workspace.agent == "pi":
    from agentcfg.pi_session_observation import from_records
    auxiliary = {target.run_id: target for target in from_records(workspace, records)}
  for run in runs:
    observation = records.get(run, {}).get("session_observation")
    if run in supplied or run in auxiliary or observation is not None and observation.get("confirmation") != "unknown":
      continue
    if workspace.agent in ("pi", "omp"):
      from agentcfg.tool_session_headers import candidates
      rows = candidates(workspace)
      if rows:
        supplied[run] = context.input_gateway.choose([(item.known.ref.native_ref,
          _text(f"{item.known.ref.native_ref} / cwd={item.known.cwd}")) for item in rows],
          policy=context.input_policy, label=f"为运行 {run} 选择恢复会话（请先在原 TUI 核对 ID）")
        continue
    identifier = context.input_gateway.text(f"运行 {run} 的完整 session ID（从原 TUI 核对）", policy=context.input_policy)
    supplied.update(_sessions([run + "=" + identifier]))
  return supplied


def _choose_runs(scope, context):
  """缺失目标只在 TTY 选择一个完整运行；显式多项仍由重复 --run 表达。"""
  from agentcfg.run_owners import instances
  gateway, policy = context.input_gateway, context.input_policy
  gateway.require_input(policy)
  observed = instances(Path(_local_path(scope)), agent=scope.agent, profile=scope.profile)
  rows = []
  for row in observed["instances"]:
    if row["kind"] != "registered" or row["process"]["ownership_state"] not in ("active", "unknown"):
      continue
    run = row["run_id"]
    if type(run) is not str or re.fullmatch(r"[0-9a-f]{32}", run) is None:
      raise Conflict("维护运行身份不可确认")
    rows.append((run, _text(f"{row['agent']} / {row['profile']} / {run} / {row['process']['ownership_state']}")))
  return [gateway.choose(rows, policy=policy, label="选择维护的运行（多项请显式重复 --run）")]


def dispatch(invocation, args):
  """返回 None 表示旧批次；只按原入口查询，绝不自动迁移。"""
  context = invocation.context
  command = context.command_path[-1]
  gateway, policy = context.input_gateway, context.input_policy
  batch_id = getattr(args, "batch", None)
  if command in ("plan", "stop") and batch_id is None:
    from agentcfg.dsh_stop import workspace_for_scope
    from agentcfg.workspace import load_workspace
    runs = list(args.run) if args.run else _choose_runs(context.scope, context)
    if command == "stop" and args.plan_id is None:
      gateway.require_input(policy)
    supplied = _sessions(args.session)
    if set(supplied) - set(runs):
      raise InputError(2)
    selected = workspace_for_scope(Path(_local_path(context.scope)), selected_runs=runs, profile=context.scope.profile)
    workspace = load_workspace(selected.local_path, selected.profile)
    if workspace.binding != selected.binding or workspace.agent != selected.agent:
      raise Conflict("维护目标范围发生变化")
    sessions = _choose_sessions(workspace, runs, supplied, context)
    value = workflow.plan(workspace, selected_runs=runs, sessions=sessions)
    if value["readiness"] != "ready" and any(blocker.startswith("session-required:") for blocker in value["blockers"]):
      raise InputError(2)
    if command == "plan":
      _render({**value, "readonly": True, "selected_runs": value["stop_plan"]["selected_runs"], "plan": value["stop_plan"]}, context)
      return 0
    if args.plan_id is not None and args.plan_id != value["plan_id"]:
      _render(value, context)
      raise Conflict("维护计划已经变化；请按当前计划重新确认")
    def approve(current):
      if args.plan_id is not None:
        return args.plan_id == current["plan_id"]
      _render(current, context, stream=gateway.stderr)
      return gateway.confirm("保存所选会话清单并仅停止这些运行；更新配置须另行批准", policy=policy)
    result = workflow.stop(workspace, expected_plan=value, approve=approve, wait_seconds=args.wait_seconds)
    _render(_next(result), context)
    return 0 if result["stop_status"] == "stopped" else 4
  if command == "execute" and args.plan_id is None or command == "restore" and args.run is None:
    gateway.require_input(policy)
  workspace = _batch_workspace(context.scope, batch_id)
  if workspace is None:
    return None
  if command == "status":
    result = workflow.status(workspace, batch_id)
    _render(_next(result), context)
    # 取消只禁止后续阶段，不能盖住已派发动作尚无结果的事实。
    unresolved = result["stop_status"] not in ("stopped", "cancelled")
    unresolved = unresolved or result["setup"] is not None and result["setup"]["action"] == "setup-intent"
    unresolved = unresolved or any(row is not None and row["action"] == "restore-intent"
      for row in result["restores"].values())
    return 4 if unresolved else 0
  if command == "cancel":
    result = workflow.cancel(workspace, batch_id)
    _render(_next(result), context)
    return 0 if result["stop_status"] in ("stopped", "cancelled") else 4
  from agentcfg.workspace import load_workspace
  selected = load_workspace(workspace.local_path, workspace.profile)
  if selected.binding != workspace.binding or selected.agent != workspace.agent:
    raise Conflict("维护批次归属发生变化")
  workspace = selected
  if command == "plan":
    result = workflow.status(workspace, batch_id)
    _render({**_next(result), "setup_preview": workflow.preview_setup(workspace)}, context)
    return 0
  if command == "execute":
    from agentcfg.progress import Progress
    if args.plan_id is None and not gateway.allows_input(policy):
      raise InputError(2)
    def preview(selected, summary):
      print(_text("当前 setup 预览：" + json.dumps(summary, ensure_ascii=False, sort_keys=True)), file=gateway.stderr)
    def approve(value):
      if args.plan_id is not None:
        return args.plan_id == value["plan_id"]
      print(_text("setup plan_id=" + value["plan_id"]), file=gateway.stderr)
      return gateway.confirm("按当前预览同步依赖并更新配置；可能联网；仍检查活动实例和共享资源", policy=policy)
    code, result = workflow.execute(workspace, batch_id, approve=approve,
      progress=Progress("maintenance setup", workflow.setup_args(workspace)), preview=preview)
    _render(_next(result), context)
    return code
  if command == "restore":
    result = workflow.status(workspace, batch_id)
    selected = getattr(args, "run", None)
    pending = [run for run, state in result["restores"].items() if state is None]
    if selected is None:
      selected = gateway.choose([(run, _text(f"{run} / session={result['targets'][run]['ref']['native_ref']} / cwd={result['targets'][run]['cwd']}"))
        for run in pending], policy=policy, label="选择本终端恢复的实例")
    def launch(target, *, expected_deployment):
      from .resume import backend_for_workspace
      if target.ref.agent == "omp":
        print("OMP 在原生写入冲突时可能生成分叉 session；请核对界面实际 ID 后手动继续。", file=gateway.stderr, flush=True)
      def notice(outcome):
        if outcome.status == "launch_dispatched" and outcome.exit_code is None:
          print("已发起恢复，加载待确认；在原生 TUI 核对 session ID、目录和历史后手动继续。", file=gateway.stderr, flush=True)
      backend = backend_for_workspace(workspace, target, expected_deployment=expected_deployment)
      outcome = ResumeCoordinator(backend, notice=notice).resume(target, location="here")
      if outcome.exit_code is None:
        # 派发或结果未知不是原生退出事实；保留原意图供明确查询，不补造失败结果。
        raise SessionError(4, "restore_exit_unconfirmed")
      return outcome.exit_code
    code, result = workflow.restore(workspace, batch_id, run_id=selected, launch=launch)
    _render(_next(result), context)
    return code
  raise InputError(2)
