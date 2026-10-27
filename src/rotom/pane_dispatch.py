"""已停止 workflow 的显式位置选择；普通终端与原生输入保持独立。"""
import json
from contextlib import ExitStack
import os
from pathlib import Path
import shlex
import socket
import stat
import struct
import sys

from agentcfg import deployment, run_owners
from agentcfg.pane_records import ContainerStore
from agentcfg.paths import PathError
from agentcfg.restore_locations import reserve
from agentcfg.schema import ConfigError
from agentcfg.sessions import SessionError
from agentcfg.storage import Conflict, StateError, Tree
from termcfg.errors import TermcfgError
from termcfg.work_config import ROOT


# 精确工具/运行包/位置须经原生验收后逐条加入；fake 测试不得修改发行准入。
_ADMITTED = frozenset({
  ("dsh", "e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d", "new-tab"),
  ("dsh", "e4d56f338da80e7854193c17b3cad7fbcc5feaa4fb221efdc091867158da724d", "original"),
  ("omp", "490e6c90d0ef4d890bb2ab14e006dcd3a3f4d79b5e6ad0ca9fbf3e8f4ab610ab-linux-x64", "new-tab"),
  ("omp", "490e6c90d0ef4d890bb2ab14e006dcd3a3f4d79b5e6ad0ca9fbf3e8f4ab610ab-linux-x64", "original"),
  ("pi", "2b087056df46cc4075d641f00a4a5af1b13820a89a72928fede81af15347bf84", "new-tab"),
  ("pi", "2b087056df46cc4075d641f00a4a5af1b13820a89a72928fede81af15347bf84", "original"),
  ("pi", "567d64966f7b4d9b92e7bb4d33504d0f86facaf2dedac8880ff6ef3c8df7a7f0", "new-tab"),
  ("pi", "567d64966f7b4d9b92e7bb4d33504d0f86facaf2dedac8880ff6ef3c8df7a7f0", "original"),
  ("pi", "b4beec0dc0f4058fac81cb66e51b04c53b5e6507645b836143d7919c61aa1acc", "new-tab"),
  ("pi", "b4beec0dc0f4058fac81cb66e51b04c53b5e6507645b836143d7919c61aa1acc", "original"),
  ("pi", "d97010399b8648a2400feb0bb6cac3d17aa1b8e86feb7806f72eb668b6ff7e1c", "new-tab"),
  ("pi", "d97010399b8648a2400feb0bb6cac3d17aa1b8e86feb7806f72eb668b6ff7e1c", "original"),
})


def _admitted(agent, identity, location):
  return sys.platform == "linux" and (agent, identity, location) in _ADMITTED


def _runtime(workspace):
  try:
    with Tree(workspace.state_root) as state:
      current = deployment.read_state(state)["current"]
      if current is None or state.read("pending.json") is not None or current["binding"] != workspace.binding:
        raise Conflict("恢复位置的部署不能核实")
      route = [item.get("literal") for item in current["launch"]["environment"]
        if item["name"] == "AGENTCFG_DSH_EXECUTION"]
      if route and (workspace.agent != "dsh" or route != ["local"]):
        raise SessionError(5, "position_requires_local_managed_backend")
      return current["launch"].get("runtime_identity", current["launch"]["lock_identity"])
  except (KeyError, TypeError, AttributeError):
    raise Conflict("恢复位置的部署不能核实") from None


def _here(workspace, batch_id, run_id):
  return ["rotom", "--no-input", "resume", workspace.agent, "--local", str(workspace.local_path),
    "--profile", workspace.profile, "--stopped", "--batch", batch_id, "--run", run_id, "--here"]


