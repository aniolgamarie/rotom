"""项目入口；锁只串行本入口，不声称跨native请求事务。"""

from contextlib import contextmanager
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import uuid

from .errors import TermcfgError
from .work_config import ROOT, ROLES, PAYLOAD_ENV, literal
from .work_config import prepare_tool, operation_timeout


SOURCE = "rotom-work-v1"
LAUNCH_SOURCE = "rotom-work-launch-v1"
LOCK_ROOT = Path("/tmp") / ("rotom-work-" + str(os.geteuid()))
_last_sequence = 0


def conflict(reason="work_context_unknown"):
  return TermcfgError(4, reason, "work enter PATH")


@contextmanager
def operation_lock(deadline, *, root=None):
  from agentcfg.paths import _absolute_directory, PathError, _check_private
  root = Path(root or LOCK_ROOT)
  directory = lock = None
  try:
    with _absolute_directory(root.parent) as parent:
      try:
        os.mkdir(root.name, mode=0o700, dir_fd=parent)
      except FileExistsError:
        pass
      directory = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        dir_fd=parent)
    _check_private(directory)
    lock = os.open("operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
      0o600, dir_fd=directory)
    info = os.fstat(lock)
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or
        stat.S_IMODE(info.st_mode) != 0o600 or info.st_nlink != 1 or info.st_size != 0):
      raise conflict("work_unsafe_mutex")
    until = time.monotonic() + min(10, deadline.remaining(10))
    while True:
      try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
      except BlockingIOError:
        if time.monotonic() >= until:
          raise conflict("work_mutex_timeout") from None
        time.sleep(min(0.01, deadline.remaining(0.01)))
    yield
  except TermcfgError:
    raise
  except PathError:
    raise conflict("work_unsafe_mutex") from None
  except OSError as error:
    code = 4 if error.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES) else 6
    raise TermcfgError(code, "work_mutex_failed", "work enter PATH") from None
  finally:
    # 不unlink：别的调用者可能仍持有同一inode。
    if lock is not None:
      os.close(lock)
    if directory is not None:
      os.close(directory)


def info(result, entity):
  value = result.get(entity, result)
  if not isinstance(value, dict):
    raise TermcfgError(5, "work_invalid_native_response", "work --help")
  return value


def tokens(value):
  result = value.get("tokens", {})
  if not isinstance(result, dict) or any(not isinstance(k, str) or not isinstance(v, str)
      for k, v in result.items()):
    raise TermcfgError(5, "work_invalid_native_tokens", "work --help")
  return result


def report_tokens(client, entity, identifier, patch, *, source=SOURCE):
  global _last_sequence
  if (entity not in ("workspace", "pane") or not isinstance(patch, dict) or
      not patch or len(patch) > 16):
    raise TermcfgError(2, "work_invalid_metadata", "work --help")
  for key, value in patch.items():
    if (not re.fullmatch(r"[A-Za-z0-9_]{1,32}", key) or
        (value is not None and (not isinstance(value, str) or not value or len(value) > 80 or
          not value.isascii() or value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value)))):
      raise TermcfgError(2, "work_invalid_metadata", "work --help")
  id_key = entity + "_id"
  current = tokens(info(client.request(entity + ".get", {id_key: identifier}), entity))
  merged = dict(current)
  for key, value in patch.items():
    if value is None: merged.pop(key, None)
    else: merged[key] = value
  if len(merged) > 32:
    raise conflict("work_metadata_capacity")
  _last_sequence = max(time.monotonic_ns(), _last_sequence + 1)
  client.request(entity + ".report_metadata", {id_key: identifier, "source": source,
    "tokens": patch, "seq": _last_sequence})
  observed = tokens(info(client.request(entity + ".get", {id_key: identifier}), entity))
  if any(observed.get(key) != value for key, value in patch.items()):
    raise conflict("work_metadata_not_confirmed")


def canonical_checkout(path, deadline):
  try:
    path = Path(literal(str(path))).resolve(strict=True)
    if not path.is_dir():
      raise ValueError()
    result = subprocess.run(["git", "-C", str(path), "rev-parse", "--show-toplevel"],
      cwd=path, env=dict(os.environ), capture_output=True, text=True,
      timeout=deadline.remaining(5), check=False)
    if result.returncode or not result.stdout.endswith("\n"):
      raise ValueError()
    root = Path(literal(result.stdout[:-1])).resolve(strict=True)
    if not root.is_absolute() or not root.is_dir():
      raise ValueError()
    return root
  except FileNotFoundError:
    raise TermcfgError(2, "work_git_directory_required", "use a native temporary workspace") from None
  except (ValueError, OSError, subprocess.SubprocessError):
    raise TermcfgError(2, "work_git_directory_required", "use a native temporary workspace") from None


