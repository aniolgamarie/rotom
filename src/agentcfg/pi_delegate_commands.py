"""受控委托命令编译；仅接受已配置的命令引用，不接收 shell、argv 或环境。"""

from datetime import datetime, timezone
from pathlib import Path

from .activity import digest
from .paths import configured_path, relative_path
from .pi_checks import check_environment, compile_check
from .pi_guarded_files import root_identity
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree


def command_binding(controller, principal, args):
  closed(args, ("run_id", "lease_id", "grant_generation", "operation_id", "command_ref"))
  data = controller.input(args["run_id"])
  request, grant = data["request"], data["grant"]
  host = controller.host
  lease = host.store.read(request["lease_id"])
  if (principal.role != "worker" or principal.lease_id != request["lease_id"] or args["lease_id"] != request["lease_id"]
      or args["grant_generation"] != request["grant_generation"] or lease["state"] != "running"
      or lease["grant_generation"] != request["grant_generation"] or datetime.now(timezone.utc) >= datetime.fromisoformat(grant["expires_at"])):
    raise Conflict("DELEGATE_GRANT_REVOKED")
  if request["backend"] != "codex" or "bash" not in grant["allowed_tools"]:
    raise Conflict("DELEGATE_COMMAND_UNAVAILABLE")
  if not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200:
    raise ConfigError("delegate-operation-id")
  manifest = host.manifest()
  if digest(manifest["permission_policy"]) != request["policy_digest"]:
    raise Conflict("DELEGATE_POLICY_CHANGED")
  reference = args["command_ref"]
  if not isinstance(reference, str) or not reference.startswith("tool:"): raise Conflict("DELEGATE_COMMAND_UNBOUND")
  name = reference[5:]
  bindings = manifest["options"].get("external_tools", {})
  if not isinstance(name, str) or name not in bindings: raise Conflict("DELEGATE_COMMAND_UNBOUND")
  binding = bindings[name]
  if not {"project_root", "read_roots", "write_roots", "timeout_seconds"} <= binding.keys():
    raise ConfigError("pi-command-scope-required")
  if binding.get("interactive", False): raise Conflict("DELEGATE_COMMAND_INTERACTIVE")
  rules = [row for row in manifest["permission_policy"]["rules"] if row["kind"] == "command" and row["command_ref"] == reference
    and "bash" in row["tool_ids"] and "execute" in row["operations"]]
  if any(row["effect"] == "deny" for row in rules) or not any(row["effect"] == "allow" for row in rules):
    raise Conflict("PERMISSION_DENIED")
  declarations = manifest["options"].get("paths", {}).get("roots", {})
  project_id = binding["project_root"]
  selected = set(binding["read_roots"]) | set(binding["write_roots"]) | {project_id}
  if not selected <= declarations.keys() or declarations[project_id]["purpose"] != "project":
    raise Conflict("DELEGATE_COMMAND_ROOT_UNBOUND")
  if project_id not in binding["read_roots"] or set(binding["write_roots"]) - {project_id}:
    raise Conflict("DELEGATE_COMMAND_ROOT_CEILING")
  writing = bool(binding["write_roots"])
  if writing and (request["execution_mode"] != "delegate-write" or request["mode"] != "implement"):
    raise Conflict("DELEGATE_COMMAND_READONLY")
  cwd = configured_path(request["cwd"]).resolve(strict=True)
  source = configured_path(declarations[project_id]["path"]).resolve(strict=True)
  candidate_identity = host.store.workspaces.identify(cwd)
  source_identity = host.store.workspaces.identify(source)
  def common(identity):
    git = Path(identity["git_dir_path"])
    with Tree(git, private=False) as tree: raw = tree.read("commondir")
    return (git / raw[0].decode().strip()).resolve(strict=True) if raw else git
  relative = source.relative_to(source_identity["worktree_path"])
  if common(candidate_identity) != common(source_identity) or not cwd.is_relative_to(Path(candidate_identity["worktree_path"]) / relative):
    raise Conflict("DELEGATE_COMMAND_PROJECT_MISMATCH")
  if root_identity(cwd) != grant["root_bindings"]["project"]["identity"]:
    raise Conflict("ROOT_IDENTITY")
  if writing:
    owner = host.store.workspaces.read(candidate_identity)
    if not owner or owner["state"] != "active" or owner["execution_lease_id"] != request["lease_id"] or owner["grant_generation"] != request["grant_generation"]:
      raise Conflict("WORKSPACE_BUSY")
  permission = manifest["options"].get("permissions", {})
  if selected & set(permission.get("denied_roots", [])) or writing and project_id in permission.get("readonly_roots", []):
    raise Conflict("PERMISSION_DENIED")
  private = [Path(path).resolve(strict=True) for path in host.config.get("protected_roots", [])]
  denied = [*private, cwd / ".git"]
  roots = {key: cwd if key == project_id else configured_path(declarations[key]["path"]).resolve(strict=True) for key in selected}
  for key, path in roots.items():
    if path == Path("/") or path == Path.home() or ".git" in path.parts:
      raise Conflict("DELEGATE_COMMAND_ROOT_CEILING")
    if key != project_id and (source.is_relative_to(path) or path.is_relative_to(source) or cwd.is_relative_to(path) or path.is_relative_to(cwd)):
      raise Conflict("DELEGATE_COMMAND_ORIGINAL_ROOT")
    if any(path.is_relative_to(secret) or secret.is_relative_to(path) for secret in private):
      raise Conflict("DELEGATE_COMMAND_PRIVATE_ROOT")
  for rule in manifest["permission_policy"]["rules"]:
    if rule["kind"] != "file" or rule["effect"] != "deny": continue
    root_id = rule["root_ref"]
    root = cwd if root_id in ("project", project_id) else configured_path(declarations[root_id]["path"]).resolve(strict=True)
    denied.append(root if rule["relative_path"] == "." else root / relative_path(rule["relative_path"]))
  denied.extend(configured_path(declarations[key]["path"]).resolve(strict=True) for key in permission.get("denied_roots", []))
  if any(cwd.is_relative_to(path) for path in denied): raise Conflict("PERMISSION_DENIED")
  executable = configured_path(binding["executable"])
  if executable.is_relative_to(source) or executable.is_relative_to(cwd) or any(executable.is_relative_to(path) for path in private):
    raise Conflict("DELEGATE_COMMAND_EXECUTABLE_SCOPE")
  remaining = int((datetime.fromisoformat(grant["expires_at"]) - datetime.now(timezone.utc)).total_seconds())
  if remaining < 1: raise Conflict("DELEGATE_GRANT_REVOKED")
  compiled = compile_check({"executable": str(executable), "args": binding.get("args", []), "project_root": project_id,
    "timeout_seconds": min(binding["timeout_seconds"], remaining), "foreground": True}, candidate=cwd, executable=executable,
    read_roots=[executable, *[roots[key] for key in binding["read_roots"]]])
  compiled["write_roots"] = [str(cwd)] if writing else []
  compiled["binding_digest"] = digest({key: value for key, value in compiled.items() if key != "binding_digest"})
  return {"check": compiled, "denied_paths": sorted({str(path) for path in denied}), "command_ref": reference,
    "parent_request_digest": request["request_digest"], "parent_lease_id": request["lease_id"], "parent_generation": request["grant_generation"]}


