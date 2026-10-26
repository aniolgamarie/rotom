"""项目入口；锁只串行本入口，不声称跨native请求事务。"""

from contextlib import contextmanager
from copy import deepcopy
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
LAUNCH_FILES = ("work", "rotom-work-shell", "src/termcfg/work.py", "src/termcfg/work_shell.py",
  "src/termcfg/work_config.py", "src/termcfg/work_state.py", "src/termcfg/work_projects.py",
  "src/termcfg/work_edit.py", "src/termcfg/work_ui.py", "src/termcfg/work_git.py",
  "src/termcfg/herdr.py", "schemas/local.schema.json")


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
  if source in ("rotom-work-v2", "rotom-work-launch-v2"):
    allowed = ({"rw2_owner", "rw2_epoch", "rw2_model", "rw2_pending"} if entity == "workspace" else
      {"rw2_owner", "rw2_epoch", "rw2_type", "rw2_instance", "rw2_kind", "rw2_op", "rw2_phase", "rw2_commit"})
    if set(patch) - allowed:
      raise TermcfgError(2, "work_invalid_structured_metadata", "work --help")
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
  for name in LAUNCH_FILES:
    digest.update(name.encode() + b"\0")
    digest.update((Path(root) / name).read_bytes())
    digest.update(b"\0")
  return digest.hexdigest()


def _v2_workspace(client, binding, *, pending=None, allow_pending=False, unmarked=False):
  from .work_state import MODEL
  workspace = _workspace(client, binding["workspace_id"])
  marker = tokens(workspace)
  owned = {key: val for key, val in marker.items() if key.startswith("rw2_")}
  expected = {"rw2_owner": binding["owner"], "rw2_epoch": binding["epoch"], "rw2_model": MODEL}
  owners = [item for item in client.request("workspace.list", {})["workspaces"]
    if tokens(item).get("rw2_owner") == binding["owner"]]
  if workspace.get("worktree") is not None or any(key.startswith("rw_") for key in marker):
    raise conflict("work_structured_group_or_legacy_workspace")
  if unmarked and not owned and not owners:
    return workspace
  if (len(owners) != 1 or owners[0]["workspace_id"] != binding["workspace_id"]
      or any(owned.get(key) != val for key, val in expected.items())
      or set(owned) - {*expected, "rw2_pending"}):
    raise conflict("work_workspace_identity_unknown")
  current = owned.get("rw2_pending")
  if ((pending is not None and current != pending) or
      (pending is None and not allow_pending and current is not None) or
      (current is not None and not re.fullmatch(r"[a-f0-9]{32}", current))):
    raise conflict("work_pending_requires_reconciliation")
  return workspace


def _v2_markers(binding, type_key, instance, kind, op):
  return {"rw2_owner": binding["owner"], "rw2_epoch": binding["epoch"],
    "rw2_type": type_key, "rw2_instance": instance, "rw2_kind": kind, "rw2_op": op}


def _v2_matches(client, marker):
  return [pane for pane in _panes(client) if all(tokens(pane).get(key) == value for key, value in marker.items())]


def _v2_instance(client, binding, marker, reference, *, phase="accepted", strict_ids=True):
  matches = _v2_matches(client, marker)
  if len(matches) != 1:
    raise conflict("work_instance_identity_unknown")
  pane = info(client.request("pane.get", {"pane_id": matches[0]["pane_id"]}), "pane")
  owned = {key: val for key, val in tokens(pane).items() if key.startswith("rw2_")}
  required = {**marker, "rw2_phase": phase}
  if phase == "accepted":
    required["rw2_commit"] = marker["rw2_op"]
  if (owned != required or pane["workspace_id"] != binding["workspace_id"]
      or pane["terminal_id"] != reference["terminal_id"]
      or (strict_ids and any(pane[key] != reference[key]
        for key in ("workspace_id", "pane_id", "terminal_id", "tab_id")))):
    raise conflict("work_instance_identity_changed")
  return pane


def _v2_focus(client, binding, pane, marker):
  _v2_workspace(client, binding, allow_pending=True)
  current = _v2_instance(client, binding, marker, pane)
  client.request("workspace.focus", {"workspace_id": current["workspace_id"]})
  client.request("tab.focus", {"tab_id": current["tab_id"]})
  client.request("pane.focus", {"pane_id": current["pane_id"]})
  _v2_workspace(client, binding, allow_pending=True)
  return _v2_instance(client, binding, marker, current)


def _v2_wait(client, binding, marker, reference, phase):
  while True:
    try:
      client.deadline.remaining()
      matches = _v2_matches(client, marker)
      if len(matches) > 1:
        raise conflict("work_launch_ambiguous")
      if matches:
        pane = matches[0]
        observed = tokens(pane)
        if (any(pane[key] != reference[key] for key in ("workspace_id", "pane_id", "terminal_id", "tab_id"))
            or observed.get("rw2_phase") == "failed"):
          raise conflict("work_launch_identity_or_phase_changed")
        if observed.get("rw2_phase") == phase:
          return _v2_instance(client, binding, marker, reference, phase=phase)
        if phase == "ready" or observed.get("rw2_phase") != "ready":
          raise conflict("work_launch_phase_unknown")
      time.sleep(client.deadline.remaining(0.02))
    except TermcfgError as error:
      if error.code == 4:
        raise
      raise conflict("work_launch_result_unknown") from None


