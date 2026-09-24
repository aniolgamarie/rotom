"""普通会话的持久代码快照；受控文件IO、预览CAS和跨实例写租约。"""

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import uuid

from .activity import digest, protected
from .deployment import json_bytes
from .paths import relative_path
from .pi_guarded_files import FilePolicy, root_identity
from .pi_supervisor import SpawnCommand, closed
from .process import environment, DependencyError
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


class Checkpoints:
  def __init__(self, host):
    self.host = host
    self.root = Path(host.config["instance_root"]) / "pi-home/checkpoints"
    self.records = {}

  def scope(self, principal, args):
    if principal.role != "manager": raise Conflict("CHECKPOINT_MANAGER_REQUIRED")
    for key in ("session_id", "cwd"):
      if not isinstance(args[key], str) or not args[key] or len(args[key]) > 4096: raise ConfigError("checkpoint-identity")
    manifest = self.host.manifest()
    if "git-checkpoint" not in manifest.get("resource_ids", {}).get("extensions", {}): raise Conflict("CHECKPOINT_NOT_SELECTED")
    options = manifest["options"]; config = options.get("checkpoints")
    if not config or not config.get("paths"): raise ConfigError("checkpoint-scope-required")
    cwd = Path(args["cwd"]).resolve(strict=True)
    declared = options.get("paths", {}).get("roots", {})
    projects = [Path(row["path"]).resolve(strict=True) for row in declared.values()
      if row["purpose"] == "project" and cwd.is_relative_to(Path(row["path"]).resolve(strict=True))]
    if len(projects) != 1: raise ConfigError("checkpoint-project-required")
    project = projects[0]
    roots = {key: {"path": str(Path(row["path"]).resolve(strict=True)), "identity": root_identity(row["path"])} for key, row in declared.items()}
    roots["project"] = {"path": str(project), "identity": root_identity(project)}
    paths = sorted({"." if name == "." else relative_path(name).as_posix() for name in config["paths"]})
    if any(".git" in Path(name).parts for name in paths): raise ConfigError("checkpoint-private-scope")
    workspace = self.host.store.workspaces.identify(project)
    scope = {"project": str(project), "roots": roots, "paths": paths, "policy_digest": digest(manifest["permission_policy"]),
      "configuration_digest": self.configuration(manifest), "runtime_identity": self.host.runtime_root.name, "git_dir_identity": workspace["git_dir_identity"], "session_id": args["session_id"],
      "max_checkpoints": config.get("max_checkpoints", 100), "max_files": config.get("max_files", 2000), "max_bytes": config.get("max_bytes", 32 * 1024 * 1024)}
    scope["scope_digest"] = digest(self.scope_identity(scope))
    return scope, workspace

  @staticmethod
  def configuration(manifest):
    options = manifest["options"]
    return digest({"paths": options.get("paths"), "permissions": options.get("permissions"), "checkpoint_paths": options.get("checkpoints", {}).get("paths")})

  @staticmethod
  def scope_identity(scope):
    return {key: value for key, value in scope.items() if key not in {"scope_digest", "max_files", "max_bytes", "max_checkpoints"}}

  def policy(self, scope, lease, *, preview=False, expires_at=None):
    manifest = self.host.manifest()
    if self.configuration(manifest) != scope["configuration_digest"] or digest(manifest["permission_policy"]) != scope["policy_digest"]: raise Conflict("CHECKPOINT_POLICY_CHANGED")
    now = datetime.now(timezone.utc)
    grant = {"schema_version": 1, "grant_id": lease["lease_id"], "operation_id": lease["execution_id"], "instance_id": lease["instance_id"],
      "issuer_activation_id": lease["supervisor_activation_id"], "execution_mode": "ordinary", "allowed_tools": ["read", "ls", "write", "edit"],
      "root_bindings": scope["roots"], "grant_generation": lease["grant_generation"], "issued_at": now.isoformat(), "expires_at": expires_at or (now + timedelta(seconds=120)).isoformat()}
    grant["grant_digest"] = digest(grant)
    def verify(_grant, _metadata):
      current = self.host.store.read(lease["lease_id"])
      return (current["state"] == "running" and current["grant_generation"] == lease["grant_generation"]
        and self.configuration(self.host.manifest()) == scope["configuration_digest"]
        and digest(self.host.manifest()["permission_policy"]) == scope["policy_digest"])
    def writer(root, _grant):
      if preview or root != "project": return False
      planned = self.host.store.workspaces.identify(scope["project"])
      held = self.host.store.workspaces.read(planned)
      return bool(held and held["state"] == "active" and held["execution_lease_id"] == lease["lease_id"] and held["grant_generation"] == lease["grant_generation"])
    limits = manifest["options"].get("permissions", {})
    return FilePolicy(policy=manifest["permission_policy"], roots=scope["roots"],
      ceiling={"allowed_tools": grant["allowed_tools"], "read_roots": ["project"], "write_roots": [] if preview else ["project"]},
      grant=grant, mode="ordinary", verify=verify, workspace=writer, readonly_roots=limits.get("readonly_roots", []),
      denied_roots=limits.get("denied_roots", []), secret_roots=[*self.host.config.get("protected_roots", []), self.root] if self.root.exists() else self.host.config.get("protected_roots", []))

  def scan(self, scope, policy):
    files, total = {}, 0
    project = Path(scope["project"])
    def hidden(path):
      return any(part.casefold() in {".git", ".ssh", ".pi", ".codex", "auth.json", ".env"} or part.casefold().startswith(".env.") for part in path.parts)
    with Tree(project, private=False) as tree:
      def visit(name):
        nonlocal total
        if hidden(Path(name)): return
        path = project / name
        if not path.exists() and not path.is_symlink(): return
        try:
          policy.authorize("ls", "list", str(path))
        except Conflict as error:
          if str(error) == "PERMISSION_DENIED": return
          raise
        if name == ".":
          children = sorted(os.listdir(tree.fd))
        else:
          with tree.parent(name) as (parent, leaf):
            try: info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError: return
            if stat.S_ISDIR(info.st_mode):
              fd = os.open(leaf, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
              try: children = sorted(os.listdir(fd))
              finally: os.close(fd)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and not info.st_mode & 0o7000:
              try: policy.authorize("read", "read", str(path))
              except Conflict as error:
                if str(error) == "PERMISSION_DENIED": return
                raise
              if info.st_size > 1024 * 1024: raise Conflict("CHECKPOINT_FILE_TOO_LARGE")
              raw = tree.read(name, max_bytes=1024 * 1024)
              if raw is None: raise Conflict("CHECKPOINT_CHANGED")
              if name in files: return
              total += len(raw[0])
              if name not in files and (len(files) >= scope["max_files"] or total > scope["max_bytes"]): raise Conflict("CHECKPOINT_LIMIT")
              files[name] = {"data": base64.b64encode(raw[0]).decode(), "mode": raw[1], "sha256": hashlib.sha256(raw[0]).hexdigest()}
              return
            else: raise Conflict("CHECKPOINT_UNSUPPORTED_ENTRY")
        for child in children: visit(child if name == "." else name + "/" + child)
      for path in scope["paths"]: visit(path)
    return files

  def save(self, scope, files, *, entry_id=None, reason="turn"):
    checkpoint = uuid.uuid4().hex
    value = {"schema_version": 1, "checkpoint_id": checkpoint, "scope": scope, "files": files, "entry_id": entry_id,
      "reason": reason, "created_at": datetime.now(timezone.utc).isoformat()}
    value["snapshot_digest"] = digest(value)
    with Tree(self.root, create=True) as tree:
      if sum(name.endswith(".json") for name in os.listdir(tree.fd)) >= scope["max_checkpoints"]: raise Conflict("CHECKPOINT_STORAGE_FULL")
      meta = {key: item for key, item in value.items() if key != "files"}
      meta["files_count"] = len(files)
      meta["metadata_digest"] = digest(meta)
      tree.write_immutable("objects/" + checkpoint + ".json", json_bytes(value))
      tree.write_immutable(checkpoint + ".json", json_bytes(meta))
    return checkpoint

  def load(self, checkpoint, scope):
    from .paths import safe_id
    safe_id(checkpoint)
    with Tree(self.root) as tree: raw = tree.read("objects/" + checkpoint + ".json", max_bytes=64 * 1024 * 1024)
    if raw is None: raise Conflict("CHECKPOINT_NOT_FOUND")
    value = json.loads(raw[0])
    if value.get("snapshot_digest") != digest({key: item for key, item in value.items() if key != "snapshot_digest"}) or self.scope_identity(value["scope"]) != self.scope_identity(scope):
      raise Conflict("CHECKPOINT_SCOPE_CHANGED")
    closed(value, ("schema_version", "checkpoint_id", "scope", "files", "entry_id", "reason", "created_at", "snapshot_digest"))
    if value["schema_version"] != 1 or value["checkpoint_id"] != checkpoint or not isinstance(value["files"], dict): raise Conflict("CHECKPOINT_CORRUPT")
    total = 0
    for name, item in value["files"].items():
      relative_path(name)
      if not any(base == "." or name == base or name.startswith(base + "/") for base in scope["paths"]): raise Conflict("CHECKPOINT_CORRUPT")
      if any(part.casefold() in {".git", ".ssh", ".pi", ".codex", "auth.json", ".env"} or part.casefold().startswith(".env.") for part in Path(name).parts): raise Conflict("CHECKPOINT_CORRUPT")
      closed(item, ("data", "mode", "sha256"))
      if type(item["mode"]) is not int or not 0 <= item["mode"] <= 0o777: raise Conflict("CHECKPOINT_CORRUPT")
      try: body = base64.b64decode(item["data"], validate=True)
      except (ValueError, TypeError): raise Conflict("CHECKPOINT_CORRUPT") from None
      total += len(body)
      if len(body) > 1024 * 1024 or hashlib.sha256(body).hexdigest() != item["sha256"]: raise Conflict("CHECKPOINT_CORRUPT")
    if len(value["files"]) > scope["max_files"] or total > scope["max_bytes"]: raise Conflict("CHECKPOINT_CORRUPT")
    return value

  def preview(self, principal, args):
    closed(args, ("session_id", "cwd", "checkpoint_id"))
    scope, _ = self.scope(principal, args)
    target = self.load(args["checkpoint_id"], scope)
    current = self.scan(scope, self.policy(scope, self.host.store.read(principal.lease_id), preview=True))
    changes = self.changes(current, target["files"])
    return {"checkpoint_id": args["checkpoint_id"], "before_digest": digest(current), "scope_digest": scope["scope_digest"],
      "write_count": sum(kind == "write" for _, kind in changes), "delete_count": sum(kind == "delete" for _, kind in changes)}

  @staticmethod
  def changes(current, target):
    return [(name, "delete" if name not in target else "write") for name in sorted(set(current) | set(target)) if current.get(name) != target.get(name)]

  def prepare(self, principal, args):
    closed(args, ("operation_id", "session_id", "cwd", "operation"), ("entry_id", "checkpoint_id", "before_digest", "scope_digest"))
    if not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200: raise ConfigError("checkpoint-identity")
    if "entry_id" in args and (not isinstance(args["entry_id"], str) or not 1 <= len(args["entry_id"]) <= 200): raise ConfigError("checkpoint-identity")
    if args["operation"] not in ("capture", "restore"): raise ConfigError("checkpoint-operation")
    if args["operation"] == "capture" and any(key in args for key in ("checkpoint_id", "before_digest", "scope_digest")):
      raise ConfigError("checkpoint-action-fields")
    if args["operation"] == "restore" and "entry_id" in args: raise ConfigError("checkpoint-action-fields")
    scope, workspace = self.scope(principal, args)
    key = digest([self.host.store.owner, args["operation_id"]])
    if key in self.records: raise Conflict("CHECKPOINT_ALREADY_DISPATCHED")
    if len(self.records) >= 128: raise Conflict("CHECKPOINT_CAPACITY")
    if args["operation"] == "restore":
      if args.get("scope_digest") != scope["scope_digest"] or not isinstance(args.get("before_digest"), str): raise Conflict("CHECKPOINT_PREVIEW_REQUIRED")
      self.load(args.get("checkpoint_id", ""), scope)
    lease = self.host.store.allocate(kind="external", execution_id="checkpoint-" + key, task_id=None, attempt_id=key,
      lock_identity=self.host.config["lock_identity"], slice_identity=self.host.config["slice_identity"], policy_digest=scope["policy_digest"],
      candidate_digest=None, planned_workspaces=[workspace])
    record = {"operation_id": key, "lease_id": lease["lease_id"], "request": args, "scope": scope,
      "generation": lease["grant_generation"], "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat()}
    try:
      with Tree(self.host.root) as tree: tree.write_immutable("activity/checkpoint-operations/" + key + ".json", json_bytes(record))
      self.records[key] = record
    except Exception:
      self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner); raise
    return {"operation_id": key, "lease_id": lease["lease_id"], "kind": "checkpoint", "tool_name": "checkpoint", "write": True, "timeout_seconds": 120}

  def command(self, lease, payload):
    closed(payload, ("operation_id",))
    record = self.records.get(payload["operation_id"])
    if (not record or lease["lease_id"] != record["lease_id"] or lease["grant_generation"] != record["generation"]
        or datetime.now(timezone.utc) >= datetime.fromisoformat(record["expires_at"]) or self.configuration(self.host.manifest()) != record["scope"]["configuration_digest"] or digest(self.host.manifest()["permission_policy"]) != record["scope"]["policy_digest"]):
      raise Conflict("CHECKPOINT_STALE")
    declaration = {"entrypoint": "supervisor/scripts/pi-checkpoint.py", "kind": "external", "engine": "python"}
    with Tree(self.host.runtime_root) as tree:
      raw = tree.read("runtime/commands.json")
    if not raw or json.loads(raw[0]).get("programs", {}).get("checkpoint") != declaration or lease["kind"] != "external":
      raise DependencyError("代码快照监督入口未登记")
    entry = self.host.runtime_root / declaration["entrypoint"]
    if not entry.is_file() or entry.is_symlink(): raise DependencyError("代码快照监督入口缺失")
    home = self.host.root / "activity/checkpoint-homes" / lease["lease_id"]; ensure_private(home)
    env = environment(home=home)
    env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(self.host.server.endpoint), AGENTCFG_SUPERVISOR_CAPABILITY=self.host.service.issue_capability("worker", lease["lease_id"]))
    return SpawnCommand((sys.executable, "-B", "-I", str(entry), "--operation", record["operation_id"]), Path(record["scope"]["project"]), env)

  def perform(self, principal, args):
    closed(args, ("operation_id",))
    record = self.records.get(args["operation_id"])
    if not record or principal.role != "worker" or principal.lease_id != record["lease_id"]: raise Conflict("CHECKPOINT_WORKER_REQUIRED")
    lease = self.host.store.read(record["lease_id"])
    if lease["state"] != "running" or lease["grant_generation"] != record["generation"] or datetime.now(timezone.utc) >= datetime.fromisoformat(record["expires_at"]):
      raise Conflict("CHECKPOINT_STALE")
    if record.get("performed"): raise Conflict("CHECKPOINT_ALREADY_DISPATCHED")
    record["performed"] = True
    scope, request = record["scope"], record["request"]
    policy = self.policy(scope, lease, expires_at=record["expires_at"])
    current = self.scan(scope, policy)
    if request["operation"] == "capture":
      result = {"status": "completed", "checkpoint_id": self.save(scope, current, entry_id=request.get("entry_id")), "files": len(current)}
    else:
      if digest(current) != request["before_digest"]: raise Conflict("CHECKPOINT_PREVIEW_STALE")
      target = self.load(request["checkpoint_id"], scope)["files"]
      changes = self.changes(current, target)
      # 所有动作先准入；缺delete/create权限不能执行一半才发现。
      for name, kind in changes:
        path = str(Path(scope["project"]) / name)
        policy.authorize("edit" if kind == "delete" else "write", kind, path)
        if kind == "write" and name not in current: policy.authorize("write", "create", path)
      backup = self.save(scope, current, reason="before-restore")
      result = {"status": "completed", "checkpoint_id": request["checkpoint_id"], "backup_id": backup, "changed": 0}
      try:
        with Tree(Path(scope["project"]), private=False) as tree:
          for name, kind in changes:
            old = tree.read(name, max_bytes=1024 * 1024)
            observed = {"data": base64.b64encode(old[0]).decode(), "mode": old[1], "sha256": hashlib.sha256(old[0]).hexdigest()} if old else None
            if observed != current.get(name): raise Conflict("CHECKPOINT_CHANGED")
            data = base64.b64decode(target[name]["data"], validate=True) if kind == "write" else None
            if kind == "write" and hashlib.sha256(data).hexdigest() != target[name]["sha256"]: raise Conflict("CHECKPOINT_CORRUPT")
            path = str(Path(scope["project"]) / name)
            policy.authorize("edit" if kind == "delete" else "write", kind, path)
            if kind == "write" and old is None:
              policy.authorize("write", "create", path)
              parent = Path(name).parent
              while parent != Path("."):
                if not (Path(scope["project"]) / parent).exists(): policy.authorize("write", "create", str(Path(scope["project"]) / parent))
                parent = parent.parent
            tree.replace(name, data, target[name]["mode"] if data is not None else 0o600, expected=old[2] if old else None)
            result["changed"] += 1
      except Exception:
        result.update(status="partial", error_code="CHECKPOINT_RESTORE_INTERRUPTED")
    with Tree(self.host.root) as tree:
      tree.write_immutable("activity/ordinary-results/" + record["operation_id"] + ".json", json_bytes({"operation_id": record["operation_id"], "lease_id": lease["lease_id"], "result": result}))
    return result

  def list(self, principal, args):
    closed(args, ("session_id", "cwd"), ("entry_id",))
    if "entry_id" in args and (not isinstance(args["entry_id"], str) or not 1 <= len(args["entry_id"]) <= 200): raise ConfigError("checkpoint-identity")
    scope, _ = self.scope(principal, args)
    rows = []
    with Tree(self.root) as tree:
      for name in sorted(os.listdir(tree.fd)) if tree.fd is not None else []:
        if name == "objects": continue
        if not name.endswith(".json"): raise Conflict("CHECKPOINT_STORAGE_UNKNOWN")
        value = json.loads(tree.read(name, max_bytes=1024 * 1024)[0])
        if value.get("metadata_digest") != digest({key: item for key, item in value.items() if key != "metadata_digest"}) or value.get("checkpoint_id") != name[:-5]:
          raise Conflict("CHECKPOINT_CORRUPT")
        if self.scope_identity(value.get("scope", {})) != self.scope_identity(scope) or "entry_id" in args and value.get("entry_id") != args["entry_id"]: continue
        rows.append({key: value[key] for key in ("checkpoint_id", "entry_id", "reason", "created_at")})
    return {"checkpoints": sorted(rows, key=lambda row: row["created_at"], reverse=True)[:200]}

  def tick(self):
    for key, record in list(self.records.items()):
      if datetime.now(timezone.utc) < datetime.fromisoformat(record["expires_at"]): continue
      lease = self.host.store.read(record["lease_id"])
      if lease["state"] == "allocating" and not lease["spawn_committed"]: self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
      elif protected(lease):
        self.host.store.request_cancel(lease["lease_id"], self.host.store.owner); continue
      self.records.pop(key)
