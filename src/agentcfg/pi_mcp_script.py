"""MCP 脚本只在私人无网络进程运行；业务访问留给已选服务的父侧 RPC。"""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from .activity import digest
from .deployment import json_bytes
from .paths import configured_path, relative_path
from .pi_checks import compile_check
from .pi_guarded_files import root_identity
from .pi_services import file_snapshot
from .pi_supervisor import closed
from .process import DependencyError
from .schema import ConfigError
from .storage import Conflict, Tree, ensure_private


def script_binding(options):
  settings = options.get("mcp", {}).get("scripting", {})
  if settings.get("enabled") is not True: raise ConfigError("pi-mcp-scripting-not-selected")
  name = settings.get("tool_ref")
  binding = options.get("external_tools", {}).get(name)
  if not binding or binding.get("args", []) or binding.get("interactive", False):
    raise ConfigError("pi-mcp-script-interpreter-binding")
  return settings, name, binding


def prepare_script(commands, principal, args):
  closed(args, ("operation_id", "timeout_seconds"))
  host = commands.host; manifest = host.manifest(); options = manifest["options"]
  if principal.role != "manager" or "pi-mcp" not in manifest.get("plugins", []):
    raise Conflict("MCP_SCRIPT_CONTEXT_UNAVAILABLE")
  settings, name, binding = script_binding(options)
  timeout = args["timeout_seconds"]
  if type(timeout) is not int or not 1 <= timeout <= settings.get("max_seconds", 30):
    raise ConfigError("pi-mcp-script-timeout")
  if not isinstance(args["operation_id"], str) or not 1 <= len(args["operation_id"]) <= 200:
    raise ConfigError("pi-operation-id")
  rules = [row for row in manifest["permission_policy"]["rules"] if row["kind"] == "command"
    and row["command_ref"] == "tool:" + name and "bash" in row["tool_ids"] and "execute" in row["operations"]]
  if not any(row["effect"] == "allow" for row in rules) or any(row["effect"] == "deny" for row in rules):
    raise Conflict("PERMISSION_DENIED")
  key = digest({"owner": host.store.owner, "operation_id": args["operation_id"]})
  request_digest = digest({"service": "mcp-script", "args": args})
  if key in commands.records:
    if commands.records[key]["request_digest"] != request_digest: raise Conflict("ORDINARY_OPERATION_CONFLICT")
    return commands.summary(commands.records[key])
  if len(commands.records) >= 128: raise Conflict("ORDINARY_OPERATION_CAPACITY")
  with Tree(host.runtime_root) as tree:
    registry = tree.read("runtime/commands.json"); profile = tree.read("runtime/profile.json")
    definition = json.loads(registry[0])["programs"].get("mcp-script") if registry else None
    toolchains = json.loads(profile[0]).get("toolchains", {}) if profile else {}
  if not definition or definition.get("kind") != "external" or definition.get("engine") != "node":
    raise DependencyError("MCP脚本监督入口未安装")
  closed(definition, ("entrypoint", "kind", "engine"))
  if definition["entrypoint"] != "runtime/mcp-script-process.mjs":
    raise DependencyError("MCP脚本监督入口身份不匹配")
  if binding.get("version") != toolchains.get("node") or not toolchains.get("node"):
    raise DependencyError("MCP脚本解释器需要锁定Node版本的明确绑定")
  entry = host.runtime_root / relative_path(definition["entrypoint"])
  executable = configured_path(binding["executable"])
  files = [file_snapshot(entry), file_snapshot(executable)]
  declarations = options.get("paths", {}).get("roots", {})
  business = [configured_path(row["path"]).resolve(strict=True) for row in declarations.values() if row["purpose"] == "project"]
  if any(Path(row["path"]).is_relative_to(root) for row in files for root in business):
    raise Conflict("MCP_SCRIPT_INTERPRETER_SCOPE")
  home = host.root / "activity/mcp-script-homes" / key
  ensure_private(home)
  denied = [configured_path(declarations[name]["path"]).resolve(strict=True) for name in options.get("permissions", {}).get("denied_roots", [])]
  for rule in manifest["permission_policy"]["rules"]:
    if rule["kind"] != "file" or rule["effect"] != "deny": continue
    if rule["root_ref"] not in declarations: raise Conflict("MCP_SCRIPT_DENIAL_UNBOUND")
    base = configured_path(declarations[rule["root_ref"]]["path"]).resolve(strict=True)
    denied.append(base if rule["relative_path"] == "." else base / relative_path(rule["relative_path"]))
  if any(home.is_relative_to(path) or path.is_relative_to(home) or any(Path(row["path"]).is_relative_to(path) for row in files) for path in denied):
    raise Conflict("PERMISSION_DENIED")
  denied += [configured_path(path).resolve(strict=True) for path in host.config.get("protected_roots", [])
    if not home.is_relative_to(configured_path(path))]
  check = compile_check({"executable": str(executable), "args": ["--no-addons", "--max-old-space-size=128", str(entry)],
    "project_root": "mcp-script", "timeout_seconds": timeout, "foreground": True},
    candidate=home, executable=executable, read_roots=[entry, executable])
  check["write_roots"] = [str(home)]
  check["binding_digest"] = digest({key: value for key, value in check.items() if key != "binding_digest"})
  lease = host.store.allocate(kind="external", execution_id="mcp-script-" + key, task_id=None, attempt_id=key,
    lock_identity=host.config["lock_identity"], slice_identity=host.config["slice_identity"], policy_digest=digest(manifest["permission_policy"]),
    candidate_digest=None, planned_workspaces=[])
  value = {"schema_version": 1, "operation_id": key, "request_digest": request_digest, "lease_id": lease["lease_id"], "command_ref": name,
    "tool_name": "mcp-script", "manifest_digest": digest(manifest), "roots": {"mcp-script": {"path": str(home), "identity": root_identity(home)}},
    "check": check, "denied_paths": [str(path) for path in denied], "grant_generation": lease["grant_generation"], "stdin_enabled": True,
    "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=timeout + 300)).isoformat(), "service_files": files, "service_sockets": []}
  grant = {"schema_version": 1, "grant_id": key, "operation_id": args["operation_id"], "instance_id": lease["instance_id"],
    "issuer_activation_id": lease["supervisor_activation_id"], "execution_mode": "ordinary", "allowed_tools": ["bash"],
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