def finalize_instance_v2(client, state, op):
  """只对原意图的唯一 accepted 事实完成记账，绝不再次创建或提交执行。"""
  from .work_state import SOURCE as source
  intent, receipt = state.read_intent(op), state.read("receipts", op)
  fields = ("op", "owner", "epoch", "action", "type", "instance", "kind")
  if (intent is None or receipt is None or any(intent[key] != receipt[key] for key in fields)
      or receipt["phase"] not in ("commit-issued", "accepted", "completed")
      or any(receipt[key] is None for key in ("workspace_id", "pane_id", "terminal_id", "tab_id"))):
    raise conflict("work_original_operation_unproved")
  binding = deepcopy(intent["binding"])
  binding["workspace_id"] = receipt["workspace_id"]
  marker = _v2_markers(binding, receipt["type"], receipt["instance"], receipt["kind"], op)
  workspace = _v2_workspace(client, binding, allow_pending=True)
  if tokens(workspace).get("rw2_pending") not in (None, op):
    raise conflict("work_pending_requires_reconciliation")
  pane = _v2_instance(client, binding, marker, receipt)
  current = state.load_binding(binding["owner"])
  if current is not None:
    if any(current[key] != binding[key] for key in
        ("epoch", "context", "workspace_start", "captured_home", "workspace_id")):
      raise conflict("work_registration_identity_changed")
    binding = current
  item = binding["types"].get(receipt["type"])
  reviewed = intent["binding"]["types"][receipt["type"]]
  if item is None:
    item = deepcopy(reviewed)
    binding["types"][receipt["type"]] = item
  if any(item[key] != reviewed[key] for key in ("cwd", "captured_home", "launch", "digest")):
    raise conflict("work_registration_contract_changed")
  instance = {"op": op, "kind": receipt["kind"], **{key: pane[key]
    for key in ("workspace_id", "pane_id", "terminal_id", "tab_id")}}
  previous = item["instances"].get(receipt["instance"])
  if previous is not None and previous != instance:
    raise conflict("work_registration_instance_changed")
  if receipt["kind"] == "default":
    if item["default"] not in (None, receipt["instance"]):
      raise conflict("work_default_already_registered")
    item["default"] = receipt["instance"]
  if previous is None:
    item["instances"][receipt["instance"]] = instance
    item["sequence"] += 1
  if receipt["phase"] == "commit-issued":
    state.update_receipt(op, "accepted")
  state.save_binding(binding)
  if tokens(workspace).get("rw2_pending") == op:
    report_tokens(client, "workspace", binding["workspace_id"], {"rw2_pending": None}, source=source)
  _v2_workspace(client, binding, allow_pending=True)
  pane = _v2_instance(client, binding, marker, receipt)
  state.compact(op)
  return pane


