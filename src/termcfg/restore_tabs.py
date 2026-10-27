"""维护恢复专用的一次新 tab transport；不承载任意命令。"""
import json
import os
from pathlib import Path
import re
import time

from agentcfg.storage import Conflict, StateError
from agentcfg.paths import PathError
from agentcfg.schema import ConfigError
from agentcfg.secrets import CredentialError
from agentcfg.sessions import SessionError

from .errors import TermcfgError
from .herdr import Deadline, HerdrClient, SUPPORTED_PROTOCOLS, require_startup_evidence
from .work import info, tokens, report_tokens, source_digest, conflict
from .work_config import ROOT, literal, resolve_executable

PAYLOAD_ENV = "ROTOM_RESTORE_LAUNCH_V1"
SOURCE = "rotom-restore-v1"


def request_digest(request):
  from agentcfg.restore_locations import request_digest as digest
  return digest(request)


def parse_payload(text):
  def unique(pairs):
    value = {}
    for key, item in pairs:
      if key in value:
        raise ValueError()
      value[key] = item
    return value
  try:
    if not isinstance(text, str) or len(text.encode()) > 8192:
      raise ValueError()
    value = json.loads(text, object_pairs_hook=unique,
      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if not isinstance(value, dict) or value.keys() != {"version", "request_path", "request_digest",
        "socket_path", "endpoint_dev", "endpoint_ino", "source_digest", "rotom_root", "expires_at_ns"}:
      raise ValueError()
    if type(value["version"]) is not int or value["version"] != 1:
      raise ValueError()
    for key in ("endpoint_dev", "endpoint_ino", "expires_at_ns"):
      if type(value[key]) is not int or value[key] < 0:
        raise ValueError()
    for key in ("source_digest", "request_digest"):
      if not isinstance(value[key], str) or not re.fullmatch("[a-f0-9]{64}", value[key]):
        raise ValueError()
    for key in ("socket_path", "request_path", "rotom_root"):
      path = literal(value[key])
      if not Path(path).is_absolute() or str(Path(path)) != path or ".." in Path(path).parts:
        raise ValueError()
    now = time.monotonic_ns()
    if not now < value["expires_at_ns"] <= now + 60_000_000_000:
      raise ValueError()
    if Path(value["request_path"]).name != "request.json":
      raise ValueError()
    return value
  except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, TermcfgError):
    raise TermcfgError(2, "restore_launch_payload_invalid", "rotom tools") from None


def _store(root):
  from agentcfg.restore_locations import LocationStore
  try:
    return LocationStore(root)
  except Conflict:
    raise conflict("restore_launch_location_conflict") from None


def _read(store, name):
  try:
    value = getattr(store, name)()
    if value is None:
      raise Conflict("restore location unavailable")
    return value
  except Conflict:
    raise conflict("restore_launch_location_conflict") from None


def _transition(store, receipt, phase, **patch):
  try:
    return store.transition(receipt, {**receipt, "phase": phase, **patch})
  except Conflict:
    raise conflict("restore_launch_location_conflict") from None


def _reference(client, pane, cwd):
  return {"socket_path": client.socket_path, "server_identity": list(client.identity),
    **{key: pane[key] for key in ("workspace_id", "tab_id", "pane_id", "terminal_id")}, "cwd": cwd}


def _check_source(request, value):
  if (value["rotom_root"] != str(ROOT) or request["rotom_root"] != str(ROOT)
      or source_digest() != value["source_digest"] or request_digest(request) != value["request_digest"]
      or request["manager_code_identity"] != value["source_digest"]
      or request["mode"] != "new-tab"):
    raise conflict("restore_launch_source_changed")


def _marker(request, value):
  return {"rr_request": request["request_id"], "rr_source": value["source_digest"]}


def _matches(client, marker):
  return [pane for pane in client.request("pane.list", {})["panes"]
    if all(tokens(pane).get(key) == val for key, val in marker.items())]


