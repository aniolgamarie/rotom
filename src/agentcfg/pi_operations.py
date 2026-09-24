"""普通工具的显式操作授权；写入使用受监督的一次性 helper 和共享工作区租约。"""

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import os
import stat
import sys

from .activity import digest
from .deployment import json_bytes
from .paths import relative_path
from .pi_guarded_files import FilePolicy, GuardedFiles, root_identity
from .pi_supervisor import SpawnCommand, closed
from .process import environment
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


class OrdinaryOperations:
  def __init__(self, host, *, now=lambda: datetime.now(timezone.utc)):
    self.host = host
    self.inputs = {}
    self.now = now
    from .pi_commands import OrdinaryCommands
    self.commands = OrdinaryCommands(host)
    from .pi_checkpoints import Checkpoints
    self.checkpoints = Checkpoints(host)
    from .pi_readseek import ReadseekController
    self.readseek = ReadseekController(self)
    from .pi_web_browser import BrowserSnapshots
    self.web_browser = BrowserSnapshots(host)
    from .pi_web_files import WebFiles
    self.web_files = WebFiles(self)

  def prepare(self, principal, args):
    closed(args, ("operation_id", "role_id", "cwd", "tool_name", "input"))
    if principal.role != "manager":
      raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    self.tick()
    if len(self.inputs) >= 128:
      raise Conflict("ORDINARY_OPERATION_CAPACITY")
    if not isinstance(args["operation_id"], str) or not args["operation_id"] or len(args["operation_id"]) > 200:
      raise ConfigError("pi-operation-id")
    name, payload = args["tool_name"], args["input"]
    fields = {"read": (("path",), ("offset", "limit")), "write": (("path", "content"), ()), "edit": (("path", "edits"), ()), "rename": (("path", "destination"), ()), "ls": ((), ("path", "limit")),
      "find": (("pattern",), ("path", "limit")), "grep": (("pattern",), ("path", "glob", "ignoreCase", "literal", "context", "limit"))}
    if name not in fields:
      raise ConfigError("pi-operation-tool-not-supported")
    closed(payload, *fields[name])
    payload = {**payload, "path": payload.get("path", ".")}
    if not isinstance(payload["path"], str) or not payload["path"] or "\0" in payload["path"]:
      raise ConfigError("pi-operation-path")
    manifest = self.host.manifest()
    cwd = Path(args["cwd"]).resolve(strict=True)
    path = Path(payload["path"])
    if not path.is_absolute(): path = cwd / path
    if name == "read" and args["role_id"] == "main" and ".." not in path.parts:
      from .pi_resource_reads import selected_resource
      resource = selected_resource(self.host, manifest, path)
      if resource is not None:
        return self.prepare_resource(principal, args, payload, path, resource, manifest)
    declared = manifest["options"].get("paths", {}).get("roots", {})
    projects = [Path(row["path"]).resolve(strict=True) for row in declared.values() if row["purpose"] == "project" and cwd.is_relative_to(Path(row["path"]).resolve(strict=True))]
    if len(projects) != 1:
      raise ConfigError("pi-operation-project-required")
    roots = {key: {"path": str(Path(row["path"]).resolve(strict=True)), "identity": root_identity(row["path"])} for key, row in declared.items()}
    roots["project"] = {"path": str(projects[0]), "identity": root_identity(projects[0])}
    if args["role_id"] == "main":
      ceiling = {"allowed_tools": ["read", "write", "edit", "rename", "ls", "find", "grep"], "read_roots": list(roots),
        "write_roots": [key for key, row in declared.items() if row["purpose"] in ("project", "write")]}
      if "project" not in ceiling["write_roots"]: ceiling["write_roots"].append("project")
    else:
      role = manifest["role_bindings"].get(args["role_id"])
      if not role or role["managed"] or name not in role["tools"]:
        raise Conflict("ORDINARY_ROLE_CEILING")
      ceiling = {"allowed_tools": role["tools"], "read_roots": role["read_roots"], "write_roots": role["write_roots"]}
    key = digest({"owner": self.host.store.owner, "operation_id": args["operation_id"]})
    existing = self.inputs.get(key)
    if existing:
      if existing["request_digest"] != digest(args): raise Conflict("ORDINARY_OPERATION_CONFLICT")
      return self.summary(existing)
    write = name in ("write", "edit", "rename")
    planned = []
    path = Path(payload["path"])
    if not path.is_absolute(): path = cwd / path
    targets = [path]
    if name == "rename":
      if not isinstance(payload["destination"], str) or not payload["destination"] or "\0" in payload["destination"]:
        raise ConfigError("pi-operation-path")
      destination = Path(payload["destination"])
      if not destination.is_absolute(): destination = cwd / destination
      targets.append(destination)
    if write:
      for target in targets:
        matching = [row for key, row in roots.items() if key in ceiling["write_roots"] and target.is_relative_to(Path(row["path"]))]
        if not matching: raise Conflict("PERMISSION_DENIED")
        workspace = self.host.store.workspaces.identify(max(matching, key=lambda row: len(row["path"]))["path"])
        if not any(row["workspace_key"] == workspace["workspace_key"] for row in planned): planned.append(workspace)
    lease = self.host.store.allocate(kind="external", execution_id="operation-" + key, task_id=None, attempt_id=key,
      lock_identity=self.host.config["lock_identity"], slice_identity=self.host.config["slice_identity"], policy_digest=digest(manifest["permission_policy"]),
      candidate_digest=None, planned_workspaces=planned) if write else self.host.store.read(principal.lease_id)
    grant = {"schema_version": 1, "grant_id": key, "operation_id": args["operation_id"], "instance_id": lease["instance_id"],
      "issuer_activation_id": lease["supervisor_activation_id"], "execution_mode": "ordinary", "allowed_tools": ceiling["allowed_tools"],
      "root_bindings": roots, "grant_generation": lease["grant_generation"], "issued_at": self.now().isoformat(),
      "expires_at": (self.now() + timedelta(seconds=300)).isoformat()}
    grant["grant_digest"] = digest(grant)
    record = {"schema_version": 1, "operation_id": key, "request_digest": digest(args), "lease_id": lease["lease_id"],
      "tool_name": name, "path": str(path), "grant": grant, "ceiling": ceiling, "policy_digest": digest(manifest["permission_policy"]), "write": write}
    if name == "rename": record["destination"] = str(destination)
    try:
      policy = self.policy(record, reserved=True)
      if name == "edit": policy.authorize(name, "read", str(path))
      for target in targets:
        policy.authorize(name, "rename" if name == "rename" else "write" if write else "list" if name == "ls" else "search" if name in ("find", "grep") else "read", str(target))
      with Tree(self.host.root) as tree:
        tree.write_immutable("activity/ordinary-operations/" + key + ".json", json_bytes(record))
      # 文件正文只在当前监督进程内存中传递，不写进通用执行日志或摘要。
      record["input"] = deepcopy(payload)
      self.inputs[key] = record
      return self.summary(record)
    except Exception:
      if write: self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
      raise

  def summary(self, value):
    return {"operation_id": value["operation_id"], "lease_id": value["lease_id"], "write": value["write"], "path": value["path"], "request_digest": value["request_digest"]}

  def prepare_resource(self, principal, args, payload, path, resource, manifest):
    key = digest({"owner": self.host.store.owner, "operation_id": args["operation_id"]})
    if key in self.inputs:
      if self.inputs[key]["request_digest"] != digest(args): raise Conflict("ORDINARY_OPERATION_CONFLICT")
      return self.summary(self.inputs[key])
    lease = self.host.store.read(principal.lease_id)
    root = Path(resource["path"])
    if not root.is_dir(): root = root.parent
    grant = {"schema_version": 1, "grant_id": key, "operation_id": args["operation_id"], "instance_id": lease["instance_id"],
      "issuer_activation_id": lease["supervisor_activation_id"], "execution_mode": "ordinary", "allowed_tools": ["read"],
      "root_bindings": {"resource": {"path": str(root), "identity": root_identity(root)}}, "grant_generation": lease["grant_generation"],
      "issued_at": self.now().isoformat(), "expires_at": (self.now() + timedelta(seconds=300)).isoformat()}
    grant["grant_digest"] = digest(grant)
    record = {"schema_version": 1, "operation_id": key, "request_digest": digest(args), "lease_id": lease["lease_id"], "tool_name": "read",
      "path": str(path), "write": False, "resource": resource, "grant": grant, "policy_digest": digest(manifest["permission_policy"])}
    with Tree(self.host.root) as tree: tree.write_immutable("activity/ordinary-operations/" + key + ".json", json_bytes(record))
    record["input"] = deepcopy(payload); self.inputs[key] = record
    return self.summary(record)

  def record(self, operation_id):
    value = self.inputs.get(operation_id)
    if value is None: raise Conflict("ORDINARY_OPERATION_UNKNOWN")
    if self.now() >= datetime.fromisoformat(value["grant"]["expires_at"]): raise Conflict("GRANT_STALE")
    return value

  def tick(self):
    self.readseek.tick()
    self.web_browser.tick()
    self.web_files.tick()
    self.commands.tick()
    self.checkpoints.tick()
    from .activity import protected
    for key, value in list(self.inputs.items()):
      if self.now() < datetime.fromisoformat(value["grant"]["expires_at"]): continue
      if value["write"]:
        lease = self.host.store.read(value["lease_id"])
        if lease["state"] == "allocating" and not lease["spawn_committed"]:
          self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
        elif protected(lease):
          self.host.store.request_cancel(lease["lease_id"], self.host.store.owner)
          continue
      self.inputs.pop(key)

  def policy(self, value, *, reserved=False):
    manifest = self.host.manifest()
    if digest(manifest["permission_policy"]) != value["policy_digest"]: raise Conflict("PERMISSION_STALE")
    lease = self.host.store.read(value["lease_id"])
    def verify(grant, _metadata):
      current = self.host.store.read(lease["lease_id"])
      return current["state"] in (("allocating", "running") if reserved else ("running",)) and current["grant_generation"] == grant["grant_generation"]
    def writer(root, grant):
      path = Path(grant["root_bindings"][root]["path"])
      for planned in lease["planned_workspaces"]:
        if path.is_relative_to(Path(planned["worktree_path"])):
          record = self.host.store.workspaces.read(planned)
          return bool(record and record["execution_lease_id"] == lease["lease_id"] and record["grant_generation"] == grant["grant_generation"]
            and record["state"] in (("reserved", "active") if reserved else ("active",)))
      return False
    options = manifest["options"].get("permissions", {})
    return FilePolicy(policy=manifest["permission_policy"], roots=value["grant"]["root_bindings"], ceiling=value["ceiling"], grant=value["grant"], mode="ordinary",
      verify=verify, workspace=writer, readonly_roots=options.get("readonly_roots", []), denied_roots=options.get("denied_roots", []),
      secret_roots=self.host.config.get("protected_roots", []))

  def metadata(self, principal, args):
    closed(args, ("operation_id",))
    if principal.role != "manager": raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    value = self.record(args["operation_id"])
    if value["tool_name"] != "read" or "resource" in value:
      raise Conflict("ORDINARY_METADATA_NOT_BOUND")
    return GuardedFiles(self.policy(value), mutation=lambda *_: None).metadata("read", value["path"])

  def read(self, principal, args):
    closed(args, ("operation_id", "offset", "limit"), ("relative_path",))
    if principal.role != "manager": raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    value = self.record(args["operation_id"])
    if type(args["offset"]) is not int or args["offset"] < 0 or type(args["limit"]) is not int or not 1 <= args["limit"] <= 65536:
      raise ConfigError("pi-operation-read-range")
    if "resource" in value:
      from .pi_resource_reads import read_resource, selected_resource
      lease = self.host.store.read(value["lease_id"])
      manifest = self.host.manifest()
      if ("relative_path" in args or lease["state"] != "running" or lease["grant_generation"] != value["grant"]["grant_generation"]
          or digest(manifest["permission_policy"]) != value["policy_digest"]
          or selected_resource(self.host, manifest, Path(value["path"])) != value["resource"]):
        raise Conflict("RESOURCE_ADMISSION_STALE")
      content = read_resource(self.host, value)
      if args["offset"] > len(content): raise ConfigError("pi-operation-read-range")
      return {"data_b64": base64.b64encode(content[args["offset"]:args["offset"] + args["limit"]]).decode(),
        "total_bytes": len(content), "content_digest": hashlib.sha256(content).hexdigest()}
    # edit在实际子进程开始前读取基线，只有之后的写入才进入active写租约。
    policy = self.policy(value, reserved=value["write"])
    files = GuardedFiles(policy, mutation=lambda *_: None, max_read_bytes=16 * 1024 * 1024)
    path = value["path"]
    operation = "search" if value["tool_name"] == "grep" else "read"
    if "relative_path" in args:
      if value["tool_name"] != "grep": raise Conflict("ORDINARY_OPERATION_PATH")
      path = str(Path(path) / relative_path(args["relative_path"]))
    policy.authorize(value["tool_name"], operation, path)
    if value.get("read_path") != path:
      value["read_cache"] = files.read(value["tool_name"], path, operation=operation)
      value["read_path"] = path
    content = value["read_cache"]
    if args["offset"] > len(content): raise ConfigError("pi-operation-read-range")
    return {"data_b64": base64.b64encode(content[args["offset"]:args["offset"] + args["limit"]]).decode(),
      "total_bytes": len(content), "content_digest": hashlib.sha256(content).hexdigest()}

  def listing(self, principal, args):
    closed(args, ("operation_id",))
    if principal.role != "manager": raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    value = self.record(args["operation_id"])
    if value["tool_name"] not in ("ls", "find", "grep"): raise Conflict("ORDINARY_OPERATION_IDENTITY")
    policy = self.policy(value)
    operation = "list" if value["tool_name"] == "ls" else "search"
    target = policy.authorize(value["tool_name"], operation, value["path"])
    from .paths import _absolute_directory
    import fnmatch
    from functools import lru_cache
    pattern = value["input"].get("glob", "*") if value["tool_name"] == "grep" else value["input"].get("pattern", "*")
    if not isinstance(pattern, str) or not pattern or len(pattern) > 1024:
      raise ConfigError("pi-find-pattern")
    parts = pattern.split("/")
    def matches(path):
      names = path.split("/")
      @lru_cache(maxsize=4096)
      def test(left, right):
        if left == len(parts): return right == len(names)
        if parts[left] == "**": return test(left + 1, right) or right < len(names) and test(left, right + 1)
        return right < len(names) and fnmatch.fnmatchcase(names[right], parts[left]) and test(left + 1, right + 1)
      return fnmatch.fnmatchcase(names[-1], pattern) if len(parts) == 1 else test(0, 0)
    limit = 2000 if value["tool_name"] == "grep" else value["input"].get("limit", 500 if operation == "list" else 1000)
    if type(limit) is not int or not 1 <= limit <= 2000: raise ConfigError("pi-list-limit")
    results, seen, truncated = [], 0, False
    def visit(fd, prefix, inherited=()):
      nonlocal seen, truncated
      policy.current()
      rules = list(inherited)
      if operation == "search":
        try:
          info = os.stat(".gitignore", dir_fd=fd, follow_symlinks=False)
        except FileNotFoundError:
          info = None
        if info is not None:
          if not stat.S_ISREG(info.st_mode) or info.st_size > 65536: raise Conflict("SEARCH_IGNORE_UNSAFE")
          policy.authorize(value["tool_name"], "search", str(target["path"] / (prefix + ".gitignore")))
          file = os.open(".gitignore", os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
          try: contents = os.read(file, 65537).decode("utf8")
          finally: os.close(file)
          for raw in contents.splitlines():
            rule = raw.strip()
            if rule and not rule.startswith("#"): rules.append((prefix, rule))
      for name in sorted(os.listdir(fd)):
        if name == ".git": continue
        path = prefix + name
        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)): continue
        seen += 1
        if seen > 20000 or len(results) >= limit:
          truncated = True; return
        try: policy.authorize(value["tool_name"], operation, str(target["path"] / path))
        except Conflict as error:
          if str(error) == "PERMISSION_DENIED": continue
          raise
        directory = stat.S_ISDIR(info.st_mode)
        ignored = False
        if operation == "search":
          for base, rule in rules:
            if not path.startswith(base): continue
            negate = rule.startswith("!")
            rule = rule[1:] if negate else rule
            directories_only = rule.endswith("/")
            rule = rule.strip("/")
            relative = path[len(base):]
            candidate = relative if "/" in rule else name
            if rule and (not directories_only or directory) and fnmatch.fnmatchcase(candidate, rule): ignored = not negate
        if ignored: continue
        if operation == "list" or not directory and matches(path): results.append({"path": path, "directory": directory})
        if operation == "search" and directory:
          child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
          try:
            opened = os.fstat(child)
            if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino): raise Conflict("ROOT_IDENTITY")
            visit(child, path + "/", rules)
          finally: os.close(child)
    if target["path"].is_file():
      if value["tool_name"] != "grep": raise ConfigError("pi-list-directory-required")
      return {"entries": [{"path": None, "directory": False}], "truncated": False}
    with _absolute_directory(target["path"]) as fd: visit(fd, "")
    return {"entries": results, "truncated": truncated}

  def stage_write(self, principal, args):
    closed(args, ("operation_id", "content", "expected_digest"))
    if principal.role != "manager" or not isinstance(args["content"], str): raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    value = self.record(args["operation_id"])
    if not value["write"]: raise Conflict("ORDINARY_OPERATION_READONLY")
    self.policy(value, reserved=True).authorize(value["tool_name"], "write", value["path"])
    if value["tool_name"] == "write" and args["content"] != value["input"]["content"]: raise Conflict("ORDINARY_OPERATION_CONFLICT")
    if value["tool_name"] == "edit" and not isinstance(args["expected_digest"], str): raise Conflict("ORDINARY_EDIT_BASELINE_REQUIRED")
    if "content" in value and (value["content"], value["expected_digest"]) != (args["content"], args["expected_digest"]): raise Conflict("ORDINARY_OPERATION_CONFLICT")
    value["content"], value["expected_digest"] = args["content"], args["expected_digest"]
    return {"staged": True}

  def perform(self, principal, args):
    closed(args, ("operation_id",))
    value = self.record(args["operation_id"])
    if principal.role != "worker" or principal.lease_id != value["lease_id"] or value["tool_name"] != "rename" and "content" not in value: raise Conflict("ORDINARY_OPERATION_IDENTITY")
    def mutation(phase, detail):
      with Tree(self.host.root) as tree:
        path = "activity/ordinary-mutations/" + value["operation_id"] + ".json"
        if phase == "prepare": tree.write_immutable(path, json_bytes({"schema_version": 1, "state": "prepared", "lease_id": value["lease_id"], "mutation": detail}))
        else: tree.write_state(path, json_bytes({"schema_version": 1, "state": "settled", "lease_id": value["lease_id"], "mutation": detail}))
      return value["operation_id"]
    files = GuardedFiles(self.policy(value), mutation=mutation)
    result = files.rename("rename", value["path"], value["destination"]) if value["tool_name"] == "rename" else files.write(
      value["tool_name"], value["path"], value["content"].encode(), expected_digest=value["expected_digest"])
    with Tree(self.host.root) as tree:
      tree.write_immutable("activity/ordinary-results/" + value["operation_id"] + ".json", json_bytes({"schema_version": 1, "operation_id": value["operation_id"], "lease_id": value["lease_id"], "result": result}))
    return result

  def command(self, lease, payload):
    closed(payload, ("operation_id",))
    value = self.record(payload["operation_id"])
    if value["lease_id"] != lease["lease_id"] or not value["write"] or value["tool_name"] != "rename" and "content" not in value: raise Conflict("ORDINARY_OPERATION_IDENTITY")
    policy = self.policy(value, reserved=True)
    policy.authorize(value["tool_name"], "rename" if value["tool_name"] == "rename" else "write", value["path"])
    if value["tool_name"] == "rename": policy.authorize("rename", "rename", value["destination"])
    home = self.host.root / "activity/ordinary-homes" / lease["lease_id"]; ensure_private(home)
    env = environment(home=home)
    env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(self.host.server.endpoint), AGENTCFG_SUPERVISOR_CAPABILITY=self.host.service.issue_capability("worker", lease["lease_id"]))
    return SpawnCommand((sys.executable, "-B", "-I", str(self.host.repository / "scripts/pi-file-operation.py"), "--operation", value["operation_id"]), home, env)

  def handle(self, principal, method, args):
    if method == "ordinary_mcp_stdio_prepare":
      from .pi_mcp_stdio import prepare_stdio
      return prepare_stdio(self, principal, args)
    if method == "ordinary_web_media_prepare":
      from .pi_web_media import prepare_media
      return prepare_media(self, principal, args)
    if method == "ordinary_web_cli_prepare":
      from .pi_web_cli import prepare
      return prepare(self, principal, args)
    if method == "ordinary_web_cli_authorize":
      from .pi_web_cli import authorize
      return authorize(self, principal, args)
    if method == "ordinary_web_git_content":
      from .pi_web_git import content
      return content(self, principal, args)
    if method == "ordinary_web_file_prepare": return self.web_files.prepare(principal, args)
    if method == "ordinary_web_file_finish": return self.web_files.finish(principal, args)
    if method == "ordinary_web_browser_prepare": return self.web_browser.prepare(principal, args)
    if method == "ordinary_web_browser_finish": return self.web_browser.finish(principal, args)
    if method.startswith("ordinary_readseek_"): return self.readseek.handle(principal, method, args)
    if method == "ordinary_checkpoint_prepare": return self.checkpoints.prepare(principal, args)
    if method == "ordinary_checkpoint_perform": return self.checkpoints.perform(principal, args)
    if method == "ordinary_checkpoint_preview": return self.checkpoints.preview(principal, args)
    if method == "ordinary_checkpoint_list": return self.checkpoints.list(principal, args)
    if method == "ordinary_rules_read":
      from .pi_rules import read_rules
      return read_rules(self.host, principal, args)
    if method == "ordinary_service_prepare":
      from .pi_services import prepare_report
      return prepare_report(self.commands, principal, args)
    if method == "ordinary_mcp_script_prepare":
      from .pi_mcp_script import prepare_script
      return prepare_script(self.commands, principal, args)
    if method == "ordinary_git_status_prepare":
      from .pi_git_status import prepare_status
      return prepare_status(self.commands, principal, args)
    if method == "ordinary_git_review_prepare":
      from .pi_git_review import prepare_review
      return prepare_review(self.commands, principal, args)
    if method == "ordinary_editor_prepare":
      from .pi_editor import prepare_editor
      return prepare_editor(self.commands, principal, args)
    if method == "ordinary_command_prepare": return self.commands.prepare(principal, args)
    if method == "ordinary_command_finish": return self.commands.finish(principal, args)
    if method == "ordinary_command_stdin": return self.commands.write_stdin(principal, args)
    if method == "ordinary_command_resize": return self.commands.resize_terminal(principal, args)
    if method == "ordinary_command_output": return self.commands.output(principal, args)
    if method == "ordinary_prepare": return self.prepare(principal, args)
    if method == "ordinary_read": return self.read(principal, args)
    if method == "ordinary_stat": return self.metadata(principal, args)
    if method == "ordinary_list": return self.listing(principal, args)
    if method == "ordinary_stage_write": return self.stage_write(principal, args)
    if method == "ordinary_perform": return self.perform(principal, args)
    if method == "ordinary_finish":
      closed(args, ("operation_id",))
      if principal.role != "manager": raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
      value = self.record(args["operation_id"])
      if value["write"]:
        from .activity import protected
        if protected(self.host.store.read(value["lease_id"])): raise Conflict("TERMINATION_UNKNOWN")
      self.inputs.pop(args["operation_id"])
      return {"finished": True}
    raise ConfigError("pi-operation-method")