def create_instance_v2(client, settings, state, binding, type_key, *, kind="default", label=None,
    caller_id=None, binary=None):
  """父调用持有 per-UID 生命周期锁；不获取配置锁，不重发任何创建。"""
  from .herdr import require_startup_evidence
  from .work_config import prepare_launch, resolve_executable, PAYLOAD_ENV_V2
  from .work_state import SOURCE as source, LAUNCH_SOURCE as launch_source, MODEL, digest
  from .work_shell import parse_payload_v2
  if kind not in ("default", "extra") or settings.model != MODEL:
    raise TermcfgError(2, "work_invalid_structured_launch", "work --help")
  binding = deepcopy(binding)
  if state.pending(binding["owner"]):
    raise conflict("work_pending_requires_reconciliation")
  initial = binding["workspace_id"] is None
  if initial:
    if kind != "default" or state.load_binding(binding["owner"]) is not None:
      raise conflict("work_context_already_bound")
    if (any(tokens(value).get("rw2_owner") == binding["owner"]
        for value in client.request("workspace.list", {})["workspaces"])
        or any(tokens(value).get("rw2_owner") == binding["owner"] for value in _panes(client))):
      raise conflict("work_live_owner_missing_private_binding")
  else:
    _v2_workspace(client, binding)
  try:
    item = binding["types"][type_key]
    definition = settings.structured["templates"][binding["template"]]["tab_types"][type_key]
  except (KeyError, TypeError):
    raise TermcfgError(2, "work_type_definition_required", "work --help") from None
  if kind == "default" and item["default"] is not None:
    raise conflict("work_default_already_registered")
  requested = prepare_launch(settings, definition, binding["workspace_start"], fixed=item)
  if any(requested[key] != item[key] for key in ("cwd", "captured_home", "launch", "digest")):
    raise conflict("work_type_configuration_drift")
  require_startup_evidence(client, settings, binary or resolve_executable(settings.herdr_binary))
  caller = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane") if caller_id else None
  def check_caller():
    if caller is not None:
      current = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane")
      if any(current[key] != caller[key] for key in ("workspace_id", "pane_id", "terminal_id")):
        raise conflict("work_caller_changed")
  op, instance = uuid.uuid4().hex, uuid.uuid4().hex
  action = "workspace-initial" if initial else "tab"
  value = {"version": 2, "action": action, "kind": kind, "op": op, "instance": instance,
    "epoch": binding["epoch"], "owner": binding["owner"], "context_kind": binding["context"]["kind"],
    "type": type_key, "workspace_start": binding["workspace_start"], "cwd": item["cwd"],
    "captured_home": item["captured_home"], "launch": item["launch"], "binding_digest": item["digest"],
    "local": str(settings.local_path), "session": settings.session, "socket_path": state.socket_path,
    "endpoint_dev": client.identity[0], "endpoint_ino": client.identity[1], "rotom_root": str(settings.repo_root),
    "source_digest": source_digest(settings.repo_root), "selection_digest": settings.selection_digest,
    "intent_path": str(state.root / "intents" / (op + ".json")),
    "expires_at_ns": int(client.deadline.expires_at * 1_000_000_000)}
  if not initial:
    value["workspace_id"] = binding["workspace_id"]
  encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
  parse_payload_v2(encoded)
  state.publish_intent(op, binding, action=action, payload_digest=digest(value),
    type_key=type_key, instance=instance, kind=kind)
  state.update_receipt(op, "dispatched")
  marker = _v2_markers(binding, type_key, instance, kind, op)
  if not initial:
    report_tokens(client, "workspace", binding["workspace_id"], {"rw2_pending": op}, source=source)
  purpose_label = literal(definition["label"])
  if kind == "extra":
    purpose_label += " " + str(item["sequence"] + 1)
  params = {"cwd": item["cwd"], "label": literal(label or purpose_label) if initial else purpose_label,
    "focus": False, "env": {PAYLOAD_ENV_V2: encoded}}
  if not initial:
    params["workspace_id"] = binding["workspace_id"]
  check_caller()
  response = None
  try:
    response = client.request("workspace.create" if initial else "tab.create", params)
  except TermcfgError as error:
    if error.code != 4:
      raise
  if response is None and initial:
    _v2_matches(client, marker)
    raise conflict("work_initial_create_birth_unknown")
  if response is not None:
    reference = response["root_pane"]
    tab = response["tab"]
    if (reference["tab_id"] != tab["tab_id"] or reference["workspace_id"] != tab["workspace_id"]):
      raise conflict("work_created_native_identity_unknown")
    if initial:
      workspace = response["workspace"]
      if (workspace["workspace_id"] != reference["workspace_id"] or workspace["active_tab_id"] != tab["tab_id"]
          or workspace.get("worktree") is not None or workspace["pane_count"] != 1 or workspace["tab_count"] != 1):
        raise conflict("work_created_workspace_unknown")
      binding["workspace_id"] = workspace["workspace_id"]
    elif reference["workspace_id"] != binding["workspace_id"]:
      raise conflict("work_created_native_identity_unknown")
  else:
    while True:
      try:
        client.deadline.remaining()
        found = _v2_matches(client, marker)
        if len(found) > 1 or (found and found[0]["workspace_id"] != binding["workspace_id"]):
          raise conflict("work_tab_create_result_unknown")
        if found:
          reference = found[0]
          break
        time.sleep(client.deadline.remaining(0.02))
      except TermcfgError:
        raise conflict("work_tab_create_result_unknown") from None
  pane = _v2_wait(client, binding, marker, reference, "ready")
  _v2_workspace(client, binding, pending=None if initial else op, unmarked=initial)
  check_caller()
  if initial:
    report_tokens(client, "workspace", binding["workspace_id"], {"rw2_owner": binding["owner"],
      "rw2_epoch": binding["epoch"], "rw2_model": MODEL, "rw2_pending": op}, source=source)
    try:
      client.request("tab.rename", {"tab_id": pane["tab_id"], "label": purpose_label})
    except TermcfgError as error:
      if error.code != 4:
        raise
    renamed = info(client.request("tab.get", {"tab_id": pane["tab_id"]}), "tab")
    if renamed["label"] != purpose_label or renamed["workspace_id"] != binding["workspace_id"]:
      raise conflict("work_initial_type_label_unknown")
  _v2_workspace(client, binding, pending=op)
  pane = _v2_instance(client, binding, marker, reference, phase="ready")
  if source_digest(settings.repo_root) != value["source_digest"]:
    raise conflict("work_launch_source_changed")
  state.update_receipt(op, "commit-issued", **{key: pane[key]
    for key in ("workspace_id", "pane_id", "terminal_id", "tab_id")})
  try:
    report_tokens(client, "pane", pane["pane_id"], {"rw2_commit": op}, source=launch_source)
  except TermcfgError as error:
    if error.code != 4:
      raise
  _v2_wait(client, binding, marker, reference, "accepted")
  check_caller()
  pane = finalize_instance_v2(client, state, op)
  focused = _v2_focus(client, state.load_binding(binding["owner"]), pane, marker)
  check_caller()
  return focused


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
  if socket_path is not None and Path(environment_socket).resolve() != Path(socket_path).resolve():
    raise conflict("work_other_server_context")
  return literal(pane_id)


@contextmanager
def connected(settings, deadline, *, start):
  from .herdr import (discover, verify_schema, start_headless, HerdrClient,
    native_inputs, observe_process, record_startup_evidence)
  from .work_config import prepared_config, validate_native_config, resolve_executable
  prepared_config()
  binary = resolve_executable(settings.herdr_binary)
  resolve_executable(str(settings.repo_root / "rotom-work-shell"))
  if not (settings.repo_root / ".venv/bin/python").is_file():
    raise TermcfgError(5, "work_environment_not_prepared", "uv sync --locked")
  structured = getattr(settings, "model", None) == "structured-v1"
  if structured:
    verify_schema(binary, deadline, structured=True)
  else:
    verify_schema(binary, deadline)
  inputs = owned_process = None
  session = discover(binary, settings.session, deadline)
  if session is None:
    if not start:
      raise conflict("work_server_not_running")
    validate_native_config(binary, deadline)
    if structured:
      inputs = native_inputs(settings, binary, deadline)
    started = start_headless(binary, settings.session, deadline, settings.repo_root)
    if structured:
      owned_process = observe_process(started.pid)
    while session is None:
      time.sleep(deadline.remaining(0.02))
      session = discover(binary, settings.session, deadline)
  if os.environ.get("HERDR_PANE_ID"):
    _caller_scope(settings, session["socket_path"])
  client = HerdrClient(session["socket_path"], deadline)
  try:
    if owned_process is not None:
      client.expected_peer_pid = owned_process["pid"]
    while True:
      try:
        client.request("ping", {})
        break
      except TermcfgError as error:
        if not start or error.code == 4 or deadline.expired:
          raise
        time.sleep(deadline.remaining(0.02))
    if owned_process is not None:
      record_startup_evidence(client, settings, binary, owned_process, inputs)
    yield client, binary
  finally:
    client.close()