def project_digest(root):
  return hashlib.sha256(str(root).encode("utf-8")).hexdigest()


def _checkout(workspace):
  try:
    return Path(literal(workspace["worktree"]["checkout_path"])).resolve(strict=True)
  except (OSError, ValueError, KeyError, TypeError, TermcfgError):
    raise conflict("work_project_provenance_unknown") from None


def _workspace(client, identifier):
  return info(client.request("workspace.get", {"workspace_id": identifier}), "workspace")


def _panes(client):
  return client.request("pane.list", {}).get("panes", [])


def _project_matches(client, root):
  values = client.request("workspace.list", {})["workspaces"]
  matches = [value for value in values if value.get("worktree") and _checkout(value) == root]
  if len(matches) > 1:
    raise conflict("work_duplicate_native_projects")
  return matches


def _identity(workspace, root):
  current = tokens(workspace)
  if (_checkout(workspace) != root or current.get("rw_project") != project_digest(root) or
      not re.fullmatch(r"[a-f0-9]{32}", current.get("rw_epoch", ""))):
    raise conflict("work_project_identity_unknown")
  return current


def _role_token(op, pane_id):
  value = "p:" + op + ":" + pane_id
  if len(value) > 80:
    raise conflict("work_native_identifier_too_long")
  return value


def _owned(pane, state, role, op, kind):
  value = tokens(pane)
  return all(value.get(k) == v for k, v in {"rw_project": state["rw_project"],
    "rw_epoch": state["rw_epoch"], "rw_role": role, "rw_op": op, "rw_kind": kind}.items())


def _reconcile_pending(client, workspace, root):
  state = _identity(workspace, root)
  pending = state.get("rw_pending")
  if not pending:
    return workspace
  match = re.fullmatch(r"(shell|edit|build|debug|pi|codex|dsh):([a-f0-9]{32}):(primary|extra)", pending)
  if not match:
    raise conflict("work_pending_unknown")
  role, op, kind = match.groups()
  found = [p for p in _panes(client) if _owned(p, state, role, op, kind)]
  if len(found) != 1 or found[0]["workspace_id"] != workspace["workspace_id"]:
    raise conflict("work_pending_unknown")
  pane, patch = found[0], {"rw_pending": None}
  value = tokens(pane)
  if value.get("rw_phase") == "failed" and value.get("rw_commit") is None:
    pass
  elif value.get("rw_phase") == "accepted" and value.get("rw_commit") == op:
    if kind == "primary":
      previous = state.get("rw_" + role, "unknown")
      registered = _role_token(op, pane["pane_id"])
      if previous not in ("unknown", "absent", registered):
        raise conflict("work_primary_conflict")
      patch["rw_" + role] = registered
  else:
    raise conflict("work_pending_unknown")
  report_tokens(client, "workspace", workspace["workspace_id"], patch)
  return _workspace(client, workspace["workspace_id"])


