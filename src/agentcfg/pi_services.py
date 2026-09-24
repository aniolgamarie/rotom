"""显式终端报告服务；只开放声明的脚本、Unix socket 与实例私人状态。"""
from datetime import datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import stat

from .activity import digest, protected
from .deployment import json_bytes
from .paths import configured_path, relative_path, _absolute_directory
from .pi_checks import compile_check
from .pi_guarded_files import root_identity
from .pi_supervisor import closed
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


ENVIRONMENT = {"TMUX", "ZELLIJ", "ZELLIJ_SESSION_NAME", "ZELLIJ_PANE_ID", "TERM_PROGRAM", "AGENT_ZELLIJ_RENAME_TAB"}


def file_snapshot(path):
  path = configured_path(str(path))
  with _absolute_directory(path.parent) as fd:
    info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid not in (0, os.geteuid())
        or info.st_mode & 0o022 or info.st_size > 16 * 1024 * 1024): raise Conflict("SERVICE_FILE_INVALID")
    source = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
    with os.fdopen(source, "rb") as stream:
      opened = os.fstat(stream.fileno())
      body = stream.read(16 * 1024 * 1024 + 1)
      after = os.fstat(stream.fileno())
    if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns): raise Conflict("SERVICE_FILE_CHANGED")
    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
      raise Conflict("SERVICE_FILE_CHANGED")
  return {"path": str(path), "device": info.st_dev, "inode": info.st_ino, "sha256": hashlib.sha256(body).hexdigest()}


def socket_snapshot(path):
  path = configured_path(str(path))
  with _absolute_directory(path.parent) as fd:
    info = os.stat(path.name, dir_fd=fd, follow_symlinks=False)
  if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid(): raise Conflict("SERVICE_SOCKET_INVALID")
  return {"path": str(path), "device": info.st_dev, "inode": info.st_ino}


def verify_inputs(value):
  if any(file_snapshot(row["path"]) != row for row in value["service_files"]): raise Conflict("SERVICE_FILE_CHANGED")
  if any(socket_snapshot(row["path"]) != row for row in value["service_sockets"]): raise Conflict("SERVICE_SOCKET_CHANGED")


def validate_report_binding(options):
  binding = options.get("agent_state")
  if not binding: raise ConfigError("pi-agent-state-binding-required")
  if binding["mode"] == "osc":
    if set(binding) != {"mode", "title"}: raise ConfigError("pi-agent-state-osc-fields")
    return binding
  required = {"mode", "executable", "version", "args", "files", "socket_paths", "environment", "timeout_seconds"}
  if not required <= binding.keys() or ("pane" in binding) == ("pane_env" in binding): raise ConfigError("pi-agent-state-service-fields")
  if set(binding["environment"]) - ENVIRONMENT: raise ConfigError("pi-agent-state-environment")
  for path in [binding["executable"], *binding["files"], *binding["socket_paths"]]: configured_path(path)
  return binding