def current_binding_v2(client, state, caller_id):
  if not caller_id:
    raise conflict("work_enter_project_first")
  pane = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane")
  if not any(item["workspace_id"] == pane["workspace_id"]
      for item in client.request("workspace.list", {})["workspaces"]):
    raise conflict("work_current_binding_unknown")
  workspace = _workspace(client, pane["workspace_id"])
  owner = tokens(workspace).get("rw2_owner")
  if not owner:
    raise conflict("work_enter_project_first")
  binding = state.load_binding(owner)
  if binding is None or binding["workspace_id"] != pane["workspace_id"]:
    raise conflict("work_current_binding_unknown")
  _v2_workspace(client, binding, allow_pending=True)
  references = [(key, locator, reference) for key, item in binding["types"].items()
    for locator, reference in item["instances"].items() if reference["pane_id"] == pane["pane_id"]
      or reference["terminal_id"] == pane["terminal_id"]]
  if references or any(key.startswith("rw2_") for key in tokens(pane)):
    if len(references) != 1:
      raise conflict("work_caller_instance_unknown")
    key, locator, reference = references[0]
    status, actual = instance_status_v2(client, binding, key, locator, reference)
    if status != "active" or actual["pane_id"] != pane["pane_id"]:
      raise conflict("work_caller_instance_unknown")
  return binding


def instance_status_v2(client, binding, type_key, instance_id, reference):
  """完整查询可以证明原终端已消失；现存编号丢标记始终为 unknown。"""
  marker = _v2_markers(binding, type_key, instance_id, reference["kind"], reference["op"])
  panes = _panes(client)
  matches = [pane for pane in panes if all(tokens(pane).get(key) == value for key, value in marker.items())]
  if len(matches) > 1:
    raise conflict("work_instance_identity_unknown")
  if not matches:
    if any(pane["pane_id"] == reference["pane_id"] or pane["terminal_id"] == reference["terminal_id"] or
        tokens(pane).get("rw2_instance") == instance_id for pane in panes):
      raise conflict("work_instance_identity_unknown")
    return "absent", None
  pane = matches[0]
  if (pane["terminal_id"] != reference["terminal_id"] or tokens(pane) != {**marker,
      "rw2_phase": "accepted", "rw2_commit": reference["op"]}):
    # 外来非 rw2 token 不影响归属，但保留固定八键的严格检查。
    owned = {key: val for key, val in tokens(pane).items() if key.startswith("rw2_")}
    if pane["terminal_id"] != reference["terminal_id"] or owned != {**marker,
        "rw2_phase": "accepted", "rw2_commit": reference["op"]}:
      raise conflict("work_instance_identity_unknown")
  if pane["workspace_id"] != binding["workspace_id"]:
    return "moved", pane
  pane = _v2_instance(client, binding, marker, reference, strict_ids=False)
  return "active", pane


def enter_context_v2(client, settings, state, candidate, *, caller_id=None, binary=None):
  from .work_config import prepare_launch
  from .work_projects import directory
  from .work_state import context_owner, MODEL
  caller = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane") if caller_id else None
  def checked(pane):
    if caller is not None:
      current = info(client.request("pane.current", {"caller_pane_id": caller_id}), "pane")
      if any(current[key] != caller[key] for key in ("workspace_id", "pane_id", "terminal_id")):
        raise conflict("work_caller_changed")
    return pane
  owner = context_owner(client.socket_path, candidate.kind, candidate.key)
  pending = state.pending(owner)
  for receipt in pending:
    intent = state.read_intent(receipt["op"])
    if intent and intent["action"] == "workspace-initial" and receipt["phase"] in ("commit-issued", "accepted"):
      finalize_instance_v2(client, state, receipt["op"])
  binding = state.load_binding(owner)
  if binding is not None:
    _v2_workspace(client, binding, allow_pending=True)
    preferred = settings.structured["templates"].get(binding["template"], {}).get("initial")
    keys = sorted(binding["types"], key=lambda key: (key != preferred, key))
    for key in keys:
      item = binding["types"][key]
      references = sorted(item["instances"].items(), key=lambda pair: (pair[0] != item["default"], pair[0]))
      for instance_id, reference in references:
        try:
          status, pane = instance_status_v2(client, binding, key, instance_id, reference)
        except TermcfgError:
          continue
        if status == "active":
          marker = _v2_markers(binding, key, instance_id, reference["kind"], reference["op"])
          checked(pane)
          return checked(_v2_focus(client, binding, pane, marker))
    raise conflict("work_context_has_no_verified_terminal")
  if state.pending(owner):
    raise conflict("work_pending_requires_reconciliation")
  start = directory(candidate.key if candidate.kind == "project" else candidate.start_path or os.environ.get("HOME", ""))
  try:
    template = settings.structured["templates"][candidate.template]
    key = template["initial"]
    prepared = prepare_launch(settings, template["tab_types"][key], start)
  except KeyError:
    raise TermcfgError(2, "work_unknown_template", "work config check") from None
  binding = {"version": 2, "owner": owner, "endpoint": state.socket_path,
    "generation": list(client.identity), "epoch": uuid.uuid4().hex,
    "context": {"kind": candidate.kind, "key": candidate.key}, "workspace_start": str(start),
    "captured_home": prepared["captured_home"], "workspace_id": None, "template": candidate.template,
    "origin": candidate.origin, "types": {key: prepared}}
  return checked(create_instance_v2(client, settings, state, binding, key, label=candidate.title,
    caller_id=caller_id, binary=binary))


def lifecycle_report_v2(client, state):
  rows = []
  for binding in state.bindings():
    row = {"context": binding["context"], "workspace_id": binding["workspace_id"],
      "state": "unknown", "instances": [], "pending": state.pending(binding["owner"])}
    try:
      _v2_workspace(client, binding, allow_pending=True)
      row["state"] = "partial" if row["pending"] else "verified"
      for key, item in binding["types"].items():
        for instance_id, reference in item["instances"].items():
          try:
            status, pane = instance_status_v2(client, binding, key, instance_id, reference)
          except TermcfgError:
            status = "unknown"
            row["state"] = "unknown"
          row["instances"].append({"type": key, "instance": instance_id, "kind": reference["kind"], "state": status})
    except TermcfgError:
      row["state"] = "stale-or-unknown"
    rows.append(row)
  registered = {row["op"] for item in rows for row in item["pending"]}
  orphaned = [{"op": intent["op"], "context": intent["binding"]["context"], "state": "unknown"}
    for intent in state.intents() if intent["op"] not in registered]
  return {"endpoint": "available", "bindings": rows, "unregistered_operations": orphaned}


