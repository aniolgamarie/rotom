"""薄驻留启动器；不持单次 Agent 租约，不读输入，普通 run 不调用此模块。"""

import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import select
import shlex
import signal
import socket
import stat
import struct
import subprocess
import sys
import termios
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
  sys.path.insert(0, str(ROOT / "src"))

from agentcfg import run_owners
from agentcfg.lifecycle import observation_guard
from agentcfg.pane_records import ContainerStore
from agentcfg.paths import PathError
from agentcfg.schema import ConfigError
from agentcfg.secrets import CredentialError
from agentcfg.storage import Conflict, LockBusy, StateError, Tree, ensure_private
from termcfg.errors import TermcfgError


_PAYLOADS = ("ROTOM_WORK_LAUNCH_V1", "ROTOM_WORK_LAUNCH_V2", "ROTOM_RESTORE_LAUNCH_V1")
_IDS = ("workspace_id", "tab_id", "pane_id", "terminal_id")


def _released(record):
  if record is None:
    return False
  state = record.get("lifecycle_state", record.get("state"))
  observation = record.get("process_observation", record.get("observation", {}))
  return (record.get("backend") == "managed" and state == "idle_confirmed" and observation.get("kind") == "complete_release"
    and observation.get("coverage") == "complete")


def _source_identity():
  from termcfg.work import source_digest
  return source_digest(ROOT)


def _verify_terminal(reference):
  from termcfg.herdr import HerdrClient, Deadline
  from termcfg.work import info
  with HerdrClient(reference["socket_path"], Deadline(timeout=2),
      expected_identity=reference["server_identity"]) as client:
    pane = info(client.request("pane.get", {"pane_id": reference["pane_id"]}), "pane")
    cwd = pane.get("foreground_cwd") or pane.get("cwd")
    if any(pane[key] != reference[key] for key in _IDS) or cwd is not None and cwd != reference["cwd"]:
      raise Conflict("原终端位置已改变；请使用当前终端恢复")
  return True


def _locations(root):
  from agentcfg.restore_locations import LocationStore
  return LocationStore(root)


def _endpoint_info(root):
  with Tree(root) as tree:
    with tree.parent("control.sock") as (fd, name):
      return os.stat(name, dir_fd=fd, follow_symlinks=False)


def _tty_fd():
  try:
    fd = sys.stdin.fileno()
    return fd if os.isatty(fd) else None
  except (OSError, ValueError):
    return None


def _request_path(workspace, value):
  path = run_owners._absolute(value)
  base = workspace.state_root / "restore-locations"
  if path.parent.parent != base:
    raise Conflict("恢复请求位置不属于所选实例")
  run_owners._run_id(path.name)
  run_owners._run_id(path.parent.name)
  return path


def _message(data):
  if len(data) > 8192:
    raise ValueError()
  value = json.loads(data, object_pairs_hook=run_owners._pairs, parse_constant=run_owners._invalid_constant)
  if (type(value) is not dict or set(value) != {"schema_version", "container_id", "generation", "request_root"}
      or type(value["schema_version"]) is not int or value["schema_version"] != 1
      or type(value["generation"]) is not int or not 1 <= value["generation"] < 2 ** 64):
    raise ValueError()
  run_owners._run_id(value["container_id"])
  run_owners._absolute(value["request_root"])
  return value


class _Close(Exception):
  pass