def wrap_launch(settings, launcher, command, cwd, client, pane):
  """只包装已接受的 Herdr Agent 新启动；未准入沿用普通一次运行。"""
  if launcher not in ("dsh", "pi"):
    return command
  from termcfg.work_config import _prepared_agent
  from agentcfg.workspace import load_instance_workspaces
  try:
    profile = getattr(settings, launcher + "_profile")
    runtime = _prepared_agent(settings, launcher, profile)
    workspace = load_instance_workspaces(settings.local_path, [profile], repository=ROOT)[0]
    admitted = (_runtime(workspace) == runtime["identity"]
      and _admitted(launcher, runtime["identity"], "original"))
  except (StateError, PathError, ConfigError, SessionError, TermcfgError, OSError, AttributeError, KeyError, TypeError):
    admitted = False
  if not admitted:
    print("该工具/运行包未准入驻留；此次为普通启动，退出后返回，原 pane 恢复不可用。", file=sys.stderr)
    return command
  reference = {"socket_path": client.socket_path, "server_identity": list(client.identity),
    **{key: pane[key] for key in ("workspace_id", "tab_id", "pane_id", "terminal_id")}, "cwd": str(cwd)}
  return [str(ROOT / ".venv/bin/python"), "-B", str(ROOT / "src/rotom/resident.py"),
    "--local", str(settings.local_path), "--profile", profile, "--cwd", str(cwd),
    "--terminal-ref", json.dumps(reference, ensure_ascii=False, separators=(",", ":"))]


def child_command(store):
  """新 tab 的恢复首启也按实测组合选择驻留；目标只来自受保护请求。"""
  request, receipt = store.read_request(), store.read_receipt()
  base = [str(ROOT / ".venv/bin/python"), "-B"]
  from agentcfg.workspace import load_workspace
  workspace = load_workspace(Path(request["scope"]["local"]), request["scope"]["profile"])
  if request["scope"] != {**workspace.binding, "agent": workspace.agent}:
    raise Conflict("恢复交接范围发生变化")
  if _admitted(workspace.agent, _runtime(workspace), "original"):
    return [*base, str(ROOT / "src/rotom/resident.py"), "--local", str(workspace.local_path),
      "--profile", workspace.profile, "--cwd", request["cwd"], "--terminal-ref",
      json.dumps(receipt["terminal_ref"], ensure_ascii=False, separators=(",", ":")),
      "--initial-request-root", str(store.root)]
  return [*base, str(ROOT / "src/rotom/restore_child.py"), "--request-root", str(store.root)]


def container_for(workspace, run_id):
  from agentcfg.paths import environment_home
  state_home = run_owners._absolute(os.environ.get("XDG_STATE_HOME", str(environment_home() / ".local/state")))
  root = state_home / "rotom" / "panes"
  rows = []
  active = []
  with Tree(root) as tree:
    if tree.fd is None:
      return None
    names = os.listdir(tree.fd)
    if len(names) > 4096:
      raise Conflict("驻留位置记录过多，无法唯一核实")
    for name in names:
      run_owners._run_id(name)
      value = ContainerStore(root / name, name).read()
      if value is not None and value["scope"] == {
          "local": str(workspace.local_path), "profile": workspace.profile, "agent": workspace.agent}:
        if value["run_id"] == run_id:
          rows.append((root / name, value))
        elif (value["run_id"] is None and value["state"] in ("running", "parking", "resume_pending")
            and value["child_identity"] is not None):
          active.append((root / name, value))
  if active:
    # 只在明确查询时关联活动 child，不在驻留父进程中轮询，也不回写容器。
    # ContainerStore 的短锁已经释放；按原物理 SH → owner 顺序读取。
    from agentcfg.lifecycle import observation_guard
    with observation_guard(workspace):
      owner = run_owners.Registry(workspace.state_root / "run-owners", workspace.binding).snapshot().get(run_id)
    if (owner is not None and owner.get("schema_version") == 2 and owner.get("agent") == workspace.agent
        and owner.get("backend") == "managed" and owner.get("profile") == workspace.profile):
      rows.extend((path, value) for path, value in active if value["child_identity"] == owner["manager_identity"])
  if len(rows) > 1:
    raise Conflict("原位置归属不唯一")
  return rows[0] if rows else None