class DelegateCommands:
  """命令是当前委托的顺序子操作；不新建 AgentManager 或第二个模型任务。"""
  def __init__(self, controller):
    self.controller, self.host = controller, controller.host
    self.records = {}

  def available(self, principal, args):
    closed(args, ("run_id", "lease_id", "grant_generation"))
    # 查询仍走同一准入器，不能凭配置存在向模型宣称可执行。
    result = []
    for name in self.host.manifest()["options"].get("external_tools", {}):
      try:
        value = command_binding(self.controller, principal, {**args, "operation_id": "list", "command_ref": "tool:" + name})
      except Conflict:
        continue
      result.append({"command_ref": value["command_ref"], "write": bool(value["check"]["write_roots"]), "timeout_seconds": value["check"]["timeout_seconds"]})
    return {"commands": result}

  def start(self, principal, args):
    import sys
    from .activity import protected
    from .deployment import json_bytes
    from .pi_delegate_files import record_mutation
    from .pi_supervisor import SpawnCommand
    from .process import DependencyError
    from .storage import ensure_private
    compiled = command_binding(self.controller, principal, args)
    request = self.controller.input(args["run_id"])["request"]
    key = digest([request["request_digest"], args["operation_id"]])
    if key in self.records:
      # 启动确认丢失不能按同一操作自动重发，即便请求内容一致。
      raise Conflict("DELEGATE_COMMAND_ALREADY_DISPATCHED")
    if any(row["run_id"] == args["run_id"] and protected(self.host.store.read(row["lease_id"])) for row in self.records.values()):
      raise Conflict("DELEGATE_COMMAND_BUSY")
    if len(self.records) >= 1000: raise Conflict("DELEGATE_COMMAND_CAPACITY")
    active = [row for row in self.host.store.records() if protected(row) and row["kind"] != "host" and row["spawn_committed"]]
    if len(active) >= self.host.service.active_children:
      raise Conflict("DELEGATE_CAPACITY_BUSY")
    entry = self.host.runtime_root / "supervisor/scripts/pi-project-check"
    with Tree(self.host.runtime_root) as tree:
      if tree.read("supervisor/scripts/pi-project-check") is None: raise DependencyError("受控命令入口未进入运行包")
    parent = self.host.store.read(request["lease_id"])
    lease = self.host.store.allocate(kind="check", execution_id="delegate-command-" + key, task_id=parent["task_id"], attempt_id=key,
      lock_identity=parent["lock_identity"], slice_identity=parent["slice_identity"], policy_digest=parent["policy_digest"],
      candidate_digest=parent["candidate_digest"], planned_workspaces=[], parent_execution_id=parent["execution_id"])
    home = self.host.root / "activity/delegate-command-homes" / lease["lease_id"]
    mutation = {"operation": "command", "command_ref": compiled["command_ref"], "binding_digest": compiled["check"]["binding_digest"]}
    record = {**compiled, "run_id": args["run_id"], "operation_id": args["operation_id"], "lease_id": lease["lease_id"], "mutation": mutation,
      "expires_at": datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + compiled["check"]["timeout_seconds"], timezone.utc).isoformat(), "ticket": None}
    try:
      self.host.store.record_external(parent["lease_id"], self.host.store.owner, ["execution-lease:" + lease["lease_id"]])
      ensure_private(home)
      value = {"check": compiled["check"], "temporary": str(home), "lease_id": lease["lease_id"],
        "grant_generation": lease["grant_generation"], "denied_paths": compiled["denied_paths"]}
      input_path = "activity/delegate-command-inputs/" + lease["lease_id"] + ".json"
      # 先持久化父子绑定，再开放启动闸门；父租约不能先于子进程回收。
      with Tree(self.host.root) as tree:
        tree.write_immutable(input_path, json_bytes(value))
        tree.write_immutable("activity/delegate-commands/" + key + ".json", json_bytes(record))
      if compiled["check"]["write_roots"]:
        record["ticket"] = record_mutation(self.controller, request, args["operation_id"], "prepare", mutation)
      self.records[key] = record
      env = check_environment(compiled["check"], home)
      env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(self.host.server.endpoint),
        AGENTCFG_SUPERVISOR_CAPABILITY=self.host.service.issue_capability("worker", lease["lease_id"]))
      command = SpawnCommand((sys.executable, "-B", "-I", str(entry), "--input", str(self.host.root / input_path)),
        Path(compiled["check"]["cwd"]), env, capture_root=self.host.root / "activity/outputs" / lease["lease_id"])
      started = self.host.store.start(lease["lease_id"], self.host.store.owner, spawn=lambda current: self.host.spawn(command, current))
      self.host.activate(started)
    except Exception:
      current = self.host.store.read(lease["lease_id"])
      if current["state"] == "allocating" and not current["spawn_committed"]:
        self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
      # 若启动已提交或变更意图已写入，保留未知/未settled，不能自动重试。
      raise
    return {"operation_id": key, "state": "running"}

  def status(self, principal, args):
    from .activity import protected
    from .pi_delegate_files import record_mutation
    import hashlib
    import json
    closed(args, ("run_id", "lease_id", "grant_generation", "operation_id"))
    record = self.records.get(args["operation_id"])
    if not record or record["run_id"] != args["run_id"]: raise Conflict("DELEGATE_COMMAND_UNKNOWN")
    if (principal.role != "worker" or principal.lease_id != record["parent_lease_id"] or args["lease_id"] != record["parent_lease_id"]
        or args["grant_generation"] != record["parent_generation"]):
      raise Conflict("DELEGATE_COMMAND_IDENTITY")
    parent = self.host.store.read(record["parent_lease_id"])
    if parent["state"] != "running" or parent["grant_generation"] != record["parent_generation"]:
      raise Conflict("DELEGATE_GRANT_REVOKED")
    self.host.manifest()
    lease = self.host.store.read(record["lease_id"])
    if protected(lease): return {"operation_id": args["operation_id"], "state": "running"}
    if record.get("result") is not None: return record["result"]
    proof = self.host.store.reconcile(lease["lease_id"])
    if not proof.get("termination_evidence", {}).get("verified"): raise Conflict("DELEGATE_COMMAND_TERMINATION_UNKNOWN")
    with Tree(self.host.root) as tree:
      raw = tree.read("activity/exits/" + lease["lease_id"] + ".json")
      exit_record = json.loads(raw[0]) if raw else None
    if not exit_record or exit_record.get("process_identity") != lease["process_identity"] or exit_record.get("lease_id") != lease["lease_id"]:
      raise Conflict("DELEGATE_COMMAND_EXIT_UNKNOWN")
    output = {}
    with Tree(self.host.root / "activity/outputs" / lease["lease_id"]) as tree:
      raw = tree.read("capture.json")
      capture = json.loads(raw[0]) if raw else None
      if not capture or capture.get("complete") is not True: raise Conflict("DELEGATE_COMMAND_OUTPUT_UNKNOWN")
      for stream in ("stdout", "stderr"):
        row = capture["streams"][stream]
        raw = tree.read(stream, max_bytes=1024 * 1024)
        if raw is None or hashlib.sha256(raw[0]).hexdigest() != row["sha256"] or row.get("failed"):
          raise Conflict("DELEGATE_COMMAND_OUTPUT_UNKNOWN")
        output[stream] = raw[0][:16384].decode("utf8", errors="replace")
        output[stream + "_truncated"] = row["truncated"] or len(raw[0]) > 16384
    if record["ticket"]:
      request = self.controller.input(record["run_id"])["request"]
      record_mutation(self.controller, request, record["operation_id"], "settle", {**record["mutation"], "ticket": record["ticket"]})
    record["result"] = {"operation_id": args["operation_id"], "state": "completed", "exit_code": exit_record["exit_code"], **output}
    return record["result"]

  def tick(self):
    from .activity import protected
    for record in self.records.values():
      parent = self.host.store.read(record["parent_lease_id"])
      child = self.host.store.read(record["lease_id"])
      if not protected(child): continue
      valid = (parent["state"] == "running" and parent["grant_generation"] == record["parent_generation"]
        and self.host.store.processes.observe(parent["process_identity"]) == "alive"
        and datetime.now(timezone.utc) < datetime.fromisoformat(record["expires_at"]))
      try: self.host.manifest()
      except (ConfigError, Conflict): valid = False
      if valid: continue
      if child["state"] == "allocating" and not child["spawn_committed"]:
        self.host.store.abort_allocation(child["lease_id"], self.host.store.owner)
      elif child["state"] == "running": self.host.store.request_cancel(child["lease_id"], self.host.store.owner)
