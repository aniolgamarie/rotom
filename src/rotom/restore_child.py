"""受保护位置交接的单次子进程；固定目标，不提供通用命令执行。"""
from pathlib import Path
import sys

# 直接执行固定脚本时也使用当前 checkout，不能落到 venv 的其它 editable 绑定。
if __package__ in (None, ""):
  sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True

import argparse
import os

from agentcfg.restore_locations import LocationStore, location_root
from agentcfg.paths import PathError
from agentcfg.storage import Conflict, StateError
from agentcfg.process import DependencyError
from agentcfg.schema import ConfigError
from agentcfg.secrets import CredentialError
from termcfg.errors import TermcfgError
from termcfg.work_config import ROOT


def verify_terminal(reference):
  from termcfg.herdr import Deadline, HerdrClient
  if os.environ.get("HERDR_PANE_ID") != reference["pane_id"]:
    raise Conflict("恢复终端调用身份不匹配")
  with HerdrClient(reference["socket_path"], Deadline(5), reference["server_identity"]) as client:
    client.request("ping", {})
    pane = client.request("pane.current", {"caller_pane_id": reference["pane_id"]})["pane"]
    if any(pane[key] != reference[key] for key in ("workspace_id", "tab_id", "pane_id", "terminal_id")):
      raise Conflict("恢复终端位置已变化")
  return True


def execute(store, *, load_workspace=None, verify=verify_terminal, launch=None):
  """handoff 后一次消费；失败/未知均不退回可再次启动的状态。"""
  from agentcfg.workspace import load_workspace as load
  from agentcfg import tool_maintenance as flow
  from termcfg.work import source_digest
  request = store.read_request()
  receipt = store.read_receipt()
  if (request is None or receipt is None or receipt["phase"] != "handoff"
      or request["rotom_root"] != str(ROOT) or request["manager_code_identity"] != source_digest(ROOT)
      or receipt["terminal_ref"] is None or verify(receipt["terminal_ref"]) is not True):
    raise Conflict("恢复交接未被准入或已消费")
  workspace = (load_workspace or load)(Path(request["scope"]["local"]), request["scope"]["profile"])
  if (request["scope"] != {**workspace.binding, "agent": workspace.agent}
      or store.root != location_root(workspace, request["batch_id"], request["run_id"])):
    raise Conflict("恢复交接不属于原工作范围")
  receipt = store.transition(receipt, {**receipt, "phase": "executing"})
  if launch is None:
    from rotom.resume import backend_for_workspace
    from agentcfg.sessions import ResumeCoordinator, SessionError
    def launch(target, *, expected_deployment):
      print("已发起恢复，加载待确认；请核对 session ID、原目录与历史后手动继续。", file=sys.stderr, flush=True)
      if target.ref.agent == "omp":
        print("OMP 在原生写入冲突时可能生成分叉 session，请核对实际 ID。", file=sys.stderr, flush=True)
      outcome = ResumeCoordinator(backend_for_workspace(workspace, target,
        expected_deployment=expected_deployment)).resume(target, location="here")
      if outcome.exit_code is None:
        raise SessionError(4, "restore_exit_unconfirmed")
      return outcome.exit_code
  code, _ = flow.restore_reserved(workspace, request, launch=launch)
  store.transition(receipt, {**receipt, "phase": "exited", "exit_code": code})
  return code


def main(argv=None):
  from agentcfg.sessions import SessionError
  parser = argparse.ArgumentParser(description="受保护的 Rotom 恢复交接内部入口")
  parser.add_argument("--request-root", required=True, type=Path)
  args = parser.parse_args(argv)
  store = None
  try:
    store = LocationStore(args.request_root)
    return execute(store)
  except (StateError, PathError, CredentialError, ConfigError, TermcfgError, SessionError, OSError, ValueError) as error:
    code = error.code if isinstance(error, (SessionError, TermcfgError)) else getattr(error, "exit_code", 4)
    code = code if code in (2, 3, 5) else 4
    # executing 可能已经启动，保留 unknown，不能补造未派发或重新开放。
    try:
      receipt = store.read_receipt() if store is not None else None
      if receipt is not None and receipt["phase"] in ("handoff", "executing"):
        store.transition(receipt, {**receipt, "phase": "failed" if code in (2, 3, 5) else "unknown",
          "reason": "restore-child-error-" + str(code), "exit_code": code if code in (2, 3, 5) else None})
    except (Conflict, OSError):
      pass
    label = {2: "恢复配置或参数无效", 3: "恢复所需凭据缺失", 5: "恢复依赖或能力不可用"}.get(code, "恢复结果不能确认")
    print(label + "；保留原请求，不自动重试。请查询原维护批次。", file=sys.stderr)
    return code


if __name__ == "__main__":
  raise SystemExit(main())