def _original_ready(workspace, run_id):
  from .resident import _verify_terminal, _source_identity
  found = container_for(workspace, run_id)
  if found is None:
    raise SessionError(5, "original_launcher_not_registered")
  root, value = found
  if value["manager_code_identity"] != _source_identity():
    raise SessionError(5, "original_manager_code_changed")
  if run_owners.observed_process_identity(value["manager_identity"]["pid"]) != value["manager_identity"]:
    raise SessionError(5, "original_launcher_lost")
  if (value["state"] != "parked" or value["run_id"] != run_id or value["child_identity"] is not None
      or _verify_terminal(value["terminal_ref"]) is not True):
    raise Conflict("原 launcher/pane 不可用或结果未知；保留停止记录")
  endpoint = value["endpoint_identity"]
  if endpoint["path"] != str(root / "control.sock"):
    raise Conflict("原 launcher 控制端点归属变化")
  return root, value


def describe_options(workspace, run_id):
  """非许可性的只读诊断；每次实际交接仍重新核验。"""
  result = {"here": {"status": "independent", "reason": "no-herdr-required"},
    "new-tab": {"status": "unavailable", "reason": "exact-combination-unavailable"},
    "original": {"status": "unsupported", "reason": "no-resident-launcher"}}
  try:
    identity = _runtime(workspace)
    if _admitted(workspace.agent, identity, "new-tab"):
      result["new-tab"] = {"status": "requires-herdr", "reason": "verify-current-herdr-before-dispatch"}
    if not _admitted(workspace.agent, identity, "original"):
      result["original"] = {"status": "unavailable", "reason": "exact-combination-unavailable"}
      return result
    found = container_for(workspace, run_id)
    if found is None:
      return result
    _, value = found
    from .resident import _source_identity, _verify_terminal
    if run_owners.observed_process_identity(value["manager_identity"]["pid"]) != value["manager_identity"]:
      result["original"] = {"status": "lost", "reason": "launcher-exited-or-replaced"}
    elif value["manager_code_identity"] != _source_identity():
      result["original"] = {"status": "incompatible", "reason": "manager-code-changed"}
    elif value["state"] == "unknown":
      result["original"] = {"status": "unknown", "reason": "lifecycle-unconfirmed"}
    elif value["state"] == "closed":
      result["original"] = {"status": "lost", "reason": "launcher-closed"}
    elif _verify_terminal(value["terminal_ref"]) is True:
      result["original"] = {"status": "available" if value["state"] == "parked" else "after-stop",
        "reason": "recheck-before-dispatch", "container_id": value["container_id"], "terminal_ref": value["terminal_ref"]}
  except SessionError:
    result["original"] = {"status": "unavailable", "reason": "local-managed-backend-required"}
  except (Conflict, TermcfgError, OSError, ValueError):
    result["original"] = {"status": "unknown", "reason": "position-cannot-be-verified"}
  return result


def _send_original(root, container, store):
  """固定 socket inode 和内核 peer；只发送请求引用，不发送终端文本。"""
  endpoint = container["endpoint_identity"]
  fd = None
  try:
    fd = os.open(endpoint["path"], os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
    info = os.fstat(fd)
    if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600
        or (info.st_dev, info.st_ino) != (endpoint["device"], endpoint["inode"])):
      raise Conflict("原 launcher 控制端点身份变化")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
      connection.settimeout(3)
      connection.connect(f"/proc/self/fd/{fd}")
      pid, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
      if (uid != os.geteuid() or pid != container["manager_identity"]["pid"]
          or run_owners.observed_process_identity(pid) != container["manager_identity"]):
        raise Conflict("原 launcher 进程身份变化")
      receipt = store.read_receipt()
      store.transition(receipt, {**receipt, "phase": "dispatched"})
      connection.sendall(run_owners._encode({"schema_version": 1, "container_id": container["container_id"],
        "generation": container["generation"], "request_root": str(store.root)}))
      data = b""
      while not data.endswith(b"\n") and len(data) <= 8192:
        part = connection.recv(8193 - len(data))
        if not part:
          break
        data += part
      response = json.loads(data, object_pairs_hook=run_owners._pairs,
        parse_constant=run_owners._invalid_constant)
      if (type(response) is not dict or set(response) != {"status", "request_id"}
          or response["status"] != "accepted" or response["request_id"] != store.read_request()["request_id"]):
        raise Conflict("原位恢复没有明确接受；保留请求，不重发")
      saved = store.read_receipt()
      if saved["phase"] not in ("handoff", "executing", "exited") or saved["terminal_ref"] != container["terminal_ref"]:
        raise Conflict("原位恢复没有对应交接事实；保留请求，不重发")
      return {"created": False, "handoff": True, "request_id": response["request_id"],
        "terminal_ref": container["terminal_ref"], "phase": "handoff"}
  except (OSError, ValueError, UnicodeError, RecursionError):
    raise Conflict("原位恢复结果未知；保留请求，不自动重发") from None
  finally:
    if fd is not None:
      os.close(fd)


