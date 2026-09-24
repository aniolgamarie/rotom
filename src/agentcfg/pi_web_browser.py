"""浏览器认证数据库只复制显式 profile；副本不进入普通命令输出或配置摘要。"""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path
import os
import json
import shutil
import re
import uuid

from .activity import digest
from .deployment import json_bytes
from .paths import configured_path, relative_path
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Tree, Conflict, identity


class BrowserSnapshots:
  def __init__(self, host, *, now=lambda: datetime.now(timezone.utc)):
    self.host = host
    self.now = now
    self.pending = {}
    self.root = host.root / "credential-cache/web-browser"

  def prepare(self, principal, args):
    closed(args, ("operation_id", "profile_id", "hosts"))
    manifest = self.host.manifest()
    if principal.role != "manager" or manifest.get("bootstrap") or "pi-web" not in manifest.get("plugins", []):
      raise Conflict("WEB_BROWSER_CONTEXT")
    if not isinstance(args["profile_id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", args["profile_id"]):
      raise ConfigError("pi-web-browser-profile")
    profile = manifest.get("web_browser_profiles", {}).get(args["profile_id"])
    if not profile: raise ConfigError("pi-web-browser-profile")
    if (not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200
        or not isinstance(args["hosts"], list) or not 1 <= len(args["hosts"]) <= 16
        or any(not isinstance(host, str) or host not in profile["allowed_hosts"] for host in args["hosts"])):
      raise Conflict("WEB_BROWSER_HOST_SCOPE")
    self.tick(scan=True)
    key = digest({"owner": self.host.store.owner, "request": args})
    if key in self.pending:
      if self.pending[key]["manifest_digest"] != digest(manifest): raise Conflict("WEB_BROWSER_STALE")
      return self.pending[key]["result"]
    if len(self.pending) >= 8: raise Conflict("WEB_BROWSER_CAPACITY")
    root = configured_path(profile["root"])
    relative = relative_path(profile["profile"]) / "Cookies"
    directory = uuid.uuid4().hex
    opened = []
    try:
      # 同时固定 DB/WAL/SHM 句柄；复制结束再一起核验，源文件不被 SQLite 打开或写入。
      with Tree(root, private=False) as source, Tree(self.root, create=True) as destination, ExitStack() as stack:
        destination.write_new(directory + "/owner.json", json_bytes({"schema_version": 1, "kind": "web-browser-snapshot",
          "instance_id": self.host.store.owner["instance_id"], "directory": directory, "expires_at": (self.now() + timedelta(seconds=300)).isoformat()}))
        for suffix in ("", "-wal", "-shm"):
          name = str(relative) + suffix
          try: stream, before = stack.enter_context(source.open_read(name, max_bytes=profile["max_bytes"]))
          except FileNotFoundError:
            if not suffix: raise Conflict("WEB_BROWSER_DATABASE_MISSING") from None
            opened.append((name, None)); continue
          if before.st_mode & 0o022: raise Conflict("WEB_BROWSER_DATABASE_WRITABLE")
          opened.append((name, identity(before)))
          if sum(item[1][3] for item in opened if item[1] is not None) > profile["max_bytes"]:
            raise Conflict("WEB_BROWSER_DATABASE_SIZE")
          with destination.parent(directory + "/" + name, create=True) as (fd, leaf):
            target = os.open(leaf, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=fd)
            with os.fdopen(target, "wb") as output:
              size = 0
              while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > before.st_size: raise Conflict("WEB_BROWSER_DATABASE_CHANGED")
                output.write(chunk)
              if size != before.st_size: raise Conflict("WEB_BROWSER_DATABASE_CHANGED")
              output.flush(); os.fsync(output.fileno())
        for name, expected in opened:
          with source.parent(name) as (fd, leaf):
            try: current = identity(os.stat(leaf, dir_fd=fd, follow_symlinks=False))
            except FileNotFoundError: current = None
          if current != expected: raise Conflict("WEB_BROWSER_DATABASE_CHANGED")
      if digest(self.host.manifest()) != digest(manifest): raise Conflict("WEB_BROWSER_STALE")
      result = {"snapshot_id": digest({"request": key, "directory": directory}), "directory": str(self.root / directory), "profile": profile["profile"], "browser": profile["browser"],
        "sidecars": [suffix for suffix in ("-wal", "-shm") if any(name.endswith(suffix) and value is not None for name, value in opened)]}
      self.pending[key] = {"directory": directory, "result": result, "manifest_digest": digest(manifest), "expires_at": self.now() + timedelta(seconds=300)}
      return result
    except Exception:
      self._remove(directory)
      raise

  def _remove(self, directory):
    if not shutil.rmtree.avoids_symlink_attacks: raise Conflict("WEB_BROWSER_CLEANUP_UNAVAILABLE")
    with Tree(self.root) as tree:
      if tree.fd is not None:
        try: shutil.rmtree(directory, dir_fd=tree.fd)
        except FileNotFoundError: pass

  def finish(self, principal, args):
    closed(args, ("snapshot_id",))
    if principal.role != "manager": raise Conflict("WEB_BROWSER_CONTEXT")
    if not isinstance(args["snapshot_id"], str) or not re.fullmatch(r"[0-9a-f]{64}", args["snapshot_id"]):
      raise ConfigError("pi-web-browser-snapshot")
    found = next(((key, value) for key, value in self.pending.items() if value["result"]["snapshot_id"] == args["snapshot_id"]), None)
    if found:
      key, record = found
      self._remove(record["directory"]); self.pending.pop(key)
    return {"released": True}

  def tick(self, *, scan=False):
    for key, record in list(self.pending.items()):
      if record["expires_at"] <= self.now():
        self._remove(record["directory"]); self.pending.pop(key)
    if not scan: return
    # 重启后只清理有本实例明确标记且过期的认证副本；没有标记的目录不自动认领。
    with Tree(self.root) as tree:
      if tree.fd is None: return
      active = {value["directory"] for value in self.pending.values()}
      for directory in os.listdir(tree.fd):
        if directory in active or not re.fullmatch(r"[0-9a-f]{32}", directory): continue
        raw = tree.read(directory + "/owner.json", max_bytes=4096)
        if raw is None: continue
        try:
          value = json.loads(raw[0])
          if (set(value) != {"schema_version", "kind", "instance_id", "directory", "expires_at"}
              or type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["kind"] != "web-browser-snapshot"
              or value["instance_id"] != self.host.store.owner["instance_id"] or value["directory"] != directory): continue
          expired = datetime.fromisoformat(value["expires_at"]) <= self.now()
        except (TypeError, ValueError): raise Conflict("WEB_BROWSER_CACHE_INVALID") from None
        if expired: self._remove(directory)