def close_preview_v2(client, state, *, caller_id):
  from .work_state import reviewed_scope
  binding = current_binding_v2(client, state, caller_id)
  workspace = _v2_workspace(client, binding, allow_pending=True)
  panes = [item for item in _panes(client) if item["workspace_id"] == binding["workspace_id"]]
  ids = sorted({item["tab_id"] for item in panes})
  if (not panes or workspace["pane_count"] != len(panes) or workspace["tab_count"] != len(ids)
      or len({item["terminal_id"] for item in panes}) != len(panes)
      or len({item["pane_id"] for item in panes}) != len(panes)):
    raise conflict("work_close_membership_unknown")
  tabs = []
  for tab_id in ids:
    tab = info(client.request("tab.get", {"tab_id": tab_id}), "tab")
    if tab["workspace_id"] != binding["workspace_id"] or tab["pane_count"] != sum(item["tab_id"] == tab_id for item in panes):
      raise conflict("work_close_membership_unknown")
    tabs.append({"tab_id": tab_id, "label": tab.get("label")})
  scope = reviewed_scope(binding, tabs, panes)
  current = [item for item in _panes(client) if item["workspace_id"] == binding["workspace_id"]]
  if reviewed_scope(binding, tabs, current) != scope:
    raise conflict("work_close_scope_changed")
  _v2_workspace(client, binding, allow_pending=True)
  return {"scope": scope, "context": binding["context"], "workspace_id": binding["workspace_id"],
    "tabs": tabs, "panes": [{key: item[key] for key in ("pane_id", "terminal_id", "tab_id", "workspace_id")} for item in panes],
    "affects_all_viewers": True, "capability": {"atomic_membership_guard": False},
    "retained": ["checkout", "branch", "configuration", "siblings", "server"],
    "diagnostic": "work_native_guarded_close_unavailable"}


def close_workspace_v2(client, state, *, caller_id, scope):
  if not isinstance(scope, str) or not re.fullmatch(r"[a-f0-9]{64}", scope):
    raise TermcfgError(2, "work_invalid_close_scope", "work close --dry-run")
  current = close_preview_v2(client, state, caller_id=caller_id)
  if current["scope"] != scope:
    raise conflict("work_close_scope_changed")
  # 审阅 token 不是原生原子 guard；当前公开协议没有安全的派发路径。
  raise TermcfgError(5, "work_native_guarded_close_unavailable", "work close --dry-run")


def open_type_v2(client, settings, state, type_key, *, new=False, caller_id, binary=None):
  from .work_config import prepare_launch
  binding = current_binding_v2(client, state, caller_id)
  desired = "extra" if new else "default"
  for receipt in state.pending(binding["owner"]):
    if receipt.get("type") == type_key and receipt.get("kind") == desired and receipt["phase"] in ("commit-issued", "accepted"):
      finalize_instance_v2(client, state, receipt["op"])
  binding = state.load_binding(binding["owner"])
  item = binding["types"].get(type_key)
  if not new and item is not None and item["default"] is not None:
    instance_id = item["default"]
    reference = item["instances"][instance_id]
    status, pane = instance_status_v2(client, binding, type_key, instance_id, reference)
    if status == "active":
      marker = _v2_markers(binding, type_key, instance_id, reference["kind"], reference["op"])
      return _v2_focus(client, binding, pane, marker)
  if state.pending(binding["owner"]):
    raise conflict("work_pending_requires_reconciliation")
  try:
    definition = settings.structured["templates"][binding["template"]]["tab_types"][type_key]
  except KeyError:
    raise TermcfgError(2, "work_type_definition_required", "work config check") from None
  if item is None:
    item = prepare_launch(settings, definition, binding["workspace_start"])
    binding["types"][type_key] = item
  elif not new and item["default"] is not None:
    # 只有完整查询已证明 closed/moved 才到这里；写入修正后再发表新意图。
    del item["instances"][item["default"]]
    item["default"] = None
    state.save_binding(binding)
  return create_instance_v2(client, settings, state, binding, type_key, kind=desired,
    caller_id=caller_id, binary=binary)


def focus_instance_v2(client, state, type_key, instance_id, *, caller_id):
  binding = current_binding_v2(client, state, caller_id)
  try:
    reference = binding["types"][type_key]["instances"][instance_id]
  except KeyError:
    raise conflict("work_instance_not_registered") from None
  status, pane = instance_status_v2(client, binding, type_key, instance_id, reference)
  if status != "active":
    raise conflict("work_instance_not_in_current_workspace")
  return _v2_focus(client, binding, pane,
    _v2_markers(binding, type_key, instance_id, reference["kind"], reference["op"]))