def enter_project(client, root):
  root = Path(root).resolve(strict=True)
  found = _project_matches(client, root)
  created = None
  if not found:
    # 0.9.5只允许从仓库主工作区发起open；linked checkout仍是目标身份。
    listing = client.request("worktree.list", {"cwd": str(root)})
    try:
      source = Path(literal(listing["source"]["repo_root"])).resolve(strict=True)
      targets = [item for item in listing["worktrees"]
        if Path(literal(item["path"])).resolve() == root]
      if not source.is_dir() or len(targets) != 1:
        raise ValueError()
    except (OSError, KeyError, ValueError, TypeError, TermcfgError):
      raise conflict("work_native_source_unknown") from None
    try:
      created = client.request("worktree.open", {"cwd": str(source), "path": str(root), "focus": False})
    except TermcfgError as error:
      if error.code != 4:
        raise
      found = _project_matches(client, root)
      if not found:
        raise conflict("work_create_result_unknown") from None
    else:
      found = _project_matches(client, root)
      if (len(found) != 1 or created["workspace"]["workspace_id"] != found[0]["workspace_id"]):
        raise conflict("work_create_result_unknown")
  workspace = found[0]
  state = tokens(workspace)
  if "rw_epoch" not in state:
    epoch = uuid.uuid4().hex
    confirmed_new = created is not None and created["already_open"] is False
    patch = {"rw_project": project_digest(root), "rw_epoch": epoch,
      **{"rw_" + role: "absent" if confirmed_new else "unknown" for role in ROLES}}
    if confirmed_new:
      pane = created["root_pane"]
      if pane["workspace_id"] != workspace["workspace_id"]:
        raise conflict("work_new_pane_mismatch")
      op = uuid.uuid4().hex
      report_tokens(client, "pane", pane["pane_id"], {"rw_project": patch["rw_project"],
        "rw_epoch": epoch, "rw_role": "shell", "rw_op": op, "rw_kind": "primary",
        "rw_commit": op, "rw_phase": "accepted"})
      patch["rw_shell"] = _role_token(op, pane["pane_id"])
    report_tokens(client, "workspace", workspace["workspace_id"], patch)
    workspace = _workspace(client, workspace["workspace_id"])
  _identity(workspace, root)
  workspace = _reconcile_pending(client, workspace, root)
  client.request("workspace.focus", {"workspace_id": workspace["workspace_id"]})
  return workspace


def _primary(client, workspace, root, role):
  state = _identity(workspace, root)
  value = state.get("rw_" + role, "unknown")
  if value in ("unknown", "absent"):
    return value, None
  match = re.fullmatch(r"p:([a-f0-9]{32}):(.+)", value)
  if not match:
    raise conflict("work_role_identity_unknown")
  op, locator = match.groups()
  panes = _panes(client)
  located = [p for p in panes if p["pane_id"] == locator]
  owned = [p for p in panes if _owned(p, state, role, op, "primary")]
  if len(owned) > 1 or len(located) > 1:
    raise conflict("work_multiple_primary")
  if not located:
    if len(owned) == 1 and owned[0]["workspace_id"] == workspace["workspace_id"]:
      pane = owned[0]
      report_tokens(client, "workspace", workspace["workspace_id"],
        {"rw_" + role: _role_token(op, pane["pane_id"])})
    else:
      report_tokens(client, "workspace", workspace["workspace_id"], {"rw_" + role: "absent"})
      return "absent", None
  else:
    pane = located[0]
    if len(owned) == 1 and owned[0]["workspace_id"] != workspace["workspace_id"]:
      report_tokens(client, "workspace", workspace["workspace_id"], {"rw_" + role: "absent"})
      return "absent", None
  if not _owned(pane, state, role, op, "primary") or pane["workspace_id"] != workspace["workspace_id"]:
    raise conflict("work_primary_identity_changed")
  if tokens(pane).get("rw_phase") != "accepted" or tokens(pane).get("rw_commit") != op:
    report_tokens(client, "workspace", workspace["workspace_id"], {"rw_" + role: "unknown"})
    return "unknown", None
  return "primary", pane


def _focus(client, pane, workspace_id, expected_tokens=None):
  current = info(client.request("pane.get", {"pane_id": pane["pane_id"]}), "pane")
  if (current["workspace_id"] != workspace_id or current["terminal_id"] != pane["terminal_id"] or
      (expected_tokens is not None and any(tokens(current).get(k) != v for k, v in expected_tokens.items()
        if k.startswith("rw_")))):
    raise conflict("work_target_changed")
  client.request("workspace.focus", {"workspace_id": workspace_id})
  client.request("tab.focus", {"tab_id": current["tab_id"]})
  client.request("pane.focus", {"pane_id": current["pane_id"]})
  after = info(client.request("pane.get", {"pane_id": current["pane_id"]}), "pane")
  if (after["workspace_id"] != workspace_id or after["terminal_id"] != current["terminal_id"] or
      any(tokens(after).get(k) != v for k, v in tokens(current).items() if k.startswith("rw_"))):
    raise conflict("work_target_changed")
  return after


def source_digest(root=ROOT):
  digest = hashlib.sha256()
  for name in ("work", "rotom-work-shell", "src/termcfg/work.py", "src/termcfg/work_shell.py",
      "src/termcfg/work_config.py", "src/termcfg/herdr.py", "schemas/local.schema.json"):
    digest.update(name.encode() + b"\0")
    digest.update((Path(root) / name).read_bytes())
    digest.update(b"\0")
  return digest.hexdigest()


