"""Pi与Codex受控工具共享逐动作文件准入；没有独立管理者或shell通道。"""

import base64
import hashlib
import json
from pathlib import Path
import re

from .activity import digest
from .deployment import json_bytes
from .pi_guarded_files import FilePolicy, GuardedFiles
from .pi_supervisor import closed
from .pi_worker_files import snapshot
from .schema import ConfigError
from .storage import Conflict, Tree


def file_action(controller, principal, args):
  closed(args, ("run_id", "lease_id", "grant_generation", "operation_id", "action"))
  value = controller.input(args["run_id"]); request = value["request"]
  if (principal.role != "worker" or principal.lease_id != request["lease_id"] or args["lease_id"] != request["lease_id"]
      or args["grant_generation"] != request["grant_generation"]):
    raise Conflict("DELEGATE_FILE_IDENTITY")
  if not isinstance(args["operation_id"], str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,200}", args["operation_id"]):
    raise ConfigError("delegate-operation-id")
  host = controller.host
  lease = host.store.read(request["lease_id"])
  if lease["state"] != "running" or lease["grant_generation"] != request["grant_generation"]:
    raise Conflict("DELEGATE_GRANT_REVOKED")
  grant = value["grant"]; manifest = host.manifest()
  if digest(manifest["permission_policy"]) != request["policy_digest"]:
    raise Conflict("DELEGATE_POLICY_CHANGED")
  writing = request["backend"] == "codex" and request["execution_mode"] == "delegate-write" and request["mode"] == "implement"
  if not writing and request["execution_mode"] != "delegate-readonly":
    raise Conflict("DELEGATE_TOOL_READONLY")
  def verify(current_grant, _metadata):
    current = host.store.read(lease["lease_id"])
    return current["state"] == "running" and current["grant_generation"] == current_grant["grant_generation"]
  def writer(root, current_grant):
    if not writing or root != "project": return False
    identity = host.store.workspaces.identify(grant["root_bindings"]["project"]["path"])
    current = host.store.workspaces.read(identity)
    return bool(current and current["state"] == "active" and current["execution_lease_id"] == lease["lease_id"]
      and current["grant_generation"] == current_grant["grant_generation"])
  policy = FilePolicy(policy=manifest["permission_policy"], roots=grant["root_bindings"],
    ceiling={"allowed_tools": grant["allowed_tools"], "read_roots": ["project"], "write_roots": ["project"] if writing else []},
    grant=grant, mode=request["execution_mode"], verify=verify, workspace=writer, secret_roots=host.config.get("protected_roots", []),
    readonly_roots=manifest["options"].get("permissions", {}).get("readonly_roots", []),
    denied_roots=manifest["options"].get("permissions", {}).get("denied_roots", []))
  def mutation(phase, detail):
    if not writing: raise Conflict("DELEGATE_TOOL_READONLY")
    return record_mutation(controller, request, args["operation_id"], phase, detail)
  files = GuardedFiles(policy, mutation=mutation)
  action = args["action"]
  closed(action, ("tool_id", "operation", "path"), ("offset", "limit", "query", "kind", "data_b64", "expected_digest", "destination"))
  tool, operation, path = action["tool_id"], action["operation"], action["path"]
  if operation == "read":
    closed(action, ("tool_id", "operation", "path", "offset", "limit"))
    offset, limit = action["offset"], action["limit"]
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 65536: raise ConfigError("delegate-read-range")
    data = files.read(tool, path)
    if offset > len(data): raise ConfigError("delegate-read-range")
    target = policy.authorize(tool, operation, path)
    return {"data_b64": base64.b64encode(data[offset:offset + limit]).decode(), "offset": offset, "total_bytes": len(data),
      "content_digest": hashlib.sha256(data).hexdigest(), "root_ref": target["root_ref"], "relative_path": target["relative_path"]}
  if operation == "list":
    closed(action, ("tool_id", "operation", "path")); return {"entries": files.list(tool, path)}
  if operation == "search":
    closed(action, ("tool_id", "operation", "path", "query", "kind")); return files.search(tool, path, action["query"], action["kind"])
  if not writing: raise Conflict("DELEGATE_TOOL_READONLY")
  if operation == "write":
    closed(action, ("tool_id", "operation", "path", "data_b64", "expected_digest"))
    if action["expected_digest"] is not None and (not isinstance(action["expected_digest"], str) or not re.fullmatch(r"[a-f0-9]{64}", action["expected_digest"])):
      raise ConfigError("delegate-content-digest")
    try: data = base64.b64decode(action["data_b64"], validate=True)
    except (ValueError, TypeError): raise ConfigError("delegate-file-content") from None
    return files.write(tool, path, data, expected_digest=action["expected_digest"])
  if operation == "rename":
    closed(action, ("tool_id", "operation", "path", "destination")); return files.rename(tool, path, action["destination"])
  raise ConfigError("delegate-file-operation")