def rebind_type_v2(client, settings, state, type_key, *, accept=False, caller_id, expected_digest=None):
  from .work_config import prepare_launch
  binding = current_binding_v2(client, state, caller_id)
  if state.pending(binding["owner"]):
    raise conflict("work_pending_requires_reconciliation")
  previous = binding["types"].get(type_key)
  if previous is None:
    raise TermcfgError(2, "work_type_not_yet_bound", "work open TYPE")
  for instance_id, reference in previous["instances"].items():
    status, _ = instance_status_v2(client, binding, type_key, instance_id, reference)
    if status == "active":
      raise conflict("work_type_still_active")
  tracked = set(previous["instances"])
  if any(tokens(pane).get("rw2_owner") == binding["owner"] and tokens(pane).get("rw2_epoch") == binding["epoch"]
      and pane["workspace_id"] == binding["workspace_id"] and tokens(pane).get("rw2_type") == type_key
      and tokens(pane).get("rw2_instance") not in tracked for pane in _panes(client)):
    raise conflict("work_unregistered_type_instance")
  try:
    definition = settings.structured["templates"][binding["template"]]["tab_types"][type_key]
  except KeyError:
    raise TermcfgError(2, "work_type_definition_required", "work config check") from None
  replacement = prepare_launch(settings, definition, binding["workspace_start"])
  replacement["sequence"] = previous["sequence"]
  if expected_digest is not None and replacement["digest"] != expected_digest:
    raise conflict("work_rebind_preview_changed")
  if accept:
    state.replace_type_binding(binding["owner"], type_key, previous, replacement)
  return replacement


def synchronize_named_title(settings, identifier, title):
  from .herdr import Deadline
  from .work_state import WorkState, context_owner
  deadline = Deadline()
  try:
    with connected(settings, deadline, start=False) as (client, binary):
      with WorkState(client.socket_path, client.identity) as state:
        binding = state.load_binding(context_owner(client.socket_path, "named", identifier))
        if binding is None:
          print("work_named_title: saved; no verified live binding")
          return 0
        with operation_lock(deadline):
          _v2_workspace(client, binding, allow_pending=True)
          client.request("workspace.rename", {"workspace_id": binding["workspace_id"], "label": title})
          actual = _v2_workspace(client, binding, allow_pending=True)
          if actual["label"] != title:
            raise conflict()
        return 0
  except TermcfgError as error:
    if error.code == 5:
      print("work_named_title: saved; native presentation not synchronized")
      return 0
    raise TermcfgError(4, "work_named_title_saved_native_presentation_pending", "work status") from None


def structured_native_command(args, settings, *, context=None):
  from .herdr import Deadline
  from .work_projects import discover, resolve_project
  from .work_state import WorkState
  if args.command == "close":
    _caller_scope(settings)
    with connected(settings, Deadline(), start=False) as (client, binary):
      with WorkState(client.socket_path, client.identity) as state:
        preview = close_preview_v2(client, state, caller_id=_caller_scope(settings, client.socket_path))
    print(json.dumps(preview, ensure_ascii=False))
    if args.dry_run:
      return 0
    if args.scope is None:
      if context is not None:
        from rotom.context import require_input
        require_input(context)
      elif not sys.stdin.isatty():
        raise TermcfgError(2, "work_close_authorization_required", "work close --dry-run")
      from .work_ui import confirm
      if not confirm("End every terminal in this workspace for all viewers", **({"context": context} if context is not None else {})):
        return 0
      scope = preview["scope"]
    else:
      scope = args.scope
    deadline = Deadline()
    with operation_lock(deadline):
      with connected(settings, deadline, start=False) as (client, binary):
        with WorkState(client.socket_path, client.identity) as state:
          close_workspace_v2(client, state, caller_id=_caller_scope(settings, client.socket_path), scope=scope)
  if args.command == "open" and (not os.environ.get("HERDR_PANE_ID") or not os.environ.get("HERDR_SOCKET_PATH")):
    raise conflict("work_enter_project_first")
  if args.command in ("open", "rebind"):
    _caller_scope(settings)
    type_key = args.role
    instance_id = None
    if type_key is None:
      from .work_ui import type_action
      with connected(settings, Deadline(), start=False) as (client, binary):
        with WorkState(client.socket_path, client.identity) as state:
          binding = current_binding_v2(client, state, _caller_scope(settings, client.socket_path))
          selected = type_action(settings, binding, new=args.new, **({"context": context} if context is not None else {}))
      if selected is None:
        return 0
      if selected[0] == "!rebind":
        return main([*settings.selectors, "rebind", selected[1]], **({"context": context} if context is not None else {}))
      type_key, instance_id = selected
    if args.command == "rebind" and not args.accept:
      if context is not None:
        from rotom.context import require_input
        require_input(context)
      elif not sys.stdin.isatty():
        raise TermcfgError(2, "work_rebind_accept_required", "work rebind TYPE --accept")
      with connected(settings, Deadline(), start=False) as (client, binary):
        with WorkState(client.socket_path, client.identity) as state:
          preview = rebind_type_v2(client, settings, state, type_key,
            caller_id=_caller_scope(settings, client.socket_path))
      print(json.dumps({"cwd": preview["cwd"], "launch": preview["launch"], "digest": preview["digest"]}, ensure_ascii=False),
        file=context.input_gateway.stderr if context is not None else sys.stdout)
      from .work_ui import confirm
      if not confirm("Rebind this inactive type", **({"context": context} if context is not None else {})):
        return 0
      reviewed = preview["digest"]
    else:
      reviewed = None
    deadline = Deadline()
    with operation_lock(deadline):
      with connected(settings, deadline, start=False) as (client, binary):
        with WorkState(client.socket_path, client.identity, create=True) as state:
          caller = _caller_scope(settings, client.socket_path)
          binding = current_binding_v2(client, state, caller)
          fixed = binding["types"].get(type_key)
          definition = settings.structured["templates"].get(binding["template"], {}).get("tab_types", {}).get(type_key, {})
          launcher = fixed["launch"]["launcher"] if fixed is not None and args.command == "open" else definition.get("launcher")
          # 从同一起点扩展已确认 Agent 的预算，不重启计时，也不读取其他模板。
          deadline.expires_at += operation_timeout(launcher) - 30
          if args.command == "rebind":
            rebind_type_v2(client, settings, state, type_key, accept=True, caller_id=caller, expected_digest=reviewed)
          elif instance_id is not None:
            focus_instance_v2(client, state, type_key, instance_id, caller_id=caller)
          else:
            open_type_v2(client, settings, state, type_key, new=args.new, caller_id=caller, binary=binary)
    print("work_" + args.command + ": " + type_key)
    return 0
  if args.command in ("status", "reconcile", "list"):
    try:
      with connected(settings, Deadline(), start=False) as (client, binary):
        with WorkState(client.socket_path, client.identity) as state:
          result = lifecycle_report_v2(client, state)
    except TermcfgError as error:
      result = {"endpoint": "unavailable-or-unknown", "bindings": [], "reason": error.reason}
    if args.command == "list":
      from dataclasses import asdict
      result["candidates"] = [asdict(item) for item in discover(settings).candidates]
    from .work_git import report
    result.update(report(settings))
    print(json.dumps(result, ensure_ascii=False))
    return 0
  if args.command == "enter":
    candidate = resolve_project(settings, args.path)
  elif args.command == "named" and args.action == "enter":
    choices = [item for item in discover(settings).candidates if item.kind == "named" and item.key == args.id]
    if len(choices) != 1:
      raise TermcfgError(2, "work_named_not_registered", "work list")
    candidate = choices[0]
  else:
    raise TermcfgError(5, "work_structured_type_workflow_not_ready", "work --help")
  definition = settings.structured["templates"][candidate.template]
  launcher = definition["tab_types"][definition["initial"]]["launcher"]
  deadline = Deadline(timeout=operation_timeout(launcher))
  inside = bool(os.environ.get("HERDR_PANE_ID"))
  if os.environ.get("TMUX") and not inside:
    raise conflict("work_leave_tmux_use_plain_ssh")
  if inside:
    _caller_scope(settings)
  with operation_lock(deadline):
    with connected(settings, deadline, start=not inside) as (client, binary):
      caller = _caller_scope(settings, client.socket_path) if inside else None
      with WorkState(client.socket_path, client.identity, create=True) as state:
        enter_context_v2(client, settings, state, candidate, caller_id=caller, binary=binary)
      if inside:
        print("work_enter: focused")
        return 0
      current = os.lstat(client.socket_path)
      if (current.st_dev, current.st_ino) != client.identity:
        raise conflict("work_server_changed_before_attach")
  environment = dict(os.environ)
  for key in (PAYLOAD_ENV, "ROTOM_WORK_LAUNCH_V2"):
    environment.pop(key, None)
  os.execvpe(binary, [binary, "session", "attach", settings.session], environment)
  return 0


