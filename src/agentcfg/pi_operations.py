"""普通工具的显式操作授权；写入使用受监督的一次性 helper 和共享工作区租约。"""

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import os
import stat
import sys
from uuid import uuid4

from .activity import digest
from .deployment import json_bytes
from .paths import relative_path
from .pi_guarded_files import FilePolicy, GuardedFiles, root_identity
from .pi_operation_admission import encode_private_input
from .pi_policy_approval import aggregate_approval
from .pi_supervisor import OrdinaryCapabilityUnavailable, SpawnCommand, closed
from .process import environment
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


class OrdinaryOperations:
  def __init__(self, host, *, now=lambda: datetime.now(timezone.utc)):
    self.host = host
    self.inputs = {}
    self.admission = None
    self.admission_control = None
    self.reviewer_scope_control = None
    # 终态请求保留到本次控制面退役，不能淘汰后让同一个请求重新取得写权。
    self.deferred_bytes = 0
    self.max_deferred_bytes = 32 * 1024 * 1024
    self.max_deferred_operations = 4096
    self.now = now
    manifest = host.manifest()
    plugins = manifest.get("plugins")
    resources = manifest.get("resource_ids", {})
    if (not isinstance(plugins, list) or any(not isinstance(value, str) or not value for value in plugins)
        or len(set(plugins)) != len(plugins) or not isinstance(resources, dict)
        or not isinstance(resources.get("extensions", {}), dict)):
      raise ConfigError("pi-operation-capabilities")
    # 本次activation冻结选择；旧数据目录不构成启用或自动恢复的授权。
    self.selected_plugins = frozenset(plugins)
    self.selected_extensions = frozenset(resources.get("extensions", {}))
    from .pi_commands import OrdinaryCommands
    self.commands = OrdinaryCommands(host)
    self.checkpoints = self.readseek = self.web_browser = self.web_files = None
    if "git-checkpoint" in self.selected_extensions:
      from .pi_checkpoints import Checkpoints
      self.checkpoints = Checkpoints(host)
    if "pi-readseek" in self.selected_plugins:
      from .pi_readseek import ReadseekController
      self.readseek = ReadseekController(self)
    if "pi-web" in self.selected_plugins:
      from .pi_web_browser import BrowserSnapshots
      self.web_browser = BrowserSnapshots(host)
      from .pi_web_files import WebFiles
      self.web_files = WebFiles(self)

  def prepare(self, principal, args, *, deferred=False, admission=None):
    closed(args, ("operation_id", "role_id", "cwd", "tool_name", "input"))
    if principal.role != "manager":
      raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    if self.host.manifest().get("profile_id") in ("pi-base", "pi-full"):
      if not deferred or self.admission is None or admission is not self.admission:
        raise Conflict("OPERATION_ADMISSION_REQUIRED")
    self.tick()
    if not isinstance(args["operation_id"], str) or not args["operation_id"] or "\0" in args["operation_id"] or len(args["operation_id"]) > 200:
      raise ConfigError("pi-operation-id")
    key = digest({"owner": self.host.store.owner, "operation_id": args["operation_id"]})
    existing = self.inputs.get(key)
    request = self.private_request(args) if deferred else None
    if existing:
      if deferred != ("state" in existing): raise Conflict("ORDINARY_OPERATION_CONFLICT")
      if deferred:
        self.manager(principal, existing)
        if existing["private_request"] != request: raise Conflict("ORDINARY_OPERATION_CONFLICT")
      elif existing["request_digest"] != digest(args): raise Conflict("ORDINARY_OPERATION_CONFLICT")
      return self.summary(existing)
    if sum(value.get("state") not in ("finished", "expired", "revoked") for value in self.inputs.values()) >= 128:
      raise Conflict("ORDINARY_OPERATION_CAPACITY")
    if deferred and (sum("state" in value for value in self.inputs.values()) >= self.max_deferred_operations
        or self.deferred_bytes + len(request) > self.max_deferred_bytes):
      raise Conflict("ORDINARY_OPERATION_CAPACITY")
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
        return self.prepare_resource(principal, args, payload, path, resource, manifest, deferred=deferred, request=request, admission=admission)
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
      candidate_digest=None, planned_workspaces=planned) if write and not deferred else self.host.store.read(principal.lease_id)
    grant = {"schema_version": 1, "grant_id": key, "operation_id": args["operation_id"], "instance_id": lease["instance_id"],
      "issuer_activation_id": lease["supervisor_activation_id"], "execution_mode": "ordinary", "allowed_tools": ceiling["allowed_tools"],
      "root_bindings": roots, "grant_generation": lease["grant_generation"], "issued_at": self.now().isoformat(),
      "expires_at": (self.now() + timedelta(seconds=300)).isoformat()}
    grant["grant_digest"] = digest(grant)
    record = {"schema_version": 1, "operation_id": key, "request_digest": digest({"operation_id": key, "input_ref": uuid4().hex}) if deferred else digest(args), "lease_id": None if deferred else lease["lease_id"],
      "tool_name": name, "path": str(path), "grant": grant, "ceiling": ceiling, "policy_digest": digest(manifest["permission_policy"]), "write": write}
    if name == "rename": record["destination"] = str(destination)
    if deferred:
      if admission is not None: record["_admission_owner"] = admission
      self.bind_prepared(record, principal, args, request, payload, planned, manifest)
      self.preview(record)
      self.inputs[key] = record
      self.deferred_bytes += len(request)
      return self.summary(record)
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
    return {"operation_id": value["operation_id"], "lease_id": value["lease_id"], "write": value["write"], "path": value["path"], "request_digest": value["request_digest"],
      **({"state": value["state"]} if "state" in value else {})}

  def prepare_resource(self, principal, args, payload, path, resource, manifest, *, deferred=False, request=None, admission=None):
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
    if deferred:
      record.update(lease_id=None, request_digest=digest({"operation_id": key, "input_ref": uuid4().hex}))
      if admission is not None: record["_admission_owner"] = admission
      self.bind_prepared(record, principal, args, request, payload, [], manifest)
      self.preview(record)
      self.inputs[key] = record
      self.deferred_bytes += len(request)
      return self.summary(record)
    with Tree(self.host.root) as tree: tree.write_immutable("activity/ordinary-operations/" + key + ".json", json_bytes(record))
    record["input"] = deepcopy(payload); self.inputs[key] = record
    return self.summary(record)

  def private_request(self, args):
    return encode_private_input(args, limit=min(self.max_deferred_bytes, 1024 * 1024))

  def access_snapshot(self, manifest):
    # 仅冻结本文件入口读取的权限配置；这不是完整的 ConfigIdentity。
    return digest({"policy": manifest["permission_policy"], "roles": manifest["role_bindings"],
      "paths": manifest["options"].get("paths", {}), "permissions": manifest["options"].get("permissions", {}),
      "protected_roots": self.host.config.get("protected_roots", [])})

  def bind_prepared(self, value, principal, args, request, payload, planned, manifest):
    value.update(state="prepared", parent_lease_id=principal.lease_id, parent_generation=principal.grant_generation,
      private_request=request, input=deepcopy(payload), planned_workspaces=deepcopy(planned),
      access_snapshot=self.access_snapshot(manifest), cwd=str(Path(args["cwd"]).resolve(strict=True)), cwd_identity=root_identity(args["cwd"]))

  def manager(self, principal, value):
    if (principal.role != "manager" or principal.lease_id != value["parent_lease_id"]
        or principal.grant_generation != value["parent_generation"]):
      raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")

  def current_context(self, value):
    manifest = self.host.manifest()
    if self.access_snapshot(manifest) != value["access_snapshot"]: raise Conflict("PERMISSION_STALE")
    if root_identity(value["cwd"]) != value["cwd_identity"]: raise Conflict("ROOT_IDENTITY")
    lease = self.host.store.read(value["parent_lease_id"])
    if lease["state"] != "running" or lease["grant_generation"] != value["parent_generation"]:
      raise Conflict("GRANT_STALE")
    if self.now() >= datetime.fromisoformat(value["grant"]["expires_at"]): raise Conflict("GRANT_STALE")
    return manifest

  def preview(self, value):
    """复核准备快照并返回可信等级；不暴露GuardedFiles策略或执行能力。"""
    manifest = self.current_context(value)
    if "resource" in value:
      from .pi_resource_reads import selected_resource
      if selected_resource(self.host, manifest, Path(value["path"])) != value["resource"]:
        raise Conflict("RESOURCE_ADMISSION_STALE")
      for binding in value["grant"]["root_bindings"].values():
        if root_identity(binding["path"]) != binding["identity"]: raise Conflict("ROOT_IDENTITY")
      return "human"
    # Writer 只在 consume 的 allocate 中申请。此处只允许同步 authorize 调用。
    policy = self.file_policy(value, manifest, lambda *_: True, lambda *_: True)
    name = value["tool_name"]
    modes = []
    if name == "edit": modes.append(policy.authorize(name, "read", value["path"])["approval"])
    operation = "rename" if name == "rename" else "write" if value["write"] else "list" if name == "ls" else "search" if name in ("find", "grep") else "read"
    for target in [value["path"]] + ([value["destination"]] if name == "rename" else []):
      authorized = policy.authorize(name, operation, target)
      modes.append(authorized["approval"])
      if name == "write":
        # 消费后文件/父目录可能消失；潜在create限制不能仅按当前exists降级。
        # 无create许可只收紧等级，原overwrite仍可由human确认；实际创建继续硬拒绝。
        potential = [authorized["path"]]
        cursor = authorized["path"].parent
        while cursor != authorized["root"] and cursor.is_relative_to(authorized["root"]):
          potential.append(cursor)
          cursor = cursor.parent
        for candidate in potential:
          try: modes.append(policy.authorize(name, "create", str(candidate))["approval"])
          except Conflict as error:
            if str(error) != "PERMISSION_DENIED": raise
            modes.append("human")
    for planned in value["planned_workspaces"]:
      if self.host.store.workspaces.identify(planned["worktree_path"]) != planned: raise Conflict("ROOT_IDENTITY")
    return aggregate_approval(modes)

  def deferred_record(self, principal, args):
    closed(args, ("operation_id",))
    if not isinstance(args["operation_id"], str): raise ConfigError("pi-operation-id")
    value = self.inputs.get(args["operation_id"])
    if value is None or "state" not in value: raise Conflict("ORDINARY_OPERATION_UNKNOWN")
    self.manager(principal, value)
    return value

  def consume(self, principal, args, *, admission=None, approval_source=None):
    value = self.deferred_record(principal, args)
    if self.host.manifest().get("profile_id") in ("pi-base", "pi-full") or "_admission_owner" in value:
      if admission is None or admission is not self.admission or value.get("_admission_owner") is not admission:
        raise Conflict("OPERATION_ADMISSION_REQUIRED")
      if type(approval_source) is not str or approval_source not in ("human", "reviewer", "deterministic-policy"):
        raise Conflict("OPERATION_ADMISSION_REQUIRED")
    if value["state"] != "prepared": raise Conflict("ORDINARY_OPERATION_ALREADY_CONSUMED")
    # SupervisorService.mutex 串行包住消费与 tick；失败也不重新开放同一操作。
    value["state"] = "revoked"
    approval = self.preview(value)
    if admission is not None and aggregate_approval([approval_source, approval]) != approval_source:
      raise Conflict("OPERATION_APPROVAL_REQUIRED")
    if admission is not None: value["approval_source"] = approval_source
    value["state"] = "unknown"
    if value["write"]:
      allocation = {"kind": "external", "execution_id": "operation-" + value["operation_id"], "task_id": None,
        "attempt_id": value["operation_id"], "lock_identity": self.host.config["lock_identity"], "slice_identity": self.host.config["slice_identity"],
        "policy_digest": value["policy_digest"], "candidate_digest": None, "parent_execution_id": None,
        "planned_workspaces": sorted(deepcopy(value["planned_workspaces"]), key=lambda row: row["workspace_key"])}
      # UUID 在 store 内生成；保留原分配描述，使丢失返回值后仍能只读定位。
      value["allocation_request"] = deepcopy({**allocation, **self.host.store.owner})
      lease = self.host.store.allocate(**allocation)
    else:
      lease = self.host.store.read(principal.lease_id)
    value["lease_id"] = lease["lease_id"]
    if value["write"] and (lease["state"] != "allocating" or lease["spawn_committed"]):
      raise Conflict("ORDINARY_OPERATION_ALLOCATION_STATE")
    grant = value["grant"]
    grant.update(instance_id=lease["instance_id"], issuer_activation_id=lease["supervisor_activation_id"], grant_generation=lease["grant_generation"])
    grant["grant_digest"] = digest({key: item for key, item in grant.items() if key != "grant_digest"})
    # 显式白名单排除正文、输入引用的私有比较副本与内存生命周期字段。
    persisted = {key: value[key] for key in ("schema_version", "operation_id", "request_digest", "lease_id", "tool_name", "path", "grant", "policy_digest", "write")}
    for key in ("ceiling", "destination", "resource", "approval_source"):
      if key in value: persisted[key] = value[key]
    with Tree(self.host.root) as tree:
      tree.write_immutable("activity/ordinary-operations/" + value["operation_id"] + ".json", json_bytes(persisted))
    value["state"] = "consumed"
    return self.summary(value)

  def status(self, principal, args):
    value = self.deferred_record(principal, args)
    result = self.summary(value)
    if value["state"] == "unknown" and value["write"] and value["lease_id"] is None:
      expected = value.get("allocation_request")
      if expected is None: raise Conflict("ORDINARY_ALLOCATION_IDENTITY")
      matches = [row for row in self.host.store.records() if row["execution_id"] == expected["execution_id"]]
      if len(matches) > 1 or matches and any(matches[0][key] != item for key, item in expected.items()):
        raise Conflict("ORDINARY_ALLOCATION_IDENTITY")
      if matches: result["lease_id"] = matches[0]["lease_id"]
      # 只返回定位信息；不改变 unknown、不发重试、不撤销或回收租约。
    return result

  def record(self, operation_id, *, principal=None):
    value = self.inputs.get(operation_id)
    if value is None: raise Conflict("ORDINARY_OPERATION_UNKNOWN")
    if "state" in value and value["state"] != "consumed": raise Conflict("ORDINARY_OPERATION_NOT_CONSUMED")
    if "state" in value:
      if principal is not None: self.manager(principal, value)
      self.current_context(value)
    if self.now() >= datetime.fromisoformat(value["grant"]["expires_at"]): raise Conflict("GRANT_STALE")
    return value

  def tick(self):
    if self.readseek is not None: self.readseek.tick()
    if self.web_browser is not None: self.web_browser.tick()
    if self.web_files is not None: self.web_files.tick()
    self.commands.tick()
    if self.checkpoints is not None: self.checkpoints.tick()
    if self.admission_control is not None and self.admission_control.shell_bridge is not None:
      self.admission_control.shell_bridge.tick()
    from .activity import protected
    for key, value in list(self.inputs.items()):
      if value.get("state") in ("finished", "expired", "revoked", "unknown"): continue
      if self.now() < datetime.fromisoformat(value["grant"]["expires_at"]): continue
      if value.get("state") == "prepared":
        self.retire(value, "expired")
        continue
      if value["write"]:
        lease = self.host.store.read(value["lease_id"])
        if lease["state"] == "allocating" and not lease["spawn_committed"]:
          self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
        elif protected(lease):
          self.host.store.request_cancel(lease["lease_id"], self.host.store.owner)
          continue
      if "state" in value:
        self.retire(value, "expired")
      else: self.inputs.pop(key)

  def policy(self, value, *, reserved=False):
    if "state" in value and value["state"] != "consumed": raise Conflict("ORDINARY_OPERATION_NOT_CONSUMED")
    manifest = self.current_context(value) if "state" in value else self.host.manifest()
    if digest(manifest["permission_policy"]) != value["policy_digest"]: raise Conflict("PERMISSION_STALE")
    lease = self.host.store.read(value["lease_id"])
    def verify(grant, _metadata):
      if "state" in value and self.access_snapshot(self.host.manifest()) != value["access_snapshot"]:
        raise Conflict("PERMISSION_STALE")
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
    return self.file_policy(value, manifest, verify, writer)

  def file_policy(self, value, manifest, verify, writer):
    options = manifest["options"].get("permissions", {})
    approval = value.get("approval_source")
    if value.get("state") == "consumed" and manifest.get("profile_id") in ("pi-base", "pi-full") and approval is None:
      raise Conflict("OPERATION_ADMISSION_REQUIRED")
    return FilePolicy(policy=manifest["permission_policy"], roots=value["grant"]["root_bindings"], ceiling=value["ceiling"], grant=value["grant"], mode="ordinary",
      verify=verify, workspace=writer, readonly_roots=options.get("readonly_roots", []), denied_roots=options.get("denied_roots", []),
      secret_roots=self.host.config.get("protected_roots", []), approval_ceiling=approval)

  def retire(self, value, state):
    value["state"] = state
    for key in ("input", "content", "read_cache", "read_path", "expected_digest"):
      value.pop(key, None)

  def metadata(self, principal, args):
    closed(args, ("operation_id",))
    if principal.role != "manager": raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    value = self.record(args["operation_id"], principal=principal)
    if value["tool_name"] != "read" or "resource" in value:
      raise Conflict("ORDINARY_METADATA_NOT_BOUND")
    return GuardedFiles(self.policy(value), mutation=lambda *_: None).metadata("read", value["path"])

  def read(self, principal, args):
    closed(args, ("operation_id", "offset", "limit"), ("relative_path",))
    if principal.role != "manager": raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    value = self.record(args["operation_id"], principal=principal)
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
      for binding in value["grant"]["root_bindings"].values():
        if root_identity(binding["path"]) != binding["identity"]: raise Conflict("ROOT_IDENTITY")
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
    value = self.record(args["operation_id"], principal=principal)
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
    value = self.record(args["operation_id"], principal=principal)
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
    if method.startswith("ordinary_reviewer_scope_"):
      if method not in {"ordinary_reviewer_scope_" + name for name in ("open", "allocate_intent", "allocate_request", "verify", "retire_intent", "retire_session")}:
        raise ConfigError("PI_RISK_REVIEW_SCOPE_CONTROL_INVALID")
      if self.reviewer_scope_control is None: raise Conflict("REVIEW_SCOPE_CONTROL_UNAVAILABLE")
      return self.reviewer_scope_control.handle(principal, method, args)
    if method.startswith("ordinary_admission_"):
      if self.admission_control is None: raise Conflict("OPERATION_CONTROL_UNAVAILABLE")
      return self.admission_control.handle(principal, method, args)
    if method == "ordinary_shell_take_input":
      closed(args, ("operation_id",))
      if self.admission_control is None or self.admission_control.shell_bridge is None:
        raise Conflict("SHELL_BACKEND_UNAVAILABLE")
      return self.admission_control.shell_bridge.take_input(principal, args["operation_id"])
    if method == "ordinary_shell_output":
      if self.admission_control is None or self.admission_control.shell_bridge is None:
        raise Conflict("SHELL_BACKEND_UNAVAILABLE")
      return self.admission_control.shell_bridge.output(principal, args)
    plugin = ("pi-readseek" if method.startswith("ordinary_readseek_") else
      "pi-web" if method.startswith("ordinary_web_") else
      "pi-mcp" if method in ("ordinary_mcp_stdio_prepare", "ordinary_mcp_script_prepare") else
      "pi-slopchop" if method in ("ordinary_editor_prepare", "ordinary_git_review_prepare") else None)
    extension = ("git-checkpoint" if method.startswith("ordinary_checkpoint_") else
      "dirty-repo-guard" if method == "ordinary_git_status_prepare" else
      "gentle-agent-state" if method == "ordinary_service_prepare" else None)
    native_stdio = method == "ordinary_mcp_stdio_prepare" and self.host.manifest().get("profile_id") in ("pi-base", "pi-full")
    native_stdio = native_stdio and "native_mcp" in self.host.manifest()
    if (plugin is not None and plugin not in self.selected_plugins and not native_stdio
        or extension is not None and extension not in self.selected_extensions):
      raise OrdinaryCapabilityUnavailable()
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
    if method == "ordinary_prepare_deferred": return self.prepare(principal, args, deferred=True)
    if method == "ordinary_consume": return self.consume(principal, args)
    if method == "ordinary_status": return self.status(principal, args)
    if method == "ordinary_read": return self.read(principal, args)
    if method == "ordinary_stat": return self.metadata(principal, args)
    if method == "ordinary_list": return self.listing(principal, args)
    if method == "ordinary_stage_write": return self.stage_write(principal, args)
    if method == "ordinary_perform": return self.perform(principal, args)
    if method == "ordinary_finish":
      closed(args, ("operation_id",))
      if principal.role != "manager": raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
      deferred = self.inputs.get(args["operation_id"])
      if deferred is not None and "state" in deferred:
        self.manager(principal, deferred)
        if deferred["state"] == "unknown": raise Conflict("TERMINATION_UNKNOWN")
        if deferred["state"] in ("prepared", "expired", "revoked", "finished"):
          self.retire(deferred, "finished")
          return {"finished": True}
        from .activity import protected
        if deferred["write"] and protected(self.host.store.read(deferred["lease_id"])): raise Conflict("TERMINATION_UNKNOWN")
        self.retire(deferred, "finished")
        return {"finished": True}
      value = self.record(args["operation_id"])
      if value["write"]:
        from .activity import protected
        if protected(self.host.store.read(value["lease_id"])): raise Conflict("TERMINATION_UNKNOWN")
      self.inputs.pop(args["operation_id"])
      return {"finished": True}
    raise ConfigError("pi-operation-method")
