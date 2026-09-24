"""普通命令只接受显式绑定；使用现有监督者、队列和工作区租约。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import os
import shlex
import sys

from .activity import digest, protected
from .deployment import json_bytes
from .paths import configured_path, relative_path
from .pi_checks import compile_check, verify_check
from .pi_guarded_files import root_identity
from .pi_supervisor import SpawnCommand, closed
from .process import environment, DependencyError
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


class OrdinaryCommands:
  def __init__(self, host):
    self.host = host
    self.records = {}

  def prepare(self, principal, args, *, inspection=None, arguments=None, terminal_size=None, service_name=None):
    closed(args, ("operation_id", "role_id", "cwd", "tool_name", "input"))
    if principal.role != "manager" or args["role_id"] != "main" or args["tool_name"] not in ("bash", "editor", "process"):
      raise Conflict("ORDINARY_COMMAND_ROLE")
    closed(args["input"], ("command",), ("timeout",))
    command = args["input"]["command"]
    if not isinstance(command, str) or not command or len(command) > 65536 or "\0" in command:
      raise ConfigError("pi-command-input")
    if not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200:
      raise ConfigError("pi-operation-id")
    manifest = self.host.manifest()
    if args["tool_name"] == "process" and "pi-processes" not in manifest.get("plugins", []):
      raise Conflict("ORDINARY_PROCESS_NOT_SELECTED")
    options = manifest["options"]
    selected = [(name, value) for name, value in options.get("external_tools", {}).items()
      if command == "agentcfg:" + name or command == shlex.join([value["executable"], *value.get("args", [])])]
    if len(selected) != 1: raise Conflict("ORDINARY_COMMAND_UNBOUND")
    name, binding = selected[0]
    if terminal_size is not None:
      from .pi_terminal import dimensions
      dimensions(*terminal_size)
      if args["tool_name"] != "editor" or not binding.get("interactive"):
        raise ConfigError("pi-editor-terminal-binding")
    if arguments is not None:
      binding = {**binding, "args": arguments}
    if inspection is not None:
      binding = {**binding, "args": inspection["argv"]}
    required = {"project_root", "read_roots", "write_roots", "timeout_seconds"}
    if not required <= binding.keys(): raise ConfigError("pi-command-scope-required")
    timeout = args["input"].get("timeout", binding["timeout_seconds"])
    if type(timeout) is not int or not 1 <= timeout <= binding["timeout_seconds"]:
      raise ConfigError("pi-command-timeout")
    cwd = configured_path(args["cwd"]).resolve(strict=True)
    declarations = options.get("paths", {}).get("roots", {})
    requested = set(binding["read_roots"]) | set(binding["write_roots"]) | {binding["project_root"]}
    if not requested <= declarations.keys(): raise ConfigError("pi-command-root-unbound")
    project = Path(declarations[binding["project_root"]]["path"]).resolve(strict=True)
    if declarations[binding["project_root"]]["purpose"] != "project" or not cwd.is_relative_to(project):
      raise Conflict("ORDINARY_COMMAND_CWD")
    if binding["project_root"] not in binding["read_roots"] or any(declarations[key]["purpose"] not in ("project", "write") for key in binding["write_roots"]):
      raise Conflict("ORDINARY_COMMAND_ROOT_CEILING")
    permission = options.get("permissions", {})
    roots = {key: {"path": str(Path(declarations[key]["path"]).resolve(strict=True)), "identity": root_identity(declarations[key]["path"])} for key in requested}
    if any(".git" in Path(row["path"]).parts for row in roots.values()): raise Conflict("PERMISSION_DENIED")
    denied = [Path(declarations[key]["path"]).resolve(strict=True) for key in permission.get("denied_roots", [])]
    readonly = [Path(declarations[key]["path"]).resolve(strict=True) for key in permission.get("readonly_roots", [])]
    if any(Path(roots[key]["path"]).is_relative_to(path) for key in requested for path in denied):
      raise Conflict("PERMISSION_DENIED")
    if any(Path(roots[key]["path"]).is_relative_to(path) or path.is_relative_to(Path(roots[key]["path"])) for key in binding["write_roots"] for path in readonly):
      raise Conflict("PERMISSION_DENIED")
    rules = [row for row in manifest["permission_policy"]["rules"] if row["kind"] == "command" and row["command_ref"] == "tool:" + name
      and args["tool_name"] in row["tool_ids"] and "execute" in row["operations"]]
    if any(row["effect"] == "deny" for row in rules) or not any(row["effect"] == "allow" for row in rules):
      raise Conflict("PERMISSION_DENIED")
    # 命令按固定argv授权；文件deny额外投影到命名空间，不能通过shell重新开放。
    denied += [Path(value).resolve(strict=True) for value in self.host.config.get("protected_roots", [])]
    if inspection is None: denied += [Path(row["path"]) / ".git" for row in roots.values() if (Path(row["path"]) / ".git").exists() or (Path(row["path"]) / ".git").is_symlink()]
    for rule in manifest["permission_policy"]["rules"]:
      if rule["kind"] != "file" or rule["effect"] != "deny": continue
      root = project if rule["root_ref"] == "project" else Path(declarations[rule["root_ref"]]["path"]).resolve(strict=True)
      denied.append(root if rule["relative_path"] == "." else root / relative_path(rule["relative_path"]))
    if any(Path(row["path"]).is_relative_to(path) for row in roots.values() for path in denied):
      raise Conflict("PERMISSION_DENIED")
    if terminal_size is not None and any(path.is_relative_to(Path("/dev")) or Path("/dev").is_relative_to(path) for path in denied):
      raise Conflict("TERMINAL_DENIAL_UNREPRESENTABLE")
    if inspection is not None:
      # 完整状态不能把被拒绝的子树隐藏后报告干净。
      visible = [project, *inspection["metadata"]]
      if any(path.is_relative_to(root) or root.is_relative_to(path) for path in denied for root in visible):
        raise Conflict("GIT_STATUS_SCOPE_INCOMPLETE")
      for index, path in enumerate(inspection["metadata"]):
        metadata_id = "git-metadata-" + str(index)
        while metadata_id in roots: metadata_id += "-git"
        roots[metadata_id] = {"path": str(path), "identity": root_identity(path)}
    executable = configured_path(binding["executable"])
    compiled = compile_check({"executable": str(executable), "args": binding.get("args", []), "project_root": binding["project_root"],
      "timeout_seconds": timeout, "foreground": True}, candidate=cwd, executable=executable,
      read_roots=[executable, *[Path(roots[key]["path"]) for key in binding["read_roots"]], *(inspection["metadata"] if inspection else [])])
    compiled["write_roots"] = [roots[key]["path"] for key in binding["write_roots"]]
    if inspection is not None: compiled["git_status"] = True
    if terminal_size is not None: compiled["terminal_size"] = list(terminal_size)
    compiled["binding_digest"] = digest({key: value for key, value in compiled.items() if key != "binding_digest"})
    request_digest = digest({"args": args, "inspection_argv": inspection["argv"] if inspection is not None else None,
      "markers": inspection.get("markers", []) if inspection else [], "arguments": arguments, "terminal_size": terminal_size, "service_name": service_name})
    key = digest({"owner": self.host.store.owner, "operation_id": args["operation_id"]})
    if key in self.records:
      if self.records[key]["request_digest"] != request_digest: raise Conflict("ORDINARY_OPERATION_CONFLICT")
      return self.summary(self.records[key])
    if len(self.records) >= 128: raise Conflict("ORDINARY_OPERATION_CAPACITY")
    planned = list(inspection.get("workspaces", [inspection["workspace"]])) if inspection is not None else []
    for root in compiled["write_roots"]:
      identity = self.host.store.workspaces.identify(root)
      if not any(row["workspace_key"] == identity["workspace_key"] for row in planned): planned.append(identity)
    lease = self.host.store.allocate(kind="external", execution_id="command-" + key, task_id=None, attempt_id=key,
      lock_identity=self.host.config["lock_identity"], slice_identity=self.host.config["slice_identity"], policy_digest=digest(manifest["permission_policy"]),
      candidate_digest=None, planned_workspaces=planned)
    value = {"schema_version": 1, "operation_id": key, "request_digest": request_digest, "lease_id": lease["lease_id"], "command_ref": name,
      "tool_name": args["tool_name"], "manifest_digest": digest(manifest), "roots": roots, "check": compiled,
      "denied_paths": sorted({str(path) for path in denied}), "grant_generation": lease["grant_generation"],
      "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=timeout + 300)).isoformat(), "stdin_enabled": binding.get("interactive", False)}
    if inspection is not None:
      value["workspace_identity"] = inspection["workspace"]
      value["git_markers"] = inspection.get("markers", [])
    grant = {"schema_version": 1, "grant_id": key, "operation_id": args["operation_id"], "instance_id": lease["instance_id"],
      "issuer_activation_id": lease["supervisor_activation_id"], "execution_mode": "ordinary", "allowed_tools": [args["tool_name"]],
      "root_bindings": roots, "grant_generation": lease["grant_generation"], "issued_at": datetime.now(timezone.utc).isoformat(), "expires_at": value["expires_at"]}
    grant["grant_digest"] = digest(grant)
    value["grant"] = grant
    try:
      if service_name is not None:
        self.host.service.register_service_lease(lease["lease_id"])
        value["service_name"] = service_name
      with Tree(self.host.root) as tree: tree.write_immutable("activity/ordinary-commands/" + key + ".json", json_bytes(value))
      self.records[key] = value
      return self.summary(value)
    except Exception:
      self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
      raise

  def summary(self, value):
    return {"operation_id": value["operation_id"], "lease_id": value["lease_id"], "write": bool(value["check"]["write_roots"]),
      "kind": "command", "tool_name": value["tool_name"], "timeout_seconds": value["check"]["timeout_seconds"], "command_ref": value["command_ref"],
      **({"destination": value["web_clone_destination"]} if "web_clone_destination" in value else {}),
      **({"terminal_size": value["check"]["terminal_size"]} if "terminal_size" in value["check"] else {}),
      **({"execution_class": "service", "service_name": value["service_name"]} if "service_name" in value else {})}

  def command(self, lease, payload):
    closed(payload, ("operation_id",))
    value = self.records.get(payload["operation_id"])
    if (not value or value["lease_id"] != lease["lease_id"] or value["grant_generation"] != lease["grant_generation"]
        or value["manifest_digest"] != digest(self.host.manifest()) or datetime.now(timezone.utc) >= datetime.fromisoformat(value["expires_at"])):
      raise Conflict("ORDINARY_COMMAND_STALE")
    for root in value["roots"].values():
      if root_identity(root["path"]) != root["identity"]: raise Conflict("ROOT_IDENTITY")
    if "workspace_identity" in value and self.host.store.workspaces.identify(value["workspace_identity"]["worktree_path"]) != value["workspace_identity"]:
      raise Conflict("ROOT_IDENTITY")
    for marker in value.get("git_markers", []):
      import hashlib
      with Tree(Path(marker["root"]), private=False) as tree: raw = tree.read(".git", max_bytes=4096)
      if not raw or hashlib.sha256(raw[0]).hexdigest() != marker["sha256"]: raise Conflict("ROOT_IDENTITY")
    for planned in lease["planned_workspaces"]:
      owned = self.host.store.workspaces.read(planned)
      if not owned or owned["execution_lease_id"] != lease["lease_id"] or owned["state"] not in ("reserved", "active"):
        raise Conflict("WORKSPACE_BUSY")
    if "service_files" in value:
      from .pi_services import verify_inputs
      verify_inputs(value)
    if "web_file_id" in value: self.host.operations.web_files.verify(value["web_file_id"])
    verify_check(value["check"])
    for job in value.get("readseek_driver", {}).get("jobs", []): verify_check(job["check"])
    for check in value.get("readseek_auxiliary_checks", []): verify_check(check)
    for check in value.get("web_cli_checks", []): verify_check(check)
    with Tree(self.host.runtime_root) as tree:
      raw = tree.read("runtime/commands.json")
      definitions = json.loads(raw[0])["programs"] if raw else {}
      kind = "readseek-driver" if "readseek_driver" in value else "ordinary-command"
      entrypoint = "supervisor/scripts/pi-readseek.py" if kind == "readseek-driver" else "supervisor/scripts/pi-project-check"
      definition = definitions.get(kind)
      if not definition or definition != {"entrypoint": entrypoint, "kind": "external", "engine": "python"}:
        raise DependencyError("普通命令监督入口缺失")
      if tree.read(definition["entrypoint"]) is None: raise DependencyError("普通命令监督入口缺失")
    home = self.host.root / "activity/ordinary-command-homes" / lease["lease_id"]; ensure_private(home)
    document = {"check": value["check"], "temporary": str(home), "lease_id": lease["lease_id"], "grant_generation": lease["grant_generation"], "denied_paths": value["denied_paths"]}
    if "readseek_driver" in value: document["readseek_driver"] = value["readseek_driver"]
    input_path = "activity/ordinary-command-inputs/" + lease["lease_id"] + ".json"
    with Tree(self.host.root) as tree: tree.write_immutable(input_path, json_bytes(document))
    env = environment(home=home)
    env.update(AGENTCFG_SUPERVISOR_ENDPOINT=str(self.host.server.endpoint), AGENTCFG_SUPERVISOR_CAPABILITY=self.host.service.issue_capability("worker", lease["lease_id"]))
    value["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=value["check"]["timeout_seconds"])).isoformat()
    return SpawnCommand((sys.executable, "-B", "-I", str(self.host.runtime_root / definition["entrypoint"]), "--input", str(self.host.root / input_path)),
      Path(value["check"]["cwd"]), env, capture_root=self.host.root / "activity/outputs" / lease["lease_id"], stdin_pipe=value["stdin_enabled"],
      terminal_size=tuple(value["check"]["terminal_size"]) if "terminal_size" in value["check"] else None)

  def resize_terminal(self, principal, args):
    closed(args, ("operation_id", "rows", "columns"))
    if principal.role != "manager": raise Conflict("ORDINARY_OPERATION_MANAGER_REQUIRED")
    value = self.records.get(args["operation_id"])
    if not value or "terminal_size" not in value["check"]: raise Conflict("TERMINAL_NOT_BOUND")
    lease = self.host.store.read(value["lease_id"])
    child = self.host.children.get(value["lease_id"])
    if (lease["state"] != "running" or lease["grant_generation"] != value["grant_generation"] or not child
        or not child.get("terminal") or child["process"].poll() is not None
        or digest(self.host.manifest()) != value["manifest_digest"] or datetime.now(timezone.utc) >= datetime.fromisoformat(value["expires_at"])
        or self.host.store.processes.observe(lease["process_identity"]) != "alive"):
      raise Conflict("ORDINARY_COMMAND_STALE")
    child["terminal"].resize(args["rows"], args["columns"])
    return {"resized": True}

  def write_stdin(self, principal, args):
    closed(args, ("operation_id", "data", "end"))
    if principal.role != "manager" or not isinstance(args["data"], str) or type(args["end"]) is not bool:
      raise ConfigError("pi-command-stdin")
    value = self.records.get(args["operation_id"])
    if not value or value["stdin_enabled"] is not True: raise Conflict("ORDINARY_STDIN_UNBOUND")
    lease = self.host.store.read(value["lease_id"])
    if (lease["state"] != "running" or lease["grant_generation"] != value["grant_generation"]
        or digest(self.host.manifest()) != value["manifest_digest"] or datetime.now(timezone.utc) >= datetime.fromisoformat(value["expires_at"])
        or self.host.store.processes.observe(lease["process_identity"]) != "alive"):
      raise Conflict("ORDINARY_COMMAND_STALE")
    for planned in lease["planned_workspaces"]:
      owned = self.host.store.workspaces.read(planned)
      if not owned or owned["state"] != "active" or owned["execution_lease_id"] != lease["lease_id"] or owned["grant_generation"] != lease["grant_generation"]:
        raise Conflict("WORKSPACE_BUSY")
    child = self.host.children.get(lease["lease_id"])
    stream = child["process"].stdin if child else None
    if stream is None or stream.closed: raise Conflict("ORDINARY_STDIN_CLOSED")
    raw = args["data"].encode()
    fd = stream.fileno()
    limit = 512 if child.get("terminal") is not None else min(4096, os.fpathconf(fd, "PC_PIPE_BUF"))
    if len(raw) > limit: raise ConfigError("pi-command-stdin-size")
    # 小于PIPE_BUF的非阻塞写入要么全部接受，要么返回背压；不持RPC锁等待程序读输入。
    os.set_blocking(fd, False)
    try:
      count = os.write(fd, raw) if raw else 0
    except BlockingIOError:
      raise Conflict("ORDINARY_STDIN_BACKPRESSURE") from None
    except (BrokenPipeError, OSError):
      raise Conflict("ORDINARY_STDIN_CLOSED") from None
    if count != len(raw): raise Conflict("ORDINARY_STDIN_UNKNOWN")
    if args["end"]: stream.close()
    return {"accepted_bytes": count, "stdin_closed": args["end"]}

  def output(self, principal, args):
    closed(args, ("operation_id", "cursor"))
    if principal.role != "manager" or type(args["cursor"]) is not int or args["cursor"] < 0:
      raise ConfigError("pi-command-output")
    value = self.records.get(args["operation_id"])
    if value is None: raise Conflict("ORDINARY_OPERATION_UNKNOWN")
    child = self.host.children.get(value["lease_id"])
    if not child or child.get("capture") is None:
      return {"events": [], "next_cursor": args["cursor"], "dropped": False, "has_more": False, "complete": False}
    if args["cursor"] > child["capture"].sequence: raise ConfigError("pi-command-output-cursor")
    return child["capture"].since(args["cursor"])

  def tick(self):
    now = datetime.now(timezone.utc)
    for key, value in list(self.records.items()):
      lease = self.host.store.read(value["lease_id"])
      if not protected(lease):
        if now >= datetime.fromisoformat(value["expires_at"]):
          if "web_cli_directory" in value:
            from .pi_web_cli import remove_directory
            remove_directory(self.host, value["web_cli_directory"])
          self.records.pop(key)
        continue
      if now < datetime.fromisoformat(value["expires_at"]): continue
      if lease["state"] == "allocating" and not lease["spawn_committed"]: self.host.store.abort_allocation(lease["lease_id"], self.host.store.owner)
      else: self.host.store.request_cancel(lease["lease_id"], self.host.store.owner)

  def finish(self, principal, args):
    closed(args, ("operation_id",))
    if principal.role != "manager": raise Conflict("ORDINARY_COMMAND_ROLE")
    value = self.records.get(args["operation_id"])
    if value is None: return {"finished": True}
    if protected(self.host.store.read(value["lease_id"])): raise Conflict("TERMINATION_UNKNOWN")
    if "web_cli_directory" in value:
      from .pi_web_cli import remove_directory
      remove_directory(self.host, value["web_cli_directory"])
    self.records.pop(args["operation_id"])
    return {"finished": True}
