"""批次只调用 Pi 已有管理者端点；无端点时拒绝，不 fork 单 run 兜底。"""

import argparse
import json
import os
from pathlib import Path
import socket
import stat
import sys
import uuid
import re

from .model_delegate import control_envelope
from .model_delegate_cli import Arguments, DelegateFailure, instance_binding
from .pi_control import read_frame
from .schema import ConfigError
from .storage import Conflict, Tree


def call(instance, method, args):
  instance, binding = instance_binding(instance)
  root = instance / "pi-home/model-delegate/manager"
  with Tree(root) as tree:
    raw = tree.read("control.json")
  if raw is None or raw[1] != 0o600:
    from .process import DependencyError
    raise DependencyError("没有可用批次管理者；不能用独立runner分叉替代")
  try:
    record = json.loads(raw[0])
  except (ValueError, UnicodeError):
    raise Conflict("DELEGATE_BATCH_ENDPOINT") from None
  if (not isinstance(record, dict) or set(record) != {"schema_version", "instance_id", "manager_activation_id", "socket", "socket_identity", "capability"}
      or record["schema_version"] != 2 or not isinstance(record["capability"], str) or not re.fullmatch(r"[a-f0-9]{64}", record["capability"])
      or not isinstance(record["socket"], str) or not Path(record["socket"]).is_absolute()
      or not isinstance(record["manager_activation_id"], str) or not 1 <= len(record["manager_activation_id"]) <= 200):
    raise Conflict("DELEGATE_BATCH_ENDPOINT")
  from .activity import digest
  if record["instance_id"] != digest({"instance": str(instance), "binding": binding["binding"]}):
    raise Conflict("DELEGATE_BATCH_INSTANCE")
  path = Path(record["socket"])
  info, parent = path.lstat(), path.parent.lstat()
  if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077
      or not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid() or parent.st_mode & 0o077
      or {"device": str(info.st_dev), "inode": str(info.st_ino)} != record["socket_identity"]):
    raise Conflict("DELEGATE_BATCH_ENDPOINT")
  raw = (json.dumps({"capability": record["capability"], "method": method, "args": args}, separators=(",", ":")) + "\n").encode()
  if len(raw) > 1024 * 1024:
    raise ConfigError("delegate-batch-too-large")
  with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
    connection.settimeout(30); connection.connect(str(path))
    from .pi_control import peer_uid
    if peer_uid(connection) != os.geteuid(): raise Conflict("DELEGATE_BATCH_ENDPOINT")
    with connection.makefile("rwb") as stream:
      stream.write(raw); stream.flush(); reply = read_frame(stream)
  if reply.get("ok") is not True:
    raise DelegateFailure(reply.get("exit_code"))
  result = reply.get("result")
  if (set(reply) != {"ok", "result"} or not isinstance(result, dict)
      or set(result) != {"batch_id", "dispatch_ids", "result_refs", "state"} or result["batch_id"] != args["batch_id"]
      or result["state"] not in {"starting", "running", "completed", "canceled", "partial"}
      or any(not isinstance(result[field], list) or len(result[field]) > 32 or any(not isinstance(value, str) or not value for value in result[field]) for field in ("dispatch_ids", "result_refs"))):
    raise Conflict("DELEGATE_BATCH_RESPONSE")
  return result


def main(argv=None):
  parser = Arguments(prog="run-model-fanout", allow_abbrev=False)
  parser.add_argument("action", choices=("submit", "status", "cancel"))
  parser.add_argument("--instance", type=Path, required=True)
  parser.add_argument("--batch-id", required=True)
  parser.add_argument("--input", type=Path)
  args = parser.parse_args(argv)
  if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args.batch_id): raise ConfigError("delegate-batch-id")
  request = {"batch_id": args.batch_id}
  if args.action == "submit":
    if args.input is None:
      raise ConfigError("delegate-batch-input-required")
    with Tree(args.input.absolute().parent, private=False) as tree:
      document = tree.read(args.input.name, max_bytes=1024 * 1024)
    try:
      request["items"] = json.loads(document[0]) if document else None
    except (ValueError, UnicodeError):
      raise ConfigError("delegate-batch-items") from None
    if not isinstance(request["items"], list) or not 1 <= len(request["items"]) <= 32:
      raise ConfigError("delegate-batch-items")
  elif args.input is not None:
    raise ConfigError("delegate-batch-unexpected-input")
  result = call(args.instance, args.action, request)
  # 完整响应保留在私人实例；默认只输出有界控制摘要。
  from .activity import digest
  from .deployment import json_bytes
  with Tree(args.instance / "pi-home/model-delegate/batch-results", create=True) as tree:
    key = digest(args.batch_id) + ".json"
    tree.write_state(key, json_bytes(result))
  result["artifact_ref"] = "batch-result-" + digest(args.batch_id)
  sys.stdout.buffer.write(control_envelope(result))
  return 0