def dispatch_location(workspace, batch_id, run_id, context, *, location):
  """先核验环境，再保留原恢复意图；创建/交接事实与加载确认分别输出。"""
  gateway = context.input_gateway
  store = None
  reservation_started = False
  client = None
  stack = ExitStack()
  try:
    if location not in ("original", "new-tab") or not _admitted(workspace.agent, _runtime(workspace), location):
      raise SessionError(5, "exact_location_combination_unavailable")
    if location == "original":
      root, container = _original_ready(workspace, run_id)
      reservation_started = True
      store = reserve(workspace, batch_id, run_id, mode=location, terminal_ref=container["terminal_ref"])
      result = _send_original(root, container, store)
    else:
      from termcfg.herdr import Deadline, require_startup_evidence
      from termcfg.work import connected
      from termcfg.work_config import read_settings
      from termcfg.restore_tabs import create_restore_tab
      settings = read_settings(local=workspace.local_path)
      client, binary = stack.enter_context(connected(settings, Deadline(60), start=False))
      caller_id = os.environ.get("HERDR_PANE_ID")
      if not caller_id:
        raise TermcfgError(5, "restore_requires_herdr_context", "rotom resume --stopped --list")
      pane = client.request("pane.current", {"caller_pane_id": caller_id})["pane"]
      require_startup_evidence(client, settings, binary)
      reservation_started = True
      store = reserve(workspace, batch_id, run_id, mode=location)
      result = create_restore_tab(client, settings, store, workspace_id=pane["workspace_id"], caller_id=caller_id)
    result = {**result, "location": location, "batch_id": batch_id, "run_id": run_id,
      "load_confirmation": "unknown", "continue_status": "not_sent"}
    if context.output_mode == "json" or context.output_mode == "auto" and not gateway.stdout.isatty():
      print(json.dumps(result, ensure_ascii=False, sort_keys=True), file=gateway.stdout)
    else:
      print("恢复位置已交接，加载待确认；不发送继续。request=" + result["request_id"], file=gateway.stdout)
    return 0
  except (SessionError, TermcfgError, Conflict, OSError) as error:
    print("所选恢复位置未完成：需要受支持的 Herdr 组合；原位还需保留 launcher/pane。结果未知不重发。", file=gateway.stderr)
    print("同范围当前终端命令（已有派发时请先查询原批次，勿重复执行）：" +
      shlex.join(_here(workspace, batch_id, run_id)), file=gateway.stderr)
    if reservation_started:
      print("恢复意图已保存或结果未知，请查询原批次与位置请求；可能已创建或交接，不自动重试。", file=gateway.stderr)
      status = ["rotom", "--no-input", "agent", "--local", str(workspace.local_path),
        "--profile", workspace.profile, "maintenance", "status", "--batch", batch_id, "--format", "json"]
      print("原批次查询：" + shlex.join(status), file=gateway.stderr)
      return 4
    return getattr(error, "code", 4 if isinstance(error, Conflict) else 6)
  finally:
    stack.close()