def _wait_launch(client, workspace_id, state, role, op, kind, phase):
  while True:
    try:
      client.deadline.remaining()
      live = tokens(_workspace(client, workspace_id))
      if any(live.get(key) != state.get(key) for key in ("rw_project", "rw_epoch", "rw_pending")):
        raise conflict("work_launch_identity_changed")
      matches = [p for p in _panes(client) if _owned(p, state, role, op, kind)]
      if len(matches) > 1:
        raise conflict("work_launch_ambiguous")
      if matches:
        pane = matches[0]
        marker = tokens(pane)
        if pane["workspace_id"] != workspace_id or marker.get("rw_phase") == "failed":
          raise conflict("work_launch_failed")
        if marker.get("rw_phase") == phase and (phase != "accepted" or marker.get("rw_commit") == op):
          return pane
      time.sleep(client.deadline.remaining(0.02))
    except TermcfgError as error:
      if error.code == 4:
        raise
      raise conflict("work_launch_result_unknown") from None


def open_role(client, settings, role, *, new=False, caller_id=None):
  if role not in ROLES:
    raise TermcfgError(2, "work_invalid_role", "work --help")
  if not caller_id:
    raise conflict()
  try:
    caller = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane")
  except (KeyError, TermcfgError):
    raise conflict() from None
  workspace = _workspace(client, caller["workspace_id"])
  root = _checkout(workspace)
  state = _identity(workspace, root)
  status, primary = _primary(client, workspace, root, role)
  def check_caller():
    current = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane")
    live_state = _identity(_workspace(client, workspace["workspace_id"]), root)
    if (current["workspace_id"] != workspace["workspace_id"] or
        current["terminal_id"] != caller["terminal_id"] or
        any(live_state.get(k) != state.get(k) for k in ("rw_project", "rw_epoch"))):
      raise conflict("work_caller_changed")
  if primary is not None and not new:
    check_caller()
    focused = _focus(client, primary, workspace["workspace_id"], tokens(primary))
    check_caller()
    return focused
  workspace = _workspace(client, workspace["workspace_id"])
  state = _identity(workspace, root)
  if state.get("rw_pending"):
    raise conflict("work_pending_requires_reconciliation")
  if status == "unknown" and not new:
    raise conflict("work_role_unknown_use_explicit_new")
  # 准备失败在创建之前报告；不读取受管Agent的凭据。
  prepare_tool(settings, role, root)
  check_caller()
  op, kind = uuid.uuid4().hex, "extra" if primary is not None else "primary"
  pending = role + ":" + op + ":" + kind
  payload = {"version": 1, "role": role, "kind": kind, "op": op, "epoch": state["rw_epoch"],
    "project_digest": state["rw_project"], "checkout": str(root), "workspace_id": workspace["workspace_id"],
    "local": str(settings.local_path), "session": settings.session, "socket_path": client.socket_path,
    "endpoint_dev": client.identity[0], "endpoint_ino": client.identity[1], "rotom_root": str(settings.repo_root),
    "source_digest": source_digest(settings.repo_root), "selection_digest": settings.selection_digest,
    "expires_at_ns": int(client.deadline.expires_at * 1_000_000_000)}
  encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
  if len(encoded.encode()) > 16384:
    raise TermcfgError(2, "work_launch_payload_too_large", "work --help")
  report_tokens(client, "workspace", workspace["workspace_id"], {"rw_pending": pending})
  state = {**state, "rw_pending": pending}
  try:
    client.request("tab.create", {"workspace_id": workspace["workspace_id"], "cwd": str(root),
      "label": role, "focus": False, "env": {PAYLOAD_ENV: encoded}})
  except TermcfgError as error:
    if error.code != 4:
      raise
    # 超时不重发；只按唯一op的原生事实对账。
  pane = _wait_launch(client, workspace["workspace_id"], state, role, op, kind, "ready")
  check_caller()
  report_tokens(client, "pane", pane["pane_id"], {"rw_commit": op})
  pane = _wait_launch(client, workspace["workspace_id"], state, role, op, kind, "accepted")
  patch = {"rw_pending": None}
  if kind == "primary":
    patch["rw_" + role] = _role_token(op, pane["pane_id"])
  report_tokens(client, "workspace", workspace["workspace_id"], patch)
  focused = _focus(client, pane, workspace["workspace_id"], tokens(pane))
  check_caller()
  return focused