def prepare_report(commands, principal, args):
  closed(args, ("operation_id", "state"))
  host = commands.host; manifest = host.manifest()
  if principal.role != "manager" or "gentle-agent-state" not in manifest.get("resource_ids", {}).get("extensions", {}):
    raise Conflict("SERVICE_CONTEXT_UNAVAILABLE")
  if args["state"] not in ("working", "blocked", "idle") or not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200:
    raise ConfigError("pi-agent-state-input")
  binding = validate_report_binding(manifest["options"])
  if binding["mode"] != "service": raise Conflict("SERVICE_NOT_SELECTED")
  pane = binding.get("pane") or os.environ.get(binding.get("pane_env", ""))
  if not pane or len(pane) > 128 or any(ord(char) < 32 for char in pane): raise ConfigError("pi-agent-state-pane-required")
  key = digest({"owner": host.store.owner, "operation_id": args["operation_id"]})
  request_digest = digest({"service": "agent-state", "args": args, "pane": pane})
  if key in commands.records:
    if commands.records[key]["request_digest"] != request_digest: raise Conflict("ORDINARY_OPERATION_CONFLICT")
    return commands.summary(commands.records[key])
  if len(commands.records) >= 128: raise Conflict("ORDINARY_OPERATION_CAPACITY")
  if any(value.get("service_files") is not None and protected(host.store.read(value["lease_id"])) for value in commands.records.values()):
    raise Conflict("SERVICE_BUSY")
  files = [file_snapshot(path) for path in binding["files"]]
  if sum(Path(row["path"]).stat().st_size for row in files) > 16 * 1024 * 1024: raise Conflict("SERVICE_FILE_LIMIT")
  sockets = [socket_snapshot(path) for path in binding["socket_paths"]]
  protected_paths = [configured_path(path).resolve(strict=True) for path in host.config.get("protected_roots", [])]
  projects = [configured_path(row["path"]).resolve(strict=True) for row in manifest["options"].get("paths", {}).get("roots", {}).values()]
  if any(Path(row["path"]).is_relative_to(root) for row in files + sockets for root in protected_paths + projects):
    raise Conflict("SERVICE_SCOPE_OVERLAP")
  home = Path(host.config["instance_root"]) / "pi-home/service-state/agent-report"; ensure_private(home)
  if any(home.is_relative_to(Path(root)) for root in ("/usr", "/bin", "/lib", "/lib64", "/System", "/dev")):
    raise Conflict("SERVICE_STATE_LOCATION")
  declarations = manifest["options"].get("paths", {}).get("roots", {})
  denied = [configured_path(declarations[name]["path"]).resolve(strict=True) for name in manifest["options"].get("permissions", {}).get("denied_roots", [])]
  for rule in manifest["permission_policy"]["rules"]:
    if rule["kind"] != "file" or rule["effect"] != "deny": continue
    if rule["root_ref"] not in declarations: raise Conflict("SERVICE_DENIAL_ROOT_UNBOUND")
    base = configured_path(declarations[rule["root_ref"]]["path"]).resolve(strict=True)
    denied.append(base if rule["relative_path"] == "." else base / relative_path(rule["relative_path"]))
  denied += [path for path in protected_paths if not home.is_relative_to(path)]
  if any(home.is_relative_to(path) or path.is_relative_to(home) for path in denied): raise Conflict("SERVICE_SCOPE_OVERLAP")
  executable = configured_path(binding["executable"])
  if any(Path(path).is_relative_to(denial) for path in [str(executable), *[row["path"] for row in files + sockets]] for denial in denied):
    raise Conflict("SERVICE_SCOPE_DENIED")
  check = compile_check({"executable": str(executable), "args": [*binding["args"], pane, args["state"]],
    "project_root": "service-state", "timeout_seconds": binding["timeout_seconds"], "foreground": True},
    candidate=home, executable=executable, read_roots=[executable, *[Path(row["path"]) for row in files + sockets]])
  check.update(write_roots=[str(home)], service_environment={**binding["environment"], "XDG_RUNTIME_DIR": str(home)},
    socket_paths=[row["path"] for row in sockets])
  check["binding_digest"] = digest({key: value for key, value in check.items() if key != "binding_digest"})
  lease = host.store.allocate(kind="external", execution_id="service-" + key, task_id=None, attempt_id=key,
    lock_identity=host.config["lock_identity"], slice_identity=host.config["slice_identity"], policy_digest=digest(manifest["permission_policy"]),
    candidate_digest=None, planned_workspaces=[])
  value = {"schema_version": 1, "operation_id": key, "request_digest": request_digest, "lease_id": lease["lease_id"], "command_ref": "agent-report",
    "tool_name": "agent-report", "manifest_digest": digest(manifest), "roots": {"service-state": {"path": str(home), "identity": root_identity(home)}},
    "check": check, "denied_paths": [str(path) for path in denied], "grant_generation": lease["grant_generation"], "stdin_enabled": False,
    "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=binding["timeout_seconds"] + 300)).isoformat(), "service_files": files, "service_sockets": sockets}
  grant = {"schema_version": 1, "grant_id": key, "operation_id": args["operation_id"], "instance_id": lease["instance_id"],
    "issuer_activation_id": lease["supervisor_activation_id"], "execution_mode": "ordinary", "allowed_tools": ["agent-report"],
    "root_bindings": value["roots"], "grant_generation": lease["grant_generation"],
    "issued_at": datetime.now(timezone.utc).isoformat(), "expires_at": value["expires_at"]}
  grant["grant_digest"] = digest(grant); value["grant"] = grant
  try:
    with Tree(host.root) as tree: tree.write_new("activity/ordinary-commands/" + key + ".json", json_bytes(value))
    commands.records[key] = value
    return commands.summary(value)
  except Exception:
    host.store.abort_allocation(lease["lease_id"], host.store.owner)
    raise
