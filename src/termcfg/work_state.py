"""受管引用与一次性意图；原生事实始终是控制前提，不保存终端清单。"""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from jsonschema import Draft202012Validator

from agentcfg.paths import PathError
from agentcfg.storage import Tree, StateError
from .errors import TermcfgError


MODEL = "structured-v1"
SOURCE = "rotom-work-v2"
LAUNCH_SOURCE = "rotom-work-launch-v2"
MAX_RECORD_BYTES = 1024 * 1024
MAX_RECORDS = 4096
ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"
HEX32 = {"type": "string", "pattern": r"^[a-f0-9]{32}$"}
HEX64 = {"type": "string", "pattern": r"^[a-f0-9]{64}$"}
TEXT = {"type": "string", "minLength": 1}
PATH = {"type": "string", "minLength": 1, "pattern": "^/"}
PATH_NAMES = ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME",
  "XDG_CACHE_HOME", "XDG_RUNTIME_DIR")


def object_schema(properties, required=None):
  return {"type": "object", "properties": properties,
    "required": list(properties) if required is None else required,
    "additionalProperties": False}


def nullable(schema):
  return {"anyOf": [schema, {"type": "null"}]}


def reviewed_scope(binding, tabs, panes):
  """只摘要非秘密目标身份；短时预览不进入目录清单或持久记录。"""
  return digest({"action": "workspace-close", "endpoint": binding["endpoint"],
    "generation": binding["generation"], "owner": binding["owner"], "epoch": binding["epoch"],
    "workspace_id": binding["workspace_id"], "atomic_membership_guard": False,
    "tabs": sorted(tab["tab_id"] for tab in tabs), "panes": sorted(
      ({key: pane[key] for key in ("workspace_id", "tab_id", "pane_id", "terminal_id")} for pane in panes),
      key=lambda pane: pane["pane_id"])})


GIT_FACTS_SCHEMA = object_schema({
  "repo": PATH, "path": PATH, "template": TEXT, "branch": TEXT,
  "branch_mode": {"enum": ["new", "existing"]}, "base": nullable(TEXT),
  "commit": {"type": "string", "pattern": r"^[a-f0-9]{40,64}$"},
  "common": PATH, "git_dir": PATH, "git_binary": PATH, "git_version": TEXT,
  "repo_identity": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
  "common_identity": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
  "git_dir_identity": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
  "parent_identity": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
  "binary_identity": {"type": "array", "items": {"type": "integer"}},
  "config_files": {"type": "object", "additionalProperties": {"type": ["array", "null"], "items": {"type": "integer"}}},
  "selection_digest": HEX64, "source": object_schema({"id": TEXT, "path": PATH,
    "mode": {"const": "git"}, "template": TEXT, "depth": {"type": "integer", "minimum": 1, "maximum": 32},
    "exclude_hidden": {"type": "boolean"}, "exclude": {"type": "array", "items": TEXT},
    "follow_symlinks": {"type": "boolean"}}),
  "worktrees": {"type": "array", "maxItems": MAX_RECORDS, "items": object_schema({"path": PATH,
    "branch": nullable(TEXT), "commit": nullable(TEXT)})},
})


LAUNCH_SCHEMA = object_schema({
  "launcher": {"enum": ["shell", "editor", "pi", "dsh", "codex"]},
  "argv": {"type": "array", "minItems": 1, "maxItems": 32, "items": TEXT},
  "runtime": nullable(object_schema({"generation": HEX64, "identity": TEXT,
    "policy": {"enum": ["legacy", "caller", "isolated"]}})),
  "paths": object_schema({name: nullable(PATH) for name in PATH_NAMES}, ["HOME"]),
})
INSTANCE_SCHEMA = object_schema({"op": HEX32, "kind": {"enum": ["default", "extra"]},
  **{name: TEXT for name in ("workspace_id", "pane_id", "terminal_id", "tab_id")}})
TYPE_SCHEMA = object_schema({"cwd": PATH, "captured_home": PATH, "launch": LAUNCH_SCHEMA,
  "digest": HEX64, "default": nullable(HEX32), "sequence": {"type": "integer", "minimum": 0},
  "instances": {"type": "object", "maxProperties": MAX_RECORDS,
    "propertyNames": HEX32, "additionalProperties": INSTANCE_SCHEMA}})
