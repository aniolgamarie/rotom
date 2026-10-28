"""位置交接的不可变精确请求与一次性回执；不接受命令或恢复正文。"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

from . import run_owners, storage
from .pane_records import _json_types, _validator as container_validator
from .paths import PathError
from .sessions import SessionRef
from .storage import Conflict, StateError


_ERROR = "恢复位置请求不能核实；保留事实，不自动重试"
_FIELDS = {"schema_version", "request_id", "mode", "scope", "batch_id", "run_id", "session_ref",
  "cwd", "deployment_digest", "workflow_revision", "workflow_digest", "manager_code_identity",
  "terminal_ref", "rotom_root"}
_RECEIPT = {"schema_version", "request_id", "phase", "terminal_ref", "exit_code", "reason"}
_NEXT = {"prepared": {"dispatched", "failed", "unknown"},
  "dispatched": {"ready", "handoff", "failed", "unknown"},
  "ready": {"committed", "failed", "unknown"}, "committed": {"handoff", "failed", "unknown"},
  "handoff": {"executing", "failed", "unknown"}, "executing": {"exited", "failed", "unknown"},
  "exited": set(), "failed": set(), "unknown": set()}


def request_digest(value):
  return hashlib.sha256(run_owners._encode(value)).hexdigest()


def validate_terminal(value):
  from jsonschema import Draft202012Validator
  schema = container_validator().schema
  _json_types(value)
  Draft202012Validator({**schema["properties"]["terminal_ref"], "$defs": schema["$defs"]}).validate(value)
  run_owners._absolute(value["socket_path"])
  run_owners._absolute(value["cwd"])


def _validate(value, *, anchored=True):
  try:
    _json_types(value)
    if (type(value) is not dict or set(value) != _FIELDS | ({"root_identity"} if anchored else set())
        or value["schema_version"] != 1 or value["mode"] not in ("original", "new-tab")):
      raise ValueError()
    for name in ("request_id", "batch_id", "run_id"):
      run_owners._run_id(value[name])
    for name in ("deployment_digest", "workflow_digest", "manager_code_identity"):
      if type(value[name]) is not str or re.fullmatch(r"[0-9a-f]{64}", value[name]) is None:
        raise ValueError()
    for name in ("cwd", "rotom_root"):
      run_owners._absolute(value[name])
    scope = value["scope"]
    if (type(scope) is not dict or set(scope) != {"machine", "local", "profile", "agent"}
        or scope["machine"] is not None and (type(scope["machine"]) is not str
          or not scope["machine"] or "\0" in scope["machine"] or len(scope["machine"]) > 128)):
      raise ValueError()
    run_owners._absolute(scope["local"])
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", scope["profile"]) is None:
      raise ValueError()
    ref = SessionRef(**value["session_ref"])
    if ref.agent != scope["agent"] or ref.backend != "managed":
      raise ValueError()
    if not 1 <= value["workflow_revision"] <= 4096:
      raise ValueError()
    if value["terminal_ref"] is not None:
      validate_terminal(value["terminal_ref"])
      if value["terminal_ref"]["cwd"] != value["cwd"]:
        raise ValueError()
    if value["mode"] == "original" and value["terminal_ref"] is None:
      raise ValueError()
    if anchored:
      anchor = value["root_identity"]
      if type(anchor) is not list or len(anchor) != 2 or any(type(v) is not int or not 0 <= v < 2**64 for v in anchor):
        raise ValueError()
  except Exception:
    raise Conflict(_ERROR) from None


def _receipt(value, request):
  try:
    _json_types(value)
    if (type(value) is not dict or set(value) != _RECEIPT or value["schema_version"] != 1
        or value["request_id"] != request["request_id"] or value["phase"] not in _NEXT):
      raise ValueError()
    if value["terminal_ref"] is not None:
      validate_terminal(value["terminal_ref"])
      if value["terminal_ref"]["cwd"] != request["cwd"]:
        raise ValueError()
    if value["exit_code"] is not None and (type(value["exit_code"]) is not int or not 0 <= value["exit_code"] <= 255):
      raise ValueError()
    if value["phase"] == "exited" and value["exit_code"] is None:
      raise ValueError()
    if value["reason"] is not None and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value["reason"]) is None:
      raise ValueError()
    if value["phase"] in ("ready", "committed", "handoff", "executing", "exited") and value["terminal_ref"] is None:
      raise ValueError()
  except Exception:
    raise Conflict(_ERROR) from None


class LocationStore:
  def __init__(self, root):
    try:
      self.root = Path(root)
      run_owners._absolute(str(self.root))
      if self.root == Path("/"):
        raise ValueError()
    except Exception:
      raise Conflict(_ERROR) from None
    self.registry = run_owners.Registry(self.root, {"kind": "restore-location"})

  @contextmanager
  def _locked(self, *, create=False):
    try:
      with self.registry._locked(create=create) as tree:
        yield tree
        if tree is not None:
          self.registry._verify_root(tree)
    except (OSError, PathError, StateError):
      raise Conflict(_ERROR) from None

  def _read(self, tree, name):
    if tree is None:
      return None, None
    raw = tree.read(name, max_bytes=65536)
    if raw is None:
      raise Conflict(_ERROR)
    try:
      if raw[1] != 0o600:
        raise ValueError()
      value = json.loads(raw[0], object_pairs_hook=run_owners._pairs,
        parse_float=run_owners._invalid_constant, parse_constant=run_owners._invalid_constant)
      if name == "request.json":
        _validate(value)
        info = os.fstat(tree.fd)
        if value["root_identity"] != [info.st_dev, info.st_ino]:
          raise ValueError()
    except Exception:
      raise Conflict(_ERROR) from None
    return value, raw

  def read_request(self):
    with self._locked() as tree:
      return self._read(tree, "request.json")[0]

  def read_receipt(self):
    with self._locked() as tree:
      if tree is None:
        return None
      request, _ = self._read(tree, "request.json")
      value, _ = self._read(tree, "receipt.json")
      _receipt(value, request)
      return value

  def create(self, value):
    _validate(value, anchored=False)
    with self._locked(create=True) as tree:
      if os.listdir(tree.fd):
        raise Conflict(_ERROR)
      info = os.fstat(tree.fd)
      request = {**deepcopy(value), "root_identity": [info.st_dev, info.st_ino]}
      receipt = {"schema_version": 1, "request_id": value["request_id"], "phase": "prepared",
        "terminal_ref": None, "exit_code": None, "reason": None}
      tree.write_new("request.json", run_owners._encode(request))
      tree.write_new("receipt.json", run_owners._encode(receipt))
      storage.sync_directory_ancestors(tree.root)
      saved, raw = self._read(tree, "request.json")
      if raw[0] != run_owners._encode(request):
        raise Conflict(_ERROR)
      return saved

  def transition(self, expected, replacement):
    with self._locked() as tree:
      request, _ = self._read(tree, "request.json")
      if request is None:
        raise Conflict(_ERROR)
      _receipt(expected, request)
      _receipt(replacement, request)
      if (replacement["phase"] not in _NEXT[expected["phase"]]
          or expected["terminal_ref"] is not None and replacement["terminal_ref"] != expected["terminal_ref"]):
        raise Conflict(_ERROR)
      current, raw = self._read(tree, "receipt.json")
      if raw[0] != run_owners._encode(expected):
        raise Conflict(_ERROR)
      encoded = run_owners._encode(replacement)
      tree.replace("receipt.json", encoded, expected=raw[2])
      saved, observed = self._read(tree, "receipt.json")
      if observed[0] != encoded:
        raise Conflict(_ERROR)
      return saved


def location_root(workspace, batch_id, run_id):
  run_owners._run_id(batch_id)
  run_owners._run_id(run_id)
  return workspace.state_root / "restore-locations" / batch_id / run_id


def status_for(workspace, batch_id, run_id):
  """只读已有位置事实；损坏不得降级成没有派发。"""
  try:
    store = LocationStore(location_root(workspace, batch_id, run_id))
    request = store.read_request()
    if request is None:
      return None
    if (request["scope"] != {**workspace.binding, "agent": workspace.agent}
        or request["batch_id"] != batch_id or request["run_id"] != run_id):
      raise Conflict(_ERROR)
    receipt = store.read_receipt()
    return {"request_id": request["request_id"], "location": request["mode"],
      "phase": receipt["phase"], "terminal_ref": receipt["terminal_ref"], "exit_code": receipt["exit_code"],
      "load_confirmation": "unknown", "continue_status": "not_sent"}
  except (Conflict, OSError):
    return {"location": "unknown", "phase": "unknown", "reason": "location-record-unavailable"}


def reserve(workspace, batch_id, run_id, *, mode, terminal_ref=None, deadline_ns=None):
  """普通 restore-intent 先阻止竞争；后续落盘/创建不明不撤销或重放。"""
  from . import tool_maintenance as flow
  from termcfg.work import ROOT, source_digest
  if mode not in ("original", "new-tab") or mode == "original" and terminal_ref is None:
    raise Conflict(_ERROR)
  if terminal_ref is not None:
    try:
      validate_terminal(terminal_ref)
    except Exception:
      raise Conflict(_ERROR) from None
  source_identity = source_digest(ROOT)
  store = LocationStore(location_root(workspace, batch_id, run_id))
  if store.read_request() is not None:
    raise Conflict(_ERROR)
  intent, target, deployment = flow.reserve_restore(workspace, batch_id, run_id=run_id,
    **({"deadline_ns": deadline_ns} if deadline_ns is not None else {}))
  value = {"schema_version": 1, "request_id": uuid.uuid4().hex, "mode": mode,
    "scope": {**workspace.binding, "agent": workspace.agent}, "batch_id": batch_id, "run_id": run_id,
    "session_ref": deepcopy(target["ref"]), "cwd": target["cwd"], "deployment_digest": deployment,
    "workflow_revision": intent["revision"], "workflow_digest": intent["digest"],
    "manager_code_identity": source_identity, "terminal_ref": terminal_ref, "rotom_root": str(ROOT)}
  store.create(value)
  return store
