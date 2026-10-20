"""原生新pane的shell回退；有意图时由一次性握手准入。"""

import os
from pathlib import Path
import json
import re
import sys
import time

from .errors import TermcfgError
from .work_config import ROOT, ROLES, PAYLOAD_ENV, resolve_executable, read_settings, prepare_tool, operation_timeout


def parse_payload(text):
  def unique(pairs):
    result = {}
    for key, value in pairs:
      if key in result:
        raise ValueError()
      result[key] = value
    return result
  try:
    if not isinstance(text, str) or len(text.encode("utf-8")) > 16384:
      raise ValueError()
    value = json.loads(text, object_pairs_hook=unique,
      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    required = {"version", "role", "kind", "op", "epoch", "project_digest", "checkout", "workspace_id",
      "session", "socket_path", "endpoint_dev", "endpoint_ino", "rotom_root", "source_digest",
      "selection_digest", "expires_at_ns"}
    if (not isinstance(value, dict) or not required <= value.keys() or
        value.keys() - required - {"machine", "local"} or len(value.keys() & {"machine", "local"}) != 1):
      raise ValueError()
    if type(value["version"]) is not int or value["version"] != 1 or value["role"] not in ROLES or value["kind"] not in ("primary", "extra"):
      raise ValueError()
    for key in ("op", "epoch", "project_digest", "source_digest", "selection_digest"):
      length = 32 if key in ("op", "epoch") else 64
      if not isinstance(value[key], str) or not re.fullmatch("[a-f0-9]{" + str(length) + "}", value[key]):
        raise ValueError()
    for key, item in value.items():
      if key in ("version", "endpoint_dev", "endpoint_ino", "expires_at_ns"):
        if type(item) is not int or item < (1 if key == "expires_at_ns" else 0):
          raise ValueError()
      elif not isinstance(item, str) or not item or any(ord(c) < 32 or ord(c) == 127 for c in item):
        raise ValueError()
    now = time.monotonic_ns()
    if not now < value["expires_at_ns"] <= now + operation_timeout(value["role"]) * 1_000_000_000:
      raise ValueError()
    for key in ("checkout", "rotom_root", "socket_path", "local"):
      if key in value and (not Path(value[key]).is_absolute() or ".." in Path(value[key]).parts):
        raise ValueError()
    return value
  except (ValueError, TypeError, UnicodeError):
    raise TermcfgError(2, "work_launch_payload_invalid", "work enter PATH") from None


def launch_payload(text, *, client=None, settings=None, execute=None):
  from .herdr import HerdrClient, Deadline
  from .work import info, tokens, report_tokens, source_digest, project_digest, LAUNCH_SOURCE
  value = parse_payload(text)
  remaining = (value["expires_at_ns"] - time.monotonic_ns()) / 1_000_000_000
  deadline = Deadline(timeout=max(0, min(operation_timeout(value["role"]), remaining)))
  deadline.expires_at = min(deadline.expires_at, value["expires_at_ns"] / 1_000_000_000)
  owned_client = False
  pane_id = None
  terminal_id = None
  marked = accepted = False
  try:
    root = Path(value["checkout"]).resolve(strict=True)
    if (str(root) != value["checkout"] or not root.is_dir() or root == Path("/") or
        Path(value["rotom_root"]) != ROOT or source_digest() != value["source_digest"] or
        project_digest(root) != value["project_digest"]):
      raise TermcfgError(4, "work_launch_source_changed", "work enter PATH")
    settings = settings or read_settings(machine=value.get("machine"), local=value.get("local"))
    if settings.selection_digest != value["selection_digest"] or settings.session != value["session"]:
      raise TermcfgError(4, "work_launch_selection_changed", "work enter PATH")
    command = prepare_tool(settings, value["role"], root)
    pane_id = os.environ.get("HERDR_PANE_ID")
    if not pane_id:
      raise TermcfgError(4, "work_launch_caller_unknown", "work enter PATH")
    if client is None:
      client = HerdrClient(value["socket_path"], deadline,
        expected_identity=(value["endpoint_dev"], value["endpoint_ino"]))
      owned_client = True
    elif client.identity != (value["endpoint_dev"], value["endpoint_ino"]):
      raise TermcfgError(4, "work_launch_endpoint_changed", "work enter PATH")
    client.request("ping", {})
    pending = value["role"] + ":" + value["op"] + ":" + value["kind"]
    def validate():
      deadline.remaining()
      caller = info(client.request("pane.current", {"caller_pane_id": pane_id}), "pane")
      workspace = info(client.request("workspace.get", {"workspace_id": value["workspace_id"]}), "workspace")
      state = tokens(workspace)
      if (caller["workspace_id"] != value["workspace_id"] or
          (terminal_id is not None and caller["terminal_id"] != terminal_id) or
          state.get("rw_epoch") != value["epoch"] or state.get("rw_project") != value["project_digest"] or
          state.get("rw_pending") != pending or
          workspace.get("worktree", {}).get("checkout_path") != str(root)):
        raise TermcfgError(4, "work_launch_identity_changed", "work enter PATH")
      return caller
    initial = validate()
    terminal_id = initial["terminal_id"]
    if tokens(initial).get("rw_op") is not None:
      raise TermcfgError(4, "work_launch_already_consumed", "work enter PATH")
    report_tokens(client, "pane", pane_id, {"rw_project": value["project_digest"],
      "rw_epoch": value["epoch"], "rw_role": value["role"], "rw_op": value["op"],
      "rw_kind": value["kind"], "rw_phase": "ready"}, source=LAUNCH_SOURCE)
    marked = True
    while True:
      caller = validate()
      state = tokens(caller)
      if any(state.get(key) != expected for key, expected in {
          "rw_project": value["project_digest"], "rw_epoch": value["epoch"], "rw_role": value["role"],
          "rw_op": value["op"], "rw_kind": value["kind"], "rw_phase": "ready"}.items()):
        raise TermcfgError(4, "work_launch_identity_changed", "work enter PATH")
      if state.get("rw_commit") == value["op"]:
        break
      if state.get("rw_commit") is not None or state.get("rw_phase") != "ready":
        raise TermcfgError(4, "work_launch_commit_mismatch", "work enter PATH")
      time.sleep(deadline.remaining(0.02))
    validate()
    # accepted请求可能已经应用但丢响应；失败上报不明时不能回退成伪有效普通shell。
    accepted = True
    report_tokens(client, "pane", pane_id, {"rw_phase": "accepted"}, source=LAUNCH_SOURCE)
    deadline.remaining()
    environment = dict(os.environ)
    environment.pop(PAYLOAD_ENV, None)
    os.environ.pop(PAYLOAD_ENV, None)
    os.chdir(root)
    try:
      (execute or os.execvpe)(command[0], command, environment)
    except OSError:
      raise TermcfgError(5, "work_launch_exec_failed", "work enter PATH") from None
    return 0
  except (TermcfgError, OSError, KeyError, ValueError) as error:
    failure = error if isinstance(error, TermcfgError) else TermcfgError(5, "work_launch_failed", "work enter PATH")
    failure.fallback_safe = not accepted
    if marked and client is not None:
      try:
        # 单独有界的失败上报不会重启任务；无法撤销accepted时不留下伪有效shell。
        client.deadline = Deadline(timeout=2)
        report_tokens(client, "pane", pane_id, {"rw_phase": "failed", "rw_commit": None,
          "rw_error": "work_launch_failed"}, source=LAUNCH_SOURCE)
        failure.fallback_safe = True
      except TermcfgError:
        pass
    raise failure from None
  finally:
    if owned_client:
      client.close()


def fallback_shell():
  value = os.environ.get("SHELL") or "/bin/sh"
  if Path(value).resolve() == (ROOT / "rotom-work-shell").resolve():
    raise TermcfgError(2, "work_recursive_shell", "work --help")
  executable = resolve_executable(value)
  env = dict(os.environ)
  env.pop(PAYLOAD_ENV, None)
  os.execvpe(executable, [executable], env)
  return 0


def main():
  payload = os.environ.pop(PAYLOAD_ENV, None)
  if payload is not None:
    try:
      return launch_payload(payload)
    except TermcfgError as error:
      print(error.reason + ": work enter PATH", file=sys.stderr)
      if not getattr(error, "fallback_safe", True):
        return error.code
  try:
    return fallback_shell()
  except (TermcfgError, OSError) as error:
    print("work_launch_shell_failed", file=sys.stderr)
    return error.code if isinstance(error, TermcfgError) else 5