BINDING_SCHEMA = object_schema({"version": {"const": 2, "type": "integer"},
  "owner": HEX64, "endpoint": PATH,
  "generation": {"type": "array", "items": {"type": "integer", "minimum": 0},
    "minItems": 2, "maxItems": 2},
  "epoch": HEX32, "context": object_schema({"kind": {"enum": ["project", "named"]}, "key": TEXT}),
  "workspace_start": PATH, "captured_home": PATH, "workspace_id": nullable(TEXT),
  "template": {"type": "string", "pattern": ID_PATTERN}, "origin": TEXT,
  "types": {"type": "object", "maxProperties": MAX_RECORDS,
    "propertyNames": {"pattern": ID_PATTERN}, "additionalProperties": TYPE_SCHEMA}})
INTENT_SCHEMA = object_schema({"version": {"const": 2, "type": "integer"}, "op": HEX32,
  "owner": HEX64, "epoch": HEX32, "action": {"enum": ["workspace-initial", "tab"]},
  "type": {"type": "string", "pattern": ID_PATTERN}, "instance": HEX32,
  "kind": {"enum": ["default", "extra"]},
  "payload_digest": HEX64, "binding": BINDING_SCHEMA})
PHASES = ("intent", "dispatched", "commit-issued", "accepted", "completed", "unknown", "failed")
RECEIPT_SCHEMA = object_schema({"version": {"const": 2, "type": "integer"}, "op": HEX32,
  "owner": HEX64, "epoch": HEX32, "action": {"enum": ["workspace-initial", "tab"]},
  "type": {"type": "string", "pattern": ID_PATTERN}, "instance": HEX32,
  "kind": {"enum": ["default", "extra"]},
  "phase": {"enum": list(PHASES)},
  **{name: nullable(TEXT) for name in ("workspace_id", "pane_id", "terminal_id", "tab_id")}})
SCHEMAS = {"bindings": BINDING_SCHEMA, "intents": INTENT_SCHEMA, "receipts": RECEIPT_SCHEMA}


def conflict(reason="work_state_conflict"):
  return TermcfgError(4, reason, "work status")


def json_bytes(value):
  return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
    separators=(",", ":")) + "\n").encode("utf-8")


def digest(value):
  return hashlib.sha256(json_bytes(value)).hexdigest()


def launch_digest(cwd, captured_home, launch):
  return digest({"cwd": str(cwd), "captured_home": str(captured_home), "launch": launch})


def _literal(value):
  if not isinstance(value, str) or not value or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
    raise conflict()
  try:
    value.encode("utf-8")
  except UnicodeError:
    raise conflict() from None
  return value


def absolute(value):
  value = _literal(os.fspath(value))
  path = Path(value)
  if not path.is_absolute() or ".." in path.parts:
    raise conflict()
  return path


def canonical_endpoint(socket_path):
  try:
    return str(absolute(socket_path).resolve())
  except (OSError, ValueError):
    raise conflict("work_endpoint_identity_invalid") from None


def context_owner(socket_path, kind, key):
  if kind not in ("project", "named"):
    raise conflict()
  key = _literal(os.fspath(key))
  if kind == "named" and not re.fullmatch(ID_PATTERN, key):
    raise conflict()
  if kind == "project":
    key = str(absolute(key))
  return digest({"endpoint": canonical_endpoint(socket_path), "kind": kind, "key": key})


def default_root():
  value = os.environ.get("XDG_STATE_HOME")
  return (absolute(value) if value else absolute(os.environ.get("HOME", "")) / ".local" / "state") / "rotom" / "work" / "v2"


def _validate_strings(value):
  if isinstance(value, float):
    raise conflict()
  if isinstance(value, str):
    _literal(value)
  elif isinstance(value, dict):
    for key, item in value.items():
      _literal(key)
      _validate_strings(item)
  elif isinstance(value, list):
    for item in value:
      _validate_strings(item)


