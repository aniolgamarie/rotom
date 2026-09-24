"""ReadSeek 计算与文件提交的监督控制；复用普通命令租约，不创建第二个任务管理者。"""
import base64
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path

from .activity import digest, protected, valid_evidence
from .deployment import json_bytes
from .pi_guarded_files import GuardedFiles
from .pi_readseek_results import accept_result, ensure_mapping_unambiguous
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


class ReadseekController:
  def __init__(self, operations):
    self.operations = operations
    self.host = operations.host
    self.records = {}
    self.anchors = {}
    self.pending = {}
    self.active_sessions = {}

  def session_key(self, session, file_operation):
    return digest({"owner": self.host.store.owner, "session": session,
      "project": file_operation["grant"]["root_bindings"]["project"], "manifest": digest(self.host.manifest()),
      "ceiling": file_operation["ceiling"]})

  def bind(self, command, file_operation, *, session, tool, params, snapshot, home, permission_tool, read_operation="read"):
    """仅供监督器内部准入使用；RPC 不能自报路径、文件权限记录或快照。"""
    key = command["operation_id"]
    lease = self.host.store.read(command["lease_id"])
    if (key in self.records or file_operation["lease_id"] != command["lease_id"]
        or lease["state"] not in ("allocating", "running")
        or command["grant_generation"] != file_operation["grant"]["grant_generation"]
        or not isinstance(session, str) or not session or len(session) > 200):
      raise Conflict("READSEEK_BINDING_INVALID")
    if len(self.records) >= 128: raise Conflict("READSEEK_CAPACITY")
    session_key = self.session_key(session, file_operation)
    if any(row["session_key"] == session_key and row["state"] not in ("published", "discarded") for row in self.records.values()):
      raise Conflict("READSEEK_SESSION_BUSY")
    home = Path(home)
    if (home != self.host.root / "activity/readseek-homes" / key
        or Path(snapshot["snapshot_root"]) != Path(self.pending.get(key, {}).get("snapshot_root", home / "snapshot"))):
      raise Conflict("READSEEK_BINDING_INVALID")
    self.operations.policy(file_operation, reserved=True).current()
    ensure_mapping_unambiguous(snapshot, params)
    value = {"operation_id": key, "lease_id": lease["lease_id"], "generation": lease["grant_generation"],
      "manifest_digest": digest(self.host.manifest()), "session_key": session_key, "tool": tool,
      "params": deepcopy(params), "snapshot": deepcopy(snapshot), "home": str(home),
      "permission_tool": permission_tool, "read_operation": read_operation,
      "file_operation": deepcopy(file_operation), "state": "prepared", "expires_at": command["expires_at"],
      "anchors": deepcopy(self.anchors.get(session_key, {}))}
    self._persist(value)
    self.records[key] = value

  def _persist(self, value):
    # 通用状态不含工具参数、源码正文或模型返回正文；具体变更留在私人提交日志。
    record = {key: value[key] for key in ("operation_id", "lease_id", "generation", "manifest_digest", "session_key", "tool", "state")}
    for name in ("artifact_digest", "result_digest", "result_bytes"):
      if name in value: record[name] = value[name]
    record["request_digest"] = digest({"params": value["params"], "snapshot": value["snapshot"]})
    with Tree(self.host.root) as tree:
      tree.write_state("activity/readseek-operations/" + value["operation_id"] + ".json", json_bytes(record))

  def tick(self):
    for key, pending in list(self.pending.items()):
      if self.operations.now() < datetime.fromisoformat(pending["file_operation"]["grant"]["expires_at"]): continue
      lease = self.host.store.read(pending["ticket"]["lease_id"])
      if lease["state"] == "allocating" and not lease["spawn_committed"]:
        self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
      elif protected(lease):
        self.host.store.request_cancel(lease["lease_id"], self.host.store.owner)
        continue
      record = self.records.pop(key, None)
      if record:
        record["state"] = "discarded"; self._persist(record)
      self.pending.pop(key, None)
      if self.active_sessions.get(pending.get("session_key")) == key: self.active_sessions.pop(pending["session_key"], None)
      self.operations.inputs.pop(key, None)

  def _record(self, principal, key, *, running=False):
    if principal.role != "manager": raise Conflict("READSEEK_MANAGER_REQUIRED")
    value = self.records.get(key)
    if value is None: raise Conflict("READSEEK_OPERATION_UNKNOWN")
    lease = self.host.store.read(value["lease_id"])
    if (lease["grant_generation"] != value["generation"] or digest(self.host.manifest()) != value["manifest_digest"]
        or self.operations.now() >= datetime.fromisoformat(value["expires_at"])):
      raise Conflict("READSEEK_OPERATION_STALE")
    if running and (lease["state"] != "running" or self.host.store.processes.observe(lease["process_identity"]) != "alive"):
      raise Conflict("READSEEK_COMPUTE_NOT_RUNNING")
    return value, lease

  def accept(self, principal, args):
    closed(args, ("operation_id", "sha256", "bytes"))
    if (type(args["bytes"]) is not int or not 1 <= args["bytes"] <= 32 * 1024 * 1024
        or not isinstance(args["sha256"], str) or len(args["sha256"]) != 64
        or any(char not in "0123456789abcdef" for char in args["sha256"])):
      raise ConfigError("readseek-artifact-receipt")
    value, _ = self._record(principal, args["operation_id"], running=True)
    if value["state"] == "accepted":
      if value["artifact_digest"] != args["sha256"] or value["artifact_bytes"] != args["bytes"]:
        raise Conflict("READSEEK_OPERATION_CONFLICT")
      return {"accepted": True, "operation_id": value["operation_id"]}
    if value["state"] != "prepared": raise Conflict("READSEEK_ACCEPTANCE_INCOMPLETE")
    with Tree(Path(value["home"])) as tree: raw = tree.read("result.json", max_bytes=32 * 1024 * 1024)
    if not raw or len(raw[0]) != args["bytes"] or hashlib.sha256(raw[0]).hexdigest() != args["sha256"]:
      raise Conflict("READSEEK_ARTIFACT_CHANGED")
    try: output = json.loads(raw[0])
    except (ValueError, UnicodeError): raise Conflict("READSEEK_ARTIFACT_INVALID") from None
    value.update(state="accepting", artifact_digest=args["sha256"], artifact_bytes=args["bytes"])
    self._persist(value)
    try:
      files = GuardedFiles(self.operations.policy(value["file_operation"]), mutation=lambda *_: None,
        max_read_bytes=1024 * 1024 if value["file_operation"]["write"] else 16 * 1024 * 1024)
      accepted = accept_result(files, value["permission_tool"], value["snapshot"], value["tool"], value["params"], output,
        journal_root=self.host.root / "activity/readseek-mutations", operation_id=value["operation_id"],
        anchors=value["anchors"], read_operation=value["read_operation"])
      body = json_bytes(accepted["result"])
      if len(body) > 32 * 1024 * 1024: raise Conflict("READSEEK_RESULT_LIMIT")
      with Tree(self.host.root) as tree:
        tree.write_new("activity/readseek-results/" + value["operation_id"] + ".json", body)
      value.update(state="accepted", pending_anchors=accepted["anchors"],
        result_digest=hashlib.sha256(body).hexdigest(), result_bytes=len(body))
      self._persist(value)
      return {"accepted": True, "operation_id": value["operation_id"]}
    except Exception:
      value["state"] = "incomplete"
      self._persist(value)
      raise

  def finalize(self, principal, args):
    closed(args, ("operation_id",))
    value, lease = self._record(principal, args["operation_id"])
    if value["state"] not in ("accepted", "published"): raise Conflict("READSEEK_RESULT_UNACCEPTED")
    if protected(lease) or not valid_evidence(lease): raise Conflict("READSEEK_TERMINATION_UNKNOWN")
    with Tree(self.host.root) as tree: raw = tree.read("activity/exits/" + lease["lease_id"] + ".json")
    try: exit_record = json.loads(raw[0]) if raw else {}
    except ValueError: raise Conflict("READSEEK_EXIT_UNVERIFIED") from None
    if (exit_record.get("lease_id") != lease["lease_id"] or exit_record.get("process_identity") != lease["process_identity"]
        or type(exit_record.get("exit_code")) is not int or exit_record["exit_code"] != 0):
      raise Conflict("READSEEK_EXIT_UNVERIFIED")
    if value["state"] == "accepted":
      self.anchors[value["session_key"]] = deepcopy(value["pending_anchors"])
      value["state"] = "published"
      self._persist(value)
    return {"operation_id": value["operation_id"], "sha256": value["result_digest"], "bytes": value["result_bytes"], "termination_confirmed": True}

  def result(self, principal, args):
    closed(args, ("operation_id", "offset", "limit"))
    if type(args["offset"]) is not int or args["offset"] < 0 or type(args["limit"]) is not int or not 1 <= args["limit"] <= 65536:
      raise ConfigError("readseek-result-range")
    value, _ = self._record(principal, args["operation_id"])
    if value["state"] != "published": raise Conflict("READSEEK_RESULT_UNPUBLISHED")
    with Tree(self.host.root) as tree: raw = tree.read("activity/readseek-results/" + value["operation_id"] + ".json", max_bytes=32 * 1024 * 1024)
    if not raw or len(raw[0]) != value["result_bytes"] or hashlib.sha256(raw[0]).hexdigest() != value["result_digest"]:
      raise Conflict("READSEEK_RESULT_CHANGED")
    if args["offset"] > len(raw[0]): raise ConfigError("readseek-result-range")
    body = raw[0][args["offset"]:args["offset"] + args["limit"]]
    return {"data_b64": base64.b64encode(body).decode(), "offset": args["offset"],
      "bytes": value["result_bytes"], "sha256": value["result_digest"]}

  def discard(self, principal, args):
    closed(args, ("operation_id",))
    if principal.role != "manager": raise Conflict("READSEEK_MANAGER_REQUIRED")
    value = self.records.get(args["operation_id"])
    if value is None:
      pending = self.pending.get(args["operation_id"])
      if pending:
        lease = self.host.store.read(pending["ticket"]["lease_id"])
        if protected(lease) or not valid_evidence(lease): raise Conflict("READSEEK_TERMINATION_UNKNOWN")
        self.pending.pop(args["operation_id"])
        if self.active_sessions.get(pending.get("session_key")) == args["operation_id"]: self.active_sessions.pop(pending["session_key"], None)
        self.operations.inputs.pop(args["operation_id"], None)
      return {"discarded": True}
    lease = self.host.store.read(value["lease_id"])
    if protected(lease) or not valid_evidence(lease): raise Conflict("READSEEK_TERMINATION_UNKNOWN")
    value["state"] = "discarded"
    self._persist(value)
    self.records.pop(value["operation_id"])
    pending = self.pending.pop(value["operation_id"], None)
    if pending and self.active_sessions.get(pending.get("session_key")) == value["operation_id"]:
      self.active_sessions.pop(pending["session_key"], None)
    self.operations.inputs.pop(value["operation_id"], None)
    return {"discarded": True}

  def handle(self, principal, method, args):
    from .pi_readseek_prepare import prepare, stage, driver_export
    if method == "ordinary_readseek_prepare": return prepare(self, principal, args)
    if method == "ordinary_readseek_stage": return stage(self, principal, args)
    if method == "ordinary_readseek_export": return driver_export(self, principal, args)
    methods = {"ordinary_readseek_accept": self.accept, "ordinary_readseek_finalize": self.finalize,
      "ordinary_readseek_result": self.result, "ordinary_readseek_discard": self.discard}
    if method not in methods: raise ConfigError("readseek-control-method")
    return methods[method](principal, args)