def create_restore_tab(client, settings, store, *, workspace_id, caller_id=None, label="恢复会话"):
  """先持久化 dispatched，再单次创建；丢失响应只读协调。"""
  request = _read(store, "read_request")
  receipt = _read(store, "read_receipt")
  if request["mode"] != "new-tab" or receipt["phase"] != "prepared":
    raise conflict("restore_launch_already_consumed")
  value = {"version": 1, "request_path": str(store.root / "request.json"),
    "request_digest": request_digest(request), "socket_path": client.socket_path,
    "endpoint_dev": client.identity[0], "endpoint_ino": client.identity[1],
    "source_digest": source_digest(), "rotom_root": str(ROOT),
    "expires_at_ns": min(int(client.deadline.expires_at * 1_000_000_000), time.monotonic_ns() + 60_000_000_000)}
  encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
  parse_payload(encoded)
  _check_source(request, value)
  if settings.repo_root != ROOT:
    raise conflict("restore_launch_source_changed")
  require_startup_evidence(client, settings, resolve_executable(settings.herdr_binary))
  caller = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane") if caller_id else None
  if caller is not None and caller["workspace_id"] != workspace_id:
    raise conflict("restore_launch_caller_changed")
  def scope():
    client.deadline.remaining()
    if (client.socket_path != value["socket_path"]
        or client.identity != (value["endpoint_dev"], value["endpoint_ino"])):
      raise conflict("restore_launch_endpoint_changed")
    workspace = info(client.request("workspace.get", {"workspace_id": workspace_id}), "workspace")
    if workspace["workspace_id"] != workspace_id:
      raise conflict("restore_launch_workspace_changed")
    if caller is not None:
      current = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane")
      if any(current[key] != caller[key] for key in ("workspace_id", "tab_id", "pane_id", "terminal_id")):
        raise conflict("restore_launch_caller_changed")
  scope()
  receipt = _transition(store, receipt, "dispatched")
  marker = _marker(request, value)
  reference = None
  try:
    try:
      result = client.request("tab.create", {"workspace_id": workspace_id, "cwd": request["cwd"],
        "label": literal(label), "focus": False, "env": {PAYLOAD_ENV: encoded}})
      reference = _reference(client, result["root_pane"], request["cwd"])
      if (result["tab"]["tab_id"] != reference["tab_id"]
          or result["tab"]["workspace_id"] != workspace_id or reference["workspace_id"] != workspace_id):
        raise conflict("restore_launch_identity_changed")
    except TermcfgError as error:
      if error.code != 4:
        raise
    while True:
      scope()
      found = _matches(client, marker)
      if len(found) > 1:
        raise conflict("restore_launch_identity_changed")
      if found:
        if {key: val for key, val in tokens(found[0]).items() if key.startswith("rr_")} != marker:
          raise conflict("restore_launch_identity_changed")
        observed = _reference(client, found[0], request["cwd"])
        if observed["workspace_id"] != workspace_id or (reference is not None and observed != reference):
          raise conflict("restore_launch_identity_changed")
        reference = observed
      receipt = _read(store, "read_receipt")
      if receipt["phase"] == "ready" and reference is not None:
        if receipt["terminal_ref"] != reference:
          raise conflict("restore_launch_identity_changed")
        _check_source(_read(store, "read_request"), value)
        receipt = _transition(store, receipt, "committed")
      elif receipt["phase"] in ("handoff", "executing", "exited"):
        if reference is None or receipt["terminal_ref"] != reference:
          raise conflict("restore_launch_identity_changed")
        return {"created": True, "handoff": True, "request_id": request["request_id"],
          "terminal_ref": reference, "phase": receipt["phase"]}
      elif receipt["phase"] not in ("dispatched", "ready", "committed"):
        raise conflict("restore_launch_result_unknown")
      time.sleep(client.deadline.remaining(0.01))
  except (TermcfgError, OSError, KeyError, ValueError, Conflict):
    receipt = _read(store, "read_receipt")
    if receipt["phase"] in ("dispatched", "ready", "committed"):
      _transition(store, receipt, "unknown", reason="restore_launch_result_unknown")
    raise conflict("restore_launch_result_unknown") from None