def validate(kind, value):
  if kind not in SCHEMAS or not Draft202012Validator(SCHEMAS[kind]).is_valid(value):
    raise conflict()
  _validate_strings(value)
  # jsonschema 将 bool 与整数分开；路径和摘要还需要语义校验。
  if kind == "bindings":
    if (value["owner"] != context_owner(value["endpoint"], **value["context"])
        or any(type(number) is not int for number in value["generation"])):
      raise conflict()
    for key in ("endpoint", "workspace_start", "captured_home"):
      absolute(value[key])
    if value["context"]["kind"] == "project":
      absolute(value["context"]["key"])
    for item in value["types"].values():
      absolute(item["cwd"])
      absolute(item["captured_home"])
      absolute(item["launch"]["argv"][0])
      if (item["launch"]["paths"]["HOME"] != item["captured_home"] or
          (item["launch"]["launcher"] in ("pi", "dsh")) != (item["launch"]["runtime"] is not None)):
        raise conflict("work_launch_boundary_invalid")
      for path in item["launch"]["paths"].values():
        if path is not None:
          absolute(path)
      if item["digest"] != launch_digest(item["cwd"], item["captured_home"], item["launch"]):
        raise conflict("work_type_binding_invalid")
      if item["default"] is not None:
        instance = item["instances"].get(item["default"])
        if instance is None or instance["kind"] != "default":
          raise conflict("work_default_binding_invalid")
      if sum(instance["kind"] == "default" for instance in item["instances"].values()
          if instance["workspace_id"] == value["workspace_id"]) > 1:
        raise conflict("work_default_binding_invalid")
  elif kind == "intents":
    validate("bindings", value["binding"])
    if (value["owner"] != value["binding"]["owner"] or value["epoch"] != value["binding"]["epoch"]
        or (value["action"] == "workspace-initial") != (value["binding"]["workspace_id"] is None)):
      raise conflict()
    item = value["binding"]["types"].get(value["type"])
    if (item is None or value["instance"] in item["instances"]
        or (value["action"] == "workspace-initial" and value["kind"] != "default")
        or (value["kind"] == "default" and item["default"] is not None)):
      raise conflict("work_intent_instance_invalid")
  return value