def execute_worktree_plan(settings, plan, *, enter=False, deadline=None, context=None):
  from . import work_git
  from .herdr import Deadline
  deadline = deadline or Deadline()
  with operation_lock(deadline):
    result = work_git.create(settings, plan, deadline=deadline)
  print(json.dumps(result, ensure_ascii=False))
  if enter:
    code = main([*settings.selectors, "enter", result["path"]], **({"context": context} if context is not None else {}))
    if code:
      print("work_git_checkout_retained: retry work enter PATH explicitly", file=sys.stderr)
    return code
  return 0


def registration_input(args):
  if args.command not in ("source", "project", "named") or args.action not in ("add", "rename"):
    return None, None
  names = {"source": ("id", "path", "mode", "template", "depth", "exclude", "follow_symlinks"),
    "project": ("path", "mode", "template"), "named": ("id", "title", "template", "start_path")}[args.command]
  values = {name: getattr(args, name) for name in names if getattr(args, name, None) is not None}
  if args.command == "source":
    values["exclude_hidden"] = not args.include_hidden
  return args.command + "-" + args.action, values


def structured_command(args, settings, *, context=None):
  from dataclasses import asdict
  from . import work_edit, work_projects, work_ui
  if args.command == "worktree":
    from . import work_git
    from .herdr import Deadline
    deadline = Deadline()
    plan = work_git.preview(settings, repo=args.repo, path=args.path, template=args.template,
      new_branch=args.new_branch, base=args.base, existing_branch=args.existing_branch, deadline=deadline)
    print(json.dumps(plan.as_dict(), ensure_ascii=False))
    if args.dry_run:
      return 0
    return execute_worktree_plan(settings, plan, enter=args.enter, deadline=deadline, **({"context": context} if context is not None else {}))
  if args.command == "config":
    if args.action == "edit":
      result = work_edit.edit(settings, **({"context": context} if context is not None else {}))
      print("work_config: saved" if result.changed else "work_config: unchanged")
    else:
      work_ui.present_discovery(work_projects.discover(settings), show_candidates=False)
      print("work_config: valid")
    return 0
  if args.command == "list" and not args.live:
    result = work_projects.discover(settings)
    value = {"candidates": [asdict(item) for item in result.candidates], "diagnostics": result.diagnostics}
    if args.json:
      print(json.dumps(value, ensure_ascii=False))
    else:
      for item in result.candidates:
        print(work_ui.candidate_label(item))
      for diagnostic in result.diagnostics:
        print(diagnostic["reason"], file=sys.stderr)
    return 0
  if args.command in ("source", "project", "named") and args.action in ("add", "rename"):
    operation, values = registration_input(args)
    proposal = work_edit.preview(settings, operation, values)
    work_ui.present_proposal(proposal)
    if args.dry_run:
      print("work_config: preview only")
      return 0
    result = work_edit.save(proposal)
    print("work_config: saved" if result.changed else "work_config: unchanged")
    if args.command == "named" and args.action == "rename":
      return synchronize_named_title(proposal.settings, args.id, args.title)
    return 0
  if args.command is None:
    action = work_ui.selector(settings, **({"context": context} if context is not None else {}))
    if isinstance(action, work_ui.ReviewedWorktreeAction):
      return execute_worktree_plan(action.settings, action.plan, enter=action.enter, **({"context": context} if context is not None else {}))
    return 0 if action is None else main([*settings.selectors, *action], **({"context": context} if context is not None else {}))
  return structured_native_command(args, settings, **({"context": context} if context is not None else {}))