def bootstrap_restore(text, *, client=None, execute=None):
  value = parse_payload(text)
  store = _store(Path(value["request_path"]).parent)
  request = _read(store, "read_request")
  _check_source(request, value)
  deadline = Deadline(max(0, (value["expires_at_ns"] - time.monotonic_ns()) / 1_000_000_000))
  deadline.expires_at = min(deadline.expires_at, value["expires_at_ns"] / 1_000_000_000)
  owned = client is None
  marked = False
  receipt = None
  try:
    if client is None:
      client = HerdrClient(value["socket_path"], deadline,
        expected_identity=(value["endpoint_dev"], value["endpoint_ino"]))
    if client.identity != (value["endpoint_dev"], value["endpoint_ino"]) or client.socket_path != value["socket_path"]:
      raise conflict("restore_launch_endpoint_changed")
    client.deadline = deadline
    if client.request("ping", {})["protocol"] not in SUPPORTED_PROTOCOLS:
      raise conflict("restore_launch_protocol_changed")
    caller = os.environ.get("HERDR_PANE_ID")
    if not caller:
      raise conflict("restore_launch_caller_unknown")
    pane = info(client.request("pane.current", {"caller_pane_id": caller}), "pane")
    reference = _reference(client, pane, request["cwd"])
    marker = _marker(request, value)
    if any(key.startswith("rr_") for key in tokens(pane)) or _matches(client, marker):
      raise conflict("restore_launch_already_consumed")
    receipt = _read(store, "read_receipt")
    if receipt["phase"] != "dispatched" or receipt["terminal_ref"] is not None:
      raise conflict("restore_launch_already_consumed")
    def scope():
      deadline.remaining()
      current = info(client.request("pane.current", {"caller_pane_id": caller}), "pane")
      workspace = info(client.request("workspace.get", {"workspace_id": pane["workspace_id"]}), "workspace")
      if (_reference(client, current, request["cwd"]) != reference
          or workspace["workspace_id"] != pane["workspace_id"]
          or (marked and {key: val for key, val in tokens(current).items() if key.startswith("rr_")} != marker)):
        raise conflict("restore_launch_identity_changed")
    scope()
    # CAS 先认领请求，阻止另一个 bootstrap 抢占同一不可变请求。
    receipt = _transition(store, receipt, "ready", terminal_ref=reference)
    marked = True
    report_tokens(client, "pane", pane["pane_id"], marker, source=SOURCE)
    while True:
      scope()
      receipt = _read(store, "read_receipt")
      if receipt["terminal_ref"] != reference:
        raise conflict("restore_launch_identity_changed")
      if receipt["phase"] == "committed":
        break
      if receipt["phase"] != "ready":
        raise conflict("restore_launch_commit_missing")
      time.sleep(deadline.remaining(0.01))
    _check_source(_read(store, "read_request"), value)
    scope()
    receipt = _transition(store, receipt, "handoff")
    environment = dict(os.environ)
    for name in list(environment):
      if name.startswith("ROTOM_") and "LAUNCH" in name:
        environment.pop(name, None)
        os.environ.pop(name, None)
    from rotom.pane_dispatch import child_command
    command = child_command(store)
    _check_source(_read(store, "read_request"), value)
    scope()
    os.chdir(request["cwd"])
    (execute or os.execvpe)(command[0], command, environment)
    return 0
  except (TermcfgError, StateError, PathError, ConfigError, CredentialError, SessionError, OSError, KeyError, ValueError) as error:
    code = error.code if isinstance(error, (TermcfgError, SessionError)) else getattr(error, "exit_code", 4)
    code = code if code in (2, 3, 5) else 4
    if marked:
      current = _read(store, "read_receipt")
      if current["phase"] in ("ready", "committed", "handoff") and current["terminal_ref"] == reference:
        _transition(store, current, "failed", reason="restore_launch_failed",
          exit_code=code if code in (2, 3, 5) else None)
    raise TermcfgError(code, "restore_launch_failed", "rotom resume --stopped --list") from None
  finally:
    if owned and client is not None:
      client.close()
