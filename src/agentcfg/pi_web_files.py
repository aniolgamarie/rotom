"""Web 本地媒体输入复用普通文件权限，再流式冻结到私有数据副本。"""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from .activity import digest, protected
from .deployment import json_bytes
from .pi_guarded_files import root_identity
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Tree, Conflict


class WebFiles:
  def __init__(self, operations, *, now=lambda: datetime.now(timezone.utc)):
    self.operations = operations
    self.host = operations.host
    self.now = now
    self.records = {}
    self.root = self.host.root / "activity/web-files"

  def prepare(self, principal, args):
    closed(args, ("operation_id", "cwd", "path"))
    manifest = self.host.manifest()
    if principal.role != "manager" or manifest.get("bootstrap") or "pi-web" not in manifest.get("plugins", []):
      raise Conflict("WEB_FILE_CONTEXT")
    if not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200: raise ConfigError("pi-operation-id")
    self.tick(scan=True)
    key = digest({"owner": self.host.store.owner, "request": args})
    if key in self.records: return self.summary(self.records[key])
    if len(self.records) >= 32: raise Conflict("WEB_FILE_CAPACITY")
    limit = manifest["options"].get("web", {}).get("media", {}).get("max_file_bytes", 128 * 1024 * 1024)
    base = self.operations.prepare(principal, {"operation_id": args["operation_id"], "role_id": "main", "cwd": args["cwd"],
      "tool_name": "read", "input": {"path": args["path"]}})
    directory = uuid.uuid4().hex
    expires_at = self.now() + timedelta(seconds=300)
    try:
      value = self.operations.record(base["operation_id"])
      policy = self.operations.policy(value)
      target = policy.authorize("read", "read", value["path"])
      sha = hashlib.sha256(); size = 0
      with Tree(target["root"], private=False) as source, source.open_read(target["relative_path"], max_bytes=limit) as (stream, before), Tree(self.root, create=True) as output:
        output.write_new(directory + "/owner.json", json_bytes(self.marker(directory, expires_at, [])))
        with output.parent(directory + "/input", create=True) as (fd, name):
          out = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o400, dir_fd=fd)
          with os.fdopen(out, "wb") as destination:
            while chunk := stream.read(1024 * 1024):
              size += len(chunk)
              if size > limit: raise Conflict("WEB_FILE_LIMIT")
              sha.update(chunk); destination.write(chunk)
            if size != before.st_size: raise Conflict("WEB_FILE_CHANGED")
            destination.flush(); os.fsync(destination.fileno())
      policy.authorize("read", "read", value["path"])
      if digest(self.host.manifest()) != digest(manifest): raise Conflict("WEB_FILE_STALE")
      result = {"file_id": digest({"request": key, "directory": directory}), "directory": str(self.root / directory),
        "path": value["path"], "size": size, "sha256": sha.hexdigest()}
      self.records[key] = {"result": result, "directory": directory, "manifest_digest": digest(manifest), "commands": [],
        "expires_at": expires_at, "root_identity": root_identity(self.root / directory),
        "source_roots": value["grant"]["root_bindings"]}
      return result
    except Exception:
      self._remove(directory)
      raise
    finally:
      self.operations.inputs.pop(base["operation_id"], None)

  def summary(self, record):
    if record["manifest_digest"] != digest(self.host.manifest()) or record["expires_at"] <= self.now(): raise Conflict("WEB_FILE_STALE")
    if record["root_identity"] != root_identity(record["result"]["directory"]): raise Conflict("WEB_FILE_CHANGED")
    return record["result"]

  def record(self, file_id):
    if not isinstance(file_id, str): raise ConfigError("pi-web-file-id")
    value = next((row for row in self.records.values() if row["result"]["file_id"] == file_id), None)
    if value is None: raise Conflict("WEB_FILE_UNKNOWN")
    self.summary(value)
    return value

  def verify(self, file_id):
    row = self.record(file_id); checksum = hashlib.sha256(); size = 0
    with Tree(Path(row["result"]["directory"])) as tree, tree.open_read("input", max_bytes=row["result"]["size"]) as (stream, _):
      while chunk := stream.read(1024 * 1024): checksum.update(chunk); size += len(chunk)
    if size != row["result"]["size"] or checksum.hexdigest() != row["result"]["sha256"]: raise Conflict("WEB_FILE_CHANGED")
    return row

  def _remove(self, directory):
    if not shutil.rmtree.avoids_symlink_attacks: raise Conflict("WEB_FILE_CLEANUP_UNAVAILABLE")
    with Tree(self.root) as tree:
      if tree.fd is not None:
        try: shutil.rmtree(directory, dir_fd=tree.fd)
        except FileNotFoundError: pass

  def marker(self, directory, expires_at, commands):
    return {"schema_version": 1, "kind": "web-file-snapshot", "instance_id": self.host.store.owner["instance_id"],
      "directory": directory, "expires_at": expires_at.isoformat(), "commands": list(commands)}

  def link_command(self, record, lease_id):
    # 先持久登记租约，再允许命令发布；重启清理不能早于物理终止证明。
    if lease_id in record["commands"]: return
    commands = [*record["commands"], lease_id]
    with Tree(self.root) as tree:
      tree.write_state(record["directory"] + "/owner.json", json_bytes(self.marker(record["directory"], record["expires_at"], commands)))
    record["commands"] = commands

  def releasable(self, commands):
    for lease_id in commands:
      try:
        if protected(self.host.store.read(lease_id)): return False
      except (Conflict, FileNotFoundError): return False
    return True

  def tick(self, *, scan=False):
    for key, record in list(self.records.items()):
      if record["expires_at"] <= self.now() and self.releasable(record["commands"]):
        if record["root_identity"] != root_identity(record["result"]["directory"]): raise Conflict("WEB_FILE_CHANGED")
        self._remove(record["directory"]); self.records.pop(key)
    if not scan: return
    with Tree(self.root) as tree:
      if tree.fd is None: return
      active = {row["directory"] for row in self.records.values()}
      for directory in os.listdir(tree.fd):
        if directory in active or not re.fullmatch(r"[0-9a-f]{32}", directory): continue
        raw = tree.read(directory + "/owner.json", max_bytes=65536)
        if raw is None: continue
        try:
          value = json.loads(raw[0])
          if (set(value) != {"schema_version", "kind", "instance_id", "directory", "expires_at", "commands"}
              or type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "web-file-snapshot"
              or value["instance_id"] != self.host.store.owner["instance_id"] or value["directory"] != directory): continue
          if not isinstance(value["commands"], list) or len(value["commands"]) > 128 or any(not isinstance(item, str) for item in value["commands"]):
            raise ValueError()
          expired = datetime.fromisoformat(value["expires_at"]) <= self.now()
        except (ValueError, TypeError): raise Conflict("WEB_FILE_CACHE_INVALID") from None
        if expired and self.releasable(value["commands"]): self._remove(directory)

  def finish(self, principal, args):
    closed(args, ("file_id",))
    if principal.role != "manager": raise Conflict("WEB_FILE_CONTEXT")
    if not isinstance(args["file_id"], str): raise ConfigError("pi-web-file-id")
    found = next(((key, row) for key, row in self.records.items() if row["result"]["file_id"] == args["file_id"]), None)
    if found:
      key, row = found
      for lease_id in row["commands"]:
        if protected(self.host.store.read(lease_id)): raise Conflict("WEB_FILE_EXECUTION_PROTECTED")
      self._remove(row["directory"]); self.records.pop(key)
    return {"released": True}