def verify_mutations(root, request, candidate_digest):
  """终态与离线读取均重放全部变更凭证；没有日志只能证明工作区未变。"""
  import os
  try:
    with Tree(Path(root) / "mutations" / request["run_id"]) as tree:
      names = sorted(os.listdir(tree.fd)) if tree.fd is not None else []
      if not names:
        if candidate_digest != request["candidate_digest"]: raise ValueError()
        return {"sequence": 0, "candidate_digest": candidate_digest}
      raw = tree.read("head.json")
      if raw is None or raw[1] != 0o600 or len(names) > 10001: raise ValueError()
      head = json.loads(raw[0])
      closed(head, ("state", "candidate_digest", "sequence"))
      if head["state"] != "settled" or type(head["sequence"]) is not int or head["sequence"] != len(names) - 1:
        raise ValueError()
      records = []
      for name in names:
        if name == "head.json": continue
        if not re.fullmatch(r"[a-f0-9]{64}\.json", name): raise ValueError()
        raw = tree.read(name)
        if raw is None or raw[1] != 0o600: raise ValueError()
        record = json.loads(raw[0])
        closed(record, ("schema_version", "state", "lease_id", "request_digest", "operation_id", "sequence", "before_digest", "after_digest", "mutation"))
        if (record["schema_version"] != 1 or record["state"] != "settled" or type(record["sequence"]) is not int
            or record["lease_id"] != request["lease_id"] or record["request_digest"] != request["request_digest"]
            or not isinstance(record["operation_id"], str) or digest(record["operation_id"]) + ".json" != name):
          raise ValueError()
        records.append(record)
      current = request["candidate_digest"]
      for sequence, record in enumerate(sorted(records, key=lambda row: row["sequence"]), 1):
        if record["sequence"] != sequence or record["before_digest"] != current: raise ValueError()
        current = record["after_digest"]
      if current != head["candidate_digest"] or current != candidate_digest: raise ValueError()
      return {"sequence": head["sequence"], "candidate_digest": current}
  except (ValueError, TypeError, KeyError, OSError, ConfigError):
    raise Conflict("DELEGATE_MUTATION_UNVERIFIED") from None


def record_mutation(controller, request, operation_id, phase, detail):
  """文件与显式派生命令共用一个串行变更日志。调用方已持监督服务锁。"""
  operation_key = digest(operation_id)
  current = snapshot(request["cwd"], protected_roots=controller.host.config.get("protected_roots", []))
  with Tree(controller.root) as tree:
    head_path = "mutations/" + request["run_id"] + "/head.json"
    path = "mutations/" + request["run_id"] + "/" + operation_key + ".json"
    raw = tree.read(head_path)
    head = json.loads(raw[0]) if raw else {"state": "settled", "candidate_digest": request["candidate_digest"], "sequence": 0}
    if phase == "prepare":
      if head["state"] != "settled" or current != head["candidate_digest"]: raise Conflict("DELEGATE_MUTATION_UNSETTLED")
      if tree.read(path) is not None: raise Conflict("DELEGATE_OPERATION_REPLAY")
      record = {"schema_version": 1, "state": "prepared", "lease_id": request["lease_id"], "request_digest": request["request_digest"],
        "operation_id": operation_id, "sequence": head["sequence"] + 1, "before_digest": current, "mutation": detail}
      tree.write_immutable(path, json_bytes(record)); tree.write_state(head_path, json_bytes({**head, "state": "prepared", "operation_id": operation_key}))
    elif phase == "settle":
      raw = tree.read(path)
      if raw is None or head.get("operation_id") != operation_key or head["state"] != "prepared" or detail.get("ticket") != operation_key:
        raise Conflict("DELEGATE_MUTATION_UNSETTLED")
      record = json.loads(raw[0])
      if record["mutation"] != {key: value for key, value in detail.items() if key != "ticket"}:
        raise Conflict("DELEGATE_MUTATION_UNSETTLED")
      record.update(state="settled", after_digest=current)
      tree.write_state(path, json_bytes(record)); tree.write_state(head_path, json_bytes({"state": "settled", "candidate_digest": current, "sequence": record["sequence"]}))
    else: raise ConfigError("delegate-mutation-phase")
  return operation_key