def _caller_scope(settings, socket_path=None):
  pane_id = os.environ.get("HERDR_PANE_ID")
  environment_socket = os.environ.get("HERDR_SOCKET_PATH")
  if not pane_id or not environment_socket or (os.environ.get("HERDR_SESSION") not in (None, settings.session)):
    raise conflict()
  if socket_path is not None and Path(environment_socket) != Path(socket_path):
    raise conflict("work_other_server_context")
  return literal(pane_id)


@contextmanager
def connected(settings, deadline, *, start):
  from .herdr import discover, verify_schema, start_headless, HerdrClient
  from .work_config import prepared_config, validate_native_config, resolve_executable
  prepared_config()
  binary = resolve_executable(settings.herdr_binary)
  resolve_executable(str(settings.repo_root / "rotom-work-shell"))
  if not (settings.repo_root / ".venv/bin/python").is_file():
    raise TermcfgError(5, "work_environment_not_prepared", "uv sync --locked")
  verify_schema(binary, deadline)
  session = discover(binary, settings.session, deadline)
  if session is None:
    if not start:
      raise conflict("work_server_not_running")
    validate_native_config(binary, deadline)
    start_headless(binary, settings.session, deadline, settings.repo_root)
    while session is None:
      time.sleep(deadline.remaining(0.02))
      session = discover(binary, settings.session, deadline)
  if os.environ.get("HERDR_PANE_ID"):
    _caller_scope(settings, session["socket_path"])
  client = HerdrClient(session["socket_path"], deadline)
  try:
    while True:
      try:
        client.request("ping", {})
        break
      except TermcfgError as error:
        if not start or error.code == 4 or deadline.expired:
          raise
        time.sleep(deadline.remaining(0.02))
    yield client, binary
  finally:
    client.close()


def main(argv=None):
  import argparse
  from .herdr import Deadline
  from .work_config import read_settings
  class Parser(argparse.ArgumentParser):
    def error(self, message):
      raise TermcfgError(2, "work_invalid_arguments", "work --help")
  parser = Parser(prog="work", description="显式选择项目，并按用途聚焦原生终端")
  selectors = parser.add_mutually_exclusive_group()
  selectors.add_argument("--machine")
  selectors.add_argument("--local")
  commands = parser.add_subparsers(dest="command", required=True)
  commands.add_parser("enter").add_argument("path")
  opening = commands.add_parser("open")
  opening.add_argument("role", choices=ROLES)
  opening.add_argument("--new", action="store_true")
  try:
    args = parser.parse_args(argv)
    if args.command == "open" and (not os.environ.get("HERDR_PANE_ID") or not os.environ.get("HERDR_SOCKET_PATH")):
      raise conflict()
    deadline = Deadline(timeout=operation_timeout(args.role if args.command == "open" else None))
    # 非Git在任何native发现/启动之前失败。
    root = canonical_checkout(args.path, deadline) if args.command == "enter" else None
    settings = read_settings(machine=args.machine, local=args.local)
    inside = bool(os.environ.get("HERDR_PANE_ID"))
    if os.environ.get("TMUX") and not inside:
      raise conflict("work_leave_tmux_use_plain_ssh")
    if inside:
      _caller_scope(settings)
    with operation_lock(deadline):
      with connected(settings, deadline, start=args.command == "enter" and not inside) as (client, binary):
        if args.command == "open":
          open_role(client, settings, args.role, new=args.new, caller_id=_caller_scope(settings, client.socket_path))
          print("work_open: " + args.role)
          return 0
        enter_project(client, root)
        if inside:
          print("work_enter: focused")
          return 0
        current = os.lstat(client.socket_path)
        if (current.st_dev, current.st_ino) != client.identity:
          raise conflict("work_server_changed_before_attach")
    # 释放管理锁后原生交互不受管理deadline影响，也不杀server。
    environment = dict(os.environ)
    environment.pop(PAYLOAD_ENV, None)
    os.execvpe(binary, [binary, "session", "attach", settings.session], environment)
    return 0
  except SystemExit as error:
    return int(error.code)
  except TermcfgError as error:
    print(error.reason + ": " + error.next_command, file=sys.stderr)
    return error.code
  except (OSError, ValueError):
    print("work_filesystem_or_runtime_failed: work --help", file=sys.stderr)
    return 6