def build_parser():
  """只构建语法；不读取配置或连接原生程序。"""
  import argparse
  class Parser(argparse.ArgumentParser):
    def error(self, message):
      raise TermcfgError(2, "work_invalid_arguments", "work --help")
  parser = Parser(prog="work", description="显式选择项目，并按用途聚焦原生终端")
  selectors = parser.add_mutually_exclusive_group()
  selectors.add_argument("--machine")
  selectors.add_argument("--local")
  commands = parser.add_subparsers(dest="command")
  commands.add_parser("enter").add_argument("path")
  opening = commands.add_parser("open")
  opening.add_argument("role", nargs="?")
  opening.add_argument("--new", action="store_true")
  rebinding = commands.add_parser("rebind")
  rebinding.add_argument("role")
  rebinding.add_argument("--accept", action="store_true")
  listing = commands.add_parser("list")
  listing.add_argument("--json", action="store_true")
  listing.add_argument("--live", action="store_true")
  for name in ("status", "reconcile"):
    commands.add_parser(name).add_argument("--json", action="store_true")
  for command in ("source", "project", "named"):
    sub = commands.add_parser(command).add_subparsers(dest="action", required=True)
    adding = sub.add_parser("add")
    if command != "project":
      adding.add_argument("--id", required=True)
    if command == "named":
      adding.add_argument("--title", required=True)
      adding.add_argument("--start-path")
      sub.add_parser("enter").add_argument("id")
      renaming = sub.add_parser("rename")
      renaming.add_argument("id")
      renaming.add_argument("--title", required=True)
      renaming.add_argument("--dry-run", action="store_true")
    else:
      adding.add_argument("--path", required=True)
      adding.add_argument("--mode", required=True, choices=("git", "directory"))
    adding.add_argument("--template", required=True)
    adding.add_argument("--dry-run", action="store_true")
    if command == "source":
      adding.add_argument("--depth", type=int, default=1)
      adding.add_argument("--include-hidden", action="store_true")
      adding.add_argument("--exclude", action="append", default=[])
      adding.add_argument("--follow-symlinks", action="store_true")
  configuring = commands.add_parser("config").add_subparsers(dest="action", required=True)
  configuring.add_parser("check")
  configuring.add_parser("edit")
  creating = commands.add_parser("worktree").add_subparsers(dest="action", required=True).add_parser("create")
  creating.add_argument("--repo", required=True)
  creating.add_argument("--path", required=True)
  creating.add_argument("--template", required=True)
  branches = creating.add_mutually_exclusive_group(required=True)
  branches.add_argument("--new-branch")
  branches.add_argument("--existing-branch")
  creating.add_argument("--base")
  creating.add_argument("--enter", action="store_true")
  creating.add_argument("--dry-run", action="store_true")
  closing = commands.add_parser("close")
  closing.add_argument("--dry-run", action="store_true")
  closing.add_argument("--scope")
  closing.add_argument("--yes", action="store_true")
  return parser


def main(argv=None, *, context=None):
  from .herdr import Deadline
  from .work_config import read_settings
  from rotom.context import InputError, require_input, TypedInvocation
  def next_hint(code):
    import shlex
    path = context.command_path if code == 2 else ("work", "status")
    tokens = TypedInvocation(context, ()).advice_tokens(path)
    return shlex.join((*tokens, "--help") if code == 2 else tokens)
  parser = build_parser()
  args = None
  try:
    args = parser.parse_args(argv)
    if context is not None:
      args.invocation_context = context
    if args.command == "close" and ((args.dry_run and (args.scope is not None or args.yes))
        or ((args.scope is not None) != args.yes)):
      raise TermcfgError(2, "work_invalid_close_authorization", "work close --dry-run")
    if context is not None and (args.command is None
        or (args.command == "open" and args.role is None)
        or (args.command == "rebind" and not args.accept)
        or (args.command == "close" and not args.dry_run and args.scope is None)
        or (args.command == "config" and args.action == "edit")):
      require_input(context)
    if args.command == "open" and args.role in ROLES and (
        not os.environ.get("HERDR_PANE_ID") or not os.environ.get("HERDR_SOCKET_PATH")):
      raise conflict()
    deadline = Deadline(timeout=operation_timeout(args.role if args.command == "open" else None))
    settings = read_settings(machine=args.machine, local=args.local)
    if getattr(settings, "model", None) is not None:
      return structured_command(args, settings, **({"context": context} if context is not None else {}))
    if args.command not in ("enter", "open") or (args.command == "open" and args.role not in ROLES):
      raise TermcfgError(2, "work_invalid_legacy_command", "work --help")
    if args.command == "open" and (not os.environ.get("HERDR_PANE_ID") or not os.environ.get("HERDR_SOCKET_PATH")):
      raise conflict()
    # 非Git在任何native发现/启动之前失败。
    root = canonical_checkout(args.path, deadline) if args.command == "enter" else None
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
  except InputError as error:
    print(("work_input_cancelled" if error.exit_code == 130 else "work_input_required")
      + ": " + next_hint(2), file=sys.stderr)
    return error.exit_code
  except TermcfgError as error:
    if args is not None and error.reason == "work_unsafe_local_configuration" and not getattr(error, "fragment", None):
      operation, values = registration_input(args)
      if operation is not None or (args.command == "config" and args.action == "edit"):
        from .work_edit import manual_fragment
        error.fragment = manual_fragment(operation, values)
    print(error.reason + ": " + (next_hint(error.code) if context is not None else error.next_command), file=sys.stderr)
    if getattr(error, "fragment", None):
      print("Manual machine.work fragment:\n" + error.fragment, file=sys.stderr)
    return error.code
  except (OSError, ValueError):
    print("work_filesystem_or_runtime_failed: work --help", file=sys.stderr)
    return 6
