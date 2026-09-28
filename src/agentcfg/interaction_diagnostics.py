"""各后端通用的离线终端和交互就绪诊断。"""

import os


def terminal_state():
  """只描述运行诊断命令的终端，不读取输入内容。"""
  result = {"stdin_tty": os.isatty(0), "canonical": None, "echo": None, "signals": None}
  if not result["stdin_tty"]:
    return result
  try:
    import termios
  except ImportError:
    return result
  try:
    flags = termios.tcgetattr(0)[3]
    result.update(canonical=bool(flags & termios.ICANON), echo=bool(flags & termios.ECHO),
      signals=bool(flags & termios.ISIG))
  except (OSError, ValueError, termios.error):
    pass
  return result


def readiness(report):
  """依据已有离线检查给出稳定、脱敏的下一步；不推断登录或模型可用性。"""
  blockers = []
  actions = []
  if report["recovery_pending"]:
    blockers.append("recovery-pending")
    actions.append("apply-or-rollback")
  if report["dependencies"] != "installed":
    blockers.append("dependencies-" + report["dependencies"])
    actions.append("sync")
  if not report["deployed"]:
    blockers.append("not-deployed")
    actions.append("setup")
  elif report.get("deployed_dependencies") != "installed":
    blockers.append("deployed-dependencies-unavailable")
    if report.get("deployed_runtime_matches_current"):
      actions.append("sync")
    else:
      actions.extend(("plan", "setup"))
  if report.get("conflicts") or report.get("drift"):
    blockers.append("deployment-conflict-or-drift")
    actions.append("plan")
  elif report.get("changes_pending"):
    blockers.append("changes-pending")
    actions.append("plan")
  return {"status": "action-required" if blockers else "offline-ready",
    "blockers": blockers, "next_commands": list(dict.fromkeys(actions)),
    "authentication": "not-inspected"}


def inspect(workspace, report):
  result = {"diagnostic_terminal": terminal_state(), "readiness": readiness(report),
    "note": "终端标志只描述诊断进程；不记录按键，也不能证明原生宿主已收到输入"}
  if workspace.agent == "omp":
    from .omp_input_diagnostics import inspect as inspect_omp
    result["host_events"] = inspect_omp(workspace)
  else:
    result["host_events"] = {"status": "not-available", "reason": "此后端没有受管输入阻塞事件源"}
  return result