class _Resident:
  def __init__(self, workspace, store, listener, record, spawn, verify, code_identity):
    self.workspace, self.store, self.listener = workspace, store, listener
    self.record = record
    self.spawn, self.verify, self.code_identity = spawn, verify, code_identity
    self.child = None
    self.child_identity = None
    self.tty_fd = _tty_fd()
    self.tty_attributes = termios.tcgetattr(self.tty_fd) if self.tty_fd is not None else None

  def _save(self, **changes):
    self.record = self.store.update(self.record, {**self.record, **changes})

  def _unknown(self):
    # 可能已写入时先重读；不能用旧 expected 覆盖已消费请求或已记录的新子进程。
    try:
      self.record = self.store.read()
      if self.record is not None:
        self._save(state="unknown")
    except (StateError, OSError):
      pass
    self._here_notice()

  def _here_notice(self):
    command = shlex.join(["rotom", "resume", self.workspace.agent,
      "--local", str(self.workspace.local_path), "--profile", self.workspace.profile, "--stopped", "--here"])
    print("原位恢复不可确认；请在当前终端恢复：" + command, file=sys.stderr, flush=True)

  def _bound(self):
    current = self.store.read()
    if (current != self.record or self.code_identity() != self.record["manager_code_identity"]
        or run_owners.observed_process_identity(self.record["manager_identity"]["pid"]) != self.record["manager_identity"]
        or self.verify(deepcopy(self.record["terminal_ref"])) is not True):
      raise Conflict("驻留启动器或原位置身份已变化")
    endpoint = self.record["endpoint_identity"]
    info = _endpoint_info(self.store.root)
    if (not stat.S_ISSOCK(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_uid != os.geteuid() or [info.st_dev, info.st_ino] != [endpoint["device"], endpoint["inode"]]):
      raise Conflict("驻留控制端点身份已变化")

  def _start(self, argv):
    environment = {key: value for key, value in os.environ.items() if key not in _PAYLOADS}
    if self.tty_fd is not None:
      # 丢弃 parked 期间积压的旧按键；不读取或向新会话发送文本。
      termios.tcflush(self.tty_fd, termios.TCIFLUSH)
    child = self.spawn(argv, cwd=self.record["terminal_ref"]["cwd"], env=environment, close_fds=True)
    self.child = child
    # 必须在任何 poll/wait 之前捕获；即使早退，未 reap 的 zombie 仍可确认出生身份。
    self.child_identity = run_owners.observed_process_identity(child.pid)
    if self.child_identity is None:
      self._unknown()
    else:
      self._save(state="running", run_id=None, child_identity=self.child_identity)

  def _owner(self):
    if self.child_identity is None:
      return None
    with observation_guard(self.workspace):
      rows = run_owners.Registry(self.workspace.state_root / "run-owners", self.workspace.binding).snapshot()
    matching = [row for row in rows.values() if row["manager_identity"] == self.child_identity]
    return matching[0] if len(matching) == 1 else None

  def _poll(self):
    if self.child is None:
      return
    code = self.child.poll()
    if code is None:
      # 活动期仅等待子进程；不争用 Agent 启动时的 owner/Domain 元数据锁。
      return
    try:
      if code is not None and self.tty_fd is not None:
        termios.tcsetattr(self.tty_fd, termios.TCSANOW, self.tty_attributes)
      try:
        owner = self._owner()
      except LockBusy:
        # 更新持物理 EX 时本轮只读观察尚未取得 SH；退出事实保留到下一 tick。
        # 不把一般 Conflict 当作可重试，不再次启动或重放写入。
        if code is not None and self.record["state"] not in ("unknown", "parking"):
          self._save(state="parking")
        return
      if owner is not None and self.record["run_id"] != owner["run_id"]:
        self._save(run_id=owner["run_id"])
      if code is not None:
        self.child = None
        if self.record["state"] != "unknown" and _released(owner):
          self._bound()
          self._save(state="parked", child_identity=None)
          print("Agent 已完整退出；等待恢复（Ctrl-C 关闭驻留启动器）。", file=sys.stderr, flush=True)
        else:
          self._unknown()
    except (StateError, PathError, OSError, TermcfgError, ValueError, termios.error):
      if code is not None:
        self.child = None
      self._unknown()

  def _request(self, value):
    request_id = None
    consumed = False
    if self.child is not None:
      return {"status": "busy", "request_id": None}
    try:
      if (value["container_id"] != self.record["container_id"] or value["generation"] != self.record["generation"]
          or self.record["state"] != "parked"):
        raise Conflict("驻留容器当前不能恢复")
      self._bound()
      request_root = _request_path(self.workspace, value["request_root"])
      location = _locations(request_root)
      request, receipt = location.read_request(), location.read_receipt()
      scope = {**self.workspace.binding, "agent": self.workspace.agent}
      if (request is None or receipt is None or request["mode"] != "original" or request["scope"] != scope
          or request["terminal_ref"] != self.record["terminal_ref"] or request["cwd"] != self.record["terminal_ref"]["cwd"]
          or request["rotom_root"] != str(ROOT) or request["manager_code_identity"] != self.record["manager_code_identity"]
          or request["batch_id"] != request_root.parent.name or request["run_id"] != request_root.name
          or request["run_id"] != self.record["run_id"]
          or receipt["phase"] != "dispatched" or receipt["request_id"] != request["request_id"]):
        raise Conflict("恢复请求与原位置不匹配")
      request_id = request["request_id"]
      run_owners._run_id(request_id)
      if request_id in self.record["consumed_request_ids"]:
        raise Conflict("恢复请求已消费")
      # 写后异常也可能已消费，禁止回滚或再次启动；读回 unknown 保留单次请求事实。
      consumed = True
      self._save(state="resume_pending", last_request_id=request_id,
        consumed_request_ids=[*self.record["consumed_request_ids"], request_id])
      location.transition(receipt, {**receipt, "phase": "handoff", "terminal_ref": self.record["terminal_ref"]})
      self._bound()
      self._start([str(ROOT / ".venv/bin/python"), "-B", str(ROOT / "src/rotom/restore_child.py"),
        "--request-root", value["request_root"]])
      if self.record["state"] == "unknown":
        return {"status": "unknown", "request_id": request_id}
      return {"status": "accepted", "request_id": request_id}
    except (StateError, PathError, OSError, TermcfgError, ValueError, KeyError, TypeError, termios.error):
      if consumed:
        self._unknown()
      else:
        self._here_notice()
      return {"status": "unknown" if consumed else "rejected", "request_id": request_id}

  def _initial_argv(self, request_root):
    root = _request_path(self.workspace, str(request_root))
    location = _locations(root)
    request, receipt = location.read_request(), location.read_receipt()
    if (request is None or receipt is None or request["mode"] != "new-tab"
        or receipt["phase"] != "handoff" or receipt["request_id"] != request["request_id"]
        or request["scope"] != {**self.workspace.binding, "agent": self.workspace.agent}
        or receipt["terminal_ref"] != self.record["terminal_ref"]
        or request["cwd"] != self.record["terminal_ref"]["cwd"]
        or request["rotom_root"] != str(ROOT) or request["manager_code_identity"] != self.record["manager_code_identity"]
        or request["batch_id"] != root.parent.name or request["run_id"] != root.name):
      raise Conflict("新标签页恢复请求与驻留入口不匹配")
    return [str(ROOT / ".venv/bin/python"), "-B", str(ROOT / "src/rotom/restore_child.py"),
      "--request-root", str(root)]

  def _connection(self, connection):
    response = {"status": "rejected", "request_id": None}
    end = time.monotonic() + 2
    try:
      connection.settimeout(2)
      _, uid, _ = struct.unpack("3i", connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i")))
      if uid != os.geteuid():
        raise ValueError()
      data = b""
      while b"\n" not in data and len(data) <= 8192:
        remaining = end - time.monotonic()
        if remaining <= 0:
          raise ValueError()
        connection.settimeout(remaining)
        part = connection.recv(8193 - len(data))
        if not part:
          break
        data += part
      if len(data) > 8192:
        raise ValueError()
      if b"\n" in data:
        line, suffix = data.split(b"\n", 1)
        if suffix:
          raise ValueError()
      else:
        line = data
      response = self._request(_message(line))
    except (StateError, ValueError, TypeError, OSError, UnicodeError, RecursionError):
      pass
    try:
      remaining = end - time.monotonic()
      if remaining <= 0:
        return
      connection.settimeout(remaining)
      connection.sendall(run_owners._encode(response))
    except OSError:
      # 响应丢失不是重新派发许可。
      pass

  def _interrupt(self, signum, frame):
    # 自定义 Python handler 在 exec 后恢复默认；不能设 SIG_IGN 导致 CLI child 忽略 Ctrl-C。
    if self.child is None:
      raise _Close()

  def run(self, interval, initial_request_root=None):
    previous = signal.signal(signal.SIGINT, self._interrupt)
    try:
      self._bound()
      argv = [str(ROOT / "rotom"), "--no-input", "run", self.workspace.agent,
        "--local", str(self.workspace.local_path), "--profile", self.workspace.profile,
        "--cwd", self.record["terminal_ref"]["cwd"]]
      if initial_request_root is not None:
        argv = self._initial_argv(initial_request_root)
      self._start(argv)
      while True:
        self._poll()
        ready, _, _ = select.select([self.listener], [], [], interval)
        if ready:
          connection, _ = self.listener.accept()
          with connection:
            self._connection(connection)
    except (_Close, KeyboardInterrupt):
      if self.child is None and self.record["state"] == "parked":
        self._save(state="closed", child_identity=None)
        return 0
      self._unknown()
      return 4
    except (StateError, PathError, OSError, TermcfgError, ValueError, termios.error, KeyError, TypeError):
      self._unknown()
      return 4
    finally:
      signal.signal(signal.SIGINT, previous)


def run_resident(workspace, terminal_ref, *, store_root=None, spawn=None,
    verify_terminal=None, code_identity=None, poll_interval=0.05, initial_request_root: Path | None = None) -> int:
  """显式 Herdr 入口使用；正式开放仍需逐工具原生验收。可信回调不来自用户配置。"""
  listener = None
  store = None
  try:
    # 父进程只保留轻量归属；完整 Workspace 的 deferred store 也可能持有原秘密文档。
    if any(hasattr(workspace, field) for field in ("secret_store", "resolved", "adapter", "backend")):
      raise ValueError()
    if (type(poll_interval) not in (int, float) or not math.isfinite(poll_interval)
        or not 0 < poll_interval <= 2):
      raise ValueError()
    from agentcfg.paths import environment_home
    container_id = uuid.uuid4().hex
    state_home = run_owners._absolute(os.environ.get("XDG_STATE_HOME", str(environment_home() / ".local/state")))
    root = Path(store_root) if store_root is not None else state_home / "rotom/panes" / container_id
    endpoint = root / "control.sock"
    if len(os.fsencode(endpoint)) > 107:
      raise Conflict("驻留控制路径过长；请使用当前终端恢复")
    store = ContainerStore(root, container_id)
    ensure_private(root)
    store.read()
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(endpoint))
    os.chmod(endpoint, 0o600, follow_symlinks=False)
    listener.listen(4)
    endpoint_info = _endpoint_info(root)
    manager = run_owners.current_process_identity()
    identity = code_identity or _source_identity
    if not callable(identity):
      raise ValueError()
    record = store.create({"schema_version": 1, "container_id": container_id, "generation": 1,
      "manager_identity": manager, "terminal_ref": deepcopy(terminal_ref), "manager_code_identity": identity(),
      "control_protocol": 1, "endpoint_identity": {"path": str(endpoint), "device": endpoint_info.st_dev,
        "inode": endpoint_info.st_ino},
      "scope": {"local": str(workspace.local_path), "profile": workspace.profile, "agent": workspace.agent},
      "state": "running", "run_id": None, "child_identity": None, "consumed_request_ids": [], "last_request_id": None})
    return _Resident(workspace, store, listener, record, spawn or subprocess.Popen,
      verify_terminal or _verify_terminal, identity).run(poll_interval, initial_request_root)
  except (StateError, PathError, OSError, TermcfgError, ValueError, TypeError, termios.error):
    if store is not None:
      try:
        saved = store.read()
        if saved is not None and saved["state"] != "closed":
          store.update(saved, {**saved, "state": "unknown"})
      except (StateError, OSError):
        pass
    print("驻留入口不可确认；请使用 rotom resume --stopped --list 与 --here。", file=sys.stderr, flush=True)
    return 4
  finally:
    if listener is not None:
      listener.close()


def main(argv=None):
  parser = argparse.ArgumentParser(prog="rotom-resident", allow_abbrev=False)
  parser.add_argument("--local", required=True)
  parser.add_argument("--profile", required=True)
  parser.add_argument("--cwd", required=True)
  parser.add_argument("--terminal-ref", required=True)
  parser.add_argument("--initial-request-root", type=Path)
  args = parser.parse_args(argv)
  try:
    from agentcfg.workspace import load_instance_workspaces
    from agentcfg.restore_locations import validate_terminal
    rows = load_instance_workspaces(run_owners._absolute(args.local), [args.profile], repository=ROOT)
    if len(rows) != 1 or rows[0].profile != args.profile:
      raise ValueError()
    workspace = rows[0]
    cwd = run_owners._absolute(args.cwd)
    if len(args.terminal_ref.encode("utf-8")) > 32768:
      raise ValueError()
    reference = json.loads(args.terminal_ref, object_pairs_hook=run_owners._pairs,
      parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
    try:
      validate_terminal(reference)
    except Exception:
      raise Conflict("终端引用无效") from None
    if reference["cwd"] != str(cwd) or os.environ.get("HERDR_PANE_ID") != reference["pane_id"]:
      raise ValueError()
    _verify_terminal(reference)
    for key in _PAYLOADS:
      os.environ.pop(key, None)
    return run_resident(workspace, reference, initial_request_root=args.initial_request_root)
  except (ConfigError, CredentialError) as error:
    print("驻留实例配置或所需凭据无效；请核对所选配方。", file=sys.stderr)
    return error.exit_code
  except (StateError, PathError, OSError, TermcfgError, ValueError, UnicodeError, RecursionError, KeyError, TypeError):
    print("Herdr 原位置或实例归属无法核验；请使用当前终端恢复。", file=sys.stderr)
    return 4


if __name__ == "__main__":
  # 可被工作树中的固定 Python 脚本入口直接执行，不能采用另一 checkout 的模块。
  raise SystemExit(main())
