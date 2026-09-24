"""监督者内的受管文件操作；工作区租约、权限快照和写入日志由同一控制者核验。"""

import base64
import hashlib
import json
import os
import re
from pathlib import Path
import stat

from .activity import digest
from .deployment import json_bytes
from .pi_guarded_files import FilePolicy, GuardedFiles, root_identity
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree
from .paths import relative_path


def snapshot(root, *, protected_roots=(), source_paths=None):
  """候选内容身份；只读目录句柄，不跟随软链接，也不读取 Git 管理目录。"""
  entries = []
  root = Path(root)
  protected = tuple(path for value in protected_roots if (path := Path(value).resolve(strict=False)) == root or root in path.parents)
  if source_paths is not None:
    with Tree(root, private=False) as tree:
      for name in sorted(set(source_paths)):
        path = relative_path(name)
        if ".git" in path.parts:
          raise Conflict("SNAPSHOT_SCOPE_INVALID")
        absolute = root / path
        if any(absolute == value or value in absolute.parents for value in protected):
          continue
        try:
          with tree.parent(name) as (parent, leaf):
            info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
              entries.append({"path": name, "kind": "symlink", "target": os.readlink(leaf, dir_fd=parent)})
              continue
          raw = tree.read(name)
          if raw is None:
            raise FileNotFoundError()
          entries.append({"path": name, "kind": "file", "sha256": hashlib.sha256(raw[0]).hexdigest(), "executable": raw[1] & 0o111})
        except FileNotFoundError:
          entries.append({"path": name, "kind": "missing"})
    return digest({"schema_version": 1, "files": entries})
  with Tree(Path(root), private=False) as tree:
    def visit(fd, prefix):
      for name in sorted(os.listdir(fd)):
        if name == ".git":
          continue
        relative = prefix + name
        absolute = root / relative
        if any(absolute == value or value in absolute.parents for value in protected):
          entries.append({"path": relative, "kind": "protected"})
          continue
        before = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISDIR(before.st_mode):
          child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
          try:
            opened = os.fstat(child)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
              raise Conflict("SNAPSHOT_CHANGED")
            visit(child, relative + "/")
          finally:
            os.close(child)
        elif stat.S_ISREG(before.st_mode) and before.st_nlink == 1:
          file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
          try:
            opened = os.fstat(file)
            if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
              raise Conflict("SNAPSHOT_CHANGED")
            value = hashlib.sha256()
            while chunk := os.read(file, 1024 * 1024):
              value.update(chunk)
            after = os.fstat(file)
            if (opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
              raise Conflict("SNAPSHOT_CHANGED")
            entries.append({"path": relative, "kind": "file", "sha256": value.hexdigest(), "executable": before.st_mode & 0o111})
          finally:
            os.close(file)
        elif stat.S_ISLNK(before.st_mode):
          entries.append({"path": relative, "kind": "symlink", "target": os.readlink(name, dir_fd=fd)})
        else:
          raise Conflict("SNAPSHOT_UNSUPPORTED_FILE")
    if tree.fd is None:
      raise Conflict("ROOT_IDENTITY")
    visit(tree.fd, "")
  return digest({"schema_version": 1, "files": entries})


def source_scope(instance_root, cwd):
  base = Path(instance_root) / "pi-home/task-keeper"
  worktrees = base / "worktrees"
  cwd = Path(cwd).resolve(strict=True)
  if not cwd.is_relative_to(worktrees):
    return None
  job_id = cwd.relative_to(worktrees).parts[0]
  with Tree(base) as tree:
    raw = tree.read("workspace-protection/" + job_id + ".json")
  if raw is None:
    raise Conflict("SNAPSHOT_SCOPE_MISSING")
  value = json.loads(raw[0])
  if value.get("schema_version") != 1 or Path(value["candidate_root"]) != worktrees / job_id:
    raise Conflict("SNAPSHOT_SCOPE_INVALID")
  paths = []
  for name in set(value["files"]) | set(value.get("owned_paths", [])):
    path = Path(value["candidate_root"]) / relative_path(name)
    if path.is_relative_to(cwd):
      paths.append(path.relative_to(cwd).as_posix())
  return paths


class WorkerFiles:
  def __init__(self, store, manifest, instance_root, *, protected_roots=()):
    self.store, self.manifest, self.instance_root = store, manifest, Path(instance_root)
    self.protected_roots = tuple(protected_roots) + (self.instance_root, store.root)

  def __call__(self, lease, operation_id, action):
    with Tree(self.store.root) as state:
      raw = state.read("activity/inputs/" + lease["lease_id"] + ".json")
    if raw is None:
      raise Conflict("WORKER_INPUT_MISSING")
    payload = json.loads(raw[0])
    descriptor, context = payload["descriptor"], payload["context"]
    current = self.manifest()
    role = current["role_bindings"].get(descriptor["role_id"])
    if (not role or role["managed"] is not True or digest(current["permission_policy"]) != lease["policy_digest"]
        or descriptor["policy_digest"] != lease["policy_digest"] or descriptor["grant_generation"] != lease["grant_generation"]
        or descriptor["allocation_id"] != lease["allocation_id"] or descriptor["attempt_id"] != lease["attempt_id"]
        or descriptor["allowed_tools"] != role["tools"] or descriptor["provider_id"] != role["model"]["provider"]
        or descriptor["model_id"] != role["model"]["model"]):
      raise Conflict("WORKER_BINDING_MISMATCH")
    roots = context["root_bindings"]
    declared = current["options"].get("paths", {}).get("roots", {})
    for name, binding in roots.items():
      expected = descriptor["cwd"] if name == "project" else declared.get(name, {}).get("path")
      if expected is None or Path(binding["path"]) != Path(expected).resolve(strict=True) or root_identity(binding["path"]) != binding["identity"]:
        raise Conflict("ROOT_IDENTITY")
    def live(grant, metadata):
      value = self.store.read(lease["lease_id"])
      return value["state"] == "running" and value["grant_generation"] == grant["grant_generation"]
    def writer(root_ref, grant):
      path = str(Path(roots[root_ref]["path"]).resolve(strict=True))
      for planned in lease["planned_workspaces"]:
        if not Path(path).is_relative_to(Path(planned["worktree_path"])):
          continue
        record = self.store.workspaces.read(planned)
        return bool(record and record["execution_lease_id"] == lease["lease_id"] and record["state"] == "active"
          and record["grant_generation"] == lease["grant_generation"] and record["holder_nonce"] == lease["owner_nonce"])
      return False
    permissions = current["options"].get("permissions", {})
    policy = FilePolicy(policy=current["permission_policy"], roots=roots, ceiling={key: role[key] if key != "allowed_tools" else role["tools"]
      for key in ("allowed_tools", "read_roots", "write_roots")}, grant=descriptor, mode="managed", verify=live, workspace=writer,
      inherited_denials=descriptor["inherited_denials"], readonly_roots=permissions.get("readonly_roots", []),
      denied_roots=permissions.get("denied_roots", []), secret_roots=[path for path in self.protected_roots if Path(path) not in (self.instance_root, self.store.root)],
      private_roots=[self.instance_root, self.store.root], source_checkout=descriptor["source_cwd"])
    closed(action, ("tool_id", "operation", "path"), ("destination", "data_b64", "expected_digest", "offset", "limit", "query", "kind"))
    if any(not isinstance(action[key], str) or not action[key] or "\0" in action[key] for key in ("tool_id", "operation", "path")):
      raise ConfigError("pi-file-action")
    if "destination" in action and (not isinstance(action["destination"], str) or not action["destination"] or "\0" in action["destination"]):
      raise ConfigError("pi-file-action")
    if action["path"].startswith("artifact:") and action["operation"] != "read":
      raise ConfigError("pi-artifact-read-only")
    key = "activity/file-actions/" + lease["lease_id"] + "/" + operation_id + ".json"
    head_key = "activity/file-actions/" + lease["lease_id"] + "/head.json"
    request_digest = digest(action)
    mutating = action["operation"] in ("write", "rename")
    if mutating:
      with Tree(self.store.root) as state:
        existing = state.read(key)
      if existing:
        record = json.loads(existing[0])
        if record["request_digest"] != request_digest or record["state"] != "settled":
          raise Conflict("FILE_OPERATION_UNKNOWN")
        policy.current()
        return record["result"]
    pending = None
    def mutation(phase, detail):
      nonlocal pending
      if phase == "prepare":
        with Tree(self.store.root) as state:
          head_raw = state.read(head_key)
        head = json.loads(head_raw[0]) if head_raw else {"schema_version": 1, "sequence": 0, "operation_id": None,
          "state": "settled", "snapshot": lease["candidate_digest"]}
        current_snapshot = snapshot(descriptor["cwd"], protected_roots=self.protected_roots, source_paths=source_scope(self.instance_root, descriptor["cwd"]))
        if head["state"] != "settled" or current_snapshot != head["snapshot"]:
          raise Conflict("MUTATION_CHAIN_UNKNOWN")
        pending = {"schema_version": 1, "operation_id": operation_id, "request_digest": request_digest, "state": "prepared",
          "lease_id": lease["lease_id"], "grant_generation": lease["grant_generation"], "mutation": detail,
          "before_snapshot": current_snapshot, "sequence": head["sequence"] + 1, "previous_operation_id": head["operation_id"]}
        with Tree(self.store.root) as state:
          state.write_immutable(key, json_bytes(pending))
          state.write_state(head_key, json_bytes({**head, "state": "prepared", "operation_id": operation_id}))
        return operation_id
      if pending is None or detail["ticket"] != operation_id:
        raise Conflict("MUTATION_INTENT_MISSING")
      scope = source_scope(self.instance_root, descriptor["cwd"])
      if scope is not None:
        base = self.instance_root / "pi-home/task-keeper"
        job_id = Path(descriptor["cwd"]).relative_to(base / "worktrees").parts[0]
        with Tree(base) as tree:
          scope_key = "workspace-protection/" + job_id + ".json"
          record = json.loads(tree.read(scope_key)[0])
          names = [detail["relative_path"]]
          if detail["operation"] == "rename":
            names.append(detail["destination_path"])
          actual = [(Path(descriptor["cwd"]) / name).relative_to(Path(record["candidate_root"])).as_posix() for name in names]
          record["owned_paths"] = sorted(set(record.get("owned_paths", [])) | set(actual))
          tree.write_state(scope_key, json_bytes(record))
        scope = source_scope(self.instance_root, descriptor["cwd"])
      pending["after_snapshot"] = snapshot(descriptor["cwd"], protected_roots=self.protected_roots, source_paths=scope)
      return operation_id
    files = GuardedFiles(policy, mutation=mutation)
    operation, tool, path = action["operation"], action["tool_id"], action["path"]
    if operation == "read":
      closed(action, ("tool_id", "operation", "path", "offset", "limit"))
      offset, limit = action["offset"], action["limit"]
      if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 65536:
        raise ConfigError("pi-read-range")
      if isinstance(path, str) and path.startswith("artifact:"):
        if tool != "tk_read" or tool not in descriptor["allowed_tools"]:
          raise Conflict("PERMISSION_DENIED")
        artifact_id = path[len("artifact:"):]
        artifact = context["artifacts"].get(artifact_id)
        if artifact_id not in descriptor["allowed_artifact_ids"] or artifact is None or not re.fullmatch(r"artifact-[a-f0-9]{64}", artifact_id):
          raise Conflict("ARTIFACT_SCOPE_MISMATCH")
        closed(artifact, ("id", "jobId", "snapshot", "contentDigest", "bytes", "source"))
        if artifact["id"] != artifact_id or artifact["jobId"] != descriptor["task_id"] or artifact["source"] not in ("runtime", "verifier", "claim"):
          raise Conflict("ARTIFACT_SCOPE_MISMATCH")
        policy.current()
        with Tree(self.instance_root / "pi-home/task-keeper") as artifacts:
          content_record = artifacts.read("artifacts/" + artifact_id, max_bytes=16 * 1024 * 1024)
        if content_record is None or len(content_record[0]) != artifact["bytes"] or hashlib.sha256(content_record[0]).hexdigest() != artifact["contentDigest"]:
          raise Conflict("ARTIFACT_CHANGED")
        content = content_record[0]
        metadata = {"artifact_id": artifact_id, "artifact_source": artifact["source"], "artifact_snapshot": artifact["snapshot"]}
      else:
        content = files.read(tool, path)
        target = policy.authorize(tool, "read", path)
        end = min(len(content), offset + limit)
        first_line = content[:offset].count(b"\n") + 1 + int(offset > 0 and content[offset - 1:offset] != b"\n")
        last_line = content[:end].count(b"\n") + int(end == len(content) and bool(content) and content[-1:] != b"\n")
        metadata = {"root_ref": target["root_ref"], "relative_path": target["relative_path"], "first_line": first_line, "last_line": last_line}
      if offset > len(content):
        raise ConfigError("pi-read-range")
      return {"data_b64": base64.b64encode(content[offset:offset + limit]).decode(), "offset": offset,
        "total_bytes": len(content), "content_digest": hashlib.sha256(content).hexdigest(), **metadata}
    if operation == "list":
      closed(action, ("tool_id", "operation", "path"))
      return {"entries": files.list(tool, path)}
    if operation == "search":
      closed(action, ("tool_id", "operation", "path", "query", "kind"))
      return files.search(tool, path, action["query"], action["kind"])
    if operation == "write":
      closed(action, ("tool_id", "operation", "path", "data_b64", "expected_digest"))
      try:
        content = base64.b64decode(action["data_b64"], validate=True)
      except (ValueError, TypeError):
        raise ConfigError("pi-file-content") from None
      result = files.write(tool, path, content, expected_digest=action["expected_digest"])
    elif operation == "rename":
      closed(action, ("tool_id", "operation", "path", "destination"))
      result = files.rename(tool, path, action["destination"])
    else:
      raise ConfigError("pi-file-operation")
    if pending is None or "after_snapshot" not in pending:
      raise Conflict("FILE_OPERATION_UNKNOWN")
    result = {**result, "candidate_digest": pending["after_snapshot"], "mutation_sequence": pending["sequence"]}
    pending.update(state="settled", result=result)
    with Tree(self.store.root) as state:
      state.write_state(key, json_bytes(pending))
      state.write_state(head_key, json_bytes({"schema_version": 1, "state": "settled", "operation_id": operation_id,
        "sequence": pending["sequence"], "snapshot": pending["after_snapshot"]}))
    return result


def mutation_chain(store, lease, cwd, *, protected_roots=(), source_paths=None):
  """结果接受时独立重建链；缺记录、分叉、未结 IO 或外部漂移都不构成证明。"""
  directory = store.root / "activity/file-actions" / lease["lease_id"]
  initial = lease["candidate_digest"]
  expected, previous, sequence = initial, None, 0
  with Tree(directory) as tree:
    if tree.fd is not None:
      records = []
      for name in os.listdir(tree.fd):
        if name == "head.json":
          continue
        raw = tree.read(name)
        if raw is None or not name.endswith(".json"):
          raise Conflict("MUTATION_CHAIN_UNKNOWN")
        value = json.loads(raw[0])
        if value.get("state") != "settled" or value.get("lease_id") != lease["lease_id"]:
          raise Conflict("MUTATION_CHAIN_UNKNOWN")
        records.append(value)
      for value in sorted(records, key=lambda item: item["sequence"]):
        if (value["sequence"] != sequence + 1 or value["previous_operation_id"] != previous
            or value["before_snapshot"] != expected or value["grant_generation"] > lease["grant_generation"]):
          raise Conflict("MUTATION_CHAIN_UNKNOWN")
        expected, previous, sequence = value["after_snapshot"], value["operation_id"], value["sequence"]
      head_raw = tree.read("head.json")
      head = json.loads(head_raw[0]) if head_raw else None
      if records and (not head or head.get("state") != "settled" or head.get("sequence") != sequence
          or head.get("snapshot") != expected or head.get("operation_id") != previous):
        raise Conflict("MUTATION_CHAIN_UNKNOWN")
  if snapshot(cwd, protected_roots=protected_roots, source_paths=source_paths) != expected:
    raise Conflict("SNAPSHOT_STALE")
  return {"mutation_chain_verified": True, "initial_candidate_digest": initial, "candidate_digest": expected,
    "mutations": sequence}