def _decode(data):
  def unique(pairs):
    result = {}
    for key, value in pairs:
      if key in result:
        raise ValueError()
      result[key] = value
    return result
  try:
    return json.loads(data, object_pairs_hook=unique,
      parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
  except (ValueError, UnicodeError, TypeError, RecursionError):
    raise conflict() from None


@contextmanager
def _io():
  try:
    yield
  except TermcfgError:
    raise
  except StateError as error:
    raise TermcfgError(error.exit_code, "work_private_state_io_failed", "work status") from None
  except PathError:
    raise conflict("work_private_state_unsafe") from None
  except OSError:
    raise TermcfgError(6, "work_private_state_io_failed", "work status") from None


class WorkState:
  """调用者负责生命周期锁；只读构造不创建任何目录或锁文件。"""

  def __init__(self, socket_path, identity, *, root=None, create=False):
    self.socket_path = canonical_endpoint(socket_path)
    if (not isinstance(identity, (list, tuple)) or len(identity) != 2
        or any(type(number) is not int or number < 0 for number in identity)):
      raise conflict()
    self.identity = tuple(identity)
    self.base = absolute(root) if root is not None else default_root()
    self.root = self.base / hashlib.sha256(self.socket_path.encode()).hexdigest()
    self.writable = create
    with _io():
      self.tree = Tree(self.root, create=create)

  def __enter__(self):
    return self

  def __exit__(self, *args):
    self.close()

  def close(self):
    self.tree.close()

  def _name(self, kind, key):
    length = 64 if kind == "bindings" else 32
    if kind not in SCHEMAS or not isinstance(key, str) or not re.fullmatch("[a-f0-9]{" + str(length) + "}", key):
      raise conflict()
    return kind + "/" + key + ".json"

  def read(self, kind, key):
    with _io():
      result = self.tree.read(self._name(kind, key), max_bytes=MAX_RECORD_BYTES)
      if result is None:
        return None
      if result[1] != 0o600:
        raise conflict("work_private_state_unsafe")
      value = validate(kind, _decode(result[0]))
      if value["owner" if kind == "bindings" else "op"] != key:
        raise conflict()
      return value

  def _write(self, kind, key, value, *, immutable=False):
    if not self.writable:
      raise conflict("work_state_read_only")
    validate(kind, value)
    data = json_bytes(value)
    if len(data) > MAX_RECORD_BYTES:
      raise conflict()
    with _io():
      name = self._name(kind, key)
      if immutable:
        self.tree.write_immutable(name, data)
      else:
        before = self.tree.read(name, max_bytes=MAX_RECORD_BYTES)
        if before and before[1] != 0o600:
          raise conflict("work_private_state_unsafe")
        self.tree.replace(name, data, expected=before[2] if before else None)

  def _list(self, kind):
    with _io():
      try:
        with self.tree.parent(kind + "/probe") as (fd, _):
          names = os.listdir(fd)
      except FileNotFoundError:
        return []
      if len(names) > MAX_RECORDS or any(not re.fullmatch(
          "[a-f0-9]{" + ("64" if kind == "bindings" else "32") + r"}\.json", name) for name in names):
        raise conflict()
      return [self.read(kind, name[:-5]) for name in sorted(names)]

  def bindings(self):
    values = self._list("bindings")
    for value in values:
      self._endpoint(value)
    return values

  def intents(self):
    values = self._list("intents")
    for value in values:
      self._endpoint(value["binding"])
    return values

  def _endpoint(self, value):
    if value["endpoint"] != self.socket_path or value["generation"] != list(self.identity):
      raise conflict("work_endpoint_generation_changed")

  def load_binding(self, owner):
    value = self.read("bindings", owner)
    if value is not None:
      self._endpoint(value)
    return value

  def save_binding(self, value):
    self._endpoint(value)
    if value["workspace_id"] is None:
      raise conflict()
    previous = self.load_binding(value["owner"])
    if previous is not None and any(previous[key] != value[key] for key in
        ("epoch", "context", "workspace_start", "captured_home", "workspace_id")):
      raise conflict("work_active_binding_changed")
    if previous is not None:
      for key, item in previous["types"].items():
        current = value["types"].get(key)
        if current is None or any(current[field] != item[field] for field in
            ("cwd", "captured_home", "launch", "digest")):
          raise conflict("work_type_binding_changed")
        if current["sequence"] < item["sequence"]:
          raise conflict("work_instance_sequence_changed")
        for instance_id in item["instances"].keys() & current["instances"].keys():
          if any(item["instances"][instance_id][field] != current["instances"][instance_id][field]
              for field in ("op", "kind", "terminal_id")):
            raise conflict("work_instance_binding_changed")
    self._write("bindings", value["owner"], value)

  def read_intent(self, op):
    value = self.read("intents", op)
    if value is not None:
      self._endpoint(value["binding"])
    return value

  def replace_type_binding(self, owner, type_key, expected, replacement):
    """调用者已持有操作锁并证明无活动实例；只显式替换一个已审阅类型。"""
    binding = self.load_binding(owner)
    if binding is None or binding["types"].get(type_key) != expected or self.pending(owner):
      raise conflict("work_rebind_state_changed")
    if replacement["default"] is not None or replacement["instances"] or replacement["sequence"] < expected["sequence"]:
      raise conflict("work_rebind_state_changed")
    binding["types"][type_key] = deepcopy(replacement)
    validate("bindings", binding)
    self._write("bindings", owner, binding)
    return binding

  def pending(self, owner):
    result = []
    intents = self.intents()
    known = {intent["op"] for intent in intents}
    for receipt in self._list("receipts"):
      if receipt["owner"] == owner and receipt["op"] not in known:
        if receipt["phase"] != "completed":
          result.append({**receipt, "phase": "unknown"})
        else:
          self._completed_binding(receipt)
    for intent in intents:
      if intent["owner"] != owner:
        continue
      receipt = self.read("receipts", intent["op"])
      if receipt is None:
        result.append({"op": intent["op"], "phase": "unknown"})
      elif any(receipt[key] != intent[key] for key in ("op", "owner", "epoch", "action", "type", "instance", "kind")):
        raise conflict()
      elif receipt["phase"] != "completed":
        result.append(receipt)
      else:
        self._completed_binding(receipt)
    return result

  def publish_intent(self, op, binding, *, action, payload_digest, type_key, instance, kind):
    self._endpoint(binding)
    intent = {"version": 2, "op": op, "owner": binding["owner"], "epoch": binding["epoch"],
      "action": action, "payload_digest": payload_digest, "type": type_key,
      "instance": instance, "kind": kind, "binding": deepcopy(binding)}
    validate("intents", intent)
    previous = self.read_intent(op)
    if previous is not None:
      if previous != intent:
        raise conflict("work_immutable_intent_changed")
      return previous
    if self.pending(binding["owner"]):
      raise conflict("work_pending_requires_reconciliation")
    existing = self.load_binding(binding["owner"])
    if action == "workspace-initial" and existing is not None:
      raise conflict("work_context_already_bound")
    if action == "workspace-initial" and set(binding["types"]) != {type_key}:
      raise conflict("work_initial_type_binding_changed")
    if action == "tab" and (existing is None or any(existing[key] != binding[key]
        for key in ("epoch", "context", "workspace_start", "captured_home", "workspace_id"))):
      raise conflict("work_active_binding_changed")
    if action == "tab":
      # 旧草稿不得在原生创建之后才发现已有默认实例；修正引用必须先持久化。
      if any(binding["types"].get(key) != item for key, item in existing["types"].items()):
        raise conflict("work_type_binding_changed")
      if set(binding["types"]) - set(existing["types"]) - {type_key}:
        raise conflict("work_type_binding_changed")
    self._write("intents", op, intent, immutable=True)
    self._write("receipts", op, {"version": 2, "op": op, "owner": binding["owner"],
      "epoch": binding["epoch"], "action": action, "phase": "intent",
      "type": type_key, "instance": instance, "kind": kind,
      **{key: None for key in ("workspace_id", "pane_id", "terminal_id", "tab_id")}}, immutable=True)
    return intent

  def update_receipt(self, op, phase, **ids):
    value = self.read("receipts", op)
    intent = self.read_intent(op)
    if value is None or intent is None or set(ids) - {"workspace_id", "pane_id", "terminal_id", "tab_id"}:
      raise conflict()
    if any(value[key] != intent[key] for key in ("op", "owner", "epoch", "action", "type", "instance", "kind")):
      raise conflict("work_receipt_identity_changed")
    transitions = {"intent": {"dispatched", "unknown", "failed"},
      "dispatched": {"commit-issued", "unknown", "failed"},
      "commit-issued": {"accepted", "unknown", "failed"},
      "accepted": {"completed", "unknown", "failed"}, "unknown": {"failed"},
      "failed": set(), "completed": set()}
    if phase != value["phase"] and phase not in transitions[value["phase"]]:
      raise conflict("work_receipt_transition_invalid")
    for key, item in ids.items():
      if value[key] is not None and value[key] != item:
        raise conflict("work_native_reference_changed")
      value[key] = item
    value["phase"] = phase
    if phase in ("commit-issued", "accepted", "completed") and any(value[key] is None
        for key in ("workspace_id", "pane_id", "terminal_id", "tab_id")):
      raise conflict()
    self._write("receipts", op, value)
    return value

  def _completed_binding(self, receipt):
    binding = self.load_binding(receipt["owner"])
    if binding is None or binding["epoch"] != receipt["epoch"] or binding["workspace_id"] != receipt["workspace_id"]:
      raise conflict("work_registration_not_durable")
    found = [instance for key, item in binding["types"].items() for locator, instance in item["instances"].items()
      if instance["op"] == receipt["op"] and key == receipt["type"] and locator == receipt["instance"]
        and instance["kind"] == receipt["kind"]]
    if len(found) != 1 or any(found[0][key] != receipt[key]
        for key in ("workspace_id", "pane_id", "terminal_id", "tab_id")):
      raise conflict("work_registration_not_durable")
    return binding

  def compact(self, op):
    """仅持久化绑定可证明已接收时删除瞬态记录；失败不清理未知意图。"""
    if not self.writable:
      raise conflict("work_state_read_only")
    receipt = self.read("receipts", op)
    if receipt is None or receipt["phase"] not in ("accepted", "completed"):
      raise conflict("work_registration_not_durable")
    self._completed_binding(receipt)
    if receipt["phase"] != "completed":
      self.update_receipt(op, "completed")
    with _io():
      for kind in ("intents", "receipts"):
        name = self._name(kind, op)
        before = self.tree.read(name, max_bytes=MAX_RECORD_BYTES)
        if before is not None:
          self.tree.replace(name, None, expected=before[2])


class GitState:
  """本地 Git 意图与结果；无端点、无配置正文、不自动清理或过期。"""
  def __init__(self, *, create=False):
    self.root = default_root() / "git"
    self.writable = create
    with _io():
      self.tree = Tree(self.root, create=create)

  def __enter__(self):
    return self

  def __exit__(self, *exc):
    self.tree.close()

  def _read(self, kind, op):
    if not re.fullmatch(r"[a-f0-9]{32}", op):
      raise conflict()
    with _io():
      result = self.tree.read(kind + "/" + op + ".json", max_bytes=MAX_RECORD_BYTES)
    if result is None:
      return None
    if result[1] != 0o600:
      raise conflict("work_private_state_unsafe")
    value = _decode(result[0])
    schema = (object_schema({"version": {"const": 1}, "op": HEX32, "facts": GIT_FACTS_SCHEMA,
      "fingerprint": HEX64}) if kind == "intents" else object_schema({"version": {"const": 1}, "op": HEX32,
      "fingerprint": HEX64, "phase": {"enum": ["intent", "dispatched", "completed", "unknown"]},
      "observation": nullable(object_schema({"path_exists": {"type": "boolean"}, "branch_oid": nullable(TEXT),
        "registered": {"type": "boolean"}})),
      "command_returncode": nullable({"type": "integer"})},
      ["version", "op", "fingerprint", "phase", "observation"]))
    if list(Draft202012Validator(schema).iter_errors(value)) or value["op"] != op:
      raise conflict("work_git_receipt_invalid")
    _validate_strings(value)
    if kind == "intents" and digest(value["facts"]) != value["fingerprint"]:
      raise conflict("work_git_receipt_invalid")
    if kind == "intents":
      for key in ("repo", "path", "common", "git_dir", "git_binary"):
        absolute(value["facts"][key])
    return value

  def records(self):
    names = set()
    with _io():
      for kind in ("intents", "receipts"):
        try:
          with self.tree.parent(kind + "/probe") as (parent, _):
            files = os.listdir(parent)
        except FileNotFoundError:
          continue
        if len(files) > MAX_RECORDS or any(not re.fullmatch(r"[a-f0-9]{32}\.json", name) for name in files):
          raise conflict("work_git_receipt_invalid")
        names.update(name[:-5] for name in files)
    result = []
    for op in sorted(names):
      intent, receipt = self._read("intents", op), self._read("receipts", op)
      if intent is None or (receipt is not None and receipt["fingerprint"] != intent["fingerprint"]):
        raise conflict("work_git_receipt_invalid")
      result.append({**intent, "phase": receipt["phase"] if receipt else "unknown",
        "observation": receipt["observation"] if receipt else None,
        "command_returncode": receipt.get("command_returncode") if receipt else None})
    return result

  def publish(self, op, facts):
    if not self.writable or list(Draft202012Validator(GIT_FACTS_SCHEMA).iter_errors(facts)):
      raise conflict("work_git_intent_invalid")
    if any(item["phase"] != "completed" and (item["facts"]["common"] == facts["common"] or
        item["facts"]["path"] == facts["path"]) for item in self.records()):
      raise conflict("work_git_recovery_required")
    with _io():
      self.tree.write_immutable("intents/" + op + ".json", json_bytes({"version": 1, "op": op,
        "facts": facts, "fingerprint": digest(facts)}))
      self.tree.write_immutable("receipts/" + op + ".json", json_bytes({"version": 1, "op": op,
        "fingerprint": digest(facts), "phase": "intent", "observation": None}))

  def update(self, op, phase, observation=None, *, command_returncode=None):
    value = self._read("receipts", op)
    if not self.writable or value is None or phase not in {
        "intent": {"dispatched"}, "dispatched": {"completed", "unknown"}, "unknown": set(), "completed": set()}[value["phase"]]:
      raise conflict("work_git_receipt_transition_invalid")
    if command_returncode is not None and type(command_returncode) is not int:
      raise conflict("work_git_receipt_invalid")
    value.update(phase=phase, observation=observation, command_returncode=command_returncode)
    with _io():
      name = "receipts/" + op + ".json"
      before = self.tree.read(name, max_bytes=MAX_RECORD_BYTES)
      self.tree.replace(name, json_bytes(value), expected=before[2])
